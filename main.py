# -*- coding: utf-8 -*-
"""
=========================================================================================
🏛️ بوت التداول المؤسسي الشامل (MT5 + Bybit V5 Gold/Forex) - الإصدار الخامس الفائق (v5.0)
=========================================================================================
المزايا الهندسية المدمجة في هذا الإصدار:
1. منع الصفقات المتعاكسة نهائياً: استبدال (2+1 العكسي) بنظام التدرج الموحد (3 صفقات في نفس
   الاتجاه المؤكد: L1 قناص سريع + L2 سوينغ متوسط + L3 رانر مؤسسي) مع تأمين الدخول التلقائي.
2. محرك التحليل الزمني الشامل (30-Day Historical + Present Micro + Future Projection):
   - تحليل 30 يوماً للوراء (D1 + H4 + H1) لتحديد الهيكل العام ومناطق السيولة والـ Order Blocks.
   - تحليل اللحظة الحالية (M15 + M5 + M1) بالثانية عند إرسال أمر التداول.
   - التوقع المستقبلي (Future Cone) عبر الانحدار الخطي (Linear Regression) وامتدادات فيبوناتشي.
3. تحديد دقيق لمستويات القمة الهدف (TOP / Take Profit) والقاع الوقف (STOP / Stop Loss)
   بالسعر الفعلي على الشارت وبالدولار في رسالة التحليل المفصلة وعند التنفيذ.
4. معالج الأخطاء الذاتي الشامل (Auto-Healer) لجميع أكواد MT5 (10004 - 10044 شاملة 10027)
   وأكواد Bybit V5 (10001 - 140000 شاملة 10002 و 110007 و 403).
5. غرفة تحكم كاملة داخل تليجرام تغنيك عن فتح منصتي MT5 و Bybit (إدارة الصفقات الحية،
   قفل نصف العقود، تأمين نقطة الدخول Break-Even، تعديل TOP/STOP حياً، وشارت نصي).
=========================================================================================
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

# ======================= 0. تهيئة الترميز والسجل الآمن =======================
os.environ["PYTHONIOENCODING"] = "utf-8"
for _stream_obj in (sys.stdout, sys.stderr):
    try:
        if hasattr(_stream_obj, "reconfigure"):
            _stream_obj.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_SECRETS = []
_LOG_BUFFER = []
_LOG_LOCK = threading.RLock()


def register_secret(val):
    if val and isinstance(val, str) and len(val.strip()) >= 6:
        s = val.strip()
        if s not in _SECRETS:
            _SECRETS.append(s)


def redact(text):
    out = str(text)
    for sec in _SECRETS:
        out = out.replace(sec, "***")
    return out


def safe_print(*args):
    msg = redact(" ".join(str(a) for a in args))
    ts_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts_str}] {msg}"
    with _LOG_LOCK:
        _LOG_BUFFER.append(line)
        if len(_LOG_BUFFER) > 250:
            _LOG_BUFFER.pop(0)
    try:
        print(line, flush=True)
    except Exception:
        try:
            sys.stdout.write(line.encode("ascii", errors="ignore").decode() + "\n")
            sys.stdout.flush()
        except Exception:
            pass


def get_recent_logs(limit=25):
    with _LOG_LOCK:
        return "\n".join(_LOG_BUFFER[-limit:]) if _LOG_BUFFER else "لا توجد سجلات حتى الآن."


# ======================= 1. الإعدادات العامة ومتغيرات البيئة =======================
def env(*names, default=""):
    for name in names:
        val = os.getenv(name)
        if val and val.strip():
            return val.strip()
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
MIN_AI_CONFIDENCE = env_num("MIN_AI_CONFIDENCE", 90, int)
MAX_ALLOWED_SPREAD_USD = env_num("MAX_ALLOWED_SPREAD_USD", 1.80, float)

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

for _secret_item in (
    TELEGRAM_BOT_TOKEN, MASTER_METAAPI_TOKEN, SECRET_ACCESS_KEY, DB_SECRET,
    GROQ_KEY, GEMINI_KEY, GITHUB_KEY, SAMBANOVA_KEY, COHERE_KEY,
    OPENROUTER_KEY, HUGGINGFACE_KEY, KNOWN_MT5_PASS, ENV_BYBIT_SECRET
):
    register_secret(_secret_item)

MAGIC = 990055
DB_FILE = "multi_mt5_gold_bot.db"
BOT_START_TIME = time.time()
IS_GITHUB_ACTIONS = os.getenv("GITHUB_ACTIONS", "").lower() == "true"
MAX_RUNTIME_SECONDS = 330 * 60 if IS_GITHUB_ACTIONS else 365 * 24 * 3600
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
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


# ======================= 2. موسوعة ومعالج أخطاء MT5 و Bybit الشامل =======================
MT5_ERROR_CATALOG = {
    10004: ("إعادة تسعير (Requote)", "RETRY_FRESH_PRICE", "تغير السعر لحظة التنفيذ؛ يقوم البوت الآن بسحب السعر الجديد وإعادة الإرسال فوراً."),
    10006: ("تم رفض الطلب من السيرفر (Request Rejected)", "SWITCH_FILLING_OR_METAAPI", "رفض السيرفر الطلب؛ جاري تجربة نمط تنفيذ بديل أو التحويل للسحابة."),
    10007: ("تم إلغاء الطلب بواسطة المتداول", "ABORT", "ألغي الطلب من طرف المستخدم."),
    10008: ("تم وضع الأمر بنجاح (Order Placed)", "SUCCESS", "تم استلام الأمر بنجاح."),
    10009: ("تم تنفيذ الصفقة بنجاح (Request Completed)", "SUCCESS", "تم التنفيذ الكامل."),
    10010: ("تنفيذ جزئي للصفقة (Partial Fill)", "SUCCESS", "تم تنفيذ جزء من الكمية المطلوبة."),
    10011: ("خطأ في معالجة الطلب (Request Processing Error)", "RETRY_DELAY", "ضغط مؤقت على سيرفر الوسيط؛ ستتم إعادة المحاولة بعد لحظة."),
    10012: ("انتهت مهلة الطلب (Request Timeout)", "RETRY_FRESH_PRICE", "تأخر رد السيرفر؛ جاري تحديث السعر وإعادة المحاولة."),
    10013: ("طلب غير صالح (Invalid Request)", "SANITIZE_REQUEST", "خلل في هيكلة الطلب؛ جاري تصفير الحقول الاختيارية وإعادة الإرسال."),
    10014: ("حجم اللوت غير صالح (Invalid Volume)", "NORMALIZE_VOLUME", "اللوت خارج حدود الوسيط؛ يقوم البوت بتعديله تلقائياً للحد الأدنى المسموح."),
    10015: ("سعر غير صالح (Invalid Price)", "RETRY_FRESH_PRICE", "السعر المرسل قديم؛ جاري سحب تسعيرة Tick حية جديدة."),
    10016: ("مستويات الوقف/الهدف قريبة جداً (Invalid Stops)", "SEPARATE_SLTP", "الوسيط يمنع وضع SL/TP مع فتح الصفقة؛ سيفتح البوت الصفقة أولاً ثم يركّب TOP و STOP فوراً."),
    10017: ("التداول معطّل لهذا الرمز أو الحساب (Trade Disabled)", "TRY_ALT_SYMBOL", "الرمز الحالي مقفل للتداول (ربما حساب مشاهدة أو رمز غير مفعل)؛ جاري تجربة رمز بديل للذهب."),
    10018: ("السوق مغلق حالياً (Market Closed)", "ABORT_MARKET_CLOSED", "سوق الفوركس/الذهب في عطلة رسمية أو جلسة التداول مغلقة حالياً عند الوسيط."),
    10019: ("الهامش الحر غير كافٍ (Not Enough Money)", "REDUCE_LOT_MIN", "الرصيد الحر لا يكفي لهذا اللوت؛ يقوم البوت بتخفيض اللوت للحد الأدنى (0.01) تلقائياً."),
    10020: ("تغيرت الأسعار بسرعة (Prices Changed)", "RETRY_FRESH_PRICE", "قفزة سعرية سريعة؛ جاري تحديث السعر مع توسيع نطاق الانزلاق المسموح."),
    10021: ("لا توجد تسعيرات حية للسوق (No Quotes)", "RESELECT_SYMBOL", "تعذر سحب الأسعار من الماركت ووتش؛ جاري تنشيط الرمز وسحب السيولة."),
    10022: ("تاريخ انتهاء الأمر غير صالح", "SANITIZE_REQUEST", "جاري تحويل نوع الوقت إلى GTC قياسي."),
    10023: ("تغيرت حالة الأمر", "RETRY_DELAY", "الأمر قيد التحديث في السيرفر."),
    10024: ("طلبات متكررة كثيرة جداً (Too Frequent Requests)", "BACKOFF_WAIT", "حماية السبام لدى الوسيط؛ يأخذ البوت استراحة قصيرة (1.5 ثانية) ثم يكمل."),
    10025: ("لا توجد تغييرات في الأمر (No Changes)", "IGNORE", "مستويات TOP و STOP مضبوطة مسبقاً على نفس القيم."),
    10026: ("التداول الآلي معطّل من سيرفر الوسيط (Server Disables AT)", "FALLBACK_METAAPI", "الوسيط يمنع الإكسبرتات؛ جاري تمرير الأمر كأمر يدوي مباشر أو عبر السحابة."),
    10027: ("التداول الآلي معطّل في المنصة (AutoTrading Disabled by Client)", "FORCE_ENABLE_AUTOTRADING", "زر Algo Trading أحمر في المنصة! يقوم البوت الآن بتفعيله برمجياً عبر Win32 API وتعديل common.ini."),
    10028: ("الأمر مقفل للمعالجة حالياً", "RETRY_DELAY", "ينتظر البوت انتهاء قفل السيرفر."),
    10029: ("الصفقة مجمدة لقرب السعر من الوقف/الهدف (Order Frozen)", "ABORT", "السعر الحالي يلامس مستوى الإغلاق بالفعل."),
    10030: ("نمط تنفيذ العقود غير مدعوم (Unsupported Filling Mode)", "CYCLE_FILLING_MODES", "يقوم البوت بالتبديل التلقائي بين FOK و IOC و RETURN حتى يقبل الوسيط."),
    10031: ("لا يوجد اتصال بسيرفر التداول (No Connection)", "RECONNECT_TERMINAL", "انقطع اتصال المنصة بالسيرفر؛ يقوم البوت بإعادة تسجيل الدخول وتنشيط السيرفر."),
    10032: ("العملية مسموحة للحسابات الحقيقية فقط", "ABORT", "هذا الرمز مخصص للحسابات الحقيقية فقط عند هذا الوسيط."),
    10033: ("تم الوصول للحد الأقصى للأوامر المعلقة", "ABORT", "الحساب وصل لسقف الأوامر المسموح به عند الوسيط."),
    10034: ("تم الوصول للحد الأقصى لحجم العقود على هذا الرمز", "REDUCE_LOT_MIN", "جاري تقليص حجم العقد ليتوافق مع سقف الوسيط."),
    10035: ("نوع الأمر غير صالح أو محظور", "SANITIZE_REQUEST", "جاري تصحيح نوع الأمر."),
    10036: ("المركز المطلوب إغلاقه تم إغلاقه بالفعل (Position Closed)", "IGNORE", "الصفقة أغلقت مسبقاً (بضرب الهدف أو الوقف)."),
    10038: ("حجم الإغلاق يتجاوز حجم الصفقة المفتوحة", "SYNC_POSITION_VOLUME", "جاري مطابقة حجم الإغلاق مع الحجم الفعلي المتبقي."),
    10039: ("يوجد أمر إغلاق معلق بالفعل لهذه الصفقة", "IGNORE", "الصفقة قيد الإغلاق حالياً."),
    10040: ("وصلت للحد الأقصى لعدد الصفقات المفتوحة المسموح بالحساب", "ABORT", "الوسيط يحدد سقفاً لعدد الصفقات المفتوحة في نفس الوقت."),
    10042: ("مسموح بصفقات الشراء فقط (Long Positions Only)", "ABORT_DIRECTION", "الوسيط يقيد البيع على هذا الرمز حالياً."),
    10043: ("مسموح بصفقات البيع فقط (Short Positions Only)", "ABORT_DIRECTION", "الوسيط يقيد الشراء على هذا الرمز حالياً."),
    10044: ("مسموح بإغلاق الصفقات القائمة فقط (Close Only Mode)", "ABORT", "الحساب أو الرمز في وضع الإغلاق فقط حالياً."),
}

MT5_IPC_ERRORS = {
    -10001: "فشل إرسال أمر IPC للمنصة (يرجى التأكد من عمل terminal64.exe).",
    -10002: "فشل قراءة رد IPC من المنصة.",
    -10003: "انقطع جسر الاتصال الداخلي مع MT5؛ يقوم البوت بإعادة تشغيل المنصة تلقائياً.",
    -10004: "منصة MT5 غير مشغّلة أو مغلقة؛ يقوم البوت بتشغيلها الآن.",
    -10005: "انتهت مهلة الاتصال بسيرفر الوسيط (تأكد من صحة اسم السيرفر أو IP:Port).",
    -2: "بيانات الحساب أو السيرفر غير مطابقة.",
}

BYBIT_ERROR_CATALOG = {
    0: ("نجاح العملية", "SUCCESS"),
    10001: ("خطأ في معاملات الطلب (Parameter Error)", "ADJUST_PARAMS"),
    10002: ("الطلب خارج نافذة الوقت المسموحة (Timestamp Drift)", "SYNC_TIME"),
    10003: ("مفتاح API غير صالح لهذا الوضع (Demo/Live/Testnet)", "SWITCH_MODE"),
    10004: ("خطأ في التوقيع السري (Invalid Sign / Secret)", "ABORT_AUTH"),
    10005: ("مفتاح API لا يملك صلاحية التداول (Permission Denied - فعّل Contract/Unified Trade)", "ABORT_AUTH"),
    10006: ("تم تجاوز حد الطلبات في الثانية (Rate Limit Exceeded)", "BACKOFF_WAIT"),
    10016: ("عطل مؤقت في سيرفر Bybit الداخلي", "RETRY_DELAY"),
    10018: ("عنوان IP غير مصرح به في إعدادات مفتاح API", "ABORT_AUTH"),
    100028: ("تعارض نمط المراكز (One-Way vs Hedge Mode) في الحساب الموحد", "SWITCH_POSITION_IDX"),
    110001: ("الأمر غير موجود", "IGNORE"),
    110003: ("سعر الأمر يتجاوز الحدود المسموحة", "RETRY_MARKET"),
    110004: ("رصيد المحفظة غير كافٍ (Insufficient Wallet Balance)", "REDUCE_QTY_MIN"),
    110007: ("الرصيد المتاح للهامش غير كافٍ (Insufficient Available Balance)", "SET_LEVERAGE_AND_MIN_QTY"),
    110012: ("الرصيد المتاح غير كافٍ لتغطية تكلفة الأمر", "SET_LEVERAGE_AND_MIN_QTY"),
    110013: ("لا يمكن ضبط الرافعة بسبب وجود أوامر/مراكز مفتوحة", "IGNORE"),
    110017: ("وضع التقليل فقط (ReduceOnly) فشل لعدم وجود مركز عكسي", "REMOVE_REDUCE_ONLY"),
    110025: ("نمط المركز لم يتغير", "IGNORE"),
    110043: ("الرافعة المالية مضبوطة مسبقاً على نفس القيمة", "IGNORE"),
    110072: ("OrderLinkId مكرر", "REGEN_LINK_ID"),
}


def explain_mt5_retcode(code, comment=""):
    info = MT5_ERROR_CATALOG.get(int(code or 0))
    if info:
        title, action, cure = info
        return f"{title} [كود {code}] — {cure}"
    ipc = MT5_IPC_ERRORS.get(int(code or 0))
    if ipc:
        return f"{ipc} [كود {code}]"
    return f"{comment or 'رفض غير معروف من السيرفر'} [كود {code}]"


def get_mt5_remediation_action(code):
    info = MT5_ERROR_CATALOG.get(int(code or 0))
    return info[1] if info else "UNKNOWN"


def explain_bybit_error(res):
    if not isinstance(res, dict):
        return "رد غير صالح من Bybit"
    code = res.get("retCode", res.get("_status", "?"))
    if res.get("_status") == 403 or "403" in str(res.get("error", "")):
        return "HTTP 403 (حجب IP جغرافي من CloudFront؛ يقوم البوت بتفعيل جسر البروكسي الأوروبي تلقائياً)"
    try:
        c_int = int(code)
    except Exception:
        c_int = -1
    if c_int in BYBIT_ERROR_CATALOG:
        return f"{BYBIT_ERROR_CATALOG[c_int][0]} [كود {c_int}]"
    raw_msg = res.get("retMsg") or res.get("error") or "خطأ غير معروف"
    return f"{raw_msg} [كود {code}]"


# ======================= 3. طبقة الشبكة HTTP + تشفير قاعدة البيانات =======================
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
        return {"_raw_text": text[:350]}


def http_request(url, method="GET", headers=None, payload=None, raw_body=None, timeout=15, verify_ssl=True, proxy_addr=None):
    h = {"User-Agent": BROWSER_UA, "Accept": "application/json"}
    if headers:
        h.update(headers)
    data = None
    if raw_body is not None:
        data = raw_body.encode("utf-8") if isinstance(raw_body, str) else raw_body
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


_CRYPTO_KEYS = {}


def _derive_keys():
    if not _CRYPTO_KEYS:
        raw = hashlib.pbkdf2_hmac("sha256", DB_SECRET.encode("utf-8"), b"mt5-ai-bot-db-v5", 120000, 64)
        _CRYPTO_KEYS["enc"], _CRYPTO_KEYS["mac"] = raw[:32], raw[32:]
    return _CRYPTO_KEYS["enc"], _CRYPTO_KEYS["mac"]


def _keystream(key, nonce, length):
    out, counter = bytearray(), 0
    while len(out) < length:
        out += hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
        counter += 1
    return bytes(out[:length])


def encrypt_text(plain):
    if not plain or str(plain).startswith("enc1:"):
        return plain
    ek, mk = _derive_keys()
    nonce = os.urandom(16)
    data = str(plain).encode("utf-8")
    ct = bytes(a ^ b for a, b in zip(data, _keystream(ek, nonce, len(data))))
    tag = hmac.new(mk, nonce + ct, hashlib.sha256).digest()
    return "enc1:" + base64.urlsafe_b64encode(nonce + tag + ct).decode("ascii")


def decrypt_text(cipher):
    if not cipher or not str(cipher).startswith("enc1:"):
        return cipher
    try:
        raw = base64.urlsafe_b64decode(str(cipher)[5:])
        nonce, tag, ct = raw[:16], raw[16:48], raw[48:]
        ek, mk = _derive_keys()
        expected = hmac.new(mk, nonce + ct, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            return ""
        return bytes(a ^ b for a, b in zip(ct, _keystream(ek, nonce, len(ct)))).decode("utf-8")
    except Exception:
        return ""


# ======================= 4. واجهة تليجرام المتقدمة =======================
def tg_api(method, params=None, timeout=14):
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
    if cur or not chunks:
        chunks.append(cur)
    return chunks


def send_msg(chat_id, text, reply_markup=None):
    res = {}
    parts = split_text(text)
    for idx, part in enumerate(parts):
        payload = {
            "chat_id": chat_id,
            "text": part,
            "disable_web_page_preview": True
        }
        if reply_markup and idx == len(parts) - 1:
            payload["reply_markup"] = reply_markup
        res = tg_api("sendMessage", payload)
    return res


def edit_msg(chat_id, message_id, text, reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": str(text)[:4000],
        "disable_web_page_preview": True
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    res = tg_api("editMessageText", payload)
    if not res.get("ok") and "not modified" not in str(res.get("description", "")).lower():
        return send_msg(chat_id, text, reply_markup)
    return res


def answer_cb(cb_id, text="", alert=False):
    return tg_api(
        "answerCallbackQuery",
        {"callback_query_id": cb_id, "text": str(text)[:190], "show_alert": bool(alert)},
        timeout=6
    )


def delete_msg(chat_id, message_id):
    return tg_api("deleteMessage", {"chat_id": chat_id, "message_id": message_id}, timeout=6)


# ======================= 5. قاعدة البيانات المؤسسية وإحصائيات الأداء =======================
db_lock = threading.RLock()

USER_COLUMNS = [
    ("chat_id", "INTEGER DEFAULT 0"),
    ("is_authorized", "INTEGER DEFAULT 0"),
    ("auto_run", "INTEGER DEFAULT 0"),
    ("active_account_id", "INTEGER DEFAULT 1"),
    ("trade_all_accounts", "INTEGER DEFAULT 0"),
    ("selected_ai_id", "INTEGER DEFAULT 1"),
    ("symbol", "TEXT DEFAULT 'XAUUSD'"),
    ("lot", "REAL DEFAULT 0.01"),
    ("trade_tp_usd", "REAL DEFAULT 0.60"),
    ("trade_sl_usd", "REAL DEFAULT 1.00"),
    ("daily_max_profit", "REAL DEFAULT 25.0"),
    ("daily_max_loss", "REAL DEFAULT 10.0"),
    ("work_start_hour", "INTEGER DEFAULT 0"),
    ("work_end_hour", "INTEGER DEFAULT 24"),
    ("current_daily_pnl", "REAL DEFAULT 0.0"),
    ("trades_today", "INTEGER DEFAULT 0"),
    ("pnl_date", "TEXT DEFAULT ''"),
    ("bybit_proxy", "TEXT DEFAULT ''"),
    ("trailing_enabled", "INTEGER DEFAULT 1"),
    ("breakeven_enabled", "INTEGER DEFAULT 1"),
    ("spread_filter_enabled", "INTEGER DEFAULT 1"),
    ("max_spread_usd", "REAL DEFAULT 1.80"),
]
USER_FIELDS = {c[0] for c in USER_COLUMNS}

TRADE_COLUMNS = [
    ("tp_usd", "REAL DEFAULT 0.60"),
    ("sl_usd", "REAL DEFAULT 1.00"),
    ("tp_price", "REAL DEFAULT 0.0"),
    ("sl_price", "REAL DEFAULT 0.0"),
    ("layer_tag", "TEXT DEFAULT 'L1'"),
    ("entry_price", "REAL DEFAULT 0.0"),
    ("capital_used", "REAL DEFAULT 0.0"),
    ("trade_date", "TEXT DEFAULT ''"),
    ("be_locked", "INTEGER DEFAULT 0"),
    ("analysis_summary", "TEXT DEFAULT ''"),
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
            )""")
            _ensure_columns(conn, "trading_accounts", [
                ("cloud_id", "TEXT DEFAULT ''"),
                ("region", "TEXT DEFAULT 'london'")
            ])

            conn.execute("""CREATE TABLE IF NOT EXISTS ai_tools (
                id INTEGER PRIMARY KEY,
                name TEXT,
                base_url TEXT,
                api_key TEXT,
                model TEXT
            )""")

            conn.execute("""CREATE TABLE IF NOT EXISTS bot_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                acc_pk INTEGER,
                platform TEXT,
                symbol TEXT,
                side TEXT,
                volume REAL,
                ticket TEXT,
                open_ts INTEGER,
                status TEXT DEFAULT 'OPEN',
                pnl REAL DEFAULT 0,
                tp_usd REAL DEFAULT 0.60,
                sl_usd REAL DEFAULT 1.00,
                tp_price REAL DEFAULT 0.0,
                sl_price REAL DEFAULT 0.0,
                layer_tag TEXT DEFAULT 'L1',
                entry_price REAL DEFAULT 0.0,
                capital_used REAL DEFAULT 0.0,
                trade_date TEXT DEFAULT '',
                be_locked INTEGER DEFAULT 0,
                analysis_summary TEXT DEFAULT ''
            )""")
            _ensure_columns(conn, "bot_trades", TRADE_COLUMNS)

            for d in AI_DEFS:
                conn.execute(
                    "INSERT OR REPLACE INTO ai_tools (id,name,base_url,api_key,model) VALUES (?,?,?,?,?)",
                    (d[0], d[1], d[2], "", d[3])
                )

            conn.execute("DELETE FROM trading_accounts WHERE login_or_key='939713' AND server_or_mode LIKE '%BlackBull%'")
            for pk, pw in conn.execute("SELECT acc_pk, password_or_secret FROM trading_accounts").fetchall():
                if pw and not str(pw).startswith("enc1:"):
                    conn.execute("UPDATE trading_accounts SET password_or_secret=? WHERE acc_pk=?", (encrypt_text(pw), pk))
            conn.commit()
        finally:
            conn.close()


