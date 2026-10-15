"""Ставит расписание cron на сервере разведки. Запуск: python3 install_cron.py

С 15.10.2026 (режим «всё на сайт», решение Савелия): новое подтягиваем
ТРИ РАЗА В ДЕНЬ. Время ниже — по БАНГКОКУ; скрипт сам пересчитывает его в
часовой пояс сервера (новый Aeza живёт по UTC), так что менять ничего не надо.

  08:30 / 13:30 / 18:30  realty_parser.py — группы недвижимости → своя таблица
  09:00 / 14:00 / 19:00  parser.py        — барахолки → таблица разведки
  10:00 / 15:00 / 20:00  prepare.py       — всё новое → на сайт (чистое сразу
                                            в ленту, сомнительное в ручную очередь)
  21:00                  fillhash.py      — добор отпечатков картинок (db/33)
  21:30                  syncsite.py      — сверка таблицы с сайтом
  03:00                  backupdb.py      — резервная копия базы
  03:30                  backup_photos.py — зеркало фотографий

Строки этих скриптов скрипт ЗАМЕНЯЕТ (старые удаляет), остальные не трогает.
Рассылки «первое касание» здесь НЕТ (остановлена 01.09.2026); её строку
выключает outreach_off.py, включает outreach_on.py — сюда не добавляем.
"""
import re
import subprocess
import time

BASE = "/root/recon"
BKK = 7 * 3600  # Бангкок = UTC+7

# (часы по Бангкоку, минута, команда)
PLAN = [
    ([8, 13, 18], 30, "/usr/bin/python3 realty_parser.py >> realty.log 2>&1"),
    ([9, 14, 19], 0, "/usr/bin/python3 parser.py >> recon.log 2>&1"),
    ([10, 15, 20], 0, "/usr/bin/python3 prepare.py >> prepare.log 2>&1"),
    ([21], 0, "/usr/bin/python3 fillhash.py >> fillhash.log 2>&1"),
    ([21], 30, "/usr/bin/python3 syncsite.py >> syncsite.log 2>&1"),
    ([3], 0, "/usr/bin/python3 -u backupdb.py >> backupdb.log 2>&1"),
    ([3], 30, "/usr/bin/python3 -u backup_photos.py >> backup.log 2>&1"),
]

# Смещение сервера от UTC в секундах (летнее время тоже учтено).
local_off = -(time.altzone if time.localtime().tm_isdst > 0 else time.timezone)
shift_h = (local_off - BKK) // 3600

NEEDED = []
for hours, minute, cmd in PLAN:
    hs = sorted(((h + shift_h) % 24) for h in hours)
    NEEDED.append(f"{minute} {','.join(map(str, hs))} * * * cd {BASE} && {cmd}")

cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
existing = cur.stdout if cur.returncode == 0 else ""
lines = [l for l in existing.splitlines() if l.strip()]


def marker(line: str):
    # «parser.py» — часть «realty_parser.py», поэтому имя берём целиком и
    # сравниваем с пробелом впереди.
    m = re.search(r" (\S+\.py)", line)
    return m.group(1) if m else None


managed = {marker(n) for n in NEEDED}
kept = [l for l in lines if marker(l) not in managed]
new = "\n".join(kept + NEEDED) + "\n"
subprocess.run(["crontab", "-"], input=new, text=True)
print(f"часовой пояс сервера: UTC{local_off // 3600:+d}; время в плане — по Бангкоку")
print("=== Текущий crontab ===")
print(new)
print(f"строк расписания разведки: {len(NEEDED)} (старые заменены)")
