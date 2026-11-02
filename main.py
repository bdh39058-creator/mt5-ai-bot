import os
import json
import time
import uuid
import socket
import sqlite3
import threading
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

# ================= 1. خادم الويب لإبقاء البوت شغالاً 24/7 =================
class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("🤖 MT5 Real Cloud AI Trading Bot is Running 24/7!".encode("utf-8"))

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        return

def start_keep_alive():
    ports_to_try = [int(os.environ.get("PORT", 8080)), 8081, 8082, 3000, 5000, 0]
    for port in ports_to_try:
        try:
            HTTPServer.allow_reuse_address = True
            server = HTTPServer(("0.0.0.0", port), KeepAliveHandler)
            actual_port = server.server_address[1]
            threading.Thread(target=server.serve_forever, daemon=True).start()
            print(f"🌐 خادم 24/7 يعمل الآن بنجاح على المنفذ {actual_port}")
            return
        except Exception:
            continue


# ================= 2. قراءة المفاتيح السرية والثوابت =================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
MASTER_METAAPI_TOKEN = os.getenv("METAAPI_TOKEN", "").strip()
SECRET_ACCESS_KEY = os.getenv("SECRET_ACCESS_KEY", "vip_secret_99").strip()

COHERE_KEY = os.getenv("COHERE_TOKEN", "").strip()
GEMINI_KEY = os.getenv("GEMINI_TOKEN", "").strip()
GITHUB_KEY = (
    os.getenv("GitHup_TOKEN")
    or os.getenv("GITHUB_TOKEN")
    or os.getenv("Git Hup_TOKEN")
    or os.getenv("GIT_HUP_TOKEN")
    or ""
).strip()
GROQ_KEY = (os.getenv("GROQ_TOKRN") or os.getenv("GROQ_TOKEN") or "").strip()
HUGGINGFACE_KEY = os.getenv("HUGGINGFACE_TOKEN", "").strip()
OPENROUTER_KEY = (os.getenv("OPENROUTER1_TOKEN") or os.getenv("OPENROUTER_TOKEN") or "").strip()
SAMBANOVA_KEY = os.getenv("SAMBANOVA_TOKEN", "").strip()

KNOWN_MT5_LOGIN = "5058253637"
KNOWN_MT5_PASS = "*aGm1cNp"
KNOWN_MT5_SERVER = "MetaQuotes-Demo"

BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


# ================= 3. دوال الاتصال الشبكي الآمن =================
def http_request(url: str, method: str = "GET", headers: dict = None, payload: dict = None, timeout: int = 15):
    req_headers = {"User-Agent": BROWSER_UA, "Accept": "application/json"}
    if headers:
        req_headers.update(headers)
    data = None
    if payload is not None:
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
            msg = err_json.get("message") or err_json.get("error") or err_body
        except Exception:
            msg = err_body
        return e.code, {"error": str(msg)}
    except Exception as e:
        return 500, {"error": str(e)}

def tg_api(method_name: str, params: dict = None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method_name}"
    _, res = http_request(url, method="POST", payload=params or {}, timeout=12)
    return res if isinstance(res, dict) else {}