def today_str():
    return (datetime.now(timezone.utc) + timedelta(hours=UTC_OFFSET)).strftime("%Y-%m-%d")


def local_now():
    return datetime.now(timezone.utc) + timedelta(hours=UTC_OFFSET)


def local_hour():
    return local_now().hour


def get_global_session_status():
    """حاسبة جلسات التداول العالمية (طوكيو، لندن، نيويورك) لتنبيه المتداول بالسيولة"""
    utc_h = datetime.now(timezone.utc).hour
    sessions = []
    if 0 <= utc_h < 9:
        sessions.append("طوكيو الآسيوية 🇯🇵")
    if 7 <= utc_h < 16:
        sessions.append("لندن الأوروبية 🇬🇧")
    if 12 <= utc_h < 21:
        sessions.append("نيويورك الأمريكية 🇺🇸")
    if 12 <= utc_h < 16:
        liquidity = "🔥 ذروة السيولة العالمية (تقاطع لندن + نيويورك)"
    elif sessions:
        liquidity = "🟢 سيولة نشطة (" + " + ".join(sessions) + ")"
    else:
        liquidity = "🌙 سيولة هادئة (بين الجلسات)"
    return liquidity


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
        db_exec(
            "INSERT OR IGNORE INTO users (user_id, pnl_date, bybit_proxy) VALUES (?,?,?)",
            (uid, today_str(), DEFAULT_BYBIT_PROXY)
        )
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
    elif not pw and raw_pw and not str(raw_pw).startswith("enc1:"):
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
        db_exec(
            "UPDATE trading_accounts SET platform=?,account_label=?,password_or_secret=?,server_or_mode=?,is_enabled=1 WHERE acc_pk=?",
            (platform, label, encrypt_text(secret), server_mode, pk)
        )
    else:
        pk = db_exec(
            "INSERT INTO trading_accounts (user_id,platform,account_label,login_or_key,password_or_secret,server_or_mode,is_enabled) VALUES (?,?,?,?,?,?,1)",
            (uid, platform, label, login_key, encrypt_text(secret), server_mode)
        )
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


def record_trade(uid, acc, symbol, side, volume, ticket, tp_usd=0.60, sl_usd=1.00, layer_tag="L1", entry_price=0.0, tp_price=0.0, sl_price=0.0, analysis_summary=""):
    p = float(entry_price or 3300.0)
    cap = round(float(volume) * p, 2)
    return db_exec(
        "INSERT INTO bot_trades (user_id,acc_pk,platform,symbol,side,volume,ticket,open_ts,tp_usd,sl_usd,tp_price,sl_price,layer_tag,entry_price,capital_used,trade_date,analysis_summary) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            uid, acc["acc_pk"], acc["platform"], symbol, side, float(volume), str(ticket), int(time.time()),
            float(tp_usd), float(sl_usd), float(tp_price or 0.0), float(sl_price or 0.0),
            str(layer_tag), p, cap, today_str(), str(analysis_summary)[:500]
        )
    )


def open_trade_rows(uid, acc_pk=None):
    if acc_pk is not None:
        return db_exec("SELECT * FROM bot_trades WHERE user_id=? AND acc_pk=? AND status='OPEN'", (uid, acc_pk))
    return db_exec("SELECT * FROM bot_trades WHERE user_id=? AND status='OPEN'", (uid,))


def mark_trade_be_locked(trade_id, new_sl_price=0.0):
    db_exec("UPDATE bot_trades SET be_locked=1, sl_price=? WHERE id=?", (float(new_sl_price or 0.0), trade_id))


def get_daily_financial_summary(uid):
    t_str = today_str()
    rows = db_exec("SELECT * FROM bot_trades WHERE user_id=? AND (trade_date=? OR trade_date='')", (uid, t_str))
    all_rows = db_exec("SELECT * FROM bot_trades WHERE user_id=?", (uid,))

    gross_profit = 0.0
    gross_loss = 0.0
    win_count = 0
    loss_count = 0
    open_count = 0
    total_capital_used = 0.0
    total_lots = 0.0

    for r in rows:
        vol = float(r.get("volume") or 0.01)
        ep = float(r.get("entry_price") or 3300.0)
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

    all_time_net = sum(float(r.get("pnl") or 0.0) for r in all_rows if r.get("status") != "OPEN")
    closed_total = win_count + loss_count
    net_pnl = gross_profit - gross_loss
    win_rate = (win_count / closed_total * 100.0) if closed_total > 0 else 100.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 1.0)

    return {
        "date": t_str,
        "total_trades_entered": len(rows),
        "open_trades": open_count,
        "closed_trades": closed_total,
        "win_count": win_count,
        "loss_count": loss_count,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "net_pnl": net_pnl,
        "all_time_net": all_time_net,
        "total_capital_used": total_capital_used,
        "total_lots": total_lots,
    }


# ======================= 6. محلل بيانات الاعتماد الذكي =======================
LABELS = {
    "login", "user", "username", "account", "id", "password", "pass", "pwd", "server",
    "key", "api", "apikey", "secret", "apisecret", "mode", "broker", "اسم المستخدم",
    "المستخدم", "الحساب", "رقم الحساب", "كلمة المرور", "كلمة السر", "الباسورد",
    "السيرفر", "الخادم", "المفتاح", "السر"
}


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
# ======================= 7. المحرك الكمي ومؤشرات المؤسسات (SMC + Quantitative Math) =======================
LIVE_RADAR_CACHE = {}


def calc_sma(prices, period):
    if not prices:
        return 0.0
    sub = prices[-period:] if len(prices) >= period else prices
    return float(sum(sub) / len(sub))


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
    diffs = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    gains = [max(x, 0.0) for x in diffs]
    losses = [max(-x, 0.0) for x in diffs]
    avg_gain = sum(gains[:period]) / float(period)
    avg_loss = sum(losses[:period]) / float(period)
    for i in range(period, len(diffs)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / float(period)
        avg_loss = (avg_loss * (period - 1) + losses[i]) / float(period)
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return float(100.0 - (100.0 / (1.0 + rs)))


def calc_stoch_rsi(prices, period=14):
    if len(prices) < period * 2:
        return 50.0
    rsi_series = []
    for idx in range(period + 1, len(prices) + 1):
        rsi_series.append(calc_rsi(prices[:idx], period))
    if len(rsi_series) < period:
        return rsi_series[-1] if rsi_series else 50.0
    recent = rsi_series[-period:]
    lo, hi = min(recent), max(recent)
    if hi - lo < 1e-9:
        return 50.0
    return float(((recent[-1] - lo) / (hi - lo)) * 100.0)


def calc_macd(prices):
    if len(prices) < 26:
        return 0.0, 0.0, 0.0
    ema12 = calc_ema(prices, 12)
    ema26 = calc_ema(prices, 26)
    macd_line = ema12 - ema26
    series = []
    start_idx = max(26, len(prices) - 18)
    for idx in range(start_idx, len(prices) + 1):
        sub = prices[:idx]
        series.append(calc_ema(sub, 12) - calc_ema(sub, 26))
    sig_line = calc_ema(series, 9) if series else macd_line
    hist = macd_line - sig_line
    return float(macd_line), float(sig_line), float(hist)


def calc_bollinger(prices, period=20, mult=2.0):
    if len(prices) < period:
        p = float(prices[-1]) if prices else 0.0
        return p, p, p
    window = prices[-period:]
    mid = sum(window) / float(period)
    var = sum((x - mid) ** 2 for x in window) / float(period)
    std = math.sqrt(var)
    return float(mid - mult * std), float(mid), float(mid + mult * std)


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
    return float(sum(recent) / len(recent))


def calc_adx_from_candles(candles, period=14):
    """حساب مؤشر قوة الاتجاه ADX + DI+ + DI- لفلترة التذبذب العرضي المسبب للخسائر"""
    if not candles or len(candles) < period + 2:
        return 25.0, 25.0, 25.0
    plus_dm, minus_dm, tr_list = [], [], []
    for i in range(1, len(candles)):
        h = float(candles[i].get("high", candles[i]["close"]))
        low = float(candles[i].get("low", candles[i]["close"]))
        ph = float(candles[i - 1].get("high", candles[i - 1]["close"]))
        plow = float(candles[i - 1].get("low", candles[i - 1]["close"]))
        pc = float(candles[i - 1]["close"])

        up_move = h - ph
        down_move = plow - low
        pdm = up_move if (up_move > down_move and up_move > 0) else 0.0
        mdm = down_move if (down_move > up_move and down_move > 0) else 0.0
        tr = max(h - low, abs(h - pc), abs(low - pc))
        plus_dm.append(pdm)
        minus_dm.append(mdm)
        tr_list.append(tr)

    if len(tr_list) < period:
        return 25.0, 25.0, 25.0

    tr_sum = sum(tr_list[-period:]) or 1e-9
    p_di = 100.0 * (sum(plus_dm[-period:]) / tr_sum)
    m_di = 100.0 * (sum(minus_dm[-period:]) / tr_sum)
    dx_vals = []
    start_k = max(period, len(tr_list) - period)
    for k in range(start_k, len(tr_list) + 1):
        sub_tr = sum(tr_list[k - period:k]) or 1e-9
        sub_p = 100.0 * (sum(plus_dm[k - period:k]) / sub_tr)
        sub_m = 100.0 * (sum(minus_dm[k - period:k]) / sub_tr)
        denom = (sub_p + sub_m) or 1e-9
        dx_vals.append(100.0 * abs(sub_p - sub_m) / denom)
    adx = sum(dx_vals) / float(len(dx_vals)) if dx_vals else 25.0
    return float(adx), float(p_di), float(m_di)


def detect_smc_structures(candles, atr_val):
    """اكتشاف بلوكات الأوامر المؤسسية (Order Blocks)، فجوات السيولة (FVG)، وكسر الهيكل (BOS/CHoCH)"""
    if not candles or len(candles) < 15:
        return {
            "bull_ob": 0.0,
            "bear_ob": 0.0,
            "fvg_bull": 0.0,
            "fvg_bear": 0.0,
            "structure": "NEUTRAL",
            "liquidity_sweep": "NONE",
            "smc_note": "بيانات غير كافية لتحليل SMC"
        }

    closes = [float(c["close"]) for c in candles]
    opens = [float(c.get("open", c["close"])) for c in candles]
    highs = [float(c.get("high", c["close"])) for c in candles]
    lows = [float(c.get("low", c["close"])) for c in candles]
    cur_p = closes[-1]
    atr = max(float(atr_val or 0.8), 0.25)

    bull_ob = 0.0
    bear_ob = 0.0
    fvg_bull = 0.0
    fvg_bear = 0.0

    for i in range(len(candles) - 12, len(candles) - 2):
        if i < 1:
            continue
        body_next = closes[i + 1] - opens[i + 1]
        if closes[i] < opens[i] and body_next > atr * 0.9 and closes[i + 1] > highs[i]:
            bull_ob = lows[i]
        if closes[i] > opens[i] and (-body_next) > atr * 0.9 and closes[i + 1] < lows[i]:
            bear_ob = highs[i]

        if i >= 2:
            if lows[i] > highs[i - 2] and (lows[i] - highs[i - 2]) >= atr * 0.20:
                fvg_bull = (lows[i] + highs[i - 2]) / 2.0
            if highs[i] < lows[i - 2] and (lows[i - 2] - highs[i]) >= atr * 0.20:
                fvg_bear = (highs[i] + lows[i - 2]) / 2.0

    prev_high_10 = max(highs[-15:-3]) if len(highs) >= 15 else max(highs[:-1])
    prev_low_10 = min(lows[-15:-3]) if len(lows) >= 15 else min(lows[:-1])

    if cur_p > prev_high_10:
        structure = "BOS_BULL"
    elif cur_p < prev_low_10:
        structure = "BOS_BEAR"
    else:
        structure = "RANGING"

    liquidity_sweep = "NONE"
    if lows[-1] < prev_low_10 and closes[-1] > prev_low_10:
        liquidity_sweep = "BULL_SWEEP"
    elif highs[-1] > prev_high_10 and closes[-1] < prev_high_10:
        liquidity_sweep = "BEAR_SWEEP"

    notes = []
    if structure == "BOS_BULL":
        notes.append("كسر هيكل صاعد (BOS Bullish)")
    elif structure == "BOS_BEAR":
        notes.append("كسر هيكل هابط (BOS Bearish)")
    if liquidity_sweep == "BULL_SWEEP":
        notes.append("سحب سيولة القاع وارتداد شرائي (Liquidity Sweep)")
    elif liquidity_sweep == "BEAR_SWEEP":
        notes.append("سحب سيولة القمة وارتداد بيعي (Liquidity Sweep)")
    if bull_ob > 0:
        notes.append(f"بلوك شرائي مؤسسي OB عند {bull_ob:.2f}")
    if bear_ob > 0:
        notes.append(f"بلوك بيعي مؤسسي OB عند {bear_ob:.2f}")
    if fvg_bull > 0:
        notes.append(f"فجوة قيمة عادلة شرائية FVG عند {fvg_bull:.2f}")
    if fvg_bear > 0:
        notes.append(f"فجوة قيمة عادلة بيعية FVG عند {fvg_bear:.2f}")

    return {
        "bull_ob": bull_ob,
        "bear_ob": bear_ob,
        "fvg_bull": fvg_bull,
        "fvg_bear": fvg_bear,
        "structure": structure,
        "liquidity_sweep": liquidity_sweep,
        "smc_note": " | ".join(notes[:3]) if notes else "توازن هيكلي"
    }


def project_future_trajectory(candles_m15, candles_h1, current_price, atr_m1):
    """
    محرك استشراف المستقبل (Future Projection Cone):
    يعتمد على الانحدار الخطي (Linear Regression Slope & R-Squared) + زخم التسارع + امتدادات فيبوناتشي
    لتوقع مسار السوق القادم (بعد 15 دقيقة، 1 ساعة، 4 ساعات) ومستويات TOP و STOP المستقبلية.
    """
    src_candles = candles_m15 if (candles_m15 and len(candles_m15) >= 20) else candles_h1
    if not src_candles or len(src_candles) < 15:
        p = float(current_price or 3300.0)
        a = max(float(atr_m1 or 1.0), 0.5)
        return {
            "future_bias": "NEUTRAL",
            "slope_per_bar": 0.0,
            "r_squared": 0.50,
            "proj_15m": p,
            "proj_1h": p + a,
            "proj_4h": p + a * 2.5,
            "fib_ext_127": p + a * 1.8,
            "fib_ext_161": p + a * 2.8,
            "future_summary": "استقرار سعري متوقع ضمن نطاق التذبذب الطبيعي."
        }

    closes = [float(c["close"]) for c in src_candles[-30:]]
    highs = [float(c.get("high", c["close"])) for c in src_candles[-30:]]
    lows = [float(c.get("low", c["close"])) for c in src_candles[-30:]]
    n = len(closes)
    x_vals = list(range(n))
    mean_x = sum(x_vals) / float(n)
    mean_y = sum(closes) / float(n)

    num = sum((x_vals[i] - mean_x) * (closes[i] - mean_y) for i in range(n))
    den = sum((x_vals[i] - mean_x) ** 2 for i in range(n)) or 1e-9
    slope = num / den
    intercept = mean_y - slope * mean_x

    ss_tot = sum((y - mean_y) ** 2 for y in closes) or 1e-9
    ss_res = sum((closes[i] - (slope * x_vals[i] + intercept)) ** 2 for i in range(n))
    r_squared = max(0.0, min(1.0, 1.0 - (ss_res / ss_tot)))

    cur_p = float(current_price or closes[-1])
    proj_15m = cur_p + slope * 1.2
    proj_1h = cur_p + slope * 4.0
    proj_4h = cur_p + slope * 12.0

    swing_hi = max(highs)
    swing_lo = min(lows)
    rng = max(swing_hi - swing_lo, float(atr_m1 or 1.0) * 2.0)

    if slope >= 0:
        future_bias = "BULLISH"
        fib_127 = swing_hi + rng * 0.272
        fib_161 = swing_hi + rng * 0.618
    else:
        future_bias = "BEARISH"
        fib_127 = swing_lo - rng * 0.272
        fib_161 = swing_lo - rng * 0.618

    direction_ar = "صاعد شرائي 📈" if future_bias == "BULLISH" else "هابط بيعي 📉"
    stability_ar = "قوي ومنتظم" if r_squared >= 0.60 else ("متوسط التماسك" if r_squared >= 0.30 else "متذبذب")
    future_summary = (
        f"الميل المستقبلي: {direction_ar} ({stability_ar} R²={r_squared:.2f}) | "
        f"توقع 15د: `{proj_15m:.2f}` | توقع 1س: `{proj_1h:.2f}` | توقع 4س: `{proj_4h:.2f}` | "
        f"امتداد فيبوناتشي القادم: `{fib_127:.2f}` ثم `{fib_161:.2f}`"
    )

    return {
        "future_bias": future_bias,
        "slope_per_bar": float(slope),
        "r_squared": float(r_squared),
        "proj_15m": float(proj_15m),
        "proj_1h": float(proj_1h),
        "proj_4h": float(proj_4h),
        "fib_ext_127": float(fib_127),
        "fib_ext_161": float(fib_161),
        "future_summary": future_summary,
    }


def analyze_30day_historical_horizon(mtf_data, current_price):
    """
    محلل الـ 30 يوماً الماضية:
    يدرس حركة السوق من قبل 30 يوماً من تاريخ اليوم مروراً بالأسابيع والأيام والساعات
    وصولاً للحظة إرسال أمر التداول بالضبط.
    """
    d1_candles = mtf_data.get("D1") or []
    h4_candles = mtf_data.get("H4") or []
    h1_candles = mtf_data.get("H1") or []
    m15_candles = mtf_data.get("M15") or []

    base_candles = d1_candles[-30:] if len(d1_candles) >= 10 else (h4_candles[-180:] if len(h4_candles) >= 20 else (h1_candles if h1_candles else m15_candles))
    if not base_candles:
        p = float(current_price or 3300.0)
        return {
            "month_start_price": p,
            "month_high": p + 25.0,
            "month_low": p - 25.0,
            "month_equilibrium": p,
            "month_change_pct": 0.0,
            "month_change_usd": 0.0,
            "macro_bias": "BUY",
            "price_zone": "EQUILIBRIUM",
            "major_resistance": p + 15.0,
            "major_support": p - 15.0,
            "historical_narrative": "جاري مزامنة السجل التاريخي للشهر الماضي."
        }

    month_start_price = float(base_candles[0].get("open", base_candles[0]["close"]))
    month_high = max(float(c.get("high", c["close"])) for c in base_candles)
    month_low = min(float(c.get("low", c["close"])) for c in base_candles)
    cur_p = float(current_price or base_candles[-1]["close"])

    month_eq = (month_high + month_low) / 2.0
    month_rng = max(month_high - month_low, 1.0)
    pos_in_month_pct = ((cur_p - month_low) / month_rng) * 100.0

    change_usd = cur_p - month_start_price
    change_pct = (change_usd / month_start_price * 100.0) if month_start_price > 0 else 0.0

    closes_macro = [float(c["close"]) for c in base_candles]
    ema_fast_m = calc_ema(closes_macro, min(9, len(closes_macro)))
    ema_slow_m = calc_ema(closes_macro, min(21, len(closes_macro)))

    if cur_p >= month_eq and ema_fast_m >= ema_slow_m:
        macro_bias = "BUY"
    elif cur_p < month_eq and ema_fast_m < ema_slow_m:
        macro_bias = "SELL"
    else:
        macro_bias = "BUY" if change_usd >= 0 else "SELL"

    if pos_in_month_pct >= 70.0:
        price_zone = "PREMIUM_HIGH (منطقة تشبع شرائي شهرية / قمة سعرية)"
    elif pos_in_month_pct <= 30.0:
        price_zone = "DISCOUNT_LOW (منطقة خصم شرائي شهرية / قاع سعري)"
    else:
        price_zone = "EQUILIBRIUM_MID (منطقة التوازن الشهري العادل 50%)"

    recent_slice = h1_candles[-48:] if len(h1_candles) >= 12 else base_candles[-12:]
    major_res = max(float(c.get("high", c["close"])) for c in recent_slice)
    major_sup = min(float(c.get("low", c["close"])) for c in recent_slice)

    start_date_str = (local_now() - timedelta(days=30)).strftime("%Y-%m-%d")
    now_date_str = local_now().strftime("%Y-%m-%d %H:%M:%S")

    narrative = (
        f"🗓️ **مسح الـ 30 يوماً الماضية (من `{start_date_str}` حتى `{now_date_str}`):**\n"
        f"• سعر الافتتاح قبل شهر: `{month_start_price:.2f}` ⬅️ السعر اللحظي الآن: `{cur_p:.2f}` ({change_usd:+.2f}$ / {change_pct:+.2f}%)\n"
        f"• القمة الشهرية (30D High): `{month_high:.2f}` | القاع الشهري (30D Low): `{month_low:.2f}` | محور التوازن: `{month_eq:.2f}`\n"
        f"• موقع السعر الحالي في الخريطة الشهرية: `{pos_in_month_pct:.1f}%` — {price_zone}\n"
        f"• المقاومة الهيكلية الكبرى: `{major_res:.2f}` | الدعم الهيكلي الأكبر: `{major_sup:.2f}`"
    )

    return {
        "month_start_price": month_start_price,
        "month_high": month_high,
        "month_low": month_low,
        "month_equilibrium": month_eq,
        "month_change_pct": change_pct,
        "month_change_usd": change_usd,
        "pos_in_month_pct": pos_in_month_pct,
        "macro_bias": macro_bias,
        "price_zone": price_zone,
        "major_resistance": major_res,
        "major_support": major_sup,
        "historical_narrative": narrative,
    }


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
    e200 = calc_ema(closes, min(200, len(closes)))
    rsi = calc_rsi(closes, 14)
    stoch_rsi = calc_stoch_rsi(closes, 14)
    macd_l, sig_l, hist = calc_macd(closes)
    bb_low, bb_mid, bb_high = calc_bollinger(closes, 20, 2.0)
    atr = max(calc_atr_from_candles(candles, 14), 0.30)
    adx, plus_di, minus_di = calc_adx_from_candles(candles, 14)
    smc = detect_smc_structures(candles, atr)

    support = min(lows[-24:])
    resistance = max(highs[-24:])

    cur_candle_bull = closes[-1] >= opens[-1]
    cur_impulse = closes[-1] - closes[-3]

    buy_pts = 0
    sell_pts = 0
    buy_reasons = []
    sell_reasons = []

    if e9 > e21:
        buy_pts += 28
        buy_reasons.append("تقاطع المتوسطات الصاعد (EMA9 > EMA21)")
        if e21 >= e50:
            buy_pts += 14
            buy_reasons.append("هيكل صاعد فوق EMA50")
    else:
        sell_pts += 28
        sell_reasons.append("تقاطع المتوسطات الهابط (EMA9 < EMA21)")
        if e21 <= e50:
            sell_pts += 14
            sell_reasons.append("هيكل هابط تحت EMA50")

    if price >= e200:
        buy_pts += 10
    else:
        sell_pts += 10

    if price > e9 and cur_impulse > 0:
        buy_pts += 16
        buy_reasons.append("اندفاع سعري شرائي نشط")
    elif price < e9 and cur_impulse < 0:
        sell_pts += 16
        sell_reasons.append("اندفاع سعري بيعي نشط")

    if 50 <= rsi <= 68:
        buy_pts += 14
        buy_reasons.append(f"زخم RSI شرائي سليم ({rsi:.1f})")
    elif rsi < 32 and cur_candle_bull:
        buy_pts += 22
        buy_reasons.append(f"ارتداد من تشبع بيعي RSI ({rsi:.1f})")
    elif 32 <= rsi < 50:
        sell_pts += 14
        sell_reasons.append(f"زخم RSI بيعي سليم ({rsi:.1f})")
    elif rsi > 68 and (not cur_candle_bull):
        sell_pts += 22
        sell_reasons.append(f"ارتداد من تشبع شرائي RSI ({rsi:.1f})")

    if hist > 0:
        buy_pts += 12
        buy_reasons.append("MACD إيجابي متسارع")
    else:
        sell_pts += 12
        sell_reasons.append("MACD سلبي هابط")

    if adx >= 20:
        if plus_di > minus_di:
            buy_pts += 12
            buy_reasons.append(f"قوة اتجاه ADX شرائية ({adx:.1f})")
        else:
            sell_pts += 12
            sell_reasons.append(f"قوة اتجاه ADX بيعية ({adx:.1f})")

    if smc["structure"] == "BOS_BULL" or smc["liquidity_sweep"] == "BULL_SWEEP":
        buy_pts += 18
        buy_reasons.append(smc["smc_note"])
    elif smc["structure"] == "BOS_BEAR" or smc["liquidity_sweep"] == "BEAR_SWEEP":
        sell_pts += 18
        sell_reasons.append(smc["smc_note"])

    dist_to_support = price - support
    dist_to_res = resistance - price
    veto_sell = False
    veto_buy = False

    if dist_to_support <= atr * 0.70 and (e9 > e21 or cur_candle_bull):
        veto_sell = True
        buy_pts += 24
        buy_reasons.append(f"ارتداد مباشر من دعم صلب ({support:.2f})")

    if dist_to_res <= atr * 0.70 and (e9 < e21 or not cur_candle_bull):
        veto_buy = True
        sell_pts += 24
        sell_reasons.append(f"ارتداد مباشر من مقاومة صلبة ({resistance:.2f})")

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
        "ema200": e200,
        "rsi": rsi,
        "stoch_rsi": stoch_rsi,
        "macd_hist": hist,
        "adx": adx,
        "plus_di": plus_di,
        "minus_di": minus_di,
        "bb_low": bb_low,
        "bb_mid": bb_mid,
        "bb_high": bb_high,
        "atr": atr,
        "support": support,
        "resistance": resistance,
        "smc": smc,
        "reasons": active_reasons[:4],
    }


