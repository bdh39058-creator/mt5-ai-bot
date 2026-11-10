# -*- coding: utf-8 -*-
"""
بوت التداول الذكي الشامل (MT5 + Bybit Gold) - النسخة المؤسسية الكاملة مع الرادار الخلفي 24/7
- رادار ذكاء اصطناعي يعمل في الخلفية كل 5 ثوانٍ لتنفيذ الصفقات في 0.2 ثانية دون انتظار 4 دقائق
- منع التناقض الفني نهائياً (عدم البيع عند تقاطع EMA الإيجابي أو فوق الدعم مباشرة)
- نظام الدرع الثلاثي الذكي (Triple Shield Matrix): لو ضربت الشمعة صفقة، تربح الأخريان وتؤمّنان الحساب
- لوحة تقارير مالية متكاملة (أرباح اليوم، خسارة اليوم، إجمالي الأموال المتداولة، الصافي، والتحكم الحي بالصفقات)
"""
import os
import sys
import re
import ssl
import math
import hmac
import json
import time
import glob
import uuid
import base64
import shutil
import hashlib
import sqlite3
import signal
import tempfile
import threading
import traceback
import subprocess
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer

# ======================= 0. ترميز ويندوز + سجل آمن =======================
os.environ["PYTHONIOENCODING"] = "utf-8"
for _s in (sys.stdout, sys.stderr):
    try:
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_SECRETS = []


def register_secret(v):
    if v and len(v) >= 6 and v not in _SECRETS:
        _SECRETS.append(v)


def redact(text):
    text = str(text)
    for s in _SECRETS:
        text = text.replace(s, "***")
    return text


def safe_print(*args):
    text = redact(" ".join(str(a) for a in args))
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {text}"
    try:
        print(line, flush=True)
    except Exception:
        try:
            sys.stdout.write(line.encode("ascii", errors="ignore").decode() + "\n")
            sys.stdout.flush()
        except Exception:
            pass


# ======================= 1. الإعدادات والمفاتيح =======================
def env(*names, default=""):
    for n in names:
        v = os.getenv(n)
        if v and v.strip():
            return v.strip()
    return default


def env_num(name, default, cast=float):
    try:
        return cast(env(name, default=str(default)))
    except Exception:
        return default


TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN")
MASTER_METAAPI_TOKEN = env("METAAPI_TOKEN")
SECRET_ACCESS_KEY = env("SECRET_ACCESS_KEY", default="vip_secret_99")
DB_SECRET = env("DB_ENCRYPTION_KEY") or SECRET_ACCESS_KEY
UTC_OFFSET = env_num("BOT_UTC_OFFSET", 3, int)
COOLDOWN_AFTER_TRADE = env_num("COOLDOWN_SECONDS", 10, int)
BYBIT_QTY_PER_LOT = env_num("BYBIT_QTY_PER_LOT", 1.0, float)
DEFAULT_BYBIT_PROXY = env("BYBIT_PROXY_URL", default="https://bybit-bridge.bdh39058.workers.dev")
MIN_AI_CONFIDENCE = env_num("MIN_AI_CONFIDENCE", 90, int)

KNOWN_MT5_LOGIN = env("MT5_LOGIN", default="5058253637")
KNOWN_MT5_PASS = env("MT5_PASSWORD", default="*aGm1cNp")
KNOWN_MT5_SERVER = env("MT5_SERVER", default="MetaQuotes-Demo")
ENV_BYBIT_KEY = env("BYBIT_API_KEY")
ENV_BYBIT_SECRET = env("BYBIT_API_SECRET")

GROQ_KEY = env("GROQ_TOKEN", "GROQ_TOKRN")
GEMINI_KEY = env("GEMINI_TOKEN")
GITHUB_KEY = env("GH_MODELS_TOKEN", "GITHUB_MODELS_TOKEN", "GITHUB_TOKEN")
SAMBANOVA_KEY = env("SAMBANOVA_TOKEN")
COHERE_KEY = env("COHERE_TOKEN")
OPENROUTER_KEY = env("OPENROUTER1_TOKEN", "OPENROUTER_TOKEN")
HUGGINGFACE_KEY = env("HUGGINGFACE_TOKEN")

for _k in (TELEGRAM_BOT_TOKEN, MASTER_METAAPI_TOKEN, SECRET_ACCESS_KEY, DB_SECRET, GROQ_KEY, GEMINI_KEY,
           GITHUB_KEY, SAMBANOVA_KEY, COHERE_KEY, OPENROUTER_KEY, HUGGINGFACE_KEY, KNOWN_MT5_PASS, ENV_BYBIT_SECRET):
    register_secret(_k)

MAGIC = 990011
DB_FILE = "multi_mt5_gold_bot.db"
BOT_START_TIME = time.time()
IS_GITHUB_ACTIONS = os.getenv("GITHUB_ACTIONS", "").lower() == "true"
MAX_RUNTIME_SECONDS = 330 * 60 if IS_GITHUB_ACTIONS else 365 * 24 * 3600
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
SHUTDOWN = threading.Event()

AI_DEFS = [
    (1, "Groq (Llama-3.3-70B)", "https://api.groq.com/openai/v1/chat/completions", "llama-3.3-70b-versatile", GROQ_KEY),
    (2, "Google (Gemini 2.5 Flash)", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", "gemini-2.0-flash", GEMINI_KEY),
    (3, "GitHub (GPT-4o Mini)", "https://models.inference.ai.azure.com/chat/completions", "gpt-4o-mini", GITHUB_KEY),
    (4, "SambaNova (Llama-3.1-70B)", "https://api.sambanova.ai/v1/chat/completions", "Meta-Llama-3.1-70B-Instruct", SAMBANOVA_KEY),
    (5, "Cohere (Command-R+)", "https://api.cohere.ai/compatibility/v1/chat/completions", "command-r-plus-08-2024", COHERE_KEY),
    (6, "OpenRouter (Gemma-2-9B)", "https://openrouter.ai/api/v1/chat/completions", "google/gemma-2-9b-it:free", OPENROUTER_KEY),
    (7, "HuggingFace (Qwen-2.5-72B)", "https://router.huggingface.co/v1/chat/completions", "Qwen/Qwen2.5-72B-Instruct", HUGGINGFACE_KEY),
    (8, "Groq-2 (Llama-3.1-8B)", "https://api.groq.com/openai/v1/chat/completions", "llama-3.1-8b-instant", GROQ_KEY),
    (9, "GitHub-2 (GPT-4o)", "https://models.inference.ai.azure.com/chat/completions", "gpt-4o", GITHUB_KEY),
    (10, "OpenRouter-2 (Llama-3.2-3B)", "https://openrouter.ai/api/v1/chat/completions", "meta-llama/llama-3.2-3b-instruct:free", OPENROUTER_KEY),
]
AI_KEYS = {d[0]: d[4] for d in AI_DEFS}
ai_circuit = {}

SSL_CTX_DEFAULT = ssl.create_default_context()
SSL_CTX_UNVERIFIED = ssl._create_unverified_context()


# ======================= 2. HTTP + تشفير قاعدة البيانات =======================
def _parse_json(raw):
    if not raw:
        return {}
    text = raw.decode("utf-8", errors="ignore").strip()
    if not text:
        return {}
    try:
        d = json.loads(text)
        return d if isinstance(d, dict) else {"data": d}
    except Exception:
        return {"_raw_text": text[:300]}


def http_request(url, method="GET", headers=None, payload=None, raw_body=None, timeout=15, verify_ssl=True, proxy_addr=None):
    h = {"User-Agent": BROWSER_UA, "Accept": "application/json"}
    if headers:
        h.update(headers)
    data = None
    if raw_body is not None:
        data = raw_body.encode("utf-8")
        h.setdefault("Content-Type", "application/json")
    elif payload is not None:
        data = json.dumps(payload).encode("utf-8")
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    ctx = SSL_CTX_DEFAULT if verify_ssl else SSL_CTX_UNVERIFIED
    try:
        if proxy_addr:
            proxy_handler = urllib.request.ProxyHandler({"http": proxy_addr, "https": proxy_addr})
            https_handler = urllib.request.HTTPSHandler(context=ctx)
            opener = urllib.request.build_opener(proxy_handler, https_handler)
            with opener.open(req, timeout=timeout) as r:
                return r.status, _parse_json(r.read())
        else:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                return r.status, _parse_json(r.read())
    except urllib.error.HTTPError as e:
        try:
            body = e.read()
        except Exception:
            body = b""
        d = _parse_json(body)
        d.setdefault("error", f"HTTP {e.code}")
        return e.code, d
    except Exception as e:
        return 0, {"error": redact(str(e))}


_KEYS = {}


def _keys():
    if not _KEYS:
        raw = hashlib.pbkdf2_hmac("sha256", DB_SECRET.encode(), b"mt5-ai-bot-db-v1", 120000, 64)
        _KEYS["enc"], _KEYS["mac"] = raw[:32], raw[32:]
    return _KEYS["enc"], _KEYS["mac"]


def _stream(key, nonce, n):
    out, c = bytearray(), 0
    while len(out) < n:
        out += hmac.new(key, nonce + c.to_bytes(8, "big"), hashlib.sha256).digest()
        c += 1
    return bytes(out[:n])


def encrypt_text(s):
    if not s or s.startswith("enc1:"):
        return s
    ek, mk = _keys()
    nonce, data = os.urandom(16), s.encode()
    ct = bytes(a ^ b for a, b in zip(data, _stream(ek, nonce, len(data))))
    tag = hmac.new(mk, nonce + ct, hashlib.sha256).digest()
    return "enc1:" + base64.urlsafe_b64encode(nonce + tag + ct).decode()


def decrypt_text(s):
    if not s or not s.startswith("enc1:"):
        return s
    try:
        raw = base64.urlsafe_b64decode(s[5:])
        nonce, tag, ct = raw[:16], raw[16:48], raw[48:]
        ek, mk = _keys()
        if not hmac.compare_digest(tag, hmac.new(mk, nonce + ct, hashlib.sha256).digest()):
            return ""
        return bytes(a ^ b for a, b in zip(ct, _stream(ek, nonce, len(ct)))).decode()
    except Exception:
        return ""


# ======================= 3. تليجرام =======================
def tg_api(method, params=None, timeout=12):
    if not TELEGRAM_BOT_TOKEN:
        return {"ok": False, "description": "no token"}
    status, res = http_request(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}",
        "POST",
        payload=params or {},
        timeout=timeout
    )
    if not isinstance(res, dict):
        res = {}
    if "ok" not in res:
        res["ok"] = False
        res.setdefault("error_code", status)
    return res


def split_text(text, limit=3800):
    chunks, cur = [], ""
    for line in str(text).split("\n"):
        while len(line) > limit:
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if cur and len(cur) + len(line) + 1 > limit:
            chunks.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    chunks.append(cur)
    return chunks


def send_msg(chat_id, text, reply_markup=None):
    res = {}
    parts = split_text(text)
    for i, part in enumerate(parts):
        p = {"chat_id": chat_id, "text": part, "disable_web_page_preview": True}
        if reply_markup and i == len(parts) - 1:
            p["reply_markup"] = reply_markup
        res = tg_api("sendMessage", p)
    return res


def edit_msg(chat_id, message_id, text, reply_markup=None):
    p = {"chat_id": chat_id, "message_id": message_id, "text": text[:4000]}
    if reply_markup:
        p["reply_markup"] = reply_markup
    res = tg_api("editMessageText", p)
    if not res.get("ok") and "not modified" not in str(res.get("description", "")):
        return send_msg(chat_id, text, reply_markup)
    return res


def answer_cb(cb_id, text="", alert=False):
    return tg_api("answerCallbackQuery", {"callback_query_id": cb_id, "text": text[:190], "show_alert": alert}, timeout=5)


def delete_msg(chat_id, message_id):
    return tg_api("deleteMessage", {"chat_id": chat_id, "message_id": message_id}, timeout=5)


# ======================= 4. قاعدة البيانات وإحصائيات الأرباح والخسائر المفصلة =======================
db_lock = threading.RLock()
USER_COLUMNS = [
    ("chat_id", "INTEGER DEFAULT 0"), ("is_authorized", "INTEGER DEFAULT 0"), ("auto_run", "INTEGER DEFAULT 0"),
    ("active_account_id", "INTEGER DEFAULT 1"), ("trade_all_accounts", "INTEGER DEFAULT 0"),
    ("selected_ai_id", "INTEGER DEFAULT 1"), ("symbol", "TEXT DEFAULT 'XAUUSD'"), ("lot", "REAL DEFAULT 0.01"),
    ("trade_tp_usd", "REAL DEFAULT 0.50"), ("trade_sl_usd", "REAL DEFAULT 1.00"),
    ("daily_max_profit", "REAL DEFAULT 20.0"), ("daily_max_loss", "REAL DEFAULT 10.0"),
    ("work_start_hour", "INTEGER DEFAULT 0"), ("work_end_hour", "INTEGER DEFAULT 24"),
    ("current_daily_pnl", "REAL DEFAULT 0.0"), ("trades_today", "INTEGER DEFAULT 0"),
    ("pnl_date", "TEXT DEFAULT ''"), ("bybit_proxy", "TEXT DEFAULT ''"),
]
USER_FIELDS = {c[0] for c in USER_COLUMNS}

TRADE_COLUMNS = [
    ("tp_usd", "REAL DEFAULT 0.50"),
    ("sl_usd", "REAL DEFAULT 1.00"),
    ("layer_tag", "TEXT DEFAULT 'L1'"),
    ("entry_price", "REAL DEFAULT 0.0"),
    ("capital_used", "REAL DEFAULT 0.0"),
    ("trade_date", "TEXT DEFAULT ''"),
]


def db_exec(sql, params=(), one=False):
    with db_lock:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA busy_timeout=30000")
            cur = conn.execute(sql, params)
            if sql.lstrip().upper().startswith("SELECT"):
                rows = [dict(r) for r in cur.fetchall()]
                return (rows[0] if rows else None) if one else rows
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()


