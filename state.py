"""
Память парсера: докуда он уже дочитал каждый канал.
Храним локально в state.json (на сервере). Формат:
  { "pattaya01": 123456, ... }  — username -> id последнего обработанного поста.

Это позволяет каждый день добирать ТОЛЬКО новые посты и не дублировать.
Историю в таблице не трогаем (правило: архив не чистим).
"""
import json
import os

STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")


def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def get_last_id(username: str) -> int:
    return int(load_state().get(username, 0))


def set_last_id(username: str, message_id: int) -> None:
    data = load_state()
    data[username] = int(message_id)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
