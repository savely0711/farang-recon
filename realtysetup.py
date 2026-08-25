"""Прописать в .env связь с таблицей «Фаранг — Недвижимость» и проверить её.

Зачем отдельный помощник: в веб-консоли Aeza (VNC) не вводятся заглавные буквы
и «_», поэтому строки вида `REALTY_SHEET_WEBHOOK_URL=…` там руками не набрать.
Скрипт пишет их сам, а адрес и токен принимает как есть — их достаточно один раз
вставить из буфера обмена.

Запуск (в имени файла нет ни заглавных, ни подчёркиваний — набирается в консоли):
    python3 realtysetup.py          → попросит вставить строку «адрес токен»
    python3 realtysetup.py check    → ничего не меняет, только проверяет связь

Вставлять надо ОДНУ строку: сначала адрес скрипта (…/exec), потом пробел, потом
пароль-токен. Порядок можно и обратный — скрипт разберётся сам: адрес тот, что
начинается на https.

Что записывает:
    REALTY_SHEET_WEBHOOK_URL=<адрес>
    REALTY_SHEET_TOKEN=<токен>

После записи скрипт САМ стучится в таблицу (действие «ping») и говорит, сошёлся
ли токен с тем, что вшит в скрипт таблицы. Если тут зелено — `realty_parser.py`
заработает.
"""
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ENV = os.path.join(BASE, ".env")

URL_KEY = "REALTY_SHEET_WEBHOOK_URL"
TOKEN_KEY = "REALTY_SHEET_TOKEN"


def _read_lines() -> list:
    if not os.path.exists(ENV):
        return []
    with open(ENV, "r", encoding="utf-8") as f:
        return f.read().splitlines()


def _get(lines: list, key: str) -> str:
    for ln in lines:
        if ln.startswith(key + "="):
            return ln.split("=", 1)[1].strip()
    return ""


def _set(lines: list, key: str, value: str) -> list:
    out, done = [], False
    for ln in lines:
        if ln.startswith(key + "="):
            out.append(f"{key}={value}")
            done = True
        else:
            out.append(ln)
    if not done:
        out.append(f"{key}={value}")
    return out


def _ping(url: str, token: str) -> bool:
    try:
        import httpx
    except ImportError:
        print("⚠ нет библиотеки httpx: pip3 install httpx --break-system-packages")
        return False
    try:
        r = httpx.Client(timeout=60.0, follow_redirects=True).post(
            url, json={"token": token, "action": "ping"})
        data = r.json()
    except Exception as e:  # noqa: BLE001
        print(f"❌ таблица не ответила: {e}")
        print("   Проверь, что развёртывание сделано с доступом «Все».")
        return False
    if data.get("ok"):
        print(f"✅ связь с таблицей есть. Строк в «Объявлениях»: {data.get('rows', 0)}")
        return True
    print(f"❌ таблица ответила отказом: {data.get('error')}")
    if data.get("error") == "bad token":
        print("   Токен не совпал с тем, что вшит в скрипт таблицы (первая строка кода).")
    return False


def main() -> None:
    lines = _read_lines()
    arg = sys.argv[1] if len(sys.argv) > 1 else ""

    if arg == "check":
        url, token = _get(lines, URL_KEY), _get(lines, TOKEN_KEY)
        if not url:
            print(f"В .env пока нет {URL_KEY}. Запусти без слова check.")
            return
        _ping(url, token)
        return

    raw = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else input(
        "Вставь строку «адрес токен» и нажми Enter:\n> ")
    parts = [p.strip() for p in raw.replace("\t", " ").split() if p.strip()]
    url = next((p for p in parts if p.startswith("http")), "")
    token = next((p for p in parts if not p.startswith("http")), "")

    if not url or not token:
        print("❌ Нужны ДВА куска: адрес (начинается на https) и токен, через пробел.")
        return
    if not url.endswith("/exec"):
        print("⚠ адрес обычно заканчивается на /exec — проверь, что скопировал целиком.")

    lines = _set(lines, URL_KEY, url)
    lines = _set(lines, TOKEN_KEY, token)
    with open(ENV, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip() + "\n")
    print(f"✅ записал в .env: {URL_KEY} и {TOKEN_KEY}")
    _ping(url, token)


if __name__ == "__main__":
    main()