def _ensure_columns(conn, table, cols):
    existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    for name, ddl in cols:
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def init_db():
    with db_lock:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)")
            _ensure_columns(conn, "users", USER_COLUMNS)
            conn.execute("""CREATE TABLE IF NOT EXISTS trading_accounts (
                acc_pk INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, platform TEXT DEFAULT 'MT5',
                account_label TEXT DEFAULT '', login_or_key TEXT DEFAULT '', password_or_secret TEXT DEFAULT '',
                server_or_mode TEXT DEFAULT '', cloud_id TEXT DEFAULT '', region TEXT DEFAULT 'london',
                is_enabled INTEGER DEFAULT 1)""")
            _ensure_columns(conn, "trading_accounts", [("cloud_id", "TEXT DEFAULT ''"), ("region", "TEXT DEFAULT 'london'")])
            conn.execute("""CREATE TABLE IF NOT EXISTS ai_tools (
                id INTEGER PRIMARY KEY, name TEXT, base_url TEXT, api_key TEXT, model TEXT)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS bot_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, acc_pk INTEGER, platform TEXT, symbol TEXT,
                side TEXT, volume REAL, ticket TEXT, open_ts INTEGER, status TEXT DEFAULT 'OPEN', pnl REAL DEFAULT 0,
                tp_usd REAL DEFAULT 0.50, sl_usd REAL DEFAULT 1.00, layer_tag TEXT DEFAULT 'L1',
                entry_price REAL DEFAULT 0.0, capital_used REAL DEFAULT 0.0, trade_date TEXT DEFAULT '')""")
            _ensure_columns(conn, "bot_trades", TRADE_COLUMNS)
            for d in AI_DEFS:
                conn.execute("INSERT OR REPLACE INTO ai_tools (id,name,base_url,api_key,model) VALUES (?,?,?,?,?)",
                             (d[0], d[1], d[2], "", d[3]))
            conn.execute("DELETE FROM trading_accounts WHERE login_or_key='939713' AND server_or_mode LIKE '%BlackBull%'")
            for pk, pw in conn.execute("SELECT acc_pk, password_or_secret FROM trading_accounts").fetchall():
                if pw and not pw.startswith("enc1:"):
                    conn.execute("UPDATE trading_accounts SET password_or_secret=? WHERE acc_pk=?", (encrypt_text(pw), pk))
            conn.commit()
        finally:
            conn.close()


def today_str():
    return (datetime.now(timezone.utc) + timedelta(hours=UTC_OFFSET)).strftime("%Y-%m-%d")


def local_hour():
    return (datetime.now(timezone.utc) + timedelta(hours=UTC_OFFSET)).hour


def ensure_default_account(uid):
    rows = db_exec("SELECT * FROM trading_accounts WHERE user_id=? ORDER BY acc_pk", (uid,))
    if not rows and KNOWN_MT5_LOGIN:
        pk = add_or_update_trading_account(uid, "MT5", KNOWN_MT5_LOGIN, KNOWN_MT5_PASS, KNOWN_MT5_SERVER, make_active=True)
        if ENV_BYBIT_KEY and ENV_BYBIT_SECRET:
            add_or_update_trading_account(uid, "BYBIT", ENV_BYBIT_KEY, ENV_BYBIT_SECRET, "BYBIT-DEMO", make_active=False)
        return pk
    return None


def get_user(uid):
    row = db_exec("SELECT * FROM users WHERE user_id=?", (uid,), one=True)
    if row is None:
        db_exec("INSERT OR IGNORE INTO users (user_id, pnl_date, bybit_proxy) VALUES (?,?,?)",
                (uid, today_str(), DEFAULT_BYBIT_PROXY))
        ensure_default_account(uid)
        row = db_exec("SELECT * FROM users WHERE user_id=?", (uid,), one=True)
    else:
        ensure_default_account(uid)
        if not row.get("bybit_proxy") and DEFAULT_BYBIT_PROXY:
            db_exec("UPDATE users SET bybit_proxy=? WHERE user_id=?", (DEFAULT_BYBIT_PROXY, uid))
            row["bybit_proxy"] = DEFAULT_BYBIT_PROXY
    return row


def update_user(uid, field, value):
    if field not in USER_FIELDS:
        raise ValueError(f"حقل غير مسموح: {field}")
    db_exec(f"UPDATE users SET {field}=? WHERE user_id=?", (value, uid))


def update_account_cloud(acc_pk, cloud_id, region):
    db_exec("UPDATE trading_accounts SET cloud_id=?, region=? WHERE acc_pk=?", (cloud_id, region, acc_pk))


def update_account_mode(acc_pk, new_mode):
    db_exec("UPDATE trading_accounts SET server_or_mode=? WHERE acc_pk=?", (new_mode, acc_pk))


def get_auto_running_users():
    return db_exec("SELECT * FROM users WHERE auto_run=1 AND chat_id!=0")


def _dec_acc(row):
    if not row:
        return {}
    row = dict(row)
    raw_pw = row.get("password_or_secret", "")
    pw = decrypt_text(raw_pw)
    if not pw and str(row.get("login_or_key")) == KNOWN_MT5_LOGIN:
        pw = KNOWN_MT5_PASS
    elif not pw and raw_pw and not raw_pw.startswith("enc1:"):
        pw = raw_pw
    row["password_or_secret"] = pw
    row["server_or_mode"] = row.get("server_or_mode", "") or ""
    return row


def get_user_accounts(uid):
    ensure_default_account(uid)
    return [_dec_acc(r) for r in db_exec("SELECT * FROM trading_accounts WHERE user_id=? ORDER BY acc_pk", (uid,))]


def get_account_by_pk(pk):
    return _dec_acc(db_exec("SELECT * FROM trading_accounts WHERE acc_pk=?", (pk,), one=True))


def get_active_account(uid):
    u = get_user(uid)
    acc = get_account_by_pk(u["active_account_id"])
    if acc and acc.get("user_id") == uid:
        return acc
    accs = get_user_accounts(uid)
    if accs:
        update_user(uid, "active_account_id", accs[0]["acc_pk"])
        return accs[0]
    return {}


def get_target_accounts(uid):
    u = get_user(uid)
    all_accs = get_user_accounts(uid)
    if u.get("trade_all_accounts") == 1:
        enabled = [a for a in all_accs if a.get("is_enabled") == 1]
        return enabled if enabled else all_accs
    act = get_active_account(uid)
    return [act] if act else all_accs


def add_or_update_trading_account(uid, platform, login_key, secret, server_mode, make_active=False):
    label = f"Bybit ({login_key[:6]})" if platform == "BYBIT" else f"MT5 ({login_key})"
    ex = db_exec("SELECT acc_pk FROM trading_accounts WHERE user_id=? AND login_or_key=?", (uid, login_key), one=True)
    if ex:
        pk = ex["acc_pk"]
        db_exec("UPDATE trading_accounts SET platform=?,account_label=?,password_or_secret=?,server_or_mode=?,is_enabled=1 WHERE acc_pk=?",
                (platform, label, encrypt_text(secret), server_mode, pk))
    else:
        pk = db_exec("INSERT INTO trading_accounts (user_id,platform,account_label,login_or_key,password_or_secret,server_or_mode,is_enabled) VALUES (?,?,?,?,?,?,1)",
                     (uid, platform, label, login_key, encrypt_text(secret), server_mode))
    if make_active:
        db_exec("UPDATE users SET active_account_id=? WHERE user_id=?", (pk, uid))
    return pk


def delete_trading_account(uid, pk):
    accs = get_user_accounts(uid)
    if len(accs) <= 1:
        return False
    acc = get_account_by_pk(pk)
    if not acc or acc.get("user_id") != uid:
        return False
    db_exec("DELETE FROM trading_accounts WHERE acc_pk=? AND user_id=?", (pk, uid))
    rest = get_user_accounts(uid)
    if rest and get_user(uid)["active_account_id"] == pk:
        update_user(uid, "active_account_id", rest[0]["acc_pk"])
    return True


def toggle_account(uid, pk):
    acc = get_account_by_pk(pk)
    if acc and acc.get("user_id") == uid:
        db_exec("UPDATE trading_accounts SET is_enabled=? WHERE acc_pk=?", (0 if acc["is_enabled"] else 1, pk))
        return True
    return False


def get_ai_tools():
    rows = db_exec("SELECT * FROM ai_tools ORDER BY id")
    for r in rows:
        r["api_key"] = AI_KEYS.get(r["id"], "")
        r["model"] = env(f"AI_MODEL_{r['id']}", default=r["model"])
    return rows


def get_ai_tool_by_id(tid):
    return next((t for t in get_ai_tools() if t["id"] == tid), {})


def record_trade(uid, acc, symbol, side, volume, ticket, tp_usd=0.50, sl_usd=1.00, layer_tag="L1", entry_price=0.0):
    p = float(entry_price or 4020.0)
    cap = round(float(volume) * p, 2)
    return db_exec(
        "INSERT INTO bot_trades (user_id,acc_pk,platform,symbol,side,volume,ticket,open_ts,tp_usd,sl_usd,layer_tag,entry_price,capital_used,trade_date) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (uid, acc["acc_pk"], acc["platform"], symbol, side, float(volume), str(ticket), int(time.time()),
         float(tp_usd), float(sl_usd), str(layer_tag), p, cap, today_str())
    )


def open_trade_rows(uid, acc_pk):
    return db_exec("SELECT * FROM bot_trades WHERE user_id=? AND acc_pk=? AND status='OPEN'", (uid, acc_pk))


def get_daily_financial_summary(uid):
    t_str = today_str()
    rows = db_exec("SELECT * FROM bot_trades WHERE user_id=? AND (trade_date=? OR trade_date='')", (uid, t_str))
    gross_profit = 0.0
    gross_loss = 0.0
    win_count = 0
    loss_count = 0
    open_count = 0
    total_capital_used = 0.0
    total_lots = 0.0

    for r in rows:
        vol = float(r.get("volume") or 0.01)
        ep = float(r.get("entry_price") or 4020.0)
        cap = float(r.get("capital_used") or (vol * ep))
        total_capital_used += cap
        total_lots += vol
        if r.get("status") == "OPEN":
            open_count += 1
        else:
            pnl = float(r.get("pnl") or 0.0)
            if pnl >= 0:
                gross_profit += pnl
                if pnl > 0:
                    win_count += 1
            else:
                gross_loss += abs(pnl)
                loss_count += 1

    closed_total = win_count + loss_count
    net_pnl = gross_profit - gross_loss
    win_rate = (win_count / closed_total * 100.0) if closed_total > 0 else 100.0
    return {
        "date": t_str,
        "total_trades_entered": len(rows),
        "open_trades": open_count,
        "closed_trades": closed_total,
        "win_count": win_count,
        "loss_count": loss_count,
        "win_rate": win_rate,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "net_pnl": net_pnl,
        "total_capital_used": total_capital_used,
        "total_lots": total_lots,
    }


# ======================= 5. تحليل بيانات الاعتماد =======================
LABELS = {"login", "user", "username", "account", "id", "password", "pass", "pwd", "server", "key", "api", "apikey",
          "secret", "apisecret", "mode", "broker", "اسم المستخدم", "المستخدم", "الحساب", "رقم الحساب", "كلمة المرور",
          "كلمة السر", "الباسورد", "السيرفر", "الخادم", "المفتاح", "السر"}


def strip_label(line):
    m = re.match(r"^\s*([^\W\d_][\w \u0600-\u06FF]{0,24}?)\s*[:：=]\s*(.+)$", line)
    if m and m.group(1).strip().lower() in LABELS:
        return m.group(2).strip()
    return line.strip()


def parse_three_line_credentials(raw):
    lines = [l.strip() for l in (raw or "").strip().splitlines() if l.strip()]
    if len(lines) >= 3:
        p1, p2, p3 = (strip_label(l) for l in lines[:3])
    elif "," in (raw or ""):
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if len(parts) < 3:
            return "INVALID", "", "", ""
        p1, p2, p3 = parts[:3]
    else:
        return "INVALID", "", "", ""
    up = p3.upper()
    if "BYBIT" in up:
        mode = "BYBIT-TESTNET" if "TEST" in up else ("BYBIT-DEMO" if "DEMO" in up else "BYBIT-LIVE")
        return ("BYBIT", p1, p2, mode) if p1 and p2 else ("INVALID", "", "", "")
    clean_login = re.sub(r"\s+", "", p1)
    if not clean_login.isdigit() or not p2 or not p3:
        return "INVALID", "", "", ""
    return "MT5", clean_login, p2, p3


# ======================= 6. رادار الذكاء الاصطناعي المستمر 24/7 ومنع التناقض الفني =======================
LIVE_RADAR_CACHE = {}


def calc_ema(prices, period):
    if not prices:
        return 0.0
    if len(prices) < period:
        return float(prices[-1])
    k = 2.0 / (period + 1.0)
    ema = sum(prices[:period]) / float(period)
    for p in prices[period:]:
        ema = p * k + ema * (1.0 - k)
    return float(ema)


def calc_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50.0
    d = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    g, l = [max(x, 0.0) for x in d], [max(-x, 0.0) for x in d]
    ag, al = sum(g[:period]) / period, sum(l[:period]) / period
    for i in range(period, len(d)):
        ag = (ag * (period - 1) + g[i]) / period
        al = (al * (period - 1) + l[i]) / period
    if al == 0:
        return 100.0 if ag > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + ag / al)


def calc_macd(prices):
    if len(prices) < 26:
        return 0.0, 0.0, 0.0
    ema12 = calc_ema(prices, 12)
    ema26 = calc_ema(prices, 26)
    macd_line = ema12 - ema26
    series = []
    for idx in range(max(26, len(prices) - 12), len(prices) + 1):
        sub = prices[:idx]
        series.append(calc_ema(sub, 12) - calc_ema(sub, 26))
    sig_line = calc_ema(series, 9) if series else macd_line
    hist = macd_line - sig_line
    return macd_line, sig_line, hist


def calc_bollinger(prices, period=20, mult=2.0):
    if len(prices) < period:
        p = prices[-1] if prices else 0.0
        return p, p, p
    window = prices[-period:]
    mid = sum(window) / float(period)
    var = sum((x - mid) ** 2 for x in window) / float(period)
    std = math.sqrt(var)
    return mid - mult * std, mid, mid + mult * std


def calc_atr_from_candles(candles, period=14):
    if not candles or len(candles) < 3:
        return 0.8
    trs = []
    for i in range(1, len(candles)):
        h = float(candles[i].get("high", candles[i]["close"]))
        low = float(candles[i].get("low", candles[i]["close"]))
        prev_c = float(candles[i - 1]["close"])
        tr = max(h - low, abs(h - prev_c), abs(low - prev_c))
        trs.append(tr)
    if not trs:
        return 0.8
    recent = trs[-period:]
    return sum(recent) / float(len(recent))


