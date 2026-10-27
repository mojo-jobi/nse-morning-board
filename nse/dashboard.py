"""docs/data.json -> docs/index.html (one self-contained page, served by GitHub Pages)."""

import html
import json
import os
import sys

SKILL_ROWS = [
    ("trader-scanner", "used", "Daily closes of every NSE EQ stock; 20-day breakout, bull flag, 20-day average, oversold"),
    ("trader-news", "used", "Headline parsing and tags over Indian market feeds (ET, Moneycontrol, Mint, BS, Google News)"),
    ("trader-entry", "used", "15-minute opening range (9:15-9:30) and the first 5-minute close above its high"),
    ("trader-exit", "used", "Stop at the opening-range midpoint, target at 2R"),
    ("trader-timemachine", "used", "10,000 replays of the rest of the day from the stock's last 60 days, plus the same rule on each past day"),
    ("trader-budget", "used", "Whole shares inside the max loss per trade, position cap and cash"),
    ("trader-risk", "used", "PASS or BLOCK against config.json (stop, max loss, reward:risk, entry window)"),
    ("trader-alerts", "used", "Stop, target and flat-by levels for each plan"),
    ("trader-analyst", "partial", "Reads SEC EDGAR, where Indian companies do not file; results are flagged from the news instead"),
    ("trader-broker", "not used", "Talks to Alpaca (US brokers). Nothing here places an order: you trade on your own broker"),
    ("trader-pelosi", "not used", "US Congress trades say nothing about NSE stocks"),
]

CSS = """
:root{--bg:#f7f7f5;--card:#fff;--ink:#1b1b19;--muted:#6b6b66;--line:#e4e3de;--accent:#2f5bd3;
--good:#17804a;--good-bg:#e5f4ea;--bad:#b3261e;--bad-bg:#fbe7e5;--warn:#8a5a00;--warn-bg:#fdf1d6;--neutral:#d9d8d2}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#141413;--card:#1e1e1c;--ink:#ecebe6;
--muted:#a3a29b;--line:#33332f;--accent:#8aa8ff;--good:#5cc98a;--good-bg:#173323;--bad:#ff8a80;--bad-bg:#3a1c1a;
--warn:#f0c062;--warn-bg:#3a2e14;--neutral:#45453f}}
:root[data-theme="dark"]{--bg:#141413;--card:#1e1e1c;--ink:#ecebe6;--muted:#a3a29b;--line:#33332f;--accent:#8aa8ff;
--good:#5cc98a;--good-bg:#173323;--bad:#ff8a80;--bad-bg:#3a1c1a;--warn:#f0c062;--warn-bg:#3a2e14;--neutral:#45453f}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:20px 16px 48px}
h1{font-size:22px;margin:0 0 2px}h2{font-size:16px;margin:28px 0 10px}
.sub{color:var(--muted);font-size:13px}
.note{background:var(--warn-bg);color:var(--warn);border-radius:8px;padding:10px 12px;font-size:13px;margin:14px 0}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-top:14px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.tile b{display:block;font-size:20px;font-variant-numeric:tabular-nums}.tile span{color:var(--muted);font-size:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;margin:10px 0}
.top{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}
.rank{font-weight:700;color:var(--muted);min-width:26px}.sym{font-weight:700;font-size:17px}
.name{color:var(--muted);font-size:13px;flex:1;min-width:140px}
.px{font-variant-numeric:tabular-nums;font-weight:600}.up{color:var(--good)}.dn{color:var(--bad)}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0}
.chip{font-size:12px;border:1px solid var(--line);border-radius:999px;padding:1px 8px;color:var(--muted)}
.chip.tag{color:var(--accent);border-color:var(--accent)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-top:10px}
.k{color:var(--muted);font-size:12px}.v{font-variant-numeric:tabular-nums;font-weight:600}
.pill{display:inline-block;font-size:12px;font-weight:700;border-radius:6px;padding:1px 8px}
.pass{background:var(--good-bg);color:var(--good)}.block{background:var(--bad-bg);color:var(--bad)}
.wait{background:var(--warn-bg);color:var(--warn)}
.odds{display:flex;height:10px;border-radius:5px;overflow:hidden;background:var(--neutral);margin:6px 0 4px}
.odds i{display:block}.o-t{background:var(--good)}.o-s{background:var(--bad)}.o-n{background:var(--neutral)}
.legend{font-size:12px;color:var(--muted)}
details{margin-top:10px}summary{cursor:pointer;color:var(--accent);font-size:13px}
ul.news{margin:6px 0 0;padding-left:18px;font-size:13px}ul.news li{margin:3px 0}
ul.news a{color:var(--ink)}ul.news .src{color:var(--muted)}
.why{font-size:12px;color:var(--muted);margin-top:4px}
table{width:100%;border-collapse:collapse;font-size:13px}td,th{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}
th{color:var(--muted);font-weight:600}.st-used{color:var(--good)}.st-partial{color:var(--warn)}.st-not{color:var(--muted)}
"""


