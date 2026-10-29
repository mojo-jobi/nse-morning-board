"""The News tab: what was said about each F&O company, how much it could move the stock, and whether
the stock is already moving that way.

Sources: Upstox's news for every F&O stock (the last 7 days, 30 stocks a request) and the Indian
market RSS feeds the intraday board reads (Economic Times, Moneycontrol, Mint, Business Standard,
Google News; at most every 15 minutes).

Each headline gets impact tags (keyword rules below): order wins, results beat or miss, broker
upgrades or downgrades, deals, capital actions, regulatory action, management changes, events and
sector news, each with a weight and a direction (+ good for the stock, - bad, 0 depends). A
headline's score is its weight times how fresh it is (1 in the first 6 hours, 0.7 within a day,
0.4 within 3 days, 0.2 older). A stock's score adds up its headlines.

Confirmed: the stock is moving the way the news points, today: 1.5%+ in that direction on 1.3x+
its usual volume for this time of day. The options shortlist: F&O stocks with a score of 3+ and a
clear direction, confirmed by the tape (or a score of 5+ before the open, when the tape cannot
confirm yet). A shortlist is a list to watch, not a trade: the trade comes from the Options tab's
checks.
"""

import datetime
import re
import time

import market
import upstox

IMPACT = [  # (tag, weight, direction, pattern)
    ("order win", 3, 1, r"order (win|inflow|worth|book)|bags? (an? )?(\w+ )?order|wins? (an? )?(\w+ )?(order|contract)|"
                        r"secures? (an? )?(\w+ )?(order|contract)|contract (worth|from)|\bL1 bidder|letter of (award|intent)|\bLoA\b"),
    ("results beat", 3, 1, r"(profit|PAT|revenue|EBITDA)\s+(jumps|surges|rises|soars|grows|climbs|up|doubles|beats)|"
                           r"beats? (estimates|street|expectations)|record (profit|revenue|quarter)|margin(s)? expan"),
    ("results miss", 3, -1, r"(profit|PAT|revenue|EBITDA)\s+(falls|drops|declines|slumps|plunges|down|dips|misses)|"
                            r"misses? (estimates|street|expectations)|loss widens|net loss|margin(s)? (contract|shrink|under pressure)"),
    ("upgrade", 2, 1, r"upgrade[sd]?\b|target (price )?(raised|hiked|increased)|(initiates?|starts?) .{0,30}\bbuy\b|"
                      r"overweight|outperform|top pick|(raises?|hikes?) (its )?(price )?target"),
    ("downgrade", 2, -1, r"downgrade[sd]?\b|target (price )?(cut|lowered|reduced|slashed)|underweight|underperform|"
                         r"\bsell (rating|call)|\breduce rating|(cuts?|lowers?|slashes) (its )?(price )?target"),
    ("deal", 2, 0, r"acqui(re|res|red|sition)|merger|demerger|stake (buy|purchase|acquisition|in)|joint venture|\bJV\b|"
                   r"takeover|open offer|partnership|ties up|collaborat"),
    ("capital", 1, 0, r"buyback|bonus issue|stock split|dividend|\bQIP\b|rights issue|fund ?rais|\bNCDs?\b|\bOFS\b|"
                      r"block deal|bulk deal|stake sale|pledge"),
    ("regulatory", 3, -1, r"\bSEBI\b.{0,40}(order|penalty|probe|notice|bars?|ban)|penalty|fined?\b|probe|raid|"
                          r"show[- ]cause|warning letter|import alert|Form 483|observations|\bGST (notice|demand)|tax demand"),
    ("approval", 2, 1, r"approval|approves?|clearance|\bEIR\b|clean chit|nod\b|licen[cs]e (granted|received)"),
    ("management", 1, 0, r"resign|steps down|appoint(s|ed|ment)|\bCEO\b|\bCFO\b|managing director|chairman"),
    ("event", 1, 0, r"board meeting|record date|ex-date|\bAGM\b|analyst meet|investor (meet|day)|results (date|on)"),
    ("sector/macro", 1, 0, r"tariff|(import|export) duty|\bPLI\b|government|policy|crude|rupee|repo rate|monsoon"),
]
IMPACT = [(t, w, d, re.compile(p, re.I)) for t, w, d, p in IMPACT]
GOOD = re.compile(r"surges?|jumps?|soars?|rall(y|ies)|gains?|hits? (a )?(record|52-week high|all-time high)|"
                  r"upper circuit|zooms?|spurts?|climbs?|rises?", re.I)
BAD = re.compile(r"slumps?|plunges?|crash(es)?|tumbles?|sinks?|falls?|drops?|dips?|slides?|lower circuit|"
                 r"52-week low|sheds?|cuts?\b|tanks?", re.I)
RSS_EVERY = 15 * 60


def classify(title, summary=""):
    """(tags, weight, direction) for one headline."""
    text = "%s %s" % (title or "", summary or "")
    tags, weight, sign = [], 0, 0
    for tag, w, d, rx in IMPACT:
        if rx.search(text):
            tags.append(tag)
            weight = max(weight, w)
            sign += d
    if not sign:
        g, b = bool(GOOD.search(title or "")), bool(BAD.search(title or ""))
        sign = 1 if g and not b else -1 if b and not g else 0
    if not tags and sign and re.search(r"\d+(\.\d+)?\s*%", title or ""):
        tags, weight = ["big move"], 1                 # "shares slump 8%": a move worth knowing, little cause
    return tags, weight, (1 if sign > 0 else -1 if sign < 0 else 0)


def freshness(age_h):
    return 1.0 if age_h <= 6 else 0.7 if age_h <= 24 else 0.4 if age_h <= 72 else 0.2


