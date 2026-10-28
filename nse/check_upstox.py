"""Health check for the Upstox token: one call to each API the board uses, printing the
shape of each answer (field names and a short sample), never the token.

    python nse/check_upstox.py        # needs UPSTOX_ANALYTICS_TOKEN
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import upstox  # noqa: E402

ISIN = "INE002A01018"                      # Reliance Industries
KEY = "NSE_EQ|" + ISIN


def show(name, path):
    t0 = time.time()
    try:
        data = upstox._get(path)
    except Exception as e:                   # noqa: BLE001 - report every API, not the first failure
        print("%-16s FAIL %s" % (name, e))
        return
    text = json.dumps(data, default=str)
    print("%-16s ok in %.1fs, %d bytes: %s" % (name, time.time() - t0, len(text), text[:700]))


if not upstox.token():
    sys.exit("UPSTOX_ANALYTICS_TOKEN is not set")
k = KEY.replace("|", "%7C")
show("quotes", "/v2/market-quote/quotes?instrument_key=" + k)
show("daily bars", "/v3/historical-candle/%s/days/1/2026-10-27/2025-10-27" % k)
show("index daily", "/v3/historical-candle/NSE_INDEX%7CNifty%2050/days/1/2026-10-27/2026-09-27")
show("key ratios", "/v2/fundamentals/%s/key-ratios" % ISIN)
show("income (qtr)", "/v2/fundamentals/%s/income-statement?time_period=quarterly" % ISIN)
show("share holdings", "/v2/fundamentals/%s/share-holdings" % ISIN)
show("news", "/v2/news?category=instrument_keys&instrument_keys=%s&page_size=3" % k)
