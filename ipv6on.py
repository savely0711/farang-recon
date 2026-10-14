"""Включить IPv6 для дата-центра Telegram DC5: пишет в .env TG_IPV6_DCS=5.
Запуск: python3 ipv6on.py   (выключить: python3 ipv6on.py off)
Нужно на Aeza Стокгольм: DC5 там недоступен по IPv4 (см. dctest.py)."""
import os
import sys

ENV = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
val = "" if len(sys.argv) > 1 and sys.argv[1] == "off" else "5"
lines = open(ENV, encoding="utf-8").read().splitlines() if os.path.exists(ENV) else []
lines = [l for l in lines if not l.startswith(("TG_IPV6_DCS=", "TG_IPV6="))] + [f"TG_IPV6_DCS={val}"]
open(ENV, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print(f"TG_IPV6_DCS={val} записано в .env")
