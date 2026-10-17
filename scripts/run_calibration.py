"""Questions (a) and (b) on resolved Polymarket markets. Reads data/polymarket/, writes aggregates to results/.

  python scripts/run_calibration.py [sample_ids.txt]     # default: every market with a downloaded history

Three measuring rules, all reported; "scheduled" is primary:
  scheduled   h before the scheduled end, only if the market is still open then (non-anticipating)
  close       h before T = min(scheduled end, actual close)                (the pre-registered rule)
  resolution  h before min(T, last price, start of the final run of prices >= 0.97 or <= 0.03)
"close" and "resolution" choose the time with hindsight; tests/test_pm.py shows both make a simulated efficient
market look miscalibrated, while "scheduled" does not.
Recurring machine-generated markets (question template shared by >= 100 markets) form their own category.
"""
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pm.calib import brier, calibration_table, longshot, murphy, recalibration
from pm.data import DAY, measure_time, price_at, recurring_templates, resolution_time, template

DATA, OUT = os.path.join(ROOT, "data", "polymarket"), os.path.join(ROOT, "results")
HORIZONS = {"1d": 1, "7d": 7, "30d": 30}
SAMPLES = {"main": 1_000, "robust": 50_000}            # minimum lifetime volume, USD
METHODS = ("scheduled", "close", "resolution")


def observations(ids=None):
    markets = {r["id"]: r for r in map(json.loads, open(os.path.join(DATA, "markets.jsonl")))}
    recurring = recurring_templates(r["question"] for r in markets.values())
    rows, whole_plateau, n = [], 0, 0
    for line in open(os.path.join(DATA, "history.jsonl")):
        h = json.loads(line)
        if (ids is not None and h["id"] not in ids) or not h["t"] or h["id"] not in markets:
            continue
        m, n = markets[h["id"]], n + 1
        ts, px = np.array(h["t"], float), np.array(h["p"], float)
        cat = "recurring" if template(m["question"]) in recurring else m["category"]
        R = resolution_time(ts, px, m["T"])
        whole_plateau += R <= m["start"]
        for method in METHODS:
            for name, days in HORIZONS.items():
                h = days * DAY
                t = {"close": m["T"] - h, "resolution": R - h,
                     "scheduled": measure_time(m["end"], m["closed"] or m["end"], h) if m["end"] else None}[method]
                if t is None or m["start"] > t:
                    continue
                p = price_at(ts, px, t)
                if p is not None:
                    rows.append((m["id"], m["event_id"], cat, m["volume"], method, name, p, m["y"]))
    cols = ["id", "event_id", "category", "volume", "method", "horizon", "price", "y"]
    return pd.DataFrame(rows, columns=cols), {"markets_with_history": n, "decided_from_first_price": whole_plateau}


def lookahead(df):
    """Share of measured prices already at >= 0.97 or <= 0.03, and how often such a price matched the outcome."""
    ext = (df.price >= 0.97) | (df.price <= 0.03)
    right = ext & ((df.price >= 0.97) == (df.y == 1))
    g = pd.DataFrame({"method": df.method, "horizon": df.horizon, "ext": ext, "right": right})
    return g.groupby(["method", "horizon"]).agg(n=("ext", "size"), share_extreme=("ext", "mean"),
                                                extreme_matching_outcome=("right", "sum")).reset_index()


def stats(d):
    p, y, ev = d.price.values, d.y.values, d.event_id.values
    r, m, ls = recalibration(p, y, ev), murphy(p, y), longshot(p, y, ev)
    return {"n": len(d), "events": r["clusters"], "yes_rate": y.mean(), "brier": brier(p, y), **m, "a": r["a"],
            "b": r["b"], "se_a": r["se_a"], "se_b": r["se_b"], "p_b1": r["p_b1"], "p_joint": r["p_joint"],
            "longshot_n": ls["n"], "longshot_overpricing": ls["mean"], "longshot_se": ls["se"]}


def summarize(df):
    out = []
    for method in METHODS:
        for sample, vmin in SAMPLES.items():
            for h in HORIZONS:
                d0 = df[(df.method == method) & (df.horizon == h) & (df.volume >= vmin)]
                groups = {"all": d0, "all_ex_recurring": d0[d0.category != "recurring"]}
                groups |= {c: d0[d0.category == c] for c in sorted(d0.category.unique())}
                for cat, d in groups.items():
                    if d.event_id.nunique() >= 30:
                        out.append({"method": method, "sample": sample, "horizon": h, "category": cat, **stats(d)})
    return pd.DataFrame(out)


def bins(df, method="scheduled", sample="main", h="7d"):
    d0 = df[(df.method == method) & (df.horizon == h) & (df.volume >= SAMPLES[sample])]
    rows = []
    for cat in ["all", "all_ex_recurring"] + sorted(d0.category.unique()):
        d = d0 if cat == "all" else d0[d0.category != "recurring"] if cat == "all_ex_recurring" else d0[d0.category == cat]
        for lo, hi, n, mp, f, wl, wh in calibration_table(d.price.values, d.y.values):
            rows.append({"category": cat, "lo": lo, "hi": hi, "n": n, "mean_price": mp, "freq": f, "wilson_lo": wl,
                         "wilson_hi": wh})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    ids = {l.strip() for l in open(sys.argv[1])} if len(sys.argv) > 1 else None
    df, cov = observations(ids)
    print("coverage:", cov)
    la = lookahead(df)
    la.to_csv(os.path.join(OUT, "lookahead.csv"), index=False, float_format="%.6g")
    print(la.to_string(index=False))
    s = summarize(df)
    s.to_csv(os.path.join(OUT, "calibration_summary.csv"), index=False, float_format="%.6g")
    bins(df).to_csv(os.path.join(OUT, "calibration_bins_7d.csv"), index=False, float_format="%.6g")
    pd.set_option("display.width", 250)
    cols = ["method", "sample", "horizon", "category", "n", "events", "brier", "reliability", "b", "se_b", "p_b1",
            "p_joint", "longshot_n", "longshot_overpricing", "longshot_se"]
    print(s[cols].round(4).to_string(index=False))
