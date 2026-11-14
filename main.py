# -*- coding: utf-8 -*-
"""MT5 Telegram Scalper v6: مدير حسابات متعدد، تحكم كامل من تليجرام"""
import os, sys, time, json, glob, shutil, sqlite3, subprocess, base64, hashlib, math, urllib.request
from datetime import datetime, timezone, timedelta
import numpy as np

try:
    import MetaTrader5 as mt5
except Exception as _e:
    print("MetaTrader5 غير مثبتة:", _e)
    sys.exit(1)
from cryptography.fernet import Fernet


def env(k, d=""):
    v = os.getenv(k)
    return v.strip().strip('"').strip("'") if v and v.strip() else d


TG_TOKEN = env("TELEGRAM_BOT_TOKEN")
SECRET = env("SECRET_ACCESS_KEY")
DB_KEY = env("DB_ENCRYPTION_KEY")
UTC_OFF = int(env("BOT_UTC_OFFSET", "2"))
MAX_ACCOUNTS = int(env("MAX_ACCOUNTS", "6"))
SPREAD_RATIO = float(env("MAX_SPREAD_RATIO", "0.4"))     # أقصى نسبة سبريد من الهدف
MAX_HOLD_MIN = int(env("MAX_HOLD_MINUTES", "20"))        # إغلاق زمني للصفقة العالقة
MAGIC = 990066
DB, RT = "multi_mt5_gold_bot.db", "runtime.db"
START = time.time()
MAX_RUNTIME = 335 * 60
SESSION = (7, 20)                                         # UTC
DIRTY = False
SECRETS = [TG_TOKEN, SECRET, DB_KEY]
AR_DAYS = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]


def log(*a):
    msg = " ".join(str(x) for x in a)
    for s in SECRETS:
        if s and len(s) > 3:
            msg = msg.replace(s, "***")
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# ================= قاعدة البيانات + التشفير =================
_F = {}


def fern():
    if "f" not in _F:
        k = hashlib.pbkdf2_hmac("sha256", DB_KEY.encode(), b"mt5bot-v6", 200000, 32)
        _F["f"] = Fernet(base64.urlsafe_b64encode(k))
    return _F["f"]


def enc(s):
    return fern().encrypt(s.encode()).decode()


def dec(s):
    return fern().decrypt(s.encode()).decode()


def q(file, sql, args=(), one=False):
    c = sqlite3.connect(file, timeout=30)
    try:
        c.row_factory = sqlite3.Row
        cur = c.execute(sql, args)
        if sql.lstrip()[:6].upper() == "SELECT":
            r = cur.fetchall()
            return (dict(r[0]) if r else None) if one else [dict(x) for x in r]
        c.commit()
        return cur.lastrowid
    finally:
        c.close()


def init_db():
    q(DB, "CREATE TABLE IF NOT EXISTS users(chat TEXT PRIMARY KEY)")
    q(DB, """CREATE TABLE IF NOT EXISTS accounts(id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT, blob TEXT,
        enabled INT DEFAULT 1, trading INT DEFAULT 0, lot REAL DEFAULT 0.01, tp REAL DEFAULT 1.0,
        sl REAL DEFAULT 1.0, maxt INT DEFAULT 2, dloss REAL DEFAULT 5, dprofit REAL DEFAULT 10,
        symbol TEXT DEFAULT '', base_day TEXT DEFAULT '', base_val REAL DEFAULT 0, halted TEXT DEFAULT '')""")
    q(DB, "CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT)")
    q(RT, "CREATE TABLE IF NOT EXISTS status(acc INTEGER PRIMARY KEY, txt TEXT, ts REAL)")
    q(RT, "CREATE TABLE IF NOT EXISTS cmds(id INTEGER PRIMARY KEY AUTOINCREMENT, acc INT, cmd TEXT, ts REAL)")
    q(RT, "CREATE TABLE IF NOT EXISTS risk(acc INTEGER PRIMARY KEY, plan TEXT, ts REAL)")


def kv_get(k, d=None):
    r = q(DB, "SELECT v FROM kv WHERE k=?", (k,), one=True)
    return r["v"] if r else d


def kv_set(k, v):
    q(DB, "INSERT OR REPLACE INTO kv VALUES(?,?)", (k, str(v)))


def mark_dirty():
    global DIRTY
    DIRTY = True


# ================= تليجرام =================
def http(url, payload=None, timeout=20):
    data = json.dumps(payload).encode() if payload is not None else None
    try:
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "ignore"))
    except Exception as e:
        return {"error": str(e)}


def tgapi(method, params=None, timeout=20):
    return http(f"https://api.telegram.org/bot{TG_TOKEN}/{method}", params or {}, timeout)


def tg(chat, text, kb=None):
    p = {"chat_id": chat, "text": text[:3900]}
    if kb:
        p["reply_markup"] = {"inline_keyboard": kb}
    return tgapi("sendMessage", p)


HELP = """🤖 أهلاً! كل التحكم من هنا.

➕ ربط حساب:
/add رقم_الحساب كلمة_السر اسم_السيرفر
مثال: /add 12345678 MyPass123 MetaQuotes-Demo

📋 /accounts  ← قائمة حساباتك ولوحة التحكم
⚙️ /set رقم الحساب المفتاح القيمة
  المفاتيح: lot (اللوت) | tp (ربح الصفقة بالدولار) | sl (خسارة الصفقة بالدولار)
  maxt (أقصى صفقات متزامنة 1-5) | dloss (حد خسارة اليوم) | dprofit (حد ربح اليوم) | symbol
  مثال: /set 1 tp 1.5   (القيمة 0 في dloss/dprofit تعني بلا حد)
▶️ /go 1   ⏸ /stop 1   📊 /status 1   ❎ /closeall 1   ♻️ /reset 1   🗑 /del 1

الحساب الجديد يبدأ متوقفاً عن التداول حتى تضغط ▶️."""


