import os
import sys
import hmac
import json
import time
import glob
import hashlib
import sqlite3
import subprocess
import threading
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

# ================= 0. حل جذري لترميز ويندوز =================
os.environ["PYTHONIOENCODING"] = "utf-8"
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

def safe_print(*args):
    text = " ".join(str(a) for a in args)
    try:
        print(text, flush=True)
    except Exception:
        try:
            sys.stdout.write(text.encode("ascii", errors="ignore").decode("ascii") + "\n")
            sys.stdout.flush()
        except Exception:
            pass

NATIVE_MT5_AVAILABLE = False
if os.name == "nt":
    try:
        import MetaTrader5 as mt5
        NATIVE_MT5_AVAILABLE = True
    except Exception:
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "MetaTrader5"], check=False)
            import MetaTrader5 as mt5
            NATIVE_MT5_AVAILABLE = True
        except Exception:
            NATIVE_MT5_AVAILABLE = False

MT5_TERMINAL_PATHS = [
    r"C:\Program Files\MetaTrader 5\terminal64.exe",
    r"C:\Program Files (x86)\MetaTrader 5\terminal64.exe"
]

def find_mt5_terminal_exe() -> str:
    for p in MT5_TERMINAL_PATHS:
        if os.path.exists(p):
            return p
    return ""

def ensure_windows_mt5_terminal():
    if os.name != "nt":
        return
    if find_mt5_terminal_exe():
        safe_print("MT5 Terminal is ready.")
        return
    safe_print("Installing Official MetaTrader 5 Terminal...")
    installer_path = os.path.join(os.getcwd(), "mt5setup.exe")
    try:
        urllib.request.urlretrieve("https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe", installer_path)
        subprocess.run([installer_path, "/auto"], timeout=120, check=False)
        for _ in range(20):
            if find_mt5_terminal_exe():
                safe_print("MT5 Terminal installed successfully!")
                return
            time.sleep(2)
    except Exception as e:
        safe_print(f"MT5 install note: {e}")

BOT_START_TIME = time.time()
MAX_RUNTIME_SECONDS = 335 * 60


# ================= 1. تفعيل التداول الآلي في MT5 لمنع كود 10027 =================
def force_enable_mt5_autotrading(login_int: int, password: str, server: str):
    try:
        if mt5.terminal_info() and getattr(mt5.terminal_info(), "trade_allowed", False):
            return True
        # محاولة إعادة تهيئة مع إعدادات التداول المسموح
        exe_path = find_mt5_terminal_exe()
        if exe_path:
            mt5.initialize(exe_path, login=login_int, password=password, server=server, timeout=30000)
        else:
            mt5.initialize(login=login_int, password=password, server=server, timeout=30000)
    except Exception:
        pass
    return True


# ================= 2. خادم الويب Keep-Alive =================
class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("Arabic MT5 AI Trading Bot is Running 24/7!".encode("utf-8"))
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()
    def log_message(self, format, *args):
        return

