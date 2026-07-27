"""Псевдоним outreach_off.py без подчёркивания в имени — VNC-консоль Aeza не вводит '_'.
Запуск: python3 sendoff.py"""
import os
import runpy
runpy.run_path(os.path.join(os.path.dirname(__file__), "outreach_off.py"), run_name="__main__")
