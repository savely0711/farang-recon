"""
Сборка объявления для сайта из поста барахолки (этап 4 мини-CRM «Присутствие»).

classify.py отвечает на вопрос «это объявление и какое», а этот модуль готовит
из поста ГОТОВУЮ КАРТОЧКУ: заголовок, чистое описание, цену, категорию. Один
вызов дешёвой модели (haiku) на пост — тот же, что и в classify.

Почему отдельный вызов, а не один общий. Разбор всех постов подряд (classify)
идёт по десяткам тысяч сообщений и должен быть максимально дешёвым: 200 токенов
ответа. Сборка карточки нужна только для тех немногих постов, чей автор дал
согласие — их единицы. Смешивать эти два запроса значило бы платить за длинный
ответ на каждом посте барахолки.

ЧТО ВЫРЕЗАЕМ ИЗ ОПИСАНИЯ (важно, это требование политики и правил площадки):
телефоны, ники, ссылки, адреса, приглашения «пишите в личку» и любые контакты.
Связь с продавцом на сайте — только кнопкой «Написать в Телеграм», а контакты
в тексте это и спам, и обход правил, и лишние персональные данные.
"""
import json
import os

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from anthropic import Anthropic  # noqa: E402

from categories import CATEGORY_LIST_FOR_PROMPT  # noqa: E402
from classify import _extract_json  # noqa: E402

_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
_client = None

# Категории, которые на сайт не идут: «other» — не товар.
SKIP_CATEGORIES = {"other"}

_SYSTEM = (
    "Ты готовишь карточку объявления для площадки объявлений в Паттайе "
    "(Таиланд) из поста, который продавец опубликовал в Telegram-барахолке. "
    "Продавец разрешил нам разместить его объявление у себя.\n\n"
    "Доступные категории (выбери ровно один slug):\n"
    f"{CATEGORY_LIST_FOR_PROMPT}\n\n"
    "Правила:\n"
    "- title: короткий заголовок, 3–7 слов, на языке поста, без цены, без "
    "CAPS, без эмодзи, без восклицательных знаков. Что продаётся — и всё.\n"
    "- description: текст поста, приведённый в порядок, НЕ ДЛИННЕЕ 1500 знаков. "
    "Если в посте перечислен целый каталог (десятки позиций) — оставь общее "
    "описание и несколько примеров, остальное опусти. СОХРАНИ смысл, "
    "характеристики, состояние, комплектацию, условия. УДАЛИ полностью: "
    "телефоны, ники и @упоминания, ссылки, адреса, «пишите в личку», "
    "«+ в комментарии», названия чатов, эмодзи-мусор, повторы, хештеги. "
    "Не выдумывай ничего, чего нет в посте. Язык оставь как в посте.\n"
    "- price_thb: цена в тайских батах числом. Цена в другой валюте или её "
    "нет — null.\n"
    "- is_free: true, если отдают даром/бесплатно.\n"
    "- is_negotiable: true, если цена «договорная» и числа нет.\n"
    "- category: slug по сути предмета.\n"
    "- subcategory: точная подкатегория сайта из списка ниже (slug). Если "
    "подходящей нет — null.\n"
    "- district: район Паттайи из списка ниже (slug), если он назван или "
    "однозначно понятен из поста. Не уверен — null. НЕ УГАДЫВАЙ.\n"
    "- attrs: объект с признаками из списка ниже — только те, что явно "
    "следуют из текста поста. Ключи и значения брать РОВНО те, что даны "
    "(для select — value, для multiselect — список value, для чисел — "
    "число без единиц). Чего в посте нет — не выдумывай, просто пропусти.\n"
    "- ok: false, если это НЕ объявление о продаже/аренде/услуге (болтовня, "
    "«куплю», «ищу», отзыв), либо если из поста невозможно понять, что "
    "продаётся. В этом случае остальные поля можно оставить пустыми.\n\n"
    "Ответь ТОЛЬКО JSON, без пояснений:\n"
    '{"ok": bool, "title": "…", "description": "…", "price_thb": number|null, '
    '"is_free": bool, "is_negotiable": bool, "category": "slug", '
    '"subcategory": "slug"|null, "district": "slug"|null, "attrs": {}}'
)


