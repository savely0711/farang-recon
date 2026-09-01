#!/usr/bin/env python3
"""
НОЧНАЯ СВЕРКА ТАБЛИЦЫ С САЙТОМ.

ЗАЧЕМ. Колонка «На сайте» заполнялась один раз — в момент авто-подготовки — и
дальше застывала. Слово «Опубликовано» означало всего лишь «отправлено на сайт
и лежит в очереди модерации»; что случилось потом (одобрили, сняли, удалили как
дубль), таблица не знала. Теперь раз в сутки спрашиваем сайт и приводим таблицу
в соответствие с действительностью.

ЧТО ДЕЛАЕТ, по порядку:

1. ЛЮДИ (это важнее). Берёт все ники таблицы и спрашивает сайт, кто из них уже
   завёл аккаунт. Каждому найденному ставит «зарегистрирован» — и он сразу
   выпадает из очереди авто-подготовки: за человека, который пришёл сам,
   публиковать больше нельзя, он теперь сам себе хозяин. Сайт и так сообщает об
   этом в момент первого входа, но сообщение могло не дойти (сеть, перезапуск) —
   сверка закрывает эту дыру.

2. ОБЪЯВЛЕНИЯ. Берёт строки, где колонка «На сайте» заполнена, и спрашивает
   состояние каждого объявления по ссылке на исходный пост. Пишет одно из:
     «В каталоге»      — одобрено, люди его видят;
     «Ждёт модератора» — лежит в очереди на проверку;
     «Снято»           — снято модерацией, продавцом или по сроку;
     «Удалено»         — удалено насовсем (в том числе как дубль).
   «Удалено» и «Не вышло» — окончательные: заново такие объявления НЕ готовим
   (решение Савелия 20.08.2026). Чтобы всё-таки переиграть, очистите ячейку
   руками — тогда строка вернётся в очередь.

ЗАПУСК (на сервере Aeza, из папки репозитория):
    python3 syncsite.py         — сверить всё
    python3 syncsite.py dry     — только показать, ничего не записывать

Ставится в cron сразу после авто-подготовки (см. install_cron.py).
"""
from __future__ import annotations

import os
import sys

import httpx
from dotenv import load_dotenv

from sheets import SITE_LIVE, SITE_OFF, SITE_REVIEW, Sheet

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

DRY = any(a.strip().lower() == "dry" for a in sys.argv[1:])
CHUNK = 300           # столько ссылок спрашиваем у сайта за один раз
NICK_CHUNK = 500      # столько ников за один раз

# Ответ сайта → значение колонки «На сайте».
# С 01.09.2026 «удалено» и «снято» ведут в ОДНУ ячейку «Снято»: человеку важно
# одно — на сайте объявления нет, а чем именно оно кончилось, видно на сайте.
STATE_TO_CELL = {
    "catalog": SITE_LIVE,
    "review": SITE_REVIEW,
    "off": SITE_OFF,
    "gone": SITE_OFF,
}


class Site:
    """Закрытая точка приёма сайта (/api/recon)."""

    def __init__(self):
        self.url = os.environ.get("SITE_API_URL", "").strip()
        self.token = os.environ.get("RECON_API_TOKEN", "").strip()
        self._client = httpx.Client(timeout=120.0, follow_redirects=True)

    @property
    def ready(self) -> bool:
        return bool(self.url and self.token)

    def ask(self, payload: dict) -> dict | None:
        try:
            r = self._client.post(self.url, json={"token": self.token, **payload})
            r.raise_for_status()
            data = r.json()
            if not data.get("ok"):
                print(f"  ⚠ сайт отказал: {data.get('error')}")
                return None
            return data
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠ сайт не ответил: {e}")
            return None


def chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def sync_people(sheet: Sheet, site: Site) -> int:
    """Кто из таблицы уже зарегистрировался — тем ставим «зарегистрирован»."""
    nicks = sheet.read_nicks()
    if nicks is None:
        print("⛔ список ников не получен — пропускаю сверку по людям.")
        return 0
    print(f"  людей в таблице: {len(nicks)}")

    known = sheet.read_consents() or {}
    registered: list[str] = []
    for part in chunks(nicks, NICK_CHUNK):
        data = site.ask({"action": "registered", "nicks": part})
        if data is None:
            continue
        registered.extend(data.get("registered") or [])

    # Пишем только тем, у кого в реестре ещё не стоит «зарегистрирован» или
    # «отказ»: лишние записи только замусорят реестр датами.
    rows = []
    for nick in registered:
        cur = str(known.get(nick.lower(), "")).strip()
        if cur in ("зарегистрирован", "отказ"):
            continue
        rows.append({
            "nick": nick,
            "status": "зарегистрирован",
            "reason": "нашёлся при ночной сверке с сайтом",
        })

    print(f"  зарегистрированы на сайте: {len(registered)}; "
          f"новых для реестра: {len(rows)}")
    if DRY or not rows:
        return 0
    changed = sheet.set_consent_bulk(rows)
    print(f"  ✦ реестр обновлён: {changed}")
    return changed


def sync_listings(sheet: Sheet, site: Site) -> int:
    """Состояние размещённых объявлений → колонка «На сайте»."""
    placed = sheet.read_placed()
    if placed is None:
        print("⛔ список размещённых не получен — пропускаю сверку объявлений.")
        return 0
    print(f"  размещённых объявлений: {len(placed)}")
    if not placed:
        return 0

    was = {str(r.get("link", "")).strip(): str(r.get("site", "")).strip()
           for r in placed}
    links = [link for link in was if link]

    updates = []
    counts: dict[str, int] = {}
    for part in chunks(links, CHUNK):
        data = site.ask({"action": "states", "links": part})
        if data is None:
            continue
        states = data.get("states") or {}
        for link, state in states.items():
            cell = STATE_TO_CELL.get(state)
            if not cell:
                continue
            counts[cell] = counts.get(cell, 0) + 1
            if was.get(link) != cell:
                updates.append({"link": link, "value": cell})

    for cell, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"    {cell}: {n}")
    print(f"  изменилось: {len(updates)}")
    if DRY or not updates:
        return 0
    updated = sheet.set_site_bulk(updates)
    print(f"  ✦ таблица обновлена: {updated}")
    return updated


def main() -> int:
    site = Site()
    if not site.ready:
        print("⛔ в .env нет SITE_API_URL и/или RECON_API_TOKEN — стоп.")
        print("   Заполнить их поможет: python3 setupsite.py")
        return 1

    try:
        sheet = Sheet()
    except KeyError:
        print("⛔ в .env нет SHEET_WEBHOOK_URL — таблица недоступна, стоп.")
        return 1

    if DRY:
        print("холостой ход: ничего не записываю\n")

    print("1. Люди — кто уже зарегистрировался сам")
    people = sync_people(sheet, site)

    print("\n2. Объявления — что с ними стало")
    listings = sync_listings(sheet, site)

    print(f"\nИтог: реестр — {people}, строк «На сайте» — {listings}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