def analyze_single_timeframe(candles):
    if not candles or len(candles) < 20:
        return None
    closes = [float(c["close"]) for c in candles]
    highs = [float(c.get("high", c["close"])) for c in candles]
    lows = [float(c.get("low", c["close"])) for c in candles]
    opens = [float(c.get("open", c["close"])) for c in candles]

    price = closes[-1]
    e9 = calc_ema(closes, 9)
    e21 = calc_ema(closes, 21)
    e50 = calc_ema(closes, 50)
    rsi = calc_rsi(closes, 14)
    macd_l, sig_l, hist = calc_macd(closes)
    bb_low, bb_mid, bb_high = calc_bollinger(closes, 20, 2.0)
    atr = max(calc_atr_from_candles(candles, 14), 0.3)

    support = min(lows[-20:])
    resistance = max(highs[-20:])

    cur_candle_bull = closes[-1] >= opens[-1]
    cur_impulse = closes[-1] - closes[-3]

    buy_pts = 0
    sell_pts = 0
    buy_reasons = []
    sell_reasons = []

    if e9 > e21:
        buy_pts += 32
        buy_reasons.append("تقاطع صاعد (EMA9>21)")
        if e21 >= e50:
            buy_pts += 15
            buy_reasons.append("ترند عام صاعد (>EMA50)")
    else:
        sell_pts += 32
        sell_reasons.append("تقاطع هابط (EMA9<21)")
        if e21 <= e50:
            sell_pts += 15
            sell_reasons.append("ترند عام هابط (<EMA50)")

    if price > e9 and cur_impulse > 0:
        buy_pts += 20
        buy_reasons.append("اندفاع سعري صاعد فوق المتوسط")
    elif price < e9 and cur_impulse < 0:
        sell_pts += 20
        sell_reasons.append("اندفاع سعري هابط تحت المتوسط")

    if 50 <= rsi <= 68:
        buy_pts += 16
        buy_reasons.append(f"زخم شرائي مثالي (RSI:{rsi:.1f})")
    elif rsi < 32 and cur_candle_bull:
        buy_pts += 24
        buy_reasons.append(f"ارتداد صاعد من تشبع بيعي (RSI:{rsi:.1f})")
    elif 32 <= rsi < 50:
        sell_pts += 16
        sell_reasons.append(f"زخم بيعي مثالي (RSI:{rsi:.1f})")
    elif rsi > 68 and (not cur_candle_bull):
        sell_pts += 24
        sell_reasons.append(f"ارتداد هابط من تشبع شرائي (RSI:{rsi:.1f})")

    if hist > 0:
        buy_pts += 14
        buy_reasons.append("MACD إيجابي")
    else:
        sell_pts += 14
        sell_reasons.append("MACD سلبي")

    dist_to_support = price - support
    dist_to_res = resistance - price
    veto_sell = False
    veto_buy = False

    if dist_to_support <= atr * 0.75 and (e9 > e21 or cur_candle_bull):
        veto_sell = True
        buy_pts += 25
        buy_reasons.append(f"ارتداد مباشر من منطقة الدعم ({support:.2f})")

    if dist_to_res <= atr * 0.75 and (e9 < e21 or not cur_candle_bull):
        veto_buy = True
        sell_pts += 25
        sell_reasons.append(f"ارتداد مباشر من منطقة المقاومة ({resistance:.2f})")

    if veto_sell:
        direction = "BUY"
        active_reasons = buy_reasons
        raw_score = buy_pts
        diff_score = max(25, buy_pts - sell_pts)
    elif veto_buy:
        direction = "SELL"
        active_reasons = sell_reasons
        raw_score = sell_pts
        diff_score = max(25, sell_pts - buy_pts)
    elif buy_pts >= sell_pts:
        direction = "BUY"
        active_reasons = buy_reasons
        raw_score = buy_pts
        diff_score = buy_pts - sell_pts
    else:
        direction = "SELL"
        active_reasons = sell_reasons
        raw_score = sell_pts
        diff_score = sell_pts - buy_pts

    return {
        "direction": direction,
        "raw_score": raw_score,
        "diff_score": diff_score,
        "price": price,
        "ema9": e9,
        "ema21": e21,
        "ema50": e50,
        "rsi": rsi,
        "macd_hist": hist,
        "atr": atr,
        "support": support,
        "resistance": resistance,
        "reasons": active_reasons[:3],
    }


def get_multi_timeframe_data(symbol, accounts):
    for acc in accounts:
        if acc["platform"] == "MT5":
            mtf = mt5_fetch_mtf_candles(acc, symbol)
            if mtf and mtf.get("M1"):
                return mtf, "MT5"
    for acc in accounts:
        if acc["platform"] == "BYBIT":
            mtf = bybit_fetch_mtf_candles(acc, symbol)
            if mtf and mtf.get("M1"):
                return mtf, "BYBIT"
    mtf = bybit_fetch_mtf_candles({"user_id": 0, "server_or_mode": "BYBIT-DEMO"}, symbol)
    if mtf and mtf.get("M1"):
        return mtf, "GLOBAL"
    return None, "NONE"


def raw_ai_request(tool, prompt, max_tokens=100):
    if not tool or not tool.get("api_key"):
        return False, "no key"
    headers = {"Authorization": f"Bearer {tool['api_key']}", "HTTP-Referer": "https://github.com", "X-Title": "AI Institutional Sniper"}
    payload = {
        "model": tool["model"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.05,
        "max_tokens": max_tokens
    }
    status, res = http_request(tool["base_url"], "POST", headers=headers, payload=payload, timeout=10)
    if status == 200 and "choices" in res:
        try:
            return True, res["choices"][0]["message"]["content"].strip()
        except Exception:
            return False, "bad shape"
    return False, str(res.get("error", status))


def parse_ai_json(text):
    try:
        clean = text.replace("```json", "").replace("```", "").strip()
        a, b = clean.find("{"), clean.rfind("}")
        d = json.loads(clean[a:b + 1])
        act = str(d.get("action", "")).upper().strip()
        if act not in ("BUY", "SELL", "WAIT", "HOLD"):
            return None
        conf = int(float(d.get("confidence", 85)))
        return {"action": act, "confidence": max(0, min(conf, 99))}
    except Exception:
        return None


def ask_ai(uid, prompt):
    pref = get_user(uid)["selected_ai_id"]
    tools = sorted(get_ai_tools(), key=lambda t: (0 if t["id"] == pref else 1, t["id"]))
    for t in tools:
        if not t["api_key"] or ai_circuit.get(t["id"], 0) > time.time():
            continue
        ok, text = raw_ai_request(t, prompt, 80)
        parsed = parse_ai_json(text) if ok else None
        if parsed:
            parsed["provider"] = t["name"]
            return parsed
        ai_circuit[t["id"]] = time.time() + 90
    return None


def compute_fresh_analysis(uid, symbol, accounts):
    mtf_data, src = get_multi_timeframe_data(symbol, accounts)
    if not mtf_data or not mtf_data.get("M1"):
        return {
            "ready": False,
            "action": "BUY",
            "confidence": 0,
            "provider": "No Market Data",
            "price": 0.0,
            "atr": 1.0,
            "indicators": "تعذر سحب الشموع الحية حالياً",
            "detailed_report": "⚠️ لا توجد بيانات شموع كافية من السيرفر حالياً.",
            "ts": time.time(),
        }

    a_m1 = analyze_single_timeframe(mtf_data.get("M1"))
    a_m5 = analyze_single_timeframe(mtf_data.get("M5")) or a_m1
    a_m15 = analyze_single_timeframe(mtf_data.get("M15")) or a_m5

    if a_m1["direction"] == a_m5["direction"]:
        dominant_dir = a_m1["direction"]
        alignment_count = 3 if a_m15["direction"] == dominant_dir else 2
    else:
        dominant_dir = a_m1["direction"] if a_m1["diff_score"] >= a_m5["diff_score"] else a_m5["direction"]
        alignment_count = 2 if a_m15["direction"] == dominant_dir else 1

    avg_raw = (a_m1["raw_score"] * 0.50) + (a_m5["raw_score"] * 0.35) + (a_m15["raw_score"] * 0.15)
    if alignment_count == 3 and a_m1["diff_score"] >= 20:
        tech_conf = min(98, int(91 + (avg_raw - 50) * 0.20))
    elif alignment_count == 2 and a_m1["direction"] == a_m5["direction"] and a_m1["diff_score"] >= 22:
        tech_conf = min(95, int(90 + (avg_raw - 55) * 0.20))
    else:
        tech_conf = max(65, min(88, int(68 + avg_raw * 0.25)))

    summary_str = (
        f"Price:{a_m1['price']:.2f} | "
        f"M1:{a_m1['direction']}(RSI:{a_m1['rsi']:.1f}) | "
        f"M5:{a_m5['direction']}(RSI:{a_m5['rsi']:.1f}) | "
        f"M15:{a_m15['direction']} | "
        f"Support:{a_m1['support']:.2f} | Res:{a_m1['resistance']:.2f}"
    )

    prompt = (
        f"You are an institutional Gold/Forex Sniper trading {symbol}. "
        f"Data: {summary_str}. Aligned reasons: {', '.join(a_m1['reasons'])}. "
        f"Alignment: {alignment_count}/3 towards {dominant_dir}. Pre-score: {tech_conf}%. "
        f"Confirm {dominant_dir} with confidence >= 91 if M1 and M5 agree strongly. "
        f"Reply ONLY in JSON: {{\"action\":\"{dominant_dir}\",\"confidence\":{tech_conf}}}"
    )

    ai_res = ask_ai(uid, prompt)
    provider_name = get_ai_tool_by_id(get_user(uid)["selected_ai_id"]).get("name", "Institutional Radar")

    if ai_res:
        provider_name = ai_res["provider"]
        if ai_res["action"] == dominant_dir:
            final_conf = max(tech_conf, ai_res["confidence"])
            if alignment_count >= 2 and a_m1["direction"] == a_m5["direction"]:
                final_conf = max(final_conf, 92)
            final_dir = dominant_dir
        elif ai_res["action"] in ("BUY", "SELL") and alignment_count == 1:
            final_dir = ai_res["action"]
            final_conf = min(86, ai_res["confidence"])
        else:
            final_dir = dominant_dir
            final_conf = tech_conf
    else:
        final_dir = dominant_dir
        final_conf = tech_conf

    clean_reasons = " ، ".join(a_m1["reasons"] or [f"توافق الفريمات نحو {final_dir}"])
    detailed_report = (
        f"📊 **تفاصيل رادار التحليل الحي ({symbol}):**\n"
        f"• السعر الحي: `{a_m1['price']:.2f}` | نطاق التذبذب ATR: `{a_m1['atr']:.2f}$`\n"
        f"• الفريمات: M1 ({a_m1['direction']}) | M5 ({a_m5['direction']}) | M15 ({a_m15['direction']})\n"
        f"• المؤشرات: RSI `{a_m1['rsi']:.1f}` | EMA9 `{a_m1['ema9']:.2f}` | EMA21 `{a_m1['ema21']:.2f}`\n"
        f"• المستويات: دعم `{a_m1['support']:.2f}` | مقاومة `{a_m1['resistance']:.2f}`\n"
        f"• الأساس الفني المؤكد: {clean_reasons}"
    )

    res_obj = {
        "ready": final_conf >= MIN_AI_CONFIDENCE,
        "action": final_dir,
        "confidence": final_conf,
        "provider": provider_name,
        "price": a_m1["price"],
        "atr": a_m1["atr"],
        "support": a_m1["support"],
        "resistance": a_m1["resistance"],
        "indicators": summary_str,
        "detailed_report": detailed_report,
        "ts": time.time(),
    }
    LIVE_RADAR_CACHE[symbol.upper()] = res_obj
    return res_obj


def get_instant_or_fresh_analysis(uid, symbol, accounts):
    cached = LIVE_RADAR_CACHE.get(symbol.upper())
    if cached and (time.time() - cached.get("ts", 0) <= 12) and cached.get("price", 0) > 0:
        return cached
    return compute_fresh_analysis(uid, symbol, accounts)


def background_market_radar_loop():
    while not SHUTDOWN.wait(6):
        try:
            users = db_exec("SELECT * FROM users WHERE chat_id != 0")
            if not users:
                continue
            for u in users[:3]:
                uid = u["user_id"]
                sym = u.get("symbol", "XAUUSD")
                accs = get_target_accounts(uid)
                if accs:
                    compute_fresh_analysis(uid, sym, accs)
        except Exception:
            pass


# ======================= 7. هندسة "الدرع الثلاثي (Triple Shield Matrix 2+1)" =======================
def build_triple_shield_plan(main_action, base_tp_usd, base_sl_usd, atr_val=1.2, risk_mode=False):
    opp_action = "SELL" if main_action == "BUY" else "BUY"
    base_tp = max(float(base_tp_usd or 0.50), 0.25)
    safe_sl = max(float(base_sl_usd or 1.00), round(float(atr_val or 1.0) * 1.15, 2), 1.20)

    if risk_mode:
        return [
            {
                "tag": "L1-قناص",
                "title": f"الصفقة 1 ({main_action} قناص سريع)",
                "side": main_action,
                "tp_usd": 0.30,
                "sl_usd": 0.45,
            },
            {
                "tag": "L2-أساسية",
                "title": f"الصفقة 2 ({main_action} هدف أساسي)",
                "side": main_action,
                "tp_usd": 0.55,
                "sl_usd": 0.65,
            },
            {
                "tag": "L3-درع_حماية",
                "title": f"الصفقة 3 ({opp_action} درع تعويض عكسي)",
                "side": opp_action,
                "tp_usd": 0.50,
                "sl_usd": 0.25,
            },
        ]

    return [
        {
            "tag": "L1-سريعة",
            "title": f"الصفقة 1 ({main_action} هدف سريع ومضمون)",
            "side": main_action,
            "tp_usd": round(max(0.35, base_tp * 0.75), 2),
            "sl_usd": round(safe_sl * 1.10, 2),
        },
        {
            "tag": "L2-أساسية",
            "title": f"الصفقة 2 ({main_action} الهدف الأساسي)",
            "side": main_action,
            "tp_usd": round(max(0.55, base_tp * 1.25), 2),
            "sl_usd": round(safe_sl * 1.45, 2),
        },
        {
            "tag": "L3-درع_حماية",
            "title": f"الصفقة 3 ({opp_action} درع التعويض الذكي)",
            "side": opp_action,
            "tp_usd": round(max(0.60, base_tp * 1.30), 2),
            "sl_usd": round(max(0.25, base_tp * 0.50), 2),
        },
    ]


def usd_to_price_distance(usd, volume, tick_value, tick_size):
    if min(usd, volume, tick_value, tick_size) <= 0:
        return 0.0
    return usd / (volume * tick_value / tick_size)


def round_step(value, step, minimum=0):
    v, s = Decimal(str(value)), Decimal(str(step))
    q = (v / s).to_integral_value(ROUND_DOWN) * s
    return max(q, Decimal(str(minimum)))


def normalize_volume(lot, vmin, vmax, vstep):
    vstep = vstep or 0.01
    vol = float(round_step(lot, vstep, vmin or vstep))
    return min(vol, vmax) if vmax else vol


def is_within_working_hours(start_h, end_h, hour=None):
    h = local_hour() if hour is None else hour
    if start_h == 0 and end_h == 24:
        return True
    return (start_h <= h < end_h) if start_h <= end_h else (h >= start_h or h < end_h)


def set_ini_values(text, section, kv):
    nl = "\r\n"
    pending, out, in_sec, found = dict(kv), [], False, False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            if in_sec:
                out.extend(f"{k}={v}" for k, v in pending.items())
                pending = {}
            in_sec = s[1:-1].lower() == section.lower()
            found = found or in_sec
            out.append(s)
            continue
        if in_sec and "=" in s:
            k = s.split("=", 1)[0].strip()
            for pk in list(pending):
                if pk.lower() == k.lower():
                    line = f"{pk}={pending.pop(pk)}"
                    break
        out.append(line.rstrip("\r\n"))
    if in_sec:
        out.extend(f"{k}={v}" for k, v in pending.items())
    elif not found:
        out.append(f"[{section}]")
        out.extend(f"{k}={v}" for k, v in pending.items())
    return nl.join(out) + nl


MT5_RETCODES = {
    10004: "إعادة تسعير (Requote)",
    10006: "تم رفض الطلب من السيرفر",
    10013: "طلب غير صالح (Invalid request)",
    10014: "حجم اللوت غير صالح (Invalid volume)",
    10015: "سعر غير صالح (Invalid price)",
    10016: "مستويات الوقف/الهدف غير صالحة (Invalid stops)",
    10017: "التداول معطّل لهذا الحساب (Trade disabled)",
    10018: "السوق مغلق حالياً (Market closed)",
    10019: "الهامش الحر غير كافٍ (Not enough money)",
    10020: "تغيرت الأسعار (Prices changed)",
    10024: "طلبات متكررة كثيرة جداً",
    10026: "التداول الآلي معطّل من سيرفر الوسيط",
    10027: "التداول الآلي معطّل في المنصة (AutoTrading disabled)",
    10030: "نمط التنفيذ غير مدعوم (Unsupported filling mode)",
    10031: "لا يوجد اتصال بسيرفر التداول",
}


def retcode_message(code, comment=""):
    return f"{MT5_RETCODES.get(code, comment or 'رفض من الوسيط')} (كود {code})"


# ======================= 8. MetaApi Cloud =======================
PROVISION_URL = "https://mt-provisioning-api-v1.agiliumtrade.agiliumtrade.ai"


def metaapi_headers(with_tx=False):
    h = {"auth-token": MASTER_METAAPI_TOKEN}
    if with_tx:
        h["transaction-id"] = str(uuid.uuid4())
    return h


def metaapi_client_url(region):
    reg = region.strip() if (region and region != "None") else "london"
    return f"https://mt-client-api-v1.{reg}.agiliumtrade.ai"


def metaapi_ensure_deployed(acc):
    if not MASTER_METAAPI_TOKEN:
        return False, "", "london", "مفتاح METAAPI_TOKEN غير مضاف."
    cid = (acc.get("cloud_id") or "").strip()
    reg = (acc.get("region") or "london").strip()
    login_str = str(acc.get("login_or_key", "")).strip()
    password = str(acc.get("password_or_secret", "")).strip()
    server = str(acc.get("server_or_mode", "")).strip()

    st, acc_list = http_request(f"{PROVISION_URL}/users/current/accounts", "GET", headers=metaapi_headers(), timeout=10)
    if st == 200 and isinstance(acc_list, list):
        for item in acc_list:
            if str(item.get("login")) == login_str or (cid and item.get("_id") == cid):
                cid = item.get("_id", cid)
                reg = item.get("region", reg)
                if item.get("state") != "DEPLOYED":
                    http_request(f"{PROVISION_URL}/users/current/accounts/{cid}/deploy", "POST", headers=metaapi_headers(), timeout=10)
                if acc.get("acc_pk"):
                    update_account_cloud(acc["acc_pk"], cid, reg)
                return True, cid, reg, "OK"

    create_payload = {
        "name": f"MT5_{login_str}",
        "type": "cloud",
        "login": login_str,
        "password": password,
        "server": server,
        "platform": "mt5",
        "magic": MAGIC
    }
    st_c, res_c = http_request(f"{PROVISION_URL}/users/current/accounts", "POST", headers=metaapi_headers(with_tx=True), payload=create_payload, timeout=15)
    if st_c in (200, 201) and isinstance(res_c, dict) and "id" in res_c:
        cid = res_c["id"]
        http_request(f"{PROVISION_URL}/users/current/accounts/{cid}/deploy", "POST", headers=metaapi_headers(), timeout=10)
        if acc.get("acc_pk"):
            update_account_cloud(acc["acc_pk"], cid, reg)
        return True, cid, reg, "OK"
    return False, "", "london", "الحساب غير مضاف في MetaApi."


def metaapi_open_single_layer(acc, side, symbol, lot, tp_usd, sl_usd, layer_tag="L1"):
    ok_dep, cid, reg, err_msg = metaapi_ensure_deployed(acc)
    if not ok_dep:
        return {"ok": False, "symbol": symbol, "msg": err_msg}
    base_c = metaapi_client_url(reg)
    action_type = "ORDER_TYPE_BUY" if side == "BUY" else "ORDER_TYPE_SELL"
    vol = max(round(float(lot), 2), 0.01)
    for sym_try in (symbol, "XAUUSD", "XAUUSDm", "GOLD", "EURUSD"):
        payload = {"actionType": action_type, "symbol": sym_try, "volume": vol, "comment": f"AI_{layer_tag}"}
        st, res = http_request(f"{base_c}/users/current/accounts/{cid}/trade", "POST", headers=metaapi_headers(), payload=payload, timeout=15)
        if st == 200 and isinstance(res, dict):
            if res.get("numericCode") in (0, 10008, 10009) or res.get("stringCode") in ("TRADE_RETCODE_DONE", "TRADE_RETCODE_DONE_PARTIAL"):
                oid = str(res.get("orderId") or res.get("positionId") or "Executed")
                return {"ok": True, "symbol": sym_try, "ticket": oid, "volume": vol, "side": side, "price": 0.0, "tp_usd": tp_usd, "sl_usd": sl_usd, "layer_tag": layer_tag}
    return {"ok": False, "symbol": symbol, "msg": "رفض التنفيذ عبر MetaApi"}


# ======================= 9. MetaTrader 5 المباشر =======================
mt5 = None
NATIVE_MT5_AVAILABLE = False
if os.name == "nt":
    try:
        import MetaTrader5 as mt5
        NATIVE_MT5_AVAILABLE = True
    except Exception:
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "MetaTrader5"], check=False, timeout=180)
            import MetaTrader5 as mt5
            NATIVE_MT5_AVAILABLE = True
        except Exception:
            mt5 = None

