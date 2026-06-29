"""
Запись в Google-таблицу через Apps Script Web App.

Почему так (а не сервисный аккаунт): на наш сервер тяжело завезти большой
JSON-ключ (консоль Aeza ломает крупную вставку, а репозиторий публичный — секрет
туда класть нельзя). Поэтому к самой таблице привязан маленький скрипт-приёмник
(Apps Script), развёрнутый как веб-приложение. Парсер шлёт ему объявления
обычным POST-запросом. На сервере нужны только две короткие строки в .env:
адрес скрипта (SHEET_WEBHOOK_URL) и общий пароль-токен (SHEET_TOKEN).

ВАЖНО (надёжность): пишем ПАЧКАМИ (много строк за один запрос) и переживаем
временные сбои Google — повторяем попытку несколько раз, и если так и не вышло,
НЕ роняем весь прогон, а сообщаем об этом наверх (парсер пропустит/повторит позже).

Структура таблицы (создаёт сам скрипт):
  - вкладка на каждый канал (по имени из channels.py → ch["tab"]);
  - колонки: Дата | Категория | Цена (฿) | Ссылка | Краткое описание.
«Краткое описание» — первые слова поста для глазной проверки; личных данных
не выносим (имена/телефоны не собираем по правилу).
"""
import os
import time

import httpx

from categories import ALL_CATEGORIES

# Сколько раз пробуем записать одну пачку, прежде чем сдаться (с паузами между).
MAX_RETRIES = 3
RETRY_BACKOFF = [3, 8, 20]  # секунды паузы перед повторами 2 и 3


class Sheet:
    def __init__(self):
        self._url = os.environ["SHEET_WEBHOOK_URL"]
        self._token = os.environ.get("SHEET_TOKEN", "")
        # follow_redirects обязателен: Apps Script отвечает 302 на googleusercontent.
        # timeout побольше: пачка строк пишется чуть дольше одной.
        self._client = httpx.Client(timeout=60.0, follow_redirects=True)
        print("📊 Пишу в Google-таблицу через Apps Script Web App (пачками).")

    @staticmethod
    def _row(listing: dict) -> dict:
        """Готовит «сырое» объявление к записи: красивая категория, цена, обрезка."""
        cat_name = ALL_CATEGORIES.get(listing["category"], listing["category"])
        price = listing["price"]
        price_str = "" if price is None else ("даром" if price == 0 else str(price))
        snippet = (listing["snippet"] or "").replace("\n", " ").strip()[:120]
        return {
            "date": listing["date"].strftime("%Y-%m-%d %H:%M"),
            "category": cat_name,
            "price": price_str,
            "link": listing["link"],
            "snippet": snippet,
        }

    def flush(self, tab: str, listings: list) -> bool:
        """Отправляет ПАЧКУ объявлений в одну вкладку одним запросом.
        listings — список «сырых» dict (date/category/price/link/snippet).
        Возвращает True при успехе; False — если Google так и не принял после
        всех повторов. Наружу исключение НЕ бросаем — прогон не должен падать."""
        if not listings:
            return True
        payload = {
            "token": self._token,
            "tab": tab,
            "rows": [self._row(l) for l in listings],
        }
        last_err = None
        for attempt in range(MAX_RETRIES):
            try:
                r = self._client.post(self._url, json=payload)
                r.raise_for_status()
                data = r.json()
                if not data.get("ok"):
                    raise RuntimeError(f"Apps Script вернул ошибку: {data}")
                return True
            except Exception as e:  # noqa: BLE001
                last_err = e
                print(f"  ⚠ запись пачки ({len(listings)} стр.) не удалась "
                      f"(попытка {attempt + 1}/{MAX_RETRIES}): {e}")
                if attempt < MAX_RETRIES - 1:
                    wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
                    print(f"     повтор через {wait}с…")
                    time.sleep(wait)
        print(f"  ⛔ пачку записать не удалось — пропускаю на этот раз "
              f"(повторим в следующий прогон): {last_err}")
        return False
