"""Upstox as the first data source; Yahoo stays the backup.

Read-only, with Upstox's Analytics Token (Developer Apps > Analytics): free, valid 12
months, and its Market Quote and Historical Data APIs answer from any server, so it
works from GitHub Actions with no static IP. The token comes from the environment
(UPSTOX_ANALYTICS_TOKEN, a GitHub Actions secret), never from a file in this repo.

What it gives the board:
  quotes()        live price, today's volume and yesterday's close, 500 stocks a request
  chart_text()    today's 5-minute bars plus about 58 past sessions, in the shape of
                  Yahoo's v8 chart JSON, so the trader skills read it unchanged
  daily_bars()    years of daily bars in one request (the swing scan)
  fundamentals()  key ratios against the sector, yearly and quarterly results, shareholding
  news()          each stock's news of the last 7 days, 30 stocks a request
  instruments()   NSE equities (key, ISIN) and F&O stocks with their lot sizes

Docs (read 2026-10-27): upstox.com/developer/api-documentation/ analytics-token,
get-full-market-quote, v3/get-intra-day-candle-data, v3/get-historical-candle-data,
instruments, rate-limiting (50 a second, 500 a minute, 2,000 per 30 minutes).
"""

import datetime
import gzip
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import market

API = "https://api.upstox.com"
INSTRUMENTS = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
ENV = "UPSTOX_ANALYTICS_TOKEN"
BATCH = 500                     # instruments per quotes request (Upstox's maximum)
WINDOW_DAYS = 28                # 5-minute history: at most one month per request
HISTORY_WINDOWS = 3             # about 58 sessions, like Yahoo's range=60d
RATE = 8                        # requests a second, all threads together: 480 a minute, under
                                # Upstox's 500 a minute for any one API
NEWS_BATCH = 30                 # instruments per news request (Upstox's maximum)


class UpstoxError(Exception):
    pass


class TokenError(UpstoxError):
    """401: the token is missing, wrong or expired."""


def token():
    return (os.environ.get(ENV) or "").strip() or None


_slot = [0.0]
_lock = threading.Lock()


def _pace():
    """Hand out request slots 1/RATE seconds apart, across threads."""
    with _lock:
        now = time.time()
        _slot[0] = max(_slot[0] + 1.0 / RATE, now)
        wait = _slot[0] - now
    if wait > 0:
        time.sleep(wait)


def _get(path, timeout=20):
    req = urllib.request.Request(API + path, headers={
        "Authorization": "Bearer " + (token() or ""), "Accept": "application/json", "User-Agent": market.UA})
    for attempt in (0, 1, 2):
        _pace()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                doc = json.loads(r.read().decode("utf-8", "replace"))
            if doc.get("status") != "success":
                raise UpstoxError("Upstox answered %s for %s" % (doc.get("status"), path.split("?")[0]))
            return doc.get("data")
        except urllib.error.HTTPError as e:
            body = e.read()[:200].decode("utf-8", "replace")
            if e.code == 401:
                raise TokenError("Upstox rejected the token (HTTP 401): make a new Analytics Token and update "
                                 "the %s secret" % ENV)
            if e.code == 429 and attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            raise UpstoxError("HTTP %d from Upstox for %s: %s" % (e.code, path.split("?")[0], body))
        except urllib.error.URLError as e:
            raise UpstoxError("could not reach Upstox: %s" % e.reason)
    raise UpstoxError("Upstox kept answering 429 for %s" % path.split("?")[0])


_instruments = {}


