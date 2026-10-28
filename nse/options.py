"""Equity options screen: the call or put strikes worth watching for each swing plan on an F&O stock.

A rules screen with its numbers, not advice: which strike to trade, and whether, is the trader's call.

For each F&O stock with a swing plan (calls for bullish setups and bottoms turning up, puts for
breakdowns and failed rallies):

  Expiry   the nearest monthly expiry at least MIN_DTE (14) calendar days away that also leaves
           BUFFER (7) days after the plan's estimated exit, so time decay is not at its worst
           when the move is due.
  Strikes  delta 0.30 to 0.75 (at the money, give or take), bid-ask spread 3% or less of the
           price, real open interest: 25 lots or more and at least a tenth of the busiest strike's
           OI among those in the delta range.
  Numbers  per strike: premium (the ask, what a buyer pays), the greeks from Upstox, OI in lots and
           its change since yesterday, the build-up it suggests, and what one lot would be worth if
           the stock reaches the plan's TARGET by its estimated day, or its STOP halfway there, or is
           flat by then: Black-Scholes at that strike's own IV (kept unchanged; IV usually falls after
           a big move or results, which hurts a buyer), 6.5% interest. Reward:risk = gain at target
           over loss at stop, per lot. Break-even at expiry, and the move it needs.
  OI       put-call ratio of the expiry; the strikes with the most call OI (writers who may cap a
           rise) and the most put OI (writers who may defend a fall). A target beyond the biggest
           call wall (for a call) or put wall (for a put) is flagged.
"""

import datetime
import math

import market
import upstox

MIN_DTE = 14
BUFFER = 7
RATE = 0.065
DELTA = (0.30, 0.75)
MAX_SPREAD = 0.03
MIN_LOTS = 25
MIN_OI_SHARE = 0.10


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


