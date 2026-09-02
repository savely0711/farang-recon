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

ЧТО ДОБАВЛЕНО 02.09.2026 (пункт 8 большого списка, склейка строк).
Точного совпадения текста мало: человек поднимает объявление, меняя пару слов,
и таблица получала вторую строку про тот же товар. Теперь ловим ещё два случая
— в пределах ОДНОГО автора (или канала, если ника нет):

  • «почти тот же текст» — сравниваем наборы слов. Чтобы не хранить сами
    тексты, от каждого объявления остаётся отпечаток из 16 чисел (по-научному
    bottom-k sketch): берём хэши слов и оставляем 16 самых маленьких. Два
    набора слов тем ближе, чем больше у отпечатков общего. Порог 0,65 — это
    «переписал пару слов», а не «другое объявление про такой же товар»;

  • «то же фото» — отпечаток картинки (phash.py, те же 64 бита, что у сайта).
    Расстояние до 6 бит считаем одной и той же фотографией: пережатие
    Telegram столько и съедает.

Прежнее правило «изменил цену — это новое предложение» осталось в силе: если
в постах разные числа (цена, пробег, площадь), объявление считается новым,
даже когда фотография та же. Иначе снижение цены — самое интересное для нас
событие — просто пропало бы.

Разных продавцов между собой здесь НЕ склеиваем: таблица — это CRM по людям,
одна и та же квартира от двух агентств должна остаться двумя строками. Такие
пары ловит сайт (db/42, экран «Похожие пары»).

Храним ключи локально в dedup.json (на сервере, как и state.json). В git НЕ
коммитим (см. .gitignore). Формат версии 3:

  {"v": 3,
   "keys":  ["<sha1 точного текста>", ...],
   "items": [{"w": "<кто>", "s": ["<хэш слова>", ...], "p": ["<64 бита>", ...]}]}

Файл версии 2 читается как есть: точные ключи сохраняем (иначе назавтра в
таблицу хлынули бы копии), а нечёткие отпечатки просто начинают копиться с
нуля. Файл версии 1 (ключи по никам) очищается — те ключи ничего не значат.

Как пользоваться (см. parser.py):
  dedup.load()                            — один раз в начале прогона;
  key = dedup.make_key(author, text, channel)
  if dedup.is_dup(author, text, channel, phashes): …  — пропустить повтор;
  dedup.remember(author, text, channel, phashes)      — пометить записанным;
  dedup.save()                            — сохранить на диск после записи.

