"""
ИИ-разбор поста барахолки. Один вызов Claude на пост:
  - объявление ли это о товаре/услуге (или просто болтовня в чате),
  - категория (slug из categories.py),
  - цена в батах (число) или null,
  - тип продавца: частник или бизнес (is_business).

Тип продавца добавлен 17.08.2026 (мини-CRM «Присутствие»): ИИ всё равно читает
текст поста, поэтому признак достаётся тем же единственным запросом — лишних
трат нет. Он нужен, чтобы отделять агентства недвижимости на свою вкладку
таблицы и чтобы потом можно было отделить любой другой тип бизнеса.

Личные данные НЕ извлекаем и НЕ храним (правило Направления 3).
Используется дешёвая быстрая модель (haiku) — как на сайте для модерации.
"""
import json
import os
import re

from dotenv import load_dotenv

# Грузим .env здесь, чтобы ключ был доступен независимо от порядка импортов.
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from anthropic import Anthropic
from categories import ALL_CATEGORIES, CATEGORY_LIST_FOR_PROMPT

_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
_client = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


# ─── Дешёвый предфильтр (без ИИ) ───────────────────────────────────────────
# В активных группах основная масса — короткая болтовня («актуально?», «+»,
# «в лс», комментарии). Чтобы не гонять ИИ на каждом таком сообщении, сначала
# дёшево отсеиваем явный не-товар. Фильтр НАМЕРЕННО щедрый: лучше отправить
# лишнее на ИИ, чем пропустить объявление. Окончательное решение — за ИИ.
MIN_CANDIDATE_LEN = 70  # длинный текст почти всегда содержательный
_KEYWORDS = re.compile(
    r"прода|отда[мю]|даром|беспла|аренд|сда[юёе]|сниму|цена|торг|"
    r"ราคา|บาท|ขาย|เช่า|price|for\s*sale|rent|baht|thb|฿|руб|\bр\.|\$",
    re.IGNORECASE,
)
_PRICE_DIGITS = re.compile(r"\d{4,}")  # 4+ цифр подряд → вероятно цена/характеристика


def is_ad_candidate(text: str) -> bool:
    """True, если сообщение стоит показать ИИ (похоже на объявление)."""
    t = (text or "").strip()
    if not t:
        return False
    if len(t) >= MIN_CANDIDATE_LEN:
        return True
    if _KEYWORDS.search(t):
        return True
    if _PRICE_DIGITS.search(t):
        return True
    return False

_SYSTEM = (
    "Ты разбираешь сообщения из русскоязычных барахолок Паттайи (Таиланд). "
    "Определи, является ли сообщение объявлением о продаже/аренде/услуге, "
    "его категорию и цену в тайских батах.\n\n"
    "Доступные категории (выбери ровно один slug):\n"
    f"{CATEGORY_LIST_FOR_PROMPT}\n\n"
    "Правила:\n"
    "- is_listing=false для болтовни, вопросов, отзывов, поиска («куплю/ищу»), флуда.\n"
    "- is_listing=true только для предложений отдать/продать/сдать что-то.\n"
    "- price_thb: число в батах. Если цена в рублях/долларах или не указана — null. "
    "«Договорная», «даром», «бесплатно» → price_thb=0.\n"
    "- Категорию выбирай по сути предмета. Недвижимость→realty, авто/мото→auto, "
    "услуги/работа→services. Если объявление, но не подходит ничего — other.\n"
    "- is_business: true, если пишет НЕ частное лицо со своей вещью, а бизнес. "
    "Признаки бизнеса: продаёт или сдаёт ЧУЖОЕ за комиссию (агентство, риелтор, "
    "посредник), много объектов или позиций сразу, прайс-лист, «пишите по "
    "вопросам аренды», «у нас в наличии», «работаем с 2015 года», подпись "
    "компании, ник-витрина (например *_realty, *_rent_pattaya, *_shop). "
    "Собственник, который сам сдаёт или продаёт СВОЮ квартиру, машину, вещь — "
    "это частник, is_business=false. Сомневаешься — false.\n"
    "Верни СТРОГО JSON: "
    '{"is_listing": bool, "category": "slug", "price_thb": number|null, '
    '"is_business": bool}'
)


def _extract_json(text: str) -> dict:
    """Достаём JSON даже если модель обернула его в текст/```."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError(f"нет JSON в ответе ИИ: {text!r}")
    return json.loads(m.group(0))


SELLER_PRIVATE = "частник"
SELLER_BUSINESS = "бизнес"


def classify(text: str) -> dict:
    """
    Возвращает {'is_listing': bool, 'category': slug, 'price_thb': int|None,
                'is_business': bool, 'seller_type': 'частник'|'бизнес'}.
    При сбое ИИ — помечает как «other», чтобы не потерять пост (fail-safe);
    тип продавца в этом случае считаем частником (осторожная сторона: строка
    останется в основной таблице, а не уедет на вкладку агентств).
    """
    text = (text or "").strip()
    if not text:
        return {"is_listing": False, "category": "other", "price_thb": None,
                "is_business": False, "seller_type": SELLER_PRIVATE}

    try:
        resp = _get_client().messages.create(
            model=_MODEL,
            max_tokens=200,
            system=_SYSTEM,
            messages=[{"role": "user", "content": text[:4000]}],
        )
        data = _extract_json(resp.content[0].text)
    except Exception as e:  # noqa: BLE001 — любой сбой не должен ронять прогон
        print(f"  ⚠ ИИ не разобрал пост ({e}); помечаю other")
        return {"is_listing": True, "category": "other", "price_thb": None,
                "is_business": False, "seller_type": SELLER_PRIVATE}

    cat = data.get("category")
    if cat not in ALL_CATEGORIES:
        cat = "other"
    price = data.get("price_thb")
    if price is not None:
        try:
            price = int(round(float(price)))
        except (TypeError, ValueError):
            price = None
    is_business = bool(data.get("is_business", False))
    return {
        "is_listing": bool(data.get("is_listing", False)),
        "category": cat,
        "price_thb": price,
        "is_business": is_business,
        "seller_type": SELLER_BUSINESS if is_business else SELLER_PRIVATE,
    }
