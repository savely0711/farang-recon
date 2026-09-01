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
           Присутствие | На сайте
Колонки «Тип продавца» больше нет (убрана 01.09.2026): агентствами занимается
отдельный контур недвижимости со своей таблицей. Передавать seller_type всё
равно нужно — по нему скрипт выбирает вкладку «Недвижимость — агентства».
«Ник» — юзернейм автора поста (чтобы писать напрямую); других данных о
пользователе не выносим (правило 3). «Описание» — первые слова поста для глаз.

Кто какой колонкой управляет:
  «Написали?»   — рассылка «первое касание»; с 01.09.2026 она остановлена,
                  колонка осталась как история;
  «Присутствие» — воронка продавца И вкладка, на которой живёт строка;
                  ставят сайт и Савелий руками;
  «На сайте»    — состояние объявления на сайте: «На сайте» / «Ждёт модератора» /
                  «Снято». Пусто = ещё не пробовали; пусто с примечанием =
                  пробовали и не вышло (см. set_site_fail).
ВКЛАДКИ (с 01.09.2026 их несколько, раскладывает скрипт таблицы сам):
  «Новые» / «Согласен» / «Отказ» / «Зарегистрирован» — воронка по колонке
  «Присутствие»; строка ПЕРЕЕЗЖАЕТ, как только статус меняется. Плюс две
  вкладки без переездов: «Без ника» (у поста скрыт автор — писать некому) и
  «Недвижимость — агентства» (бизнес + категория realty). Здесь про это знать
  не нужно: достаточно передать slug категории, ник и тип продавца.

Связка с авто-рассылкой (outreach.py). Сама рассылка ОСТАНОВЛЕНА 01.09.2026
(решение Савелия), но методы оставлены — колонка «Написали?» живёт как история:
  - read_statuses() — карта {ник: статус «Написали?»} (кому уже написали);
  - mark_written(author, value) — ставит автору статус в «Написали?» СРАЗУ ВО
    ВСЕХ его строках («Да» после отправки, «Премиум» или «Не доставлено» —
    если письмо не ушло);
  - set_presence(author, value) — задел под этапы 3–4 (сайт сообщает «согласен»
    / «зарегистрирован»); рассылка этим методом не пользуется;
  - read_todo() / set_site_result(link, value) / set_site_fail(link, reason) —
    ОЧЕРЕДЬ АВТО-ПОДГОТОВКИ: какие объявления согласившихся ещё не выложены на
    сайт и чем закончилась попытка. Колонка «На сайте»;
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

# Значения колонки «На сайте». Держим здесь, чтобы не расходились
# с apps_script.gs — там ровно те же три строки.
#
# С 01.09.2026 их ровно ТРИ (решение Савелия — упростить таблицу):
#   «Удалено» слито со «Снято» (человеку важно одно: на сайте этого нет),
#   «Не вышло» упразднено — вместо него ПУСТАЯ ячейка, а причина уходит
#   в примечание к ячейке (set_site_fail). Пустая ячейка без примечания
#   означает «ещё не пробовали», с примечанием — «пробовали, не вышло»;
#   очередь авто-подготовки берёт только первые.
SITE_LIVE = "На сайте"           # ночная сверка: одобрено, люди его видят
SITE_REVIEW = "Ждёт модератора"  # ушло на сайт и лежит в очереди на проверку
SITE_OFF = "Снято"               # снято/удалено — на сайте его нет

