"""docs/data.json -> docs/index.html (one self-contained page, served by GitHub Pages)."""

import html
import json
import os
import sys

SKILL_ROWS = [
    ("trader-scanner", "used", "Daily closes of every NSE EQ stock (Yahoo); 20-day breakout, bull flag, 20-day average, "
                               "oversold. Live prices and volume from Upstox when its token is set"),
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
.head{display:flex;gap:12px;align-items:flex-start;justify-content:space-between;flex-wrap:wrap}
button{font:inherit;font-size:14px;font-weight:600;border-radius:8px;padding:7px 14px;cursor:pointer;
border:1px solid var(--accent);background:var(--accent);color:var(--bg)}
button.ghost{background:transparent;color:var(--accent)}button:disabled{opacity:.55;cursor:wait}
.rstatus{font-size:13px;color:var(--muted);margin-top:6px;text-align:right;max-width:340px}.rstatus.bad{color:var(--bad)}
.rstatus.ok{color:var(--good)}
#rsetup ol{margin:8px 0;padding-left:20px;font-size:13px}#rsetup li{margin:3px 0}
#rsetup input{font:inherit;font-size:14px;padding:7px 10px;border:1px solid var(--line);border-radius:8px;
background:var(--bg);color:var(--ink);width:min(100%,360px);margin:4px 8px 8px 0}
a{color:var(--accent)}
.move{font-size:12px;font-weight:700;border-radius:6px;padding:1px 7px}
.move.new{background:var(--good-bg);color:var(--good)}.move.upr{color:var(--good)}.move.dnr{color:var(--bad)}
.changes{font-size:13px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin-top:10px}
"""

# The page is static (GitHub Pages) and Yahoo will not answer a browser, so Refresh asks
# GitHub to run the same scan (workflow_dispatch, stage=refresh), waits for that run, then
# loads the board it committed. It needs the viewer's own GitHub token, kept in this browser.
REFRESH_JS = r"""
(function(){
var REPO = __REPO__, KEY = "nse_gh_token";
var btn = document.getElementById("refresh"), st = document.getElementById("rstatus"),
    setup = document.getElementById("rsetup"), input = document.getElementById("rtoken");
function get(){try{return localStorage.getItem(KEY)}catch(e){return null}}
function put(v){try{if(v)localStorage.setItem(KEY,v);else localStorage.removeItem(KEY)}catch(e){}}
function say(t,cls,link){st.className="rstatus "+(cls||"");st.textContent=t;
  if(link){var a=document.createElement("a");a.href=link;a.target="_blank";a.rel="noopener";a.textContent=" Open the run";st.appendChild(a)}}
function sleep(ms){return new Promise(function(r){setTimeout(r,ms)})}
function clock(s){return Math.floor(s/60)+":"+("0"+(s%60)).slice(-2)}
function api(path,opt){opt=opt||{};
  var h={"Accept":opt.accept||"application/vnd.github+json","Authorization":"Bearer "+get(),"X-GitHub-Api-Version":"2022-11-28"};
  if(opt.body)h["Content-Type"]="application/json";
  return fetch("https://api.github.com/repos/"+REPO+path,{method:opt.method||"GET",headers:h,cache:"no-store",
    body:opt.body?JSON.stringify(opt.body):undefined});}
try{var done=sessionStorage.getItem("nse_refreshed");if(done){sessionStorage.removeItem("nse_refreshed");
  say("Refreshed just now (took "+clock(+done)+").","ok")}}catch(e){}
async function refresh(){
  if(!REPO){say("No GitHub repository is set in config.json.","bad");return}
  if(!get()){setup.hidden=false;input.focus();return}
  setup.hidden=true;btn.disabled=true;
  var id=Math.random().toString(36).slice(2,10), t0=Date.now(), run=null;
  say("Asking GitHub to rescan…");
  try{
    var r=await api("/actions/workflows/morning.yml/dispatches",{method:"POST",
      body:{ref:"main",inputs:{stage:"refresh",request:id}}});
    if(r.status===401||r.status===403||r.status===404){
      say("GitHub refused the token ("+r.status+"): it needs Actions read and write on "+REPO+".","bad");
      setup.hidden=false;btn.disabled=false;return}
    if(!r.ok){say("GitHub answered "+r.status+". Try again in a minute.","bad");btn.disabled=false;return}
    for(;;){
      await sleep(5000);
      var el=clock(Math.round((Date.now()-t0)/1000));
      if(!run){
        var l=await api("/actions/runs?event=workflow_dispatch&per_page=10");
        if(l.ok){var j=await l.json();run=(j.workflow_runs||[]).filter(function(x){
          return (x.display_title||"").indexOf(id)>=0})[0]||null}
        if(!run){say("Waiting for GitHub to start the run… "+el);continue}
      }
      var g=await api("/actions/runs/"+run.id);
      if(g.ok)run=await g.json();
      if(run.status!=="completed"){
        say((run.status==="in_progress"?"Rescanning every NSE stock and the news…":
             "Queued: another run is ahead of it…")+" "+el,"",run.html_url);continue}
      if(run.conclusion!=="success"){say("The run ended: "+run.conclusion+".","bad",run.html_url);
        btn.disabled=false;return}
      break;
    }
    say("Done. Loading the new board…");
    var h=await api("/contents/docs/index.html?ref=main",{accept:"application/vnd.github.raw"});
    if(!h.ok){say("Updated on GitHub. Reload the page in a minute to see it.","ok");btn.disabled=false;return}
    var page=await h.text();
    try{sessionStorage.setItem("nse_refreshed",String(Math.round((Date.now()-t0)/1000)))}catch(e){}
    document.open();document.write(page);document.close();
  }catch(e){say("Could not reach GitHub: "+e.message,"bad");btn.disabled=false}
}
btn.addEventListener("click",refresh);
document.getElementById("rsave").addEventListener("click",function(){
  var v=(input.value||"").trim();if(!v){input.focus();return}put(v);input.value="";refresh()});
document.getElementById("rcancel").addEventListener("click",function(){setup.hidden=true});
document.getElementById("rforget").addEventListener("click",function(ev){ev.preventDefault();put(null);
  say("Saved token removed from this browser.")});
})();
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


