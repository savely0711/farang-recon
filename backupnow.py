"""Запустить резервное зеркало фотографий ПРЯМО СЕЙЧАС, в фоне.

Зачем отдельный файл. В консоли Aeza не набираются подчёркивания, поэтому
команду `python3 backup_photos.py` там просто не напечатать. Здесь имя без
подчёркиваний - как у preparenow.py и realtynow.py.

Запуск:   cd /root/recon && git pull && python3 backupnow.py
Посмотреть, как идёт:   tail -n 20 backup.log
Только посчитать, ничего не качая:   python3 backupnow.py check
"""
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(BASE, "backup.log")

# -u обязателен: без него Python копит вывод в буфере, и `tail backup.log`
# показывает пустоту, пока скрипт не закончит. Проверено 08.09.2026 —
# зеркало исправно качало, а лог был пустой, и выглядело как поломка.
args = ["/usr/bin/python3", "-u", os.path.join(BASE, "backup_photos.py")]
if len(sys.argv) > 1 and sys.argv[1] == "check":
    args.append("check")

with open(LOG, "a", encoding="utf-8") as log:
    subprocess.Popen(args, stdout=log, stderr=log, cwd=BASE,
                     start_new_session=True)

print("зеркало фотографий запущено в фоне.")
print(f"лог: {LOG}")
print("посмотреть, как идёт:  tail -n 20 backup.log")
print("первый прогон качает всю библиотеку (около 0,6 ГБ) - это 10-20 минут,")
print("дальше каждую ночь будут докачиваться только новые снимки.")