def panel_kb(i):
    return [[{"text": "▶️ بدء", "callback_data": f"go:{i}"}, {"text": "⏸ إيقاف", "callback_data": f"stop:{i}"}],
            [{"text": "📊 الحالة", "callback_data": f"p:{i}"}, {"text": "❎ إغلاق الكل", "callback_data": f"ca:{i}"}],
            [{"text": "♻️ تصفير العدادات", "callback_data": f"rs:{i}"}, {"text": "🗑 حذف", "callback_data": f"dl:{i}"}]]


def settings_text(a):
    return (f"⚙️ حساب #{a['id']}\nاللوت {a['lot']} | ربح الصفقة +{a['tp']}$ | خسارة الصفقة -{a['sl']}$\n"
            f"أقصى صفقات متزامنة {a['maxt']} | حد خسارة اليوم {a['dloss']}$ | حد ربح اليوم {a['dprofit']}$\n"
            f"الرمز: {a['symbol'] or 'تلقائي (ذهب)'}\n"
            f"التداول: {'▶️ مفعّل' if a['trading'] else '⏸ متوقف'}"
            f"{' | 🛑 ' + a['halted'].split(':', 1)[-1] if a['halted'] else ''}")


def status_text(a):
    r = q(RT, "SELECT * FROM status WHERE acc=?", (a["id"],), one=True)
    body = r["txt"] if r and time.time() - r["ts"] < 120 else "⏳ الحساب قيد الاتصال أو إعادة الاتصال..."
    return f"📊 حساب #{a['id']}\n{body}\n\n{settings_text(a)}"


def is_user(chat):
    return q(DB, "SELECT 1 AS x FROM users WHERE chat=?", (chat,), one=True) is not None


def my_acc(chat, i):
    return q(DB, "SELECT * FROM accounts WHERE id=? AND owner=?", (i, chat), one=True)


def cmd_add(chat, args):
    parts = args.split(None, 2)
    if len(parts) < 3 or not parts[0].isdigit():
        tg(chat, "الصيغة: /add رقم_الحساب كلمة_السر اسم_السيرفر")
        return
    if q(DB, "SELECT COUNT(*) AS n FROM accounts", one=True)["n"] >= MAX_ACCOUNTS:
        tg(chat, f"❌ وصلت للحد الأقصى ({MAX_ACCOUNTS} حسابات) المسموح على هذا السيرفر.")
        return
    login, pw, server = parts[0], parts[1], parts[2].strip()
    SECRETS.append(pw)
    for r in q(DB, "SELECT * FROM accounts WHERE owner=?", (chat,)):
        try:
            c = json.loads(dec(r["blob"]))
            if c["login"] == login and c["server"] == server:
                tg(chat, f"الحساب موجود مسبقاً (#{r['id']}).", [[{"text": "فتح اللوحة", "callback_data": f"p:{r['id']}"}]])
                return
        except Exception:
            pass
    blob = enc(json.dumps({"login": login, "password": pw, "server": server}))
    i = q(DB, "INSERT INTO accounts(owner,blob) VALUES(?,?)", (chat, blob))
    mark_dirty()
    tg(chat, f"✅ تم حفظ الحساب #{i} مشفّراً. جاري الاتصال (قد يستغرق دقيقة)...\n"
             "🔒 احذف رسالتك التي فيها كلمة السر من المحادثة.")


def do_action(chat, act, i, extra=None):
    a = my_acc(chat, i)
    if not a:
        tg(chat, "❌ حساب غير موجود.")
        return
    if act in ("p", "ss"):
        tg(chat, status_text(a), panel_kb(i))
    elif act == "go":
        q(DB, "UPDATE accounts SET trading=1 WHERE id=?", (i,))
        mark_dirty()
        tg(chat, f"▶️ بدأ التداول على الحساب #{i}. سيصلك تحليل كل دخول أو سبب الانتظار.")
    elif act == "stop":
        q(DB, "UPDATE accounts SET trading=0 WHERE id=?", (i,))
        mark_dirty()
        tg(chat, f"⏸ توقف الدخول على #{i} (الصفقات المفتوحة تبقى بوقفها وهدفها).")
    elif act == "ca":
        q(RT, "INSERT INTO cmds(acc,cmd,ts) VALUES(?,?,?)", (i, "closeall", time.time()))
        tg(chat, "جاري إغلاق كل صفقات البوت على الحساب...")
    elif act == "rs":
        q(RT, "INSERT INTO cmds(acc,cmd,ts) VALUES(?,?,?)", (i, "reset", time.time()))
        tg(chat, "♻️ جاري تصفير عدادات الربح والخسارة اليومية.")
    elif act == "rk":
        q(RT, "INSERT INTO cmds(acc,cmd,ts) VALUES(?,?,?)", (i, f"risk:{extra or 0}", time.time()))
        tg(chat, "⚡ تم استلام طلب المخاطرة، جاري التنفيذ...")
    elif act == "dl":
        tg(chat, f"⚠️ حذف الحساب #{i} نهائياً؟ الصفقات المفتوحة تبقى على حسابك بوقفها وهدفها.",
           [[{"text": "نعم احذف", "callback_data": f"dy:{i}"}, {"text": "تراجع", "callback_data": f"p:{i}"}]])
    elif act == "dy":
        q(DB, "DELETE FROM accounts WHERE id=?", (i,))
        mark_dirty()
        tg(chat, f"🗑 تم حذف الحساب #{i}.")


