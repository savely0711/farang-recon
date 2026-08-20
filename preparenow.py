"""
АВТО-ПОДГОТОВКА ОБЪЯВЛЕНИЙ ВРУЧНУЮ, В ФОНЕ.

Зачем отдельный скрипт: разбор очереди идёт долго (на каждое объявление — ИИ,
скачивание всех фотографий и отправка на сайт), а VNC-консоль Aeza не умеет
прерывать запущенное: `Ctrl+C` там печатает букву «c». Запустишь напрямую —
консоль занята до самого конца. Этот скрипт уводит работу в фон и сразу
возвращает приглашение.

Запуск:
    python3 preparenow.py           — сколько задано в .env (по умолчанию 30)
    python3 preparenow.py 300       — разобрать до 300 объявлений за прогон

Смотреть ход:   tail -n 40 prepare.log
Готово, когда в логе появится строка «Готово. На сайт: …».
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "prepare.log")

args = [a for a in sys.argv[1:] if a.strip()]

with open(LOG, "a", encoding="utf-8") as log:
    p = subprocess.Popen(
        # -u: питон пишет в лог сразу, а не копит буфер — чтобы tail показывал ход
        [sys.executable, "-u", "prepare.py", *args],
        cwd=HERE, stdout=log, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, start_new_session=True,
    )

print(f"авто-подготовка запущена в фоне, номер процесса {p.pid}")
print(f"лог: {LOG}")
print("смотреть ход:  tail -n 40 prepare.log")
