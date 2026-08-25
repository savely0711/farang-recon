"""
Разбор объявлений о недвижимости ИИ (решение Савелия 25.08.2026).

Правила (`realty_extract.py`) никуда не делись — они работают ПЕРВЫМИ и остаются
страховкой: если ИИ не ответил (кончился баланс Anthropic, сбой сети, мусор
вместо JSON), строка всё равно попадёт в таблицу, просто с тем, что нашли
правила. Прогон из-за ИИ не встаёт никогда.

Что добавляет ИИ поверх правил:
  - тип продавца: агентство или частник (по правилам это не определить);
  - название агентства — если оно названо в тексте или в подписи;
  - жилой комплекс (проект);
  - и уточняет всё остальное: сделку, тип жилья, цену, период, спальни,
    площадь, район — там, где формулировка кривая и правила промахнулись.

Как объединяются (`merge`): за основу берётся разбор правилами, поверх кладутся
непустые ответы ИИ. Колонка «Разбор» в таблице показывает, кто сработал:
«ИИ», «правила» или «ИИ+правила».

Цена: просим ИИ вернуть число в БАТАХ. Если объявление в рублях или долларах,
ИИ так и говорит в поле currency, а пересчётом мы не занимаемся — курс дело
переменчивое, а нам нужна честная картина.
"""
import json
import os

from dotenv import load_dotenv

# Грузим .env здесь, чтобы ключ был доступен независимо от порядка импортов.
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from anthropic import Anthropic  # noqa: E402

from classify import _extract_json  # noqa: E402  — тот же надёжный разбор JSON

_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
# Выключатель на случай «денег нет, но парсить надо»: REALTY_AI=0 → только правила.
AI_ENABLED = os.environ.get("REALTY_AI", "1") != "0"

_client = None

SELLER_AGENCY = "агентство"
SELLER_PRIVATE = "частник"

DEALS = ("аренда", "продажа", "аренда и продажа")
KINDS = ("предложение", "спрос")
PERIODS = ("месяц", "сутки", "год", "всего")
PROP_TYPES = ("студия", "квартира", "кондо", "дом", "вилла", "таунхаус",
              "пентхаус", "комната", "участок", "коммерция")

_SYSTEM = (
    "Ты разбираешь объявления о недвижимости из русскоязычных Telegram-групп "
    "Паттайи (Таиланд). Тексты бывают на русском, английском и тайском, часто "
    "с эмодзи и в свободной форме.\n\n"
    "Верни СТРОГО JSON без пояснений:\n"
    '{"is_realty": bool, "kind": "предложение"|"спрос", '
    '"deal": "аренда"|"продажа"|"аренда и продажа"|null, '
    '"prop_type": "студия"|"квартира"|"кондо"|"дом"|"вилла"|"таунхаус"|'
    '"пентхаус"|"комната"|"участок"|"коммерция"|null, '
    '"price": number|null, "price_max": number|null, '
    '"currency": "THB"|"USD"|"RUB"|"EUR"|null, '
    '"period": "месяц"|"сутки"|"год"|"всего"|null, '
    '"bedrooms": number|null, "area": number|null, '
    '"district": string|null, "project": string|null, '
    '"seller": "агентство"|"частник", "agency": string|null}\n\n'
    "Правила:\n"
    "- is_realty=false для болтовни, вопросов, отзывов и объявлений не про "
    "жильё (мебель, техника, байки, услуги, работа).\n"
    "- kind='спрос', если человек ИЩЕТ жильё («сниму», «ищу квартиру»). "
    "«Ищете квартиру? Поможем» — это предложение агентства, а не спрос.\n"
    "- price: главная цена объекта числом. НЕ бери залог, депозит, комиссию, "
    "коммунальные платежи и цену соседнего объекта. Если названа вилка цен — "
    "price это низ, price_max это верх. Если цены нет — null.\n"
    "- period: за какой срок цена. Для продажи всегда 'всего'.\n"
    "- bedrooms: число спален, студия = 0.\n"
    "- area: площадь в кв. метрах числом.\n"
    "- district: район Паттайи по-русски, как принято говорить: Джомтьен, "
    "На Джомтьен, Пратамнак, Наклуа, Вонгамат, Сои Буакао, Центр Паттайи, "
    "Северная Паттайя, Южная Паттайя, Восточная Паттайя, Банг Сарай, "
    "Банг Ламунг, Хуай Яй, Саттахип. Если назван только жилой комплекс — "
    "определи район по нему. Не знаешь — null.\n"
    "- project: название жилого комплекса латиницей, как в тексте.\n"
    "- seller: 'агентство', если пишет посредник, риелтор, агентство или "
    "менеджер: сдаёт ЧУЖОЕ за комиссию, много объектов сразу, прайс-лист, "
    "«подберём», «у нас в наличии», подпись компании, ник-витрина "
    "(*_realty, *_property, *_rent_pattaya). Собственник, который сдаёт или "
    "продаёт СВОЮ квартиру, — 'частник'. Сомневаешься — 'частник'.\n"
    "- agency: название конторы, если оно есть в тексте или подписи. "
    "Нет названия — null."
)


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def _num(v, lo=None, hi=None):
    if v is None or v is True or v is False:
        return None
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    if lo is not None and n < lo:
        return None
    if hi is not None and n > hi:
        return None
    return int(round(n)) if float(n).is_integer() else round(n, 1)


