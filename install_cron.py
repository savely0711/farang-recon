"""Ставит расписание cron на сервере разведки. Идемпотентно: если строка со
скриптом уже есть — не дублирует. Запуск: python3 install_cron.py

Что и когда:
  09:00  parser.py    — ночной обход групп: новые объявления в таблицу
  10:00  prepare.py   — авто-подготовка объявлений «согласных» в очередь модерации
  10:40  fillhash.py  — добор отпечатков картинок для поиска дублей (db/33)
  11:20  syncsite.py  — сверка таблицы с сайтом: что стало с объявлениями и
                        кто из авторов зарегистрировался сам
  каждые 25 мин  outreach.py — рассылка первого касания

Порядок важен: prepare.py работает по свежей таблице, fillhash.py — по уже
загруженным на сайт снимкам, а syncsite.py подводит итог дня."""
import subprocess

BASE = "/root/recon"
NEEDED = [
    f"0 9 * * * cd {BASE} && /usr/bin/python3 parser.py >> recon.log 2>&1",
    f"0 10 * * * cd {BASE} && /usr/bin/python3 prepare.py >> prepare.log 2>&1",
    f"40 10 * * * cd {BASE} && /usr/bin/python3 fillhash.py >> fillhash.log 2>&1",
    f"20 11 * * * cd {BASE} && /usr/bin/python3 syncsite.py >> syncsite.log 2>&1",
    f"*/25 * * * * cd {BASE} && /usr/bin/python3 outreach.py >> outreach.log 2>&1",
]

cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
existing = cur.stdout if cur.returncode == 0 else ""
lines = [l for l in existing.splitlines() if l.strip()]

added = 0
for ln in NEEDED:
    marker = next(
        name for name in ("parser.py", "prepare.py", "fillhash.py",
                          "syncsite.py", "outreach.py")
        if name in ln
    )
    if any(marker in e for e in lines):
        continue
    lines.append(ln)
    added += 1

new = "\n".join(lines) + "\n"
subprocess.run(["crontab", "-"], input=new, text=True)
print("=== Текущий crontab ===")
print(new)
print(f"Добавлено новых строк: {added}")
