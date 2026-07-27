"""Псевдоним login_send.py без подчёркивания в имени — VNC-консоль Aeza не вводит '_'.
Запуск: python3 loginsend.py"""
import os
import runpy
runpy.run_path(os.path.join(os.path.dirname(__file__), "login_send.py"), run_name="__main__")
