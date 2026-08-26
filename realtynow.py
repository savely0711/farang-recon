"""
ЗАПУСК ПАРСЕРА НЕДВИЖИМОСТИ ВРУЧНУЮ, В ФОНЕ.

Зачем отдельный скрипт: VNC-консоль Aeza не передаёт Shift (значков «>» и «&»
там не набрать) и не умеет прерывать запущенное — `Ctrl+C` печатает букву «c».
А первый прогон длинный: за месяц в двух группах тысячи постов, каждый идёт
через ИИ. Этот скрипт уводит работу в фон и сразу возвращает приглашение.

Запуск:
    python3 realtynow.py           — обычный добор новых постов
    python3 realtynow.py 25        — ПЕРВЫЙ заход: собрать посты за 25 дней
                                     (сколько дней назад начинать)
    python3 realtynow.py 25 200    — то же, но не больше 200 постов на группу
                                     (чтобы прицениться, прежде чем гнать всё)

Число дней действует только на группы, которые ещё ни разу не читались: если
парсер уже был в группе, он всё равно берёт только новое — так устроена память
`realty_state.json`.

Смотреть ход:  tail -n 40 realty.log
Готово, когда в логе появится строка «Прогон недвижимости завершён».
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "realty.log")

args = [a for a in sys.argv[1:] if a.strip()]
env = dict(os.environ)
if len(args) > 0 and args[0].isdigit():
    env["REALTY_FIRST_RUN_DAYS"] = args[0]
if len(args) > 1 and args[1].isdigit():
    env["REALTY_MAX_POSTS"] = args[1]

with open(LOG, "a", encoding="utf-8") as log:
    p = subprocess.Popen(
        # -u: питон пишет в лог сразу, а не копит буфер — чтобы tail показывал ход
        [sys.executable, "-u", "realty_parser.py"],
        cwd=HERE, stdout=log, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, start_new_session=True, env=env,
    )

days = env.get("REALTY_FIRST_RUN_DAYS", "7")
limit = env.get("REALTY_MAX_POSTS", "0")
print(f"парсер недвижимости запущен в фоне, номер процесса {p.pid}")
print(f"первый заход: за {days} дн.; постов на группу: "
      f"{'без ограничения' if limit in ('', '0') else limit}")
print(f"лог: {LOG}")
print("смотреть ход:  tail -n 40 realty.log")