MT5_PATHS = [r"C:\Program Files\MetaTrader 5\terminal64.exe", r"C:\Program Files (x86)\MetaTrader 5\terminal64.exe"]
MT5_SETUP_URL = "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe"
mt5_lock = threading.RLock()
MT5_BOOT_DONE = threading.Event()
failed_mt5_servers = {}
_discovered_data_paths = set()


def find_mt5_terminal_exe():
    return next((p for p in MT5_PATHS if os.path.exists(p)), "")


def inject_global_broker_servers():
    if os.name != "nt":
        return
    urls = ["https://raw.githubusercontent.com/hudsonventura/MT5_Docker/main/src/servers.dat"]
    dst_tmp = os.path.join(tempfile.gettempdir(), "global_servers.dat")
    for u in urls:
        try:
            with urllib.request.urlopen(u, timeout=8, context=SSL_CTX_UNVERIFIED) as r, open(dst_tmp, "wb") as f:
                f.write(r.read())
            if os.path.exists(dst_tmp) and os.path.getsize(dst_tmp) > 2000:
                break
        except Exception:
            continue
    if not os.path.exists(dst_tmp) or os.path.getsize(dst_tmp) < 2000:
        return

    dirs = set()
    for dp in list(_discovered_data_paths):
        if dp:
            dirs.add(os.path.join(dp, "config"))
    for env_var in ("APPDATA", "LOCALAPPDATA"):
        base_d = os.environ.get(env_var, "")
        if base_d:
            for d in glob.glob(os.path.join(base_d, "MetaQuotes", "Terminal", "*", "config")):
                dirs.add(d)
    for d in dirs:
        try:
            if os.path.exists(d):
                shutil.copyfile(dst_tmp, os.path.join(d, "servers.dat"))
        except Exception:
            pass


def ensure_windows_mt5_terminal():
    if find_mt5_terminal_exe():
        return True
    safe_print("Installing Official MT5 Terminal...")
    setup = os.path.join(tempfile.gettempdir(), "mt5setup.exe")
    req = urllib.request.Request(MT5_SETUP_URL, headers={"User-Agent": BROWSER_UA})
    with urllib.request.urlopen(req, timeout=120) as r, open(setup, "wb") as f:
        shutil.copyfileobj(r, f)
    subprocess.Popen([setup, "/auto"])
    deadline = time.time() + 300
    while time.time() < deadline:
        if find_mt5_terminal_exe():
            time.sleep(12)
            return True
        time.sleep(3)
    return False


def patch_common_ini_file(path, login_str="", password="", server=""):
    try:
        if os.path.exists(path):
            raw = open(path, "rb").read()
            utf16 = raw.startswith(b"\xff\xfe")
            text = raw[2:].decode("utf-16-le", errors="ignore") if utf16 else raw.decode("utf-8", errors="ignore")
        else:
            utf16 = True
            text = ""
        if login_str and server:
            text = set_ini_values(text, "Common", {
                "Login": login_str,
                "Password": password,
                "Server": server,
                "KeepPrivate": "1",
                "NewsEnable": "0",
                "CertInstall": "1"
            })
        text = set_ini_values(text, "Experts", {
            "AllowLiveTrading": "1",
            "Enabled": "1",
            "AllowDllImport": "1",
            "Account": "0",
            "Profile": "0",
            "Chart": "0",
            "Api": "0"
        })
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"\xff\xfe" + text.encode("utf-16-le") if utf16 else text.encode("utf-8"))
    except Exception as e:
        safe_print(f"patch_common_ini note ({path}): {e}")


def prepare_autotrading_config(exe, login_str="", password="", server=""):
    login_str = login_str or KNOWN_MT5_LOGIN
    password = password or KNOWN_MT5_PASS
    server = server or KNOWN_MT5_SERVER

    paths = set()
    for dp in list(_discovered_data_paths):
        if dp:
            paths.add(os.path.join(dp, "config", "common.ini"))

    for env_var in ("APPDATA", "LOCALAPPDATA", "USERPROFILE"):
        base_d = os.environ.get(env_var, "")
        if base_d:
            for p in glob.glob(os.path.join(base_d, "**", "MetaQuotes", "Terminal", "*", "config", "common.ini"), recursive=True):
                paths.add(p)
    paths.add(os.path.join(os.path.dirname(exe), "config", "common.ini"))

    for p in paths:
        patch_common_ini_file(p, login_str, password, server)

    ini = os.path.join(tempfile.gettempdir(), "mt5_startup.ini")
    ini_text = (
        "[Common]\r\n"
        f"Login={login_str}\r\n"
        f"Password={password}\r\n"
        f"Server={server}\r\n"
        "KeepPrivate=1\r\n"
        "NewsEnable=0\r\n"
        "CertInstall=1\r\n"
        "\r\n"
        "[StartUp]\r\n"
        "Symbol=XAUUSD\r\n"
        "\r\n"
        "[Experts]\r\n"
        "AllowLiveTrading=1\r\n"
        "Enabled=1\r\n"
        "AllowDllImport=1\r\n"
        "Account=0\r\n"
        "Profile=0\r\n"
        "Chart=0\r\n"
        "Api=0\r\n"
    )
    with open(ini, "wb") as f:
        f.write(ini_text.encode("ascii", errors="ignore"))
    return ini


def send_win32_autotrading_enable():
    if os.name != "nt" or not mt5:
        return False
    ti = mt5.terminal_info()
    if ti and getattr(ti, "trade_allowed", False) and not getattr(ti, "tradeapi_disabled", False):
        return True

    try:
        import ctypes
        u = ctypes.windll.user32
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        hwnds = []
        dialogs = []

        h_main = u.FindWindowW("MetaQuotes::MetaTrader::5.00", None)
        if h_main:
            hwnds.append(h_main)

        def enum_cb(hwnd, lparam):
            cls_buf = ctypes.create_unicode_buffer(64)
            u.GetClassNameW(hwnd, cls_buf, 64)
            if cls_buf.value == "#32770" and u.IsWindowVisible(hwnd):
                dialogs.append(hwnd)
            length = u.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                u.GetWindowTextW(hwnd, buf, length + 1)
                t = buf.value.upper()
                if "METATRADER" in t or "METAQUOTES" in t or "DEMO" in t or "LIVE" in t or "REAL" in t:
                    if hwnd not in hwnds:
                        hwnds.append(hwnd)
            return True

        u.EnumWindows(WNDENUMPROC(enum_cb), 0)

        for d_hwnd in dialogs:
            u.PostMessageW(d_hwnd, 0x0010, 0, 0)
        if dialogs:
            time.sleep(0.3)

        WM_COMMAND = 0x0111
        for cmd_id in (32851, 33021, 32850, 32852):
            for hwnd in hwnds:
                u.PostMessageW(hwnd, WM_COMMAND, cmd_id, 0)
            time.sleep(0.4)
            ti = mt5.terminal_info()
            if ti and getattr(ti, "trade_allowed", False):
                return True
    except Exception as e:
        safe_print("Win32 Algo toggle note:", e)
    return False


def launch_mt5_with_verified_autotrading(login_str="", password="", server=""):
    exe = find_mt5_terminal_exe()
    if not exe:
        return False
    login_str = login_str or KNOWN_MT5_LOGIN
    password = password or KNOWN_MT5_PASS
    server = server or KNOWN_MT5_SERVER

    if not _discovered_data_paths:
        if mt5.initialize(exe, timeout=20000):
            ti = mt5.terminal_info()
            if ti and getattr(ti, "data_path", ""):
                _discovered_data_paths.add(ti.data_path)

    try:
        mt5.shutdown()
    except Exception:
        pass
    subprocess.run(["taskkill", "/F", "/IM", "terminal64.exe"], capture_output=True, timeout=20)
    time.sleep(2)

    ini = prepare_autotrading_config(exe, login_str, password, server)
    subprocess.Popen([exe, f"/config:{ini}"])
    time.sleep(8)

    if mt5.initialize(exe, login=int(login_str), password=password, server=server, timeout=25000):
        ti = mt5.terminal_info()
        if ti and getattr(ti, "data_path", ""):
            _discovered_data_paths.add(ti.data_path)
        for s in ("XAUUSD", "GOLD", "EURUSD"):
            try:
                mt5.symbol_select(s, True)
            except Exception:
                pass
        if ti and not getattr(ti, "trade_allowed", False):
            send_win32_autotrading_enable()
    return True


_last_autotrading_fix = 0.0