def on_message(m):
    chat = str(m["chat"]["id"])
    txt = (m.get("text") or "").strip()
    if not txt:
        return
    if txt.startswith("/start"):
        p = txt.split(None, 1)
        if len(p) == 2 and SECRET and p[1].strip() == SECRET:
            q(DB, "INSERT OR IGNORE INTO users VALUES(?)", (chat,))
            mark_dirty()
            tgapi("deleteMessage", {"chat_id": chat, "message_id": m["message_id"]})
            tg(chat, HELP)
        else:
            tg(chat, "أرسل: /start كلمة_السر_السرية")
        return
    if not is_user(chat):
        return
    cmd, _, rest = txt.partition(" ")
    cmd = cmd.split("@")[0].lower()
    rest = rest.strip()
    if cmd == "/add":
        tgapi("deleteMessage", {"chat_id": chat, "message_id": m["message_id"]})
        cmd_add(chat, rest)
    elif cmd in ("/help", "/menu"):
        tg(chat, HELP)
    elif cmd in ("/accounts", "/status") and not rest:
        rows = q(DB, "SELECT * FROM accounts WHERE owner=?", (chat,))
        if not rows:
            tg(chat, "لا حسابات بعد. استخدم /add")
            return
        tg(chat, "📋 حساباتك:", [[{"text": f"#{r['id']} {'▶️' if r['trading'] else '⏸'}", "callback_data": f"p:{r['id']}"}] for r in rows])
    elif cmd == "/set":
        p = rest.split(None, 2)
        if len(p) < 3 or not p[0].isdigit() or not my_acc(chat, int(p[0])):
            tg(chat, "الصيغة: /set رقم_الحساب المفتاح القيمة")
            return
        i, k, v = int(p[0]), p[1].lower(), p[2].strip()
        try:
            if k == "symbol":
                val = v.upper() if v != "-" else ""
            elif k == "maxt":
                val = max(1, min(5, int(v)))
            elif k in ("lot", "tp", "sl"):
                val = float(v)
                assert val > 0
            elif k in ("dloss", "dprofit"):
                val = float(v)
                assert val >= 0
            else:
                raise ValueError
        except Exception:
            tg(chat, "❌ مفتاح أو قيمة غير صالحة. المفاتيح: lot tp sl maxt dloss dprofit symbol")
            return
        q(DB, f"UPDATE accounts SET {k}=? WHERE id=?", (val, i))
        mark_dirty()
        tg(chat, "✅ تم.\n" + settings_text(my_acc(chat, i)))
    elif cmd in ("/go", "/stop", "/status", "/closeall", "/reset", "/del") and rest.isdigit():
        act = {"/go": "go", "/stop": "stop", "/status": "p", "/closeall": "ca", "/reset": "rs", "/del": "dl"}[cmd]
        if act in ("go", "ca") and time.time() - m.get("date", 0) > 600:
            tg(chat, "تجاهلت أمراً قديماً (أكثر من 10 دقائق). أعد إرساله إن كنت تريده.")
            return
        do_action(chat, act, int(rest))


def on_callback(cq):
    chat = str(cq["message"]["chat"]["id"])
    tgapi("answerCallbackQuery", {"callback_query_id": cq["id"]})
    if not is_user(chat):
        return
    p = cq.get("data", "").split(":")
    if len(p) >= 2 and p[1].isdigit():
        do_action(chat, p[0], int(p[1]), p[2] if len(p) > 2 else None)


# ================= مراقبة العمّال + Git =================
WORKERS, LAST_START = {}, 0.0


def start_worker(i):
    global LAST_START
    p = subprocess.Popen([sys.executable, "-X", "utf8", os.path.abspath(__file__), "worker", str(i)])
    WORKERS[i] = {"p": p, "end": None}
    LAST_START = time.time()
    log(f"تشغيل عامل الحساب #{i}")


def supervise():
    ids = {r["id"] for r in q(DB, "SELECT id FROM accounts WHERE enabled=1")}
    for i in list(WORKERS):
        if i not in ids:
            try:
                WORKERS[i]["p"].terminate()
            except Exception:
                pass
            WORKERS.pop(i)
    for i in sorted(ids):
        w = WORKERS.get(i)
        if w and w["p"].poll() is None:
            continue
        if w and w["p"].returncode == 3:                 # فشل تسجيل الدخول: لا إعادة محاولة
            q(DB, "UPDATE accounts SET enabled=0, trading=0 WHERE id=?", (i,))
            mark_dirty()
            WORKERS.pop(i)
            continue
        if w:
            if w["end"] is None:
                w["end"] = time.time()
            if time.time() - w["end"] < 45:
                continue
        if time.time() - LAST_START > 20:
            start_worker(i)


def sh(*cmd):
    try:
        return subprocess.run(list(cmd), capture_output=True, text=True, timeout=90).returncode
    except Exception:
        return 1


def git_sync():
    global DIRTY
    if os.getenv("GITHUB_ACTIONS", "").lower() != "true":
        return
    br = env("GITHUB_REF_NAME", "main")
    sh("git", "config", "user.name", "MT5-Cloud-Bot")
    sh("git", "config", "user.email", "bot@users.noreply.github.com")
    sh("git", "add", DB)
    if sh("git", "diff", "--cached", "--quiet") == 0:
        DIRTY = False
        return
    sh("git", "commit", "-m", "Auto-save bot state [skip ci]")
    if sh("git", "push", "origin", f"HEAD:{br}") != 0:
        if sh("git", "pull", "--rebase", "--autostash", "origin", br) != 0:
            sh("git", "rebase", "--abort")
        if sh("git", "push", "origin", f"HEAD:{br}", "--force") != 0:
            log("git push فشل")
    DIRTY = False


