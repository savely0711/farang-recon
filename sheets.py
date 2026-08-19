"""
Запись в Google-таблицу через Apps Script Web App (режим CRM).

Почему так (а не сервисный аккаунт): на наш сервер тяжело завезти большой
JSON-ключ (консоль Aeza ломает крупную вставку, а репозиторий публичный — секрет
туда класть нельзя). Поэтому к самой таблице привязан маленький скрипт-приёмник
(Apps Script), развёрнутый как веб-приложение. Парсер шлёт ему объявления
обычным POST-запросом. На сервере нужны только две короткие строки в .env:
адрес скрипта (SHEET_WEBHOOK_URL) и общий пароль-токен (SHEET_TOKEN).

Мини-CRM «Присутствие» (с 17.08.2026): СТРОКА = ОБЪЯВЛЕНИЕ, а не человек.
Дедуп делает скрипт таблицы по ССЫЛКЕ на пост (одна ссылка = одна строка);
повторную публикацию того же текста отсеивает раньше сам парсер (dedup.py).
Объявления без ника тоже записываем — как рыночные данные; писать им некому.
  Колонки: Ник | Ссылка | Канал | Категория | Дата | Описание | Написали? |
           Присутствие | Нет на сайте | Тип продавца
«Ник» — юзернейм автора поста (чтобы писать напрямую); других данных о
пользователе не выносим (правило 3). «Описание» — первые слова поста для глаз.

Кто какой колонкой управляет (решение Савелия 16.08.2026):
  «Написали?»   — только бот-рассыльщик, он же по ней решает, писать или нет;
  «Присутствие» — воронка продавца; бот её НЕ читает и НЕ трогает (её ставит
                  сайт на этапах 3–4 плана и Савелий руками);
  «Нет на сайте», «Тип продавца» — см. план мини-CRM.
Объявления бизнеса в категории «недвижимость» скрипт сам кладёт на отдельную
вкладку «Недвижимость — агентства» — здесь про это знать не нужно, достаточно
передать slug категории и тип продавца.

Связка с авто-рассылкой (outreach.py) — не изменилась:
  - read_statuses() — карта {ник: статус «Написали?»} (кому уже написали);
  - mark_written(author, value) — ставит автору статус в «Написали?» СРАЗУ ВО
    ВСЕХ его строках («Да» после отправки, «Премиум» или «Не доставлено» —
    если письмо не ушло);
  - set_presence(author, value) — задел под этапы 3–4 (сайт сообщает «согласен»
    / «зарегистрирован»); рассылка этим методом не пользуется;
  - read_todo() / set_site_result(link, value) — ОЧЕРЕДЬ АВТО-ПОДГОТОВКИ
    (этап 4): какие объявления согласившихся ещё не выложены на сайт и чем
    закончилась попытка. Колонка «На сайте»;
  - set_consent(nick, status, reason) / read_consents() — РЕЕСТР СОГЛАСИЙ
    (вкладка «Согласия», этап 3): одна строка на человека, единственный
    источник правды о согласии. Пополняет его сайт; разведке нужен только для
    проверок. Статусы по силе: отказ > зарегистрирован > согласен.

ВАЖНО (надёжность): пишем ПАЧКАМИ и переживаем временные сбои Google — повторяем
несколько раз, и если не вышло, НЕ роняем прогон, а сообщаем наверх.
"""
import os
import time

import httpx

from categories import ALL_CATEGORIES

CRM_TAB = "CRM"

