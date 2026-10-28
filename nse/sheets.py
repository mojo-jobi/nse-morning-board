"""The swing board in a Google Sheet, rewritten on every run.

Needs two GitHub secrets (nothing else changes without them; the run just skips the sheet):
  GOOGLE_SERVICE_ACCOUNT_JSON   the JSON key of a Google Cloud service account
  SHEET_ID                      the sheet's id (the long part of its URL between /d/ and /edit)
and the sheet shared with the service account's e-mail as an Editor.

Tabs (created if missing): Bullish, Breakdowns (F&O), Bottoms, Equity Options, Track record, Live, Read me.
Each has a "Live (Google)" column, =GOOGLEFINANCE("NSE:SYMBOL"), so the price keeps moving
between runs (Google's quotes can lag up to 20 minutes).

Needs the google-auth and requests packages (the workflow installs them).
"""

import json
import os

ENV_KEY = "GOOGLE_SERVICE_ACCOUNT_JSON"
ENV_SHEET = "SHEET_ID"
API = "https://sheets.googleapis.com/v4/spreadsheets/"

TRADE_HEAD = ["Recommended", "Failed checks", "Rank", "Symbol", "Company", "Setup", "Status", "Last close", "Prev close", "Change %",
              "Live (Google)", "Entry (trigger)", "Stop loss", "Target", "Reward:risk", "Est. days",
              "Target first %", "Stop first %", "Avg R (replays)", "Rule history", "Tech score",
              "Fund score", "Score", "Size / lot", "If target / if stop", "Why", "Fundamentals", "Chart", "Signal date"]


def _lv(sym):
    return '=IFERROR(GOOGLEFINANCE("NSE:%s"),"")' % sym.replace(".NS", "")


def _chart(sym):
    return '=HYPERLINK("https://www.tradingview.com/chart/?symbol=NSE:%s","chart")' % sym.replace(".NS", "")


def _pct(x):
    return "" if x is None else round(100 * x)


def failed(checks):
    return "; ".join("%s: %s" % (c["name"], c["detail"]) for c in checks or [] if not c["ok"])


def trade_rows(rows):
    out = [TRADE_HEAD]
    for r in rows:
        p = r.get("plan") or (r.get("bottom") or {}).get("plan") or {}
        o, h = p.get("odds") or {}, p.get("history") or {}
        if r.get("size"):
            sz = r["size"]
            size = "%s shares (%s)" % (sz.get("qty"), "Rs %s" % format(round(sz.get("cost") or 0), ",")) if sz.get("qty") else sz.get("refusal")
            money = "+%s / -%s" % (round(sz.get("reward") or 0), round(sz.get("max_loss") or 0)) if sz.get("qty") else ""
        elif r.get("lot"):
            lt = r["lot"]
            size = "lot %s (Rs %s)" % (lt["lot"], format(lt["notional"], ","))
            money = "move per lot: %s / %s" % (lt["move_to_target"], lt["move_to_stop"])
        else:
            size = money = ""
        hist = ("%d fired: %d target, %d stop, %d time" % (h["fired"], h["target"], h["stop"], h["time"])
                if h.get("fired") else "")
        out.append(["yes" if r.get("qualified") else "watchlist", failed(r.get("checks")),
                    r.get("rank"), r["symbol"].replace(".NS", ""), r.get("name"), p.get("kind", ""), r.get("status", ""),
                    r.get("price"), r.get("prev_close"), r.get("chg_pct"), _lv(r["symbol"]), p.get("entry"),
                    p.get("stop"), p.get("target"), p.get("rr"), p.get("est_days"), _pct(o.get("p_target")),
                    _pct(o.get("p_stop")), o.get("avg_R"), hist, r.get("tech"), r.get("fund"), r.get("score"),
                    size, money, "; ".join(p.get("why") or []), "; ".join(r.get("fund_notes") or []),
                    _chart(r["symbol"]), r.get("session")])
    return out


def bottom_rows(rows):
    out = [["Recommended", "Failed checks", "Rank", "Symbol", "Company", "State", "Last close", "Change %", "Live (Google)", "Support",
            "Touches", "Buy zone", "Breaks below (close)", "Off 52w high %", "RSI", "RSI divergence",
            "Entry if turning up", "Stop", "Target", "Fund score", "Quality", "Score", "Fundamentals", "Chart",
            "Signal date"]]
    for r in rows:
        b = r.get("bottom") or {}
        p = b.get("plan") or {}
        out.append(["yes" if r.get("qualified") else ("watch zone" if not p else "watchlist"), failed(r.get("checks")),
                    r.get("rank"), r["symbol"].replace(".NS", ""), r.get("name"), b.get("kind"), r.get("price"),
                    r.get("chg_pct"), _lv(r["symbol"]), b.get("support"), b.get("touches"),
                    "%s - %s" % tuple(b["zone"]) if b.get("zone") else "", b.get("invalidation"),
                    b.get("drawdown_pct"), b.get("rsi"), "yes" if b.get("divergence") else "", p.get("entry"),
                    p.get("stop"), p.get("target"), r.get("fund"), "yes" if r.get("quality") else "", r.get("score"),
                    "; ".join(r.get("fund_notes") or []), _chart(r["symbol"]), r.get("session")])
    return out