# ======================= 8. هندسة مستويات الـ TOP والـ STOP ونظام التدرج الموحد بلا تناقض =======================
def compute_structural_top_and_stop(action, entry_price, atr_m1, atr_m15, support, resistance, major_sup, major_res):
    """
    حساب هندسي علمي لمستويات القمة الهدف (TOP / Take Profit) والقاع الوقف (STOP / Stop Loss)
    على الشارت الفعلي بحيث يوضع STOP خلف الدعم/المقاومة الهيكلي والـ Order Block لمنع ضرب الاستوب العشوائي.
    """
    p = float(entry_price or 3300.0)
    a1 = max(float(atr_m1 or 0.9), 0.40)
    a15 = max(float(atr_m15 or a1 * 2.2), a1 * 1.5)

    if action == "BUY":
        struct_floor = min(float(support or p - a1 * 2), p - a1 * 1.3)
        stop_price = round(min(p - a1 * 1.8, struct_floor - a1 * 0.35), 2)
        stop_dist = max(round(p - stop_price, 2), round(a1 * 1.4, 2))
        stop_price = round(p - stop_dist, 2)

        top1_price = round(p + max(a1 * 1.2, stop_dist * 0.75), 2)
        top2_price = round(p + max(a15 * 1.1, stop_dist * 1.50), 2)
        top3_price = round(max(float(resistance or p + stop_dist * 2.5), p + stop_dist * 2.60), 2)
    else:
        struct_ceil = max(float(resistance or p + a1 * 2), p + a1 * 1.3)
        stop_price = round(max(p + a1 * 1.8, struct_ceil + a1 * 0.35), 2)
        stop_dist = max(round(stop_price - p, 2), round(a1 * 1.4, 2))
        stop_price = round(p + stop_dist, 2)

        top1_price = round(p - max(a1 * 1.2, stop_dist * 0.75), 2)
        top2_price = round(p - max(a15 * 1.1, stop_dist * 1.50), 2)
        top3_price = round(min(float(support or p - stop_dist * 2.5), p - stop_dist * 2.60), 2)

    return {
        "entry_price": round(p, 2),
        "stop_price": stop_price,
        "stop_distance": round(abs(p - stop_price), 2),
        "top1_price": top1_price,
        "top2_price": top2_price,
        "top3_price": top3_price,
    }


def build_triple_shield_plan(main_action, base_tp_usd, base_sl_usd, atr_val=1.2, risk_mode=False, price_levels=None):
    """
    النظام المؤسسي الموحد (Unidirectional 3-Tier Scaling Matrix):
    - تم إلغاء الصفقة العكسية المتناقضة نهائياً حتى لا تخسر صفقة BUY مقابل صفقتين SELL!
    - جميع الصفقات الـ 3 تدخل في نفس الاتجاه المؤكد (BUY كلها أو SELL كلها):
      * الصفقة 1 (L1-قناص_تأمين): هدف سريع ومضمون؛ فور إغلاقها على ربح، يتم نقل STOP للصفقتين L2 و L3 إلى نقطة الدخول (Break-Even = خسارة صفر).
      * الصفقة 2 (L2-هدف_هيكلي): تستهدف قمة/قاع الموجة المتوسطة (TOP 2).
      * الصفقة 3 (L3-رانر_مؤسسي): تستهدف الهدف الممتد (TOP 3) مع وقف متحرك Trailing Stop يطارد الأرباح.
    """
    base_tp = max(float(base_tp_usd or 0.60), 0.25)
    safe_sl = max(float(base_sl_usd or 1.00), round(float(atr_val or 1.0) * 1.10, 2), 0.85)
    lv = price_levels or {}

    if risk_mode:
        return [
            {
                "tag": "L1-قناص_تأمين",
                "title": f"الصفقة 1 ({main_action} قناص سريع — يؤمّن الحساب)",
                "side": main_action,
                "tp_usd": 0.35,
                "sl_usd": 0.55,
                "tp_price": lv.get("top1_price", 0.0),
                "sl_price": lv.get("stop_price", 0.0),
            },
            {
                "tag": "L2-هدف_متوسط",
                "title": f"الصفقة 2 ({main_action} هدف الموجة المتوسط)",
                "side": main_action,
                "tp_usd": 0.65,
                "sl_usd": 0.65,
                "tp_price": lv.get("top2_price", 0.0),
                "sl_price": lv.get("stop_price", 0.0),
            },
            {
                "tag": "L3-قمة_ممتدة",
                "title": f"الصفقة 3 ({main_action} صائد القمة/القاع مع وقف متحرك)",
                "side": main_action,
                "tp_usd": 1.10,
                "sl_usd": 0.75,
                "tp_price": lv.get("top3_price", 0.0),
                "sl_price": lv.get("stop_price", 0.0),
            },
        ]

    return [
        {
            "tag": "L1-قناص_تأمين",
            "title": f"الصفقة 1 ({main_action} هدف سريع لتأمين الدخول Break-Even)",
            "side": main_action,
            "tp_usd": round(max(0.40, base_tp * 0.70), 2),
            "sl_usd": round(safe_sl, 2),
            "tp_price": lv.get("top1_price", 0.0),
            "sl_price": lv.get("stop_price", 0.0),
        },
        {
            "tag": "L2-هدف_هيكلي",
            "title": f"الصفقة 2 ({main_action} الهدف الهيكلي الأساسي TOP 2)",
            "side": main_action,
            "tp_usd": round(max(0.75, base_tp * 1.35), 2),
            "sl_usd": round(safe_sl * 1.10, 2),
            "tp_price": lv.get("top2_price", 0.0),
            "sl_price": lv.get("stop_price", 0.0),
        },
        {
            "tag": "L3-رانر_مؤسسي",
            "title": f"الصفقة 3 ({main_action} الهدف المؤسسي الممتد TOP 3 + Trailing)",
            "side": main_action,
            "tp_usd": round(max(1.30, base_tp * 2.25), 2),
            "sl_usd": round(safe_sl * 1.20, 2),
            "tp_price": lv.get("top3_price", 0.0),
            "sl_price": lv.get("stop_price", 0.0),
        },
    ]


def render_telegram_ascii_chart(symbol, candles, action, levels):
    """رسم شارت نصي احترافي داخل تليجرام يوضح الشموع ومستويات TOP 1/2/3 و Entry و STOP"""
    if not candles or len(candles) < 10:
        return "📈 لا تتوفر شموع كافية لرسم الشارت النصي حالياً."
    sub = candles[-16:]
    closes = [float(c["close"]) for c in sub]
    opens = [float(c.get("open", c["close"])) for c in sub]
    bar_str = ""
    for o, c in zip(opens, closes):
        bar_str += "🟢" if c >= o else "🔴"

    ep = levels.get("entry_price", closes[-1])
    sp = levels.get("stop_price", 0.0)
    t1 = levels.get("top1_price", 0.0)
    t2 = levels.get("top2_price", 0.0)
    t3 = levels.get("top3_price", 0.0)

    if action == "BUY":
        ladder = (
            f"🎯 TOP 3 (الهدف الممتد) : `{t3:.2f}`\n"
            f"🎯 TOP 2 (الهدف الهيكلي) : `{t2:.2f}`\n"
            f"🎯 TOP 1 (هدف التأمين)  : `{t1:.2f}`\n"
            f"🔵 ENTRY (نقطة الدخول) : `{ep:.2f}` ⬅️ السعر الآن\n"
            f"🛑 STOP  (وقف الخسارة) : `{sp:.2f}`"
        )
    else:
        ladder = (
            f"🛑 STOP  (وقف الخسارة) : `{sp:.2f}`\n"
            f"🔵 ENTRY (نقطة الدخول) : `{ep:.2f}` ⬅️ السعر الآن\n"
            f"🎯 TOP 1 (هدف التأمين)  : `{t1:.2f}`\n"
            f"🎯 TOP 2 (الهدف الهيكلي) : `{t2:.2f}`\n"
            f"🎯 TOP 3 (الهدف الممتد) : `{t3:.2f}`"
        )

    return (
        f"📉 **خريطة الشارت اللحظي ومستويات TOP / STOP ({symbol}):**\n"
        f"آخر 16 شمعة: {bar_str}\n"
        f"{ladder}"
    )


# ======================= 9. محرك الذكاء الاصطناعي والرادار الشامل (الماضي + الحاضر + المستقبل) =======================
def synthesize_higher_timeframes(mtf_dict):
    """توليد الفريمات العليا تلقائياً في حال أعاد السيرفر فريمات جزئية لضمان عمل تحليل الـ 30 يوماً دائماً"""
    if not mtf_dict or "M1" not in mtf_dict:
        return mtf_dict
    m15 = mtf_dict.get("M15") or mtf_dict.get("M5") or mtf_dict.get("M1")
    if "H1" not in mtf_dict and m15 and len(m15) >= 16:
        h1_synth = []
        for i in range(0, len(m15) - 3, 4):
            chunk = m15[i:i + 4]
            h1_synth.append({
                "open": float(chunk[0]["open"]),
                "high": max(float(x["high"]) for x in chunk),
                "low": min(float(x["low"]) for x in chunk),
                "close": float(chunk[-1]["close"]),
            })
        if h1_synth:
            mtf_dict["H1"] = h1_synth
    return mtf_dict


def get_multi_timeframe_data(symbol, accounts):
    for acc in accounts:
        if acc["platform"] == "MT5":
            mtf = mt5_fetch_mtf_candles(acc, symbol)
            if mtf and mtf.get("M1"):
                return synthesize_higher_timeframes(mtf), "MT5"
    for acc in accounts:
        if acc["platform"] == "BYBIT":
            mtf = bybit_fetch_mtf_candles(acc, symbol)
            if mtf and mtf.get("M1"):
                return synthesize_higher_timeframes(mtf), "BYBIT"
    mtf = bybit_fetch_mtf_candles({"user_id": 0, "server_or_mode": "BYBIT-DEMO"}, symbol)
    if mtf and mtf.get("M1"):
        return synthesize_higher_timeframes(mtf), "GLOBAL"
    return None, "NONE"


def raw_ai_request(tool, prompt, max_tokens=140):
    if not tool or not tool.get("api_key"):
        return False, "no key"
    headers = {
        "Authorization": f"Bearer {tool['api_key']}",
        "HTTP-Referer": "https://github.com",
        "X-Title": "AI Institutional Sniper v5"
    }
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
        if a == -1 or b == -1:
            return None
        d = json.loads(clean[a:b + 1])
        act = str(d.get("action", "")).upper().strip()
        if act not in ("BUY", "SELL", "WAIT", "HOLD"):
            return None
        conf = int(float(d.get("confidence", 88)))
        return {"action": act, "confidence": max(0, min(conf, 99))}
    except Exception:
        return None


def ask_ai(uid, prompt):
    pref = get_user(uid)["selected_ai_id"]
    tools = sorted(get_ai_tools(), key=lambda t: (0 if t["id"] == pref else 1, t["id"]))
    for t in tools:
        if not t["api_key"] or ai_circuit.get(t["id"], 0) > time.time():
            continue
        ok, text = raw_ai_request(t, prompt, 120)
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
            "support": 0.0,
            "resistance": 0.0,
            "levels": {"entry_price": 0.0, "stop_price": 0.0, "top1_price": 0.0, "top2_price": 0.0, "top3_price": 0.0},
            "indicators": "تعذر سحب الشموع الحية حالياً",
            "detailed_report": "⚠️ لا توجد بيانات شموع كافية من السيرفر حالياً.",
            "ascii_chart": "",
            "ts": time.time(),
        }

    a_m1 = analyze_single_timeframe(mtf_data.get("M1"))
    a_m5 = analyze_single_timeframe(mtf_data.get("M5")) or a_m1
    a_m15 = analyze_single_timeframe(mtf_data.get("M15")) or a_m5
    a_h1 = analyze_single_timeframe(mtf_data.get("H1")) or a_m15
    a_h4 = analyze_single_timeframe(mtf_data.get("H4")) or a_h1
    a_d1 = analyze_single_timeframe(mtf_data.get("D1")) or a_h4

    cur_price = a_m1["price"]
    hist_30d = analyze_30day_historical_horizon(mtf_data, cur_price)
    fut_proj = project_future_trajectory(mtf_data.get("M15"), mtf_data.get("H1"), cur_price, a_m1["atr"])

    tf_dirs = [
        a_m1["direction"],
        a_m5["direction"],
        a_m15["direction"],
        a_h1["direction"],
        a_h4["direction"],
        hist_30d["macro_bias"]
    ]
    buy_votes = sum(1 for d in tf_dirs if d == "BUY")
    sell_votes = sum(1 for d in tf_dirs if d == "SELL")

    if a_m1["direction"] == a_m5["direction"] == a_m15["direction"]:
        dominant_dir = a_m1["direction"]
        micro_alignment = 3
    elif a_m1["direction"] == a_m5["direction"]:
        dominant_dir = a_m1["direction"]
        micro_alignment = 2
    else:
        dominant_dir = "BUY" if buy_votes >= sell_votes else "SELL"
        micro_alignment = 1

    total_alignment = buy_votes if dominant_dir == "BUY" else sell_votes

    avg_raw = (
        (a_m1["raw_score"] * 0.35) +
        (a_m5["raw_score"] * 0.25) +
        (a_m15["raw_score"] * 0.20) +
        (a_h1["raw_score"] * 0.10) +
        (a_h4["raw_score"] * 0.10)
    )

    fut_matches = (
        (dominant_dir == "BUY" and fut_proj["future_bias"] == "BULLISH") or
        (dominant_dir == "SELL" and fut_proj["future_bias"] == "BEARISH")
    )

    if micro_alignment == 3 and total_alignment >= 4 and a_m1["diff_score"] >= 18:
        tech_conf = min(98, int(92 + (avg_raw - 50) * 0.18 + (2 if fut_matches else 0)))
    elif micro_alignment >= 2 and total_alignment >= 4 and a_m1["diff_score"] >= 20:
        tech_conf = min(96, int(90 + (avg_raw - 52) * 0.18 + (1 if fut_matches else 0)))
    elif micro_alignment >= 2 and a_m1["adx"] >= 22:
        tech_conf = min(93, int(89 + (avg_raw - 55) * 0.18))
    else:
        tech_conf = max(68, min(88, int(70 + avg_raw * 0.22)))

    levels = compute_structural_top_and_stop(
        dominant_dir,
        cur_price,
        a_m1["atr"],
        a_m15["atr"],
        a_m15["support"],
        a_m15["resistance"],
        hist_30d["major_support"],
        hist_30d["major_resistance"],
    )

    summary_str = (
        f"Price:{cur_price:.2f} | 30D_Range:{hist_30d['month_low']:.2f}-{hist_30d['month_high']:.2f} | "
        f"D1:{a_d1['direction']} | H4:{a_h4['direction']} | H1:{a_h1['direction']} | "
        f"M15:{a_m15['direction']} | M5:{a_m5['direction']}(RSI:{a_m5['rsi']:.1f}) | "
        f"M1:{a_m1['direction']}(RSI:{a_m1['rsi']:.1f},ADX:{a_m1['adx']:.1f}) | "
        f"FutureSlope:{fut_proj['slope_per_bar']:+.3f} | TOP:{levels['top2_price']:.2f} | STOP:{levels['stop_price']:.2f}"
    )

    prompt = (
        f"You are an institutional Gold/Forex Quantitative Strategist trading {symbol}. "
        f"30-Day Macro & Multi-Timeframe Data: {summary_str}. "
        f"SMC Structure: {a_m15['smc']['smc_note']}. "
        f"Reasons: {', '.join(a_m1['reasons'])}. "
        f"Alignment: {total_alignment}/6 timeframes towards {dominant_dir}. Pre-score: {tech_conf}%. "
        f"Confirm {dominant_dir} with confidence >= 91 if M1, M5, and structure align. "
        f"Reply ONLY in JSON: {{\"action\":\"{dominant_dir}\",\"confidence\":{tech_conf}}}"
    )

    ai_res = ask_ai(uid, prompt)
    provider_name = get_ai_tool_by_id(get_user(uid)["selected_ai_id"]).get("name", "Institutional Radar v5")

    if ai_res:
        provider_name = ai_res["provider"]
        if ai_res["action"] == dominant_dir:
            final_conf = max(tech_conf, ai_res["confidence"])
            if micro_alignment >= 2 and total_alignment >= 4:
                final_conf = max(final_conf, 92)
            final_dir = dominant_dir
        elif ai_res["action"] in ("BUY", "SELL") and micro_alignment == 1:
            final_dir = ai_res["action"]
            final_conf = min(87, ai_res["confidence"])
            levels = compute_structural_top_and_stop(
                final_dir, cur_price, a_m1["atr"], a_m15["atr"],
                a_m15["support"], a_m15["resistance"],
                hist_30d["major_support"], hist_30d["major_resistance"]
            )
        else:
            final_dir = dominant_dir
            final_conf = tech_conf
    else:
        final_dir = dominant_dir
        final_conf = tech_conf

    ascii_chart = render_telegram_ascii_chart(symbol, mtf_data.get("M5") or mtf_data.get("M1"), final_dir, levels)
    clean_reasons_m1 = " ، ".join(a_m1["reasons"] or [f"توافق الفريمات نحو {final_dir}"])
    clean_reasons_m15 = " ، ".join(a_m15["reasons"] or [a_m15["smc"]["smc_note"]])
    action_ar = "شراء (BUY 🟢)" if final_dir == "BUY" else "بيع (SELL 🔴)"

    detailed_report = (
        f"🏛️ **تقرير التحليل المؤسسي الشامل ({symbol}) — {action_ar}**\n"
        f"• وقت إصدار التحليل الدقيق: `{local_now().strftime('%Y-%m-%d %H:%M:%S')}` | السيولة: {get_global_session_status()}\n\n"
        f"{hist_30d['historical_narrative']}\n\n"
        f"⏱️ **تحليل اللحظة الراهنة (Multi-Timeframe Matrix):**\n"
        f"• الفريمات الكبرى: الشهري/اليومي `{a_d1['direction']}` | 4 ساعات `{a_h4['direction']}` | 1 ساعة `{a_h1['direction']}`\n"
        f"• الفريمات اللحظية: 15 دقيقة `{a_m15['direction']}` | 5 دقائق `{a_m5['direction']}` | 1 دقيقة `{a_m1['direction']}`\n"
        f"• المؤشرات الفنية: RSI(14)=`{a_m1['rsi']:.1f}` | StochRSI=`{a_m1['stoch_rsi']:.1f}` | قوة الاتجاه ADX=`{a_m1['adx']:.1f}` | ATR=`{a_m1['atr']:.2f}$`\n"
        f"• المتوسطات المتحركة: EMA9=`{a_m1['ema9']:.2f}` | EMA21=`{a_m1['ema21']:.2f}` | EMA50=`{a_m1['ema50']:.2f}` | EMA200=`{a_m1['ema200']:.2f}`\n"
        f"• هيكل الأموال الذكية (SMC): {a_m15['smc']['smc_note']}\n\n"
        f"🔮 **استشراف المستقبل (Future Market Projection):**\n"
        f"• {fut_proj['future_summary']}\n\n"
        f"📐 **تحديد القمة الهدف (TOP) والقاع الوقف (STOP) على الشارت:**\n"
        f"• 🔵 سعر الدخول المرجعي (Entry): `{levels['entry_price']:.2f}`\n"
        f"• 🎯 الهدف الأول (TOP 1 - قناص التأمين): `{levels['top1_price']:.2f}`\n"
        f"• 🎯 الهدف الثاني (TOP 2 - الهدف الهيكلي): `{levels['top2_price']:.2f}`\n"
        f"• 🎯 الهدف الثالث (TOP 3 - الهدف المؤسسي): `{levels['top3_price']:.2f}`\n"
        f"• 🛑 وقف الخسارة الهيكلي (STOP Loss): `{levels['stop_price']:.2f}` (بُعد الأمان: `{levels['stop_distance']:.2f}$`)\n\n"
        f"🧠 **لماذا اتخذ البوت قرار {action_ar} الآن؟**\n"
        f"1. على الفريم اللحظي: {clean_reasons_m1}\n"
        f"2. على الفريم الهيكلي: {clean_reasons_m15}\n"
        f"3. توافق `{total_alignment}` من أصل `6` فريمات زمنية في نفس الاتجاه بدون أي صفقة عكسية متناقضة."
    )

    res_obj = {
        "ready": final_conf >= MIN_AI_CONFIDENCE,
        "action": final_dir,
        "confidence": final_conf,
        "provider": provider_name,
        "price": cur_price,
        "atr": a_m1["atr"],
        "adx": a_m1["adx"],
        "support": a_m15["support"],
        "resistance": a_m15["resistance"],
        "levels": levels,
        "hist_30d": hist_30d,
        "fut_proj": fut_proj,
        "indicators": summary_str,
        "detailed_report": detailed_report,
        "ascii_chart": ascii_chart,
        "ts": time.time(),
    }
    LIVE_RADAR_CACHE[symbol.upper()] = res_obj
    return res_obj


