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
            '<div class="sub">%s</div><ul class="why2">%s</ul>%s%s%s</div>' % (
                e(r.get("rank")), e(sym(r["symbol"])), e(p.get("side")), e(p.get("kind")), status_pill(r.get("status")),
                e(r.get("name")), price_line(r), tech, "".join("<li>%s</li>" % e(w) for w in p.get("why") or []),
                plan_block(r, p), scores(r), extras(r, lines)))


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
                ('<h3 style="font-size:14px;margin:12px 0 0">Turning up: a plan</h3>' + plan_block(r, p)) if p else "",
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
    kind = '<span class="kind %s">%s</span>' % ("long" if o["type"] == "CE" else "short",
                                                "CALL" if o["type"] == "CE" else "PUT")
    head = ('<div class="top"><span class="sym">%s</span>%s<span class="name">%s</span>'
            '<span class="px">%s</span></div>' % (e(sym(o["symbol"])), kind, e(o.get("name")), rs(o.get("spot"))))
    plan = ('<div class="sub">From the %s list (#%s, score %s): %s, stock entry %s %s, stop %s, target %s, ~%s sessions, '
            'target first in %s of replays.</div>' % (
                e(o.get("source")), e(o.get("rank")), e(o.get("score")), e(p.get("kind")),
                "above" if o["type"] == "CE" else "below", rs(p.get("entry")), rs(p.get("stop")), rs(p.get("target")),
                e(p.get("est_days") or "?"), pct(o.get("p_target"))))
    chain = ('<div class="sub">Expiry <b>%s</b> (%d days) &middot; lot %s &middot; put-call ratio %s &middot; most call OI '
             'at %s &middot; most put OI at %s</div>' % (e(o["expiry"]), o["dte"], e(o["lot"]), e(o.get("pcr")),
                                                       k(o.get("call_wall")), k(o.get("put_wall"))))
    if o.get("void"):
        watch = ""
    elif o.get("watch"):
        lo, hi = o["watch"]
        watch = ('<div class="changes"><b>Strike range to watch: %s%s</b> &middot; best reward:risk by the numbers: '
                 '<b>%s %s</b></div>' % (k(lo), "" if lo == hi else " to %s" % k(hi), k(o["best"]), e(o["type"])))
    else:
        watch = '<div class="changes">No strike passes the liquidity and delta filters for this expiry.</div>'
    notes = "".join('<div class="note" style="margin:8px 0">%s</div>' % e(n) for n in o.get("notes") or [])
    trs = ""
    for s in o.get("strikes") or []:
        best = s["strike"] == o.get("best")
        style = ' style="font-weight:700;background:var(--good-bg)"' if best else (
            ' style="color:var(--muted)"' if not s["ok"] else "")
        trs += ("<tr%s><td>%s%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s%s</td><td>%s</td>"
                "<td>%s</td><td>%s</td><td>%s</td><td>%s (%+.1f%%)</td></tr>" % (
                    style, k(s["strike"]), " (%s)" % e(", ".join(s["why_not"])) if s["why_not"] else "",
                    rs(s["premium_lot"], 0), e(s["delta"]), rs(s["theta_lot_day"], 0), rs(s["vega_lot"], 0),
                    "%.1f%%" % s["iv"], format(s["oi_lots"], ","),
                    " (%+.0f%%)" % s["oi_chg_pct"] if s.get("oi_chg_pct") is not None else "", e(s.get("buildup") or "-"),
                    '<span class="up">+%s</span>' % rs(s["gain_lot"], 0) if s["gain_lot"] >= 0 else '<span class="dn">%s</span>' % rs(s["gain_lot"], 0),
                    '<span class="dn">-%s</span>' % rs(s["loss_lot"], 0) if s["loss_lot"] >= 0 else '<span class="up">+%s</span>' % rs(-s["loss_lot"], 0),
                    e(s["rr"] if s["rr"] is not None else "-"), rs(s["breakeven"]), s["be_move_pct"]))
    table = ('<div class="tbl"><table><tr><th>Strike</th><th>Premium a lot</th><th>Delta</th><th>Theta a lot/day</th>'
             '<th>Vega a lot</th><th>IV</th><th>OI lots (chg)</th><th>Build-up</th><th>Stock at target</th>'
             '<th>Stock at stop</th><th>R:R</th><th>Break-even at expiry (move)</th></tr>%s</table></div>' % trs)
    return '<div class="card">%s%s%s%s%s%s</div>' % (head, plan, chain, watch, notes, table)


