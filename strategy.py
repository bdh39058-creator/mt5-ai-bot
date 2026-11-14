# -*- coding: utf-8 -*-
"""محرك استراتيجية احترافي: اتجاه H4 + زخم H1 + دخول M15 + SL/TP + إدارة مخاطر"""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime, timezone

RISK_PCT = 0.5            # مخاطرة 0.5% من الرصيد لكل صفقة
RR = 2.0                  # الهدف = ضعف الوقف
ATR_SL_MULT = 1.5
MIN_ADX = 22
MAX_SPREAD = 0.60         # بالدولار للذهب
DAILY_LOSS_LIMIT_PCT = 3.0
MAX_CONSEC_LOSSES = 3
SESSION_UTC = (7, 20)     # لندن + نيويورك فقط


def _rates(sym, tf, n=300):
    r = mt5.copy_rates_from_pos(sym, tf, 1, n)  # 1 = شموع مغلقة فقط
    if r is None or len(r) < 220:
        return None
    return r


def ema(a, n):
    k = 2 / (n + 1)
    out = np.empty_like(a, dtype=float)
    out[0] = a[0]
    for i in range(1, len(a)):
        out[i] = a[i] * k + out[i - 1] * (1 - k)
    return out


def _wilder(a, n):
    out = np.zeros_like(a, dtype=float)
    out[n - 1] = a[:n].mean()
    for i in range(n, len(a)):
        out[i] = (out[i - 1] * (n - 1) + a[i]) / n
    return out


def atr(r, n=14):
    h, l, c = r["high"], r["low"], r["close"]
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    return _wilder(np.concatenate([[h[0] - l[0]], tr]), n)


def rsi(c, n=14):
    d = np.diff(c, prepend=c[0])
    up, dn = np.where(d > 0, d, 0.0), np.where(d < 0, -d, 0.0)
    au, ad = _wilder(up, n), _wilder(dn, n)
    rs = np.divide(au, ad, out=np.full_like(au, 100.0), where=ad != 0)
    return 100 - 100 / (1 + rs)


def adx(r, n=14):
    h, l = r["high"], r["low"]
    up, dn = np.diff(h, prepend=h[0]), -np.diff(l, prepend=l[0])
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    a = atr(r, n)
    pdi = 100 * _wilder(pdm, n) / np.where(a == 0, 1, a)
    mdi = 100 * _wilder(mdm, n) / np.where(a == 0, 1, a)
    dx = 100 * abs(pdi - mdi) / np.where(pdi + mdi == 0, 1, pdi + mdi)
    return _wilder(dx, n)


def _round_down_step(v, step):
    return np.floor(v / step) * step


def calc_lot(sym, sl_dist, balance):
    info = mt5.symbol_info(sym)
    if not info or info.trade_tick_size == 0:
        return None
    risk_money = balance * RISK_PCT / 100
    loss_per_lot = sl_dist / info.trade_tick_size * info.trade_tick_value
    if loss_per_lot <= 0:
        return None
    lot = _round_down_step(risk_money / loss_per_lot, info.volume_step)
    lot = max(info.volume_min, min(lot, info.volume_max))
    # إذا أقل لوت يعرّضك لمخاطرة أكبر من 3 أضعاف المسموح: ارفض الصفقة
    if lot * loss_per_lot > risk_money * 3:
        return None
    return round(float(lot), 2)


def risk_blocked(magic, balance):
    """يوقف التداول بعد خسارة يومية كبيرة أو 3 خسائر متتالية"""
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    deals = mt5.history_deals_get(start, now) or []
    mine = [d for d in deals if d.magic == magic and d.entry == mt5.DEAL_ENTRY_OUT]
    pnl = sum(d.profit + d.commission + d.swap for d in mine)
    if pnl <= -balance * DAILY_LOSS_LIMIT_PCT / 100:
        return "تم بلوغ حد الخسارة اليومي"
    streak = 0
    for d in sorted(mine, key=lambda x: x.time, reverse=True):
        if d.profit + d.commission + d.swap < 0:
            streak += 1
        else:
            break
    if streak >= MAX_CONSEC_LOSSES:
        return f"{streak} خسائر متتالية: استراحة حتى الغد"
    return None


