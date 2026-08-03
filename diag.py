"""
ОТЧЁТ О СОСТОЯНИИ РАССЫЛКИ — один экран вместо десятка команд в консоли.

Показывает: время, расписание cron, настройки темпа из .env, состояние каждого
отправляющего аккаунта (лимит, пауза, счётчик блокировок, когда можно слать),
письма за сегодня и хвост журнала. Секреты НЕ печатает: у сессий и ключей видно
только «задано/не задано».

Запуск на сервере:  cd /root/recon && python3 diag.py
Больше строк журнала: python3 diag.py 100
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

BKK = timezone(timedelta(hours=7))
BASE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE, ".env")
LOG = os.path.join(BASE, "outreach.log")
STATE = os.path.join(BASE, "outreach_state.json")
CONTACTED = os.path.join(BASE, "contacted.json")
QUEUE = os.path.join(BASE, "outreach_queue.jsonl")

SECRET_KEYS = ("SESSION", "HASH", "KEY", "TOKEN", "PASSWORD")
TAIL = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 40


def line(t=""):
    print(t)


def human(iso):
    """ISO-время → «03.08 14:20 (через 5 ч 10 мин)» по Бангкоку."""
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return str(iso)
    if not dt.tzinfo:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = dt - datetime.now(timezone.utc)
    mins = int(abs(delta).total_seconds() // 60)
    when = f"{mins // 60} ч {mins % 60} мин"
    tail = f"через {when}" if delta.total_seconds() > 0 else f"{when} назад"
    return f"{dt.astimezone(BKK).strftime('%d.%m %H:%M')} ({tail})"


def read_env():
    out = {}
    if not os.path.exists(ENV_PATH):
        return out
    for ln in open(ENV_PATH, encoding="utf-8"):
        ln = ln.strip()
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        k, v = ln.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def show(k, env, default=None):
    v = env.get(k)
    if any(s in k for s in SECRET_KEYS):
        v = "задано" if v else "НЕ задано"
    elif not v:
        v = f"(не задано → по умолчанию {default})" if default is not None else "(не задано)"
    line(f"    {k} = {v}")


line("═══ ОТЧЁТ О РАССЫЛКЕ «ПЕРВОЕ КАСАНИЕ» ═══")
line(f"Сейчас по Бангкоку: {datetime.now(BKK).strftime('%d.%m.%Y %H:%M')}")

line()
line("── Расписание (crontab) ──")
cron = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
rows = [l for l in cron.stdout.splitlines() if l.strip() and not l.strip().startswith("#")]
for r in rows:
    line(f"    {r}")
n_out = sum(1 for r in rows if "outreach.py" in r)
if n_out != 1:
    line(f"    ⚠ строк запуска рассылки: {n_out} (должна быть ровно одна!)")

env = read_env()
line()
line("── Настройки ──")
for k, d in (("OUTREACH_ENABLED", None), ("OUTREACH_HOURS", "10-20"),
             ("OUTREACH_MIN_GAP_MIN", 25), ("OUTREACH_GAP_JITTER_MIN", 10),
             ("OUTREACH_PER_RUN", 1), ("OUTREACH_DAILY_START", 5),
             ("OUTREACH_DAILY_MAX", 18), ("OUTREACH_WARMUP_STEP", 2),
             ("OUTREACH_MIN_AGE_HOURS", 24), ("OUTREACH_MAX_ATTEMPTS", 5),
             ("OUTREACH_PEERFLOOD_STEPS", "6,24,72"),
             ("OUTREACH_PEERFLOOD_RESET_HOURS", 24),
             ("OUTREACH_NOTIFY_TO", None)):
    show(k, env, d)
for i in range(1, 6):
    k = f"TG_SEND_SESSION_{i}"
    if k in env or i <= 3:
        show(k, env)

line()
line("── Аккаунты (файл состояния) ──")
state = {}
if os.path.exists(STATE):
    state = json.load(open(STATE, encoding="utf-8"))
for acct_id, a in (state.get("accounts") or {}).items():
    line(f"  Аккаунт {acct_id}:")
    line(f"    сегодня отправлено: {a.get('sent_today', 0)}   всего: {a.get('total', 0)}")
    line(f"    первый день работы: {a.get('started', '—')}   день учёта: {a.get('day', '—')}")
    line(f"    прошлое письмо: {human(a.get('last_sent_at'))}")
    line(f"    можно слать с: {human(a.get('next_allowed_at'))}")
    line(f"    пауза до: {human(a.get('paused_until'))}")
    line(f"    блокировок подряд: {a.get('peerflood_streak', 0)}"
         f"   конец прошлой паузы: {human(a.get('pf_pause_end'))}")
if not state.get("accounts"):
    line("    (пусто — бот ещё ни разу не отправлял)")

line()
line("── Объёмы ──")
if os.path.exists(QUEUE):
    line(f"    очередь объявлений: {sum(1 for _ in open(QUEUE, encoding='utf-8'))} строк")
if os.path.exists(CONTACTED):
    c = json.load(open(CONTACTED, encoding="utf-8")).get("authors", {})
    sent = sum(1 for v in c.values() if v.get("status") == "sent")
    line(f"    авторов в памяти: {len(c)} (отправлено {sent}, остальные — недоставучие)")

line()
line("── Письма за сегодня (по журналу) ──")
today = datetime.now(BKK).strftime("%Y-%m-%d")
sends, prev = [], None
if os.path.exists(LOG):
    for ln in open(LOG, encoding="utf-8", errors="replace"):
        if ln.startswith(today) and "✉" in ln:
            sends.append(ln.rstrip())
for s in sends:
    m = re.match(r"\d{4}-\d{2}-\d{2}\s+(\d{2}):(\d{2})", s)
    gap = ""
    if m:
        cur = int(m.group(1)) * 60 + int(m.group(2))
        if prev is not None:
            d = cur - prev
            gap = f"   [интервал {d} мин]" + ("  ⚠ МАЛО" if d < 20 else "")
        prev = cur
    line(f"    {s}{gap}")
if not sends:
    line("    (сегодня писем не было)")

line()
line(f"── Хвост журнала ({TAIL} строк) ──")
if os.path.exists(LOG):
    with open(LOG, encoding="utf-8", errors="replace") as f:
        for ln in f.readlines()[-TAIL:]:
            line("    " + ln.rstrip())
else:
    line("    (журнала ещё нет)")
line()
line("═══ конец отчёта ═══")
