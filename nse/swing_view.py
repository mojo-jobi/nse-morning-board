"""The swing tabs of docs/index.html, from docs/swing.json (written by swing.py).

Charts: TradingView's open-source Lightweight Charts library (Apache-2.0), loaded on the first
chart opened, drawing the last ~130 daily candles from docs/swing-charts.json with the plan's lines.
"""

import html

CHART_LIB = "https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"

CSS = """
nav.tabs{position:sticky;top:0;z-index:5;display:flex;gap:4px;overflow-x:auto;background:var(--bg);
padding:8px 0;margin:14px 0 4px;border-bottom:1px solid var(--line);-webkit-overflow-scrolling:touch}
nav.tabs a{flex:0 0 auto;padding:7px 14px;border-radius:999px;text-decoration:none;color:var(--muted);
font-weight:600;font-size:14px;border:1px solid var(--line)}
nav.tabs a.on{background:var(--accent);border-color:var(--accent);color:var(--bg)}
.kind{font-size:12px;font-weight:700;border-radius:6px;padding:1px 8px;background:var(--neutral);color:var(--ink)}
.kind.long{background:var(--good-bg);color:var(--good)}.kind.short{background:var(--bad-bg);color:var(--bad)}
.st{font-size:12px;font-weight:600;border-radius:6px;padding:1px 8px;border:1px solid var(--line);color:var(--muted)}
.st.entered{border-color:var(--accent);color:var(--accent)}.st.target{background:var(--good-bg);color:var(--good);border-color:transparent}
.st.stop{background:var(--bad-bg);color:var(--bad);border-color:transparent}
.scores{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
.score{font-size:12px;border-radius:6px;padding:2px 8px;background:var(--neutral);font-variant-numeric:tabular-nums}
.chart{height:300px;margin-top:8px}
section.tab .grid{grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}
.moves{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px}
.moves ul{margin:6px 0 0;padding-left:18px;font-size:13px}
.tbl{overflow-x:auto}.tbl table{min-width:760px}
.why2{margin:6px 0 0;padding-left:18px;font-size:13px;color:var(--muted)}
.empty{color:var(--muted);font-size:14px;padding:6px 0}
.checks{margin:8px 0;font-size:13px}.checks ul{margin:4px 0 0;padding-left:18px}.checks li{margin:2px 0}
.ck-ok{color:var(--good)}.ck-no{color:var(--bad)}div.checks>.ck-no{font-weight:700}
details.watch{margin-top:12px}details.watch>summary{font-weight:600}
"""


def e(x):
    return html.escape("" if x is None else str(x))


def rs(x, dp=2):
    if x is None:
        return "-"
    x = float(x)
    return ("-" if x < 0 else "") + "₹" + ("{:,.%df}" % dp).format(abs(x))


def pct(x):
    return "-" if x is None else "%.0f%%" % (100 * x)


def sym(s):
    return (s or "").replace(".NS", "")


def status_pill(st):
    if not st:
        return ""
    cls = ("target" if st == "target hit" else "stop" if st == "stop hit" else
           "entered" if st == "entered" else "")
    return '<span class="st %s">%s</span>' % (cls, e(st))


def price_line(r):
    chg = r.get("chg_pct")
    s = '<span class="px">%s</span>' % rs(r.get("price"))
    if chg is not None:
        s += ' <span class="%s">%+.2f%%</span>' % ("up" if chg >= 0 else "dn", chg)
    if r.get("live_price") is not None:
        lc = r.get("live_chg_pct") or 0
        s += ' <span class="sub">now %s <span class="%s">%+.2f%%</span></span>' % (
            rs(r["live_price"]), "up" if lc >= 0 else "dn", lc)
    return s