def move_badge(r, show):
    if "prev_rank" not in r:
        return ""
    p = r["prev_rank"]
    if not p or p > show:
        return '<span class="move new">NEW%s</span>' % (" (was #%d)" % p if p else "")
    if p > r["rank"]:
        return '<span class="move upr">&#9650; from #%d</span>' % p
    if p < r["rank"]:
        return '<span class="move dnr">&#9660; from #%d</span>' % p
    return ""


def card(r, basis="last session", show=10):
    chg = r.get("chg_pct")
    chg_s = "" if chg is None else '<span class="%s">%+.2f%%</span>' % ("up" if chg >= 0 else "dn", chg)
    chips = "".join('<span class="chip tag">%s</span>' % e(t) for t in r.get("news_tags") or [])
    chips += "".join('<span class="chip">%s</span>' % e(s.replace("_", " ")) for s in r.get("setups") or [])
    if r.get("earnings_flag"):
        chips += '<span class="chip" style="color:var(--warn);border-color:var(--warn)">results in the news</span>'
    cc = r.get("cross_check")
    if cc and cc.get("flag"):
        chips += ('<span class="chip" style="color:var(--warn);border-color:var(--warn)">prices differ: Yahoo %s%s, '
                  '%.1f%% apart</span>' % (rs(cc["yahoo"], 2), " at " + e(cc["yahoo_time"]) if cc.get("yahoo_time") else "",
                                           cc["gap_pct"]))
    news = "".join('<li><a href="%s" target="_blank" rel="noopener">%s</a> <span class="src">%s%s</span></li>' % (
        e(n.get("link")), e(n.get("title")), e(n.get("source")), (", " + e(n["time"])) if n.get("time") else "")
        for n in r.get("news") or [])
    return ('<div class="card"><div class="top"><span class="rank">#%d</span><span class="sym">%s</span>%s'
            '<span class="name">%s</span><span class="px">%s</span>%s</div>'
            '<div class="sub">%d headlines &middot; traded %s cr %s (%s shares) &middot; score %s%s</div>'
            '<div class="chips">%s</div>%s'
            '<details><summary>Headlines (%d)</summary><ul class="news">%s</ul></details></div>'
            % (r["rank"], e(r["symbol"].replace(".NS", "")), move_badge(r, show), e(r.get("name")),
               rs(r.get("price"), 2), chg_s, r.get("news_count", 0), rs(r.get("turnover_cr"), 1),
               {"today so far": "today so far", "today": "today"}.get(basis, "in the last session"),
               "{:,}".format(r.get("volume") or 0), r.get("score"),
               " &middot; price from %s%s" % (e(r.get("price_source") or "Yahoo"),
                                              ", bars from %s" % e(r["trade"]["bars_source"])
                                              if (r.get("trade") or {}).get("bars_source") else ""),
               chips, trade_block(r.get("trade")), len(r.get("news") or []), news))