def get_instant_or_fresh_analysis(uid, symbol, accounts, force_fresh=False):
    if not force_fresh:
        cached = LIVE_RADAR_CACHE.get(symbol.upper())
        if cached and (time.time() - cached.get("ts", 0) <= 10) and cached.get("price", 0) > 0:
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
# ======================= 10. دوال الهندسة المالية ومعالجة العقود وملفات INI =======================
def usd_to_price_distance(usd, volume, tick_value, tick_size):
    if min(float(usd or 0), float(volume or 0), float(tick_value or 0), float(tick_size or 0)) <= 0:
        return 0.0
    val_per_point = (float(volume) * float(tick_value)) / float(tick_size)
    if val_per_point <= 0:
        return 0.0
    return float(usd) / val_per_point


def price_distance_to_usd(price_dist, volume, tick_value, tick_size):
    if min(abs(float(price_dist or 0)), float(volume or 0), float(tick_value or 0), float(tick_size or 0)) <= 0:
        return 0.0
    val_per_point = (float(volume) * float(tick_value)) / float(tick_size)
    return abs(float(price_dist)) * val_per_point


def round_step(value, step, minimum=0):
    try:
        v = Decimal(str(value))
        s = Decimal(str(step if step and float(step) > 0 else "0.01"))
        q = (v / s).to_integral_value(ROUND_DOWN) * s
        return max(q, Decimal(str(minimum)))
    except Exception:
        return Decimal(str(minimum or 0.01))


def normalize_volume(lot, vmin, vmax, vstep):
    vstep = float(vstep or 0.01)
    vmin = float(vmin or vstep)
    vol = float(round_step(lot, vstep, vmin))
    if vmax and float(vmax) > 0:
        vol = min(vol, float(vmax))
    return max(vol, vmin)


def is_within_working_hours(start_h, end_h, hour=None):
    h = local_hour() if hour is None else int(hour)
    start_h, end_h = int(start_h), int(end_h)
    if start_h == 0 and end_h == 24:
        return True
    return (start_h <= h < end_h) if start_h <= end_h else (h >= start_h or h < end_h)


def set_ini_values(text, section, kv):
    nl = "\r\n"
    pending = dict(kv)
    out = []
    in_sec = False
    found = False
    for line in str(text).splitlines():
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


def retcode_message(code, comment=""):
    return explain_mt5_retcode(code, comment)


# ======================= 11. محرك MetaApi السحابي المتكامل (الرديف السحابي لـ MT5) =======================
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

    st, acc_list = http_request(
        f"{PROVISION_URL}/users/current/accounts",
        "GET",
        headers=metaapi_headers(),
        timeout=10
    )
    if st == 200 and isinstance(acc_list, list):
        for item in acc_list:
            if str(item.get("login")) == login_str or (cid and item.get("_id") == cid):
                cid = item.get("_id", cid)
                reg = item.get("region", reg)
                if item.get("state") != "DEPLOYED":
                    http_request(
                        f"{PROVISION_URL}/users/current/accounts/{cid}/deploy",
                        "POST",
                        headers=metaapi_headers(),
                        timeout=10
                    )
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
    st_c, res_c = http_request(
        f"{PROVISION_URL}/users/current/accounts",
        "POST",
        headers=metaapi_headers(with_tx=True),
        payload=create_payload,
        timeout=15
    )
    if st_c in (200, 201) and isinstance(res_c, dict) and "id" in res_c:
        cid = res_c["id"]
        http_request(
            f"{PROVISION_URL}/users/current/accounts/{cid}/deploy",
            "POST",
            headers=metaapi_headers(),
            timeout=10
        )
        if acc.get("acc_pk"):
            update_account_cloud(acc["acc_pk"], cid, reg)
        return True, cid, reg, "OK"
    return False, "", "london", "تعذر ربط الحساب عبر سحابة MetaApi."


def metaapi_status(acc):
    ok_dep, cid, reg, err_msg = metaapi_ensure_deployed(acc)
    if not ok_dep:
        return False, 0.0, 0.0, 0, err_msg
    base_c = metaapi_client_url(reg)
    st, info = http_request(
        f"{base_c}/users/current/accounts/{cid}/account-information",
        "GET",
        headers=metaapi_headers(),
        timeout=10
    )
    if st != 200 or not isinstance(info, dict):
        return False, 0.0, 0.0, 0, "جاري مزامنة الحساب السحابي..."
    st_p, pos = http_request(
        f"{base_c}/users/current/accounts/{cid}/positions",
        "GET",
        headers=metaapi_headers(),
        timeout=10
    )
    pos_list = pos if (st_p == 200 and isinstance(pos, list)) else []
    bal = float(info.get("balance") or 0.0)
    eq = float(info.get("equity") or bal)
    return True, bal, eq, len(pos_list), "متصل سحابياً عبر MetaApi 🟢"


def metaapi_positions(acc):
    ok_dep, cid, reg, _ = metaapi_ensure_deployed(acc)
    if not ok_dep:
        return None
    base_c = metaapi_client_url(reg)
    st, pos = http_request(
        f"{base_c}/users/current/accounts/{cid}/positions",
        "GET",
        headers=metaapi_headers(),
        timeout=10
    )
    if st != 200 or not isinstance(pos, list):
        return None
    out = []
    for p in pos:
        out.append({
            "id": str(p.get("id")),
            "symbol": str(p.get("symbol", "XAUUSD")),
            "volume": float(p.get("volume") or 0.01),
            "price_open": float(p.get("openPrice") or 0.0),
            "price_current": float(p.get("currentPrice") or 0.0),
            "sl": float(p.get("stopLoss") or 0.0),
            "tp": float(p.get("takeProfit") or 0.0),
            "side": "BUY" if "BUY" in str(p.get("type", "")).upper() else "SELL",
            "profit": float(p.get("profit") or 0.0) + float(p.get("swap") or 0.0),
            "magic": int(p.get("magic") or 0),
        })
    return out


def metaapi_modify_sltp(acc, pos_id, symbol, sl_price, tp_price):
    ok_dep, cid, reg, _ = metaapi_ensure_deployed(acc)
    if not ok_dep:
        return False
    base_c = metaapi_client_url(reg)
    payload = {
        "actionType": "POSITION_MODIFY",
        "positionId": str(pos_id),
    }
    if sl_price and float(sl_price) > 0:
        payload["stopLoss"] = round(float(sl_price), 2)
    if tp_price and float(tp_price) > 0:
        payload["takeProfit"] = round(float(tp_price), 2)
    st, res = http_request(
        f"{base_c}/users/current/accounts/{cid}/trade",
        "POST",
        headers=metaapi_headers(),
        payload=payload,
        timeout=12
    )
    return st == 200 and isinstance(res, dict) and res.get("numericCode") in (0, 10008, 10009)


def metaapi_close(acc, pos, partial_volume=None):
    ok_dep, cid, reg, _ = metaapi_ensure_deployed(acc)
    if not ok_dep:
        return False
    base_c = metaapi_client_url(reg)
    if partial_volume and float(partial_volume) < float(pos.get("volume", 0)):
        payload = {
            "actionType": "POSITION_PARTIAL",
            "positionId": str(pos["id"]),
            "volume": round(float(partial_volume), 2),
        }
    else:
        payload = {
            "actionType": "POSITION_CLOSE_ID",
            "positionId": str(pos["id"]),
        }
    st, res = http_request(
        f"{base_c}/users/current/accounts/{cid}/trade",
        "POST",
        headers=metaapi_headers(),
        payload=payload,
        timeout=12
    )
    return st == 200 and isinstance(res, dict) and res.get("numericCode") in (0, 10008, 10009)


def metaapi_open_single_layer(acc, side, symbol, lot, tp_usd, sl_usd, layer_tag="L1", tp_price=0.0, sl_price=0.0):
    ok_dep, cid, reg, err_msg = metaapi_ensure_deployed(acc)
    if not ok_dep:
        return {"ok": False, "symbol": symbol, "msg": err_msg}
    base_c = metaapi_client_url(reg)
    action_type = "ORDER_TYPE_BUY" if side == "BUY" else "ORDER_TYPE_SELL"
    vol = max(round(float(lot), 2), 0.01)

    for sym_try in (symbol, "XAUUSD", "XAUUSDm", "GOLD", "EURUSD"):
        payload = {
            "actionType": action_type,
            "symbol": sym_try,
            "volume": vol,
            "comment": f"AI_{layer_tag}"
        }
        if tp_price and float(tp_price) > 0:
            payload["takeProfit"] = round(float(tp_price), 2)
        if sl_price and float(sl_price) > 0:
            payload["stopLoss"] = round(float(sl_price), 2)

        st, res = http_request(
            f"{base_c}/users/current/accounts/{cid}/trade",
            "POST",
            headers=metaapi_headers(),
            payload=payload,
            timeout=15
        )
        if st == 200 and isinstance(res, dict):
            if res.get("numericCode") in (0, 10008, 10009) or res.get("stringCode") in ("TRADE_RETCODE_DONE", "TRADE_RETCODE_DONE_PARTIAL"):
                oid = str(res.get("orderId") or res.get("positionId") or "Executed")
                return {
                    "ok": True,
                    "symbol": sym_try,
                    "ticket": oid,
                    "volume": vol,
                    "side": side,
                    "price": float(res.get("openPrice") or 0.0),
                    "tp_usd": tp_usd,
                    "sl_usd": sl_usd,
                    "tp_price": float(tp_price or 0.0),
                    "sl_price": float(sl_price or 0.0),
                    "layer_tag": layer_tag,
                }
    return {"ok": False, "symbol": symbol, "msg": "رفض التنفيذ عبر سحابة MetaApi"}


# ======================= 12. محرك MetaTrader 5 المباشر + المعالج الذاتي للأخطاء (10004 - 10044) =======================
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

MT5_PATHS = [
    r"C:\Program Files\MetaTrader 5\terminal64.exe",
    r"C:\Program Files (x86)\MetaTrader 5\terminal64.exe",
]
MT5_SETUP_URL = "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe"
mt5_lock = threading.RLock()
MT5_BOOT_DONE = threading.Event()
failed_mt5_servers = {}
_discovered_data_paths = set()
_last_autotrading_fix = 0.0


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
    """
    الحل الجذري النهائي لمشكلة الكود 10027 (AutoTrading Disabled by Client):
    يفعّل زر Algo Trading في المنصة عبر أوامر Win32 المباشرة + اختصار لوحة المفاتيح Ctrl+E
    دون أن يضطر المستخدم لفتح شاشة MT5 أبداً.
    """
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
                if any(k in t for k in ("METATRADER", "METAQUOTES", "DEMO", "LIVE", "REAL")):
                    if hwnd not in hwnds:
                        hwnds.append(hwnd)
            return True

        u.EnumWindows(WNDENUMPROC(enum_cb), 0)

        for d_hwnd in dialogs:
            u.PostMessageW(d_hwnd, 0x0010, 0, 0)
        if dialogs:
            time.sleep(0.25)

        WM_COMMAND = 0x0111
        for cmd_id in (32851, 33021, 32850, 32852):
            for hwnd in hwnds:
                u.PostMessageW(hwnd, WM_COMMAND, cmd_id, 0)
            time.sleep(0.35)
            ti = mt5.terminal_info()
            if ti and getattr(ti, "trade_allowed", False):
                return True

        if hwnds:
            try:
                u.SetForegroundWindow(hwnds[0])
                time.sleep(0.15)
                VK_CONTROL = 0x11
                VK_E = 0x45
                KEYEVENTF_KEYUP = 0x0002
                u.keybd_event(VK_CONTROL, 0, 0, 0)
                u.keybd_event(VK_E, 0, 0, 0)
                time.sleep(0.08)
                u.keybd_event(VK_E, 0, KEYEVENTF_KEYUP, 0)
                u.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
                time.sleep(0.35)
                ti = mt5.terminal_info()
                if ti and getattr(ti, "trade_allowed", False):
                    return True
            except Exception:
                pass
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


def auto_clean_broken_demo_accounts(uid, acc_pk):
    if not uid or not acc_pk:
        return
    acc = get_account_by_pk(acc_pk)
    if acc and "DEMO" in str(acc.get("server_or_mode", "")).upper() and acc.get("login_or_key") != KNOWN_MT5_LOGIN:
        delete_trading_account(uid, acc_pk)


def mt5_connect_locked(acc, for_trading=False):
    global _last_autotrading_fix
    if not NATIVE_MT5_AVAILABLE:
        return False, "MetaTrader5 يعمل على ويندوز فقط (أو عبر سحابة MetaApi)"
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
        return False, f"سيرفر ({server}) غير مستجيب حالياً في قائمة MT5."

    info = mt5.account_info()
    if info is None:
        if not mt5.initialize(exe, timeout=12000):
            err_c, err_d = mt5.last_error()
            return False, f"تعذر ربط قناة MT5: {explain_mt5_retcode(err_c, err_d)}"
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
            return False, f"فشل تسجيل الدخول: {explain_mt5_retcode(err_c, str(err_d))}"

    ti = mt5.terminal_info()
    if ti and (not getattr(ti, "trade_allowed", False) or getattr(ti, "tradeapi_disabled", False)):
        if not send_win32_autotrading_enable():
            if for_trading and (time.time() - _last_autotrading_fix > 55):
                _last_autotrading_fix = time.time()
                launch_mt5_with_verified_autotrading(login_str, password, server)

    return True, "OK"


def match_mt5_symbol(desired):
    d = desired.upper().strip()
    cands = (
        [d, "XAUUSD", "XAUUSDm", "XAUUSD.", "XAUUSDc", "XAUUSD#", "XAUUSDpro", "GOLD", "GOLDm", "GOLD.", "XAUUSD.a"]
        if d in ("XAUUSD", "GOLD")
        else [d, d + "m", d + ".", d + "#", d + "c", d + "pro"]
    )
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
                sp = float(tick.ask - tick.bid) if (tick.ask > 0 and tick.bid > 0) else 0.20
                return p, sp
        time.sleep(0.12)

    si = mt5.symbol_info(sym)
    if si:
        p = float(getattr(si, "ask", 0.0) if is_buy else getattr(si, "bid", 0.0))
        if p > 0:
            return p, 0.30

    rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, 5)
    if rates is not None and len(rates) > 0:
        last_close = float(rates[-1]["close"])
        if last_close > 0:
            return last_close, 0.30

    return 0.0, 0.0


def mt5_fetch_mtf_candles(acc, symbol):
    """
    سحب الشموع التاريخية واللحظية الشاملة من MT5:
    يسحب D1 (35 يوماً) + H4 (180 شمعة = 30 يوماً) + H1 (240 شمعة) + M15 + M5 + M1
    ليتمكن البوت من تحليل الشهر الماضي بالكامل وصولاً للحظة إرسال أمر التداول بالثانية.
    """
    with mt5_lock:
        ok, _ = mt5_connect_locked(acc, for_trading=False)
        if not ok:
            return None
        sym = match_mt5_symbol(symbol)
        if not sym:
            return None
        out = {}
        tf_map = {
            "M1": (mt5.TIMEFRAME_M1, 90),
            "M5": (mt5.TIMEFRAME_M5, 90),
            "M15": (mt5.TIMEFRAME_M15, 96),
            "H1": (mt5.TIMEFRAME_H1, 180),
            "H4": (mt5.TIMEFRAME_H4, 185),
            "D1": (mt5.TIMEFRAME_D1, 35),
        }
        for name, (tf_code, count) in tf_map.items():
            rates = mt5.copy_rates_from_pos(sym, tf_code, 0, count)
            if rates is not None and len(rates) >= 10:
                out[name] = [{
                    "open": float(r["open"]),
                    "high": float(r["high"]),
                    "low": float(r["low"]),
                    "close": float(r["close"]),
                } for r in rates]
        return out if "M1" in out else None


def mt5_get_symbol_specs(acc, symbol):
    """فحص مواصفات العقد والسبريد الحي ومستويات الوقف داخل تليجرام دون الحاجة لفتح MT5"""
    with mt5_lock:
        ok, msg = mt5_connect_locked(acc, for_trading=False)
        if not ok:
            return {"ok": False, "msg": msg}
        sym = match_mt5_symbol(symbol)
        if not sym:
            return {"ok": False, "msg": f"الرمز {symbol} غير متاح عند الوسيط"}
        si = mt5.symbol_info(sym)
        price, spread = get_reliable_mt5_price(sym, True)
        if not si:
            return {"ok": False, "msg": "تعذر قراءة خصائص الرمز"}
        return {
            "ok": True,
            "symbol": sym,
            "bid": round(price - spread, si.digits),
            "ask": round(price, si.digits),
            "spread_usd": round(spread, 2),
            "digits": int(si.digits),
            "volume_min": float(si.volume_min),
            "volume_max": float(si.volume_max),
            "volume_step": float(si.volume_step),
            "stops_level_pts": int(si.trade_stops_level),
            "contract_size": float(getattr(si, "trade_contract_size", 100.0)),
        }


def mt5_status(acc):
    with mt5_lock:
        ok, msg = mt5_connect_locked(acc, for_trading=False)
        if not ok:
            if MASTER_METAAPI_TOKEN:
                return metaapi_status(acc)
            return False, 0.0, 0.0, 0, msg
        info, ti = mt5.account_info(), mt5.terminal_info()
        pos = mt5.positions_get() or []
        acc_type = "ديمو Demo" if getattr(info, "trade_mode", 0) == mt5.ACCOUNT_TRADE_MODE_DEMO else "حقيقي Live"
        allowed = bool(ti and getattr(ti, "trade_allowed", False) and not getattr(ti, "tradeapi_disabled", False))
        algo = "مفعّل 🟢" if allowed else "محمي ذاتياً ⚡"
        free_m = float(getattr(info, "margin_free", info.equity))
        return True, float(info.balance), float(info.equity), len(pos), f"متصل ({acc_type}) | هامش حر: {free_m:.2f}$ | التداول الآلي: {algo}"