def master():
    if not TG_TOKEN or not SECRET or len(DB_KEY) < 16:
        print("❌ يجب ضبط الأسرار: TELEGRAM_BOT_TOKEN و SECRET_ACCESS_KEY و DB_ENCRYPTION_KEY (16 حرفاً فأكثر)")
        sys.exit(1)
    init_db()
    offset = int(kv_get("offset", 0) or 0)
    last_sync = time.time()
    for u in q(DB, "SELECT chat FROM users"):
        tg(u["chat"], "🟢 البوت يعمل الآن. أرسل /accounts للتحكم.")
    log("المدير يعمل")
    try:
        while time.time() - START < MAX_RUNTIME:
            res = tgapi("getUpdates", {"offset": offset, "timeout": 8,
                                       "allowed_updates": ["message", "callback_query"]}, timeout=25)
            if "error" in res:
                time.sleep(3)
            for u in res.get("result", []) or []:
                offset = u["update_id"] + 1
                kv_set("offset", offset)
                try:
                    if "message" in u:
                        on_message(u["message"])
                    elif "callback_query" in u:
                        on_callback(u["callback_query"])
                except Exception as e:
                    log("خطأ معالجة:", repr(e))
            supervise()
            if (DIRTY and time.time() - last_sync > 60) or time.time() - last_sync > 1200:
                git_sync()
                last_sync = time.time()
    finally:
        for w in WORKERS.values():
            try:
                w["p"].terminate()
            except Exception:
                pass
        git_sync()
    with open("restart.flag", "w") as f:
        f.write("ok")


# ================= المؤشرات =================
def ema(a, n):
    k = 2 / (n + 1)
    out = np.empty(len(a))
    out[0] = a[0]
    for j in range(1, len(a)):
        out[j] = a[j] * k + out[j - 1] * (1 - k)
    return out


def wilder(a, n):
    out = np.zeros(len(a))
    out[n - 1] = a[:n].mean()
    for j in range(n, len(a)):
        out[j] = (out[j - 1] * (n - 1) + a[j]) / n
    return out


def atr(r, n=14):
    h, l, c = r["high"], r["low"], r["close"]
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    return wilder(np.concatenate([[h[0] - l[0]], tr]), n)


def rsi(c, n=14):
    d = np.diff(c, prepend=c[0])
    au, ad = wilder(np.where(d > 0, d, 0.0), n), wilder(np.where(d < 0, -d, 0.0), n)
    rs = np.divide(au, ad, out=np.full_like(au, 100.0), where=ad != 0)
    return 100 - 100 / (1 + rs)


def adx(r, n=14):
    h, l = r["high"], r["low"]
    up, dn = np.diff(h, prepend=h[0]), -np.diff(l, prepend=l[0])
    pdm, mdm = np.where((up > dn) & (up > 0), up, 0.0), np.where((dn > up) & (dn > 0), dn, 0.0)
    a = atr(r, n)
    a = np.where(a == 0, 1, a)
    pdi, mdi = 100 * wilder(pdm, n) / a, 100 * wilder(mdm, n) / a
    s = np.where(pdi + mdi == 0, 1, pdi + mdi)
    return wilder(100 * abs(pdi - mdi) / s, n)


def rates(sym, tf, need):
    r = mt5.copy_rates_from_pos(sym, tf, 1, 320)         # شموع مغلقة فقط
    return r if r is not None and len(r) >= need else None


# ================= عامل الحساب (MT5) =================
def wlog(i, *a):
    log(f"[acc{i}]", *a)


def find_src():
    for p in [r"C:\Program Files\MetaTrader 5"] + glob.glob(r"C:\Program Files*\*MetaTrader*"):
        if os.path.exists(os.path.join(p, "terminal64.exe")):
            return p
    return None


def ensure_terminal(i):
    src = find_src()
    if not src:
        return None
    dst = rf"C:\mt5_acc\{i}"
    exe = os.path.join(dst, "terminal64.exe")
    if not os.path.exists(exe):
        shutil.copytree(src, dst, dirs_exist_ok=True)
    os.makedirs(os.path.join(dst, "config"), exist_ok=True)
    with open(os.path.join(dst, "config", "common.ini"), "w", encoding="utf-16") as f:
        f.write("[Experts]\nEnabled=1\nAllowLiveTrading=1\nAllowDllImport=0\n")
    return exe


def mt5_connect(i, cred, exe):
    err = None
    for _ in range(3):
        mt5.shutdown()
        if mt5.initialize(path=exe, portable=True, login=int(cred["login"]), password=cred["password"],
                          server=cred["server"], timeout=90000):
            ac = mt5.account_info()
            if ac and ac.login == int(cred["login"]):
                return True, None
        err = mt5.last_error()
        wlog(i, "initialize فشل:", err)
        time.sleep(8)
    return False, err


def pick_symbol(pref):
    c = ([pref] if pref else []) + ["XAUUSD", "XAUUSDm", "XAUUSD.", "XAUUSD.a", "XAUUSDc", "GOLD", "GOLDm", "XAUUSD#"]
    for s in c:
        if mt5.symbol_select(s, True) and mt5.symbol_info(s):
            return s
    if not pref:
        for s in mt5.symbols_get() or []:
            if "XAU" in s.name.upper() or "GOLD" in s.name.upper():
                mt5.symbol_select(s.name, True)
                return s.name
    return None


def norm_lot(sym, lot):
    info = mt5.symbol_info(sym)
    step = info.volume_step or 0.01
    lot = math.floor(lot / step + 1e-9) * step
    return round(max(info.volume_min, min(lot, info.volume_max)), 2)


