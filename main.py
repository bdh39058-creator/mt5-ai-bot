# -*- coding: utf-8 -*-
import os, sys, time, json, glob, sqlite3, subprocess, tempfile, urllib.request
from datetime import datetime, timezone, timedelta
import numpy as np

try:
    import MetaTrader5 as mt5
except Exception as _e:
    print("MetaTrader5 غير مثبتة:", _e)
    sys.exit(1)


def env(k, d=""):
    v = os.getenv(k)
    return v.strip().strip('"').strip("'") if v and v.strip() else d


TG_TOKEN = env("TELEGRAM_BOT_TOKEN")
TG_CHAT_ENV = env("TELEGRAM_CHAT_ID")
SECRET = env("SECRET_ACCESS_KEY", "change_me_now")
MT5_PASS = env("MT5_PASSWORD")
MT5_SERVER = env("MT5_SERVER")
GROQ_KEY = env("GROQ_TOKEN")
try:
    MT5_LOGIN = int(env("MT5_LOGIN", "0"))
except ValueError:
    MT5_LOGIN = 0

MAGIC = 990055
DB_FILE = "multi_mt5_gold_bot.db"
RISK_PCT = float(env("RISK_PCT", "0.5"))
RR = 2.0
ATR_SL_MULT = 1.5
MIN_ADX = 22
MAX_SPREAD = float(env("MAX_ALLOWED_SPREAD_USD", "0.60"))
DAILY_LOSS_PCT = 3.0
MAX_DRAWDOWN_PCT = 15.0
MAX_CONSEC_LOSSES = 3
SESSION_UTC = (7, 20)
MAX_RUNTIME = 330 * 60
START = time.time()
STATE = {"offset": 0, "sym": None}


# ================= سجل + قاعدة بيانات =================
def log(*a):
    msg = " ".join(str(x) for x in a)
    for s in (TG_TOKEN, MT5_PASS, GROQ_KEY):
        if s:
            msg = msg.replace(s, "***")
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def kv_get(k, d=None):
    try:
        c = sqlite3.connect(DB_FILE)
        c.execute("CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT)")
        r = c.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        c.close()
        return r[0] if r else d
    except Exception:
        return d


def kv_set(k, v):
    try:
        c = sqlite3.connect(DB_FILE)
        c.execute("CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT)")
        c.execute("INSERT OR REPLACE INTO kv VALUES(?,?)", (k, str(v)))
        c.commit()
        c.close()
    except Exception as e:
        log("db err", e)


# ================= HTTP + تليجرام =================
def http_json(url, payload=None, headers=None, timeout=15):
    data = json.dumps(payload).encode() if payload is not None else None
    h = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
    if headers:
        h.update(headers)
    try:
        req = urllib.request.Request(url, data=data, headers=h)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "ignore"))
    except Exception as e:
        return {"error": str(e)}


def chat_id():
    return TG_CHAT_ENV or kv_get("chat_id")


def tg(text):
    log("TG:", text.replace("\n", " | "))
    cid = chat_id()
    if TG_TOKEN and cid:
        http_json(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                  {"chat_id": cid, "text": text[:3900]})


def poll_telegram():
    if not TG_TOKEN:
        return
    res = http_json(f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates",
                    {"offset": STATE["offset"], "timeout": 0}, timeout=10)
    for u in res.get("result", []) or []:
        STATE["offset"] = u["update_id"] + 1
        m = u.get("message") or {}
        txt = (m.get("text") or "").strip()
        cid = str(m.get("chat", {}).get("id", ""))
        if txt.startswith("/start"):
            if SECRET in txt:
                kv_set("chat_id", cid)
                tg("✅ تم الربط.\n/status الحالة\n/pause إيقاف الدخول\n/resume استئناف\n"
                   "/closeall إغلاق كل الصفقات\n/resetkill إلغاء القاطع الكلي")
            continue
        if time.time() - m.get("date", 0) > 90:      # تجاهل الأوامر القديمة
            continue
        if cid != str(chat_id()):
            continue
        if txt == "/status":
            tg(status_text())
        elif txt == "/pause":
            kv_set("paused", "1")
            tg("⏸ تم إيقاف الدخول (الصفقات المفتوحة تبقى محمية).")
        elif txt == "/resume":
            kv_set("paused", "0")
            tg("▶️ تم الاستئناف.")
        elif txt == "/closeall":
            close_all()
        elif txt == "/resetkill":
            acc = mt5.account_info()
            if acc:
                kv_set("killed", "0")
                kv_set("peak", acc.equity)
                tg("♻️ تم إلغاء القاطع الكلي وإعادة ضبط القمة على الإكويتي الحالي.")