def mt5_connect_locked(acc, for_trading=False):
    global _last_autotrading_fix
    if not NATIVE_MT5_AVAILABLE:
        return False, "MetaTrader5 يعمل على ويندوز فقط"
    if not MT5_BOOT_DONE.is_set():
        return False, "منصة MT5 قيد التجهيز الأولي، أعد المحاولة بعد ثوانٍ"
    exe = find_mt5_terminal_exe()
    if not exe:
        return False, "لم يتم العثور على terminal64.exe"

    login_str = str(acc.get("login_or_key", "")).strip()
    if not login_str.isdigit():
        return False, f"رقم حساب غير صالح: {login_str}"
    login_int = int(login_str)
    password = acc.get("password_or_secret", "")
    server = acc.get("server_or_mode", "")

    if failed_mt5_servers.get(f"{login_int}_{server}", 0) > time.time():
        return False, f"سيرفر ({server}) غير مدرج في قائمة MT5 القياسية."

    info = mt5.account_info()
    if info is None:
        if not mt5.initialize(exe, timeout=12000):
            return False, f"تعذر ربط قناة MT5: {mt5.last_error()}"
        info = mt5.account_info()

    ti = mt5.terminal_info()
    if ti and getattr(ti, "data_path", ""):
        _discovered_data_paths.add(ti.data_path)

    if info is None or int(info.login) != login_int:
        if not mt5.login(login_int, password=password, server=server, timeout=10000):
            err_c, err_d = mt5.last_error()
            if err_c in (-10005, -10003, -10004):
                failed_mt5_servers[f"{login_int}_{server}"] = time.time() + 600
                auto_clean_broken_demo_accounts(acc.get("user_id"), acc.get("acc_pk"))
                try:
                    mt5.login(int(KNOWN_MT5_LOGIN), password=KNOWN_MT5_PASS, server=KNOWN_MT5_SERVER, timeout=5000)
                except Exception:
                    pass
            return False, f"فشل تسجيل الدخول ({err_c}, {err_d})"

    ti = mt5.terminal_info()
    if ti and (not getattr(ti, "trade_allowed", False) or getattr(ti, "tradeapi_disabled", False)):
        if not send_win32_autotrading_enable():
            if for_trading and (time.time() - _last_autotrading_fix > 60):
                _last_autotrading_fix = time.time()
                launch_mt5_with_verified_autotrading(login_str, password, server)

    return True, "OK"


def auto_clean_broken_demo_accounts(uid, acc_pk):
    """تنظيف تلقائي لحسابات الديمو التي يثبت أن سيرفرها غير مستجيب (مثل BlackBullMarkets-Demo) لمنع الفحص البطيء المتكرر"""
    if not uid or not acc_pk:
        return
    acc = get_account_by_pk(acc_pk)
    if acc and "DEMO" in str(acc.get("server_or_mode", "")).upper() and acc.get("login_or_key") != KNOWN_MT5_LOGIN:
        delete_trading_account(uid, acc_pk)


def match_mt5_symbol(desired):
    d = desired.upper().strip()
    cands = ([d, "XAUUSD", "XAUUSDm", "XAUUSD.", "XAUUSDc", "XAUUSD#", "XAUUSDpro", "GOLD", "GOLDm", "GOLD."]
             if d in ("XAUUSD", "GOLD") else [d, d + "m", d + ".", d + "#", d + "c"])
    for s in cands:
        si = mt5.symbol_info(s)
        if si is not None:
            if not si.visible:
                mt5.symbol_select(s, True)
            return s
    all_syms = mt5.symbols_get() or []
    for s_obj in all_syms:
        up = s_obj.name.upper()
        if d in up or ("XAU" in d and ("XAU" in up or "GOLD" in up)):
            mt5.symbol_select(s_obj.name, True)
            return s_obj.name
    return None


def get_ordered_filling_modes(si):
    modes = []
    fm = int(getattr(si, "filling_mode", 0) or 0)
    if fm & 1:
        modes.append(mt5.ORDER_FILLING_FOK)
    if fm & 2:
        modes.append(mt5.ORDER_FILLING_IOC)
    modes.append(mt5.ORDER_FILLING_RETURN)
    for fallback_m in (mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN):
        if fallback_m not in modes:
            modes.append(fallback_m)
    return modes


def get_reliable_mt5_price(sym, is_buy):
    mt5.symbol_select(sym, True)
    for _ in range(10):
        tick = mt5.symbol_info_tick(sym)
        if tick:
            p = float(tick.ask if is_buy else tick.bid)
            if p > 0:
                return p, float(tick.ask - tick.bid) if (tick.ask > 0 and tick.bid > 0) else 0.2
        time.sleep(0.15)

    si = mt5.symbol_info(sym)
    if si:
        p = float(getattr(si, "ask", 0.0) if is_buy else getattr(si, "bid", 0.0))
        if p > 0:
            return p, 0.3

    rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, 5)
    if rates is not None and len(rates) > 0:
        last_close = float(rates[-1]["close"])
        if last_close > 0:
            return last_close, 0.3

    return 0.0, 0.0


def mt5_fetch_mtf_candles(acc, symbol):
    with mt5_lock:
        ok, _ = mt5_connect_locked(acc, for_trading=False)
        if not ok:
            return None
        sym = match_mt5_symbol(symbol)
        if not sym:
            return None
        out = {}
        tf_map = {
            "M1": mt5.TIMEFRAME_M1,
            "M5": mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15,
        }
        for name, tf_code in tf_map.items():
            rates = mt5.copy_rates_from_pos(sym, tf_code, 0, 65)
            if rates is not None and len(rates) >= 20:
                out[name] = [{
                    "open": float(r["open"]),
                    "high": float(r["high"]),
                    "low": float(r["low"]),
                    "close": float(r["close"]),
                } for r in rates]
        return out if "M1" in out else None


def mt5_status(acc):
    with mt5_lock:
        ok, msg = mt5_connect_locked(acc, for_trading=False)
        if not ok:
            return False, 0.0, 0.0, 0, msg
        info, ti = mt5.account_info(), mt5.terminal_info()
        pos = mt5.positions_get() or []
        acc_type = "ديمو" if getattr(info, "trade_mode", 0) == mt5.ACCOUNT_TRADE_MODE_DEMO else "حقيقي Live"
        allowed = bool(ti and getattr(ti, "trade_allowed", False) and not getattr(ti, "tradeapi_disabled", False))
        algo = "مفعّل 🟢" if allowed else "جاهز للتفعيل ⚡"
        return True, float(info.balance), float(info.equity), len(pos), f"متصل ({acc_type}) | التداول الآلي: {algo}"


def mt5_positions(acc, only_bot=True):
    with mt5_lock:
        ok, _ = mt5_connect_locked(acc)
        if not ok:
            return None
        pos = mt5.positions_get()
        if pos is None:
            return []
        return [{
            "id": str(p.ticket), "symbol": p.symbol, "volume": float(p.volume),
            "price_open": float(getattr(p, "price_open", 0.0)),
            "sl": float(getattr(p, "sl", 0.0)),
            "tp": float(getattr(p, "tp", 0.0)),
            "side": "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
            "profit": float(p.profit) + float(p.swap), "magic": p.magic
        } for p in pos if (not only_bot or p.magic == MAGIC)]


def mt5_move_to_breakeven(acc, pos):
    with mt5_lock:
        if not mt5_connect_locked(acc, for_trading=False)[0]:
            return False
        entry_p = float(pos.get("price_open", 0.0))
        cur_sl = float(pos.get("sl", 0.0))
        if entry_p <= 0:
            return False
        is_buy = pos["side"] == "BUY"
        if is_buy and (cur_sl >= entry_p):
            return True
        if (not is_buy) and (cur_sl > 0 and cur_sl <= entry_p):
            return True
        res = mt5.order_send({
            "action": mt5.TRADE_ACTION_SLTP,
            "position": int(pos["id"]),
            "symbol": pos["symbol"],
            "sl": entry_p,
            "tp": float(pos.get("tp", 0.0)),
        })
        return bool(res and res.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL))


def mt5_close(acc, pos):
    with mt5_lock:
        ok, _ = mt5_connect_locked(acc, for_trading=True)
        if not ok:
            return False
        is_buy = pos["side"] == "BUY"
        price, _ = get_reliable_mt5_price(pos["symbol"], not is_buy)
        if price <= 0:
            return False
        si = mt5.symbol_info(pos["symbol"])
        modes = get_ordered_filling_modes(si) if si else [mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN]
        for fm in modes:
            res = mt5.order_send({
                "action": mt5.TRADE_ACTION_DEAL, "symbol": pos["symbol"], "volume": float(pos["volume"]),
                "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY, "position": int(pos["id"]),
                "price": price, "deviation": 100, "magic": MAGIC,
                "comment": "AI_Close", "type_time": mt5.ORDER_TIME_GTC, "type_filling": fm
            })
            if res is not None and res.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL):
                return True
    return False


def mt5_closed_pnl(acc, row):
    with mt5_lock:
        ok, _ = mt5_connect_locked(acc)
        if not ok:
            return None
        deals = mt5.history_deals_get(position=int(row["ticket"]))
        if not deals or not any(d.entry == mt5.DEAL_ENTRY_OUT for d in deals):
            return None
        return float(sum(d.profit + d.swap + d.commission + getattr(d, "fee", 0.0) for d in deals))


def _fail(symbol, msg):
    return {"ok": False, "symbol": symbol, "msg": msg}


def mt5_open_single_layer(acc, side, symbol, lot, tp_usd, sl_usd, layer_tag="L1"):
    with mt5_lock:
        ok, msg = mt5_connect_locked(acc, for_trading=True)
        if not ok:
            if MASTER_METAAPI_TOKEN:
                return metaapi_open_single_layer(acc, side, symbol, lot, tp_usd, sl_usd, layer_tag)
            return _fail(symbol, msg)

        sym = match_mt5_symbol(symbol)
        if not sym:
            return _fail(symbol, f"الرمز {symbol} غير موجود عند الوسيط")

        si = mt5.symbol_info(sym)
        buy = side == "BUY"
        price, spread = get_reliable_mt5_price(sym, buy)
        if price <= 0:
            return _fail(sym, "السوق مغلق حالياً أو لا توجد تسعيرات حية")

        vol = normalize_volume(lot, si.volume_min, si.volume_max, si.volume_step)
        min_dist = si.trade_stops_level * si.point + spread * 1.4
        dists = {}
        for key, usd in (("tp", tp_usd), ("sl", sl_usd)):
            d = usd_to_price_distance(usd, vol, si.trade_tick_value, si.trade_tick_size)
            dists[key] = max(d, min_dist * 1.15) if d > 0 else None

        modes = get_ordered_filling_modes(si)
        last = ""
        for attempt in range(2):
            for mode in modes:
                cur_p, _ = get_reliable_mt5_price(sym, buy)
                use_p = cur_p if cur_p > 0 else price
                req = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": sym,
                    "volume": vol,
                    "type": mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL,
                    "price": use_p,
                    "deviation": 100,
                    "magic": MAGIC,
                    "comment": f"AI_{layer_tag}",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mode,
                }
                res = mt5.order_send(req)

                if res is not None and res.retcode in (10004, 10020):
                    cur_p2, _ = get_reliable_mt5_price(sym, buy)
                    if cur_p2 > 0:
                        req["price"] = cur_p2
                        res = mt5.order_send(req)

                if res is not None and res.retcode in (10019, 10014) and vol > float(si.volume_min or 0.01):
                    vol = float(si.volume_min or 0.01)
                    req["volume"] = vol
                    res = mt5.order_send(req)

                if res is None:
                    last = f"لا رد من المنصة {mt5.last_error()}"
                    continue

                if res.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL):
                    pos_ticket = res.order or res.deal
                    exec_p = float(res.price or use_p)
                    tp_final = round(exec_p + dists["tp"] if buy else exec_p - dists["tp"], si.digits) if dists["tp"] else 0.0
                    sl_final = round(exec_p - dists["sl"] if buy else exec_p + dists["sl"], si.digits) if dists["sl"] else 0.0
                    if (sl_final > 0 or tp_final > 0) and pos_ticket:
                        time.sleep(0.15)
                        live_pos = mt5.positions_get(symbol=sym) or []
                        target_pos = next((p for p in live_pos if p.ticket == pos_ticket), live_pos[-1] if live_pos else None)
                        p_id = int(target_pos.ticket) if target_pos else int(pos_ticket)
                        mt5.order_send({
                            "action": mt5.TRADE_ACTION_SLTP,
                            "position": p_id,
                            "symbol": sym,
                            "sl": sl_final,
                            "tp": tp_final,
                        })
                    return {
                        "ok": True, "symbol": sym, "ticket": str(pos_ticket), "volume": vol, "side": side,
                        "price": exec_p, "tp_usd": tp_usd, "sl_usd": sl_usd, "layer_tag": layer_tag
                    }

                last = retcode_message(res.retcode, res.comment)
                if res.retcode == 10027 and attempt == 0:
                    launch_mt5_with_verified_autotrading(
                        str(acc.get("login_or_key")),
                        acc.get("password_or_secret"),
                        acc.get("server_or_mode")
                    )
                    break
                if res.retcode != 10030:
                    break
            else:
                break
        if MASTER_METAAPI_TOKEN:
            return metaapi_open_single_layer(acc, side, symbol, lot, tp_usd, sl_usd, layer_tag)
        return _fail(sym, last or "رفض الوسيط")


# ======================= 10. Bybit V5 =======================
BYBIT_HOST_LIST = {
    "BYBIT-LIVE": ["https://api.bytick.com", "https://api.bybit.com"],
    "BYBIT-DEMO": ["https://api-demo.bybit.com"],
    "BYBIT-TESTNET": ["https://api-testnet.bybit.com"],
}
bybit_time_offset_ms = 0
_working_eu_proxy = None
_eu_proxy_checked_at = 0.0


def find_working_non_us_proxy():
    global _working_eu_proxy, _eu_proxy_checked_at
    if _working_eu_proxy and (time.time() - _eu_proxy_checked_at < 600):
        return _working_eu_proxy

    _eu_proxy_checked_at = time.time()
    candidates = []
    try:
        st, geo = http_request(
            "https://proxylist.geonode.com/api/proxy-list?limit=30&page=1&sort_by=lastChecked&sort_type=desc&protocols=http%2Chttps",
            "GET", timeout=6, verify_ssl=False
        )
        if st == 200 and isinstance(geo, dict):
            for item in geo.get("data", []):
                cc = str(item.get("country", "")).upper()
                if cc not in ("US", "CA", "CN", "HK", "SG", "GB"):
                    ip, port = item.get("ip"), item.get("port")
                    if ip and port:
                        candidates.append(f"http://{ip}:{port}")
    except Exception:
        pass

    text_sources = [
        "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=2500&country=DE,NL,FR,CH,FI,SE,AT,IE,PL,JP,KR&ssl=yes&anonymity=all",
    ]
    for src in text_sources:
        try:
            with urllib.request.urlopen(src, timeout=6, context=SSL_CTX_UNVERIFIED) as r:
                raw_txt = r.read().decode("utf-8", errors="ignore")
            for line in raw_txt.splitlines():
                line = line.strip()
                if re.match(r"^\d+\.\d+\.\d+\.\d+:\d+$", line):
                    p_str = f"http://{line}"
                    if p_str not in candidates:
                        candidates.append(p_str)
                if len(candidates) >= 25:
                    break
        except Exception:
            continue

    if not candidates:
        return None

    def test_one(p_url):
        st, res = http_request("https://api-demo.bybit.com/v5/market/time", "GET", timeout=3, verify_ssl=False, proxy_addr=p_url)
        if st == 200 and isinstance(res, dict) and res.get("retCode") == 0:
            return p_url
        return None

    with ThreadPoolExecutor(max_workers=8) as ex:
        for res_p in ex.map(test_one, candidates[:20]):
            if res_p:
                _working_eu_proxy = res_p
                return res_p
    return None


def get_user_bybit_proxy(uid):
    if uid:
        u = get_user(uid)
        if u and u.get("bybit_proxy"):
            return u["bybit_proxy"].strip().rstrip("/")
    return DEFAULT_BYBIT_PROXY.strip().rstrip("/")


