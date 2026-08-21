"""
Авто-подготовка объявлений «согласных» продавцов (этап 4 мини-CRM «Присутствие»).

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
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession

from build import build_listing
from phash import fingerprint
from sheets import SITE_FAIL, SITE_REVIEW, Sheet

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

MAX_AGE_DAYS = int(os.environ.get("PREPARE_MAX_AGE_DAYS", "30"))
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
LIMIT = int(os.environ.get("PREPARE_LIMIT", "30"))
for _a in _ARGS:
    if _a.isdigit() and int(_a) > 0:
        LIMIT = int(_a)

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
            raw = await client.download_media(m, file=bytes)
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
        stats["fail"] += 1
        print(f"    ⛔ {reason}")
        if not DRY:
            sheet.set_site_result(link, SITE_FAIL)

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

    card = build_listing(text, schema)
    if not card["ok"]:
        return fail(card["reason"])

    photos = await _collect_photos(client, entity, msg)
    if not photos:
        return fail("нет фотографий")

    price = (
        "даром" if card["is_free"]
        else "договорная" if card["is_negotiable"]
        else f"{card['price_thb']} ฿"
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
    })

    if not res.get("ok"):
        return fail(f"сайт отказал: {res.get('error')}")
    if res.get("duplicate"):
        stats["dup"] += 1
        print("    ↩ модератор его уже смотрел — не трогаю, помечаю строку")
        sheet.set_site_result(link, SITE_REVIEW)
        return
    if res.get("verdict") == "reject":
        stats["rejected"] += 1
        print("    🚫 ИИ-модерация сайта отклонила — помечаю «Не вышло»")
        sheet.set_site_result(link, SITE_FAIL)
        return

    stats["ok"] += 1
    print("    ✅ на сайте, ждёт модератора")
    sheet.set_site_result(link, SITE_REVIEW)


async def main() -> int:
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
    if not rows:
        print("✅ очередь пуста: у согласившихся всё уже разобрано.")
        return 0

    print(f"📋 в очереди {len(rows)} объявлений "
          f"(потолок {LIMIT}, не старше {MAX_AGE_DAYS} дн.)")

    stats = {"ok": 0, "fail": 0, "dup": 0, "rejected": 0, "dry": 0}
    schema = site.schema() if site.ready else {}
    if schema:
        print(f"📚 справочник сайта получен: подкатегорий "
              f"{len(schema.get('subcategories') or [])}, районов "
              f"{len(schema.get('districts') or [])}")

    api_id = int(os.environ["TG_API_ID"])
    api_hash = os.environ["TG_API_HASH"]
    session = StringSession(os.environ["TG_SESSION"])

    async with TelegramClient(session, api_id, api_hash) as client:
        me = await client.get_me()
        print(f"🔑 вошёл как {me.first_name} (id {me.id})")
        for i, row in enumerate(rows):
            try:
                await process_row(client, site, sheet, row, stats, schema)
            except FloodWaitError as e:
                print(f"  ⏳ Telegram просит подождать {e.seconds}с — стоп на сегодня")
                break
            except Exception as e:  # noqa: BLE001
                print(f"  ⚠ строка прервалась: {e} — иду дальше")
            if i < len(rows) - 1:
                await asyncio.sleep(DELAY_BETWEEN_POSTS)

    print(f"\n🏁 Готово. На сайт: {stats['ok']}; не вышло: {stats['fail']}; "
          f"уже были: {stats['dup']}; сняты ИИ: {stats['rejected']}"
          + (f"; в тестовом режиме собрано: {stats['dry']}" if DRY else ""))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
