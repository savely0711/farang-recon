"""
«Первое касание» — авто-отправка авторам объявлений (Направление 3, пункт 14).

ЧТО ДЕЛАЕТ за один запуск:
  - берёт очередь новых объявлений (outreach_queue.jsonl), которую наполняет
    разведка (parser.py) — только объявления с открытым ником автора;
  - отбирает тех, кому МОЖНО написать: объявление старше суток И автору ещё
    НИ РАЗУ не писали (вечный список contacted.json — один автор = одно
    сообщение навсегда);
  - с 2–3 личных аккаунтов Савелия (по очереди) шлёт короткое сообщение:
        «Здравствуйте! Ваше объявление ещё актуально? <ссылка>»
    дальше диалог Савелий ведёт сам, как человек;
  - соблюдает ЩАДЯЩИЙ режим: дневной лимит на аккаунт с ПРОГРЕВОМ (растёт по
    дням), случайные паузы, только «человеческие» часы по Бангкоку;
  - сразу записывает автора в contacted.json + строку в outreach.log;
  - если письмо не ушло, разбирается ПОЧЕМУ и больше не топчется на одном
    человеке: «нужен Premium» → статус «Премиум» в таблице (пишет Савелий сам),
    «личка закрыта / ника нет» → «Не доставлено», временный сбой → ещё пара
    попыток, потом тоже «Не доставлено». За один запуск пробует нескольких
    авторов подряд (MAX_ATTEMPTS), пока одно письмо не уйдёт.

БЕЗОПАСНОСТЬ (осознанный риск Савелия — рассылка первым это против правил TG):
  - по умолчанию ВЫКЛЮЧЕНО (OUTREACH_ENABLED=1 включает);
  - если Telegram ограничивает аккаунт (PeerFlood/FloodWait) — аккаунт ставится
    на паузу, программа не давит дальше;
  - за один запуск с аккаунта уходит максимум OUTREACH_PER_RUN сообщений (по
    умолчанию 1) — реальный объём набирается частыми мелкими запусками (cron),
    так это выглядит по-человечески и размазано во времени.

Запуск: python3 outreach.py   (обычно из cron каждые ~20–30 мин в рабочие часы)
Тест без отправки: OUTREACH_DRY=1 python3 outreach.py  (только показывает, кому бы написал)
"""
import asyncio
import json
import os
import random
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv()

# ── таймзона Таиланда (без перехода на летнее время) ──
BKK = timezone(timedelta(hours=7))

# ── настройки (значения по умолчанию — щадящие) ──
ENABLED = os.environ.get("OUTREACH_ENABLED") == "1"
DRY = os.environ.get("OUTREACH_DRY") == "1"
MESSAGE = os.environ.get(
    "OUTREACH_MESSAGE", "Здравствуйте! Ваше объявление ещё актуально? "
)
MIN_AGE_HOURS = int(os.environ.get("OUTREACH_MIN_AGE_HOURS", "24"))
DAILY_START = int(os.environ.get("OUTREACH_DAILY_START", "5"))    # старт прогрева
DAILY_MAX = int(os.environ.get("OUTREACH_DAILY_MAX", "18"))       # потолок в день
WARMUP_STEP = int(os.environ.get("OUTREACH_WARMUP_STEP", "2"))    # +N/день
PER_RUN = int(os.environ.get("OUTREACH_PER_RUN", "1"))            # макс. за 1 запуск/аккаунт
HOURS = os.environ.get("OUTREACH_HOURS", "10-20")                 # «человеческие» часы (Бангкок)
DELAY_MIN = int(os.environ.get("OUTREACH_DELAY_MIN", "45"))       # пауза перед письмом, сек
DELAY_MAX = int(os.environ.get("OUTREACH_DELAY_MAX", "180"))
# сколько авторов пробуем за один запуск, пока одно письмо не уйдёт (глухие
# авторы больше не съедают весь запуск)
MAX_ATTEMPTS = int(os.environ.get("OUTREACH_MAX_ATTEMPTS", "5"))
# столько неудач подряд по «временным» причинам — и автор помечается «Не доставлено»
FAIL_LIMIT = int(os.environ.get("OUTREACH_FAIL_LIMIT", "3"))
RETRY_DELAY_MIN = int(os.environ.get("OUTREACH_RETRY_DELAY_MIN", "5"))
RETRY_DELAY_MAX = int(os.environ.get("OUTREACH_RETRY_DELAY_MAX", "15"))

