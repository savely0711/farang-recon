"""
ПЕРЕСЧЁТ ЗАВИСШЕЙ ПАУЗЫ по новому правилу «подряд».

Зачем: до правки от 03.08.2026 счётчик блокировок не имел срока давности, и
редкие блокировки (раз в пару дней) складывались в трёхсуточный простой. Этот
скрипт разово приводит состояние в порядок: находит в журнале время последней
блокировки, считает счётчик заново (первая = 6 ч) и ставит правильную паузу.
Если она уже истекла — снимает паузу совсем.

Запуск:  cd /root/recon && python3 resume.py        (показать, что изменится)
         cd /root/recon && python3 resume.py yes    (применить)
Снять паузу вообще:  python3 resume.py now
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

BKK = timezone(timedelta(hours=7))
BASE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(BASE, "outreach_state.json")
LOG = os.path.join(BASE, "outreach.log")

STEPS = [int(x) for x in os.environ.get("OUTREACH_PEERFLOOD_STEPS", "6,24,72").split(",")]
FIRST_HOURS = STEPS[0]

mode = (sys.argv[1].lower() if len(sys.argv) > 1 else "")
apply_it = mode in ("yes", "now")
drop_all = mode == "now"


def bkk(dt):
    return dt.astimezone(BKK).strftime("%d.%m %H:%M")


def last_block_time():
    """Время последней записи о блокировке PeerFlood в журнале (по Бангкоку)."""
    if not os.path.exists(LOG):
        return None
    found = None
    for ln in open(LOG, encoding="utf-8", errors="replace"):
        if "PeerFlood" in ln:
            m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", ln)
            if m:
                found = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=BKK)
    return found


if not os.path.exists(STATE):
    print("Файла состояния нет — пересчитывать нечего.")
    raise SystemExit

state = json.load(open(STATE, encoding="utf-8"))
accounts = state.get("accounts") or {}
if not accounts:
    print("В состоянии нет аккаунтов — пересчитывать нечего.")
    raise SystemExit

block = last_block_time()
print(f"Последняя блокировка по журналу: {bkk(block) if block else 'не найдена'}")
now = datetime.now(timezone.utc)
changed = 0

for acct_id, a in accounts.items():
    old_pause, old_streak = a.get("paused_until"), a.get("peerflood_streak", 0)
    if not old_pause and not old_streak:
        print(f"Аккаунт {acct_id}: паузы нет, счётчик 0 — не трогаю.")
        continue
    if drop_all or not block:
        new_pause, new_streak = None, 0
    else:
        until = block + timedelta(hours=FIRST_HOURS)
        new_streak = 1
        new_pause = None if until <= now else until.astimezone(timezone.utc).isoformat()
    print(f"Аккаунт {acct_id}:")
    print(f"   было: пауза до {old_pause or '—'}, блокировок подряд {old_streak}")
    print(f"   станет: пауза {'снята' if not new_pause else 'до ' + bkk(datetime.fromisoformat(new_pause))}"
          f", блокировок подряд {new_streak}")
    if apply_it:
        a["paused_until"] = new_pause
        a["peerflood_streak"] = new_streak
        a["pf_pause_end"] = new_pause or (
            (block + timedelta(hours=FIRST_HOURS)).astimezone(timezone.utc).isoformat()
            if block else None)
        changed += 1

if apply_it:
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE)
    print(f"\n✅ Применено к {changed} аккаунтам. Дальше бот сам продолжит по расписанию.")
else:
    print("\nЭто был предпросмотр. Применить: python3 resume.py yes")
