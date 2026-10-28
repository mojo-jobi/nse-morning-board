"""Equity options screen, options first: every liquid F&O stock, its own direction checks, then the
structure (a debit spread by default, a single call or put only when it is cheap) inside your budget.

A rules screen with its numbers, not advice: whether to trade, and what, is the trader's call.

1. Direction (calls for bullish plans and bottoms turning up, puts for breakdowns and failed rallies),
   every check must pass:
     Replay edge      the stock plan's target first in 33%+ of 10,000 replays, expectancy +0.15R+
     Not failing here the same rule has not lost money on this stock (fewer than 3 past trades is
                      no evidence either way)
     Market agrees    a long in a falling Nifty must be stronger than 70% of stocks; a put needs a
                      Nifty that is not rising and a stock weaker than average
     Fundamentals     not fighting it: longs 45+, puts 60 or less (missing counts as neutral)
     No results due   the last quarter's results are out (in Upstox's fundamentals, or a results
                      headline in its news since the quarter end), or its deadline has passed (45
                      days after a quarter end, 60 after March's). Implied volatility usually
                      collapses right after results, which hurts an option buyer

2. Expiry: the nearest monthly one at least 14 days away that still leaves 7 days after the plan's
   estimated exit.

3. Structure, inside the budget (the most a trade can lose = what it costs):
     Debit spread  buy a strike near the money (delta 0.40-0.65), sell one further out, at most at
                   the target. Checks: cost a lot within budget; pay at most half the strikes'
                   width; reward:risk 1.5+ from the plan's stop to its target; break-even inside the
                   target; both legs liquid; at most 25% lost to time decay if the stock stands
                   still to the estimated day; no OI wall before the sold strike.
     Single        a call or put (delta 0.30-0.75) only if it fits the budget and the IV is cheap
                   (at most the stock's realised 20-day volatility, or in the lower half of its own
                   recorded IV once 40+ days of history exist), plus reward:risk 2+, break-even
                   inside the target, at most 25% decay, no OI wall before the target.
   Values at the target and stop: Black-Scholes at each strike's own IV on the estimated day.

4. Exits (the record follows them): take profit at +60% of the cost, cut at -40%, or when the stock
   plan hits its target or stop, or 7 days before expiry, whichever comes first. At most 3 trades
   open (or waiting) at once: a 4th that qualifies is shown, not taken.
"""

import datetime
import math
import re

import market
import upstox

MIN_DTE = 14
BUFFER = 7
RATE = 0.065
DELTA = (0.30, 0.75)
LONG_LEG = (0.40, 0.65)
MAX_SPREAD = 0.03
MAX_SPREAD_SHORT = 0.06      # the sold leg is further out; a slightly wider spread is normal
MIN_LOTS = 25
MIN_OI_SHARE = 0.10
MIN_RR = 2.0                 # singles: gain at the target over the loss at the stop, per lot
MIN_RR_SPREAD = 1.5
MAX_DECAY = 0.25
DEFAULTS = {"max_loss_per_trade": 5000, "max_open": 3, "take_profit_pct": 60, "stop_pct": 40, "exit_dte": 7,
            "structures": "spreads_first",
            "direction": {"min_p_target": 0.33, "min_avg_r": 0.15, "rs_long_in_down_market": 70, "rs_short_max": 50,
                          "long_min_fund": 45, "short_max_fund": 60}}


def settings(cfg):
    o = dict(DEFAULTS, **(cfg.get("options") or {}))
    o["direction"] = dict(DEFAULTS["direction"], **((cfg.get("options") or {}).get("direction") or {}))
    return o


def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs(S, K, T, iv, call):
    """Black-Scholes value per share; T in years, iv in % a year."""
    if T <= 0 or not iv:
        return max(S - K, 0.0) if call else max(K - S, 0.0)
    s = iv / 100.0
    d1 = (math.log(S / K) + (RATE + s * s / 2) * T) / (s * math.sqrt(T))
    d2 = d1 - s * math.sqrt(T)
    if call:
        return S * ncdf(d1) - K * math.exp(-RATE * T) * ncdf(d2)
    return K * math.exp(-RATE * T) * ncdf(-d2) - S * ncdf(-d1)


def calendar_days(sessions):
    return int(math.ceil((sessions or 10) * 7 / 5.0))


def pick_expiry(expiries, today, est_days):
    need = max(MIN_DTE, calendar_days(est_days) + BUFFER)
    for d in expiries:
        dte = (datetime.date.fromisoformat(d) - today).days
        if dte >= need:
            return d, dte, need
    return None, None, need


