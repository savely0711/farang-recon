"""Разовый прогон отправки ПРЯМО СЕЙЧАС, мимо ограничения по часам (для проверки).
Всё остальное — как обычно: дневной лимит, паузы, статусы CRM.
Запуск: python3 sendnow.py   (имя без '_' — VNC-консоль Aeza не вводит подчёркивание)"""
import os
import runpy

os.environ["OUTREACH_HOURS"] = "0-24"
runpy.run_path(os.path.join(os.path.dirname(__file__), "outreach.py"), run_name="__main__")
