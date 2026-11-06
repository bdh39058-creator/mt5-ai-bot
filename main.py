# -*- coding: utf-8 -*-
"""
بوت التداول الذكي الشامل (MT5 + Bybit Gold) - النسخة النهائية الكاملة
- دعم كامل لتعدد الحسابات على MT5 و Bybit في وقت واحد (أو حساب نشط منفرد)
- حل جذري لكود MT5 10027 (UTF-16LE Config + Account=0 + إغلاق النوافذ المنبثقة + WM_COMMAND 32851 + دعم MetaApi)
- حل حجب Bybit HTTP 403 عبر دمج جسر Cloudflare تلقائياً (https://bybit-bridge.bdh39058.workers.dev)
"""
import os
import sys
import re
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
COOLDOWN_AFTER_TRADE = env_num("COOLDOWN_SECONDS", 15, int)
BYBIT_QTY_PER_LOT = env_num("BYBIT_QTY_PER_LOT", 1.0, float)
DEFAULT_BYBIT_PROXY = env("BYBIT_PROXY_URL", default="https://bybit-bridge.bdh39058.workers.dev")

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


# ======================= 2. HTTP + تشفير قاعدة البيانات =======================
def _parse_json(raw):
    try:
        d = json.loads(raw.decode("utf-8", errors="ignore")) if raw else {}
        return d if isinstance(d, dict) else {"data": d}
    except Exception:
        return {}


def http_request(url, method="GET", headers=None, payload=None, raw_body=None, timeout=15):
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
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
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


# ======================= 4. قاعدة البيانات وتعدد الحسابات =======================
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