def plan_block(r, p):
    o, h = p.get("odds") or {}, p.get("history") or {}
    cells = [("Entry (trigger)", "%s %s" % ("above" if p["side"] == "long" else "below", rs(p["entry"]))),
             ("Stop loss", rs(p["stop"])),
             ("Target", "%s (%s)" % (rs(p["target"]), e(p.get("target_label")))),
             ("Reward : risk", "%.1f" % p["rr"]),
             ("Estimated days", "~%s sessions" % p["est_days"] if p.get("est_days") else "-")]
    if r.get("size"):
        sz = r["size"]
        if sz.get("qty"):
            cells += [("Size (₹%s risk)" % format(round(sz["max_loss"] or 0), ","),
                       "%d shares, %s" % (sz["qty"], rs(sz["cost"], 0))),
                      ("If target / if stop", '<span class="up">+%s</span> / <span class="dn">-%s</span>' % (
                          rs(sz.get("reward"), 0), rs(sz.get("max_loss"), 0)))]
        else:
            cells.append(("Size", e(sz.get("refusal") or "no shares fit")))
    if r.get("lot"):
        lt = r["lot"]
        cells += [("F&O lot", "%s shares (%s)" % (lt["lot"], rs(lt["notional"], 0))),
                  ("Stock move per lot", "%s to target / %s to stop" % (rs(lt["move_to_target"], 0), rs(lt["move_to_stop"], 0)))]
    grid = "".join('<div><div class="k">%s</div><div class="v">%s</div></div>' % (e(k), v if "<span" in v else e(v))
                   for k, v in cells)
    odds = ""
    if o.get("n"):
        odds = ('<div style="margin-top:10px"><div class="k">%s replays of up to %d sessions from its own last year</div>'
                '<div class="odds"><i class="o-t" style="width:%.1f%%"></i><i class="o-s" style="width:%.1f%%"></i>'
                '<i class="o-n" style="width:%.1f%%"></i></div><div class="legend">target first %s &middot; stop first %s'
                ' &middot; neither in %d sessions %s &middot; average %+.2fR</div>' % (
                    format(o["n"], ","), o["horizon"], 100 * o["p_target"], 100 * o["p_stop"], 100 * o["p_time"],
                    pct(o["p_target"]), pct(o["p_stop"]), o["horizon"], pct(o["p_time"]), o["avg_R"]))
        if h.get("fired"):
            odds += ('<div class="why">Same rule on this stock\'s past: fired %d times, target %d, stop %d, '
                     'neither %d%s.</div>' % (h["fired"], h["target"], h["stop"], h["time"],
                                              ", average %+.2fR" % h["avg_R"] if h.get("avg_R") is not None else ""))
        elif "fired" in h:
            odds += '<div class="why">This rule never fired on this stock in its last 2 to 3 years.</div>'
        odds += "</div>"
    return '<div class="grid">%s</div>%s' % (grid, odds)


def scores(r):
    out = ['<span class="score">Score %s</span>' % e(r.get("score")), '<span class="score">Technical %s</span>' % e(r.get("tech"))]
    out.append('<span class="score">Fundamental %s</span>' % (e(r["fund"]) if r.get("fund") is not None else "n/a"))
    if r.get("rs_pct") is not None:
        if (r.get("plan") or {}).get("side") == "short":
            out.append('<span class="score">vs Nifty: weaker than %d%% of stocks</span>' % (100 - r["rs_pct"]))
        else:
            out.append('<span class="score">vs Nifty: stronger than %d%% of stocks</span>' % r["rs_pct"])
    return '<div class="scores">%s</div>' % "".join(out)


def extras(r, lines):
    fn = r.get("fund_notes") or []
    news = r.get("news") or []
    out = ""
    if fn:
        out += '<div class="why">%s</div>' % e(" · ".join(fn))
    out += ('<details class="chartbox" data-sym="%s" data-lines="%s"><summary>Chart</summary><div class="chart"></div></details>'
            % (e(r["symbol"]), e(lines)))
    if news:
        out += '<details><summary>News (%d)</summary><ul class="news">%s</ul></details>' % (len(news), "".join(
            '<li><a href="%s" target="_blank" rel="noopener">%s</a> <span class="src">%s</span></li>' % (
                e(n.get("link")), e(n.get("title")), e(n.get("time"))) for n in news))
    return out


def _lines(*pairs):
    import json
    return json.dumps([{"p": p, "t": t, "c": c} for p, t, c in pairs if p is not None])


def checks_block(checks, qualified):
    """The gate's checks: all shown, folded when every one passed; failures listed first otherwise."""
    if not checks:
        return ""
    items = "".join('<li class="%s"><b>%s %s</b>: %s</li>' % ("ck-ok" if c["ok"] else "ck-no", "\u2713" if c["ok"] else "\u2717",
                                                             e(c["name"]), e(c["detail"]))
                    for c in sorted(checks, key=lambda c: c["ok"]))
    if qualified:
        return ('<details class="checks"><summary class="ck-ok">\u2713 Clears all %d checks</summary><ul>%s</ul></details>'
                % (len(checks), items))
    n = sum(1 for c in checks if not c["ok"])
    return '<div class="checks"><div class="ck-no">\u2717 Fails %d of %d checks: watchlist only</div><ul>%s</ul></div>' % (
        n, len(checks), items)


