"""
Запись в Google-таблицу через сервисный аккаунт.

Структура таблицы:
  - вкладка на каждый канал (создаётся автоматически при первом посте);
  - колонки: Дата | Категория | Цена (฿) | Ссылка | Краткое описание.
«Краткое описание» — первые слова поста для глазной проверки; личных данных
не выносим (имена/телефоны не собираем по правилу).

Доступ: сервисный аккаунт Google; таблица расшарена на его email (Editor).
"""
import os

import gspread
from google.oauth2.service_account import Credentials

from categories import ALL_CATEGORIES

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
_HEADER = ["Дата", "Категория", "Цена (฿)", "Ссылка", "Краткое описание"]


class Sheet:
    def __init__(self):
        creds = Credentials.from_service_account_file(
            os.environ["GOOGLE_CREDENTIALS_FILE"], scopes=_SCOPES
        )
        self._gc = gspread.authorize(creds)
        self._doc = self._gc.open_by_key(os.environ["SHEET_ID"])
        self._tabs = {}  # имя вкладки -> worksheet (кэш)

    def _worksheet(self, tab: str):
        if tab in self._tabs:
            return self._tabs[tab]
        try:
            ws = self._doc.worksheet(tab)
        except gspread.WorksheetNotFound:
            ws = self._doc.add_worksheet(title=tab, rows=1000, cols=len(_HEADER))
            ws.append_row(_HEADER, value_input_option="USER_ENTERED")
        self._tabs[tab] = ws
        return ws

    def append_listing(self, tab: str, *, date, category, price, link, snippet):
        """Добавляет одну строку-объявление в конец вкладки канала."""
        cat_name = ALL_CATEGORIES.get(category, category)
        price_str = "" if price is None else ("даром" if price == 0 else str(price))
        snippet = (snippet or "").replace("\n", " ").strip()[:120]
        row = [
            date.strftime("%Y-%m-%d %H:%M"),
            cat_name,
            price_str,
            link,
            snippet,
        ]
        self._worksheet(tab).append_row(row, value_input_option="USER_ENTERED")
