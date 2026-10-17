"""Every test checks against a known answer. Run: python -m pytest  (or python tests/test_pm.py)"""
import os
import sys
from decimal import ROUND_HALF_UP, Decimal as D

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pm.arb import (annualized, at_budget, basket_profit, best_basket, book_problems, episodes, kalshi_asks, kalshi_leg,
                    pm_leg, reachable, tbill_yield)
from pm.calib import brier, calibration_table, longshot, murphy, recalibration, wilson
from pm.data import DAY, measure_time, parse_market, price_at, recurring_templates, resolution_time, template
from pm.fees import kalshi_buy_cash, kalshi_fill_rounding, kalshi_trade_fee, polymarket_fee

PRICES = ["0.01"] + [f"{x / 100:.2f}" for x in range(5, 100, 5)] + ["0.99"]


def _table(half):                       # published tables are symmetric around 0.50
    return half + half[-2::-1]


def test_polymarket_fee_tables():
    """docs.polymarket.com/trading/fees: taker fee for 100 shares, shown to the cent."""
    tables = {
        "0.07": _table([.07, .33, .63, .89, 1.12, 1.31, 1.47, 1.59, 1.68, 1.73, 1.75]),          # crypto
        "0.05": _table([.05, .24, .45, .64, .80, .94, 1.05, 1.14, 1.20, 1.24, 1.25]),            # sports, econ, ...
        "0.04": _table([.04, .19, .36, .51, .64, .75, .84, .91, .96, .99, 1.00]),                # politics, finance
    }
    for rate, fees in tables.items():
        for p, want in zip(PRICES, fees):
            got = polymarket_fee(100, p, rate).quantize(D("0.01"), rounding=ROUND_HALF_UP)
            assert got == D(f"{want:.2f}"), (rate, p, got, want)
    assert polymarket_fee(100, "0.5", 0) == 0                                                    # geopolitics
    assert polymarket_fee("0.2", "0.001", "0.04") == 0                 # 0.0000080 USDC: below 0.00001, zero


def test_kalshi_fee_schedule_and_rounding():
    """kalshi.com/fee-schedule: 100 contracts cost $0.07-$1.75 taker; combos maker (50%) $0.04-$0.88.
    docs fee_rounding example: C=1 at $0.055, model fee $0.00363825 -> trade fee $0.003639, balance -$0.06."""
    for mult, lo, hi in (("0.07", "0.07", "1.75"), ("0.035", "0.04", "0.88")):
        fees = [kalshi_buy_cash([(p, 100)], mult)[1] for p in (f"{c / 100:.2f}" for c in range(1, 100))]
        assert (min(fees), max(fees)) == (D(lo), D(hi)), mult
    assert kalshi_trade_fee(1, "0.055") == D("0.003639")
    assert kalshi_fill_rounding("-0.055", "0.00363825") == (D("0.003639"), D("-0.06"), D("0.001361"))
    assert kalshi_buy_cash([("0.055", 1)]) == (D("0.06"), D("0.005"))      # "trade fee plus rounding fee is $0.005"


def test_arbitrage_walks_the_book_with_fees():
    yes, no = [("0.45", 100), ("0.40", 100)], [("0.50", 50), ("0.58", 200)]       # unsorted on purpose
    # no fees: 0.90/unit for 50, then 0.98 for 50, then 1.03 -> best q = 100, profit 5.0 + 1.0
    assert best_basket([pm_leg(yes), pm_leg(no)], 1) == (D("0.10"), D(100), D("6.00"))
    # fee rate 0.05: units 1-50 cost 0.90 + 0.012 + 0.0125; units 51-100 cost 0.98 + 0.012 + 0.01218 > 1
    at_min, q, profit = best_basket([pm_leg(yes, "0.05"), pm_leg(no, "0.05")], 1)
    assert (at_min, q, profit) == (D("0.0755"), D(50), D("3.775"))
    assert basket_profit([pm_leg(yes), pm_leg(no)], 201, 1) is None                       # book too thin
    # multi-outcome: YES on three exclusive outcomes at 0.30 + 0.30 + 0.35, 10 deep
    legs = [pm_leg([(p, 10)]) for p in ("0.30", "0.30", "0.35")]
    assert best_basket(legs, 1) == (D("0.05"), D(10), D("0.50"))
    # no edge: prices sum to more than the payout
    assert best_basket([pm_leg([("0.51", 10)]), pm_leg([("0.50", 10)])], 1)[1:] == (D(0), D(0))


