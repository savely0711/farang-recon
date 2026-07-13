"""
Защита от дублей объявлений (правило Савелия 13.07).

Зачем: в живых барахолках один и тот же товар продавец публикует по многу раз
(перепост «чтобы подняли»), плюс попадаются копипасты. В таблицу такое сыпалось
пачками (≈80% мусора). Тут мы запоминаем, какие объявления уже записали, и
повторы в таблицу больше не добавляем.

Что считаем дублем (выбор Савелия): «тот же автор + похожий текст».
  - «автор» — ник Telegram (если ника нет — считаем пустым; тогда одинаковый
    текст у анонимов тоже схлопнется, это допустимо и безопасно);
  - «похожий текст» — очищенный текст (без регистра, эмодзи, знаков и лишних
    пробелов). Так ловятся перепосты одного товара с мелкими отличиями в
    оформлении. Настоящее «умное» сравнение опечаток (Левенштейн) — на будущее,
    если простого способа окажется мало.

Храним ключи локально в dedup.json (на сервере, как и state.json). В git НЕ
коммитим (см. .gitignore). Формат: {"keys": ["<sha1>", ...]}.

Как пользоваться (см. parser.py):
  dedup.load()                      — один раз в начале прогона;
  if dedup.is_dup(author, text): …  — пропустить повтор;
  dedup.remember(author, text)      — пометить как записанное (в памяти);
  dedup.save()                      — сохранить на диск после успешной записи.
"""
import hashlib
import json
import os
import re

DEDUP_FILE = os.path.join(os.path.dirname(__file__), "dedup.json")

_keys: set | None = None


def _norm(text: str) -> str:
    """Очищает текст: нижний регистр, долой эмодзи/знаки, схлопнуть пробелы.
    \\w в Python по умолчанию — юникодный (ловит и кириллицу, и тайские буквы)."""
    t = (text or "").lower()
    t = re.sub(r"[^\w\s]", " ", t)   # убрать пунктуацию и эмодзи (не буквы/цифры)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _key(author: str | None, text: str) -> str:
    a = (author or "").lower().strip()
    return hashlib.sha1(f"{a}|{_norm(text)}".encode("utf-8")).hexdigest()


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


def is_dup(author: str | None, text: str) -> bool:
    """True — если такое объявление (тот же автор + похожий текст) уже видели."""
    _ensure_loaded()
    return _key(author, text) in _keys


def remember(author: str | None, text: str) -> None:
    """Помечает объявление как записанное (в памяти; на диск — через save())."""
    _ensure_loaded()
    _keys.add(_key(author, text))


def save() -> None:
    """Сохраняет ключи на диск. Зовём после УСПЕШНОЙ записи в таблицу."""
    _ensure_loaded()
    tmp = DEDUP_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"keys": sorted(_keys)}, f, ensure_ascii=False)
    os.replace(tmp, DEDUP_FILE)  # атомарно: не бьём файл при сбое записи
