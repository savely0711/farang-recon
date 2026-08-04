"""
Карта каналов для чтения. Источник правды по составу — Google-таблица
«Фаранг — Разведка рынка». Здесь — рабочий список для парсера.

Начинаем с топ-3 лидеров (проверенные юзернеймы). Остальные добавим
после первого прогона (часть юзернеймов уточняется уже с аккаунта).

Каждый канал:
  username  — без @ (для построения ссылок t.me/<username>/<id>)
  title     — короткое имя для вкладки в таблице
  tab       — имя вкладки Google-таблицы (создаётся автоматически)
"""

CHANNELS = [
    {
        "username": "pattaya01",
        "title": "Паттайя Барахолка №1",
        "tab": "pattaya01",
    },
    {
        "username": "baraholka_pattaya",
        "title": "Барахолка Паттайя (SEA)",
        "tab": "baraholka_pattaya",
    },
    {
        "username": "baraholka_pattaya_ru",
        "title": "Объявления Паттайя (SEA)",
        "tab": "baraholka_pattaya_ru",
    },
    # --- добавлены 03.08.2026 (проверены: открытые, живые) ---
    # @pattaya2nd не берём: Савелий не смог вступить в группу.
    {
        "username": "Pattaia_barakholka",
        "title": "Паттайа Чат Объявления Барахолка №1",   # ~6,3 тыс. участников
        "tab": "Pattaia_barakholka",
    },
    {
        "username": "barakholka_pattaia",
        "title": "Паттайя Барахолка / Объявления",   # ~11,2 тыс.
        "tab": "barakholka_pattaia",
    },
    {
        "username": "pattaya_baraholka77",
        "title": "Паттайя Объявления | Барахолка",   # ~4,8 тыс.
        "tab": "pattaya_baraholka77",
    },
    {
        "username": "pattaya_happy_ads",
        "title": "Паттайя - Объявления/Барахолка",   # ~10 тыс.
        "tab": "pattaya_happy_ads",
    },
]
