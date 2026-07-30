"""Прописать в .env ник, которому слать предупреждения о блокировке рассылки.

Зачем отдельный помощник: в веб-консоли Aeza (VNC) не вводятся заглавные буквы,
«_» и «@», поэтому строку `OUTREACH_NOTIFY_TO=@ник` руками там не набрать.

Запуск (только строчные буквы, дефис вместо подчёркивания):
    python3 setnotify.py savely-k          → запишет OUTREACH_NOTIFY_TO=@savely_k
    python3 setnotify.py savely-k test     → ещё и пошлёт пробное сообщение
"""
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ENV = os.path.join(BASE, ".env")
KEY = "OUTREACH_NOTIFY_TO"


def set_nick(raw: str) -> str:
    nick = raw.strip().lstrip("@").replace("-", "_")
    line = f"{KEY}=@{nick}"
    lines = []
    if os.path.exists(ENV):
        with open(ENV, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    out, replaced = [], False
    for ln in lines:
        if ln.strip().startswith(KEY + "=") or ln.strip().startswith("#" + KEY + "="):
            if not replaced:
                out.append(line)
                replaced = True
        else:
            out.append(ln)
    if not replaced:
        out.append(line)
    with open(ENV, "w", encoding="utf-8") as f:
        f.write("\n".join(out).rstrip("\n") + "\n")
    return f"@{nick}"


def send_test(nick: str) -> None:
    import asyncio
    from dotenv import load_dotenv
    load_dotenv(ENV, override=True)

    async def go():
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        session = os.environ.get("TG_SEND_SESSION_1")
        if not session:
            print("Нет сессии отправки (TG_SEND_SESSION_1) — пробное не шлю.")
            return
        client = TelegramClient(StringSession(session),
                                int(os.environ["TG_API_ID"]), os.environ["TG_API_HASH"])
        await client.connect()
        try:
            await client.send_message(
                nick, "Проверка связи: сюда будут приходить предупреждения, "
                      "если рассылка «первое касание» встанет.")
            print(f"Пробное сообщение отправлено {nick}.")
        except Exception as e:  # noqa: BLE001
            print(f"Не вышло отправить пробное: {type(e).__name__}: {e}")
        finally:
            await client.disconnect()

    asyncio.run(go())


def main():
    if len(sys.argv) < 2:
        print("Укажите ник строчными, дефис вместо подчёркивания:\n"
              "    python3 setnotify.py savely-k")
        raise SystemExit(1)
    nick = set_nick(sys.argv[1])
    print(f"Записал в .env: {KEY}={nick}")
    if len(sys.argv) > 2 and sys.argv[2].lower() == "test":
        send_test(nick)


if __name__ == "__main__":
    main()