def _pick(value, allowed):
    v = (value or "").strip().lower() if isinstance(value, str) else ""
    for a in allowed:
        if v == a:
            return a
    return ""


def _str(v, limit=60):
    if not isinstance(v, str):
        return ""
    return v.strip()[:limit]


def parse(text: str) -> dict:
    """Разбор поста ИИ. Всегда возвращает словарь; при любом сбое — пустой
    (ключ 'ok' = False), и тогда наверху остаётся разбор правилами."""
    text = (text or "").strip()
    empty = {"ok": False}
    if not text or not AI_ENABLED:
        return empty
    try:
        resp = _get_client().messages.create(
            model=_MODEL,
            max_tokens=400,
            system=_SYSTEM,
            messages=[{"role": "user", "content": text[:4000]}],
        )
        data = _extract_json(resp.content[0].text)
    except Exception as e:  # noqa: BLE001 — сбой ИИ не роняет прогон
        print(f"  ⚠ ИИ не разобрал пост ({e}); беру разбор правилами")
        return empty

    seller = _pick(data.get("seller"), (SELLER_AGENCY, SELLER_PRIVATE)) or SELLER_PRIVATE
    return {
        "ok": True,
        "is_realty": bool(data.get("is_realty", False)),
        "kind": _pick(data.get("kind"), KINDS),
        "deal": _pick(data.get("deal"), DEALS),
        "prop_type": _pick(data.get("prop_type"), PROP_TYPES),
        "price": _num(data.get("price"), lo=1),
        "price_max": _num(data.get("price_max"), lo=1),
        "currency": _pick(data.get("currency"), ("thb", "usd", "rub", "eur")).upper(),
        "period": _pick(data.get("period"), PERIODS),
        "bedrooms": _num(data.get("bedrooms"), lo=0, hi=20),
        "area": _num(data.get("area"), lo=5, hi=5000),
        "district": _str(data.get("district"), 40),
        "project": _str(data.get("project"), 60),
        "seller": seller,
        "agency": _str(data.get("agency"), 60),
    }


# Поля, которые ИИ может уточнить поверх правил.
_OVERRIDABLE = ("kind", "deal", "prop_type", "price", "price_max", "currency",
                "period", "bedrooms", "area", "district")


def merge(rules: dict, ai: dict) -> dict:
    """Складывает разбор правилами и разбор ИИ в одну строку таблицы.
    За основу — правила, поверх непустые ответы ИИ. Плюс поля, которых у правил
    нет вовсе: тип продавца, агентство, проект. Колонка «Разбор» говорит, кто
    сработал, — чтобы потом было видно, доверять строке или нет."""
    out = dict(rules)
    out.setdefault("project", "")
    out.setdefault("seller", "")
    out.setdefault("agency", "")

    if not ai or not ai.get("ok"):
        out["parsed_by"] = "правила"
        return out

    # Про жильё ли — решает ИИ: он видит смысл, а не слова.
    out["is_realty"] = ai["is_realty"]
    changed = False
    for key in _OVERRIDABLE:
        value = ai.get(key)
        if value not in (None, "", []):
            if out.get(key) != value:
                changed = True
            out[key] = value
    out["project"] = ai.get("project") or ""
    out["seller"] = ai.get("seller") or ""
    out["agency"] = ai.get("agency") or ""
    # Цена за месяц у продажи и наоборот — приводим к здравому смыслу.
    if out.get("deal") == "продажа" and out.get("period") not in ("", "всего"):
        out["period"] = "всего"
    out["parsed_by"] = "ИИ+правила" if changed else "ИИ"
    return out
