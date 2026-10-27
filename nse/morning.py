"""NSE morning run: news + volume + the trader skills -> docs/ (the dashboard).

    python nse/morning.py pre        # 9:00 IST: news across the market, the daily scan, the shortlist
    python nse/morning.py orb        # 9:35 IST: opening range, entry, exit, time machine, size, risk
    python nse/morning.py all        # both, one after the other (testing)
    python nse/morning.py refresh    # the dashboard's Refresh button: all, compared with the board it replaces
    python nse/morning.py orb --now "2026-10-27 10:15"   # pin the clock (India time)

Data: Upstox first (live quotes and 5-minute bars, when UPSTOX_ANALYTICS_TOKEN is set),
Yahoo as the backup for anything Upstox does not answer, and always for the daily
closes behind the five setups. See upstox.py.

What each trader skill does here:
  trader-scanner      daily closes of every NSE stock, the five setups, liquidity
  trader-news         headline parsing and tags; the feeds are Indian market RSS
                      (Economic Times, Moneycontrol, Mint, Business Standard,
                      Google News), because Yahoo's headline feed is empty for .NS
  trader-entry        the 15-minute opening range and the breakout bar
  trader-exit         stop at the range midpoint, target at 2R
  trader-timemachine  10,000 replays of the rest of the day + the rule on 60 days
  trader-budget       whole shares inside the max loss, position cap and cash
  trader-risk         PASS / BLOCK against config.json
  trader-alerts       the stop, target and flat-by alerts for each plan
  trader-analyst      SEC EDGAR only: Indian companies do not file there, so
                      results come from the news tags (earnings) instead
  trader-broker       not used: it talks to Alpaca (US). Nothing here places orders.
  trader-pelosi       not used: US Congress trades say nothing about NSE stocks.

Nothing here is a recommendation. The ranking is "most news + most traded",
the odds are a replay of the stock's own last 60 days, not a forecast.
"""

import argparse
import datetime
import html
import json
import math
import os
import re
import sys
import time
import urllib.parse
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import market  # noqa: E402
import upstox  # noqa: E402

ROOT = market.ROOT
OUT = os.path.join(ROOT, "docs")                 # GitHub Pages serves /docs
STATE = os.path.join(ROOT, "trader")
UNIVERSE = os.path.join(STATE, "universe.txt")

