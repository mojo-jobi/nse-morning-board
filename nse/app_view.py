"""The webapp shell and its new sections: a trading-terminal page (docs/index.html) that keeps itself
up to date. Every minute it fetches docs/view.json (each tab's HTML, rebuilt by every run) and
docs/data/market.json (prices, every 5 minutes in market hours) and swaps them in without a reload,
keeping the open tab and the expanded cards.

Tabs: (1) Options: news shortlist, intraday options, weekly/positional options; (2) Swing; (3) Long
term (work in progress); News; Track record; Filters (the rules in force and how each setup did).
"""

import html
import json

import options
import swing_view as sv

e, rs, pct, sym = sv.e, sv.rs, sv.pct, sv.sym

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">')

CSS = """
:root,:root[data-theme]{--bg:#0a0e14;--card:#111821;--ink:#e6edf3;--muted:#8b98a8;--line:#1f2a37;--accent:#36c5f0;
--good:#16c784;--good-bg:#0f2a20;--bad:#ea3943;--bad-bg:#2e1316;--warn:#f5b84a;--warn-bg:#2b2412;--neutral:#2a3646}
body{background:var(--bg);color:var(--ink);font:14px/1.45 Inter,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.px,.v,.tile b,.score,td,.tk,.num{font-family:"JetBrains Mono",ui-monospace,Consolas,monospace;font-variant-numeric:tabular-nums}
.wrap{max-width:1200px}
header.bar{position:sticky;top:0;z-index:20;background:rgba(10,14,20,.96);backdrop-filter:blur(6px);border-bottom:1px solid var(--line)}
.bar-in{max-width:1200px;margin:0 auto;padding:10px 16px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.brand{font-weight:700;font-size:17px;letter-spacing:.3px}.brand b{color:var(--accent)}
.mkt{font-size:12px;font-weight:700;padding:3px 9px;border-radius:999px;border:1px solid var(--line)}
.mkt.open{color:var(--good);border-color:var(--good)}.mkt.closed{color:var(--muted)}
.mkt.open::before{content:"";display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--good);
margin-right:6px;animation:pulse 1.6s infinite}@keyframes pulse{50%{opacity:.25}}
.clock{font-family:"JetBrains Mono",monospace;color:var(--muted);font-size:12px}
.upd{margin-left:auto;font-size:12px;color:var(--muted)}.upd b{color:var(--ink)}
.ticker{overflow:hidden;border-top:1px solid var(--line);background:#070a0f;white-space:nowrap}
.tape{display:inline-block;padding:6px 0;animation:scroll 90s linear infinite}.ticker:hover .tape{animation-play-state:paused}
@keyframes scroll{from{transform:translateX(0)}to{transform:translateX(-50%)}}
.tk{display:inline-block;margin:0 14px;font-size:12.5px}.tk b{color:var(--ink);margin-right:6px;font-family:Inter,sans-serif}
.tk .up{color:var(--good)}.tk .dn{color:var(--bad)}
nav.tabs{top:86px;background:var(--bg)}nav.tabs a{border-color:var(--line);color:var(--muted)}
nav.tabs a.on{background:var(--accent);border-color:var(--accent);color:#04121a}
.card{background:var(--card);border-color:var(--line);border-radius:10px}.tile{background:var(--card);border-color:var(--line)}
.note{background:#1a1f12;color:#d9c48a;border:1px solid #3a3420}
.changes{background:#0e1a24;border-color:#1d3346}
h2{font-size:15px;letter-spacing:.3px;text-transform:uppercase;color:var(--accent);margin-top:26px}
.lp{font-family:"JetBrains Mono",monospace;font-size:12.5px;margin-left:6px}
.flash-up{animation:fu 1.2s}.flash-dn{animation:fd 1.2s}@keyframes fu{0%{background:var(--good-bg)}}@keyframes fd{0%{background:var(--bad-bg)}}
.pill{font-family:Inter,sans-serif}.wip{border:1px dashed var(--warn);color:var(--warn);padding:14px;border-radius:10px}
.nf{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0}.nf button{background:transparent;color:var(--muted);border:1px solid var(--line);
padding:4px 10px;font-size:12px;border-radius:999px}.nf button.on{color:#04121a;background:var(--accent);border-color:var(--accent)}
.nrow{display:grid;grid-template-columns:92px 1fr auto;gap:10px;align-items:baseline;padding:8px 0;border-bottom:1px solid var(--line)}
.nrow .s{font-weight:700}.nrow a{color:var(--ink);text-decoration:none}.nrow a:hover{color:var(--accent)}
.nrow .meta{font-size:12px;color:var(--muted)}.sg{font-weight:700;font-size:12px}.sg.p{color:var(--good)}.sg.n{color:var(--bad)}
@media (max-width:640px){.nrow{grid-template-columns:70px 1fr}.nrow .meta{grid-column:2}.upd{margin-left:0;width:auto;font-size:11px}
header.bar{position:static}nav.tabs{top:0}.bar-in{gap:8px;padding:8px 12px}.brand{font-size:15px}
button#refresh{padding:5px 10px;font-size:12px}.tile b{font-size:16px}.tiles{gap:8px}.tile{padding:8px 10px}}
button#refresh{background:var(--accent);color:#04121a;border-color:var(--accent)}
"""