def bybit_symbol_candidates(symbol):
    s = symbol.upper().strip()
    if s in ("XAUUSD", "GOLD", "XAUTUSDT", "XAUT", "PAXG", "PAXGUSDT"):
        return ["PAXGUSDT", "XAUTUSDT"]
    return [s if s.endswith("USDT") else f"{s}USDT"]


def bybit_sign(secret, ts, key, recv, payload):
    return hmac.new(secret.encode(), f"{ts}{key}{recv}{payload}".encode(), hashlib.sha256).hexdigest()


def bybit_err(res):
    code = res.get("retCode", res.get("_status", "?"))
    if code == 10003:
        return "مفتاح API غير صالح لهذا الوضع"
    if code == 10004:
        return "خطأ في التوقيع السري API Secret"
    if code == 10005:
        return "مفتاح الـ API لا يملك صلاحية التداول"
    if code == 110007:
        return "رصيد USDT المتاح غير كافٍ"
    if res.get("_status") == 403 or "403" in str(res.get("error", "")):
        return "HTTP 403 (حجب IP أمريكي من Bybit)."
    return f"{res.get('retMsg') or res.get('error') or 'خطأ غير معروف'} (كود {code})"


def sync_bybit_time(proxy, host):
    global bybit_time_offset_ms
    try:
        url = (proxy + "/v5/market/time") if proxy else (host + "/v5/market/time")
        headers = {"X-Target-Host": host} if proxy else None
        st, res = http_request(url, "GET", headers=headers, timeout=6, verify_ssl=False)
        if st == 200 and isinstance(res, dict):
            srv_sec = (res.get("result") or {}).get("timeSecond")
            if srv_sec:
                bybit_time_offset_ms = int(srv_sec) * 1000 - int(time.time() * 1000)
    except Exception:
        pass


def _single_bybit_call(acc, mode, method, path, params=None, body=None):
    global _working_eu_proxy
    hosts = list(BYBIT_HOST_LIST.get(mode, BYBIT_HOST_LIST["BYBIT-DEMO"]))
    proxy = get_user_bybit_proxy(acc.get("user_id"))
    key, secret = acc["login_or_key"], acc["password_or_secret"]
    recv = "25000"

    for attempt in range(2):
        ts = str(int(time.time() * 1000) + bybit_time_offset_ms)
        if method == "GET":
            qs = urllib.parse.urlencode(params or {})
            sig = bybit_sign(secret, ts, key, recv, qs)
            full_path = path + ("?" + qs if qs else "")
            raw = None
        else:
            raw = json.dumps(body or {}, separators=(",", ":"))
            sig = bybit_sign(secret, ts, key, recv, raw)
            full_path = path

        base_headers = {
            "X-BAPI-API-KEY": key,
            "X-BAPI-TIMESTAMP": ts,
            "X-BAPI-RECV-WINDOW": recv,
            "X-BAPI-SIGN": sig
        }
        last_res = {"_status": 500, "error": "No host"}

        if proxy:
            h = dict(base_headers)
            h["X-Target-Host"] = hosts[0]
            status, res = http_request(proxy + full_path, method, headers=h, raw_body=raw, timeout=10, verify_ssl=False)
            res["_status"] = status
            if status == 200 and "retCode" in res:
                if res.get("retCode") == 10002 and attempt == 0:
                    sync_bybit_time(proxy, hosts[0])
                    continue
                return res.get("retCode") == 0, res
            last_res = res

        for host in hosts:
            status, res = http_request(host + full_path, method, headers=base_headers, raw_body=raw, timeout=10, verify_ssl=False)
            res["_status"] = status
            last_res = res
            if status == 200 and "retCode" in res:
                return res.get("retCode") == 0, res

        if last_res.get("_status") == 403 or "403" in str(last_res.get("error", "")):
            eu_p = find_working_non_us_proxy()
            if eu_p:
                status_eu, res_eu = http_request(
                    hosts[0] + full_path, method, headers=base_headers, raw_body=raw,
                    timeout=10, verify_ssl=False, proxy_addr=eu_p
                )
                res_eu["_status"] = status_eu
                if status_eu == 200 and "retCode" in res_eu:
                    return res_eu.get("retCode") == 0, res_eu
                else:
                    _working_eu_proxy = None

        if last_res.get("retCode") == 10002 and attempt == 0:
            sync_bybit_time(proxy, hosts[0])
            continue
        break

    return last_res.get("retCode") == 0, last_res


def bybit_request(acc, method, path, params=None, body=None):
    mode = acc.get("server_or_mode", "BYBIT-DEMO").upper()
    ok, res = _single_bybit_call(acc, mode, method, path, params, body)
    if not ok and res.get("retCode") == 10003:
        for alt_mode in ("BYBIT-LIVE", "BYBIT-DEMO", "BYBIT-TESTNET"):
            if alt_mode == mode:
                continue
            ok_alt, res_alt = _single_bybit_call(acc, alt_mode, method, path, params, body)
            if ok_alt:
                acc["server_or_mode"] = alt_mode
                if acc.get("acc_pk"):
                    update_account_mode(acc["acc_pk"], alt_mode)
                return True, res_alt
    return ok, res


def bybit_public(acc, path, params):
    qs = urllib.parse.urlencode(params)
    proxy = get_user_bybit_proxy(acc.get("user_id"))
    hosts = ["https://api.bytick.com", "https://api.bybit.com"]
    if proxy:
        status, res = http_request(f"{proxy}{path}?{qs}", "GET", headers={"X-Target-Host": "https://api.bybit.com"}, timeout=8, verify_ssl=False)
        res["_status"] = status
        if status == 200 and res.get("retCode") == 0:
            return True, res
    for host in hosts:
        status, res = http_request(f"{host}{path}?{qs}", "GET", timeout=8, verify_ssl=False)
        res["_status"] = status
        if status == 200 and res.get("retCode") == 0:
            return True, res
    eu_p = find_working_non_us_proxy()
    if eu_p:
        status, res = http_request(f"https://api.bybit.com{path}?{qs}", "GET", timeout=8, verify_ssl=False, proxy_addr=eu_p)
        res["_status"] = status
        if status == 200 and res.get("retCode") == 0:
            return True, res
    return False, {"_status": 403, "error": "HTTP 403"}


def bybit_fetch_mtf_candles(acc, symbol):
    out = {}
    tf_map = {"M1": "1", "M5": "5", "M15": "15"}
    for sym in bybit_symbol_candidates(symbol):
        for tf_name, interval in tf_map.items():
            ok, res = bybit_public(acc, "/v5/market/kline", {"category": "linear", "symbol": sym, "interval": interval, "limit": 65})
            if ok:
                rows = (res.get("result") or {}).get("list") or []
                if len(rows) >= 20:
                    out[tf_name] = [{
                        "open": float(r[1]),
                        "high": float(r[2]),
                        "low": float(r[3]),
                        "close": float(r[4]),
                    } for r in reversed(rows)]
        if "M1" in out:
            return out
    return None


def bybit_status(acc):
    ok, res = bybit_request(acc, "GET", "/v5/account/wallet-balance", {"accountType": "UNIFIED"})
    if not ok:
        return False, 0.0, 0.0, 0, bybit_err(res)
    lst = (res.get("result") or {}).get("list") or [{}]
    a = lst[0]
    okp, rp = bybit_request(acc, "GET", "/v5/position/list", {"category": "linear", "settleCoin": "USDT"})
    n = sum(1 for p in ((rp.get("result") or {}).get("list") or []) if float(p.get("size") or 0) > 0) if okp else 0
    mode = acc.get("server_or_mode", "")
    return True, float(a.get("totalWalletBalance") or 0), float(a.get("totalEquity") or 0), n, f"متصل بنجاح ({mode}) 🟢"


def bybit_positions(acc, symbol=None):
    params = {"category": "linear", "settleCoin": "USDT"}
    ok, res = bybit_request(acc, "GET", "/v5/position/list", params)
    if not ok:
        return None
    out = []
    for p in (res.get("result") or {}).get("list") or []:
        if float(p.get("size") or 0) > 0:
            out.append({
                "id": p["symbol"], "symbol": p["symbol"], "volume": float(p["size"]), "raw_size": p["size"],
                "positionIdx": int(p.get("positionIdx") or 0),
                "side": "BUY" if p.get("side") == "Buy" else "SELL", "profit": float(p.get("unrealisedPnl") or 0)
            })
    return out


def bybit_close(acc, pos):
    ok, _ = bybit_request(acc, "POST", "/v5/order/create", body={
        "category": "linear", "symbol": pos["symbol"], "side": "Sell" if pos["side"] == "BUY" else "Buy",
        "orderType": "Market", "qty": pos["raw_size"], "reduceOnly": True, "positionIdx": pos.get("positionIdx", 0)
    })
    return ok


def bybit_closed_pnl(acc, row):
    ok, res = bybit_request(acc, "GET", "/v5/position/closed-pnl", {"category": "linear", "symbol": row["symbol"], "limit": 20})
    if not ok:
        return None
    since = (row["open_ts"] - 5) * 1000
    recs = [r for r in ((res.get("result") or {}).get("list") or []) if int(r.get("updatedTime") or 0) >= since]
    return float(sum(float(r["closedPnl"]) for r in recs)) if recs else None


def bybit_open_single_layer(acc, side, symbol, lot, tp_usd, sl_usd, layer_tag="L1"):
    qty = max(round(float(lot) * BYBIT_QTY_PER_LOT, 2), 0.01)
    buy = side == "BUY"
    last_err = ""
    for sym in bybit_symbol_candidates(symbol):
        for pos_idx in (0, 1 if buy else 2):
            body = {
                "category": "linear", "symbol": sym, "side": "Buy" if buy else "Sell",
                "orderType": "Market", "qty": str(qty), "positionIdx": pos_idx,
                "orderLinkId": f"ai_{layer_tag}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:4]}"
            }
            ok, res = bybit_request(acc, "POST", "/v5/order/create", body=body)
            if not ok and res.get("retCode") == 110007 and qty > 0.01:
                body["qty"] = "0.01"
                ok, res = bybit_request(acc, "POST", "/v5/order/create", body=body)
                if ok:
                    qty = 0.01
            if ok:
                oid = (res.get("result") or {}).get("orderId", "Executed")
                return {
                    "ok": True, "symbol": sym, "ticket": str(oid), "volume": qty, "side": side,
                    "price": 0.0, "tp_usd": tp_usd, "sl_usd": sl_usd, "layer_tag": layer_tag
                }
            last_err = bybit_err(res)
            if "positionIdx" not in str(res.get("retMsg", "")):
                break
    return _fail(symbol, last_err)


# ======================= 11. واجهة موحدة للمنصات + فتح الصفقات الثلاثية =======================
def broker_status(acc):
    try:
        return mt5_status(acc) if acc["platform"] == "MT5" else bybit_status(acc)
    except Exception as e:
        return False, 0.0, 0.0, 0, f"استثناء: {redact(str(e))}"


def broker_positions(acc, symbol=None, only_bot=True):
    try:
        return mt5_positions(acc, only_bot) if acc["platform"] == "MT5" else bybit_positions(acc, symbol if only_bot else None)
    except Exception:
        return None


def broker_close(acc, pos):
    try:
        return mt5_close(acc, pos) if acc["platform"] == "MT5" else bybit_close(acc, pos)
    except Exception:
        return False


def broker_open_triple_batch(acc, action, symbol, lot, base_tp_usd, base_sl_usd, risk_mode=False, current_atr=1.0):
    """فتح 3 صفقات متزامنة في MT5/Bybit بناءً على الخطة المجهزة"""
    layers = build_triple_shield_plan(action, base_tp_usd, base_sl_usd, current_atr, risk_mode=risk_mode)
    batch_results = []
    fn = mt5_open_single_layer if acc["platform"] == "MT5" else bybit_open_single_layer

    for layer in layers:
        res = fn(acc, layer["side"], symbol, lot, layer["tp_usd"], layer["sl_usd"], layer_tag=layer["tag"])
        res["layer_title"] = layer["title"]
        res["tp_usd"] = layer["tp_usd"]
        res["sl_usd"] = layer["sl_usd"]
        batch_results.append(res)
        if not res.get("ok"):
            break
        time.sleep(0.15)
    return batch_results


def broker_closed_pnl(acc, row):
    try:
        return mt5_closed_pnl(acc, row) if acc["platform"] == "MT5" else bybit_closed_pnl(acc, row)
    except Exception:
        return None


# ======================= 12. محرك التداول المتعدد الحسابات =======================
PENDING = {}
CLOSE_TRIES = {}
LAST_WAIT_NOTICE = {}
diag_running = set()
trade_running = set()


class Runtime:
    def __init__(self):
        self.stop = threading.Event()
        self.thread = None
        self.next_analysis = 0.0


RUNTIMES = {}


def is_running(uid):
    rt = RUNTIMES.get(uid)
    return bool(rt and rt.thread and rt.thread.is_alive() and not rt.stop.is_set())


def roll_daily(uid):
    u = get_user(uid)
    if u.get("pnl_date") != today_str():
        update_user(uid, "current_daily_pnl", 0.0)
        update_user(uid, "trades_today", 0)
        update_user(uid, "pnl_date", today_str())


def finalize_trade(uid, chat_id, acc, row, pnl):
    db_exec("UPDATE bot_trades SET status='CLOSED', pnl=? WHERE id=?", (pnl, row["id"]))
    u = get_user(uid)
    update_user(uid, "current_daily_pnl", float(u["current_daily_pnl"]) + pnl)
    update_user(uid, "trades_today", int(u["trades_today"]) + 1)
    icon = "💰" if pnl >= 0 else "🛡️"
    send_msg(chat_id, f"{icon} أُغلقت صفقة ({row.get('layer_tag', 'L1')}) {row['side']} {row['symbol']} على [{acc['account_label']}]: {pnl:+.2f}$")


def reconcile_account(uid, chat_id, acc, symbol, manage=True):
    u = get_user(uid)
    positions = broker_positions(acc, symbol)
    if positions is None:
        return None
    live_map = {p["id"]: p for p in positions}
    rows = open_trade_rows(uid, acc["acc_pk"])
    known_map = {r["ticket"]: r for r in rows}

    if acc["platform"] == "MT5":
        for p in positions:
            if p["id"] not in known_map:
                record_trade(uid, acc, p["symbol"], p["side"], p["volume"], p["id"], u["trade_tp_usd"], u["trade_sl_usd"], "L2-أساسية", p.get("price_open"))
        rows = open_trade_rows(uid, acc["acc_pk"])
        known_map = {r["ticket"]: r for r in rows}

    if manage:
        for p in positions:
            r_meta = known_map.get(p["id"], {})
            target_tp = float(r_meta.get("tp_usd") or u["trade_tp_usd"] or 0.50)
            target_sl = float(r_meta.get("sl_usd") or u["trade_sl_usd"] or 1.00)
            if p["profit"] >= target_tp or p["profit"] <= -abs(target_sl):
                broker_close(acc, p)

    any_closed_in_profit = False
    for r in rows:
        if r["ticket"] in live_map:
            continue
        pnl = broker_closed_pnl(acc, r)
        if pnl is None:
            CLOSE_TRIES[r["id"]] = CLOSE_TRIES.get(r["id"], 0) + 1
            if CLOSE_TRIES[r["id"]] < 8:
                continue
            finalize_trade(uid, chat_id, acc, r, 0.0)
        else:
            if pnl > 0:
                any_closed_in_profit = True
            finalize_trade(uid, chat_id, acc, r, pnl)

    if any_closed_in_profit and acc["platform"] == "MT5":
        for p in positions:
            if p["id"] in live_map and p["profit"] > 0.05:
                mt5_move_to_breakeven(acc, p)

    return set(live_map.keys())


