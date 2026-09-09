"""Резервная копия БАЗЫ на этом сервере.

Зачем переехало сюда (09.09.2026)
---------------------------------
Копию базы делал ночной робот GitHub. Но бесплатное хранилище GitHub Actions
(0,5 ГБ) было израсходовано архивами фотографий, которые тот же робот качал
каждую ночь. Фотографии мы убрали, однако GitHub считает не «занято сейчас»,
а сколько места ты занимал в течение месяца, - и потраченное не возвращается
до 1 октября. Значит три недели копия базы просто не сохранялась бы.

Здесь никаких лимитов нет: дамп весит единицы мегабайт, диск сервера 30 ГБ.
Рядом уже лежит зеркало фотографий (backup_photos.py) - вся резервная копия
проекта в одном месте.

Что делает
----------
1. Снимает дамп схем public, auth и storage через pg_dump.
2. Кладёт в ~/backup/db/farang-ГГГГ-ММ-ДД.sql.gz
3. Удаляет копии старше 30 дней (иначе диск однажды кончится). Копии за
   последние 30 дней не трогает никогда.

Нужен pg_dump и строка подключения DB_URL в .env - и то и другое ставит
помощник: python3 setupdb.py

Запуск вручную:  cd /root/recon && python3 backupdb.py
По расписанию:   ставится через setcron.py, ежедневно в 03:00.
"""
import glob
import gzip
import os
import subprocess
import sys
import time

from dotenv import load_dotenv

BASE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE, ".env"))

DEST = os.path.expanduser("~/backup/db")
KEEP_DAYS = 30
SCHEMAS = ["public", "auth", "storage"]


def human(n: int) -> str:
    for unit, size in (("ГБ", 1 << 30), ("МБ", 1 << 20), ("КБ", 1 << 10)):
        if n >= size:
            return f"{n / size:.1f} {unit}".replace(".", ",")
    return f"{n} Б"


def find_pgdump() -> str:
    """Путь к pg_dump. Сначала обычный, потом версии из /usr/lib/postgresql."""
    from shutil import which
    found = which("pg_dump")
    if found:
        return found
    candidates = sorted(glob.glob("/usr/lib/postgresql/*/bin/pg_dump"), reverse=True)
    return candidates[0] if candidates else ""


def main() -> int:
    db_url = (os.environ.get("DB_URL") or "").strip()
    if not db_url:
        print("⛔ в .env нет DB_URL - строки подключения к базе.")
        print("   Заполнить поможет: python3 setupdb.py")
        return 1

    pgdump = find_pgdump()
    if not pgdump:
        print("⛔ на сервере нет pg_dump.")
        print("   Поставить поможет: python3 setupdb.py")
        return 1

    os.makedirs(DEST, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d")
    dest = os.path.join(DEST, f"farang-{stamp}.sql.gz")
    tmp = dest + ".part"

    args = [pgdump, db_url, "--no-owner", "--no-privileges"]
    for s in SCHEMAS:
        args += ["--schema=" + s]

    print(f"снимаю дамп базы ({', '.join(SCHEMAS)})...")
    started = time.time()
    try:
        proc = subprocess.run(args, capture_output=True)
    except Exception as e:  # noqa: BLE001
        print(f"⛔ pg_dump не запустился: {e}")
        return 1
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        print("⛔ pg_dump отказал:")
        for line in err[-6:]:
            print("   " + line)
        return 1

    with gzip.open(tmp, "wb") as f:
        f.write(proc.stdout)
    os.replace(tmp, dest)

    size = os.path.getsize(dest)
    print(f"✅ копия готова: {dest}")
    print(f"   размер: {human(size)}   заняло: {int(time.time() - started)} сек")

    # Ротация: держим 30 дней, старше - убираем, иначе диск однажды кончится.
    edge = time.time() - KEEP_DAYS * 86400
    removed = 0
    for old in glob.glob(os.path.join(DEST, "farang-*.sql.gz")):
        if os.path.getmtime(old) < edge:
            os.remove(old)
            removed += 1
    kept = len(glob.glob(os.path.join(DEST, "farang-*.sql.gz")))
    print(f"   копий в папке: {kept}" + (f"   убрано старых: {removed}" if removed else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