JS = r"""
(function(){
var VIEW="view.json",MARKET="data/market.json",lastGen=document.body.dataset.gen||"",lastMkt=null,lastUpd=document.body.dataset.updated||"";
function $(q,el){return (el||document).querySelector(q)}
function $$(q,el){return Array.prototype.slice.call((el||document).querySelectorAll(q))}
function fmt(n,dp){return n==null?"-":Number(n).toLocaleString("en-IN",{minimumFractionDigits:dp,maximumFractionDigits:dp})}
function ist(){var d=new Date(Date.now()+(330+new Date().getTimezoneOffset())*60000);return d}
function tick(){var d=ist(),hm=d.getHours()*60+d.getMinutes(),wd=d.getDay();
  $("#clock").textContent=d.toTimeString().slice(0,8)+" IST";
  var open=lastMkt?lastMkt.in_session:(wd>0&&wd<6&&hm>=555&&hm<930);
  var m=$("#mkt");m.className="mkt "+(open?"open":"closed");m.textContent=open?"MARKET OPEN":"MARKET CLOSED";
  if(lastUpd){var t=new Date(lastUpd.replace(" ","T")+":00+05:30"),mins=Math.round((Date.now()-t)/60000);
    $("#upd").innerHTML="data updated <b>"+(mins<1?"just now":mins+" min ago")+"</b> ("+lastUpd.slice(11)+" IST)"}}
function tape(m){if(!m)return;var items=(m.indices||[]).map(function(x){return [x.name,x.price,x.chg_pct]});
  var q=m.quotes||{},fo=Object.keys(q).filter(function(s){return q[s].fo&&q[s].c!=null});
  fo.sort(function(a,b){return Math.abs(q[b].c)-Math.abs(q[a].c)});
  fo.slice(0,40).forEach(function(s){items.push([s.replace(".NS",""),q[s].p,q[s].c])});
  var h=items.map(function(x){var c=x[2];return '<span class="tk"><b>'+x[0]+'</b>'+fmt(x[1],2)+' <span class="'+(c>=0?"up":"dn")+'">'+
    (c==null?"":(c>=0?"▲ +":"▼ ")+fmt(c,2)+"%")+'</span></span>'}).join("");
  $("#tape").innerHTML=h+h}
function prices(m){if(!m)return;var q=m.quotes||{};$$(".lp[data-sym]").forEach(function(el){var x=q[el.dataset.sym];if(!x)return;
  var old=parseFloat(el.dataset.p||"0"),txt="now ₹"+fmt(x.p,2)+" "+(x.c>=0?"+":"")+fmt(x.c,2)+"%";
  if(el.textContent!==txt){el.textContent=txt;el.className="lp "+(x.c>=0?"up":"dn");
    if(old&&x.p!==old){el.classList.add(x.p>old?"flash-up":"flash-dn")}el.dataset.p=x.p}})}
function openKeys(){return $$("details[open]").map(function(d){return keyOf(d)})}
function keyOf(d){var c=d.closest(".card"),s=c&&c.querySelector(".sym");return (s?s.textContent:"")+"|"+(d.querySelector("summary")||{}).textContent}
function swap(v){Object.keys(v.sections||{}).forEach(function(k){var el=document.getElementById("tab-"+k);if(!el)return;
    var keep=openKeys();el.innerHTML=v.sections[k];$$("details",el).forEach(function(d){if(keep.indexOf(keyOf(d))>=0)d.open=true})});
  if(v.top)$("#top").innerHTML=v.top;lastGen=v.generated;lastUpd=v.updated||lastUpd;
  document.dispatchEvent(new Event("view-swapped"));newsFilter();prices(lastMkt)}
function poll(){var t="?t="+Date.now();
  fetch(MARKET+t,{cache:"no-cache"}).then(function(r){return r.ok?r.json():null}).then(function(m){if(m){lastMkt=m;tape(m);prices(m);
    if(m.updated_ist&&m.updated_ist>lastUpd)lastUpd=m.updated_ist}}).catch(function(){});
  fetch(VIEW+t,{cache:"no-cache"}).then(function(r){return r.ok?r.json():null}).then(function(v){if(v&&v.generated!==lastGen)swap(v)}).catch(function(){})}
var nfSel="all";
function newsFilter(){var box=$("#tab-news");if(!box)return;$$(".nf button",box).forEach(function(b){b.classList.toggle("on",b.dataset.f===nfSel)});
  $$(".nrow",box).forEach(function(r){var f=nfSel,ok=f==="all"||(f==="impact"?+r.dataset.score>=2:f==="good"?r.dataset.sign==="1":
    f==="bad"?r.dataset.sign==="-1":(" "+r.dataset.tags+" ").indexOf(" "+f+" ")>=0);r.hidden=!ok})}
document.addEventListener("click",function(ev){var b=ev.target.closest(".nf button");if(b){nfSel=b.dataset.f;newsFilter()}});
newsFilter();tick();setInterval(tick,1000);poll();setInterval(poll,60000);
})();
"""


