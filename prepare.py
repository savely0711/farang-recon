"""
Авто-подготовка объявлений из Telegram-групп для сайта.

РЕЖИМ «ВСЁ НА САЙТ» (с 15.10.2026, решение Савелия 14.10). Владельцы групп
разрешили переносить объявления, поэтому берём ВСЕ строки таблицы разведки с
ником, кроме авторов из «Отказ» (чёрный список) и «Зарегистрирован» (публикуют
сами), плюс предложения из таблицы «Фаранг — Недвижимость». Сайт получает флаг
`auto` и сам решает: чистое (ИИ «нормально») — сразу в ленту, сомнительное (нет
цены, нет фото, похожее у другого продавца, ИИ засомневался) — в ручную
очередь. Спрос («куплю/ищу») отсеивает ИИ при сборке карточки. Посты старше
PREPARE_MAX_AGE_DAYS (по умолчанию 14) не берём.

Строка с итогом «опубликовано» получает в колонке «На сайте» значение
«На сайте», ушедшая к человеку — «Ждёт модератора» с причиной в примечании.
Недвижимость из отдельной таблицы колонки «На сайте» не имеет — что уже
сделано, помнит файл realty_done.json рядом со скриптом.

Ниже — исходное описание этапа 4 (механика та же).

ЧТО ДЕЛАЕТ. Берёт из Google-таблицы строки, у которых «Присутствие» = «согласен»
и колонка «На сайте» ещё пуста, заново открывает исходный пост в Telegram,
собирает из него карточку (заголовок, описание, цена, фото) и отправляет на сайт
в ОЧЕРЕДЬ МОДЕРАЦИИ. В ленту само ничего не попадает: на сайте объявление ждёт,
пока человек нажмёт «Одобрить» в админке (вкладка «Авто-подготовленные»).

ПОЧЕМУ ЗАНОВО ОТКРЫВАЕМ ПОСТ. В таблице от объявления хранится только ссылка и
120 символов текста — ни полного описания, ни фотографий там нет и быть не
должно. Поэтому за содержимым идём в Telegram по ссылке из колонки «Ссылка».

ИТОГ КАЖДОЙ СТРОКИ пишется обратно в колонку «На сайте»:
  «Опубликовано» (зелёным) — ушло на сайт, ждёт модератора;
  «Не вышло» (красным)     — пост удалён, нет цены, нет фото, сбой сайта и т. п.
Помеченная строка в очередь больше не возвращается. Чтобы попробовать снова —
очистите ячейку в таблице.

ЗАЩИТА ОТ ДУБЛЕЙ ДВОЙНАЯ: пометка в таблице и уникальная ссылка на исходный
пост в базе сайта (db/32). Даже двойной запуск не создаст второе объявление.
Если объявление ещё ждёт модератора, повторная присылка ПЕРЕСОБЕРЁТ его —
так дозаполняются карточки, сделанные более старой версией разбора. Как только
человек его посмотрел (одобрил, снял, вернул на доработку), автоматика больше
не вмешивается.

Что заполняется в карточке, кроме текста и цены: подкатегория сайта, район
Паттайи и признаки раздела (спальни, площадь, пробег, коробка…). Справочник
для этого берётся С САЙТА (действие schema), а не хранится копией здесь —
иначе списки разъедутся при первом же изменении каталога.

ЗАПУСК (на сервере Aeza):
    python3 prepare.py        # обычный прогон
    python3 prepare.py dry    # показать, что бы сделал, ничего не меняя

Настройки (.env):
    SITE_API_URL          — адрес точки приёма сайта (…/api/recon)
    RECON_API_TOKEN       — общий пароль-токен с сайтом
    PREPARE_LIMIT         — сколько объявлений за один запуск (по умолчанию 30;
                            то же самое можно задать числом в аргументах:
                            python3 prepare.py 300)
    PREPARE_MAX_AGE_DAYS  — не трогать посты старше стольких дней (по умолч. 30)
    PREPARE_MAX_PHOTOS    — сколько фото брать из альбома (по умолчанию 6)
"""
import asyncio
import base64
import io
import os
import re
import sys

import httpx
from dotenv import load_dotenv
from telethon import TelegramClient  # noqa: F401
from tgclient import tg_client
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession

from build import build_listing
from phash import fingerprint
from sheets import SITE_LIVE, SITE_REVIEW, Sheet

import json
import time

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

MAX_AGE_DAYS = int(os.environ.get("PREPARE_MAX_AGE_DAYS", "14"))
MAX_PHOTOS = int(os.environ.get("PREPARE_MAX_PHOTOS", "6"))

