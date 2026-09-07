"""
ЗАМЕР УСЛУГ В ФОНЕ (07.09.2026).

Зачем отдельный файл: в VNC-консоли Aeza не набирается подчёркивание, а
запущенное не прервать (Ctrl+C печатает букву «c»). Здесь имя без подчёркиваний
и работа уходит в фон — консоль сразу свободна.

Запуск:
    cd farang-recon && git pull && python3 zamer.py
    python3 zamer.py 80          — взять до 80 постов (по умолчанию 40)

Смотреть ход:   tail -n 50 zamer.log
Готово, когда в логе появятся таблички «УСЛУГИ» и «ВСЁ ОСТАЛЬНОЕ».
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "zamer.log")

args = [a for a in sys.argv[1:] if a.strip()] or ["40"]

with open(LOG, "w", encoding="utf-8") as log:
    p = subprocess.Popen(
        [sys.executable, "-u", "services_hits.py", *args],
        cwd=HERE, stdout=log, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, start_new_session=True,
    )

print(f"замер запущен в фоне, номер процесса {p.pid}")
print(f"лог: {LOG}")
print("смотреть ход:  tail -n 50 zamer.log")
