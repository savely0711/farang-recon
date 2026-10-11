"""Разовая настройка сервера разведки ЧЕРЕЗ БРАУЗЕР (11.10.2026).

Зачем: в веб-консоли Aeza не работает Shift и нормальная вставка, поэтому
ключи там не ввести. Этот скрипт поднимает на сервере маленькую страницу
с формой: Савелий открывает её в своём браузере, вставляет ключи обычным
Cmd+V, вводит код из Telegram — и всё записывается в .env само.

Запуск (только строчные буквы):  python3 websetup.py
Скрипт напечатает адрес вида  http://<IP>:8765/<случайный-ключ>
Без ключа в адресе страница не открывается. Скрипт сам выключается после
кнопки «Готово» или через 12 часов.

Пустое поле = «оставить как есть», поэтому форму можно заполнять в несколько
заходов. После сохранения каждая связка сразу проверяется (таблица, сайт,
база, Anthropic), результат показывается на странице.
"""
import asyncio
import contextlib
import html
import io
import os
import secrets
import shutil
import socket
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
ENV = os.path.join(BASE, ".env")
PORT = 8765
KEY = secrets.token_hex(8)
DEADLINE = time.time() + 12 * 60 * 60

FIELDS = [
    # (ключ в .env, подпись, где взять, секрет?)
    ("TG_API_ID", "Telegram api_id", "my.telegram.org → API development tools (число)", False),
    ("TG_API_HASH", "Telegram api_hash", "там же, строка из 32 символов", True),
    ("ANTHROPIC_API_KEY", "Ключ Anthropic", "console.anthropic.com → API keys (начинается на sk-ant-)", True),
    ("SHEET_WEBHOOK_URL", "Адрес скрипта таблицы разведки", "Apps Script таблицы → Развёртывания → ссылка …/exec", False),
    ("SHEET_TOKEN", "Токен таблицы разведки", "первая строка кода скрипта таблицы: TOKEN = '…'", True),
    ("REALTY_SHEET_WEBHOOK_URL", "Адрес скрипта таблицы «Недвижимость»", "так же, в таблице «Фаранг — Недвижимость»", False),
    ("REALTY_SHEET_TOKEN", "Токен таблицы «Недвижимость»", "первая строка кода её скрипта", True),
    ("RECON_API_TOKEN", "Токен сайта (RECON_API_TOKEN)", "Vercel → проект → Settings → Environment Variables", True),
    ("DB_PASSWORD", "Пароль базы Supabase", "Supabase → Settings → Database (можно сбросить — больше нигде не используется)", True),
]

LOOP = asyncio.new_event_loop()
threading.Thread(target=LOOP.run_forever, daemon=True).start()
TG = {"client": None, "phone": "", "hash": "", "qr": None}
DONE = threading.Event()


# ───────────────────────── .env ─────────────────────────
def read_env() -> dict:
    out = {}
    if os.path.exists(ENV):
        for ln in open(ENV, encoding="utf-8").read().splitlines():
            if "=" in ln and not ln.lstrip().startswith("#"):
                k, v = ln.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def set_env(updates: dict) -> None:
    if not os.path.exists(ENV):
        src = os.path.join(BASE, ".env.example")
        if os.path.exists(src):
            shutil.copy(src, ENV)
        else:
            open(ENV, "w").close()
    lines = open(ENV, encoding="utf-8").read().splitlines()
    for key, value in updates.items():
        new, done = [], False
        for ln in lines:
            st = ln.strip()
            if st.startswith(key + "=") or st.startswith("#" + key + "="):
                if not done:
                    new.append(f"{key}={value}")
                    done = True
            else:
                new.append(ln)
        if not done:
            new.append(f"{key}={value}")
        lines = new
    with open(ENV, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip("\n") + "\n")
    os.chmod(ENV, 0o600)


# ───────────────────────── проверки ─────────────────────────
def quiet(fn, *a):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            res = fn(*a)
        except Exception as e:  # noqa: BLE001
            print(f"ошибка: {type(e).__name__}: {e}")
            res = False
    return res, buf.getvalue().strip()


