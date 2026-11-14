# -*- coding: utf-8 -*-
import os, sys, time, json, sqlite3, subprocess, urllib.request
from datetime import datetime, timezone
import numpy as np
import MetaTrader5 as mt5

def env(k, d=""):
    v = os.getenv(k)
    return v.strip() if v and v.strip() else d

TG_TOKEN = env("TELEGRAM_BOT_TOKEN")
SECRET = env("SECRET_ACCESS_KEY", "vip_secret_99")
MT5_LOGIN = int(env("MT5_LOGIN", "0") or 0)
MT5_PASS = env("MT5_PASSWORD")
MT5_SERVER = env("MT5_SERVER", "MetaQuotes-Demo")
GROQ_KEY = env("GROQ_TOKEN")
MT5_EXE = r"C:\Program Files\MetaTrader 5\terminal64.exe"

MAGIC = 990055
DB_FILE = "multi_mt5_gold_bot.db"
RISK_PCT = 0.5
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

# ---------- سجل + قاعدة بيانات ----------
def log(*a):
    msg = " ".join(str(x) for x in a)
    for s in (TG_TOKEN, MT5_PASS, GROQ_KEY):
        if s:
            msg = msg.replace(s, "***")
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)

def db():
    c = sqlite3.connect(DB_FILE)
    c.execute("CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT)")
    return c

def kv_get(k, d=None):
    try:
        c = db()
        r = c.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        c.close()
        return r[0] if r else d
    except Exception:
        return d

def kv_set(k, v):
    try:
        c = db()
        c.execute("INSERT OR REPLACE INTO kv VALUES(?,?)", (k, str(v)))
        c.commit()
        c.close()
    except Exception as e:
        log("db err", e)

# ---------- تليجرام ----------
def http_json(url, payload=None, headers=None, timeout=15):
    data = json.dumps(payload).encode() if payload is not None else None
    h = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "ignore"))
    except Exception as e:
        return {"error": str(e)}

def tg(text):
    chat = kv_get("chat_id")
    if not TG_TOKEN or not chat:
        log("TG:", text)
        return
    http_json(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
              {"chat_id": chat, "text": text[:3900]})

STATE = {"paused": False, "offset": 0}

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
                tg("✅ تم ربطك بالبوت.\n/status الحالة\n/pause إيقاف الدخول\n/resume استئناف\n/closeall إغلاق كل الصفقات")
            continue
        if cid != kv_get("chat_id"):
            continue
        if txt == "/status":
            tg(status_text())
        elif txt == "/pause":
            STATE["paused"] = True
            tg("⏸ تم إيقاف الدخول (الصفقات المفتوحة تبقى محمية).")
        elif txt == "/resume":
            STATE["paused"] = False
            tg("▶️ تم الاستئناف.")
        elif txt == "/closeall":
            close_all()

# ---------- MT5 ----------
def launch_terminal():
    ini = os.path.join(os.getcwd(), "startup.ini")
    with open(ini, "w") as f:
        f.write(f"[Common]\nLogin={MT5_LOGIN}\nPassword={MT5_PASS}\nServer={MT5_SERVER}\n"
                f"[Experts]\nEnabled=1\nAllowLiveTrading=1\nAllowDllImport=1\n")
    if os.path.exists(MT5_EXE):
        subprocess.Popen([MT5_EXE, f"/config:{ini}"])
        time.sleep(25)

def connect():
    if not MT5_LOGIN or not MT5_PASS:
        log("MT5_LOGIN / MT5_PASSWORD غير مضبوطين في secrets")
        return False
    launch_terminal()
    for i in range(5):
        kw = dict(login=MT5_LOGIN, password=MT5_PASS, server=MT5_SERVER, timeout=60000)
        if os.path.exists(MT5_EXE):
            kw["path"] = MT5_EXE
        if mt5.initialize(**kw):
            ti = mt5.terminal_info()
            if ti and not ti.trade_allowed:
                log("تحذير: التداول الآلي غير مفعّل في المنصة")
            return True
        log("init fail", mt5.last_error())
        time.sleep(10)
    return False