# Аргументы командной строки — ради консоли сервера Aeza: там не вводятся
# заглавные буквы и «_», то есть строку PREPARE_LIMIT=300 руками не набрать.
# Поэтому понимаем простые слова и числа, в любом порядке:
#   python3 prepare.py            — как задано в .env (по умолчанию 30 штук)
#   python3 prepare.py 300        — разобрать до 300 объявлений за прогон
#   python3 prepare.py dry        — холостой ход, на сайт ничего не уходит
#   python3 prepare.py dry 50     — и то, и другое
_ARGS = [a.strip().lower() for a in sys.argv[1:]]
DRY = os.environ.get("PREPARE_DRY") == "1" or "dry" in _ARGS
LIMIT = int(os.environ.get("PREPARE_LIMIT", "150"))  # 15.10: 3 прогона в день по 150
for _a in _ARGS:
    if _a.isdigit() and int(_a) > 0:
        LIMIT = int(_a)
    # «d14» — брать посты не старше 14 дней (без заглавных и «_», для консоли)
    if _a.startswith("d") and _a[1:].isdigit() and int(_a[1:]) > 0:
        MAX_AGE_DAYS = int(_a[1:])
# «norealty» — не трогать таблицу недвижимости в этом прогоне
WITH_REALTY = "norealty" not in _ARGS

REALTY_DONE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "realty_done.json")

DELAY_BETWEEN_POSTS = 3.0   # сек: читаем не спеша, как человек
PHOTO_MAX_SIDE = 1600       # px: больше на карточке всё равно не нужно
PHOTO_QUALITY = 82
ALBUM_WINDOW = 10           # на сколько сообщений вокруг искать соседей альбома

LINK_RE = re.compile(r"^https://t\.me/([A-Za-z0-9_]+)/(\d+)/?$")


# ─────────────────────────── ФОТО ───────────────────────────
def _shrink(raw: bytes) -> tuple[bytes, str] | None:
    """Уменьшает снимок до разумного размера. Pillow нет — отдаём как есть
    (при условии, что файл не великан: у Vercel потолок тела запроса 4,5 МБ)."""
    try:
        from PIL import Image  # noqa: PLC0415 — необязательная зависимость
    except ImportError:
        return (raw, "jpg") if len(raw) <= 3_000_000 else None

    try:
        img = Image.open(io.BytesIO(raw))
        img = img.convert("RGB")
        img.thumbnail((PHOTO_MAX_SIDE, PHOTO_MAX_SIDE))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=PHOTO_QUALITY, optimize=True)
        return buf.getvalue(), "jpg"
    except Exception:  # noqa: BLE001
        return (raw, "jpg") if len(raw) <= 3_000_000 else None


async def _collect_photos(client, entity, msg) -> list[dict]:
    """Все снимки поста. Если пост — часть альбома, добираем соседние
    сообщения с тем же grouped_id (Telegram шлёт альбом отдельными записями)."""
    messages = [msg]
    if getattr(msg, "grouped_id", None):
        lo = max(1, msg.id - ALBUM_WINDOW)
        ids = list(range(lo, msg.id + ALBUM_WINDOW + 1))
        try:
            around = await client.get_messages(entity, ids=ids)
        except Exception:  # noqa: BLE001
            around = []
        messages = [
            m for m in around
            if m and getattr(m, "grouped_id", None) == msg.grouped_id
        ] or [msg]
        messages.sort(key=lambda m: m.id)

    out: list[dict] = []
    for m in messages:
        if len(out) >= MAX_PHOTOS:
            break
        if not getattr(m, "photo", None):
            continue
        try:
            raw = await asyncio.wait_for(client.download_media(m, file=bytes), timeout=60)
        except Exception as e:  # noqa: BLE001
            print(f"    ⚠ снимок не скачался: {e}")
            continue
        if not raw:
            continue
        small = _shrink(raw)
        if not small:
            continue
        data, ext = small
        # Отпечаток картинки — для поиска дублей на сайте (db/33). Считаем
        # здесь: снимок уже в руках, а сайту разбирать JPEG нечем.
        out.append({
            "data": base64.b64encode(data).decode("ascii"),
            "ext": ext,
            "phash": fingerprint(data),
        })
    return out


# ─────────────────────────── САЙТ ───────────────────────────
class Site:
    """Точка приёма сайта (/api/recon). Ошибки наружу не бросает."""

    def __init__(self):
        self.url = os.environ.get("SITE_API_URL", "").strip()
        self.token = os.environ.get("RECON_API_TOKEN", "").strip()
        self._client = httpx.Client(timeout=120.0, follow_redirects=True)

    @property
    def ready(self) -> bool:
        return bool(self.url and self.token)

    def send(self, payload: dict) -> dict:
        body = {"token": self.token, "action": "listing", **payload}
        try:
            r = self._client.post(self.url, json=body)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"сайт не ответил: {e}"}

    def schema(self) -> dict:
        """Справочник сайта: подкатегории, районы, признаки разделов.

        Держим его НА САЙТЕ, а не копией здесь: заведут новую подкатегорию или
        признак — ИИ узнает о нём со следующего прогона сам. Не отдался —
        работаем без него (карточка соберётся, просто без признаков)."""
        try:
            r = self._client.post(self.url, json={"token": self.token,
                                                  "action": "schema"})
            r.raise_for_status()
            data = r.json()
            if not data.get("ok"):
                raise RuntimeError(data)
            return data
        except Exception as e:  # noqa: BLE001
            print(f"⚠ справочник сайта не получен ({e}) — "
                  f"признаки и район заполнены не будут.")
            return {}