def check_all() -> list:
    import httpx
    env = read_env()
    res = []

    def row(name, ok, note=""):
        res.append((name, ok, note))

    key = env.get("ANTHROPIC_API_KEY", "")
    if key:
        try:
            r = httpx.get("https://api.anthropic.com/v1/models",
                          headers={"x-api-key": key, "anthropic-version": "2023-06-01"}, timeout=30)
            row("Anthropic", r.status_code == 200, "" if r.status_code == 200 else f"ответ {r.status_code}")
        except Exception as e:  # noqa: BLE001
            row("Anthropic", False, str(e))
    else:
        row("Anthropic", None, "ключа нет")

    url, tok = env.get("SHEET_WEBHOOK_URL", ""), env.get("SHEET_TOKEN", "")
    if url and tok:
        try:
            r = httpx.get(url, params={"action": "statuses", "token": tok}, timeout=60, follow_redirects=True)
            d = r.json()
            row("Таблица разведки", bool(d.get("ok")), "" if d.get("ok") else str(d.get("error")))
        except Exception as e:  # noqa: BLE001
            row("Таблица разведки", False, str(e))
    else:
        row("Таблица разведки", None, "адреса или токена нет")

    url, tok = env.get("REALTY_SHEET_WEBHOOK_URL", ""), env.get("REALTY_SHEET_TOKEN", "")
    if url and tok:
        import realtysetup
        ok, out = quiet(realtysetup._ping, url, tok)
        row("Таблица «Недвижимость»", bool(ok), "" if ok else out[-200:])
    else:
        row("Таблица «Недвижимость»", None, "адреса или токена нет")

    if env.get("RECON_API_TOKEN"):
        import setupsite
        code, out = quiet(setupsite.check)
        row("Сайт farang.market", code == 0, "" if code == 0 else out[-200:])
    else:
        row("Сайт farang.market", None, "токена нет")

    if env.get("DB_URL"):
        import setupdb
        code, out = quiet(setupdb.check)
        row("База (резервные копии)", code == 0, "" if code == 0 else out[-200:])
    else:
        row("База (резервные копии)", None, "пароля нет")

    row("Вход в Telegram", bool(env.get("TG_SESSION")), "" if env.get("TG_SESSION") else "ещё не выполнен")
    return res


# ───────────────────────── Telegram ─────────────────────────
def tg_run(coro):
    return asyncio.run_coroutine_threadsafe(coro, LOOP).result(timeout=120)


async def _tg_send(phone):
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    env = read_env()
    if TG["client"] is None:
        TG["client"] = TelegramClient(StringSession(), int(env["TG_API_ID"]), env["TG_API_HASH"])
        await TG["client"].connect()
    sent = await TG["client"].send_code_request(phone)
    TG["phone"], TG["hash"] = phone, sent.phone_code_hash


async def _tg_code(code):
    from telethon.errors import SessionPasswordNeededError
    try:
        await TG["client"].sign_in(TG["phone"], code, phone_code_hash=TG["hash"])
    except SessionPasswordNeededError:
        return "password"
    return await _tg_finish()


async def _tg_pass(pw):
    await TG["client"].sign_in(password=pw)
    return await _tg_finish()


async def _tg_qr():
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    env = read_env()
    if TG["client"] is not None:
        try:
            await TG["client"].disconnect()
        except Exception:  # noqa: BLE001
            pass
    TG["client"] = TelegramClient(StringSession(), int(env["TG_API_ID"]), env["TG_API_HASH"])
    await TG["client"].connect()
    TG["qr"] = await TG["client"].qr_login()
    return TG["qr"].url


async def _tg_qr_wait():
    from telethon.errors import SessionPasswordNeededError
    qr = TG.get("qr")
    if qr is None:
        return {"state": "none"}
    try:
        await qr.wait(timeout=20)
    except SessionPasswordNeededError:
        return {"state": "password"}
    except asyncio.TimeoutError:
        await qr.recreate()
        return {"state": "wait", "url": qr.url}
    TG["qr"] = None
    r = await _tg_finish()
    return {"state": "ok", "who": r[3:]}


async def _tg_finish():
    me = await TG["client"].get_me()
    set_env({"TG_SESSION": TG["client"].session.save()})
    await TG["client"].disconnect()
    TG["client"] = None
    return f"ok:@{me.username or me.id}"