def buildup(o):
    """What price and OI did since yesterday say about this strike."""
    if not o.get("prev_oi") or not o.get("close") or o.get("oi") is None or o.get("ltp") is None:
        return None
    up_p, up_oi = o["ltp"] > o["close"], o["oi"] > o["prev_oi"]
    return {(True, True): "long build-up", (False, True): "short build-up (writing)",
            (True, False): "short covering", (False, False): "long unwinding"}[(up_p, up_oi)]


def k_(x):
    return str(int(x)) if x is not None and float(x).is_integer() else str(x)


# ---------------------------------------------------------------- 1. direction

MONTHS = {m: i for i, m in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}


def quarter_end(text):
    """"Jun 2026" -> 2026-06-30."""
    try:
        mon, yr = text.split()
        m, y = MONTHS[mon[:3]], int(yr)
    except (AttributeError, KeyError, ValueError):
        return None
    nxt = datetime.date(y + (m == 12), m % 12 + 1, 1)
    return nxt - datetime.timedelta(days=1)


def fiscal_quarter(qe):
    """India's fiscal quarter of a quarter end: 2026-09-30 -> ("Q2", "FY27")."""
    q = {6: 1, 9: 2, 12: 3, 3: 4}[qe.month]
    fy = qe.year + 1 if qe.month > 3 else qe.year
    return "Q%d" % q, "FY%02d" % (fy % 100)


RESULT_WORDS = re.compile(r"result|earning|profit|\bPAT\b|revenue|income|margin|EBITDA|loss", re.I)


def reported_in_news(news, qe):
    """A headline since the quarter end that reports that quarter's results ("Q2 results", "Q2FY27 net
    profit", "September quarter profit") means the results are out, whatever the fundamentals say."""
    q, fy = fiscal_quarter(qe)
    month = qe.strftime("%B")
    since_ms = (datetime.datetime.combine(qe, datetime.time()) - datetime.datetime(1970, 1, 1)).total_seconds() * 1000
    pat = re.compile(r"\b%s\s*%s\b|\b%s\b|%s[- ]quarter|quarter ended %s" % (q, fy, q, month, month), re.I)
    for n in news or []:
        t = n.get("title") or ""
        if (n.get("time_ms") or 0) >= since_ms and pat.search(t) and RESULT_WORDS.search(t) \
                and not re.search(r"\b(preview|ahead of|to announce|date|board meeting|expect|estimate)\b", t, re.I):
            return t
    return None


def results_due(q_period, today, window=None, news=None):
    """(due, why): the last quarter is not reported yet (neither in the fundamentals nor in a headline)
    and its results deadline has not passed: 45 days after a quarter end (60 after March's)."""
    last_qe = max(d for d in (datetime.date(today.year - 1, 12, 31), datetime.date(today.year, 3, 31),
                              datetime.date(today.year, 6, 30), datetime.date(today.year, 9, 30),
                              datetime.date(today.year, 12, 31)) if d < today)
    deadline = 60 if last_qe.month == 3 else 45
    reported = quarter_end(q_period) if q_period else None
    if reported and reported >= last_qe:
        return False, "%s results are out" % q_period
    head = reported_in_news(news, last_qe)
    if head:
        return False, "%s results are out (news: %s)" % ("%s %s" % fiscal_quarter(last_qe), head[:90])
    if (today - last_qe).days > deadline:
        return False, "the %s results deadline has passed" % last_qe.strftime("%b %Y")
    if reported is None and not news:
        return False, "no quarterly results on file"
    return True, "%s %s results not out yet (latest on file %s, no results headline): due by %s" % (
        fiscal_quarter(last_qe) + (q_period or "none", (last_qe + datetime.timedelta(days=deadline)).strftime("%d %b")))


