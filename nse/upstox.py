"""Upstox as the first data source; Yahoo stays the backup.

Read-only, with Upstox's Analytics Token (Developer Apps > Analytics): free, valid 12
months, and its Market Quote and Historical Data APIs answer from any server, so it
works from GitHub Actions with no static IP. The token comes from the environment
(UPSTOX_ANALYTICS_TOKEN, a GitHub Actions secret), never from a file in this repo.

What it gives the board:
  quotes()      live price, today's volume and yesterday's close, 500 stocks a request
  chart_text()  today's 5-minute bars plus about 58 past sessions, in the shape of
                Yahoo's v8 chart JSON, so the trader skills read it unchanged

Docs (read 2026-10-27): upstox.com/developer/api-documentation/ analytics-token,
get-full-market-quote, v3/get-intra-day-candle-data, v3/get-historical-candle-data,
instruments, rate-limiting (50 a second, 500 a minute, 2,000 per 30 minutes).
"""

import datetime
import gzip
import json
import os
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
GAP = 0.05                      # seconds between requests: 20 a second, well under 50


class UpstoxError(Exception):
    pass


class TokenError(UpstoxError):
    """401: the token is missing, wrong or expired."""


def token():
    return (os.environ.get(ENV) or "").strip() or None


_last = [0.0]


def _get(path, timeout=20):
    wait = GAP - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(API + path, headers={
        "Authorization": "Bearer " + (token() or ""), "Accept": "application/json", "User-Agent": market.UA})
    for attempt in (0, 1):
        _last[0] = time.time()
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
            if e.code == 429 and attempt == 0:
                time.sleep(2)
                continue
            raise UpstoxError("HTTP %d from Upstox for %s: %s" % (e.code, path.split("?")[0], body))
        except urllib.error.URLError as e:
            raise UpstoxError("could not reach Upstox: %s" % e.reason)
    raise UpstoxError("Upstox kept answering 429 for %s" % path.split("?")[0])


def instrument_keys():
    """{"RELIANCE.NS": "NSE_EQ|INE002A01018"} for NSE equities, from Upstox's daily file (no login needed)."""
    req = urllib.request.Request(INSTRUMENTS, headers={"User-Agent": market.UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        rows = json.loads(gzip.decompress(r.read()))
    return {row["trading_symbol"] + ".NS": row["instrument_key"] for row in rows
            if row.get("segment") == "NSE_EQ" and row.get("instrument_type") == "EQ"}


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
