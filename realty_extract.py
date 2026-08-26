"""
Разбор объявлений о недвижимости ПРАВИЛАМИ (без ИИ).

Зачем без ИИ (решение Савелия 25.08.2026): контур недвижимости читает только
специализированные группы, где почти каждый пост — про жильё. Гонять ИИ на
каждый пост дорого, а цену, спальни и район в большинстве постов видно обычными
правилами. Если качество разбора окажется низким — точечно добавим ИИ ТОЛЬКО
на непонятые посты (отчёт качества показывает `realtytry.py`).

Что достаём из текста поста:
  is_realty  — про жильё ли это вообще (в смешанной группе отсеивает мебель,
               байки, услуги);
  kind       — «предложение» (сдаю/продаю) или «спрос» (сниму/ищу). Спрос тоже
               записываем: это рыночные данные, но в счётчик агентств он не идёт;
  deal       — аренда / продажа / «аренда и продажа»;
  prop_type  — студия, кондо, дом, вилла, таунхаус, комната, участок, коммерция;
  price      — число; price_max — верх диапазона, если цен несколько;
  currency   — THB / USD / RUB / EUR;
  period     — месяц / сутки / год / всего (для продажи);
  bedrooms   — число спален (студия = 0);
  area       — площадь в кв. м;
  district   — район Паттайи (в т.ч. выведенный из названия крупного проекта).

Пустое поле — не беда: ссылка, ник, дата и текст есть всегда, а счётчик
агентств от разбора вообще не зависит.

Личные данные не собираем (правило Направления 3): телефоны, имена и контакты
из текста НЕ достаём — только характеристики объекта.

Проверка: python3 test_realty.py
"""
import re

# Пробелы бывают неразрывные и тонкие — приводим к обычному, иначе «25 000»
# с неразрывным пробелом не соберётся в одно число.
_SPACES = dict.fromkeys(map(ord, "   ⁠"), " ")

# ─────────────────────────── словари ───────────────────────────

# Сильные признаки жилья: если есть хоть один — это точно про недвижимость.
_STRONG_HOUSING = re.compile(
    r"кондо|квартир|апартамент|студи|вилл|таунхаус|таун-?хаус|пентхаус|"
    r"condo|apartment|studio|villa|townhouse|penthouse|"
    r"спальн|bedroom|\d\s?br\b|ห้องนอน|คอนโด",
    re.IGNORECASE)

# Слабые признаки: сами по себе ничего не значат («мебель для дома»),
# но вместе со сделкой или ценой — уже похоже на жильё.
_WEAK_HOUSING = re.compile(
    r"\bдом\w*|\bжиль[её]|комнат|бунгало|house|room|บ้าน|ที่พัก|"
    r"участ[ко]к|земл[яию]|\bland\b|офис|office|помещени|коммерч",
    re.IGNORECASE)

# Если встретилось это, а сильных признаков жилья нет — пост не про недвижимость
# (в смешанных группах так отсеиваются мебель, техника, байки).
_NOT_HOUSING = re.compile(
    r"мебел|диван|холодильник|стиральн|телевизор|ноутбук|iphone|"
    r"айфон|телефон\b|велосипед|байк|скутер|мотоцикл|мопед|автомобил|\bавто\b|"
    r"\bмашин\w*|коляск|шкаф\b|кроват|матрас|посуд|одежд|обув|виза\b|визаран|"
    r"страхов|массаж|маникюр|курс[ыа]?\b|уроки|вакансия|резюме",
    re.IGNORECASE)

# Спрос: человек ИЩЕТ жильё. Только от первого лица — «Ищете квартиру? Поможем»
# это предложение агентства, а не спрос, поэтому «ищете» сюда не попадает.
_WANTED = re.compile(
    r"\bсниму\b|\bснимем\b|\bищу\b|\bищем\b|\bкуплю\b|\bкупим\b|"
    r"\bнужн[аоы]?\b[^.!?\n]{0,40}(кварт|жиль|дом|студи|кондо|вилл|комнат)|"
    r"\bрассматрива[юе]м?\b[^.!?\n]{0,30}аренд|"
    r"looking\s+for\s+(a\s+)?(condo|apartment|house|room|villa|studio)|"
    r"\bwant\s+to\s+rent\b|\bwanted\b|\bsearching\s+for\b",
    re.IGNORECASE)

