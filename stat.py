"""
СВОДКА ПО РАЗВЕДКЕ — почему в таблице столько строк, сколько есть.

Показывает: сколько авторов уже в таблице CRM и с какими статусами, сколько
объявлений собрано за последние дни, сколько среди их авторов НОВЫХ (то есть тех,
кто реально добавит строку в таблицу), и сколько объявлений вообще без ника
(таких таблица не берёт).

Ничего не пишет и не тратит ИИ. Запуск:  python3 stat.py
"""
import json
import os
from collections import Counter
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv()

HERE = os.path.dirname(os.path.abspath(__file__))


def _load_jsonl(name):
    p = os.path.join(HERE, name)
    rows = []
    if not os.path.exists(p):
        return rows
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


print("=== ТАБЛИЦА CRM ===")
statuses = None
try:
    from sheets import Sheet
    statuses = Sheet().read_statuses()
except Exception as e:  # noqa: BLE001
    print(f"не смог прочитать таблицу: {e}")

if statuses is not None:
    print(f"всего авторов в таблице: {len(statuses)}")
    for k, v in Counter(str(s).strip() or "(пусто)" for s in statuses.values()).most_common():
        print(f"   {k}: {v}")

known = {str(k).lower().lstrip("@") for k in (statuses or {})}

print("\n=== ОЧЕРЕДЬ РАССЫЛКИ (что собрал парсер) ===")
q = _load_jsonl("outreach_queue.jsonl")
print(f"всего записей в очереди за всё время: {len(q)}")
now = datetime.now(timezone.utc)
for days in (1, 2, 7):
    since = now - timedelta(days=days)
    recent = []
    for r in q:
        t = r.get("queued_at")
        try:
            if t and datetime.fromisoformat(t) >= since:
                recent.append(r)
        except ValueError:
            pass
    authors = {str(r.get("author", "")).lower().lstrip("@") for r in recent if r.get("author")}
    fresh = authors - known
    print(f"  за последние {days} дн.: объявлений {len(recent)}, "
          f"разных авторов {len(authors)}, из них НОВЫХ (дадут строку) {len(fresh)}")

print("\n=== ПАМЯТЬ ПАРСЕРА ===")
for name in ("dedup.json", "state.json", "contacted.json"):
    p = os.path.join(HERE, name)
    if not os.path.exists(p):
        print(f"  {name}: нет файла")
        continue
    try:
        data = json.load(open(p, encoding="utf-8"))
        if isinstance(data, dict) and "authors" in data:
            print(f"  {name}: авторов {len(data['authors'])}")
        elif isinstance(data, dict):
            print(f"  {name}: записей {len(data)}")
        elif isinstance(data, list):
            print(f"  {name}: записей {len(data)}")
    except Exception as e:  # noqa: BLE001
        print(f"  {name}: не прочитался ({e})")
