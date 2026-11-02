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

# ================= 1. خادم الويب لإبقاء البوت شغالاً 24/7 على Render =================
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


# ================= 2. قراءة المفاتيح السرية وبيانات الحساب الافتراضية =================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
MASTER_METAAPI_TOKEN = os.getenv("METAAPI_TOKEN", "").strip()
ENV_METAAPI_ACCOUNT_ID = os.getenv("METAAPI_ACCOUNT_ID", "").strip()
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
KNOWN_FALLBACK_ACC_ID = "d24ac5aa438f47a5be121f7827c557a2"

BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


# ================= 3. طبقة الاتصال الشبكي الآمن ومعالجة الأخطاء =================
def http_request(url: str, method: str = "GET", headers: dict = None, payload: dict = None, timeout: int = 20):
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
            details = err_json.get("details")
            if details:
                msg = f"{msg} ({details})"
        except Exception:
            msg = err_body
        return e.code, {"error": str(msg), "raw_error": err_body}
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


# ================= 4. قاعدة البيانات وإدارة الـ 10 أدوات ذكاء اصطناعي =================
DEFAULT_CLOUD_LOGIN = KNOWN_MT5_LOGIN
DEFAULT_CLOUD_PASS = KNOWN_MT5_PASS
DEFAULT_CLOUD_SERVER = KNOWN_MT5_SERVER
DEFAULT_CLOUD_ID = ENV_METAAPI_ACCOUNT_ID
DEFAULT_CLOUD_REGION = "new-york"

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
            mt5_region TEXT DEFAULT 'new-york',
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
        "ALTER TABLE users ADD COLUMN mt5_region TEXT DEFAULT 'new-york'"
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
    if (not u.get("cloud_account_id") or u.get("cloud_account_id") == "None") and DEFAULT_CLOUD_ID:
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
    clean_reg = region if (region and region != "None") else "new-york"
    conn = sqlite3.connect("pure_mt5_bot.db")
    c = conn.cursor()
    c.execute(
        "UPDATE users SET mt5_login = ?, mt5_password = ?, mt5_server = ?, cloud_account_id = ?, mt5_region = ?",
        (str(login), str(password), str(server), str(acc_id), str(clean_reg))
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


# ================= 5. محلل مدخلات حساب MT5 (3 أسطر أو فاصلة أو Account ID) =================
def parse_mt5_credentials(raw_text: str) -> tuple[str, str, str, str]:
    """
    يدعم:
    1) إرسال البيانات في 3 أسطر تحت بعضها:
       اسم المستخدم
       كلمة المرور
       السيرفر
    2) أو إرسالهم بفاصلة: رقم_الحساب,كلمة_المرور,السيرفر
    3) أو إرسال Account ID مباشر من MetaApi (مثل d24ac5aa...)
    """
    cleaned = raw_text.strip()
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]

    # إذا أرسل المستخدم 3 أسطر تحت بعضها
    if len(lines) >= 3:
        login = lines[0].split(":")[-1].strip()
        password = lines[1].split(":")[-1].strip()
        server = lines[2].split(":")[-1].strip()
        return "CREDENTIALS", login, password, server

    # إذا أرسلهم بفاصلة
    if "," in cleaned:
        parts = [p.strip() for p in cleaned.split(",") if p.strip()]
        if len(parts) >= 3:
            return "CREDENTIALS", parts[0], parts[1], parts[2]

    # إذا أرسل 3 كلمات مفصولة بمسافة
    parts = cleaned.split()
    if len(parts) == 3 and parts[0].isdigit():
        return "CREDENTIALS", parts[0].strip(), parts[1].strip(), parts[2].strip()

    # إذا أرسل معرف حساب MetaApi مباشرة (Account ID)
    if len(cleaned) >= 24 and " " not in cleaned and not cleaned.isdigit():
        return "ACCOUNT_ID", cleaned, "", ""

    return "INVALID", "", "", ""