def find_symbol():
    for s in ("XAUUSD", "XAUUSDm", "XAUUSD.", "XAUUSD.a", "GOLD", "GOLDm", "XAUUSD#"):
        if mt5.symbol_select(s, True) and mt5.symbol_info(s):
            return s
    for s in (mt5.symbols_get() or []):
        if "XAU" in s.name.upper() or "GOLD" in s.name.upper():
            mt5.symbol_select(s.name, True)
            return s.name
    return None

# ---------- المؤشرات ----------
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
    a = np.where(atr(r, n) == 0, 1, atr(r, n))
    pdi, mdi = 100 * wilder(pdm, n) / a, 100 * wilder(mdm, n) / a
    s = np.where(pdi + mdi == 0, 1, pdi + mdi)
    return wilder(100 * abs(pdi - mdi) / s, n)

def rates(sym, tf, n=300):
    r = mt5.copy_rates_from_pos(sym, tf, 1, n)  # شموع مغلقة فقط
    return r if r is not None and len(r) >= 220 else None

# ---------- إدارة المخاطر ----------
def day_stats():
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    deals = mt5.history_deals_get(start, now) or []
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

def risk_check():
    acc = mt5.account_info()
    peak = max(float(kv_get("peak", acc.equity)), acc.equity)
    kv_set("peak", peak)
    dd = (peak - acc.equity) / peak * 100
    if dd >= MAX_DRAWDOWN_PCT:
        return f"🛑 القاطع الكلي: السحب {dd:.1f}% عن القمة. التداول متوقف نهائياً."
    pnl, streak = day_stats()
    if pnl <= -acc.balance * DAILY_LOSS_PCT / 100:
        return "حد الخسارة اليومي"
    if streak >= MAX_CONSEC_LOSSES:
        return f"{streak} خسائر متتالية: استراحة"
    return None

def calc_lot(sym, side, entry, sl):
    info, acc = mt5.symbol_info(sym), mt5.account_info()
    typ = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL
    loss1 = mt5.order_calc_profit(typ, sym, 1.0, entry, sl)
    if loss1 is None or loss1 == 0:
        return None
    loss1 = abs(loss1)
    risk_money = acc.balance * RISK_PCT / 100
    lot = np.floor(risk_money / loss1 / info.volume_step) * info.volume_step
    lot = max(info.volume_min, min(lot, info.volume_max))
    if lot * loss1 > risk_money * 2:
        return None
    margin = mt5.order_calc_margin(typ, sym, lot, entry)
    if margin is None or margin > acc.margin_free * 0.5:
        return None
    return round(float(lot), 2), risk_money

# ---------- الإشارة ----------
def get_plan(sym):
    tick, info = mt5.symbol_info_tick(sym), mt5.symbol_info(sym)
    if not tick or not info:
        return None, "لا بيانات"
    pos = mt5.positions_get(symbol=sym) or []
    if any(p.magic == MAGIC for p in pos):
        return None, "توجد صفقة مفتوحة"
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5 or not (SESSION_UTC[0] <= now.hour < SESSION_UTC[1]):
        return None, "خارج الجلسة"
    if now.weekday() == 4 and now.hour >= 18:
        return None, "نهاية الأسبوع"
    if tick.ask - tick.bid > MAX_SPREAD:
        return None, f"سبريد مرتفع {tick.ask - tick.bid:.2f}"
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
    if abs(entry - sl) > 3 * a:
        return None, "وقف بعيد (دخول متأخر)"
    lr = calc_lot(sym, side, entry, sl)
    if not lr:
        return None, "الرصيد/الهامش لا يكفي لمخاطرة آمنة"
    lot, risk_money = lr
    d = info.digits
    return {"side": side, "entry": entry, "sl": round(sl, d), "tp": round(tp, d), "lot": lot,
            "risk": round(risk_money, 2), "reward": round(risk_money * RR, 2),
            "adx": round(ax[-1], 1), "rsi": round(r15[-1], 1)}, "OK"