# ================= الاتصال بـ MT5 =================
def find_exe():
    c = [r"C:\Program Files\MetaTrader 5\terminal64.exe"]
    c += glob.glob(r"C:\Program Files*\*\terminal64.exe")
    for p in c:
        if os.path.exists(p):
            return p
    return None


def kill_terminal():
    subprocess.run(["taskkill", "/F", "/IM", "terminal64.exe"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)


def launch_terminal(exe):
    ini = os.path.join(tempfile.gettempdir(), "mt5_start.ini")
    try:
        with open(ini, "w") as f:
            f.write(f"[Common]\nLogin={MT5_LOGIN}\nPassword={MT5_PASS}\nServer={MT5_SERVER}\n"
                    f"[Experts]\nEnabled=1\nAllowLiveTrading=1\nAllowDllImport=1\n")
        subprocess.Popen([exe, f"/config:{ini}"])
        time.sleep(30)
    finally:
        try:
            os.remove(ini)
        except Exception:
            pass


def patch_common_ini(data_path):
    """تفعيل التداول الآلي في common.ini كخطة بديلة"""
    try:
        p = os.path.join(data_path, "config", "common.ini")
        text, enc = "", "utf-16"
        if os.path.exists(p):
            raw = open(p, "rb").read()
            enc = "utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8"
            text = raw.decode(enc, "ignore").lstrip("\ufeff")
        lines = [l for l in text.splitlines()
                 if not l.strip().lower().startswith(("allowlivetrading=", "enabled="))]
        if "[Experts]" not in lines:
            lines.append("[Experts]")
        i = lines.index("[Experts]")
        lines[i + 1:i + 1] = ["Enabled=1", "AllowLiveTrading=1"]
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding=enc) as f:
            f.write("\n".join(lines) + "\n")
        return True
    except Exception as e:
        log("patch common.ini فشل:", e)
        return False


def connect():
    if not (MT5_LOGIN and MT5_PASS and MT5_SERVER):
        tg("❌ أسرار MT5_LOGIN / MT5_PASSWORD / MT5_SERVER ناقصة في GitHub Secrets.")
        return False
    exe = find_exe()
    if not exe:
        tg("❌ لم يتم العثور على terminal64.exe (فشل تثبيت MT5).")
        return False
    patched = False
    for attempt in range(1, 4):
        mt5.shutdown()
        kill_terminal()
        launch_terminal(exe)
        ok = False
        for _ in range(6):
            if mt5.initialize(path=exe, login=MT5_LOGIN, password=MT5_PASS,
                              server=MT5_SERVER, timeout=60000):
                ok = True
                break
            log("initialize فشل:", mt5.last_error())
            time.sleep(10)
        if not ok:
            continue
        acc = mt5.account_info()
        if not acc or acc.login != MT5_LOGIN:
            log("تسجيل الدخول غير مطابق، المحاولة", attempt)
            continue
        ti = mt5.terminal_info()
        if ti and not ti.trade_allowed and not patched:
            log("Algo Trading مغلق، جاري التفعيل")
            patched = patch_common_ini(ti.data_path)
            continue
        if ti and not ti.trade_allowed:
            tg("⚠️ Algo Trading ما زال مغلقاً؛ قد تُرفض الأوامر (كود 10027).")
        return True
    tg("❌ فشل الاتصال بـ MT5 بعد 3 محاولات (تحقق من رقم الحساب/كلمة السر/اسم السيرفر).")
    return False


def find_symbol():
    for s in ("XAUUSD", "XAUUSDm", "XAUUSD.", "XAUUSD.a", "XAUUSDc", "GOLD", "GOLDm", "XAUUSD#"):
        if mt5.symbol_select(s, True) and mt5.symbol_info(s):
            return s
    for s in (mt5.symbols_get() or []):
        n = s.name.upper()
        if "XAU" in n or "GOLD" in n:
            mt5.symbol_select(s.name, True)
            return s.name
    return None


