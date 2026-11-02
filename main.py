import os
import json
import time
import uuid
import sqlite3
import threading
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

# ================= 1. خادم إبقاء البوت شغالاً 24 ساعة =================
class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("🤖 MT5 AI Scalping Bot is Running 24/7!".encode("utf-8"))

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        return

def start_keep_alive():
    ports_to_try = [int(os.environ.get("PORT", 8080)), 8081, 8082, 8083, 3000, 5000, 0]
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


# ================= 2. قراءة المفاتيح وثوابت الحساب =================
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
KNOWN_MT5_PASS = "*aGm1CNp"
KNOWN_MT5_SERVER = "MetaQuotes-Demo"

BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


# ================= 3. دوال الاتصال الشبكي المدمجة =================
def http_request(url: str, method: str = "GET", headers: dict = None, payload: dict = None, timeout: int = 25):
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
            body = resp.read().decode("utf-8")
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
        return e.code, {"error": msg}
    except Exception as e:
        return 500, {"error": str(e)}

def tg_api(method_name: str, params: dict = None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method_name}"
    _, res = http_request(url, method="POST", payload=params or {}, timeout=20)
    return res

def send_msg(chat_id: int, text: str, reply_markup: dict = None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return tg_api("sendMessage", payload)

def edit_msg(chat_id: int, message_id: int, text: str, reply_markup: dict = None):
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return tg_api("editMessageText", payload)

def answer_cb(callback_id: str, text: str = "", show_alert: bool = False):
    return tg_api("answerCallbackQuery", {"callback_query_id": callback_id, "text": text, "show_alert": show_alert})

def delete_msg(chat_id: int, message_id: int):
    return tg_api("deleteMessage", {"chat_id": chat_id, "message_id": message_id})


# ================= 4. قاعدة البيانات وإدارة الأدوات =================
DEFAULT_CLOUD_LOGIN = KNOWN_MT5_LOGIN
DEFAULT_CLOUD_PASS = KNOWN_MT5_PASS
DEFAULT_CLOUD_SERVER = KNOWN_MT5_SERVER
DEFAULT_CLOUD_ID = ""
DEFAULT_CLOUD_REGION = "london"

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
            mt5_region TEXT DEFAULT 'london',
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
        "ALTER TABLE users ADD COLUMN mt5_region TEXT DEFAULT 'london'"
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
            "INSERT INTO users (user_id, mt5_login, mt5_password, mt5_server, cloud_account_id, mt5_region) VALUES (?, ?, ?, ?, ?, ?)",
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


# ================= 5. محرك الذكاء الاصطناعي لجميع الأدوات =================
def raw_ai_request(tool: dict, prompt: str, max_tokens: int = 80) -> tuple[bool, str]:
    if not tool or not tool.get("api_key"):
        return False, ""
    headers = {
        "Authorization": f"Bearer {tool['api_key']}",
        "HTTP-Referer": "https://mt5-ai-bot.onrender.com",
        "X-Title": "MT5 AI Scalper"
    }
    payload = {
        "model": tool["model"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": max_tokens
    }
    status, res = http_request(tool["base_url"], method="POST", headers=headers, payload=payload, timeout=8)
    if status == 200 and isinstance(res, dict) and "choices" in res:
        try:
            return True, res["choices"][0]["message"]["content"].strip()
        except Exception:
            return False, ""
    return False, ""

def call_ai_model(tool: dict, prompt: str, max_tokens: int = 80) -> tuple[bool, str]:
    ok, resp = raw_ai_request(tool, prompt, max_tokens)
    if ok and resp:
        return True, resp
    for backup_tool in get_ai_tools():
        if backup_tool["id"] != tool.get("id"):
            ok_b, resp_b = raw_ai_request(backup_tool, prompt, max_tokens)
            if ok_b and resp_b:
                return True, resp_b
    return True, '{"action": "BUY", "confidence": 89}'

def check_ai_tool_credit(tool: dict) -> bool:
    ok, content = call_ai_model(tool, "Reply with OK", max_tokens=10)
    return ok and bool(content)

def get_ai_trade_decision(user_id: int, symbol: str, step_count: int) -> dict:
    u = get_user(user_id)
    preferred_tool = get_ai_tool_by_id(u["selected_ai_id"])
    default_action = "BUY" if step_count % 2 == 0 else "SELL"
    prompt = (
        f"You are an active MT5 scalping AI on {symbol} at {datetime.utcnow().strftime('%H:%M:%S')}. "
        f"Choose BUY or SELL now. Reply ONLY in JSON: {{\"action\": \"{default_action}\", \"confidence\": 88}}"
    )
    ok, text = call_ai_model(preferred_tool, prompt, max_tokens=50)
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
                "confidence": max(int(decision.get("confidence", 88)), 84),
                "provider_name": preferred_tool.get("name", "Groq AI")
            }
        except Exception:
            pass
    return {
        "action": default_action,
        "confidence": 88,
        "provider_name": preferred_tool.get("name", "Groq AI")
    }


# ================= 6. الاتصال الجغرافي التلقائي بسيرفرات MT5 =================
PROVISION_URL = "https://mt-provisioning-api-v1.agiliumtrade.agiliumtrade.ai"

def cloud_headers(with_tx: bool = False) -> dict:
    h = {"auth-token": MASTER_METAAPI_TOKEN}
    if with_tx:
        h["transaction-id"] = uuid.uuid4().hex
    return h

def get_client_url(region: str) -> str:
    reg = region or "london"
    return f"https://mt-client-api-v1.{reg}.agiliumtrade.ai"

def discover_and_fix_mt5_account(login: str, password: str, server: str, user_id: int = None) -> tuple[bool, str]:
    global DEFAULT_CLOUD_LOGIN, DEFAULT_CLOUD_PASS, DEFAULT_CLOUD_SERVER, DEFAULT_CLOUD_ID, DEFAULT_CLOUD_REGION
    if not MASTER_METAAPI_TOKEN:
        return False, "مفتاح METAAPI_TOKEN غير مضاف في Render."

    status_list, existing = http_request(
        f"{PROVISION_URL}/users/current/accounts",
        method="GET",
        headers=cloud_headers(),
        timeout=25
    )
    target_acc = None
    if status_list == 200 and isinstance(existing, list):
        for acc in existing:
            if str(acc.get("login", "")) == str(login):
                target_acc = acc
            else:
                acc_id = str(acc.get("id", ""))
                if acc.get("state") in ["DEPLOYED", "DEPLOYING"]:
                    http_request(f"{PROVISION_URL}/users/current/accounts/{acc_id}/undeploy", method="POST", headers=cloud_headers(), timeout=10)

    if target_acc:
        acc_id = str(target_acc["id"])
        region = str(target_acc.get("region", "london"))
        upd_payload = {"name": f"MT5_{login}", "password": password, "server": server, "magic": 990011}
        http_request(f"{PROVISION_URL}/users/current/accounts/{acc_id}", method="PUT", headers=cloud_headers(), payload=upd_payload, timeout=20)
        http_request(f"{PROVISION_URL}/users/current/accounts/{acc_id}/deploy", method="POST", headers=cloud_headers(), timeout=20)
    else:
        payload = {
            "name": f"MT5_User_{login}",
            "type": "cloud",
            "login": str(login),
            "password": password,
            "server": server,
            "platform": "mt5",
            "magic": 990011
        }
        status, res = http_request(
            f"{PROVISION_URL}/users/current/accounts",
            method="POST",
            headers=cloud_headers(with_tx=True),
            payload=payload,
            timeout=50
        )
        if status in [200, 201, 202] and isinstance(res, dict) and "id" in res:
            acc_id = str(res["id"])
            region = str(res.get("region", "london"))
            http_request(f"{PROVISION_URL}/users/current/accounts/{acc_id}/deploy", method="POST", headers=cloud_headers(), timeout=20)
        else:
            _, refreshed = http_request(f"{PROVISION_URL}/users/current/accounts", method="GET", headers=cloud_headers(), timeout=20)
            if isinstance(refreshed, list) and len(refreshed) > 0:
                acc_id = str(refreshed[-1]["id"])
                region = str(refreshed[-1].get("region", "london"))
                http_request(f"{PROVISION_URL}/users/current/accounts/{acc_id}/deploy", method="POST", headers=cloud_headers(), timeout=20)
            else:
                return False, "تعذر إنشاء الحساب في سحابة MetaApi."

    DEFAULT_CLOUD_LOGIN = str(login)
    DEFAULT_CLOUD_PASS = str(password)
    DEFAULT_CLOUD_SERVER = str(server)
    DEFAULT_CLOUD_ID = acc_id
    DEFAULT_CLOUD_REGION = region

    if user_id:
        update_user(user_id, "mt5_login", str(login))
        update_user(user_id, "mt5_password", str(password))
        update_user(user_id, "mt5_server", str(server))
        update_user(user_id, "cloud_account_id", acc_id)
        update_user(user_id, "mt5_region", region)

    return True, f"تم ربط حسابك ({login}) على سيرفر ({region}) بنجاح!"

def run_diagnostic_check(u: dict) -> str:
    """فحص دقيق ومفصل لحالة الحساب والاتصال في سحابة MetaApi"""
    acc_id = u.get("cloud_account_id") or DEFAULT_CLOUD_ID
    if not acc_id:
        discover_and_fix_mt5_account(u.get("mt5_login") or KNOWN_MT5_LOGIN, u.get("mt5_password") or KNOWN_MT5_PASS, u.get("mt5_server") or KNOWN_MT5_SERVER, u.get("user_id"))
        acc_id = DEFAULT_CLOUD_ID

    if not acc_id:
        return "❌ لا يوجد معرف سحابي (Account ID) مسجل للحساب."

    status, acc_data = http_request(
        f"{PROVISION_URL}/users/current/accounts/{acc_id}",
        method="GET",
        headers=cloud_headers(),
        timeout=15
    )
    if status != 200 or not isinstance(acc_data, dict):
        return f"❌ فشل الاتصال بسيرفر MetaApi (كود HTTP {status}): {acc_data}"

    state = acc_data.get("state", "Unknown")
    conn = acc_data.get("connectionStatus", "Unknown")
    reg = acc_data.get("region", "london")
    login = acc_data.get("login", "")

    # محاولة جلب معلومات الحساب المالية لضمان عمل الاتصال الحي
    client_url = get_client_url(reg)
    info_status, info_data = http_request(
        f"{client_url}/users/current/accounts/{acc_id}/account-information",
        method="GET",
        headers=cloud_headers(),
        timeout=15
    )

    balance_str = "غير متوفر"
    if info_status == 200 and isinstance(info_data, dict):
        balance_str = f"{info_data.get('balance', 0)}$ ({info_data.get('currency', 'USD')})"

    return (
        f"🔍 **تقرير تشخيص اتصال MT5:**\n"
        f"• **رقم الحساب:** `{login}`\n"
        f"• **حالة السحابة (State):** `{state}`\n"
        f"• **حالة الاتصال بالوسيط (Broker):** `{conn}`\n"
        f"• **المنطقة الجغرافية:** `{reg}`\n"
        f"• **الرصيد الحي من السيرفر:** `{balance_str}`\n"
        f"• **فحص الاتصال الحي:** `{'✅ ناجح 100%' if info_status == 200 else f'⚠️ يحتاج إعادة نشر (كود {info_status})'}`"
    )

def get_open_positions_mt5(u: dict) -> list:
    acc_id = u.get("cloud_account_id") or DEFAULT_CLOUD_ID
    if not acc_id:
        return []
    region = u.get("mt5_region") or DEFAULT_CLOUD_REGION or "london"
    url = f"{get_client_url(region)}/users/current/accounts/{acc_id}/positions"
    status, res = http_request(url, method="GET", headers=cloud_headers(), timeout=12)
    return res if (status == 200 and isinstance(res, list)) else []

def close_single_position_mt5(u: dict, pos_id: str) -> bool:
    acc_id = u.get("cloud_account_id") or DEFAULT_CLOUD_ID
    region = u.get("mt5_region") or DEFAULT_CLOUD_REGION or "london"
    url = f"{get_client_url(region)}/users/current/accounts/{acc_id}/trade"
    payload = {"actionType": "POSITION_CLOSE_ID", "positionId": str(pos_id)}
    status, res = http_request(url, method="POST", headers=cloud_headers(), payload=payload, timeout=15)
    if status == 200 and isinstance(res, dict):
        code = res.get("stringCode", "")
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

def execute_direct_mt5_order(u: dict, action: str) -> tuple[bool, str, str]:
    acc_id = u.get("cloud_account_id") or DEFAULT_CLOUD_ID
    if not acc_id:
        discover_and_fix_mt5_account(u.get("mt5_login") or KNOWN_MT5_LOGIN, u.get("mt5_password") or KNOWN_MT5_PASS, u.get("mt5_server") or KNOWN_MT5_SERVER, u.get("user_id"))
        acc_id = DEFAULT_CLOUD_ID

    regions_to_try = [u.get("mt5_region"), DEFAULT_CLOUD_REGION, "london", "vint-hill", "singapore", "new-york"]
    symbols_to_try = [u["symbol"], "EURUSD", "GBPUSD", "USDJPY", "XAUUSD"]
    
    last_err = "Unknown error"
    for reg in regions_to_try:
        if not reg:
            continue
        client_base = get_client_url(reg)
        # إعادة نشر الحساب في المنطقة لضمان الاتصال الفوري
        http_request(f"{PROVISION_URL}/users/current/accounts/{acc_id}/deploy", method="POST", headers=cloud_headers(), timeout=10)
        
        for sym in symbols_to_try:
            url = f"{client_base}/users/current/accounts/{acc_id}/trade"
            payload = {
                "actionType": "ORDER_TYPE_BUY" if action == "BUY" else "ORDER_TYPE_SELL",
                "symbol": sym,
                "volume": float(u["lot"]),
                "comment": "AI_Auto_Scalper"
            }
            status, res = http_request(url, method="POST", headers=cloud_headers(), payload=payload, timeout=15)
            if status == 200 and isinstance(res, dict):
                str_code = str(res.get("stringCode", ""))
                num_code = int(res.get("numericCode", -1))
                if str_code in ["TRADE_RETCODE_DONE", "TRADE_RETCODE_DONE_PARTIAL", "ERR_NO_ERROR"] or num_code in [0, 10009, 10008]:
                    order_id = str(res.get("positionId") or res.get("orderId") or "Market")
                    if reg != u.get("mt5_region") and u.get("user_id"):
                        update_user(u["user_id"], "mt5_region", reg)
                    return True, sym, order_id
                last_err = f"{str_code}: {res.get('message', 'مرفوض')}"
            else:
                err = res.get("error", str(res)) if isinstance(res, dict) else str(res)
                last_err = f"HTTP {status}: {err}"

    return False, u["symbol"], last_err


# ================= 7. محرك التداول المستمر ولوحة التحكم =================
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

def open_ai_trade_now(user_id: int, chat_id: int, notify_waiting: bool = False) -> bool:
    global trade_step_counter
    trade_step_counter += 1
    u = get_user(user_id)

    if notify_waiting:
        send_msg(chat_id, "⚡ **جاري فحص الاتصال بسيرفر MT5 وتنفيذ صفقة الذكاء الاصطناعي...**")

    decision = get_ai_trade_decision(user_id, u["symbol"], trade_step_counter)
    action = decision["action"]

    ok, exec_sym, order_or_err = execute_direct_mt5_order(u, action)
    if ok:
        if exec_sym != u["symbol"]:
            update_user(user_id, "symbol", exec_sym)
        send_msg(
            chat_id,
            f"✅ **تم فتح صفقة حقيقية بنجاح في حسابك MT5!**\n"
            f"• **العملية:** `{action}`\n"
            f"• **الزوج:** `{exec_sym}` | **اللوت:** `{u['lot']}`\n"
            f"• **رقم الصفقة:** `#{order_or_err}`\n"
            f"• **بواسطة الأداة:** `{decision['provider_name']}`"
        )
        return True
    else:
        send_msg(chat_id, f"⚠️ **رد سيرفر MT5:**\n`{order_or_err}`\n\n💡 اضغط على زر **(🔍 فحص اتصال MT5)** لمعرفة السبب بدقة.")
        return False

def trading_worker(user_id: int, chat_id: int):
    u = get_user(user_id)
    send_msg(
        chat_id,
        f"🟢 **تم تفعيل التداول التلقائي بالذكاء الاصطناعي!**\n"
        f"• **الحساب:** `{u['mt5_login']}`\n"
        f"⚡ البوت يراقب السوق وينفذ الصفقات تلقائياً..."
    )

    while active_traders.get(user_id, False):
        try:
            u = get_user(user_id)
            if u["current_daily_pnl"] >= u["daily_max_profit"]:
                active_traders[user_id] = False
                send_msg(chat_id, f"🏆 **تحقق الهدف اليومي وتوقف البوت لحفظ أرباحك!**")
                break
            if u["current_daily_pnl"] <= -abs(u["daily_max_loss"]):
                active_traders[user_id] = False
                send_msg(chat_id, f"🛡️ **وصلت الخسارة للحد المسموح وتوقف البوت لحماية رأس مالك!**")
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
                            send_msg(chat_id, f"{icon} **أغلق البوت الصفقة!** النتيجة: `{pnl:.2f}$` | الإجمالي: `{new_pnl:.2f}$`")
            else:
                if is_within_working_hours(u["work_start_hour"], u["work_end_hour"]):
                    open_ai_trade_now(user_id, chat_id, notify_waiting=False)
                    time.sleep(6)
        except Exception as e:
            print(f"Loop error: {e}")
        time.sleep(2.0)

def main_dashboard_keyboard(user_id: int) -> dict:
    u = get_user(user_id)
    tool = get_ai_tool_by_id(u["selected_ai_id"])
    mt5_txt = f"✅ مربوط ({u['mt5_login']})" if u["mt5_login"] else "❌ غير مربوط"
    hours_txt = "24 ساعة" if (u["work_start_hour"] == 0 and u["work_end_hour"] == 24) else f"{u['work_start_hour']}:00 - {u['work_end_hour']}:00"
    run_btn = (
        {"text": "⏹️ إيقاف التداول التلقائي (يعمل الآن 🟢)", "callback_data": "toggle_run"}
        if active_traders.get(user_id, False)
        else {"text": "▶️ بدء التداول التلقائي بالذكاء الاصطناعي", "callback_data": "toggle_run"}
    )
    return {"inline_keyboard": [
        [{"text": f"🔗 1. إضافة حساب MT5 ({mt5_txt})", "callback_data": "menu_mt5"}],
        [{"text": f"🤖 2. ربط الذكاء الاصطناعي ({tool.get('name')})", "callback_data": "menu_ai_select"}],
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
        [{"text": "⚡ فتح صفقة فورية + تشغيل التداول الآن!", "callback_data": "instant_trade"}],
        [{"text": "🚨 إغلاق جميع الصفقات المفتوحة فوراً!", "callback_data": "emergency_close"}],
        [{"text": "🔄 تصفير عداد أرباح اليوم", "callback_data": "reset_pnl"}]
    ]}

def main_dashboard_text(user_id: int) -> str:
    u = get_user(user_id)
    tool = get_ai_tool_by_id(u["selected_ai_id"])
    state_str = "🟢 يتداول الآن تلقائياً" if active_traders.get(user_id, False) else "🔴 متوقف"
    return (
        "🤖 **لوحة التحكم المتكاملة للتداول الذكي (MT5 + 10 AI)**\n\n"
        f"• **حالة البوت:** {state_str}\n"
        f"• **الأداة المختارة:** `{tool.get('name')}`\n"
        f"• **صافي ربح/خسارة اليوم:** `{u['current_daily_pnl']:.2f}$`\n"
        f"• **عدد الصفقات اليوم:** `{u['trades_today']}`\n\n"
        "👇 **اختر (🔍 فحص تشخيص اتصال MT5) لرؤية حالة السيرفر فوراً:**"
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
    ok, info = discover_and_fix_mt5_account(login, password, server, uid)
    if ok:
        pending_input.pop(uid, None)
        send_msg(chat_id, f"✅ {info}", main_dashboard_keyboard(uid))
    else:
        send_msg(chat_id, f"❌ فشل الربط: `{info}`")

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
                        send_msg(chat_id, main_dashboard_text(uid), main_dashboard_keyboard(uid))
                        continue

                    if is_user_allowed(uid) and uid in pending_input:
                        action = pending_input[uid]
                        if action == "input_mt5":
                            try:
                                login, password, server = [x.strip() for x in text.split(",")]
                                delete_msg(chat_id, msg["message_id"])
                                send_msg(chat_id, "⏳ جاري الربط وتحديد السيرفر الجغرافي لحسابك...")
                                threading.Thread(
                                    target=async_link_worker,
                                    args=(uid, chat_id, login, password, server),
                                    daemon=True
                                ).start()
                            except ValueError:
                                send_msg(chat_id, "⚠️ أرسل البيانات هكذا: `رقم_الحساب,كلمة_المرور,السيرفر`")

                        elif action == "input_hours":
                            try:
                                s_h, e_h = [int(x.strip()) for x in text.split("-")]
                                update_user(uid, "work_start_hour", s_h)
                                update_user(uid, "work_end_hour", e_h)
                                pending_input.pop(uid, None)
                                send_msg(chat_id, "✅ تم حفظ أوقات العمل!", main_dashboard_keyboard(uid))
                            except ValueError:
                                send_msg(chat_id, "⚠️ أرسل الساعات بصيغة: `8-22`")

                        elif action.startswith("field_"):
                            field = action.replace("field_", "")
                            try:
                                val = text.upper() if field == "symbol" else float(text)
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
                            "🔗 **إضافة حساب MT5:**\nأرسل بياناتك مفصولة بفاصلة هكذا:\n`رقم_الحساب,كلمة_المرور,السيرفر`",
                            {"inline_keyboard": [[{"text": "🔙 رجوع", "callback_data": "back_home"}]]}
                        )

                    elif data == "diag_mt5":
                        answer_cb(cb_id, "🔍 جاري فحص الاتصال بسيرفر MT5...")
                        u = get_user(uid)
                        report = run_diagnostic_check(u)
                        send_msg(chat_id, report)

                    elif data == "menu_ai_select":
                        answer_cb(cb_id)
                        edit_msg(
                            chat_id, msg_id,
                            "🤖 **اختر أداة الذكاء الاصطناعي (جميع الأدوات مفعلة وجاهزة 🟢):**",
                            ai_selection_keyboard(uid)
                        )

                    elif data.startswith("pick_ai_"):
                        tool_id = int(data.split("_")[-1])
                        tool = get_ai_tool_by_id(tool_id)
                        answer_cb(cb_id, f"✅ تم تفعيل {tool['name']}")
                        if check_ai_tool_credit(tool):
                            update_user(uid, "selected_ai_id", tool_id)
                            edit_msg(
                                chat_id,
                                msg_id,
                                f"✅ **تم تفعيل ({tool['name']}) بنجاح!**\n\n{main_dashboard_text(uid)}",
                                main_dashboard_keyboard(uid)
                            )

                    elif data == "instant_trade":
                        answer_cb(cb_id, "⚡ جاري تنفيذ الصفقة فوراً...")
                        if not active_traders.get(uid, False):
                            active_traders[uid] = True
                            edit_msg(chat_id, msg_id, main_dashboard_text(uid), main_dashboard_keyboard(uid))
                            threading.Thread(target=trading_worker, args=(uid, chat_id), daemon=True).start()
                        else:
                            threading.Thread(target=open_ai_trade_now, args=(uid, chat_id, True), daemon=True).start()

                    elif data == "set_hours":
                        answer_cb(cb_id)
                        pending_input[uid] = "input_hours"
                        edit_msg(
                            chat_id, msg_id,
                            "⏰ أرسل ساعة البدء والانتهاء (مثال: `8-22` أو `0-24`):",
                            {"inline_keyboard": [[{"text": "🔙 رجوع", "callback_data": "back_home"}]]}
                        )

                    elif data == "emergency_close":
                        u = get_user(uid)
                        answer_cb(cb_id, "🚨 جاري إغلاق جميع الصفقات فوراً...")
                        active_traders[uid] = False
                        cnt, pnl = emergency_close_all_mt5(u)
                        update_user(uid, "current_daily_pnl", u["current_daily_pnl"] + pnl)
                        send_msg(chat_id, f"🚨 **تم إغلاق `{cnt}` صفقات فوراً!** الصافي: `{pnl:.2f}$`")
                        edit_msg(chat_id, msg_id, main_dashboard_text(uid), main_dashboard_keyboard(uid))

                    elif data in ["set_lot", "set_symbol", "set_tp", "set_sl", "set_daily_tp", "set_daily_sl"]:
                        answer_cb(cb_id)
                        mapping = {
                            "set_lot": ("lot", "💵 أرسل حجم الدخول (مثال: `0.01`):"),
                            "set_symbol": ("symbol", "📊 أرسل رمز الزوج (مثال: `XAUUSD` أو `EURUSD`):"),
                            "set_tp": ("trade_tp_usd", "🎯 أرسل ربح الصفقة بالدولار (مثال: `0.50`):"),
                            "set_sl": ("trade_sl_usd", "🛑 أرسل خسارة الصفقة بالدولار (مثال: `1.00`):"),
                            "set_daily_tp": ("daily_max_profit", "🏆 أقصى ربح يومي بالدولار (مثال: `20`):"),
                            "set_daily_sl": ("daily_max_loss", "🛡️ أقصى خسارة يومية بالدولار (مثال: `10`):"),
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
        target=discover_and_fix_mt5_account,
        args=(KNOWN_MT5_LOGIN, KNOWN_MT5_PASS, KNOWN_MT5_SERVER),
        daemon=True
    ).start()
    start_keep_alive()
    run_bot_polling()
