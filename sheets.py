"""
Запись в Google-таблицу через Apps Script Web App (режим CRM).

Почему так (а не сервисный аккаунт): на наш сервер тяжело завезти большой
JSON-ключ (консоль Aeza ломает крупную вставку, а репозиторий публичный — секрет
туда класть нельзя). Поэтому к самой таблице привязан маленький скрипт-приёмник
(Apps Script), развёрнутый как веб-приложение. Парсер шлёт ему объявления
обычным POST-запросом. На сервере нужны только две короткие строки в .env:
адрес скрипта (SHEET_WEBHOOK_URL) и общий пароль-токен (SHEET_TOKEN).

CRM: все авторы со всех каналов сводятся в ОДНУ вкладку «CRM» (её создаёт сам
скрипт). Дедуп по нику делает скрипт таблицы — один ник = одна строка навсегда;
существующая строка (и её «Написали?») при этом не перетирается.
  Колонки: Ник | Ссылка | Канал | Категория | Дата | Описание | Написали?
«Ник» — юзернейм автора поста (чтобы писать напрямую); других данных о
пользователе не выносим (правило 3). «Описание» — первые слова поста для глаз.

Связка с авто-рассылкой (outreach.py):
  - read_statuses() — карта {ник: "Да"|"Нет"} по всей CRM (кому уже написали);
  - mark_written(author) — ставит автору «Написали?»=Да после отправки.

ВАЖНО (надёжность): пишем ПАЧКАМИ и переживаем временные сбои Google — повторяем
несколько раз, и если не вышло, НЕ роняем прогон, а сообщаем наверх.
"""
import os
import time

import httpx

from categories import ALL_CATEGORIES

CRM_TAB = "CRM"

# Сколько раз пробуем записать одну пачку, прежде чем сдаться (с паузами между).
MAX_RETRIES = 3
RETRY_BACKOFF = [3, 8, 20]  # секунды паузы перед повторами 2 и 3


class Sheet:
    def __init__(self):
        self._url = os.environ["SHEET_WEBHOOK_URL"]
        self._token = os.environ.get("SHEET_TOKEN", "")
        # follow_redirects обязателен: Apps Script отвечает 302 на googleusercontent.
        self._client = httpx.Client(timeout=60.0, follow_redirects=True)
        print("📊 Пишу в Google-таблицу CRM через Apps Script Web App (пачками).")

    @staticmethod
    def _row(listing: dict) -> dict:
        """Готовит «сырое» объявление к записи в CRM (порядок колонок задаёт скрипт)."""
        cat_name = ALL_CATEGORIES.get(listing["category"], listing["category"])
        snippet = (listing["snippet"] or "").replace("\n", " ").strip()[:120]
        author = listing.get("author") or ""
        return {
            "author": author,                 # ник автора (без @); пусто, если ника нет
            "link": listing["link"],
            "channel": listing.get("channel") or "",
            "category": cat_name,
            "date": listing["date"].strftime("%Y-%m-%d %H:%M"),
            "snippet": snippet,
        }

    def flush(self, listings: list) -> bool:
        """Отправляет ПАЧКУ авторов в CRM одним запросом (канал — колонкой у каждой
        строки). Дубли по нику отсекает скрипт таблицы. Возвращает True при успехе;
        False — если Google так и не принял после повторов (наружу не бросаем)."""
        if not listings:
            return True
        payload = {
            "token": self._token,
            "action": "append",
            "rows": [self._row(l) for l in listings],
        }
        return self._post_retry(payload, note=f"пачка ({len(listings)} стр.)")

    def read_statuses(self):
        """Карта {ник(нижний, без @): "Да"|"Нет"} по всей CRM.
        Возвращает dict при успехе (в т.ч. пустой {} для пустой таблицы) и None,
        если прочитать так и не удалось — наверху None означает «статус неизвестен,
        ради безопасности запуск отправки лучше пропустить»."""
        params = {"action": "statuses", "token": self._token}
        for attempt in range(MAX_RETRIES):
            try:
                r = self._client.get(self._url, params=params)
                r.raise_for_status()
                data = r.json()
                if not data.get("ok"):
                    raise RuntimeError(f"Apps Script вернул ошибку: {data}")
                return data.get("statuses", {}) or {}
            except Exception as e:  # noqa: BLE001
                print(f"  ⚠ чтение статусов не удалось "
                      f"(попытка {attempt + 1}/{MAX_RETRIES}): {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)])
        return None

    def mark_written(self, author: str) -> bool:
        """Ставит автору «Написали?»=Да в CRM. True при успехе."""
        payload = {"token": self._token, "action": "mark", "author": author}
        return self._post_retry(payload, note=f"пометка @{author}=Да")

    def _post_retry(self, payload: dict, note: str) -> bool:
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
                print(f"  ⚠ {note} не удалась "
                      f"(попытка {attempt + 1}/{MAX_RETRIES}): {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)])
        print(f"  ⛔ {note} не удалась — пропускаю на этот раз: {last_err}")
        return False