# ───────────────────────── страница ─────────────────────────
CSS = """body{font:16px -apple-system,Segoe UI,sans-serif;max-width:720px;margin:24px auto;padding:0 16px;color:#222}
h1{font-size:22px}h2{font-size:18px;margin-top:28px}label{display:block;margin-top:14px;font-weight:600}
small{display:block;color:#666;font-weight:400}input{width:100%;padding:9px;font-size:15px;box-sizing:border-box;margin-top:4px}
button{margin-top:18px;padding:11px 20px;font-size:16px;background:#1a73e8;color:#fff;border:0;border-radius:6px;cursor:pointer}
.ok{color:#188038}.bad{color:#c5221f}.skip{color:#888}.msg{background:#f1f3f4;padding:12px;border-radius:6px;margin-top:12px}
td{padding:4px 10px 4px 0;vertical-align:top}"""


def page(body: str) -> bytes:
    return (f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
            f"<title>Настройка разведки</title><style>{CSS}</style>{body}").encode()


def render(msg: str = "", tg_step: str = "") -> bytes:
    env = read_env()
    p = f"/{KEY}"
    out = ["<h1>Настройка сервера разведки</h1>"]
    if msg:
        out.append(f"<div class=msg>{msg}</div>")

    out.append(f"<h2>1. Ключи</h2><form method=post action='{p}/save'>")
    out.append("<small>Пустое поле — оставить как есть. Значения не показываются.</small>")
    for k, label, hint, secret in FIELDS:
        have = env.get("DB_URL") if k == "DB_PASSWORD" else env.get(k)
        st = "<span class=ok>✓ уже есть</span>" if have else "<span class=bad>нет</span>"
        typ = "password" if secret else "text"
        out.append(f"<label>{label} — {st}<small>{html.escape(hint)}</small>"
                   f"<input name={k} type={typ} autocomplete=off></label>")
    out.append("<button>Сохранить и проверить</button></form>")

    out.append("<h2>2. Вход в Telegram (аккаунт разведки)</h2>")
    if env.get("TG_SESSION") and not tg_step:
        out.append("<p class=ok>✓ вход выполнен. Повторять не нужно.</p>")
    elif not (env.get("TG_API_ID") and env.get("TG_API_HASH")):
        out.append("<p class=skip>Сначала сохраните api_id и api_hash в пункте 1.</p>")
    elif tg_step == "code":
        out.append(f"<form method=post action='{p}/code'><label>Код из Telegram<small>пришёл в приложение Telegram на номер {html.escape(TG['phone'])}</small>"
                   f"<input name=code autocomplete=off inputmode=numeric></label><button>Войти</button></form>")
        out.append(f"<form method=post action='{p}/qr'><button style='background:#188038'>Войти по QR-коду (без кода из SMS)</button></form>")
    elif tg_step == "password":
        out.append(f"<form method=post action='{p}/pass'><label>Облачный пароль Telegram<small>у аккаунта включена двухэтапная проверка</small>"
                   f"<input name=pw type=password autocomplete=off></label><button>Войти</button></form>")
    else:
        out.append(f"<form method=post action='{p}/phone'><label>Номер телефона аккаунта разведки<small>в международном виде, например +66…</small>"
                   f"<input name=phone autocomplete=off></label><button>Прислать код</button></form>")
        out.append(f"<form method=post action='{p}/qr'><button style='background:#188038'>Войти по QR-коду (без кода из SMS)</button></form>")

    out.append("<h2>3. Проверка</h2><table>")
    for name, ok, note in check_all():
        cls, mark = ("ok", "✓") if ok else (("skip", "—") if ok is None else ("bad", "✗"))
        out.append(f"<tr><td class={cls}>{mark}</td><td>{name}</td><td class=skip>{html.escape(note or '')}</td></tr>")
    out.append("</table>")
    out.append(f"<form method=post action='{p}/done'><button style='background:#188038'>Готово — выключить эту страницу</button></form>")
    return page("".join(out))