def options_block(opts):
    if not opts:
        return ('<div class="card empty">The options screen needs the Upstox token and runs with the swing scan. '
                'It appears after the next scan.</div>')
    r = opts.get("rules") or {}
    intro = ('<div class="note">A rules screen, not advice: it lists the strikes that pass these filters, with their '
             'numbers; whether to trade, and which, is your call. Expiry: the nearest monthly one at least %s days away '
             'that still leaves %s days after the plan\'s estimated exit. Strikes: delta %.2f to %.2f, bid-ask spread '
             '%.0f%% or less, open interest of %s+ lots and at least a tenth of the busiest tradable strike. "Stock at target" and '
             '"Stock at stop" are what one lot would be worth on its estimated day (stop: halfway), from Black-Scholes at '
             'that strike\'s own IV, minus the premium. IV usually drops after a big move or results, which makes a '
             'bought option worth less than shown. Buying options can lose the whole premium. Updated %s IST.</div>' % (
                 e(r.get("min_dte")), e(r.get("buffer")), (r.get("delta") or [0, 0])[0], (r.get("delta") or [0, 0])[1],
                 r.get("max_spread_pct") or 0, e(r.get("min_lots")), e(opts.get("created_ist"))))
    calls = "".join(option_card(o) for o in opts.get("calls") or []) or '<div class="card empty">No bullish F&amp;O plan today.</div>'
    puts = "".join(option_card(o) for o in opts.get("puts") or []) or '<div class="card empty">No bearish F&amp;O plan today.</div>'
    skipped = ""
    if opts.get("skipped"):
        skipped = '<details><summary>%d skipped</summary><ul class="news">%s</ul></details>' % (
            len(opts["skipped"]), "".join("<li>%s</li>" % e(x) for x in opts["skipped"]))
    return intro + "<h2>Calls: bullish swing plans</h2>" + calls + "<h2>Puts: breakdown plans</h2>" + puts + skipped


def options_record_block(rec):
    head = '<h2>Equity options</h2>'
    if not rec or not rec.get("rows"):
        return head + ('<div class="card empty">The best strike on each Equity Options card is tracked here from the day '
                       'it appears: bought at the ask once its stock triggers the entry, sold at the bid when the stock '
                       'plan hits its target or stop, reaches day 15, or at expiry.</div>')
    st = rec["stats"]
    tiles = [("Tracked", st["tracked"]), ("Waiting or open", st["open"]), ("Closed", st["closed"]),
             ("Entry missed", st["missed"]), ("Closed result, per lot each", rs(st["total_lot"], 0)),
             ("Average closed result", "%+.1f%%" % st["avg_pct"] if st.get("avg_pct") is not None else "-"),
             ("Win rate", pct(st.get("win_rate"))), ("Open trades now, per lot each", rs(st["open_mark_lot"], 0))]
    t = '<div class="tiles">%s</div>' % "".join('<div class="tile"><b>%s</b><span>%s</span></div>' % (e(v), e(k)) for k, v in tiles)
    trs = ""
    for r in rec["rows"]:
        res = ""
        if r.get("result_lot") is not None:
            res = '<span class="%s">%s (%+.1f%%)</span>' % ("up" if r["result_lot"] >= 0 else "dn", rs(r["result_lot"], 0),
                                                           r["result_pct"] or 0)
        elif r.get("mark_lot") is not None:
            res = 'now <span class="%s">%s (%+.1f%%)</span>' % ("up" if r["mark_lot"] >= 0 else "dn", rs(r["mark_lot"], 0),
                                                              r.get("mark_pct") or 0)
        trs += ("<tr><td>%s</td><td><b>%s %s %s</b><br><span class='sub'>exp %s, lot %s</span></td><td>%s</td><td>%s</td>"
                "<td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                    e(r["created"]), e(sym(r["symbol"])), k(r["strike"]), e(r["type"]), e(r["expiry"]), e(r["lot"]),
                    status_pill(r["status"]), e(r.get("stock_status")), rs(r["signal_ask"]),
                    rs(r.get("fill")) if r.get("fill") else "-",
                    rs(r.get("exit")) if r.get("exit") is not None else (rs(r.get("last")) if r.get("last") else "-"),
                    res, e((r.get("closed_ist") or r.get("entered_ist") or r.get("last_ist") or "")[5:])))
    return head + t + ('<div class="card tbl"><table><tr><th>Signal</th><th>Option</th><th>Status</th><th>Stock plan</th>'
                       '<th>Premium at signal</th><th>Bought</th><th>Sold / now</th><th>Per lot</th><th>Updated</th></tr>'
                       '%s</table></div><div class="sub">Bought at the ask, sold at the bid, at the 30-minute update after '
                       'the stock\'s move, so real fills can differ. One lot each.</div>' % trs)


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

    def section(title, note, rows, card):
        body = "".join(card(r) for r in rows[:show]) or '<div class="card empty">Nothing matches today.</div>'
        more = rows[show:]
        if more:
            body += '<details><summary>%d more</summary>%s</details>' % (len(more), "".join(card(r) for r in more))
        return '<h2>%s</h2><div class="sub">%s</div>%s' % (title, note, body)

    bull = moves_block(doc.get("live")) + section(
        "Bullish swing setups", "All liquid NSE stocks: breakouts, pullbacks in an uptrend, bounces off support. "
        "Ranked half on technicals, half on fundamentals.", doc.get("bull") or [], trade_card) + sub
    falling = section(
        "Breakdowns (F&amp;O stocks)", "Stocks with options only: breakdowns below support and failed rallies in a "
        "downtrend. The levels are the stock's; picking a put (strike, expiry) is your call. Ranked on weak technicals "
        "and weak fundamentals.", doc.get("bear") or [], trade_card) + section(
        "Bottoms: support to watch", "All liquid stocks 20%+ off their 52-week high, sitting on support with RSI 40 or "
        "under or a bullish divergence. 'Turning up' once it closes above its 10-day high and 20-day EMA. Ranked "
        "60% on fundamentals, for a later swing or a long-term buy.", doc.get("bottoms") or [], bottom_card) + sub
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
