# Where are prediction markets least efficient?

A read-only measurement study of Kalshi and Polymarket. If a contract trades at 70 cents, the market says
"70% likely". This project tests whether those prices can be trusted, and where they break down.

Scope: measurement only. Public read-only data, no accounts, no API keys, no orders. Whatever comes out is
reported, including "these markets are efficient".

## Research questions (written before looking at any results)

This section was committed before any data was downloaded or analysed. Later changes to it are visible in
the git history and are listed under "Deviations" below.

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

## Deviations

None yet.