def qr_page(url: str) -> bytes:
    p = f"/{KEY}"
    body = f"""<h1>Вход в Telegram по QR-коду</h1>
<ol><li>На телефоне в Telegram переключитесь на аккаунт разведки (@savely_karelin).</li>
<li>Настройки → Устройства → <b>Подключить устройство</b> (Link Desktop Device).</li>
<li>Наведите камеру на код ниже. Код обновляется сам — просто держите камеру.</li></ol>
<div id=q style='margin:24px 0'></div><p id=s class=skip>Жду сканирования…</p>
<p><a href='{p}'>← назад к настройке</a></p>
<script src='https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js'></script>
<script>
let qr=new QRCode(document.getElementById('q'),{{text:{json_str(url)},width:260,height:260}});
async function poll(){{
  try{{
    const d=await fetch('{p}/qrwait').then(r=>r.json());
    const s=document.getElementById('s');
    if(d.state==='ok'){{s.className='ok';s.textContent='✓ Вход выполнен: '+d.who+'. Возвращаю на страницу настройки…';setTimeout(()=>location.href='{p}',2000);return;}}
    if(d.state==='password'){{s.innerHTML="У аккаунта включён облачный пароль — <a href='{p}/pw'>введите его здесь</a>.";return;}}
    if(d.state==='wait'&&d.url){{qr.clear();qr.makeCode(d.url);}}
    if(d.state==='error'){{s.className='bad';s.textContent='Ошибка: '+d.error;return;}}
  }}catch(e){{}}
  setTimeout(poll,500);
}}
poll();
</script>"""
    return page(body)


def json_str(x: str) -> str:
    import json
    return json.dumps(x)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body: bytes, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _form(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        data = urllib.parse.parse_qs(self.rfile.read(n).decode("utf-8"), keep_blank_values=True)
        return {k: v[0].strip() for k, v in data.items()}

    def do_GET(self):
        if self.path == f"/{KEY}/qrwait":
            import json
            try:
                data = tg_run(_tg_qr_wait())
            except Exception as e:  # noqa: BLE001
                data = {"state": "error", "error": f"{type(e).__name__}: {e}"}
            body = json.dumps(data).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == f"/{KEY}/pw":
            return self._send(render("", "password"))
        if self.path.rstrip("/") != f"/{KEY}":
            return self._send(b"not found", 404)
        self._send(render())

    def do_POST(self):
        if not self.path.startswith(f"/{KEY}/"):
            return self._send(b"not found", 404)
        act = self.path.split("/")[-1]
        f = self._form()
        msg, step = "", ""
        try:
            if act == "save":
                upd = {k: f[k] for k, *_ in FIELDS if f.get(k) and k != "DB_PASSWORD"}
                if f.get("DB_PASSWORD"):
                    import setupdb
                    if not setupdb.have_pgdump():
                        quiet(setupdb.install_pgdump)
                    upd["DB_URL"] = setupdb.build_url(f["DB_PASSWORD"])
                if upd:
                    set_env(upd)
                    msg = f"Сохранено полей: {len(upd)}. Результат проверки — внизу."
                else:
                    msg = "Ничего не введено — ничего не менял."
            elif act == "phone":
                tg_run(_tg_send(f.get("phone", "").replace(" ", "")))
                msg, step = "Код отправлен в Telegram.", "code"
            elif act == "code":
                r = tg_run(_tg_code(f.get("code", "").replace(" ", "")))
                if r == "password":
                    step = "password"
                else:
                    msg = f"✓ Вход выполнен: {r[3:]}"
            elif act == "pass":
                r = tg_run(_tg_pass(f.get("pw", "")))
                msg = f"✓ Вход выполнен: {r[3:]}"
            elif act == "qr":
                url = tg_run(_tg_qr())
                return self._send(qr_page(url))
            elif act == "done":
                DONE.set()
                return self._send(page("<h1>Готово</h1><p>Страница выключена. Вкладку можно закрыть.</p>"))
        except Exception as e:  # noqa: BLE001
            msg = f"<span class=bad>Ошибка: {html.escape(type(e).__name__)}: {html.escape(str(e))}</span>"
            if act in ("code", "pass") and TG["client"] is not None:
                step = "code" if act == "code" else "password"
        self._send(render(msg, step))


def my_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("1.1.1.1", 80))
        return s.getsockname()[0]
    except Exception:  # noqa: BLE001
        return "<IP-сервера>"


def main():
    os.chdir(BASE)
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print()
    print("Страница настройки открыта по адресу:")
    print(f"   http://{my_ip()}:{PORT}/{KEY}")
    print()
    print("Скрипт выключится сам после кнопки «Готово» или через 12 часов.")
    while not DONE.is_set() and time.time() < DEADLINE:
        time.sleep(1)
    time.sleep(1)
    srv.shutdown()
    print("Страница выключена.")


if __name__ == "__main__":
    main()
