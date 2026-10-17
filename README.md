# Where are prediction markets least efficient?

A read-only measurement study of Polymarket (Kalshi was planned and dropped: its API terms forbid this use,
see below). If a contract trades at 70 cents, the market says
"70% likely". This project tests whether those prices can be trusted, and where they break down.

Scope: measurement only. Public read-only data, no accounts, no API keys, no orders. Whatever comes out is
reported, including "these markets are efficient".

## Research questions (written before looking at any results)

This section was committed before any data was downloaded or analysed. Later changes to it are visible in
the git history and are listed under "Changes to plan" below.

### (a) Calibration

When a market says 70%, does it happen about 70% of the time?

- Sample: resolved binary markets (outcome exactly YES or NO; voided or 50/50 resolutions dropped).
  One observation per market: the first listed outcome ("Yes" in yes/no markets) and its price.
- Reference time `T` = the earlier of the scheduled end date and the actual close time. Price at horizon
  `h` = the last recorded price at or before `T - h`, for `h` = 1 day, 7 days and 30 days. The market must
  have a price within the 24 hours before `T - h`; markets younger than `h` at `T` are dropped for that
  horizon. Primary horizon: 7 days. 1 day and 30 days are secondary.
- Main sample: lifetime volume >= $1,000. Robustness: volume >= $50,000.
- Metrics: Brier score with its Murphy decomposition (reliability, resolution, uncertainty); calibration
  curve in 10 equal-width price bins with 95% Wilson intervals; logistic recalibration
  `logit P(YES) = a + b * logit(price)`. A calibrated market has `a = 0, b = 1`; tested jointly with a
  Wald test using standard errors clustered by event (outcomes of one event are not independent).
- By category: sports, politics, economics, weather, crypto, other, assigned from the venue's own tags by
  a fixed mapping in the code (`pm/data.py`).

### (b) Favorite-longshot bias

Are cheap contracts overpriced, as in betting markets?

- Same sample and prices as (a).
- Test: the slope `b` above. `b > 1` means true probabilities are more extreme than prices, i.e. longshots
  are overpriced and favorites underpriced. Two-sided test of `b = 1` at 5%, clustered by event.
- Descriptive: average overpricing of longshots, `mean(price - outcome)` over contracts priced at or below
  10 cents, with an event-clustered standard error.

### (c) Arbitrage inside one venue

How often does buying both YES and NO cost less than $1 after the official fee schedule, the spread and
slippage? How long do these gaps last?

- From order-book snapshots: for each binary market, walk the YES and NO asks to buy `q` of each, add the
  venue's official taker fee for every fill, and compare with the $1 payout. Report the share of snapshots
  with a positive net edge at the smallest allowed order size, the most profitable `q`, and the profit.
- Duration: consecutive snapshots with a positive edge form an episode. With snapshots every `N` minutes a
  duration is known only to within `N` minutes; shorter gaps are mostly missed. This is stated with every
  number.
- Gas and deposit/withdrawal costs are ignored; they can only shrink an edge.

