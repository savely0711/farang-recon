"""
Запись в Google-таблицу через Apps Script Web App.

Почему так (а не сервисный аккаунт): на наш сервер тяжело завезти большой
JSON-ключ (консоль Aeza ломает крупную вставку, а репозиторий публичный — секрет
туда класть нельзя). Поэтому к самой таблице привязан маленький скрипт-приёмник
(Apps Script), развёрнутый как веб-приложение. Парсер просто шлёт ему строку
обычным POST-запросом. На сервере нужны только две короткие строки в .env:
адрес скрипта (SHEET_WEBHOOK_URL) и общий пароль-токен (SHEET_TOKEN).

Структура таблицы (создаёт сам скрипт):
  - вкладка на каждый канал (по имени из channels.py → ch["tab"]);
  - колонки: Дата | Категория | Цена (฿) | Ссылка | Краткое описание.
«Краткое описание» — первые слова поста для глазной проверки; личных данных
не выносим (имена/телефоны не собираем по правилу).
"""
import os

import httpx

from categories import ALL_CATEGORIES


class Sheet:
    def __init__(self):
        self._url = os.environ["SHEET_WEBHOOK_URL"]
        self._token = os.environ.get("SHEET_TOKEN", "")
        # follow_redirects обязателен: Apps Script отвечает 302 на googleusercontent.
        self._client = httpx.Client(timeout=30.0, follow_redirects=True)
        print("📊 Пишу в Google-таблицу через Apps Script Web App.")

    def append_listing(self, tab: str, *, date, category, price, link, snippet):
        """Добавляет одну строку-объявление в конец вкладки канала."""
        cat_name = ALL_CATEGORIES.get(category, category)
        price_str = "" if price is None else ("даром" if price == 0 else str(price))
        snippet = (snippet or "").replace("\n", " ").strip()[:120]
        payload = {
            "token": self._token,
            "tab": tab,
            "date": date.strftime("%Y-%m-%d %H:%M"),
            "category": cat_name,
            "price": price_str,
            "link": link,
            "snippet": snippet,
        }
        r = self._client.post(self._url, json=payload)
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"Apps Script вернул ошибку: {data}")
