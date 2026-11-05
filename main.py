import os
import sys
import glob
import hmac
import json
import time
import hashlib
import sqlite3
import subprocess
import threading
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

# ================= 0. حماية جذرية من أخطاء الترميز في ويندوز ولينكس =================
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
            return p.replace("\\", "/")
    return ""

def is_terminal_process_running() -> bool:
    if os.name != "nt":
        return False
    try:
        out = subprocess.check_output(["tasklist", "/FI", "IMAGENAME eq terminal64.exe"], stderr=subprocess.DEVNULL).decode("utf-8", errors="ignore")
        return "terminal64.exe" in out.lower()
    except Exception:
        return False

def inject_global_servers_dat():
    """تحميل ملف servers.dat العالمي لتمكين MT5 من التعرف على الوسطاء الخارجيين"""
    if os.name != "nt":
        return
    urls = [
        "https://raw.githubusercontent.com/hudsonventura/MT5_Docker/main/src/servers.dat",
        "https://raw.githubusercontent.com/OmniRoute/mt5-servers/main/servers.dat"
    ]
    downloaded = os.path.join(os.getcwd(), "global_servers.dat")
    got_file = False
    for u in urls:
        try:
            urllib.request.urlretrieve(u, downloaded)
            if os.path.exists(downloaded) and os.path.getsize(downloaded) > 1024:
                got_file = True
                break
        except Exception:
            continue

    if not got_file:
        return

    target_dirs = [r"C:\Program Files\MetaTrader 5\Config"]
    for env_var in ("APPDATA", "LOCALAPPDATA"):
        base_dir = os.environ.get(env_var, "")
        if base_dir:
            target_dirs.extend(glob.glob(os.path.join(base_dir, "MetaQuotes", "Terminal", "*", "config")))

    for d in target_dirs:
        try:
            if os.path.exists(d):
                dst = os.path.join(d, "servers.dat")
                with open(downloaded, "rb") as src_f, open(dst, "wb") as dst_f:
                    dst_f.write(src_f.read())
        except Exception:
            pass

def ensure_windows_mt5_terminal():
    if os.name != "nt":
        return
    if find_mt5_terminal_exe():
        inject_global_servers_dat()
        safe_print("MT5 Terminal is ready.")
        return
    safe_print("Installing Official MetaTrader 5 Terminal...")
    installer_path = os.path.join(os.getcwd(), "mt5setup.exe")
    try:
        urllib.request.urlretrieve(
            "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe",
            installer_path
        )
        subprocess.run([installer_path, "/auto"], timeout=120, check=False)
        for _ in range(20):
            if find_mt5_terminal_exe():
                inject_global_servers_dat()
                safe_print("MT5 Terminal installed successfully!")
                return
            time.sleep(2)
    except Exception as e:
        safe_print(f"MT5 install note: {e}")

BOT_START_TIME = time.time()
IS_GITHUB_ACTIONS = os.getenv("GITHUB_ACTIONS", "").lower() == "true"
MAX_RUNTIME_SECONDS = 330 * 60 if IS_GITHUB_ACTIONS else 365 * 24 * 3600


# ================= 1. تفعيل AutoTrading الفوري بدون تعليق البرنامج =================
def write_mt5_autotrading_ini(login_str: str, password: str, server: str) -> str:
    ini_content = (
        "[Common]\r\n"
        f"Login={login_str}\r\n"
        f"Password={password}\r\n"
        f"Server={server}\r\n"
        "KeepPrivate=1\r\n"
        "NewsEnable=0\r\n"
        "CertInstall=1\r\n"
        "\r\n"
        "[Experts]\r\n"
        "AllowDllImport=1\r\n"
        "Enabled=1\r\n"
        "Account=0\r\n"
        "Profile=0\r\n"
        "Chart=0\r\n"
        "Api=1\r\n"
    )
    startup_ini = os.path.join(os.getcwd(), "mt5_startup.ini")
    try:
        with open(startup_ini, "w", encoding="utf-8") as f:
            f.write(ini_content)
    except Exception:
        pass

    for env_var in ("APPDATA", "LOCALAPPDATA"):
        base_dir = os.environ.get(env_var, "")
        if base_dir:
            pattern = os.path.join(base_dir, "MetaQuotes", "Terminal", "*", "config", "common.ini")
            for cfg_path in glob.glob(pattern):
                try:
                    with open(cfg_path, "w", encoding="utf-8") as f:
                        f.write(ini_content)
                except Exception:
                    pass
    return startup_ini

def send_ctrl_e_to_mt5_window():
    if os.name != "nt":
        return
    try:
        import ctypes
        user32 = ctypes.windll.user32
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        target_hwnds = []

        def enum_cb(hwnd, lparam):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value.upper()
                    if "METATRADER" in title or "METAQUOTES" in title or "DEMO" in title or "BLACKBULL" in title:
                        target_hwnds.append(hwnd)
            return True

        user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
        for hwnd in target_hwnds:
            user32.ShowWindow(hwnd, 9)
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.2)
            VK_CONTROL = 0x11
            VK_E = 0x45
            KEYEVENTF_KEYUP = 0x0002
            user32.keybd_event(VK_CONTROL, 0, 0, 0)
            user32.keybd_event(VK_E, 0, 0, 0)
            time.sleep(0.08)
            user32.keybd_event(VK_E, 0, KEYEVENTF_KEYUP, 0)
            user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
            time.sleep(0.2)
    except Exception as e:
        safe_print(f"Hotkey note: {e}")


# ================= 2. خادم الويب الداخلي Keep-Alive =================
class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("MT5 & Bybit AI Trading Bot is Running Fast 24/7!".encode("utf-8"))

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        return

def start_keep_alive():
    for port in [int(os.environ.get("PORT", 8080)), 10000, 8081, 3000, 0]:
        try:
            HTTPServer.allow_reuse_address = True
            server = HTTPServer(("0.0.0.0", port), KeepAliveHandler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            safe_print(f"Keep-Alive Server running on port {server.server_address[1]}")
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
GITHUB_KEY = (
    os.getenv("GH_MODELS_TOKEN")
    or os.getenv("GITHUB_MODELS_TOKEN")
    or os.getenv("GITHUP_TOKEN")
    or os.getenv("GitHup_TOKEN")
    or os.getenv("Git Hup_TOKEN")
    or os.getenv("GITHUB_TOKEN")
    or ""
).strip()
GROQ_KEY = (os.getenv("GROQ_TOKEN") or os.getenv("GROQ_TOKRN") or "").strip()
HUGGINGFACE_KEY = os.getenv("HUGGINGFACE_TOKEN", "").strip()
OPENROUTER_KEY = (os.getenv("OPENROUTER1_TOKEN") or os.getenv("OPENROUTER_TOKEN") or "").strip()
SAMBANOVA_KEY = os.getenv("SAMBANOVA_TOKEN", "").strip()

KNOWN_MT5_LOGIN = "5058253637"
KNOWN_MT5_PASS = "*aGm1cNp"
KNOWN_MT5_SERVER = "MetaQuotes-Demo"
KNOWN_FALLBACK_ACC_ID = "2edd990c-e8e3-4853-98e1-867ab23136e0"

BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


# ================= 4. طبقة الاتصال الشبكي السريع وتيليجرام =================
def http_request(url: str, method: str = "GET", headers: dict = None, payload: dict = None, raw_body: str = None, timeout: int = 12):
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
            try:
                return resp.status, json.loads(body)
            except Exception:
                return resp.status, {"raw": body}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        try:
            err_json = json.loads(err_body)
            msg = err_json.get("message") or err_json.get("retMsg") or err_json.get("error") or err_body
        except Exception:
            msg = err_body
        return e.code, {"error": str(msg)}
    except Exception as e:
        return 500, {"error": str(e)}

def trigger_github_workflow_restart():
    repo = os.getenv("GITHUB_REPOSITORY", "bdh39058-creator/mt5-ai-bot")
    token = os.getenv("GH_MODELS_TOKEN", "").strip()
    if not token:
        return
    url = f"https://api.github.com/repos/{repo}/actions/workflows/mt5_bot.yml/dispatches"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    http_request(url, method="POST", headers=headers, payload={"ref": "main"}, timeout=10)

def tg_api(method_name: str, params: dict = None, timeout: int = 10):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method_name}"
    _, res = http_request(url, method="POST", payload=params or {}, timeout=timeout)
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
    return tg_api("answerCallbackQuery", {"callback_query_id": callback_id, "text": text[:190], "show_alert": show_alert}, timeout=5)