# ─────────────────────────── ПРОГОН ───────────────────────────
class RealtyMarks:
    """Итоги по объявлениям из таблицы недвижимости — у неё нет колонки
    «На сайте», поэтому помним сами, в файле. Интерфейс как у Sheet."""

    def __init__(self):
        try:
            with open(REALTY_DONE, encoding="utf-8") as f:
                self.done = json.load(f)
        except Exception:  # noqa: BLE001
            self.done = {}

    def has(self, link: str) -> bool:
        return link in self.done

    def _save(self):
        tmp = REALTY_DONE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.done, f, ensure_ascii=False)
        os.replace(tmp, REALTY_DONE)

    def set_site_result(self, link, value, note=""):
        self.done[link] = {"v": value, "note": note, "t": int(time.time())}
        self._save()
        return True

    def set_site_fail(self, link, reason):
        return self.set_site_result(link, "", reason)


async def process_row(client, site, sheet, row: dict, stats: dict,
                      schema: dict) -> None:
    link = row.get("link") or ""
    nick = row.get("nick") or ""
    m = LINK_RE.match(link)
    if not m:
        print(f"  ⚠ странная ссылка, пропускаю: {link}")
        return
    channel, msg_id = m.group(1), int(m.group(2))
    print(f"\n  📄 @{nick} · {link}")

    def fail(reason: str) -> None:
        """Не получилось. Ячейка «На сайте» остаётся ПУСТОЙ, причина уходит в
        примечание к ней (статуса «Не вышло» больше нет — решение Савелия
        01.09.2026). Строка с примечанием в очередь больше не попадает, поэтому
        мы не тратим деньги ИИ на один и тот же битый пост каждую ночь."""
        stats["fail"] += 1
        print(f"    ⛔ {reason}")
        if not DRY:
            sheet.set_site_fail(link, reason)

    try:
        entity = await client.get_entity(channel)
        msg = await client.get_messages(entity, ids=msg_id)
    except Exception as e:  # noqa: BLE001
        return fail(f"пост не открылся: {e}")
    if not msg:
        return fail("пост удалён или недоступен")

    text = msg.message or ""
    if not text.strip():
        return fail("в посте нет текста")

    card = build_listing(text, schema, allow_no_price=True)
    if not card["ok"]:
        return fail(card["reason"])

    # Без фото больше не бросаем: сайт положит такое в ручную очередь.
    photos = await _collect_photos(client, entity, msg)

    price = (
        "даром" if card["is_free"]
        else "договорная" if card["is_negotiable"]
        else f"{card['price_thb']} ฿" if card["price_thb"]
        else "без цены"
    )
    what = card.get("subcategory") or card["category"]
    where = f" · {card['district']}" if card.get("district") else ""
    attrs = card.get("attrs") or {}
    marks = f" · признаков: {len(attrs)}" if attrs else ""
    print(f"    «{card['title']}» · {what}{where} · {price} · "
          f"фото: {len(photos)}{marks}")

    if DRY:
        stats["dry"] += 1
        return

    res = site.send({
        "source_url": link,
        "author_username": nick,
        "title": card["title"],
        "description": card["description"],
        "price_thb": card["price_thb"],
        "is_free": card["is_free"],
        "is_negotiable": card["is_negotiable"],
        "category_slug": card["category"],
        "subcategory_slug": card.get("subcategory"),
        "district_slug": card.get("district"),
        "attrs": attrs,
        "photos": photos,
        "auto": True,
    })

    if not res.get("ok"):
        return fail(f"сайт отказал: {res.get('error')}")
    if res.get("skipped") == "registered":
        stats["registered"] += 1
        print("    👤 автор зарегистрирован на сайте сам — не публикуем")
        sheet.set_site_fail(link, "автор зарегистрирован на сайте — публикует сам")
        return
    if res.get("duplicate"):
        stats["dup"] += 1
        print("    ↩ этот товар этого автора уже на сайте — вторую карточку не завожу")
        sheet.set_site_fail(link, "повтор: этот товар автора уже на сайте")
        return
    if res.get("verdict") == "reject":
        stats["rejected"] += 1
        print("    🚫 ИИ-модерация сайта отклонила — помечаю причину в примечании")
        sheet.set_site_fail(link, "ИИ-модерация сайта отклонила")
        return
    if res.get("verdict") == "published":
        stats["ok"] += 1
        print("    ✅ опубликовано, уже в ленте")
        sheet.set_site_result(link, SITE_LIVE)
        return

    stats["review"] += 1
    why = res.get("reason") or "проверить вручную"
    print(f"    🕓 в ручную очередь: {why}")
    sheet.set_site_result(link, SITE_REVIEW, why)