def lp(symbol):
    """A live-price slot the page fills from market.json."""
    return '<span class="lp" data-sym="%s"></span>' % e(symbol)


# ---------------------------------------------------------------- (1) options: intraday

def intraday_card(r):
    t = r.get("trade") or {}
    p, o = t.get("plan") or {}, t.get("option") or {}
    checks = t.get("checks") or options.intraday_checks(t)
    q = all(c["ok"] for c in checks)
    side = "CALL" if p.get("side") == "buy" else "PUT"
    head = ('<div class="top"><span class="sym">%s</span><span class="kind %s">%s</span>%s<span class="name">%s</span>'
            '<span class="px">%s</span>%s</div>' % (e(sym(r["symbol"])), "long" if side == "CALL" else "short", side,
                                                  sv.status_pill(t.get("status")), e(r.get("name")), rs(r.get("price")), lp(r["symbol"])))
    stock = ('<div class="sub">%s &middot; stock entry %s, stop %s, target %s &middot; flat by %s</div>' % (
        e(t.get("entry_kind")), rs(p.get("entry")), rs(p.get("stop")), rs(p.get("target")), e(p.get("flat_by"))))
    opt = ""
    if o.get("label"):
        cells = [("Option", "%s, exp %s (%s days)" % (o["label"], o["expiry"], o["dte"])),
                 ("Lot", "%s shares" % format(o["lot"], ",")),
                 ("Buy at", "%s = <b>%s a lot</b>" % (rs(o["ask"]), rs(o["cost_lot"], 0))),
                 ("Option stop", '%s (<span class="dn">-%s a lot</span>, %s)' % (rs(o["stop"]), rs(o["risk_lot"], 0), e(o["stop_rule"]))),
                 ("Option target", '%s (<span class="up">+%s a lot</span>)' % (rs(o["target"]), rs(o["reward_lot"], 0))),
                 ("Reward : risk", e(o["rr"])), ("Delta / IV", "%s / %s%%" % (o["delta"], o["iv"])),
                 ("Theta a lot a day", rs(o["theta_lot_day"], 0))]
        opt = '<div class="grid">%s</div>' % "".join('<div><div class="k">%s</div><div class="v">%s</div></div>' % (e(a), b)
                                                      for a, b in cells)
    elif o.get("error"):
        opt = '<div class="why">Option: %s</div>' % e(o["error"])
    cap = ('<div class="note" style="margin:8px 0">Clears every check, but the intraday slots are full: shown, not taken.</div>'
           if t.get("capacity") else "")
    return q, '<div class="card">%s%s%s%s%s</div>' % (head, stock, sv.checks_block(checks, q), cap, opt)


