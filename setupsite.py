"""Прописать в .env настройки связи с сайтом (этап 4, prepare.py) и проверить их.

Зачем отдельный помощник: в веб-консоли Aeza (VNC) не вводятся заглавные буквы
и «_», поэтому строки вида `RECON_API_TOKEN=…` там руками не набрать. Скрипт
пишет их сам, а сам пароль-токен принимает как есть — его достаточно вставить
из буфера обмена (или передать первым аргументом).

Запуск (только строчные буквы, подчёркиваний в имени файла нет):
    python3 setupsite.py            → спросит токен и вставит всё в .env
    python3 setupsite.py <токен>    → то же самое без вопросов
    python3 setupsite.py check      → ничего не меняет, только проверяет связь

Что записывает:
    SITE_API_URL=https://farang.market/api/recon
    RECON_API_TOKEN=<то, что вы вставили>
    PREPARE_LIMIT=30
    PREPARE_MAX_AGE_DAYS=30
    PREPARE_MAX_PHOTOS=6

После записи скрипт САМ стучится на сайт (действие «ping») и говорит, сошёлся
ли токен с тем, что лежит в переменных Vercel. Это главная проверка: если тут
зелено, `prepare.py` заработает.
"""
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ENV = os.path.join(BASE, ".env")

DEFAULTS = [
    ("SITE_API_URL", "https://farang.market/api/recon"),
    ("PREPARE_LIMIT", "30"),
    ("PREPARE_MAX_AGE_DAYS", "30"),
    ("PREPARE_MAX_PHOTOS", "6"),
]


def _read_lines() -> list:
    if not os.path.exists(ENV):
        return []
    with open(ENV, "r", encoding="utf-8") as f:
        return f.read().splitlines()


def set_key(lines: list, key: str, value: str) -> list:
    """Заменяет строку KEY=… (или закомментированную #KEY=…), либо дописывает."""
    line = f"{key}={value}"
    out, replaced = [], False
    for ln in lines:
        st = ln.strip()
        if st.startswith(key + "=") or st.startswith("#" + key + "="):
            if not replaced:
                out.append(line)
                replaced = True
        else:
            out.append(ln)
    if not replaced:
        out.append(line)
    return out


def write_env(token: str) -> None:
    lines = _read_lines()
    for key, value in DEFAULTS:
        lines = set_key(lines, key, value)
    lines = set_key(lines, "RECON_API_TOKEN", token)
    with open(ENV, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip("\n") + "\n")


def mask(token: str) -> str:
    if len(token) <= 10:
        return "*" * len(token)
    return f"{token[:6]}…{token[-4:]} (длина {len(token)})"


def check() -> int:
    """Стучится на сайт действием «ping». Возвращает код выхода."""
    from dotenv import load_dotenv
    load_dotenv(ENV, override=True)

    url = (os.environ.get("SITE_API_URL") or "").strip()
    token = (os.environ.get("RECON_API_TOKEN") or "").strip()
    if not url or not token:
        print("В .env нет SITE_API_URL и/или RECON_API_TOKEN — проверять нечего.")
        return 1

    import httpx
    print(f"Стучусь на {url} …")
    try:
        r = httpx.post(url, json={"token": token, "action": "ping"},
                       timeout=30.0, follow_redirects=True)
    except Exception as e:  # noqa: BLE001
        print(f"НЕ ДОЗВОНИЛСЯ: {type(e).__name__}: {e}")
        return 1

    if r.status_code == 404:
        print("Сайт ответил 404. Это значит, что переменной RECON_API_TOKEN нет "
              "в Vercel (без неё точка приёма выключена). Добавьте её и "
              "дождитесь нового развёртывания.")
        return 1
    try:
        data = r.json()
    except Exception:  # noqa: BLE001
        print(f"Сайт ответил {r.status_code}, но не JSON. Тело: {r.text[:200]}")
        return 1

    if data.get("ok"):
        print("ГОТОВО: сайт отвечает, токен сошёлся. Можно запускать prepare.py.")
        return 0
    if data.get("error") == "bad_token":
        print("Сайт отвечает, но ТОКЕН НЕ СОВПАЛ с тем, что в Vercel. "
              "Проверьте, что вставили одно и то же значение в оба места.")
        return 1
    print(f"Сайт ответил: {data}")
    return 1


def main() -> int:
    arg = sys.argv[1].strip() if len(sys.argv) > 1 else ""

    if arg.lower() == "check":
        return check()

    token = arg
    if not token:
        print("Вставьте пароль-токен (тот же, что в переменной RECON_API_TOKEN "
              "в Vercel) и нажмите Enter:")
        try:
            token = input("> ").strip()
        except EOFError:
            token = ""
    if not token:
        print("Пусто — ничего не меняю.")
        return 1

    write_env(token)
    print(f"Записал в .env: RECON_API_TOKEN={mask(token)}")
    for key, value in DEFAULTS:
        print(f"Записал в .env: {key}={value}")
    print()
    return check()


if __name__ == "__main__":
    raise SystemExit(main())