def dist_for(sym, lot, usd, down=False):
    """يحوّل مبلغاً بالدولار إلى مسافة سعرية حقيقية عند هذا اللوت"""
    info, t = mt5.symbol_info(sym), mt5.symbol_info_tick(sym)
    p = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, sym, lot, t.ask, t.ask + info.point * 100)
    if not p:
        return None
    pts = usd / (abs(p) / 100)
    tick = info.trade_tick_size or info.point
    n = pts * info.point / tick
    n = math.floor(n + 1e-9) if down else round(n)
    return max(n, 1) * tick


def local(dt):
    return (dt + timedelta(hours=UTC_OFF)).strftime("%H:%M")


def next_window(kind, now):
    if kind == "session":
        nxt = now.replace(hour=SESSION[0], minute=0, second=0, microsecond=0)
        if now >= nxt:
            nxt += timedelta(days=1)
        while nxt.weekday() >= 5:
            nxt += timedelta(days=1)
        return f"أقرب نافذة: افتتاح لندن {AR_DAYS[(nxt + timedelta(hours=UTC_OFF)).weekday()]} {local(nxt)} بتوقيتك."
    if kind == "spread":
        return "السبريد يتسع عادة عند الأخبار وافتتاح الجلسات ويضيق بعدها؛ أتوقع تحسناً خلال 10–30 دقيقة."
    if kind == "amount":
        return "لن يتحسن الوضع وحده: عدّل المبلغ أو اللوت بالأمر /set."
    w0 = now.replace(hour=13, minute=0, second=0, microsecond=0)
    if now < w0:
        return f"أقوى نافذة سيولة عادةً {local(w0)}–{local(w0 + timedelta(hours=4))} بتوقيتك (تداخل لندن/نيويورك)."
    if now.hour < 17:
        return "نحن داخل أقوى نافذة سيولة؛ أنتظر اتجاهاً واضحاً (عادة خلال 15–60 دقيقة)."
    return "أقوى نافذة لاحقة غداً من 13:00 UTC؛ سأراقب أي تحسن قبلها."


def analyze(sym, a):
    R = {"d": "BLOCK", "ok": [], "bad": [], "kind": "", "side": None, "score": 0, "risk_ok": False}
    info, t = mt5.symbol_info(sym), mt5.symbol_info_tick(sym)
    if not info or not t or t.ask <= 0:
        R["bad"].append("لا أسعار حية"); R["kind"] = "data"; return R
    if info.trade_mode != mt5.SYMBOL_TRADE_MODE_FULL:
        R["bad"].append("السوق مغلق أو الرمز غير متاح للتداول"); R["kind"] = "session"; return R
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5 or not (SESSION[0] <= now.hour < SESSION[1]) or (now.weekday() == 4 and now.hour >= 19):
        R["bad"].append("خارج ساعات السيولة (لندن/نيويورك)"); R["kind"] = "session"; return R
    spread = t.ask - t.bid
    lot = norm_lot(sym, a["lot"])
    dtp, dsl = dist_for(sym, lot, a["tp"]), dist_for(sym, lot, a["sl"], True)
    if not dtp or not dsl:
        R["bad"].append("تعذر حساب مستويات الدولار"); R["kind"] = "amount"; return R
    minstop = info.trade_stops_level * info.point + spread + 2 * info.point
    if min(dsl, dtp) < minstop:
        R["bad"].append(f"مبلغ الوقف/الهدف صغير جداً: مسافتك {min(dsl, dtp):.2f} والمطلوب ≥ {minstop:.2f}")
        R["kind"] = "amount"; return R
    spread_bad = spread > SPREAD_RATIO * dtp
    if spread_bad:
        R["bad"].append(f"السبريد {spread:.2f} يلتهم {spread / dtp * 100:.0f}% من هدفك ({dtp:.2f})")
    m15, m5, m1 = rates(sym, mt5.TIMEFRAME_M15, 220), rates(sym, mt5.TIMEFRAME_M5, 60), rates(sym, mt5.TIMEFRAME_M1, 60)
    if m15 is None or m5 is None or m1 is None:
        R["bad"].append("بيانات الشموع غير كافية"); R["kind"] = "data"; return R
    c15 = m15["close"]
    e50, e200 = ema(c15, 50), ema(c15, 200)
    d15 = 1 if (e50[-1] > e200[-1] and c15[-1] > e50[-1] and e50[-1] > e50[-4]) else \
        -1 if (e50[-1] < e200[-1] and c15[-1] < e50[-1] and e50[-1] < e50[-4]) else 0
    c5 = m5["close"]
    e9, e21, ax, at5 = ema(c5, 9), ema(c5, 21), adx(m5)[-1], atr(m5)[-1]
    d5 = 1 if (e9[-1] > e21[-1] and c5[-1] > e21[-1]) else -1 if (e9[-1] < e21[-1] and c5[-1] < e21[-1]) else 0
    c1, o1 = m1["close"], m1["open"]
    e9m, r7, at1 = ema(c1, 9), rsi(c1, 7), atr(m1)[-1]
    trig = 0
    if m1["low"][-2] <= e9m[-2] and c1[-1] > e9m[-1] and c1[-1] > o1[-1] and 40 <= r7[-1] <= 70 and r7[-1] > r7[-2]:
        trig = 1
    elif m1["high"][-2] >= e9m[-2] and c1[-1] < e9m[-1] and c1[-1] < o1[-1] and 30 <= r7[-1] <= 60 and r7[-1] < r7[-2]:
        trig = -1
    sc = 0
    if d15:
        sc += 30; R["ok"].append("اتجاه M15 " + ("صاعد" if d15 > 0 else "هابط") + " (EMA50/200)")
    else:
        R["bad"].append("لا اتجاه واضح على M15 (السوق متذبذب)")
    if d15 and d5 == d15:
        sc += 20; R["ok"].append("زخم M5 يوافق الاتجاه (EMA9/21)")
    else:
        R["bad"].append("زخم M5 لا يوافق اتجاه M15")
    if d15 and trig == d15:
        sc += 25; R["ok"].append("ارتداد مؤكد على M1 عند EMA9 مع RSI(7) متجه")
    else:
        R["bad"].append("لا إشارة ارتداد/دخول مؤكدة على M1")
    if ax >= 20:
        sc += 15; R["ok"].append(f"قوة الاتجاه ADX={ax:.0f}")
    else:
        R["bad"].append(f"ADX={ax:.0f} ضعيف (سوق عرضي)")
    if dtp / 4 <= at1 <= 1.5 * dsl:
        sc += 10; R["ok"].append("تذبذب الدقيقة مناسب لحجم هدفك ووقفك")
    elif at1 > 1.5 * dsl:
        R["bad"].append(f"ضجيج الدقيقة ({at1:.2f}) أكبر من وقفك ({dsl:.2f}): سيُضرب بالعشوائية")
    else:
        R["bad"].append("حركة الدقيقة أضعف من أن تبلغ هدفك بسرعة")
    if abs(c5[-1] - e21[-1]) > 2.5 * at5:
        sc -= 15; R["bad"].append("السعر ممتد بعيداً عن متوسطه (دخول متأخر خطر)")
    side = d15 or d5 or trig
    R.update(score=sc, side=("BUY" if side > 0 else "SELL") if side else None, adx=ax, spread=spread, dtp=dtp, dsl=dsl)
    if d15 and d5 == d15 and trig == d15 and sc >= 85 and not spread_bad:
        R["d"] = "ENTER"
        return R
    R["kind"] = "spread" if spread_bad else "trend" if not d15 else "adx" if ax < 20 else "trigger"
    R["risk_ok"] = bool(side) and sc >= 40 and spread <= 0.8 * dtp
    R["d"] = "WEAK" if R["risk_ok"] else "BLOCK"
    return R