def intraday_block(doc):
    rows = [r for r in (doc or {}).get("shortlist") or [] if (r.get("trade") or {}).get("plan")]
    if not doc or doc.get("stage") == "closed":
        return '<div class="card empty">%s</div>' % e((doc or {}).get("closed_reason") or "The intraday board runs from 9:00 IST on trading days.")
    if not rows:
        return ('<div class="card empty">No opening-range breakout or breakdown on the F&amp;O shortlist yet (the range sets at '
                '9:30 IST; plans are checked every 5 minutes until 14:45).</div>')
    cards = [intraday_card(r) for r in rows]
    q = "".join(c for ok, c in cards if ok) or ('<div class="card empty">No intraday option clears every check right now. '
                                                'Sitting out is the plan.</div>')
    rest = [c for ok, c in cards if not ok]
    if rest:
        q += '<details class="watch"><summary>%d plans that did not clear every check</summary>%s</details>' % (len(rest), "".join(rest))
    return q


def news_shortlist_block(news):
    sl = (news or {}).get("shortlist") or []
    if not sl:
        return '<div class="card empty">No F&amp;O stock has strong news confirmed by its price and volume right now.</div>'
    out = ""
    for s in sl:
        out += ('<div class="card"><div class="top"><span class="sym">%s</span><span class="kind %s">%s</span><span class="name">%s</span>'
                '<span class="px">%s</span>%s</div><div class="sub">%s &middot; news score %s &middot; %s</div><ul class="news">%s</ul></div>' % (
                    e(sym(s["symbol"])), "long" if s["option"] == "CE" else "short", "CALLS" if s["option"] == "CE" else "PUTS",
                    e(s.get("name")), ("%+.2f%%" % s["chg_pct"]) if s.get("chg_pct") is not None else "", lp(s["symbol"]),
                    e(s["why"]), e(s["score"]), e(", ".join(s.get("tags") or [])),
                    "".join('<li><a href="%s" target="_blank" rel="noopener">%s</a> <span class="src">%s</span></li>' % (
                        e(t.get("link")), e(t["title"]), e(t.get("time"))) for t in s.get("titles") or [])))
    return out


def options_tab(swing, intraday, news):
    return ('<div class="note">Profile 1: equity options on F&amp;O stocks. Intraday trades are opening-range breakouts '
            '(calls) and breakdowns (puts), flat by 15:15. Weekly/positional trades hold up to about two weeks on the nearest '
            'monthly expiry 14+ days away (stock options have no weekly expiries). A screen, not advice: a bought option '
            'can lose its whole cost.</div>'
            '<h2>News movers to watch</h2><div class="sub">Strong news confirmed by today\'s price and volume. A watchlist: '
            'the trade still needs a setup below.</div>' + news_shortlist_block(news) +
            '<h2>Intraday options</h2>' + intraday_block(intraday) +
            '<h2>Weekly / positional options</h2>' + sv.options_block((swing or {}).get("options")))


# ---------------------------------------------------------------- (2) swing, (3) long term

def swing_tab(swing, bull_html):
    th = ", ".join(_theme_names((swing or {}).get("config") or {}))
    return ('<div class="note">Profile 2: swing trades of 3 to 15 sessions in stocks with momentum: liquid midcaps and '
            'smallcaps included, stocks in the themes you follow (%s) and in confirmed good news ranked first. A plan is '
            'recommended only if it clears every check, including moving enough (an average daily range of 2%%+) and '
            'trading enough (Rs 10 cr+ a day). Size: whole shares inside your risk per trade.</div>' % e(th or "none set")) + bull_html