def trade_card(r):
    p = r.get("plan") or {}
    tech = "support %s &middot; resistance %s &middot; RSI %s &middot; 50-day %s &middot; 200-day %s" % (
        rs(r.get("support")), rs(r.get("resistance")), e(r.get("rsi")), rs(r.get("sma50")), rs(r.get("sma200")))
    if r.get("vol_ratio"):
        tech += " &middot; volume %.1fx usual" % r["vol_ratio"]
    lines = _lines((p.get("entry"), "entry", "#2f5bd3"), (p.get("stop"), "stop", "#b3261e"),
                   (p.get("target"), "target", "#17804a"))
    return ('<div class="card"><div class="top"><span class="rank">#%s</span><span class="sym">%s</span>'
            '<span class="kind %s">%s</span>%s<span class="name">%s</span>%s</div>'
            '<div class="sub">%s</div><ul class="why2">%s</ul>%s%s%s%s</div>' % (
                e(r.get("rank")), e(sym(r["symbol"])), e(p.get("side")), e(p.get("kind")), status_pill(r.get("status")),
                e(r.get("name")), price_line(r), tech, "".join("<li>%s</li>" % e(w) for w in p.get("why") or []),
                checks_block(r.get("checks"), r.get("qualified")), plan_block(r, p), scores(r), extras(r, lines)))


def bottom_card(r):
    b = r.get("bottom") or {}
    p = b.get("plan")
    cells = [("Support", "%s (%s)" % (rs(b.get("support")), "52-week low" if b.get("touches") == 1 else "%s touches" % b.get("touches"))),
             ("Buy zone", "%s to %s" % (rs(b["zone"][0]), rs(b["zone"][1])) if b.get("zone") else "-"),
             ("Support broken on a close below", rs(b.get("invalidation"))),
             ("Off its 52-week high", "%s%%" % e(b.get("drawdown_pct"))),
             ("RSI", "%s%s" % (e(b.get("rsi")), ", higher low (divergence)" if b.get("divergence") else ""))]
    grid = '<div class="grid">%s</div>' % "".join(
        '<div><div class="k">%s</div><div class="v">%s</div></div>' % (e(k), e(v)) for k, v in cells)
    lines = _lines((b.get("support"), "support", "#8a5a00"), (b.get("invalidation"), "breaks below", "#b3261e"),
                   ((p or {}).get("entry"), "entry", "#2f5bd3"), ((p or {}).get("target"), "target", "#17804a"))
    state = '<span class="kind %s">%s</span>' % ("long" if p else "", e(b.get("kind")))
    q = ' <span class="kind long">quality</span>' if r.get("quality") else ""
    return ('<div class="card"><div class="top"><span class="rank">#%s</span><span class="sym">%s</span>%s%s%s'
            '<span class="name">%s</span>%s</div><ul class="why2">%s</ul>%s%s%s%s</div>' % (
                e(r.get("rank")), e(sym(r["symbol"])), state, q, status_pill(r.get("status")), e(r.get("name")),
                price_line(r), "".join("<li>%s</li>" % e(w) for w in b.get("why") or []), grid,
                ('<h3 style="font-size:14px;margin:12px 0 0">Turning up: a plan</h3>' +
                 checks_block(r.get("checks"), r.get("qualified")) + plan_block(r, p)) if p else "",
                scores(r), extras(r, lines)))


def moves_block(live):
    if not live or not live.get("in_session"):
        return ""
    m = live.get("moves") or {}

    def lst(title, key, fmt):
        items = m.get(key) or []
        body = "".join("<li>%s</li>" % fmt(x) for x in items[:8]) or '<li class="empty">none right now</li>'
        return '<div class="card"><b>%s</b><ul>%s</ul></div>' % (title, body)
    return ('<h2>Moving now <span class="sub">(%s IST; a cross counts only if it holds to the close)</span></h2>'
            '<div class="moves">%s%s%s</div>' % (
                e((live.get("created_ist") or "")[11:]),
                lst("Breaking out", "breakouts", lambda x: "%s %s above %s, volume %sx" % (
                    e(sym(x["symbol"])), rs(x["price"]), rs(x["level"]), x["volume_pace"])),
                lst("Breaking down (F&O)", "breakdowns", lambda x: "%s %s below %s, volume %sx" % (
                    e(sym(x["symbol"])), rs(x["price"]), rs(x["level"]), x["volume_pace"])),
                lst("In a bottom's buy zone", "in_zone", lambda x: "%s %s in %s to %s" % (
                    e(sym(x["symbol"])), rs(x["price"]), rs(x["zone"][0]), rs(x["zone"][1])))))