def intraday_body(doc):
    cfg = doc.get("config") or {}
    show = 10
    rows = (doc.get("shortlist") or [])[:show]
    if not doc:
        body = '<div class="note">No intraday board yet: it runs at 9:00 and 9:35 IST on trading days.</div>'
    elif doc.get("stage") == "closed":
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
        srcs = doc.get("sources") or {}
        if srcs:
            live = srcs.get("quotes_upstox") or 0
            bars = ", ".join("%s %d" % kv for kv in (srcs.get("bars") or {}).items() if kv[1])
            tiles.insert(0, ("Prices: Upstox live for %s stocks" % "{:,}".format(live) if live else
                             "Prices: Yahoo (Upstox %s)" % srcs.get("upstox", "not set"),
                             "Upstox" if live else "Yahoo"))
            if bars:
                tiles.insert(1, ("5-minute bars for the trade numbers", bars))
        body = ""
        if srcs.get("upstox") == "token rejected":
            body += ('<div class="note">Upstox rejected the token, so this board used Yahoo. Make a new Analytics '
                     'Token in Upstox Developer Apps and update the UPSTOX_ANALYTICS_TOKEN secret on GitHub.</div>')
        body += '<div class="tiles">%s</div>' % "".join(
            '<div class="tile"><b>%s</b><span>%s</span></div>' % (e(v), e(k)) for k, v in tiles)
        stage = ("Pre-open run at %s IST. Trade numbers are added at 9:35 IST." % e(doc.get("created_ist"))
                 if doc.get("stage") == "pre" else
                 "News and scan at %s IST, opening range and trade numbers at %s IST." % (e(doc.get("created_ist")), e(doc.get("orb_ist"))))
        body += '<h2>Top %d by news and volume</h2><div class="sub">%s Daily closes through %s.</div>' % (
            len(rows), stage, e(doc.get("closes_through")))
        prev = doc.get("previous")
        if prev:
            names = {r["symbol"]: r for r in rows}
            if prev.get("entered") or prev.get("dropped"):
                inn = ", ".join("%s (#%d)" % (e(s.replace(".NS", "")), names[s]["rank"])
                                for s in prev.get("entered") or [] if s in names) or "none"
                out = ", ".join("%s (was #%d)" % (e(d["symbol"].replace(".NS", "")), d["rank"])
                                for d in prev.get("dropped") or []) or "none"
                body += ('<div class="changes"><b>Changed since the %s board.</b> Came into the top %d: %s. '
                         'Dropped out: %s.</div>' % (e((prev.get("created_ist") or "")[11:]), show, inn, out))
            else:
                body += '<div class="changes">Same top %d as the %s board; arrows show any change in order.</div>' % (
                    show, e((prev.get("created_ist") or "")[11:]))
        basis = doc.get("volume_basis") or "last session"
        body += "".join(card(r, basis, show) for r in rows) or '<div class="card">No liquid stock was named in the news.</div>'
        if doc.get("errors"):
            body += '<details><summary>%d feed problems</summary><ul class="news">%s</ul></details>' % (
                len(doc["errors"]), "".join("<li>%s</li>" % e(x) for x in doc["errors"]))
    head = ('<div class="note">Intraday: ranked by how much news a stock got and how much of it traded, not by how good '
            'a trade it is. Opening-range plans for today only, flat by %s IST; budget %s, max loss %s a trade, %s trades '
            'a day. The odds replay each stock\'s last 60 days of 5-minute bars, not a forecast.</div>' % (
                e(cfg.get("flat_by")), rs(cfg.get("budget")), rs(cfg.get("max_loss_per_trade_usd")),
                e(cfg.get("max_trades_per_day"))) if doc and doc.get("stage") != "closed" else "")
    skills = "".join('<tr><td>%s</td><td class="st-%s">%s</td><td>%s</td></tr>' % (
        e(n), s.split()[0], e(s), e(w)) for n, s, w in SKILL_ROWS)
    return (head + body + '<h2>The 11 trader skills</h2><div class="card" style="overflow-x:auto"><table><tr><th>Skill'
            '</th><th>Status</th><th>What it does here</th></tr>%s</table></div>' % skills)


