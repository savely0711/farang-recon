"""Общий TelegramClient для серверных скриптов разведки (14.10.2026).

Зачем: на Aeza Стокгольм дата-центр Telegram DC5 (Сингапур) недоступен по
IPv4, а DC2 — по IPv6. Поэтому IPv6 включаем ТОЧЕЧНО — только для DC из
переменной TG_IPV6_DCS в .env (например «5»). Остальные идут по IPv4.
Включить: python3 ipv6on.py   Проверить связь: python3 dctest.py
"""
import os

from telethon import TelegramClient


def _ipv6_dcs() -> set:
    raw = os.environ.get("TG_IPV6_DCS", "")
    return {int(x) for x in raw.replace(" ", "").split(",") if x.isdigit()}


class ReconClient(TelegramClient):
    async def _get_dc(self, dc_id, cdn=False):
        if dc_id in _ipv6_dcs() and not self._use_ipv6:
            self._use_ipv6 = True
            try:
                return await super()._get_dc(dc_id, cdn)
            finally:
                self._use_ipv6 = False
        return await super()._get_dc(dc_id, cdn)


def tg_client(session, api_id, api_hash):
    """Короткие повторы подключения, чтобы недоступный DC не вешал прогон."""
    return ReconClient(session, api_id, api_hash,
                       connection_retries=3, retry_delay=2, timeout=15)