# ---------- التنفيذ ----------
OK = (10008, 10009, 10010)
TR = {}


def fills(info):
    f = []
    if info.filling_mode & 2:
        f.append(mt5.ORDER_FILLING_IOC)
    if info.filling_mode & 1:
        f.append(mt5.ORDER_FILLING_FOK)
    return f + [mt5.ORDER_FILLING_RETURN]


def open_trade(i, owner, sym, side, a, tag, why):
    info, acc = mt5.symbol_info(sym), mt5.account_info()
    lot = norm_lot(sym, a["lot"])
    dtp, dsl = dist_for(sym, lot, a["tp"]), dist_for(sym, lot, a["sl"], True)
    buy = side == "BUY"
    typ = mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL
    t = mt5.symbol_info_tick(sym)
    margin = mt5.order_calc_margin(typ, sym, lot, t.ask if buy else t.bid)
    if margin is None or margin > acc.margin_free * 0.5:
        return False, "الهامش الحر لا يكفي"
    fl, last = fills(info), None
    for n in range(6):
        t = mt5.symbol_info_tick(sym)
        price = t.ask if buy else t.bid
        sl = round(price - dsl if buy else price + dsl, info.digits)
        tp = round(price + dtp if buy else price - dtp, info.digits)
        req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": lot, "type": typ, "price": price,
               "sl": sl, "tp": tp, "deviation": 20, "magic": MAGIC, "comment": tag,
               "type_time": mt5.ORDER_TIME_GTC, "type_filling": fl[n % len(fl)]}
        res = mt5.order_send(req)
        last = res
        if res is None:
            time.sleep(1.5); continue
        if res.retcode in OK:
            break
        if res.retcode == 10016:                       # افتح أولاً ثم ركّب الوقف
            req.pop("sl"); req.pop("tp")
            r2 = mt5.order_send(req)
            if r2 and r2.retcode in OK:
                time.sleep(1)
                for p in mt5.positions_get(symbol=sym) or []:
                    if p.magic == MAGIC and p.sl == 0:
                        mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": p.ticket,
                                        "symbol": sym, "sl": sl, "tp": tp})
                res = r2
                break
        if res.retcode in (10017, 10018, 10019, 10027, 10040, 10042, 10043, 10044):
            return False, f"رفض الوسيط (كود {res.retcode})" + (" - فعّل Algo Trading" if res.retcode == 10027 else "")
        time.sleep(1.5 if res.retcode == 10024 else 0.7)
    else:
        return False, f"فشل التنفيذ (كود {last.retcode if last else 'None'})"
    time.sleep(0.4)
    pos = [p for p in (mt5.positions_get(symbol=sym) or []) if p.magic == MAGIC]
    p = next((x for x in pos if x.ticket == res.order), None) or (max(pos, key=lambda x: x.time) if pos else None)
    if not p:
        return True, "تم"
    TR[p.ticket] = {"side": side}
    tg(owner, f"📈 دخول {side} {sym} | حساب #{i}{' ⚡ مخاطرة' if tag == 'RISK' else ''}\n"
              f"💵 اللوت {lot} | الهامش المحجوز ≈ {margin:.2f}$\n📍 سعر الدخول: {p.price_open}\n"
              f"🛑 STOP على المنصة: {p.sl}  (خسارة ≤ {a['sl']}$)\n🎯 TOP على المنصة: {p.tp}  (ربح ≈ {a['tp']}$)\n"
              f"⏱ إغلاق زمني تلقائي بعد {MAX_HOLD_MIN} دقيقة إن لم يضرب أحدهما\n🧠 سبب الدخول:\n{why}")
    return True, "تم"