_RENT = re.compile(
    r"\bсда[юмёеет]\w*|\bсдаётся|\bсдается|аренд\w*|в\s+рент|"
    r"\brent\b|\bfor\s+rent\b|rental|\blease\b|เช่า|"
    r"долгосрок|краткосрок|посуточн",
    re.IGNORECASE)

_SALE = re.compile(
    r"\bпрода[юмёеет]\w*|\bпродаётся|\bпродается|\bпродаж\w*|\bперепродаж|"
    r"\bfor\s+sale\b|\bsale\b|\bselling\b|ขาย",
    re.IGNORECASE)

# Тип жилья. Порядок важен: первое совпадение и берём (студия перед квартирой,
# иначе «студия/квартира» станет квартирой).
_PROP_TYPES = [
    ("студия",     r"студи[яию]|\bstudio\b|สตูดิโอ"),
    ("пентхаус",   r"пентхаус|penthouse"),
    ("вилла",      r"вилл[аыуе]|\bvilla\b|วิลล่า"),
    ("таунхаус",   r"таун-?хаус|townhouse|town\s?house"),
    ("дом",        r"\bдом\w*|\bhouse\b|บ้าน|бунгало|bungalow"),
    ("кондо",      r"кондо\w*|\bcondo\w*|คอนโด"),
    ("квартира",   r"квартир\w*|апартамент\w*|\bapartment\b|\bapt\b|\bflat\b"),
    ("комната",    r"комнат\w*|\broom\b|ห้องพัก"),
    ("участок",    r"участ[ко]к\w*|\bземл[яию]\b|\bland\b|ที่ดิน"),
    ("коммерция",  r"офис\w*|\boffice\b|помещени\w*|коммерч\w*|магазин\w*|\bshop\b"),
]
_PROP_TYPES = [(name, re.compile(pat, re.IGNORECASE)) for name, pat in _PROP_TYPES]

# Районы Паттайи и окрестностей. Пишут их как угодно — собираем синонимы.
_DISTRICTS = [
    ("На Джомтьен",      r"на\s?-?\s?джом[тч]ь?[еи]н|na\s?-?jomtien|นาจอมเทียน"),
    ("Джомтьен",         r"джом[тч]ь?[еи]н\w*|jomtien|jomthien|จอมเทียน"),
    ("Пратамнак",        r"прат[ау]мнак\w*|pratumnak|pratamnak|เขาพระตำหนัก"),
    ("Вонгамат",         r"вонгамат\w*|wongamat|วงศ์อมาตย์"),
    ("Наклуа",           r"наклуа\w*|na\s?-?klua|naklua|นาเกลือ"),
    ("Сои Буакао",       r"сои?\s?буа\s?-?као|soi\s?bua\s?-?khao|บัวขาว"),
    ("Северная Паттайя", r"север\w*\s+паттай\w*|north\s+pattaya|pattaya\s+nua|"
                         r"พัทยาเหนือ"),
    ("Южная Паттайя",    r"южн\w*\s+паттай\w*|south\s+pattaya|pattaya\s+tai|"
                         r"พัทยาใต้"),
    ("Восточная Паттайя", r"восточн\w*\s+паттай\w*|east\s+pattaya|dark\s?side|"
                          r"т[её]мн\w*\s+сторон\w*"),
    ("Центр Паттайи",    r"центр\w*\s+паттай\w*|central\s+pattaya|pattaya\s+klang|"
                         r"в\s+центре\s+паттай|พัทยากลาง"),
    ("Банг Сарай",       r"банг\s?-?сар[ае]\w*|bang\s?-?saray|บางเสร่"),
    ("Банг Ламунг",      r"банг\s?-?ламунг|bang\s?-?lamung|บางละมุง"),
    ("Хуай Яй",          r"хуай?\s?-?[ья]й|huai\s?-?yai|ห้วยใหญ่"),
    ("Сиам Кантри Клаб", r"сиам\s+кантри|siam\s+country"),
    ("Мабпрачан",        r"мабпрачан|мап\s?-?прачан|mabprachan|map\s?prachan"),
    ("Саттахип",         r"саттахип|sattahip|สัตหีบ"),
    ("Районг",           r"районг|rayong|ระยอง"),
    ("Ко Лан",           r"\bко\s?-?лан\b|koh\s?larn|เกาะล้าน"),
    ("Паттайя",          r"паттай\w*|pattaya|พัทยา"),  # последним: общий случай
]
_DISTRICTS = [(name, re.compile(pat, re.IGNORECASE)) for name, pat in _DISTRICTS]

