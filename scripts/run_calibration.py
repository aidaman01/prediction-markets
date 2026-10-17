"""Questions (a) and (b) on resolved Polymarket markets. Reads data/polymarket/, writes aggregates to results/.

  python scripts/run_calibration.py
"""
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pm.calib import brier, calibration_table, longshot, murphy, recalibration
from pm.data import DAY, price_at

DATA, OUT = os.path.join(ROOT, "data", "polymarket"), os.path.join(ROOT, "results")
HORIZONS = {"1d": 1, "7d": 7, "30d": 30}
SAMPLES = {"main": 1_000, "robust": 50_000}            # minimum lifetime volume, USD


def observations():
    markets = {r["id"]: r for r in map(json.loads, open(os.path.join(DATA, "markets.jsonl")))}
    rows, coverage = [], {"history_rows": 0, "empty_history": 0}
    for line in open(os.path.join(DATA, "history.jsonl")):
        h = json.loads(line)
        coverage["history_rows"] += 1
        if not h["t"]:
            coverage["empty_history"] += 1
            continue
        m = markets[h["id"]]
        ts, px = np.array(h["t"], float), np.array(h["p"], float)
        for name, days in HORIZONS.items():
            t = m["T"] - days * DAY
            if m["start"] > t:
                continue
            p = price_at(ts, px, t)
            if p is not None:
                rows.append((m["id"], m["event_id"], m["category"], m["volume"], name, p, m["y"]))
    cols = ["id", "event_id", "category", "volume", "horizon", "price", "y"]
    return pd.DataFrame(rows, columns=cols), coverage


def summarize(df):
    out = []
    for (sample, vmin) in SAMPLES.items():
        for h in HORIZONS:
            d0 = df[(df.horizon == h) & (df.volume >= vmin)]
            for cat in ["all"] + sorted(d0.category.unique()):
                d = d0 if cat == "all" else d0[d0.category == cat]
                if d.event_id.nunique() < 30:
                    continue
                p, y, ev = d.price.values, d.y.values, d.event_id.values
                r, m, ls = recalibration(p, y, ev), murphy(p, y), longshot(p, y, ev)
                out.append({"sample": sample, "horizon": h, "category": cat, "n": len(d), "events": r["clusters"],
                            "yes_rate": y.mean(), "brier": brier(p, y), **m, "a": r["a"], "b": r["b"],
                            "se_a": r["se_a"], "se_b": r["se_b"], "p_b1": r["p_b1"], "p_joint": r["p_joint"],
                            "longshot_n": ls["n"], "longshot_overpricing": ls["mean"], "longshot_se": ls["se"]})
    return pd.DataFrame(out)


def bins(df, sample="main", h="7d"):
    d0 = df[(df.horizon == h) & (df.volume >= SAMPLES[sample])]
    rows = []
    for cat in ["all"] + sorted(d0.category.unique()):
        d = d0 if cat == "all" else d0[d0.category == cat]
        for lo, hi, n, mp, f, wl, wh in calibration_table(d.price.values, d.y.values):
            rows.append({"category": cat, "lo": lo, "hi": hi, "n": n, "mean_price": mp, "freq": f, "wilson_lo": wl,
                         "wilson_hi": wh})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    df, cov = observations()
    print("coverage:", cov)
    print(df.groupby(["horizon", "category"]).size().unstack(0).to_string())
    s = summarize(df)
    s.to_csv(os.path.join(OUT, "calibration_summary.csv"), index=False, float_format="%.6g")
    bins(df).to_csv(os.path.join(OUT, "calibration_bins_7d.csv"), index=False, float_format="%.6g")
    pd.set_option("display.width", 250)
    print(s.round(4).to_string(index=False))
