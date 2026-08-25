"""
Запись объявлений о недвижимости в ОТДЕЛЬНУЮ Google-таблицу
(«Фаранг — Недвижимость»), через свой скрипт-приёмник realty_apps_script.gs.

Почему отдельный файл-таблица, а не вкладка в старой (решение Савелия
25.08.2026): рассылка `outreach.py` и авто-подготовка `prepare.py` читают
таблицу разведки. Если положить недвижимость туда же, они рано или поздно
зацепят агентства — начнут им писать или тащить их объявления на сайт. Разные
файлы делают это невозможным физически, а не «по договорённости в коде».

В .env нужны две строки (свои, НЕ те же, что у разведки):
  REALTY_SHEET_WEBHOOK_URL — адрес веб-приложения (…/exec)
  REALTY_SHEET_TOKEN       — пароль-токен, тот же, что вшит в скрипт таблицы
Пока адрес пуст — парсер работает вхолостую (показывает на экране, не пишет).

Вкладки таблицы (их делает и наполняет скрипт-приёмник):
  «Объявления» — строка = пост. Ник | Ссылка | Группа | Дата | Что это |
                 Сделка | Тип жилья | Цена | Валюта | Период | Цена макс |
                 Спальни | Площадь | Район | Тип продавца | Агентство |
                 Проект | Разбор | Описание
  «Счётчик»    — строка = ник. Тип продавца, агентство, сколько объявлений за
                 7 дней, за 30 дней и за всё время, первый и последний пост,
                 в каких группах, доля от всех объявлений. Пересчитывается
                 сама раз в сутки и кнопкой в меню таблицы.

Колонка «Разбор» показывает, кто разобрал строку: «ИИ», «ИИ+правила» или
«правила» (ИИ не ответил — например, кончился баланс Anthropic).

Дубли по ссылке отсекает скрипт таблицы; повтор того же текста — раньше, сам
парсер (realty_dedup.json). Пишем пачками и переживаем временные сбои Google.
"""
import os
import time

import httpx

LISTINGS_TAB = "Объявления"
COUNTER_TAB = "Счётчик"

MAX_RETRIES = 3
RETRY_BACKOFF = [3, 8, 20]


def _clean_nick(author) -> str:
    """Ник без @ и в нижнем регистре — иначе @Agency и @agency станут двумя
    разными агентствами в счётчике."""
    return (author or "").lstrip("@").strip().lower()


class RealtySheet:
    def __init__(self):
        self._url = os.environ["REALTY_SHEET_WEBHOOK_URL"]
        self._token = os.environ.get("REALTY_SHEET_TOKEN", "")
        # follow_redirects обязателен: Apps Script отвечает 302 на googleusercontent.
        self._client = httpx.Client(timeout=60.0, follow_redirects=True)
        print("🏠 Пишу в таблицу «Фаранг — Недвижимость» (пачками).")

    @staticmethod
    def _row(listing: dict) -> dict:
        """Готовит объявление к записи. `fields` — результат realty_extract.extract."""
        f = listing.get("fields") or {}
        snippet = (listing.get("snippet") or "").replace("\n", " ").strip()[:300]
        area = f.get("area")
        return {
            "author": _clean_nick(listing.get("author")),
            "link": listing["link"],
            "channel": listing.get("channel") or "",
            "date": listing["date"].strftime("%Y-%m-%d %H:%M"),
            "kind": f.get("kind") or "",
            "deal": f.get("deal") or "",
            "prop_type": f.get("prop_type") or "",
            "price": f.get("price"),
            "currency": f.get("currency") or "",
            "period": f.get("period") or "",
            "price_max": f.get("price_max"),
            "bedrooms": f.get("bedrooms"),
            "area": area,
            "district": f.get("district") or "",
            "seller": f.get("seller") or "",
            "agency": f.get("agency") or "",
            "project": f.get("project") or "",
            "parsed_by": f.get("parsed_by") or "",
            "snippet": snippet,
        }

    def flush(self, listings: list) -> bool:
        """Отправляет пачку одним запросом. False — Google не принял даже после
        повторов (наружу не бросаем, прогон не роняем)."""
        if not listings:
            return True
        payload = {
            "token": self._token,
            "action": "append",
            "rows": [self._row(x) for x in listings],
        }
        return self._post_retry(payload, note=f"пачка ({len(listings)} стр.)")

    def rebuild_counter(self) -> bool:
        """Просит таблицу пересчитать вкладку «Счётчик» прямо сейчас."""
        return self._post_retry({"token": self._token, "action": "counter"},
                                note="пересчёт счётчика")

    def ping(self) -> bool:
        return self._post_retry({"token": self._token, "action": "ping"},
                                note="проверка связи")

    def _post_retry(self, payload: dict, note: str) -> bool:
        for attempt in range(MAX_RETRIES):
            try:
                r = self._client.post(self._url, json=payload)
                r.raise_for_status()
                data = r.json()
                if data.get("ok"):
                    return True
                print(f"  ⚠ таблица отказала ({note}): {data.get('error')}")
            except Exception as e:  # noqa: BLE001
                print(f"  ⚠ не дошло до таблицы ({note}): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF[attempt])
        print(f"  ❌ так и не записал ({note}) — эти посты перечитаю в следующий раз")
        return False
