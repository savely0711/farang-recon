"""
Парсер НЕДВИЖИМОСТИ — отдельный контур разведки (25.08.2026).

Что делает за один запуск:
  - заходит тем же техническим аккаунтом (TG_SESSION из .env);
  - по каждой группе из realty_channels.py читает НОВЫЕ посты
    (первый заход — за последнюю неделю, дальше — только новые);
  - каждый пост разбирает ПРАВИЛАМИ, без ИИ (realty_extract.py): сделка, тип
    жилья, цена, период, спальни, площадь, район;
  - пропускает повторы (тот же автор + тот же текст) — realty_dedup.json;
  - пишет пачками в ОТДЕЛЬНУЮ таблицу «Фаранг — Недвижимость».

Чего НЕ делает специально (решение Савелия 25.08.2026):
  - никому не пишет: очередь «первого касания» здесь не подключена вовсе;
  - ничего не публикует на сайт: авто-подготовка этот контур не видит;
  - не тратит ИИ.

Разделение со старой разведкой — на уровне файлов, а не договорённостей:
свой список групп, своя память прочитанного (realty_state.json), свой список
повторов (realty_dedup.json), своя таблица. Поэтому один и тот же пост может
попасть и в старую таблицу, и в новую — это нормально, таблицы разные.

Запуск:
  python3 realty_parser.py                 # обычный прогон
  DRY_RUN=1 python3 realty_parser.py       # вхолостую, показать на экране
  REALTY_MAX_POSTS=50 python3 realty_parser.py   # ограничить постов на группу
"""
import asyncio
import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession
from telethon.tl.types import User

import dedup
import state
from realty_channels import CHANNELS
from realty_extract import extract, is_realty_candidate

load_dotenv()

# ── СВОИ файлы памяти. Ставим ДО первого обращения к модулям: иначе контур
# недвижимости начнёт двигать метки старой разведки и та потеряет свои посты.
_HERE = os.path.dirname(os.path.abspath(__file__))
state.STATE_FILE = os.path.join(_HERE, "realty_state.json")
dedup.DEDUP_FILE = os.path.join(_HERE, "realty_dedup.json")

# --- настройки аккуратности (те же, что у старой разведки) ---
FIRST_RUN_DAYS = int(os.environ.get("REALTY_FIRST_RUN_DAYS", "7"))
DELAY_BETWEEN_POSTS = 1.0
DELAY_BETWEEN_CHANNELS = 8
BATCH_SIZE = int(os.environ.get("REALTY_BATCH_SIZE", "50"))
MAX_POSTS_PER_CHANNEL = int(os.environ.get("REALTY_MAX_POSTS", "0"))  # 0 = без лимита
# Записывать ли посты «спрос» (сниму/ищу). По умолчанию да — это рыночные
# данные; в счётчик агентств они всё равно не попадают.
KEEP_WANTED = os.environ.get("REALTY_SKIP_WANTED") != "1"


async def _author_username(msg):
    """Ник автора поста (без @) или None. Больше НИКАКИХ данных о человеке
    не берём (правило Направления 3)."""
    try:
        sender = await msg.get_sender()
        return getattr(sender, "username", None) or None
    except Exception:  # noqa: BLE001
        return None


