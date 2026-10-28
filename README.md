# NSE Swing Board

A web page (phone and desktop) of **swing setups** on NSE, 3 to 15 trading days, ranked on
**technicals and fundamentals**, with a Google Sheet that tracks every plan. The tabs:

- **Swing**: bullish setups on all liquid stocks (breakouts, pullbacks in an uptrend, bounces off
  support), and what is crossing a level right now during the session.
- **Falling market**: breakdowns and failed rallies on **F&O stocks only** (the ones with stock
  options, for puts), and **bottoms**: stocks 20 %+ off their high sitting on support, with a buy
  zone, the close that would break it, and a plan once the stock turns up.
- **Equity Options** (`nse/options.py`, settings in `config.json` under `options`), options-first:
  every liquid F&O stock with a swing plan gets its own direction checks (replay edge, the rule not
  losing on that stock, the market, fundamentals, and **no results due**: the last quarter not yet
  reported within 60 days of its end means IV crush ahead). Expiry: the nearest monthly one 14+
  days away and 7+ days after the plan's estimated exit. Structure inside the budget (Rs 15,000 at
  risk a trade): a **debit spread** by default (buy delta 0.40-0.65, sell at or before the target,
  pay at most half the width, reward:risk 1.5+, break-even inside the target, both legs liquid,
  at most 25% time decay by the estimated day, no OI wall before the sold strike); a **single**
  call/put only if it fits the budget and its IV is at most the stock's realised volatility (or in
  the lower half of its own IV history once 40+ days are recorded in `trader/iv-history.json`).
  Exits: +60% / -40% of the cost, the stock's target or stop, or 7 days before expiry. At most 3
  trades open or waiting. A screen, not advice: a bought option can lose its whole cost.
- **Track record**: every plan shown (and every F&O plan behind an option card), from the day it
  appears: entry hit or missed, then target, stop or day 15, with the result in R and %. Below
  it, the **options record** (`trader/options-log.json`): each option card's best strike, bought at
  the ask once its stock triggers the entry and sold at the bid when the stock plan hits its target
  or stop, reaches day 15, or at expiry (intrinsic value); open ones marked to market at the bid.
  Prices are those of the 30-minute update after the stock's move, so real fills can differ.
- **Intraday**: the original news-and-volume morning board with opening-range plans.

It is a rules screen, not advice. The odds are replays of each stock's own past, not a forecast.
Nothing here places an order.

## Swing: how a setup is found and planned (`nse/swing.py`)

- **Universe**: all NSE EQ stocks, quoted from Upstox; those at Rs 20+ get 3 years of daily bars;
  liquid = 20-day median turnover of Rs 5 crore or more (about 800 stocks).
- **Levels**: a swing high/low is the extreme of the 11 bars around it; swing points within half
  an ATR cluster into a zone; a zone touched twice or more is support or resistance.
- **Rules** (on the last completed session): breakout above resistance or the 52-week high on 1.5x
  volume; pullback to the rising 20-day EMA or 50-day average in an uptrend; bounce off support
  above the 200-day; mirror images for breakdowns and failed rallies (F&O stocks only).
- **Plan**: entry is a trigger above the day's high (below its low for a breakdown), valid 3
  sessions; stop where the setup is proven wrong, at least 1 ATR away; target at the next level
  1.5R+ away, else 2R. Size: whole shares inside Rs 1,000 risk (trader-budget); F&O lot for breakdowns.
- **Odds**: 10,000 replays of up to 15 sessions resampled from the stock's own last year of
  days (a gap through the stop fills at the open), plus the same rule on its own last 2-3 years.
  Estimated days = the median days to target in the replays that hit it.
- **Score**: technical (trend, strength against the Nifty 50, volume, replay edge) and
  fundamental (ROE, ROCE, profit and revenue growth, P/E against its sector, shareholding change,
  each ranked against the other liquid stocks) at 50/50; breakdowns favour weak fundamentals;
  bottoms weigh fundamentals 60 %.

## When it runs (GitHub Actions)

| IST | stage | what |
| --- | ----- | ---- |
| 9:00 weekdays | `pre` | intraday: news + daily scan + shortlist |
| 9:35 weekdays | `orb` | intraday: opening range and trade numbers |
| 9:45 to 15:15, every 30 min | `swing-live` | live prices, entries/stops/targets hit, levels being crossed, buy zones reached |
| 15:50 weekdays | `swing-eod` | the full swing scan, track record, page and sheet |
| Saturday 10:00 | `swing-fundamentals` | refresh every liquid stock's fundamentals (Upstox, about 9 minutes) |

The Refresh button runs `refresh`: the intraday board and the swing live update.

## Google Sheet

Each swing run rewrites the tabs Bullish, Breakdowns (F&O), Bottoms, Track record, Live and Read
me, with a `Live (Google)` column (`GOOGLEFINANCE`, can lag 20 minutes). Setup, once:

