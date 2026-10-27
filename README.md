# NSE Morning Board

Every NSE trading day this builds a dashboard of the top 10 NSE stocks by **news and volume**.
For each one it adds a day-trade plan with the reward if the target hits, the loss if the stop
hits, and the odds of each from replaying that stock's own last 60 days.

It is a rules engine, not advice. The ranking measures attention, not quality. The odds are
replays, not a forecast. Nothing here places an order.

## When it runs (GitHub Actions, weekdays)

| IST  | stage | what |
| ---- | ----- | ---- |
| 9:00 | `pre` | reads ~500 headlines from Indian market feeds and matches them to all 2,364 NSE EQ stocks; scans every stock's daily closes; ranks liquid stocks by news (50 %), turnover (40 %) and a daily setup (10 %); keeps 20 |
| 9:35 | `orb` | for those 20: 15-minute opening range, breakout bar, stop and target, 10,000-replay Time Machine, sizing, risk check, alerts |

GitHub's scheduler can start a few minutes late at busy times. On an NSE holiday the page says
the market is closed (the holiday is read from the NIFTY 50's trading period on Yahoo).

## Run it yourself

```bash
python nse/morning.py pre
python nse/morning.py orb
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

Yahoo Finance's chart and spark endpoints are free and unofficial, and their data is delayed.
News comes from the RSS feeds of Economic Times, Moneycontrol, Mint and Business Standard, plus
Google News. The NSE stock list comes from nsearchives.nseindia.com.