def test_kalshi_book_and_cross_venue_edge():
    ob = {"yes_dollars": [["0.40", "10"], ["0.38", "5"]], "no_dollars": [["0.55", "7"]]}
    a = kalshi_asks(ob)
    assert a["yes"] == [(D("0.45"), D(7))] and a["no"] == [(D("0.60"), D(10)), (D("0.62"), D(5))]
    # Polymarket YES at 0.40 (rate 0.04) + Kalshi NO at 0.55, 10 units:
    # 4.00 + 0.096 fee; 5.50 + 0.17325 model fee -> 5.68 after cent rounding; profit 10 - 9.776
    legs = [pm_leg([("0.40", 10)], "0.04"), kalshi_leg([("0.55", 10)])]
    assert basket_profit(legs, 10, 1) == D("0.224")
    assert basket_profit(legs, 1, 1) == D(1) - D("0.4096") - D("0.57")


def test_episode_durations():
    t = [0, 1, 2, 3, 4, 5, 6, 10, 11]
    f = [False, True, True, False, True, False, False, True, False]
    assert episodes(t, f, max_gap=2) == [(1, 2, 2, 1, 3), (4, 4, 1, 0, 2), (10, 10, 1, 0, None)]


def test_brier_and_wilson_known_values():
    assert np.isclose(brier([0.7, 0.2], [1, 0]), 0.065)
    lo, hi = wilson(5, 10)
    assert np.isclose(lo, 0.2366, atol=1e-4) and np.isclose(hi, 0.7634, atol=1e-4)


def simulate(n_events, rng, slope=1.0):
    """Events of 1-8 exclusive outcomes. Prices on [0.01, 0.99]; truth = logistic(slope * logit(price))."""
    p, y, ev = [], [], []
    for e in range(n_events):
        k = rng.integers(1, 9)
        if k == 1:
            pr = rng.uniform(0.01, 0.99, 1)
        else:
            pr = 0.01 + (1 - 0.01 * k) * rng.dirichlet(np.ones(k))
        lg = np.log(pr / (1 - pr))
        q = 1 / (1 + np.exp(-slope * lg))
        if k == 1:
            out = (rng.random(1) < q).astype(float)
        else:
            out = np.zeros(k)
            out[rng.choice(k, p=q / q.sum())] = 1           # exactly one winner per event
        p += list(pr); y += list(out); ev += [e] * k
    return np.array(p), np.array(y), np.array(ev)


def test_calibrated_forecasts_pass():
    rng = np.random.default_rng(1)
    p, y, ev = simulate(6000, rng)
    r = recalibration(p, y, ev)
    assert abs(r["b"] - 1) < 3 * r["se_b"] and abs(r["a"]) < 3 * r["se_a"] and r["p_joint"] > 0.01
    assert abs(brier(p, y) - np.mean(p * (1 - p))) < 0.005           # calibrated: E[Brier] = E[p(1-p)]
    rows = calibration_table(p, y)
    assert sum(lo <= f <= hi for *_, f, lo, hi in rows) >= 9           # observed frequencies inside 95% bands
    ls = longshot(p, y, ev)
    assert abs(ls["mean"]) < 3 * ls["se"]


def test_miscalibrated_and_longshot_bias_detected():
    rng = np.random.default_rng(2)
    p, y, ev = simulate(6000, rng, slope=0.6)                           # prices too extreme
    r = recalibration(p, y, ev)
    assert r["p_joint"] < 1e-6 and abs(r["b"] - 0.6) < 0.1
    p, y, ev = simulate(6000, rng, slope=1.3)                           # favorite-longshot bias
    r = recalibration(p, y, ev)
    assert r["b"] > 1 and r["p_b1"] < 1e-6 and abs(r["b"] - 1.3) < 0.15
    ls = longshot(p, y, ev)
    assert ls["mean"] > 3 * ls["se"]                                    # longshots overpriced