# Старые имена: оставлены, чтобы не ломать чужие импорты. Скрипт таблицы
# переводит эти значения в новые сам.
SITE_CATALOG = SITE_LIVE
SITE_GONE = SITE_OFF

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

    def set_site_result(self, link: str, value: str, note: str = "") -> bool:
        """Пишет РЕЗУЛЬТАТ авто-подготовки в колонку «На сайте» у одной строки
        (ключ — ссылка на пост). Значения: SITE_REVIEW «Ждёт модератора»
        (объявление ушло на сайт и ждёт человека), SITE_LIVE «На сайте»,
        SITE_OFF «Снято». Пустая строка снимает пометку и возвращает
        объявление в очередь — если только не передан `note` (см. ниже).

        Помеченные строки в очередь `read_todo()` больше не попадают — это и
        есть защита от повторной публикации на стороне таблицы (вторая, кроме
        уникальной ссылки в базе сайта)."""
        payload = {"token": self._token, "action": "site",
                   "link": link, "value": value, "note": note}
        return self._post_retry(payload, note=f"«{value or 'пусто'}» для {link}")

    def set_site_fail(self, link: str, reason: str) -> bool:
        """НЕ ПОЛУЧИЛОСЬ выложить объявление: ячейка «На сайте» остаётся ПУСТОЙ,
        а причина уходит в примечание к ней.

        Почему не отдельный статус (было «Не вышло»). Савелий 01.09.2026 попросил
        убрать этот статус из таблицы — глазами он ничего не даёт, только пестрит.
        Но и совсем без пометки нельзя: пустая ячейка означает «ещё не пробовали»,
        и следующий же прогон снова потратил бы деньги ИИ на пост, у которого,
        например, нет фотографий. Примечание решает обе задачи: поле выглядит
        пустым, причину видно при наведении, а очередь такую строку пропускает.
        Вернуть объявление в очередь — меню «Фаранг» → «Очистить пометки неудач»."""
        return self.set_site_result(link, "", note=reason or "не удалось выложить")

    def mark_no_site(self, link: str, value: str = "") -> bool:
        """Старое имя `set_site_result` — оставлено, чтобы не ломать вызовы."""
        return self.set_site_result(link, value)

    def read_placed(self):
        """РАЗМЕЩЁННЫЕ ОБЪЯВЛЕНИЯ для ночной сверки: строки, у которых колонка
        «На сайте» заполнена (пустые пропускаем — за ними объявления нет).
        Снятое проверяем тоже: модератор может вернуть его в каталог.

        Возвращает список словарей {"link", "site"}; None — не удалось."""
        return self._get_list("placed", "rows", "список размещённых")

    def read_nicks(self):
        """Все ники таблицы без повторов — чтобы спросить у сайта, кто из них
        уже зарегистрировался. None — не удалось."""
        return self._get_list("nicks", "nicks", "список ников")

    def _get_list(self, action: str, field: str, note: str):
        params = {"action": action, "token": self._token}
        for attempt in range(MAX_RETRIES):
            try:
                r = self._client.get(self._url, params=params)
                r.raise_for_status()
                data = r.json()
                if not data.get("ok"):
                    raise RuntimeError(f"Apps Script вернул ошибку: {data}")
                return data.get(field) or []
            except Exception as e:  # noqa: BLE001
                print(f"  ⚠ {note} не получен "
                      f"(попытка {attempt + 1}/{MAX_RETRIES}): {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)])
        return None

    def set_site_bulk(self, rows: list) -> int:
        """Пишет колонку «На сайте» ПАЧКОЙ: [{"link", "value"}, …].
        Возвращает число реально изменённых строк (0 — либо нечего менять,
        либо не удалось)."""
        if not rows:
            return 0
        payload = {"token": self._token, "action": "sitebulk", "rows": rows}
        data = self._post_json(payload, note=f"состояния {len(rows)} строк")
        return int((data or {}).get("updated") or 0)

    def set_consent_bulk(self, rows: list) -> int:
        """Пишет пачку событий в реестр согласий: [{"nick","status","reason"}].
        Возвращает число изменённых записей."""
        if not rows:
            return 0
        payload = {"token": self._token, "action": "consentbulk", "rows": rows}
        data = self._post_json(payload, note=f"согласия {len(rows)} человек")
        return int((data or {}).get("changed") or 0)

    def _post_json(self, payload: dict, note: str):
        """POST с повторами, который отдаёт ОТВЕТ (а не только True/False)."""
        for attempt in range(MAX_RETRIES):
            try:
                r = self._client.post(self._url, json=payload)
                r.raise_for_status()
                data = r.json()
                if not data.get("ok"):
                    raise RuntimeError(f"Apps Script вернул ошибку: {data}")
                return data
            except Exception as e:  # noqa: BLE001
                print(f"  ⚠ не записалось ({note}, "
                      f"попытка {attempt + 1}/{MAX_RETRIES}): {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)])
        return None

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