# Крупные проекты → район. Многие объявления называют только жилой комплекс,
# и без этой таблицы район остался бы пустым.
_PROJECTS = [
    ("Вонгамат", r"riviera\s+wongamat|\bzire\b|baan\s?plai\s?haad|the\s+palm\b|"
                 r"wong\s?amat\s+tower|north\s?point|ananya|ана[нь]я"),
    ("Джомтьен", r"riviera\s+jomtien|lumpini|laguna\s+beach|atlantis\s+condo|"
                 r"grand\s+florida|copacabana|dusit\s+grand\s+park|"
                 r"jomtien\s+beach\s+condo|view\s?talay|вью\s?талай|лагуна\s+бич"),
    ("Пратамнак", r"the\s+peak\s+towers|serenity\s+wongamat|paradise\s+ocean|"
                  r"seven\s+seas\s+cote|cosy\s+beach|the\s+cliff\b|\bunixx\b|юникс"),
    ("Центр Паттайи", r"centric\s+sea|the\s+base\b|riviera\s+monaco|"
                      r"the\s+bay\s?view|city\s+garden|arcadia\s+beach|"
                      r"grand\s+avenue|the\s+edge\b|treetops|empire\s+tower|"
                      r"the\s+trust\b|centara\s+grand"),
    ("Восточная Паттайя", r"the\s+ville\b|siam\s+royal\s+view|mabprachan\s+lake"),
]
_PROJECTS = [(name, re.compile(pat, re.IGNORECASE)) for name, pat in _PROJECTS]

# ─────────────────────────── цена ───────────────────────────

# Число: «25 000», «25,000», «25.000», «25000», «1.5». Разделители тысяч
# разбираем отдельно — здесь только собираем сам кусок текста.
_NUM = r"\d{1,3}(?:[ .,]\d{3})+|\d+(?:[.,]\d+)?"
_MULT_K = re.compile(r"^(к|k|тыс\.?|тысяч[а-я]*)$", re.IGNORECASE)
_MULT_M = re.compile(r"^(млн\.?|mln|million|m|м)$", re.IGNORECASE)

_PRICE_RE = re.compile(
    r"(?P<pre>[฿$€])?\s*"
    r"(?P<num>" + _NUM + r")\s*"
    r"(?P<mult>кк|kk|к|k|тыс\.?|тысяч[а-я]*|млн\.?|mln|million|m|м)?\s*"
    r"(?P<cur>бат\w*|baht|thb|฿|บาท|руб\w*|₽|rub|\$|usd|долл\w*|€|eur)?",
    re.IGNORECASE)

_CUR_MAP = [
    ("THB", re.compile(r"^(бат|baht|thb|฿|บาท)", re.IGNORECASE)),
    ("RUB", re.compile(r"^(руб|₽|rub)", re.IGNORECASE)),
    ("USD", re.compile(r"^(\$|usd|долл)", re.IGNORECASE)),
    ("EUR", re.compile(r"^(€|eur)", re.IGNORECASE)),
]

# Единицы, после которых число — это НЕ цена (площадь, этаж, расстояние).
_AFTER_NOT_PRICE = re.compile(
    r"^\s*(кв\.?\s?м|м2|м²|m2|m²|sq\.?\s?m|sqm|ตร\.?ม|этаж|floor|"
    r"км\b|km\b|мин\w*|min\b|%|человек|чел\.|год[ау]?\b|года|лет\b|"
    r"спальн|спален|bedroom|комнат|bath|ванн)", re.IGNORECASE)
