"""
ОТЧЁТ О КАЧЕСТВЕ РАЗБОРА — сколько всего вытаскивают правила из настоящих
постов. Ничего не пишет: ни в таблицу, ни в память прочитанного, ни в дедуп.

Зачем: разбор идёт правилами, без ИИ, и мы заранее не знаем, какая доля постов
разбирается полностью. Этот отчёт показывает по живым постам, у скольких
объявлений нашлись цена, спальни, район и тип сделки. Если доля низкая —
поправим словари или добавим ИИ точечно на непонятые посты.

Запуск (последнее число — сколько постов смотреть на группу):
    python3 realtytry.py 200
Показать примеры того, что НЕ разобралось:
    python3 realtytry.py 200 bad
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession

from realty_channels import CHANNELS
from realty_extract import extract, is_realty_candidate

load_dotenv()

LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 200
SHOW_BAD = "bad" in sys.argv
DAYS = int(os.environ.get("REALTY_TRY_DAYS", "14"))


def _pct(part: int, total: int) -> str:
    return f"{(100 * part / total):.0f}%" if total else "—"


async def main():
    client = TelegramClient(
        StringSession(os.environ["TG_SESSION"]),
        int(os.environ["TG_API_ID"]),
        os.environ["TG_API_HASH"],
    )
    await client.start()
    since = datetime.now(timezone.utc) - timedelta(days=DAYS)

    total = candidates = realty = 0
    got = {"deal": 0, "price": 0, "bedrooms": 0, "district": 0, "prop_type": 0}
    kinds = {"предложение": 0, "спрос": 0}
    full = 0
    samples, bad = [], []

    for ch in CHANNELS:
        print(f"\n📂 @{ch['username']} — читаю до {LIMIT} постов за {DAYS} дней")
        try:
            entity = await client.get_entity(ch["username"])
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠ не открылась: {e}")
            continue
        seen = 0
        async for msg in client.iter_messages(entity, offset_date=since, reverse=True):
            text = msg.message
            if not text:
                continue
            total += 1
            if not is_realty_candidate(text):
                continue
            candidates += 1
            f = extract(text)
            if not f["is_realty"]:
                continue
            realty += 1
            kinds[f["kind"]] = kinds.get(f["kind"], 0) + 1
            for key in got:
                if f[key] not in (None, "", False):
                    got[key] += 1
            if f["deal"] and f["price"] and f["district"]:
                full += 1
                if len(samples) < 5:
                    samples.append((f, text))
            elif len(bad) < 8:
                bad.append((f, text))
            seen += 1
            if seen >= LIMIT:
                break
            await asyncio.sleep(0.3)
        print(f"  просмотрено постов: {seen}")

    await client.disconnect()

    print("\n" + "=" * 60)
    print("ОТЧЁТ О КАЧЕСТВЕ РАЗБОРА (ничего не записано)")
    print(f"  всего постов прочитано:      {total}")
    print(f"  похожи на объявление:        {candidates}")
    print(f"  признаны недвижимостью:      {realty}")
    if realty:
        print(f"    из них предложений:        {kinds.get('предложение', 0)}")
        print(f"    из них спроса (сниму/ищу): {kinds.get('спрос', 0)}")
        print("\n  что удалось вытащить (доля от объявлений):")
        print(f"    сделка (аренда/продажа):   {got['deal']:5} — {_pct(got['deal'], realty)}")
        print(f"    цена:                      {got['price']:5} — {_pct(got['price'], realty)}")
        print(f"    тип жилья:                 {got['prop_type']:5} — {_pct(got['prop_type'], realty)}")
        print(f"    спальни:                   {got['bedrooms']:5} — {_pct(got['bedrooms'], realty)}")
        print(f"    район:                     {got['district']:5} — {_pct(got['district'], realty)}")
        print(f"\n  разобрано целиком (сделка+цена+район): {full} — {_pct(full, realty)}")

    if samples:
        print("\n  примеры удачного разбора:")
        for f, text in samples:
            print(f"    · {f['deal']} · {f['prop_type']} · {f['price']} {f['currency']}"
                  f"/{f['period']} · {f['bedrooms']} сп. · {f['district']}")
            print(f"      «{text[:90].replace(chr(10), ' ')}…»")
    if SHOW_BAD and bad:
        print("\n  чего не хватило (для подкрутки словарей):")
        for f, text in bad:
            miss = [k for k in ("deal", "price", "district") if not f[k]]
            print(f"    · не нашлось: {', '.join(miss)}")
            print(f"      «{text[:120].replace(chr(10), ' ')}…»")


asyncio.run(main())
