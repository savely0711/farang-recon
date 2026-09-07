"""
ЗАМЕР: НАСКОЛЬКО ЛУЧШЕ СТАЛ РАЗБОР УСЛУГ (сессия 4, 07.09.2026).

Зачем. Мы дали ИИ справочник подкатегорий услуг с примерами и разрешили
услугам жить без цены. Этот скрипт показывает цифрами, что изменилось: берёт
РЕАЛЬНЫЕ посты из очереди авто-подготовки и разбирает каждый ДВАЖДЫ —
как было до правок и как стало. Ничего никуда не пишет: ни в таблицу,
ни на сайт.

Что считаем:
  • сколько постов вообще превратились в карточку (было / стало);
  • сколько из них потеряно из-за «цена не разобрана» (было / стало);
  • у скольких выбрана подкатегория (было / стало) — для услуг это и есть
    «процент попаданий»: до правок выбирать было НЕ ИЗ ЧЕГО;
  • как услуги разложились по подкатегориям — глазами видно, разумно ли.

Стоит денег ИИ: два обращения на пост (модель дешёвая, 60 постов ≈ копейки).

Откуда берутся посты. Сначала — очередь авто-подготовки (то, что реально
поедет на сайт). Если она пуста (её каждый день в 10:00 разбирает расписание),
берём свежие посты прямо из групп разведки, отбирая по словам-приметам услуг:
иначе на девять постов про вещи пришёлся бы один про услугу и замер стоил бы
вдесятеро дороже. Выборка тогда СМЕЩЁННАЯ — это не «доля услуг на рынке», а
ответ на вопрос «когда услуга приходит, разбирается ли она правильно».

Запуск (в консоли Aeza, сначала обновить код):
    cd farang-recon && git pull && python3 zamer.py    — в фоне, лог zamer.log
    python3 services_hits.py 40                        — прямо в консоли

Полная таблица по каждому посту ложится рядом в services_hits.tsv.
"""
import asyncio
import os
import re
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession

load_dotenv()

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_TSV = os.path.join(HERE, "services_hits.tsv")

LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 60
DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else 0
# Третьим словом можно попросить брать посты прямо из групп, не из очереди:
# в очереди услуг единицы, а мерить надо на них.
FORCE_GROUPS = len(sys.argv) > 3 and sys.argv[3].strip().lower() == "groups"

LINK_RE = re.compile(r"^https://t\.me/([A-Za-z0-9_]+)/(\d+)/?$")

import build  # noqa: E402
from sheets import Sheet  # noqa: E402
from prepare import Site  # noqa: E402


# ─────────────────────── «КАК БЫЛО» ───────────────────────
# Восстанавливаем прежнее поведение разбора, не трогая build.py:
#  1) в подсказке нет примеров к подкатегориям (поле hint);
#  2) правило «подкатегорию выбрать обязательно» заменено на прежнее мягкое;
#  3) услуга без цены отбивается (флаг SERVICES_NO_PRICE=0).

OLD_SUB_RULE = ("- subcategory: точная подкатегория сайта из списка ниже (slug). "
                "Если подходящей нет — null.\n")


def _old_system() -> str:
    """Прежняя подсказка: новый абзац про подкатегорию меняем на старую фразу."""
    s = build._SYSTEM
    start = s.find("- subcategory: точная подкатегория")
    end = s.find("- district:", start)
    if start == -1 or end == -1:
        return s  # подсказку переписали — сравнивать нечего, идём как есть
    return s[:start] + OLD_SUB_RULE + s[end:]


def _old_schema(schema: dict) -> dict:
    """Справочник, каким ИИ видел его ДО правок: без примеров и БЕЗ подкатегорий
    услуг — их до миграции db/43 не существовало вовсе. Если оставить их здесь,
    колонка «было» покажет то, чего никогда не было, и замер соврёт в нашу
    пользу."""
    subs = [{k: v for k, v in sub.items() if k != "hint"}
            for sub in (schema.get("subcategories") or [])
            if sub.get("section") != "services"]
    return {**schema, "subcategories": subs}