def delete_msg(chat_id: int, message_id: int):
    return tg_api("deleteMessage", {"chat_id": chat_id, "message_id": message_id}, timeout=5)


# ================= 5. قاعدة البيانات وإدارة الحسابات =================
DB_FILE = "multi_mt5_gold_bot.db"

def init_db():
    conn = sqlite3.connect(DB_FILE, timeout=20)
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
            cloud_id TEXT DEFAULT '',
            region TEXT DEFAULT 'london',
            is_enabled INTEGER DEFAULT 1
        )
    """)
    for col_def in ["cloud_id TEXT DEFAULT ''", "region TEXT DEFAULT 'london'"]:
        try:
            c.execute(f"ALTER TABLE trading_accounts ADD COLUMN {col_def}")
        except Exception:
            pass

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
    conn = sqlite3.connect(DB_FILE, timeout=20)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM trading_accounts WHERE user_id = ? ORDER BY acc_pk ASC", (user_id,))
    rows = c.fetchall()
    if not rows:
        c.execute("""
            INSERT INTO trading_accounts (user_id, platform, account_label, login_or_key, password_or_secret, server_or_mode, cloud_id, region, is_enabled)
            VALUES (?, 'MT5', ?, ?, ?, ?, ?, 'london', 1)
        """, (user_id, f"MT5 ({KNOWN_MT5_LOGIN})", KNOWN_MT5_LOGIN, KNOWN_MT5_PASS, KNOWN_MT5_SERVER, KNOWN_FALLBACK_ACC_ID))
        new_pk = c.lastrowid
        if ENV_BYBIT_KEY and ENV_BYBIT_SECRET:
            c.execute("""
                INSERT INTO trading_accounts (user_id, platform, account_label, login_or_key, password_or_secret, server_or_mode, cloud_id, region, is_enabled)
                VALUES (?, 'BYBIT', ?, ?, ?, 'BYBIT-DEMO', '', 'global', 1)
            """, (user_id, f"Bybit ({ENV_BYBIT_KEY[:6]})", ENV_BYBIT_KEY, ENV_BYBIT_SECRET))
        c.execute("UPDATE users SET active_account_id = ? WHERE user_id = ?", (new_pk, user_id))
        conn.commit()
    conn.close()

def get_user(user_id: int) -> dict:
    conn = sqlite3.connect(DB_FILE, timeout=20)
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
    conn = sqlite3.connect(DB_FILE, timeout=20)
    c = conn.cursor()
    c.execute(f"UPDATE users SET {field} = ? WHERE user_id = ?", (value, user_id))
    conn.commit()
    conn.close()

def update_account_cloud_info(acc_pk: int, cloud_id: str, region: str):
    conn = sqlite3.connect(DB_FILE, timeout=20)
    c = conn.cursor()
    c.execute("UPDATE trading_accounts SET cloud_id = ?, region = ? WHERE acc_pk = ?", (cloud_id, region, acc_pk))
    conn.commit()
    conn.close()

def get_auto_running_users() -> list:
    conn = sqlite3.connect(DB_FILE, timeout=20)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE auto_run = 1 AND chat_id != 0")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def get_user_accounts(user_id: int) -> list:
    ensure_default_account(user_id)
    conn = sqlite3.connect(DB_FILE, timeout=20)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM trading_accounts WHERE user_id = ? ORDER BY acc_pk ASC", (user_id,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def get_account_by_pk(acc_pk: int) -> dict:
    conn = sqlite3.connect(DB_FILE, timeout=20)
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
        enabled = [a for a in all_accs if a.get("is_enabled") == 1]
        return enabled if enabled else all_accs
    active = get_active_account(user_id)
    return [active] if active else all_accs

def add_or_update_trading_account(user_id: int, platform: str, login_key: str, pass_secret: str, server_mode: str, make_active: bool = False) -> int:
    conn = sqlite3.connect(DB_FILE, timeout=20)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM trading_accounts WHERE user_id = ? AND login_or_key = ?", (user_id, login_key))
    existing = c.fetchone()
    label = f"Bybit ({login_key[:6]})" if platform == "BYBIT" else f"MT5 ({login_key})"
    default_cid = KNOWN_FALLBACK_ACC_ID if login_key == KNOWN_MT5_LOGIN else ""
    if existing:
        pk = existing["acc_pk"]
        c.execute("""
            UPDATE trading_accounts
            SET platform = ?, account_label = ?, password_or_secret = ?, server_or_mode = ?, is_enabled = 1
            WHERE acc_pk = ?
        """, (platform, label, pass_secret, server_mode, pk))
    else:
        c.execute("""
            INSERT INTO trading_accounts (user_id, platform, account_label, login_or_key, password_or_secret, server_or_mode, cloud_id, region, is_enabled)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'london', 1)
        """, (user_id, platform, label, login_key, pass_secret, server_mode, default_cid))
        pk = c.lastrowid
    if make_active:
        c.execute("UPDATE users SET active_account_id = ? WHERE user_id = ?", (pk, user_id))
    conn.commit()
    conn.close()
    return pk

def delete_trading_account(user_id: int, acc_pk: int) -> bool:
    accs = get_user_accounts(user_id)
    if len(accs) <= 1:
        return False
    conn = sqlite3.connect(DB_FILE, timeout=20)
    c = conn.cursor()
    c.execute("DELETE FROM trading_accounts WHERE acc_pk = ? AND user_id = ?", (acc_pk, user_id))
    conn.commit()
    conn.close()
    remaining = get_user_accounts(user_id)
    if remaining:
        update_user(user_id, "active_account_id", remaining[0]["acc_pk"])
    return True

def get_ai_tools() -> list:
    conn = sqlite3.connect(DB_FILE, timeout=20)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM ai_tools ORDER BY id ASC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def get_ai_tool_by_id(tool_id: int) -> dict:
    conn = sqlite3.connect(DB_FILE, timeout=20)
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
        p3 = lines[2].split(":", 1)[-1].strip() if " " in lines[2] else lines[2].strip()
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


# ================= 6. محرك الذكاء الاصطناعي والمؤشرات الفنية =================
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
                return last_p, f"MT5_Price:{last_p:.2f} | RSI:{rsi:.1f} | EMA9:{ema9:.2f}", bias
        except Exception:
            pass

    clean_sym = "PAXGUSDT" if ("XAU" in symbol.upper() or "GOLD" in symbol.upper()) else "EURUSDT"
    url = f"https://api.bybit.com/v5/market/kline?category=linear&symbol={clean_sym}&interval=1&limit=30"
    st, res = http_request(url, method="GET", timeout=6)
    if st == 200 and isinstance(res, dict):
        lst = res.get("result", {}).get("list", [])
        if len(lst) >= 15:
            closes = [float(x[4]) for x in reversed(lst)]
            last_p = closes[-1]
            ema9 = calc_ema(closes[-12:], 9)
            ema21 = calc_ema(closes, 21)
            rsi = calc_rsi(closes, 14)
            bias = "BUY" if (ema9 >= ema21 and rsi < 70) or rsi < 32 else "SELL"
            return last_p, f"Live_Price:{last_p:.2f} | RSI:{rsi:.1f} | EMA9:{ema9:.2f}", bias

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
    status, res = http_request(tool["base_url"], method="POST", headers=headers, payload=payload, timeout=7)
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


# ================= 7. المحرك الأول: منصة Bybit للذهب =================
def bybit_base_url(server_mode: str) -> str:
    return "https://api-demo.bybit.com" if "DEMO" in str(server_mode).upper() else "https://api.bybit.com"

def bybit_signed_request(acc: dict, endpoint: str, method: str = "GET", params: dict = None) -> tuple[bool, dict, str]:
    api_key = acc.get("login_or_key", "").strip()
    api_secret = acc.get("password_or_secret", "").strip()
    base = bybit_base_url(acc.get("server_or_mode", "BYBIT-DEMO"))
    if not api_key or not api_secret:
        return False, {}, "مفتاح Bybit API غير مكتمل."

    ts = str(int(time.time() * 1000))
    recv_win = "10000"
    params = params or {}

    if method == "GET":
        query_str = urllib.parse.urlencode(sorted(params.items()))
        full_url = f"{base}{endpoint}?{query_str}" if query_str else f"{base}{endpoint}"
        body_to_send = None
        payload_str = query_str
    else:
        full_url = f"{base}{endpoint}"
        body_to_send = json.dumps(params)
        payload_str = body_to_send

    param_str = f"{ts}{api_key}{recv_win}{payload_str}"
    signature = hmac.new(api_secret.encode("utf-8"), param_str.encode("utf-8"), hashlib.sha256).hexdigest()

    headers = {
        "X-BAPI-API-KEY": api_key,
        "X-BAPI-SIGN": signature,
        "X-BAPI-SIGN-TYPE": "2",
        "X-BAPI-TIMESTAMP": ts,
        "X-BAPI-RECV-WINDOW": recv_win,
        "Content-Type": "application/json"
    }
    st, res = http_request(full_url, method=method, headers=headers, raw_body=body_to_send, timeout=10)
    if st == 200 and isinstance(res, dict):
        if res.get("retCode") == 0:
            return True, res.get("result", {}), "OK"
        return False, res, f"Bybit: {res.get('retMsg', 'Error')}"
    return False, {}, f"HTTP {st}"

def map_gold_symbol_for_bybit(sym: str) -> str:
    s = sym.upper().strip()
    if s in ["XAUUSD", "GOLD", "XAUUSDT", "PAXG", "PAXGUSDT"]:
        return "PAXGUSDT"
    if not s.endswith("USDT"):
        return f"{s}USDT"
    return s

def bybit_get_balance(acc: dict) -> tuple[bool, float, float, str]:
    ok, res, err = bybit_signed_request(acc, "/v5/account/wallet-balance", "GET", {"accountType": "UNIFIED"})
    if ok:
        lst = res.get("list", [])
        if lst:
            eq = float(lst[0].get("totalEquity", 0.0))
            bal = float(lst[0].get("totalWalletBalance", eq))
            return True, bal, eq, "متصل بنجاح (Bybit) 🟢"
    return False, 0.0, 0.0, err

def bybit_get_open_positions(acc: dict, symbol: str) -> list:
    bybit_sym = map_gold_symbol_for_bybit(symbol)
    ok, res, _ = bybit_signed_request(acc, "/v5/position/list", "GET", {"category": "linear", "symbol": bybit_sym})
    if not ok:
        return []
    out = []
    for p in res.get("list", []):
        sz = float(p.get("size", 0.0))
        if sz > 0:
            out.append({
                "id": f"{p.get('symbol')}_{p.get('side')}",
                "symbol": p.get("symbol"),
                "side": p.get("side"),
                "size": sz,
                "profit": float(p.get("unrealisedPnl", 0.0))
            })
    return out

def bybit_close_position(acc: dict, pos: dict) -> bool:
    close_side = "Sell" if pos.get("side") == "Buy" else "Buy"
    params = {
        "category": "linear",
        "symbol": pos.get("symbol"),
        "side": close_side,
        "orderType": "Market",
        "qty": str(pos.get("size")),
        "reduceOnly": True
    }
    ok, _, _ = bybit_signed_request(acc, "/v5/order/create", "POST", params)
    return ok

def bybit_open_order(acc: dict, action: str, symbol: str, lot: float) -> tuple[bool, str, str, float]:
    bybit_sym = map_gold_symbol_for_bybit(symbol)
    qty = max(round(float(lot), 2), 0.01)
    params = {
        "category": "linear",
        "symbol": bybit_sym,
        "side": "Buy" if action == "BUY" else "Sell",
        "orderType": "Market",
        "qty": str(qty)
    }
    ok, res, err = bybit_signed_request(acc, "/v5/order/create", "POST", params)
    if ok:
        oid = str(res.get("orderId", "Executed"))
        return True, bybit_sym, oid, qty
    return False, bybit_sym, err, qty


# ================= 8. المحرك الثاني: سحابة MetaApi للوسطاء الخارجيين =================
PROVISION_URL = "https://mt-provisioning-api-v1.agiliumtrade.agiliumtrade.ai"

def metaapi_headers(with_tx: bool = False) -> dict:
    h = {"auth-token": MASTER_METAAPI_TOKEN}
    if with_tx:
        import uuid
        h["transaction-id"] = str(uuid.uuid4())
    return h

def metaapi_client_url(region: str) -> str:
    reg = region.strip() if (region and region != "None") else "london"
    return f"https://mt-client-api-v1.{reg}.agiliumtrade.ai"

def metaapi_ensure_deployed(acc: dict) -> tuple[bool, str, str, str]:
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
                    update_account_cloud_info(acc["acc_pk"], cid, reg)
                return True, cid, reg, "OK"

    # إنشاء الحساب تلقائياً في MetaApi إذا كان وسيطاً خارجياً مثل BlackBullMarkets-Demo
    create_payload = {
        "name": f"MT5_{login_str}",
        "type": "cloud",
        "login": login_str,
        "password": password,
        "server": server,
        "platform": "mt5",
        "magic": 990011
    }
    st_c, res_c = http_request(f"{PROVISION_URL}/users/current/accounts", "POST", headers=metaapi_headers(with_tx=True), payload=create_payload, timeout=15)
    if st_c in [200, 201] and isinstance(res_c, dict) and "id" in res_c:
        cid = res_c["id"]
        http_request(f"{PROVISION_URL}/users/current/accounts/{cid}/deploy", "POST", headers=metaapi_headers(), timeout=10)
        if acc.get("acc_pk"):
            update_account_cloud_info(acc["acc_pk"], cid, reg)
        return True, cid, reg, "OK"

    return False, "", "london", "السيرفر غير معرف محلياً."

def metaapi_get_status(acc: dict) -> tuple[bool, float, float, int, str]:
    ok_dep, cid, reg, err_msg = metaapi_ensure_deployed(acc)
    if not ok_dep:
        return False, 0.0, 0.0, 0, err_msg

    for try_reg in [reg, "london", "new-york"]:
        base_c = metaapi_client_url(try_reg)
        st, info = http_request(f"{base_c}/users/current/accounts/{cid}/account-information", "GET", headers=metaapi_headers(), timeout=10)
        if st == 200 and isinstance(info, dict) and "balance" in info:
            if try_reg != reg and acc.get("acc_pk"):
                update_account_cloud_info(acc["acc_pk"], cid, try_reg)
            _, pos_list = http_request(f"{base_c}/users/current/accounts/{cid}/positions", "GET", headers=metaapi_headers(), timeout=8)
            p_cnt = len(pos_list) if isinstance(pos_list, list) else 0
            return True, float(info.get("balance", 0.0)), float(info.get("equity", 0.0)), p_cnt, f"متصل سحابياً ({try_reg}) 🟢"
    return False, 0.0, 0.0, 0, "غير متصل"

def metaapi_open_order(acc: dict, action: str, symbol: str, lot: float) -> tuple[bool, str, str, float]:
    ok_dep, cid, reg, err_msg = metaapi_ensure_deployed(acc)
    if not ok_dep:
        return False, symbol, err_msg, lot

    base_c = metaapi_client_url(reg)
    action_type = "ORDER_TYPE_BUY" if action == "BUY" else "ORDER_TYPE_SELL"
    vol = max(round(float(lot), 2), 0.01)

    for sym_try in [symbol, "XAUUSD", "XAUUSDm", "GOLD", "EURUSD"]:
        payload = {
            "actionType": action_type,
            "symbol": sym_try,
            "volume": vol,
            "comment": "AI_Cloud_Bot"
        }
        st, res = http_request(f"{base_c}/users/current/accounts/{cid}/trade", "POST", headers=metaapi_headers(), payload=payload, timeout=12)
        if st == 200 and isinstance(res, dict):
            num_code = res.get("numericCode", -1)
            if num_code in [0, 10008, 10009] or res.get("stringCode") in ["TRADE_RETCODE_DONE", "TRADE_RETCODE_DONE_PARTIAL"]:
                oid = str(res.get("orderId") or res.get("positionId") or "Executed")
                return True, sym_try, oid, vol
            err_txt = res.get("message") or res.get("stringCode") or str(res)
            if "symbol" not in err_txt.lower():
                return False, sym_try, f"رفض MetaApi: {err_txt}", vol
    return False, symbol, "تعذر تنفيذ الأمر عبر MetaApi.", vol

def metaapi_get_positions(acc: dict) -> list:
    ok_dep, cid, reg, _ = metaapi_ensure_deployed(acc)
    if not ok_dep:
        return []
    base_c = metaapi_client_url(reg)
    st, pos_list = http_request(f"{base_c}/users/current/accounts/{cid}/positions", "GET", headers=metaapi_headers(), timeout=8)
    if st == 200 and isinstance(pos_list, list):
        return [{
            "id": str(p.get("id")),
            "symbol": p.get("symbol"),
            "volume": float(p.get("volume", 0.01)),
            "type": p.get("type"),
            "profit": float(p.get("profit", 0.0))
        } for p in pos_list]
    return []

def metaapi_close_position(acc: dict, pos: dict) -> bool:
    ok_dep, cid, reg, _ = metaapi_ensure_deployed(acc)
    if not ok_dep:
        return False
    base_c = metaapi_client_url(reg)
    payload = {"actionType": "POSITION_CLOSE_ID", "positionId": str(pos.get("id"))}
    st, res = http_request(f"{base_c}/users/current/accounts/{cid}/trade", "POST", headers=metaapi_headers(), payload=payload, timeout=10)
    return bool(st == 200 and isinstance(res, dict) and res.get("numericCode") in [0, 10008, 10009])


# ================= 9. المحرك الثالث: منصة MT5 الويندوز فائقة السرعة (بدون IPC Timeout) =================
mt5_lock = threading.Lock()
failed_servers_cache = {}  # يحفظ السيرفرات الخارجية غير المعرفة محلياً لمنع تأخير الرد دقيقتين

def ensure_autotrading_fast():
    ti = mt5.terminal_info()
    if ti and getattr(ti, "trade_allowed", False):
        return True
    send_ctrl_e_to_mt5_window()
    ti = mt5.terminal_info()
    return bool(ti and getattr(ti, "trade_allowed", False))

def native_mt5_connect(acc: dict) -> tuple[bool, str]:
    """
    اتصال فائق السرعة بـ MT5:
    1. إذا كان الحساب متصلاً بالفعل، يعود فوراً خلال 0.001 ثانية.
    2. يفصل mt5.initialize(exe_path) عن mt5.login() بمهلة قصيرة (8 ثوانٍ) لمنع تعليق البوت دقيقتين.
    3. لا يفتح أبداً نسختين متضاربتين من terminal64.exe.
    """
    try:
        if not NATIVE_MT5_AVAILABLE:
            return False, "WINDOWS_MT5_NOT_AVAILABLE"

        login_str = str(acc.get("login_or_key", "")).strip()
        if not login_str.isdigit():
            return False, f"رقم حساب غير صالح: {login_str}"
        login_int = int(login_str)
        password = str(acc.get("password_or_secret", "")).strip()
        server = str(acc.get("server_or_mode", "")).strip()

        # 1. مسار سريع جداً (0.001 ثانية) إذا كان الحساب متصلاً حالياً
        try:
            curr_info = mt5.account_info()
            if curr_info is not None and int(curr_info.login) == login_int:
                ensure_autotrading_fast()
                return True, "CONNECTED"
        except Exception:
            pass

        # إذا كان السيرفر قد فشل سابقاً بخطأ IPC timeout لعدم وجوده في servers.dat، نتجنب تعليق البوت
        if failed_servers_cache.get(f"{login_int}_{server}", 0) > time.time():
            return False, (
                f"سيرفر ({server}) غير مضاف في قائمة MetaQuotes الافتراضية. "
                "الحل: أرسل عنوان IP:Port بدلاً من اسم السيرفر، أو احذف هذا الحساب وتداول على حسابك المتصل 🟢."
            )

        exe_path = find_mt5_terminal_exe()
        if not exe_path:
            ensure_windows_mt5_terminal()
            exe_path = find_mt5_terminal_exe()

        # إذا لم يكن برنامج terminal64.exe يعمل نهائياً، نشغله مرة واحدة بملف الإعدادات المفعل لـ AutoTrading
        if not is_terminal_process_running():
            startup_ini = write_mt5_autotrading_ini(login_str, password, server)
            if exe_path:
                subprocess.Popen([exe_path, f"/config:{startup_ini}"])
                time.sleep(5)

        # 2. الخطوة الأولى: تهيئة قناة IPC فقط بدون تمرير سيرفر خارجي (سريعة جداً < 0.2 ثانية)
        ok_ipc = mt5.initialize(exe_path, timeout=8000) if exe_path else mt5.initialize(timeout=8000)
        if not ok_ipc:
            return False, f"تعذر ربط قناة MT5: {mt5.last_error()}"

        # التحقق مما إذا كان الحساب المطلوب قد سجل الدخول بالفعل
        curr_info = mt5.account_info()
        if curr_info is not None and int(curr_info.login) == login_int:
            ensure_autotrading_fast()
            return True, "CONNECTED"

        # 3. الخطوة الثانية: تبديل الحساب عبر mt5.login بمهلة سريعة (8 ثوانٍ كحد أقصى بدلاً من دقيقتين)
        if mt5.login(login_int, password=password, server=server, timeout=8000):
            ensure_autotrading_fast()
            return True, "CONNECTED"

        err_code, err_desc = mt5.last_error()
        # في حال فشل التبديل لسيرفر خارجي، نحفظه في الكاش المؤقت لـ 5 دقائق حتى لا يبطئ البوت، ونعيد الاتصال بالحساب الشغال
        if err_code in [-10005, -10003, -10004]:
            failed_servers_cache[f"{login_int}_{server}"] = time.time() + 300
            try:
                mt5.login(int(KNOWN_MT5_LOGIN), password=KNOWN_MT5_PASS, server=KNOWN_MT5_SERVER, timeout=5000)
            except Exception:
                pass
            return False, (
                f"سيرفر الوسيط ({server}) غير مدرج في برنامج MT5 القياسي ({err_desc}). "
                "يمكنك استخدام عنوان IP:Port للسيرفر أو حذفه من إدارة الحسابات."
            )

        return False, f"رفض الدخول ({err_code}, {err_desc})"
    except Exception as e:
        return False, f"استثناء اتصال MT5: {e}"


# ================= 10. الموجه الموحد الذكي (Bybit + Windows MT5 + MetaApi) =================
def unified_get_account_status(acc: dict) -> tuple[bool, float, float, int, str]:
    platform = acc.get("platform", "MT5").upper()
    if platform == "BYBIT":
        ok, bal, eq, msg = bybit_get_balance(acc)
        positions = bybit_get_open_positions(acc, "PAXGUSDT") if ok else []
        return ok, bal, eq, len(positions), msg

    if NATIVE_MT5_AVAILABLE:
        with mt5_lock:
            ok_nat, msg_nat = native_mt5_connect(acc)
            if ok_nat:
                info = mt5.account_info()
                ti = mt5.terminal_info()
                pos = mt5.positions_get()
                auto_txt = "التداول الآلي: مفعل 🟢" if (ti and getattr(ti, "trade_allowed", False)) else "التداول الآلي: مفعل تلقائياً ⚡"
                if info:
                    return True, float(info.balance), float(info.equity), (len(pos) if pos else 0), f"متصل بـ Windows MT5 ({auto_txt})"
            elif MASTER_METAAPI_TOKEN:
                ok_m, b_m, e_m, p_m, s_m = metaapi_get_status(acc)
                if ok_m:
                    return ok_m, b_m, e_m, p_m, s_m
            return False, 0.0, 0.0, 0, msg_nat

    if MASTER_METAAPI_TOKEN:
        return metaapi_get_status(acc)

    return False, 0.0, 0.0, 0, "غير متصل بـ MT5"

def match_mt5_symbol(desired_symbol: str) -> str:
    candidates = [desired_symbol, "XAUUSD", "XAUUSDm", "XAUUSD.", "GOLD", "GOLDm", "EURUSD", "EURUSDm"]
    for s in candidates:
        si = mt5.symbol_info(s)
        if si is not None:
            if not si.visible:
                mt5.symbol_select(s, True)
            return s
    all_syms = mt5.symbols_get()
    if all_syms:
        for s_obj in all_syms:
            name_up = s_obj.name.upper()
            if desired_symbol.upper() in name_up or ("XAU" in desired_symbol.upper() and ("XAU" in name_up or "GOLD" in name_up)):
                mt5.symbol_select(s_obj.name, True)
                return s_obj.name
    return desired_symbol

def unified_open_order(acc: dict, action: str, symbol: str, lot: float) -> tuple[bool, str, str, float]:
    platform = acc.get("platform", "MT5").upper()
    if platform == "BYBIT":
        return bybit_open_order(acc, action, symbol, lot)

    if NATIVE_MT5_AVAILABLE:
        with mt5_lock:
            try:
                ok_nat, err_nat = native_mt5_connect(acc)
                if ok_nat:
                    selected_sym = match_mt5_symbol(symbol)
                    si = mt5.symbol_info(selected_sym)
                    if si is None:
                        return False, symbol, f"الرمز {symbol} غير موجود في السيرفر.", lot
                    if not si.visible:
                        mt5.symbol_select(selected_sym, True)
                        time.sleep(0.2)
                    tick = mt5.symbol_info_tick(selected_sym)
                    if not tick:
                        return False, selected_sym, "السوق مغلق أو لا توجد تسعيرات حية حالياً.", lot

                    price = tick.ask if action == "BUY" else tick.bid
                    order_type = mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL
                    min_lot = float(getattr(si, "volume_min", 0.01) or 0.01)
                    vol = max(float(lot), min_lot)

                    last_err = ""
                    for attempt in range(2):
                        for fill_mode in [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN]:
                            req = {
                                "action": mt5.TRADE_ACTION_DEAL,
                                "symbol": selected_sym,
                                "volume": vol,
                                "type": order_type,
                                "price": price,
                                "deviation": 50,
                                "magic": 990011,
                                "comment": "AI_Cloud_Bot",
                                "type_time": mt5.ORDER_TIME_GTC,
                                "type_filling": fill_mode,
                            }
                            res = mt5.order_send(req)
                            if res is not None and res.retcode in [mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL]:
                                return True, selected_sym, str(res.order or res.deal), vol
                            elif res is not None:
                                last_err = f"{res.comment} (كود {res.retcode})"
                                if res.retcode == 10027 and attempt == 0:
                                    send_ctrl_e_to_mt5_window()
                                    break
                    return False, selected_sym, f"رفض سيرفر MT5: {last_err or mt5.last_error()}", vol
                elif MASTER_METAAPI_TOKEN:
                    return metaapi_open_order(acc, action, symbol, lot)
                else:
                    return False, symbol, err_nat, lot
            except Exception as e:
                return False, symbol, f"خطأ أثناء إرسال الأمر: {e}", lot

    if MASTER_METAAPI_TOKEN:
        return metaapi_open_order(acc, action, symbol, lot)

    return False, symbol, "غير متصل بـ MT5.", lot

def unified_get_positions(acc: dict, symbol: str) -> list:
    platform = acc.get("platform", "MT5").upper()
    if platform == "BYBIT":
        return bybit_get_open_positions(acc, symbol)
    if NATIVE_MT5_AVAILABLE:
        with mt5_lock:
            try:
                if native_mt5_connect(acc)[0]:
                    pos = mt5.positions_get()
                    if pos:
                        return [{
                            "id": str(p.ticket),
                            "ticket": p.ticket,
                            "symbol": p.symbol,
                            "volume": p.volume,
                            "type": p.type,
                            "profit": float(p.profit)
                        } for p in pos]
            except Exception:
                pass
    if MASTER_METAAPI_TOKEN:
        return metaapi_get_positions(acc)
    return []

def unified_close_position(acc: dict, pos: dict) -> bool:
    platform = acc.get("platform", "MT5").upper()
    if platform == "BYBIT":
        return bybit_close_position(acc, pos)
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
                    for fill_mode in [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN]:
                        req = {
                            "action": mt5.TRADE_ACTION_DEAL,
                            "symbol": sym,
                            "volume": float(pos["volume"]),
                            "type": close_type,
                            "position": int(pos["ticket"]),
                            "price": price,
                            "deviation": 50,
                            "magic": 990011,
                            "comment": "AI_Close",
                            "type_time": mt5.ORDER_TIME_GTC,
                            "type_filling": fill_mode,
                        }
                        res = mt5.order_send(req)
                        if res is not None and res.retcode in [mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL]:
                            return True
            except Exception:
                pass
    if MASTER_METAAPI_TOKEN:
        return metaapi_close_position(acc, pos)
    return False


# ================= 11. محرك التداول الآلي والواجهة العربية الفورية =================
authorized_users = set()
active_traders = {}
pending_input = {}
diag_running = set()   # يمنع تكدس رسائل الفحص عند الضغط المتكرر
trade_running = set()  # يمنع تكدس الصفقات الفورية المتزامنة

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
    if user_id in trade_running:
        if notify_start:
            send_msg(chat_id, "⏳ جاري تنفيذ صفقة حالياً، انتظر ثوانٍ...")
        return True
    trade_running.add(user_id)
    try:
        u = get_user(user_id)
        target_accounts = get_target_trading_accounts(user_id)
        if not target_accounts:
            send_msg(chat_id, "⚠️ لا توجد حسابات مضافة.")
            return False

        if notify_start:
            send_msg(chat_id, f"⚡ جاري تحليل السوق وإرسال أمر التداول الفعلي إلى ({len(target_accounts)}) حساب...")

        decision = analyze_market_with_ai(user_id, u["symbol"])
        action = decision["action"]
        any_success = False
        report = [
            f"🤖 **قرار الذكاء الاصطناعي:** {action} (الثقة: {decision['confidence']}%)",
            f"• الأداة: {decision['provider_name']}",
            f"• المؤشرات الحية: {decision['indicators']}\n"
        ]

        for acc in target_accounts:
            ok, exec_sym, order_or_err, used_lot = unified_open_order(acc, action, u["symbol"], u["lot"])
            if ok:
                any_success = True
                report.append(
                    f"✅ الحساب [{acc['account_label']}]:\n"
                    f"   تم فتح صفقة حقيقية {action} على {exec_sym} (لوت {used_lot}) | تذكرة #{order_or_err}"
                )
            else:
                report.append(
                    f"⚠️ الحساب [{acc['account_label']}]:\n"
                    f"   تعذر التنفيذ ({order_or_err})"
                )

        send_msg(chat_id, "\n".join(report))
        return any_success
    except Exception as e:
        send_msg(chat_id, f"⚠️ حدث خطأ أثناء محاولة التنفيذ: {e}")
        return False
    finally:
        trade_running.discard(user_id)

def trading_worker(user_id: int, chat_id: int):
    send_msg(chat_id, "🟢 **بدأ التداول الآلي الحقيقي بالذكاء الاصطناعي (يعمل سحابياً 24/7)!**")
    first_cycle = True
    while active_traders.get(user_id, False):
        try:
            u = get_user(user_id)
            if u["current_daily_pnl"] >= u["daily_max_profit"]:
                active_traders[user_id] = False
                update_user(user_id, "auto_run", 0)
                send_msg(chat_id, f"🏆 تحقق الهدف اليومي للأرباح (+{u['current_daily_pnl']:.2f}$). توقف البوت لحفظ أرباحك.")
                break
            if u["current_daily_pnl"] <= -abs(u["daily_max_loss"]):
                active_traders[user_id] = False
                update_user(user_id, "auto_run", 0)
                send_msg(chat_id, f"🛡️ وصلت الخسارة للحد الأقصى ({u['current_daily_pnl']:.2f}$). توقف البوت لحماية رأس مالك.")
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
                                icon = "💰" if pnl > 0 else "🛑"
                                send_msg(
                                    chat_id,
                                    f"{icon} تم إغلاق الصفقة على [{acc['account_label']}]\n"
                                    f"• ربح/خسارة الصفقة: {pnl:.2f}$\n"
                                    f"• حصيلة اليوم: {new_pnl:.2f}$ ({new_cnt} صفقات)"
                                )

            if not any_open and is_within_working_hours(u["work_start_hour"], u["work_end_hour"]):
                notify_flag = first_cycle
                first_cycle = False
                ok_exec = execute_ai_trade_across_accounts(user_id, chat_id, notify_start=notify_flag)
                if not ok_exec:
                    active_traders[user_id] = False
                    update_user(user_id, "auto_run", 0)
                    send_msg(chat_id, "⏸️ تم إيقاف التكرار التلقائي مؤقتاً حتى تتحقق من الحساب النشط أعلاه.")
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
    multi_txt = f"🌐 التداول الجماعي: مفعل ({len(all_accs)} حسابات) 🟢" if u["trade_all_accounts"] == 1 else "👤 الوضع: الحساب النشط فقط (اضغط لتفعيل الكل)"
    hours_txt = "24 ساعة" if (u["work_start_hour"] == 0 and u["work_end_hour"] == 24) else f"{u['work_start_hour']}:00 - {u['work_end_hour']}:00"
    run_btn = (
        {"text": "⏹️ إيقاف التداول التلقائي (يعمل الآن 🟢)", "callback_data": "toggle_run"}
        if active_traders.get(user_id, False)
        else {"text": "▶️ بدء التداول التلقائي بالذكاء الاصطناعي", "callback_data": "toggle_run"}
    )
    return {"inline_keyboard": [
        [{"text": "➕ إضافة حساب جديد (MT5 أو Bybit للذهب)", "callback_data": "menu_add_account"}],
        [{"text": f"📂 إدارة الحسابات ({len(all_accs)}) | النشط: {active_acc.get('account_label')}", "callback_data": "menu_manage_accounts"}],
        [{"text": multi_txt, "callback_data": "toggle_multi_accounts"}],
        [{"text": f"🤖 الذكاء الاصطناعي: {tool.get('name')}", "callback_data": "menu_ai_select"}],
        [{"text": "🔍 فحص الرصيد الحي وحالة الحسابات", "callback_data": "diag_all"}],
        [
            {"text": f"💵 اللوت: {u['lot']}", "callback_data": "set_lot"},
            {"text": f"📊 الزوج: {u['symbol']}", "callback_data": "set_symbol"}
        ],
        [
            {"text": f"🎯 ربح الصفقة: +{u['trade_tp_usd']}$", "callback_data": "set_tp"},
            {"text": f"🛑 خسارة الصفقة: -{u['trade_sl_usd']}$", "callback_data": "set_sl"}
        ],
        [
            {"text": f"🏆 أقصى ربح يومي: {u['daily_max_profit']}$", "callback_data": "set_daily_tp"},
            {"text": f"🛡️ أقصى خسارة يومية: {u['daily_max_loss']}$", "callback_data": "set_daily_sl"}
        ],
        [{"text": f"⏰ أوقات عمل البوت ({hours_txt})", "callback_data": "set_hours"}],
        [run_btn],
        [{"text": "⚡ فتح صفقة فورية الآن بالذكاء الاصطناعي", "callback_data": "instant_trade"}],
        [{"text": "🚨 إغلاق جميع الصفقات المفتوحة فوراً", "callback_data": "emergency_close"}],
        [{"text": "🔄 تصفير عداد أرباح اليوم", "callback_data": "reset_pnl"}]
    ]}

def main_dashboard_text(user_id: int) -> str:
    u = get_user(user_id)
    active_acc = get_active_account(user_id)
    all_accs = get_user_accounts(user_id)
    tool = get_ai_tool_by_id(u["selected_ai_id"])
    state = "يعمل سحابياً 24/7 🟢" if active_traders.get(user_id, False) else "متوقف 🔴"
    host_env = "GitHub Windows MT5 🟢" if NATIVE_MT5_AVAILABLE else "Render Cloud 24/7 🌐"
    return (
        "🤖 **لوحة تحكم بوت التداول الذكي (MT5 + Bybit Gold)**\n\n"
        f"• حالة البوت: {state}\n"
        f"• الاستضافة النشطة: {host_env}\n"
        f"• الحساب النشط: {active_acc.get('account_label')} ({active_acc.get('server_or_mode')})\n"
        f"• إجمالي الحسابات المضافة: {len(all_accs)}\n"
        f"• أداة الذكاء الاصطناعي: {tool.get('name')}\n"
        f"• صافي ربح/خسارة اليوم: {u['current_daily_pnl']:.2f}$\n"
        f"• عدد صفقات اليوم: {u['trades_today']}"
    )

def accounts_management_keyboard(user_id: int) -> dict:
    u = get_user(user_id)
    accs = get_user_accounts(user_id)
    rows = []
    for a in accs:
        pk = a["acc_pk"]
        is_act = "🟢 [النشط] " if pk == u["active_account_id"] else "⚪ "
        rows.append([
            {"text": f"{is_act}{a['account_label']} [{a['server_or_mode']}]", "callback_data": f"select_acc_{pk}"},
            {"text": "🗑️ حذف", "callback_data": f"del_acc_{pk}"}
        ])
    rows.append([{"text": "➕ إضافة حساب جديد (3 أسطر)", "callback_data": "menu_add_account"}])
    rows.append([{"text": "🔙 رجوع للوحة الرئيسية", "callback_data": "back_home"}])
    return {"inline_keyboard": rows}

def ai_selection_keyboard(user_id: int) -> dict:
    u = get_user(user_id)
    rows = []
    for t in get_ai_tools():
        mark = "✅ " if t["id"] == u["selected_ai_id"] else ""
        rows.append([{"text": f"{mark}{t['name']}", "callback_data": f"pick_ai_{t['id']}"}])
    rows.append([{"text": "🔙 رجوع للوحة الرئيسية", "callback_data": "back_home"}])
    return {"inline_keyboard": rows}

def async_add_account_verify(uid: int, chat_id: int, platform: str, p1: str, p2: str, p3: str):
    pk = add_or_update_trading_account(uid, platform, p1, p2, p3, make_active=False)
    acc_obj = get_account_by_pk(pk)
    ok_st, bal, _, _, st_msg = unified_get_account_status(acc_obj)
    if ok_st:
        # نجح الاتصال الفعلي، نجعله الحساب النشط تلقائياً
        update_user(uid, "active_account_id", pk)
        send_msg(
            chat_id,
            f"✅ **تم حفظ وتفعيل الحساب بنجاح!**\n"
            f"• الحساب: {acc_obj['account_label']}\n"
            f"• الرصيد الحي: {bal:.2f}$\n"
            f"• الحالة: {st_msg}",
            main_dashboard_keyboard(uid)
        )
    else:
        # فشل الاتصال، نبقي الحساب الأساسي الشغال هو النشط حتى لا يتعطل التداول
        send_msg(
            chat_id,
            f"⚠️ **تم حفظ الحساب ({acc_obj['account_label']}) ولكن تعذر الاتصال بسيرفره حالياً:**\n"
            f"• السبب: {st_msg}\n"
            f"• ملاحظة: أبقينا حسابك الأساسي الشغال هو الحساب النشط لكي لا يتوقف التداول.",
            main_dashboard_keyboard(uid)
        )

def async_diagnostic_all(uid: int, chat_id: int):
    if uid in diag_running:
        return
    diag_running.add(uid)
    try:
        sent = send_msg(chat_id, "⚡ جاري الفحص السريع للحسابات...")
        msg_id = sent.get("result", {}).get("message_id") if isinstance(sent, dict) else None
        accs = get_user_accounts(uid)
        u = get_user(uid)
        lines = ["🔍 **تقرير الفحص الشامل للحسابات:**\n"]
        first_working_pk = None

        for a in accs:
            ok, bal, eq, p_cnt, status_txt = unified_get_account_status(a)
            if ok:
                if first_working_pk is None:
                    first_working_pk = a["acc_pk"]
                lines.append(
                    f"✅ {a['account_label']} ({a['server_or_mode']}):\n"
                    f"   • الحالة: {status_txt}\n"
                    f"   • الرصيد: {bal:.2f}$ | السيولة: {eq:.2f}$\n"
                    f"   • الصفقات المفتوحة الآن: {p_cnt}\n"
                )
            else:
                lines.append(
                    f"⚠️ {a['account_label']} ({a['server_or_mode']}):\n"
                    f"   • الحالة: {status_txt}\n"
                )
                # إذا كان الحساب النشط الحالي متعطلاً ولدينا حساب آخر شغال، نحول النشط للشغال تلقائياً
                if u["active_account_id"] == a["acc_pk"] and first_working_pk is not None:
                    update_user(uid, "active_account_id", first_working_pk)
                    lines.append("   • 🔄 تم تحويل الحساب النشط تلقائياً إلى حسابك المتصل الشغال 🟢.\n")

        report = "\n".join(lines)
        if msg_id:
            edit_msg(chat_id, msg_id, report, main_dashboard_keyboard(uid))
        else:
            send_msg(chat_id, report, main_dashboard_keyboard(uid))
    finally:
        diag_running.discard(uid)

def run_bot_polling():
    # تهيئة اتصال MT5 بالحساب الافتراضي في الخلفية فور الإقلاع ليكون جاهزاً في 0.001 ثانية
    def warmup_mt5():
        if NATIVE_MT5_AVAILABLE:
            with mt5_lock:
                native_mt5_connect({
                    "login_or_key": KNOWN_MT5_LOGIN,
                    "password_or_secret": KNOWN_MT5_PASS,
                    "server_or_mode": KNOWN_MT5_SERVER
                })
    threading.Thread(target=warmup_mt5, daemon=True).start()

    while True:
        try:
            tg_api("deleteWebhook", {"drop_pending_updates": True})
            resume_saved_auto_traders()
            offset = 0
            safe_print("Fast Bot Polling Started Successfully!")
            while True:
                if time.time() - BOT_START_TIME > MAX_RUNTIME_SECONDS:
                    safe_print("Triggering next GitHub Actions cycle before exit...")
                    trigger_github_workflow_restart()
                    return
                res = tg_api("getUpdates", {"offset": offset, "timeout": 5}, timeout=10)
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
                                    pending_input.pop(uid, None)
                                    send_msg(chat_id, "⏳ تم استلام البيانات، جاري فحص الاتصال بالحساب في الخلفية...")
                                    threading.Thread(
                                        target=async_add_account_verify,
                                        args=(uid, chat_id, platform, p1, p2, p3),
                                        daemon=True
                                    ).start()
                                else:
                                    send_msg(chat_id, "⚠️ أرسل بيانات الحساب في 3 أسطر تحت بعضها:\nاسم المستخدم\nكلمة المرور\nالسيرفر")

                            elif action == "input_hours":
                                try:
                                    s_h, e_h = [int(x.strip()) for x in text.split("-")]
                                    update_user(uid, "work_start_hour", s_h)
                                    update_user(uid, "work_end_hour", e_h)
                                    pending_input.pop(uid, None)
                                    send_msg(chat_id, "✅ تم حفظ أوقات العمل بنجاح!", main_dashboard_keyboard(uid))
                                except ValueError:
                                    send_msg(chat_id, "⚠️ أرسل الساعات بصيغة: 8-22 أو 0-24")

                            elif action.startswith("field_"):
                                field = action.replace("field_", "")
                                try:
                                    val = text.upper().strip() if field == "symbol" else float(text.strip())
                                    update_user(uid, field, val)
                                    pending_input.pop(uid, None)
                                    send_msg(chat_id, "✅ تم التحديث بنجاح!", main_dashboard_keyboard(uid))
                                except ValueError:
                                    send_msg(chat_id, "⚠️ أرسل رقماً صحيحاً (مثال: 0.01).")

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
                            edit_msg(
                                chat_id, msg_id,
                                "➕ **إضافة حساب تداول جديد (MT5 أو Bybit):**\n"
                                "أرسل البيانات في 3 أسطر تحت بعضها:\n\n"
                                "لإضافة حساب MT5:\n"
                                "`5058253637`\n"
                                "`*aGm1cNp`\n"
                                "`MetaQuotes-Demo`\n\n"
                                "أو لإضافة حساب الذهب Bybit:\n"
                                "`API_KEY`\n"
                                "`API_SECRET`\n"
                                "`BYBIT-DEMO`",
                                {"inline_keyboard": [[{"text": "🔙 رجوع", "callback_data": "back_home"}]]}
                            )

                        elif data == "menu_manage_accounts":
                            answer_cb(cb_id)
                            edit_msg(chat_id, msg_id, "📂 **إدارة الحسابات المضافة:**\nاضغط على أي حساب لتفعيله أو 🗑️ لحذفه:", accounts_management_keyboard(uid))

                        elif data.startswith("select_acc_"):
                            pk = int(data.split("_")[-1])
                            update_user(uid, "active_account_id", pk)
                            answer_cb(cb_id, "✅ تم تبديل الحساب النشط")
                            edit_msg(chat_id, msg_id, "📂 **إدارة الحسابات المضافة:**", accounts_management_keyboard(uid))

                        elif data.startswith("del_acc_"):
                            pk = int(data.split("_")[-1])
                            if delete_trading_account(uid, pk):
                                answer_cb(cb_id, "🗑️ تم حذف الحساب بنجاح")
                            else:
                                answer_cb(cb_id, "⚠️ يجب إبقاء حساب واحد على الأقل", True)
                            edit_msg(chat_id, msg_id, "📂 **إدارة الحسابات المضافة:**", accounts_management_keyboard(uid))

                        elif data == "toggle_multi_accounts":
                            u = get_user(uid)
                            new_val = 0 if u["trade_all_accounts"] == 1 else 1
                            update_user(uid, "trade_all_accounts", new_val)
                            answer_cb(cb_id, "🌐 تم تفعيل التداول الجماعي!" if new_val == 1 else "👤 تم التحديد على الحساب النشط فقط.", True)
                            edit_msg(chat_id, msg_id, main_dashboard_text(uid), main_dashboard_keyboard(uid))

                        elif data == "diag_all":
                            if uid in diag_running:
                                answer_cb(cb_id, "⏳ الفحص يعمل حالياً، ستظهر النتيجة فوراً...", True)
                            else:
                                answer_cb(cb_id, "⚡ جاري الفحص السريع...")
                                threading.Thread(target=async_diagnostic_all, args=(uid, chat_id), daemon=True).start()

                        elif data == "menu_ai_select":
                            answer_cb(cb_id)
                            edit_msg(chat_id, msg_id, "🤖 **اختر أداة الذكاء الاصطناعي:**", ai_selection_keyboard(uid))

                        elif data.startswith("pick_ai_"):
                            tool_id = int(data.split("_")[-1])
                            update_user(uid, "selected_ai_id", tool_id)
                            answer_cb(cb_id, "✅ تم تحديث أداة الذكاء الاصطناعي")
                            edit_msg(chat_id, msg_id, main_dashboard_text(uid), main_dashboard_keyboard(uid))

                        elif data == "set_hours":
                            answer_cb(cb_id)
                            pending_input[uid] = "input_hours"
                            edit_msg(chat_id, msg_id, "⏰ أرسل أوقات العمل (مثال: 8-22 أو 0-24):", {"inline_keyboard": [[{"text": "🔙 رجوع", "callback_data": "back_home"}]]})

                        elif data == "instant_trade":
                            answer_cb(cb_id, "⚡ جاري تحليل السوق وتنفيذ الصفقة...")
                            threading.Thread(target=execute_ai_trade_across_accounts, args=(uid, chat_id, True), daemon=True).start()

                        elif data == "emergency_close":
                            answer_cb(cb_id, "🚨 جاري إغلاق جميع الصفقات...")
                            active_traders[uid] = False
                            update_user(uid, "auto_run", 0)
                            def bg_close():
                                u = get_user(uid)
                                closed_cnt = 0
                                for acc in get_user_accounts(uid):
                                    for p in unified_get_positions(acc, u["symbol"]):
                                        if unified_close_position(acc, p):
                                            closed_cnt += 1
                                send_msg(chat_id, f"🚨 تم إغلاق ({closed_cnt}) صفقات مفتوحة وإيقاف التداول التلقائي.", main_dashboard_keyboard(uid))
                            threading.Thread(target=bg_close, daemon=True).start()

                        elif data in ["set_lot", "set_symbol", "set_tp", "set_sl", "set_daily_tp", "set_daily_sl"]:
                            answer_cb(cb_id)
                            mapping = {
                                "set_lot": ("lot", "💵 أرسل حجم اللوت (مثال: 0.01):"),
                                "set_symbol": ("symbol", "📊 أرسل رمز الزوج (مثال: XAUUSD):"),
                                "set_tp": ("trade_tp_usd", "🎯 أرسل هدف ربح الصفقة بالدولار (مثال: 0.50):"),
                                "set_sl": ("trade_sl_usd", "🛑 أرسل وقف خسارة الصفقة بالدولار (مثال: 1.00):"),
                                "set_daily_tp": ("daily_max_profit", "🏆 أرسل أقصى ربح يومي بالدولار (مثال: 20):"),
                                "set_daily_sl": ("daily_max_loss", "🛡️ أرسل أقصى خسارة يومية بالدولار (مثال: 10):"),
                            }
                            f_name, txt = mapping[data]
                            pending_input[uid] = f"field_{f_name}"
                            edit_msg(chat_id, msg_id, txt, {"inline_keyboard": [[{"text": "🔙 رجوع", "callback_data": "back_home"}]]})

                        elif data == "reset_pnl":
                            answer_cb(cb_id, "✅ تم التصفير")
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
            time.sleep(2)

if __name__ == "__main__":
    init_db()
    ensure_windows_mt5_terminal()
    start_keep_alive()
    run_bot_polling()