def record_block(rec):
    st = rec.get("stats") or {}
    rows = rec.get("rows") or []
    tiles = [("Tracked", st.get("tracked")), ("Open now", st.get("open")), ("Closed", st.get("closed")),
             ("Target hit", st.get("targets")), ("Stop hit", st.get("stops")), ("Entry missed", st.get("missed")),
             ("Average result", "%+.2fR" % st["avg_R"] if st.get("avg_R") is not None else "-"),
             ("Win rate", pct(st.get("win_rate")))]
    t = '<div class="tiles">%s</div>' % "".join('<div class="tile"><b>%s</b><span>%s</span></div>' % (e(v if v is not None else 0), e(k))
                                                 for k, v in tiles)
    if not rows:
        return t + ('<div class="card empty">Every plan shown on the Swing and Falling market tabs is tracked here from '
                    'the day it appears: entry hit or missed (3 sessions), then target, stop or day 15.</div>')
    trs = "".join(
        "<tr><td>%s</td><td><b>%s</b></td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
        "<td>%s</td><td>%s</td><td>%s</td></tr>" % (
            e(r["created"]), e(sym(r["symbol"])), e(r["kind"]), status_pill(r["status"]), rs(r["entry"]), rs(r["stop"]),
            rs(r["target"]), rs(r.get("last_price")), e(r.get("entered", "")), e(r.get("closed", "")),
            ("%+.2fR (%+.1f%%)" % (r["result_R"], r["result_pct"])) if r.get("result_R") is not None else "")
        for r in rows)
    return t + ('<div class="card tbl"><table><tr><th>Signal</th><th>Stock</th><th>Setup</th><th>Status</th><th>Entry</th>'
                '<th>Stop</th><th>Target</th><th>Last</th><th>Entered</th><th>Closed</th><th>Result</th></tr>%s</table></div>' % trs)


def k(x):
    """A strike without a trailing .0: 1190.0 -> 1190, 162.5 stays."""
    return e(int(x) if x is not None and float(x).is_integer() else x)