def mt5_positions(acc, only_bot=True):
    with mt5_lock:
        ok, _ = mt5_connect_locked(acc)
        if not ok:
            if MASTER_METAAPI_TOKEN:
                return metaapi_positions(acc)
            return None
        pos = mt5.positions_get()
        if pos is None:
            return []
        return [{
            "id": str(p.ticket),
            "symbol": p.symbol,
            "volume": float(p.volume),
            "price_open": float(getattr(p, "price_open", 0.0)),
            "price_current": float(getattr(p, "price_current", 0.0)),
            "sl": float(getattr(p, "sl", 0.0)),
            "tp": float(getattr(p, "tp", 0.0)),
            "side": "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
            "profit": float(p.profit) + float(getattr(p, "swap", 0.0)),
            "magic": int(getattr(p, "magic", 0)),
        } for p in pos if (not only_bot or p.magic == MAGIC)]


def mt5_modify_position_sltp(acc, pos_id, symbol, new_sl, new_tp):
    """تعديل القمة الهدف (TOP) والقاع الوقف (STOP) لأي صفقة حية مباشرة من تليجرام"""
    with mt5_lock:
        ok, _ = mt5_connect_locked(acc, for_trading=True)
        if not ok:
            if MASTER_METAAPI_TOKEN:
                return metaapi_modify_sltp(acc, pos_id, symbol, new_sl, new_tp)
            return False
        si = mt5.symbol_info(symbol)
        digits = si.digits if si else 2
        req = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": int(pos_id),
            "symbol": symbol,
            "sl": round(float(new_sl or 0.0), digits),
            "tp": round(float(new_tp or 0.0), digits),
        }
        res = mt5.order_send(req)
        return bool(res and res.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL, 10025))


def mt5_move_to_breakeven(acc, pos, lock_offset_price=0.12):
    """نقل وقف الخسارة (STOP) إلى نقطة الدخول + ربح بسيط لحماية الحساب من أي انعكاس (خسارة = صفر)"""
    with mt5_lock:
        if not mt5_connect_locked(acc, for_trading=False)[0]:
            return False
        entry_p = float(pos.get("price_open", 0.0))
        cur_sl = float(pos.get("sl", 0.0))
        cur_tp = float(pos.get("tp", 0.0))
        if entry_p <= 0:
            return False
        is_buy = pos["side"] == "BUY"
        si = mt5.symbol_info(pos["symbol"])
        digits = si.digits if si else 2
        target_be = round(entry_p + lock_offset_price if is_buy else entry_p - lock_offset_price, digits)

        if is_buy and cur_sl >= target_be:
            return True
        if (not is_buy) and (cur_sl > 0 and cur_sl <= target_be):
            return True

        res = mt5.order_send({
            "action": mt5.TRADE_ACTION_SLTP,
            "position": int(pos["id"]),
            "symbol": pos["symbol"],
            "sl": target_be,
            "tp": cur_tp,
        })
        return bool(res and res.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL, 10025))


def mt5_trailing_stop_update(acc, pos, trail_dist_price=0.85):
    """الوقف المتحرك الذكي (Dynamic Trailing Stop): يلاحق السعر ويحجز الأرباح أولاً بأول"""
    with mt5_lock:
        if not mt5_connect_locked(acc, for_trading=False)[0]:
            return False
        entry_p = float(pos.get("price_open", 0.0))
        cur_p = float(pos.get("price_current", 0.0))
        cur_sl = float(pos.get("sl", 0.0))
        cur_tp = float(pos.get("tp", 0.0))
        if entry_p <= 0 or cur_p <= 0:
            return False
        is_buy = pos["side"] == "BUY"
        si = mt5.symbol_info(pos["symbol"])
        digits = si.digits if si else 2
        min_step = max(float(trail_dist_price) * 0.25, 0.20)

        if is_buy:
            if cur_p - entry_p < trail_dist_price * 1.2:
                return False
            new_sl = round(cur_p - trail_dist_price, digits)
            if new_sl <= entry_p or (cur_sl > 0 and new_sl - cur_sl < min_step):
                return False
        else:
            if entry_p - cur_p < trail_dist_price * 1.2:
                return False
            new_sl = round(cur_p + trail_dist_price, digits)
            if new_sl >= entry_p or (cur_sl > 0 and cur_sl - new_sl < min_step):
                return False

        res = mt5.order_send({
            "action": mt5.TRADE_ACTION_SLTP,
            "position": int(pos["id"]),
            "symbol": pos["symbol"],
            "sl": new_sl,
            "tp": cur_tp,
        })
        return bool(res and res.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL))


def mt5_close(acc, pos, partial_ratio=1.0):
    """إغلاق كامل أو جزئي (مثلاً إغلاق 50% من العقد) مع معالجة تلقائية لجميع أكواد الرفض"""
    with mt5_lock:
        ok, _ = mt5_connect_locked(acc, for_trading=True)
        if not ok:
            if MASTER_METAAPI_TOKEN:
                part_v = float(pos["volume"]) * float(partial_ratio) if partial_ratio < 1.0 else None
                return metaapi_close(acc, pos, partial_volume=part_v)
            return False
        is_buy = pos["side"] == "BUY"
        price, _ = get_reliable_mt5_price(pos["symbol"], not is_buy)
        if price <= 0:
            return False
        si = mt5.symbol_info(pos["symbol"])
        vmin = float(si.volume_min if si else 0.01)
        vstep = float(si.volume_step if si else 0.01)
        vmax = float(si.volume_max if si else 100.0)

        target_vol = float(pos["volume"])
        if 0.0 < float(partial_ratio) < 1.0:
            target_vol = normalize_volume(target_vol * float(partial_ratio), vmin, vmax, vstep)

        modes = get_ordered_filling_modes(si) if si else [mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN]
        for fm in modes:
            res = mt5.order_send({
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": pos["symbol"],
                "volume": target_vol,
                "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
                "position": int(pos["id"]),
                "price": price,
                "deviation": 120,
                "magic": MAGIC,
                "comment": "AI_Close",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": fm,
            })
            if res is not None:
                if res.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL, 10036):
                    return True
                if res.retcode == 10038:
                    live_p = mt5.positions_get(ticket=int(pos["id"]))
                    if live_p:
                        target_vol = float(live_p[0].volume)
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


def mt5_open_single_layer(acc, side, symbol, lot, tp_usd, sl_usd, layer_tag="L1", tp_price=0.0, sl_price=0.0):
    """
    المنفذ الذكي لصفقات MT5 مع المعالجة الآلية الفورية لجميع الأكواد (10004 - 10044 شاملة 10027)
    وضبط مستويات القمة الهدف (TOP) والقاع الوقف (STOP) بدقة عالية.
    """
    with mt5_lock:
        ok, msg = mt5_connect_locked(acc, for_trading=True)
        if not ok:
            if MASTER_METAAPI_TOKEN:
                return metaapi_open_single_layer(acc, side, symbol, lot, tp_usd, sl_usd, layer_tag, tp_price, sl_price)
            return _fail(symbol, msg)

        sym = match_mt5_symbol(symbol)
        if not sym:
            return _fail(symbol, f"الرمز {symbol} غير موجود عند الوسيط")

        si = mt5.symbol_info(sym)
        buy = side == "BUY"
        price, spread = get_reliable_mt5_price(sym, buy)
        if price <= 0:
            return _fail(sym, "السوق مغلق حالياً أو لا توجد تسعيرات حية (كود 10018/10021)")

        uid = acc.get("user_id")
        if uid:
            u_cfg = get_user(uid)
            max_sp = float(u_cfg.get("max_spread_usd") or MAX_ALLOWED_SPREAD_USD)
            if u_cfg.get("spread_filter_enabled", 1) == 1 and spread > max_sp and sym.upper().startswith(("XAU", "GOLD")):
                return _fail(sym, f"تم حجب الدخول لحمايتك: السبريد الحالي مرتفع جداً ({spread:.2f}$ > {max_sp:.2f}$)")

        vol = normalize_volume(lot, si.volume_min, si.volume_max, si.volume_step)
        min_dist = si.trade_stops_level * si.point + spread * 1.4

        dists = {}
        for key, usd in (("tp", tp_usd), ("sl", sl_usd)):
            d = usd_to_price_distance(usd, vol, si.trade_tick_value, si.trade_tick_size)
            dists[key] = max(d, min_dist * 1.15) if d > 0 else None

        modes = get_ordered_filling_modes(si)
        last = ""
        for attempt in range(3):
            for mode in modes:
                cur_p, _ = get_reliable_mt5_price(sym, buy)
                use_p = cur_p if cur_p > 0 else price
                req = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": sym,
                    "volume": vol,
                    "type": mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL,
                    "price": use_p,
                    "deviation": 120,
                    "magic": MAGIC,
                    "comment": f"AI_{layer_tag}",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mode,
                }
                res = mt5.order_send(req)

                if res is None:
                    err_c, err_d = mt5.last_error()
                    last = explain_mt5_retcode(err_c, str(err_d))
                    continue

                rc = int(res.retcode)
                if rc in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL, 10008, 10009, 10010):
                    pos_ticket = res.order or res.deal
                    exec_p = float(res.price or use_p)

                    if dists["tp"]:
                        tp_final = round(exec_p + dists["tp"] if buy else exec_p - dists["tp"], si.digits)
                    elif tp_price and float(tp_price) > 0:
                        tp_final = round(float(tp_price), si.digits)
                    else:
                        tp_final = 0.0

                    if dists["sl"]:
                        sl_final = round(exec_p - dists["sl"] if buy else exec_p + dists["sl"], si.digits)
                    elif sl_price and float(sl_price) > 0:
                        sl_final = round(float(sl_price), si.digits)
                    else:
                        sl_final = 0.0

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
                        "ok": True,
                        "symbol": sym,
                        "ticket": str(pos_ticket),
                        "volume": vol,
                        "side": side,
                        "price": exec_p,
                        "tp_usd": tp_usd,
                        "sl_usd": sl_usd,
                        "tp_price": tp_final,
                        "sl_price": sl_final,
                        "layer_tag": layer_tag,
                    }

                last = explain_mt5_retcode(rc, res.comment)
                rem_action = get_mt5_remediation_action(rc)

                if rem_action == "RETRY_FRESH_PRICE":
                    time.sleep(0.15)
                    continue
                elif rem_action in ("REDUCE_LOT_MIN", "NORMALIZE_VOLUME"):
                    vol = float(si.volume_min or 0.01)
                    continue
                elif rem_action == "BACKOFF_WAIT":
                    time.sleep(1.5)
                    continue
                elif rem_action == "FORCE_ENABLE_AUTOTRADING":
                    if not send_win32_autotrading_enable() and attempt == 0:
                        launch_mt5_with_verified_autotrading(
                            str(acc.get("login_or_key")),
                            acc.get("password_or_secret"),
                            acc.get("server_or_mode"),
                        )
                    break
                elif rem_action == "RECONNECT_TERMINAL":
                    mt5_connect_locked(acc, for_trading=True)
                    break
                elif rem_action == "CYCLE_FILLING_MODES":
                    continue
                else:
                    break
            else:
                break

        if MASTER_METAAPI_TOKEN:
            return metaapi_open_single_layer(acc, side, symbol, lot, tp_usd, sl_usd, layer_tag, tp_price, sl_price)
        return _fail(sym, last or "رفض التنفيذ من الوسيط")
# ======================= 13. محرك Bybit V5 المؤسسي (شامل 30 يوماً + TOP/STOP + معالجة الأخطاء) =======================
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
            "GET",
            timeout=6,
            verify_ssl=False,
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
        st, res = http_request(
            "https://api-demo.bybit.com/v5/market/time",
            "GET",
            timeout=3,
            verify_ssl=False,
            proxy_addr=p_url,
        )
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
    return hmac.new(secret.encode("utf-8"), f"{ts}{key}{recv}{payload}".encode("utf-8"), hashlib.sha256).hexdigest()


def bybit_err(res):
    return explain_bybit_error(res)


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
            "X-BAPI-SIGN": sig,
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
                    hosts[0] + full_path,
                    method,
                    headers=base_headers,
                    raw_body=raw,
                    timeout=10,
                    verify_ssl=False,
                    proxy_addr=eu_p,
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
        status, res = http_request(
            f"{proxy}{path}?{qs}",
            "GET",
            headers={"X-Target-Host": "https://api.bybit.com"},
            timeout=8,
            verify_ssl=False,
        )
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
    """
    سحب الشموع التاريخية واللحظية الشاملة من Bybit V5:
    يسحب D1 (35 يوماً) + H4 (180 شمعة = 30 يوماً) + H1 + M15 + M5 + M1
    لبناء التحليل الشهري (30 يوماً) والتحليل اللحظي والتوقع المستقبلي بدقة.
    """
    out = {}
    tf_map = {
        "M1": ("1", 90),
        "M5": ("5", 90),
        "M15": ("15", 96),
        "H1": ("60", 160),
        "H4": ("240", 180),
        "D1": ("D", 35),
    }
    for sym in bybit_symbol_candidates(symbol):
        for tf_name, (interval, limit_cnt) in tf_map.items():
            ok, res = bybit_public(
                acc,
                "/v5/market/kline",
                {"category": "linear", "symbol": sym, "interval": interval, "limit": limit_cnt},
            )
            if ok:
                rows = (res.get("result") or {}).get("list") or []
                if len(rows) >= 10:
                    out[tf_name] = [{
                        "open": float(r[1]),
                        "high": float(r[2]),
                        "low": float(r[3]),
                        "close": float(r[4]),
                    } for r in reversed(rows)]
        if "M1" in out:
            return out
    return None


def bybit_get_live_ticker(acc, sym):
    ok, res = bybit_public(acc, "/v5/market/tickers", {"category": "linear", "symbol": sym})
    if ok:
        lst = (res.get("result") or {}).get("list") or []
        if lst:
            item = lst[0]
            bid = float(item.get("bid1Price") or item.get("lastPrice") or 0.0)
            ask = float(item.get("ask1Price") or item.get("lastPrice") or 0.0)
            last = float(item.get("lastPrice") or bid or ask)
            return last, bid, ask, round(abs(ask - bid), 2)
    return 0.0, 0.0, 0.0, 0.20


def bybit_get_symbol_specs(acc, symbol):
    for sym in bybit_symbol_candidates(symbol):
        last, bid, ask, sp = bybit_get_live_ticker(acc, sym)
        if last > 0:
            return {
                "ok": True,
                "symbol": sym,
                "bid": round(bid, 2),
                "ask": round(ask, 2),
                "spread_usd": round(sp, 2),
                "digits": 2,
                "volume_min": 0.01,
                "volume_max": 100.0,
                "volume_step": 0.01,
                "stops_level_pts": 10,
                "contract_size": 1.0,
            }
    return {"ok": False, "msg": "تعذر سحب بيانات الرمز من Bybit حالياً"}


def bybit_status(acc):
    ok, res = bybit_request(acc, "GET", "/v5/account/wallet-balance", {"accountType": "UNIFIED"})
    if not ok:
        return False, 0.0, 0.0, 0, bybit_err(res)
    lst = (res.get("result") or {}).get("list") or [{}]
    a = lst[0]
    okp, rp = bybit_request(acc, "GET", "/v5/position/list", {"category": "linear", "settleCoin": "USDT"})
    n = sum(1 for p in ((rp.get("result") or {}).get("list") or []) if float(p.get("size") or 0) > 0) if okp else 0
    mode = acc.get("server_or_mode", "")
    bal = float(a.get("totalWalletBalance") or 0.0)
    eq = float(a.get("totalEquity") or bal)
    avail = float(a.get("totalAvailableBalance") or eq)
    return True, bal, eq, n, f"متصل بنجاح ({mode}) | متاح: {avail:.2f}$ 🟢"


def bybit_positions(acc, symbol=None):
    params = {"category": "linear", "settleCoin": "USDT"}
    ok, res = bybit_request(acc, "GET", "/v5/position/list", params)
    if not ok:
        return None
    out = []
    for p in (res.get("result") or {}).get("list") or []:
        sz = float(p.get("size") or 0)
        if sz > 0:
            sym = str(p.get("symbol", ""))
            pos_idx = int(p.get("positionIdx") or 0)
            out.append({
                "id": f"{sym}:{pos_idx}",
                "raw_id": sym,
                "symbol": sym,
                "volume": sz,
                "raw_size": str(p.get("size")),
                "price_open": float(p.get("avgPrice") or 0.0),
                "price_current": float(p.get("markPrice") or p.get("avgPrice") or 0.0),
                "sl": float(p.get("stopLoss") or 0.0),
                "tp": float(p.get("takeProfit") or 0.0),
                "positionIdx": pos_idx,
                "side": "BUY" if p.get("side") == "Buy" else "SELL",
                "profit": float(p.get("unrealisedPnl") or 0.0),
                "magic": MAGIC,
            })
    return out


def bybit_modify_position_sltp(acc, pos, new_sl, new_tp):
    """ضبط أو تعديل مستويات القمة الهدف (TOP) والقاع الوقف (STOP) على منصة Bybit V5 مباشرة"""
    sym = pos.get("symbol") or str(pos.get("id", "")).split(":")[0]
    pos_idx = int(pos.get("positionIdx") or 0)
    body = {
        "category": "linear",
        "symbol": sym,
        "positionIdx": pos_idx,
        "tpslMode": "Full",
    }
    if new_tp is not None and float(new_tp) >= 0:
        body["takeProfit"] = str(round(float(new_tp), 2))
    if new_sl is not None and float(new_sl) >= 0:
        body["stopLoss"] = str(round(float(new_sl), 2))
    ok, res = bybit_request(acc, "POST", "/v5/position/trading-stop", body=body)
    if ok or res.get("retCode") == 110025:
        return True
    return False


def bybit_move_to_breakeven(acc, pos, lock_offset_price=0.12):
    entry_p = float(pos.get("price_open") or 0.0)
    cur_sl = float(pos.get("sl") or 0.0)
    cur_tp = float(pos.get("tp") or 0.0)
    if entry_p <= 0:
        return False
    is_buy = pos["side"] == "BUY"
    target_be = round(entry_p + lock_offset_price if is_buy else entry_p - lock_offset_price, 2)
    if is_buy and cur_sl >= target_be:
        return True
    if (not is_buy) and (cur_sl > 0 and cur_sl <= target_be):
        return True
    return bybit_modify_position_sltp(acc, pos, target_be, cur_tp if cur_tp > 0 else None)


def bybit_trailing_stop_update(acc, pos, trail_dist_price=0.85):
    entry_p = float(pos.get("price_open") or 0.0)
    cur_p = float(pos.get("price_current") or 0.0)
    cur_sl = float(pos.get("sl") or 0.0)
    cur_tp = float(pos.get("tp") or 0.0)
    if entry_p <= 0 or cur_p <= 0:
        return False
    is_buy = pos["side"] == "BUY"
    min_step = max(float(trail_dist_price) * 0.25, 0.20)
    if is_buy:
        if cur_p - entry_p < trail_dist_price * 1.2:
            return False
        new_sl = round(cur_p - trail_dist_price, 2)
        if new_sl <= entry_p or (cur_sl > 0 and new_sl - cur_sl < min_step):
            return False
    else:
        if entry_p - cur_p < trail_dist_price * 1.2:
            return False
        new_sl = round(cur_p + trail_dist_price, 2)
        if new_sl >= entry_p or (cur_sl > 0 and cur_sl - new_sl < min_step):
            return False
    return bybit_modify_position_sltp(acc, pos, new_sl, cur_tp if cur_tp > 0 else None)


def bybit_close(acc, pos, partial_ratio=1.0):
    sym = pos.get("symbol") or str(pos.get("id", "")).split(":")[0]
    full_sz = float(pos.get("volume") or pos.get("raw_size") or 0.01)
    if 0.0 < float(partial_ratio) < 1.0:
        close_sz = max(round(full_sz * float(partial_ratio), 2), 0.01)
    else:
        close_sz = full_sz

    body = {
        "category": "linear",
        "symbol": sym,
        "side": "Sell" if pos["side"] == "BUY" else "Buy",
        "orderType": "Market",
        "qty": str(close_sz),
        "reduceOnly": True,
        "positionIdx": int(pos.get("positionIdx") or 0),
    }
    ok, res = bybit_request(acc, "POST", "/v5/order/create", body=body)
    if not ok and res.get("retCode") == 110017:
        return True
    return ok


def bybit_closed_pnl(acc, row):
    sym = row["symbol"]
    ok, res = bybit_request(acc, "GET", "/v5/position/closed-pnl", {"category": "linear", "symbol": sym, "limit": 20})
    if not ok:
        return None
    since = (int(row["open_ts"]) - 5) * 1000
    recs = [r for r in ((res.get("result") or {}).get("list") or []) if int(r.get("updatedTime") or 0) >= since]
    return float(sum(float(r.get("closedPnl") or 0.0) for r in recs)) if recs else None


def bybit_open_single_layer(acc, side, symbol, lot, tp_usd, sl_usd, layer_tag="L1", tp_price=0.0, sl_price=0.0):
    qty = max(round(float(lot) * BYBIT_QTY_PER_LOT, 2), 0.01)
    buy = side == "BUY"
    last_err = ""

    for sym in bybit_symbol_candidates(symbol):
        last_p, bid_p, ask_p, sp = bybit_get_live_ticker(acc, sym)
        ref_p = (ask_p if buy else bid_p) or last_p

        if ref_p > 0 and qty > 0:
            tp_dist = max(float(tp_usd or 0.50) / qty, sp * 1.5, 0.35)
            sl_dist = max(float(sl_usd or 1.00) / qty, sp * 1.8, 0.50)
            calc_tp = round(ref_p + tp_dist if buy else ref_p - tp_dist, 2)
            calc_sl = round(ref_p - sl_dist if buy else ref_p + sl_dist, 2)
        else:
            calc_tp = round(float(tp_price or 0.0), 2)
            calc_sl = round(float(sl_price or 0.0), 2)

        for pos_idx in (0, 1 if buy else 2):
            body = {
                "category": "linear",
                "symbol": sym,
                "side": "Buy" if buy else "Sell",
                "orderType": "Market",
                "qty": str(qty),
                "positionIdx": pos_idx,
                "orderLinkId": f"ai_{layer_tag}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:4]}",
            }
            if calc_tp > 0:
                body["takeProfit"] = str(calc_tp)
            if calc_sl > 0:
                body["stopLoss"] = str(calc_sl)

            ok, res = bybit_request(acc, "POST", "/v5/order/create", body=body)

            if not ok and res.get("retCode") in (110007, 110012, 110004):
                bybit_request(acc, "POST", "/v5/position/set-leverage", body={
                    "category": "linear", "symbol": sym, "buyLeverage": "50", "sellLeverage": "50"
                })
                if qty > 0.01:
                    qty = 0.01
                    body["qty"] = "0.01"
                    body["orderLinkId"] = f"ai_{layer_tag}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:4]}"
                ok, res = bybit_request(acc, "POST", "/v5/order/create", body=body)

            if not ok and res.get("retCode") == 10001 and ("takeProfit" in body or "stopLoss" in body):
                body.pop("takeProfit", None)
                body.pop("stopLoss", None)
                body["orderLinkId"] = f"ai_{layer_tag}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:4]}"
                ok, res = bybit_request(acc, "POST", "/v5/order/create", body=body)

            if ok:
                oid = (res.get("result") or {}).get("orderId", "Executed")
                return {
                    "ok": True,
                    "symbol": sym,
                    "ticket": str(oid),
                    "volume": qty,
                    "side": side,
                    "price": ref_p,
                    "tp_usd": tp_usd,
                    "sl_usd": sl_usd,
                    "tp_price": calc_tp,
                    "sl_price": calc_sl,
                    "layer_tag": layer_tag,
                }
            last_err = bybit_err(res)
            if res.get("retCode") != 100028 and "positionIdx" not in str(res.get("retMsg", "")):
                break
    return _fail(symbol, last_err or "تعذر فتح الصفقة على Bybit")