def build_old(text: str, schema: dict) -> dict:
    saved_system, saved_flag = build._SYSTEM, build.SERVICES_NO_PRICE
    build._SYSTEM, build.SERVICES_NO_PRICE = _old_system(), False
    try:
        return build.build_listing(text, _old_schema(schema))
    finally:
        build._SYSTEM, build.SERVICES_NO_PRICE = saved_system, saved_flag


# ─────────────────────── СЧЁТ ───────────────────────
def blank() -> dict:
    return {"posts": 0, "ok": 0, "no_price": 0, "with_sub": 0, "subs": {}}


def note(acc: dict, card: dict) -> None:
    acc["posts"] += 1
    if card["ok"]:
        acc["ok"] += 1
        sub = card.get("subcategory")
        if sub:
            acc["with_sub"] += 1
            acc["subs"][sub] = acc["subs"].get(sub, 0) + 1
    elif "цена не разобрана" in card.get("reason", ""):
        acc["no_price"] += 1


def pct(part: int, whole: int) -> str:
    return f"{(100 * part / whole):.0f}%" if whole else "—"


def report(name: str, was: dict, now: dict) -> None:
    print(f"\n{name}: постов {now['posts']}")
    if now["posts"] == 0:
        print("  (в выборке таких постов не было)")
        return
    rows = [
        ("собралась карточка", was["ok"], now["ok"]),
        ("потеряно из-за «нет цены»", was["no_price"], now["no_price"]),
        ("выбрана подкатегория", was["with_sub"], now["with_sub"]),
    ]
    print(f"  {'':30} {'было':>14}   {'стало':>14}")
    for label, a, b in rows:
        print(f"  {label:30} {a:>5} ({pct(a, now['posts']):>4})   "
              f"{b:>5} ({pct(b, now['posts']):>4})")
    if now["subs"]:
        print("  как разложились:")
        for slug, n in sorted(now["subs"].items(), key=lambda x: -x[1]):
            print(f"     {slug:22} {n}")


# ─────────────── ОТКУДА БРАТЬ ПОСТЫ ───────────────
# Слова-приметы услуги. Нужны только запасному источнику: в группах на одну
# услугу приходится примерно девять постов про вещи, и без отбора замер стоил
# бы вдесятеро дороже. Отбор грубый и намеренно широкий — решает всё равно ИИ.
SERVICE_WORDS = re.compile(
    r"(услуг|мастер|сантехник|электрик|ремонт|уборк|клининг|химчистк|"
    r"маникюр|педикюр|ресниц|бров|парикмахер|барбер|космет|массаж|спа|"
    r"трансфер|такси|перевозк|доставк|курьер|грузчик|переезд|"
    r"репетитор|обучен|уроки|курсы|тренер|инструктор|"
    r"фотограф|видеограф|съёмк|съемк|монтаж|ведущ|аниматор|"
    r"визы|виза|продлен|документ|бухгалтер|перевод док|юрист|нотариус|"
    r"экскурс|тур\b|гид\b|яхт|катер|рыбалк|"
    r"груминг|стрижка собак|ветеринар|передержк|выгул|"
    r"настройк|установк|прошивк|разблокир|сайт под ключ|реклам|smm|"
    r"няня|сиделк|домработниц|прайс|запись на|записыва|выезд на дом)",
    re.IGNORECASE)


async def posts_from_queue(client, rows: list):
    """Посты из очереди авто-подготовки — по ссылке на конкретный пост."""
    for row in rows:
        link = row.get("link") or ""
        m = LINK_RE.match(link)
        if not m:
            continue
        try:
            entity = await client.get_entity(m.group(1))
            msg = await client.get_messages(entity, ids=int(m.group(2)))
        except Exception as e:  # noqa: BLE001
            print(f"     пост не открылся: {e}")
            continue
        text = (msg.message if msg else "") or ""
        if text.strip():
            yield link, text