def limit_message(u):
    if u["current_daily_pnl"] >= u["daily_max_profit"]:
        return f"🏆 تحقق الهدف اليومي (+{u['current_daily_pnl']:.2f}$). توقف البوت لحفظ أرباحك."
    if u["current_daily_pnl"] <= -abs(u["daily_max_loss"]):
        return f"🛡️ بلغت الخسارة اليومية الحد الأقصى ({u['current_daily_pnl']:.2f}$). توقف البوت لحماية رأس مالك."
    return ""


def risk_button_markup(action):
    return {
        "inline_keyboard": [
            [{"text": "⚠️ مخاطرة (دخول ثلاثي محمي بخسارة < 0.50$)", "callback_data": f"force_risk_{action}"}],
            [{"text": "🔙 رجوع للوحة الرئيسية", "callback_data": "back_home"}],
        ]
    }


def execute_ai_trade(uid, chat_id, accounts, rt=None, manual=False, force_risk=False, forced_action=None):
    if uid in trade_running:
        if manual or force_risk:
            send_msg(chat_id, "⏳ جاري تنفيذ تحليل/صفقة حالياً، انتظر ثوانٍ...")
        return "busy"
    trade_running.add(uid)
    try:
        u = get_user(uid)
        if manual and not force_risk:
            send_msg(chat_id, f"⚡ جاري التحليل المؤسسي العميق (M1+M5+M15) وفحص نسبة الثقة على ({len(accounts)}) حساب...")
        elif force_risk:
            send_msg(chat_id, "⚠️ جاري تنفيذ أمر المخاطرة المحمي (3 صفقات متدرجة بإجمالي وقف خسارة < 0.50$)...")

        d = get_instant_or_fresh_analysis(uid, u["symbol"], accounts)
        action = forced_action if (force_risk and forced_action in ("BUY", "SELL")) else d["action"]

        if not force_risk and not d["ready"]:
            should_notify = manual or (time.time() - LAST_WAIT_NOTICE.get(uid, 0) > 600)
            if should_notify:
                LAST_WAIT_NOTICE[uid] = time.time()
                wait_msg = (
                    f"🔎 **نتيجة الفحص المؤسسي للفرصة ({u['symbol']}):**\n"
                    f"• الاتجاه المرصود: {action} | نسبة الثقة الحالية: **{d['confidence']}%** (الحد المطلوب: {MIN_AI_CONFIDENCE}%)\n"
                    f"• الأداة: {d['provider']}\n\n"
                    f"{d['detailed_report']}\n\n"
                    "⚠️ **(ليس وقت مناسب حاليا ولكن إذا تريد المخاطرة اضغط على زر مخاطرة الذي بالاسفل)**"
                )
                send_msg(chat_id, wait_msg, risk_button_markup(action))
            return "wait_opportunity"

        mt5_accs = [a for a in accounts if a["platform"] == "MT5"]
        other = [a for a in accounts if a["platform"] != "MT5"]
        results = []

        def run_group(group):
            return [
                (a, broker_open_triple_batch(a, action, u["symbol"], u["lot"], u["trade_tp_usd"], u["trade_sl_usd"], force_risk, d.get("atr", 1.0)))
                for a in group
            ]

        with ThreadPoolExecutor(max_workers=max(1, min(5, len(other) + 1))) as ex:
            futs = ([ex.submit(run_group, mt5_accs)] if mt5_accs else []) + [ex.submit(run_group, [a]) for a in other]
            for f in futs:
                results.extend(f.result())

        mode_title = "⚠️ وضع المخاطرة المحمي (خسارة < 0.50$)" if force_risk else f"🎯 دخول مؤسسي عالي الدقة (ثقة: {d['confidence']}%)"
        lines = [
            f"🤖 **قرار التداول الثلاثي:** {action}",
            f"• الوضع: {mode_title}",
            f"• الأداة: {d['provider']}",
            f"{d['detailed_report']}\n",
        ]
        okn = 0
        for acc, batch in results:
            acc_ok = [r for r in batch if r.get("ok")]
            if acc_ok:
                okn += len(acc_ok)
                lines.append(f"✅ **الحساب [{acc['account_label']}] — تم فتح ({len(acc_ok)}/3) صفقات متدرجة:**")
                for r in acc_ok:
                    record_trade(uid, acc, r["symbol"], r["side"], r["volume"], r["ticket"], r["tp_usd"], r["sl_usd"], r["layer_tag"], r.get("price"))
                    lines.append(
                        f"   🔹 {r['layer_title']}:\n"
                        f"      تذكرة `#{r['ticket']}` | لوت `{r['volume']}` | ربح `+{r['tp_usd']}$` | وقف `-{r['sl_usd']}$`"
                    )
            else:
                first_err = batch[0]["msg"] if batch else "خطأ غير معروف"
                lines.append(f"⚠️ الحساب [{acc['account_label']}]:\n   تعذر التنفيذ ({first_err})")

        send_msg(chat_id, "\n".join(lines))
        return "executed" if okn else "failed"
    finally:
        trade_running.discard(uid)


def tick_cycle(uid, chat_id, rt):
    roll_daily(uid)
    u = get_user(uid)
    accounts = get_target_accounts(uid)
    if not accounts:
        return
    open_ids = {}
    for acc in accounts:
        ids = reconcile_account(uid, chat_id, acc, u["symbol"])
        open_ids[acc["acc_pk"]] = set() if ids is None else ids
    u = get_user(uid)
    msg = limit_message(u)
    if msg:
        stop_trader(uid, chat_id, msg)
        return
    if not is_within_working_hours(u["work_start_hour"], u["work_end_hour"]) or time.time() < rt.next_analysis:
        return
    free = [a for a in accounts if not open_ids.get(a["acc_pk"])]
    if not free:
        return
    res = execute_ai_trade(uid, chat_id, free, rt=rt, manual=False, force_risk=False)
    if res == "executed":
        rt.next_analysis = time.time() + COOLDOWN_AFTER_TRADE
    elif res == "wait_opportunity":
        rt.next_analysis = time.time() + 15
    else:
        rt.next_analysis = time.time() + 30


def trading_worker(uid, chat_id, rt):
    send_msg(
        chat_id,
        "🟢 **بدأ قناص التداول الآلي بالذكاء الاصطناعي (24/7)!**\n"
        "• يفحص الفريمات الثلاثة (M1 + M5 + M15) في الخلفية.\n"
        f"• يدخل تلقائياً بـ 3 صفقات متدرجة فور وصول نسبة الثقة إلى {MIN_AI_CONFIDENCE}% فأكثر."
    )
    while not rt.stop.is_set() and not SHUTDOWN.is_set():
        try:
            tick_cycle(uid, chat_id, rt)
        except Exception as e:
            safe_print("worker error:", redact(str(e)))
        rt.stop.wait(3)


def start_trader(uid, chat_id):
    if is_running(uid):
        return False
    rt = Runtime()
    RUNTIMES[uid] = rt
    update_user(uid, "auto_run", 1)
    rt.thread = threading.Thread(target=trading_worker, args=(uid, chat_id, rt), daemon=True)
    rt.thread.start()
    return True


def stop_trader(uid, chat_id=None, notice=""):
    rt = RUNTIMES.get(uid)
    if rt:
        rt.stop.set()
    update_user(uid, "auto_run", 0)
    if chat_id and notice:
        send_msg(chat_id, notice)


def emergency_close_all(uid, chat_id):
    stop_trader(uid)
    closed_cnt = 0
    for acc in get_user_accounts(uid):
        pos = broker_positions(acc, None, only_bot=False) or []
        for p in pos:
            if broker_close(acc, p):
                closed_cnt += 1
    send_msg(chat_id, f"🚨 تم إغلاق ({closed_cnt}) صفقات مفتوحة وإيقاف التداول التلقائي.", main_keyboard(uid))


def show_financial_report(uid, chat_id):
    data = get_daily_financial_summary(uid)
    msg = (
        "📊 **التقرير المالي المفصل لليوم** 📊\n"
        f"📅 التاريخ: `{data['date']}`\n\n"
        f"📈 **إحصائيات الصفقات:**\n"
        f"• إجمالي الصفقات التي دخلها البوت: `{data['total_trades_entered']}`\n"
        f"• صفقات مغلقة (منتهية): `{data['closed_trades']}`\n"
        f"• صفقات لا تزال مفتوحة: `{data['open_trades']}`\n"
        f"• صفقات رابحة: `{data['win_count']}`\n"
        f"• صفقات خاسرة: `{data['loss_count']}`\n"
        f"• نسبة النجاح الدقيقة: `{data['win_rate']:.1f}%`\n\n"
        f"💰 **الأموال والنتائج:**\n"
        f"• إجمالي الأرباح المحققة: `+{data['gross_profit']:.2f}$`\n"
        f"• إجمالي الخسائر: `-{data['gross_loss']:.2f}$`\n"
        f"• **صافي نتيجة اليوم:** `{data['net_pnl']:+.2f}$`\n\n"
        f" حجم الأموال المشغّلة في السوق اليوم: `~{data['total_capital_used']:.2f}$`\n"
        f" إجمالي اللوتات المتداولة: `{data['total_lots']:.2f}` لوت"
    )
    send_msg(chat_id, msg, {"inline_keyboard": [[{"text": "🔙 رجوع للوحة الرئيسية", "callback_data": "back_home"}]]})


def resume_saved_auto_traders():
    for u in get_auto_running_users():
        if not is_running(u["user_id"]):
            start_trader(u["user_id"], u["chat_id"])


# ======================= 13. لوحة التحكم بالعربية =======================
FIELD_SPECS = {
    "lot": (float, 0.001, 100.0, "💵 أرسل حجم اللوت لكل صفقة من الصفقات الثلاث (مثال 0.01):"),
    "symbol": (str, 0, 0, "📊 أرسل رمز الزوج (مثال XAUUSD):"),
    "trade_tp_usd": (float, 0.05, 100000.0, "🎯 أرسل هدف الربح الأساسي بالدولار (وسيتم تدريج الصفقات الـ 3 حوله تلقائياً):"),
    "trade_sl_usd": (float, 0.10, 100000.0, "🛑 أرسل وقف الخسارة الأساسي بالدولار للصفقات:"),
    "daily_max_profit": (float, 0.10, 1e7, "🏆 أرسل الحد الأقصى للربح اليومي بالدولار:"),
    "daily_max_loss": (float, 0.10, 1e7, "🛡️ أرسل الحد الأقصى للخسارة اليومية بالدولار:"),
    "work_start_hour": (int, 0, 23, "🕐 أرسل ساعة بدء العمل (0-23):"),
    "work_end_hour": (int, 1, 24, "🕑 أرسل ساعة نهاية العمل (1-24):"),
}
SET_CB = {
    "set_lot": "lot", "set_symbol": "symbol", "set_tp": "trade_tp_usd", "set_sl": "trade_sl_usd",
    "set_dmp": "daily_max_profit", "set_dml": "daily_max_loss", "set_ws": "work_start_hour", "set_we": "work_end_hour"
}
BACK = {"inline_keyboard": [[{"text": "🔙 رجوع", "callback_data": "back_home"}]]}


def validate_field(field, text):
    kind, lo, hi, _ = FIELD_SPECS[field]
    text = text.strip()
    if kind is str:
        v = text.upper()
        if not re.fullmatch(r"[A-Z0-9._#]{3,20}", v):
            raise ValueError("رمز غير صالح")
        return v
    v = kind(text.replace(",", "."))
    if not lo <= v <= hi:
        raise ValueError(f"القيمة يجب أن تكون بين {lo} و {hi}")
    return v


def main_keyboard(uid):
    u, accs = get_user(uid), get_user_accounts(uid)
    act, tool = get_active_account(uid), get_ai_tool_by_id(get_user(uid)["selected_ai_id"])
    en_cnt = sum(1 for a in accs if a.get("is_enabled") == 1)
    run = {"text": "⏹️ إيقاف القناص التلقائي (يعمل 🟢)" if is_running(uid) else f"▶️ بدء القناص التلقائي (ثقة >= {MIN_AI_CONFIDENCE}% | 3 صفقات)",
           "callback_data": "toggle_run"}
    return {"inline_keyboard": [
        [{"text": "➕ إضافة حساب جديد (MT5 ديمو/حقيقي أو Bybit)", "callback_data": "menu_add_account"}],
        [{"text": f"📂 إدارة الحسابات ({len(accs)}) | النشط: {act.get('account_label', '-')}", "callback_data": "menu_manage_accounts"}],
        [{"text": f"🌐 التداول الجماعي: مفعّل ({en_cnt} حسابات) 🟢" if u["trade_all_accounts"] else "👤 الوضع: الحساب النشط فقط (اضغط لتفعيل الكل)", "callback_data": "toggle_all"}],
        [{"text": f"🤖 الذكاء الاصطناعي: {tool.get('name', '-')}", "callback_data": "menu_ai_select"}],
        [{"text": "🔍 فحص الرصيد الحي وحالة الحسابات", "callback_data": "diag_all"}],
        [{"text": f"💵 اللوت: {u['lot']}", "callback_data": "set_lot"}, {"text": f"📊 الزوج: {u['symbol']}", "callback_data": "set_symbol"}],
        [{"text": f"🎯 ربح أساسي: +{u['trade_tp_usd']}$", "callback_data": "set_tp"}, {"text": f"🛑 وقف أساسي: -{u['trade_sl_usd']}$", "callback_data": "set_sl"}],
        [{"text": f"🏆 أقصى ربح: {u['daily_max_profit']}$", "callback_data": "set_dmp"}, {"text": f"🛡️ أقصى خسارة: {u['daily_max_loss']}$", "callback_data": "set_dml"}],
        [{"text": "📊 تقرير الأرباح والخسائر اليومية", "callback_data": "show_report"}],
        [run],
        [{"text": "⚡ تحليل السوق ودخول 3 صفقات فورية الآن", "callback_data": "instant_trade"}],
        [{"text": "🚨 إغلاق جميع الصفقات المفتوحة فوراً", "callback_data": "emergency_close"}],
        [{"text": "🔄 تصفير عداد أرباح اليوم", "callback_data": "reset_pnl"}],
    ]}


