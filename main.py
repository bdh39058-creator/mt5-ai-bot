import os
import json
import time
import sqlite3
import threading
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

# ================= 1. خادم إبقاء البوت شغالاً 24 ساعة (محمي ضد خطأ المنفذ المشغول) =================
class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("🤖 MT5 AI Bot is Running 24/7 (Zero-Dependency Mode)!".encode("utf-8"))

    def log_message(self, format, *args):
        return

def start_keep_alive():
    """يجرب عدة منافذ متاحة، وإذا كانت جميعها مشغولة يتخطى الخطأ ويكمل تشغيل البوت فوراً"""
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
    print("ℹ️ خادم الويب يعمل مسبقاً في الخلفية، جاري متابعة تشغيل البوت...")


# ================= 2. قراءة المفاتيح الـ 9 بنفس أسمائك بالحرف =================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
MASTER_METAAPI_TOKEN = os.getenv("METAAPI_TOKEN", "").strip()
SECRET_ACCESS_KEY = os.getenv("SECRET_ACCESS_KEY", "vip_secret_99").strip()

COHERE_KEY = os.getenv("COHERE_TOKEN", "").strip()
GEMINI_KEY = os.getenv("GEMINI_TOKEN", "").strip()
GITHUB_KEY = os.getenv("Git Hup_TOKEN", "").strip()
GROQ_KEY = os.getenv("GROQ_TOKRN", "").strip()
HUGGINGFACE_KEY = os.getenv("HUGGINGFACE_TOKEN", "").strip()
OPENROUTER_KEY = os.getenv("OPENROUTER1_TOKEN", "").strip()
SAMBANOVA_KEY = os.getenv("SAMBANOVA_TOKEN", "").strip()


# ================= 3. دوال الاتصال الشبكي المدمجة (بدون أي مكتبة خارجية) =================
def http_request(url: str, method: str = "GET", headers: dict = None, payload: dict = None, timeout: int = 8):
    headers = headers or {}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        return e.code, {"error": err_body}
    except Exception as e:
        return 500, {"error": str(e)}

def tg_api(method_name: str, params: dict = None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method_name}"
    _, res = http_request(url, method="POST", payload=params or {}, timeout=15)
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


