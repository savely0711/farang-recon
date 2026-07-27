"""
РАЗОВЫЙ вход ОТПРАВЛЯЮЩЕГО аккаунта (для «первого касания», пункт 14).

Отличие от login.py: сохраняет сессию в первый СВОБОДНЫЙ слот
TG_SEND_SESSION_1..3 в .env и НЕ трогает TG_SESSION (аккаунт разведки).
Телефон можно вводить просто цифрами с кодом страны — «+» добавится сам
(в VNC-консоли Aeza не работает Shift, поэтому «+» набрать нельзя).

Запуск на сервере:  python3 login_send.py
Спросит телефон -> код из Telegram -> облачный пароль (если включён).
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


def next_free_slot() -> int | None:
    text = open(ENV_PATH, encoding="utf-8").read()
    for i in range(1, 6):
        m = re.search(rf"^TG_SEND_SESSION_{i}=(.*)$", text, re.MULTILINE)
        if not m or not m.group(1).strip():
            return i
    return None


def save_session(slot: int, session_str: str) -> None:
    key = f"TG_SEND_SESSION_{slot}"
    text = open(ENV_PATH, encoding="utf-8").read()
    if re.search(rf"^{key}=.*$", text, re.MULTILINE):
        text = re.sub(rf"^{key}=.*$", f"{key}={session_str}", text, flags=re.MULTILINE)
    else:
        text = text.rstrip() + f"\n{key}={session_str}\n"
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write(text)


def ask_phone() -> str:
    p = input("Телефон (можно просто цифрами с кодом страны, напр. 66812345678): ").strip()
    if p and not p.startswith("+"):
        p = "+" + re.sub(r"\D", "", p)
    return p


async def main():
    slot = next_free_slot()
    if slot is None:
        print("Все слоты TG_SEND_SESSION_1..3 заняты. Чтобы перелогинить аккаунт — "
              "очисти нужную строку в .env и запусти снова.")
        return
    print(f"Вход отправляющего аккаунта в слот TG_SEND_SESSION_{slot}…")
    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.start(phone=ask_phone)  # код и пароль спросит сам через input()
    me = await client.get_me()
    save_session(slot, client.session.save())
    who = getattr(me, "username", None) or me.first_name
    print(f"\n✅ Готово: @{who} сохранён в слот {slot}. Сессия записана в .env.")
    print("Запусти ещё раз для следующего аккаунта, либо переходи к включению отправки.")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