def test_bias_test_false_positive_rate():
    """On unbiased markets with the same event clustering the 5% test must reject about 5% of the time."""
    rng = np.random.default_rng(3)
    rej = [recalibration(*simulate(250, rng))["p_b1"] < 0.05 for _ in range(1000)]
    assert 0.03 <= np.mean(rej) <= 0.07, np.mean(rej)


def test_murphy_decomposition_exact_on_binned_forecasts():
    rng = np.random.default_rng(4)
    p = rng.choice(np.arange(0.05, 1, 0.1), 20000)
    y = (rng.random(20000) < p).astype(float)
    m = murphy(p, y)
    assert np.isclose(brier(p, y), m["reliability"] - m["resolution"] + m["uncertainty"], atol=1e-12)


def test_parse_market_and_price_at():
    m = {"id": 799646, "question": "Q", "outcomes": '["Yes", "No"]', "outcomePrices": '["0", "1"]',
         "clobTokenIds": '["111", "222"]', "endDate": "2026-09-01T00:00:00Z", "closedTime": "2026-09-02 03:37:28+00",
         "startDate": "2025-12-02T20:41:57.974Z", "volumeNum": 3561.2, "negRisk": True, "enableOrderBook": True,
         "feeType": "politics_fees", "events": [{"id": "95915", "tags": [{"slug": "politics"}, {"slug": "economy"}]}]}
    r = parse_market(m)
    assert (r["y"], r["token0"], r["event_id"], r["category"]) == (0, "111", "95915", "economics")   # econ before politics
    assert r["T"] == r["end"] == 1788220800 and r["closed"] == 1788320248
    assert parse_market({**m, "outcomePrices": '["0.5", "0.5"]'})["y"] is None
    assert parse_market({**m, "events": [{"id": 1}], "feeType": "sports_fees_v2"})["category"] == "sports"
    ts, px = np.array([0, 10800, 21600]), np.array([0.2, 0.3, 0.4])
    assert price_at(ts, px, 15000) == 0.3 and price_at(ts, px, -1) is None
    assert price_at(ts, px, 21600 + 86400) == 0.4 and price_at(ts, px, 21601 + 86400) is None


def test_early_resolution_does_not_leak_the_outcome():
    """Scheduled end day 100; the event happens on day 60 and the price jumps to 0.99; the market closes on day 63
    (resolution lag). Anchoring on the close, 1 day before it sees 0.99: the outcome leaks. The fixed time
    before the scheduled end finds the market already closed and measures nothing."""
    ts = np.arange(0, 63 * DAY + 1, 10800.0)
    px = np.where(ts < 60 * DAY, 0.40, 0.99)
    end, closed = 100 * DAY, 63 * DAY
    assert price_at(ts, px, min(end, closed) - DAY) == 0.99                 # the leak
    assert measure_time(end, closed, DAY) is None and measure_time(end, closed, 40 * DAY) == 60 * DAY
    R = resolution_time(ts, px, closed)
    assert R == 60 * DAY and price_at(ts, px, R - DAY) == 0.40
    assert resolution_time(ts, np.full(len(ts), 0.5), closed) == ts[-1]
    assert resolution_time(ts, np.where(ts < 30 * DAY, 0.6, 0.01), closed) == 30 * DAY


def simulate_by_date(n, rng, E=60 * DAY, lag=2 * DAY):
    """Efficient 'will it happen by day 60' markets: hazard lam, price = P(event before E | none yet), calibrated at
    every fixed time. The event sends the price to 0.999 and the market closes `lag` later; with no event it
    decays to 0.001 and closes at E."""
    grid = np.arange(0, E + lag + 1, 10800.0)
    for _ in range(n):
        p0 = rng.uniform(0.05, 0.95)
        lam = -np.log(1 - p0) / E
        tau = rng.exponential(1 / lam)
        y = tau < E
        closed = tau + lag if y else E
        ts = grid[grid <= closed]
        px = np.clip(np.where(ts < min(tau, E), 1 - np.exp(-lam * np.clip(E - ts, 0, None)), float(y)), 0.001, 0.999)
        yield ts, px, E, closed, float(y)