def server_now(sym):
    t = mt5.symbol_info_tick(sym)
    ts = t.time if t and t.time else time.time()
    return datetime.fromtimestamp(ts, timezone.utc)   # وقت السيرفر كأنه UTC


# ================= المؤشرات =================
def ema(a, n):
    k = 2 / (n + 1)
    out = np.empty(len(a))
    out[0] = a[0]
    for i in range(1, len(a)):
        out[i] = a[i] * k + out[i - 1] * (1 - k)
    return out


def wilder(a, n):
    out = np.zeros(len(a))
    out[n - 1] = a[:n].mean()
    for i in range(n, len(a)):
        out[i] = (out[i - 1] * (n - 1) + a[i]) / n
    return out


def atr(r, n=14):
    h, l, c = r["high"], r["low"], r["close"]
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    return wilder(np.concatenate([[h[0] - l[0]], tr]), n)


def rsi(c, n=14):
    d = np.diff(c, prepend=c[0])
    au = wilder(np.where(d > 0, d, 0.0), n)
    ad = wilder(np.where(d < 0, -d, 0.0), n)
    rs = np.divide(au, ad, out=np.full_like(au, 100.0), where=ad != 0)
    return 100 - 100 / (1 + rs)


def adx(r, n=14):
    h, l = r["high"], r["low"]
    up, dn = np.diff(h, prepend=h[0]), -np.diff(l, prepend=l[0])
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    a = atr(r, n)
    a = np.where(a == 0, 1, a)
    pdi, mdi = 100 * wilder(pdm, n) / a, 100 * wilder(mdm, n) / a
    s = np.where(pdi + mdi == 0, 1, pdi + mdi)
    return wilder(100 * abs(pdi - mdi) / s, n)


def rates(sym, tf, n=300):
    r = mt5.copy_rates_from_pos(sym, tf, 1, n)       # شموع مغلقة فقط
    return r if r is not None and len(r) >= 220 else None


# ================= إدارة المخاطر =================
def day_stats(sym):
    sn = server_now(sym)
    start = sn.replace(hour=0, minute=0, second=0, microsecond=0)
    deals = mt5.history_deals_get(start, sn + timedelta(days=1)) or []
    mine = sorted([d for d in deals if d.magic == MAGIC and d.entry == mt5.DEAL_ENTRY_OUT],
                  key=lambda x: x.time, reverse=True)
    pnl = sum(d.profit + d.commission + d.swap for d in mine)
    streak = 0
    for d in mine:
        if d.profit + d.commission + d.swap < 0:
            streak += 1
        else:
            break
    return pnl, streak


def risk_check(sym):
    acc = mt5.account_info()
    if kv_get("killed") == "1":
        return "🛑 القاطع الكلي مفعّل (أرسل /resetkill بعد المراجعة)."
    peak = max(float(kv_get("peak", acc.equity) or acc.equity), acc.equity)
    kv_set("peak", peak)
    dd = (peak - acc.equity) / peak * 100 if peak else 0
    if dd >= MAX_DRAWDOWN_PCT:
        kv_set("killed", "1")
        return f"🛑 القاطع الكلي: السحب {dd:.1f}% عن القمة. التداول متوقف."
    pnl, streak = day_stats(sym)
    if pnl <= -acc.balance * DAILY_LOSS_PCT / 100:
        return "حد الخسارة اليومي"
    if streak >= MAX_CONSEC_LOSSES:
        return f"{streak} خسائر متتالية: استراحة حتى الغد"
    return None


def calc_lot(sym, side, entry, sl):
    info, acc = mt5.symbol_info(sym), mt5.account_info()
    typ = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL
    loss1 = mt5.order_calc_profit(typ, sym, 1.0, entry, sl)
    if not loss1:
        return None
    loss1 = abs(loss1)
    risk_money = acc.balance * RISK_PCT / 100
    lot = np.floor(risk_money / loss1 / info.volume_step) * info.volume_step
    lot = max(info.volume_min, min(lot, info.volume_max))
    real_risk = lot * loss1
    if real_risk > risk_money * 2:                    # أقل لوت يتجاوز المخاطرة المسموحة
        return None
    margin = mt5.order_calc_margin(typ, sym, lot, entry)
    if margin is None or margin > acc.margin_free * 0.5:
        return None
    return round(float(lot), 2), real_risk