def ai_veto(sym, plan):
    """فلتر اختياري: يرفض فقط إذا قال AI صراحة REJECT"""
    if not GROQ_KEY:
        return False
    prompt = (f"Gold {plan['side']} setup: entry {plan['entry']}, SL {plan['sl']}, TP {plan['tp']}, "
              f"ADX {plan['adx']}, RSI {plan['rsi']}, H4 trend aligned. Reply ONLY with ACCEPT or REJECT.")
    r = http_json("https://api.groq.com/openai/v1/chat/completions",
                  {"model": "llama-3.3-70b-versatile", "max_tokens": 5, "temperature": 0,
                   "messages": [{"role": "user", "content": prompt}]},
                  headers={"Authorization": f"Bearer {GROQ_KEY}"})
    try:
        return "REJECT" in r["choices"][0]["message"]["content"].upper()
    except Exception:
        return False

# ---------- التنفيذ ----------
def send_order(sym, plan):
    info = mt5.symbol_info(sym)
    fm = [mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN]
    if info.filling_mode & 2:
        pass
    elif info.filling_mode & 1:
        fm = [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN]
    buy = plan["side"] == "BUY"
    last = None
    for attempt in range(6):
        tick = mt5.symbol_info_tick(sym)
        price = tick.ask if buy else tick.bid
        req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": plan["lot"],
               "type": mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL,
               "price": price, "sl": plan["sl"], "tp": plan["tp"], "deviation": 30,
               "magic": MAGIC, "comment": "ProBot", "type_time": mt5.ORDER_TIME_GTC,
               "type_filling": fm[attempt % len(fm)]}
        res = mt5.order_send(req)
        last = res
        if res is None:
            time.sleep(1.5)
            continue
        if res.retcode in (10008, 10009, 10010):
            return res
        if res.retcode == 10016:      # وقف قريب: افتح ثم عدّل
            req.pop("sl"); req.pop("tp")
            r2 = mt5.order_send(req)
            if r2 and r2.retcode in (10008, 10009, 10010):
                time.sleep(1)
                mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": r2.order,
                                "symbol": sym, "sl": plan["sl"], "tp": plan["tp"]})
                return r2
        if res.retcode in (10018, 10019, 10027, 10040, 10017, 10044):
            break
        time.sleep(1.5 if res.retcode == 10024 else 0.7)
    return last

def verify_sl(sym):
    """أي صفقة بدون وقف تُغلق فوراً (حماية)"""
    for p in mt5.positions_get(symbol=sym) or []:
        if p.magic == MAGIC and (p.sl == 0 or p.tp == 0):
            log("صفقة بلا SL/TP: إغلاق")
            close_pos(p)

def close_pos(p):
    t = mt5.symbol_info_tick(p.symbol)
    buy = p.type == 0
    mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": p.symbol, "volume": p.volume,
                    "type": mt5.ORDER_TYPE_SELL if buy else mt5.ORDER_TYPE_BUY,
                    "position": p.ticket, "price": t.bid if buy else t.ask, "deviation": 30,
                    "magic": MAGIC, "comment": "close", "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC})

def close_all():
    n = 0
    for p in mt5.positions_get() or []:
        if p.magic == MAGIC:
            close_pos(p); n += 1
    tg(f"تم إرسال إغلاق {n} صفقة.")

def manage(sym):
    """تأمين الصفقة عند ربح 1R بنقل الوقف لنقطة الدخول"""
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
                tg(f"🔒 تم تأمين الصفقة #{p.ticket} عند نقطة الدخول (Break-Even)")

TRACKED = set()

