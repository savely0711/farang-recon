"""Ставит расписание cron: разведка (ежедневно 09:00) + отправка (каждые 25 мин).
Идемпотентно: если строка со скриптом уже есть — не дублирует.
Запуск: python3 install_cron.py"""
import subprocess

BASE = "/root/recon"
NEEDED = [
    f"0 9 * * * cd {BASE} && /usr/bin/python3 parser.py >> recon.log 2>&1",
    f"*/25 * * * * cd {BASE} && /usr/bin/python3 outreach.py >> outreach.log 2>&1",
]

cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
existing = cur.stdout if cur.returncode == 0 else ""
lines = [l for l in existing.splitlines() if l.strip()]

added = 0
for ln in NEEDED:
    marker = "parser.py" if "parser.py" in ln else "outreach.py"
    if any(marker in e for e in lines):
        continue
    lines.append(ln)
    added += 1

new = "\n".join(lines) + "\n"
subprocess.run(["crontab", "-"], input=new, text=True)
print("=== Текущий crontab ===")
print(new)
print(f"Добавлено новых строк: {added}")
