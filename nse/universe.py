"""NSE's equity list -> trader/universe.txt (SYMBOL.NS|Name, Yahoo symbols).

    python nse/universe.py                 # download EQUITY_L.csv from NSE archives
    python nse/universe.py --csv FILE      # or read a saved copy

Keeps the EQ series only: the series where intraday trading is allowed.
BE and BZ are trade-for-trade (delivery only), so a day trade cannot use them.
"""

import argparse
import collections
import csv
import io
import os
import sys
import urllib.request

URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read_rows(text):
    series, rows = collections.Counter(), []
    for r in csv.DictReader(io.StringIO(text), skipinitialspace=True):
        s = (r.get("SERIES") or "").strip()
        series[s] += 1
        if s == "EQ":
            rows.append((r["SYMBOL"].strip().upper() + ".NS", " ".join(r["NAME OF COMPANY"].split())))
    return sorted(rows), series


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", help="a saved EQUITY_L.csv instead of the download")
    ap.add_argument("--out", default=os.path.join(ROOT, "trader", "universe.txt"))
    a = ap.parse_args(argv)
    if a.csv:
        with open(a.csv, encoding="utf-8-sig") as fh:
            text = fh.read()
    else:
        req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            text = r.read().decode("utf-8-sig", "replace")
    rows, series = read_rows(text)
    if not rows:
        print("NSE's list came back with no EQ rows; universe left as it was.")
        return 1
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as fh:
        for sym, name in rows:
            fh.write("%s|%s\n" % (sym, name.replace("|", "/")))
    print("NSE EQUITY_L.csv: %s rows (%s). Kept %s EQ-series stocks. Wrote %s." % (
        "{:,}".format(sum(series.values())), ", ".join("%s %d" % kv for kv in series.most_common()),
        "{:,}".format(len(rows)), a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