def instruments():
    """Upstox's daily NSE file (no login needed), read once a run:
    {"eq": {"RELIANCE.NS": {"key", "isin", "name"}}, "fo": {"RELIANCE.NS": lot_size}}.
    "fo" holds the stocks with F&O contracts, the only ones with stock options."""
    if not _instruments:
        req = urllib.request.Request(INSTRUMENTS, headers={"User-Agent": market.UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            rows = json.loads(gzip.decompress(r.read()))
        eq, fo, expiries = {}, {}, {}
        for row in rows:
            if row.get("segment") == "NSE_EQ" and row.get("instrument_type") == "EQ":
                eq[row["trading_symbol"] + ".NS"] = {"key": row["instrument_key"], "isin": row.get("isin"),
                                                     "name": row.get("name")}
            elif row.get("segment") == "NSE_FO" and row.get("underlying_type") == "EQUITY":
                sym = row["underlying_symbol"] + ".NS"
                if row.get("instrument_type") == "FUT":
                    fo[sym] = row.get("lot_size")
                elif row.get("instrument_type") in ("CE", "PE") and row.get("expiry"):
                    d = market.to_ist(datetime.datetime(1970, 1, 1) + datetime.timedelta(milliseconds=row["expiry"])).date()
                    expiries.setdefault(sym, set()).add(d.isoformat())
        _instruments.update(eq=eq, fo=fo, expiries={s: sorted(v) for s, v in expiries.items()})
    return _instruments


def instrument_keys():
    """{"RELIANCE.NS": "NSE_EQ|INE002A01018"} for NSE equities."""
    return {s: v["key"] for s, v in instruments()["eq"].items()}


def quotes(symbols, keys):
    """{sym: {price, volume, prev_close, open, high, low, time}} for every symbol Upstox knows.
    Raises TokenError at once; any other failure of a batch is raised too (the caller falls back)."""
    by_key = {keys[s]: s for s in symbols if s in keys}
    order = list(by_key)
    out = {}
    for i in range(0, len(order), BATCH):
        part = order[i:i + BATCH]
        data = _get("/v2/market-quote/quotes?instrument_key=" + ",".join(urllib.parse.quote(k, safe="") for k in part))
        for q in (data or {}).values():
            sym = by_key.get(q.get("instrument_token"))
            price = q.get("last_price")
            if not sym or not price:
                continue
            ohlc = q.get("ohlc") or {}
            chg = q.get("net_change")
            out[sym] = {"price": float(price), "volume": int(q.get("volume") or 0),
                        "prev_close": round(float(price) - float(chg), 2) if chg is not None else None,
                        "open": ohlc.get("open"), "high": ohlc.get("high"), "low": ohlc.get("low"),
                        "time": q.get("last_trade_time")}
    return out


def _candles(path):
    return (_get(path) or {}).get("candles") or []


def _epoch(stamp):
    return int(datetime.datetime.fromisoformat(stamp).timestamp())


def chart_text(sym, key, now_utc, prev_close=None):
    """Today's 5-minute bars and ~58 past sessions as Yahoo v8 chart JSON text (what tm.fetch_chart returns)."""
    k = urllib.parse.quote(key, safe="")
    today = market.to_ist(now_utc).date()
    rows = list(_candles("/v3/historical-candle/intraday/%s/minutes/5" % k))
    to = today - datetime.timedelta(days=1)
    for _ in range(HISTORY_WINDOWS):
        frm = to - datetime.timedelta(days=WINDOW_DAYS - 1)
        rows += _candles("/v3/historical-candle/%s/minutes/5/%s/%s" % (k, to.isoformat(), frm.isoformat()))
        to = frm - datetime.timedelta(days=1)
    bars = {}
    for c in rows:                                   # [time, open, high, low, close, volume, oi], newest first
        if len(c) >= 6 and None not in c[1:5]:
            bars[_epoch(c[0])] = c
    if not bars:
        raise UpstoxError("Upstox has no 5-minute bars for %s" % sym)
    ts = sorted(bars)
    now_epoch = int((now_utc - datetime.datetime(1970, 1, 1)).total_seconds())
    meta = {"symbol": sym, "dataSource": "upstox", "regularMarketPrice": bars[ts[-1]][4],
            "regularMarketTime": min(ts[-1] + 300, now_epoch),
            "previousClose": prev_close, "chartPreviousClose": prev_close}
    quote = {name: [bars[t][i] for t in ts] for i, name in ((1, "open"), (2, "high"), (3, "low"), (4, "close"))}
    quote["volume"] = [int(bars[t][5] or 0) for t in ts]
    return json.dumps({"chart": {"result": [{"meta": meta, "timestamp": ts, "indicators": {"quote": [quote]}}],
                                 "error": None}})


# ---------------------------------------------------------------- swing: daily bars, fundamentals, news

def daily_bars(key, to_date, years=3):
    """[{"d": "2026-10-27", "o", "h", "l", "c", "v"}] oldest first, through to_date (one request)."""
    frm = to_date.replace(year=to_date.year - years)
    rows = _candles("/v3/historical-candle/%s/days/1/%s/%s" % (urllib.parse.quote(key, safe=""),
                                                              to_date.isoformat(), frm.isoformat()))
    out = {}
    for c in rows:
        if len(c) >= 6 and None not in c[1:5]:
            out[c[0][:10]] = {"d": c[0][:10], "o": float(c[1]), "h": float(c[2]), "l": float(c[3]),
                              "c": float(c[4]), "v": int(c[5] or 0)}
    return [out[d] for d in sorted(out)]


def _num(text):
    """"8.94%" -> 8.94, "1,234.5" -> 1234.5, junk -> None."""
    try:
        return float(str(text).replace("%", "").replace(",", "").strip())
    except ValueError:
        return None


def fundamentals(isin):
    """Key ratios (company and sector), latest yearly and quarterly results with their change,
    and shareholding now and its change over about a year; 4 requests."""
    out = {"isin": isin}
    for r in _get("/v2/fundamentals/%s/key-ratios" % isin) or []:
        name = (r.get("name") or "").lower().replace("/", "").replace(" ", "_")   # "P/E" -> "pe"
        out[name] = _num(r.get("company_value"))
        out[name + "_sector"] = _num(r.get("sector_value"))
    for period, tag in (("yearly", "y"), ("quarterly", "q")):
        inc = _get("/v2/fundamentals/%s/income-statement?time_period=%s" % (isin, period)) or {}
        for cat in inc.get("income_statement") or []:
            hist = cat.get("history") or []           # newest first
            if hist:
                name = "%s_%s" % (cat.get("category"), tag)
                out[name] = hist[0].get("value")
                out[name + "_chg"] = _num(hist[0].get("change"))
                out[name + "_period"] = hist[0].get("period")
    for cat in _get("/v2/fundamentals/%s/share-holdings" % isin) or []:
        vals = [h.get("value") for h in cat.get("history") or []]        # newest first
        name = "hold_" + (cat.get("category") or "")
        if vals and vals[0] is not None:
            out[name] = vals[0]
            out[name + "_chg"] = round(vals[0] - vals[-1], 2) if vals[-1] is not None else None
    return out


def option_chain(key, expiry):
    """Every strike of one expiry: [{"strike", "spot", "pcr", "call": {...}, "put": {...}}], where each
    side has ltp, bid, ask, volume, oi, prev_oi, close (all per share; oi in shares) and the greeks
    delta, gamma, theta (Rs a share a calendar day), vega (Rs a share per IV point), iv (% a year)."""
    out = []
    for s in _get("/v2/option/chain?instrument_key=%s&expiry_date=%s" % (urllib.parse.quote(key, safe=""), expiry)) or []:
        row = {"strike": s.get("strike_price"), "spot": s.get("underlying_spot_price"), "pcr": s.get("pcr")}
        for side, name in (("call_options", "call"), ("put_options", "put")):
            o = s.get(side) or {}
            md, g = o.get("market_data") or {}, o.get("option_greeks") or {}
            row[name] = {"ltp": md.get("ltp"), "bid": md.get("bid_price"), "ask": md.get("ask_price"),
                         "volume": md.get("volume"), "oi": md.get("oi"), "prev_oi": md.get("prev_oi"),
                         "close": md.get("close_price"), "delta": g.get("delta"), "gamma": g.get("gamma"),
                         "theta": g.get("theta"), "vega": g.get("vega"), "iv": g.get("iv"), "pop": g.get("pop")}
        out.append(row)
    return sorted(out, key=lambda r: r["strike"] or 0)


def news(keys, page_size=100):
    """{instrument_key: [{"title", "summary", "link", "time_ms"}]}, the last 7 days, 30 keys a request."""
    out = {}
    keys = list(keys)
    for i in range(0, len(keys), NEWS_BATCH):
        part = keys[i:i + NEWS_BATCH]
        data = _get("/v2/news?category=instrument_keys&page_size=%d&instrument_keys=%s"
                    % (page_size, ",".join(urllib.parse.quote(k, safe="") for k in part))) or {}
        for k, items in data.items():
            out[k] = [{"title": n.get("heading"), "summary": n.get("summary"), "link": n.get("article_link"),
                       "time_ms": n.get("published_time")} for n in items or []]
    return out