# Телефоны вырезаем из текста ДО поиска цен: «+66 81 234 5678» иначе распадается
# на куски, и «5678» уезжает в цену. Режем только то, что явно телефон —
# начинается с «+» или стоит после слова «тел/whatsapp/line». Диапазон цен
# «25 000 - 30 000» под это правило не попадает и остаётся целым.
_PHONE_STRIP = re.compile(
    r"\+\d[\d\s\-()]{7,}\d|"
    r"(?:тел\w*|phone|whats\s?app|whatsapp|viber|line|ватсап|вотсап|вайбер)"
    r"[^\d\n]{0,6}[\d\s\-()]{7,}\d",
    re.IGNORECASE)

# Числа рядом с этими словами — не цена объекта, а залог, комиссия и счета.
# В выбор главной цены они не идут (иначе «депозит 90 000» станет ценой).
_AUX_BEFORE = re.compile(
    r"(депозит|залог|deposit|комисси\w*|commission|agency\s+fee|"
    r"коммунал\w*|электр\w*|за\s+свет|вод[аыу]\b|water|internet|интернет|"
    r"уборк\w*|cleaning|страхов\w*|insurance|штраф|бронь|предоплат\w*)"
    r"[^\d\n]{0,20}$", re.IGNORECASE)

# Явный диапазон цен: «от 15 000 до 25 000», «25000-30000 бат», «3–5 млн».
_RANGE = re.compile(
    r"(?P<a>" + _NUM + r")\s*(?P<am>кк|kk|к|k|тыс\.?|млн\.?|mln|m|м)?\s*"
    r"(?:бат\w*|baht|thb|฿|บาท)?\s*(?:-|–|—|до|to)\s*"
    r"(?P<b>" + _NUM + r")\s*(?P<bm>кк|kk|к|k|тыс\.?|млн\.?|mln|m|м)?",
    re.IGNORECASE)

_PERIOD_MONTH = re.compile(
    r"/\s?мес|в\s+месяц|за\s+месяц|мес\.?\b|месяц\w*|/\s?mo\b|per\s+month|"
    r"month\w*|monthly|เดือน|долгосрок\w*|long\s?-?\s?term",
    re.IGNORECASE)
_PERIOD_DAY = re.compile(
    r"/\s?сут|в\s+сутки|за\s+сутки|сутк\w*|/\s?день|в\s+день|посуточн\w*|"
    r"per\s+day|/\s?day|daily|per\s+night|/\s?night|คืน", re.IGNORECASE)
_PERIOD_YEAR = re.compile(
    r"/\s?год|в\s+год|за\s+год|годов\w*|per\s+year|/\s?year|annual|ต่อปี",
    re.IGNORECASE)

# Границы правдоподобия (баты). Аренда в Паттайе — тысячи в месяц,
# продажа — миллионы. Числа вне границ считаем не ценой.
RENT_MIN, RENT_MAX = 1_500, 500_000
SALE_MIN, SALE_MAX = 200_000, 500_000_000


def _to_number(raw: str, mult: str | None) -> float | None:
    """«25 000» → 25000, «1.5» + «млн» → 1500000. None, если не разобрали."""
    s = raw.strip()
    # Разделители тысяч: группы ровно по 3 цифры («25 000», «1,250,000»).
    if re.fullmatch(r"\d{1,3}(?:[ .,]\d{3})+", s):
        value = float(re.sub(r"[ .,]", "", s))
    else:
        value = float(s.replace(",", "."))
    if mult:
        m = mult.strip().lower()
        if m in ("кк", "kk") or _MULT_M.match(m):
            value *= 1_000_000
        elif _MULT_K.match(m):
            value *= 1_000
    return value


def _currency_of(token: str | None, pre: str | None) -> str:
    for name, rx in _CUR_MAP:
        if token and rx.match(token.strip()):
            return name
        if pre and rx.match(pre.strip()):
            return name
    return ""


def _period_near(text: str, end: int) -> str:
    """Период смотрим в 25 символах ПОСЛЕ цены: «25000 бат/мес»."""
    tail = text[end:end + 25]
    if _PERIOD_MONTH.search(tail):
        return "месяц"
    if _PERIOD_DAY.search(tail):
        return "сутки"
    if _PERIOD_YEAR.search(tail):
        return "год"
    return ""