# статусы в колонке «Написали?» таблицы-CRM
ST_DONE = "Да"
ST_TODO = "Нет"
ST_PREMIUM = "Премиум"        # пишут только Premium-аккаунты → Савелий напишет сам
ST_UNDELIVERABLE = "Не доставлено"  # личка закрыта, ник исчез и т.п.

BASE = os.path.dirname(__file__)
CONTACTED_FILE = os.path.join(BASE, "contacted.json")
STATE_FILE = os.path.join(BASE, "outreach_state.json")
LOG_FILE = os.path.join(BASE, "outreach.log")

import outreach_queue


# ─────────────────────── маленькие хранилища ───────────────────────
def _load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def _save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _log(line: str) -> None:
    stamp = datetime.now(BKK).strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{stamp}  {line}\n")
    print(line)


# ─────────────────────── вспомогательное ───────────────────────
def within_hours() -> bool:
    lo, hi = (int(x) for x in HOURS.split("-"))
    return lo <= datetime.now(BKK).hour < hi


def _norm_author(a) -> str:
    return (a or "").lstrip("@").strip().lower()


def is_old_enough(row) -> bool:
    iso = row.get("date") or row.get("queued_at")
    if not iso:
        return False
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - dt >= timedelta(hours=MIN_AGE_HOURS)


def _cap_today(acct: dict) -> int:
    """Дневной лимит с прогревом: растёт по дням с момента старта аккаунта."""
    started = acct.get("started")
    try:
        d0 = datetime.strptime(started, "%Y-%m-%d").date()
        days = (datetime.now(BKK).date() - d0).days
    except (TypeError, ValueError):
        days = 0
    return min(DAILY_MAX, DAILY_START + WARMUP_STEP * max(0, days))


def _refresh_day(acct: dict) -> None:
    today = datetime.now(BKK).strftime("%Y-%m-%d")
    if not acct.get("started"):
        acct["started"] = today
    if acct.get("day") != today:
        acct["day"] = today
        acct["sent_today"] = 0


def _sessions() -> dict:
    """Собирает сессии отправляющих аккаунтов из .env: TG_SEND_SESSION_1..5."""
    out = {}
    for i in range(1, 6):
        s = os.environ.get(f"TG_SEND_SESSION_{i}")
        if s:
            out[str(i)] = s
    return out


def classify_error(e) -> str:
    """Что за отказ: 'premium' (нужен Telegram Premium), 'permanent' (написать
    никогда не выйдет), 'retry' (похоже на временный сбой — попробуем позже)."""
    text = str(e).upper()
    if "PREMIUM" in text:
        return "premium"
    name = type(e).__name__
    permanent_names = {
        "UserPrivacyRestrictedError", "UsernameNotOccupiedError",
        "UsernameInvalidError", "UserIsBlockedError", "YouBlockedUserError",
        "InputUserDeactivatedError", "UserDeactivatedError", "UserBannedInChannelError",
        "PeerIdInvalidError", "UserIsBotError", "ForbiddenError", "ValueError",
    }
    if name in permanent_names:
        return "permanent"
    permanent_markers = (
        "PRIVACY", "USERNAME_NOT_OCCUPIED", "USERNAME_INVALID", "PEER_ID_INVALID",
        "USER_IS_BLOCKED", "USER_DEACTIVATED", "USER_BANNED", "CHAT_WRITE_FORBIDDEN",
        "NO USER HAS", "CANNOT FIND ANY ENTITY",
    )
    for marker in permanent_markers:
        if marker in text:
            return "permanent"
    return "retry"


def _mark_bad(contacted, author, status, reason, acct_id):
    """Больше к этому автору не возвращаемся (локальная память бота)."""
    contacted["authors"][author] = {
        "status": status, "reason": reason,
        "at": datetime.now(timezone.utc).isoformat(), "account": acct_id,
    }
    _save_json(CONTACTED_FILE, contacted)


# ─────────────────────── отбор кандидатов ───────────────────────
def pick_candidates(contacted: dict, need: int, statuses: dict) -> list:
    """Возвращает до `need` объявлений: автору ещё НЕ писали (ни бот локально, ни
    кто-то вручную — статус «Да» в таблице), объявление >суток, один автор — не
    чаще раза (в т.ч. в пределах запуска)."""
    seen_contacted = set(contacted.get("authors", {}).keys())
    # в таблице трогаем только тех, у кого «Нет»: «Да» (уже писали), «Премиум»
    # (Савелий напишет сам) и «Не доставлено» — пропускаем
    written = {k for k, v in (statuses or {}).items()
               if str(v).strip() and str(v).strip() != ST_TODO}
    picked, used = [], set()
    for row in outreach_queue.read_all():
        a = _norm_author(row.get("author"))
        if not a or a in seen_contacted or a in used or a in written:
            continue
        if not is_old_enough(row):
            continue
        used.add(a)
        picked.append(row)
        if len(picked) >= need:
            break
    return picked


