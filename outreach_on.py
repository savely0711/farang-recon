"""Включает авто-отправку: ставит OUTREACH_ENABLED=1 в .env.
Запуск: python3 outreach_on.py   (выключить: python3 outreach_off.py)"""
import os
import re

ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
text = open(ENV_PATH, encoding="utf-8").read()
if re.search(r"^OUTREACH_ENABLED=.*$", text, re.MULTILINE):
    text = re.sub(r"^OUTREACH_ENABLED=.*$", "OUTREACH_ENABLED=1", text, flags=re.MULTILINE)
else:
    text = text.rstrip() + "\nOUTREACH_ENABLED=1\n"
open(ENV_PATH, "w", encoding="utf-8").write(text)
print("✅ Авто-отправка ВКЛЮЧЕНА (OUTREACH_ENABLED=1).")