def e(x):
    return html.escape("" if x is None else str(x))


def rs(x, dp=0):
    if x is None:
        return "-"
    x = float(x)
    s = ("{:,.%df}" % dp).format(abs(x))
    return ("-" if x < 0 else "") + "₹" + s


def pct(x):
    return "-" if x is None else "%.0f%%" % (100 * x)


def trade_block(t):
    if not t:
        return '<div class="why">Trade numbers come at 9:35 IST, once the 15-minute opening range is set.</div>'
    st = t.get("status")
    if st in ("error", "no-data", "expired") or "plan" not in t:
        msg = t.get("refused") or t.get("reason") or st
        return '<div class="why"><span class="pill wait">%s</span> %s</div>' % (e((st or "").upper()), e(msg))
    p, tm, sz, rk = t["plan"], t.get("timemachine", {}), t.get("sizing", {}), t.get("risk", {})
    head = '<span class="pill %s">%s</span> ' % ("pass" if st == "triggered" else "wait", e(st.upper()))
    head += e(t.get("entry_kind"))
    orr = t.get("opening_range") or {}
    cells = [
        ("Opening range", "%s to %s" % (rs(orr.get("low"), 2), rs(orr.get("high"), 2))),
        ("Entry / stop / target", "%s / %s / %s" % (rs(p["entry"], 2), rs(p["stop"], 2), rs(p["target"], 2))),
    ]
    if sz.get("qty"):
        cells += [("Size", "%d shares (%s), bound by %s" % (sz["qty"], rs(sz["cost"]), sz["bound_by"])),
                  ("If target hits first", '<span class="up">+%s</span>' % rs(sz.get("reward"))),
                  ("If stop hits first", '<span class="dn">-%s</span>' % rs(sz.get("max_loss")))]
    else:
        cells.append(("Size", e(sz.get("refusal") or "no shares fit")))
    if t.get("rel_volume") is not None:
        cells.append(("Volume vs usual by now", "%.1fx" % t["rel_volume"]))
    grid = "".join('<div><div class="k">%s</div><div class="v">%s</div></div>' % (e(k), v if "<span" in v else e(v))
                   for k, v in cells)
    odds = ""
    if "p_target" in tm:
        pt, ps, pn = tm["p_target"], tm["p_stop"], tm["p_neither"]
        hist = tm.get("history") or {}
        odds = ('<div style="margin-top:10px"><div class="k">Time Machine: 10,000 replays to %s</div>'
                '<div class="odds"><i class="o-t" style="width:%.1f%%"></i><i class="o-s" style="width:%.1f%%"></i>'
                '<i class="o-n" style="width:%.1f%%"></i></div>'
                '<div class="legend">target first %s &middot; stop first %s &middot; neither by %s %s &middot; '
                'average %+.2fR%s</div><div class="why">%s</div>'
                '<div class="why">Same rule on the last %s sessions: fired %s times, target %s, stop %s, open at flat-by %s%s.</div></div>'
                % (e(p.get("flat_by")), 100 * pt, 100 * ps, 100 * pn, pct(pt), pct(ps), e(p.get("flat_by")), pct(pn),
                   tm.get("avg_R", 0),
                   (" (about %s a trade at this size)" % rs(sz["replay_avg"])) if sz.get("replay_avg") is not None else "",
                   e(tm.get("verdict")), hist.get("sessions", "-"), hist.get("triggered", "-"), hist.get("target", "-"),
                   hist.get("stop", "-"), hist.get("close", "-"),
                   (", average %+.2fR" % hist["avg_R"]) if hist.get("avg_R") is not None else ""))
    elif tm.get("skipped"):
        odds = '<div class="why">Time Machine skipped: %s</div>' % e(tm["skipped"])
    rv = rk.get("verdict", "-")
    risk = '<div style="margin-top:8px"><span class="pill %s">RISK %s</span> <span class="why">%s</span></div>' % (
        "pass" if rv == "PASS" else "block", e(rv), e("; ".join(rk.get("reasons") or [])))
    return '<div style="margin-top:8px">%s</div><div class="grid">%s</div>%s%s' % (head, grid, odds, risk)