def _schema_hint(schema: dict) -> str:
    """Человекочитаемый кусок подсказки: подкатегории, районы, признаки.

    Справочник приходит С САЙТА (действие schema точки /api/recon), а не лежит
    копией здесь — чтобы новые подкатегории и признаки подхватывались сами.
    Пустой справочник = подсказки нет, ИИ просто не заполнит эти поля.
    """
    if not schema:
        return ""
    lines = []

    subs = schema.get("subcategories") or []
    if subs:
        lines.append("\nПОДКАТЕГОРИИ САЙТА (поле subcategory, выбери одну):")
        for s in subs:
            sec = s.get("section") or "—"
            lines.append(f"- {s['slug']}: {s['name']} (раздел {sec})")

    dists = schema.get("districts") or []
    if dists:
        lines.append("\nРАЙОНЫ ПАТТАЙИ (поле district):")
        lines.append(", ".join(f"{d['slug']} — {d['name']}" for d in dists))

    attrs = schema.get("attrs") or {}
    if attrs:
        lines.append("\nПРИЗНАКИ (поле attrs). Применять только к своему разделу:")
        for section, defs in attrs.items():
            lines.append(f"  Раздел {section}:")
            for d in defs:
                bits = [f"    {d['key']} ({d['type']}) — {d['name']}"]
                if d.get("unit"):
                    bits.append(f", в {d['unit']}")
                subcats = d.get("subcats")
                if subcats and subcats != "*":
                    bits.append(f"; только для: {', '.join(subcats)}")
                show = d.get("showIf")
                if show:
                    bits.append(
                        f"; только если {show['key']} = {'/'.join(show['values'])}")
                opts = d.get("options")
                if opts:
                    bits.append("; варианты: "
                                + ", ".join(f"{o['value']}={o['name']}" for o in opts))
                lines.append("".join(bits))

    return "\n".join(lines)


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def build_listing(text: str, schema: dict | None = None) -> dict:
    """
    Готовит карточку из текста поста.

    Возвращает {'ok': bool, 'reason': str, 'title', 'description',
                'price_thb', 'is_free', 'is_negotiable', 'category'}.
    При любом сбое возвращает ok=False с причиной — прогон не роняем никогда.
    """
    fail = {"ok": False, "reason": "", "title": "", "description": "",
            "price_thb": None, "is_free": False, "is_negotiable": False,
            "category": "other", "subcategory": None, "district": None,
            "attrs": {}}

    text = (text or "").strip()
    if not text:
        return {**fail, "reason": "пустой пост"}

    try:
        resp = _get_client().messages.create(
            model=_MODEL,
            max_tokens=2000,
            system=_SYSTEM + _schema_hint(schema or {}),
            messages=[{"role": "user", "content": text[:6000]}],
        )
        # Обрыв по лимиту токенов даёт неполный JSON — ловим это отдельно,
        # чтобы в логе было видно причину, а не общее «нет JSON в ответе».
        if getattr(resp, "stop_reason", None) == "max_tokens":
            return {**fail, "reason": "пост слишком длинный, ИИ не уложился в ответ"}
        data = _extract_json(resp.content[0].text)
    except Exception as e:  # noqa: BLE001
        return {**fail, "reason": f"ИИ не ответил: {e}"}

    if not data.get("ok"):
        return {**fail, "reason": "ИИ: это не объявление о продаже"}

    title = str(data.get("title") or "").strip()[:120]
    if not title:
        return {**fail, "reason": "ИИ не смог составить заголовок"}

    category = data.get("category")
    if category in SKIP_CATEGORIES or not category:
        return {**fail, "reason": f"категория «{category}» на сайт не идёт"}

    price = data.get("price_thb")
    if price is not None:
        try:
            price = int(round(float(price)))
        except (TypeError, ValueError):
            price = None
    if price is not None and price <= 0:
        price = None

    is_free = bool(data.get("is_free"))
    is_negotiable = bool(data.get("is_negotiable")) and not is_free
    if price is None and not is_free and not is_negotiable:
        return {**fail, "reason": "цена не разобрана"}
    if price is not None:
        is_negotiable = False

    sub = data.get("subcategory")
    district = data.get("district")
    attrs = data.get("attrs")
    if not isinstance(attrs, dict):
        attrs = {}

    return {
        "ok": True,
        "reason": "",
        "title": title,
        "description": str(data.get("description") or "").strip()[:4000],
        "price_thb": None if (is_free or is_negotiable) else price,
        "is_free": is_free,
        "is_negotiable": is_negotiable,
        "category": category,
        # Значения не проверяем здесь: сайт всё равно чистит их по своему
        # конфигу (sanitizeAttrs) — двойная проверка только разъедется.
        "subcategory": str(sub).strip() if sub else None,
        "district": str(district).strip() if district else None,
        "attrs": attrs,
    }


if __name__ == "__main__":  # ручная проверка: python3 build.py "текст поста"
    import sys
    print(json.dumps(build_listing(" ".join(sys.argv[1:])),
                     ensure_ascii=False, indent=2))
