"""
Защита от дублей авторов (режим CRM, правило Савелия 26.07).

Зачем: таблица теперь работает как CRM для обзвона — один ник = одна строка
НАВСЕГДА. Поэтому дубль считаем ПО НИКУ автора (а не «автор+текст», как было
раньше). Как только автор попал в таблицу, любые его следующие посты в таблицу
не добавляются и даже не тратят на себя ИИ (проверка идёт ДО классификации).

Раньше ключом был «ник + очищенный текст» — это ловило перепосты одного товара.
Теперь задача другая: не заводить второй контакт на того же человека. Значит
достаточно самого ника. Посты без ника до дедупа не доходят — их парсер
пропускает раньше (писать некому).

Храним ключи локально в dedup.json (на сервере, как и state.json). В git НЕ
коммитим (см. .gitignore). Формат: {"keys": ["<sha1(ника)>", ...]}.

Как пользоваться (см. parser.py):
  dedup.load()                      — один раз в начале прогона;
  if dedup.is_dup(author): …        — пропустить автора, который уже в таблице;
  dedup.remember(author)            — пометить автора как записанного (в памяти);
  dedup.save()                      — сохранить на диск после успешной записи.

Совместимость сигнатур: функции принимают необязательный второй аргумент text
(он теперь игнорируется), чтобы не ломать старые вызовы.
"""
import hashlib
import json
import os

DEDUP_FILE = os.path.join(os.path.dirname(__file__), "dedup.json")

_keys: set | None = None


def _key(author: str | None, text: str | None = None) -> str:
    """Ключ дубля = только ник автора (нормализованный: без @, нижний регистр).
    Аргумент text больше не участвует — оставлен для совместимости вызовов."""
    a = (author or "").lstrip("@").strip().lower()
    return hashlib.sha1(a.encode("utf-8")).hexdigest()


def make_key(author, text=None):
    """Публичный ключ дубля (тот же, что внутри is_dup) — для отсева повторов
    в пределах одного прогона (используется в parser.py)."""
    return _key(author)


def load() -> None:
    """Читает ранее записанные ключи в память (один раз за прогон)."""
    global _keys
    if not os.path.exists(DEDUP_FILE):
        _keys = set()
        return
    try:
        with open(DEDUP_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        _keys = set(data.get("keys", []))
    except (json.JSONDecodeError, OSError):
        _keys = set()


def _ensure_loaded() -> None:
    if _keys is None:
        load()


def is_dup(author: str | None, text: str | None = None) -> bool:
    """True — если этот автор уже есть в таблице (уже заводили контакт)."""
    _ensure_loaded()
    return _key(author) in _keys


def remember(author: str | None, text: str | None = None) -> None:
    """Помечает автора как записанного (в памяти; на диск — через save())."""
    _ensure_loaded()
    _keys.add(_key(author))


def save() -> None:
    """Сохраняет ключи на диск. Зовём после УСПЕШНОЙ записи в таблицу."""
    _ensure_loaded()
    tmp = DEDUP_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"keys": sorted(_keys)}, f, ensure_ascii=False)
    os.replace(tmp, DEDUP_FILE)  # атомарно: не бьём файл при сбое записи