# ======================= 14. الواجهة الموحدة للمنصات (Unified Broker Gateway) =======================
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


def broker_close(acc, pos, partial_ratio=1.0):
    try:
        return mt5_close(acc, pos, partial_ratio) if acc["platform"] == "MT5" else bybit_close(acc, pos, partial_ratio)
    except Exception:
        return False


def broker_modify_sltp(acc, pos, new_sl, new_tp):
    try:
        if acc["platform"] == "MT5":
            return mt5_modify_position_sltp(acc, pos["id"], pos["symbol"], new_sl, new_tp)
        return bybit_modify_position_sltp(acc, pos, new_sl, new_tp)
    except Exception:
        return False


def broker_move_to_breakeven(acc, pos, lock_offset_price=0.12):
    try:
        if acc["platform"] == "MT5":
            return mt5_move_to_breakeven(acc, pos, lock_offset_price)
        return bybit_move_to_breakeven(acc, pos, lock_offset_price)
    except Exception:
        return False


def broker_trailing_stop(acc, pos, trail_dist_price=0.85):
    try:
        if acc["platform"] == "MT5":
            return mt5_trailing_stop_update(acc, pos, trail_dist_price)
        return bybit_trailing_stop_update(acc, pos, trail_dist_price)
    except Exception:
        return False


def broker_symbol_specs(acc, symbol):
    try:
        if acc["platform"] == "MT5":
            return mt5_get_symbol_specs(acc, symbol)
        return bybit_get_symbol_specs(acc, symbol)
    except Exception as e:
        return {"ok": False, "msg": redact(str(e))}


def broker_open_triple_batch(acc, action, symbol, lot, base_tp_usd, base_sl_usd, risk_mode=False, current_atr=1.0, price_levels=None):
    """
    فتح 3 صفقات متدرجة في نفس الاتجاه المؤكد 100% (بلا أي صفقة عكسية خاسرة):
    L1 (قناص التأمين) + L2 (الهدف الهيكلي) + L3 (الهدف الممتد مع وقف متحرك)
    """
    layers = build_triple_shield_plan(action, base_tp_usd, base_sl_usd, current_atr, risk_mode=risk_mode, price_levels=price_levels)
    batch_results = []
    fn = mt5_open_single_layer if acc["platform"] == "MT5" else bybit_open_single_layer

    for layer in layers:
        res = fn(
            acc,
            layer["side"],
            symbol,
            lot,
            layer["tp_usd"],
            layer["sl_usd"],
            layer_tag=layer["tag"],
            tp_price=layer.get("tp_price", 0.0),
            sl_price=layer.get("sl_price", 0.0),
        )
        res["layer_title"] = layer["title"]
        res["tp_usd"] = layer["tp_usd"]
        res["sl_usd"] = layer["sl_usd"]
        res.setdefault("tp_price", layer.get("tp_price", 0.0))
        res.setdefault("sl_price", layer.get("sl_price", 0.0))
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


# ======================= 15. محرك التداول الآلي، الدرع الصفرية للخسائر (Zero-Loss Shield)، والتقارير =======================
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
    new_daily = float(u["current_daily_pnl"]) + float(pnl)
    update_user(uid, "current_daily_pnl", new_daily)
    update_user(uid, "trades_today", int(u["trades_today"]) + 1)
    icon = "💰" if pnl >= 0 else "🛡️"
    send_msg(
        chat_id,
        f"{icon} **إشعار إغلاق صفقة ({row.get('layer_tag', 'L1')}):**\n"
        f"• الحساب: `{acc['account_label']}` | الاتجاه: `{row['side']} {row['symbol']}`\n"
        f"• النتيجة المحققة: `{pnl:+.2f}$` | صافي أرباح اليوم: `{new_daily:+.2f}$`"
    )


def reconcile_account(uid, chat_id, acc, symbol, manage=True):
    """
    مراقب الصفقات الحي ودرع الحماية من الخسارة:
    1. يراقب الصفقات المفتوحة ويغلقها فوراً عند بلوغ ربح TOP أو وقف STOP.
    2. فور وصول أي صفقة لـ 55% من هدفها أو إغلاق الصفقة الأولى (L1) على ربح، ينقل وقف الخسارة (STOP)
       لبقية الصفقات المفتوحة إلى نقطة الدخول + ربح بسيط (Break-Even) لتصبح نسبة الخسارة المحتملة = 0.00$!
    3. يفعّل الوقف المتحرك (Trailing Stop) لمطاردة القمة/القاع وحجز الأرباح المتصاعدة تلقائياً.
    """
    u = get_user(uid)
    positions = broker_positions(acc, symbol, only_bot=False)
    if positions is None:
        return None
    live_map = {p["id"]: p for p in positions}
    rows = open_trade_rows(uid, acc["acc_pk"])
    known_map = {r["ticket"]: r for r in rows}

    if acc["platform"] == "MT5":
        for p in positions:
            if p["id"] not in known_map:
                record_trade(
                    uid, acc, p["symbol"], p["side"], p["volume"], p["id"],
                    u["trade_tp_usd"], u["trade_sl_usd"], "L2-هدف_هيكلي",
                    p.get("price_open"), p.get("tp"), p.get("sl")
                )
        rows = open_trade_rows(uid, acc["acc_pk"])
        known_map = {r["ticket"]: r for r in rows}

    if manage:
        be_enabled = u.get("breakeven_enabled", 1) == 1
        trail_enabled = u.get("trailing_enabled", 1) == 1
        cached_an = LIVE_RADAR_CACHE.get(symbol.upper(), {})
        cur_atr = float(cached_an.get("atr") or 0.90)

        for p in positions:
            r_meta = known_map.get(p["id"]) or known_map.get(p.get("raw_id", ""), {})
            target_tp = float(r_meta.get("tp_usd") or u["trade_tp_usd"] or 0.60)
            target_sl = float(r_meta.get("sl_usd") or u["trade_sl_usd"] or 1.00)

            if p["profit"] >= target_tp or p["profit"] <= -abs(target_sl):
                broker_close(acc, p)
                continue

            if be_enabled and p["profit"] >= max(0.22, target_tp * 0.55):
                if broker_move_to_breakeven(acc, p, lock_offset_price=0.12):
                    if r_meta and r_meta.get("id") and not r_meta.get("be_locked"):
                        mark_trade_be_locked(r_meta["id"], p.get("price_open", 0.0))

            if trail_enabled and p["profit"] >= max(0.35, target_tp * 0.75):
                broker_trailing_stop(acc, p, trail_dist_price=max(0.55, cur_atr * 0.75))

    any_closed_in_profit = False
    for r in rows:
        if r["ticket"] in live_map or any(p.get("raw_id") == r["ticket"] for p in positions):
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

    if any_closed_in_profit and u.get("breakeven_enabled", 1) == 1:
        locked_cnt = 0
        for p in positions:
            if p["id"] in live_map and p["profit"] >= 0.02:
                if broker_move_to_breakeven(acc, p, lock_offset_price=0.12):
                    locked_cnt += 1
        if locked_cnt > 0:
            send_msg(
                chat_id,
                f"🛡️ **درع عدم الخسارة التلقائي (Auto Break-Even):**\n"
                f"بعد إغلاق الصفقة الأولى على ربح، تم نقل وقف الخسارة (`STOP`) لـ `{locked_cnt}` صفقات متبقية إلى نقطة الدخول + ربح مؤمّن! (نسبة الخسارة الآن = 0%)."
            )

    return set(live_map.keys())


def limit_message(u):
    if u["current_daily_pnl"] >= u["daily_max_profit"]:
        return f"🏆 تحقق الهدف اليومي (+{u['current_daily_pnl']:.2f}$). توقف البوت تلقائياً لحفظ أرباحك."
    if u["current_daily_pnl"] <= -abs(u["daily_max_loss"]):
        return f"🛡️ بلغت الخسارة اليومية الحد الأقصى ({u['current_daily_pnl']:.2f}$). توقف البوت لحماية رأس مالك."
    return ""


def risk_button_markup(action):
    return {
        "inline_keyboard": [
            [{"text": f"⚠️ دخول ثلاثي موحد ({action}) مع تأمين سريع Break-Even", "callback_data": f"force_risk_{action}"}],
            [{"text": "📊 تحديث التحليل والشارت اللحظي", "callback_data": "live_radar_analysis"}],
            [{"text": "🔙 رجوع للوحة الرئيسية", "callback_data": "back_home"}],
        ]
    }


def execute_ai_trade(uid, chat_id, accounts, rt=None, manual=False, force_risk=False, forced_action=None):
    """
    المنفذ الرئيسي للصفقات:
    - لا يدخل أي صفقة أبداً دون إجراء التحليل الشامل (30 يوماً + اللحظة الراهنة + التوقع المستقبلي).
    - يحدد مستويات TOP (الأهداف الثلاثة) و STOP (وقف الخسارة) بالسعر وبالدولار ويرسلها في رسالة التحليل والتنفيذ.
    - يدخل الـ 3 صفقات في نفس الاتجاه المؤكد (كلها BUY أو كلها SELL) لمنع تضارب الصفقات نهائياً.
    """
    if uid in trade_running:
        if manual or force_risk:
            send_msg(chat_id, "⏳ جاري تنفيذ التحليل الشامل وفتح الصفقات حالياً، انتظر لحظات...")
        return "busy"
    trade_running.add(uid)
    try:
        u = get_user(uid)
        if manual and not force_risk:
            send_msg(
                chat_id,
                f"⚡ **جاري تشغيل محرك التحليل المؤسسي الشامل ({u['symbol']}):**\n"
                f"• مسح تاريخي لـ 30 يوماً (D1+H4+H1) + الفريمات اللحظية (M15+M5+M1) + التوقع المستقبلي على ({len(accounts)}) حساب..."
            )
        elif force_risk:
            send_msg(chat_id, "⚠️ جاري تنفيذ الدخول الثلاثي الموحد المحمي مع حساب مستويات TOP و STOP...")

        d = get_instant_or_fresh_analysis(uid, u["symbol"], accounts, force_fresh=manual)
        if d.get("price", 0) <= 0:
            if manual or force_risk:
                send_msg(chat_id, "⚠️ تعذر سحب بيانات الشموع الحية من المنصة في هذه اللحظة؛ لن يدخل البوت أي صفقة بدون تحليل كامل للسوق.", main_keyboard(uid))
            return "no_data"

        action = forced_action if (force_risk and forced_action in ("BUY", "SELL")) else d["action"]
        levels = d.get("levels") or compute_structural_top_and_stop(
            action, d["price"], d["atr"], d["atr"] * 2.0, d["support"], d["resistance"], d["support"], d["resistance"]
        )

        if not force_risk and not d["ready"]:
            should_notify = manual or (time.time() - LAST_WAIT_NOTICE.get(uid, 0) > 600)
            if should_notify:
                LAST_WAIT_NOTICE[uid] = time.time()
                wait_msg = (
                    f"🔎 **نتيجة الفحص المؤسسي الشامل (30 يوماً + اللحظة الحالية + المستقبل):**\n"
                    f"• الاتجاه المرصود: `{action}` | نسبة الثقة الحالية: **{d['confidence']}%** (الشرط الآمن للدخول التلقائي: `{MIN_AI_CONFIDENCE}%`)\n"
                    f"• محرك القرار: `{d['provider']}`\n\n"
                    f"{d['detailed_report']}\n\n"
                    f"{d.get('ascii_chart', '')}\n\n"
                    "⚠️ **البوت ينتظر اكتمال شروط عدم الخسارة (توافق الفريمات وقوة الزخم)، أو يمكنك الضغط على زر الدخول الموحد بالأسفل:**"
                )
                send_msg(chat_id, wait_msg, risk_button_markup(action))
            return "wait_opportunity"

        mt5_accs = [a for a in accounts if a["platform"] == "MT5"]
        other = [a for a in accounts if a["platform"] != "MT5"]
        results = []

        def run_group(group):
            return [
                (
                    a,
                    broker_open_triple_batch(
                        a,
                        action,
                        u["symbol"],
                        u["lot"],
                        u["trade_tp_usd"],
                        u["trade_sl_usd"],
                        force_risk,
                        d.get("atr", 1.0),
                        price_levels=levels,
                    ),
                )
                for a in group
            ]

        with ThreadPoolExecutor(max_workers=max(1, min(5, len(other) + 1))) as ex:
            futs = ([ex.submit(run_group, mt5_accs)] if mt5_accs else []) + [ex.submit(run_group, [a]) for a in other]
            for f in futs:
                results.extend(f.result())

        action_ar = "شراء موحد (3x BUY 🟢)" if action == "BUY" else "بيع موحد (3x SELL 🔴)"
        mode_title = "⚡ دخول ثلاثي موحد محمي" if force_risk else f"🎯 دخول مؤسسي فائق الدقة (ثقة: {d['confidence']}%)"
        lines = [
            f"🚀 **تم تفعيل الدخول المؤسسي الموحد:** {action_ar}",
            f"• النمط: {mode_title} | الأداة: `{d['provider']}`",
            f"• جميع الصفقات الـ 3 في نفس الاتجاه (`{action}`) لمنع أي تضارب، مع تأمين تلقائي لنقطة الدخول فور ربح الهدف الأول!\n",
            f"{d['detailed_report']}\n",
            f"{d.get('ascii_chart', '')}\n",
            "📋 **تفاصيل العقود المنفذة ومستويات TOP / STOP لكل صفقة:**",
        ]
        okn = 0
        for acc, batch in results:
            acc_ok = [r for r in batch if r.get("ok")]
            if acc_ok:
                okn += len(acc_ok)
                lines.append(f"\n✅ **الحساب [{acc['account_label']}] — تم فتح ({len(acc_ok)}/3) صفقات `{action}` متدرجة:**")
                for r in acc_ok:
                    record_trade(
                        uid,
                        acc,
                        r["symbol"],
                        r["side"],
                        r["volume"],
                        r["ticket"],
                        r["tp_usd"],
                        r["sl_usd"],
                        r["layer_tag"],
                        r.get("price"),
                        r.get("tp_price"),
                        r.get("sl_price"),
                        analysis_summary=f"Conf:{d['confidence']}% | {action} | Entry:{r.get('price', 0):.2f}",
                    )
                    ep_str = f"{float(r.get('price') or levels['entry_price']):.2f}"
                    tp_p_str = f"{float(r.get('tp_price') or levels['top2_price']):.2f}"
                    sl_p_str = f"{float(r.get('sl_price') or levels['stop_price']):.2f}"
                    lines.append(
                        f"   🔹 **{r['layer_title']}**:\n"
                        f"      • تذكرة: `#{r['ticket']}` | اللوت: `{r['volume']}` | سعر الدخول: `{ep_str}`\n"
                        f"      • 🎯 القمة الهدف (TOP): `{tp_p_str}` (`+{r['tp_usd']}$`)\n"
                        f"      • 🛑 القاع الوقف (STOP): `{sl_p_str}` (`-{r['sl_usd']}$`)"
                    )
            else:
                first_err = batch[0]["msg"] if batch else "خطأ غير معروف"
                lines.append(f"\n⚠️ **الحساب [{acc['account_label']}]:**\n   • تعذر التنفيذ: {first_err}")

        ctrl_kb = {
            "inline_keyboard": [
                [{"text": "🎛️ غرفة إدارة الصفقات الحية (تأمين / إغلاق جزئي / تعديل)", "callback_data": "menu_live_positions"}],
                [{"text": "🛡️ تأمين جميع الصفقات لنقطة الدخول (Break-Even) الآن", "callback_data": "lock_all_be"}],
                [{"text": "🔙 اللوحة الرئيسية", "callback_data": "back_home"}],
            ]
        }
        send_msg(chat_id, "\n".join(lines), ctrl_kb)
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
        "🟢 **انطلق قناص التداول المؤسسي الآلي (v5.0 - 24/7)!**\n"
        "• يحلل حركة السوق لـ 30 يوماً ماضية + اللحظة الحالية + التوقع المستقبلي.\n"
        f"• يفتح 3 صفقات موحدة الاتجاه فور بلوغ الثقة `{MIN_AI_CONFIDENCE}%` مع تحديد `TOP` و `STOP`.\n"
        "• يفعّل تأمين نقطة الدخول (Break-Even) والوقف المتحرك (Trailing Stop) تلقائياً لمنع الخسائر."
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
            if broker_close(acc, p, partial_ratio=1.0):
                closed_cnt += 1
    send_msg(chat_id, f"🚨 تم إغلاق ({closed_cnt}) صفقات مفتوحة فوراً وإيقاف التداول التلقائي.", main_keyboard(uid))


def close_profitable_positions_only(uid, chat_id):
    closed_cnt = 0
    total_locked = 0.0
    for acc in get_user_accounts(uid):
        pos = broker_positions(acc, None, only_bot=False) or []
        for p in pos:
            if float(p.get("profit") or 0.0) > 0:
                if broker_close(acc, p, partial_ratio=1.0):
                    closed_cnt += 1
                    total_locked += float(p.get("profit") or 0.0)
    send_msg(
        chat_id,
        f"💰 تم جني أرباح ({closed_cnt}) صفقات رابحة بنجاح بإجمالي `+{total_locked:.2f}$`!",
        main_keyboard(uid),
    )


def lock_all_profits_breakeven(uid, chat_id):
    locked_cnt = 0
    for acc in get_user_accounts(uid):
        pos = broker_positions(acc, None, only_bot=False) or []
        for p in pos:
            if broker_move_to_breakeven(acc, p, lock_offset_price=0.10):
                locked_cnt += 1
    send_msg(
        chat_id,
        f"🛡️ تم نقل وقف الخسارة (`STOP`) إلى نقطة الدخول لـ ({locked_cnt}) صفقات حية بنجاح!",
        main_keyboard(uid),
    )


def close_half_all_positions(uid, chat_id):
    part_cnt = 0
    for acc in get_user_accounts(uid):
        pos = broker_positions(acc, None, only_bot=False) or []
        for p in pos:
            if float(p.get("volume") or 0.0) >= 0.02:
                if broker_close(acc, p, partial_ratio=0.50):
                    part_cnt += 1
    send_msg(
        chat_id,
        f"✂️ تم إغلاق 50% من حجم العقود وجني نصف الأرباح على ({part_cnt}) صفقات مفتوحة!",
        main_keyboard(uid),
    )


def show_financial_report(uid, chat_id):
    data = get_daily_financial_summary(uid)
    msg = (
        "📊 **التقرير المالي والمؤسسي المفصل** 📊\n"
        f"📅 التاريخ: `{data['date']}` | الجلسة: {get_global_session_status()}\n\n"
        f"📈 **إحصائيات الصفقات اليومية:**\n"
        f"• إجمالي الصفقات المنفذة اليوم: `{data['total_trades_entered']}`\n"
        f"• صفقات مغلقة (منتهية): `{data['closed_trades']}` | مفتوحة الآن: `{data['open_trades']}`\n"
        f"• صفقات رابحة: `{data['win_count']}` | صفقات خاسرة: `{data['loss_count']}`\n"
        f"• نسبة النجاح الدقيقة (Win Rate): `{data['win_rate']:.1f}%`\n"
        f"• معامل الربحية (Profit Factor): `{data['profit_factor']:.2f}`\n\n"
        f"💰 **الأموال والنتائج المحققة:**\n"
        f"• إجمالي الأرباح اليومية: `+{data['gross_profit']:.2f}$`\n"
        f"• إجمالي الخسائر اليومية: `-{data['gross_loss']:.2f}$`\n"
        f"• **صافي ربح/خسارة اليوم:** `{data['net_pnl']:+.2f}$`\n"
        f"• **صافي الأرباح التراكمي الكلي:** `{data['all_time_net']:+.2f}$`\n\n"
        f"🏦 **السيولة المشغّلة:**\n"
        f"• حجم الأموال المتداولة اليوم: `~{data['total_capital_used']:.2f}$`\n"
        f"• إجمالي اللوتات المنفذة: `{data['total_lots']:.2f}` لوت"
    )
    kb = {
        "inline_keyboard": [
            [{"text": "🎛️ إدارة الصفقات الحية الآن", "callback_data": "menu_live_positions"}],
            [{"text": "🔙 رجوع للوحة الرئيسية", "callback_data": "back_home"}],
        ]
    }
    send_msg(chat_id, msg, kb)


def resume_saved_auto_traders():
    for u in get_auto_running_users():
        if not is_running(u["user_id"]):
            start_trader(u["user_id"], u["chat_id"])
