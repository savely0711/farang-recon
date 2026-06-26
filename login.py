"""
РАЗОВЫЙ вход техническим аккаунтом Telegram.

Запуск на сервере:  python3 login.py
Спросит номер телефона → код из Telegram → пароль (если включён облачный).
Строку сессии сохранит САМ в .env (TG_SESSION) — руками править ничего не надо.
Дальше парсер входит автоматически, код больше не понадобится.

API_ID / API_HASH должны быть уже в .env (их кладёт configure.sh).
Совместимо с Python 3.14 (используется asyncio.run, без telethon.sync).
"""
import asyncio
import os
import re

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession

ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(ENV_PATH)

api_id = int(os.environ["TG_API_ID"])
api_hash = os.environ["TG_API_HASH"]


def save_session_to_env(session_str: str) -> None:
    with open(ENV_PATH, "r", encoding="utf-8") as f:
        text = f.read()
    if re.search(r"^TG_SESSION=.*$", text, re.MULTILINE):
        text = re.sub(r"^TG_SESSION=.*$", f"TG_SESSION={session_str}", text, flags=re.MULTILINE)
    else:
        text += f"\nTG_SESSION={session_str}\n"
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write(text)


async def main():
    print("Входим в Telegram техническим аккаунтом…")
    client = TelegramClient(StringSession(), api_id, api_hash)
    # start() сам спросит телефон, код и (если есть) облачный пароль через input()
    await client.start()
    me = await client.get_me()
    save_session_to_env(client.session.save())
    print(f"\n✅ Вход выполнен: {me.first_name} (id {me.id})")
    print("Строка сессии сохранена в .env. Код больше не понадобится.")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