# ─────────────────────── отправка ───────────────────────
async def send_all():
    from telethon import TelegramClient
    from telethon.errors import FloodWaitError, PeerFloodError
    from telethon.sessions import StringSession

    api_id = int(os.environ["TG_API_ID"])
    api_hash = os.environ["TG_API_HASH"]
    sessions = _sessions()
    if not sessions:
        _log("⚠ нет ни одной сессии отправки (TG_SEND_SESSION_1..) — выходим")
        return

    state = _load_json(STATE_FILE, {"accounts": {}})
    contacted = _load_json(CONTACTED_FILE, {"authors": {}})
    accounts = state.setdefault("accounts", {})
    total_sent = 0

    # Источник правды «кому уже писали» — таблица CRM (её ведут и бот, и агенты
    # вручную). Читаем статусы ДО отправки; contacted.json остаётся локальным
    # бэкапом (недоставучие + наши отправки — на случай, если таблица недоступна).
    sheet = None
    statuses = {}
    if os.environ.get("SHEET_WEBHOOK_URL"):
        from sheets import Sheet
        sheet = Sheet()
        statuses = sheet.read_statuses()
        if statuses is None:
            _log("⚠ не смог прочитать статусы CRM — пропускаю запуск, чтобы никого "
                 "не написать дважды (повторим в следующий запуск)")
            return

    for acct_id, session_str in sessions.items():
        acct = accounts.setdefault(acct_id, {})
        _refresh_day(acct)

        # аккаунт на паузе после ограничения TG?
        pu = acct.get("paused_until")
        if pu:
            try:
                if datetime.now(timezone.utc) < datetime.fromisoformat(pu):
                    _log(f"⏸ аккаунт {acct_id} на паузе до {pu} — пропускаю")
                    continue
            except ValueError:
                pass
            acct["paused_until"] = None

        cap = _cap_today(acct)
        remaining = min(PER_RUN, cap - acct.get("sent_today", 0))
        if remaining <= 0:
            _log(f"✓ аккаунт {acct_id}: дневной лимит {cap} исчерпан ({acct.get('sent_today',0)})")
            continue

        # берём с запасом: глухие авторы не должны съедать весь запуск
        cands = pick_candidates(contacted, remaining + MAX_ATTEMPTS, statuses)
        if not cands:
            _log(f"· аккаунт {acct_id}: подходящих авторов сейчас нет")
            continue

        client = TelegramClient(StringSession(session_str), api_id, api_hash)
        try:
            await client.connect()
            if not await client.is_user_authorized():
                _log(f"⚠ аккаунт {acct_id}: сессия не залогинена — пропускаю")
                continue
            me = await client.get_me()
            _log(f"🔑 аккаунт {acct_id} = @{getattr(me,'username',None) or me.first_name}; "
                 f"лимит сегодня {cap}, отправлено {acct.get('sent_today',0)}")

            fails = state.setdefault("fails", {})
            sent_here = 0
            attempts = 0
            for row in cands:
                if sent_here >= remaining or attempts >= MAX_ATTEMPTS:
                    break
                author = _norm_author(row["author"])
                link = row["link"]
                attempts += 1
                # перед первым письмом — «человеческая» пауза; после отказа
                # (никто ничего не получил) достаточно короткой
                if attempts == 1:
                    await asyncio.sleep(random.randint(DELAY_MIN, DELAY_MAX))
                else:
                    await asyncio.sleep(random.randint(RETRY_DELAY_MIN, RETRY_DELAY_MAX))
                try:
                    entity = await client.get_entity(author)
                    await client.send_message(entity, MESSAGE + link)
                except FloodWaitError as e:
                    until = datetime.now(timezone.utc) + timedelta(seconds=e.seconds + 30)
                    acct["paused_until"] = until.isoformat()
                    _log(f"⏳ аккаунт {acct_id}: FloodWait {e.seconds}с — пауза до {until.isoformat()}")
                    break
                except PeerFloodError:
                    tomorrow = datetime.now(BKK).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
                    acct["paused_until"] = tomorrow.astimezone(timezone.utc).isoformat()
                    _log(f"🚫 аккаунт {acct_id}: PeerFlood (TG ограничил рассылку) — пауза до утра")
                    break
                except Exception as e:  # noqa: BLE001
                    kind = classify_error(e)
                    reason = f"{type(e).__name__}: {e}"
                    if kind == "premium":
                        _mark_bad(contacted, author, "premium", reason, acct_id)
                        if sheet:
                            sheet.mark_written(author, ST_PREMIUM)
                        _log(f"  ⭐ @{author}: принимает письма только от Premium — "
                             f"пометил «{ST_PREMIUM}», пишет Савелий сам")
                    elif kind == "permanent":
                        _mark_bad(contacted, author, "undeliverable", reason, acct_id)
                        if sheet:
                            sheet.mark_written(author, ST_UNDELIVERABLE)
                        _log(f"  ↷ @{author}: написать не выйдет ({type(e).__name__}) — "
                             f"пометил «{ST_UNDELIVERABLE}»")
                    else:
                        n = fails.get(author, 0) + 1
                        fails[author] = n
                        if n >= FAIL_LIMIT:
                            fails.pop(author, None)
                            _mark_bad(contacted, author, "undeliverable", reason, acct_id)
                            if sheet:
                                sheet.mark_written(author, ST_UNDELIVERABLE)
                            _log(f"  ↷ @{author}: {n} сбоя подряд ({type(e).__name__}) — "
                                 f"пометил «{ST_UNDELIVERABLE}»")
                        else:
                            _log(f"  ↻ @{author}: временный сбой ({type(e).__name__}: {e}) — "
                                 f"попробую ещё (попытка {n} из {FAIL_LIMIT})")
                        _save_json(STATE_FILE, state)
                    continue

                # успех
                fails.pop(author, None)
                contacted["authors"][author] = {
                    "status": "sent", "at": datetime.now(timezone.utc).isoformat(),
                    "account": acct_id, "link": link,
                }
                _save_json(CONTACTED_FILE, contacted)
                if sheet:
                    sheet.mark_written(author)  # «Написали?»=Да в CRM (для агентов)
                acct["sent_today"] = acct.get("sent_today", 0) + 1
                acct["total"] = acct.get("total", 0) + 1
                sent_here += 1
                total_sent += 1
                _save_json(STATE_FILE, state)
                _log(f"  ✉ @{author} ← аккаунт {acct_id}  {link}")
        finally:
            await client.disconnect()
            _save_json(STATE_FILE, state)

    _log(f"🏁 запуск завершён; отправлено за этот запуск: {total_sent}")