def track_closed(sym):
    cur = {p.ticket for p in (mt5.positions_get(symbol=sym) or []) if p.magic == MAGIC}
    for t in list(TRACKED - cur):
        deals = mt5.history_deals_get(position=t) or []
        out = [d for d in deals if d.entry == mt5.DEAL_ENTRY_OUT]
        if out:
            pnl = sum(d.profit + d.commission + d.swap for d in out)
            tg(f"{'✅ ربح' if pnl >= 0 else '❌ خسارة'} الصفقة #{t}: {pnl:+.2f}$")
        TRACKED.discard(t)
    TRACKED.update(cur)

def status_text():
    acc = mt5.account_info()
    if not acc:
        return "لا اتصال بالمنصة"
    peak = float(kv_get("peak", acc.equity))
    dd = (peak - acc.equity) / peak * 100 if peak else 0
    pnl, streak = day_stats()
    n = len([p for p in (mt5.positions_get() or []) if p.magic == MAGIC])
    return (f"💰 الرصيد {acc.balance:.2f} | الإكويتي {acc.equity:.2f}\n"
            f"📉 السحب عن القمة {dd:.1f}% (الحد {MAX_DRAWDOWN_PCT}%)\n"
            f"📆 أرباح اليوم {pnl:+.2f}$ | خسائر متتالية {streak}\n"
            f"📂 صفقات مفتوحة {n} | {'⏸ متوقف' if STATE['paused'] else '▶️ يعمل'}")

# ---------- الحلقة الرئيسية ----------
def main():
    log("بدء البوت")
    if not connect():
        tg("❌ فشل الاتصال بـ MT5. تأكد من MT5_LOGIN و MT5_PASSWORD و MT5_SERVER في secrets.")
        return
    sym = find_symbol()
    if not sym:
        tg("❌ لم أجد رمز الذهب عند الوسيط.")
        return
    acc = mt5.account_info()
    log(f"متصل: حساب {acc.login} رمز {sym} رصيد {acc.balance}")
    if not kv_get("peak"):
        kv_set("peak", acc.equity)
    tg(f"🤖 البوت يعمل على {sym}\n" + status_text())
    last_bar, killed_notified = 0, False
    while time.time() - START < MAX_RUNTIME:
        try:
            poll_telegram()
            if not mt5.terminal_info():
                connect()
            manage(sym)
            verify_sl(sym)
            track_closed(sym)
            blk = risk_check()
            if blk and blk.startswith("🛑"):
                if not killed_notified:
                    tg(blk); killed_notified = True
                time.sleep(30); continue
            m15 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M15, 1, 2)
            if m15 is not None and not STATE["paused"] and not blk:
                bar = int(m15[-1]["time"])
                if bar != last_bar:           # فحص واحد لكل شمعة M15 مغلقة
                    last_bar = bar
                    plan, why = get_plan(sym)
                    if plan is None:
                        log("لا دخول:", why)
                    elif ai_veto(sym, plan):
                        log("AI رفض الإشارة")
                    else:
                        res = send_order(sym, plan)
                        if res and res.retcode in (10008, 10009, 10010):
                            tg(f"📈 {plan['side']} {sym}\nدخول: {plan['entry']}\n"
                               f"🛑 STOP: {plan['sl']} (-{plan['risk']}$)\n"
                               f"🎯 TOP: {plan['tp']} (+{plan['reward']}$)\n"
                               f"لوت: {plan['lot']} | ADX {plan['adx']} | RSI {plan['rsi']}")
                        else:
                            rc = res.retcode if res else "None"
                            tg(f"⚠️ فشل التنفيذ (كود {rc})")
        except Exception as e:
            log("خطأ:", repr(e))
        time.sleep(10)
    log("انتهت الدورة؛ الصفقات المفتوحة محمية بوقف وهدف على السيرفر")
    mt5.shutdown()

if __name__ == "__main__":
    main()