def close_pos(p):
    t = mt5.symbol_info_tick(p.symbol)
    buy = p.type == 0
    info = mt5.symbol_info(p.symbol)
    for f in fills(info):
        r = mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": p.symbol, "volume": p.volume,
                            "type": mt5.ORDER_TYPE_SELL if buy else mt5.ORDER_TYPE_BUY, "position": p.ticket,
                            "price": t.bid if buy else t.ask, "deviation": 30, "magic": MAGIC,
                            "comment": "close", "type_time": mt5.ORDER_TIME_GTC, "type_filling": f})
        if r and r.retcode in OK:
            return True
    return False


def my_pos():
    return [p for p in (mt5.positions_get() or []) if p.magic == MAGIC]


def track_closed(i, owner):
    cur = {p.ticket for p in my_pos()}
    for tk in list(TR):
        if tk not in cur:
            out = [d for d in (mt5.history_deals_get(position=tk) or []) if d.entry == mt5.DEAL_ENTRY_OUT]
            if out:
                pnl = sum(d.profit + d.commission + d.swap for d in out)
                why = {mt5.DEAL_REASON_TP: "🎯 ضرب الهدف", mt5.DEAL_REASON_SL: "🛑 ضرب الوقف"}.get(out[-1].reason, "إغلاق بالبوت/يدوي")
                tg(owner, f"{'✅ ربح' if pnl >= 0 else '❌ خسارة'} #{tk} حساب #{i}: {pnl:+.2f}$ ({why})")
            TR.pop(tk)
    for tk in cur:
        TR.setdefault(tk, {})


