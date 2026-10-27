"""NSE clock for the trader skills.

The trader-* skills are written for the NYSE: New York time, 9:30 to 16:00,
78 five-minute bars and the US holiday list. Their maths (stops, sizing, the
Monte Carlo replays, the risk rules) does not care which market it is. This
module loads each skill as a library and swaps its clock for NSE's:
India time (UTC+5:30, no daylight saving), 9:15 to 15:30, 75 five-minute bars.

Holidays come from the data, not a list: Yahoo's chart for the NIFTY 50
(^NSEI) reports the next regular session, so a weekday whose session is not
today is a holiday. Extra dates can go in config.json "holidays".
"""

import datetime
import importlib.util
import json
import os
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS = os.path.join(ROOT, "skills")

IST = datetime.timedelta(hours=5, minutes=30)
OPEN = datetime.time(9, 15)
CLOSE = datetime.time(15, 30)
OPEN_MIN = 9 * 60 + 15
CLOSE_MIN = 15 * 60 + 30
SESSION_BARS = (CLOSE_MIN - OPEN_MIN) // 5          # 75
INDEX = "^NSEI"
UA = "Mozilla/5.0 (compatible; nse-morning/1.0)"

HOLIDAYS = {}                                        # filled by load_holidays()


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0, tzinfo=None)


def to_ist(utc):
    return utc.replace(tzinfo=None) + IST


def ist_to_utc(local):
    return local.replace(tzinfo=None) - IST


def parse_now(text):
    """"2026-10-27 09:35" (India time) or ISO with an offset -> naive UTC."""
    if not text:
        return utc_now()
    dt = datetime.datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return ist_to_utc(dt)
    return (dt - dt.utcoffset()).replace(tzinfo=None)


def trading_day(d):
    if d.weekday() >= 5:
        return False, "weekend"
    name = HOLIDAYS.get(d.isoformat())
    if name:
        return False, "NSE holiday: " + name
    return True, ""


def session(d):
    return (OPEN, CLOSE) if trading_day(d)[0] else None


def yahoo_symbol(sym):
    """RELIANCE.NS stays RELIANCE.NS; M&M.NS is URL-encoded."""
    return urllib.parse.quote(sym.upper(), safe=".-^=")


def yahoo_json(path, timeout=20):
    last = None
    for host in ("query2", "query1"):
        try:
            req = urllib.request.Request("https://%s.finance.yahoo.com%s" % (host, path),
                                         headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:                       # noqa: BLE001 - try the other host
            last = e
    raise RuntimeError("Yahoo did not answer for %s: %s" % (path, last))


def load_holidays(cfg_holidays=None):
    HOLIDAYS.clear()
    for d in cfg_holidays or []:
        HOLIDAYS[str(d)] = "from config.json"


def session_today(now_utc):
    """(open_today, reason, next_session_date) from the NIFTY 50 chart's trading period."""
    today = to_ist(now_utc).date()
    ok, why = trading_day(today)
    if not ok:
        return False, why, None
    try:
        doc = yahoo_json("/v8/finance/chart/%s?range=1d&interval=5m" % yahoo_symbol(INDEX))
        reg = doc["chart"]["result"][0]["meta"]["currentTradingPeriod"]["regular"]
        start = to_ist(datetime.datetime(1970, 1, 1) + datetime.timedelta(seconds=reg["start"])).date()
    except Exception as e:                           # noqa: BLE001 - say we could not tell, run anyway
        return True, "could not read the NSE session from Yahoo (%s); assuming open" % e, None
    if start == today:
        return True, "", start
    if start > today:
        HOLIDAYS[today.isoformat()] = "no NSE session today per Yahoo's ^NSEI trading period"
        return False, "NSE holiday (no session today; next session %s)" % start.isoformat(), start
    return True, "", start


MAX_MISSING = 3


def full_sessions(days, before):
    """The time machine's full_sessions for NSE. Yahoo leaves one to three 5-minute
    bars of most NSE days empty (null prices), so "all 75 bars" would keep almost
    no day. A day missing at most MAX_MISSING bars, none of them the 9:15 bar, is
    kept with each gap filled by a flat bar at the previous close and no volume;
    a day missing more is left out, as before."""
    full, short = [], []
    for d in sorted(days):
        if d >= before:
            continue
        s = days[d]
        missing = [i for i in range(SESSION_BARS) if i not in s]
        if 0 in missing or len(missing) > MAX_MISSING:
            short.append({"date": d, "bars": len(s)})
            continue
        row = []
        for i in range(SESSION_BARS):
            if i in s:
                row.append(s[i])
            else:
                c = row[-1]["c"]
                row.append(dict(row[-1], slot=i, o=c, h=c, l=c, c=c, v=0, filled=True))
        full.append((d, row))
    return full, short


# ---------------------------------------------------------------- loading the skills with NSE's clock

def _load(name, rel):
    path = os.path.join(SKILLS, rel)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _patch_clock(mod):
    """Every skill keeps its New York clock in module globals; its functions look
    them up at call time, so replacing the globals moves the whole skill to India."""
    for name, value in (("to_eastern", to_ist), ("eastern_to_utc", ist_to_utc),
                        ("eastern_offset", lambda utc: 5.5),
                        ("trading_day", trading_day), ("session", session),
                        ("yahoo_symbol", yahoo_symbol),
                        ("NYSE_HOLIDAYS", HOLIDAYS), ("NYSE_EARLY_CLOSE", {}),
                        # NSE has no half days; EARLY is only read for a date in the (empty) early-close list
                        ("OPEN", OPEN), ("CLOSE", CLOSE), ("EARLY", datetime.time(12, 0)),
                        ("OPEN_MIN", OPEN_MIN), ("CLOSE_MIN", CLOSE_MIN), ("EARLY_MIN", CLOSE_MIN),
                        ("SESSION_BARS", SESSION_BARS)):
        if hasattr(mod, name):
            setattr(mod, name, value)
    return mod


def skills():
    """All eleven trader skills, the ones with Python on NSE's clock."""
    s = {
        "scanner": _load("trader_scan", "trader-scanner/scan.py"),
        "news": _load("trader_news", "trader-news/news.py"),
        "entry": _load("trader_entry", "trader-entry/entry.py"),
        "exit": _load("trader_exit", "trader-exit/exit.py"),
        "timemachine": _load("trader_tm", "trader-timemachine/timemachine.py"),
        "budget": _load("trader_size", "trader-budget/size.py"),
        "risk": _load("trader_risk", "trader-risk/check.py"),
        "alerts": _load("trader_alerts", "trader-alerts/alerts.py"),
        "analyst": _load("trader_analyst", "trader-analyst/facts.py"),
        "broker": _load("trader_ticket", "trader-broker/ticket.py"),
        "pelosi": _load("trader_ptr", "trader-pelosi/ptr.py"),
    }
    for m in s.values():
        _patch_clock(m)
    # the time machine reads chart meta.symbol back as BRK-B style; NSE symbols keep their dot
    tm = s["timemachine"]
    tm.full_sessions = full_sessions
    tm.chart_url = lambda sym, host="query2": "https://%s.finance.yahoo.com/v8/finance/chart/%s?range=60d&interval=5m" % (
        host, yahoo_symbol(sym))
    # the risk check's ticker format is US-only (1-5 letters); NSE has M&M, BAJAJ-AUTO, 20MICRONS
    import re
    s["risk"].TICKER = re.compile(r"^[A-Z0-9&\-]{1,20}\.(NS|BO)$|^[A-Z]{1,5}([.\-][A-Z]{1,2})?$")
    return s