def direction_checks(pk, nifty_trend, today, oc):
    D = oc["direction"]
    p = pk["plan"]
    o, h = p.get("odds") or {}, p.get("history") or {}
    long_ = p["side"] == "long"
    rs, fund = pk.get("rs_pct", 50), pk.get("fund")
    out = []

    def add(name, ok, detail):
        out.append({"name": name, "ok": bool(ok), "detail": detail})

    add("Replay edge", o.get("p_target", 0) >= D["min_p_target"] and o.get("avg_R", -9) >= D["min_avg_r"],
        "target first in %d%% of replays, expectancy %+.2fR (needs %d%%+ and %+.2fR+)" % (
            100 * o.get("p_target", 0), o.get("avg_R", 0), 100 * D["min_p_target"], D["min_avg_r"]))
    fired, havg = h.get("fired", 0), h.get("avg_R")
    add("Not failing on this stock", fired < 3 or (havg is not None and havg >= 0),
        "the same rule fired %d times here%s" % (fired, ", average %+.2fR" % havg if havg is not None else ""))
    if long_:
        add("Market agrees", nifty_trend != "down" or rs >= D["rs_long_in_down_market"],
            "Nifty %s; stronger than %d%% of stocks (a call in a falling market needs %d%%+)" % (
                nifty_trend or "?", rs, D["rs_long_in_down_market"]))
        add("Fundamentals not against it", fund is None or fund >= D["long_min_fund"],
            "score %s (a call needs %d+)" % ("n/a" if fund is None else fund, D["long_min_fund"]))
    else:
        add("Market agrees", nifty_trend != "up" and rs <= D["rs_short_max"],
            "Nifty %s; stronger than %d%% of stocks (a put needs a Nifty not rising and %d%% or less)" % (
                nifty_trend or "?", rs, D["rs_short_max"]))
        add("Fundamentals not against it", fund is None or fund <= D["short_max_fund"],
            "score %s (a put needs %d or less)" % ("n/a" if fund is None else fund, D["short_max_fund"]))
    due, why = results_due(pk.get("q_period"), today, news=pk.get("news"))
    add("No results due", not due, why)
    return out


# ---------------------------------------------------------------- 2-3. strikes, singles and spreads

def legs(chain, side, lot, spot):
    """Every quoted strike on one side with what the screen needs, nearest the money first."""
    rows = []
    for s in chain:
        o = s.get(side) or {}
        if o.get("delta") is None or not o.get("ask") or not o.get("bid") or not o.get("iv"):
            continue
        rows.append(dict(o, strike=s["strike"], lots=(o.get("oi") or 0) / lot,
                         spread=(o["ask"] - o["bid"]) / ((o["ask"] + o["bid"]) / 2)))
    return rows