def day_info(sym, ign):
    t = mt5.symbol_info_tick(sym)
    ts = t.time if t and t.time else time.time()
    day0 = int(ts // 86400 * 86400)
    frm = datetime.fromtimestamp(day0 - 86400, timezone.utc)
    deals = mt5.history_deals_get(frm, frm + timedelta(days=4)) or []
    mine = sorted([d for d in deals if d.magic == MAGIC and d.entry == mt5.DEAL_ENTRY_OUT and d.time >= day0],
                  key=lambda d: d.time, reverse=True)
    realized = sum(d.profit + d.commission + d.swap for d in mine)
    streak, last_loss = 0, 0
    for d in mine:
        if d.time <= ign:
            break
        if d.profit + d.commission + d.swap < 0:
            streak += 1
            last_loss = last_loss or d.time
        else:
            break
    floating = sum(p.profit + p.swap for p in my_pos())
    return datetime.fromtimestamp(day0, timezone.utc).strftime("%Y-%m-%d"), realized, floating, streak, last_loss, ts


def worker(i):
    a = q(DB, "SELECT * FROM accounts WHERE id=?", (i,), one=True)
    if not a:
        sys.exit(0)
    owner = a["owner"]
    cred = json.loads(dec(a["blob"]))
    SECRETS.append(cred["password"])
    exe = ensure_terminal(i)
    if not exe:
        tg(owner, f"❌ حساب #{i}: لم أجد منصة MT5 على السيرفر."); sys.exit(4)
    ok, err = mt5_connect(i, cred, exe)
    if not ok:
        if err and err[0] == -6:
            tg(owner, f"❌ حساب #{i}: فشل تسجيل الدخول (رقم الحساب/كلمة السر/السيرفر غير صحيحة). "
                      f"احذفه بـ /del {i} وأضفه من جديد بالبيانات الصحيحة.")
            sys.exit(3)
        tg(owner, f"⚠️ حساب #{i}: تعذر الاتصال بالسيرفر {cred['server']} {err}. سأعيد المحاولة تلقائياً.")
        sys.exit(4)
    acc = mt5.account_info()
    sym = pick_symbol(a["symbol"])
    if not sym:
        tg(owner, f"❌ حساب #{i}: لم أجد رمز الذهب عند الوسيط. حدده: /set {i} symbol اسم_الرمز"); sys.exit(3)
    kind = "تجريبي" if acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO else "حقيقي ⚠️"
    ti = mt5.terminal_info()
    tg(owner, f"✅ تم ربط الحساب #{i} ({kind}) | {cred['server']}\n💰 الرصيد {acc.balance:.2f} {acc.currency} | الرمز {sym}\n"
              + ("" if ti and ti.trade_allowed else "⚠️ Algo Trading مغلق في المنصة، قد تُرفض الأوامر.\n")
              + ("▶️ التداول يعمل." if a["trading"] else "⏸ التداول متوقف: اضغط ▶️ لبدء."),
       [[{"text": "🎛 لوحة التحكم", "callback_data": f"p:{i}"}]])
    last_bar, last_ns, ign, fails, notified_halt = 0, 0, 0, 0, ""
    for p in my_pos():
        TR[p.ticket] = {}
    while True:
        try:
            a = q(DB, "SELECT * FROM accounts WHERE id=?", (i,), one=True)
            if not a or not a["enabled"]:
                break
            if not mt5.terminal_info() or not mt5.account_info():
                fails += 1
                ok, _ = mt5_connect(i, cred, exe)
                if not ok and fails >= 3:
                    tg(owner, f"❌ حساب #{i}: انقطع الاتصال. الصفقات المفتوحة محمية بوقف وهدف على السيرفر.")
                    sys.exit(4)
                continue
            fails = 0
            maxt = max(1, min(5, a["maxt"]))
            daykey, realized, floating, streak, last_loss, sts = day_info(sym, ign)
            base = a["base_val"] if a["base_day"] == daykey else 0.0
            pnl = realized - base + floating
            if a["halted"] and not a["halted"].startswith(daykey):
                q(DB, "UPDATE accounts SET halted='' WHERE id=?", (i,)); a["halted"] = ""
            for c in q(RT, "SELECT * FROM cmds WHERE acc=? ORDER BY id", (i,)):
                q(RT, "DELETE FROM cmds WHERE id=?", (c["id"],))
                if c["cmd"] == "closeall":
                    n = sum(1 for p in my_pos() if close_pos(p))
                    tg(owner, f"❎ حساب #{i}: تم إغلاق {n} صفقة.")
                elif c["cmd"] == "reset":
                    q(DB, "UPDATE accounts SET base_day=?, base_val=?, halted='' WHERE id=?", (daykey, realized, i))
                    ign = int(sts); a["halted"] = ""; pnl = floating; streak = 0
                    tg(owner, f"♻️ حساب #{i}: تم تصفير عدادات اليوم واستئناف الدخول.")
                elif c["cmd"].startswith("risk"):
                    plan = q(RT, "SELECT * FROM risk WHERE acc=?", (i,), one=True)
                    if not plan or time.time() - plan["ts"] > 600 or time.time() - c["ts"] > 600:
                        tg(owner, f"⌛ حساب #{i}: لا توجد فرصة مخاطرة صالحة الآن (انتهت صلاحيتها).")
                    elif len(my_pos()) >= maxt or a["halted"]:
                        tg(owner, f"❌ حساب #{i}: لا يمكن المخاطرة (وصلت للحد الأقصى للصفقات أو التداول متوقف).")
                    else:
                        side = json.loads(plan["plan"])["side"]
                        ok2, msg = open_trade(i, owner, sym, side, a, "RISK",
                                              "• مخاطرة يدوية بطلبك رغم أن التحليل لم يكتمل (خسارة محدودة بالوقف).")
                        if not ok2:
                            tg(owner, f"❌ حساب #{i}: {msg}")
                        q(RT, "DELETE FROM risk WHERE acc=?", (i,))
            track_closed(i, owner)
            for p in my_pos():                                   # إغلاق زمني
                if sts - p.time > MAX_HOLD_MIN * 60 and close_pos(p):
                    tg(owner, f"⏱ حساب #{i}: أُغلقت #{p.ticket} زمنياً (تجاوزت {MAX_HOLD_MIN} دقيقة بلا هدف/وقف).")
            if not a["halted"]:
                why = None
                if a["dloss"] > 0 and pnl <= -a["dloss"]:
                    why = f"وصلت لحد الخسارة اليومي ({pnl:+.2f}$)"
                elif a["dprofit"] > 0 and pnl >= a["dprofit"]:
                    why = f"وصلت لحد الربح اليومي ({pnl:+.2f}$)"
                if why:
                    for p in my_pos():
                        close_pos(p)
                    q(DB, "UPDATE accounts SET halted=? WHERE id=?", (f"{daykey}:{why}", i))
                    a["halted"] = f"{daykey}:{why}"
                    tg(owner, f"🛑 حساب #{i}: {why}. أغلقت الصفقات وأوقفت الدخول حتى غداً أو /reset {i}.")
            cooldown = streak >= 3 and sts - last_loss < 900
            state = ("🛑 " + a["halted"].split(":", 1)[-1]) if a["halted"] else "⏸ التداول متوقف" if not a["trading"] \
                else "😴 استراحة 15 دقيقة بعد 3 خسائر متتالية" if cooldown else "🔍 أحلل السوق"
            ac = mt5.account_info()
            q(RT, "INSERT OR REPLACE INTO status VALUES(?,?,?)",
              (i, f"💰 رصيد {ac.balance:.2f} | إكويتي {ac.equity:.2f} {ac.currency}\n📂 صفقات مفتوحة {len(my_pos())}/{maxt} "
                  f"(عائم {floating:+.2f}$)\n📆 نتيجة اليوم {pnl:+.2f}$ | خسائر متتالية {streak}\n🔁 {state}", time.time()))
            if a["trading"] and not a["halted"] and not cooldown:
                bar = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 1, 1)
                if bar is not None and int(bar[-1]["time"]) != last_bar:
                    last_bar = int(bar[-1]["time"])
                    R = analyze(sym, a)
                    pos = my_pos()
                    if R["d"] == "ENTER":
                        opp = any((p.type == 0) != (R["side"] == "BUY") for p in pos)
                        if len(pos) < maxt and not opp:
                            ok2, msg = open_trade(i, owner, sym, R["side"], a, "ProBot",
                                                  "\n".join("• " + x for x in R["ok"]) + f"\n📊 درجة الثقة {R['score']}/100")
                            if not ok2 and time.time() - last_ns > 900:
                                last_ns = time.time()
                                tg(owner, f"⚠️ حساب #{i}: لم يُنفَّذ الدخول: {msg}")
                    elif not pos and time.time() - last_ns > 1800:
                        last_ns = time.time()
                        now = datetime.now(timezone.utc)
                        txt = (f"⏳ الوقت الحالي غير مناسب للتداول (حساب #{i})\n❓ السبب:\n"
                               + "\n".join("• " + x for x in R["bad"][:5])
                               + f"\n\n🔮 توقعي للوقت المناسب: {next_window(R['kind'], now)}\n(تقدير تقريبي وليس ضماناً)")
                        kb = None
                        if R["risk_ok"]:
                            q(RT, "INSERT OR REPLACE INTO risk VALUES(?,?,?)", (i, json.dumps({"side": R["side"]}), time.time()))
                            kb = [[{"text": f"⚡ خاطر (خسارة ≤ {a['sl']}$)", "callback_data": f"rk:{i}:{int(time.time())}"}]]
                            txt += f"\n\nاتجاه المخاطرة المحتمل: {R['side']} (ثقة {R['score']}/100)"
                        tg(owner, txt, kb)
        except SystemExit:
            raise
        except Exception as e:
            wlog(i, "خطأ:", repr(e))
        time.sleep(2)
    mt5.shutdown()


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "worker":
        worker(int(sys.argv[2]))
    else:
        master()
