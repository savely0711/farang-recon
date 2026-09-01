"""Включает авто-отправку: ставит OUTREACH_ENABLED=1 в .env и ВОЗВРАЩАЕТ строку
outreach.py в расписание cron (её убирает outreach_off.py).

Запуск: python3 outreach_on.py   (выключить: python3 outreach_off.py)
"""
import os
import re
import subprocess

BASE = os.path.dirname(os.path.abspath(__file__))
CRON_LINE = f"*/25 * * * * cd {BASE} && /usr/bin/python3 outreach.py >> outreach.log 2>&1"

ENV_PATH = os.path.join(BASE, ".env")
text = open(ENV_PATH, encoding="utf-8").read()
if re.search(r"^OUTREACH_ENABLED=.*$", text, re.MULTILINE):
    text = re.sub(r"^OUTREACH_ENABLED=.*$", "OUTREACH_ENABLED=1", text, flags=re.MULTILINE)
else:
    text = text.rstrip() + "\nOUTREACH_ENABLED=1\n"
open(ENV_PATH, "w", encoding="utf-8").write(text)
print("✅ Авто-отправка ВКЛЮЧЕНА (OUTREACH_ENABLED=1).")

cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
existing = cur.stdout if cur.returncode == 0 else ""
lines = [l for l in existing.splitlines() if l.strip()]
if any(" outreach.py" in l for l in lines):
    print("· строка в расписании уже была")
else:
    lines.append(CRON_LINE)
    subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n", text=True)
    print("🕒 Строка outreach.py возвращена в расписание (каждые 25 минут).")