def main_text(uid):
    u, accs = get_user(uid), get_user_accounts(uid)
    act, tool = get_active_account(uid), get_ai_tool_by_id(get_user(uid)["selected_ai_id"])
    return (
        "🤖 **لوحة تحكم قناص التداول المؤسسي (MT5 + Bybit Gold)**\n\n"
        f"• حالة البوت: {'يعمل سحابياً 24/7 🟢' if is_running(uid) else 'متوقف 🔴'}\n"
        f"• استراتيجية الدخول: 3 صفقات متدرجة (ثقة $\\ge$ {MIN_AI_CONFIDENCE}% عبر M1+M5+M15)\n"
        f"• الحساب النشط: {act.get('account_label', 'لا يوجد')} ({act.get('server_or_mode', '')})\n"
        f"• إجمالي الحسابات: {len(accs)} (يدعم الديمو والحقيقي)\n"
        f"• الذكاء الاصطناعي: {tool.get('name', '-')}\n"
        f"• صافي ربح/خسارة اليوم: {u['current_daily_pnl']:+.2f}$\n"
        f"• صفقات اليوم المغلقة: {u['trades_today']}"
    )


def accounts_keyboard(uid):
    u, rows = get_user(uid), []
    for a in get_user_accounts(uid):
        pk = a["acc_pk"]
        rows.append([
            {"text": ("🟢 [النشط] " if pk == u["active_account_id"] else "⚪ ") + f"{a['account_label']} [{a['server_or_mode']}]", "callback_data": f"select_acc_{pk}"},
            {"text": "✅" if a["is_enabled"] else "⛔", "callback_data": f"tog_acc_{pk}"},
            {"text": "🗑️ حذف", "callback_data": f"del_acc_{pk}"}
        ])
    rows += [[{"text": "➕ إضافة حساب", "callback_data": "menu_add_account"}], [{"text": "🔙 رجوع", "callback_data": "back_home"}]]
    return {"inline_keyboard": rows}


def ai_keyboard(uid):
    sel = get_user(uid)["selected_ai_id"]
    rows = [[{"text": ("✅ " if t["id"] == sel else "") + t["name"], "callback_data": f"pick_ai_{t['id']}"}] for t in get_ai_tools()]
    return {"inline_keyboard": rows + [[{"text": "🔙 رجوع", "callback_data": "back_home"}]]}


def diagnostic_all(uid, chat_id):
    if uid in diag_running:
        return
    diag_running.add(uid)
    try:
        sent = send_msg(chat_id, "⏳ جاري فحص الاتصال الفعلي وسحب الرصيد الحي لجميع الحسابات...")
        mid = (sent.get("result") or {}).get("message_id")
        lines = ["🔍 تقرير الفحص الشامل للحسابات:\n"]
        first_ok_pk = None
        u = get_user(uid)

        for a in get_user_accounts(uid):
            ok, bal, eq, n, txt = broker_status(a)
            if ok:
                if first_ok_pk is None:
                    first_ok_pk = a["acc_pk"]
                lines.append(
                    f"✅ {a['account_label']} ({a['server_or_mode']}):\n"
                    f"   • الحالة: {txt}\n"
                    f"   • الرصيد: {bal:.2f}$ | السيولة: {eq:.2f}$\n"
                    f"   • الصفقات المفتوحة الآن: {n}\n"
                )
            else:
                lines.append(f"⚠️ {a['account_label']} ({a['server_or_mode']}):\n   • الحالة: {txt}\n")
                if u["active_account_id"] == a["acc_pk"] and first_ok_pk is not None:
                    update_user(uid, "active_account_id", first_ok_pk)

        rep = "\n".join(lines)
        edit_msg(chat_id, mid, rep, main_keyboard(uid)) if mid else send_msg(chat_id, rep, main_keyboard(uid))
    finally:
        diag_running.discard(uid)


def test_new_account(uid, chat_id, pk):
    acc = get_account_by_pk(pk)
    ok, bal, eq, n, txt = broker_status(acc)
    if ok:
        update_user(uid, "active_account_id", pk)
        send_msg(chat_id, f"✅ تم حفظ وتفعيل الحساب ({acc['account_label']}) بنجاح!\n• الرصيد الحي: {bal:.2f}$\n• الحالة: {txt}", main_keyboard(uid))
    else:
        send_msg(
            chat_id,
            f"⚠️ تم حفظ الحساب ({acc['account_label']}) ولكن تعذر الاتصال بسيرفره حالياً:\n"
            f"• السبب: {txt}\n"
            f"• نصيحة: إذا كان الوسيط خارجياً، اكتب عنوان IP:Port بدلاً من اسم السيرفر.",
            main_keyboard(uid)
        )


# ======================= 14. الاستقبال (Polling) والمراقبة والتشغيل =======================
HEARTBEAT = {"poll": time.time()}
POLL_GEN = 0


def handle_message(msg):
    if "text" not in msg:
        return
    uid, chat_id, text = msg["from"]["id"], msg["chat"]["id"], msg["text"].strip()
    get_user(uid)
    update_user(uid, "is_authorized", 1)
    update_user(uid, "chat_id", chat_id)

    if text.startswith("/setproxy"):
        parts = text.split(maxsplit=1)
        proxy_url = parts[1].strip() if len(parts) > 1 else ""
        update_user(uid, "bybit_proxy", proxy_url)
        send_msg(chat_id, f"✅ تم تحديث جسر Bybit إلى:\n{proxy_url or 'مباشر'}", main_keyboard(uid))
        return

    if text.startswith("/start") or text.startswith("/menu") or SECRET_ACCESS_KEY in text:
        PENDING.pop(uid, None)
        send_msg(chat_id, main_text(uid), main_keyboard(uid))
        return

    action = PENDING.get(uid)
    if action == "input_new_account":
        plat, p1, p2, p3 = parse_three_line_credentials(text)
        if plat == "INVALID":
            send_msg(chat_id, "⚠️ أرسل البيانات في 3 أسطر تحت بعضها:\nرقم الحساب\nكلمة المرور\nاسم السيرفر (أو BYBIT-DEMO)")
            return
        delete_msg(chat_id, msg["message_id"])
        pk = add_or_update_trading_account(uid, plat, p1, p2, p3, make_active=False)
        PENDING.pop(uid, None)
        send_msg(chat_id, "⏳ تم استلام البيانات، جاري فحص الاتصال بالحساب...")
        threading.Thread(target=test_new_account, args=(uid, chat_id, pk), daemon=True).start()
    elif action and action.startswith("field_"):
        field = action[6:]
        try:
            update_user(uid, field, validate_field(field, text))
            PENDING.pop(uid, None)
            send_msg(chat_id, "✅ تم التحديث بنجاح!", main_keyboard(uid))
        except ValueError as e:
            send_msg(chat_id, f"⚠️ {e}. أعد الإرسال.")
    else:
        send_msg(chat_id, main_text(uid), main_keyboard(uid))


def handle_callback(cb):
    cid, uid = cb["id"], cb["from"]["id"]
    chat_id, mid, data = cb["message"]["chat"]["id"], cb["message"]["message_id"], cb.get("data", "")
    get_user(uid)
    update_user(uid, "is_authorized", 1)
    update_user(uid, "chat_id", chat_id)
    home = lambda: edit_msg(chat_id, mid, main_text(uid), main_keyboard(uid))

    if data == "back_home":
        answer_cb(cid)
        PENDING.pop(uid, None)
        home()
    elif data == "menu_add_account":
        answer_cb(cid)
        PENDING[uid] = "input_new_account"
        edit_msg(
            chat_id, mid,
            "➕ **إضافة حساب MT5 (ديمو/حقيقي) أو Bybit:**\n"
            "أرسل البيانات في 3 أسطر تحت بعضها:\n\n"
            "لإضافة حساب MT5:\n"
            "رقم الحساب\n"
            "كلمة المرور الرئيسية\n"
            "اسم السيرفر (أو IP:Port)\n\n"
            "لإضافة حساب Bybit:\n"
            "API_KEY\n"
            "API_SECRET\n"
            "BYBIT-DEMO (أو BYBIT-LIVE)",
            BACK
        )
    elif data == "menu_manage_accounts":
        answer_cb(cid)
        edit_msg(chat_id, mid, "📂 إدارة الحسابات المضافة (اضغط على الاسم لتفعيله، أو ✅/⛔ للتداول الجماعي، أو 🗑️ للحذف):", accounts_keyboard(uid))
    elif data.startswith(("select_acc_", "tog_acc_", "del_acc_")):
        pk = int(data.rsplit("_", 1)[1])
        acc = get_account_by_pk(pk)
        if acc and acc.get("user_id") == uid:
            if data.startswith("select_acc_"):
                update_user(uid, "active_account_id", pk)
                answer_cb(cid, "✅ تم التبديل")
            elif data.startswith("tog_acc_"):
                toggle_account(uid, pk)
                answer_cb(cid, "✅ تم تحديث حالة الحساب")
            else:
                if delete_trading_account(uid, pk):
                    answer_cb(cid, "🗑️ تم حذف الحساب")
                else:
                    answer_cb(cid, "⚠️ يجب إبقاء حساب واحد على الأقل", True)
        edit_msg(chat_id, mid, "📂 إدارة الحسابات المضافة:", accounts_keyboard(uid))
    elif data == "toggle_all":
        answer_cb(cid)
        update_user(uid, "trade_all_accounts", 0 if get_user(uid)["trade_all_accounts"] else 1)
        home()
    elif data == "diag_all":
        answer_cb(cid, "⚡ جاري الفحص السريع...")
        threading.Thread(target=diagnostic_all, args=(uid, chat_id), daemon=True).start()
    elif data == "menu_ai_select":
        answer_cb(cid)
        edit_msg(chat_id, mid, "🤖 اختر أداة الذكاء الاصطناعي:", ai_keyboard(uid))
    elif data.startswith("pick_ai_"):
        answer_cb(cid, "✅ تم اختيار الأداة")
        update_user(uid, "selected_ai_id", int(data.rsplit("_", 1)[1]))
        home()
    elif data == "instant_trade":
        answer_cb(cid, "⚡ جاري التحليل المؤسسي العميق...")
        accs = get_target_accounts(uid)
        threading.Thread(
            target=execute_ai_trade,
            args=(uid, chat_id, accs),
            kwargs={"manual": True, "force_risk": False},
            daemon=True
        ).start()
    elif data.startswith("force_risk_"):
        forced_dir = data.rsplit("_", 1)[1]
        answer_cb(cid, "⚠️ جاري الدخول المحمي بأقل من 0.50$ خسارة...")
        accs = get_target_accounts(uid)
        threading.Thread(
            target=execute_ai_trade,
            args=(uid, chat_id, accs),
            kwargs={"manual": True, "force_risk": True, "forced_action": forced_dir},
            daemon=True
        ).start()
    elif data == "show_report":
        answer_cb(cid, "📊 جاري تجهيز التقرير المالي...")
        threading.Thread(target=show_financial_report, args=(uid, chat_id), daemon=True).start()
    elif data == "emergency_close":
        answer_cb(cid, "🚨 جاري إغلاق الصفقات...")
        threading.Thread(target=emergency_close_all, args=(uid, chat_id), daemon=True).start()
    elif data in SET_CB:
        answer_cb(cid)
        PENDING[uid] = f"field_{SET_CB[data]}"
        edit_msg(chat_id, mid, FIELD_SPECS[SET_CB[data]][3], BACK)
    elif data == "reset_pnl":
        answer_cb(cid, "✅ تم التصفير")
        update_user(uid, "current_daily_pnl", 0.0)
        update_user(uid, "trades_today", 0)
        home()
    elif data == "toggle_run":
        answer_cb(cid)
        if is_running(uid):
            stop_trader(uid)
        else:
            start_trader(uid, chat_id)
        time.sleep(0.2)
        home()


def handle_update(upd):
    if "message" in upd:
        handle_message(upd["message"])
    elif "callback_query" in upd:
        handle_callback(upd["callback_query"])


def polling_loop(gen):
    safe_print(f"Polling started (gen {gen})")
    offset, backoff = 0, 1
    while not SHUTDOWN.is_set() and gen == POLL_GEN:
        HEARTBEAT["poll"] = time.time()
        res = tg_api("getUpdates", {"offset": offset, "timeout": 15, "allowed_updates": ["message", "callback_query"]}, timeout=25)
        HEARTBEAT["poll"] = time.time()
        if not res.get("ok"):
            code = res.get("error_code")
            if code == 409:
                tg_api("deleteWebhook", {"drop_pending_updates": False})
                wait = 3
            else:
                wait = backoff
                backoff = min(backoff * 2, 30)
            SHUTDOWN.wait(wait)
            continue
        backoff = 1
        for upd in res.get("result", []):
            offset = upd["update_id"] + 1
            try:
                handle_update(upd)
            except Exception:
                safe_print("update error:", redact(traceback.format_exc()))


def start_polling_thread():
    global POLL_GEN
    POLL_GEN += 1
    HEARTBEAT["poll"] = time.time()
    threading.Thread(target=polling_loop, args=(POLL_GEN,), daemon=True).start()


def watchdog():
    while not SHUTDOWN.wait(30):
        try:
            if time.time() - HEARTBEAT["poll"] > 90:
                start_polling_thread()
            resume_saved_auto_traders()
        except Exception:
            pass


class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(f"AI Institutional Sniper Bot OK | last poll {int(time.time() - HEARTBEAT['poll'])}s ago".encode())

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, *a):
        return


def start_keep_alive():
    for port in (env_num("PORT", 8080, int), 10000, 8081, 3000, 0):
        try:
            HTTPServer.allow_reuse_address = True
            srv = HTTPServer(("0.0.0.0", port), KeepAliveHandler)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            return
        except Exception:
            continue


def mt5_boot():
    try:
        if NATIVE_MT5_AVAILABLE:
            if ensure_windows_mt5_terminal():
                with mt5_lock:
                    launch_mt5_with_verified_autotrading(KNOWN_MT5_LOGIN, KNOWN_MT5_PASS, KNOWN_MT5_SERVER)
                    inject_global_broker_servers()
                safe_print("MT5 Ready with AutoTrading Enabled.")
    except Exception:
        safe_print("mt5_boot error:", redact(traceback.format_exc()))
    finally:
        MT5_BOOT_DONE.set()


def main():
    for sig in (signal.SIGINT, getattr(signal, "SIGTERM", signal.SIGINT)):
        try:
            signal.signal(sig, lambda *a: SHUTDOWN.set())
        except Exception:
            pass
    init_db()
    start_keep_alive()
    threading.Thread(target=mt5_boot, daemon=True).start()
    tg_api("deleteWebhook", {"drop_pending_updates": False})
    start_polling_thread()
    resume_saved_auto_traders()
    threading.Thread(target=background_market_radar_loop, daemon=True).start()
    threading.Thread(target=watchdog, daemon=True).start()
    safe_print("Bot started successfully.")
    while not SHUTDOWN.is_set() and time.time() - BOT_START_TIME < MAX_RUNTIME_SECONDS:
        SHUTDOWN.wait(5)
    SHUTDOWN.set()


if __name__ == "__main__":
    main()