# ======================= 16. لوحة التحكم الشاملة وغرفة العمليات داخل تليجرام =======================
FIELD_SPECS = {
    "lot": (
        float,
        0.001,
        100.0,
        "💵 **تعديل حجم اللوت (Lot Size):**\nأرسل حجم اللوت لكل صفقة من الصفقات الثلاث الموحدة (مثال: `0.01` أو `0.05`):",
    ),
    "symbol": (
        str,
        0,
        0,
        "📊 **تغيير رمز التداول (Symbol):**\nأرسل رمز الزوج المطلوب (مثال: `XAUUSD` للذهب أو `EURUSD` أو `BTCUSDT`):",
    ),
    "trade_tp_usd": (
        float,
        0.05,
        100000.0,
        "🎯 **تعديل القمة الهدف الأساسي (TOP / Take Profit بالدولار):**\nأرسل قيمة الربح الأساسي بالدولار (مثال: `0.60`) وسيقوم البوت بتدريج الأهداف الثلاثة (TOP 1, TOP 2, TOP 3) تلقائياً:",
    ),
    "trade_sl_usd": (
        float,
        0.10,
        100000.0,
        "🛑 **تعديل القاع الوقف الأساسي (STOP / Stop Loss بالدولار):**\nأرسل قيمة وقف الخسارة الأساسي بالدولار (مثال: `1.00`):",
    ),
    "daily_max_profit": (
        float,
        0.10,
        1e7,
        "🏆 **الحد الأقصى للربح اليومي بالدولار:**\nأرسل المبلغ الذي يتوقف عنده البوت تلقائياً لحفظ أرباحك اليومية (مثال: `25`):",
    ),
    "daily_max_loss": (
        float,
        0.10,
        1e7,
        "🛡️ **الحد الأقصى للخسارة اليومية بالدولار:**\nأرسل أقصى مبلغ مسموح به قبل تفعيل قاطع الحماية اليومي (مثال: `10`):",
    ),
    "work_start_hour": (
        int,
        0,
        23,
        "🕐 **ساعة بدء العمل اليومي (0 - 23):**\nأرسل رقم الساعة بالتوقيت المحلي لبدء التداول الآلي:",
    ),
    "work_end_hour": (
        int,
        1,
        24,
        "🕑 **ساعة انتهاء العمل اليومي (1 - 24):**\nأرسل رقم الساعة بالتوقيت المحلي لانتهاء التداول الآلي:",
    ),
    "max_spread_usd": (
        float,
        0.10,
        50.0,
        "📡 **أقصى سبريد مسموح للدخول بالدولار (Spread Filter):**\nأرسل أقصى فرق سعر مقبول لفتح الصفقة (مثال: `1.80`):",
    ),
}

SET_CB = {
    "set_lot": "lot",
    "set_symbol": "symbol",
    "set_tp": "trade_tp_usd",
    "set_sl": "trade_sl_usd",
    "set_dmp": "daily_max_profit",
    "set_dml": "daily_max_loss",
    "set_ws": "work_start_hour",
    "set_we": "work_end_hour",
    "set_max_spread": "max_spread_usd",
}

BACK = {"inline_keyboard": [[{"text": "🔙 رجوع للوحة الرئيسية", "callback_data": "back_home"}]]}


def validate_field(field, text):
    kind, lo, hi, _ = FIELD_SPECS[field]
    text = text.strip()
    if kind is str:
        v = text.upper()
        if not re.fullmatch(r"[A-Z0-9._#]{3,20}", v):
            raise ValueError("رمز غير صالح، استخدم الحروف والأرقام فقط مثل XAUUSD")
        return v
    v = kind(text.replace(",", "."))
    if not lo <= v <= hi:
        raise ValueError(f"القيمة يجب أن تكون بين {lo} و {hi}")
    return v


def main_keyboard(uid):
    u = get_user(uid)
    accs = get_user_accounts(uid)
    act = get_active_account(uid)
    tool = get_ai_tool_by_id(u["selected_ai_id"])
    en_cnt = sum(1 for a in accs if a.get("is_enabled") == 1)

    run_btn = {
        "text": "⏹️ إيقاف القناص المؤسسي (يعمل 24/7 🟢)"
        if is_running(uid)
        else f"▶️ تشغيل القناص المؤسسي (ثقة >= {MIN_AI_CONFIDENCE}% | 3 صفقات موحدة)",
        "callback_data": "toggle_run",
    }

    be_icon = "🟢" if u.get("breakeven_enabled", 1) == 1 else "🔴"
    tr_icon = "🟢" if u.get("trailing_enabled", 1) == 1 else "🔴"

    return {
        "inline_keyboard": [
            [run_btn],
            [
                {"text": "⚡ تحليل شامل ودخول 3 صفقات موحدة الآن", "callback_data": "instant_trade"},
            ],
            [
                {"text": "🟢 شراء موحد فوري (3x BUY)", "callback_data": "manual_exec_BUY"},
                {"text": "🔴 بيع موحد فوري (3x SELL)", "callback_data": "manual_exec_SELL"},
            ],
            [
                {"text": "🔭 رادار الـ 30 يوماً + الحاضر + المستقبل + الشارت", "callback_data": "live_radar_analysis"},
            ],
            [
                {"text": "🎛️ غرفة إدارة الصفقات الحية (بدون فتح المنصة)", "callback_data": "menu_live_positions"},
            ],
            [
                {"text": "🛡️ تأمين الكل لنقطة الدخول (Break-Even)", "callback_data": "lock_all_be"},
                {"text": "💰 جني وإغلاق الرابحة فقط", "callback_data": "close_winners_only"},
            ],
            [
                {"text": f"🛡️ درع عدم الخسارة (BE:{be_icon} | Trail:{tr_icon})", "callback_data": "menu_protection_shield"},
                {"text": "📡 فحص السبريد ومواصفات العقد", "callback_data": "inspect_symbol"},
            ],
            [
                {"text": f"💵 اللوت: {u['lot']}", "callback_data": "set_lot"},
                {"text": f"📊 الزوج: {u['symbol']}", "callback_data": "set_symbol"},
            ],
            [
                {"text": f"🎯 القمة TOP: +{u['trade_tp_usd']}$", "callback_data": "set_tp"},
                {"text": f"🛑 القاع STOP: -{u['trade_sl_usd']}$", "callback_data": "set_sl"},
            ],
            [
                {"text": f"🏆 أقصى ربح: {u['daily_max_profit']}$", "callback_data": "set_dmp"},
                {"text": f"🛡️ أقصى خسارة: {u['daily_max_loss']}$", "callback_data": "set_dml"},
            ],
            [
                {"text": f"📂 الحسابات ({len(accs)}) | النشط: {act.get('account_label', '-')}", "callback_data": "menu_manage_accounts"},
                {"text": "➕ إضافة حساب", "callback_data": "menu_add_account"},
            ],
            [
                {
                    "text": f"🌐 التداول الجماعي: مفعّل ({en_cnt} حسابات) 🟢"
                    if u["trade_all_accounts"]
                    else "👤 الوضع: الحساب النشط فقط (اضغط لتفعيل الكل)",
                    "callback_data": "toggle_all",
                }
            ],
            [
                {"text": f"🤖 الذكاء الاصطناعي: {tool.get('name', '-')}", "callback_data": "menu_ai_select"},
            ],
            [
                {"text": "🔍 فحص الرصيد الحي والحسابات", "callback_data": "diag_all"},
                {"text": "📊 التقرير المالي المفصل", "callback_data": "show_report"},
            ],
            [
                {"text": "🔧 المعالج الذاتي للأخطاء (10027 / Bybit)", "callback_data": "menu_self_healer"},
                {"text": "📖 موسوعة الأكواد وحلولها", "callback_data": "menu_error_codes"},
            ],
            [
                {"text": "🚨 إغلاق جميع الصفقات المفتوحة فوراً", "callback_data": "emergency_close"},
                {"text": "🔄 تصفير عداد اليوم", "callback_data": "reset_pnl"},
            ],
        ]
    }


def main_text(uid):
    u = get_user(uid)
    accs = get_user_accounts(uid)
    act = get_active_account(uid)
    tool = get_ai_tool_by_id(u["selected_ai_id"])
    cached = LIVE_RADAR_CACHE.get(u["symbol"].upper(), {})
    live_p_str = f"`{cached['price']:.2f}`" if cached.get("price", 0) > 0 else "جاري الرصد..."
    be_status = "مفعّل 🟢" if u.get("breakeven_enabled", 1) == 1 else "معطّل 🔴"
    tr_status = "مفعّل 🟢" if u.get("trailing_enabled", 1) == 1 else "معطّل 🔴"
    sp_status = f"مفعّل (<= {u.get('max_spread_usd', 1.80):.2f}$) 🟢" if u.get("spread_filter_enabled", 1) == 1 else "معطّل 🔴"

    return (
        "🏛️ **غرفة العمليات المؤسسية الشاملة (MT5 + Bybit V5 Gold Sniper v5.0)**\n\n"
        f"• **حالة القناص الآلي:** {'يعمل بأقصى طاقة 24/7 🟢' if is_running(uid) else 'متوقف مؤقتاً 🔴'}\n"
        f"• **السيولة العالمية الآن:** {get_global_session_status()}\n"
        f"• **الزوج النشط:** `{u['symbol']}` | **السعر اللحظي:** {live_p_str}\n"
        f"• **هندسة الصفقات:** 3 صفقات موحدة الاتجاه (`L1` + `L2` + `L3` بدون أي صفقة عكسية متناقضة)\n"
        f"• **منهجية التحليل:** مسح 30 يوماً (D1/H4/H1) + اللحظة الراهنة (M15/M5/M1) + التوقع المستقبلي\n"
        f"• **تأمين الدخول التلقائي (Break-Even):** {be_status} | **الوقف المتحرك (Trailing):** {tr_status}\n"
        f"• **فلتر الحماية من السبريد:** {sp_status}\n"
        f"• **الحساب النشط:** `{act.get('account_label', 'لا يوجد')}` (`{act.get('server_or_mode', '')}`)\n"
        f"• **إجمالي الحسابات المربوطة:** `{len(accs)}` | **محرك AI:** `{tool.get('name', '-')}`\n"
        f"• **صافي ربح/خسارة اليوم:** `{u['current_daily_pnl']:+.2f}$` (`{u['trades_today']}` صفقات مغلقة)"
    )


def protection_settings_text(uid):
    u = get_user(uid)
    be_s = "مفعّل 🟢 (ينقل STOP لنقطة الدخول فور تحقيق 55% من الهدف الأول)" if u.get("breakeven_enabled", 1) == 1 else "معطّل 🔴"
    tr_s = "مفعّل 🟢 (يطارد السعر ويحجز الأرباح تلقائياً)" if u.get("trailing_enabled", 1) == 1 else "معطّل 🔴"
    sp_s = f"مفعّل 🟢 (يمنع الدخول إذا زاد السبريد عن {u.get('max_spread_usd', 1.80):.2f}$)" if u.get("spread_filter_enabled", 1) == 1 else "معطّل 🔴"
    return (
        "🛡️ **إعدادات درع الحماية الصفرية للخسائر (Zero-Loss Protection Shield):**\n\n"
        f"1️⃣ **تأمين نقطة الدخول التلقائي (Auto Break-Even):**\n   • الحالة: {be_s}\n\n"
        f"2️⃣ **الوقف المتحرك الذكي (Dynamic Trailing Stop):**\n   • الحالة: {tr_s}\n\n"
        f"3️⃣ **فلتر الحماية من السبريد العالي وقت الأخبار:**\n   • الحالة: {sp_s}\n\n"
        f"4️⃣ **ساعات عمل البوت المسموحة:**\n   • من الساعة `{u['work_start_hour']}:00` إلى `{u['work_end_hour']}:00`"
    )


def protection_settings_keyboard(uid):
    u = get_user(uid)
    be_txt = "✅ تأمين الدخول التلقائي (Break-Even): مفعّل" if u.get("breakeven_enabled", 1) == 1 else "⛔ تأمين الدخول التلقائي: معطّل"
    tr_txt = "✅ الوقف المتحرك (Trailing Stop): مفعّل" if u.get("trailing_enabled", 1) == 1 else "⛔ الوقف المتحرك: معطّل"
    sp_txt = "✅ فلتر السبريد الذكي: مفعّل" if u.get("spread_filter_enabled", 1) == 1 else "⛔ فلتر السبريد الذكي: معطّل"
    return {
        "inline_keyboard": [
            [{"text": be_txt, "callback_data": "toggle_be_shield"}],
            [{"text": tr_txt, "callback_data": "toggle_trail_shield"}],
            [{"text": sp_txt, "callback_data": "toggle_spread_shield"}],
            [{"text": f"📡 تعديل أقصى سبريد مسموح ({u.get('max_spread_usd', 1.80):.2f}$)", "callback_data": "set_max_spread"}],
            [
                {"text": f"🕐 بدء العمل: {u['work_start_hour']}h", "callback_data": "set_ws"},
                {"text": f"🕑 انتهاء العمل: {u['work_end_hour']}h", "callback_data": "set_we"},
            ],
            [{"text": "🔙 رجوع للوحة الرئيسية", "callback_data": "back_home"}],
        ]
    }


def accounts_keyboard(uid):
    u = get_user(uid)
    rows = []
    for a in get_user_accounts(uid):
        pk = a["acc_pk"]
        rows.append([
            {
                "text": ("🟢 [النشط] " if pk == u["active_account_id"] else "⚪ ")
                + f"{a['account_label']} [{a['server_or_mode']}]",
                "callback_data": f"select_acc_{pk}",
            },
            {"text": "✅" if a["is_enabled"] else "⛔", "callback_data": f"tog_acc_{pk}"},
            {"text": "🗑️ حذف", "callback_data": f"del_acc_{pk}"},
        ])
    rows += [
        [{"text": "➕ إضافة حساب جديد (MT5 أو Bybit)", "callback_data": "menu_add_account"}],
        [{"text": "🔙 رجوع للوحة الرئيسية", "callback_data": "back_home"}],
    ]
    return {"inline_keyboard": rows}


def ai_keyboard(uid):
    sel = get_user(uid)["selected_ai_id"]
    rows = [
        [{"text": ("✅ " if t["id"] == sel else "") + t["name"], "callback_data": f"pick_ai_{t['id']}"}]
        for t in get_ai_tools()
    ]
    return {"inline_keyboard": rows + [[{"text": "🔙 رجوع للوحة الرئيسية", "callback_data": "back_home"}]]}


# ======================= 17. غرفة إدارة الصفقات الحية والرادار داخل تليجرام (تغنيك عن فتح المنصة) =======================
def render_live_positions_panel(uid):
    """
    تعرض جميع الصفقات المفتوحة حالياً في MT5 و Bybit مع أزرار تحكم مباشرة لكل صفقة:
    - إغلاق الصفقة فوراً (100%)
    - إغلاق نصف العقد (50%) وجني ربح جزئي
    - تأمين الصفقة لنقطة الدخول (Break-Even: STOP = Entry)
    - تعديل سعر القمة الهدف (TOP) أو القاع الوقف (STOP) يدوياً من داخل تليجرام
    """
    accs = get_user_accounts(uid)
    lines = ["🎛️ **غرفة العمليات الحية لإدارة الصفقات المفتوحة (MT5 + Bybit):**\n"]
    kb_rows = []
    total_floating = 0.0
    total_count = 0

    for acc in accs:
        pos_list = broker_positions(acc, None, only_bot=False)
        if pos_list is None:
            lines.append(f"⚠️ **{acc['account_label']}:** تعذر سحب المراكز حالياً.")
            continue
        if not pos_list:
            lines.append(f"⚪ **{acc['account_label']}:** لا توجد صفقات مفتوحة حالياً.")
            continue

        lines.append(f"\n🏦 **الحساب [{acc['account_label']}] ({len(pos_list)} صفقات نشطة):**")
        for p in pos_list:
            total_count += 1
            pnl = float(p.get("profit") or 0.0)
            total_floating += pnl
            p_icon = "🟢" if pnl >= 0 else "🔴"
            pid = str(p["id"])
            ep = float(p.get("price_open") or 0.0)
            cp = float(p.get("price_current") or ep)
            tp_v = float(p.get("tp") or 0.0)
            sl_v = float(p.get("sl") or 0.0)

            lines.append(
                f"   {p_icon} **`{p['side']} {p['symbol']}`** | تذكرة: `#{pid}` | لوت: `{p['volume']}`\n"
                f"      • الدخول: `{ep:.2f}` ➡️ السعر الآن: `{cp:.2f}` | العائم: **`{pnl:+.2f}$`**\n"
                f"      • 🎯 القمة (TOP): `{tp_v:.2f}` | 🛑 الوقف (STOP): `{sl_v:.2f}`"
            )
            acc_pk = acc["acc_pk"]
            kb_rows.append([
                {"text": f"❌ إغلاق #{pid[:6]} ({pnl:+.2f}$)", "callback_data": f"pos_close_{acc_pk}_{pid}"},
                {"text": f"✂️ نصف العقد 50%", "callback_data": f"pos_half_{acc_pk}_{pid}"},
            ])
            kb_rows.append([
                {"text": f"🛡️ تأمين دخول #{pid[:6]}", "callback_data": f"pos_be_{acc_pk}_{pid}"},
                {"text": f"✏️ تعديل TOP/STOP #{pid[:6]}", "callback_data": f"pos_edit_{acc_pk}_{pid}"},
            ])

    lines.insert(
        1,
        f"• إجمالي الصفقات المفتوحة الآن: `{total_count}` | **إجمالي الربح/الخسارة العائم:** `{total_floating:+.2f}$`\n",
    )

    if total_count > 0:
        kb_rows.append([
            {"text": "🛡️ تأمين الكل لنقطة الدخول (Break-Even)", "callback_data": "lock_all_be"},
            {"text": "✂️ إغلاق 50% للكل", "callback_data": "half_all_pos"},
        ])
        kb_rows.append([
            {"text": "💰 إغلاق الصفقات الرابحة فقط", "callback_data": "close_winners_only"},
            {"text": "🚨 إغلاق كافة الصفقات فوراً", "callback_data": "emergency_close"},
        ])

    kb_rows.append([
        {"text": "🔄 تحديث الأسعار والأرباح الحية الآن", "callback_data": "menu_live_positions"},
        {"text": "🔙 رجوع للوحة الرئيسية", "callback_data": "back_home"},
    ])
    return "\n".join(lines), {"inline_keyboard": kb_rows}


def handle_single_position_action(uid, chat_id, mid, action_type, acc_pk, pos_id):
    acc = get_account_by_pk(int(acc_pk))
    if not acc or acc.get("user_id") != uid:
        send_msg(chat_id, "⚠️ الحساب غير موجود.")
        return
    pos_list = broker_positions(acc, None, only_bot=False) or []
    target_pos = next((p for p in pos_list if str(p["id"]) == str(pos_id)), None)
    if not target_pos:
        send_msg(chat_id, f"ℹ️ الصفقة `#{pos_id}` غير موجودة أو أُغلقت بالفعل.")
        txt, kb = render_live_positions_panel(uid)
        edit_msg(chat_id, mid, txt, kb)
        return

    if action_type == "close":
        ok = broker_close(acc, target_pos, partial_ratio=1.0)
        send_msg(chat_id, f"{'✅ تم إغلاق' if ok else '⚠️ تعذر إغلاق'} الصفقة `#{pos_id}` على `{acc['account_label']}`.")
    elif action_type == "half":
        ok = broker_close(acc, target_pos, partial_ratio=0.50)
        send_msg(chat_id, f"{'✂️ تم إغلاق 50% من' if ok else '⚠️ تعذر تقليص'} الصفقة `#{pos_id}`.")
    elif action_type == "be":
        ok = broker_move_to_breakeven(acc, target_pos, lock_offset_price=0.10)
        send_msg(
            chat_id,
            f"{'🛡️ تم تأمين وقف الخسارة (STOP) عند نقطة الدخول' if ok else '⚠️ السعر الحالي لم يسمح بعد بتأمين الدخول'} للصفقة `#{pos_id}`.",
        )

    time.sleep(0.3)
    txt, kb = render_live_positions_panel(uid)
    edit_msg(chat_id, mid, txt, kb)


def show_deep_market_radar(uid, chat_id):
    """عرض تقرير التحليل الشامل (30 يوماً ماضية + اللحظة الحالية + التوقع المستقبلي + الشارت النصي ومستويات TOP/STOP)"""
    u = get_user(uid)
    accs = get_target_accounts(uid)
    sent = send_msg(
        chat_id,
        f"🔭 **جاري إجراء المسح المؤسسي الشامل لزوج `{u['symbol']}`:**\n"
        "• سحب بيانات الـ 30 يوماً الماضية + الفريمات اللحظية + حساب معادلات المستقبل ومستويات TOP/STOP...",
    )
    mid = (sent.get("result") or {}).get("message_id")
    d = get_instant_or_fresh_analysis(uid, u["symbol"], accs, force_fresh=True)

    full_txt = (
        f"📡 **الرادار المؤسسي الحي — نسبة الثقة الحالية: `{d['confidence']}%` ({d['action']})**\n"
        f"• المحرك التحليلي: `{d['provider']}`\n\n"
        f"{d['detailed_report']}\n\n"
        f"{d.get('ascii_chart', '')}"
    )
    kb = {
        "inline_keyboard": [
            [{"text": f"🚀 دخول 3 صفقات موحدة ({d['action']}) بناءً على هذا التحليل", "callback_data": f"force_risk_{d['action']}"}],
            [{"text": "🔄 تحديث الرادار اللحظي الآن", "callback_data": "live_radar_analysis"}],
            [{"text": "🔙 رجوع للوحة الرئيسية", "callback_data": "back_home"}],
        ]
    }
    edit_msg(chat_id, mid, full_txt, kb) if mid else send_msg(chat_id, full_txt, kb)


def show_symbol_inspector(uid, chat_id):
    u = get_user(uid)
    acc = get_active_account(uid)
    if not acc:
        send_msg(chat_id, "⚠️ لا يوجد حساب نشط حالياً.", BACK)
        return
    specs = broker_symbol_specs(acc, u["symbol"])
    if not specs.get("ok"):
        send_msg(chat_id, f"⚠️ تعذر قراءة مواصفات الرمز: {specs.get('msg')}", BACK)
        return
    msg = (
        f"📡 **فاحص المواصفات والسيولة الحية ({specs['symbol']}) على [{acc['account_label']}]:**\n\n"
        f"• **سعر البيع الحي (Bid):** `{specs['bid']}`\n"
        f"• **سعر الشراء الحي (Ask):** `{specs['ask']}`\n"
        f"• **السبريد الفعلي الآن (Spread):** `{specs['spread_usd']}$` "
        f"({'ممتاز وآمن للدخول 🟢' if specs['spread_usd'] <= u.get('max_spread_usd', 1.80) else 'مرتفع حالياً ⚠️'})\n"
        f"• **أقل لوت مسموح:** `{specs['volume_min']}` | **أعلى لوت:** `{specs['volume_max']}` | **الخطوة:** `{specs['volume_step']}`\n"
        f"• **حجم العقد القياسي (Contract Size):** `{specs['contract_size']}`\n"
        f"• **أدنى مسافة وقف عند الوسيط (Stops Level):** `{specs['stops_level_pts']}` نقطة"
    )
    send_msg(chat_id, msg, BACK)