def option_card(o):
    p = o["plan"]
    typ = o["type"]
    kind = '<span class="kind %s">%s</span>' % ("long" if typ == "CE" else "short", "CALL" if typ == "CE" else "PUT")
    head = ('<div class="top"><span class="sym">%s</span>%s<span class="name">%s</span>'
            '<span class="px">%s</span></div>' % (e(sym(o["symbol"])), kind, e(o.get("name")), rs(o.get("spot"))))
    plan = ('<div class="sub">Stock plan (%s list, score %s): %s, entry %s %s, stop %s, target %s, ~%s sessions, '
            'target first in %s of replays.</div>' % (
                e(o.get("source")), e(o.get("score")), e(p.get("kind")), "above" if typ == "CE" else "below",
                rs(p.get("entry")), rs(p.get("stop")), rs(p.get("target")), e(p.get("est_days") or "?"), pct(o.get("p_target"))))
    cap = ('<div class="note" style="margin:8px 0">Clears every check, but the open slots are full (at most %s trades open '
           'or waiting): shown, not taken.</div>' % e(o.get("max_open", 3))) if o.get("capacity") else ""
    ivr = (" &middot; IV rank %s" % e(o["iv_rank"])) if o.get("iv_rank") is not None else ""
    chain = ('<div class="sub">Expiry <b>%s</b> (%s days) &middot; lot size <b>%s shares</b> &middot; stock\'s realised '
             'volatility %s%%%s &middot; put-call ratio %s &middot; most call OI at %s &middot; most put OI at %s</div>' % (
                 e(o["expiry"]), e(o["dte"]), format(o["lot"], ","), e(o.get("hv20")), ivr, e(o.get("pcr")),
                 k(o.get("call_wall")), k(o.get("put_wall"))))
    t = o.get("trade")
    trade = ""
    if t:
        name = ("Buy %s %s" % (k(t["buy"]), typ) if t["structure"] == "single" else
                "Buy %s %s, sell %s %s (debit spread)" % (k(t["buy"]), typ, k(t["sell"]), typ))
        budget = o.get("budget") or 0
        tp, sl = (o.get("take_profit_pct") or 60) / 100.0, (o.get("stop_pct") or 40) / 100.0
        cells = [("Cost (the most a gap can lose)", "%s a share = <b>%s a lot</b>" % (rs(t["cost"]), rs(t["cost_lot"], 0))),
                 ("Planned loss at the -%d%% stop" % round(100 * sl),
                  '<span class="dn">-%s a lot</span>' % rs(t["cost_lot"] * sl, 0)),
                 ("Lots within your %s" % rs(budget, 0), e(t.get("lots_in_budget"))),
                 ("If the stock reaches the target", '<span class="up">+%s a lot</span>' % rs(t["gain_lot"], 0)),
                 ("If the stock hits its stop", '<span class="dn">-%s a lot</span>' % rs(t["loss_lot"], 0)),
                 ("Reward : risk (stock target vs stock stop)", e(t["rr"])), ("Break-even at expiry", rs(t["breakeven"]))]
        if t.get("max_profit_lot"):
            cells.insert(3, ("Most it can make", "%s a lot" % rs(t["max_profit_lot"], 0)))
        cells.append(("Exits", "take profit at %s a lot (+%d%%), cut at %s (-%d%%), or at the stock's target or stop, "
                               "or %s days before expiry, whichever comes first" % (
                                   rs(t["cost_lot"] * (1 + tp), 0), round(100 * tp), rs(t["cost_lot"] * (1 - sl), 0),
                                   round(100 * sl), e(o.get("exit_dte") or 7))))
        trade = ('<div class="changes"><b>The trade: %s</b></div><div class="grid">%s</div>' % (name, "".join(
            '<div><div class="k">%s</div><div class="v">%s</div></div>' % (e(a), b) for a, b in cells)))
    sp_rows = "".join(
        "<tr%s><td>%s / %s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            ' style="font-weight:700;background:var(--good-bg)"' if t and t.get("sell") == s["sell"] and t["buy"] == s["buy"]
            else (' style="color:var(--muted)"' if s["fails"] else ""),
            k(s["buy"]), k(s["sell"]), rs(s["cost_lot"], 0), rs(s["max_profit_lot"], 0),
            '<span class="up">+%s</span>' % rs(s["gain_lot"], 0), '<span class="dn">-%s</span>' % rs(s["loss_lot"], 0),
            e(s["rr"]), rs(s["breakeven"]), e("; ".join(s["fails"]) or "passes"))
        for s in o.get("spreads") or [])
    spreads = ('<details><summary>Debit spreads (%d)</summary><div class="tbl"><table><tr><th>Buy / sell</th>'
               '<th>Cost a lot</th><th>Most it can make</th><th>At target</th><th>At stop</th><th>R:R</th>'
               '<th>Break-even</th><th>Checks</th></tr>%s</table></div></details>' % (len(o.get("spreads") or []), sp_rows)
               if sp_rows else "")
    trs = ""
    for s in o.get("strikes") or []:
        trs += ("<tr%s><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%.1f%%</td><td>%s%s</td><td>%s</td>"
                "<td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                    ' style="color:var(--muted)"' if s["fails"] else ' style="font-weight:700"', k(s["strike"]),
                    rs(s["ask"]), rs(s["premium_lot"], 0), e(s["delta"]), rs(s["theta_lot_day"], 0), s["iv"],
                    format(s["oi_lots"], ","), " (%+.0f%%)" % s["oi_chg_pct"] if s.get("oi_chg_pct") is not None else "",
                    e(s.get("buildup") or "-"), '<span class="up">+%s</span>' % rs(s["gain_lot"], 0) if s["gain_lot"] >= 0
                    else '<span class="dn">%s</span>' % rs(s["gain_lot"], 0), '<span class="dn">-%s</span>' % rs(s["loss_lot"], 0),
                    e(s["rr"] if s["rr"] is not None else "-"), e("; ".join(s["fails"]) or "passes")))
    singles = ('<details><summary>Single %ss (%d strikes)</summary><div class="tbl"><table><tr><th>Strike</th><th>Price a share</th>'
               '<th>Value of 1 lot</th><th>Delta</th><th>Theta a lot/day</th><th>IV</th><th>OI lots (chg)</th><th>Build-up</th>'
               '<th>At target</th><th>At stop</th><th>R:R</th><th>Checks</th></tr>%s</table></div></details>' % (
                   "call" if typ == "CE" else "put", len(o.get("strikes") or []), trs) if trs else "")
    notes = "".join('<div class="note" style="margin:8px 0">%s</div>' % e(n) for n in o.get("notes") or [])
    return '<div class="card">%s%s%s%s%s%s%s%s%s</div>' % (head, plan, checks_block(o.get("checks"), o.get("qualified")),
                                                          cap, chain, notes, trade, spreads, singles)