def test_only_scheduled_anchor_keeps_an_efficient_market_calibrated():
    """Measuring 7 days before the actual close, or before prices settle, picks the moment with hindsight and
    makes an efficient market look miscalibrated; 7 days before the scheduled end (if still open) does not."""
    rng, h = np.random.default_rng(5), 7 * DAY
    obs = {"close": ([], []), "resolution": ([], []), "scheduled": ([], [])}
    for ts, px, end, closed, y in simulate_by_date(6000, rng):
        T = min(end, closed)
        for k, t in (("close", T - h), ("resolution", resolution_time(ts, px, T) - h), ("scheduled", measure_time(end, closed, h))):
            p = price_at(ts, px, t) if t is not None and t >= 0 else None
            if p is not None:
                obs[k][0].append(p)
                obs[k][1].append(y)
    fit = {k: recalibration(np.array(p), np.array(y), np.arange(len(p))) for k, (p, y) in obs.items()}
    assert fit["scheduled"]["p_joint"] > 0.01 and abs(fit["scheduled"]["b"] - 1) < 3 * fit["scheduled"]["se_b"]
    assert fit["close"]["p_joint"] < 1e-6 and fit["resolution"]["p_joint"] < 1e-6


def test_recurring_templates():
    qs = [f"Bitcoin Up or Down - October {d}, {h}:15AM-{h}:30AM ET" for d in range(1, 31) for h in range(1, 5)]
    qs += ["Will Everton FC win on 2026-10-17?", "Will Everton FC win on 2026-10-24?"]
    assert template(qs[0]) == "bitcoin up or down"
    assert recurring_templates(qs) == {"bitcoin up or down"}         # 120 markets; Everton only 2


def test_capacity_at_budget():
    legs = [pm_leg([("0.40", 100), ("0.45", 100)]), pm_leg([("0.50", 50), ("0.58", 200)])]
    # cost: 0.90/unit to 50, 0.98 to 100 (total 94), then 1.03/unit
    assert at_budget(legs, 1, 10) == (D("11.11"), D("9.9990"), D("1.1110"))
    assert at_budget(legs, 1, 100) == (D("105.82"), D("99.9946"), D("5.8254"))
    assert at_budget(legs, 1, 1000) is None                         # full depth costs only 197


def test_annualized_gap_vs_tbill():
    r = annualized(D("0.011"), D("0.989"), 75)                     # 1.1 cents on 98.9 for 75 days
    assert np.isclose(r, 0.011 / 0.989 * 365 / 75)
    assert np.isclose(tbill_yield(5.0), 365 * 0.05 / (360 - 0.05 * 91))   # 5.134%
    assert r > tbill_yield(4.0) and r < tbill_yield(6.0)


def test_book_sanity_checks():
    t = 1_000_000
    good = [t * 1000, [["0.40", "10"], ["0.39", "5"]], [["0.42", "7"], ["0.45", "1"]]]
    assert book_problems(good, t) == []
    assert book_problems([t * 1000, [["0.43", "1"]], [["0.42", "1"]]], t) == ["crossed book"]
    assert book_problems([t * 1000, [], [["1.00", "1"]]], t) == ["price outside (0, 1)"]
    assert book_problems([t * 1000, [["0.40", "0"]], []], t) == ["non-positive size"]
    assert book_problems([t * 1000, [["0.39", "1"], ["0.40", "1"]], []], t) == ["levels out of order or duplicated"]
    assert book_problems([(t - 36000) * 1000, *good[1:]], t) == []                # untouched for 10 h: still current
    assert book_problems([(t + 3600) * 1000, *good[1:]], t) == ["timestamp after snapshot"]


def test_gap_must_persist_into_next_snapshot():
    assert reachable([0, 120, 240, 360, 600], [True, True, False, True, True], 300) == [True, False, False, True, False]
    assert reachable([0, 1000], [True, True], 300) == [False, False]          # next snapshot too late


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok", t.__name__)
    print(len(tests), "tests ok")
