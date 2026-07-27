"""Псевдоним outreach_on.py без подчёркивания в имени — VNC-консоль Aeza не вводит '_'.
Запуск: python3 sendon.py"""
import os
import runpy
runpy.run_path(os.path.join(os.path.dirname(__file__), "outreach_on.py"), run_name="__main__")