1. Google Cloud console: create a project, enable the **Google Sheets API**, create a **service
   account**, and add a **JSON key** for it (it downloads a .json file).
2. Make a Google Sheet and **Share** it with the service account's e-mail (in the JSON,
   `client_email`) as **Editor**.
3. Add two repository secrets: `GOOGLE_SERVICE_ACCOUNT_JSON` (the whole JSON file) and `SHEET_ID`
   (the part of the sheet's URL between `/d/` and `/edit`), for example from your own terminal:
   `gh secret set GOOGLE_SERVICE_ACCOUNT_JSON -R mojo-jobi/nse-morning-board < key.json`.
   Delete the downloaded key file afterwards.

## Intraday board: when it runs

| IST  | stage | what |
| ---- | ----- | ---- |
| 9:00 | `pre` | reads ~500 headlines from Indian market feeds and matches them to all 2,364 NSE EQ stocks; scans every stock's daily closes; ranks liquid stocks by news (50 %), turnover (40 %) and a daily setup (10 %); keeps 20 |
| 9:35 | `orb` | for those 20: 15-minute opening range, breakout bar, stop and target, 10,000-replay Time Machine, sizing, risk check, alerts |

GitHub's scheduler can start a few minutes late at busy times. On an NSE holiday the page says
the market is closed (the holiday is read from the NIFTY 50's trading period on Yahoo).

**Refresh** on the dashboard runs both stages again now (`refresh`), and marks which stocks came
into or dropped out of the top 10 since the last board. It starts the workflow through the GitHub
API with your own fine-grained token (Actions read/write on this repo only), kept in that browser.
With live Upstox prices, a refresh reuses the day's saved setups (`trader/setups-DATE.json`).

## Run it yourself

```bash
python nse/morning.py pre
python nse/morning.py orb
python nse/morning.py refresh     # what the dashboard's Refresh button runs (plus swing live)
python nse/swing.py eod           # the swing scan (after 15:30 it includes today's bar)
python nse/swing.py live          # prices, entries and exits, levels crossed now
python nse/swing.py fundamentals  # refresh fundamentals (needs UPSTOX_ANALYTICS_TOKEN)
python nse/check_upstox.py        # is the Upstox token working?
python nse/universe.py            # refresh the NSE stock list (the workflow does it on Mondays)
```

Rules live in `config.json`, in rupees: budget 1,00,000, max loss 1,000 a trade and 3,000 a day,
3 trades a day, reward:risk at least 1.5, entries 9:30 to 14:45, flat by 15:15.

## How the 11 trader skills are used

`skills/` holds copies of the trader skills. `nse/market.py` loads them as libraries and swaps
their New York clock for NSE's: IST, 9:15 to 15:30, 75 five-minute bars.

- **scanner, news, entry, exit, timemachine, budget, risk, alerts**: used.
- **analyst**: reads SEC EDGAR, where Indian companies don't file. Results are flagged from the news.
- **broker**: talks to Alpaca (US). Not used. You place trades on your own broker.
- **pelosi**: US Congress trades. Not relevant to NSE.

Changes from the original skills: `.NS` symbols keep their dot (scanner, timemachine). Yahoo
leaves 1 to 3 five-minute bars of most NSE days empty, so a day with at most 3 empty bars (never
the 9:15 bar) is kept with each gap filled flat at the previous close.

## Data

**Upstox first, Yahoo as the backup** (`nse/upstox.py`). With an Upstox Analytics Token, live
quotes for every NSE stock come from Upstox (500 a request), and so do the 5-minute bars behind
each trade plan (today plus about 58 past sessions). Anything Upstox does not answer falls back
to Yahoo, stock by stock; a rejected token switches the whole run to Yahoo and the page says so.
The five daily setups always use Yahoo's daily closes (Upstox serves those one stock at a time).
When Upstox priced a stock, its price is checked against Yahoo's and a gap over 1 % is flagged.

To turn Upstox on:
1. Upstox Developer Apps > **Analytics** tab > Generate Token (free, read-only, valid 12 months,
   no static IP needed for Market Quote and Historical Data).
2. Add it as the repository secret `UPSTOX_ANALYTICS_TOKEN` (Settings > Secrets and variables >
   Actions), or run `gh secret set UPSTOX_ANALYTICS_TOKEN -R mojo-jobi/nse-morning-board`,
   which asks for the value. Never commit it. To run locally, set the same environment variable.
3. Make a new one before it expires; the page warns when Upstox rejects it.

Yahoo Finance's chart and spark endpoints are free and unofficial, and their data is delayed.
News comes from the RSS feeds of Economic Times, Moneycontrol, Mint and Business Standard, plus
Google News. The NSE stock list comes from nsearchives.nseindia.com.