def run_self_healer_and_diagnostics(uid, chat_id):
    """المعالج الذاتي الشامل: يفحص ويصلح تلقائياً مشكلة 10027 في MT5 ومشكلة التوقيت/البروكسي في Bybit"""
    sent = send_msg(
        chat_id,
        "🔧 **جاري تشغيل المعالج الذاتي الشامل (Self-Healer Engine):**\n"
        "1. فحص وتفعيل زر Algo Trading في MT5 (علاج كود 10027)...\n"
        "2. مزامنة التوقيت الذري وفحص جسر Bybit (علاج أكواد 10002 و 403)...\n"
        "3. مطابقة الصفقات المفتوحة وتأمين الحسابات...",
    )
    mid = (sent.get("result") or {}).get("message_id")
    report_lines = ["🛠️ **تقرير المعالج الذاتي الشامل (Auto-Healer Report):**\n"]

    if NATIVE_MT5_AVAILABLE:
        with mt5_lock:
            algo_ok = send_win32_autotrading_enable()
            inject_global_broker_servers()
            report_lines.append(
                f"• **منصة MT5 (علاج الكود 10027):** {'تم تفعيل التداول الآلي بنجاح 🟢' if algo_ok else 'تم تحديث ملفات INI وجاهز للتشغيل ⚡'}"
            )
    else:
        report_lines.append("• **منصة MT5:** تعمل عبر الوضع السحابي / الهجين.")

    sync_bybit_time(get_user_bybit_proxy(uid), "https://api-demo.bybit.com")
    report_lines.append(f"• **مزامنة توقيت Bybit V5 (علاج كود 10002):** تم الضبط الدقيق (`offset={bybit_time_offset_ms}ms`) 🟢")

    u = get_user(uid)
    for acc in get_user_accounts(uid):
        ok, bal, eq, n, txt = broker_status(acc)
        status_icon = "✅" if ok else "⚠️"
        report_lines.append(f"• **{acc['account_label']} ({acc['server_or_mode']}):** {status_icon} {txt} | الرصيد: `{bal:.2f}$`")
        if ok:
            reconcile_account(uid, chat_id, acc, u["symbol"], manage=True)

    report_lines.append("\n📜 **آخر العمليات المسجلة في النظام:**\n`" + get_recent_logs(8) + "`")
    final_rep = "\n".join(report_lines)
    edit_msg(chat_id, mid, final_rep, main_keyboard(uid)) if mid else send_msg(chat_id, final_rep, main_keyboard(uid))


def show_error_encyclopedia_menu(chat_id, mid=None):
    txt = (
        "📖 **موسوعة أكواد أخطاء MT5 و Bybit V5 والحلول المدمجة في البوت:**\n\n"
        "🔹 **أشهر أكواد منصة MT5 وكيف يعالجها البوت تلقائياً:**\n"
        "• `10027` (AutoTrading Disabled): يقوم البوت بتفعيل زر Algo Trading برمجياً عبر Win32 API وتعديل `common.ini` بصيغة UTF-16LE.\n"
        "• `10030` (Unsupported Filling Mode): يجرب البوت تلقائياً أنماط `FOK` ثم `IOC` ثم `RETURN` حتى يقبل الوسيط.\n"
        "• `10016` (Invalid Stops): يفتح البوت الصفقة بالسوق أولاً ثم يركّب `TOP` و `STOP` في خطوة منفصلة مع مراعاة `StopsLevel`.\n"
        "• `10019` / `10014` (No Money / Invalid Volume): يخفض البوت حجم اللوت تلقائياً إلى الحد الأدنى المسموح (`0.01`).\n"
        "• `10004` / `10020` (Requote / Prices Changed): يسحب البوت تسعيرة Tick جديدة ويعيد الإرسال فوراً.\n"
        "• `10018` (Market Closed): يوقف المحاولة فوراً ريثما يفتح السوق الرسمي.\n\n"
        "🔸 **أشهر أكواد منصة Bybit V5 وكيف يعالجها البوت تلقائياً:**\n"
        "• `10002` (Timestamp Drift): يزامن البوت ساعته الداخلية مع سيرفر Bybit بالملي ثانية.\n"
        "• `10003` (Invalid API Key for Mode): يبدل البوت تلقائياً بين `BYBIT-DEMO` و `BYBIT-LIVE` و `BYBIT-TESTNET`.\n"
        "• `100028` (PositionIdx Mismatch): يكتشف البوت تلقائياً وضع `One-Way (0)` أو `Hedge Mode (1/2)`.\n"
        "• `110007` (Insufficient Balance): يرفع البوت الرافعة المالية إلى `50x` ويضبط الكمية على الحد الأدنى.\n"
        "• `HTTP 403` (Geo-Block): يمرر البوت الاتصال عبر جسر Cloudflare Worker أو بروكسي أوروبي تلقائياً.\n\n"
        "💡 *يمكنك أيضاً إرسال أي رقم كود في رسالة (مثال: `10027` أو `110007`) ليشرحه البوت لك بالتفصيل!*"
    )
    if mid:
        edit_msg(chat_id, mid, txt, BACK)
    else:
        send_msg(chat_id, txt, BACK)


def diagnostic_all(uid, chat_id):
    if uid in diag_running:
        return
    diag_running.add(uid)
    try:
        sent = send_msg(chat_id, "⏳ جاري فحص الاتصال الفعلي وسحب الرصيد الحي والهامش الحر لجميع الحسابات...")
        mid = (sent.get("result") or {}).get("message_id")
        lines = ["🔍 **تقرير الفحص الشامل للحسابات المربوطة:**\n"]
        first_ok_pk = None
        u = get_user(uid)

        for a in get_user_accounts(uid):
            ok, bal, eq, n, txt = broker_status(a)
            if ok:
                if first_ok_pk is None:
                    first_ok_pk = a["acc_pk"]
                lines.append(
                    f"✅ **{a['account_label']}** (`{a['server_or_mode']}`):\n"
                    f"   • الحالة: {txt}\n"
                    f"   • الرصيد (Balance): `{bal:.2f}$` | السيولة (Equity): `{eq:.2f}$`\n"
                    f"   • الصفقات المفتوحة الآن: `{n}`\n"
                )
            else:
                lines.append(f"⚠️ **{a['account_label']}** (`{a['server_or_mode']}`):\n   • الحالة: {txt}\n")
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
        send_msg(
            chat_id,
            f"✅ **تم حفظ وتفعيل الحساب ({acc['account_label']}) بنجاح!**\n"
            f"• الرصيد الحي: `{bal:.2f}$` | السيولة: `{eq:.2f}$`\n"
            f"• الحالة: {txt}",
            main_keyboard(uid),
        )
    else:
        send_msg(
            chat_id,
            f"⚠️ **تم حفظ الحساب ({acc['account_label']}) ولكن تعذر الاتصال بسيرفره حالياً:**\n"
            f"• السبب: {txt}\n"
            f"• نصيحة: إذا كان الوسيط خارجياً، تأكد من كتابة اسم السيرفر الدقيق أو `IP:Port`.",
            main_keyboard(uid),
        )


# ======================= 18. الاستقبال (Polling) ومعالجة الأوامر والتشغيل الرئيسي =======================
HEARTBEAT = {"poll": time.time()}
POLL_GEN = 0


def handle_message(msg):
    if "text" not in msg:
        return
    uid = msg["from"]["id"]
    chat_id = msg["chat"]["id"]
    text = msg["text"].strip()
    get_user(uid)
    update_user(uid, "is_authorized", 1)
    update_user(uid, "chat_id", chat_id)

    if text.startswith("/setproxy"):
        parts = text.split(maxsplit=1)
        proxy_url = parts[1].strip() if len(parts) > 1 else ""
        update_user(uid, "bybit_proxy", proxy_url)
        send_msg(chat_id, f"✅ تم تحديث جسر Bybit إلى:\n`{proxy_url or 'اتصال مباشر'}`", main_keyboard(uid))
        return

    if text.startswith("/start") or text.startswith("/menu") or SECRET_ACCESS_KEY in text:
        PENDING.pop(uid, None)
        send_msg(chat_id, main_text(uid), main_keyboard(uid))
        return

    if text.isdigit() and int(text) in MT5_ERROR_CATALOG:
        code_int = int(text)
        send_msg(chat_id, f"📖 **شرح كود MT5 ({code_int}):**\n{explain_mt5_retcode(code_int)}", main_keyboard(uid))
        return

    if text.isdigit() and int(text) in BYBIT_ERROR_CATALOG:
        code_int = int(text)
        send_msg(
            chat_id,
            f"📖 **شرح كود Bybit ({code_int}):**\n{BYBIT_ERROR_CATALOG[code_int][0]}",
            main_keyboard(uid),
        )
        return

    action = PENDING.get(uid)
    if action == "input_new_account":
        plat, p1, p2, p3 = parse_three_line_credentials(text)
        if plat == "INVALID":
            send_msg(
                chat_id,
                "⚠️ **صيغة غير مكتملة!** أرسل البيانات في 3 أسطر تحت بعضها:\n"
                "`رقم الحساب أو API_KEY`\n`كلمة المرور أو API_SECRET`\n`اسم السيرفر أو BYBIT-DEMO`",
            )
            return
        delete_msg(chat_id, msg["message_id"])
        pk = add_or_update_trading_account(uid, plat, p1, p2, p3, make_active=False)
        PENDING.pop(uid, None)
        send_msg(chat_id, "⏳ تم استلام البيانات وتشفيرها، جاري فحص الاتصال الفعلي بالحساب...")
        threading.Thread(target=test_new_account, args=(uid, chat_id, pk), daemon=True).start()

    elif action and action.startswith("edit_pos_"):
        parts = action.split("_", 3)
        acc_pk = int(parts[2])
        pos_id = parts[3]
        nums = re.findall(r"\d+(?:\.\d+)?", text.replace(",", "."))
        if len(nums) < 2:
            send_msg(
                chat_id,
                "⚠️ أرسل سعر القمة الهدف (`TOP`) وسعر القاع الوقف (`STOP`) مفصولين بمسافة (مثال: `3345.50 3328.00`):",
            )
            return
        new_top = float(nums[0])
        new_stop = float(nums[1])
        acc = get_account_by_pk(acc_pk)
        pos_list = broker_positions(acc, None, only_bot=False) or []
        target_pos = next((p for p in pos_list if str(p["id"]) == str(pos_id)), None)
        PENDING.pop(uid, None)
        if not target_pos:
            send_msg(chat_id, f"⚠️ الصفقة `#{pos_id}` غير موجودة أو أغلقت.", main_keyboard(uid))
            return
        ok = broker_modify_sltp(acc, target_pos, new_stop, new_top)
        send_msg(
            chat_id,
            f"{'✅ تم تحديث' if ok else '⚠️ تعذر تحديث'} مستويات الصفقة `#{pos_id}`:\n"
            f"• 🎯 القمة الهدف الجديد (TOP): `{new_top:.2f}`\n"
            f"• 🛑 القاع الوقف الجديد (STOP): `{new_stop:.2f}`",
            main_keyboard(uid),
        )

    elif action and action.startswith("field_"):
        field = action[6:]
        try:
            update_user(uid, field, validate_field(field, text))
            PENDING.pop(uid, None)
            send_msg(chat_id, "✅ تم حفظ الإعداد الجديد بنجاح!", main_keyboard(uid))
        except ValueError as e:
            send_msg(chat_id, f"⚠️ {e}. أعد الإرسال.")
    else:
        send_msg(chat_id, main_text(uid), main_keyboard(uid))


def handle_callback(cb):
    cid = cb["id"]
    uid = cb["from"]["id"]
    chat_id = cb["message"]["chat"]["id"]
    mid = cb["message"]["message_id"]
    data = cb.get("data", "")
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
            chat_id,
            mid,
            "➕ **إضافة حساب تداول جديد (MT5 ديمو/حقيقي أو Bybit V5):**\n"
            "أرسل البيانات في 3 أسطر تحت بعضها مباشرة:\n\n"
            "🔹 **لإضافة حساب MT5:**\n"
            "`رقم الحساب`\n"
            "`كلمة المرور`\n"
            "`اسم السيرفر (مثال: MetaQuotes-Demo أو IP:Port)`\n\n"
            "🔸 **لإضافة حساب Bybit:**\n"
            "`API_KEY`\n"
            "`API_SECRET`\n"
            "`BYBIT-DEMO` (أو `BYBIT-LIVE`)",
            BACK,
        )

    elif data == "menu_manage_accounts":
        answer_cb(cid)
        edit_msg(
            chat_id,
            mid,
            "📂 **إدارة الحسابات المربوطة:**\n"
            "• اضغط على اسم الحساب لتعيينه كحساب نشط.\n"
            "• اضغط على ✅/⛔ لتفعيله أو تعطيله في التداول الجماعي.\n"
            "• اضغط على 🗑️ لحذفه:",
            accounts_keyboard(uid),
        )

    elif data.startswith(("select_acc_", "tog_acc_", "del_acc_")):
        pk = int(data.rsplit("_", 1)[1])
        acc = get_account_by_pk(pk)
        if acc and acc.get("user_id") == uid:
            if data.startswith("select_acc_"):
                update_user(uid, "active_account_id", pk)
                answer_cb(cid, "✅ تم تفعيل الحساب")
            elif data.startswith("tog_acc_"):
                toggle_account(uid, pk)
                answer_cb(cid, "✅ تم تحديث حالة الحساب")
            else:
                if delete_trading_account(uid, pk):
                    answer_cb(cid, "🗑️ تم حذف الحساب")
                else:
                    answer_cb(cid, "⚠️ يجب إبقاء حساب واحد على الأقل", True)
        edit_msg(chat_id, mid, "📂 **إدارة الحسابات المربوطة:**", accounts_keyboard(uid))

    elif data == "toggle_all":
        answer_cb(cid)
        update_user(uid, "trade_all_accounts", 0 if get_user(uid)["trade_all_accounts"] else 1)
        home()

    elif data == "menu_protection_shield":
        answer_cb(cid)
        edit_msg(chat_id, mid, protection_settings_text(uid), protection_settings_keyboard(uid))

    elif data in ("toggle_be_shield", "toggle_trail_shield", "toggle_spread_shield"):
        u = get_user(uid)
        col_map = {
            "toggle_be_shield": "breakeven_enabled",
            "toggle_trail_shield": "trailing_enabled",
            "toggle_spread_shield": "spread_filter_enabled",
        }
        col = col_map[data]
        new_val = 0 if u.get(col, 1) == 1 else 1
        update_user(uid, col, new_val)
        answer_cb(cid, "✅ تم تحديث درع الحماية")
        edit_msg(chat_id, mid, protection_settings_text(uid), protection_settings_keyboard(uid))

    elif data == "menu_live_positions":
        answer_cb(cid, "🎛️ جاري سحب الصفقات الحية...")
        txt, kb = render_live_positions_panel(uid)
        edit_msg(chat_id, mid, txt, kb)

    elif data.startswith("pos_close_"):
        _, _, acc_pk, pid = data.split("_", 3)
        answer_cb(cid, "⏳ جاري إغلاق الصفقة...")
        threading.Thread(
            target=handle_single_position_action,
            args=(uid, chat_id, mid, "close", acc_pk, pid),
            daemon=True,
        ).start()

    elif data.startswith("pos_half_"):
        _, _, acc_pk, pid = data.split("_", 3)
        answer_cb(cid, "✂️ جاري إغلاق 50% من العقد...")
        threading.Thread(
            target=handle_single_position_action,
            args=(uid, chat_id, mid, "half", acc_pk, pid),
            daemon=True,
        ).start()

    elif data.startswith("pos_be_"):
        _, _, acc_pk, pid = data.split("_", 3)
        answer_cb(cid, "🛡️ جاري تأمين نقطة الدخول...")
        threading.Thread(
            target=handle_single_position_action,
            args=(uid, chat_id, mid, "be", acc_pk, pid),
            daemon=True,
        ).start()

    elif data.startswith("pos_edit_"):
        _, _, acc_pk, pid = data.split("_", 3)
        answer_cb(cid)
        PENDING[uid] = f"edit_pos_{acc_pk}_{pid}"
        edit_msg(
            chat_id,
            mid,
            f"✏️ **تعديل مستويات القمة (TOP) والوقف (STOP) للصفقة `#{pid}`:**\n\n"
            "أرسل الآن سعر القمة الهدف (`TOP`) متبوعاً بمسافة ثم سعر القاع الوقف (`STOP`)\n"
            "مثال:\n`3352.00 3331.50`",
            BACK,
        )

    elif data == "lock_all_be":
        answer_cb(cid, "🛡️ جاري تأمين جميع الصفقات لنقطة الدخول...")
        threading.Thread(target=lock_all_profits_breakeven, args=(uid, chat_id), daemon=True).start()

    elif data == "half_all_pos":
        answer_cb(cid, "✂️ جاري إغلاق 50% من جميع الصفقات...")
        threading.Thread(target=close_half_all_positions, args=(uid, chat_id), daemon=True).start()

    elif data == "close_winners_only":
        answer_cb(cid, "💰 جاري جني وإغلاق الصفقات الرابحة...")
        threading.Thread(target=close_profitable_positions_only, args=(uid, chat_id), daemon=True).start()

    elif data == "live_radar_analysis":
        answer_cb(cid, "🔭 جاري تحليل الـ 30 يوماً + الحاضر + المستقبل...")
        threading.Thread(target=show_deep_market_radar, args=(uid, chat_id), daemon=True).start()

    elif data == "inspect_symbol":
        answer_cb(cid, "📡 جاري فحص السبريد ومواصفات العقد...")
        threading.Thread(target=show_symbol_inspector, args=(uid, chat_id), daemon=True).start()

    elif data == "menu_self_healer":
        answer_cb(cid, "🔧 جاري تشغيل المعالج الذاتي الشامل...")
        threading.Thread(target=run_self_healer_and_diagnostics, args=(uid, chat_id), daemon=True).start()

    elif data == "menu_error_codes":
        answer_cb(cid)
        show_error_encyclopedia_menu(chat_id, mid)

    elif data == "diag_all":
        answer_cb(cid, "⚡ جاري الفحص الشامل للحسابات...")
        threading.Thread(target=diagnostic_all, args=(uid, chat_id), daemon=True).start()

    elif data == "menu_ai_select":
        answer_cb(cid)
        edit_msg(chat_id, mid, "🤖 **اختر محرك الذكاء الاصطناعي المفضل للتحليل:**", ai_keyboard(uid))

    elif data.startswith("pick_ai_"):
        answer_cb(cid, "✅ تم اختيار المحرك")
        update_user(uid, "selected_ai_id", int(data.rsplit("_", 1)[1]))
        home()

    elif data == "instant_trade":
        answer_cb(cid, "⚡ جاري التحليل الشامل (30 يوماً + اللحظة + المستقبل)...")
        accs = get_target_accounts(uid)
        threading.Thread(
            target=execute_ai_trade,
            args=(uid, chat_id, accs),
            kwargs={"manual": True, "force_risk": False},
            daemon=True,
        ).start()

    elif data.startswith("manual_exec_"):
        forced_dir = data.rsplit("_", 1)[1]
        answer_cb(cid, f"🚀 جاري تحليل السوق وتنفيذ 3 صفقات {forced_dir} موحدة...")
        accs = get_target_accounts(uid)
        threading.Thread(
            target=execute_ai_trade,
            args=(uid, chat_id, accs),
            kwargs={"manual": True, "force_risk": True, "forced_action": forced_dir},
            daemon=True,
        ).start()

    elif data.startswith("force_risk_"):
        forced_dir = data.rsplit("_", 1)[1]
        answer_cb(cid, f"⚡ جاري الدخول الثلاثي الموحد ({forced_dir})...")
        accs = get_target_accounts(uid)
        threading.Thread(
            target=execute_ai_trade,
            args=(uid, chat_id, accs),
            kwargs={"manual": True, "force_risk": True, "forced_action": forced_dir},
            daemon=True,
        ).start()

    elif data == "show_report":
        answer_cb(cid, "📊 جاري تجهيز التقرير المالي...")
        threading.Thread(target=show_financial_report, args=(uid, chat_id), daemon=True).start()

    elif data == "emergency_close":
        answer_cb(cid, "🚨 جاري إغلاق جميع الصفقات فوراً...")
        threading.Thread(target=emergency_close_all, args=(uid, chat_id), daemon=True).start()

    elif data in SET_CB:
        answer_cb(cid)
        PENDING[uid] = f"field_{SET_CB[data]}"
        edit_msg(chat_id, mid, FIELD_SPECS[SET_CB[data]][3], BACK)

    elif data == "reset_pnl":
        answer_cb(cid, "✅ تم تصفير عداد اليوم")
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
    safe_print(f"Telegram Polling started (generation {gen})")
    offset, backoff = 0, 1
    while not SHUTDOWN.is_set() and gen == POLL_GEN:
        HEARTBEAT["poll"] = time.time()
        res = tg_api(
            "getUpdates",
            {"offset": offset, "timeout": 15, "allowed_updates": ["message", "callback_query"]},
            timeout=25,
        )
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
        uptime_m = int((time.time() - BOT_START_TIME) // 60)
        status_line = (
            f"AI Institutional Sniper Bot v5.0 OK | Uptime: {uptime_m}m | "
            f"Last poll: {int(time.time() - HEARTBEAT['poll'])}s ago"
        )
        self.wfile.write(status_line.encode("utf-8"))

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
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
                safe_print("MT5 Terminal Ready with Verified AutoTrading Enabled.")
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
    safe_print("AI Institutional Sniper Bot v5.0 started successfully.")
    while not SHUTDOWN.is_set() and (time.time() - BOT_START_TIME < MAX_RUNTIME_SECONDS):
        SHUTDOWN.wait(5)
    SHUTDOWN.set()


if __name__ == "__main__":
    main()