# ─────────────────────── тестовый показ (без отправки) ───────────────────────
def dry_preview():
    contacted = _load_json(CONTACTED_FILE, {"authors": {}})
    state = _load_json(STATE_FILE, {"accounts": {}})
    sessions = _sessions() or {"1": "(нет сессии)"}
    statuses = {}
    if os.environ.get("SHEET_WEBHOOK_URL"):
        from sheets import Sheet
        statuses = Sheet().read_statuses() or {}
    print("🧪 ТЕСТ (OUTREACH_DRY): никому не пишу, только показываю план.\n")
    for acct_id in sessions:
        acct = state.get("accounts", {}).get(acct_id, {})
        acct_copy = dict(acct)
        _refresh_day(acct_copy)
        cap = _cap_today(acct_copy)
        remaining = min(PER_RUN, cap - acct_copy.get("sent_today", 0))
        cands = pick_candidates(contacted, max(0, remaining), statuses)
        print(f"— аккаунт {acct_id}: лимит сегодня {cap}, "
              f"отправлено {acct_copy.get('sent_today',0)}, за запуск ещё {max(0,remaining)}")
        for row in cands:
            print(f"    → @{_norm_author(row['author'])}  {row['link']}")
    print(f"\nТекст: «{MESSAGE}<ссылка>»")
    print(f"Часы отправки (Бангкок): {HOURS}; сейчас в окне: {within_hours()}")


def main():
    dry = DRY or (len(sys.argv) > 1 and sys.argv[1].lower() == "dry")
    if not ENABLED and not dry:
        print("Отправка ВЫКЛЮЧЕНА. Включить: OUTREACH_ENABLED=1 в .env "
              "(или разовый тест: python3 outreach.py dry).")
        return
    if dry:
        dry_preview()
        return
    if not within_hours():
        print(f"Сейчас вне рабочих часов ({HOURS}, Бангкок) — ничего не шлю.")
        return
    asyncio.run(send_all())


if __name__ == "__main__":
    main()