def render(doc, path=None):
    """Kept for morning.py: the whole site, with this intraday board."""
    render_site(intraday=doc, path=path)


def _load(name):
    try:
        with open(os.path.join(DOCS, name), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def render_site(intraday=None, swing=None, path=None):
    """docs/index.html: Swing, Falling market, Track record and Intraday tabs from docs/swing.json
    and docs/data.json (either can be missing)."""
    import swing_view
    intraday = intraday if intraday is not None else (_load("data.json") or {})
    swing = swing if swing is not None else _load("swing.json")
    repo = intraday.get("repo") or (swing or {}).get("repo") or _repo()
    bull, falling, record, top = swing_view.tabs(swing)
    updated = max(((swing or {}).get("live") or {}).get("created_ist") or "",
                  (swing or {}).get("created_ist") or "", intraday.get("orb_ist") or intraday.get("created_ist") or "")
    page = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>NSE Swing Board</title>
<style>%s%s</style></head><body><div class="wrap">
<div class="head"><div><h1>NSE Swing Board</h1><div class="sub">Updated %s IST &middot; swing setups for 3 to 15 trading days, ranked on technicals and fundamentals</div></div>
<div><button id="refresh" type="button">Refresh</button><div id="rstatus" class="rstatus">Updates prices, entries, stops and targets, and rescans intraday (about 2 minutes)</div></div></div>
<div id="rsetup" class="card" hidden><b>Let this page start a rescan on GitHub</b>
<ol><li>Open <a href="https://github.com/settings/personal-access-tokens/new" target="_blank" rel="noopener">GitHub &rarr; new fine-grained token</a>.</li>
<li>Repository access: <b>Only select repositories</b> &rarr; <b>%s</b>.</li>
<li>Permissions &rarr; Repository: <b>Actions: Read and write</b> and <b>Contents: Read-only</b>. Nothing else.</li>
<li>Pick an expiry (30 days is plenty), generate it, and paste it here.</li></ol>
<input type="password" id="rtoken" placeholder="github_pat_..." autocomplete="off" spellcheck="false">
<button id="rsave" type="button">Save and refresh</button> <button id="rcancel" type="button" class="ghost">Cancel</button>
<div class="why">The token is kept only in this browser and sent only to api.github.com. It can start and read runs of this one repository, nothing else.
<a href="#" id="rforget">Forget the saved token</a>. No token? <a href="https://github.com/%s/actions/workflows/morning.yml" target="_blank" rel="noopener">Run it on GitHub</a>
(Run workflow &rarr; stage <b>refresh</b>) and reload this page when it finishes.</div></div>
<div class="note">A rules screen, not advice to buy or sell. Entries are triggers; stops sit where the setup is proven wrong.
The odds replay each stock's own past, not a forecast: results, news and gaps can do what those days never did. Paper trade first. Nothing here places an order.</div>
%s
<nav class="tabs" role="tablist"><a href="#swing" data-tab="swing">Swing</a><a href="#falling" data-tab="falling">Falling market</a><a href="#record" data-tab="record">Track record</a><a href="#intraday" data-tab="intraday">Intraday</a></nav>
<section id="tab-swing" class="tab">%s</section>
<section id="tab-falling" class="tab" hidden>%s</section>
<section id="tab-record" class="tab" hidden>%s</section>
<section id="tab-intraday" class="tab" hidden>%s</section>
</div><script>%s</script><script>%s</script></body></html>""" % (
        CSS, swing_view.CSS, e(updated or "-"), e(repo.split("/")[-1]), e(repo), top, bull, falling, record,
        intraday_body(intraday), REFRESH_JS.replace("__REPO__", json.dumps(repo or None)), swing_view.JS)
    path = path or os.path.join(DOCS, "index.html")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(page)


def _repo():
    try:
        with open(os.path.join(os.path.dirname(DOCS), "config.json"), encoding="utf-8") as fh:
            return json.load(fh).get("repo") or ""
    except (OSError, ValueError):
        return ""


DOCS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")

if __name__ == "__main__":
    render_site()
