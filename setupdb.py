"""Подготовить сервер к резервным копиям базы: поставить pg_dump и записать
строку подключения в .env.

Зачем отдельный помощник: в веб-консоли Aeza не вводятся заглавные буквы,
«_» и «&», поэтому ни `apt install postgresql-client`, ни строку вида
`DB_URL=postgresql://…` там руками не набрать. Скрипт делает это сам, а саму
строку подключения принимает как есть - её достаточно вставить из буфера.

Запуск (имя файла без подчёркиваний - его можно напечатать в консоли Aeza):
    python3 setupdb.py            → поставит pg_dump, спросит строку, проверит
    python3 setupdb.py check      → ничего не меняет, только проверяет

Где взять строку подключения: Supabase → проект → кнопка «Connect» вверху →
вкладка «Direct connection string» → пункт «Session pooler» → кнопка
копирования у строки. Вставляется она ЦЕЛИКОМ, одним куском - логин и пароль
внутри неё, отдельно ничего вводить не надо.

Supabase отдаёт строку с заглушкой [YOUR-PASSWORD] вместо пароля. Вписывать
его руками в консоли Aeza невозможно (там нет заглавных букв), поэтому скрипт
увидит заглушку и попросит вставить пароль ВТОРЫМ куском - тоже из буфера.
Подставит сам. Пароль нигде не показывается и не пишется, кроме .env на этом
сервере (файл закрыт от чужих глаз, права 600).
"""
import os
import re
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ENV = os.path.join(BASE, ".env")


def _read_lines() -> list:
    if not os.path.exists(ENV):
        return []
    with open(ENV, "r", encoding="utf-8") as f:
        return f.read().splitlines()


def set_key(lines: list, key: str, value: str) -> list:
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


def mask(url: str) -> str:
    """Показать строку без пароля: postgresql://user:****@host/db"""
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:****@", url)


def have_pgdump() -> str:
    from shutil import which
    import glob
    found = which("pg_dump")
    if found:
        return found
    cands = sorted(glob.glob("/usr/lib/postgresql/*/bin/pg_dump"), reverse=True)
    return cands[0] if cands else ""


def install_pgdump() -> str:
    print("ставлю postgresql-client (это минута)...")
    env = dict(os.environ, DEBIAN_FRONTEND="noninteractive")
    subprocess.run(["apt-get", "update", "-qq"], env=env)
    subprocess.run(["apt-get", "install", "-y", "-qq", "postgresql-client"], env=env)
    return have_pgdump()


def check() -> int:
    from dotenv import load_dotenv
    load_dotenv(ENV, override=True)

    pgdump = have_pgdump()
    if not pgdump:
        print("НЕТ pg_dump. Запустите без «check», скрипт его поставит.")
        return 1
    ver = subprocess.run([pgdump, "--version"], capture_output=True, text=True)
    print(f"pg_dump: {pgdump} ({ver.stdout.strip()})")

    db_url = (os.environ.get("DB_URL") or "").strip()
    if not db_url:
        print("В .env нет DB_URL - проверять нечего.")
        return 1
    print(f"DB_URL: {mask(db_url)}")

    print("пробую снять пробный кусочек дампа...")
    r = subprocess.run([pgdump, db_url, "--schema-only", "--schema=public"],
                       capture_output=True)
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", "replace").strip().splitlines()
        print("НЕ ВЫШЛО:")
        for line in err[-6:]:
            print("   " + line)
        print()
        print("Чаще всего это значит, что в строке остался текст "
              "[YOUR-PASSWORD] вместо настоящего пароля базы.")
        return 1
    print(f"ГОТОВО: база отвечает, дамп снимается ({len(r.stdout)} байт схемы).")
    print("Теперь можно: python3 backupdb.py")
    return 0


def main() -> int:
    arg = sys.argv[1].strip() if len(sys.argv) > 1 else ""
    if arg.lower() == "check":
        return check()

    if not have_pgdump():
        if not install_pgdump():
            print("⛔ поставить pg_dump не вышло. Скажите об этом Клоду.")
            return 1
    print(f"pg_dump на месте: {have_pgdump()}")

    db_url = arg
    if not db_url:
        print()
        print("Вставьте строку подключения к базе и нажмите Enter.")
        print("Взять её: Supabase → Settings → Database → Connection string →")
        print("вкладка Session pooler. Вместо [YOUR-PASSWORD] должен стоять")
        print("настоящий пароль базы.")
        try:
            db_url = input("> ").strip()
        except EOFError:
            db_url = ""
    if not db_url:
        print("Пусто - ничего не меняю.")
        return 1
    if not db_url.startswith("postgres"):
        print("Это не похоже на строку подключения (должна начинаться с "
              "postgresql://). Ничего не меняю.")
        return 1

    # Supabase отдаёт строку с заглушкой вместо пароля. Просим пароль вторым
    # куском и подставляем сами: в консоли Aeza его не напечатать - там нет
    # заглавных букв, а пароли почти всегда с ними.
    placeholders = ("[YOUR-PASSWORD]", "%5BYOUR-PASSWORD%5D", "[your-password]")
    hit = next((ph for ph in placeholders if ph in db_url), "")
    if hit:
        print()
        print(f"В строке стоит заглушка {hit} вместо настоящего пароля.")
        print("Вставьте пароль базы и нажмите Enter.")
        print("(Если пароля нет под рукой: Supabase → Settings → Database →")
        print(" Reset database password. Сбросить безопасно - этот пароль")
        print(" больше нигде не используется.)")
        try:
            password = input("> ").strip()
        except EOFError:
            password = ""
        if not password:
            print("Пусто - ничего не меняю.")
            return 1
        db_url = db_url.replace(hit, password)
        print("Пароль подставил.")

    lines = set_key(_read_lines(), "DB_URL", db_url)
    with open(ENV, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip("\n") + "\n")
    os.chmod(ENV, 0o600)
    print(f"Записал в .env: DB_URL={mask(db_url)}")
    print()
    return check()


if __name__ == "__main__":
    raise SystemExit(main())