# ================= الإشارة =================
def get_plan(sym):
    tick, info = mt5.symbol_info_tick(sym), mt5.symbol_info(sym)
    if not tick or not info:
        return None, "لا بيانات"
    if info.trade_mode != mt5.SYMBOL_TRADE_MODE_FULL:
        return None, "التداول مغلق على الرمز"
    if any(p.magic == MAGIC for p in (mt5.positions_get(symbol=sym) or [])):
        return None, "توجد صفقة مفتوحة"
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5 or not (SESSION_UTC[0] <= now.hour < SESSION_UTC[1]):
        return None, "خارج الجلسة"
    if now.weekday() == 4 and now.hour >= 18:
        return None, "نهاية الأسبوع"
    spread = tick.ask - tick.bid
    if spread > MAX_SPREAD:
        return None, f"سبريد مرتفع {spread:.2f}"
    h4, h1, m15 = rates(sym, mt5.TIMEFRAME_H4), rates(sym, mt5.TIMEFRAME_H1), rates(sym, mt5.TIMEFRAME_M15)
    if h4 is None or h1 is None or m15 is None:
        return None, "شموع غير كافية"
    c4, c1, c15 = h4["close"], h1["close"], m15["close"]
    e50, e200 = ema(c4, 50), ema(c4, 200)
    e20h, e50h = ema(c1, 20), ema(c1, 50)
    e20m = ema(c15, 20)
    r15, ax, at = rsi(c15), adx(h1), atr(m15)
    if ax[-1] < MIN_ADX:
        return None, f"سوق عرضي ADX={ax[-1]:.0f}"
    up = e50[-1] > e200[-1] and c4[-1] > e50[-1] and e20h[-1] > e50h[-1]
    dn = e50[-1] < e200[-1] and c4[-1] < e50[-1] and e20h[-1] < e50h[-1]
    side = None
    if up and m15["low"][-2] <= e20m[-2] and c15[-1] > e20m[-1] and 45 <= r15[-1] <= 65 and r15[-1] > r15[-2]:
        side = "BUY"
    elif dn and m15["high"][-2] >= e20m[-2] and c15[-1] < e20m[-1] and 35 <= r15[-1] <= 55 and r15[-1] < r15[-2]:
        side = "SELL"
    if not side:
        return None, "لا إشارة مؤكدة"
    a = at[-1]
    entry = tick.ask if side == "BUY" else tick.bid
    if side == "BUY":
        sl = min(entry - ATR_SL_MULT * a, m15["low"][-10:].min() - 0.1 * a)
        tp = entry + RR * (entry - sl)
    else:
        sl = max(entry + ATR_SL_MULT * a, m15["high"][-10:].max() + 0.1 * a)
        tp = entry - RR * (sl - entry)
    dist = abs(entry - sl)
    if dist > 3 * a:
        return None, "وقف بعيد (دخول متأخر)"
    min_dist = max(info.trade_stops_level, info.trade_freeze_level) * info.point + spread
    if dist < min_dist:
        return None, "الوقف أقرب من الحد الأدنى للوسيط"
    lr = calc_lot(sym, side, entry, sl)
    if not lr:
        return None, "الرصيد/الهامش لا يكفي لمخاطرة آمنة"
    lot, risk_money = lr
    d = info.digits
    return {"side": side, "entry": round(entry, d), "sl": round(sl, d), "tp": round(tp, d), "lot": lot,
            "risk": round(risk_money, 2), "reward": round(risk_money * RR, 2),
            "adx": round(float(ax[-1]), 1), "rsi": round(float(r15[-1]), 1)}, "OK"


def ai_veto(plan):
    """فلتر اعتراض فقط: يرفض إذا قال AI صراحة REJECT، وأي عطل = لا اعتراض"""
    if not GROQ_KEY:
        return False
    prompt = (f"Gold {plan['side']} setup: entry {plan['entry']}, SL {plan['sl']}, TP {plan['tp']}, "
              f"ADX {plan['adx']}, RSI {plan['rsi']}, H4 trend aligned. Reply ONLY ACCEPT or REJECT.")
    r = http_json("https://api.groq.com/openai/v1/chat/completions",
                  {"model": "llama-3.3-70b-versatile", "max_tokens": 5, "temperature": 0,
                   "messages": [{"role": "user", "content": prompt}]},
                  headers={"Authorization": f"Bearer {GROQ_KEY}"})
    try:
        return "REJECT" in r["choices"][0]["message"]["content"].upper()
    except Exception:
        return False