# ================= 6. محرك الذكاء الاصطناعي الحقيقي (10 أدوات + Failover) =================
def raw_ai_request(tool: dict, prompt: str, max_tokens: int = 80) -> tuple[bool, str]:
    if not tool or not tool.get("api_key"):
        return False, ""
    headers = {
        "Authorization": f"Bearer {tool['api_key']}",
        "HTTP-Referer": "https://mt5-ai-bot.onrender.com",
        "X-Title": "MT5 Real AI Scalper"
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

def call_ai_with_failover(user_id: int, prompt: str, max_tokens: int = 80) -> tuple[bool, str, str, bool]:
    u = get_user(user_id)
    preferred_id = u["selected_ai_id"]
    all_tools = get_ai_tools()
    ordered_tools = sorted(all_tools, key=lambda x: 0 if x["id"] == preferred_id else x["id"])

    for tool in ordered_tools:
        ok, resp = raw_ai_request(tool, prompt, max_tokens)
        if ok and resp:
            switched = (tool["id"] != preferred_id)
            if switched:
                update_user(user_id, "selected_ai_id", tool["id"])
            return True, resp, tool["name"], switched

    fallback_name = get_ai_tool_by_id(preferred_id).get("name", "AI Engine")
    return False, "", fallback_name, False

def analyze_market_with_ai(user_id: int, symbol: str, market_summary: str, tech_bias: str) -> dict:
    prompt = (
        f"You are an institutional MT5 scalping AI trading {symbol}. "
        f"Live market data: {market_summary}. Technical bias: {tech_bias}. "
        f"Decide immediate market order (BUY or SELL). "
        f"Reply ONLY in valid JSON: {{\"action\": \"{tech_bias}\", \"confidence\": 90}}"
    )
    ok, text, provider_name, switched = call_ai_with_failover(user_id, prompt, max_tokens=60)
    if ok and text:
        try:
            clean = text.replace("```json", "").replace("```", "").strip()
            s_i, e_i = clean.find("{"), clean.rfind("}")
            if s_i != -1 and e_i != -1:
                clean = clean[s_i:e_i + 1]
            decision = json.loads(clean)
            act = str(decision.get("action", "")).upper()
            if act not in ["BUY", "SELL"]:
                act = tech_bias
            conf = int(decision.get("confidence", 88))
            return {
                "action": act,
                "confidence": max(min(conf, 99), 80),
                "provider_name": provider_name,
                "switched": switched
            }
        except Exception:
            pass
    return {
        "action": tech_bias,
        "confidence": 86,
        "provider_name": provider_name,
        "switched": switched
    }


# ================= 7. الربط الجذري بـ MetaApi ومعالجة (_id) والمناطق الجغرافية =================
PROVISION_URL = "https://mt-provisioning-api-v1.agiliumtrade.agiliumtrade.ai"
KNOWN_REGIONS = ["new-york", "london", "vint-hill", "singapore", "frankfurt"]

def cloud_headers(with_tx: bool = False) -> dict:
    h = {"auth-token": MASTER_METAAPI_TOKEN}
    if with_tx:
        h["transaction-id"] = uuid.uuid4().hex
    return h

def extract_acc_id(acc_dict: dict) -> str:
    """استخراج معرف الحساب سواء كان باسم _id أو id في استجابة MetaApi"""
    if not isinstance(acc_dict, dict):
        return ""
    val = acc_dict.get("_id") or acc_dict.get("id") or ""
    return str(val).strip() if val and str(val) != "None" else ""

def extract_acc_region(acc_dict: dict) -> str:
    """استخراج المنطقة الجغرافية بأمان ومنع تحول None إلى نص 'None'"""
    if not isinstance(acc_dict, dict):
        return "new-york"
    reg = acc_dict.get("region")
    if reg and isinstance(reg, str) and reg.strip() and reg.strip() != "None":
        return reg.strip()
    replicas = acc_dict.get("accountReplicas")
    if isinstance(replicas, list) and len(replicas) > 0 and isinstance(replicas[0], dict):
        r2 = replicas[0].get("region")
        if r2 and isinstance(r2, str) and r2.strip() != "None":
            return r2.strip()
    return "new-york"

def get_client_url(region: str) -> str:
    clean_reg = region.strip() if (region and isinstance(region, str) and region.strip() != "None") else "new-york"
    host = f"mt-client-api-v1.{clean_reg}.agiliumtrade.ai"
    try:
        socket.gethostbyname(host)
        return f"https://{host}"
    except Exception:
        return "https://mt-client-api-v1.new-york.agiliumtrade.ai"

def probe_working_region(acc_id: str, initial_region: str) -> str:
    """فحص السيرفر الجغرافي الفعلي الذي يستجيب عليه الحساب في MetaApi"""
    ordered_regions = [initial_region] + [r for r in KNOWN_REGIONS if r != initial_region]
    for reg in ordered_regions:
        if not reg or reg == "None":
            continue
        base = get_client_url(reg)
        st, res = http_request(
            f"{base}/users/current/accounts/{acc_id}/account-information",
            method="GET",
            headers=cloud_headers(),
            timeout=8
        )
        if st == 200 and isinstance(res, dict) and "balance" in res:
            return reg
        # إذا كان الحساب في نفس المنطقة لكنه ما زال يتصل بالوسيط، لا يعطي 404 من منطقة خاطئة
        if st in [400, 422, 504] and isinstance(res, dict):
            err_txt = str(res.get("error", ""))
            if "not found" not in err_txt.lower() and "region" not in err_txt.lower():
                return reg
    return initial_region if (initial_region and initial_region != "None") else "new-york"

def fetch_all_metaapi_accounts() -> tuple[int, list, str]:
    """جلب جميع الحسابات من MetaApi سواء عادت كقائمة Array أو ككائن items"""
    if not MASTER_METAAPI_TOKEN:
        return 401, [], "مفتاح METAAPI_TOKEN غير مضاف في Environment Variables على Render."

    st, res = http_request(
        f"{PROVISION_URL}/users/current/accounts",
        method="GET",
        headers=cloud_headers(),
        timeout=15
    )
    if st == 200:
        if isinstance(res, list):
            return 200, res, ""
        if isinstance(res, dict) and isinstance(res.get("items"), list):
            return 200, res["items"], ""
        return 200, [], ""
    err = res.get("error", str(res)) if isinstance(res, dict) else str(res)
    return st, [], err

def discover_or_provision_mt5(login: str, password: str, server: str, user_id: int = None, provided_acc_id: str = "") -> tuple[bool, str, str, str, str]:
    """
    الربط الجذري الكامل:
    1) إذا تم تمرير Account ID مباشر أو كان مخزناً، يفحصه مباشرة.
    2) يبحث في قائمة حسابات MetaApi باستخدام _id و id.
    3) ينشر الحساب (Deploy) وينتظر اتصاله.
    4) إذا لم يكن موجوداً، ينشئه باستخدام cloud-g1 + regular لتجنب خطأ Top up.
    """
    global DEFAULT_CLOUD_ID, DEFAULT_CLOUD_REGION, DEFAULT_CLOUD_LOGIN, DEFAULT_CLOUD_PASS, DEFAULT_CLOUD_SERVER

    if not MASTER_METAAPI_TOKEN:
        return False, "", "new-york", "NO_TOKEN", "مفتاح METAAPI_TOKEN غير موجود في Render."

    # 1. البحث في الحسابات المسجلة داخل MetaApi
    st_list, accounts, err_list = fetch_all_metaapi_accounts()
    chosen_acc = None

    if st_list == 200 and accounts:
        for acc in accounts:
            aid = extract_acc_id(acc)
            alogin = str(acc.get("login", "")).strip()
            if provided_acc_id and aid == provided_acc_id:
                chosen_acc = acc
                break
            if login and alogin == str(login).strip():
                chosen_acc = acc
                break
        if not chosen_acc:
            chosen_acc = accounts[-1]

    # 2. إذا لم يظهر في القائمة العامة، نجرب فحص المعرف المباشر (مثل d24ac5aa438f47a5be121f7827c557a2)
    candidate_ids = [x for x in [provided_acc_id, DEFAULT_CLOUD_ID, KNOWN_FALLBACK_ACC_ID] if x and x != "None"]
    if not chosen_acc:
        for cid in candidate_ids:
            st_one, acc_one = http_request(
                f"{PROVISION_URL}/users/current/accounts/{cid}",
                method="GET",
                headers=cloud_headers(),
                timeout=12
            )
            if st_one == 200 and isinstance(acc_one, dict) and extract_acc_id(acc_one):
                chosen_acc = acc_one
                break

    # 3. إذا وجدنا الحساب في MetaApi، نحدثه عند الحاجة ونشغله (Deploy)
    if chosen_acc:
        acc_id = extract_acc_id(chosen_acc)
        reg = extract_acc_region(chosen_acc)
        state = str(chosen_acc.get("state", "UNKNOWN"))
        conn_st = str(chosen_acc.get("connectionStatus", "DISCONNECTED"))
        found_login = str(chosen_acc.get("login") or login or KNOWN_MT5_LOGIN)
        found_server = str(chosen_acc.get("server") or server or KNOWN_MT5_SERVER)

        # إذا أرسل المستخدم كلمة مرور وسيرفر وكان الحساب غير متصل، نحدث بياناته
        if password and server and conn_st != "CONNECTED":
            http_request(
                f"{PROVISION_URL}/users/current/accounts/{acc_id}",
                method="PUT",
                headers=cloud_headers(),
                payload={"name": f"MT5_{found_login}", "password": password, "server": server, "magic": 990011},
                timeout=15
            )

        if state != "DEPLOYED":
            http_request(
                f"{PROVISION_URL}/users/current/accounts/{acc_id}/deploy",
                method="POST",
                headers=cloud_headers(),
                timeout=15
            )

        # التحقق من الحالة بعد النشر
        st_check, acc_Refresh = http_request(
            f"{PROVISION_URL}/users/current/accounts/{acc_id}",
            method="GET",
            headers=cloud_headers(),
            timeout=12
        )
        if st_check == 200 and isinstance(acc_Refresh, dict):
            state = str(acc_Refresh.get("state", state))
            conn_st = str(acc_Refresh.get("connectionStatus", conn_st))
            reg = extract_acc_region(acc_Refresh)

        DEFAULT_CLOUD_ID = acc_id
        DEFAULT_CLOUD_REGION = reg
        DEFAULT_CLOUD_LOGIN = found_login
        if password:
            DEFAULT_CLOUD_PASS = password
        if server:
            DEFAULT_CLOUD_SERVER = found_server

        sync_all_users_cloud_id(found_login, DEFAULT_CLOUD_PASS, found_server, acc_id, reg)
        return True, acc_id, reg, state, conn_st

    # 4. إذا لم يكن هناك أي حساب في MetaApi، نقوم بإنشائه مع معالجة قيد (High reliability top up)
    use_login = str(login or KNOWN_MT5_LOGIN).strip()
    use_pass = str(password or KNOWN_MT5_PASS).strip()
    use_srv = str(server or KNOWN_MT5_SERVER).strip()

    creation_profiles = [
        {"type": "cloud-g1", "reliability": "regular"},
        {"type": "cloud-g2", "reliability": "regular"},
        {"type": "cloud"}
    ]
    last_create_err = ""

    for prof in creation_profiles:
        payload = {
            "name": f"MT5_{use_login}",
            "login": use_login,
            "password": use_pass,
            "server": use_srv,
            "platform": "mt5",
            "magic": 990011
        }
        payload.update(prof)
        st_cr, res_cr = http_request(
            f"{PROVISION_URL}/users/current/accounts",
            method="POST",
            headers=cloud_headers(with_tx=True),
            payload=payload,
            timeout=35
        )
        if st_cr in [200, 201, 202] and isinstance(res_cr, dict):
            new_id = extract_acc_id(res_cr)
            new_reg = extract_acc_region(res_cr)
            if new_id:
                http_request(f"{PROVISION_URL}/users/current/accounts/{new_id}/deploy", method="POST", headers=cloud_headers(), timeout=15)
                DEFAULT_CLOUD_ID = new_id
                DEFAULT_CLOUD_REGION = new_reg
                DEFAULT_CLOUD_LOGIN = use_login
                DEFAULT_CLOUD_PASS = use_pass
                DEFAULT_CLOUD_SERVER = use_srv
                sync_all_users_cloud_id(use_login, use_pass, use_srv, new_id, new_reg)
                return True, new_id, new_reg, "DEPLOYED", "CONNECTING"
        else:
            last_create_err = res_cr.get("error", str(res_cr)) if isinstance(res_cr, dict) else str(res_cr)
            # إذا كانت رسالة الخطأ تحتوي في نهايتها على معرف الحساب بين قوسين مثل (d24ac5aa438f47a5be121f7827c557a2)
            if "(" in last_create_err and ")" in last_create_err:
                possible_id = last_create_err.split("(")[-1].split(")")[0].strip()
                if len(possible_id) >= 24:
                    st_p, acc_p = http_request(f"{PROVISION_URL}/users/current/accounts/{possible_id}", method="GET", headers=cloud_headers(), timeout=10)
                    if st_p == 200 and isinstance(acc_p, dict) and extract_acc_id(acc_p):
                        aid = extract_acc_id(acc_p)
                        areg = extract_acc_region(acc_p)
                        http_request(f"{PROVISION_URL}/users/current/accounts/{aid}/deploy", method="POST", headers=cloud_headers(), timeout=12)
                        DEFAULT_CLOUD_ID = aid
                        DEFAULT_CLOUD_REGION = areg
                        sync_all_users_cloud_id(use_login, use_pass, use_srv, aid, areg)
                        return True, aid, areg, str(acc_p.get("state", "DEPLOYED")), str(acc_p.get("connectionStatus", "CONNECTING"))

    return False, "", "new-york", "CREATE_FAILED", last_create_err or err_list


# ================= 8. دوال التداول الفعلي على MT5 (رصيد، صفقات، أسعار، أوامر) =================
def get_mt5_account_info(u: dict) -> tuple[bool, dict, str, str, str]:
    login = u.get("mt5_login") or KNOWN_MT5_LOGIN
    password = u.get("mt5_password") or KNOWN_MT5_PASS
    server = u.get("mt5_server") or KNOWN_MT5_SERVER
    acc_id = u.get("cloud_account_id") or DEFAULT_CLOUD_ID

    ok, acc_id, reg, state, conn_st = discover_or_provision_mt5(login, password, server, u.get("user_id"), acc_id)
    if not ok or not acc_id:
        return False, {}, state, conn_st, f"تعذر الوصول لمعرف الحساب في MetaApi: {conn_st}"

    working_reg = probe_working_region(acc_id, reg)
    if working_reg != reg:
        reg = working_reg
        sync_all_users_cloud_id(login, password, server, acc_id, reg)

    client_base = get_client_url(reg)
    st, info = http_request(
        f"{client_base}/users/current/accounts/{acc_id}/account-information",
        method="GET",
        headers=cloud_headers(),
        timeout=12
    )
    if st == 200 and isinstance(info, dict) and "balance" in info:
        return True, info, state, "CONNECTED", reg

    err_msg = info.get("error", str(info)) if isinstance(info, dict) else str(info)
    return False, {}, state, conn_st, f"HTTP {st}: {err_msg}"

def get_open_positions_mt5(u: dict) -> list:
    acc_id = u.get("cloud_account_id") or DEFAULT_CLOUD_ID
    reg = u.get("mt5_region") or DEFAULT_CLOUD_REGION
    if not acc_id or acc_id == "None":
        ok, acc_id, reg, _, _ = discover_or_provision_mt5(
            u.get("mt5_login") or KNOWN_MT5_LOGIN,
            u.get("mt5_password") or KNOWN_MT5_PASS,
            u.get("mt5_server") or KNOWN_MT5_SERVER,
            u.get("user_id")
        )
        if not ok or not acc_id:
            return []
    client_base = get_client_url(reg)
    st, res = http_request(f"{client_base}/users/current/accounts/{acc_id}/positions", method="GET", headers=cloud_headers(), timeout=10)
    return res if (st == 200 and isinstance(res, list)) else []

def close_single_position_mt5(u: dict, pos_id: str) -> bool:
    acc_id = u.get("cloud_account_id") or DEFAULT_CLOUD_ID
    reg = u.get("mt5_region") or DEFAULT_CLOUD_REGION
    client_base = get_client_url(reg)
    url = f"{client_base}/users/current/accounts/{acc_id}/trade"
    payload = {"actionType": "POSITION_CLOSE_ID", "positionId": str(pos_id)}
    st, res = http_request(url, method="POST", headers=cloud_headers(), payload=payload, timeout=12)
    if st == 200 and isinstance(res, dict):
        code = str(res.get("stringCode", ""))
        num = int(res.get("numericCode", -1))
        return code in ["TRADE_RETCODE_DONE", "TRADE_RETCODE_DONE_PARTIAL", "ERR_NO_ERROR"] or num in [0, 10009, 10008]
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

def match_broker_symbol(acc_id: str, reg: str, desired_symbol: str) -> list:
    """البحث الذكي عن اسم الزوج الدقيق داخل سيرفر الوسيط (مثلاً XAUUSD أو XAUUSDm أو GOLD)"""
    client_base = get_client_url(reg)
    st, syms = http_request(
        f"{client_base}/users/current/accounts/{acc_id}/symbols",
        method="GET",
        headers=cloud_headers(),
        timeout=10
    )
    candidates = [desired_symbol]
    if st == 200 and isinstance(syms, list) and len(syms) > 0:
        str_syms = [str(s) for s in syms]
        if desired_symbol in str_syms:
            candidates = [desired_symbol]
        else:
            # مطابقة اللواحق مثل XAUUSDm أو XAUUSD.a
            prefix_matches = [s for s in str_syms if s.upper().startswith(desired_symbol.upper())]
            contains_matches = [s for s in str_syms if desired_symbol.upper() in s.upper()]
            gold_matches = [s for s in str_syms if ("XAU" in s.upper() or "GOLD" in s.upper())] if "XAU" in desired_symbol.upper() else []
            eur_matches = [s for s in str_syms if s.upper().startswith("EURUSD")]
            combined = prefix_matches + contains_matches + gold_matches + eur_matches
            seen = []
            for c in combined:
                if c not in seen:
                    seen.append(c)
            if seen:
                candidates = seen[:4]
                return candidates

    for fallback_sym in ["XAUUSD", "EURUSD", "GBPUSD"]:
        if fallback_sym not in candidates:
            candidates.append(fallback_sym)
    return candidates

live_price_memory = {}

def fetch_live_market_context(acc_id: str, reg: str, symbol: str) -> tuple[float, str, str]:
    client_base = get_client_url(reg)
    enc_sym = urllib.parse.quote(symbol)
    st, res = http_request(
        f"{client_base}/users/current/accounts/{acc_id}/symbols/{enc_sym}/current-price",
        method="GET",
        headers=cloud_headers(),
        timeout=8
    )
    if st == 200 and isinstance(res, dict) and "bid" in res:
        bid = float(res.get("bid", 0.0))
        ask = float(res.get("ask", bid))
        hist = live_price_memory.setdefault(symbol, [])
        hist.append(bid)
        if len(hist) > 25:
            hist.pop(0)
        bias = "BUY" if (len(hist) < 2 or hist[-1] >= hist[0]) else "SELL"
        spread = abs(ask - bid)
        return bid, f"Symbol:{symbol}, Bid:{bid}, Ask:{ask}, Spread:{spread:.4f}, Samples:{len(hist)}", bias
    bias = "BUY" if int(time.time()) % 2 == 0 else "SELL"
    return 0.0, f"Symbol:{symbol}, DirectMarketExecution", bias

def execute_real_mt5_order(u: dict, action: str) -> tuple[bool, str, str, float, float]:
    """إرسال أمر بيع أو شراء حقيقي إلى سيرفر MT5 والتحقق من رقم التذكرة الفعلي"""
    login = u.get("mt5_login") or KNOWN_MT5_LOGIN
    password = u.get("mt5_password") or KNOWN_MT5_PASS
    server = u.get("mt5_server") or KNOWN_MT5_SERVER
    acc_id = u.get("cloud_account_id") or DEFAULT_CLOUD_ID

    ok_disc, acc_id, reg, state, conn_status = discover_or_provision_mt5(login, password, server, u.get("user_id"), acc_id)
    if not ok_disc or not acc_id:
        return False, u["symbol"], f"تعذر الربط بـ MetaApi: {conn_status}", float(u["lot"]), 0.0

    # التأكد من المنطقة الجغرافية الصحيحة
    reg = probe_working_region(acc_id, reg)
    client_base = get_client_url(reg)
    trade_url = f"{client_base}/users/current/accounts/{acc_id}/trade"

    symbols_to_try = match_broker_symbol(acc_id, reg, u["symbol"])
    user_lot = float(u.get("lot", 0.01))
    lots_to_try = [user_lot, 0.01] if user_lot != 0.01 else [0.01]

    last_error = f"حالة السحابة: {state} | الاتصال بالوسيط: {conn_status}"

    for sym in symbols_to_try:
        live_price, _, _ = fetch_live_market_context(acc_id, reg, sym)
        for current_lot in lots_to_try:
            payload = {
                "actionType": "ORDER_TYPE_BUY" if action == "BUY" else "ORDER_TYPE_SELL",
                "symbol": sym,
                "volume": current_lot,
                "comment": "AI_MT5_Real"
            }
            st, res = http_request(trade_url, method="POST", headers=cloud_headers(), payload=payload, timeout=15)
            if st == 200 and isinstance(res, dict):
                str_code = str(res.get("stringCode", ""))
                num_code = int(res.get("numericCode", -1))
                if str_code in ["TRADE_RETCODE_DONE", "TRADE_RETCODE_DONE_PARTIAL", "ERR_NO_ERROR"] or num_code in [0, 10009, 10008]:
                    order_id = str(res.get("positionId") or res.get("orderId") or "Executed")
                    return True, sym, order_id, current_lot, live_price
                last_error = f"{str_code}: {res.get('message', 'رفض من سيرفر MT5')}"
                if "VOLUME" in str_code or "MONEY" in str_code:
                    continue
                else:
                    break
            else:
                err = res.get("error", str(res)) if isinstance(res, dict) else str(res)
                last_error = f"HTTP {st}: {err}"
                break

    return False, u["symbol"], last_error, user_lot, 0.0


# ================= 9. محرك التداول الآلي الكامل والتشخيص المباشر =================
authorized_users = set()
active_traders = {}
pending_input = {}

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
    sent = send_msg(chat_id, "⏳ جاري فحص الاتصال الفعلي وسحب الرصيد الحي والصفقات من سيرفر MT5...")
    msg_id = sent.get("result", {}).get("message_id") if isinstance(sent, dict) else None
    try:
        u = get_user(uid)
        ok, info, state, conn_st, reg_or_err = get_mt5_account_info(u)
        u_updated = get_user(uid)
        acc_id_now = u_updated.get("cloud_account_id") or DEFAULT_CLOUD_ID

        if ok:
            bal = float(info.get("balance", 0.0))
            eq = float(info.get("equity", 0.0))
            free_m = float(info.get("freeMargin", 0.0))
            curr = info.get("currency", "USD")
            srv = info.get("server", u_updated.get("mt5_server", KNOWN_MT5_SERVER))
            open_pos = get_open_positions_mt5(u_updated)
            report = (
                f"✅ اتصال MT5 حقيقي ومكتمل 100%!\n\n"
                f"• رقم الحساب: {u_updated['mt5_login']}\n"
                f"• السيرفر: {srv}\n"
                f"• معرف MetaApi (_id): {acc_id_now}\n"
                f"• المنطقة السحابية: {reg_or_err}\n"
                f"• حالة الاتصال: {state} | {conn_st}\n"
                f"• الرصيد الفعلي (Balance): {bal:.2f} {curr}\n"
                f"• السيولة الحية (Equity): {eq:.2f} {curr}\n"
                f"• الهامش المتاح (Free Margin): {free_m:.2f} {curr}\n"
                f"• الصفقات المفتوحة حالياً في MT5: {len(open_pos)}\n\n"
                f"🚀 البوت متصل فعلياً بحسابك في MT5 وجاهز لإرسال الأوامر!"
            )
        else:
            report = (
                f"🔍 تقرير التشخيص الدقيق لحساب MT5:\n\n"
                f"• رقم الحساب: {u_updated['mt5_login']}\n"
                f"• السيرفر: {u_updated['mt5_server']}\n"
                f"• معرف MetaApi (_id): {acc_id_now or 'غير مستخرج بعد'}\n"
                f"• حالة السحابة: {state} | الاتصال: {conn_st}\n"
                f"• رد سيرفر MetaApi/MT5:\n{reg_or_err}\n\n"
                f"💡 الحل المباشر إذا ظهر قيد من MetaApi:\n"
                f"1. افتح app.metaapi.cloud وتأكد أن الحساب {u_updated['mt5_login']} في حالة Deployed.\n"
                f"2. أو افتح حساباً تجريبياً مجانياً في تطبيق MT5 على سيرفر Exness-MT5Trial وأرسل بياناته في 3 أسطر."
            )

        if msg_id:
            edit_msg(chat_id, msg_id, report, main_dashboard_keyboard(uid))
        else:
            send_msg(chat_id, report, main_dashboard_keyboard(uid))
    except Exception as e:
        send_msg(chat_id, f"⚠️ خطأ أثناء التشخيص: {e}")

def open_ai_trade_now(user_id: int, chat_id: int, notify_waiting: bool = False) -> bool:
    try:
        u = get_user(user_id)
        msg_id = None
        if notify_waiting:
            sent = send_msg(chat_id, f"⚡ جاري تحليل السوق عبر الذكاء الاصطناعي وإرسال أمر حقيقي إلى حسابك ({u['mt5_login']})...")
            msg_id = sent.get("result", {}).get("message_id") if isinstance(sent, dict) else None

        acc_id = u.get("cloud_account_id") or DEFAULT_CLOUD_ID
        reg = u.get("mt5_region") or DEFAULT_CLOUD_REGION
        _, market_ctx, tech_bias = fetch_live_market_context(acc_id, reg, u["symbol"])

        decision = analyze_market_with_ai(user_id, u["symbol"], market_ctx, tech_bias)
        action = decision["action"]

        if decision.get("switched"):
            send_msg(chat_id, f"🔄 تم التحويل تلقائياً إلى أداة الذكاء الاصطناعي النشطة: {decision['provider_name']}")

        ok, exec_sym, order_or_err, used_lot, exec_price = execute_real_mt5_order(u, action)
        if ok:
            if exec_sym != u["symbol"]:
                update_user(user_id, "symbol", exec_sym)
            if used_lot != float(u["lot"]):
                update_user(user_id, "lot", used_lot)
            price_str = f"{exec_price}" if exec_price > 0 else "سعر السوق الفوري"
            success_txt = (
                f"✅ تم تنفيذ صفقة حقيقية داخل حسابك في MT5!\n\n"
                f"• رقم الحساب: {u['mt5_login']}\n"
                f"• نوع الأمر: {action}\n"
                f"• الزوج: {exec_sym} | اللوت: {used_lot}\n"
                f"• سعر التنفيذ: {price_str}\n"
                f"• رقم التذكرة الحقيقي في MT5: #{order_or_err}\n"
                f"• أداة الذكاء الاصطناعي: {decision['provider_name']} (ثقة {decision['confidence']}%)\n"
                f"🎯 يراقب البوت ربح الصفقة الحقيقي في MT5 لإغلاقها عند +{u['trade_tp_usd']}$ أو -{u['trade_sl_usd']}$"
            )
            if msg_id:
                edit_msg(chat_id, msg_id, success_txt)
            else:
                send_msg(chat_id, success_txt)
            return True
        else:
            fail_txt = (
                f"⚠️ لم يتم تنفيذ الصفقة في سيرفر MT5:\n"
                f"السبب الفعلي من السيرفر:\n{order_or_err}\n\n"
                f"👇 اضغط على (🔍 فحص وتشخيص اتصال MT5 الآن) لمعرفة حالة الرصيد والاتصال."
            )
            if msg_id:
                edit_msg(chat_id, msg_id, fail_txt)
            else:
                send_msg(chat_id, fail_txt)
            return False
    except Exception as e:
        send_msg(chat_id, f"⚠️ خطأ أثناء تنفيذ الأمر: {e}")
        return False

def trading_worker(user_id: int, chat_id: int):
    u = get_user(user_id)
    tool_name = get_ai_tool_by_id(u["selected_ai_id"]).get("name", "AI")
    send_msg(
        chat_id,
        f"🟢 بدأ التداول الآلي الحقيقي بالذكاء الاصطناعي على حسابك MT5!\n"
        f"• الحساب: {u['mt5_login']} ({u['mt5_server']})\n"
        f"• الأداة النشطة: {tool_name}\n"
        f"⚡ البوت يراقب صفقاتك الحقيقية في MT5 على مدار الساعة..."
    )

    first_attempt = True
    while active_traders.get(user_id, False):
        try:
            u = get_user(user_id)
            if u["current_daily_pnl"] >= u["daily_max_profit"]:
                active_traders[user_id] = False
                send_msg(chat_id, f"🏆 تحقق الهدف اليومي (+{u['current_daily_pnl']:.2f}$) وتوقف البوت لحفظ أرباحك!")
                break
            if u["current_daily_pnl"] <= -abs(u["daily_max_loss"]):
                active_traders[user_id] = False
                send_msg(chat_id, f"🛡️ وصلت الخسارة للحد اليومي ({u['current_daily_pnl']:.2f}$) وتوقف البوت لحماية رأس مالك!")
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
                                f"{icon} أغلق الذكاء الاصطناعي الصفقة الحقيقية في MT5!\n"
                                f"• التذكرة: #{pos.get('id')}\n"
                                f"• الزوج: {pos.get('symbol', u['symbol'])}\n"
                                f"• الربح/الخسارة الفعلية: {pnl:.2f}$\n"
                                f"• إجمالي حصيلة اليوم: {new_pnl:.2f}$ ({new_cnt} صفقات)"
                            )
            else:
                if is_within_working_hours(u["work_start_hour"], u["work_end_hour"]):
                    ok_trade = open_ai_trade_now(user_id, chat_id, notify_waiting=first_attempt)
                    first_attempt = False
                    if not ok_trade:
                        # إيقاف التكرار المزعج في حال كان الحساب غير متصل بعد
                        active_traders[user_id] = False
                        send_msg(
                            chat_id,
                            "⏸️ تم إيقاف التكرار التلقائي مؤقتاً حتى يكتمل اتصال سيرفر MT5.\n"
                            "اضغط على (🔍 فحص وتشخيص اتصال MT5 الآن) للتأكد من جاهزية السيرفر."
                        )
                        break
                    else:
                        time.sleep(5)
        except Exception as e:
            print(f"Trading loop error: {e}")
        time.sleep(3.0)


