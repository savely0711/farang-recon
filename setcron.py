"""Псевдоним install_cron.py без подчёркивания в имени — VNC-консоль Aeza не вводит '_'.
Запуск: python3 setcron.py"""
import os
import runpy
runpy.run_path(os.path.join(os.path.dirname(__file__), "install_cron.py"), run_name="__main__")