def get_trade_plan(sym, magic):
    """يرجع (plan, reason). plan=None يعني: لا تدخل."""
    acc = mt5.account_info()
    tick = mt5.symbol_info_tick(sym)
    if not acc or not tick:
        return None, "لا بيانات"
    if mt5.positions_get(symbol=sym) and any(p.magic == magic for p in mt5.positions_get(symbol=sym)):
        return None, "توجد صفقة مفتوحة بالفعل"
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5 or not (SESSION_UTC[0] <= now.hour < SESSION_UTC[1]):
        return None, "خارج جلسة لندن/نيويورك"
    if now.weekday() == 4 and now.hour >= 18:
        return None, "نهاية الأسبوع"
    if tick.ask - tick.bid > MAX_SPREAD:
        return None, f"السبريد مرتفع {tick.ask - tick.bid:.2f}"
    blk = risk_blocked(magic, acc.balance)
    if blk:
        return None, blk

    h4, h1, m15 = _rates(sym, mt5.TIMEFRAME_H4), _rates(sym, mt5.TIMEFRAME_H1), _rates(sym, mt5.TIMEFRAME_M15)
    if h4 is None or h1 is None or m15 is None:
        return None, "بيانات الشموع غير كافية"

    c4, c1, c15 = h4["close"], h1["close"], m15["close"]
    e50_4, e200_4 = ema(c4, 50), ema(c4, 200)
    e20_1, e50_1 = ema(c1, 20), ema(c1, 50)
    e20_15 = ema(c15, 20)
    rsi15, adx1, atr15 = rsi(c15), adx(h1), atr(m15)

    trend_up = e50_4[-1] > e200_4[-1] and c4[-1] > e50_4[-1]
    trend_dn = e50_4[-1] < e200_4[-1] and c4[-1] < e50_4[-1]
    h1_up, h1_dn = e20_1[-1] > e50_1[-1], e20_1[-1] < e50_1[-1]
    if adx1[-1] < MIN_ADX:
        return None, f"سوق عرضي ADX={adx1[-1]:.0f}"

    side = None
    # شراء: اتجاه صاعد + ارتداد لـ EMA20 ثم إغلاق فوقه + RSI صحي
    if trend_up and h1_up and m15["low"][-2] <= e20_15[-2] and c15[-1] > e20_15[-1] \
            and 45 <= rsi15[-1] <= 65 and rsi15[-1] > rsi15[-2]:
        side = "BUY"
    elif trend_dn and h1_dn and m15["high"][-2] >= e20_15[-2] and c15[-1] < e20_15[-1] \
            and 35 <= rsi15[-1] <= 55 and rsi15[-1] < rsi15[-2]:
        side = "SELL"
    if not side:
        return None, "لا توجد إشارة مؤكدة"

    a = atr15[-1]
    entry = tick.ask if side == "BUY" else tick.bid
    if side == "BUY":
        sl = min(entry - ATR_SL_MULT * a, m15["low"][-10:].min() - 0.1 * a)
        risk = entry - sl
        tp = entry + RR * risk
    else:
        sl = max(entry + ATR_SL_MULT * a, m15["high"][-10:].max() + 0.1 * a)
        risk = sl - entry
        tp = entry - RR * risk
    if risk > 3 * a:
        return None, "الوقف بعيد جداً (دخول متأخر)"

    lot = calc_lot(sym, risk, acc.balance)
    if not lot:
        return None, "الرصيد لا يكفي لمخاطرة آمنة"
    d = mt5.symbol_info(sym).digits
    return {"side": side, "entry": entry, "sl": round(sl, d), "tp": round(tp, d),
            "lot": lot, "risk_usd": round(acc.balance * RISK_PCT / 100, 2),
            "atr": round(a, 2), "adx": round(adx1[-1], 1), "rsi": round(rsi15[-1], 1)}, "OK"


def manage_positions(sym, magic):
    """استدعِها كل 30 ثانية: عند ربح 1R ينقل الوقف لنقطة الدخول (تأمين)"""
    for p in (mt5.positions_get(symbol=sym) or []):
        if p.magic != magic or p.sl == 0:
            continue
        r_dist = abs(p.price_open - p.sl)
        if p.sl == p.price_open or r_dist == 0:
            continue
        moved = (p.price_current - p.price_open) if p.type == 0 else (p.price_open - p.price_current)
        already_be = (p.type == 0 and p.sl >= p.price_open) or (p.type == 1 and p.sl <= p.price_open)
        if moved >= r_dist and not already_be:
            mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": p.ticket,
                            "symbol": sym, "sl": p.price_open, "tp": p.tp})