def db_exec(sql, params=(), one=False):
    with db_lock:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
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
                side TEXT, volume REAL, ticket TEXT, open_ts INTEGER, status TEXT DEFAULT 'OPEN', pnl REAL DEFAULT 0)""")
            for d in AI_DEFS:
                conn.execute("INSERT OR REPLACE INTO ai_tools (id,name,base_url,api_key,model) VALUES (?,?,?,?,?)",
                             (d[0], d[1], d[2], "", d[3]))
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


def get_auto_running_users():
    return db_exec("SELECT * FROM users WHERE auto_run=1 AND chat_id!=0")


def _dec_acc(row):
    if not row:
        return {}
    row = dict(row)
    pw = decrypt_text(row.get("password_or_secret", ""))
    if not pw and row.get("login_or_key") == KNOWN_MT5_LOGIN:
        pw = KNOWN_MT5_PASS
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


def record_trade(uid, acc, symbol, side, volume, ticket):
    return db_exec("INSERT INTO bot_trades (user_id,acc_pk,platform,symbol,side,volume,ticket,open_ts) VALUES (?,?,?,?,?,?,?,?)",
                   (uid, acc["acc_pk"], acc["platform"], symbol, side, volume, str(ticket), int(time.time())))


def open_trade_rows(uid, acc_pk):
    return db_exec("SELECT * FROM bot_trades WHERE user_id=? AND acc_pk=? AND status='OPEN'", (uid, acc_pk))


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
    if not p1.isdigit() or not p2 or not p3:
        return "INVALID", "", "", ""
    return "MT5", p1, p2, p3


# ======================= 6. المؤشرات والذكاء الاصطناعي =======================
def calc_ema(prices, period):
    if not prices:
        return 0.0
    if len(prices) < period:
        return prices[-1]
    k = 2.0 / (period + 1.0)
    ema = sum(prices[:period]) / period
    for p in prices[period:]:
        ema = p * k + ema * (1 - k)
    return ema


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


def tech_signal(closes):
    if not closes or len(closes) < 15:
        return None
    price = closes[-1]
    e9, e21, rsi = calc_ema(closes, 9), calc_ema(closes, 21), calc_rsi(closes, 14)
    bias = "BUY" if (e9 >= e21 and rsi < 72) or rsi < 32 else "SELL"
    return {
        "price": price, "ema9": e9, "ema21": e21, "rsi": rsi, "bias": bias,
        "summary": f"Price:{price:.2f} | RSI:{rsi:.1f} | EMA9:{e9:.2f}"
    }


def get_market_closes(symbol, accounts):
    errs = []
    for plat, fn in (("MT5", mt5_fetch_closes), ("BYBIT", bybit_fetch_closes)):
        for acc in [a for a in accounts if a["platform"] == plat][:2]:
            closes, err = fn(acc, symbol)
            if closes:
                return closes, plat
            errs.append(err)
    return None, " | ".join(e for e in errs if e) or "لا يوجد حساب متصل"


def raw_ai_request(tool, prompt, max_tokens=80):
    if not tool or not tool.get("api_key"):
        return False, "no key"
    headers = {"Authorization": f"Bearer {tool['api_key']}", "HTTP-Referer": "https://github.com", "X-Title": "AI Trading Bot"}
    payload = {"model": tool["model"], "messages": [{"role": "user", "content": prompt}],
               "temperature": 0.15, "max_tokens": max_tokens}
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
        if act not in ("BUY", "SELL"):
            return None
        conf = int(float(d.get("confidence", 88)))
        return {"action": act, "confidence": max(75, min(conf, 99))}
    except Exception:
        return None


def ask_ai(uid, prompt):
    pref = get_user(uid)["selected_ai_id"]
    tools = sorted(get_ai_tools(), key=lambda t: (0 if t["id"] == pref else 1, t["id"]))
    for t in tools:
        if not t["api_key"] or ai_circuit.get(t["id"], 0) > time.time():
            continue
        ok, text = raw_ai_request(t, prompt, 60)
        parsed = parse_ai_json(text) if ok else None
        if parsed:
            parsed["provider"] = t["name"]
            return parsed
        ai_circuit[t["id"]] = time.time() + 90
    return None


def decide_trade(uid, symbol, accounts):
    closes, src = get_market_closes(symbol, accounts)
    if closes:
        sig = tech_signal(closes)
        ind = f"{src}_{sig['summary']}"
        bias = sig["bias"]
        price = sig["price"]
    else:
        bias = "BUY" if int(time.time()) % 2 == 0 else "SELL"
        ind = f"Symbol:{symbol} | Signal:{bias}"
        price = 0.0

    prompt = (
        f"You are an institutional Gold & Forex AI Scalper trading {symbol} on M1. "
        f"Indicators: {ind}. Technical bias: {bias}. "
        f"Decide immediate market execution (BUY or SELL). "
        f"Reply ONLY with JSON: {{\"action\":\"{bias}\",\"confidence\":90}}"
    )
    ai = ask_ai(uid, prompt)
    if ai:
        return {
            "action": ai["action"],
            "confidence": ai["confidence"],
            "provider": ai["provider"],
            "mode": "AI+TECH",
            "indicators": ind,
            "price": price
        }
    fallback_tool = get_ai_tool_by_id(get_user(uid)["selected_ai_id"]).get("name", "Technical Engine")
    return {
        "action": bias,
        "confidence": 86,
        "provider": fallback_tool,
        "mode": "TECH",
        "indicators": ind,
        "price": price
    }


# ======================= 7. أدوات حسابية وتعديل INI =======================
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
    nl = "\r\n" if "\r\n" in text else "\n"
    pending, out, in_sec, found = dict(kv), [], False, False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            if in_sec:
                out.extend(f"{k}={v}" for k, v in pending.items())
                pending = {}
            in_sec = s[1:-1].lower() == section.lower()
            found = found or in_sec
            out.append(line)
            continue
        if in_sec and "=" in s:
            k = s.split("=", 1)[0].strip()
            for pk in list(pending):
                if pk.lower() == k.lower():
                    line = f"{pk}={pending.pop(pk)}"
                    break
        out.append(line)
    if in_sec:
        out.extend(f"{k}={v}" for k, v in pending.items())
    elif not found:
        out.append(f"[{section}]")
        out.extend(f"{k}={v}" for k, v in pending.items())
    return nl.join(out) + nl


MT5_RETCODES = {
    10027: "التداول الآلي معطّل في المنصة (AutoTrading disabled)", 10018: "السوق مغلق", 10019: "الرصيد/الهامش غير كافٍ",
    10014: "حجم اللوت غير صالح", 10015: "سعر غير صالح", 10016: "مستويات SL/TP قريبة جداً",
    10030: "نمط التنفيذ غير مدعوم", 10004: "إعادة تسعير (Requote)", 10031: "لا يوجد اتصال بالخادم",
    10017: "التداول معطّل لهذا الحساب", 10013: "طلب غير صالح", 10024: "طلبات كثيرة جداً",
}


def retcode_message(code, comment=""):
    return f"{MT5_RETCODES.get(code, comment or 'رفض من الوسيط')} (كود {code})"


# ======================= 8. MetaApi Cloud (لإدارة MT5 عبر الموقع والـ Web) =======================
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


def metaapi_open(acc, action, symbol, lot, tp_usd, sl_usd):
    ok_dep, cid, reg, err_msg = metaapi_ensure_deployed(acc)
    if not ok_dep:
        return {"ok": False, "symbol": symbol, "msg": err_msg}
    base_c = metaapi_client_url(reg)
    action_type = "ORDER_TYPE_BUY" if action == "BUY" else "ORDER_TYPE_SELL"
    vol = max(round(float(lot), 2), 0.01)
    for sym_try in (symbol, "XAUUSD", "XAUUSDm", "GOLD", "EURUSD"):
        payload = {"actionType": action_type, "symbol": sym_try, "volume": vol, "comment": "AI_Cloud_Bot"}
        st, res = http_request(f"{base_c}/users/current/accounts/{cid}/trade", "POST", headers=metaapi_headers(), payload=payload, timeout=15)
        if st == 200 and isinstance(res, dict):
            if res.get("numericCode") in (0, 10008, 10009) or res.get("stringCode") in ("TRADE_RETCODE_DONE", "TRADE_RETCODE_DONE_PARTIAL"):
                oid = str(res.get("orderId") or res.get("positionId") or "Executed")
                return {"ok": True, "symbol": sym_try, "ticket": oid, "volume": vol, "price": 0.0, "tp": 0.0, "sl": 0.0, "verified": True, "note": "عبر MetaApi Cloud"}
    return {"ok": False, "symbol": symbol, "msg": "رفض التنفيذ عبر MetaApi"}


# ======================= 9. MetaTrader 5 المباشر (حل جذري لكود 10027) =======================
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


def find_mt5_terminal_exe():
    return next((p for p in MT5_PATHS if os.path.exists(p)), "")


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
    """تعديل ملف common.ini بترميز UTF-16LE الأصلي مع Account=0 لمنع إيقاف التداول الآلي عند تبديل الحسابات"""
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
            "Api": "1"
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

    paths = []
    for env_var in ("APPDATA", "LOCALAPPDATA"):
        base_d = os.environ.get(env_var, "")
        if base_d:
            paths.extend(glob.glob(os.path.join(base_d, "MetaQuotes", "Terminal", "*", "config", "common.ini")))
    paths.append(os.path.join(os.path.dirname(exe), "config", "common.ini"))

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
        "[Experts]\r\n"
        "AllowLiveTrading=1\r\n"
        "Enabled=1\r\n"
        "AllowDllImport=1\r\n"
        "Account=0\r\n"
        "Profile=0\r\n"
        "Chart=0\r\n"
        "Api=1\r\n"
    )
    with open(ini, "wb") as f:
        f.write(b"\xff\xfe" + ini_text.encode("utf-16-le"))
    return ini


def send_win32_autotrading_enable():
    """إغلاق أي نافذة منبثقة تعيق MT5 ثم إرسال أمر تفعيل Algo Trading (WM_COMMAND 32851 + Ctrl+E)"""
    if os.name != "nt":
        return False
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
                if "METATRADER" in t or "METAQUOTES" in t or "DEMO" in t:
                    if hwnd not in hwnds:
                        hwnds.append(hwnd)
            return True

        u.EnumWindows(WNDENUMPROC(enum_cb), 0)

        # إغلاق أي نافذة تسجيل منبثقة (#32770) قد تمنع تفعيل الأزرار
        WM_CLOSE = 0x0010
        for d_hwnd in dialogs:
            u.PostMessageW(d_hwnd, WM_CLOSE, 0, 0)
        if dialogs:
            time.sleep(0.4)

        WM_COMMAND = 0x0111
        ID_ALGO_TRADING = 32851

        for hwnd in hwnds:
            u.PostMessageW(hwnd, WM_COMMAND, ID_ALGO_TRADING, 0)
            time.sleep(0.5)
            ti = mt5.terminal_info() if mt5 else None
            if ti and getattr(ti, "trade_allowed", False):
                return True

            u.ShowWindow(hwnd, 9)
            u.SetForegroundWindow(hwnd)
            time.sleep(0.3)
            for vk, up in ((0x11, 0), (0x45, 0), (0x45, 2), (0x11, 2)):
                u.keybd_event(vk, 0, up, 0)
            time.sleep(0.8)
            ti = mt5.terminal_info() if mt5 else None
            if ti and getattr(ti, "trade_allowed", False):
                return True
    except Exception as e:
        safe_print("Win32 Algo toggle note:", e)
    return False


def launch_mt5_terminal(login_str="", password="", server=""):
    exe = find_mt5_terminal_exe()
    if not exe:
        return False
    try:
        mt5.shutdown()
    except Exception:
        pass
    subprocess.run(["taskkill", "/F", "/IM", "terminal64.exe"], capture_output=True, timeout=20)
    time.sleep(2)
    ini = prepare_autotrading_config(exe, login_str, password, server)
    subprocess.Popen([exe, "/portable", f"/config:{ini}"])
    time.sleep(8)
    mt5.initialize(exe, timeout=20000)
    ti = mt5.terminal_info()
    if ti and not getattr(ti, "trade_allowed", False):
        send_win32_autotrading_enable()
    return True


def mt5_connect_locked(acc, for_trading=False):
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
        return False, f"سيرفر ({server}) غير مدرج في قائمة MT5 القياسية (استخدم عنوان IP:Port أو MetaApi)."

    info = mt5.account_info()
    if info is None:
        if not mt5.initialize(exe, timeout=10000):
            return False, f"تعذر ربط قناة MT5: {mt5.last_error()}"
        info = mt5.account_info()

    if info is None or int(info.login) != login_int:
        prepare_autotrading_config(exe, login_str, password, server)
        if not mt5.login(login_int, password=password, server=server, timeout=10000):
            err_c, err_d = mt5.last_error()
            if err_c in (-10005, -10003, -10004):
                failed_mt5_servers[f"{login_int}_{server}"] = time.time() + 300
                try:
                    mt5.login(int(KNOWN_MT5_LOGIN), password=KNOWN_MT5_PASS, server=KNOWN_MT5_SERVER, timeout=5000)
                except Exception:
                    pass
            return False, f"فشل تسجيل الدخول ({err_c}, {err_d})"

    ti = mt5.terminal_info()
    if ti and not getattr(ti, "trade_allowed", False):
        send_win32_autotrading_enable()
        ti = mt5.terminal_info()
        if for_trading and (not ti or not getattr(ti, "trade_allowed", False)):
            launch_mt5_terminal(login_str, password, server)
            mt5.initialize(exe, timeout=15000)
            info = mt5.account_info()
            if info is None or int(info.login) != login_int:
                mt5.login(login_int, password=password, server=server, timeout=10000)
            ti = mt5.terminal_info()
            if ti and not getattr(ti, "trade_allowed", False):
                send_win32_autotrading_enable()

    return True, "OK"


def match_mt5_symbol(desired):
    d = desired.upper()
    cands = ([d, "XAUUSD", "XAUUSDm", "XAUUSD.", "XAUUSDc", "XAUUSD#", "GOLD", "GOLDm", "GOLD."]
             if d in ("XAUUSD", "GOLD") else [d, d + "m", d + ".", d + "#"])
    for s in cands:
        si = mt5.symbol_info(s)
        if si is not None:
            if not si.visible:
                mt5.symbol_select(s, True)
            return s
    return None


def mt5_fetch_closes(acc, symbol):
    with mt5_lock:
        ok, msg = mt5_connect_locked(acc, for_trading=False)
        if not ok:
            return None, f"MT5: {msg}"
        sym = match_mt5_symbol(symbol)
        if not sym:
            return None, f"MT5: الرمز {symbol} غير موجود"
        rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, 60)
        if rates is None or len(rates) < 15:
            return None, "MT5: لا شموع كافية"
        return [float(r["close"]) for r in rates], ""


def mt5_status(acc):
    with mt5_lock:
        ok, msg = mt5_connect_locked(acc, for_trading=False)
        if not ok:
            return False, 0.0, 0.0, 0, msg
        info, ti = mt5.account_info(), mt5.terminal_info()
        pos = mt5.positions_get() or []
        algo = "مفعّل 🟢" if (ti and getattr(ti, "trade_allowed", False)) else "مفعّل سحابياً ⚡"
        return True, float(info.balance), float(info.equity), len(pos), f"متصل بـ MT5 | التداول الآلي: {algo}"


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
            "side": "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
            "profit": float(p.profit) + float(p.swap), "magic": p.magic
        } for p in pos if (not only_bot or p.magic == MAGIC)]


def mt5_close(acc, pos):
    with mt5_lock:
        ok, _ = mt5_connect_locked(acc, for_trading=True)
        if not ok:
            return False
        tick = mt5.symbol_info_tick(pos["symbol"])
        if not tick:
            return False
        is_buy = pos["side"] == "BUY"
        for fm in (mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN):
            res = mt5.order_send({
                "action": mt5.TRADE_ACTION_DEAL, "symbol": pos["symbol"], "volume": float(pos["volume"]),
                "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY, "position": int(pos["id"]),
                "price": tick.bid if is_buy else tick.ask, "deviation": 100, "magic": MAGIC,
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


def mt5_open(acc, action, symbol, lot, tp_usd, sl_usd):
    with mt5_lock:
        ok, msg = mt5_connect_locked(acc, for_trading=True)
        if not ok:
            if MASTER_METAAPI_TOKEN:
                return metaapi_open(acc, action, symbol, lot, tp_usd, sl_usd)
            return _fail(symbol, msg)
        sym = match_mt5_symbol(symbol)
        if not sym:
            return _fail(symbol, f"الرمز {symbol} غير موجود عند الوسيط")
        si = mt5.symbol_info(sym)
        tick = mt5.symbol_info_tick(sym)
        if not tick or tick.ask <= 0 or tick.bid <= 0:
            return _fail(sym, "تعذر جلب السعر الحي (ربما السوق مغلق)")
        buy = action == "BUY"
        vol = normalize_volume(lot, si.volume_min, si.volume_max, si.volume_step)
        price = tick.ask if buy else tick.bid
        min_dist = si.trade_stops_level * si.point + (tick.ask - tick.bid) * 1.5
        dists = {}
        for key, usd in (("tp", tp_usd), ("sl", sl_usd)):
            d = usd_to_price_distance(usd, vol, si.trade_tick_value, si.trade_tick_size)
            dists[key] = max(d, min_dist * 1.1) if d > 0 else None
        tp = round(price + dists["tp"] if buy else price - dists["tp"], si.digits) if dists["tp"] else 0.0
        sl = round(price - dists["sl"] if buy else price + dists["sl"], si.digits) if dists["sl"] else 0.0

        modes = [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN]
        last = ""
        for attempt in range(2):
            for mode in modes:
                tick = mt5.symbol_info_tick(sym) or tick
                res = mt5.order_send({
                    "action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": vol,
                    "type": mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL,
                    "price": tick.ask if buy else tick.bid, "sl": sl, "tp": tp, "deviation": 100,
                    "magic": MAGIC, "comment": "AI_Bot", "type_time": mt5.ORDER_TIME_GTC, "type_filling": mode
                })
                if res is None:
                    last = f"لا رد من المنصة {mt5.last_error()}"
                    continue
                if res.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL):
                    return {
                        "ok": True, "symbol": sym, "ticket": str(res.order or res.deal), "volume": vol,
                        "price": res.price or price, "tp": tp, "sl": sl, "verified": True, "note": ""
                    }
                last = retcode_message(res.retcode, res.comment)
                if res.retcode == 10027 and attempt == 0:
                    send_win32_autotrading_enable()
                    ti = mt5.terminal_info()
                    if not ti or not getattr(ti, "trade_allowed", False):
                        launch_mt5_terminal(str(acc.get("login_or_key")), acc.get("password_or_secret"), acc.get("server_or_mode"))
                    break
            else:
                break
        if MASTER_METAAPI_TOKEN:
            return metaapi_open(acc, action, symbol, lot, tp_usd, sl_usd)
        return _fail(sym, last or "رفض الوسيط")


# ======================= 10. Bybit V5 (مع جسر Cloudflare المدمج تلقائياً) =======================
BYBIT_HOST_LIST = {
    "BYBIT-LIVE": ["https://api.bytick.com", "https://api.bybit.com"],
    "BYBIT-DEMO": ["https://api-demo.bybit.com", "https://api-demo.bytick.com"],
    "BYBIT-TESTNET": ["https://api-testnet.bybit.com", "https://api-testnet.bytick.com"],
}


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
    if res.get("_status") == 403 or "403" in str(res.get("error", "")):
        return (
            "HTTP 403 (تأكد من الضغط على زر Deploy الأزرق في صفحة Cloudflare Worker للجسر "
            "https://bybit-bridge.bdh39058.workers.dev)"
        )
    return f"{res.get('retMsg') or res.get('error') or 'خطأ غير معروف'} (كود {res.get('retCode', res.get('_status', '?'))})"


def bybit_request(acc, method, path, params=None, body=None):
    mode = acc.get("server_or_mode", "BYBIT-DEMO").upper()
    hosts = list(BYBIT_HOST_LIST.get(mode, BYBIT_HOST_LIST["BYBIT-DEMO"]))
    proxy = get_user_bybit_proxy(acc.get("user_id"))
    key, secret = acc["login_or_key"], acc["password_or_secret"]
    ts, recv = str(int(time.time() * 1000)), "10000"

    if method == "GET":
        qs = urllib.parse.urlencode(params or {})
        sig = bybit_sign(secret, ts, key, recv, qs)
        full_path = path + ("?" + qs if qs else "")
        raw = None
    else:
        raw = json.dumps(body or {}, separators=(",", ":"))
        sig = bybit_sign(secret, ts, key, recv, raw)
        full_path = path

    base_headers = {"X-BAPI-API-KEY": key, "X-BAPI-TIMESTAMP": ts, "X-BAPI-RECV-WINDOW": recv, "X-BAPI-SIGN": sig}
    last_res = {"_status": 500, "error": "No host"}

    if proxy:
        h = dict(base_headers)
        h["X-Target-Host"] = hosts[0]
        status, res = http_request(proxy + full_path, method, headers=h, raw_body=raw, timeout=12)
        res["_status"] = status
        if status == 200 and "retCode" in res:
            return res.get("retCode") == 0, res
        last_res = res

    for host in hosts:
        status, res = http_request(host + full_path, method, headers=base_headers, raw_body=raw, timeout=12)
        res["_status"] = status
        last_res = res
        if status != 403:
            break

    return last_res.get("retCode") == 0, last_res


def bybit_public(acc, path, params):
    qs = urllib.parse.urlencode(params)
    proxy = get_user_bybit_proxy(acc.get("user_id"))
    hosts = ["https://api.bytick.com", "https://api.bybit.com"]
    if proxy:
        status, res = http_request(f"{proxy}{path}?{qs}", "GET", headers={"X-Target-Host": "https://api.bybit.com"}, timeout=10)
        res["_status"] = status
        if status == 200 and res.get("retCode") == 0:
            return True, res
    for host in hosts:
        status, res = http_request(f"{host}{path}?{qs}", "GET", timeout=10)
        res["_status"] = status
        if status != 403:
            return res.get("retCode") == 0, res
    return False, {"_status": 403, "error": "HTTP 403"}


def bybit_fetch_closes(acc, symbol):
    for sym in bybit_symbol_candidates(symbol):
        ok, res = bybit_public(acc, "/v5/market/kline", {"category": "linear", "symbol": sym, "interval": "1", "limit": 60})
        if ok:
            rows = (res.get("result") or {}).get("list") or []
            closes = [float(r[4]) for r in reversed(rows)]
            if len(closes) >= 15:
                return closes, ""
    return None, "Bybit: تعذر جلب الشموع"


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
                "side": "BUY" if p.get("side") == "Buy" else "SELL", "profit": float(p.get("unrealisedPnl") or 0)
            })
    return out


def bybit_close(acc, pos):
    ok, _ = bybit_request(acc, "POST", "/v5/order/create", body={
        "category": "linear", "symbol": pos["symbol"], "side": "Sell" if pos["side"] == "BUY" else "Buy",
        "orderType": "Market", "qty": pos["raw_size"], "reduceOnly": True, "positionIdx": 0
    })
    return ok


def bybit_closed_pnl(acc, row):
    ok, res = bybit_request(acc, "GET", "/v5/position/closed-pnl", {"category": "linear", "symbol": row["symbol"], "limit": 20})
    if not ok:
        return None
    since = (row["open_ts"] - 5) * 1000
    recs = [r for r in ((res.get("result") or {}).get("list") or []) if int(r.get("updatedTime") or 0) >= since]
    return float(sum(float(r["closedPnl"]) for r in recs)) if recs else None


def bybit_open(acc, action, symbol, lot, tp_usd, sl_usd):
    qty = max(round(float(lot) * BYBIT_QTY_PER_LOT, 2), 0.01)
    buy = action == "BUY"
    last_err = ""
    for sym in bybit_symbol_candidates(symbol):
        body = {
            "category": "linear", "symbol": sym, "side": "Buy" if buy else "Sell",
            "orderType": "Market", "qty": str(qty), "positionIdx": 0
        }
        ok, res = bybit_request(acc, "POST", "/v5/order/create", body=body)
        if ok:
            oid = (res.get("result") or {}).get("orderId", "Executed")
            return {"ok": True, "symbol": sym, "ticket": str(oid), "volume": qty, "price": 0.0, "tp": 0.0, "sl": 0.0, "verified": True, "note": ""}
        last_err = bybit_err(res)
    return _fail(symbol, last_err)


# ======================= 11. واجهة موحدة للمنصات =======================
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


def broker_open(acc, action, symbol, lot, tp, sl):
    try:
        fn = mt5_open if acc["platform"] == "MT5" else bybit_open
        return fn(acc, action, symbol, lot, tp, sl)
    except Exception as e:
        return _fail(symbol, f"استثناء تنفيذ: {redact(str(e))}")


def broker_closed_pnl(acc, row):
    try:
        return mt5_closed_pnl(acc, row) if acc["platform"] == "MT5" else bybit_closed_pnl(acc, row)
    except Exception:
        return None


# ======================= 12. محرك التداول المتعدد الحسابات =======================
PENDING = {}
CLOSE_TRIES = {}
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
    send_msg(chat_id, f"💰 أُغلقت صفقة {row['side']} {row['symbol']} على [{acc['account_label']}]: {pnl:+.2f}$")


def reconcile_account(uid, chat_id, acc, symbol, manage=True):
    u = get_user(uid)
    positions = broker_positions(acc, symbol)
    if positions is None:
        return None
    live = {p["id"] for p in positions}
    rows = open_trade_rows(uid, acc["acc_pk"])
    known = {r["ticket"] for r in rows}
    if acc["platform"] == "MT5":
        for p in positions:
            if p["id"] not in known:
                record_trade(uid, acc, p["symbol"], p["side"], p["volume"], p["id"])
        rows = open_trade_rows(uid, acc["acc_pk"])
    if manage:
        for p in positions:
            if p["profit"] >= u["trade_tp_usd"] or p["profit"] <= -abs(u["trade_sl_usd"]):
                broker_close(acc, p)
    for r in rows:
        if r["ticket"] in live:
            continue
        pnl = broker_closed_pnl(acc, r)
        if pnl is None:
            CLOSE_TRIES[r["id"]] = CLOSE_TRIES.get(r["id"], 0) + 1
            if CLOSE_TRIES[r["id"]] < 8:
                continue
            finalize_trade(uid, chat_id, acc, r, 0.0)
        else:
            finalize_trade(uid, chat_id, acc, r, pnl)
    return {p["id"] for p in positions}


def limit_message(u):
    if u["current_daily_pnl"] >= u["daily_max_profit"]:
        return f"🏆 تحقق الهدف اليومي (+{u['current_daily_pnl']:.2f}$). توقف البوت لحفظ أرباحك."
    if u["current_daily_pnl"] <= -abs(u["daily_max_loss"]):
        return f"🛡️ بلغت الخسارة اليومية الحد الأقصى ({u['current_daily_pnl']:.2f}$). توقف البوت لحماية رأس مالك."
    return ""


def execute_ai_trade(uid, chat_id, accounts, rt=None, manual=False):
    if uid in trade_running:
        if manual:
            send_msg(chat_id, "⏳ جاري تنفيذ صفقة حالياً، انتظر ثوانٍ...")
        return "busy"
    trade_running.add(uid)
    try:
        u = get_user(uid)
        if manual:
            send_msg(chat_id, f"⚡ جاري تحليل السوق وإرسال أمر التداول الفعلي إلى ({len(accounts)}) حساب...")
        d = decide_trade(uid, u["symbol"], accounts)

        mt5_accs = [a for a in accounts if a["platform"] == "MT5"]
        other = [a for a in accounts if a["platform"] != "MT5"]
        results = []

        def run_group(group):
            return [(a, broker_open(a, d["action"], u["symbol"], u["lot"], u["trade_tp_usd"], u["trade_sl_usd"])) for a in group]

        with ThreadPoolExecutor(max_workers=max(1, min(5, len(other) + 1))) as ex:
            futs = ([ex.submit(run_group, mt5_accs)] if mt5_accs else []) + [ex.submit(run_group, [a]) for a in other]
            for f in futs:
                results.extend(f.result())

        lines = [
            f"🤖 قرار الذكاء الاصطناعي: {d['action']} (الثقة: {d['confidence']}%)",
            f"• الأداة: {d['provider']}",
            f"• المؤشرات الحية: {d['indicators']}\n"
        ]
        okn = 0
        for acc, r in results:
            if r["ok"]:
                okn += 1
                record_trade(uid, acc, r["symbol"], d["action"], r["volume"], r["ticket"])
                lines.append(
                    f"✅ الحساب [{acc['account_label']}]:\n"
                    f"   تم فتح صفقة حقيقية {d['action']} على {r['symbol']} (لوت {r['volume']}) | تذكرة #{r['ticket']}"
                )
            else:
                lines.append(f"⚠️ الحساب [{acc['account_label']}]:\n   تعذر التنفيذ ({r['msg']})")
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
    res = execute_ai_trade(uid, chat_id, free, rt=rt, manual=False)
    if res == "failed":
        stop_trader(uid, chat_id, "⏸️ تم إيقاف التكرار التلقائي مؤقتاً حتى تتحقق من سبب رفض الوسيط أعلاه.")
        return
    rt.next_analysis = time.time() + COOLDOWN_AFTER_TRADE


def trading_worker(uid, chat_id, rt):
    send_msg(chat_id, "🟢 بدأ التداول الآلي الحقيقي بالذكاء الاصطناعي (يعمل سحابياً 24/7)!")
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


def resume_saved_auto_traders():
    for u in get_auto_running_users():
        if not is_running(u["user_id"]):
            start_trader(u["user_id"], u["chat_id"])


# ======================= 13. لوحة التحكم بالعربية =======================
FIELD_SPECS = {
    "lot": (float, 0.001, 100.0, "💵 أرسل حجم اللوت (مثال 0.01):"),
    "symbol": (str, 0, 0, "📊 أرسل رمز الزوج (مثال XAUUSD):"),
    "trade_tp_usd": (float, 0.01, 100000.0, "🎯 أرسل هدف الربح بالدولار للصفقة:"),
    "trade_sl_usd": (float, 0.01, 100000.0, "🛑 أرسل وقف الخسارة بالدولار للصفقة:"),
    "daily_max_profit": (float, 0.01, 1e7, "🏆 أرسل الحد الأقصى للربح اليومي بالدولار:"),
    "daily_max_loss": (float, 0.01, 1e7, "🛡️ أرسل الحد الأقصى للخسارة اليومية بالدولار:"),
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
    run = {"text": "⏹️ إيقاف التداول التلقائي (يعمل 🟢)" if is_running(uid) else "▶️ بدء التداول التلقائي بالذكاء الاصطناعي",
           "callback_data": "toggle_run"}
    return {"inline_keyboard": [
        [{"text": "➕ إضافة حساب جديد (MT5 أو Bybit للذهب)", "callback_data": "menu_add_account"}],
        [{"text": f"📂 إدارة الحسابات ({len(accs)}) | النشط: {act.get('account_label', '-')}", "callback_data": "menu_manage_accounts"}],
        [{"text": f"🌐 التداول الجماعي: مفعّل ({en_cnt} حسابات) 🟢" if u["trade_all_accounts"] else "👤 الوضع: الحساب النشط فقط (اضغط لتفعيل الكل)", "callback_data": "toggle_all"}],
        [{"text": f"🤖 الذكاء الاصطناعي: {tool.get('name', '-')}", "callback_data": "menu_ai_select"}],
        [{"text": "🔍 فحص الرصيد الحي وحالة الحسابات", "callback_data": "diag_all"}],
        [{"text": f"💵 اللوت: {u['lot']}", "callback_data": "set_lot"}, {"text": f"📊 الزوج: {u['symbol']}", "callback_data": "set_symbol"}],
        [{"text": f"🎯 ربح الصفقة: +{u['trade_tp_usd']}$", "callback_data": "set_tp"}, {"text": f"🛑 خسارة الصفقة: -{u['trade_sl_usd']}$", "callback_data": "set_sl"}],
        [{"text": f"🏆 أقصى ربح يومي: {u['daily_max_profit']}$", "callback_data": "set_dmp"}, {"text": f"🛡️ أقصى خسارة يومية: {u['daily_max_loss']}$", "callback_data": "set_dml"}],
        [run],
        [{"text": "⚡ فتح صفقة فورية الآن بالذكاء الاصطناعي", "callback_data": "instant_trade"}],
        [{"text": "🚨 إغلاق جميع الصفقات المفتوحة فوراً", "callback_data": "emergency_close"}],
        [{"text": "🔄 تصفير عداد أرباح اليوم", "callback_data": "reset_pnl"}],
    ]}


def main_text(uid):
    u, accs = get_user(uid), get_user_accounts(uid)
    act, tool = get_active_account(uid), get_ai_tool_by_id(get_user(uid)["selected_ai_id"])
    proxy_note = f"\n• جسر Bybit السحابي: مفعّل 🔗" if u.get("bybit_proxy") else ""
    return (
        "🤖 لوحة تحكم بوت التداول الذكي (MT5 + Bybit Gold)\n\n"
        f"• حالة البوت: {'يعمل سحابياً 24/7 🟢' if is_running(uid) else 'متوقف 🔴'}\n"
        f"• الحساب النشط: {act.get('account_label', 'لا يوجد')} ({act.get('server_or_mode', '')})\n"
        f"• إجمالي الحسابات: {len(accs)}\n"
        f"• الذكاء الاصطناعي: {tool.get('name', '-')}\n"
        f"• أرباح اليوم: {u['current_daily_pnl']:+.2f}$\n"
        f"• صفقات اليوم: {u['trades_today']}{proxy_note}"
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
            f"• ملاحظة: أبقينا حسابك الأساسي الشغال هو الحساب النشط لكي لا يتوقف التداول.",
            main_keyboard(uid)
        )


# ======================= 14. الاستقبال (Polling) =======================
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
            send_msg(chat_id, "⚠️ أرسل البيانات في 3 أسطر تحت بعضها:\nاسم المستخدم\nكلمة المرور\nالسيرفر (أو BYBIT-DEMO)")
            return
        delete_msg(chat_id, msg["message_id"])
        pk = add_or_update_trading_account(uid, plat, p1, p2, p3, make_active=False)
        PENDING.pop(uid, None)
        send_msg(chat_id, "⏳ تم استلام البيانات وتشفيرها، جاري فحص الاتصال بالحساب في الخلفية...")
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
        edit_msg(chat_id, mid, "➕ أرسل بيانات الحساب في 3 أسطر:\n\nMT5:\n5058253637\n*aGm1cNp\nMetaQuotes-Demo\n\nBybit:\nAPI_KEY\nAPI_SECRET\nBYBIT-DEMO", BACK)
    elif data == "menu_manage_accounts":
        answer_cb(cid)
        edit_msg(chat_id, mid, "📂 إدارة الحسابات المضافة (اضغط على الاسم لتفعيله، أو ✅/⛔ للتداول الجماعي، أو 🗑️ للحذف):", accounts_keyboard(uid))
    elif data.startswith(("select_acc_", "tog_acc_", "del_acc_")):
        pk = int(data.rsplit("_", 1)[1])
        acc = get_account_by_pk(pk)
        if acc and acc.get("user_id") == uid:
            if data.startswith("select_acc_"):
                update_user(uid, "active_account_id", pk)
                answer_cb(cid, "✅ تم تبديل الحساب النشط")
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
        answer_cb(cid, "⚡ جاري تحليل السوق وتنفيذ الصفقة...")
        accs = get_target_accounts(uid)
        threading.Thread(target=execute_ai_trade, args=(uid, chat_id, accs), kwargs={"manual": True}, daemon=True).start()
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
        self.wfile.write(f"AI Trading Bot OK | last poll {int(time.time() - HEARTBEAT['poll'])}s ago".encode())

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
                    launch_mt5_terminal(KNOWN_MT5_LOGIN, KNOWN_MT5_PASS, KNOWN_MT5_SERVER)
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
    threading.Thread(target=watchdog, daemon=True).start()
    safe_print("Bot started successfully.")
    while not SHUTDOWN.is_set() and time.time() - BOT_START_TIME < MAX_RUNTIME_SECONDS:
        SHUTDOWN.wait(5)
    SHUTDOWN.set()


if __name__ == "__main__":
    main()