async def process_channel(client, sheet, ch: dict, persist: bool):
    username = ch["username"]
    print(f"\n🏠 Группа @{username} ({ch['title']})")

    try:
        entity = await client.get_entity(username)
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠ не удалось открыть @{username}: {e}")
        return

    last_id = state.get_last_id(username)
    if last_id > 0:
        kwargs = {"min_id": last_id, "reverse": True}
        print(f"  читаю новые посты после id {last_id}")
    else:
        since = datetime.now(timezone.utc) - timedelta(days=FIRST_RUN_DAYS)
        kwargs = {"offset_date": since, "reverse": True}
        print(f"  первый заход: посты за последние {FIRST_RUN_DAYS} дней")

    max_read_id = last_id
    written_id = last_id
    added = skipped = duped = not_realty = seen = 0
    write_failed = False
    buffer = []
    pending = set()

    def flush() -> bool:
        nonlocal written_id, added
        if not buffer:
            return True
        ok = sheet.flush([item for _, item in buffer])
        if ok:
            written_id = max(written_id, max(mid for mid, _ in buffer))
            added += len(buffer)
            if persist:
                for _, item in buffer:
                    dedup.remember(item.get("author"), item["snippet"],
                                   item.get("channel"))
                dedup.save()
            buffer.clear()
        return ok

    try:
        async for msg in client.iter_messages(entity, **kwargs):
            max_read_id = max(max_read_id, msg.id)
            text = msg.message
            if not text:
                continue
            if not is_realty_candidate(text):
                skipped += 1
                continue
            author = await _author_username(msg)
            key = dedup.make_key(author, text, ch["title"])
            if key in pending or dedup.is_dup(author, text, ch["title"]):
                duped += 1
                continue
            seen += 1
            if MAX_POSTS_PER_CHANNEL and seen > MAX_POSTS_PER_CHANNEL:
                print(f"  ⏹ достигнут лимит {MAX_POSTS_PER_CHANNEL} постов — стоп")
                break
            fields = extract(text)
            if not fields["is_realty"]:
                not_realty += 1
                continue
            if fields["kind"] == "спрос" and not KEEP_WANTED:
                not_realty += 1
                continue
            pending.add(key)
            buffer.append((msg.id, {
                "date": msg.date,
                "link": f"https://t.me/{username}/{msg.id}",
                "author": author,
                "channel": ch["title"],
                "snippet": text,
                "fields": fields,
            }))
            if len(buffer) >= BATCH_SIZE and not flush():
                write_failed = True
                break
            await asyncio.sleep(DELAY_BETWEEN_POSTS)
    except FloodWaitError as e:
        print(f"  ⏳ Telegram просит подождать {e.seconds}с — пауза")
        await asyncio.sleep(e.seconds + 5)

    if not write_failed and not flush():
        write_failed = True

    final_id = written_id if write_failed else max(max_read_id, written_id)
    if final_id > last_id:
        state.set_last_id(username, final_id)

    tail = " (запись прервалась — остальное в след. раз)" if write_failed else ""
    print(f"  ✅ записано: {added}; не про жильё: {not_realty}; "
          f"копий отсеяно: {duped}; болтовни пропущено: {skipped}; "
          f"докуда дочитал: {final_id}{tail}")


class DryRunSink:
    """Холостой ход: показывает разбор на экране вместо записи в таблицу."""

    def __init__(self):
        print("🧪 ХОЛОСТОЙ ХОД (DRY_RUN): в таблицу НЕ пишу, только показываю.")

    def flush(self, listings):
        for x in listings:
            f = x["fields"]
            price = f"{f['price']:,}".replace(",", " ") if f["price"] else "цена ?"
            per = f"/{f['period']}" if f["period"] else ""
            beds = f"{f['bedrooms']} сп." if f["bedrooms"] is not None else "спальни ?"
            author = f"@{x['author']}" if x.get("author") else "без ника"
            snip = (x["snippet"] or "").replace("\n", " ").strip()[:70]
            print(f"    [{x['date']:%Y-%m-%d}] {f['kind']} · {f['deal'] or '?'} · "
                  f"{f['prop_type'] or '?'} · {price}{per} · {beds} · "
                  f"{f['district'] or 'район ?'} · {author}\n"
                  f"        {x['link']}\n        «{snip}»")
        return True

    def rebuild_counter(self):
        return True


def _make_sink():
    dry = os.environ.get("DRY_RUN") == "1" or not os.environ.get("REALTY_SHEET_WEBHOOK_URL")
    if dry:
        return DryRunSink()
    from realty_sheets import RealtySheet
    return RealtySheet()


async def main():
    api_id = int(os.environ["TG_API_ID"])
    api_hash = os.environ["TG_API_HASH"]
    session = StringSession(os.environ["TG_SESSION"])

    sheet = _make_sink()
    persist = not isinstance(sheet, DryRunSink)
    dedup.load()

    async with TelegramClient(session, api_id, api_hash) as client:
        me = await client.get_me()
        assert isinstance(me, User), "сессия не залогинена как аккаунт"
        print(f"🔑 вошёл как {me.first_name} (id {me.id})")

        for i, ch in enumerate(CHANNELS):
            try:
                await process_channel(client, sheet, ch, persist)
            except Exception as e:  # noqa: BLE001
                print(f"  ⚠ группа @{ch['username']} прервалась: {e} — иду дальше")
            if i < len(CHANNELS) - 1:
                await asyncio.sleep(DELAY_BETWEEN_CHANNELS)

    # Счётчик агентств пересчитываем сразу после прогона — чтобы цифры в
    # таблице всегда соответствовали свежим строкам.
    sheet.rebuild_counter()
    print("\n🏁 Прогон недвижимости завершён.")


if __name__ == "__main__":
    asyncio.run(main())