def _theme_names(cfg):
    import themes
    return [themes.label(k) for k in cfg.get("themes") or []]


def longterm_tab(swing):
    bots = [r for r in (swing or {}).get("bottoms") or []]
    quality = [r for r in bots if (r.get("fund") or 0) >= 65]
    body = "".join(sv.bottom_card(r) for r in quality[:10]) or '<div class="card empty">None today.</div>'
    return ('<div class="wip"><b>Work in progress.</b> Profile 3 will screen for 6-month-plus holdings on fundamentals '
            '(growth, returns on capital, valuation against the sector, ownership trends) with an entry plan. For now: '
            'quality stocks sitting on support, a starting list to research, not a buy list.</div>'
            '<h2>Quality at support</h2><div class="sub">Fundamental score 65+, 20%%+ off the 52-week high, on a support zone.</div>' + body)


# ---------------------------------------------------------------- news

def news_tab(news):
    if not news or not news.get("items"):
        return '<div class="card empty">The news tab fills in on the next run (every 5 minutes in market hours).</div>'
    c = news.get("counts") or {}
    filters = [("all", "All"), ("impact", "High impact"), ("good", "Good"), ("bad", "Bad"), ("order win", "Orders"),
               ("results beat", "Results beat"), ("results miss", "Results miss"), ("upgrade", "Upgrades"),
               ("downgrade", "Downgrades"), ("deal", "Deals"), ("regulatory", "Regulatory"), ("approval", "Approvals")]
    rows = ""
    for it in news["items"]:
        sg = '<span class="sg %s">%s</span>' % ({1: "p", -1: "n"}.get(it["sign"], ""), {1: "▲ good", -1: "▼ bad"}.get(it["sign"], "●"))
        rows += ('<div class="nrow" data-score="%s" data-sign="%s" data-tags="%s"><div class="s">%s%s</div>'
                 '<div><a href="%s" target="_blank" rel="noopener">%s</a><div class="meta">%s &middot; %s &middot; %s</div></div>'
                 '<div class="meta">%s</div></div>' % (
                     e(it["weight"]), e(it["sign"]), e(" ".join(it["tags"])), e(sym(it["symbol"])), lp(it["symbol"]),
                     e(it.get("link")), e(it["title"]), e(it.get("source")), e(it.get("time") or "?"),
                     e(", ".join(it["tags"]) or "general"), sg))
    return ('<div class="sub">%s headlines on %s F&amp;O stocks, updated %s IST. Impact tags are keyword rules; open the '
            'story before acting on it.</div><h2>Shortlist for options</h2>%s<h2>All F&amp;O news</h2><div class="nf">%s</div>'
            '<div class="card">%s</div>' % (
                format(c.get("headlines", 0), ","), c.get("stocks", 0), e(news.get("updated_ist")),
                news_shortlist_block(news), "".join('<button type="button" data-f="%s">%s</button>' % (e(k), e(v)) for k, v in filters),
                rows))


# ---------------------------------------------------------------- filters: the rules and how they did