# Значения колонки «На сайте» (этап 4). Держим здесь, чтобы не расходились
# с apps_script.gs — там ровно те же две строки.
SITE_OK = "Опубликовано"
SITE_FAIL = "Не вышло"

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
        """Готовит «сырое» объявление к записи в CRM (порядок колонок задаёт скрипт).
        category_slug и seller_type нужны скрипту, чтобы выбрать вкладку:
        бизнес + недвижимость → «Недвижимость — агентства»."""
        slug = listing["category"]
        cat_name = ALL_CATEGORIES.get(slug, slug)
        snippet = (listing["snippet"] or "").replace("\n", " ").strip()[:120]
        author = listing.get("author") or ""
        return {
            "author": author,                 # ник автора (без @); пусто, если ника нет
            "link": listing["link"],
            "channel": listing.get("channel") or "",
            "category": cat_name,
            "category_slug": slug,
            "date": listing["date"].strftime("%Y-%m-%d %H:%M"),
            "snippet": snippet,
            "seller_type": listing.get("seller_type") or "",
        }

    def flush(self, listings: list) -> bool:
        """Отправляет ПАЧКУ объявлений одним запросом (канал — колонкой у каждой
        строки). Дубли по ссылке отсекает скрипт таблицы, он же раскладывает
        строки по вкладкам. Возвращает True при успехе; False — если Google так
        и не принял после повторов (наружу не бросаем)."""
        if not listings:
            return True
        payload = {
            "token": self._token,
            "action": "append",
            "rows": [self._row(l) for l in listings],
        }
        return self._post_retry(payload, note=f"пачка ({len(listings)} стр.)")

    def read_statuses(self):
        """Карта {ник(нижний, без @): "Да"|"Нет"|"Премиум"|"Не доставлено"} по
        обеим вкладкам. У человека теперь много строк — скрипт отдаёт «сильный»
        статус (любой, кроме «Нет»), чтобы написанный однажды человек не вернулся
        в очередь на второе письмо.
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

    def mark_written(self, author: str, value: str = "Да") -> bool:
        """Ставит автору статус в колонке «Написали?»: «Да» (написали),
        «Премиум» (пишут только Premium — Савелий напишет сам) или
        «Не доставлено». Проставляется СРАЗУ ВО ВСЕХ строках этого ника
        (у человека их теперь много). True при успехе."""
        payload = {"token": self._token, "action": "mark",
                   "author": author, "value": value}
        return self._post_retry(payload, note=f"пометка @{author}={value}")

    def set_presence(self, author: str, value: str) -> bool:
        """Ставит автору статус воронки в колонке «Присутствие» во всех его
        строках: «нет ответа», «согласен», «зарегистрирован», «отказ»
        (пустая строка — очистить).

        ЗАДЕЛ ПОД ЭТАПЫ 3–4 плана мини-CRM: этим методом пользуется сайт, когда
        публикует объявление «за автора» или когда автор входит через Telegram.
        Бот-рассыльщик «Присутствие» НЕ трогает — у него своя колонка
        «Написали?» (решение Савелия 16.08.2026)."""
        payload = {"token": self._token, "action": "presence",
                   "author": author, "value": value}
        return self._post_retry(payload, note=f"присутствие @{author}={value}")

    def set_consent(self, nick: str, status: str, reason: str = "") -> bool:
        """Пишет событие в РЕЕСТР СОГЛАСИЙ (вкладка «Согласия») и заодно
        проставляет «Присутствие» во всех строках этого ника.

        Статусы: «согласен» (мы опубликовали его объявление), «зарегистрирован»
        (завёл аккаунт на сайте), «отказ». Слабый статус не перезаписывает
        сильный — отказ, поставленный руками, автоматика не снимет.

        Этим пользуется САЙТ (этап 3 плана мини-CRM). Разведке метод нужен
        только для проверок и разовых заливок."""
        payload = {"token": self._token, "action": "consent",
                   "nick": nick, "status": status, "reason": reason}
        return self._post_retry(payload, note=f"согласие @{nick}={status}")

    def read_consents(self):
        """Реестр согласий целиком: {ник(нижний, без @): статус}.
        None — если прочитать так и не удалось."""
        params = {"action": "consents", "token": self._token}
        for attempt in range(MAX_RETRIES):
            try:
                r = self._client.get(self._url, params=params)
                r.raise_for_status()
                data = r.json()
                if not data.get("ok"):
                    raise RuntimeError(f"Apps Script вернул ошибку: {data}")
                return data.get("consents", {}) or {}
            except Exception as e:  # noqa: BLE001
                print(f"  ⚠ чтение реестра согласий не удалось "
                      f"(попытка {attempt + 1}/{MAX_RETRIES}): {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)])
        return None

    def set_site_result(self, link: str, value: str) -> bool:
        """Пишет РЕЗУЛЬТАТ авто-подготовки в колонку «На сайте» у одной строки
        (ключ — ссылка на пост). Значения: SITE_OK «Опубликовано» (зелёным,
        объявление ушло на сайт и ждёт модератора), SITE_FAIL «Не вышло»
        (красным), пустая строка — снять пометку и вернуть объявление в очередь.

        Помеченные строки в очередь `read_todo()` больше не попадают — это и
        есть защита от повторной публикации на стороне таблицы (вторая, кроме
        уникальной ссылки в базе сайта)."""
        payload = {"token": self._token, "action": "site",
                   "link": link, "value": value}
        return self._post_retry(payload, note=f"«{value}» для {link}")

    def mark_no_site(self, link: str, value: str = SITE_FAIL) -> bool:
        """Старое имя `set_site_result` — оставлено, чтобы не ломать вызовы."""
        return self.set_site_result(link, value)

    def read_todo(self, limit: int = 50, days: int = 0):
        """ОЧЕРЕДЬ АВТО-ПОДГОТОВКИ (этап 4): объявления людей со статусом
        «согласен», которые мы ещё не пробовали выложить на сайт.

        Возвращает список словарей {"nick", "link", "time"} от свежих к старым
        (`time` — метка времени поста в миллисекундах, 0 если дату не разобрать).
        `days` > 0 отсекает посты старше указанного числа дней — старое чаще
        всего уже продано, публиковать его вредно.
        None — если прочитать так и не удалось."""
        params = {"action": "todo", "token": self._token,
                  "limit": str(int(limit)), "days": str(int(days))}
        for attempt in range(MAX_RETRIES):
            try:
                r = self._client.get(self._url, params=params)
                r.raise_for_status()
                data = r.json()
                if not data.get("ok"):
                    raise RuntimeError(f"Apps Script вернул ошибку: {data}")
                return data.get("rows", []) or []
            except Exception as e:  # noqa: BLE001
                print(f"  ⚠ чтение очереди авто-подготовки не удалось "
                      f"(попытка {attempt + 1}/{MAX_RETRIES}): {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)])
        return None

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