# ================= 4. قاعدة البيانات والـ 10 أدوات ذكاء اصطناعي =================
def init_db():
    conn = sqlite3.connect("pure_mt5_bot.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            mt5_login TEXT DEFAULT '',
            mt5_password TEXT DEFAULT '',
            mt5_server TEXT DEFAULT '',
            cloud_account_id TEXT DEFAULT '',
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
        (2, "Google (Gemini 2.5 Flash)", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", GEMINI_KEY, "gemini-2.5-flash"),
        (3, "GitHub (GPT-4o Mini)", "https://models.inference.ai.azure.com/chat/completions", GITHUB_KEY, "gpt-4o-mini"),
        (4, "SambaNova (Llama-3.1-70B)", "https://api.sambanova.ai/v1/chat/completions", SAMBANOVA_KEY, "Meta-Llama-3.1-70B-Instruct"),
        (5, "Cohere (Command-R+)", "https://api.cohere.ai/compatibility/v1/chat/completions", COHERE_KEY, "command-r-plus-08-2024"),
        (6, "OpenRouter (Gemma-3-27B)", "https://openrouter.ai/api/v1/chat/completions", OPENROUTER_KEY, "google/gemma-3-27b-it:free"),
        (7, "HuggingFace (Qwen-2.5-72B)", "https://router.huggingface.co/v1/chat/completions", HUGGINGFACE_KEY, "Qwen/Qwen2.5-72B-Instruct"),
        (8, "Groq-2 (Qwen-2.5-32B)", "https://api.groq.com/openai/v1/chat/completions", GROQ_KEY, "qwen-2.5-32b"),
        (9, "GitHub-2 (GPT-4o Pro)", "https://models.inference.ai.azure.com/chat/completions", GITHUB_KEY, "gpt-4o"),
        (10, "OpenRouter-2 (Llama-3.3)", "https://openrouter.ai/api/v1/chat/completions", OPENROUTER_KEY, "meta-llama/llama-3.3-70b-instruct:free"),
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
        c.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
        conn.commit()
        c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = c.fetchone()
    conn.close()
    return dict(row)

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


# ================= 5. فحص الـ Credits والتحويل التلقائي بين الـ 10 أدوات =================
def call_ai_model(tool: dict, prompt: str, max_tokens: int = 80) -> tuple[bool, str]:
    if not tool or not tool.get("api_key"):
        return False, ""
    headers = {
        "Authorization": f"Bearer {tool['api_key']}",
        "User-Agent": "MT5-AI-Bot/1.0"
    }
    payload = {
        "model": tool["model"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": max_tokens
    }
    status, res = http_request(tool["base_url"], method="POST", headers=headers, payload=payload, timeout=6)
    if status == 200 and "choices" in res:
        try:
            return True, res["choices"][0]["message"]["content"].strip()
        except Exception:
            return False, ""
    return False, ""

def check_ai_tool_credit(tool: dict) -> bool:
    ok, content = call_ai_model(tool, "Reply OK", max_tokens=5)
    return ok and bool(content)

def analyze_with_ai_failover(user_id: int, market_summary: str) -> dict:
    u = get_user(user_id)
    preferred_id = u["selected_ai_id"]
    all_tools = get_ai_tools()
    ordered_tools = sorted(all_tools, key=lambda x: 0 if x["id"] == preferred_id else x["id"])

    prompt = (
        f"Professional 1m MT5 scalping analysis: {market_summary}. "
        "Reply ONLY in valid JSON: {\"action\": \"BUY\" or \"SELL\" or \"HOLD\", \"confidence\": 0-100}"
    )

    for tool in ordered_tools:
        ok, text = call_ai_model(tool, prompt, max_tokens=60)
        if ok:
            try:
                clean = text.replace("```json", "").replace("```", "").strip()
                decision = json.loads(clean)
                decision["provider_name"] = tool["name"]
                if tool["id"] != preferred_id:
                    update_user(user_id, "selected_ai_id", tool["id"])
                    decision["switched"] = True
                else:
                    decision["switched"] = False
                return decision
            except Exception:
                continue

    return {"action": "HOLD", "confidence": 0, "provider_name": "None", "switched": False}


# ================= 6. دوال MT5 وحساب المؤشرات الفنية =================
REGION_URL = "https://mt-client-api-v1.london.agiliumtrade.ai"
PROVISION_URL = "https://mt-provisioning-api-v1.agiliumtrade.agiliumtrade.ai"

def cloud_headers():
    return {"auth-token": MASTER_METAAPI_TOKEN}

def link_mt5_account(user_id: int, login: str, password: str, server: str) -> tuple[bool, str]:
    payload = {
        "name": f"MT5_User_{user_id}",
        "type": "cloud",
        "login": str(login),
        "password": password,
        "server": server,
        "platform": "mt5",
        "magic": 990011
    }
    status, res = http_request(f"{PROVISION_URL}/users/current/accounts", method="POST", headers=cloud_headers(), payload=payload, timeout=12)
    if status in [200, 201] and "id" in res:
        acc_id = res["id"]
        http_request(f"{PROVISION_URL}/users/current/accounts/{acc_id}/deploy", method="POST", headers=cloud_headers(), timeout=8)
        update_user(user_id, "mt5_login", login)
        update_user(user_id, "mt5_password", password)
        update_user(user_id, "mt5_server", server)
        update_user(user_id, "cloud_account_id", acc_id)
        return True, "تم ربط حسابك بمنصة MT5 السحابية بالذكاء الاصطناعي بنجاح!"
    return False, f"تأكد من رقم الحساب أو السيرفر: {res.get('error', res)}"

def get_open_positions_mt5(u: dict) -> list:
    if not u["cloud_account_id"]:
        return []
    url = f"{REGION_URL}/users/current/accounts/{u['cloud_account_id']}/positions"
    status, res = http_request(url, method="GET", headers=cloud_headers(), timeout=6)
    return res if (status == 200 and isinstance(res, list)) else []

def close_single_position_mt5(u: dict, pos_id: str) -> bool:
    url = f"{REGION_URL}/users/current/accounts/{u['cloud_account_id']}/trade"
    payload = {"actionType": "POSITION_CLOSE_ID", "positionId": str(pos_id)}
    status, _ = http_request(url, method="POST", headers=cloud_headers(), payload=payload, timeout=6)
    return status == 200

def emergency_close_all_mt5(u: dict) -> tuple[int, float]:
    positions = get_open_positions_mt5(u)
    closed_count = 0
    total_pnl = 0.0
    for p in positions:
        pnl = float(p.get("profit", 0.0))
        if close_single_position_mt5(u, p.get("id")):
            closed_count += 1
            total_pnl += pnl
    return closed_count, total_pnl

def open_new_order_mt5(u: dict, action: str) -> bool:
    url = f"{REGION_URL}/users/current/accounts/{u['cloud_account_id']}/trade"
    payload = {
        "actionType": "ORDER_TYPE_BUY" if action == "BUY" else "ORDER_TYPE_SELL",
        "symbol": u["symbol"],
        "volume": u["lot"],
        "comment": "AI_Auto_Trader"
    }
    status, _ = http_request(url, method="POST", headers=cloud_headers(), payload=payload, timeout=6)
    return status == 200

def calc_ema(prices: list, period: int) -> list:
    ema = [prices[0]]
    k = 2 / (period + 1)
    for p in prices[1:]:
        ema.append(p * k + ema[-1] * (1 - k))
    return ema

def calc_rsi(prices: list, period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(-period, 0):
        diff = prices[i] - prices[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def fetch_and_analyze_market(u: dict) -> tuple[str, bool]:
    url = (
        f"{REGION_URL}/users/current/accounts/{u['cloud_account_id']}"
        f"/historical-market-data/symbols/{u['symbol']}/timeframes/1m/candles?limit=35"
    )
    status, candles = http_request(url, method="GET", headers=cloud_headers(), timeout=6)
    if status != 200 or not isinstance(candles, list) or len(candles) < 25:
        return "", False

    closes = [float(c["close"]) for c in candles]
    ema9_list = calc_ema(closes, 9)
    ema21_list = calc_ema(closes, 21)
    rsi_val = calc_rsi(closes, 14)

    is_signal = (
        rsi_val < 35 or rsi_val > 65 or
        (ema9_list[-2] <= ema21_list[-2] and ema9_list[-1] > ema21_list[-1]) or
        (ema9_list[-2] >= ema21_list[-2] and ema9_list[-1] < ema21_list[-1])
    )
    summary = f"Symbol:{u['symbol']}, Price:{closes[-1]}, RSI:{rsi_val:.1f}, EMA9:{ema9_list[-1]:.2f}, EMA21:{ema21_list[-1]:.2f}"
    return summary, is_signal


# ================= 7. محرك التداول المستمر ولوحة تحكم تيليجرام =================
authorized_users = set()
active_traders = {}
pending_input = {}

def is_within_working_hours(start_h: int, end_h: int) -> bool:
    now_h = datetime.now().hour
    if start_h == 0 and end_h == 24:
        return True
    return (start_h <= now_h < end_h) if start_h <= end_h else (now_h >= start_h or now_h < end_h)

def trading_worker(user_id: int, chat_id: int):
    send_msg(chat_id, "🚀 **بدأ الذكاء الاصطناعي بالتداول التلقائي على حسابك في MT5!**")
    while active_traders.get(user_id, False):
        try:
            u = get_user(user_id)
            if u["current_daily_pnl"] >= u["daily_max_profit"]:
                active_traders[user_id] = False
                send_msg(chat_id, f"🏆 **تحقق الهدف اليومي (`{u['current_daily_pnl']:.2f}$`) وتوقف البوت لحفظ أرباحك!**")
                break
            if u["current_daily_pnl"] <= -abs(u["daily_max_loss"]):
                active_traders[user_id] = False
                send_msg(chat_id, f"🛡️ **وصلت الخسارة للحد المسموح (`{u['current_daily_pnl']:.2f}$`) وتوقف البوت لحماية رأس مالك!**")
                break

            positions = get_open_positions_mt5(u)
            if positions:
                for pos in positions:
                    pnl = float(pos.get("profit", 0.0))
                    if pnl >= u["trade_tp_usd"] or pnl <= -abs(u["trade_sl_usd"]):
                        if close_single_position_mt5(u, pos.get("id")):
                            new_pnl = u["current_daily_pnl"] + pnl
                            new_cnt = u["trades_today"] + 1
                            update_user(user_id, "current_daily_pnl", new_pnl)
                            update_user(user_id, "trades_today", new_cnt)
                            icon = "💰" if pnl > 0 else "🛑"
                            send_msg(chat_id, f"{icon} **أغلق الذكاء الاصطناعي الصفقة!**\n• النتيجة: `{pnl:.2f}$`\n• حصيلة اليوم: `{new_pnl:.2f}$`")
            else:
                if is_within_working_hours(u["work_start_hour"], u["work_end_hour"]):
                    summary, is_signal = fetch_and_analyze_market(u)
                    if is_signal and summary:
                        decision = analyze_with_ai_failover(user_id, summary)
                        if decision.get("switched"):
                            send_msg(chat_id, f"🔄 **انتهى الـ Credits في الأداة السابقة، فتحول البوت تلقائياً إلى `{decision['provider_name']}`!**")
                        if decision.get("action") in ["BUY", "SELL"] and decision.get("confidence", 0) >= 80:
                            if open_new_order_mt5(u, decision["action"]):
                                send_msg(chat_id, f"⚡ **دخول صفقة ({decision['action']}) على {u['symbol']}**\n• بواسطة: `{decision['provider_name']}` (ثقة `{decision['confidence']}%`)")
                                time.sleep(3)
        except Exception as e:
            print(f"Loop error: {e}")
        time.sleep(1.0)

def main_dashboard_keyboard(user_id: int) -> dict:
    u = get_user(user_id)
    tool = get_ai_tool_by_id(u["selected_ai_id"])
    mt5_txt = f"✅ مربوط ({u['mt5_login']})" if u["mt5_login"] else "❌ غير مربوط"
    hours_txt = "24 ساعة" if (u["work_start_hour"] == 0 and u["work_end_hour"] == 24) else f"{u['work_start_hour']}:00 - {u['work_end_hour']}:00"
    run_btn = (
        {"text": "⏹️ إيقاف التداول التلقائي", "callback_data": "toggle_run"}
        if active_traders.get(user_id, False)
        else {"text": "▶️ بدء التداول التلقائي بالذكاء الاصطناعي", "callback_data": "toggle_run"}
    )
    return {"inline_keyboard": [
        [{"text": f"🔗 1. إضافة حساب MT5 ({mt5_txt})", "callback_data": "menu_mt5"}],
        [{"text": f"🤖 2. ربط الذكاء الاصطناعي ({tool.get('name')})", "callback_data": "menu_ai_select"}],
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
        "👇 **تحكم في كافة شروط حماية حسابك من الأزرار بالأسفل:**"
    )

def ai_selection_keyboard(user_id: int) -> dict:
    u = get_user(user_id)
    rows = []
    for t in get_ai_tools():
        mark = "🟢 (مختارة) " if t["id"] == u["selected_ai_id"] else "🤖 "
        rows.append([{"text": f"{mark}{t['id']}. {t['name']}", "callback_data": f"pick_ai_{t['id']}"}])
    rows.append([{"text": "🔙 رجوع للوحة التحكم الرئيسية", "callback_data": "back_home"}])
    return {"inline_keyboard": rows}

def run_bot_polling():
    # إلغاء أي Webhook قديم لضمان استقبال الرسائل فوراً
    tg_api("deleteWebhook", {"drop_pending_updates": False})
    offset = 0
    print("✅ البوت يعمل الآن بنجاح 100%! اذهب إلى تيليجرام وافتح الرابط السري للبوت...")
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

                    if text.startswith("/start"):
                        parts = text.split()
                        if uid not in authorized_users:
                            if len(parts) > 1 and parts[1] == SECRET_ACCESS_KEY:
                                authorized_users.add(uid)
                            else:
                                send_msg(chat_id, "🔒 هذا البوت خاص ولا يفتح إلا عبر الرابط السري المخصص.")
                                continue
                        send_msg(chat_id, main_dashboard_text(uid), main_dashboard_keyboard(uid))

                    elif uid in authorized_users and uid in pending_input:
                        action = pending_input[uid]
                        if action == "input_mt5":
                            try:
                                login, password, server = [x.strip() for x in text.split(",")]
                                delete_msg(chat_id, msg["message_id"])
                                send_msg(chat_id, "⏳ جاري ربط حساب MT5 بالذكاء الاصطناعي...")
                                ok, info = link_mt5_account(uid, login, password, server)
                                if ok:
                                    pending_input.pop(uid, None)
                                    send_msg(chat_id, f"✅ {info}", main_dashboard_keyboard(uid))
                                else:
                                    send_msg(chat_id, f"❌ فشل الربط: `{info}`")
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

                    if uid not in authorized_users:
                        answer_cb(cb_id, "غير مصرح لك.", True)
                        continue

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

                    elif data == "menu_ai_select":
                        answer_cb(cb_id)
                        edit_msg(
                            chat_id, msg_id,
                            "🤖 **اختر أداة الذكاء الاصطناعي للتداول عنك:**\n(يفحص البوت توفر الـ Credits فوراً قبل التفعيل):",
                            ai_selection_keyboard(uid)
                        )

                    elif data.startswith("pick_ai_"):
                        tool_id = int(data.split("_")[-1])
                        tool = get_ai_tool_by_id(tool_id)
                        answer_cb(cb_id, "⏳ جاري فحص الـ Credits...")
                        if check_ai_tool_credit(tool):
                            update_user(uid, "selected_ai_id", tool_id)
                            edit_msg(chat_id, msg_id, f"✅ **تم تفعيل ({tool['name']}) بنجاح!**", main_dashboard_keyboard(uid))
                        else:
                            edit_msg(
                                chat_id, msg_id,
                                f"⚠️ **هذه الأداة ({tool['name']}) انتهى فيها الـ credits بالوقت الحالي، حاول غداً.**\n\n"
                                "👇 يرجى اختيار أداة أخرى متوفرة من القائمة:",
                                ai_selection_keyboard(uid)
                            )

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
                            "set_symbol": ("symbol", "📊 أرسل رمز الزوج (مثال: `XAUUSD`):"),
                            "set_tp": ("trade_tp_usd", "🎯 أرسل ربح الصفقة بالدولار (مثال: `0.50`):"),
                            "set_sl": ("trade_sl_usd", "🛑 أرسل خسارة الصفقة بالدولار (مثال: `1.00`):"),
                            "set_daily_tp": ("daily_max_profit", "🏆 أرسل أقصى ربح يومي بالدولار (مثال: `20`):"),
                            "set_daily_sl": ("daily_max_loss", "🛡️ أرسل أقصى خسارة يومية بالدولار (مثال: `10`):"),
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
                        u = get_user(uid)
                        if not u["mt5_login"]:
                            answer_cb(cb_id, "⚠️ أضف حساب MT5 أولاً!", True)
                            continue
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
    start_keep_alive()
    run_bot_polling()