def _single_run_lock():
    """Не даём двум прогонам идти одновременно: длинная выкладка (сотни
    постов) может не успеть до следующего запуска по расписанию."""
    import fcntl
    f = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          ".prepare.lock"), "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return None
    return f


async def main() -> int:
    lock = _single_run_lock()
    if lock is None:
        print("⏳ предыдущий прогон ещё идёт — этот пропускаю.")
        return 0
    sheet = Sheet()
    site = Site()
    if not DRY and not site.ready:
        print("⛔ не заданы SITE_API_URL и/или RECON_API_TOKEN в .env — стоп.")
        return 1
    if DRY:
        print("🧪 ТЕСТОВЫЙ РЕЖИМ (dry): на сайт не шлю, таблицу не правлю.")

    rows = sheet.read_todo(limit=LIMIT, days=MAX_AGE_DAYS)
    if rows is None:
        print("⛔ очередь из таблицы прочитать не удалось — стоп (ничего не делаю).")
        return 1
    jobs = [(r, sheet) for r in rows]

    # Недвижимость из отдельной таблицы (агентства). Чёрный список общий —
    # реестр основной таблицы: «отказ» и «зарегистрирован» не публикуем.
    realty_n = 0
    if WITH_REALTY and len(jobs) < LIMIT and os.environ.get("REALTY_SHEET_WEBHOOK_URL"):
        try:
            from realty_sheets import RealtySheet
            rrows = RealtySheet().read_todo(days=MAX_AGE_DAYS)
        except Exception as e:  # noqa: BLE001
            print(f"⚠ таблица недвижимости недоступна: {e}")
            rrows = None
        consents = sheet.read_consents()
        if rrows and consents is None:
            print("⚠ реестр отказов не прочитался — недвижимость в этот раз пропускаю")
            rrows = None
        if rrows:
            marks = RealtyMarks()
            seen = {r.get("link") for r in rows}
            for r in rrows:
                nick = (r.get("nick") or "").lower()
                link = r.get("link") or ""
                if not nick or not link or link in seen or marks.has(link):
                    continue
                if consents.get(nick) in ("отказ", "зарегистрирован"):
                    continue
                jobs.append((r, marks))
                realty_n += 1
                if len(jobs) >= LIMIT:
                    break

    if not jobs:
        print("✅ очередь пуста: всё уже разобрано.")
        return 0

    print(f"📋 в очереди {len(jobs)} объявлений, из них недвижимость агентств: "
          f"{realty_n} (потолок {LIMIT}, не старше {MAX_AGE_DAYS} дн.)")

    stats = {"ok": 0, "review": 0, "fail": 0, "dup": 0, "rejected": 0,
             "registered": 0, "dry": 0}
    schema = site.schema() if site.ready else {}
    if schema:
        print(f"📚 справочник сайта получен: подкатегорий "
              f"{len(schema.get('subcategories') or [])}, районов "
              f"{len(schema.get('districts') or [])}")

    api_id = int(os.environ["TG_API_ID"])
    api_hash = os.environ["TG_API_HASH"]
    session = StringSession(os.environ["TG_SESSION"])

    async with tg_client(session, api_id, api_hash) as client:
        me = await client.get_me()
        print(f"🔑 вошёл как {me.first_name} (id {me.id})")
        for i, (row, target) in enumerate(jobs):
            try:
                await process_row(client, site, target, row, stats, schema)
            except FloodWaitError as e:
                print(f"  ⏳ Telegram просит подождать {e.seconds}с — стоп на сегодня")
                break
            except Exception as e:  # noqa: BLE001
                print(f"  ⚠ строка прервалась: {e} — иду дальше")
            if i < len(jobs) - 1:
                await asyncio.sleep(DELAY_BETWEEN_POSTS)

    print(f"\n🏁 Готово. Сразу в ленте: {stats['ok']}; в ручной очереди: "
          f"{stats['review']}; отсеяно (не объявление/спрос/сбой): {stats['fail']}; "
          f"повторы: {stats['dup']}; сняты ИИ: {stats['rejected']}; "
          f"зарегистрированы сами: {stats['registered']}"
          + (f"; в тестовом режиме собрано: {stats['dry']}" if DRY else ""))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
