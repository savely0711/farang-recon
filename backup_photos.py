"""Резервное ЗЕРКАЛО фотографий сайта на этом сервере.

Зачем это появилось (08.09.2026)
--------------------------------
Раньше копию снимков делал ночной робот GitHub: каждую ночь он скачивал ВСЮ
библиотеку целиком и паковал в архив. Пока фотографий было мало, это ничего
не стоило. К сентябрю их стало 0,6 ГБ - и одна и та же библиотека выкачивалась
заново 30 раз в месяц: 17 ГБ трафика при бесплатном лимите Supabase в 5 ГБ.
Заодно архивы забили всё бесплатное хранилище GitHub Actions (0,5 ГБ).

Теперь копия живёт здесь и устроена как ЗЕРКАЛО: каждый снимок хранится ровно
один раз, а скачиваются только те, которых ещё нет. Это десятки мегабайт в
сутки вместо полугигабайта.

Что делает
----------
1. Спрашивает у сайта список всех фотографий (действие photos_all).
2. Сверяет со своей папкой и качает недостающие.
3. Ничего не удаляет: снимок снятого объявления в хранилище сайта исчезает, а
   в копии остаётся - она для того и нужна.

Куда кладёт:  ~/backup/photos/<путь как в хранилище сайта>
Отчёт:        ~/backup/photos_state.json  (когда, сколько, какой объём)

Запуск вручную:  cd ~/farang-recon && git pull && python3 backup_photos.py
По расписанию:   ставится через install_cron.py, ежедневно в 03:30.

Ключи:
    python3 backup_photos.py            обычный прогон
    python3 backup_photos.py check      только посчитать, ничего не качать
"""
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

PAGE = 500        # сколько путей просим у сайта за раз
WORKERS = 4       # столько снимков качаем одновременно (сервер слабый)
DEST = os.path.expanduser("~/backup/photos")
STATE = os.path.expanduser("~/backup/photos_state.json")


def human(n: int) -> str:
    """Байты словами: 1536 -> «1,5 МБ»."""
    for unit, size in (("ГБ", 1 << 30), ("МБ", 1 << 20), ("КБ", 1 << 10)):
        if n >= size:
            return f"{n / size:.1f} {unit}".replace(".", ",")
    return f"{n} Б"


def ask_site(client: httpx.Client, url: str, token: str) -> list:
    """Полный список фотографий сайта: [{id, path, url}, ...]."""
    items = []
    after = None
    while True:
        r = client.post(url, json={"token": token, "action": "photos_all",
                                   "after": after, "limit": PAGE})
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"сайт отказал: {data.get('error')}")
        items.extend(data.get("items") or [])
        after = data.get("next")
        if not after:
            return items


def _dir_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def _save_state(on_site: int, added: int, total_bytes: int) -> None:
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump({
            "когда": time.strftime("%Y-%m-%d %H:%M:%S"),
            "фотографий на сайте": on_site,
            "скачано за прогон": added,
            "объём копии": human(total_bytes),
        }, f, ensure_ascii=False, indent=2)


def main() -> int:
    site = os.environ.get("SITE_API_URL", "").strip()
    token = os.environ.get("RECON_API_TOKEN", "").strip()
    if not site or not token:
        print("⛔ в .env нет SITE_API_URL и/или RECON_API_TOKEN - стоп.")
        print("   Заполнить их поможет: python3 setupsite.py")
        return 1

    only_check = len(sys.argv) > 1 and sys.argv[1] == "check"
    os.makedirs(DEST, exist_ok=True)
    client = httpx.Client(timeout=120.0, follow_redirects=True)

    print("спрашиваю у сайта список фотографий...")
    try:
        photos = ask_site(client, site, token)
    except Exception as e:  # noqa: BLE001
        print(f"⛔ список не получен: {e}")
        return 1
    print(f"всего фотографий на сайте: {len(photos)}")

    # Чего нет в зеркале. Пустые файлы (оборванная закачка) перекачиваем.
    todo = []
    for p in photos:
        dest = os.path.join(DEST, p["path"])
        if not os.path.exists(dest) or os.path.getsize(dest) == 0:
            todo.append((p, dest))
    print(f"уже в копии: {len(photos) - len(todo)}   надо скачать: {len(todo)}")

    if only_check:
        print("режим проверки - ничего не качаю.")
        return 0
    if not todo:
        print("✅ копия уже полная, качать нечего.")
        _save_state(len(photos), 0, _dir_size(DEST))
        return 0

    def one(job) -> int:
        """Скачать один снимок. Возвращает размер в байтах, 0 - не вышло."""
        photo, dest = job
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        tmp = dest + ".part"
        try:
            with client.stream("GET", photo["url"]) as r:
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in r.iter_bytes(64 * 1024):
                        f.write(chunk)
            os.replace(tmp, dest)          # готовый файл появляется целиком
            return os.path.getsize(dest)
        except Exception as e:  # noqa: BLE001
            print(f"   ⚠ не скачалось: {photo['path']} ({e})")
            if os.path.exists(tmp):
                os.remove(tmp)
            return 0

    started = time.time()
    got = failed = 0
    downloaded = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for i, size in enumerate(pool.map(one, todo), 1):
            if size:
                got += 1
                downloaded += size
            else:
                failed += 1
            if i % 100 == 0:
                print(f"   ... {i} из {len(todo)}")

    total = _dir_size(DEST)
    print(f"\n✅ скачано: {got}   не вышло: {failed}")
    print(f"   докачано за прогон: {human(downloaded)}")
    print(f"   объём копии: {human(total)}   папка: {DEST}")
    print(f"   заняло: {int(time.time() - started)} сек")
    _save_state(len(photos), got, total)
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
