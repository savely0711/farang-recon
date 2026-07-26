"""
Очередь «первого касания» (Направление 3, пункт 14).

Разведка (parser.py) при записи КАЖДОГО нового объявления с ником автора
добавляет его сюда — в простой файл-очередь outreach_queue.jsonl (по строке на
объявление). Программа отправки (outreach.py) читает очередь и решает, кому и
когда написать (одному автору — один раз навсегда, объявление старше суток,
щадящие лимиты). Так авто-отправка работает ТОЛЬКО по новым объявлениям — тех,
кому Савелий уже писал руками до запуска, она не трогает.

Формат строки (одна на объявление):
  {"author": "ник_без_собаки", "link": "https://t.me/канал/123",
   "date": "2026-07-26T09:15:00+00:00", "queued_at": "2026-07-26T09:20:00+00:00"}

Файл живёт локально на сервере (в git не коммитим — см. .gitignore).
"""
import json
import os
from datetime import datetime, timezone

QUEUE_FILE = os.path.join(os.path.dirname(__file__), "outreach_queue.jsonl")


def enqueue(author, link, date) -> None:
    """Добавляет объявление в очередь на «первое касание».
    Пишем ТОЛЬКО если у автора есть открытый ник — иначе написать некому.
    date — datetime поста (с таймзоной)."""
    if not author:
        return
    try:
        date_iso = date.astimezone(timezone.utc).isoformat() if date else None
    except Exception:  # noqa: BLE001
        date_iso = None
    row = {
        "author": author.lstrip("@").strip(),
        "link": link,
        "date": date_iso,
        "queued_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(QUEUE_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_all() -> list:
    """Читает всю очередь (список объявлений в порядке добавления)."""
    if not os.path.exists(QUEUE_FILE):
        return []
    rows = []
    with open(QUEUE_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows
