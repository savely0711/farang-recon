"""Подготовить сервер к резервным копиям базы: поставить pg_dump и записать
строку подключения в .env.

Зачем отдельный помощник: в веб-консоли Aeza не вводятся заглавные буквы,
«_» и «&», поэтому ни `apt install postgresql-client`, ни строку вида
`DB_URL=postgresql://…` там руками не набрать. Скрипт делает это сам, а саму
строку подключения принимает как есть - её достаточно вставить из буфера.

Запуск (имя файла без подчёркиваний - его можно напечатать в консоли Aeza):
    python3 setupdb.py            → поставит pg_dump, спросит строку, проверит
    python3 setupdb.py check      → ничего не меняет, только проверяет
    python3 setupdb.py clean      → стереть историю команд консоли

Про «clean». Если строку подключения или пароль случайно напечатали прямо в
консоли (а не в ответ на вопрос скрипта), они остаются в истории команд -
файле ~/.bash_history. Имя этого файла с подчёркиванием, в консоли Aeza его
не набрать, поэтому чистку делает скрипт.

От человека нужен ТОЛЬКО ПАРОЛЬ базы. Адрес, пользователя, порт и имя базы
скрипт знает сам (они постоянны и не секретны) и соберёт строку подключения
за вас. Пароль экранируется, так что спецсимволы в нём не помеха.

Если всё же удобнее вставить строку подключения целиком - скрипт поймёт и её,
а если в ней осталась заглушка [YOUR-PASSWORD], спросит пароль отдельно.

Пароль нигде не показывается и не пишется, кроме .env на этом сервере
(файл закрыт от чужих глаз, права 600).
"""
import os
import re
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ENV = os.path.join(BASE, ".env")

# Всё, кроме пароля, у строки подключения постоянно и не секретно — это видно
# в дашборде Supabase любому, у кого есть доступ к проекту. Держим здесь,
# чтобы от человека требовалось ровно одно действие: вставить пароль.
# Если проект когда-нибудь переедет, просто вставьте в скрипт полную строку
# подключения целиком — он поймёт и её.
DEFAULT_USER = "postgres.ccxbqeuowmrfkijhmiez"
DEFAULT_HOST = "aws-1-ap-northeast-1.pooler.supabase.com"
DEFAULT_PORT = "5432"
DEFAULT_DB = "postgres"


def build_url(password: str) -> str:
    """Собрать строку подключения из постоянных частей и пароля."""
    from urllib.parse import quote
    # Пароль может содержать @ ? # и прочее — экранируем, иначе строка
    # развалится на части в самом неожиданном месте.
    return (f"postgresql://{DEFAULT_USER}:{quote(password, safe='')}"
            f"@{DEFAULT_HOST}:{DEFAULT_PORT}/{DEFAULT_DB}")


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


def clean_history() -> int:
    """Стереть историю команд: там мог осесть пароль, напечатанный вручную."""
    path = os.path.expanduser("~/.bash_history")
    if not os.path.exists(path):
        print("Файла истории нет - чистить нечего.")
    else:
        with open(path, "w", encoding="utf-8") as f:
            f.write("")
        print(f"Историю команд стёр: {path}")
    print()
    print("Осталось стереть то, что видно на экране консоли: нажмите")
    print("Ctrl+L или наберите  clear  и нажмите Enter.")
    print("В самой оболочке история этого сеанса живёт до выхода -")
    print("надёжнее закрыть вкладку консоли и открыть заново.")
    return 0


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
    if arg.lower() == "clean":
        return clean_history()

    if not have_pgdump():
        if not install_pgdump():
            print("⛔ поставить pg_dump не вышло. Скажите об этом Клоду.")
            return 1
    print(f"pg_dump на месте: {have_pgdump()}")

    entered = arg
    if not entered:
        print()
        print("Вставьте ПАРОЛЬ базы и нажмите Enter.")
        print("Всё остальное в строке подключения я знаю и подставлю сам:")
        print(f"   {DEFAULT_USER} @ {DEFAULT_HOST}")
        print()
        print("Где взять пароль: Supabase → Settings → Database. Если его нет")
        print("под рукой — там же «Reset database password», сбросить")
        print("безопасно: этот пароль больше нигде не используется.")
        try:
            entered = input("> ").strip()
        except EOFError:
            entered = ""
    if not entered:
        print("Пусто - ничего не меняю.")
        return 1

    # Вставили целую строку подключения вместо пароля — тоже принимаем.
    if entered.startswith("postgres"):
        db_url = entered
        placeholders = ("[YOUR-PASSWORD]", "%5BYOUR-PASSWORD%5D", "[your-password]")
        hit = next((ph for ph in placeholders if ph in db_url), "")
        if hit:
            print()
            print(f"В строке стоит заглушка {hit} вместо настоящего пароля.")
            print("Вставьте пароль базы и нажмите Enter.")
            try:
                password = input("> ").strip()
            except EOFError:
                password = ""
            if not password:
                print("Пусто - ничего не меняю.")
                return 1
            from urllib.parse import quote
            db_url = db_url.replace(hit, quote(password, safe=""))
            print("Пароль подставил.")
    else:
        db_url = build_url(entered)
        print("Строку подключения собрал сам, подставив ваш пароль.")

    lines = set_key(_read_lines(), "DB_URL", db_url)
    with open(ENV, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip("\n") + "\n")
    os.chmod(ENV, 0o600)
    print(f"Записал в .env: DB_URL={mask(db_url)}")
    print()
    return check()


if __name__ == "__main__":
    raise SystemExit(main())