FEEDS = [
    ("Economic Times", "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms"),
    ("Economic Times", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("Economic Times", "https://economictimes.indiatimes.com/markets/stocks/earnings/rssfeeds/2143429.cms"),
    ("Moneycontrol", "https://www.moneycontrol.com/rss/buzzingstocks.xml"),
    ("Moneycontrol", "https://www.moneycontrol.com/rss/latestnews.xml"),
    ("Moneycontrol", "https://www.moneycontrol.com/rss/results.xml"),
    ("Mint", "https://www.livemint.com/rss/markets"),
    ("Business Standard", "https://www.business-standard.com/rss/markets-106.rss"),
    ("Google News", "https://news.google.com/rss/search?q=stocks+to+watch+today+NSE+when:1d&hl=en-IN&gl=IN&ceid=IN:en"),
    ("Google News", "https://news.google.com/rss/search?q=shares+NSE+when:1d&hl=en-IN&gl=IN&ceid=IN:en"),
    ("Google News", "https://news.google.com/rss/search?q=Q2+results+shares+when:1d&hl=en-IN&gl=IN&ceid=IN:en"),
    ("Google News", "https://news.google.com/rss/search?q=order+win+shares+when:1d&hl=en-IN&gl=IN&ceid=IN:en"),
]
COMPANY_NEWS = "https://news.google.com/rss/search?q=%s&hl=en-IN&gl=IN&ceid=IN:en"

# tags for Indian headlines, added to trader-news' own list
INDIA_KEYWORDS = [
    ("earnings", r"\bQ[1-4]\b|\bprofit\b|\brevenue\b|\bnet loss\b|\bPAT\b|\bEBITDA\b|\bmargin"),
    ("deal", r"\border(?:s)? (?:win|worth|from)\b|\bbags?\b.*\border\b|\bstake\b|\bblock deal\b|\bbulk deal\b|\bJV\b"),
    ("capital", r"\bbonus\b|\bsplit\b|\bQIP\b|\brights issue\b|\bOFS\b|\bIPO\b|\bfund ?rais"),
    ("regulatory", r"\bSEBI\b|\bRBI\b|\bUSFDA\b|\bCCI\b|\bNCLT\b|\bwarning letter\b|\bpenalty\b"),
    ("analyst", r"\btarget price\b|\bbrokerage\b|\brating\b|\bbuy call\b|\binitiates? coverage\b|\bMotilal\b|\bJefferies\b|\bCLSA\b|\bNomura\b"),
]
STRONG_TAGS = {"earnings", "deal", "analyst", "capital", "regulatory", "legal", "risk", "people"}

# headline words that are also tickers, and common short names headlines use
NOT_A_TICKER = {"NSE", "BSE", "IPO", "CEO", "CFO", "GDP", "RBI", "SEBI", "USA", "FII", "DII", "ETF", "MSCI",
                "FPI", "GST", "EPS", "PAT", "MCAP", "NIFTY", "SENSEX", "INDIA", "BANK", "GOLD", "OIL", "POWER",
                "TATA", "ADANI", "JIO", "THE", "AND", "FOR", "NEW", "IT", "AI", "EV", "US", "UK", "EU"}
ALIASES = {
    "LT.NS": ["L&T", "Larsen & Toubro", "Larsen and Toubro"], "SBIN.NS": ["SBI", "State Bank of India"],
    "HINDUNILVR.NS": ["HUL", "Hindustan Unilever"], "INFY.NS": ["Infosys"], "RELIANCE.NS": ["Reliance Industries", "RIL"],
    "BHARTIARTL.NS": ["Bharti Airtel", "Airtel"], "MARUTI.NS": ["Maruti Suzuki", "Maruti"], "ETERNAL.NS": ["Eternal", "Zomato"],
    "M&M.NS": ["M&M", "Mahindra & Mahindra", "Mahindra and Mahindra"], "BAJFINANCE.NS": ["Bajaj Finance"],
    "KOTAKBANK.NS": ["Kotak Mahindra Bank", "Kotak Bank"], "ICICIBANK.NS": ["ICICI Bank"], "AXISBANK.NS": ["Axis Bank"],
    "HCLTECH.NS": ["HCLTech", "HCL Tech"], "SUNPHARMA.NS": ["Sun Pharma"], "TATASTEEL.NS": ["Tata Steel"],
    "ADANIENT.NS": ["Adani Enterprises"], "ADANIPORTS.NS": ["Adani Ports"], "ONGC.NS": ["ONGC"], "NTPC.NS": ["NTPC"],
    "PAYTM.NS": ["Paytm", "One 97"], "NYKAA.NS": ["Nykaa"], "DMART.NS": ["DMart", "Avenue Supermarts"],
    "BAJAJ-AUTO.NS": ["Bajaj Auto"], "HEROMOTOCO.NS": ["Hero MotoCorp"], "ULTRACEMCO.NS": ["UltraTech"],
    "ASIANPAINT.NS": ["Asian Paints"], "TITAN.NS": ["Titan"], "WIPRO.NS": ["Wipro"], "TECHM.NS": ["Tech Mahindra"],
}
SUFFIX = re.compile(r"\s+(limited|ltd\.?|corporation|corp\.?|company|co\.?|\(india\)|india)$", re.I)


# ---------------------------------------------------------------- helpers

def log(msg):
    print("[%s] %s" % (market.to_ist(market.utc_now()).strftime("%H:%M:%S"), msg), flush=True)


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def write_json(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1, default=str, ensure_ascii=False)
        fh.write("\n")


def load_config():
    return read_json(os.path.join(ROOT, "config.json"), {})


def read_universe():
    out = []
    with open(UNIVERSE, encoding="utf-8") as fh:
        for line in fh:
            sym, _, name = line.strip().partition("|")
            if sym:
                out.append((sym, name))
    return out


def short_name(name):
    n = " ".join(name.split())
    for _ in range(3):
        n2 = SUFFIX.sub("", n).strip(" .,")
        if n2 == n:
            break
        n = n2
    return n


def pct_rank(values):
    """{key: 0..1} by rank, ties share the lower rank."""
    keys = sorted(values, key=lambda k: values[k])
    n = len(keys)
    if n <= 1:
        return {k: 1.0 for k in keys}
    out, i = {}, 0
    while i < n:
        j = i
        while j + 1 < n and values[keys[j + 1]] == values[keys[i]]:
            j += 1
        for k in keys[i:j + 1]:
            out[k] = i / (n - 1)
        i = j + 1
    return out


def inr(x, dp=0):
    if x is None:
        return None
    return round(float(x), dp)


# ---------------------------------------------------------------- data sources: Upstox first, Yahoo backup

class Sources(object):
    """Which source answered. Upstox when its token is set and it answers; Yahoo for
    anything it does not. A rejected token stops every later Upstox call this run."""

    def __init__(self, errors):
        self.errors = errors
        self.keys = None
        self.status = "set, not needed yet" if upstox.token() else "no token"
        self.charts = {"Upstox": 0, "Yahoo": 0}

    def ready(self):
        if self.status in ("no token", "token rejected", "instrument list failed"):
            return False
        if self.keys is None:
            try:
                self.keys = upstox.instrument_keys()
            except Exception as e:                   # noqa: BLE001 - Yahoo carries the run
                self.errors.append("Upstox instrument list: %s; used Yahoo" % e)
                self.status = "instrument list failed"
                return False
        return bool(self.keys)

    def _rejected(self, e):
        self.status = "token rejected"
        self.errors.append(str(e))

    def quotes(self, symbols):
        if not self.ready():
            return {}
        try:
            q = upstox.quotes(symbols, self.keys)
        except upstox.TokenError as e:
            self._rejected(e)
            return {}
        except Exception as e:                       # noqa: BLE001
            self.errors.append("Upstox quotes: %s; used Yahoo" % e)
            self.status = "quotes failed"
            return {}
        self.status = "ok"
        return q

    def chart(self, sym, now_utc, tm, prev_close=None):
        """Yahoo-shaped chart text and who supplied it."""
        if self.ready() and sym in self.keys:
            try:
                text = upstox.chart_text(sym, self.keys[sym], now_utc, prev_close)
                self.charts["Upstox"] += 1
                if self.status != "quotes failed":
                    self.status = "ok"
                return text, "Upstox"
            except upstox.TokenError as e:
                self._rejected(e)
            except Exception as e:                   # noqa: BLE001
                self.errors.append("Upstox bars for %s: %s; used Yahoo" % (sym, e))
        text = tm.fetch_chart(sym)
        self.charts["Yahoo"] += 1
        return text, "Yahoo"


def daily_setups(symbols, now_utc, sc, scan_cfg, cache_path, use_cache):
    """trader-scanner's five setups on daily closes (Yahoo, 20 stocks a request), plus each stock's
    last price, volume and close before today. Saved once a day: a refresh with live Upstox
    quotes reuses it, since the setups use completed days only and do not change during the day."""
    cached = read_json(cache_path) if use_cache else None
    if cached:
        return cached
    data, failed = sc.fetch_spark(symbols, "3mo", "1d", 0.3, None)
    hits, counts, last_date = sc.scan_daily(data, symbols, now_utc, scan_cfg.get("min_price", 20),
                                            scan_cfg.get("min_volume", 100000))
    today = market.to_ist(now_utc).date()
    last = {}
    for sym in symbols:
        s = data.get(sym)
        if not s:
            continue
        meta = s.get("meta") or {}
        # during the session the last daily bar is today's, so take the last close before today
        prev = [c for t, c in zip(s.get("t") or [], s.get("c") or [])
                if c and market.to_ist(datetime.datetime.fromtimestamp(t, datetime.timezone.utc)).date() < today]
        last[sym] = {"price": meta.get("regularMarketPrice"), "volume": meta.get("regularMarketVolume") or 0,
                     "prev_close": prev[-1] if prev else None}
    doc = {"created_ist": market.to_ist(now_utc).strftime("%Y-%m-%d %H:%M"),
           "closes_through": last_date.isoformat() if last_date else None,
           "counts": {"fetched": counts["fetched"], "scanned": counts["scanned"]}, "failed": len(failed),
           "hits": {h["symbol"]: {"setups": h["setups"], "rsi": h.get("rsi")} for h in hits}, "last": last}
    write_json(cache_path, doc)
    for name in os.listdir(STATE):                   # only today's is ever read; keep the repo small
        if name.startswith("setups-") and name != os.path.basename(cache_path):
            os.remove(os.path.join(STATE, name))
    return doc


def cross_check(rows, sc, errors, limit_pct=1.0):
    """Upstox's price against Yahoo's for the shortlist (one Yahoo request for 20 stocks)."""
    live = [r["symbol"] for r in rows if r.get("price_source") == "Upstox"]
    if not live:
        return
    try:
        data, _ = sc.fetch_spark(live, "1d", "5m", 0.3, None)
    except Exception as e:                           # noqa: BLE001
        errors.append("cross-check with Yahoo: %s" % e)
        return
    for r in rows:
        meta = ((data.get(r["symbol"]) or {}).get("meta") or {})
        y, t = meta.get("regularMarketPrice"), meta.get("regularMarketTime")
        if not y or r.get("price_source") != "Upstox":
            continue
        gap = abs(r["price"] - y) / r["price"] * 100
        r["cross_check"] = {"yahoo": round(y, 2), "gap_pct": round(gap, 2), "flag": gap > limit_pct,
                            "yahoo_time": market.to_ist(datetime.datetime.fromtimestamp(t, datetime.timezone.utc))
                            .strftime("%H:%M") if t else None}


# ---------------------------------------------------------------- news (trader-news parsing, Indian feeds)

# "ITC Hotels", "SBI Life", "APOLLO TUBES": a short name followed by another capitalised
# word is usually a different company; these words after it are fine
SAME_CO = r"(?:Share|Shares|Stock|Stocks|Ltd|Limited|Q[1-4]|Results?|Price|Target|Rally|Falls?|Jumps?|Slips?)\b"
NOT_ANOTHER_CO = r"(?![\w&])(?-i:(?!\s+(?!%s)[A-Z][A-Za-z]{2,}))" % SAME_CO   # case-sensitive inside re.I


def news_patterns(universe):
    pats = {}
    for sym, name in universe:
        base = sym[:-3]
        alts = []
        sn = short_name(name)
        if len(sn) >= 5:
            alts.append(re.escape(sn).replace(r"\ ", r"[\s-]+"))
        for a in ALIASES.get(sym, []):
            alts.append(re.escape(a).replace(r"\ ", r"\s+") + (NOT_ANOTHER_CO if len(a) <= 4 else ""))
        rx_ci = re.compile(r"(?<![\w&])(?:%s)(?![\w&])" % "|".join(alts), re.I) if alts else None
        rx_sym = None
        if len(base) >= 3 and base.isalpha() and base not in NOT_A_TICKER:
            rx_sym = re.compile(r"(?<![\w&])%s%s" % (re.escape(base), NOT_ANOTHER_CO))   # case-sensitive ticker
        pats[sym] = (rx_ci, rx_sym)
    return pats


REFUSED = re.compile(r"HTTP (401|403|429|503)\b")


REFUSALS = 2                    # one bad feed is not the whole site: stop after the second refusal


def refused_by(host, refused, e):
    """Count a site's refusals (cloud IPs get 403 / 503), so the run stops asking it."""
    if REFUSED.search(str(e)):
        refused[host] = refused.get(host, 0) + 1


def blocked(host, refused):
    return refused.get(host, 0) >= REFUSALS


def host_of(url):
    return urllib.parse.urlsplit(url).netloc


def fetch_feeds(news, feeds, errors, refused):
    fetcher = news.Fetcher(pause=0.4)
    items = []
    for src, url in feeds:
        if blocked(host_of(url), refused):
            errors.append("%s feed: skipped, %s refused earlier in this run" % (src, host_of(url)))
            continue
        try:
            got = news.parse_rss(fetcher.get(url, "feed"), "")
            for it in got:
                it["source"] = src
                t = it.get("title") or ""
                m = re.search(r"\s+-\s+([^-]{2,60})$", t)             # Google News: "title - Publisher"
                if src == "Google News" and m:
                    it["source"] = m.group(1).strip()
                    it["title"] = t[:m.start()].strip()
            items += got
        except Exception as e:                       # noqa: BLE001 - one feed down is not the run down
            errors.append("%s feed: %s" % (src, e))
            refused_by(host_of(url), refused, e)
    return items


def tag_items(news, items):
    for it in items:
        hay = "%s %s" % (it.get("title") or "", re.sub(r"<[^>]+>", " ", it.get("summary") or ""))
        tags = [label for label, rx in news.KEYWORDS + INDIA_KEYWORDS if re.search(rx, hay, re.I)]
        it["tags"] = sorted(set(tags), key=tags.index)
        it["hay"] = hay
    return items


def match_items(items, pats, cutoff):
    """{sym: [items]} for items newer than cutoff that name the company."""
    seen, by_sym = set(), {}
    for it in items:
        if it.get("time") and it["time"].replace(tzinfo=None) < cutoff:
            continue
        key = re.sub(r"\W+", " ", (it.get("title") or "").lower()).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        hay = it["hay"]
        for sym, (rx_ci, rx_sym) in pats.items():
            if (rx_ci and rx_ci.search(hay)) or (rx_sym and rx_sym.search(hay)):
                by_sym.setdefault(sym, []).append(it)
    return by_sym


def news_score(items):
    return sum(1.0 + (1.0 if set(it.get("tags") or []) & STRONG_TAGS else 0.0) for it in items)


def public_item(it):
    t = it.get("time")
    return {"title": html.unescape(it.get("title") or ""), "source": it.get("source"), "link": it.get("link"),
            "time": market.to_ist(t.replace(tzinfo=None)).strftime("%d %b %H:%M") if t else None,
            "tags": it.get("tags") or []}


# ---------------------------------------------------------------- stage 1: pre-open

def stage_pre(now_utc, cfg, sk, src):
    t0 = time.time()
    errors = []
    universe = read_universe()
    names = dict(universe)
    symbols = [s for s, _ in universe]
    scan_cfg = cfg.get("scan", {})
    rank_cfg = cfg.get("rank", {})
    ist = market.to_ist(now_utc)
    min_price, min_volume = scan_cfg.get("min_price", 20), scan_cfg.get("min_volume", 100000)

    # live prices from the open on: Upstox, every NSE stock in about 5 requests
    live = {}
    if ist.time() >= market.OPEN:
        live = src.quotes(symbols)
        if live:
            log("upstox: live quotes for %d of %d stocks" % (len(live), len(symbols)))

    # trader-scanner: daily closes of every NSE stock (Yahoo), saved for the day's refreshes
    sc = sk["scanner"]
    cache_path = os.path.join(STATE, "setups-%s.json" % ist.date().isoformat())
    use_cache = len(live) >= 0.9 * len(symbols)
    if not (use_cache and os.path.exists(cache_path)):
        log("scanner: daily closes for %d NSE stocks" % len(symbols))
    daily = daily_setups(symbols, now_utc, sc, scan_cfg, cache_path, use_cache)
    setups, last, counts = daily["hits"], daily["last"], daily["counts"]
    liquid = {}
    for sym in symbols:
        u, y = live.get(sym), last.get(sym) or {}
        q = u or y
        p, v = q.get("price"), q.get("volume") or 0
        # liquid on the larger of today's volume so far and the last session's, so the list
        # does not shrink to nothing at 9:20; ranked on the volume the price source reports
        if not p or p < min_price or max(v, y.get("volume") or 0) < min_volume:
            continue
        prev = q.get("prev_close") or y.get("prev_close")
        liquid[sym] = {"price": p, "volume": v, "turnover": p * v, "source": "Upstox" if u else "Yahoo",
                       "chg_pct": round((p / prev - 1) * 100, 2) if prev else None}
    log("scanner: %d of %d fetched, %d liquid, %d setups%s" % (
        counts["fetched"], len(symbols), len(liquid), len(setups),
        " (setups saved at %s)" % daily["created_ist"][11:] if daily["created_ist"] != ist.strftime("%Y-%m-%d %H:%M") else ""))

    # trader-news: market-wide Indian feeds, matched to every ticker
    news = sk["news"]
    hours = rank_cfg.get("news_hours", 24)
    cutoff = now_utc - datetime.timedelta(hours=hours)
    log("news: %d market feeds" % len(FEEDS))
    refused = {}
    items = tag_items(news, fetch_feeds(news, FEEDS, errors, refused))
    pats = news_patterns([(s, n) for s, n in universe if s in liquid])
    by_sym = match_items(items, pats, cutoff)
    log("news: %d headlines, %d liquid stocks named" % (len(items), len(by_sym)))

    # first ranking: news + turnover over every liquid stock named in the news
    def ranked(by):
        named = {s: news_score(v) for s, v in by.items() if s in liquid}
        if not named:
            return [], {}
        nr = pct_rank(named)
        tr = pct_rank({s: liquid[s]["turnover"] for s in named})
        score = {s: 0.5 * nr[s] + 0.4 * tr[s] + (0.1 if s in setups else 0.0) for s in named}
        return sorted(named, key=lambda s: (-score[s], -liquid[s]["turnover"])), score

    order, _ = ranked(by_sym)
    pool = order[:max(30, rank_cfg.get("shortlist", 20) + 10)]

    # each company's own news (Google News, last day) for the pool
    fetcher = news.Fetcher(pause=0.5)
    if blocked(host_of(COMPANY_NEWS), refused):
        log("news: company headlines skipped, %s refused this run" % host_of(COMPANY_NEWS))
        errors.append("company news: skipped for %d stocks, %s refused earlier in this run"
                      % (len(pool), host_of(COMPANY_NEWS)))
        pool_news = []
    else:
        log("news: company headlines for %d stocks" % len(pool))
        pool_news = pool
    for i, sym in enumerate(pool_news):
        if blocked(host_of(COMPANY_NEWS), refused):
            errors.append("company news: skipped the other %d stocks, %s refused"
                          % (len(pool_news) - i, host_of(COMPANY_NEWS)))
            break
        q = '"%s" share when:1d' % (ALIASES.get(sym, [short_name(names[sym])])[0])
        url = COMPANY_NEWS % urllib.parse.quote(q)
        try:
            got = news.parse_rss(fetcher.get(url, "company"), sym)
        except Exception as e:                       # noqa: BLE001
            errors.append("company news for %s: %s" % (sym, e))
            refused_by(host_of(url), refused, e)
            continue
        for it in got:
            it["source"] = "Google News"
            m = re.search(r"\s+-\s+([^-]{2,60})$", it.get("title") or "")
            if m:
                it["source"], it["title"] = m.group(1).strip(), it["title"][:m.start()].strip()
        tag_items(news, got)
        extra = match_items(got, {sym: pats[sym]}, cutoff).get(sym, [])
        have = {re.sub(r"\W+", " ", (i.get("title") or "").lower()).strip() for i in by_sym.get(sym, [])}
        by_sym.setdefault(sym, []).extend(i for i in extra
                                          if re.sub(r"\W+", " ", i["title"].lower()).strip() not in have)

    order, score = ranked(by_sym)
    shortlist = order[:rank_cfg.get("shortlist", 20)]
    rows = []
    for rank, sym in enumerate(shortlist, 1):
        its = sorted(by_sym[sym], key=lambda i: i.get("time") or datetime.datetime.min.replace(
            tzinfo=datetime.timezone.utc), reverse=True)
        tags = sorted({t for i in its for t in (i.get("tags") or [])})
        h = setups.get(sym)
        rows.append({
            "rank": rank, "symbol": sym, "name": names.get(sym, ""), "score": round(score[sym] * 100),
            "price": inr(liquid[sym]["price"], 2), "chg_pct": liquid[sym]["chg_pct"],
            "volume": int(liquid[sym]["volume"]), "turnover_cr": round(liquid[sym]["turnover"] / 1e7, 1),
            "news_count": len(its), "news_tags": tags, "news": [public_item(i) for i in its[:6]],
            "setups": h["setups"] if h else [], "rsi": h["rsi"] if h else None,
            "earnings_flag": "earnings" in tags, "price_source": liquid[sym]["source"],
        })
    cross_check(rows, sc, errors)
    if not market.OPEN <= ist.time():
        basis = "last session"
    elif ist.time() < market.CLOSE:
        basis = "today so far"
    else:
        basis = "today" if live else "last session"
    doc = {
        "stage": "pre", "market": "NSE", "created_ist": ist.strftime("%Y-%m-%d %H:%M"),
        "volume_basis": basis, "closes_through": daily["closes_through"],
        "scan": {"universe": len(symbols), "fetched": counts["fetched"], "failed": daily["failed"],
                 "liquid": len(liquid), "scanned": counts["scanned"], "setups": len(setups),
                 "min_price": min_price, "min_volume": min_volume},
        "news": {"feeds": len(FEEDS), "headlines": len(items), "stocks_named": len(by_sym), "hours": hours},
        "sources": {"quotes": "Upstox" if live else "Yahoo", "quotes_upstox": len(live),
                    "setups_saved_ist": daily["created_ist"]},
        "shortlist": rows, "errors": errors, "seconds": round(time.time() - t0),
    }
    log("pre: shortlist of %d in %ds" % (len(rows), doc["seconds"]))
    return doc


# ---------------------------------------------------------------- stage 2: after the opening range

def tick_up(x, tick=0.05):
    return round(math.ceil(round(x / tick, 6)) * tick + tick, 2)


def plan_one(sym, cfg, now_utc, sk, src, prev_close=None):
    """entry -> exit -> time machine -> budget -> risk -> alerts, for one stock."""
    pc = cfg.get("plan", {})
    or_min = pc.get("or_minutes", 15)
    target_r = Decimal(str(pc.get("target_r", 2)))
    tm, ent, ex, bud, rk, al = (sk[k] for k in ("timemachine", "entry", "exit", "budget", "risk", "alerts"))
    text, source = src.chart(sym, now_utc, tm, prev_close)      # ~60 days of 5-minute bars
    chart = ent.parse_chart(text, sym)
    ecfg = {"no_entries_before": cfg.get("no_entries_before", "09:30"),
            "no_entries_after": cfg.get("no_entries_after", "14:45")}
    res = ent.evaluate(chart, now_utc, setup="orb", or_minutes=or_min, interval="5m", cfg=ecfg)
    out = {"status": res["status"], "phase": res.get("phase"), "reason": res.get("reason"),
           "opening_range": res.get("opening_range"), "last": res.get("last"), "bars_source": source}
    orr = res.get("opening_range")
    if res["status"] == "no-data" or not orr or not (orr.get("complete")):
        return out
    bars_today = res["_bars"]
    today_vol = sum(b["v"] for b in bars_today)

    # entry: the breakout bar if it fired, else "if it closes above the high on the next bar"
    if res["status"] == "triggered":
        entry, k = res["trigger"]["price"], res["trigger"]["bar_index"]
        entry_time = res["trigger"]["close_time"]
        out["entry_kind"] = "triggered at %s" % res["trigger"]["time"]
    elif res["status"] == "waiting":
        entry, k = tick_up(orr["high"]), max(b["slot"] for b in bars_today)
        entry_time = (datetime.datetime.combine(datetime.date.today(), market.OPEN)
                      + datetime.timedelta(minutes=5 * (k + 1))).strftime("%H:%M")
        out["entry_kind"] = "not triggered: plan if a bar closes above %.2f" % orr["high"]
    else:
        return out

    # trader-exit: stop at the range midpoint, target at 2R
    try:
        p = ex.compute(entry, pc.get("stop", "or_mid"), None, "r", target_r, orr["high"], orr["low"])
    except ex.PlanError as e:
        out["refused"] = "exit: %s" % e
        return out
    plan = {"symbol": sym, "side": "buy", "setup": "orb", "date": market.to_ist(now_utc).date().isoformat(),
            "entry": float(p["entry"]), "stop": float(p["stop"]), "target": float(p["target"]),
            "entry_time": entry_time, "entry_bar": k, "risk_per_share": float(p["risk"]),
            "reward_risk": float(p["reward_risk"]), "stop_label": p["stop_label"], "target_label": p["target_label"],
            "opening_range": {"high": orr["high"], "low": orr["low"], "minutes": or_min},
            "flat_by": cfg.get("flat_by", "15:15"), "interval": "5m"}

    # trader-timemachine: 10,000 replays to flat-by, and the rule on every past session
    result = tm.chart_result(text, sym)
    _, bars, _ = tm.parse_bars(result, now_utc)
    days = tm.split_sessions(bars)
    sessions, short = tm.full_sessions(days, plan["date"])
    fb = plan["flat_by"]
    last = (int(fb[:2]) * 60 + int(fb[3:]) - market.OPEN_MIN) // 5 - 1
    tmd = {"sessions": len(sessions)}
    if len(sessions) >= tm.MIN_SESSIONS and last > k:
        pool = tm.build_pool(sessions)
        mc = tm.simulate(pool, plan["entry"], plan["stop"], plan["target"], k, last, 10000, 19, 2, "buy")
        mc["until"] = fb
        hist = tm.history_replay(sessions, {"setup": "orb", "or_minutes": or_min, "stop_rule": "or_mid",
                                            "target_r": float(target_r)}, last, "buy")
        tmd.update({k2: mc[k2] for k2 in ("p_target", "p_stop", "p_neither", "p_green", "avg_R", "median_close",
                                          "p5_close", "p95_close", "r_at_target")})
        tmd["verdict"] = tm.verdict(mc)
        tmd["notes"] = tm.verdict_notes(mc)
        tmd["history"] = {k2: hist[k2] for k2 in ("sessions", "triggered", "target", "stop", "close", "avg_R")}
        upto = max(b["slot"] for b in bars_today)            # same stretch of the day: 9:15 to the last closed bar
        avg_day_vol = sum(sum(b["v"] for b in D[:upto + 1]) for _, D in sessions) / len(sessions)
        out["rel_volume"] = round(today_vol / avg_day_vol, 2) if avg_day_vol else None
    else:
        tmd["skipped"] = "only %d full sessions in 60 days (needs %d)" % (len(sessions), tm.MIN_SESSIONS)

    # trader-budget: whole shares inside the rupee max loss, position cap and cash
    s = bud.size_trade(plan, cfg)
    order = bud.bracket_order(s)
    sizing = {"qty": s["qty"], "bound_by": s["bound_by"], "cost": s["cost"], "max_loss": s["max_loss"],
              "refusal": s["refusal"]}
    if s["qty"]:
        sizing["reward"] = round(s["qty"] * (plan["target"] - s["entry"]), 2)
        if "avg_R" in tmd:
            sizing["replay_avg"] = round(tmd["avg_R"] * s["max_loss"], 2)

    # trader-risk: PASS or BLOCK (checked at the entry bar's time for a waiting setup)
    if order:
        r = rk.check([order], cfg, now=now_utc, prices={sym: plan["entry"]})
        rr = r["results"][0]
        risk = {"verdict": rr["verdict"],
                "reasons": rr.get("reasons") or [], "warnings": (rr.get("warnings") or []) + r.get("warnings", [])}
    else:
        risk = {"verdict": "BLOCK", "reasons": [s["refusal"] or "no order"], "warnings": []}

    # trader-alerts: stop, target and flat-by
    alerts = al.rules_from_plan(plan, cfg.get("flat_by"))
    out.update(plan=plan, timemachine=tmd, sizing=sizing, risk=risk, order=order,
               alerts=[{"type": a["type"], "price": a.get("price"), "at": a.get("at")} for a in alerts])
    return out


def stage_orb(now_utc, cfg, sk, pre, src):
    t0 = time.time()
    rows = pre.get("shortlist") or []
    log("orb: %d stocks from the %s shortlist" % (len(rows), pre.get("created_ist")))
    for r in rows:
        prev = None
        if r.get("price") and r.get("chg_pct") is not None:
            prev = round(r["price"] / (1 + r["chg_pct"] / 100), 2)
        try:
            r["trade"] = plan_one(r["symbol"], cfg, now_utc, sk, src, prev)
        except Exception as e:                       # noqa: BLE001 - one stock failing is a row, not the run
            r["trade"] = {"status": "error", "reason": str(e)}
        log("  %-16s %s" % (r["symbol"], r["trade"].get("status")))
        time.sleep(0.5)
    doc = dict(pre, stage="orb", orb_ist=market.to_ist(now_utc).strftime("%Y-%m-%d %H:%M"),
               orb_seconds=round(time.time() - t0))
    return doc


def compare_boards(doc, before, day, show):
    """Mark each top-`show` row new / up / down against today's previous board, and list who dropped out."""
    if (before.get("created_ist") or "")[:10] != day or not before.get("shortlist"):
        return
    old = {r["symbol"]: r["rank"] for r in before["shortlist"]}
    top = doc.get("shortlist") or []
    for r in top:
        r["prev_rank"] = old.get(r["symbol"])
    now_top = {r["symbol"] for r in top[:show]}
    doc["previous"] = {
        "created_ist": before.get("created_ist"),
        "entered": [r["symbol"] for r in top[:show] if not r["prev_rank"] or r["prev_rank"] > show],
        "dropped": [{"symbol": r["symbol"], "rank": r["rank"], "name": r.get("name")}
                    for r in before["shortlist"][:show] if r["symbol"] not in now_top],
    }


# ---------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", choices=("pre", "orb", "all", "refresh"),
                    help="refresh = the whole scan and news again now, plus trade numbers after 9:30 IST, "
                         "compared with the board it replaces")
    ap.add_argument("--now", help='pin the clock, India time: "2026-10-27 09:35"')
    ap.add_argument("--force", action="store_true", help="run on a holiday or weekend anyway (testing)")
    a = ap.parse_args(argv)
    cfg = load_config()
    market.load_holidays(cfg.get("holidays"))
    now_utc = market.parse_now(a.now)
    open_today, why, _ = market.session_today(now_utc)
    day = market.to_ist(now_utc).date().isoformat()
    if not open_today and not a.force:
        doc = {"stage": "closed", "market": "NSE", "created_ist": market.to_ist(now_utc).strftime("%Y-%m-%d %H:%M"),
               "closed_reason": why, "shortlist": []}
        write_json(os.path.join(OUT, "data.json"), doc)
        import dashboard
        dashboard.render(doc, os.path.join(OUT, "index.html"))
        log("NSE closed today (%s): wrote a closed dashboard." % why)
        return 0
    if why:
        log(why)
    sk = market.skills()
    pre_path = os.path.join(STATE, "pre-%s.json" % day)
    before = read_json(os.path.join(OUT, "data.json"), {})
    if a.stage == "refresh":
        a.stage = "all"
    src_errors = []
    src = Sources(src_errors)
    log("upstox: %s" % src.status)
    if a.stage in ("pre", "all"):
        doc = stage_pre(now_utc, cfg, sk, src)
        write_json(pre_path, doc)
    else:
        doc = read_json(pre_path)
        if not doc:
            log("no pre-open run for %s yet: running it now" % day)
            doc = stage_pre(now_utc, cfg, sk, src)
            write_json(pre_path, doc)
    if a.stage in ("orb", "all"):
        if a.stage == "all" and not a.now:
            ist = market.to_ist(now_utc)
            if ist.time() < datetime.time(9, 30):
                log("orb: the opening range is not complete before 9:30 IST; skipped")
            else:
                doc = stage_orb(now_utc, cfg, sk, doc, src)
        else:
            doc = stage_orb(now_utc, cfg, sk, doc, src)
    doc["errors"] = list(dict.fromkeys((doc.get("errors") or []) + src_errors))
    doc.setdefault("sources", {}).update(upstox=src.status, bars=src.charts)
    log("sources: upstox %s, quotes from %s, 5-minute bars %s" % (
        src.status, doc["sources"].get("quotes", "Yahoo"),
        ", ".join("%s %d" % kv for kv in src.charts.items() if kv[1]) or "not fetched"))
    compare_boards(doc, before, day, cfg.get("rank", {}).get("show", 10))
    doc["config"] = {k: cfg.get(k) for k in ("budget", "max_loss_per_trade_usd", "max_daily_loss_usd",
                                              "max_trades_per_day", "min_reward_risk", "flat_by", "plan")}
    doc["repo"] = os.environ.get("GITHUB_REPOSITORY") or cfg.get("repo")
    write_json(os.path.join(OUT, "data.json"), doc)
    write_json(os.path.join(STATE, "watchlist.json"),
               {"mode": "nse-morning", "as_of": doc["created_ist"], "hits": [{"symbol": r["symbol"]} for r in doc["shortlist"]]})
    import dashboard
    dashboard.render(doc, os.path.join(OUT, "index.html"))
    log("wrote docs/index.html and docs/data.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