`phashes` — список отпечатков фотографий поста (строки из 64 нулей и единиц);
их может не быть вовсе, тогда работает только сравнение текста.
"""
import hashlib
import json
import os
import re

DEDUP_FILE = os.path.join(os.path.dirname(__file__), "dedup.json")
FORMAT_VERSION = 3

_keys: set | None = None
# Нечёткие отпечатки: [{"w": кто, "s": [хэши слов], "p": [отпечатки фото]}].
_items: list[dict] | None = None

# Сколько объявлений помним «нечётко». Точные ключи весят копейки и хранятся
# все, а здесь у каждой записи 16 хэшей слов и отпечатки фото — файл не должен
# расти бесконечно. 20 000 объявлений — это месяцы работы разведки.
_MAX_ITEMS = 20000
# Сколько хэшей слов оставляем от объявления.
_SKETCH_K = 16
# Ближе этого — «почти тот же текст».
_TEXT_NEAR = 0.65
# Столько бит может съесть пережатие Telegram у одной и той же фотографии.
_PHOTO_NEAR = 6
# Короткие объявления по словам не сравниваем: у «продам стол 500 бат» и
# «продам стул 500 бат» слишком много общего.
_MIN_WORDS = 8
# Числа длиной от трёх знаков — это цена, пробег, площадь. Их набор и решает,
# «то же самое объявление» или «то же самое, но за другие деньги».
_NUMBERS = re.compile(r"\d{3,}")

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


def _who(author: str | None, channel: str | None) -> str:
    """Владелец объявления для сравнения: ник, а если его нет — канал.
    Разных продавцов между собой не склеиваем (см. шапку файла)."""
    who = _norm_author(author)
    return who if who else "#" + (channel or "").strip().lower()


def _sketch(text: str | None) -> list[str]:
    """Отпечаток набора слов: 16 самых маленьких хэшей. Короткие слова
    выбрасываем — они есть везде и только зашумляют сравнение."""
    words = {w for w in _norm_text(text).split() if len(w) >= 3}
    if len(words) < _MIN_WORDS:
        return []
    hashes = sorted(
        hashlib.blake2b(w.encode("utf-8"), digest_size=6).hexdigest()
        for w in words
    )
    return hashes[:_SKETCH_K]


def _sketch_near(a: list[str], b: list[str]) -> bool:
    """Похожи ли два набора слов. Оценка снизу-вверх: берём общий список
    отпечатков, оставляем столько же самых маленьких — и смотрим, какая доля
    из них есть в обоих. Это обычный приём для быстрых сравнений текстов."""
    if not a or not b:
        return False
    sa, sb = set(a), set(b)
    union = sorted(sa | sb)[:_SKETCH_K]
    if not union:
        return False
    both = sum(1 for h in union if h in sa and h in sb)
    return both / len(union) >= _TEXT_NEAR


def _numbers(text: str | None) -> list[str]:
    """Числа объявления (цена и прочее) — по ним отличаем «поднял тот же пост»
    от «снизил цену»."""
    return sorted(set(_NUMBERS.findall(_norm_text(text))))


def _clean_phashes(phashes) -> list[str]:
    out = []
    for h in phashes or []:
        h = (h or "").strip()
        if len(h) == 64 and set(h) <= {"0", "1"}:
            out.append(h)
    return out


def _photo_near(a: list[str], b: list[str]) -> bool:
    """Есть ли среди двух наборов фотографий одна и та же."""
    for x in a:
        for y in b:
            if sum(1 for i, j in zip(x, y) if i != j) <= _PHOTO_NEAR:
                return True
    return False


def load() -> None:
    """Читает ранее записанное в память (один раз за прогон).

    Файл версии 2 подходит: точные ключи оставляем как есть, нечёткие
    отпечатки начнут копиться заново. Версию 1 (ключи по никам) сбрасываем —
    те ключи давно ничего не значат."""
    global _keys, _items
    _keys, _items = set(), []
    if not os.path.exists(DEDUP_FILE):
        return
    try:
        with open(DEDUP_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        version = int(data.get("v", 1))
        if version < 2:
            print("  ℹ dedup.json старого формата (ключи по никам) — начинаю заново")
            return
        _keys = set(data.get("keys", []))
        if version >= 3:
            _items = [x for x in data.get("items", []) if isinstance(x, dict)]
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        _keys, _items = set(), []


def _ensure_loaded() -> None:
    if _keys is None or _items is None:
        load()


def is_dup(author: str | None, text: str | None = None,
           channel: str | None = None, phashes=None) -> bool:
    """True — если это объявление у нас уже есть.

    Три способа узнать, от дешёвого к дорогому: тот же текст слово в слово,
    та же фотография, почти тот же текст. Сравниваем только с объявлениями
    ТОГО ЖЕ автора (или канала, если ника нет)."""
    _ensure_loaded()
    if _key(author, text, channel) in _keys:
        return True

    who = _who(author, channel)
    photos = _clean_phashes(phashes)
    sketch = _sketch(text)
    numbers = _numbers(text)
    if not photos and not sketch:
        return False

    for item in _items:
        if item.get("w") != who:
            continue
        # Цена (и любые другие числа) изменились — это новое предложение,
        # и увидеть его в таблице как раз хочется.
        if numbers != (item.get("n") or []):
            continue
        if photos and _photo_near(photos, item.get("p") or []):
            return True
        if sketch and _sketch_near(sketch, item.get("s") or []):
            return True
    return False


def remember(author: str | None, text: str | None = None,
             channel: str | None = None, phashes=None) -> None:
    """Помечает объявление как записанное (в памяти; на диск — через save())."""
    _ensure_loaded()
    _keys.add(_key(author, text, channel))

    sketch = _sketch(text)
    photos = _clean_phashes(phashes)
    if not sketch and not photos:
        return
    _items.append({
        "w": _who(author, channel),
        "s": sketch,
        "p": photos,
        "n": _numbers(text),
    })
    if len(_items) > _MAX_ITEMS:
        del _items[: len(_items) - _MAX_ITEMS]  # забываем самые старые


def save() -> None:
    """Сохраняет ключи на диск. Зовём после УСПЕШНОЙ записи в таблицу."""
    _ensure_loaded()
    tmp = DEDUP_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"v": FORMAT_VERSION, "keys": sorted(_keys),
                   "items": _items},
                  f, ensure_ascii=False)
    os.replace(tmp, DEDUP_FILE)  # атомарно: не бьём файл при сбое записи
