"""Every test checks against a known answer. Run: python -m pytest  (or python tests/test_pm.py)"""
import os
import sys
from decimal import ROUND_HALF_UP, Decimal as D

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pm.arb import basket_profit, best_basket, episodes, kalshi_asks, kalshi_leg, pm_leg
from pm.calib import brier, calibration_table, longshot, murphy, recalibration, wilson
from pm.data import parse_market, price_at
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


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok", t.__name__)
    print(len(tests), "tests ok")
