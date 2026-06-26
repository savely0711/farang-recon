"""
ИИ-разбор поста барахолки. Один вызов Claude на пост:
  - объявление ли это о товаре/услуге (или просто болтовня в чате),
  - категория (slug из categories.py),
  - цена в батах (число) или null.

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
    "Верни СТРОГО JSON: "
    '{"is_listing": bool, "category": "slug", "price_thb": number|null}'
)


def _extract_json(text: str) -> dict:
    """Достаём JSON даже если модель обернула его в текст/```."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError(f"нет JSON в ответе ИИ: {text!r}")
    return json.loads(m.group(0))


def classify(text: str) -> dict:
    """
    Возвращает {'is_listing': bool, 'category': slug, 'price_thb': int|None}.
    При сбое ИИ — помечает как «other», чтобы не потерять пост (fail-safe).
    """
    text = (text or "").strip()
    if not text:
        return {"is_listing": False, "category": "other", "price_thb": None}

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
        return {"is_listing": True, "category": "other", "price_thb": None}

    cat = data.get("category")
    if cat not in ALL_CATEGORIES:
        cat = "other"
    price = data.get("price_thb")
    if price is not None:
        try:
            price = int(round(float(price)))
        except (TypeError, ValueError):
            price = None
    return {
        "is_listing": bool(data.get("is_listing", False)),
        "category": cat,
        "price_thb": price,
    }