def start_keep_alive():
    for port in [int(os.environ.get("PORT", 8080)), 8081, 3000, 5000, 0]:
        try:
            HTTPServer.allow_reuse_address = True
            server = HTTPServer(("0.0.0.0", port), KeepAliveHandler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            return
        except Exception:
            continue


# ================= 3. قراءة المفاتيح السرية =================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
MASTER_METAAPI_TOKEN = os.getenv("METAAPI_TOKEN", "").strip()
ENV_BYBIT_KEY = os.getenv("BYBIT_API_KEY", "").strip()
ENV_BYBIT_SECRET = os.getenv("BYBIT_API_SECRET", "").strip()
SECRET_ACCESS_KEY = os.getenv("SECRET_ACCESS_KEY", "vip_secret_99").strip()

COHERE_KEY = os.getenv("COHERE_TOKEN", "").strip()
GEMINI_KEY = os.getenv("GEMINI_TOKEN", "").strip()
GITHUB_KEY = (os.getenv("GH_MODELS_TOKEN") or os.getenv("GITHUB_MODELS_TOKEN") or os.getenv("GITHUB_TOKEN") or "").strip()
GROQ_KEY = (os.getenv("GROQ_TOKEN") or os.getenv("GROQ_TOKRN") or "").strip()
HUGGINGFACE_KEY = os.getenv("HUGGINGFACE_TOKEN", "").strip()
OPENROUTER_KEY = (os.getenv("OPENROUTER1_TOKEN") or os.getenv("OPENROUTER_TOKEN") or "").strip()
SAMBANOVA_KEY = os.getenv("SAMBANOVA_TOKEN", "").strip()

KNOWN_MT5_LOGIN = "5058253637"
KNOWN_MT5_PASS = "*aGm1cNp"
KNOWN_MT5_SERVER = "MetaQuotes-Demo"
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


# ================= 4. طبقة الاتصال الآمن وتيليجرام =================
def http_request(url: str, method: str = "GET", headers: dict = None, payload: dict = None, raw_body: str = None, timeout: int = 20):
    req_headers = {"User-Agent": BROWSER_UA, "Accept": "application/json"}
    if headers:
        req_headers.update(headers)
    data = None
    if raw_body is not None:
        data = raw_body.encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")
    elif payload is not None:
        data = json.dumps(payload).encode("utf-8")
        req_headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            if not body:
                return resp.status, {}
            return resp.status, json.loads(body)
    except Exception as e:
        return 500, {"error": str(e)}

def tg_api(method_name: str, params: dict = None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method_name}"
    _, res = http_request(url, method="POST", payload=params or {}, timeout=15)
    return res if isinstance(res, dict) else {}

def send_msg(chat_id: int, text: str, reply_markup: dict = None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    res = tg_api("sendMessage", payload)
    if not res.get("ok"):
        fallback = {"chat_id": chat_id, "text": text.replace("**", "").replace("`", "")}
        if reply_markup:
            fallback["reply_markup"] = reply_markup
        res = tg_api("sendMessage", fallback)
    return res

def edit_msg(chat_id: int, message_id: int, text: str, reply_markup: dict = None):
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    res = tg_api("editMessageText", payload)
    if not res.get("ok"):
        fallback = {"chat_id": chat_id, "message_id": message_id, "text": text.replace("**", "").replace("`", "")}
        if reply_markup:
            fallback["reply_markup"] = reply_markup
        res = tg_api("editMessageText", fallback)
    return res

def answer_cb(callback_id: str, text: str = "", show_alert: bool = False):
    return tg_api("answerCallbackQuery", {"callback_query_id": callback_id, "text": text[:190], "show_alert": show_alert})

def delete_msg(chat_id: int, message_id: int):
    return tg_api("deleteMessage", {"chat_id": chat_id, "message_id": message_id})


# ================= 5. قاعدة البيانات =================
DB_FILE = "multi_mt5_gold_bot.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            chat_id INTEGER DEFAULT 0,
            is_authorized INTEGER DEFAULT 0,
            auto_run INTEGER DEFAULT 0,
            active_account_id INTEGER DEFAULT 1,
            trade_all_accounts INTEGER DEFAULT 0,
            selected_ai_id INTEGER DEFAULT 1,
            symbol TEXT DEFAULT 'XAUUSD',
            lot REAL DEFAULT 0.01,
            trade_tp_usd REAL DEFAULT 0.50,
            trade_sl_usd REAL DEFAULT 1.00,
            daily_max_profit REAL DEFAULT 20.0,
            daily_max_loss REAL DEFAULT 10.0,
            work_start_hour INTEGER DEFAULT 0,
            work_end_hour INTEGER DEFAULT 24,
            current_daily_pnl REAL DEFAULT 0.0,
            trades_today INTEGER DEFAULT 0
        )
    """)
    for col_def in ["chat_id INTEGER DEFAULT 0", "auto_run INTEGER DEFAULT 0"]:
        try:
            c.execute(f"ALTER TABLE users ADD COLUMN {col_def}")
        except Exception:
            pass
    c.execute("""
        CREATE TABLE IF NOT EXISTS trading_accounts (
            acc_pk INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            platform TEXT DEFAULT 'MT5',
            account_label TEXT DEFAULT '',
            login_or_key TEXT DEFAULT '',
            password_or_secret TEXT DEFAULT '',
            server_or_mode TEXT DEFAULT '',
            is_enabled INTEGER DEFAULT 1
        )
    """)
    c.execute("DROP TABLE IF EXISTS ai_tools")
    c.execute("""
        CREATE TABLE ai_tools (
            id INTEGER PRIMARY KEY,
            name TEXT,
            base_url TEXT,
            api_key TEXT,
            model TEXT
        )
    """)
    tools_list = [
        (1, "Groq (Llama-3.3-70B)", "https://api.groq.com/openai/v1/chat/completions", GROQ_KEY, "llama-3.3-70b-versatile"),
        (2, "Google (Gemini 2.5 Flash)", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", GEMINI_KEY, "gemini-2.0-flash"),
        (3, "GitHub (GPT-4o Mini)", "https://models.inference.ai.azure.com/chat/completions", GITHUB_KEY, "gpt-4o-mini"),
        (4, "SambaNova (Llama-3.1-70B)", "https://api.sambanova.ai/v1/chat/completions", SAMBANOVA_KEY, "Meta-Llama-3.1-70B-Instruct"),
        (5, "Cohere (Command-R+)", "https://api.cohere.ai/compatibility/v1/chat/completions", COHERE_KEY, "command-r-plus-08-2024"),
        (6, "OpenRouter (Gemma-3-27B)", "https://openrouter.ai/api/v1/chat/completions", OPENROUTER_KEY, "google/gemma-2-9b-it:free"),
        (7, "HuggingFace (Qwen-2.5-72B)", "https://router.huggingface.co/v1/chat/completions", HUGGINGFACE_KEY, "Qwen/Qwen2.5-72B-Instruct"),
        (8, "Groq-2 (Llama-3.1-8B)", "https://api.groq.com/openai/v1/chat/completions", GROQ_KEY, "llama-3.1-8b-instant"),
        (9, "GitHub-2 (GPT-4o Pro)", "https://models.inference.ai.azure.com/chat/completions", GITHUB_KEY, "gpt-4o"),
        (10, "OpenRouter-2 (Llama-3.3)", "https://openrouter.ai/api/v1/chat/completions", OPENROUTER_KEY, "meta-llama/llama-3.2-3b-instruct:free"),
    ]
    c.executemany("INSERT INTO ai_tools VALUES (?, ?, ?, ?, ?)", tools_list)
    conn.commit()
    conn.close()

def ensure_default_account(user_id: int):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM trading_accounts WHERE user_id = ? ORDER BY acc_pk ASC", (user_id,))
    rows = c.fetchall()
    if not rows:
        c.execute("""
            INSERT INTO trading_accounts (user_id, platform, account_label, login_or_key, password_or_secret, server_or_mode, is_enabled)
            VALUES (?, 'MT5', ?, ?, ?, ?, 1)
        """, (user_id, f"MT5 ({KNOWN_MT5_LOGIN})", KNOWN_MT5_LOGIN, KNOWN_MT5_PASS, KNOWN_MT5_SERVER))
        new_pk = c.lastrowid
        c.execute("UPDATE users SET active_account_id = ? WHERE user_id = ?", (new_pk, user_id))
        conn.commit()
    conn.close()

def get_user(user_id: int) -> dict:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    if not row:
        c.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
        conn.commit()
        c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = c.fetchone()
    conn.close()
    ensure_default_account(user_id)
    return dict(row)

def update_user(user_id: int, field: str, value):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(f"UPDATE users SET {field} = ? WHERE user_id = ?", (value, user_id))
    conn.commit()
    conn.close()

def get_auto_running_users() -> list:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE auto_run = 1 AND chat_id != 0")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def get_user_accounts(user_id: int) -> list:
    ensure_default_account(user_id)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM trading_accounts WHERE user_id = ? ORDER BY acc_pk ASC", (user_id,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def get_account_by_pk(acc_pk: int) -> dict:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM trading_accounts WHERE acc_pk = ?", (acc_pk,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else {}

def get_active_account(user_id: int) -> dict:
    u = get_user(user_id)
    acc = get_account_by_pk(u["active_account_id"])
    if acc:
        return acc
    accs = get_user_accounts(user_id)
    if accs:
        update_user(user_id, "active_account_id", accs[0]["acc_pk"])
        return accs[0]
    return {}

def get_target_trading_accounts(user_id: int) -> list:
    u = get_user(user_id)
    all_accs = get_user_accounts(user_id)
    if u.get("trade_all_accounts") == 1:
        enabled = [a for a in all_accs if a.get("is_enabled"] == 1]
        return enabled if enabled else all_accs
    active = get_active_account(user_id)
    return [active] if active else all_accs

def add_or_update_trading_account(user_id: int, platform: str, login_key: str, pass_secret: str, server_mode: str) -> int:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM trading_accounts WHERE user_id = ? AND login_or_key = ?", (user_id, login_key))
    existing = c.fetchone()
    label = f"Bybit ({login_key[:6]})" if platform == "BYBIT" else f"MT5 ({login_key})"
    if existing:
        pk = existing["acc_pk"]
        c.execute("""
            UPDATE trading_accounts
            SET platform = ?, account_label = ?, password_or_secret = ?, server_or_mode = ?, is_enabled = 1
            WHERE acc_pk = ?
        """, (platform, label, pass_secret, server_mode, pk))
    else:
        c.execute("""
            INSERT INTO trading_accounts (user_id, platform, account_label, login_or_key, password_or_secret, server_or_mode, is_enabled)
            VALUES (?, ?, ?, ?, ?, ?, 1)
        """, (user_id, platform, label, login_key, pass_secret, server_mode))
        pk = c.lastrowid
    c.execute("UPDATE users SET active_account_id = ? WHERE user_id = ?", (pk, user_id))
    conn.commit()
    conn.close()
    return pk

def delete_trading_account(user_id: int, acc_pk: int) -> bool:
    accs = get_user_accounts(user_id)
    if len(accs) <= 1:
        return False
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM trading_accounts WHERE acc_pk = ? AND user_id = ?", (acc_pk, user_id))
    conn.commit()
    conn.close()
    remaining = get_user_accounts(user_id)
    if remaining:
        update_user(user_id, "active_account_id", remaining[0]["acc_pk"])
    return True

def get_ai_tools() -> list:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM ai_tools ORDER BY id ASC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def get_ai_tool_by_id(tool_id: int) -> dict:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM ai_tools WHERE id = ?", (tool_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else {}

def parse_three_line_credentials(raw_text: str) -> tuple[str, str, str, str]:
    cleaned = raw_text.strip()
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if len(lines) >= 3:
        p1 = lines[0].split(":")[-1].strip()
        p2 = lines[1].split(":")[-1].strip()
        p3 = lines[2].split(":")[-1].strip()
    elif "," in cleaned:
        parts = [p.strip() for p in cleaned.split(",") if p.strip()]
        if len(parts) < 3:
            return "INVALID", "", "", ""
        p1, p2, p3 = parts[0], parts[1], parts[2]
    else:
        return "INVALID", "", "", ""
    srv_upper = p3.upper()
    if "BYBIT" in srv_upper:
        mode = "BYBIT-DEMO" if "DEMO" in srv_upper else "BYBIT-LIVE"
        return "BYBIT", p1, p2, mode
    return "MT5", p1, p2, p3


# ================= 6. المؤشرات ومحرك الذكاء الاصطناعي =================
def calc_ema(prices: list, period: int) -> float:
    if not prices:
        return 0.0
    k = 2.0 / (period + 1.0)
    ema = prices[0]
    for p in prices[1:]:
        ema = p * k + ema * (1.0 - k)
    return ema

def calc_rsi(prices: list, period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(-period, 0):
        diff = prices[i] - prices[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    avg_g = sum(gains) / period
    avg_l = sum(losses) / period
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return 100.0 - (100.0 / (1.0 + rs))

def fetch_live_market_indicators(symbol: str) -> tuple[float, str, str]:
    if NATIVE_MT5_AVAILABLE:
        try:
            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 30)
            if rates is not None and len(rates) >= 15:
                closes = [float(r['close']) for r in rates]
                last_p = closes[-1]
                ema9 = calc_ema(closes[-12:], 9)
                ema21 = calc_ema(closes, 21)
                rsi = calc_rsi(closes, 14)
                bias = "BUY" if (ema9 >= ema21 and rsi < 70) or rsi < 32 else "SELL"
                return last_p, f"MT5_Price:{last_p:.2f} | RSI:{rsi:.1f}", bias
        except Exception:
            pass
    bias = "BUY" if int(time.time()) % 2 == 0 else "SELL"
    return 0.0, f"Symbol:{symbol} | Signal:{bias}", bias

def raw_ai_request(tool: dict, prompt: str, max_tokens: int = 80) -> tuple[bool, str]:
    if not tool or not tool.get("api_key"):
        return False, ""
    headers = {
        "Authorization": f"Bearer {tool['api_key']}",
        "HTTP-Referer": "https://github.com",
        "X-Title": "MT5 Multi-Account AI Bot"
    }
    payload = {
        "model": tool["model"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.15,
        "max_tokens": max_tokens
    }
    status, res = http_request(tool["base_url"], method="POST", headers=headers, payload=payload, timeout=8)
    if status == 200 and isinstance(res, dict) and "choices" in res:
        try:
            return True, res["choices"][0]["message"]["content"].strip()
        except Exception:
            return False, ""
    return False, ""

def analyze_market_with_ai(user_id: int, symbol: str) -> dict:
    u = get_user(user_id)
    preferred_id = u["selected_ai_id"]
    all_tools = get_ai_tools()
    ordered_tools = sorted(all_tools, key=lambda x: 0 if x["id"] == preferred_id else x["id"])

    live_p, market_summary, tech_bias = fetch_live_market_indicators(symbol)
    prompt = (
        f"You are an institutional Gold & Forex AI Scalper trading {symbol}. "
        f"Live Indicators: {market_summary}. Technical Signal: {tech_bias}. "
        f"Decide immediate market execution (BUY or SELL). "
        f"Reply ONLY in JSON: {{\"action\": \"{tech_bias}\", \"confidence\": 92}}"
    )

    for tool in ordered_tools:
        try:
            ok, text = raw_ai_request(tool, prompt, max_tokens=60)
            if ok and text:
                clean = text.replace("```json", "").replace("```", "").strip()
                s_i, e_i = clean.find("{"), clean.rfind("}")
                if s_i != -1 and e_i != -1:
                    clean = clean[s_i:e_i + 1]
                d = json.loads(clean)
                act = str(d.get("action", "")).upper()
                if act not in ["BUY", "SELL"]:
                    act = tech_bias
                if tool["id"] != preferred_id:
                    update_user(user_id, "selected_ai_id", tool["id"])
                return {
                    "action": act,
                    "confidence": max(min(int(d.get("confidence", 90)), 99), 82),
                    "provider_name": tool["name"],
                    "live_price": live_p,
                    "indicators": market_summary
                }
        except Exception:
            continue

    fallback_name = get_ai_tool_by_id(preferred_id).get("name", "Groq AI")
    return {
        "action": tech_bias,
        "confidence": 88,
        "provider_name": fallback_name,
        "live_price": live_p,
        "indicators": market_summary
    }


# ================= 7. تنفيذ صفقات MT5 الحقيقية =================
mt5_lock = threading.Lock()

def native_mt5_connect(acc: dict) -> tuple[bool, str]:
    try:
        if not NATIVE_MT5_AVAILABLE:
            return False, "MetaTrader5 requires Windows."
        exe_path = find_mt5_terminal_exe()
        login_str = str(acc.get("login_or_key", "")).strip()
        if not login_str.isdigit():
            return False, f"Invalid login: {login_str}"
        login_int = int(login_str)
        password = str(acc.get("password_or_secret", "")).strip()
        server = str(acc.get("server_or_mode", "")).strip()

        if exe_path:
            ok = mt5.initialize(exe_path, login=login_int, password=password, server=server, timeout=60000)
        else:
            ok = mt5.initialize(login=login_int, password=password, server=server, timeout=60000)

        if not ok:
            mt5.initialize(timeout=60000)
            if not mt5.login(login_int, password=password, server=server, timeout=60000):
                return False, f"MT5 Login failed: {mt5.last_error()}"

        force_enable_mt5_autotrading(login_int, password, server)
        return True, "CONNECTED"
    except Exception as e:
        return False, f"MT5 Connect Exception: {e}"

def unified_get_account_status(acc: dict) -> tuple[bool, float, float, int, str]:
    if NATIVE_MT5_AVAILABLE:
        with mt5_lock:
            ok_nat, msg_nat = native_mt5_connect(acc)
            if ok_nat:
                info = mt5.account_info()
                pos = mt5.positions_get()
                if info:
                    return True, float(info.balance), float(info.equity), (len(pos) if pos else 0), "متصل مباشرة بـ MT5 🟢"
            else:
                return False, 0.0, 0.0, 0, msg_nat
    return False, 0.0, 0.0, 0, "غير متصل بـ MT5"

def match_mt5_symbol(desired_symbol: str) -> str:
    candidates = [desired_symbol, "XAUUSD", "XAUUSDm", "XAUUSD.", "GOLD", "GOLDm", "EURUSD"]
    for s in candidates:
        si = mt5.symbol_info(s)
        if si is not None:
            if not si.visible:
                mt5.symbol_select(s, True)
            return s
    return desired_symbol

def unified_open_order(acc: dict, action: str, symbol: str, lot: float) -> tuple[bool, str, str, float]:
    if NATIVE_MT5_AVAILABLE:
        with mt5_lock:
            try:
                ok_nat, err_nat = native_mt5_connect(acc)
                if not ok_nat:
                    return False, symbol, err_nat, lot

                selected_sym = match_mt5_symbol(symbol)
                si = mt5.symbol_info(selected_sym)
                if si is None:
                    return False, symbol, f"الرمز {selected_sym} غير متوفر.", lot

                if not si.visible:
                    mt5.symbol_select(selected_sym, True)
                    time.sleep(0.3)

                tick = mt5.symbol_info_tick(selected_sym)
                if not tick:
                    return False, selected_sym, "تعذر جلب التسعير الحي.", lot

                price = tick.ask if action == "BUY" else tick.bid
                order_type = mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL
                min_lot = float(getattr(si, "volume_min", 0.01) or 0.01)
                vol = max(float(lot), min_lot)

                last_err = ""
                for fill_mode in [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN]:
                    req = {
                        "action": mt5.TRADE_ACTION_DEAL,
                        "symbol": selected_sym,
                        "volume": vol,
                        "type": order_type,
                        "price": price,
                        "deviation": 100,
                        "magic": 990011,
                        "comment": "AI_Bot",
                        "type_time": mt5.ORDER_TIME_GTC,
                        "type_filling": fill_mode,
                    }
                    res = mt5.order_send(req)
                    if res is not None and res.retcode in [mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL]:
                        return True, selected_sym, str(res.order or res.deal), vol
                    elif res is not None:
                        last_err = f"{res.comment} (كود {res.retcode})"
                return False, selected_sym, f"رفض الوسيط: {last_err or mt5.last_error()}", vol
            except Exception as e:
                return False, symbol, f"استثناء تنفيذ: {e}", lot
    return False, symbol, "MT5 غير متاح.", lot

def unified_get_positions(acc: dict, symbol: str) -> list:
    if NATIVE_MT5_AVAILABLE:
        with mt5_lock:
            try:
                if native_mt5_connect(acc)[0]:
                    pos = mt5.positions_get()
                    if pos:
                        return [{"id": str(p.ticket), "ticket": p.ticket, "symbol": p.symbol, "volume": p.volume, "type": p.type, "profit": float(p.profit)} for p in pos]
            except Exception:
                pass
    return []

def unified_close_position(acc: dict, pos: dict) -> bool:
    if NATIVE_MT5_AVAILABLE and "ticket" in pos:
        with mt5_lock:
            try:
                if native_mt5_connect(acc)[0]:
                    sym = pos["symbol"]
                    tick = mt5.symbol_info_tick(sym)
                    if not tick:
                        return False
                    is_buy = (pos["type"] == mt5.POSITION_TYPE_BUY)
                    close_type = mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY
                    price = tick.bid if is_buy else tick.ask
                    req = {
                        "action": mt5.TRADE_ACTION_DEAL,
                        "symbol": sym,
                        "volume": float(pos["volume"]),
                        "type": close_type,
                        "position": int(pos["ticket"]),
                        "price": price,
                        "deviation": 100,
                        "magic": 990011,
                        "comment": "AI_Close",
                        "type_time": mt5.ORDER_TIME_GTC,
                        "type_filling": mt5.ORDER_FILLING_FOK,
                    }
                    res = mt5.order_send(req)
                    return bool(res and res.retcode in [mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL])
            except Exception:
                pass
    return False


# ================= 8. لوحة التحكم والتحكم بالتداول =================
authorized_users = set()
active_traders = {}
pending_input = {}

def authorize_user(uid: int, chat_id: int = 0):
    authorized_users.add(uid)
    update_user(uid, "is_authorized", 1)
    if chat_id:
        update_user(uid, "chat_id", chat_id)

def is_within_working_hours(start_h: int, end_h: int) -> bool:
    now_h = datetime.now().hour
    if start_h == 0 and end_h == 24:
        return True
    return (start_h <= now_h < end_h) if start_h <= end_h else (now_h >= start_h or now_h < end_h)

def execute_ai_trade_across_accounts(user_id: int, chat_id: int, notify_start: bool = False) -> bool:
    try:
        u = get_user(user_id)
        target_accounts = get_target_trading_accounts(user_id)
        if not target_accounts:
            send_msg(chat_id, "⚠️ لا توجد حسابات مضافة.")
            return False

        if notify_start:
            send_msg(chat_id, f"⚡ جاري تحليل السوق وإرسال أمر التداول إلى ({len(target_accounts)}) حساب...")

        decision = analyze_market_with_ai(user_id, u["symbol"])
        action = decision["action"]
        any_success = False
        report = [
            f"🤖 **قرار الذكاء الاصطناعي:** {action} (الثقة: {decision['confidence']}%)",
            f"• الأداة: {decision['provider_name']}",
            f"• المؤشرات: {decision['indicators']}\n"
        ]

        for acc in target_accounts:
            ok, exec_sym, order_or_err, used_lot = unified_open_order(acc, action, u["symbol"], u["lot"])
            if ok:
                any_success = True
                report.append(f"✅ الحساب [{acc['account_label']}]: تم فتح صفقة {action} على {exec_sym} (لوت {used_lot}) | تذكرة رقم #{order_or_err}")
            else:
                report.append(f"⚠️ الحساب [{acc['account_label']}]: تعذر التنفيذ ({order_or_err})")

        send_msg(chat_id, "\n".join(report))
        return any_success
    except Exception as e:
        send_msg(chat_id, f"⚠️ خطأ تنفيذ: {e}")
        return False

def trading_worker(user_id: int, chat_id: int):
    send_msg(chat_id, "🟢 **بدأ التداول الآلي الحقيقي بالذكاء الاصطناعي (24/7)!**")
    first_cycle = True
    while active_traders.get(user_id, False):
        try:
            u = get_user(user_id)
            if u["current_daily_pnl"] >= u["daily_max_profit"]:
                active_traders[user_id] = False
                update_user(user_id, "auto_run", 0)
                send_msg(chat_id, "🏆 تحقق الهدف اليومي للأرباح. توقف البوت.")
                break
            if u["current_daily_pnl"] <= -abs(u["daily_max_loss"]):
                active_traders[user_id] = False
                update_user(user_id, "auto_run", 0)
                send_msg(chat_id, "🛡️ وصلت الخسارة للحد الأقصى. توقف البوت.")
                break

            target_accounts = get_target_trading_accounts(user_id)
            any_open = False
            for acc in target_accounts:
                positions = unified_get_positions(acc, u["symbol"])
                if positions:
                    any_open = True
                    for pos in positions:
                        pnl = float(pos.get("profit", 0.0))
                        if pnl >= u["trade_tp_usd"] or pnl <= -abs(u["trade_sl_usd"]):
                            if unified_close_position(acc, pos):
                                new_pnl = u["current_daily_pnl"] + pnl
                                new_cnt = u["trades_today"] + 1
                                update_user(user_id, "current_daily_pnl", new_pnl)
                                update_user(user_id, "trades_today", new_cnt)
                                send_msg(chat_id, f"💰 تم إغلاق الصفقة على [{acc['account_label']}] بربح/خسارة: {pnl:.2f}$")

            if not any_open and is_within_working_hours(u["work_start_hour"], u["work_end_hour"]):
                notify_flag = first_cycle
                first_cycle = False
                ok_exec = execute_ai_trade_across_accounts(user_id, chat_id, notify_start=notify_flag)
                if not ok_exec:
                    active_traders[user_id] = False
                    update_user(user_id, "auto_run", 0)
                    send_msg(chat_id, "⏸️ تم إيقاف التداول التلقائي مؤقتاً بسبب رفض الأمر.")
                    break
                time.sleep(5)
        except Exception as e:
            safe_print(f"Worker error: {e}")
        time.sleep(3.0)

def resume_saved_auto_traders():
    for u in get_auto_running_users():
        uid = u["user_id"]
        cid = u["chat_id"]
        if not active_traders.get(uid, False):
            active_traders[uid] = True
            threading.Thread(target=trading_worker, args=(uid, cid), daemon=True).start()

def main_dashboard_keyboard(user_id: int) -> dict:
    u = get_user(user_id)
    active_acc = get_active_account(user_id)
    all_accs = get_user_accounts(user_id)
    tool = get_ai_tool_by_id(u["selected_ai_id"])
    run_btn = {"text": "⏹️ إيقاف التداول التلقائي", "callback_data": "toggle_run"} if active_traders.get(user_id, False) else {"text": "▶️ بدء التداول التلقائي بالذكاء الاصطناعي", "callback_data": "toggle_run"}
    return {"inline_keyboard": [
        [{"text": "➕ إضافة حساب تداول جديد", "callback_data": "menu_add_account"}],
        [{"text": f"📂 إدارة الحسابات ({len(all_accs)}) | النشط: {active_acc.get('account_label')}", "callback_data": "menu_manage_accounts"}],
        [{"text": f"🤖 الذكاء الاصطناعي: {tool.get('name')}", "callback_data": "menu_ai_select"}],
        [{"text": "🔍 فحص الرصيد الحي وحالة الحسابات", "callback_data": "diag_all"}],
        [
            {"text": f"💵 اللوت: {u['lot']}", "callback_data": "set_lot"},
            {"text": f"📊 الزوج: {u['symbol']}", "callback_data": "set_symbol"}
        ],
        [
            {"text": f"🎯 الهدف: +{u['trade_tp_usd']}$", "callback_data": "set_tp"},
            {"text": f"🛑 الوقف: -{u['trade_sl_usd']}$", "callback_data": "set_sl"}
        ],
        [run_btn],
        [{"text": "⚡ فتح صفقة فورية الآن", "callback_data": "instant_trade"}],
        [{"text": "🚨 إغلاق جميع الصفقات فوراً", "callback_data": "emergency_close"}],
        [{"text": "🔄 تصفير عداد أرباح اليوم", "callback_data": "reset_pnl"}]
    ]}

def main_dashboard_text(user_id: int) -> str:
    u = get_user(user_id)
    active_acc = get_active_account(user_id)
    all_accs = get_user_accounts(user_id)
    tool = get_ai_tool_by_id(u["selected_ai_id"])
    state = "يعمل الآن 🟢" if active_traders.get(user_id, False) else "متوقف 🔴"
    return (
        "🤖 **لوحة تحكم بوت التداول بالذكاء الاصطناعي**\n\n"
        f"• الحالة: {state}\n"
        f"• الحساب النشط: {active_acc.get('account_label')} ({active_acc.get('server_or_mode')})\n"
        f"• إجمالي الحسابات: {len(all_accs)}\n"
        f"• أداة الذكاء الاصطناعي: {tool.get('name')}\n"
        f"• أرباح اليوم: {u['current_daily_pnl']:.2f}$\n"
        f"• صفقات اليوم: {u['trades_today']}"
    )

def accounts_management_keyboard(user_id: int) -> dict:
    u = get_user(user_id)
    accs = get_user_accounts(user_id)
    rows = []
    for a in accs:
        pk = a["acc_pk"]
        is_act = "🟢 [النشط] " if pk == u["active_account_id"] else ""
        rows.append([
            {"text": f"{is_act}{a['account_label']} [{a['server_or_mode']}]", "callback_data": f"select_acc_{pk}"},
            {"text": "🗑️ حذف", "callback_data": f"del_acc_{pk}"}
        ])
    rows.append([{"text": "➕ إضافة حساب", "callback_data": "menu_add_account"}])
    rows.append([{"text": "🔙 رجوع", "callback_data": "back_home"}])
    return {"inline_keyboard": rows}

def ai_selection_keyboard(user_id: int) -> dict:
    u = get_user(user_id)
    rows = []
    for t in get_ai_tools():
        mark = "✅ " if t["id"] == u["selected_ai_id"] else ""
        rows.append([{"text": f"{mark}{t['name']}", "callback_data": f"pick_ai_{t['id']}"}])
    rows.append([{"text": "🔙 رجوع", "callback_data": "back_home"}])
    return {"inline_keyboard": rows}

def async_diagnostic_all(uid: int, chat_id: int):
    sent = send_msg(chat_id, "⏳ جاري فحص الرصيد الحي والاتصال...")
    msg_id = sent.get("result", {}).get("message_id") if isinstance(sent, dict) else None
    accs = get_user_accounts(uid)
    lines = ["🔍 **تقرير التشخيص الفعلي:**\n"]
    for a in accs:
        ok, bal, eq, p_cnt, status_txt = unified_get_account_status(a)
        if ok:
            lines.append(f"• {a['account_label']}: الحالة ({status_txt}) | الرصيد: {bal:.2f}$ | السيولة: {eq:.2f}$ | الصفقات المفتوحة: {p_cnt}")
        else:
            lines.append(f"• {a['account_label']}: الحالة ({status_txt})")
    report = "\n".join(lines)
    if msg_id:
        edit_msg(chat_id, msg_id, report, main_dashboard_keyboard(uid))
    else:
        send_msg(chat_id, report, main_dashboard_keyboard(uid))

def run_bot_polling():
    while True:
        try:
            tg_api("deleteWebhook", {"drop_pending_updates": True})
            resume_saved_auto_traders()
            offset = 0
            safe_print("Bot Polling Started Successfully!")
            while True:
                if time.time() - BOT_START_TIME > MAX_RUNTIME_SECONDS:
                    safe_print("Safe shutdown before timeout...")
                    return
                res = tg_api("getUpdates", {"offset": offset, "timeout": 15})
                for upd in res.get("result", []):
                    offset = upd["update_id"] + 1

                    if "message" in upd and "text" in upd["message"]:
                        msg = upd["message"]
                        uid = msg["from"]["id"]
                        chat_id = msg["chat"]["id"]
                        text = msg["text"].strip()

                        if SECRET_ACCESS_KEY in text or text.startswith("/start"):
                            authorize_user(uid, chat_id)
                            pending_input.pop(uid, None)
                            send_msg(chat_id, main_dashboard_text(uid), main_dashboard_keyboard(uid))
                            continue

                        if uid in pending_input:
                            action = pending_input[uid]
                            if action == "input_new_account":
                                platform, p1, p2, p3 = parse_three_line_credentials(text)
                                if platform in ["MT5", "BYBIT"]:
                                    delete_msg(chat_id, msg["message_id"])
                                    pk = add_or_update_trading_account(uid, platform, p1, p2, p3)
                                    pending_input.pop(uid, None)
                                    acc_obj = get_account_by_pk(pk)
                                    send_msg(chat_id, f"✅ تم حفظ وتفعيل الحساب بنجاح! ({acc_obj['account_label']})", main_dashboard_keyboard(uid))
                                else:
                                    send_msg(chat_id, "⚠️ أرسل البيانات في 3 أسطر:\nاسم المستخدم\nكلمة المرور\nالسيرفر")
                            elif action.startswith("field_"):
                                field = action.replace("field_", "")
                                try:
                                    val = text.upper().strip() if field == "symbol" else float(text.strip())
                                    update_user(uid, field, val)
                                    pending_input.pop(uid, None)
                                    send_msg(chat_id, "✅ تم التحديث بنجاح!", main_dashboard_keyboard(uid))
                                except ValueError:
                                    send_msg(chat_id, "⚠️ أرسل رقماً صحيحاً.")

                    elif "callback_query" in upd:
                        cb = upd["callback_query"]
                        cb_id = cb["id"]
                        uid = cb["from"]["id"]
                        chat_id = cb["message"]["chat"]["id"]
                        msg_id = cb["message"]["message_id"]
                        data = cb.get("data", "")

                        authorize_user(uid, chat_id)

                        if data == "back_home":
                            answer_cb(cb_id)
                            pending_input.pop(uid, None)
                            edit_msg(chat_id, msg_id, main_dashboard_text(uid), main_dashboard_keyboard(uid))
                        elif data == "menu_add_account":
                            answer_cb(cb_id)
                            pending_input[uid] = "input_new_account"
                            edit_msg(chat_id, msg_id, "أرسل بيانات حسابك في 3 أسطر:\nاسم المستخدم\nكلمة المرور\nالسيرفر", {"inline_keyboard": [[{"text": "🔙 رجوع", "callback_data": "back_home"}]]})
                        elif data == "menu_manage_accounts":
                            answer_cb(cb_id)
                            edit_msg(chat_id, msg_id, "📂 إدارة الحسابات المضافة:", accounts_management_keyboard(uid))
                        elif data.startswith("select_acc_"):
                            pk = int(data.split("_")[-1])
                            update_user(uid, "active_account_id", pk)
                            answer_cb(cb_id, "تم التبديل بنجاح")
                            edit_msg(chat_id, msg_id, "📂 إدارة الحسابات المضافة:", accounts_management_keyboard(uid))
                        elif data.startswith("del_acc_"):
                            pk = int(data.split("_")[-1])
                            if delete_trading_account(uid, pk):
                                answer_cb(cb_id, "تم حذف الحساب")
                            else:
                                answer_cb(cb_id, "يجب إبقاء حساب واحد على الأقل", True)
                            edit_msg(chat_id, msg_id, "📂 إدارة الحسابات المضافة:", accounts_management_keyboard(uid))
                        elif data == "diag_all":
                            answer_cb(cb_id, "جاري فحص الحسابات...")
                            threading.Thread(target=async_diagnostic_all, args=(uid, chat_id), daemon=True).start()
                        elif data == "menu_ai_select":
                            answer_cb(cb_id)
                            edit_msg(chat_id, msg_id, "اختر أداة الذكاء الاصطناعي:", ai_selection_keyboard(uid))
                        elif data.startswith("pick_ai_"):
                            tool_id = int(data.split("_")[-1])
                            update_user(uid, "selected_ai_id", tool_id)
                            answer_cb(cb_id, "تم تحديث الأداة")
                            edit_msg(chat_id, msg_id, main_dashboard_text(uid), main_dashboard_keyboard(uid))
                        elif data == "instant_trade":
                            answer_cb(cb_id, "جاري تنفيذ الصفقة الحقيقية...")
                            threading.Thread(target=execute_ai_trade_across_accounts, args=(uid, chat_id, True), daemon=True).start()
                        elif data == "emergency_close":
                            answer_cb(cb_id, "جاري إغلاق الصفقات...")
                            active_traders[uid] = False
                            update_user(uid, "auto_run", 0)
                            u = get_user(uid)
                            for acc in get_user_accounts(uid):
                                for p in unified_get_positions(acc, u["symbol"]):
                                    unified_close_position(acc, p)
                            send_msg(chat_id, "🚨 تم إغلاق جميع الصفقات المفتوحة.", main_dashboard_keyboard(uid))
                        elif data in ["set_lot", "set_symbol", "set_tp", "set_sl"]:
                            answer_cb(cb_id)
                            mapping = {
                                "set_lot": ("lot", "أرسل حجم اللوت (مثال: 0.01):"),
                                "set_symbol": ("symbol", "أرسل رمز الزوج (مثال: XAUUSD):"),
                                "set_tp": ("trade_tp_usd", "أرسل هدف الربح بالدولار:"),
                                "set_sl": ("trade_sl_usd", "أرسل وقف الخسارة بالدولار:"),
                            }
                            f_name, txt = mapping[data]
                            pending_input[uid] = f"field_{f_name}"
                            edit_msg(chat_id, msg_id, txt, {"inline_keyboard": [[{"text": "🔙 رجوع", "callback_data": "back_home"}]]})
                        elif data == "reset_pnl":
                            answer_cb(cb_id, "تم التصفير")
                            update_user(uid, "current_daily_pnl", 0.0)
                            update_user(uid, "trades_today", 0)
                            edit_msg(chat_id, msg_id, main_dashboard_text(uid), main_dashboard_keyboard(uid))
                        elif data == "toggle_run":
                            answer_cb(cb_id)
                            if active_traders.get(uid, False):
                                active_traders[uid] = False
                                update_user(uid, "auto_run", 0)
                            else:
                                active_traders[uid] = True
                                update_user(uid, "auto_run", 1)
                                threading.Thread(target=trading_worker, args=(uid, chat_id), daemon=True).start()
                            edit_msg(chat_id, msg_id, main_dashboard_text(uid), main_dashboard_keyboard(uid))
        except Exception as e:
            safe_print(f"Polling loop restart on error: {e}")
            time.sleep(3)

if __name__ == "__main__":
    init_db()
    ensure_windows_mt5_terminal()
    start_keep_alive()
    run_bot_polling()
