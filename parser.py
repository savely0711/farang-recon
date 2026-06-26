"""
Парсер разведки рынка (Направление 3).

Что делает за один запуск:
  - заходит техническим аккаунтом (сессия из .env, без ввода кода);
  - по каждому каналу из channels.py читает НОВЫЕ посты
    (первый заход — за последнюю неделю, дальше — что появилось со вчера);
  - каждый пост разбирает ИИ: объявление ли это, категория, цена;
  - объявления пишет в Google-таблицу (своя вкладка на канал);
  - запоминает, докуда дочитал (state.json), чтобы не дублировать.

Работаем АККУРАТНО (правило Направления 3): медленное чтение с паузами,
никому не пишем, не более одного нового вступления в группу за запуск.
Запуск:  python3 parser.py
"""
import asyncio
import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.types import User

import state
from channels import CHANNELS
from classify import classify, is_ad_candidate

load_dotenv()

# --- настройки аккуратности ---
FIRST_RUN_DAYS = 7          # первый заход: посты за последнюю неделю
DELAY_BETWEEN_POSTS = 1.5   # сек между постами (медленно, по-человечески)
DELAY_BETWEEN_CHANNELS = 8  # сек между каналами
# Авто-вступление в группы ВЫКЛЮЧЕНО (0): в группы вступает сам Савелий руками
# из приложения (проходит капчу как человек, выглядит естественно). Парсер только
# читает те группы, где аккаунт уже состоит; в остальные не лезет. Можно временно
# включить через переменную MAX_JOINS, но по умолчанию — 0 (безопасно).
MAX_NEW_JOINS_PER_RUN = int(os.environ.get("MAX_JOINS", "0"))
# Ограничение постов на канал за запуск (0 = без лимита). Для первого теста
# удобно поставить, например, MAX_POSTS=20 — чтобы быстро проверить и не жечь ИИ.
MAX_POSTS_PER_CHANNEL = int(os.environ.get("MAX_POSTS", "0"))


async def ensure_member(client, entity) -> bool:
    """Проверяет, состоим ли в группе; при необходимости — вступает (осторожно)."""
    try:
        # если можем прочитать хоть один пост — значит уже участники / канал публичный
        async for _ in client.iter_messages(entity, limit=1):
            return True
        return True
    except Exception:  # noqa: BLE001
        return False


async def process_channel(client, sheet, ch: dict, joins_left: list):
    username = ch["username"]
    print(f"\n📂 Канал @{username} ({ch['title']})")

    try:
        entity = await client.get_entity(username)
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠ не удалось открыть @{username}: {e}")
        return

    if not await ensure_member(client, entity):
        if joins_left[0] <= 0:
            print("  ⏭ аккаунт не состоит в группе — пропускаю (вступи руками из приложения)")
            return
        try:
            await client(JoinChannelRequest(entity))
            joins_left[0] -= 1
            print("  ➕ вступил в группу (аккуратно)")
            await asyncio.sleep(5)
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠ не смог вступить: {e}")
            return

    last_id = state.get_last_id(username)
    if last_id > 0:
        kwargs = {"min_id": last_id, "reverse": True}
        print(f"  читаю новые посты после id {last_id}")
    else:
        since = datetime.now(timezone.utc) - timedelta(days=FIRST_RUN_DAYS)
        kwargs = {"offset_date": since, "reverse": True}
        print(f"  первый заход: посты за последние {FIRST_RUN_DAYS} дней")

    max_id = last_id
    added = 0
    seen = 0
    skipped = 0
    try:
        async for msg in client.iter_messages(entity, **kwargs):
            max_id = max(max_id, msg.id)
            text = msg.message  # только текст; личные данные не трогаем
            if not text:
                continue
            # Умный предфильтр: короткую болтовню пропускаем мгновенно (без ИИ, без паузы)
            if not is_ad_candidate(text):
                skipped += 1
                continue
            seen += 1
            if MAX_POSTS_PER_CHANNEL and seen > MAX_POSTS_PER_CHANNEL:
                print(f"  ⏹ достигнут лимит {MAX_POSTS_PER_CHANNEL} постов на канал — стоп")
                break
            result = classify(text)
            if result["is_listing"]:
                link = f"https://t.me/{username}/{msg.id}"
                sheet.append_listing(
                    ch["tab"],
                    date=msg.date,
                    category=result["category"],
                    price=result["price_thb"],
                    link=link,
                    snippet=text,
                )
                added += 1
            await asyncio.sleep(DELAY_BETWEEN_POSTS)
    except FloodWaitError as e:
        print(f"  ⏳ Telegram просит подождать {e.seconds}с — пауза")
        await asyncio.sleep(e.seconds + 5)

    if max_id > last_id:
        state.set_last_id(username, max_id)
    print(f"  ✅ объявлений добавлено: {added}; проверено ИИ: {seen}; "
          f"пропущено болтовни: {skipped}; докуда дочитал: {max_id}")


class DryRunSink:
    """Тестовый режим: печатает найденные объявления вместо записи в таблицу.
    Включается, если DRY_RUN=1 или не настроен Google (нет файла-ключа)."""

    def __init__(self):
        print("🧪 ТЕСТОВЫЙ РЕЖИМ (DRY_RUN): в Google-таблицу НЕ пишу, только показываю.")

    def append_listing(self, tab, *, date, category, price, link, snippet):
        from categories import ALL_CATEGORIES
        cat = ALL_CATEGORIES.get(category, category)
        price_str = "—" if price is None else ("даром" if price == 0 else f"{price}฿")
        snip = (snippet or "").replace("\n", " ").strip()[:70]
        print(f"    [{tab}] {date:%Y-%m-%d} | {cat} | {price_str} | {link}\n        «{snip}»")


def _make_sink():
    # В таблицу пишем, только если задан адрес скрипта-приёмника (SHEET_WEBHOOK_URL).
    # Нет адреса или явно DRY_RUN=1 → тестовый режим (только показываем на экране).
    dry = os.environ.get("DRY_RUN") == "1" or not os.environ.get("SHEET_WEBHOOK_URL")
    if dry:
        return DryRunSink()
    from sheets import Sheet
    return Sheet()


async def main():
    api_id = int(os.environ["TG_API_ID"])
    api_hash = os.environ["TG_API_HASH"]
    session = StringSession(os.environ["TG_SESSION"])

    sheet = _make_sink()
    joins_left = [MAX_NEW_JOINS_PER_RUN]

    async with TelegramClient(session, api_id, api_hash) as client:
        me = await client.get_me()
        assert isinstance(me, User), "сессия не залогинена как аккаунт"
        print(f"🔑 вошёл как {me.first_name} (id {me.id})")

        for i, ch in enumerate(CHANNELS):
            await process_channel(client, sheet, ch, joins_left)
            if i < len(CHANNELS) - 1:
                await asyncio.sleep(DELAY_BETWEEN_CHANNELS)

    print("\n🏁 Прогон завершён.")


if __name__ == "__main__":
    asyncio.run(main())