def screen_one(row, plan, chain, expiry, dte, lot, today, cfg):
    call = plan["side"] == "long"
    side = "call" if call else "put"
    spot = next((s["spot"] for s in chain if s.get("spot")), None) or row["price"]
    sides = [s for s in chain if s.get(side) and s["strike"]]
    # the busiest strike among the tradable ones (delta in range), not a far out-of-the-money wall
    oi_all = [s[side].get("oi") or 0 for s in sides
              if s[side].get("delta") is not None and DELTA[0] <= abs(s[side]["delta"]) <= DELTA[1]]
    max_oi = max(oi_all) if oi_all else 0
    call_oi = sum((s["call"].get("oi") or 0) for s in chain)
    put_oi = sum((s["put"].get("oi") or 0) for s in chain)
    wall_c = max(chain, key=lambda s: s["call"].get("oi") or 0)["strike"] if chain else None
    wall_p = max(chain, key=lambda s: s["put"].get("oi") or 0)["strike"] if chain else None
    est = plan.get("est_days") or 10
    t_hit = calendar_days(est)
    t_stop = calendar_days(max(est // 2, 1))
    strikes = []
    for s in sides:
        o = s[side]
        d, ask, bid = o.get("delta"), o.get("ask"), o.get("bid")
        if d is None or not ask or not bid or not o.get("iv"):
            continue
        mid = (ask + bid) / 2
        why_not = []
        if not DELTA[0] <= abs(d) <= DELTA[1]:
            continue                                  # far from the money: not in the range at all
        if (ask - bid) / mid > MAX_SPREAD:
            why_not.append("spread %.1f%%" % (100 * (ask - bid) / mid))
        lots = (o.get("oi") or 0) / lot
        if lots < MIN_LOTS or (o.get("oi") or 0) < MIN_OI_SHARE * max_oi:
            why_not.append("thin OI")
        K = s["strike"]
        v_t = bs(plan["target"], K, (dte - t_hit) / 365.0, o["iv"], call)
        v_s = bs(plan["stop"], K, (dte - t_stop) / 365.0, o["iv"], call)
        v_f = bs(spot, K, (dte - t_hit) / 365.0, o["iv"], call)
        gain, loss = (v_t - ask) * lot, (ask - v_s) * lot
        be = K + ask if call else K - ask
        strikes.append({
            "strike": K, "ltp": o.get("ltp"), "bid": bid, "ask": ask, "iv": o["iv"], "delta": round(d, 3),
            "gamma": o.get("gamma"), "theta": o.get("theta"), "vega": o.get("vega"),
            "theta_lot_day": round((o.get("theta") or 0) * lot), "vega_lot": round((o.get("vega") or 0) * lot),
            "oi_lots": round(lots), "oi_chg_pct": round((o["oi"] / o["prev_oi"] - 1) * 100, 1) if o.get("prev_oi") else None,
            "volume_lots": round((o.get("volume") or 0) / lot), "buildup": buildup(o),
            "premium_lot": round(ask * lot), "at_target_lot": round(v_t * lot), "at_stop_lot": round(v_s * lot),
            "flat_lot": round(v_f * lot), "gain_lot": round(gain), "loss_lot": round(loss),
            "rr": round(gain / loss, 2) if loss > 0 else None, "breakeven": round(be, 2),
            "be_move_pct": round((be / spot - 1) * 100, 2), "ok": not why_not, "why_not": why_not})
    good = [x for x in strikes if x["ok"] and x["rr"] and x["rr"] > 0 and x["gain_lot"] > 0]
    best = max(good, key=lambda x: (x["rr"], -abs(abs(x["delta"]) - 0.5))) if good else None
    watch = [x["strike"] for x in good if x["rr"] >= 1.5] or ([best["strike"]] if best else [])
    notes = []
    if call and wall_c and spot < wall_c < plan["target"]:
        notes.append("most call OI (writers) sits at %s, between the price and the target: it may cap the rise" % wall_c)
    if not call and wall_p and plan["target"] < wall_p < spot:
        notes.append("most put OI (writers) sits at %s, between the price and the target: it may hold the fall" % wall_p)
    max_loss = cfg.get("max_loss_per_trade")
    if best and max_loss and best["loss_lot"] > max_loss:
        notes.append("one lot of the best strike loses about Rs %s at the stop, over your Rs %s a trade"
                     % (format(best["loss_lot"], ","), format(max_loss, ",")))
    pcr = round(put_oi / call_oi, 2) if call_oi else None
    return {"symbol": row["symbol"], "name": row.get("name"), "type": "CE" if call else "PE",
            "source": row.get("_list"), "rank": row.get("rank"), "score": row.get("score"),
            "plan": {k: plan.get(k) for k in ("kind", "entry", "stop", "target", "rr", "est_days")},
            "p_target": (plan.get("odds") or {}).get("p_target"), "spot": spot, "expiry": expiry, "dte": dte,
            "lot": lot, "pcr": pcr, "call_wall": wall_c, "put_wall": wall_p,
            "strikes": sorted(strikes, key=lambda x: x["strike"]), "best": best["strike"] if best else None,
            "watch": [min(watch), max(watch)] if watch else None, "notes": notes}


def fo_plans(lists, inst, limit=30):
    """The swing plans on F&O stocks, best score first: [{"symbol", "name", "price", "rank", "score",
    "_list", "plan"}]. lists: (rows, label) pairs, the full ranked lists, not just the shown ones."""
    fo, exps, eq = inst.get("fo") or {}, inst.get("expiries") or {}, inst.get("eq") or {}
    out = []
    for rows, label in lists:
        for r in rows:
            plan = r.get("plan") or (r.get("bottom") or {}).get("plan")
            if plan and r["symbol"] in fo and r["symbol"] in eq and r["symbol"] in exps:
                p = dict(plan)
                p.setdefault("est_days", (p.get("odds") or {}).get("days_to_target"))
                out.append({"symbol": r["symbol"], "name": r.get("name"), "price": r.get("price"), "rank": r.get("rank"),
                            "score": r.get("score"), "_list": label, "plan": p})
    return sorted(out, key=lambda x: -(x["score"] or 0))[:limit]


def screen(picks, inst, now_utc, cfg, errors):
    """Options rows for each pick (from fo_plans): one option-chain request each."""
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
            chain = upstox.option_chain(eq[r["symbol"]]["key"], expiry)
        except Exception as e:                       # noqa: BLE001
            errors.append("option chain %s: %s" % (r["symbol"], e))
            continue
        if not chain:
            out["skipped"].append("%s: empty chain for %s" % (r["symbol"][:-3], expiry))
            continue
        res = screen_one(r, plan, chain, expiry, dte, fo[r["symbol"]], today, cfg)
        (out["calls"] if res["type"] == "CE" else out["puts"]).append(res)
    for k in ("calls", "puts"):
        out[k].sort(key=lambda x: (x["best"] is None, -(x["score"] or 0)))
    out.update(created_ist=market.to_ist(now_utc).strftime("%Y-%m-%d %H:%M"),
               rules={"min_dte": MIN_DTE, "buffer": BUFFER, "delta": DELTA, "max_spread_pct": 100 * MAX_SPREAD,
                      "min_lots": MIN_LOTS, "rate_pct": 100 * RATE})
    return out