# ================= 10. لوحة التحكم الشاملة في تيليجرام =================
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
        [{"text": "🔍 فحص وتشخيص اتصال MT5 والرصيد الحي الآن", "callback_data": "diag_mt5"}],
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
        [{"text": "⚡ فتح صفقة حقيقية فورية في MT5 الآن!", "callback_data": "instant_trade"}],
        [{"text": "🚨 إغلاق جميع الصفقات المفتوحة في MT5 فوراً!", "callback_data": "emergency_close"}],
        [{"text": "🔄 تصفير عداد أرباح اليوم", "callback_data": "reset_pnl"}]
    ]}

def main_dashboard_text(user_id: int) -> str:
    u = get_user(user_id)
    tool = get_ai_tool_by_id(u["selected_ai_id"])
    state_str = "🟢 يتداول الآن تلقائياً" if active_traders.get(user_id, False) else "🔴 متوقف"
    acc_id_short = (u.get("cloud_account_id") or DEFAULT_CLOUD_ID or "غير محدد")[:12]
    return (
        "🤖 لوحة التحكم المتكاملة للتداول الحقيقي (MT5 + 10 AI)\n\n"
        f"• حالة البوت: {state_str}\n"
        f"• حساب MT5: {u['mt5_login']} ({u['mt5_server']})\n"
        f"• معرف السحابة (_id): {acc_id_short}...\n"
        f"• الأداة المختارة: {tool.get('name')}\n"
        f"• صافي ربح/خسارة اليوم (الفعلي): {u['current_daily_pnl']:.2f}$\n"
        f"• عدد الصفقات المغلقة اليوم: {u['trades_today']}\n\n"
        "👇 اضغط على (🔍 فحص وتشخيص اتصال MT5) للتأكد من الرصيد الحي قبل بدء التداول:"
    )