def record_rows(record):
    st = record.get("stats") or {}
    out = [["Track record", "tracked %s, open %s, closed %s (target %s, stop %s), entries missed %s, average %sR, "
                            "win rate %s" % (st.get("tracked"), st.get("open"), st.get("closed"), st.get("targets"),
                                             st.get("stops"), st.get("missed"), st.get("avg_R"),
                                             "-" if st.get("win_rate") is None else "%d%%" % round(100 * st["win_rate"]))],
           [],
           ["Signal date", "Symbol", "Company", "Side", "Setup", "Status", "Entry", "Stop", "Target", "Est. days",
            "Target first %", "Price at signal", "Last close", "Current price", "Live (Google)", "Entered", "Closed",
            "Exit", "Result R", "Result %"]]
    for r in record.get("rows") or []:
        out.append([r["created"], r["symbol"].replace(".NS", ""), r.get("name"), r["side"], r["kind"], r["status"],
                    r["entry"], r["stop"], r["target"], r.get("est_days"), _pct(r.get("p_target")),
                    r.get("price_at_signal"), r.get("last_close"), r.get("last_price"), _lv(r["symbol"]),
                    r.get("entered", ""), r.get("closed", ""), r.get("exit", ""), r.get("result_R", ""),
                    r.get("result_pct", "")])
    return out


def live_rows(doc):
    live = (doc.get("live") or {})
    out = [["Updated", live.get("created_ist") or doc.get("created_ist"), "in session" if live.get("in_session") else "market closed"], []]
    for title, key in (("Breaking out now (confirm at the close)", "breakouts"),
                       ("Breaking down now, F&O (confirm at the close)", "breakdowns"),
                       ("In a bottom's buy zone", "in_zone")):
        out.append([title])
        out.append(["Symbol", "Price", "Change %", "Volume pace (x usual)", "Level / zone", "Live (Google)"])
        for m in (live.get("moves") or {}).get(key) or []:
            lvl = m.get("level") if "level" in m else "%s - %s" % tuple(m["zone"])
            out.append([m["symbol"].replace(".NS", ""), m["price"], m["chg_pct"], m["volume_pace"], lvl, _lv(m["symbol"])])
        out.append([])
    return out


def options_rows(opts):
    out = [["Rules screen, not advice. Options-first: every F&O plan with direction checks (replay edge, not failing on "
            "the stock, market, fundamentals, no results due); a debit spread by default, a single only when IV is cheap; "
            "cost within budget; exits +60% / -40% / stock target or stop / 7 days before expiry; max 3 open."], [],
           ["Recommended", "Failed checks", "The trade", "Cost a lot (max loss)", "Gain at target a lot",
            "Loss at stop a lot", "Trade R:R", "Symbol", "Type", "Plan", "Spot", "Expiry", "Days left", "Lot", "PCR", "Most call OI", "Most put OI",
            "Watch range", "Best", "Strike", "Price a share", "Value of 1 lot (price x lot)", "Delta", "Theta/lot/day", "Vega/lot", "IV %", "OI lots",
            "OI chg %", "Build-up", "Gain at target/lot", "Loss at stop/lot", "R:R", "Break-even", "Passes filters",
            "Notes"]]
    for o in (opts or {}).get("calls", []) + (opts or {}).get("puts", []):
        p = o["plan"]
        plan = "%s: entry %s, stop %s, target %s" % (p.get("kind"), p.get("entry"), p.get("stop"), p.get("target"))
        watch = "%s - %s" % tuple(o["watch"]) if o.get("watch") else ""
        for s in o.get("strikes") or []:
            t = o.get("trade") or {}
            name = ("" if not t else "buy %s %s" % (t["buy"], o["type"]) if t["structure"] == "single"
                    else "buy %s / sell %s %s spread" % (t["buy"], t["sell"], o["type"]))
            out.append(["yes" if o.get("qualified") else "no", failed(o.get("checks")), name, t.get("cost_lot", ""),
                        t.get("gain_lot", ""), -t["loss_lot"] if t else "", t.get("rr", ""),
                        o["symbol"].replace(".NS", ""), o["type"], plan, o.get("spot"), o["expiry"], o["dte"], o["lot"],
                        o.get("pcr"), o.get("call_wall"), o.get("put_wall"), watch,
                        "best" if s["strike"] == o.get("best") else "", s["strike"], s["ask"], s["premium_lot"], s["delta"],
                        s["theta_lot_day"], s["vega_lot"], s["iv"], s["oi_lots"], s.get("oi_chg_pct"), s.get("buildup"),
                        s["gain_lot"], -s["loss_lot"], s["rr"], s["breakeven"],
                        "yes" if not s.get("fails") else "; ".join(s["fails"]),
                        "; ".join(o.get("notes") or [])])
    return out