def build(fo_syms, names, inst, quotes, now_utc, prev=None, errors=None, sk=None):
    """news.json: {"updated_ist", "items", "stocks", "shortlist", "rss_at"}. quotes: {sym: {price,
    prev_close, volume}} for the tape check; volume pace is today's volume against avg_volume
    (passed in each quote as "vavg") for the time of day."""
    errors = errors if errors is not None else []
    prev = prev or {}
    ist = market.to_ist(now_utc)
    eq = inst.get("eq") or {}
    by_key = {eq[s]["key"]: s for s in fo_syms if s in eq}
    raw = []
    try:
        for key, items in upstox.news(list(by_key)).items():
            for n in items:
                raw.append({"symbol": by_key.get(key), "title": n.get("title"), "summary": n.get("summary"),
                            "link": n.get("link"), "source": "Upstox", "time_ms": n.get("time_ms")})
    except Exception as e:                           # noqa: BLE001
        errors.append("Upstox news: %s" % e)
    # the RSS feeds at most every 15 minutes; otherwise keep the last run's RSS items
    rss_at = prev.get("rss_at") or 0
    if time.time() - rss_at >= RSS_EVERY and sk is not None:
        try:
            import morning
            items = morning.tag_items(sk["news"], morning.fetch_feeds(sk["news"], morning.FEEDS, errors, {}))
            pats = morning.news_patterns([(s, names.get(s, "")) for s in fo_syms])
            cutoff = now_utc - datetime.timedelta(days=3)
            for sym, its in morning.match_items(items, pats, cutoff).items():
                for it in its:
                    t = it.get("time")
                    raw.append({"symbol": sym, "title": it.get("title"), "summary": "", "link": it.get("link"),
                                "source": it.get("source") or "RSS",
                                "time_ms": int(t.timestamp() * 1000) if t else None})
            rss_at = time.time()
        except Exception as e:                       # noqa: BLE001
            errors.append("RSS feeds: %s" % e)
    else:
        raw += [dict(i, from_prev=True) for i in prev.get("items") or [] if i.get("source") != "Upstox"]

    now_ms = (now_utc - datetime.datetime(1970, 1, 1)).total_seconds() * 1000
    seen, items = set(), []
    for n in raw:
        if not n.get("symbol") or not n.get("title"):
            continue
        k = (n["symbol"], re.sub(r"\W+", " ", n["title"].lower()).strip()[:90])
        if k in seen:
            continue
        seen.add(k)
        age_h = (now_ms - n["time_ms"]) / 3.6e6 if n.get("time_ms") else 48
        if age_h > 24 * 7:
            continue
        tags, w, sign = classify(n["title"], n.get("summary"))
        items.append({"symbol": n["symbol"], "name": names.get(n["symbol"], ""), "title": n["title"],
                      "link": n.get("link"), "source": n.get("source"), "time_ms": n.get("time_ms"),
                      "time": market.to_ist(datetime.datetime(1970, 1, 1) + datetime.timedelta(milliseconds=n["time_ms"]))
                      .strftime("%d %b %H:%M") if n.get("time_ms") else None,
                      "age_h": round(age_h, 1), "tags": tags, "weight": w, "sign": sign,
                      "score": round(w * freshness(age_h), 2)})
    items.sort(key=lambda x: (-x["score"], x["age_h"]))

    in_session = market.OPEN <= ist.time() < market.CLOSE
    elapsed = max(min((ist.hour * 60 + ist.minute - market.OPEN_MIN) / float(market.CLOSE_MIN - market.OPEN_MIN), 1), 0.05)
    stocks = {}
    for it in items:
        s = stocks.setdefault(it["symbol"], {"symbol": it["symbol"], "name": it["name"], "score": 0.0, "net": 0.0,
                                             "tags": [], "titles": []})
        s["score"] += it["score"]
        s["net"] += it["score"] * it["sign"]
        for t in it["tags"]:
            if t not in s["tags"]:
                s["tags"].append(t)
        if len(s["titles"]) < 3:
            s["titles"].append({"title": it["title"], "link": it["link"], "time": it["time"], "sign": it["sign"]})
    shortlist = []
    for s in stocks.values():
        q = quotes.get(s["symbol"]) or {}
        s["score"] = round(s["score"], 1)
        s["direction"] = 1 if s["net"] >= 1 else -1 if s["net"] <= -1 else 0
        if q.get("price") and q.get("prev_close"):
            s["chg_pct"] = round((q["price"] / q["prev_close"] - 1) * 100, 2)
        if q.get("volume") is not None and q.get("vavg"):
            s["volume_pace"] = round(q["volume"] / (q["vavg"] * (elapsed if in_session else 1)), 1)
        chg, pace = s.get("chg_pct"), s.get("volume_pace") or 0
        s["confirmed"] = bool(s["direction"] and chg is not None and chg * s["direction"] >= 1.5 and pace >= 1.3)
        why = None
        if s["direction"] and s["score"] >= 3 and s["confirmed"]:
            why = "%s news, the stock %+.1f%% on %.1fx volume" % ("good" if s["direction"] > 0 else "bad", chg, pace)
        elif s["direction"] and s["score"] >= 5 and not in_session:
            why = "strong %s news before the open: watch the opening range" % ("good" if s["direction"] > 0 else "bad")
        if why:
            shortlist.append(dict(s, why=why, option="CE" if s["direction"] > 0 else "PE"))
    ranked = sorted(stocks.values(), key=lambda x: -x["score"])
    shortlist.sort(key=lambda x: -x["score"])
    return {"updated_ist": ist.strftime("%Y-%m-%d %H:%M"), "in_session": in_session, "rss_at": rss_at,
            "items": items[:200], "stocks": ranked[:120], "shortlist": shortlist[:15],
            "counts": {"headlines": len(items), "stocks": len(stocks), "fo_stocks": len(fo_syms)}}
