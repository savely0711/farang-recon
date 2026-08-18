"""
Парсер разведки рынка (Направление 3).

Что делает за один запуск:
  - заходит техническим аккаунтом (сессия из .env, без ввода кода);
  - по каждому каналу из channels.py читает НОВЫЕ посты
    (первый заход — за последнюю неделю, дальше — что появилось со вчера);
  - каждый пост разбирает ИИ: объявление ли это, категория, цена, частник или
    бизнес (тип продавца);
  - у объявления берёт НИК автора поста (без прочих данных — правило 3);
  - ПРОПУСКАЕТ повторы одного объявления (тот же автор + тот же текст) — в
    таблицу не пишет копии и даже не тратит на них ИИ (см. dedup.py);
  - объявления пишет в Google-таблицу ПАЧКАМИ;
  - запоминает, докуда дочитал (state.json), чтобы не дублировать.

Мини-CRM «Присутствие» (17.08.2026) — что поменялось:
  - СТРОКА = ОБЪЯВЛЕНИЕ, а не человек. Раньше действовало правило «один ник =
    одна строка навсегда», и все следующие объявления продавца выбрасывались —
    из-за этого таблица росла на одну строку в день. Теперь у продавца столько
    строк, сколько у него объявлений; статусы всё равно остаются «на человека»
    (их проставляет скрипт таблицы сразу всем строкам ника).
  - Посты БЕЗ НИКА больше не выбрасываются: их записываем как рыночные данные
    (цены, спрос). В очередь «первого касания» они не идут — писать некому.

Надёжность (правка 29.06): если запись пачки в таблицу не удалась даже после
повторов — НЕ роняем весь прогон. Прерываем только текущий канал (его дочитаем
в следующий раз с того места, что реально записали) и идём к следующим каналам.

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

import dedup
import outreach_queue
import state
from channels import CHANNELS
from classify import classify, is_ad_candidate

load_dotenv()

# --- настройки аккуратности ---
FIRST_RUN_DAYS = 7          # первый заход: посты за последнюю неделю
DELAY_BETWEEN_POSTS = 1.5   # сек между постами (медленно, по-человечески)
DELAY_BETWEEN_CHANNELS = 8  # сек между каналами
# Размер пачки записи в таблицу: до 50 строк за один запрос. Это ПОТОЛОК, а не
# минимум — остаток (хоть 1 строка) всегда досылается в конце канала. Поэтому
# даже если за день нашлось мало объявлений, они все попадут в таблицу.
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "50"))
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


async def _author_username(msg) -> str | None:
    """Ник автора поста (без @) или None, если открытого ника нет.
    Больше НИКАКИХ данных о пользователе не берём (правило Направления 3)."""
    try:
        sender = await msg.get_sender()
        return getattr(sender, "username", None) or None
    except Exception:  # noqa: BLE001
        return None


async def process_channel(client, sheet, ch: dict, joins_left: list, persist: bool):
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

    max_read_id = last_id     # докуда прочитали (любые посты)
    written_id = last_id      # докуда реально ЗАПИСАЛИ в таблицу (для надёжного докуда)
    added = 0
    seen = 0
    skipped = 0
    duped = 0                 # сколько копий объявлений отсеяли (не тратя ИИ и таблицу)
    write_failed = False
    buffer = []               # копим объявления: список (msg_id, «сырое» объявление)
    pending = set()           # ключи дублей этого прогона (ещё не записанных на диск)

    def flush() -> bool:
        """Отправляет накопленную пачку. При успехе двигает written_id, помечает
        объявления как записанные (dedup) и чистит буфер."""
        nonlocal written_id, added
        if not buffer:
            return True
        ok = sheet.flush([item for _, item in buffer])
        if ok:
            written_id = max(written_id, max(mid for mid, _ in buffer))
            added += len(buffer)
            if persist:
                # Запоминаем ТОЛЬКО реально записанные объявления, чтобы та же
                # публикация завтра не завела вторую строку. Ключ — автор (или
                # канал, если ника нет) + текст поста; см. dedup.py.
                for _, item in buffer:
                    dedup.remember(item.get("author"), item["snippet"],
                                   item.get("channel"))
                dedup.save()
                # Пункт 14: новые объявления с ником автора — в очередь
                # «первого касания» (её разбирает outreach.py). Объявления без
                # ника enqueue() отбросит сам — писать некому.
                for _, item in buffer:
                    outreach_queue.enqueue(
                        item.get("author"), item["link"], item.get("date"))
            buffer.clear()
        return ok

    try:
        async for msg in client.iter_messages(entity, **kwargs):
            max_read_id = max(max_read_id, msg.id)
            text = msg.message  # только текст; личные данные не трогаем
            if not text:
                continue
            # Умный предфильтр: короткую болтовню пропускаем мгновенно (без ИИ, без паузы)
            if not is_ad_candidate(text):
                skipped += 1
                continue
            # Ник автора нужен для рассылки и для ключа дубля. Его может не
            # быть — такие объявления мы теперь ВСЁ РАВНО записываем (рыночные
            # данные), просто в рассылку они не идут.
            author = await _author_username(msg)
            # Повтор ТОГО ЖЕ объявления? Отсеиваем ДО ИИ — не тратим ни ИИ, ни
            # строку в таблице. Ключ: автор (или канал, если ника нет) + текст.
            key = dedup.make_key(author, text, ch["title"])
            if key in pending or dedup.is_dup(author, text, ch["title"]):
                duped += 1
                continue
            seen += 1
            if MAX_POSTS_PER_CHANNEL and seen > MAX_POSTS_PER_CHANNEL:
                print(f"  ⏹ достигнут лимит {MAX_POSTS_PER_CHANNEL} постов на канал — стоп")
                break
            result = classify(text)
            if result["is_listing"]:
                pending.add(key)  # чтобы повтор в этом же прогоне не прошёл дважды
                buffer.append((msg.id, {
                    "date": msg.date,
                    "category": result["category"],
                    "link": f"https://t.me/{username}/{msg.id}",
                    "author": author,
                    "channel": ch["title"],
                    "snippet": text,
                    "seller_type": result.get("seller_type", ""),
                }))
                # Дошли до потолка пачки — отправляем сразу.
                if len(buffer) >= BATCH_SIZE and not flush():
                    write_failed = True
                    break
            await asyncio.sleep(DELAY_BETWEEN_POSTS)
    except FloodWaitError as e:
        print(f"  ⏳ Telegram просит подождать {e.seconds}с — пауза")
        await asyncio.sleep(e.seconds + 5)

    # Досылаем остаток (даже если там 1–2 строки), если не было сбоя записи.
    if not write_failed and not flush():
        write_failed = True

    # Докуда дочитал: при сбое записи — только до реально записанного (остальное
    # перечитаем в следующий раз); при норме — до последнего прочитанного поста.
    final_id = written_id if write_failed else max(max_read_id, written_id)
    if final_id > last_id:
        state.set_last_id(username, final_id)

    tail = " (запись прервалась — докуда успели; остальное в след. раз)" if write_failed else ""
    print(f"  ✅ объявлений записано: {added}; проверено ИИ: {seen}; "
          f"копий отсеяно: {duped}; пропущено болтовни: {skipped}; "
          f"докуда дочитал: {final_id}{tail}")


class DryRunSink:
    """Тестовый режим: печатает найденные объявления вместо записи в таблицу.
    Включается, если DRY_RUN=1 или не настроен Google (нет SHEET_WEBHOOK_URL)."""

    def __init__(self):
        print("🧪 ТЕСТОВЫЙ РЕЖИМ (DRY_RUN): в Google-таблицу НЕ пишу, только показываю.")

    def flush(self, listings):
        from categories import ALL_CATEGORIES
        for l in listings:
            cat = ALL_CATEGORIES.get(l["category"], l["category"])
            author = l.get("author")
            author_str = f"@{author}" if author else "без ника"
            chan = l.get("channel") or "—"
            seller = l.get("seller_type") or "?"
            snip = (l["snippet"] or "").replace("\n", " ").strip()[:70]
            print(f"    [CRM] {l['date']:%Y-%m-%d} | {chan} | {cat} | {seller} | "
                  f"автор {author_str} | {l['link']}\n        «{snip}»")
        return True


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
    # Дубли запоминаем на диск только при реальной записи в таблицу
    # (в тестовом прогоне файл dedup.json не трогаем, чтобы не «засорять» память).
    persist = not isinstance(sheet, DryRunSink)
    dedup.load()
    joins_left = [MAX_NEW_JOINS_PER_RUN]

    async with TelegramClient(session, api_id, api_hash) as client:
        me = await client.get_me()
        assert isinstance(me, User), "сессия не залогинена как аккаунт"
        print(f"🔑 вошёл как {me.first_name} (id {me.id})")

        for i, ch in enumerate(CHANNELS):
            # Защитная сеть: непредвиденный сбой на одном канале не должен
            # ронять весь прогон — сообщаем и идём к следующему.
            try:
                await process_channel(client, sheet, ch, joins_left, persist)
            except Exception as e:  # noqa: BLE001
                print(f"  ⚠ канал @{ch['username']} прервался: {e} — иду дальше")
            if i < len(CHANNELS) - 1:
                await asyncio.sleep(DELAY_BETWEEN_CHANNELS)

    print("\n🏁 Прогон завершён.")


if __name__ == "__main__":
    asyncio.run(main())
