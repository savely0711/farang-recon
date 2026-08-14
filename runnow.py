"""
ЗАПУСК РАЗВЕДКИ ВРУЧНУЮ, В ФОНЕ.

Зачем отдельный скрипт: VNC-консоль Aeza не передаёт Shift, поэтому набрать
руками «nohup ... > recon.log 2>&1 &» в ней невозможно (нет знаков > и &).
Этот скрипт делает то же самое сам.

Запуск:  python3 runnow.py
(флаг -u: питон пишет в лог сразу, а не копит буфер — чтобы tail показывал ход)
Смотреть ход:  tail -n 40 recon.log
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "recon.log")

with open(LOG, "a", encoding="utf-8") as log:
    p = subprocess.Popen(
        [sys.executable, "-u", "parser.py"],
        cwd=HERE, stdout=log, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, start_new_session=True,
    )

print(f"разведка запущена в фоне, номер процесса {p.pid}")
print(f"лог: {LOG}")
print("смотреть ход:  tail -n 40 recon.log")