# ================= التنفيذ =================
OK_CODES = (10008, 10009, 10010)


def send_order(sym, plan):
    fills = [mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN]
    buy = plan["side"] == "BUY"
    last = None
    for i in range(7):
        tick = mt5.symbol_info_tick(sym)
        req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": plan["lot"],
               "type": mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL,
               "price": tick.ask if buy else tick.bid, "sl": plan["sl"], "tp": plan["tp"],
               "deviation": 30, "magic": MAGIC, "comment": "ProBot",
               "type_time": mt5.ORDER_TIME_GTC, "type_filling": fills[i % 3]}
        res = mt5.order_send(req)
        last = res
        if res is None:
            time.sleep(1.5)
            continue
        if res.retcode in OK_CODES:
            return res
        if res.retcode == 10016:                       # افتح أولاً ثم ركّب الوقف
            req.pop("sl"); req.pop("tp")
            r2 = mt5.order_send(req)
            if r2 and r2.retcode in OK_CODES:
                time.sleep(1)
                for p in mt5.positions_get(symbol=sym) or []:
                    if p.magic == MAGIC and p.sl == 0:
                        mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": p.ticket,
                                        "symbol": sym, "sl": plan["sl"], "tp": plan["tp"]})
                return r2
        if res.retcode in (10017, 10018, 10019, 10027, 10040, 10042, 10043, 10044):
            break                                      # أخطاء لا تُحل بإعادة المحاولة
        time.sleep(1.5 if res.retcode == 10024 else 0.7)
    return last


def close_pos(p):
    t = mt5.symbol_info_tick(p.symbol)
    buy = p.type == 0
    return mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": p.symbol, "volume": p.volume,
                           "type": mt5.ORDER_TYPE_SELL if buy else mt5.ORDER_TYPE_BUY,
                           "position": p.ticket, "price": t.bid if buy else t.ask, "deviation": 30,
                           "magic": MAGIC, "comment": "close", "type_time": mt5.ORDER_TIME_GTC,
                           "type_filling": mt5.ORDER_FILLING_IOC})


def close_all():
    n = 0
    for p in mt5.positions_get() or []:
        if p.magic == MAGIC:
            close_pos(p)
            n += 1
    tg(f"تم إرسال إغلاق {n} صفقة.")


def verify_sl(sym):
    """صفقة بلا وقف/هدف لأكثر من 30 ثانية تُغلق فوراً"""
    sn = server_now(sym).timestamp()
    for p in mt5.positions_get(symbol=sym) or []:
        if p.magic == MAGIC and (p.sl == 0 or p.tp == 0) and sn - p.time > 30:
            tg(f"⚠️ الصفقة #{p.ticket} بلا SL/TP، يتم إغلاقها حمايةً.")
            close_pos(p)


def manage(sym):
    """عند ربح 1R ينقل الوقف لنقطة الدخول"""
    for p in mt5.positions_get(symbol=sym) or []:
        if p.magic != MAGIC or p.sl == 0:
            continue
        buy = p.type == 0
        r = abs(p.price_open - p.sl)
        be = (buy and p.sl >= p.price_open) or ((not buy) and p.sl <= p.price_open)
        if be or r == 0:
            continue
        moved = (p.price_current - p.price_open) if buy else (p.price_open - p.price_current)
        if moved >= r:
            res = mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": p.ticket,
                                  "symbol": sym, "sl": p.price_open, "tp": p.tp})
            if res and res.retcode == 10009:
                tg(f"🔒 تم تأمين الصفقة #{p.ticket} عند نقطة الدخول")


TRACKED = set()


