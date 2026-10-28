"""Swing setups on NSE: 3 to 15 trading days, from daily bars, fundamentals and technicals.

    python nse/swing.py eod            # after the close: full scan, new setups, track record, page, sheet
    python nse/swing.py live           # in the session: prices, entries and exits hit, levels crossed now
    python nse/swing.py fundamentals   # weekly: refresh every liquid stock's fundamentals (Upstox)
    python nse/swing.py options        # the options screen on the last scan's plans (options.py)

Three lists, each ranked on technicals and fundamentals together:
  Bullish     all liquid stocks: breakouts, pullbacks in an uptrend, bounces off support
  Breakdowns  F&O stocks only (the stocks with options): breakdowns, failed rallies in a downtrend
  Bottoms     all liquid stocks well off their high and sitting on support; "turning up" once
              price confirms, with a buy zone and the close that would prove the support broken

Every plan: a trigger entry (above the day's high, or below its low for a breakdown), a stop
where the setup is proven wrong, a target (the next level that is at least 1.5R away, else 2R),
the replay odds (the stock's own last year of days, resampled) and the estimated days.

Support and resistance are price zones where past swing highs and lows cluster (a swing high
is the highest bar of the 11 around it). A zone touched twice or more counts.

Nothing here is advice to buy or sell. It is a rules screen with its numbers; the replays are
not a forecast, and a gap can jump any stop.
"""

import argparse
import bisect
import concurrent.futures
import datetime
import json
import math
import os
import random
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import market  # noqa: E402
import options  # noqa: E402
import upstox  # noqa: E402

ROOT = market.ROOT
OUT = os.path.join(ROOT, "docs")
STATE = os.path.join(ROOT, "trader")
LEVELS = os.path.join(STATE, "swing-levels.json")
LOG = os.path.join(STATE, "swing-log.json")
OPT_LOG = os.path.join(STATE, "options-log.json")
IV_LOG = os.path.join(STATE, "iv-history.json")
RESULTS_SEEN = os.path.join(STATE, "results-headlines.json")
FUNDS = os.path.join(STATE, "fundamentals.json")
PAGE = os.path.join(OUT, "swing.json")
CHARTS = os.path.join(OUT, "swing-charts.json")

DEFAULTS = {
    "min_price": 20, "min_turnover_cr": 5,        # liquid: 20-day median turnover of at least 5 crore
    "horizon_days": 15, "entry_valid_days": 3,    # a trade lasts up to 15 sessions; an entry waits 3
    "budget": 100000, "max_loss_per_trade": 1000, "max_position_pct": 40, "cash_buffer_pct": 10,
    "min_reward_risk": 1.5, "target_r": 2, "show": 10, "replays": 10000, "fundamentals_days": 7,
    # a plan is recommended only if it clears every one of these; otherwise it is watchlist only
    "gate": {"min_avg_r": 0.30, "min_p_target": 0.35, "min_hist_trades": 3, "min_hist_avg_r": 0.25,
             "min_turnover_cr": 20, "min_rr": 2.0, "long_min_fund": 55, "short_max_fund": 50,
             "bottom_min_fund": 60, "rs_long_in_down_market": 85, "rs_short_max": 50},
}
TICK = 0.05
PIVOT = 5                                         # a swing high is the top of the 11 bars around it
LOOKBACK = 250                                    # a year of sessions for levels and the 52-week range


def log(msg):
    print("[%s] %s" % (market.to_ist(market.utc_now()).strftime("%H:%M:%S"), msg), flush=True)


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def write_json(path, doc, indent=1):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=indent, default=str, ensure_ascii=False)
        fh.write("\n")


def config():
    cfg = read_json(os.path.join(ROOT, "config.json"), {})
    out = dict(DEFAULTS, **(cfg.get("swing") or {}))
    out["gate"] = dict(DEFAULTS["gate"], **((cfg.get("swing") or {}).get("gate") or {}))
    return out, cfg


def gate(r, p, nifty_trend, cfg):
    """Every check a plan must clear to be recommended: [{"name", "ok", "detail"}], and whether all passed.
    Run after the full numbers (10,000 replays, the rule's own history) are in."""
    G = cfg["gate"]
    o, h = p.get("odds") or {}, p.get("history") or {}
    long_ = p["side"] == "long"
    fund, rs = r.get("fund"), r.get("rs_pct", 50)
    out = []

    def add(name, ok, detail):
        out.append({"name": name, "ok": bool(ok), "detail": detail})

    add("Replay expectancy", o.get("avg_R", -9) >= G["min_avg_r"],
        "%+.2fR a trade over %s replays (needs %+.2fR or more)" % (o.get("avg_R", 0), format(o.get("n", 0), ","), G["min_avg_r"]))
    add("Target reachable", o.get("p_target", 0) >= G["min_p_target"],
        "target first in %d%% of replays, stop first in %d%% (needs %d%%+)" % (
            100 * o.get("p_target", 0), 100 * o.get("p_stop", 0), 100 * G["min_p_target"]))
    fired, havg = h.get("fired", 0), h.get("avg_R")
    add("Worked on this stock before",
        fired >= G["min_hist_trades"] and havg is not None and havg >= G["min_hist_avg_r"] and h.get("target", 0) >= h.get("stop", 0),
        "fired %d times: %d targets, %d stops%s (needs %d+ times, %+.2fR+ average, targets >= stops)" % (
            fired, h.get("target", 0), h.get("stop", 0), ", average %+.2fR" % havg if havg is not None else "",
            G["min_hist_trades"], G["min_hist_avg_r"]))
    if long_:
        need = G["bottom_min_fund"] if p["kind"] == "bottom reversal" else G["long_min_fund"]
        add("Fundamentals agree", fund is not None and fund >= need,
            "score %s (needs %d or more)" % ("n/a" if fund is None else fund, need))
        add("Market agrees", nifty_trend != "down" or rs >= G["rs_long_in_down_market"],
            "Nifty trend %s; stronger than %d%% of stocks (in a falling market needs %d%%+)" % (
                nifty_trend or "?", rs, G["rs_long_in_down_market"]))
    else:
        add("Fundamentals agree", fund is not None and fund <= G["short_max_fund"],
            "score %s (a short needs %d or less)" % ("n/a" if fund is None else fund, G["short_max_fund"]))
        add("Market agrees", nifty_trend != "up" and rs <= G["rs_short_max"],
            "Nifty trend %s; stronger than %d%% of stocks (a short needs a Nifty not rising and %d%% or less)" % (
                nifty_trend or "?", rs, G["rs_short_max"]))
    add("Liquid", (r.get("turnover_cr") or 0) >= G["min_turnover_cr"],
        "Rs %s cr traded a day (needs %s cr+)" % (r.get("turnover_cr"), G["min_turnover_cr"]))
    add("Reward:risk", p["rr"] >= G["min_rr"], "%.1f (needs %.1f+)" % (p["rr"], G["min_rr"]))
    return out, all(c["ok"] for c in out)


def up(x):
    return round(math.ceil(round(x / TICK, 6)) * TICK, 2)


def down(x):
    return round(math.floor(round(x / TICK, 6)) * TICK, 2)


# ---------------------------------------------------------------- data

