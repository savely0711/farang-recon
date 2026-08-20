#!/usr/bin/env python3
"""Добор отпечатков картинок для поиска дублей (db/33).

ЗАЧЕМ. Отпечаток картинки нужен сайту, чтобы показывать модератору «похоже на
дубль». Там, где картинка проходит через браузер или через нашу авто-подготовку,
отпечаток считается сразу. Но остаётся всё остальное: снимки, залитые до
появления этой затеи, и всё, что пришло через бота. Сайту посчитать их нечем —
Node не разбирает JPEG без тяжёлых библиотек, а ставить их на Vercel ради ночной
работы не стоит. Зато здесь стоит Pillow.

КАК РАБОТАЕТ. Спрашивает у сайта список фотографий без отпечатка
(`action=photos_todo`), скачивает уменьшенные копии, считает отпечатки тем же
способом, что и браузер (см. phash.py), и отправляет обратно
(`action=photos_phash`). Никаких новых паролей: тот же токен разведки.

Снимки скачиваются в несколько потоков: сайт отдаёт уменьшенные копии, и почти
всё время уходит именно на ожидание сети. Без этого прогон на сотню снимков
занимал шесть минут, с этим — меньше минуты.

ЗАПУСК (на сервере Aeza, из папки репозитория):
    python3 fillhash.py          — разобрать очередь (по 100 за круг)
    python3 fillhash.py 500      — не больше 500 снимков за прогон

Работает по кругу, пока очередь не опустеет или не упрётся в потолок. Ставится
в cron сразу после ночной разведки — тогда отпечатки всегда свежие.
"""
from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor

import httpx
from dotenv import load_dotenv

from phash import fingerprint

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

BATCH = 100            # сколько снимков просим у сайта за раз
WORKERS = 8            # столько снимков качаем одновременно
DEFAULT_LIMIT = 2000   # потолок за один прогон, чтобы не крутиться часами


def main() -> int:
    url = os.environ.get("SITE_API_URL", "").strip()
    token = os.environ.get("RECON_API_TOKEN", "").strip()
    if not url or not token:
        print("⛔ в .env нет SITE_API_URL и/или RECON_API_TOKEN — стоп.")
        print("   Заполнить их поможет: python3 setupsite.py")
        return 1

    try:
        limit = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_LIMIT
    except ValueError:
        limit = DEFAULT_LIMIT

    client = httpx.Client(timeout=120.0, follow_redirects=True)
    done = failed = 0

    while done + failed < limit:
        try:
            r = client.post(url, json={"token": token, "action": "photos_todo",
                                       "limit": BATCH})
            r.raise_for_status()
            data = r.json()
        except Exception as e:  # noqa: BLE001
            print(f"⛔ сайт не ответил: {e}")
            return 1
        if not data.get("ok"):
            print(f"⛔ сайт отказал: {data.get('error')}")
            return 1

        photos = data.get("photos") or []
        if not photos:
            print("✅ очередь пуста — отпечатки есть у всех фотографий.")
            break

        def one(photo: dict) -> dict | None:
            """Скачать снимок и посчитать отпечаток. None — не поддался."""
            try:
                img = client.get(photo["url"])
                img.raise_for_status()
                fp = fingerprint(img.content)
            except Exception:  # noqa: BLE001
                return None
            return {"id": photo["id"], "phash": fp} if fp else None

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            results = list(pool.map(one, photos))
        items = [r for r in results if r]
        failed += len(results) - len(items)

        if items:
            try:
                r = client.post(url, json={"token": token,
                                           "action": "photos_phash",
                                           "items": items})
                r.raise_for_status()
                saved = int(r.json().get("saved") or 0)
            except Exception as e:  # noqa: BLE001
                print(f"⛔ отпечатки не отправились: {e}")
                return 1
            done += saved
            print(f"  … посчитано {done}, не вышло {failed}")

        # Ни один снимок в круге не поддался — дальше будет то же самое.
        if not items:
            print(f"⚠ {len(photos)} снимков подряд не открылись — прекращаю, "
                  f"чтобы не крутиться впустую.")
            break

    print(f"\nИтог: отпечатков посчитано {done}, не удалось {failed}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
