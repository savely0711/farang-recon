"""Выключает авто-отправку ПОЛНОСТЬЮ: снимает флаг в .env И убирает строку
outreach.py из расписания cron.

Почему двумя действиями. Флаг в .env останавливает отправку мгновенно, но
строка в cron остаётся и каждые 25 минут будит скрипт впустую — он
просыпается, видит выключенный флаг и молча выходит, засоряя outreach.log.
Савелий 01.09.2026 попросил остановить рассылку насовсем, поэтому убираем
и расписание. Обратно включает outreach_on.py — он же возвращает строку в cron.

Запуск: python3 outreach_off.py   (или короче: python3 sendoff.py)
"""
import os
import re
import subprocess

ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
text = open(ENV_PATH, encoding="utf-8").read()
if re.search(r"^OUTREACH_ENABLED=.*$", text, re.MULTILINE):
    text = re.sub(r"^OUTREACH_ENABLED=.*$", "OUTREACH_ENABLED=", text, flags=re.MULTILINE)
else:
    text = text.rstrip() + "\nOUTREACH_ENABLED=\n"
open(ENV_PATH, "w", encoding="utf-8").write(text)
print("⏸ Авто-отправка ВЫКЛЮЧЕНА (флаг в .env снят).")

# ── убираем строку из расписания ──
# Ищем по " outreach.py" с пробелом впереди — чтобы не зацепить чужие строки
# (тот же приём, что в install_cron.py: «parser.py» — часть «realty_parser.py»).
cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
if cur.returncode != 0:
    print("· расписание cron не прочиталось — строку убрать не удалось")
else:
    lines = [l for l in cur.stdout.splitlines() if l.strip()]
    kept = [l for l in lines if " outreach.py" not in l]
    removed = len(lines) - len(kept)
    if removed:
        subprocess.run(["crontab", "-"], input="\n".join(kept) + "\n", text=True)
        print(f"🗑 Из расписания убрано строк с outreach.py: {removed}")
    else:
        print("· в расписании строки с outreach.py не было")
print("Сбор объявлений, авто-подготовка и сверка с сайтом продолжают работать.")