(c') Added at design time, before any data: on both venues a single binary market's YES ask plus NO ask
below $1 implies a crossed book (Polymarket mirrors the YES and NO books; a Kalshi ask is one minus the
opposite bid), so (c) is expected to be close to never. The multi-outcome version is measured as well: for
an event whose outcomes are mutually exclusive and exhaustive, buying YES on every outcome pays exactly $1
(and NO on every outcome pays `n - 1`). Same fee and book-walking rules. Events that can still add outcomes
are excluded, since they are not exhaustive.

### (d) Arbitrage across venues

Is the same event priced differently on Kalshi and Polymarket, after fees?

**Status: closed, not possible under the venue terms.** Kalshi's API Developer Agreement allows API use only
for a member's own trading and forbids collecting or storing its data for any other purpose (see "Data and
venue terms"). Without Kalshi data there is no second venue to compare. The plan below is kept as written.

- Only event pairs whose resolution rules are verified to match: same event, same resolution source, same
  cut-off date and time zone, same treatment of edge cases. The evidence for each pair (both rule texts and
  the comparison) is stored in `pairs/`; pairs with different rules are dropped and listed with the reason.
- Edge: buy YES on one venue and NO on the other at the walked asks plus both venues' taker fees, against
  the $1 payout. Same reporting as (c).

## Validation: every component is tested against a known answer

- Fee calculators reproduce the venues' published fee examples.
- Brier score and calibration on simulated forecasts that are calibrated by construction (must pass) and
  miscalibrated (must be detected).
- Arbitrage detector on synthetic order books with hand-computed edges, including walking the book and fees.
- The bias test rejects about 5% of the time on simulated unbiased markets with the same event clustering.
- The measuring-time rule keeps a simulated efficient market calibrated; a market that resolves early cannot
  leak its outcome into the measured price.
- Capacity at a budget, annualized return against the T-bill yield, the next-snapshot rule and the book sanity
  checks each have a test with a hand-computed answer.

## Results

Final numbers for (a) and (b) come from a random sample stratified by month over the whole history (see
"Changes to plan"); they will replace this section when that run is done.

### Superseded: first preliminary results (2026-10-17)

Kept for the record; do not use. Two flaws: the sample was the first markets the API listed (83% resolved in
2025, 217 in 2026), and prices were measured 7 days before the actual close, a rule that looks into the future
(see "Changes to plan"). On that basis: 2,018 markets, Brier 0.0889, slope `b` = 1.138 (SE 0.064, p = 0.032),
longshot overpricing 0.88 cents (SE 0.30).

An error in the first (c') note is corrected here: for "How many Fed rate cuts in 2026?" the $0.0111 edge was
the profit on the minimum order of 5 sets, not on one set: about 0.2 cents per set, 1.1% a year to the
scheduled end, below the 3-month T-bill. It is not an arbitrage under the rules below.

## Data and venue terms

| | Polymarket | Kalshi |
|---|---|---|
| Resolved markets with outcomes | Gamma `GET /markets/keyset?closed=true` | `GET /markets`, `GET /historical/markets` |
| Price history | data-api `GET /v2/prices-history`: 3-hour and 12-hour buckets kept permanently, finer ones 30 days; only order-book (CLOB) markets, so the 2020-22 AMM markets have no history | candlesticks 1 min / 1 h / 1 day; settled markets before the archive cutoff via `/historical/...` |
| Live order books | CLOB `GET /book`, `POST /books` (500 tokens per call) | `GET /markets/{ticker}/orderbook` (bids only) |
| Published rate limits | per IP: Gamma `/markets` 300 per 10 s, `/v2/prices-history` 200 per 10 s, `/books` 500 per 10 s | token buckets per account tier (Basic: 200 tokens/s, 10 per request) |
| Fees | `C * rate * p(1-p)`, taker only, rate per market (0 to 0.07) | `0.07 * C * P(1-P)` rounded up to the cent for most markets |
| Terms | [Terms of Use](https://polymarket.com/tos) (effective 2026-08-11) forbid scraping the site and access or redistribution of the Data by capital-market firms and market-data distributors. Reading the documented public API for personal research is not in a prohibited category. | [Developer Agreement v1.1](https://assets.kalshi.com/Kalshi-Developer-Agreement.pdf), accepted by any API use: "Use of Kalshi APIs is expressly limited to facilitating a members own trading"; collecting, caching, aggregating or storing API data for other purposes is prohibited. The [Data Terms of Use](https://kalshi-public-docs.s3.amazonaws.com/kalshi-data-terms-of-service.pdf) also forbid compiling databases from Kalshi Data. |

Consequences: raw data is never committed. The repository holds code and aggregate results only, and
`data/` is git-ignored. **Kalshi is not used at all**: the study never sent a request to its API. Question
(d) is closed and (c) covers Polymarket only. The Kalshi fee and order-book functions in `pm/` stay, since they
are tested against Kalshi's published fee examples, but no script calls them.

## Order-book collector (questions c and c')

`python -m pm.collect` takes a snapshot every 2 minutes of every open order-book market in every
Polymarket event with at least $10,000 traded in the last 24 hours (about 16,600 markets in 480 events on
2026-10-17), keeping 5 price levels a side. The universe is refreshed hourly. The published `/books` limit
would allow a snapshot every few seconds. Disk is the binding constraint (about 1.1 MB per compressed
snapshot, about 0.9 GB a day). Only the first outcome's book is stored: Polymarket derives the second
outcome's book from it. In a check of 347 markets with both books fetched in the same request, 346 were
exact mirrors (bid `p` = ask `1 - p`, same size). `scripts/install_collector.sh` installs it as a launchd
agent that starts at login and restarts if it dies (checked by killing it: launchd restarted it within a
minute). It runs under `caffeinate -s`, which keeps the Mac awake while it is on AC power.

## How to run

```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python tests/test_pm.py                       # 18 known-answer tests
.venv/bin/python scripts/fetch_history.py markets       # resolved markets, volume >= $1,000 (resumable)
.venv/bin/python scripts/fetch_history.py sample        # up to 1,000 markets per month -> sample_ids.txt
.venv/bin/python scripts/fetch_history.py sample_prices # their 3-hour price histories (resumable)
.venv/bin/python scripts/run_calibration.py data/polymarket/sample_ids.txt   # (a) and (b) -> results/
.venv/bin/python scripts/plot_calibration.py            # -> calibration.png
./scripts/install_collector.sh                          # (c) collector as a background agent
.venv/bin/python scripts/scan_arb.py                    # (c) and (c') -> results/arbitrage_summary.csv
```

## Changes to plan

### Changes to plan (before results), 2026-10-17

- Kalshi dropped: its Developer Agreement forbids storing data for non-trading use. Question (d) is dropped
  with it. The study covers Polymarket only.
- Implementation details: prices of exactly 0 or 1 are clipped to [0.001, 0.999] (the smallest Polymarket
  tick) before taking logits; a category is reported only if it has at least 30 events.

### Changes after the superseded preliminary results, 2026-10-17

Made after seeing the preliminary numbers, each for the stated reason. The old rules are still computed and
reported next to the new ones.

1. **Measuring time.** The pre-registered rule measured the price `h` before `T = min(scheduled end, actual
   close)`. Many markets close early, after their outcome is known, so this rule chooses the measuring time
   with hindsight. Measuring `h` before the moment prices settle (the start of the final run at >= 0.97 or
   <= 0.03) has the same problem. On simulated efficient "will it happen by day 60" markets, calibrated by
   construction, the slope is `b` = 2.34 for the close rule and 2.51 for the settle rule, but 0.945 (SE 0.048)
   for the rule now used: **`h` before the scheduled end, and only if the market is still open then.** Whether a
   market is open at a fixed time is known at that time, so nothing is chosen with hindsight
   (`test_only_scheduled_anchor_keeps_an_efficient_market_calibrated`). `results/lookahead.csv` reports, for
   each rule, the share of measured prices already at >= 0.97 or <= 0.03.
2. **Recurring markets.** Machine-generated recurring series (crypto "Up or Down", price and temperature
   ladders, tweet counts, ...) form their own category, "recurring": a question whose template, with dates,
   times and numbers removed, is shared by at least 100 markets. Results are reported with and without them.
3. **Sample.** Up to 1,000 markets drawn at random from each calendar month of resolution, over the whole
   history (`scripts/fetch_history.py sample`). Pooled numbers therefore weight months roughly equally.
4. **Arbitrage rules for (c) and (c').** A gap counts only if every book passes sanity checks (prices in
   (0, 1), positive sizes, ordered levels, not crossed, no timestamp after the snapshot); if its simple
   annualized return to the scheduled end beats the 3-month T-bill (FRED `DTB3`, converted to a bond-equivalent
   yield); and if it is still there in the next snapshot. Profit is also reported for deploying $100, $1,000 and
   $10,000.