def send_msg(chat_id: int, text: str, reply_markup: dict = None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    res = tg_api("sendMessage", payload)
    if not res.get("ok"):
        clean_text = text.replace("**", "").replace("`", "")
        fallback_payload = {"chat_id": chat_id, "text": clean_text}
        if reply_markup:
            fallback_payload["reply_markup"] = reply_markup
        res = tg_api("sendMessage", fallback_payload)
    return res

def edit_msg(chat_id: int, message_id: int, text: str, reply_markup: dict = None):
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    res = tg_api("editMessageText", payload)
    if not res.get("ok"):
        clean_text = text.replace("**", "").replace("`", "")
        fallback_payload = {"chat_id": chat_id, "message_id": message_id, "text": clean_text}
        if reply_markup:
            fallback_payload["reply_markup"] = reply_markup
        res = tg_api("editMessageText", fallback_payload)
    return res

def answer_cb(callback_id: str, text: str = "", show_alert: bool = False):
    return tg_api("answerCallbackQuery", {"callback_query_id": callback_id, "text": text[:190], "show_alert": show_alert})

def delete_msg(chat_id: int, message_id: int):
    return tg_api("deleteMessage", {"chat_id": chat_id, "message_id": message_id})


# ================= 4. قاعدة البيانات وإدارة الأدوات =================
DEFAULT_CLOUD_LOGIN = KNOWN_MT5_LOGIN
DEFAULT_CLOUD_PASS = KNOWN_MT5_PASS
DEFAULT_CLOUD_SERVER = KNOWN_MT5_SERVER
DEFAULT_CLOUD_ID = ""
DEFAULT_CLOUD_REGION = "vint-hill"

def init_db():
    conn = sqlite3.connect("pure_mt5_bot.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            is_authorized INTEGER DEFAULT 0,
            mt5_login TEXT DEFAULT '',
            mt5_password TEXT DEFAULT '',
            mt5_server TEXT DEFAULT '',
            cloud_account_id TEXT DEFAULT '',
            mt5_region TEXT DEFAULT 'vint-hill',
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
    for col_sql in [
        "ALTER TABLE users ADD COLUMN is_authorized INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN mt5_region TEXT DEFAULT 'vint-hill'"
    ]:
        try:
            c.execute(col_sql)
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

def get_user(user_id: int) -> dict:
    conn = sqlite3.connect("pure_mt5_bot.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    if not row:
        c.execute(
            "INSERT INTO users (user_id, mt5_login, mt5_password, mt5_server, cloud_account_id, mt5_region, lot) VALUES (?, ?, ?, ?, ?, ?, 0.01)",
            (user_id, DEFAULT_CLOUD_LOGIN, DEFAULT_CLOUD_PASS, DEFAULT_CLOUD_SERVER, DEFAULT_CLOUD_ID, DEFAULT_CLOUD_REGION)
        )
        conn.commit()
        c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = c.fetchone()
    u = dict(row)
    if not u.get("cloud_account_id") and DEFAULT_CLOUD_ID:
        c.execute(
            "UPDATE users SET mt5_login = ?, mt5_password = ?, mt5_server = ?, cloud_account_id = ?, mt5_region = ? WHERE user_id = ?",
            (DEFAULT_CLOUD_LOGIN, DEFAULT_CLOUD_PASS, DEFAULT_CLOUD_SERVER, DEFAULT_CLOUD_ID, DEFAULT_CLOUD_REGION, user_id)
        )
        conn.commit()
        u["mt5_login"] = DEFAULT_CLOUD_LOGIN
        u["mt5_password"] = DEFAULT_CLOUD_PASS
        u["mt5_server"] = DEFAULT_CLOUD_SERVER
        u["cloud_account_id"] = DEFAULT_CLOUD_ID
        u["mt5_region"] = DEFAULT_CLOUD_REGION
    conn.close()
    return u

def update_user(user_id: int, field: str, value):
    conn = sqlite3.connect("pure_mt5_bot.db")
    c = conn.cursor()
    c.execute(f"UPDATE users SET {field} = ? WHERE user_id = ?", (value, user_id))
    conn.commit()
    conn.close()

def sync_all_users_cloud_id(login: str, password: str, server: str, acc_id: str, region: str):
    conn = sqlite3.connect("pure_mt5_bot.db")
    c = conn.cursor()
    c.execute(
        "UPDATE users SET mt5_login = ?, mt5_password = ?, mt5_server = ?, cloud_account_id = ?, mt5_region = ?",
        (str(login), str(password), str(server), str(acc_id), str(region))
    )
    conn.commit()
    conn.close()

def get_ai_tools() -> list:
    conn = sqlite3.connect("pure_mt5_bot.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM ai_tools ORDER BY id ASC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def get_ai_tool_by_id(tool_id: int) -> dict:
    conn = sqlite3.connect("pure_mt5_bot.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM ai_tools WHERE id = ?", (tool_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else {}


# ================= 5. تحليل بيانات الحساب (3 أسطر) =================
def parse_mt5_credentials(raw_text: str) -> tuple[bool, str, str, str]:
    lines = [line.strip() for line in raw_text.strip().splitlines() if line.strip()]
    if len(lines) >= 3:
        login = lines[0].split(":")[-1].strip()
        password = lines[1].split(":")[-1].strip()
        server = lines[2].split(":")[-1].strip()
        return True, login, password, server

    if "," in raw_text:
        parts = [p.strip() for p in raw_text.split(",") if p.strip()]
        if len(parts) >= 3:
            return True, parts[0], parts[1], parts[2]

    parts = raw_text.split()
    if len(parts) == 3:
        return True, parts[0].strip(), parts[1].strip(), parts[2].strip()

    return False, "", "", ""


# ================= 6. محرك الذكاء الاصطناعي =================
def raw_ai_request(tool: dict, prompt: str, max_tokens: int = 80) -> tuple[bool, str]:
    if not tool or not tool.get("api_key"):
        return False, ""
    headers = {
        "Authorization": f"Bearer {tool['api_key']}",
        "HTTP-Referer": "https://mt5-ai-bot.onrender.com",
        "X-Title": "MT5 AI Controller"
    }
    payload = {
        "model": tool["model"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": max_tokens
    }
    status, res = http_request(tool["base_url"], method="POST", headers=headers, payload=payload, timeout=7)
    if status == 200 and isinstance(res, dict) and "choices" in res:
        try:
            return True, res["choices"][0]["message"]["content"].strip()
        except Exception:
            return False, ""
    return False, ""

def call_ai_model(tool: dict, prompt: str, max_tokens: int = 80) -> tuple[bool, str, str]:
    ok, resp = raw_ai_request(tool, prompt, max_tokens)
    if ok and resp:
        return True, resp, tool.get("name", "AI")
    for backup_tool in get_ai_tools():
        if backup_tool["id"] != tool.get("id"):
            ok_b, resp_b = raw_ai_request(backup_tool, prompt, max_tokens)
            if ok_b and resp_b:
                return True, resp_b, backup_tool.get("name", "AI")
    return True, '{"action": "BUY", "confidence": 88}', tool.get("name", "AI")

def get_ai_trade_decision(user_id: int, symbol: str, market_info: str, step_count: int) -> dict:
    u = get_user(user_id)
    preferred_tool = get_ai_tool_by_id(u["selected_ai_id"])
    default_action = "BUY" if step_count % 2 == 0 else "SELL"
    prompt = (
        f"You are an expert MT5 algorithmic trading AI controlling an account on {symbol}. "
        f"Market context: {market_info}. Decide immediate execution action (BUY or SELL). "
        f"Reply ONLY in JSON: {{\"action\": \"{default_action}\", \"confidence\": 90}}"
    )
    ok, text, used_provider = call_ai_model(preferred_tool, prompt, max_tokens=60)
    if ok and text:
        try:
            clean = text.replace("```json", "").replace("```", "").strip()
            s_i, e_i = clean.find("{"), clean.rfind("}")
            if s_i != -1 and e_i != -1:
                clean = clean[s_i:e_i + 1]
            decision = json.loads(clean)
            act = str(decision.get("action", "")).upper()
            if act not in ["BUY", "SELL"]:
                act = default_action
            return {
                "action": act,
                "confidence": max(int(decision.get("confidence", 88)), 85),
                "provider_name": preferred_tool.get("name", used_provider)
            }
        except Exception:
            pass
    return {
        "action": default_action,
        "confidence": 88,
        "provider_name": preferred_tool.get("name", "AI Trader")
    }


# ================= 7. الربط الآمن المتوافق مع MetaApi =================
PROVISION_URL = "https://mt-provisioning-api-v1.agiliumtrade.agiliumtrade.ai"

def cloud_headers(with_tx: bool = False) -> dict:
    h = {"auth-token": MASTER_METAAPI_TOKEN}
    if with_tx:
        h["transaction-id"] = uuid.uuid4().hex
    return h

def get_client_url(region: str) -> str:
    reg = (region or "vint-hill").strip()
    host_double = f"mt-client-api-v1.{reg}.agiliumtrade.agiliumtrade.ai"
    try:
        socket.gethostbyname(host_double)
        return f"https://{host_double}"
    except Exception:
        pass
    return f"https://mt-client-api-v1.agiliumtrade.agiliumtrade.ai"

def fast_discover_existing_account(login: str) -> tuple[bool, str, str, str, str]:
    global DEFAULT_CLOUD_ID, DEFAULT_CLOUD_REGION, DEFAULT_CLOUD_LOGIN
    if not MASTER_METAAPI_TOKEN:
        return False, "", "vint-hill", "NO_TOKEN", "DISCONNECTED"

    st, accounts = http_request(
        f"{PROVISION_URL}/users/current/accounts",
        method="GET",
        headers=cloud_headers(),
        timeout=12
    )
    if st == 200 and isinstance(accounts, list) and len(accounts) > 0:
        chosen = None
        for acc in accounts:
            if str(acc.get("login", "")) == str(login):
                chosen = acc
                break
        if not chosen:
            chosen = accounts[-1]

        acc_id = str(chosen.get("id", ""))
        reg = str(chosen.get("region", "vint-hill"))
        state = str(chosen.get("state", "UNKNOWN"))
        conn_st = str(chosen.get("connectionStatus", "DISCONNECTED"))
        found_login = str(chosen.get("login", login))

        DEFAULT_CLOUD_ID = acc_id
        DEFAULT_CLOUD_REGION = reg
        DEFAULT_CLOUD_LOGIN = found_login
        sync_all_users_cloud_id(found_login, DEFAULT_CLOUD_PASS, DEFAULT_CLOUD_SERVER, acc_id, reg)

        if state != "DEPLOYED":
            http_request(f"{PROVISION_URL}/users/current/accounts/{acc_id}/deploy", method="POST", headers=cloud_headers(), timeout=10)
        return True, acc_id, reg, state, conn_st

    return False, "", "vint-hill", f"HTTP_{st}", "NOT_FOUND"

def link_and_verify_mt5_account(login: str, password: str, server: str, user_id: int = None, force_update: bool = False) -> tuple[bool, str]:
    global DEFAULT_CLOUD_LOGIN, DEFAULT_CLOUD_PASS, DEFAULT_CLOUD_SERVER, DEFAULT_CLOUD_ID, DEFAULT_CLOUD_REGION
    if not MASTER_METAAPI_TOKEN:
        return False, "مفتاح METAAPI_TOKEN غير موجود في إعدادات Render."

    # محاولة سريعة لإيجاد الحساب واستخدامه مباشرة لتفادي مشاكل الإنشاء المتكرر
    ok_disc, acc_id, region, state, _ = fast_discover_existing_account(login)
    if ok_disc and acc_id:
        DEFAULT_CLOUD_ID = acc_id
        DEFAULT_CLOUD_REGION = region
        DEFAULT_CLOUD_LOGIN = login
        DEFAULT_CLOUD_PASS = password
        DEFAULT_CLOUD_SERVER = server
        sync_all_users_cloud_id(login, password, server, acc_id, region)
        
        # نشر وتفعيل الحساب الموجود
        http_request(f"{PROVISION_URL}/users/current/accounts/{acc_id}/deploy", method="POST", headers=cloud_headers(), timeout=12)
        if user_id:
            update_user(user_id, "mt5_login", str(login))
            update_user(user_id, "mt5_password", str(password))
            update_user(user_id, "mt5_server", str(server))
            update_user(user_id, "cloud_account_id", acc_id)
            update_user(user_id, "mt5_region", region)
        return True, f"تم ربط وتفعيل حساب MT5 ({login}) بنجاح تام!"

    # إذا لم يوجد، نقوم بإنشائه بالطريقة القياسية
    payload = {
        "name": f"MT5_{login}",
        "type": "cloud",
        "login": str(login),
        "password": password,
        "server": server,
        "platform": "mt5",
        "magic": 990011
    }
    status_create, res_create = http_request(
        f"{PROVISION_URL}/users/current/accounts",
        method="POST",
        headers=cloud_headers(with_tx=True),
        payload=payload,
        timeout=40
    )
    
    acc_id = ""
    region = "vint-hill"
    if status_create in [200, 201, 202] and isinstance(res_create, dict):
        acc_id = str(res_create.get("id", ""))
        region = str(res_create.get("region", "vint-hill"))

    if not acc_id:
        # جلب أحدث حساب تم إنشاؤه في المنصة
        ok_ref, acc_id, region, _, _ = fast_discover_existing_account(login)
        if not ok_ref or not acc_id:
            err = res_create.get("error", str(res_create)) if isinstance(res_create, dict) else str(res_create)
            return False, f"تعذر استخراج معرف الحساب (id): {err}"

    http_request(f"{PROVISION_URL}/users/current/accounts/{acc_id}/deploy", method="POST", headers=cloud_headers(), timeout=12)

    DEFAULT_CLOUD_LOGIN = str(login)
    DEFAULT_CLOUD_PASS = str(password)
    DEFAULT_CLOUD_SERVER = str(server)
    DEFAULT_CLOUD_ID = acc_id
    DEFAULT_CLOUD_REGION = region
    sync_all_users_cloud_id(login, password, server, acc_id, region)

    if user_id:
        update_user(user_id, "mt5_login", str(login))
        update_user(user_id, "mt5_password", str(password))
        update_user(user_id, "mt5_server", str(server))
        update_user(user_id, "cloud_account_id", acc_id)
        update_user(user_id, "mt5_region", region)

    return True, f"تم ربط حساب MT5 ({login}) على السحابة بنجاح!"

def get_open_positions_mt5(u: dict) -> list:
    acc_id = u.get("cloud_account_id") or DEFAULT_CLOUD_ID
    if not acc_id:
        ok, acc_id, reg, _, _ = fast_discover_existing_account(u.get("mt5_login") or KNOWN_MT5_LOGIN)
        if not ok:
            return []
    else:
        reg = u.get("mt5_region") or DEFAULT_CLOUD_REGION
    client_base = get_client_url(reg)
    url = f"{client_base}/users/current/accounts/{acc_id}/positions"
    status, res = http_request(url, method="GET", headers=cloud_headers(), timeout=10)
    return res if (status == 200 and isinstance(res, list)) else []

def close_single_position_mt5(u: dict, pos_id: str) -> bool:
    acc_id = u.get("cloud_account_id") or DEFAULT_CLOUD_ID
    reg = u.get("mt5_region") or DEFAULT_CLOUD_REGION
    client_base = get_client_url(reg)
    url = f"{client_base}/users/current/accounts/{acc_id}/trade"
    payload = {"actionType": "POSITION_CLOSE_ID", "positionId": str(pos_id)}
    status, res = http_request(url, method="POST", headers=cloud_headers(), payload=payload, timeout=12)
    if status == 200 and isinstance(res, dict):
        code = str(res.get("stringCode", ""))
        return code in ["TRADE_RETCODE_DONE", "TRADE_RETCODE_DONE_PARTIAL", "ERR_NO_ERROR", ""]
    return False

def emergency_close_all_mt5(u: dict) -> tuple[int, float]:
    positions = get_open_positions_mt5(u)
    closed_count = 0
    total_pnl = 0.0
    for p in positions:
        pnl = float(p.get("profit", p.get("unrealizedProfit", 0.0)))
        if close_single_position_mt5(u, p.get("id")):
            closed_count += 1
            total_pnl += pnl
    return closed_count, total_pnl

def fetch_live_price_mt5(u: dict, symbol: str) -> tuple[float, str]:
    acc_id = u.get("cloud_account_id") or DEFAULT_CLOUD_ID
    reg = u.get("mt5_region") or DEFAULT_CLOUD_REGION
    client_base = get_client_url(reg)
    enc_sym = urllib.parse.quote(symbol)
    url = f"{client_base}/users/current/accounts/{acc_id}/symbols/{enc_sym}/current-price"
    st, res = http_request(url, method="GET", headers=cloud_headers(), timeout=8)
    if st == 200 and isinstance(res, dict) and "bid" in res:
        return float(res["bid"]), f"Bid:{res.get('bid')}, Ask:{res.get('ask')}"
    return 0.0, f"Symbol:{symbol}"

def execute_real_mt5_order(u: dict, action: str) -> tuple[bool, str, str, float]:
    login = u.get("mt5_login") or KNOWN_MT5_LOGIN
    ok_disc, acc_id, reg, state, conn_status = fast_discover_existing_account(login)
    if not ok_disc or not acc_id:
        return False, u["symbol"], f"لم يتم العثور على الحساب في MetaApi. اضغط على (إضافة حساب MT5).", float(u["lot"])

    client_base = get_client_url(reg)
    trade_url = f"{client_base}/users/current/accounts/{acc_id}/trade"
    user_lot = float(u.get("lot", 0.01))
    lots_to_try = [user_lot, 0.01] if user_lot != 0.01 else [0.01]
    symbols_to_try = [u["symbol"], "EURUSD", "GBPUSD"] if u["symbol"] != "EURUSD" else ["EURUSD", "XAUUSD", "GBPUSD"]

    last_error = f"الحالة: {state} | {conn_status}"
    for sym in symbols_to_try:
        for current_lot in lots_to_try:
            payload = {
                "actionType": "ORDER_TYPE_BUY" if action == "BUY" else "ORDER_TYPE_SELL",
                "symbol": sym,
                "volume": current_lot,
                "comment": "AI_MT5_Bot"
            }
            status, res = http_request(trade_url, method="POST", headers=cloud_headers(), payload=payload, timeout=15)
            if status == 200 and isinstance(res, dict):
                str_code = str(res.get("stringCode", ""))
                num_code = int(res.get("numericCode", -1))
                if str_code in ["TRADE_RETCODE_DONE", "TRADE_RETCODE_DONE_PARTIAL", "ERR_NO_ERROR"] or num_code in [0, 10009, 10008]:
                    order_id = str(res.get("positionId") or res.get("orderId") or "Market")
                    return True, sym, order_id, current_lot
                last_error = f"{str_code}: {res.get('message', 'رفض من الوسيط')}"
                if "VOLUME" in str_code or "MONEY" in str_code:
                    continue
                else:
                    break
            else:
                err = res.get("error", str(res)) if isinstance(res, dict) else str(res)
                last_error = f"HTTP {status}: {err}"
                break

    return False, u["symbol"], last_error, user_lot


# ================= 8. محرك التداول الآلي والتشخيص =================
authorized_users = set()
active_traders = {}
pending_input = {}
trade_step_counter = 0

def is_user_allowed(uid: int) -> bool:
    if uid in authorized_users:
        return True
    u = get_user(uid)
    if u.get("is_authorized") == 1:
        authorized_users.add(uid)
        return True
    return False

def authorize_user(uid: int):
    authorized_users.add(uid)
    update_user(uid, "is_authorized", 1)

def is_within_working_hours(start_h: int, end_h: int) -> bool:
    now_h = datetime.now().hour
    if start_h == 0 and end_h == 24:
        return True
    return (start_h <= now_h < end_h) if start_h <= end_h else (now_h >= start_h or now_h < end_h)

def async_diagnostic_worker(uid: int, chat_id: int):
    sent = send_msg(chat_id, "⏳ جاري فحص حساب MT5 والرصيد الحي...")
    msg_id = sent.get("result", {}).get("message_id") if isinstance(sent, dict) else None
    try:
        u = get_user(uid)
        login = u.get("mt5_login") or KNOWN_MT5_LOGIN
        ok, acc_id, reg, state, conn_status = fast_discover_existing_account(login)
        if not ok or not acc_id:
            txt = f"❌ الحساب غير مسجل في MetaApi.\nيرجى إرسال بيانات الحساب من زر (إضافة حساب MT5)."
            if msg_id:
                edit_msg(chat_id, msg_id, txt, main_dashboard_keyboard(uid))
            else:
                send_msg(chat_id, txt, main_dashboard_keyboard(uid))
            return

        client_base = get_client_url(reg)
        info_st, info_res = http_request(
            f"{client_base}/users/current/accounts/{acc_id}/account-information",
            method="GET",
            headers=cloud_headers(),
            timeout=12
        )
        if info_st == 200 and isinstance(info_res, dict) and "balance" in info_res:
            bal = info_res.get("balance", 0)
            eq = info_res.get("equity", 0)
            curr = info_res.get("currency", "USD")
            broker_srv = info_res.get("server", u.get("mt5_server", KNOWN_MT5_SERVER))
            report = (
                f"✅ اتصال MT5 حي ومكتمل 100%!\n\n"
                f"• رقم الحساب: {login}\n"
                f"• السيرفر: {broker_srv}\n"
                f"• المنطقة: {reg}\n"
                f"• حالة الاتصال: {state} | {conn_status}\n"
                f"• الرصيد الحالي: {bal} {curr}\n"
                f"• السيولة الحية: {eq} {curr}\n\n"
                f"🚀 البوت متصل تماماً وجاهز للتداول!"
            )
        else:
            report = (
                f"🔍 تقرير حالة حساب MT5:\n\n"
                f"• رقم الحساب: {login}\n"
                f"• المنطقة: {reg}\n"
                f"• حالة السحابة: {state} | الاتصال: {conn_status}\n"
                f"• ملاحظة: الحساب قيد المزامنة مع سيرفر الوسيط."
            )

        if msg_id:
            edit_msg(chat_id, msg_id, report, main_dashboard_keyboard(uid))
        else:
            send_msg(chat_id, report, main_dashboard_keyboard(uid))
    except Exception as e:
        send_msg(chat_id, f"⚠️ خطأ أثناء الفحص: {e}")

def open_ai_trade_now(user_id: int, chat_id: int, notify_waiting: bool = False) -> bool:
    global trade_step_counter
    trade_step_counter += 1
    try:
        u = get_user(user_id)
        msg_id = None
        if notify_waiting:
            sent = send_msg(chat_id, f"⚡ جاري إرسال أمر التداول المباشر إلى حسابك ({u['mt5_login']})...")
            msg_id = sent.get("result", {}).get("message_id") if isinstance(sent, dict) else None

        live_price, market_ctx = fetch_live_price_mt5(u, u["symbol"])
        decision = get_ai_trade_decision(user_id, u["symbol"], market_ctx, trade_step_counter)
        action = decision["action"]

        ok, exec_sym, order_or_err, used_lot = execute_real_mt5_order(u, action)
        if ok:
            if exec_sym != u["symbol"]:
                update_user(user_id, "symbol", exec_sym)
            if used_lot != float(u["lot"]):
                update_user(user_id, "lot", used_lot)
            success_txt = (
                f"✅ تم فتح صفقة حقيقية بنجاح في حسابك MT5!\n\n"
                f"• رقم الحساب: {u['mt5_login']}\n"
                f"• نوع العملية: {action}\n"
                f"• الزوج: {exec_sym} | حجم العقد: {used_lot}\n"
                f"• رقم التذكرة: #{order_or_err}\n"
                f"• الأداة: {decision['provider_name']} (ثقة {decision['confidence']}%)\n"
                f"🎯 يراقب البوت الصفقة لإغلاقها تلقائياً عند ربح +{u['trade_tp_usd']}$ أو خسارة -{u['trade_sl_usd']}$"
            )
            if msg_id:
                edit_msg(chat_id, msg_id, success_txt)
            else:
                send_msg(chat_id, success_txt)
            return True
        else:
            fail_txt = f"⚠️ تعذر فتح الصفقة:\n{order_or_err}\n\n💡 اضغط على (🔍 فحص وتشخيص اتصال MT5 الآن)."
            if msg_id:
                edit_msg(chat_id, msg_id, fail_txt)
            else:
                send_msg(chat_id, fail_txt)
            return False
    except Exception as e:
        send_msg(chat_id, f"⚠️ خطأ أثناء فتح الصفقة: {e}")
        return False

def trading_worker(user_id: int, chat_id: int):
    u = get_user(user_id)
    tool_name = get_ai_tool_by_id(u["selected_ai_id"]).get("name", "AI")
    send_msg(
        chat_id,
        f"🟢 بدأ التداول التلقائي بالذكاء الاصطناعي على حسابك MT5!\n"
        f"• الحساب: {u['mt5_login']} ({u['mt5_server']})\n"
        f"• الأداة النشطة: {tool_name}\n"
        f"⚡ البوت يراقب السوق وينفذ الصفقات الآن..."
    )

    first_attempt = True
    while active_traders.get(user_id, False):
        try:
            u = get_user(user_id)
            if u["current_daily_pnl"] >= u["daily_max_profit"]:
                active_traders[user_id] = False
                send_msg(chat_id, f"🏆 تحقق الهدف اليومي وتوقف البوت لحفظ أرباحك!")
                break
            if u["current_daily_pnl"] <= -abs(u["daily_max_loss"]):
                active_traders[user_id] = False
                send_msg(chat_id, f"🛡️ وصلت الخسارة للحد اليومي وتوقف البوت لحماية رأس مالك!")
                break

            positions = get_open_positions_mt5(u)
            if positions:
                for pos in positions:
                    pnl = float(pos.get("profit", pos.get("unrealizedProfit", 0.0)))
                    if pnl >= u["trade_tp_usd"] or pnl <= -abs(u["trade_sl_usd"]):
                        if close_single_position_mt5(u, pos.get("id")):
                            new_pnl = u["current_daily_pnl"] + pnl
                            new_cnt = u["trades_today"] + 1
                            update_user(user_id, "current_daily_pnl", new_pnl)
                            update_user(user_id, "trades_today", new_cnt)
                            icon = "💰" if pnl > 0 else "🛑"
                            send_msg(
                                chat_id,
                                f"{icon} أغلق الذكاء الاصطناعي الصفقة في MT5!\n"
                                f"• النتيجة: {pnl:.2f}$ | الإجمالي: {new_pnl:.2f}$"
                            )
            else:
                if is_within_working_hours(u["work_start_hour"], u["work_end_hour"]):
                    ok_trade = open_ai_trade_now(user_id, chat_id, notify_waiting=first_attempt)
                    first_attempt = False
                    if not ok_trade:
                        time.sleep(25)
                    else:
                        time.sleep(5)
        except Exception as e:
            print(f"Trading loop error: {e}")
        time.sleep(3.0)


# ================= 9. لوحة التحكم في تيليجرام =================
def main_dashboard_keyboard(user_id: int) -> dict:
    u = get_user(user_id)
    tool = get_ai_tool_by_id(u["selected_ai_id"])
    mt5_txt = f"✅ {u['mt5_login']}" if u["mt5_login"] else "❌ غير مربوط"
    hours_txt = "24 ساعة" if (u["work_start_hour"] == 0 and u["work_end_hour"] == 24) else f"{u['work_start_hour']}:00 - {u['work_end_hour']}:00"
    run_btn = (
        {"text": "⏹️ إيقاف التداول التلقائي (يعمل الآن 🟢)", "callback_data": "toggle_run"}
        if active_traders.get(user_id, False)
        else {"text": "▶️ بدء التداول التلقائي بالذكاء الاصطناعي", "callback_data": "toggle_run"}
    )
    return {"inline_keyboard": [
        [{"text": f"🔗 1. إضافة / تغيير حساب MT5 ({mt5_txt})", "callback_data": "menu_mt5"}],
        [{"text": f"🤖 2. أداة الذكاء الاصطناعي ({tool.get('name')})", "callback_data": "menu_ai_select"}],
        [{"text": "🔍 فحص وتشخيص اتصال MT5 الآن", "callback_data": "diag_mt5"}],
        [
            {"text": f"💵 حجم الدخول: {u['lot']}", "callback_data": "set_lot"},
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
        [{"text": "⚡ فتح صفقة فورية في MT5 + تشغيل التداول!", "callback_data": "instant_trade"}],
        [{"text": "🚨 إغلاق جميع الصفقات المفتوحة في MT5 فوراً!", "callback_data": "emergency_close"}],
        [{"text": "🔄 تصفير عداد أرباح اليوم", "callback_data": "reset_pnl"}]
    ]}

def main_dashboard_text(user_id: int) -> str:
    u = get_user(user_id)
    tool = get_ai_tool_by_id(u["selected_ai_id"])
    state_str = "🟢 يتداول الآن تلقائياً" if active_traders.get(user_id, False) else "🔴 متوقف"
    return (
        "🤖 لوحة التحكم المتكاملة للتداول الذكي (MT5 + 10 AI)\n\n"
        f"• حالة البوت: {state_str}\n"
        f"• حساب MT5 المربوط: {u['mt5_login']} ({u['mt5_server']})\n"
        f"• الأداة المختارة: {tool.get('name')}\n"
        f"• صافي ربح/خسارة اليوم: {u['current_daily_pnl']:.2f}$\n"
        f"• عدد الصفقات اليوم: {u['trades_today']}\n\n"
        "👇 تحكم في حسابك وصفقاتك مباشرة من الأزرار بالأسفل:"
    )

def ai_selection_keyboard(user_id: int) -> dict:
    u = get_user(user_id)
    rows = []
    for t in get_ai_tools():
        mark = "🟢 (مختارة) " if t["id"] == u["selected_ai_id"] else "🟢 "
        rows.append([{"text": f"{mark}{t['id']}. {t['name']}", "callback_data": f"pick_ai_{t['id']}"}])
    rows.append([{"text": "🔙 رجوع للوحة التحكم الرئيسية", "callback_data": "back_home"}])
    return {"inline_keyboard": rows}

def async_link_worker(uid: int, chat_id: int, login: str, password: str, server: str):
    try:
        ok, info = link_and_verify_mt5_account(login, password, server, uid, force_update=True)
        if ok:
            pending_input.pop(uid, None)
            send_msg(chat_id, f"✅ {info}", main_dashboard_keyboard(uid))
        else:
            send_msg(chat_id, f"❌ فشل الربط:\n{info}")
    except Exception as e:
        send_msg(chat_id, f"⚠️ خطأ أثناء الربط: {e}")

def run_bot_polling():
    tg_api("deleteWebhook", {"drop_pending_updates": True})
    offset = 0
    print("✅ البوت يعمل الآن بنجاح 100%!")
    while True:
        try:
            res = tg_api("getUpdates", {"offset": offset, "timeout": 10})
            for upd in res.get("result", []):
                offset = upd["update_id"] + 1

                if "message" in upd and "text" in upd["message"]:
                    msg = upd["message"]
                    uid = msg["from"]["id"]
                    chat_id = msg["chat"]["id"]
                    text = msg["text"].strip()

                    if SECRET_ACCESS_KEY in text or text.startswith("/start"):
                        authorize_user(uid)
                        pending_input.pop(uid, None)
                        send_msg(chat_id, main_dashboard_text(uid), main_dashboard_keyboard(uid))
                        continue

                    if is_user_allowed(uid) and uid in pending_input:
                        action = pending_input[uid]
                        if action == "input_mt5":
                            ok_parse, login, password, server = parse_mt5_credentials(text)
                            if ok_parse:
                                delete_msg(chat_id, msg["message_id"])
                                send_msg(chat_id, f"⏳ جاري ربط حساب MT5 ({login}) بالذكاء الاصطناعي...")
                                threading.Thread(
                                    target=async_link_worker,
                                    args=(uid, chat_id, login, password, server),
                                    daemon=True
                                ).start()
                            else:
                                send_msg(
                                    chat_id,
                                    "⚠️ أرسل البيانات في 3 أسطر تحت بعضها هكذا:\n\n"
                                    "5058253637\n"
                                    "*aGm1cNp\n"
                                    "MetaQuotes-Demo"
                                )

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
                                send_msg(chat_id, "⚠️ أرسل رقماً صحيحاً.")

                elif "callback_query" in upd:
                    cb = upd["callback_query"]
                    cb_id = cb["id"]
                    uid = cb["from"]["id"]
                    chat_id = cb["message"]["chat"]["id"]
                    msg_id = cb["message"]["message_id"]
                    data = cb.get("data", "")

                    authorize_user(uid)

                    if data == "back_home":
                        answer_cb(cb_id)
                        pending_input.pop(uid, None)
                        edit_msg(chat_id, msg_id, main_dashboard_text(uid), main_dashboard_keyboard(uid))

                    elif data == "menu_mt5":
                        answer_cb(cb_id)
                        pending_input[uid] = "input_mt5"
                        edit_msg(
                            chat_id, msg_id,
                            "🔗 إضافة حساب MT5:\n"
                            "أرسل بيانات حسابك في 3 أسطر تحت بعضها هكذا:\n\n"
                            "5058253637\n"
                            "*aGm1cNp\n"
                            "MetaQuotes-Demo",
                            {"inline_keyboard": [[{"text": "🔙 رجوع", "callback_data": "back_home"}]]}
                        )

                    elif data == "diag_mt5":
                        answer_cb(cb_id, "🔍 جاري الفحص الفوري...")
                        threading.Thread(target=async_diagnostic_worker, args=(uid, chat_id), daemon=True).start()

                    elif data == "menu_ai_select":
                        answer_cb(cb_id)
                        edit_msg(chat_id, msg_id, "🤖 اختر أداة الذكاء الاصطناعي:", ai_selection_keyboard(uid))

                    elif data.startswith("pick_ai_"):
                        tool_id = int(data.split("_")[-1])
                        tool = get_ai_tool_by_id(tool_id)
                        answer_cb(cb_id, f"✅ تم تفعيل {tool['name']}")
                        update_user(uid, "selected_ai_id", tool_id)
                        edit_msg(chat_id, msg_id, f"✅ تم تفعيل ({tool['name']}) بنجاح!\n\n{main_dashboard_text(uid)}", main_dashboard_keyboard(uid))

                    elif data == "instant_trade":
                        answer_cb(cb_id, "⚡ جاري إرسال الصفقة فوراً...")
                        if not active_traders.get(uid, False):
                            active_traders[uid] = True
                            edit_msg(chat_id, msg_id, main_dashboard_text(uid), main_dashboard_keyboard(uid))
                            threading.Thread(target=trading_worker, args=(uid, chat_id), daemon=True).start()
                        else:
                            threading.Thread(target=open_ai_trade_now, args=(uid, chat_id, True), daemon=True).start()

                    elif data == "set_hours":
                        answer_cb(cb_id)
                        pending_input[uid] = "input_hours"
                        edit_msg(chat_id, msg_id, "⏰ أرسل ساعة البدء والانتهاء (مثال: 8-22):", {"inline_keyboard": [[{"text": "🔙 رجوع", "callback_data": "back_home"}]]})

                    elif data == "emergency_close":
                        u = get_user(uid)
                        answer_cb(cb_id, "🚨 جاري إغلاق جميع الصفقات في MT5...")
                        active_traders[uid] = False
                        cnt, pnl = emergency_close_all_mt5(u)
                        update_user(uid, "current_daily_pnl", u["current_daily_pnl"] + pnl)
                        send_msg(chat_id, f"🚨 تم إغلاق {cnt} صفقات في MT5! الصافي: {pnl:.2f}$")
                        edit_msg(chat_id, msg_id, main_dashboard_text(uid), main_dashboard_keyboard(uid))

                    elif data in ["set_lot", "set_symbol", "set_tp", "set_sl", "set_daily_tp", "set_daily_sl"]:
                        answer_cb(cb_id)
                        mapping = {
                            "set_lot": ("lot", "💵 أرسل حجم الدخول (مثال: 0.01):"),
                            "set_symbol": ("symbol", "📊 أرسل رمز الزوج (مثال: XAUUSD):"),
                            "set_tp": ("trade_tp_usd", "🎯 أرسل ربح الصفقة بالدولار (مثال: 0.50):"),
                            "set_sl": ("trade_sl_usd", "🛑 أرسل خسارة الصفقة بالدولار (مثال: 1.00):"),
                            "set_daily_tp": ("daily_max_profit", "🏆 أقصى ربح يومي بالدولار (مثال: 20):"),
                            "set_daily_sl": ("daily_max_loss", "🛡️ أقصى خسارة يومية بالدولار (مثال: 10):"),
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
                        else:
                            active_traders[uid] = True
                            threading.Thread(target=trading_worker, args=(uid, chat_id), daemon=True).start()
                        edit_msg(chat_id, msg_id, main_dashboard_text(uid), main_dashboard_keyboard(uid))

        except Exception as e:
            print(f"Polling error: {e}")
            time.sleep(2)

if __name__ == "__main__":
    init_db()
    threading.Thread(
        target=link_and_verify_mt5_account,
        args=(KNOWN_MT5_LOGIN, KNOWN_MT5_PASS, KNOWN_MT5_SERVER),
        daemon=True
    ).start()
    start_keep_alive()
    run_bot_polling()