def options_block(opts):
    if not opts:
        return ('<div class="card empty">The options screen needs the Upstox token and runs with the swing scan. '
                'It appears after the next scan.</div>')
    r = opts.get("rules") or {}
    d = r.get("direction") or {}
    intro = (
        '<div class="note"><b>How an options trade is chosen</b> (a rules screen, not advice; the decision is yours). '
        'Every liquid F&amp;O stock with a swing plan is screened on its own. <b>Direction</b>: target first in %d%%+ of '
        '10,000 replays and an expectancy of %+.2fR+; the same rule not losing money on this stock; the market agrees (a '
        'call in a falling Nifty needs a stock stronger than %d%% of others, a put a Nifty not rising and a weaker stock); '
        'fundamentals not against it; and <b>no results due</b> (implied volatility usually collapses right after '
        'results). <b>Expiry</b>: the nearest monthly one %s+ days away that leaves %s days after the plan\'s exit. '
        '<b>Structure</b>, within your %s a trade: a <b>debit spread</b> by default (buy near the money, sell at or before '
        'the target; pay at most half the width; reward:risk %.1f+; break-even inside the target; both legs liquid; at most '
        '%d%% lost to time decay by the estimated day; no OI wall before the sold strike). A <b>single</b> call or put only '
        'when it fits the budget and its IV is no higher than the stock\'s realised volatility. <b>Entry</b>: only after '
        'the stock trades through the plan\'s entry trigger within 3 sessions, and only if the trade still clears every '
        'check then. <b>Exit</b>, whichever comes first: +%s%% of the cost, -%s%% of it, the stock\'s target or stop, or '
        '%s days before expiry. At most %s trades open at once.</div>'
        '<div class="note">The values at the target and stop are Black-Scholes at each strike\'s own IV on the estimated '
        'day; real prices will differ. A spread caps the profit; a bought option can lose its whole cost. Updated %s IST.</div>'
        % (100 * d.get("min_p_target", 0), d.get("min_avg_r", 0), d.get("rs_long_in_down_market", 0), e(r.get("min_dte")),
           e(r.get("buffer")), rs(r.get("budget"), 0), r.get("min_rr_spread") or 1.5, r.get("max_decay_pct") or 25,
           e(r.get("take_profit_pct")), e(r.get("stop_pct")), e(r.get("exit_dte")), e(r.get("max_open")),
           e(opts.get("created_ist"))))

    def group(rows, none_msg):
        for o in rows:
            o.setdefault("max_open", r.get("max_open"))
        q = [o for o in rows if o.get("qualified")]
        rest = [o for o in rows if not o.get("qualified")]
        body = "".join(option_card(o) for o in q) or '<div class="card empty">%s</div>' % none_msg
        if rest:
            body += ('<details class="watch"><summary>%d that did not clear every check</summary>'
                     '<div class="sub">Not recommended. Each card lists the checks it failed.</div>%s</details>'
                     % (len(rest), "".join(option_card(o) for o in rest)))
        return body
    calls = group(opts.get("calls") or [], "No call trade clears every check today. Sitting out is the plan.")
    puts = group(opts.get("puts") or [], "No put trade clears every check today. Sitting out is the plan.")
    skipped = ""
    if opts.get("skipped"):
        skipped = '<details><summary>%d skipped</summary><ul class="news">%s</ul></details>' % (
            len(opts["skipped"]), "".join("<li>%s</li>" % e(x) for x in opts["skipped"]))
    return intro + "<h2>Calls</h2>" + calls + "<h2>Puts</h2>" + puts + skipped


def options_record_block(rec):
    head = '<h2>Equity options</h2>'
    if not rec or not rec.get("rows"):
        return head + ('<div class="card empty">Every options trade that clears every check is tracked here from the day it '
                       'appears: bought once its stock triggers the entry (spread: near leg at the ask, far leg at the bid), '
                       'closed at +60%, -40%, the stock\'s target or stop, or 7 days before expiry.</div>')
    st = rec["stats"]
    tiles = [("Tracked", st["tracked"]), ("Waiting or open", st["open"]), ("Closed", st["closed"]),
             ("Not entered", st["missed"]), ("Closed result, per lot each", rs(st["total_lot"], 0)),
             ("Average closed result", "%+.1f%%" % st["avg_pct"] if st.get("avg_pct") is not None else "-"),
             ("Win rate", pct(st.get("win_rate"))), ("Open trades now, per lot each", rs(st["open_mark_lot"], 0))]
    t = '<div class="tiles">%s</div>' % "".join('<div class="tile"><b>%s</b><span>%s</span></div>' % (e(v), e(n)) for n, v in tiles)
    trs = ""
    for r in rec["rows"]:
        res = ""
        if r.get("result_lot") is not None:
            res = '<span class="%s">%s (%+.1f%%)</span>' % ("up" if r["result_lot"] >= 0 else "dn", rs(r["result_lot"], 0),
                                                           r["result_pct"] or 0)
        elif r.get("mark_lot") is not None:
            res = 'now <span class="%s">%s (%+.1f%%)</span>' % ("up" if r["mark_lot"] >= 0 else "dn", rs(r["mark_lot"], 0),
                                                              r.get("mark_pct") or 0)
        label = "%s %s" % (k(r["strike"]), r["type"])
        if r.get("short_strike"):
            label = "%s/%s %s spread" % (k(r["strike"]), k(r["short_strike"]), r["type"])
        now = r.get("exit") if r.get("exit") is not None else r.get("last")
        trs += ("<tr><td>%s</td><td><b>%s %s</b><br><span class='sub'>exp %s</span></td><td>%s shares</td><td>%s%s</td>"
                "<td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                    e(r["created"]), e(sym(r["symbol"])), e(label), e(r["expiry"]), format(r["lot"], ","),
                    status_pill(r["status"]), ("<br><span class='sub'>%s</span>" % e(r["skip_reason"])) if r.get("skip_reason") else "",
                    e(r.get("stock_status")), per_lot(r["signal_ask"], r["lot"]), per_lot(r.get("fill"), r["lot"]),
                    per_lot(now, r["lot"]), res, e((r.get("closed_ist") or r.get("entered_ist") or r.get("last_ist") or "")[5:])))
    return head + t + ('<div class="card tbl"><table><tr><th>Signal</th><th>Trade</th><th>Lot size</th><th>Status</th>'
                       '<th>Stock plan</th><th>At signal</th><th>Bought</th><th>Sold / now</th><th>Result per lot</th>'
                       '<th>Updated</th></tr>%s</table></div><div class="sub">Prices a share, and per lot (price &times; lot '
                       'size). Spreads: near leg at the ask and far leg at the bid to open, the reverse to close. Prices of '
                       'the 30-minute update after the move, so real fills differ. One lot each.</div>' % trs)