def find_prices(text: str) -> list:
    """Все похожие на цену числа: [{'value', 'currency', 'period'}, ...]."""
    out = []
    for m in _PRICE_RE.finditer(text):
        raw, mult = m.group("num"), m.group("mult")
        cur = _currency_of(m.group("cur"), m.group("pre"))
        after = text[m.end():m.end() + 12]
        before = text[max(0, m.start() - 30):m.start()]
        # Одинокая «м» (или «m») — это миллион ТОЛЬКО рядом с валютой («5M бат»).
        # Иначе это метры: «35 м²», «300 м до моря» — множитель отбрасываем.
        if mult and mult.strip().lower() in ("м", "m") and not cur:
            mult = None
        # «45 кв.м», «12 этаж», «5 мин до моря» — это не цена.
        if not cur and _AFTER_NOT_PRICE.match(after):
            continue
        digits = re.sub(r"\D", "", raw)
        if len(digits) >= 9:      # длинный номер — телефон, а не цена
            continue
        try:
            value = _to_number(raw, mult)
        except ValueError:
            continue
        if value is None:
            continue
        # Без явной валюты верим числу, только если оно похоже на цену.
        if not cur:
            if value < 1_000 or 1990 <= value <= 2100:   # «2024 год» — не цена
                continue
            cur = "THB"   # в тайских группах цена по умолчанию в батах
        out.append({
            "value": int(round(value)),
            "currency": cur,
            "period": _period_near(text, m.end()),
            "aux": bool(_AUX_BEFORE.search(before)),   # залог, коммуналка, комиссия
        })
    return out


def _range_prices(text: str, rent: bool):
    """Явный диапазон «от X до Y» → (низ, верх). Иначе (None, None).
    Только так и получается верхняя цена: без этого «депозит 90 000» или
    годовой платёж превращались бы в мнимый диапазон."""
    lo, hi = (RENT_MIN, RENT_MAX) if rent else (SALE_MIN, SALE_MAX)
    for m in _RANGE.finditer(text):
        try:
            a = _to_number(m.group("a"), m.group("am") or m.group("bm"))
            b = _to_number(m.group("b"), m.group("bm"))
        except ValueError:
            continue
        if a is None or b is None or a >= b:
            continue
        if lo <= a <= hi and lo <= b <= hi:
            return int(round(a)), int(round(b))
    return None, None


def _pick_price(prices: list, deal: str, text: str) -> dict:
    """Выбирает главную цену и верх диапазона.
    Аренда — самое маленькое правдоподобное число (обычно это цена за месяц, а
    рядом стоят залог и годовая); продажа — самое большое."""
    if not prices:
        return {"price": None, "price_max": None, "currency": "", "period": ""}

    rent = deal in ("аренда", "аренда и продажа")
    lo, hi = (RENT_MIN, RENT_MAX) if rent else (SALE_MIN, SALE_MAX)
    real = [p for p in prices if not p["aux"]] or prices
    band = [p for p in real if p["currency"] == "THB" and lo <= p["value"] <= hi]
    if not band:
        band = [p for p in real if lo <= p["value"] <= hi] or real

    main = min(band, key=lambda p: p["value"]) if rent else max(band, key=lambda p: p["value"])

    period = main["period"]
    if not period:
        # Периода у самой цены нет — ищем во всём тексте, иначе ставим по сделке.
        if _PERIOD_DAY.search(text):
            period = "сутки"
        elif _PERIOD_MONTH.search(text):
            period = "месяц"
        elif _PERIOD_YEAR.search(text):
            period = "год"
        else:
            period = "месяц" if rent else "всего"
    if not rent:
        period = "всего"

    low, high = _range_prices(text, rent)
    if low is not None and low <= main["value"] <= high:
        return {"price": low, "price_max": high,
                "currency": main["currency"], "period": period}
    return {
        "price": main["value"],
        "price_max": None,
        "currency": main["currency"],
        "period": period,
    }


# ─────────────────────────── спальни и площадь ───────────────────────────

_STUDIO = re.compile(r"студи[яию]\w*|\bstudio\b|สตูดิโอ", re.IGNORECASE)
_BEDS_NUM = re.compile(
    r"(\d)\s*(?:-|\s)?\s*(?:спален|спальн\w*|\bсп\b|комнатн\w*|"
    r"bedrooms?|beds?\b|br\b|bhk\b|ห้องนอน)", re.IGNORECASE)