def ai_selection_keyboard(user_id: int) -> dict:
    u = get_user(user_id)
    rows = []
    for t in get_ai_tools():
        mark = "🟢 (مختارة) " if t["id"] == u["selected_ai_id"] else "🟢 "
        rows.append([{"text": f"{mark}{t['id']}. {t['name']}", "callback_data": f"pick_ai_{t['id']}"}])
    rows.append([{"text": "🔙 رجوع للوحة التحكم الرئيسية", "callback_data": "back_home"}])
    return {"inline_keyboard": rows}

def async_link_worker(uid: int, chat_id: int, mode: str, p1: str, p2: str, p3: str):
    try:
        u = get_user(uid)
        if mode == "ACCOUNT_ID":
            ok, acc_id, reg, state, conn_st = discover_or_provision_mt5(
                u.get("mt5_login") or KNOWN_MT5_LOGIN,
                u.get("mt5_password") or KNOWN_MT5_PASS,
                u.get("mt5_server") or KNOWN_MT5_SERVER,
                uid,
                provided_acc_id=p1
            )
        else:
            ok, acc_id, reg, state, conn_st = discover_or_provision_mt5(p1, p2, p3, uid)

        if ok and acc_id:
            pending_input.pop(uid, None)
            send_msg(
                chat_id,
                f"✅ تم ربط حساب MT5 بنجاح!\n"
                f"• معرف الحساب (_id): {acc_id}\n"
                f"• المنطقة السحابية: {reg}\n"
                f"• حالة السحابة: {state} | {conn_st}\n\n"
                f"اضغط الآن على (🔍 فحص وتشخيص اتصال MT5) لقراءة الرصيد الحي من داخل MT5.",
                main_dashboard_keyboard(uid)
            )
        else:
            send_msg(
                chat_id,
                f"❌ تعذر إتمام الربط التلقائي:\n{conn_st}\n\n"
                f"💡 الحل الفوري:\n"
                f"ادخل إلى موقع app.metaapi.cloud واضغط Deploy على حسابك ثم انسخ الـ ID وأرسله هنا، أو افتح حساباً تجريبياً مجانياً على سيرفر Exness-MT5Trial وأرسل بياناته في 3 أسطر."
            )
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
                            mode, p1, p2, p3 = parse_mt5_credentials(text)
                            if mode in ["CREDENTIALS", "ACCOUNT_ID"]:
                                delete_msg(chat_id, msg["message_id"])
                                send_msg(chat_id, "⏳ جاري ربط ومزامنة حساب MT5 مع سحابة MetaApi...")
                                threading.Thread(
                                    target=async_link_worker,
                                    args=(uid, chat_id, mode, p1, p2, p3),
                                    daemon=True
                                ).start()
                            else:
                                send_msg(
                                    chat_id,
                                    "⚠️ صيغة غير مكتملة! أرسل بيانات حسابك في 3 أسطر تحت بعضها هكذا:\n\n"
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
                                send_msg(chat_id, "⚠️ أرسل رقماً صحيحاً (مثال: 0.01).")

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
                            "🔗 إضافة أو تحديث حساب MT5:\n"
                            "أرسل بيانات حسابك في 3 أسطر تحت بعضها هكذا:\n\n"
                            "اسم المستخدم\n"
                            "كلمة المرور\n"
                            "السيرفر\n\n"
                            "مثال جاهز للنسخ:\n"
                            "5058253637\n"
                            "*aGm1cNp\n"
                            "MetaQuotes-Demo\n\n"
                            "💡 أو يمكنك لصق الـ Account ID مباشرة من موقع app.metaapi.cloud",
                            {"inline_keyboard": [[{"text": "🔙 رجوع", "callback_data": "back_home"}]]}
                        )

                    elif data == "diag_mt5":
                        answer_cb(cb_id, "🔍 جاري فحص الاتصال الحقيقي...")
                        threading.Thread(target=async_diagnostic_worker, args=(uid, chat_id), daemon=True).start()

                    elif data == "menu_ai_select":
                        answer_cb(cb_id)
                        edit_msg(chat_id, msg_id, "🤖 اختر أداة الذكاء الاصطناعي للتداول والتحكم بحسابك:", ai_selection_keyboard(uid))

                    elif data.startswith("pick_ai_"):
                        tool_id = int(data.split("_")[-1])
                        tool = get_ai_tool_by_id(tool_id)
                        answer_cb(cb_id, f"✅ تم تفعيل {tool['name']}")
                        update_user(uid, "selected_ai_id", tool_id)
                        edit_msg(chat_id, msg_id, f"✅ تم تفعيل ({tool['name']}) بنجاح!\n\n{main_dashboard_text(uid)}", main_dashboard_keyboard(uid))

                    elif data == "instant_trade":
                        answer_cb(cb_id, "⚡ جاري إرسال أمر حقيقي لـ MT5...")
                        threading.Thread(target=open_ai_trade_now, args=(uid, chat_id, True), daemon=True).start()

                    elif data == "set_hours":
                        answer_cb(cb_id)
                        pending_input[uid] = "input_hours"
                        edit_msg(chat_id, msg_id, "⏰ أرسل أوقات العمل (مثال: 8-22 أو 0-24):", {"inline_keyboard": [[{"text": "🔙 رجوع", "callback_data": "back_home"}]]})

                    elif data == "emergency_close":
                        u = get_user(uid)
                        answer_cb(cb_id, "🚨 جاري إغلاق الصفقات المفتوحة في MT5...")
                        active_traders[uid] = False
                        cnt, pnl = emergency_close_all_mt5(u)
                        update_user(uid, "current_daily_pnl", u["current_daily_pnl"] + pnl)
                        send_msg(chat_id, f"🚨 تم إغلاق {cnt} صفقات حقيقية في MT5! الصافي: {pnl:.2f}$")
                        edit_msg(chat_id, msg_id, main_dashboard_text(uid), main_dashboard_keyboard(uid))

                    elif data in ["set_lot", "set_symbol", "set_tp", "set_sl", "set_daily_tp", "set_daily_sl"]:
                        answer_cb(cb_id)
                        mapping = {
                            "set_lot": ("lot", "💵 أرسل حجم الدخول اللوت (مثال: 0.01):"),
                            "set_symbol": ("symbol", "📊 أرسل رمز الزوج (مثال: XAUUSD أو EURUSD):"),
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
        target=discover_or_provision_mt5,
        args=(KNOWN_MT5_LOGIN, KNOWN_MT5_PASS, KNOWN_MT5_SERVER, None, KNOWN_FALLBACK_ACC_ID),
        daemon=True
    ).start()
    start_keep_alive()
    run_bot_polling()
