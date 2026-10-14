"""Включить IPv6 для связи с Telegram: пишет в .env строку TG_IPV6=1.
Запуск: python3 ipv6on.py   (выключить: python3 ipv6on.py off)
Нужно на Aeza Стокгольм: дата-центр Telegram DC5 там недоступен по IPv4."""
import os
import sys

ENV = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
val = "0" if len(sys.argv) > 1 and sys.argv[1] == "off" else "1"
lines = open(ENV, encoding="utf-8").read().splitlines() if os.path.exists(ENV) else []
lines = [l for l in lines if not l.startswith("TG_IPV6=")] + [f"TG_IPV6={val}"]
open(ENV, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print(f"TG_IPV6={val} записано в .env")