_BEDS_WORD = [
    (1, re.compile(r"односпальн|однокомнатн|1-?комн|one\s?bedroom", re.IGNORECASE)),
    (2, re.compile(r"двухспальн|двухкомнатн|2-?комн|two\s?bedroom", re.IGNORECASE)),
    (3, re.compile(r"тр[её]хспальн|тр[её]хкомнатн|3-?комн|three\s?bedroom", re.IGNORECASE)),
    (4, re.compile(r"четыр[её]хкомнатн|four\s?bedroom", re.IGNORECASE)),
]
_AREA = re.compile(
    r"(\d{1,4}(?:[.,]\d+)?)\s*(?:кв\.?\s?м|м2|м²|m2|m²|sq\.?\s?m\b|sqm|ตร\.?ม)",
    re.IGNORECASE)


def _bedrooms(text: str):
    m = _BEDS_NUM.search(text)
    if m:
        n = int(m.group(1))
        if 0 <= n <= 9:
            return n
    for n, rx in _BEDS_WORD:
        if rx.search(text):
            return n
    if _STUDIO.search(text):
        return 0
    return None


def _area(text: str):
    m = _AREA.search(text)
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", "."))
    except ValueError:
        return None
    return v if 8 <= v <= 3000 else None


def _district(text: str) -> str:
    for name, rx in _PROJECTS:      # проект точнее общего «Паттайя»
        if rx.search(text):
            return name
    for name, rx in _DISTRICTS:
        if rx.search(text):
            return name
    return ""


def _prop_type(text: str) -> str:
    for name, rx in _PROP_TYPES:
        if rx.search(text):
            return name
    return ""


def _deal(text: str) -> str:
    rent = bool(_RENT.search(text))
    sale = bool(_SALE.search(text))
    if rent and sale:
        return "аренда и продажа"
    if rent:
        return "аренда"
    if sale:
        return "продажа"
    return ""


EMPTY = {"is_realty": False, "kind": "", "deal": "", "prop_type": "",
         "price": None, "price_max": None, "currency": "", "period": "",
         "bedrooms": None, "area": None, "district": ""}


def extract(text: str) -> dict:
    """Разбирает текст поста. Возвращает словарь полей (см. шапку файла)."""
    t = (text or "").translate(_SPACES)
    if not t.strip():
        return dict(EMPTY)

    deal = _deal(t)
    # Цены ищем в тексте БЕЗ телефонов (см. _PHONE_STRIP).
    clean = _PHONE_STRIP.sub(" ", t)
    # Сделку не назвали, но есть «бат/мес» или «посуточно» — это аренда.
    # Без этой догадки цена за месяц не попадает в границы правдоподобия.
    if not deal and (_PERIOD_MONTH.search(clean) or _PERIOD_DAY.search(clean)):
        deal = "аренда"
    prices = find_prices(clean)
    price = _pick_price(prices, deal, clean)
    beds = _bedrooms(clean)
    area = _area(clean)

    strong = bool(_STRONG_HOUSING.search(t))
    weak = bool(_WEAK_HOUSING.search(t))
    # Про жильё ли: сильный признак — сразу да; слабый — только вместе со
    # сделкой, ценой или спальнями. Мебель, техника и байки без сильного
    # признака отсекаются, даже если в тексте есть слово «дом».
    is_realty = strong or (weak and (bool(deal) or price["price"] or beds is not None))
    if is_realty and not strong and _NOT_HOUSING.search(t):
        is_realty = False

    kind = "спрос" if _WANTED.search(t) else "предложение"

    return {
        "is_realty": bool(is_realty),
        "kind": kind,
        "deal": deal,
        "prop_type": _prop_type(t),
        "price": price["price"],
        "price_max": price["price_max"],
        "currency": price["currency"],
        "period": price["period"],
        "bedrooms": beds,
        "area": area,
        "district": _district(t),
    }


def is_realty_candidate(text: str) -> bool:
    """Дешёвый предфильтр ДО полного разбора: стоит ли вообще смотреть пост.
    Намеренно щедрый — лучше разобрать лишнее, чем пропустить объявление."""
    t = (text or "").strip()
    if len(t) < 25:
        return False
    return bool(_STRONG_HOUSING.search(t) or _WEAK_HOUSING.search(t))