def filters_tab(swing, cfg_all):
    sw = (swing or {}).get("config") or {}
    G, O = sw.get("gate") or {}, cfg_all.get("options") or {}
    D = O.get("direction") or {}
    rows = [("Swing: capital, risk a trade", "%s, %s" % (rs(sw.get("budget"), 0), rs(sw.get("max_loss_per_trade"), 0))),
            ("Swing: replay expectancy, target first", "%+.2fR+, %d%%+" % (G.get("min_avg_r", 0), 100 * G.get("min_p_target", 0))),
            ("Swing: worked on this stock before", "%s+ times, %+.2fR+ average" % (G.get("min_hist_trades"), G.get("min_hist_avg_r", 0))),
            ("Swing: fundamentals (long / short / bottom)", "%s+ / %s- / %s+" % (G.get("long_min_fund"), G.get("short_max_fund"), G.get("bottom_min_fund"))),
            ("Swing: in a falling market a long needs", "stronger than %s%% of stocks" % G.get("rs_long_in_down_market")),
            ("Swing: moves enough, liquid, reward:risk", "%s%%+ daily range, Rs %s cr+ a day, %s+" % (
                G.get("min_atr_pct"), G.get("min_turnover_cr"), G.get("min_rr"))),
            ("Swing: themes favoured", ", ".join(_theme_names(sw)) or "none"),
            ("Options: budget a trade, max open", "%s, %s" % (rs(O.get("max_loss_per_trade"), 0), O.get("max_open"))),
            ("Options: exits", "+%s%% / -%s%% of the cost, the stock's target or stop, %s days before expiry" % (
                O.get("take_profit_pct"), O.get("stop_pct"), O.get("exit_dte"))),
            ("Options: direction", "target first %d%%+, expectancy %+.2fR+, no results due" % (
                100 * D.get("min_p_target", 0), D.get("min_avg_r", 0))),
            ("Options: structure", O.get("structures", "spreads_first").replace("_", " ")),
            ("Intraday: universe, flat by", "%s, %s IST" % ("F&O stocks" if (cfg_all.get("rank") or {}).get("universe") == "fo" else "all", cfg_all.get("flat_by")))]
    t = "".join("<tr><td>%s</td><td class='num'>%s</td></tr>" % (e(a), e(b)) for a, b in rows)
    by = {}
    for r in ((swing or {}).get("record") or {}).get("rows") or []:
        s = by.setdefault(r["kind"], {"n": 0, "closed": 0, "wins": 0, "R": 0.0})
        s["n"] += 1
        if r.get("result_R") is not None:
            s["closed"] += 1
            s["wins"] += r["result_R"] > 0
            s["R"] += r["result_R"]
    perf = "".join("<tr><td>%s</td><td class='num'>%d</td><td class='num'>%d</td><td class='num'>%s</td><td class='num'>%s</td></tr>" % (
        e(k), v["n"], v["closed"], pct(v["wins"] / v["closed"]) if v["closed"] else "-",
        "%+.2fR" % (v["R"] / v["closed"]) if v["closed"] else "-") for k, v in sorted(by.items()))
    return ('<div class="note">The rules in force (config.json) and how each setup has done since the stricter screen. '
            'We tune these together: a setup that keeps losing gets tightened or dropped, one that works gets more room. '
            'Change a number by asking, or edit config.json.</div><h2>Rules</h2><div class="card tbl"><table>%s</table></div>'
            '<h2>How each setup did</h2><div class="card tbl"><table><tr><th>Setup</th><th>Plans</th><th>Closed</th>'
            '<th>Win rate</th><th>Average</th></tr>%s</table></div>' % (t, perf or "<tr><td colspan=5>No closed plans yet.</td></tr>"))


