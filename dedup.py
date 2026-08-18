"""
Защита от повторов ОБЪЯВЛЕНИЙ (мини-CRM «Присутствие», решение Савелия 16.08.2026).

Что изменилось и почему
-----------------------
Раньше (с 26.07) ключом дубля был ТОЛЬКО ник автора: один ник = одна строка в
таблице навсегда. Это и убило рост — второе и любое следующее объявление того же
продавца в таблицу не попадало, а посты без ника выбрасывались ещё раньше.

Теперь строка в таблице = ОБЪЯВЛЕНИЕ. Значит, отсеивать нужно не человека, а
повторную публикацию одного и того же текста: в барахолках люди поднимают свой
пост каждый день, и без этой защиты таблица захлебнулась бы копиями.

Ключ дубля:
  - есть ник  → «ник + нормализованный текст»;
  - ника нет  → «канал + нормализованный текст» (такие посты мы теперь тоже
    записываем — как рыночные данные; писать им некому).

Нормализация текста делает копии одинаковыми, даже если человек поменял регистр,
эмодзи или расставил другие пробелы: нижний регистр, выкидываем всё, кроме букв
и цифр, схлопываем пробелы. Цифры НЕ выкидываем — изменение цены это по сути
новое предложение, и такую строку хочется видеть.

ВАЖНО: проверка идёт ДО вызова ИИ (см. parser.py), поэтому повторы не стоят
ни денег, ни строки в таблице.

Второй рубеж — сама Google-таблица: скрипт-приёмник отсекает дубли по ссылке на
пост. Здесь мы ловим «тот же текст в новом посте», там — «тот же пост дважды».

Храним ключи локально в dedup.json (на сервере, как и state.json). В git НЕ
коммитим (см. .gitignore). Формат: {"v": 2, "keys": ["<sha1>", ...]}.
Файл версии 1 (ключи по никам) при первом запуске очищается: те ключи больше
ничего не значат, и таскать их за собой смысла нет.

Как пользоваться (см. parser.py):
  dedup.load()                            — один раз в начале прогона;
  key = dedup.make_key(author, text, channel)
  if dedup.is_dup(author, text, channel): …  — пропустить повтор;
  dedup.remember(author, text, channel)   — пометить как записанное (в памяти);
  dedup.save()                            — сохранить на диск после записи.
"""
import hashlib
import json
import os
import re

DEDUP_FILE = os.path.join(os.path.dirname(__file__), "dedup.json")
FORMAT_VERSION = 2

_keys: set | None = None

# Всё, что не буква и не цифра (в любом алфавите — русском, тайском, латинице),
# считаем «мусором» и выкидываем: знаки, эмодзи, переводы строк, рамки из звёзд.
_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)
# Сколько символов текста берём в ключ. Хватает с запасом, а очень длинные
# простыни не заставляют считать хэш от килобайтов.
_TEXT_LIMIT = 2000


def _norm_author(author: str | None) -> str:
    return (author or "").lstrip("@").strip().lower()


def _norm_text(text: str | None) -> str:
    """Приводит текст поста к виду, одинаковому у копий одного объявления."""
    t = (text or "").strip().lower()
    t = _NON_WORD.sub(" ", t)
    return " ".join(t.split())[:_TEXT_LIMIT]


def _key(author: str | None, text: str | None = None,
         channel: str | None = None) -> str:
    """Ключ дубля объявления.

    Есть ник → «ник|текст»; ника нет → «канал|текст». Разделитель '\\x00'
    выбран специально: в нормализованном тексте его быть не может, поэтому
    склеить два разных объявления в один ключ невозможно.
    """
    who = _norm_author(author)
    if not who:
        who = "#" + (channel or "").strip().lower()
    return hashlib.sha1(
        f"{who}\x00{_norm_text(text)}".encode("utf-8")
    ).hexdigest()


def make_key(author, text=None, channel=None):
    """Публичный ключ дубля (тот же, что внутри is_dup) — для отсева повторов
    в пределах одного прогона (используется в parser.py)."""
    return _key(author, text, channel)


def load() -> None:
    """Читает ранее записанные ключи в память (один раз за прогон).
    Файл старого формата (v1, ключи по никам) сбрасывается."""
    global _keys
    if not os.path.exists(DEDUP_FILE):
        _keys = set()
        return
    try:
        with open(DEDUP_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if int(data.get("v", 1)) != FORMAT_VERSION:
            print("  ℹ dedup.json старого формата (ключи по никам) — начинаю заново")
            _keys = set()
            return
        _keys = set(data.get("keys", []))
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        _keys = set()


def _ensure_loaded() -> None:
    if _keys is None:
        load()


def is_dup(author: str | None, text: str | None = None,
           channel: str | None = None) -> bool:
    """True — если ровно это объявление уже записано в таблицу."""
    _ensure_loaded()
    return _key(author, text, channel) in _keys


def remember(author: str | None, text: str | None = None,
             channel: str | None = None) -> None:
    """Помечает объявление как записанное (в памяти; на диск — через save())."""
    _ensure_loaded()
    _keys.add(_key(author, text, channel))


def save() -> None:
    """Сохраняет ключи на диск. Зовём после УСПЕШНОЙ записи в таблицу."""
    _ensure_loaded()
    tmp = DEDUP_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"v": FORMAT_VERSION, "keys": sorted(_keys)},
                  f, ensure_ascii=False)
    os.replace(tmp, DEDUP_FILE)  # атомарно: не бьём файл при сбое записи