def card(r):
    chg = r.get("chg_pct")
    chg_s = "" if chg is None else '<span class="%s">%+.2f%%</span>' % ("up" if chg >= 0 else "dn", chg)
    chips = "".join('<span class="chip tag">%s</span>' % e(t) for t in r.get("news_tags") or [])
    chips += "".join('<span class="chip">%s</span>' % e(s.replace("_", " ")) for s in r.get("setups") or [])
    if r.get("earnings_flag"):
        chips += '<span class="chip" style="color:var(--warn);border-color:var(--warn)">results in the news</span>'
    news = "".join('<li><a href="%s" target="_blank" rel="noopener">%s</a> <span class="src">%s%s</span></li>' % (
        e(n.get("link")), e(n.get("title")), e(n.get("source")), (", " + e(n["time"])) if n.get("time") else "")
        for n in r.get("news") or [])
    return ('<div class="card"><div class="top"><span class="rank">#%d</span><span class="sym">%s</span>'
            '<span class="name">%s</span><span class="px">%s</span>%s</div>'
            '<div class="sub">%d headlines &middot; traded %s cr yesterday (%s shares) &middot; score %s</div>'
            '<div class="chips">%s</div>%s'
            '<details><summary>Headlines (%d)</summary><ul class="news">%s</ul></details></div>'
            % (r["rank"], e(r["symbol"].replace(".NS", "")), e(r.get("name")), rs(r.get("price"), 2), chg_s,
               r.get("news_count", 0), rs(r.get("turnover_cr"), 1), "{:,}".format(r.get("volume") or 0), r.get("score"),
               chips, trade_block(r.get("trade")), len(r.get("news") or []), news))


def render(doc, path):
    cfg = doc.get("config") or {}
    show = 10
    rows = (doc.get("shortlist") or [])[:show]
    if doc.get("stage") == "closed":
        body = '<div class="note">NSE is closed today: %s</div>' % e(doc.get("closed_reason"))
    else:
        sc, nw = doc.get("scan", {}), doc.get("news", {})
        tiles = [("NSE stocks scanned", "%s of %s" % ("{:,}".format(sc.get("scanned", 0)), "{:,}".format(sc.get("universe", 0)))),
                 ("Liquid (₹%s+, %s+ shares)" % (sc.get("min_price"), "{:,}".format(sc.get("min_volume") or 0)),
                  "{:,}".format(sc.get("liquid", 0))),
                 ("Matched a daily setup", "{:,}".format(sc.get("setups", 0))),
                 ("Headlines read (last %sh)" % nw.get("hours"), "{:,}".format(nw.get("headlines", 0))),
                 ("Stocks named in the news", "{:,}".format(nw.get("stocks_named", 0))),
                 ("Max loss a trade / a day", "%s / %s" % (rs(cfg.get("max_loss_per_trade_usd")), rs(cfg.get("max_daily_loss_usd"))))]
        body = '<div class="tiles">%s</div>' % "".join(
            '<div class="tile"><b>%s</b><span>%s</span></div>' % (e(v), e(k)) for k, v in tiles)
        stage = ("Pre-open run at %s IST. Trade numbers are added at 9:35 IST." % e(doc.get("created_ist"))
                 if doc.get("stage") == "pre" else
                 "News and scan at %s IST, opening range and trade numbers at %s IST." % (e(doc.get("created_ist")), e(doc.get("orb_ist"))))
        body += '<h2>Top %d by news and volume</h2><div class="sub">%s Daily closes through %s.</div>' % (
            len(rows), stage, e(doc.get("closes_through")))
        body += "".join(card(r) for r in rows) or '<div class="card">No liquid stock was named in the news.</div>'
        if doc.get("errors"):
            body += '<details><summary>%d feed problems</summary><ul class="news">%s</ul></details>' % (
                len(doc["errors"]), "".join("<li>%s</li>" % e(x) for x in doc["errors"]))
    skills = "".join('<tr><td>%s</td><td class="st-%s">%s</td><td>%s</td></tr>' % (
        e(n), s.split()[0], e(s), e(w)) for n, s, w in SKILL_ROWS)
    page = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>NSE Morning Board</title>
<style>%s</style></head><body><div class="wrap">
<h1>NSE Morning Board</h1><div class="sub">%s &middot; budget %s, max loss %s a trade, %s trades a day, flat by %s IST</div>
<div class="note">Ranked by how much news a stock got and how much of it traded, not by how good a trade it is.
The odds are replays of each stock's own last 60 days, not a forecast: results, news and halts can do what those days never did.
A stop can fill worse than planned on a gap. Paper trade first. Nothing on this page places an order.</div>
%s
<h2>The 11 trader skills</h2><div class="card" style="overflow-x:auto"><table><tr><th>Skill</th><th>Status</th><th>What it does here</th></tr>%s</table></div>
</div></body></html>""" % (CSS, e(doc.get("created_ist")), rs(cfg.get("budget")), rs(cfg.get("max_loss_per_trade_usd")),
                           e(cfg.get("max_trades_per_day")), e(cfg.get("flat_by")), body, skills)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(page)


if __name__ == "__main__":
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "docs", "data.json")
    with open(src, encoding="utf-8") as fh:
        render(json.load(fh), os.path.join(os.path.dirname(src), "index.html"))