def screen_one(pk, chain, expiry, dte, lot, today, oc, nifty_trend, iv_rank=None):
    plan = pk["plan"]
    call = plan["side"] == "long"
    side = "call" if call else "put"
    typ = "CE" if call else "PE"
    spot = next((s["spot"] for s in chain if s.get("spot")), None) or pk["price"]
    base = {"symbol": pk["symbol"], "name": pk.get("name"), "type": typ, "source": pk.get("_list"),
            "rank": pk.get("rank"), "score": pk.get("score"), "session": pk.get("session"),
            "plan": {k: plan.get(k) for k in ("kind", "entry", "stop", "target", "rr", "est_days")},
            "p_target": (plan.get("odds") or {}).get("p_target"), "spot": spot, "expiry": expiry, "dte": dte,
            "lot": lot, "hv20": pk.get("hv20"), "iv_rank": iv_rank, "budget": oc["max_loss_per_trade"],
            "take_profit_pct": oc["take_profit_pct"], "stop_pct": oc["stop_pct"], "exit_dte": oc["exit_dte"]}
    direction = direction_checks(pk, nifty_trend, today, oc)
    void = None
    if (call and spot <= plan["stop"]) or (not call and spot >= plan["stop"]):
        void = "the stock (%s) is already past the plan's stop (%s): the plan is off" % (spot, plan["stop"])
    elif (call and spot >= plan["target"]) or (not call and spot <= plan["target"]):
        void = "the stock (%s) is already at the plan's target (%s): nothing left to catch" % (spot, plan["target"])
    if void:
        return dict(base, void=True, qualified=False, strikes=[], spreads=[], best=None, watch=None, trade=None,
                    pcr=None, call_wall=None, put_wall=None, notes=[void], direction=direction,
                    checks=[{"name": "Plan still live", "ok": False, "detail": void}])

    L = legs(chain, side, lot, spot)
    tradable = [x for x in L if DELTA[0] <= abs(x["delta"]) <= DELTA[1]]
    max_oi = max([x.get("oi") or 0 for x in tradable] or [0])
    call_oi = sum((s["call"].get("oi") or 0) for s in chain)
    put_oi = sum((s["put"].get("oi") or 0) for s in chain)
    wall_c = max(chain, key=lambda s: s["call"].get("oi") or 0)["strike"]
    wall_p = max(chain, key=lambda s: s["put"].get("oi") or 0)["strike"]
    est = plan.get("est_days") or 10
    T_hit = (dte - calendar_days(est)) / 365.0
    T_stop = (dte - calendar_days(max(est // 2, 1))) / 365.0
    budget, hv = oc["max_loss_per_trade"], pk.get("hv20")

    def liquid(x, max_spread):
        why = []
        if x["spread"] > max_spread:
            why.append("bid-ask spread %.1f%%" % (100 * x["spread"]))
        if x["lots"] < MIN_LOTS or (x.get("oi") or 0) < MIN_OI_SHARE * max_oi:
            why.append("thin OI (%d lots)" % x["lots"])
        return why

    def wall_before(level):
        if call and spot < wall_c < level:
            return "most call OI (writers) sits at %s, before %s: it may cap the rise" % (k_(wall_c), k_(level))
        if not call and level < wall_p < spot:
            return "most put OI (writers) sits at %s, before %s: it may hold the fall" % (k_(wall_p), k_(level))
        return None

    # singles
    strikes = []
    for x in tradable:
        K = x["strike"]
        v_t, v_s, v_f = (bs(plan["target"], K, T_hit, x["iv"], call), bs(plan["stop"], K, T_stop, x["iv"], call),
                         bs(spot, K, T_hit, x["iv"], call))
        ask = x["ask"]
        gain, loss = (v_t - ask) * lot, (ask - v_s) * lot
        be = K + ask if call else K - ask
        s = {"strike": K, "ltp": x.get("ltp"), "bid": x["bid"], "ask": ask, "iv": x["iv"], "delta": round(x["delta"], 3),
             "gamma": x.get("gamma"), "theta": x.get("theta"), "vega": x.get("vega"),
             "theta_lot_day": round((x.get("theta") or 0) * lot), "vega_lot": round((x.get("vega") or 0) * lot),
             "oi_lots": round(x["lots"]), "oi_chg_pct": round((x["oi"] / x["prev_oi"] - 1) * 100, 1) if x.get("prev_oi") else None,
             "buildup": buildup(x), "premium_lot": round(ask * lot), "at_target_lot": round(v_t * lot),
             "at_stop_lot": round(v_s * lot), "flat_lot": round(v_f * lot), "gain_lot": round(gain), "loss_lot": round(loss),
             "rr": round(gain / loss, 2) if loss > 0 else None, "breakeven": round(be, 2),
             "be_move_pct": round((be / spot - 1) * 100, 2)}
        f = liquid(x, MAX_SPREAD)
        s["ok"], s["why_not"] = not f, list(f)
        if s["premium_lot"] > budget:
            f.append("costs Rs %s a lot, over the Rs %s budget" % (format(s["premium_lot"], ","), format(budget, ",")))
        if not s["rr"] or s["rr"] < MIN_RR:
            f.append("reward:risk %s, needs %.1f+" % (s["rr"], MIN_RR))
        if iv_rank is not None:
            if iv_rank > 50:
                f.append("IV in the top half of its own history (rank %d)" % iv_rank)
        elif not hv or x["iv"] > hv:
            f.append("IV %.0f%% is above the stock's realised %s%%: buy a spread instead" % (x["iv"], hv or "?"))
        if s["flat_lot"] < (1 - MAX_DECAY) * s["premium_lot"]:
            f.append("loses %d%% to time decay by day %d if the stock stands still" % (
                round(100 * (1 - s["flat_lot"] / s["premium_lot"])), est))
        if (call and be > plan["target"]) or (not call and be < plan["target"]):
            f.append("break-even %s is beyond the target %s" % (s["breakeven"], plan["target"]))
        w = wall_before(plan["target"])
        if w:
            f.append(w)
        s["fails"] = f
        strikes.append(s)

    # debit spreads: buy near the money, sell further out, no further than the target
    spreads = []
    longs = [x for x in L if LONG_LEG[0] <= abs(x["delta"]) <= LONG_LEG[1]]
    for a in longs:
        for b in L:
            if (call and not a["strike"] < b["strike"] <= plan["target"]) or \
                    (not call and not plan["target"] <= b["strike"] < a["strike"]):
                continue
            width = abs(b["strike"] - a["strike"])
            cost = a["ask"] - b["bid"]
            if cost <= 0 or cost >= width:
                continue
            Ka, Kb = a["strike"], b["strike"]
            v_t = bs(plan["target"], Ka, T_hit, a["iv"], call) - bs(plan["target"], Kb, T_hit, b["iv"], call)
            v_s = bs(plan["stop"], Ka, T_stop, a["iv"], call) - bs(plan["stop"], Kb, T_stop, b["iv"], call)
            v_f = bs(spot, Ka, T_hit, a["iv"], call) - bs(spot, Kb, T_hit, b["iv"], call)
            gain, loss = (v_t - cost) * lot, (cost - v_s) * lot
            be = Ka + cost if call else Ka - cost
            sp = {"buy": Ka, "sell": Kb, "width": width, "cost": round(cost, 2), "cost_lot": round(cost * lot),
                  "max_profit_lot": round((width - cost) * lot), "gain_lot": round(gain), "loss_lot": round(loss),
                  "rr": round(gain / loss, 2) if loss > 0 else None, "breakeven": round(be, 2),
                  "flat_lot": round(v_f * lot), "buy_delta": round(a["delta"], 3), "sell_delta": round(b["delta"], 3),
                  "buy_iv": a["iv"], "sell_iv": b["iv"],
                  "theta_lot_day": round(((a.get("theta") or 0) - (b.get("theta") or 0)) * lot),
                  "lots_in_budget": int(budget // (cost * lot)) if cost * lot else 0}
            f = liquid(a, MAX_SPREAD) + ["sold leg: " + w for w in liquid(b, MAX_SPREAD_SHORT)]
            if sp["cost_lot"] > budget:
                f.append("costs Rs %s a lot, over the Rs %s budget" % (format(sp["cost_lot"], ","), format(budget, ",")))
            if cost > width / 2:
                f.append("pays %d%% of the width (max 50%%)" % round(100 * cost / width))
            if not sp["rr"] or sp["rr"] < MIN_RR_SPREAD:
                f.append("reward:risk %s, needs %.1f+" % (sp["rr"], MIN_RR_SPREAD))
            if (call and be > plan["target"]) or (not call and be < plan["target"]):
                f.append("break-even %s is beyond the target" % sp["breakeven"])
            if sp["flat_lot"] < (1 - MAX_DECAY) * sp["cost_lot"]:
                f.append("loses %d%% to time decay by day %d if the stock stands still" % (
                    round(100 * (1 - sp["flat_lot"] / sp["cost_lot"])), est))
            w = wall_before(Kb)
            if w:
                f.append(w)
            sp["fails"] = f
            spreads.append(sp)

    ok_single = [s for s in strikes if not s["fails"]]
    ok_spread = [s for s in spreads if not s["fails"]]
    by_rr = lambda xs: max(xs, key=lambda x: (x["rr"] or 0, x.get("max_profit_lot", 0)))  # noqa: E731
    trade = None
    if ok_single and oc.get("structures") != "spreads_only":
        b = by_rr(ok_single)
        trade = {"structure": "single", "buy": b["strike"], "sell": None, "cost": b["ask"], "cost_lot": b["premium_lot"],
                 "gain_lot": b["gain_lot"], "loss_lot": b["loss_lot"], "rr": b["rr"], "breakeven": b["breakeven"],
                 "max_profit_lot": None, "lots_in_budget": int(budget // b["premium_lot"]) if b["premium_lot"] else 0}
    if ok_spread and oc.get("structures") != "singles_only" and (not trade or oc.get("structures") == "spreads_first"
                                                                  and not (iv_rank is not None and iv_rank <= 30)):
        b = by_rr(ok_spread)
        trade = dict(b, structure="spread")
    spreads.sort(key=lambda x: (bool(x["fails"]), -(x["rr"] or 0)))
    nearest = (by_rr([s for s in spreads if s["rr"]]) if spreads and any(s["rr"] for s in spreads) else None)
    struct_detail = ("%s %s%s %s: costs Rs %s a lot, reward:risk %s" % (
        "buy" if trade["structure"] == "single" else "spread", k_(trade["buy"]),
        "/%s" % k_(trade["sell"]) if trade.get("sell") else "", typ, format(trade["cost_lot"], ","), trade["rr"])
        if trade else "none fits: closest spread %s/%s fails on %s" % (
            k_(nearest["buy"]), k_(nearest["sell"]), "; ".join(nearest["fails"])) if nearest else
        "no liquid strikes to build one")
    checks = direction + [{"name": "A structure fits every option check", "ok": bool(trade), "detail": struct_detail}]
    pcr = round(put_oi / call_oi, 2) if call_oi else None
    good = [s["strike"] for s in ok_single] or ([trade["buy"]] if trade else [])
    return dict(base, pcr=pcr, call_wall=wall_c, put_wall=wall_p, strikes=sorted(strikes, key=lambda x: x["strike"]),
                spreads=spreads[:8], trade=trade, best=trade["buy"] if trade else None,
                watch=[min(good), max(good)] if good else None, direction=direction, checks=checks,
                qualified=all(c["ok"] for c in checks), notes=[])


def fo_plans(lists, inst, funds=None, limit=40):
    """Every plan on an F&O stock (not just the recommended swings), with what the direction checks
    need: [{"symbol", "name", "price", "rank", "score", "_list", "plan", "session", "hv20", "rs_pct",
    "fund", "q_period", "qualified"}], best score first."""
    fo, exps, eq = inst.get("fo") or {}, inst.get("expiries") or {}, inst.get("eq") or {}
    funds = funds or {}
    out = []
    for rows, label in lists:
        for r in rows:
            plan = r.get("plan") or (r.get("bottom") or {}).get("plan")
            if plan and plan.get("odds") and r["symbol"] in fo and r["symbol"] in eq and r["symbol"] in exps:
                p = dict(plan)
                p.setdefault("est_days", (p.get("odds") or {}).get("days_to_target"))
                f = funds.get(r["symbol"]) or {}
                out.append({"symbol": r["symbol"], "name": r.get("name"), "price": r.get("price"), "rank": r.get("rank"),
                            "score": r.get("score"), "_list": label, "plan": p, "session": r.get("session"),
                            "hv20": r.get("hv20"), "rs_pct": r.get("rs_pct"), "fund": r.get("fund"),
                            "q_period": f.get("net_profit_q_period") or f.get("revenue_q_period"),
                            "qualified": r.get("qualified")})
    return sorted(out, key=lambda x: -(x["score"] or 0))[:limit]


def screen(picks, inst, now_utc, cfg, errors, nifty_trend=None, iv_hist=None):
    """Option cards for each pick: one option-chain request each."""
    oc = settings(cfg)
    today = market.to_ist(now_utc).date()
    fo, exps, eq = inst.get("fo") or {}, inst.get("expiries") or {}, inst.get("eq") or {}
    out = {"calls": [], "puts": [], "skipped": []}
    for r in picks:
        plan = r["plan"]
        if r["symbol"] not in exps or r["symbol"] not in eq:
            continue
        expiry, dte, need = pick_expiry(exps[r["symbol"]], today, plan.get("est_days"))
        if not expiry:
            out["skipped"].append("%s: no expiry %d+ days away" % (r["symbol"][:-3], need))
            continue
        try:
            chain = get_chain(eq[r["symbol"]]["key"], expiry)
        except Exception as e:                       # noqa: BLE001
            errors.append("option chain %s: %s" % (r["symbol"], e))
            continue
        if not chain:
            out["skipped"].append("%s: empty chain for %s" % (r["symbol"][:-3], expiry))
            continue
        res = screen_one(r, chain, expiry, dte, fo[r["symbol"]], today, oc, nifty_trend,
                         iv_rank_of(iv_hist, r["symbol"], atm_iv(chain)))
        (out["calls"] if res["type"] == "CE" else out["puts"]).append(res)

    def rank_key(x):
        t = x.get("trade") or {}
        return (not x.get("qualified"), bool(x.get("void")), -((x.get("p_target") or 0) * (t.get("rr") or 0)),
                -(x["score"] or 0))
    for k in ("calls", "puts"):
        out[k].sort(key=rank_key)
    out.update(created_ist=market.to_ist(now_utc).strftime("%Y-%m-%d %H:%M"),
               rules={"min_dte": MIN_DTE, "buffer": BUFFER, "delta": DELTA, "long_leg": LONG_LEG,
                      "max_spread_pct": 100 * MAX_SPREAD, "min_lots": MIN_LOTS, "rate_pct": 100 * RATE,
                      "min_rr": MIN_RR, "min_rr_spread": MIN_RR_SPREAD, "max_decay_pct": 100 * MAX_DECAY,
                      "budget": oc["max_loss_per_trade"], "max_open": oc["max_open"],
                      "take_profit_pct": oc["take_profit_pct"], "stop_pct": oc["stop_pct"], "exit_dte": oc["exit_dte"],
                      "direction": oc["direction"]})
    return out


# ---------------------------------------------------------------- IV history (for IV rank)

def atm_iv(chain):
    """Average of the call and put IV at the strike nearest the price."""
    if not chain:
        return None
    spot = next((s["spot"] for s in chain if s.get("spot")), None)
    if not spot:
        return None
    s = min(chain, key=lambda x: abs((x["strike"] or 0) - spot))
    ivs = [s[k].get("iv") for k in ("call", "put") if s.get(k) and s[k].get("iv")]
    return round(sum(ivs) / len(ivs), 2) if ivs else None


def iv_rank_of(hist, sym, iv, min_days=40):
    """Where today's IV sits in the stock's own recorded IV (0 = lowest, 100 = highest), once there is enough."""
    days = sorted(((hist or {}).get(sym) or {}).values())
    if iv is None or len(days) < min_days:
        return None
    return round(100 * sum(1 for x in days if x < iv) / len(days))


def record_iv(hist, symbols, inst, today, errors, keep=300):
    """Today's at-the-money IV (nearest monthly expiry 7+ days out) for each F&O stock."""
    eq, exps = inst.get("eq") or {}, inst.get("expiries") or {}
    n = 0
    for sym in symbols:
        ex = next((d for d in exps.get(sym, []) if (datetime.date.fromisoformat(d) - today).days >= 7), None)
        if not ex or sym not in eq:
            continue
        try:
            iv = atm_iv(get_chain(eq[sym]["key"], ex))
        except Exception as e:                       # noqa: BLE001
            errors.append("IV history %s: %s" % (sym, e))
            continue
        if iv:
            h = hist.setdefault(sym, {})
            h[today.isoformat()] = iv
            for d in sorted(h)[:-keep]:
                del h[d]
            n += 1
    return n


# ---------------------------------------------------------------- 4. the options track record

_chains = {}


def get_chain(key, expiry):
    """One request per (stock, expiry) a run: the screen, the IV history and the record share it."""
    if (key, expiry) not in _chains:
        _chains[(key, expiry)] = upstox.option_chain(key, expiry)
    return _chains[(key, expiry)]


OPEN = ("waiting for entry", "entered")


def _q(chain, strike, typ):
    side = "call" if typ == "CE" else "put"
    for s in chain:
        if s["strike"] == strike and s.get(side):
            return s[side], s.get("spot")
    return None, None


def _price(r, chain, buying):
    """What opening (buying) or closing (selling) the trade costs or brings now, a share; and the spot."""
    a, spot = _q(chain, r["strike"], r["type"])
    if not a:
        return None, spot
    if not r.get("short_strike"):
        return (a.get("ask") if buying else a.get("bid")) or a.get("ltp"), spot
    b, _ = _q(chain, r["short_strike"], r["type"])
    if not b:
        return None, spot
    if buying:                                        # buy the near leg at the ask, sell the far one at the bid
        return ((a.get("ask") or a.get("ltp")) - (b.get("bid") or b.get("ltp"))), spot
    return ((a.get("bid") or a.get("ltp")) - (b.get("ask") or b.get("ltp"))), spot


def _intrinsic(r, spot):
    call = r["type"] == "CE"
    v = max(spot - r["strike"], 0) if call else max(r["strike"] - spot, 0)
    if r.get("short_strike"):
        v -= max(spot - r["short_strike"], 0) if call else max(r["short_strike"] - spot, 0)
    return v


def track(rows, opts, stock_records, inst, now_utc, errors, cfg=None):
    """Move the option record on. New: each qualifying card's trade (one per stock and signal session),
    while fewer than max_open trades are open or waiting. Entry: when the stock triggers the plan's entry,
    if the card still qualifies with the same strikes, at the ask (spread: near leg at the ask, far leg
    at the bid). Exit, first of: +take_profit% or -stop% of the cost, the stock plan's target or stop or
    day 15, 7 days before expiry, expiry. Prices are those at the 30-minute update after the move."""
    oc = settings(cfg or {})
    today = market.to_ist(now_utc).date()
    stamp = market.to_ist(now_utc).strftime("%Y-%m-%d %H:%M")
    eq = inst.get("eq") or {}
    have = {r["id"] for r in rows}
    cards = ((opts or {}).get("calls") or []) + ((opts or {}).get("puts") or [])
    for o in cards:
        if not o.get("qualified") or not o.get("trade") or not o.get("session"):
            continue
        rid = "%s-%s-%s" % (o["session"], o["symbol"], o["type"])
        if rid in have:
            continue
        if sum(1 for r in rows if r["status"] in OPEN) >= oc["max_open"]:
            o["capacity"] = True                       # qualifies, but the open slots are full: shown, not taken
            continue
        t = o["trade"]
        rows.append({"id": rid, "stock_id": "%s-%s" % (o["session"], o["symbol"]), "created": o["session"],
                     "created_ist": stamp, "symbol": o["symbol"], "name": o.get("name"), "type": o["type"],
                     "structure": t["structure"], "strike": t["buy"], "short_strike": t.get("sell"),
                     "expiry": o["expiry"], "lot": o["lot"], "plan": o["plan"], "signal_ask": t["cost"],
                     "signal_spot": o["spot"], "status": "waiting for entry", "stock_status": "waiting for entry",
                     "last": t["cost"], "last_ist": stamp})
        have.add(rid)
    stocks = {r["id"]: r for r in stock_records}
    by_sym = {o["symbol"]: o for o in cards}
    tp, sl = oc["take_profit_pct"] / 100.0, oc["stop_pct"] / 100.0
    for r in rows:
        if r["status"] not in OPEN:
            continue
        st = stocks.get(r["stock_id"]) or {}
        r["stock_status"] = st.get("status", r.get("stock_status"))
        key = (eq.get(r["symbol"]) or {}).get("key")
        chain = None
        if key:
            try:
                chain = get_chain(key, r["expiry"])
            except Exception as e:                   # noqa: BLE001
                errors.append("option record %s: %s" % (r["id"], e))
        expiry = datetime.date.fromisoformat(r["expiry"])
        if today >= expiry:
            if r["status"] == "entered":
                spot = next((s["spot"] for s in chain or [] if s.get("spot")), None) or r.get("last_spot") or r["signal_spot"]
                _close(r, "expired", _intrinsic(r, spot), stamp)
            else:
                r.update(status="not entered before expiry", closed_ist=stamp)
            continue
        if not chain:
            continue
        sell, spot = _price(r, chain, buying=False)
        if sell is None:
            continue
        r.update(last=round(sell, 2), last_ist=stamp, last_spot=spot)
        stock_done = r["stock_status"] in ("target hit", "stop hit") or str(r["stock_status"]).startswith("closed at day")
        if r["status"] == "waiting for entry":
            if r["stock_status"] == "entered":
                card = by_sym.get(r["symbol"])
                t = (card or {}).get("trade") or {}
                if opts and not (card and card.get("qualified") and t.get("buy") == r["strike"]
                                 and t.get("sell") == r.get("short_strike")):
                    why = ([c["detail"] for c in card.get("checks", []) if not c["ok"]] if card else ["no option card now"])
                    if card and t and (t.get("buy"), t.get("sell")) != (r["strike"], r.get("short_strike")):
                        why.append("the trade is now %s/%s" % (t.get("buy"), t.get("sell")))
                    r.update(status="skipped at entry", closed_ist=stamp, skip_reason="; ".join(why)[:300])
                    continue
                buy, _ = _price(r, chain, buying=True)
                r.update(status="entered", fill=round(buy, 2), entered_ist=stamp)
            elif stock_done:
                r.update(status="stock plan opened and closed between updates", closed_ist=stamp)
                continue
            elif r["stock_status"] == "entry missed":
                r.update(status="entry missed", closed_ist=stamp)
                continue
            else:
                continue
        change = sell / r["fill"] - 1 if r["fill"] else 0
        if stock_done:
            _close(r, "stock " + r["stock_status"], sell, stamp)
        elif change >= tp:
            _close(r, "take profit +%d%%" % oc["take_profit_pct"], sell, stamp)
        elif change <= -sl:
            _close(r, "option stop -%d%%" % oc["stop_pct"], sell, stamp)
        elif (expiry - today).days <= oc["exit_dte"]:
            _close(r, "%d days to expiry" % oc["exit_dte"], sell, stamp)
        else:
            r["mark_lot"] = round((sell - r["fill"]) * r["lot"])
            r["mark_pct"] = round(change * 100, 1)
    return rows


def _close(r, why, price, stamp):
    fill = r.get("fill") or 0
    r.update(status="closed: " + why, exit=round(price, 2), closed_ist=stamp,
             result_lot=round((price - fill) * r["lot"]),
             result_pct=round((price / fill - 1) * 100, 1) if fill else None)
    r.pop("mark_lot", None)
    r.pop("mark_pct", None)


def summary(rows):
    done = [r for r in rows if r.get("result_lot") is not None]
    opened = [r for r in rows if r["status"] == "entered"]
    st = {"tracked": len(rows), "open": sum(1 for r in rows if r["status"] in OPEN), "entered_now": len(opened),
          "closed": len(done), "missed": sum(1 for r in rows if r["status"] in (
              "entry missed", "not entered before expiry", "skipped at entry", "stock plan opened and closed between updates")),
          "wins": sum(1 for r in done if r["result_lot"] > 0),
          "total_lot": sum(r["result_lot"] for r in done), "open_mark_lot": sum(r.get("mark_lot") or 0 for r in opened)}
    st["avg_pct"] = round(sum(r["result_pct"] or 0 for r in done) / len(done), 1) if done else None
    st["win_rate"] = round(st["wins"] / len(done), 3) if done else None
    return {"stats": st, "rows": sorted(rows, key=lambda r: r["created_ist"], reverse=True)[:60]}