def universe():
    out = []
    with open(os.path.join(STATE, "universe.txt"), encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                sym, _, name = line.strip().partition("|")
                out.append((sym, name))
    return out


def yahoo_daily(sym):
    doc = market.yahoo_json("/v8/finance/chart/%s?range=2y&interval=1d" % market.yahoo_symbol(sym))
    r = doc["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    out = []
    for i, t in enumerate(r.get("timestamp") or []):
        o, h, lo, c, v = (q.get(k, [None])[i] for k in ("open", "high", "low", "close", "volume"))
        if None in (o, h, lo, c):
            continue
        d = market.to_ist(datetime.datetime(1970, 1, 1) + datetime.timedelta(seconds=t)).date().isoformat()
        out.append({"d": d, "o": o, "h": h, "l": lo, "c": c, "v": int(v or 0)})
    return out


class Data(object):
    """Upstox first, Yahoo for anything Upstox does not answer. Records what came from where."""

    def __init__(self, errors):
        self.errors = errors
        self.ok = bool(upstox.token())
        self.status = "ok" if self.ok else "no token"
        self.inst = {"eq": {}, "fo": {}}
        try:
            self.inst = upstox.instruments()
        except Exception as e:                       # noqa: BLE001
            errors.append("Upstox instrument list: %s" % e)
            self.ok = False
            self.status = "instrument list failed"
        self.bars_from = {"Upstox": 0, "Yahoo": 0}

    def _off(self, e):
        if isinstance(e, upstox.TokenError):
            self.ok = False
            self.status = "token rejected"
            self.errors.append(str(e))

    def quotes(self, symbols):
        if self.ok:
            keys = {s: v["key"] for s, v in self.inst["eq"].items()}
            try:
                return upstox.quotes(symbols, keys), "Upstox"
            except Exception as e:                   # noqa: BLE001
                self._off(e)
                self.errors.append("Upstox quotes: %s; used Yahoo" % e)
        return yahoo_quotes(symbols), "Yahoo"

    def bars(self, sym, to_date):
        info = self.inst["eq"].get(sym)
        if self.ok and info:
            try:
                b = upstox.daily_bars(info["key"], to_date)
                if len(b) > 60:
                    self.bars_from["Upstox"] += 1
                    return b
            except Exception as e:                   # noqa: BLE001
                self._off(e)
        b = yahoo_daily(sym)
        self.bars_from["Yahoo"] += 1
        return b


def yahoo_quotes(symbols):
    """Fallback quotes from Yahoo's spark meta: price, volume, previous close (20 stocks a request)."""
    out = {}
    for i in range(0, len(symbols), 20):
        part = symbols[i:i + 20]
        try:
            doc = market.yahoo_json("/v7/finance/spark?symbols=%s&range=5d&interval=1d"
                                    % ",".join(market.yahoo_symbol(s) for s in part))
        except Exception:                            # noqa: BLE001
            continue
        for r in (doc.get("spark") or {}).get("result") or []:
            resp = (r.get("response") or [{}])[0]
            meta = resp.get("meta") or {}
            closes = [c for c in ((resp.get("indicators") or {}).get("quote") or [{}])[0].get("close") or [] if c]
            if meta.get("regularMarketPrice"):
                out[r["symbol"]] = {"price": meta["regularMarketPrice"], "volume": meta.get("regularMarketVolume") or 0,
                                    "prev_close": closes[-2] if len(closes) >= 2 else None,
                                    "high": meta.get("regularMarketDayHigh"), "low": meta.get("regularMarketDayLow"),
                                    "open": None}
        time.sleep(0.3)
    return out


# ---------------------------------------------------------------- indicators

def sma(vals, n):
    out, s = [None] * len(vals), 0.0
    for i, v in enumerate(vals):
        s += v
        if i >= n:
            s -= vals[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema(vals, n):
    out, k = [None] * len(vals), 2.0 / (n + 1)
    if len(vals) < n:
        return out
    e = sum(vals[:n]) / n
    out[n - 1] = e
    for i in range(n, len(vals)):
        e = vals[i] * k + e * (1 - k)
        out[i] = e
    return out


def wilder(vals, n):
    out = [None] * len(vals)
    if len(vals) <= n:
        return out
    a = sum(vals[1:n + 1]) / n
    out[n] = a
    for i in range(n + 1, len(vals)):
        a = (a * (n - 1) + vals[i]) / n
        out[i] = a
    return out


def rsi(closes, n=14):
    gains = [0.0] + [max(closes[i] - closes[i - 1], 0) for i in range(1, len(closes))]
    losses = [0.0] + [max(closes[i - 1] - closes[i], 0) for i in range(1, len(closes))]
    g, lo = wilder(gains, n), wilder(losses, n)
    return [None if g[i] is None else (100.0 if lo[i] == 0 else 100 - 100 / (1 + g[i] / lo[i]))
            for i in range(len(closes))]


def series(bars):
    """Every indicator the rules read, as lists aligned with the bars."""
    o, h, l, c, v = ([b[k] for b in bars] for k in "ohlcv")
    tr = [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]
    vprev = [None] + sma(v, 20)[:-1]                  # average volume of the 20 sessions before
    S = {"d": [b["d"] for b in bars], "o": o, "h": h, "l": l, "c": c, "v": v,
         "sma20": sma(c, 20), "sma50": sma(c, 50), "sma200": sma(c, 200), "ema20": ema(c, 20),
         "rsi": rsi(c), "atr": wilder(tr, 14), "vavg": vprev,
         "turn": [c[i] * v[i] for i in range(len(c))]}
    S["piv_hi"] = [j for j in range(PIVOT, len(h) - PIVOT) if h[j] == max(h[j - PIVOT:j + PIVOT + 1])]
    S["piv_lo"] = [j for j in range(PIVOT, len(l) - PIVOT) if l[j] == min(l[j - PIVOT:j + PIVOT + 1])]
    return S


def hv20(S):
    """Realised volatility of the last 20 sessions, % a year (to compare with an option's IV)."""
    c = S["c"][-21:]
    rets = [math.log(c[j] / c[j - 1]) for j in range(1, len(c))]
    if len(rets) < 10:
        return None
    m = sum(rets) / len(rets)
    return round(math.sqrt(sum((x - m) ** 2 for x in rets) / (len(rets) - 1)) * math.sqrt(252) * 100, 1)


def levels_at(S, i):
    """Support/resistance zones known at bar i (only swing points confirmed by then):
    [(price, touches)] sorted by price. Points within half an ATR of each other are one zone."""
    atr = S["atr"][i]
    if not atr:
        return []
    lo_j = i - LOOKBACK
    pts = sorted([S["h"][j] for j in S["piv_hi"] if lo_j <= j <= i - PIVOT] +
                 [S["l"][j] for j in S["piv_lo"] if lo_j <= j <= i - PIVOT])
    zones, cur = [], []
    for p in pts:
        if cur and p - cur[-1] > 0.5 * atr:
            zones.append(cur)
            cur = []
        cur.append(p)
    if cur:
        zones.append(cur)
    return [(sum(z) / len(z), len(z)) for z in zones]


def nearest(levels, price, above, min_touches=2):
    pick = [(p, t) for p, t in levels if t >= min_touches and ((p > price) if above else (p < price))]
    if not pick:
        return None
    return min(pick, key=lambda x: abs(x[0] - price))


# ---------------------------------------------------------------- the rules

def _target(levels, entry, risk, side, cfg):
    """The first level at least min R:R away, else target_r x risk."""
    need = cfg["min_reward_risk"] * risk
    if side == "long":
        lv = sorted(p for p, t in levels if t >= 2 and p >= entry + need)
        return (round(lv[0], 2), "next resistance") if lv else (up(entry + cfg["target_r"] * risk), "%gR" % cfg["target_r"])
    lv = sorted((p for p, t in levels if t >= 2 and p <= entry - need), reverse=True)
    return (round(lv[0], 2), "next support") if lv else (down(entry - cfg["target_r"] * risk), "%gR" % cfg["target_r"])


def _plan(kind, side, entry, stop, levels, atr, cfg, why, level=None):
    if abs(entry - stop) < atr:                       # inside one day's normal range: widen to 1 ATR
        stop = down(entry - atr) if side == "long" else up(entry + atr)
    risk = abs(entry - stop)
    if risk > 3 * atr or risk / entry > 0.12:
        return None
    target, tlabel = _target(levels, entry, risk, side, cfg)
    rr = abs(target - entry) / risk
    if rr < cfg["min_reward_risk"]:
        return None
    return {"kind": kind, "side": side, "entry": round(entry, 2), "stop": round(stop, 2), "target": target,
            "target_label": tlabel, "risk": round(risk, 2), "rr": round(rr, 2), "level": level, "why": why}


def trend(S, i, side):
    c, s50, s200 = S["c"][i], S["sma50"][i], S["sma200"][i]
    rising = S["sma50"][i - 10] is not None and s50 > S["sma50"][i - 10]
    pts = [c > s50, s50 > s200, rising, c > s200]
    if side == "short":
        pts = [not x for x in pts]
    return sum(pts) / 4.0


def detect(S, i, cfg, fo=False):
    """Setups that fired on bar i, each with its plan. Long ones for every stock; short ones only if fo."""
    if i < 210 or S["sma200"][i] is None or not S["atr"][i] or not S["vavg"][i]:
        return []
    o, h, l, c, v = (S[k][i] for k in "ohlcv")
    atr, ema20, s50, s200, r = S["atr"][i], S["ema20"][i], S["sma50"][i], S["sma200"][i], S["rsi"][i]
    vr = v / S["vavg"][i] if S["vavg"][i] else 0
    rng = (h - l) or TICK
    pos = (c - l) / rng                               # where it closed in the day's range
    hi52 = max(S["h"][max(0, i - LOOKBACK):i])
    lo52 = min(S["l"][max(0, i - LOOKBACK):i])
    lv = levels_at(S, i)
    pc = S["c"][i - 1]
    out = []
    up_tr, dn_tr = trend(S, i, "long"), trend(S, i, "short")
    long_entry, short_entry = up(h) + TICK, down(l) - TICK

    # Bullish
    res = [(p, t) for p, t in lv if t >= 2 and pc <= p < c]
    if c > s200 and vr >= 1.5 and pos >= 0.7 and (res or c > hi52):
        lvl = max(res)[0] if res else hi52
        stop = max(min(lvl - 0.5 * atr, long_entry - atr), long_entry - 2.5 * atr)
        p = _plan("breakout", "long", long_entry, down(stop), lv, atr, cfg,
                  ["closed above %s %.2f on %.1fx volume" % ("its 52-week high" if not res else
                                                             "resistance (%d touches)" % max(res)[1], lvl, vr)], lvl)
        if p:
            out.append(p)
    if up_tr >= 0.75 and 40 <= r <= 60 and c > o and c > pc:
        ma = min((x for x in (ema20, s50) if abs(min(S["l"][i - 2:i + 1]) - x) <= 0.5 * atr), default=None,
                 key=lambda x: abs(min(S["l"][i - 2:i + 1]) - x))
        if ma is not None:
            stop = min(S["l"][i - 4:i + 1]) - 0.25 * atr
            p = _plan("pullback", "long", long_entry, down(stop), lv, atr, cfg,
                      ["uptrend, pulled back to the %s %.2f and closed up" % ("20-day EMA" if ma == ema20 else "50-day average", ma)], ma)
            if p:
                out.append(p)
    sup = nearest(lv, c + 0.5 * atr, above=False)
    if (c > s200 and up_tr >= 0.5 and sup and l <= sup[0] + 0.25 * atr and c >= sup[0] + 0.25 * atr
            and c > o and pos >= 0.6 and r < 55):
        p = _plan("support bounce", "long", long_entry, down(sup[0] - 0.5 * atr), lv, atr, cfg,
                  ["bounced off support %.2f (%d touches) above the 200-day average" % sup], sup[0])
        if p:
            out.append(p)

    # Breakdowns (F&O only)
    if fo:
        brk = [(p, t) for p, t in lv if t >= 2 and c < p <= pc]
        if c < s200 and vr >= 1.5 and pos <= 0.3 and (brk or c < lo52):
            lvl = min(brk)[0] if brk else lo52
            stop = min(max(lvl + 0.5 * atr, short_entry + atr), short_entry + 2.5 * atr)
            p = _plan("breakdown", "short", short_entry, up(stop), lv, atr, cfg,
                      ["closed below %s %.2f on %.1fx volume" % ("its 52-week low" if not brk else
                                                                 "support (%d touches)" % min(brk)[1], lvl, vr)], lvl)
            if p:
                out.append(p)
        if dn_tr >= 0.75 and 40 <= r <= 60 and c < o and c < pc:
            hi3 = max(S["h"][i - 2:i + 1])
            ma = min((x for x in (ema20, s50) if abs(hi3 - x) <= 0.5 * atr), default=None, key=lambda x: abs(hi3 - x))
            if ma is not None:
                stop = max(S["h"][i - 4:i + 1]) + 0.25 * atr
                p = _plan("failed rally", "short", short_entry, up(stop), lv, atr, cfg,
                          ["downtrend, rallied into the %s %.2f and closed down" % ("20-day EMA" if ma == ema20 else "50-day average", ma)], ma)
                if p:
                    out.append(p)
    return out


def bottom(S, i, cfg):
    """Well off the high, close to support: a watch with a buy zone; a plan once it turns up."""
    if i < 210 or not S["atr"][i] or S["rsi"][i] is None:
        return None
    c, atr, r = S["c"][i], S["atr"][i], S["rsi"][i]
    hi = max(S["h"][max(0, i - LOOKBACK):i + 1])
    dd = 1 - c / hi
    if dd < 0.20:
        return None
    lv = levels_at(S, i)
    win = S["l"][max(0, i - LOOKBACK):i + 1]
    lo52 = min(win)
    lo52_age = len(win) - 1 - (len(win) - 1 - win[::-1].index(lo52))   # sessions since the 52-week low
    lows10 = min(S["l"][i - 10:i + 1])
    # the highest support at or just under the price, within 3 ATR: a zone touched twice, or the
    # 52-week low if it was set 15+ sessions ago (a fresh low is a fall still going, not a floor)
    near = [(p, t) for p, t in lv if t >= 2 and p <= c + 0.5 * atr and c - p <= 3 * atr]
    if lo52_age >= 15 and c - lo52 <= 3 * atr:
        near.append((lo52, 1))
    if not near:
        return None
    s, touches = max(near)
    if min(S["l"][i - 4:i + 1]) < s - 0.5 * atr:      # broke under it this week: not holding
        return None
    turned = (c > max(S["c"][i - 10:i]) and c > S["ema20"][i] and lows10 >= s - 0.75 * atr)
    if not turned and c - s > 1.5 * atr:
        return None
    # bullish divergence: the last two swing lows, price lower, RSI higher
    pl = [j for j in S["piv_lo"] if i - 60 <= j <= i - PIVOT]
    div = len(pl) >= 2 and S["l"][pl[-1]] < S["l"][pl[-2]] and (S["rsi"][pl[-1]] or 0) > (S["rsi"][pl[-2]] or 100)
    if not turned and r > 40 and not div:
        return None
    out = {"kind": "turning up" if turned else "on support", "support": round(s, 2), "touches": touches,
           "zone": [down(s - 0.25 * atr), up(s + 0.5 * atr)], "invalidation": down(s - atr),
           "drawdown_pct": round(dd * 100, 1), "rsi": round(r, 1), "divergence": div,
           "why": ["%.0f%% below its 52-week high" % (dd * 100),
                   "%s %.2f%s" % ("52-week low" if touches == 1 else "support", s,
                                  "" if touches == 1 else " (%d touches)" % touches)]}
    if div:
        out["why"].append("RSI made a higher low while price made a lower low")
    if turned:
        p = _plan("bottom reversal", "long", up(S["h"][i]) + TICK, down(lows10 - 0.25 * atr), lv, atr, cfg,
                  ["closed above its 10-day high and the 20-day EMA after holding support"], s)
        if p:
            out["plan"] = p
    return out


# ---------------------------------------------------------------- odds: replays of the stock's own days

def day_moves(S, n=LOOKBACK):
    c = S["c"]
    return [(S["o"][j] / c[j - 1], S["h"][j] / c[j - 1], S["l"][j] / c[j - 1], c[j] / c[j - 1])
            for j in range(max(1, len(c) - n), len(c))]


def simulate(moves, plan, horizon, n, seed):
    """Replays of up to `horizon` sessions after the entry fills, each a random draw of one of the
    stock's last 250 days. A gap through the stop fills at the open (worse than 1R); a day that
    touches both counts as the stop."""
    rnd = random.Random(seed)
    e, s, t = plan["entry"], plan["stop"], plan["target"]
    long_ = plan["side"] == "long"
    risk = abs(e - s)
    m = len(moves)
    hit_t = hit_s = 0
    total_r, days_t = 0.0, []
    for _ in range(n):
        p, done = e, None
        for d in range(1, horizon + 1):
            mo, mh, ml, mc = moves[rnd.randrange(m)]
            o, hh, ll = p * mo, p * mh, p * ml
            if long_:
                if o <= s:
                    done = (o, "s")
                elif o >= t:
                    done = (o, "t")
                elif ll <= s:
                    done = (s, "s")
                elif hh >= t:
                    done = (t, "t")
            else:
                if o >= s:
                    done = (o, "s")
                elif o <= t:
                    done = (o, "t")
                elif hh >= s:
                    done = (s, "s")
                elif ll <= t:
                    done = (t, "t")
            if done:
                break
            p *= mc
        x, kind = done or (p, "n")
        total_r += ((x - e) if long_ else (e - x)) / risk
        if kind == "t":
            hit_t += 1
            days_t.append(d)
        elif kind == "s":
            hit_s += 1
    days_t.sort()
    return {"p_target": round(hit_t / n, 3), "p_stop": round(hit_s / n, 3), "p_time": round(1 - (hit_t + hit_s) / n, 3),
            "avg_R": round(total_r / n, 2), "days_to_target": days_t[len(days_t) // 2] if days_t else None,
            "n": n, "horizon": horizon}


def outcome(S, i, plan, cfg):
    """What the plan made of the real days after bar i: (result, R, days) or None if it never filled."""
    e, s, t, long_ = plan["entry"], plan["stop"], plan["target"], plan["side"] == "long"
    risk, n = abs(e - s), len(S["c"])
    fill = None
    for j in range(i + 1, min(n, i + 1 + cfg["entry_valid_days"])):
        if (long_ and S["h"][j] >= e) or (not long_ and S["l"][j] <= e):
            fill = j
            break
    if fill is None:
        return None
    for j in range(fill, min(n, fill + cfg["horizon_days"])):
        o, hh, ll = S["o"][j], S["h"][j], S["l"][j]
        if j > fill and ((long_ and o <= s) or (not long_ and o >= s)):
            return "stop", ((o - e) if long_ else (e - o)) / risk, j - fill + 1
        if (long_ and ll <= s) or (not long_ and hh >= s):
            return "stop", -1.0, j - fill + 1
        if (long_ and hh >= t) or (not long_ and ll <= t):
            return "target", abs(t - e) / risk, j - fill + 1
    if fill + cfg["horizon_days"] > n:
        return None                                  # still open: not a result yet
    x = S["c"][fill + cfg["horizon_days"] - 1]
    return "time", ((x - e) if long_ else (e - x)) / risk, cfg["horizon_days"]


def history(S, kind, cfg, fo):
    """The same rule on the stock's own past: every time it fired (no overlaps), what happened."""
    res = {"fired": 0, "target": 0, "stop": 0, "time": 0, "sumR": 0.0}
    i = 210
    end = len(S["c"]) - 2
    while i < end:
        p = next((x for x in detect(S, i, cfg, fo) if x["kind"] == kind), None)
        if not p:
            i += 1
            continue
        o = outcome(S, i, p, cfg)
        if o:
            res["fired"] += 1
            res[o[0]] += 1
            res["sumR"] += o[1]
            i += o[2] + 1
        else:
            i += 1
    res["avg_R"] = round(res.pop("sumR") / res["fired"], 2) if res["fired"] else None
    return res


# ---------------------------------------------------------------- fundamentals

def rank_pct(sorted_vals, x):
    """Share of the values below x, ties counting half (0 to 1)."""
    lo, hi = bisect.bisect_left(sorted_vals, x), bisect.bisect_right(sorted_vals, x)
    return (lo + 0.5 * (hi - lo)) / len(sorted_vals)


def fund_score(funds, symbols):
    """0-100 against the other liquid stocks: ROE, ROCE, profit and revenue growth, P/E against
    its sector (lower is better, a loss is worst), and shareholding change (promoters and institutions)."""
    def metric(f):
        pe, pes = f.get("pe"), f.get("pe_sector")
        val = None
        if pe is not None:
            val = -99.0 if pe <= 0 else (-(pe / pes) if pes and pes > 0 else -pe / 25.0)
        inst = [f.get("hold_%s_chg" % k) for k in ("fii", "mutual_funds", "other_dii")]
        inst = [x for x in inst if x is not None]
        hold = None
        if f.get("hold_promoters_chg") is not None or inst:
            hold = (f.get("hold_promoters_chg") or 0) + 0.5 * sum(inst)
        return {"roe": f.get("roe"), "roce": f.get("roce"), "profit": f.get("net_profit_y_chg"),
                "revenue": f.get("revenue_y_chg"), "value": val, "hold": hold}
    W = {"roe": .2, "roce": .2, "profit": .2, "revenue": .15, "value": .15, "hold": .1}
    raw = {s: metric(funds[s]) for s in symbols if s in funds}
    pct = {}
    for k in W:
        vals = sorted(m[k] for m in raw.values() if m[k] is not None)
        if not vals:
            continue
        for s, m in raw.items():
            if m[k] is not None:
                pct.setdefault(s, {})[k] = rank_pct(vals, m[k])
    out = {}
    for s, comps in pct.items():
        w = sum(W[k] for k in comps)
        if w >= 0.5:                                  # at least half the weight known
            out[s] = round(100 * sum(W[k] * comps[k] for k in comps) / w)
    return out


def fund_notes(f):
    if not f:
        return []
    out = []
    if f.get("roe") is not None:
        out.append("ROE %.1f%%%s" % (f["roe"], " (sector %.1f%%)" % f["roe_sector"] if f.get("roe_sector") is not None else ""))
    if f.get("roce") is not None:
        out.append("ROCE %.1f%%" % f["roce"])
    if f.get("pe") is not None:
        out.append("P/E %.1f%s" % (f["pe"], " (sector %.1f)" % f["pe_sector"] if f.get("pe_sector") else ""))
    if f.get("net_profit_y_chg") is not None:
        out.append("profit %+.0f%% in %s" % (f["net_profit_y_chg"], f.get("net_profit_y_period") or "the last year"))
    if f.get("revenue_y_chg") is not None:
        out.append("revenue %+.0f%%" % f["revenue_y_chg"])
    if f.get("hold_promoters") is not None:
        out.append("promoters %.1f%%%s" % (f["hold_promoters"], " (%+.1f)" % f["hold_promoters_chg"]
                                           if f.get("hold_promoters_chg") else ""))
    return out


def refresh_fundamentals(data, symbols, limit=None):
    """Fetch the stalest fundamentals first (4 requests a stock); keep the rest."""
    cfg, _ = config()
    doc = read_json(FUNDS, {"stocks": {}})
    stocks = doc["stocks"]
    today = datetime.date.today()
    stale = [s for s in symbols if s in data.inst["eq"] and
             (s not in stocks or (today - datetime.date.fromisoformat(stocks[s].get("as_of", "2000-01-01"))).days
              >= cfg["fundamentals_days"])]
    stale.sort(key=lambda s: stocks.get(s, {}).get("as_of", ""))
    if limit:
        stale = stale[:limit]
    if not stale or not data.ok:
        return doc, 0
    log("fundamentals: %d stocks to refresh" % len(stale))
    got = 0

    def one(sym):
        f = upstox.fundamentals(data.inst["eq"][sym]["isin"])
        f["as_of"] = today.isoformat()
        return sym, f

    with concurrent.futures.ThreadPoolExecutor(4) as ex:
        for fut in concurrent.futures.as_completed([ex.submit(one, s) for s in stale]):
            try:
                sym, f = fut.result()
                stocks[sym] = f
                got += 1
            except upstox.TokenError as e:
                data._off(e)
            except Exception as e:                   # noqa: BLE001
                data.errors.append("fundamentals: %s" % e)
    doc["updated"] = today.isoformat()
    write_json(FUNDS, doc, indent=None)
    log("fundamentals: %d refreshed, %d on file" % (got, len(stocks)))
    return doc, got


# ---------------------------------------------------------------- track record

def sessions_between(d0, d1):
    """Trading days after d0 up to and including d1 (weekends and config holidays skipped)."""
    n, d = 0, d0
    while d < d1:
        d += datetime.timedelta(days=1)
        if market.trading_day(d)[0]:
            n += 1
    return n


def update_record(rec, day, o, h, l, c, cfg):
    """Move one tracked plan on by a day (or the day so far): entry, stop, target, time."""
    if rec["status"] not in ("waiting for entry", "entered"):
        return
    long_ = rec["side"] == "long"
    e, s, t = rec["entry"], rec["stop"], rec["target"]
    created = datetime.date.fromisoformat(rec["created"])
    if rec["status"] == "waiting for entry":
        if day <= created:
            return
        if (long_ and h >= e) or (not long_ and l <= e):
            gap = o is not None and ((long_ and o > e) or (not long_ and o < e))
            rec.update(status="entered", entered=day.isoformat(), fill=round(o if gap else e, 2))
        elif sessions_between(created, day) >= cfg["entry_valid_days"]:
            rec.update(status="entry missed", closed=day.isoformat())
            return
        else:
            return
    fill = rec.get("fill", e)
    risk = abs(e - s)
    entered = datetime.date.fromisoformat(rec["entered"])
    x = None
    if (long_ and l <= s) or (not long_ and h >= s):
        gap = o is not None and ((long_ and o <= s) or (not long_ and o >= s)) and day > entered
        x, status = (o if gap else s), "stop hit"
    elif (long_ and h >= t) or (not long_ and l <= t):
        x, status = t, "target hit"
    elif sessions_between(entered, day) + 1 >= cfg["horizon_days"] and c is not None:
        x, status = c, "closed at day %d" % cfg["horizon_days"]
    if x is not None:
        rec.update(status=status, closed=day.isoformat(), exit=round(x, 2),
                   result_R=round(((x - fill) if long_ else (fill - x)) / risk, 2),
                   result_pct=round(((x - fill) if long_ else (fill - x)) / fill * 100, 2))


def page_list(rows, show):
    """Every plan that cleared the gate, then the top of the rest as a watchlist."""
    return [r for r in rows if r.get("qualified")] + [r for r in rows if not r.get("qualified")][:2 * show]


def add_plan_record(records, sym, name, p, session, score, price, prev_close=None):
    """One record per stock and signal session; False if it is already there."""
    if any(r["symbol"] == sym and r["created"] == session for r in records):
        return False
    records.append({"id": "%s-%s" % (session, sym), "created": session, "symbol": sym, "name": name,
                    "side": p["side"], "kind": p["kind"], "entry": p["entry"], "stop": p["stop"], "target": p["target"],
                    "rr": p["rr"], "est_days": p.get("est_days"), "p_target": (p.get("odds") or {}).get("p_target"),
                    "score": score, "status": "waiting for entry", "price_at_signal": price, "last_price": price,
                    "last_close": prev_close})
    return True


def track_options(records, opts, data, now_utc, errors, full_cfg=None):
    """The option record: new trades from opts, every open one moved on; saved, summarised for the page."""
    if not data.ok:
        return read_json(OPT_LOG, None) and options.summary(read_json(OPT_LOG, []))
    rows = read_json(OPT_LOG, [])
    options.track(rows, opts, records, data.inst, now_utc, errors, full_cfg)
    write_json(OPT_LOG, rows)
    s = options.summary(rows)
    log("options record: %d tracked, %d open, %d closed" % (s["stats"]["tracked"], s["stats"]["open"], s["stats"]["closed"]))
    return s


def attach_results_news(picks, data, errors):
    """Each pick's news (Upstox keeps 7 days), plus every results headline seen before: Upstox's
    fundamentals can lag a results announcement by weeks, so a remembered "Q2 results" headline is
    what tells the options screen the results are already out."""
    seen = read_json(RESULTS_SEEN, {})
    eq = data.inst.get("eq") or {}
    keys = {eq[pk["symbol"]]["key"]: pk for pk in picks if pk["symbol"] in eq}
    try:
        nws = upstox.news(list(keys)) if keys else {}
    except Exception as e:                           # noqa: BLE001
        errors.append("Upstox news for the options screen: %s" % e)
        nws = {}
    for key, pk in keys.items():
        items = [{"title": n["title"], "time_ms": n.get("time_ms")} for n in nws.get(key, [])]
        for n in items:
            if n["title"] and options.RESULT_WORDS.search(n["title"]) and re.search(r"\bQ[1-4]\b|quarter", n["title"], re.I):
                seen.setdefault(pk["symbol"], {})[n["title"][:160]] = n.get("time_ms")
        pk["news"] = items + [{"title": t, "time_ms": ms} for t, ms in (seen.get(pk["symbol"]) or {}).items()]
    for sym in list(seen):                           # keep a year of headlines
        seen[sym] = dict(sorted(seen[sym].items(), key=lambda kv: kv[1] or 0)[-12:])
    write_json(RESULTS_SEEN, seen)


def run_options(picks, data, now_utc, full_cfg, errors, nifty_trend, records, session):
    """Screen the picks' options, put each qualifying card's stock plan in the stock record (the option
    follows its entry and exit), and move the option record on. (cards, record summary)."""
    iv_hist = read_json(IV_LOG, {})
    attach_results_news(picks, data, errors)
    opts = options.screen(picks, data.inst, now_utc, full_cfg, errors, nifty_trend, iv_hist)
    by_sym = {pk["symbol"]: pk for pk in picks}
    for o in opts["calls"] + opts["puts"]:
        pk = by_sym.get(o["symbol"])
        if o.get("qualified") and pk:
            add_plan_record(records, pk["symbol"], pk["name"], pk["plan"], pk.get("session") or session,
                            pk["score"], pk["price"])
    write_json(LOG, records)
    n_q = sum(1 for o in opts["calls"] + opts["puts"] if o.get("qualified"))
    log("options: %d of %d F&O plans have a trade that clears every check" % (n_q, len(picks)))
    return opts, track_options(records, opts, data, now_utc, errors, full_cfg)


def record_stats(records):
    done = [r for r in records if r.get("result_R") is not None]
    st = {"tracked": len(records), "open": sum(1 for r in records if r["status"] in ("waiting for entry", "entered")),
          "closed": len(done), "missed": sum(1 for r in records if r["status"] == "entry missed"),
          "targets": sum(1 for r in done if r["status"] == "target hit"),
          "stops": sum(1 for r in done if r["status"] == "stop hit")}
    st["avg_R"] = round(sum(r["result_R"] for r in done) / len(done), 2) if done else None
    st["win_rate"] = round(sum(1 for r in done if r["result_R"] > 0) / len(done), 3) if done else None
    return st


# ---------------------------------------------------------------- the end-of-day scan

def size_long(plan, sym, cfg, sk):
    bcfg = {"budget": cfg["budget"], "max_loss_per_trade_usd": cfg["max_loss_per_trade"],
            "max_position_pct": cfg["max_position_pct"], "max_order_usd": cfg["budget"],
            "cash_buffer_pct": cfg["cash_buffer_pct"], "min_order_usd": 500, "min_reward_risk": cfg["min_reward_risk"]}
    s = sk["budget"].size_trade({"symbol": sym, "side": "buy", "entry": plan["entry"], "stop": plan["stop"],
                                 "target": plan["target"], "setup": plan["kind"]}, bcfg)
    out = {"qty": s["qty"], "bound_by": s["bound_by"], "cost": s["cost"], "max_loss": s["max_loss"],
           "refusal": s["refusal"]}
    if s["qty"]:
        out["reward"] = round(s["qty"] * (plan["target"] - plan["entry"]), 2)
    return out


def lot_info(plan, lot):
    if not lot:
        return None
    return {"lot": lot, "notional": round(lot * plan["entry"]),
            "move_to_target": round(lot * abs(plan["entry"] - plan["target"])),
            "move_to_stop": round(lot * abs(plan["stop"] - plan["entry"]))}


def stage_eod(now_utc, force=False):
    t0 = time.time()
    cfg, full_cfg = config()
    market.load_holidays(full_cfg.get("holidays"))
    errors = []
    data = Data(errors)
    sk = market.skills()
    ist = market.to_ist(now_utc)
    today = ist.date()
    uni = universe()
    names = dict(uni)
    symbols = [s for s, _ in uni]

    # 1. today's quotes for every NSE stock, then the ones worth a closer look
    quotes, qsrc = data.quotes(symbols)
    log("quotes: %d of %d from %s" % (len(quotes), len(symbols), qsrc))
    cands = [s for s in symbols if (quotes.get(s) or {}).get("price", 0) >= cfg["min_price"]
             and (quotes[s].get("volume") or 0) >= 20000]
    # 2. daily bars (3 years) for those. Only completed sessions: before 15:30 today's bar is
    # still forming, so the scan is of the last close; after it, today's bar comes from the
    # quote if the history does not have it yet
    session_open = market.session_today(now_utc)[0] if not force else True
    closed = ist.time() >= market.CLOSE
    bars = {}
    to_date = today if closed else today - datetime.timedelta(days=1)

    def load(sym):
        b = [x for x in data.bars(sym, to_date) if closed or x["d"] < today.isoformat()]
        q = quotes.get(sym) or {}
        if session_open and closed and q.get("open") and (not b or b[-1]["d"] < today.isoformat()):
            b.append({"d": today.isoformat(), "o": q["open"], "h": max(q.get("high") or q["price"], q["price"]),
                      "l": min(q.get("low") or q["price"], q["price"]), "c": q["price"], "v": q.get("volume") or 0})
        return sym, b

    log("bars: daily history for %d stocks" % len(cands))
    with concurrent.futures.ThreadPoolExecutor(4) as ex:
        for fut in concurrent.futures.as_completed([ex.submit(load, s) for s in cands]):
            try:
                sym, b = fut.result()
                if len(b) >= 220:
                    bars[sym] = b
            except Exception as e:                   # noqa: BLE001
                errors.append("bars: %s" % e)
    log("bars: %d with a year or more (Upstox %d, Yahoo %d)" % (len(bars), data.bars_from["Upstox"], data.bars_from["Yahoo"]))

    # 3. liquid: median turnover of the last 20 sessions
    S_all, liquid = {}, []
    for sym, b in bars.items():
        S = series(b)
        turn = sorted(S["turn"][-20:])
        if S["c"][-1] >= cfg["min_price"] and turn[len(turn) // 2] >= cfg["min_turnover_cr"] * 1e7:
            S_all[sym] = S
            liquid.append(sym)
    session = max((S["d"][-1] for S in S_all.values()), default=None)
    S_all = {s: S for s, S in S_all.items() if S["d"][-1] == session}   # stale charts out
    liquid = sorted(S_all)
    fo = data.inst.get("fo") or {}
    log("liquid: %d (turnover >= %s cr), %d with F&O; last session %s" % (len(liquid), cfg["min_turnover_cr"],
                                                                         sum(1 for s in liquid if s in fo), session))

    # 4. fundamentals: fill the gaps a few hundred at a time; the weekly run refreshes them all
    fdoc, _ = refresh_fundamentals(data, liquid, limit=300)
    funds = fdoc.get("stocks", {})
    fscore = fund_score(funds, liquid)

    # 5. relative strength against the Nifty 50 over 63 sessions
    try:
        nb = upstox.daily_bars("NSE_INDEX|Nifty 50", to_date, years=1) if data.ok else []
    except Exception:                                # noqa: BLE001
        nb = []
    if len(nb) < 70:
        nb = yahoo_daily("^NSEI")
    n_ret = nb[-1]["c"] / nb[-64]["c"] - 1 if len(nb) > 64 else 0
    rs = {s: S["c"][-1] / S["c"][-64] - 1 - n_ret for s, S in S_all.items() if len(S["c"]) > 64}
    rs_sorted = sorted(rs.values())
    rs_pct = {s: rank_pct(rs_sorted, v) for s, v in rs.items()}
    nifty = {"close": nb[-1]["c"] if nb else None, "ret_63": round(n_ret * 100, 1)}
    if len(nb) > 200:
        NS = series(nb)
        nifty["trend"] = ("up" if trend(NS, len(nb) - 1, "long") >= 0.75 else
                          "down" if trend(NS, len(nb) - 1, "short") >= 0.75 else "mixed")

    # 6. the rules on today's bar
    cands = {"long": [], "short": [], "bottom": []}
    rnd_seed = int(today.strftime("%Y%m%d"))
    for sym in liquid:
        S = S_all[sym]
        i = len(S["c"]) - 1
        for p in detect(S, i, cfg, fo=sym in fo):
            cands[p["side"]].append((sym, p))
        b = bottom(S, i, cfg)
        if b:
            cands["bottom"].append((sym, b))
    log("setups: %d bullish, %d breakdowns (F&O), %d bottoms" % (len(cands["long"]), len(cands["short"]), len(cands["bottom"])))

    def row(sym, p, side_list):
        S = S_all[sym]
        i = len(S["c"]) - 1
        q = quotes.get(sym) or {}
        prev = S["c"][i - 1]
        f = funds.get(sym)
        lv = levels_at(S, i)
        sup, res = nearest(lv, S["c"][i], above=False), nearest(lv, S["c"][i], above=True)
        r = {"symbol": sym, "name": names.get(sym, ""), "price": round(S["c"][i], 2), "prev_close": round(prev, 2),
             "chg_pct": round((S["c"][i] / prev - 1) * 100, 2), "session": S["d"][i],
             "rsi": round(S["rsi"][i], 1), "atr": round(S["atr"][i], 2),
             "vol_ratio": round(S["v"][i] / S["vavg"][i], 2) if S["vavg"][i] else None,
             "sma50": round(S["sma50"][i], 2), "sma200": round(S["sma200"][i], 2),
             "support": round(sup[0], 2) if sup else None, "resistance": round(res[0], 2) if res else None,
             "rs_pct": round(rs_pct.get(sym, 0.5) * 100), "fund": fscore.get(sym), "fund_notes": fund_notes(f),
             "fo_lot": fo.get(sym), "turnover_cr": round(sorted(S["turn"][-20:])[10] / 1e7, 1),
             "hv20": hv20(S)}
        if p and "entry" in p:
            r["plan"] = p
        return r

    def score_trades(side):
        rows = []
        for sym, p in cands[side]:
            S = S_all[sym]
            p["odds"] = simulate(day_moves(S), p, cfg["horizon_days"], 2000, rnd_seed)
            if p["odds"]["p_target"] < 0.10:           # the target almost never comes first: not a plan
                continue
            r = row(sym, p, side)
            tr = trend(S, len(S["c"]) - 1, side)
            rsv = rs_pct.get(sym, 0.5) if side == "long" else 1 - rs_pct.get(sym, 0.5)
            vol = min((r["vol_ratio"] or 0) / 2.0, 1) if p["kind"] in ("breakout", "breakdown") else 0.5
            edge = (p["odds"]["p_target"] - p["odds"]["p_stop"] + 1) / 2
            r["tech"] = round(100 * (0.25 * tr + 0.25 * rsv + 0.15 * vol + 0.35 * edge))
            fs = r["fund"] if r["fund"] is not None else 50   # not loaded yet: neutral, and the card says n/a
            r["score"] = round(0.5 * r["tech"] + 0.5 * (fs if side == "long" else 100 - fs))
            rows.append(r)
        # one row per stock: its best setup
        best = {}
        for r in sorted(rows, key=lambda x: -x["score"]):
            best.setdefault(r["symbol"], r)
        return sorted(best.values(), key=lambda x: (-x["score"], -x["turnover_cr"]))

    bull, bear = score_trades("long"), score_trades("short")
    bots = []
    for sym, b in cands["bottom"]:
        S = S_all[sym]
        r = row(sym, None, "bottom")
        r["bottom"] = b
        if b.get("plan"):
            b["plan"]["odds"] = simulate(day_moves(S), b["plan"], cfg["horizon_days"], 2000, rnd_seed)
        near = max(0.0, 1 - (S["c"][-1] - b["support"]) / (1.5 * S["atr"][-1]))
        tech = 100 * (0.35 * min(near, 1) + 0.25 * min(max((45 - b["rsi"]) / 25, 0), 1) +
                      0.2 * b["divergence"] + 0.2 * (b["kind"] == "turning up"))
        r["tech"] = round(tech)
        r["score"] = round(0.4 * tech + 0.6 * (r["fund"] if r["fund"] is not None else 50))
        r["quality"] = (r["fund"] or 0) >= 60
        bots.append(r)
    bots.sort(key=lambda x: (-x["score"], -x["turnover_cr"]))

    # 7. full numbers (10,000 replays, the rule's own history) for the top of each list and for every
    # plan that might clear the gate; then the gate, which decides what is recommended
    show, G = cfg["show"], cfg["gate"]

    def plan_of(r):
        return r.get("plan") or (r.get("bottom") or {}).get("plan")

    def maybe(r):                                     # cheap pre-check on the 2,000-replay numbers
        p = plan_of(r)
        return (p and (r.get("turnover_cr") or 0) >= G["min_turnover_cr"] and p["rr"] >= G["min_rr"]
                and p["odds"]["avg_R"] >= G["min_avg_r"] - 0.1 and p["odds"]["p_target"] >= G["min_p_target"] - 0.05)
    shown, seen = [], set()
    # options are screened on their own: every F&O plan with a fair replay edge gets the full numbers too
    fo_maybe = [r for r in bull + bear + bots if r["symbol"] in fo and plan_of(r)
                and plan_of(r)["odds"]["p_target"] >= 0.28 and plan_of(r)["odds"]["avg_R"] >= 0.05]
    for r in bull[:show] + bear[:show] + bots[:show] + [r for r in bull + bear + bots if maybe(r)] + fo_maybe:
        if id(r) not in seen:
            seen.add(id(r))
            shown.append(r)
    for r in shown:
        S = S_all[r["symbol"]]
        p = plan_of(r)
        if not p:
            continue
        p["odds"] = simulate(day_moves(S), p, cfg["horizon_days"], cfg["replays"], rnd_seed)
        p["history"] = history(S, p["kind"], cfg, r["symbol"] in fo)
        p["est_days"] = p["odds"]["days_to_target"]
        r["checks"], r["qualified"] = gate(r, p, nifty.get("trend"), cfg)
        if p["side"] == "long":
            r["size"] = size_long(p, r["symbol"], cfg, sk)
        else:
            r["lot"] = lot_info(p, r.get("fo_lot"))
    n_q = {k: sum(1 for r in lst if r.get("qualified")) for k, lst in (("bull", bull), ("bear", bear), ("bottoms", bots))}
    log("gate: %d bullish, %d breakdowns, %d bottoms turning up clear every check (of %d checked)" % (
        n_q["bull"], n_q["bear"], n_q["bottoms"], sum(1 for r in shown if plan_of(r))))
    if data.ok:
        try:
            nws = upstox.news([data.inst["eq"][r["symbol"]]["key"] for r in shown if r["symbol"] in data.inst["eq"]])
            for r in shown:
                items = nws.get(data.inst["eq"].get(r["symbol"], {}).get("key"), [])
                r["news"] = [{"title": n["title"], "link": n["link"],
                              "time": market.to_ist(datetime.datetime(1970, 1, 1) + datetime.timedelta(
                                  milliseconds=n["time_ms"])).strftime("%d %b %H:%M") if n.get("time_ms") else None}
                             for n in items[:4]]
        except Exception as e:                       # noqa: BLE001
            errors.append("Upstox news: %s" % e)
    for lst in (bull, bear, bots):
        for k, r in enumerate(lst, 1):
            r["rank"] = k

    # 8. track record: today's bar moves every open plan on; the shown plans join it
    records = read_json(LOG, [])
    for rec in records:
        S = S_all.get(rec["symbol"])
        if S and S["d"][-1] == session:
            update_record(rec, datetime.date.fromisoformat(session), S["o"][-1], S["h"][-1], S["l"][-1], S["c"][-1], cfg)
            rec["last_price"], rec["last_close"] = S["c"][-1], S["c"][-2]
    for r in shown:                                   # only what is recommended is tracked
        p = r.get("plan") or (r.get("bottom") or {}).get("plan")
        if p and r.get("qualified"):
            add_plan_record(records, r["symbol"], r["name"], p, session, r["score"], r["price"], r["prev_close"])
    write_json(LOG, records)
    status = {(rec["symbol"], rec["created"]): rec for rec in records}
    for r in shown:
        rec = status.get((r["symbol"], session))
        if rec:
            r["status"] = rec["status"]

    # 9. levels for the live runs, charts for the page
    lv_doc = {"session": session, "created_ist": ist.strftime("%Y-%m-%d %H:%M"), "stocks": {}}
    for sym, S in S_all.items():
        i = len(S["c"]) - 1
        lv = levels_at(S, i)
        sup, res = nearest(lv, S["c"][i], above=False), nearest(lv, S["c"][i], above=True)
        lv_doc["stocks"][sym] = {"close": S["c"][i], "atr": round(S["atr"][i], 2),
                                 "res": round(max(res[0], 0), 2) if res else None,
                                 "sup": round(sup[0], 2) if sup else None,
                                 "hi52": max(S["h"][-LOOKBACK:]), "lo52": min(S["l"][-LOOKBACK:]),
                                 "vavg": round(S["vavg"][i] or 0), "up": trend(S, i, "long"),
                                 "fo": sym in fo}
    write_json(LEVELS, lv_doc, indent=None)
    charts = {}
    chart_syms = {r["symbol"] for r in shown} | {r["symbol"] for r in records if r["status"] in ("waiting for entry", "entered")}
    for sym in chart_syms:
        S = S_all.get(sym)
        if S:
            charts[sym] = [[S["d"][j], round(S["o"][j], 2), round(S["h"][j], 2), round(S["l"][j], 2), round(S["c"][j], 2)]
                           for j in range(max(0, len(S["c"]) - 130), len(S["c"]))]
    write_json(CHARTS, charts, indent=None)

    # 10. options, screened on their own: every F&O plan with the full numbers (one chain request each),
    # then today's at-the-money IV of every liquid F&O stock for the IV history
    fo_picks, opts, opt_record = [], None, None
    if data.ok:
        has_numbers = lambda rows: [r for r in rows if (plan_of(r) or {}).get("history") is not None]  # noqa: E731
        fo_picks = options.fo_plans([(has_numbers(bull), "bullish"), (has_numbers(bear), "breakdown"),
                                     (has_numbers([b for b in bots if plan_of(b)]), "bottom turning up")],
                                    data.inst, funds)
        opts, opt_record = run_options(fo_picks, data, now_utc, full_cfg, errors, nifty.get("trend"), records, session)
        iv_hist = read_json(IV_LOG, {})
        n_iv = options.record_iv(iv_hist, [s for s in liquid if s in fo], data.inst, today, errors)
        write_json(IV_LOG, iv_hist, indent=None)
        log("IV history: today's at-the-money IV for %d F&O stocks (%d days on file)" % (
            n_iv, max((len(v) for v in iv_hist.values()), default=0)))

    doc = {"stage": "eod", "options_record": opt_record, "fo_plans": fo_picks, "options": opts, "created_ist": ist.strftime("%Y-%m-%d %H:%M"), "session": session,
           "counts": {"universe": len(symbols), "quoted": len(quotes), "with_bars": len(bars), "liquid": len(liquid),
                      "fo": sum(1 for s in liquid if s in fo), "with_fundamentals": len(fscore),
                      "bull": len(bull), "bear": len(bear), "bottoms": len(bots)},
           "sources": {"quotes": qsrc, "bars": data.bars_from, "upstox": data.status},
           "nifty": nifty, "bull": page_list(bull, show), "bear": page_list(bear, show), "bottoms": page_list(bots, show),
           "record": {"stats": record_stats(records), "rows": sorted(records, key=lambda r: r["created"], reverse=True)[:60]},
           "live": None, "config": cfg, "errors": list(dict.fromkeys(errors))[:30],
           "seconds": round(time.time() - t0)}
    write_json(PAGE, doc)
    log("eod: %d bullish, %d breakdowns, %d bottoms; %d tracked (%d open) in %ds" % (
        len(bull), len(bear), len(bots), len(records), doc["record"]["stats"]["open"], doc["seconds"]))
    return doc


# ---------------------------------------------------------------- live: during the session

def stage_live(now_utc):
    cfg, full_cfg = config()
    market.load_holidays(full_cfg.get("holidays"))
    page = read_json(PAGE)
    lv = read_json(LEVELS)
    if not page or not lv:
        log("live: no end-of-day scan yet; running it now")
        return stage_eod(now_utc)
    errors = []
    data = Data(errors)
    ist = market.to_ist(now_utc)
    today = ist.date()
    records = read_json(LOG, [])
    open_syms = {r["symbol"] for r in records if r["status"] in ("waiting for entry", "entered")}
    syms = sorted(set(lv["stocks"]) | open_syms)
    quotes, qsrc = data.quotes(syms)
    log("live: quotes for %d of %d from %s" % (len(quotes), len(syms), qsrc))
    in_session = market.session_today(now_utc)[0] and ist.time() >= market.OPEN

    # every shown row and open plan gets today's price
    for key in ("bull", "bear", "bottoms"):
        for r in page.get(key) or []:
            q = quotes.get(r["symbol"])
            if q and in_session:
                r["live_price"] = q["price"]
                r["live_chg_pct"] = round((q["price"] / r["price"] - 1) * 100, 2) if r["price"] else None
    if in_session:
        for rec in records:
            q = quotes.get(rec["symbol"])
            if q:
                update_record(rec, today, q.get("open"), max(q.get("high") or q["price"], q["price"]),
                              min(q.get("low") or q["price"], q["price"]), None, cfg)
                rec["last_price"] = q["price"]
                if q.get("prev_close"):
                    rec["last_close"] = q["prev_close"]
        write_json(LOG, records)

    # levels being crossed right now (confirm at the close)
    moves = {"breakouts": [], "breakdowns": [], "in_zone": []}
    if in_session:
        elapsed = max(min((ist.hour * 60 + ist.minute - market.OPEN_MIN) / float(market.CLOSE_MIN - market.OPEN_MIN), 1), 0.05)
        zones = {r["symbol"]: r["bottom"] for r in page.get("bottoms") or [] if r.get("bottom")}
        for sym, L in lv["stocks"].items():
            q = quotes.get(sym)
            if not q:
                continue
            p, pace = q["price"], (q.get("volume") or 0) / (L["vavg"] * elapsed) if L["vavg"] else 0
            item = {"symbol": sym, "price": p, "chg_pct": round((p / L["close"] - 1) * 100, 2), "volume_pace": round(pace, 1)}
            lvl = L["res"] if L["res"] and L["res"] < L["hi52"] else L["hi52"]
            if L["up"] >= 0.5 and p > lvl >= L["close"] and pace >= 1.2:
                moves["breakouts"].append(dict(item, level=lvl))
            lvl = L["sup"] if L["sup"] and L["sup"] > L["lo52"] else L["lo52"]
            if L["fo"] and L["up"] <= 0.5 and p < lvl <= L["close"] and pace >= 1.2:
                moves["breakdowns"].append(dict(item, level=lvl))
            z = zones.get(sym)
            if z and z["zone"][0] <= p <= z["zone"][1]:
                moves["in_zone"].append(dict(item, zone=z["zone"], invalidation=z["invalidation"]))
        for k in moves:
            moves[k].sort(key=lambda x: -x["volume_pace"])
            moves[k] = moves[k][:15]
    page["live"] = {"created_ist": ist.strftime("%Y-%m-%d %H:%M"), "in_session": in_session, "quotes": qsrc,
                    "moves": moves}
    if in_session and data.ok and page.get("fo_plans"):
        page["options"], page["options_record"] = run_options(
            page["fo_plans"], data, now_utc, full_cfg, errors, (page.get("nifty") or {}).get("trend"), records,
            page.get("session"))
    elif in_session and data.ok:
        page["options_record"] = track_options(records, page.get("options"), data, now_utc, errors, full_cfg)
    page["record"] = {"stats": record_stats(records),
                      "rows": sorted(records, key=lambda r: r["created"], reverse=True)[:60]}
    status = {(rec["symbol"], rec["created"]): rec["status"] for rec in records}
    for key in ("bull", "bear", "bottoms"):
        for r in page.get(key) or []:
            if (r["symbol"], r.get("session")) in status:
                r["status"] = status[(r["symbol"], r["session"])]
    page["errors"] = list(dict.fromkeys((page.get("errors") or []) + errors))[:30]
    write_json(PAGE, page)
    log("live: %d breaking out, %d breaking down, %d in a bottom's buy zone; %d plans open" % (
        len(moves["breakouts"]), len(moves["breakdowns"]), len(moves["in_zone"]), page["record"]["stats"]["open"]))
    return page


def stage_options(now_utc):
    """The options screen on the last scan's plans, without rescanning (one chain request a stock)."""
    cfg, full_cfg = config()
    page = read_json(PAGE)
    if not page:
        log("options: no swing scan yet; run eod first")
        return None
    errors = []
    data = Data(errors)
    if not data.ok:
        log("options: needs the Upstox token (%s)" % data.status)
        return page
    picks = page.get("fo_plans") or options.fo_plans(
        [([r for r in page.get(k) or [] if (r.get("plan") or (r.get("bottom") or {}).get("plan") or {}).get("history")
           is not None], label)
         for k, label in (("bull", "bullish"), ("bear", "breakdown"), ("bottoms", "bottom turning up"))],
        data.inst, (read_json(FUNDS, {}) or {}).get("stocks"))
    for pk in picks:                                  # plans saved before the record existed carry no session
        if not pk.get("session"):
            pk["session"] = page.get("session")
    page["fo_plans"] = picks
    records = read_json(LOG, [])
    page["options"], page["options_record"] = run_options(
        picks, data, now_utc, full_cfg, errors, (page.get("nifty") or {}).get("trend"), records, page.get("session"))
    page["record"] = {"stats": record_stats(records),
                      "rows": sorted(records, key=lambda r: r["created"], reverse=True)[:60]}
    page["errors"] = list(dict.fromkeys((page.get("errors") or []) + errors))[:30]
    write_json(PAGE, page)
    log("options: %d call and %d put underlyings from %d F&O plans" % (
        len(page["options"]["calls"]), len(page["options"]["puts"]), len(picks)))
    return page


def publish(doc):
    """The page and the Google Sheet (the sheet only when its secret is set)."""
    import dashboard
    dashboard.render_site()
    try:
        import sheets
        msg = sheets.write(doc)
        log("sheet: %s" % msg)
    except Exception as e:                           # noqa: BLE001 - the page is out; the sheet can wait
        log("sheet: not written (%s)" % e)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", choices=("eod", "live", "fundamentals", "options",
                                      "swing-eod", "swing-live", "swing-fundamentals", "swing-options"))
    ap.add_argument("--now", help='pin the clock, India time: "2026-10-27 15:50"')
    ap.add_argument("--force", action="store_true", help="run on a holiday or weekend anyway")
    a = ap.parse_args(argv)
    a.stage = a.stage.replace("swing-", "")
    now_utc = market.parse_now(a.now)
    if a.stage == "fundamentals":
        errors = []
        lv = read_json(LEVELS) or {}
        syms = sorted((lv.get("stocks") or {}).keys())
        if not syms:
            log("fundamentals: no end-of-day scan yet, so no liquid list; run eod first")
            return 1
        refresh_fundamentals(Data(errors), syms)
        for e in errors[:5]:
            log(e)
        return 0
    open_today, why, _ = market.session_today(now_utc)
    if not open_today and not a.force and a.stage == "live":
        log("live: NSE closed today (%s); nothing to update" % why)
        return 0
    if a.stage == "options":
        doc = stage_options(now_utc)
    else:
        doc = stage_eod(now_utc, a.force) if a.stage == "eod" else stage_live(now_utc)
    if doc:
        publish(doc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
