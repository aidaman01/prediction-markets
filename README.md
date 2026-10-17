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

### (a) and (b): calibration and the favorite-longshot bias (2026-10-17)

![calibration](calibration.png)

Sample: 30,666 markets drawn at random, up to 1,000 per month of resolution, from the 1,070,804 resolved
Polymarket markets with volume >= $1,000 (February 2023 to October 2026); 30,402 have a price history.
Primary rule: price 7 days before the scheduled end, market still open, volume >= $1,000. Months are weighted
roughly equally (early months have fewer than 1,000 eligible markets and are taken whole).

| 7 days before scheduled end | n (events) | Brier | reliability | slope `b` (SE) | p(`b` = 1) | intercept `a` (SE) | longshots <= 10c: overpricing (SE), n |
|---|---|---|---|---|---|---|---|
| all | 11,029 (8,301) | 0.1317 | 0.0009 | 1.071 (0.028) | 0.010 | -0.119 (0.027) | 0.77c (0.21), 3,883 |
| all without recurring | 10,669 (8,053) | 0.1324 | 0.0009 | 1.068 (0.028) | 0.015 | -0.117 (0.027) | 0.74c (0.21), 3,708 |
| sports | 6,391 (5,286) | 0.1756 | 0.0011 | 0.988 (0.040) | 0.77 | -0.121 (0.031) | 0.18c (0.45), 1,142 |
| politics | 2,020 (1,277) | 0.0603 | 0.0009 | 1.178 (0.064) | 0.006 | -0.012 (0.089) | 0.59c (0.35), 1,253 |
| other | 1,064 (712) | 0.0774 | 0.0035 | 1.142 (0.075) | 0.059 | -0.056 (0.111) | 1.59c (0.43), 609 |
| economics | 664 (452) | 0.0870 | 0.0025 | 1.080 (0.099) | 0.42 | -0.252 (0.134) | 1.14c (0.58), 336 |
| crypto | 439 (275) | 0.0459 | 0.0090 | 1.169 (0.147) | 0.25 | -0.754 (0.221) | 1.60c (0.52), 322 |
| recurring | 360 (266) | 0.1092 | 0.0044 | 1.142 (0.172) | 0.41 | -0.189 (0.204) | 1.26c (0.79), 175 |
| weather | 91 (55) | 0.0928 | 0.0068 | 0.905 (0.288) | 0.74 | -0.063 (0.352) | -1.25c (2.88), 46 |
| all, volume >= $50,000 | 4,682 (3,610) | 0.1221 | 0.0004 | 0.996 (0.037) | 0.92 | -0.006 (0.043) | 0.03c (0.31), 1,900 |

- (a) Prices are well calibrated in size: reliability, the miscalibration part of the Brier score, is
  0.0009 of 0.1317. Calibration is still statistically rejected (joint test p < 0.0001), mostly through the
  intercept: the first-listed outcome resolves YES a little less often than priced. In the 0.4-0.5 bin the
  price averages 0.457 and the outcome 0.384 (n = 1,453). Exploratory, found after looking: in sports this
  comes from props, spreads and totals (spreads 0.473 vs 0.271, n = 85), not from head-to-head games
  (0.450 vs 0.471, n = 488). In markets with volume >= $50,000 the intercept is -0.006 (SE 0.043): gone.
- (b) There is a small favorite-longshot bias: `b` = 1.07, p = 0.010, and contracts at or below 10 cents
  resolve YES 0.77 cents less often than their price says. It is strongest in politics (`b` = 1.18). In
  markets with volume >= $50,000 it disappears (`b` = 0.996, p = 0.92; 0.03 cents). Recurring markets
  barely matter at 7 days (360 of 11,029); removing them changes nothing.
- Horizons: at 1 day `b` = 1.019 (p = 0.30, n = 21,394); at 30 days `b` = 1.094 (p = 0.036, n = 3,352).
- Many tests (8 categories x 3 horizons x 2 samples x 3 rules): a single p near 0.05 is weak evidence.
  Full tables: `results/calibration_summary.csv`, `results/calibration_bins_7d.csv`.

Look-ahead check (`results/lookahead.csv`): share of measured prices already at >= 0.97 or <= 0.03, 7 days
out. Pre-registered close rule: 33.0% (n = 10,561). Settle rule: 10.9% (n = 8,978). Scheduled rule: 27.4%
(n = 11,029). The scheduled rule still sees many extreme prices: longshots in multi-outcome events, and
outcomes already known while the market is still open. Neither is look-ahead, because the time is fixed in
advance. The settle rule removes extreme prices only by choosing the time with hindsight, which biases it
(see "Changes to plan").

### (c) and (c'): arbitrage inside Polymarket (collection started 2026-10-17)

First 81 snapshots (about 2.7 hours): 995,552 single-market checks with no YES + NO gap after fees, as
mirrored books imply. Exhaustive multi-outcome events: 66 gap-snapshots after fees in 14,750 checks,
3 of them above the T-bill hurdle, none still there in the next snapshot. So far: no arbitrage. The
collector keeps running; this section will be updated after 2-3 weeks.

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