def track_closed(sym):
    cur = {p.ticket for p in (mt5.positions_get(symbol=sym) or []) if p.magic == MAGIC}
    for t in list(TRACKED - cur):
        out = [d for d in (mt5.history_deals_get(position=t) or []) if d.entry == mt5.DEAL_ENTRY_OUT]
        if out:
            pnl = sum(d.profit + d.commission + d.swap for d in out)
            tg(f"{'✅ ربح' if pnl >= 0 else '❌ خسارة'} الصفقة #{t}: {pnl:+.2f}$")
        TRACKED.discard(t)
    TRACKED.update(cur)


def status_text():
    acc = mt5.account_info()
    sym = STATE["sym"]
    if not acc or not sym:
        return "لا اتصال بالمنصة"
    peak = float(kv_get("peak", acc.equity) or acc.equity)
    dd = (peak - acc.equity) / peak * 100 if peak else 0
    pnl, streak = day_stats(sym)
    n = len([p for p in (mt5.positions_get() or []) if p.magic == MAGIC])
    mode = "🛑 قاطع كلي" if kv_get("killed") == "1" else ("⏸ متوقف" if kv_get("paused") == "1" else "▶️ يعمل")
    return (f"💰 الرصيد {acc.balance:.2f} | الإكويتي {acc.equity:.2f}\n"
            f"📉 السحب عن القمة {dd:.1f}% (الحد {MAX_DRAWDOWN_PCT}%)\n"
            f"📆 نتيجة اليوم {pnl:+.2f}$ | خسائر متتالية {streak}\n"
            f"📂 صفقات مفتوحة {n} | {mode}")


# ================= الحلقة الرئيسية =================
def main():
    log("بدء البوت")
    if not connect():
        sys.exit(1)                                   # لا يُنشأ restart.flag
    sym = find_symbol()
    if not sym:
        tg("❌ لم أجد رمز الذهب عند الوسيط.")
        sys.exit(1)
    STATE["sym"] = sym
    acc = mt5.account_info()
    if not kv_get("peak"):
        kv_set("peak", acc.equity)
    tg(f"🤖 البوت يعمل على {sym} (حساب {acc.login})\n" + status_text())
    last_bar, notified, fails, last_hb = 0, False, 0, time.time()
    while time.time() - START < MAX_RUNTIME:
        try:
            poll_telegram()
            if not mt5.terminal_info() or not mt5.account_info():
                if connect():
                    fails = 0
                    sym = find_symbol() or sym
                    STATE["sym"] = sym
                else:
                    fails += 1
                    if fails >= 3:
                        tg("❌ انقطع الاتصال بـ MT5 نهائياً. الصفقات المفتوحة محمية بوقف وهدف.")
                        sys.exit(1)
                    continue
            manage(sym)
            verify_sl(sym)
            track_closed(sym)
            blk = risk_check(sym)
            if blk and blk.startswith("🛑"):
                if not notified:
                    tg(blk)
                    notified = True
                time.sleep(30)
                continue
            if time.time() - last_hb > 600:
                log(status_text().replace("\n", " | "))
                last_hb = time.time()
            m15 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M15, 1, 2)
            if m15 is not None and kv_get("paused") != "1" and not blk:
                bar = int(m15[-1]["time"])
                if bar != last_bar:                   # فحص واحد لكل شمعة M15
                    last_bar = bar
                    plan, why = get_plan(sym)
                    if plan is None:
                        log("لا دخول:", why)
                    elif ai_veto(plan):
                        log("AI اعترض على الإشارة")
                    else:
                        res = send_order(sym, plan)
                        if res and res.retcode in OK_CODES:
                            tg(f"📈 {plan['side']} {sym}\nدخول: {plan['entry']}\n"
                               f"🛑 STOP: {plan['sl']} (-{plan['risk']}$)\n"
                               f"🎯 TOP: {plan['tp']} (+{plan['reward']}$)\n"
                               f"لوت {plan['lot']} | ADX {plan['adx']} | RSI {plan['rsi']}")
                        else:
                            tg(f"⚠️ فشل التنفيذ (كود {res.retcode if res else 'None'})")
        except SystemExit:
            raise
        except Exception as e:
            log("خطأ:", repr(e))
        time.sleep(10)
    log("انتهت الدورة بنجاح؛ الصفقات المفتوحة محمية بوقف وهدف على السيرفر.")
    with open("restart.flag", "w") as f:              # يسمح للـ workflow بإعادة التشغيل
        f.write("ok")
    mt5.shutdown()


if __name__ == "__main__":
    main()