def options_record_rows(rec):
    st = (rec or {}).get("stats") or {}
    out = [["Options record", "tracked %s, waiting/open %s, closed %s, entry missed %s, closed result %s a lot each, "
                              "open now %s, win rate %s" % (
                                  st.get("tracked"), st.get("open"), st.get("closed"), st.get("missed"), st.get("total_lot"),
                                  st.get("open_mark_lot"), "-" if st.get("win_rate") is None else "%d%%" % round(100 * st["win_rate"]))],
           ["Bought at the ask, sold at the bid, at the 30-minute update after the stock's move; one lot each."], [],
           ["Signal date", "Symbol", "Option", "Expiry", "Lot size (shares)", "Status", "Stock plan",
            "Price at signal (a share)", "Value of 1 lot at signal", "Bought (a share)", "Value of 1 lot bought",
            "Sold / last (a share)", "Value of 1 lot sold / now", "Result per lot", "Result %", "Open now per lot",
            "Open now %", "Updated"]]
    for r in (rec or {}).get("rows") or []:
        now = r.get("exit", r.get("last"))
        lot_val = lambda x: round(x * r["lot"]) if x else ""  # noqa: E731
        label = ("%s/%s %s spread" % (r["strike"], r["short_strike"], r["type"]) if r.get("short_strike")
                 else "%s %s" % (r["strike"], r["type"]))
        out.append([r["created"], r["symbol"].replace(".NS", ""), label, r["expiry"], r["lot"],
                    r["status"], r.get("stock_status"), r["signal_ask"], lot_val(r["signal_ask"]), r.get("fill", ""),
                    lot_val(r.get("fill")), now if now is not None else "", lot_val(now),
                    r.get("result_lot", ""), r.get("result_pct", ""),
                    r.get("mark_lot", ""), r.get("mark_pct", ""),
                    r.get("closed_ist") or r.get("entered_ist") or r.get("last_ist") or ""])
    return out


README = [["NSE swing board"],
          ["Rules screen, not advice. Entries are triggers (above the day's high; below its low for a breakdown), "
           "valid 3 sessions. Stops sit where the setup is proven wrong; targets at the next level 1.5R+ away, else 2R."],
          ["Odds: 10,000 replays of up to 15 sessions resampled from the stock's own last year of days, and the "
           "same rule on its own past. Not a forecast; a gap can jump any stop."],
          ["Breakdowns list F&O stocks only (the ones with stock options). Bottoms: 20%+ off the 52-week high, "
           "on support; 'turning up' once it closes above its 10-day high and 20-day EMA."],
          ["Live (Google) uses GOOGLEFINANCE, which can lag up to 20 minutes."]]


def write(doc):
    key, sheet = os.environ.get(ENV_KEY), os.environ.get(ENV_SHEET)
    if not key or not sheet:
        return "skipped (%s and %s are not both set)" % (ENV_KEY, ENV_SHEET)
    from google.oauth2 import service_account
    from google.auth.transport.requests import AuthorizedSession
    creds = service_account.Credentials.from_service_account_info(
        json.loads(key), scopes=["https://www.googleapis.com/auth/spreadsheets"])
    s = AuthorizedSession(creds)
    base = API + sheet.strip()
    tabs = {"Bullish": trade_rows(doc.get("bull") or []), "Breakdowns (F&O)": trade_rows(doc.get("bear") or []),
            "Bottoms": bottom_rows(doc.get("bottoms") or []), "Equity Options": options_rows(doc.get("options")),
            "Track record": record_rows(doc.get("record") or {}),
            "Options record": options_record_rows(doc.get("options_record")),
            "Live": live_rows(doc), "Read me": README}
    meta = s.get(base, params={"fields": "sheets.properties.title"})
    meta.raise_for_status()
    have = {x["properties"]["title"] for x in meta.json().get("sheets", [])}
    add = [{"addSheet": {"properties": {"title": t}}} for t in tabs if t not in have]
    if add:
        s.post(base + ":batchUpdate", json={"requests": add}).raise_for_status()
    s.post(base + "/values:batchClear", json={"ranges": ["'%s'" % t for t in tabs]}).raise_for_status()
    stamp = "updated %s IST (%s)" % ((doc.get("live") or {}).get("created_ist") or doc.get("created_ist"), doc.get("stage"))
    data = [{"range": "'%s'!A1" % t, "values": [[stamp]] + [[("" if v is None else v) for v in row] for row in rows]}
            for t, rows in tabs.items()]
    s.post(base + "/values:batchUpdate", json={"valueInputOption": "USER_ENTERED", "data": data}).raise_for_status()
    return "wrote %s" % ", ".join("%s (%d rows)" % (t, len(r) - 1) for t, r in tabs.items())
