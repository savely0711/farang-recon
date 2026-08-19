"""
Проверка питон-части разведки после перехода на мини-CRM «Присутствие».
Ничего не пишет в Google и не ходит в сеть. Запуск: python3 test_recon.py
"""
import json
import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

FAILED = []


def check(name, cond, extra=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        FAILED.append(name)
        print(f"  ❌ {name}" + (f"\n       {extra}" if extra else ""))


# ─────────────── dedup.py ───────────────
print("\n1. Повторы объявлений (dedup.py)")
import dedup  # noqa: E402

tmpdir = tempfile.mkdtemp()
dedup.DEDUP_FILE = os.path.join(tmpdir, "dedup.json")
dedup.load()

TEXT = "Продам айфон 13, 15000 бат, Джомтьен"
dedup.remember("ivan", TEXT, "Барахолка")
check("тот же автор и тот же текст — повтор", dedup.is_dup("ivan", TEXT, "Барахолка"))
check("тот же автор, другой текст — новое объявление",
      not dedup.is_dup("ivan", "Продам макбук, 30000 бат", "Барахолка"))
check("другой автор, тот же текст — новое объявление",
      not dedup.is_dup("petr", TEXT, "Барахолка"))
check("@ и регистр ника не важны", dedup.is_dup("@IVAN", TEXT, "Барахолка"))
check("эмодзи, регистр и лишние пробелы не создают новую строку",
      dedup.is_dup("ivan", "🔥ПРОДАМ  Айфон 13 — 15000 бат!!! Джомтьен🔥", "Барахолка"))
check("изменённая цена = новое объявление (так и задумано)",
      not dedup.is_dup("ivan", "Продам айфон 13, 12000 бат, Джомтьен", "Барахолка"))

dedup.remember(None, "Отдам диван даром, Наклуа", "Барахолка")
check("пост без ника запоминается по каналу",
      dedup.is_dup("", "Отдам диван даром, Наклуа", "Барахолка"))
check("тот же текст без ника в ДРУГОМ канале — отдельное объявление",
      not dedup.is_dup("", "Отдам диван даром, Наклуа", "Аренда Паттайя"))
check("безымянный и именной ключи не склеиваются",
      dedup.make_key(None, TEXT, "Барахолка") != dedup.make_key("ivan", TEXT, "Барахолка"))

dedup.save()
with open(dedup.DEDUP_FILE, encoding="utf-8") as f:
    saved = json.load(f)
check("файл сохранён во втором формате", saved.get("v") == 2, str(saved)[:120])

# старый формат (ключи по никам) должен обнулиться
with open(dedup.DEDUP_FILE, "w", encoding="utf-8") as f:
    json.dump({"keys": ["deadbeef"]}, f)
dedup._keys = None
dedup.load()
check("файл старого формата сбрасывается", dedup._keys == set())

# ─────────────── classify.py ───────────────
print("\n2. Разбор ответа ИИ (classify.py)")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
import classify  # noqa: E402


def fake_client(payload_text):
    msg = types.SimpleNamespace(content=[types.SimpleNamespace(text=payload_text)])
    messages = types.SimpleNamespace(create=lambda **kw: msg)
    return types.SimpleNamespace(messages=messages)


classify._get_client = lambda: fake_client(
    '{"is_listing": true, "category": "realty", "price_thb": 25000, "is_business": true}')
r = classify.classify("Сдаём кондо, у нас в наличии 40 объектов")
check("бизнес распознан", r["is_business"] is True and r["seller_type"] == "бизнес", str(r))
check("категория и цена не сломались", r["category"] == "realty" and r["price_thb"] == 25000)

classify._get_client = lambda: fake_client(
    '{"is_listing": true, "category": "electronics", "price_thb": 15000, "is_business": false}')
r = classify.classify("Продам свой айфон")
check("частник распознан", r["is_business"] is False and r["seller_type"] == "частник", str(r))

classify._get_client = lambda: fake_client(
    '{"is_listing": true, "category": "electronics", "price_thb": 100}')
r = classify.classify("Старый ответ без нового поля")
check("ответ без is_business не роняет разбор (считаем частником)",
      r["seller_type"] == "частник", str(r))


def boom():
    raise RuntimeError("нет связи")


classify._get_client = boom
r = classify.classify("любой текст")
check("сбой ИИ: пост не теряется и уезжает в основную таблицу",
      r["category"] == "other" and r["seller_type"] == "частник", str(r))

r = classify.classify("")
check("пустой текст — не объявление", r["is_listing"] is False and "seller_type" in r)

# Разбор «грязных» ответов — в боевом логе такое реально встречалось
d = classify._extract_json(
    '{"is_listing": true, "category": "auto", "price_thb": 5000, "is_business": false}\n\n'
    'Пояснение: {"почему": "продаёт свой байк"}')
check("два JSON подряд: берём первый (раньше падало «Extra data»)",
      d["category"] == "auto" and d["price_thb"] == 5000, str(d))

d = classify._extract_json(
    '```json\n{"is_listing": true, "category": "other", "price_thb": null, '
    '"is_business": true}\n```')
check("ответ в ```json``` разбирается", d["is_business"] is True, str(d))

d = classify._extract_json(
    'Вот разбор: {"is_listing": true, "category": "realty", '
    '"price_thb": 20000, "is_business": false, "note": "цена {за месяц}"}')
check("вложенные скобки внутри строки не ломают разбор",
      d["category"] == "realty" and d["price_thb"] == 20000, str(d))

try:
    classify._extract_json("тут вообще нет ответа")
    check("текст без JSON поднимает ошибку", False)
except ValueError:
    check("текст без JSON поднимает ошибку", True)

# ─────────────── sheets.py ───────────────
print("\n3. Подготовка строки для таблицы (sheets.py)")
import sheets  # noqa: E402
from categories import ALL_CATEGORIES  # noqa: E402
from datetime import datetime  # noqa: E402

row = sheets.Sheet._row({
    "author": "ivan", "link": "https://t.me/g/1", "channel": "Барахолка",
    "category": "realty", "date": datetime(2026, 8, 17, 10, 30),
    "snippet": "Кондо\nу моря", "seller_type": "бизнес",
})
check("slug категории уходит в таблицу (по нему выбирается вкладка)",
      row["category_slug"] == "realty", str(row))
check("человекочитаемая категория тоже на месте",
      row["category"] == ALL_CATEGORIES["realty"], str(row["category"]))
check("тип продавца уходит в таблицу", row["seller_type"] == "бизнес")
check("перенос строки в описании убран", "\n" not in row["snippet"])

row_no_nick = sheets.Sheet._row({
    "author": None, "link": "https://t.me/g/2", "channel": "Барахолка",
    "category": "other", "date": datetime(2026, 8, 17, 11, 0),
    "snippet": "Диван", "seller_type": "частник",
})
check("объявление без ника готовится к записи (а не выбрасывается)",
      row_no_nick["author"] == "" and row_no_nick["link"] == "https://t.me/g/2")

# ─────────────── outreach_queue.py ───────────────
print("\n4. Очередь первого касания (outreach_queue.py)")
import outreach_queue  # noqa: E402

outreach_queue.QUEUE_FILE = os.path.join(tmpdir, "q.jsonl")
outreach_queue.enqueue("ivan", "https://t.me/g/1", None)
outreach_queue.enqueue(None, "https://t.me/g/2", None)
outreach_queue.enqueue("", "https://t.me/g/3", None)
q = outreach_queue.read_all()
check("в рассылку попал только автор с ником", len(q) == 1 and q[0]["author"] == "ivan",
      json.dumps(q, ensure_ascii=False))

# ─────────────── build.py (сборка карточки, этап 4) ───────────────
print("\n5. Сборка карточки объявления (build.py)")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
import build  # noqa: E402


class _FakeResp:
    def __init__(self, text):
        self.content = [types.SimpleNamespace(text=text)]


def fake_ai(answer):
    """Подменяет вызов ИИ заранее заданным ответом."""
    client = types.SimpleNamespace(
        messages=types.SimpleNamespace(create=lambda **kw: _FakeResp(answer))
    )
    build._client = client
    return client


fake_ai('{"ok": true, "title": "iPhone 13 128 ГБ", "description": "Состояние отличное.",'
        ' "price_thb": 15000, "is_free": false, "is_negotiable": false,'
        ' "category": "electronics"}')
card = build.build_listing("Продам айфон 13, 15000 бат, пишите в личку @ivan")
check("карточка собрана", card["ok"] and card["title"] == "iPhone 13 128 ГБ",
      json.dumps(card, ensure_ascii=False))
check("цена числом", card["price_thb"] == 15000 and not card["is_free"])

fake_ai('{"ok": false}')
check("не объявление — отказ", not build.build_listing("Кто знает хорошего врача?")["ok"])

fake_ai('{"ok": true, "title": "Диван", "description": "", "price_thb": null,'
        ' "is_free": false, "is_negotiable": false, "category": "furniture"}')
check("без цены и без «даром» — не публикуем",
      not build.build_listing("Отдам диван")["ok"])

fake_ai('{"ok": true, "title": "Диван", "description": "", "price_thb": null,'
        ' "is_free": true, "is_negotiable": false, "category": "furniture"}')
free = build.build_listing("Отдам диван даром")
check("«даром» проходит без цены", free["ok"] and free["is_free"] and free["price_thb"] is None)

fake_ai('{"ok": true, "title": "Байк", "description": "", "price_thb": 500,'
        ' "is_free": false, "is_negotiable": true, "category": "auto"}')
both = build.build_listing("Сдам байк 500 бат, торг")
check("цена сильнее «договорной»", both["price_thb"] == 500 and not both["is_negotiable"])

fake_ai('{"ok": true, "title": "Что-то", "description": "", "price_thb": 100,'
        ' "is_free": false, "is_negotiable": false, "category": "other"}')
check("категория other на сайт не идёт", not build.build_listing("Всякое")["ok"])


def boom(**kw):
    raise RuntimeError("ИИ недоступен")


build._client = types.SimpleNamespace(
    messages=types.SimpleNamespace(create=boom)
)
check("сбой ИИ не роняет прогон", not build.build_listing("Продам стол")["ok"])

# ─────────────── prepare.py (разбор ссылки) ───────────────
print("\n6. Авто-подготовка (prepare.py)")
import prepare  # noqa: E402

m = prepare.LINK_RE.match("https://t.me/baraholka_pattaya/12345")
check("ссылка на пост разбирается", bool(m) and m.group(1) == "baraholka_pattaya"
      and m.group(2) == "12345")
check("ссылка со слэшем на конце тоже",
      bool(prepare.LINK_RE.match("https://t.me/g/7/")))
check("чужая ссылка отбрасывается",
      not prepare.LINK_RE.match("https://example.com/g/7"))
check("приватная ссылка (t.me/c/...) не берётся",
      not prepare.LINK_RE.match("https://t.me/c/1234567/89"))

# ─────────────── итог ───────────────
if FAILED:
    print(f"\n⛔ ПРОВАЛЕНО ПРОВЕРОК: {len(FAILED)}\n")
    sys.exit(1)
print("\n🏁 ВСЁ ЗЕЛЁНОЕ\n")