def per_lot(price, lot):
    if not price:
        return "-"
    return "%s<br><b>%s a lot</b>" % (rs(price), rs(price * lot, 0))


def tabs(doc):
    """(swing tab, falling-market tab, track-record tab, options tab, strip above the tabs)."""
    if not doc:
        none = '<div class="card empty">The first swing scan runs after today\'s close (15:50 IST).</div>'
        return none, none, none, none, ""
    c, src, nifty = doc.get("counts") or {}, doc.get("sources") or {}, doc.get("nifty") or {}
    tiles = [("NSE stocks quoted", "%s of %s" % (format(c.get("quoted", 0), ","), format(c.get("universe", 0), ","))),
             ("Liquid (20-day turnover %s cr+)" % (doc.get("config") or {}).get("min_turnover_cr", 5), format(c.get("liquid", 0), ",")),
             ("With fundamentals", format(c.get("with_fundamentals", 0), ",")),
             ("Nifty 50: 3-month change, trend", "%s%%, %s" % (e(nifty.get("ret_63")), e(nifty.get("trend", "-")))),
             ("Data", "%s (Upstox %s)" % (e(src.get("quotes")), e(src.get("upstox"))))]
    top = '<div class="tiles">%s</div>' % "".join('<div class="tile"><b>%s</b><span>%s</span></div>' % (e(v), e(k)) for k, v in tiles)
    if src.get("upstox") == "token rejected":
        top = ('<div class="note">Upstox rejected the token, so Yahoo was used. Make a new Analytics Token in Upstox '
               'Developer Apps and update the UPSTOX_ANALYTICS_TOKEN secret on GitHub.</div>') + top
    sub = '<div class="sub">Scan of the %s session, made %s IST.</div>' % (e(doc.get("session")), e(doc.get("created_ist")))
    show = (doc.get("config") or {}).get("show", 10)

    def section(title, note, rows, card, none_msg):
        q = [r for r in rows if r.get("qualified")]
        rest = [r for r in rows if not r.get("qualified")]
        body = "".join(card(r) for r in q) or '<div class="card empty">%s</div>' % none_msg
        if rest:
            body += ('<details class="watch"><summary>Watchlist: %d setups that did not clear every check</summary>'
                     '<div class="sub">Not recommended. Each card lists the checks it failed.</div>%s</details>'
                     % (len(rest), "".join(card(r) for r in rest[:show])))
        return '<h2>%s</h2><div class="sub">%s</div>%s' % (title, note, body)

    G = (doc.get("config") or {}).get("gate") or {}
    gate_note = ('<div class="note">Only setups that clear <b>every</b> check are recommended; no trade is a valid '
                 'result. The checks: replay expectancy %+.2fR or more and the target first in %d%%+ of 10,000 replays; '
                 'the same rule worked on this stock before (%d+ times, %+.2fR+ average, at least as many targets as '
                 'stops); fundamentals agree (longs %d+, shorts %d or less, bottoms %d+); the market agrees (in a '
                 'falling Nifty a long must be stronger than %d%% of stocks; a short needs a Nifty not rising and a '
                 'weak stock); Rs %s cr+ traded a day; reward:risk %.1f+. Nothing guarantees a profit: these raise the '
                 'odds, they do not remove the risk.</div>' % (
                     G.get("min_avg_r", 0), 100 * G.get("min_p_target", 0), G.get("min_hist_trades", 0),
                     G.get("min_hist_avg_r", 0), G.get("long_min_fund", 0), G.get("short_max_fund", 0),
                     G.get("bottom_min_fund", 0), G.get("rs_long_in_down_market", 0), G.get("min_turnover_cr", 0),
                     G.get("min_rr", 0))) if G else ""

    bull = gate_note + moves_block(doc.get("live")) + section(
        "Recommended bullish swings", "All liquid NSE stocks: breakouts, pullbacks in an uptrend, bounces off support, "
        "that clear every check.", doc.get("bull") or [], trade_card,
        "No bullish setup clears every check today. Sitting out is the plan.") + sub
    bots = doc.get("bottoms") or []
    watch_bots = [r for r in bots if not (r.get("bottom") or {}).get("plan")]
    falling = gate_note + section(
        "Recommended breakdowns (F&amp;O stocks)", "Stocks with options only: breakdowns below support and failed "
        "rallies in a downtrend that clear every check.", doc.get("bear") or [], trade_card,
        "No breakdown clears every check today. Sitting out is the plan.") + section(
        "Bottoms turning up", "Stocks 20%+ off their high that held support and closed above their 10-day high and "
        "20-day EMA, and clear every check.", [r for r in bots if (r.get("bottom") or {}).get("plan")], bottom_card,
        "No bottom has turned up and cleared every check today.") + (
        '<h2>Bottoms: support zones to watch</h2><div class="sub">Not trade signals: stocks 20%+ off their 52-week '
        'high sitting on support (RSI 40 or under, or a bullish divergence), with the buy zone and the close that would '
        'break the support. One that turns up and clears every check moves to the list above.</div>' +
        ("".join(bottom_card(r) for r in watch_bots[:show]) or '<div class="card empty">None today.</div>')) + sub
    record = ("<h2>Stock plans</h2>" + record_block(doc.get("record") or {}) +
              options_record_block(doc.get("options_record")))
    if doc.get("errors"):
        record += '<details><summary>%d data problems</summary><ul class="news">%s</ul></details>' % (
            len(doc["errors"]), "".join("<li>%s</li>" % e(x) for x in doc["errors"]))
    return bull, falling, record, options_block(doc.get("options")), top


