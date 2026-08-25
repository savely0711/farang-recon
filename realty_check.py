"""
ПРОВЕРКА ГРУПП НЕДВИЖИМОСТИ — состоит ли аккаунт разведки в каждой группе из
realty_channels.py и сколько там постов за последние 7 дней.

Ничего не пишет: ни в таблицу, ни в память прочитанного. Только читает.

Запуск (набирается в консоли Aeza без Shift):  python3 realty_check.py
"""
import asyncio
import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession

from realty_channels import CHANNELS

load_dotenv()

DAYS = 7


async def main():
    client = TelegramClient(
        StringSession(os.environ["TG_SESSION"]),
        int(os.environ["TG_API_ID"]),
        os.environ["TG_API_HASH"],
    )
    await client.start()
    me = await client.get_me()
    print(f"аккаунт: @{getattr(me, 'username', None) or me.first_name}\n")

    since = datetime.now(timezone.utc) - timedelta(days=DAYS)
    for ch in CHANNELS:
        u = ch["username"]
        try:
            entity = await client.get_entity(u)
        except Exception as e:  # noqa: BLE001
            print(f"  НЕТ ДОСТУПА  @{u}: {e}")
            continue
        try:
            n = 0
            last = None
            async for msg in client.iter_messages(entity, offset_date=since, reverse=True):
                n += 1
                last = msg.date
            mark = "ok" if n else "пусто"
            last_s = last.strftime("%d.%m %H:%M") if last else "-"
            print(f"  {mark:6} @{u}: постов за {DAYS} дней {n}, последний {last_s}")
        except Exception as e:  # noqa: BLE001
            print(f"  ОШИБКА ЧТЕНИЯ @{u}: {e}")
        await asyncio.sleep(2)

    await client.disconnect()


asyncio.run(main())
