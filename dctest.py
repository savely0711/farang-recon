"""Проверка связи сервера с дата-центрами Telegram (14.10.2026).

Запуск:  python3 dctest.py
Печатает, до каких DC Telegram сервер достаёт по IPv4 и IPv6 (порт 443).
Зачем: на Aeza Стокгольм DC5 (91.108.56.x, Сингапур) по IPv4 не отвечает —
из-за этого не качаются фото, а parser.py зависал на часы.
"""
import socket

DCS = {
    1: ("149.154.175.53", "2001:b28:f23d:f001::a"),
    2: ("149.154.167.51", "2001:67c:4e8:f002::a"),
    3: ("149.154.175.100", "2001:b28:f23d:f003::a"),
    4: ("149.154.167.91", "2001:67c:4e8:f004::a"),
    5: ("91.108.56.130", "2001:b28:f23f:f005::a"),
}


def probe(family, addr):
    s = socket.socket(family, socket.SOCK_STREAM)
    s.settimeout(5)
    try:
        s.connect((addr, 443))
        return "ok"
    except Exception as e:  # noqa: BLE001
        return f"нет ({type(e).__name__})"
    finally:
        s.close()


for dc, (v4, v6) in DCS.items():
    print(f"DC{dc}:  IPv4 {probe(socket.AF_INET, v4):22}  IPv6 {probe(socket.AF_INET6, v6)}")