JS = r"""
(function(){
var tabs=document.querySelectorAll("nav.tabs a");
function show(name){var ok=false;tabs.forEach(function(a){var on=a.dataset.tab===name;a.classList.toggle("on",on);if(on)ok=true});
  if(!ok)return show("swing");
  document.querySelectorAll("section.tab").forEach(function(s){s.hidden=s.id!=="tab-"+name})}
tabs.forEach(function(a){a.addEventListener("click",function(ev){ev.preventDefault();show(a.dataset.tab);
  try{history.replaceState(null,"","#"+a.dataset.tab)}catch(e){}})});
show((location.hash||"#swing").slice(1));
var data=null,lib=null;
function loadLib(){if(lib)return lib;lib=new Promise(function(ok,bad){var s=document.createElement("script");
  s.src="__LIB__";s.onload=ok;s.onerror=bad;document.head.appendChild(s)});return lib}
function loadData(){if(data)return data;data=fetch("swing-charts.json",{cache:"no-store"}).then(function(r){return r.json()});return data}
function css(v){return getComputedStyle(document.documentElement).getPropertyValue(v).trim()}
document.querySelectorAll("details.chartbox").forEach(function(d){d.addEventListener("toggle",function(){
  if(!d.open||d.dataset.done)return;d.dataset.done="1";var box=d.querySelector(".chart");
  Promise.all([loadLib(),loadData()]).then(function(r){var bars=r[1][d.dataset.sym];
    if(!bars){box.textContent="No chart data for this stock.";return}
    var ch=LightweightCharts.createChart(box,{autoSize:true,layout:{background:{color:"transparent"},textColor:css("--muted")},
      grid:{vertLines:{color:css("--line")},horzLines:{color:css("--line")}},timeScale:{borderColor:css("--line")},
      rightPriceScale:{borderColor:css("--line")}});
    var lines=JSON.parse(d.dataset.lines||"[]"),ps=lines.map(function(l){return l.p});
    var s=ch.addCandlestickSeries({upColor:css("--good"),downColor:css("--bad"),borderVisible:false,
      wickUpColor:css("--good"),wickDownColor:css("--bad"),
      autoscaleInfoProvider:function(orig){var r=orig();if(r&&ps.length){   // keep the target and stop in view
        r.priceRange.minValue=Math.min.apply(null,[r.priceRange.minValue].concat(ps));
        r.priceRange.maxValue=Math.max.apply(null,[r.priceRange.maxValue].concat(ps))}return r}});
    s.setData(bars.map(function(b){return{time:b[0],open:b[1],high:b[2],low:b[3],close:b[4]}}));
    lines.forEach(function(l){s.createPriceLine({price:l.p,color:l.c,lineWidth:1,lineStyle:2,
      axisLabelVisible:true,title:l.t})});
    ch.timeScale().fitContent();
  }).catch(function(){box.textContent="Could not load the chart."})})});
})();
""".replace("__LIB__", CHART_LIB)