def shell(sections, top, updated, generated, repo_js, refresh_js, css_base):
    tabs = [("options", "① Options"), ("swing", "② Swing"), ("longterm", "③ Long term"), ("news", "News"),
            ("record", "Track record"), ("filters", "Filters")]
    nav = "".join('<a href="#%s" data-tab="%s">%s</a>' % (k, k, v) for k, v in tabs)
    secs = "".join('<section id="tab-%s" class="tab"%s>%s</section>' % (k, "" if k == "options" else " hidden", sections.get(k, ""))
                   for k, _ in tabs)
    return """<!doctype html><html lang="en" data-theme="dark"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>NSE Trading Desk</title>%s
<style>%s%s%s</style></head><body data-gen="%s" data-updated="%s">
<header class="bar"><div class="bar-in"><div class="brand">NSE <b>Trading Desk</b></div><span id="mkt" class="mkt">MARKET</span>
<span id="clock" class="clock"></span><span id="upd" class="upd"></span>
<div><button id="refresh" type="button">Update now</button></div></div>
<div class="ticker"><div id="tape" class="tape"></div></div></header>
<div class="wrap"><div id="rstatus" class="rstatus" style="text-align:left;max-width:none"></div>
<div id="rsetup" class="card" hidden><b>Let this page start an update on GitHub</b>
<ol><li>Open <a href="https://github.com/settings/personal-access-tokens/new" target="_blank" rel="noopener">GitHub &rarr; new fine-grained token</a>.</li>
<li>Repository access: <b>Only select repositories</b> &rarr; <b>%s</b>.</li>
<li>Permissions &rarr; Repository: <b>Actions: Read and write</b> and <b>Contents: Read-only</b>.</li>
<li>Pick an expiry, generate it, and paste it here.</li></ol>
<input type="password" id="rtoken" placeholder="github_pat_..." autocomplete="off" spellcheck="false">
<button id="rsave" type="button">Save and update</button> <button id="rcancel" type="button" class="ghost">Cancel</button>
<div class="why">Kept only in this browser, sent only to api.github.com. <a href="#" id="rforget">Forget the saved token</a>.</div></div>
<div id="top">%s</div>
<nav class="tabs" role="tablist">%s</nav>%s
<div class="sub" style="margin-top:30px">A rules screen, not advice. Prices update every 5 minutes in market hours; the page fetches them every minute.
Nothing here places an order.</div></div>
<script>%s</script><script>%s</script><script>%s</script></body></html>""" % (
        FONTS, css_base, sv.CSS, CSS, e(generated), e(updated), e(repo_js[1]), top, nav, secs,
        refresh_js, sv.JS, JS)


def intraday_record_block(rec):
    head = '<h2>Intraday options</h2>'
    if not rec or not rec.get("rows"):
        return head + ('<div class="card empty">Every intraday option that clears every check is tracked here: bought at the '
                       'ask when its stock triggers, sold at the bid at the option\'s stop or target, the stock\'s stop, '
                       'or flat by 15:15. One lot each.</div>')
    st = rec["stats"]
    tiles = [("Tracked", st["tracked"]), ("Waiting or open", st["open"]), ("Closed", st["closed"]),
             ("Entry missed", st["missed"]), ("Closed result, per lot each", rs(st["total_lot"], 0)),
             ("Average closed result", "%+.1f%%" % st["avg_pct"] if st.get("avg_pct") is not None else "-"),
             ("Win rate", pct(st.get("win_rate"))), ("Open now, per lot each", rs(st["open_mark_lot"], 0))]
    t = '<div class="tiles">%s</div>' % "".join('<div class="tile"><b>%s</b><span>%s</span></div>' % (e(v), e(n)) for n, v in tiles)
    trs = ""
    for r in rec["rows"]:
        res = ""
        if r.get("result_lot") is not None:
            res = '<span class="%s">%s (%+.1f%%)</span>' % ("up" if r["result_lot"] >= 0 else "dn", rs(r["result_lot"], 0), r["result_pct"])
        elif r.get("mark_lot") is not None:
            res = 'now <span class="%s">%s (%+.1f%%)</span>' % ("up" if r["mark_lot"] >= 0 else "dn", rs(r["mark_lot"], 0), r["mark_pct"])
        now = r.get("exit") if r.get("exit") is not None else r.get("last")
        trs += ("<tr><td>%s</td><td><b>%s %s %s</b><br><span class='sub'>exp %s, lot %s</span></td><td>%s</td>"
                "<td>%s / %s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                    e(r["date"]), e(sym(r["symbol"])), sv.k(r["strike"]), e(r["type"]), e(r["expiry"]), format(r["lot"], ","),
                    sv.status_pill(r["status"]), rs(r["opt_stop"]), rs(r["opt_target"]),
                    sv.per_lot(r.get("fill"), r["lot"]), sv.per_lot(now, r["lot"]), res,
                    e((r.get("closed_ist") or r.get("entered_ist") or r.get("last_ist") or "")[11:])))
    return head + t + ('<div class="card tbl"><table><tr><th>Day</th><th>Option</th><th>Status</th><th>Option stop / target</th>'
                       '<th>Bought</th><th>Sold / now</th><th>Result per lot</th><th>At</th></tr>%s</table></div>'
                       '<div class="sub">Bought at the ask and sold at the bid at the 5-minute update after the move, so real '
                       'fills differ. One lot each.</div>' % trs)