async def posts_from_groups(client, limit: int, days: int):
    """Запасной источник: свежие посты групп, похожие на услуги."""
    from channels import CHANNELS
    since = None
    if days > 0:
        since = datetime.now(timezone.utc) - timedelta(days=days)
    taken = 0
    for ch in CHANNELS:
        if taken >= limit:
            return
        username = ch["username"]
        try:
            entity = await client.get_entity(username)
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠ группа @{username} не открылась: {e}")
            continue
        try:
            async for msg in client.iter_messages(entity, limit=300):
                if since and msg.date and msg.date < since:
                    break
                text = (msg.message or "").strip()
                if len(text) < 40 or not SERVICE_WORDS.search(text):
                    continue
                yield f"https://t.me/{username}/{msg.id}", text
                taken += 1
                if taken >= limit:
                    return
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠ чтение @{username} прервалось: {e}")
        await asyncio.sleep(2)


async def main() -> int:
    site = Site()
    if not site.ready:
        print("⛔ в .env нет SITE_API_URL / RECON_API_TOKEN — справочник не получить.")
        return 1
    schema = site.schema()
    subs = schema.get("subcategories") or []
    serv = [s for s in subs if s.get("section") == "services"]
    print(f"📚 справочник сайта: подкатегорий {len(subs)}, из них по услугам {len(serv)}")
    if not serv:
        print("⛔ подкатегорий услуг в справочнике нет — миграция db/43 не применена "
              "или сайт не переразвёрнут. Замер бессмыслен, останавливаюсь.")
        return 1

    rows = None if FORCE_GROUPS else Sheet().read_todo(limit=LIMIT, days=DAYS)
    source = "очередь авто-подготовки"
    if not rows:
        print("ℹ беру свежие посты из групп (отбор по словам-приметам услуг).")
        rows = None
        source = "свежие посты групп (отбор по словам-приметам услуг)"
    else:
        print(f"📋 беру {len(rows)} постов из очереди авто-подготовки\n")

    was_s, now_s = blank(), blank()   # услуги
    was_a, now_a = blank(), blank()   # всё остальное
    diffs = []                        # где старый и новый разбор разошлись

    api_id = int(os.environ["TG_API_ID"])
    api_hash = os.environ["TG_API_HASH"]
    session = StringSession(os.environ["TG_SESSION"])

    out = open(OUT_TSV, "w", encoding="utf-8")
    out.write("ссылка\tраздел\tбыло итог\tбыло подкат\tстало итог\tстало подкат\tзаголовок\n")

    async with TelegramClient(session, api_id, api_hash) as client:
        posts = (posts_from_queue(client, rows) if rows
                 else posts_from_groups(client, LIMIT, DAYS or 30))
        i = 0
        async for link, text in posts:
            i += 1
            new = build.build_listing(text, schema)
            old = build_old(text, schema)

            is_serv = (new.get("category") == "services"
                       or old.get("category") == "services")
            note(was_s if is_serv else was_a, old)
            note(now_s if is_serv else now_a, new)

            def brief(c: dict) -> str:
                return "карточка" if c["ok"] else f"отказ: {c.get('reason', '')}"

            out.write("\t".join([
                link, new.get("category") or old.get("category") or "—",
                brief(old), old.get("subcategory") or "—",
                brief(new), new.get("subcategory") or "—",
                (new.get("title") or old.get("title") or "").replace("\t", " "),
            ]) + "\n")

            if brief(old) != brief(new):
                diffs.append((link, brief(old), brief(new), is_serv))

            mark = "🛠" if is_serv else "  "
            print(f"  {i:>3}.{mark} было: {brief(old)[:34]:34} | "
                  f"стало: {brief(new)[:34]:34} | {new.get('subcategory') or '—'}")

    out.close()
    if diffs:
        print(f"\nГДЕ РАЗОШЛИСЬ ({len(diffs)}):")
        for link, o, n, is_serv in diffs[:15]:
            tag = "услуга" if is_serv else "прочее"
            print(f"  {tag} {link}\n     было: {o}\n     стало: {n}")

    print(f"\nисточник постов: {source}")
    report("УСЛУГИ", was_s, now_s)
    report("ВСЁ ОСТАЛЬНОЕ (не должно измениться)", was_a, now_a)
    print(f"\nподробности по каждому посту: {OUT_TSV}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
