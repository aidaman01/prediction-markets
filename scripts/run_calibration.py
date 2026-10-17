"""Questions (a) and (b) on the stratified sample. Reads data/polymarket/ and config.toml, writes results/.

  python scripts/run_calibration.py

Three measuring rules, all reported; "scheduled" is primary:
  scheduled   h before the scheduled end, only if the market is still open then (non-anticipating)
  close       h before T = min(scheduled end, actual close)                (the pre-registered rule)
  resolution  h before min(T, last price, start of the final run of prices >= 0.97 or <= 0.03)
"close" and "resolution" choose the time with hindsight; pm/sim.py shows both make a simulated efficient market
look miscalibrated, while "scheduled" does not.
Primary hypothesis: slope b = 1 for all markets, scheduled rule, primary horizon, main sample, all prices.
Every other category / horizon row of that sample is exploratory and gets Holm-adjusted p-values.
Robustness checks (not in the Holm family): without recurring markets; volume >= robust_volume; fresh prices.
Robustness: volume >= robust_volume; and "fresh" prices only (price changed within max_age_hours).
"""
import json
import os
import sys
import time

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pm.calib import brier, calibration_table, holm, longshot, murphy, recalibration
from pm.config import CFG
from pm.data import measure_time, price_age, price_at, recurring_templates, resolution_time, template

DATA, OUT = os.path.join(ROOT, "data", "polymarket"), os.path.join(ROOT, "results")
MANIFEST = os.path.join(OUT, "sample_ids.txt")
M, A, S = CFG["measure"], CFG["analysis"], CFG["sample"]
HORIZONS = {f"{d}d": d * 86400 for d in M["horizons_days"]}
SAMPLES = {"main": A["main_volume"], "robust": A["robust_volume"]}
METHODS = ("scheduled", "close", "resolution")
PRIMARY = {"method": "scheduled", "sample": "main", "horizon": M["primary_horizon"], "category": "all", "prices": "all"}


def observations():
    """One row per market, rule and horizon with a usable price. Complete months of resolution only."""
    ids = {l.strip() for l in open(MANIFEST)}
    markets = {r["id"]: r for r in map(json.loads, open(os.path.join(DATA, "markets.jsonl")))}
    recurring = recurring_templates((r["question"] for r in markets.values()), A["recurring_min_count"])
    rows, gap = [], M["max_gap_hours"] * 3600
    for line in open(os.path.join(DATA, "history.jsonl")):
        h = json.loads(line)
        if h["id"] not in ids or not h["t"] or h["id"] not in markets:
            continue
        m = markets[h["id"]]
        month = time.strftime("%Y-%m", time.gmtime(m["T"]))
        if not S["first_month"] <= month <= S["last_month"]:
            continue
        ts, px = np.array(h["t"], float), np.array(h["p"], float)
        cat = "recurring" if template(m["question"]) in recurring else m["category"]
        R = resolution_time(ts, px, m["T"], M["extreme_hi"], M["extreme_lo"])
        for method in METHODS:
            for name, hsec in HORIZONS.items():
                t = {"close": m["T"] - hsec, "resolution": R - hsec,
                     "scheduled": measure_time(m["end"], m["closed"] or m["end"], hsec) if m["end"] else None}[method]
                if t is None or m["start"] > t:
                    continue
                p = price_at(ts, px, t, gap)
                if p is not None:
                    rows.append((m["id"], m["event_id"], cat, m["volume"], month, method, name, p, m["y"],
                                 price_age(ts, px, t)))
    cols = ["id", "event_id", "category", "volume", "month", "method", "horizon", "price", "y", "age"]
    return pd.DataFrame(rows, columns=cols)


def stats(d):
    p, y, ev = d.price.values, d.y.values, d.event_id.values
    r, m, ls = recalibration(p, y, ev), murphy(p, y), longshot(p, y, ev, A["longshot_cut"])
    b = brier(p, y)
    return {"n": len(d), "events": r["clusters"], "yes_rate": y.mean(), "brier": b, **m,
            "climatology_brier": m["uncertainty"], "skill_vs_climatology": 1 - b / m["uncertainty"],
            "a": r["a"], "b": r["b"], "se_a": r["se_a"], "se_b": r["se_b"], "p_b1": r["p_b1"], "p_joint": r["p_joint"],
            "longshot_n": ls["n"], "longshot_overpricing": ls["mean"], "longshot_se": ls["se"]}


def groups(d0):
    g = {"all": d0, "all_ex_recurring": d0[d0.category != "recurring"]}
    return g | {c: d0[d0.category == c] for c in sorted(d0.category.unique())}


def summarize(df):
    out, fresh = [], df.age <= M["max_age_hours"] * 3600
    for method in METHODS:
        for prices, sel in (("all", df.method == method), ("fresh", (df.method == method) & fresh)):
            if prices == "fresh" and method != "scheduled":
                continue
            for sample, vmin in SAMPLES.items():
                for h in HORIZONS:
                    for cat, d in groups(df[sel & (df.horizon == h) & (df.volume >= vmin)]).items():
                        if d.event_id.nunique() >= A["min_events"]:
                            out.append({"method": method, "prices": prices, "sample": sample, "horizon": h,
                                        "category": cat, **stats(d)})
    s = pd.DataFrame(out)
    key = (s.method == "scheduled") & (s.prices == "all") & (s["sample"] == "main")
    prim = key & (s.horizon == PRIMARY["horizon"]) & (s.category == "all")
    expl = key & ~prim & (s.category != "all_ex_recurring")      # without recurring: a robustness check
    s["role"] = np.where(prim, "primary", np.where(expl, "exploratory", "robustness / other rule"))
    for c in ("p_b1", "p_joint"):
        s[c + "_holm"] = np.nan
        s.loc[expl, c + "_holm"] = holm(s.loc[expl, c].values)
    return s


def primary(df):
    return df[(df.method == "scheduled") & (df.horizon == PRIMARY["horizon"]) & (df.volume >= A["main_volume"])]


def binning(d):
    out = []
    for bins in A["bins"]:
        out.append({"binning": f"{bins} equal-width", **murphy(d.price.values, d.y.values, bins)})
    out.append({"binning": "10 equal-count", **murphy(d.price.values, d.y.values, 10, equal_count=True)})
    return pd.DataFrame(out)


def longshot_by_volume(d):
    edges = A["volume_buckets"] + [np.inf]
    out = []
    for lo, hi in zip(edges, edges[1:]):
        x = d[(d.volume >= lo) & (d.volume < hi)]
        ls = longshot(x.price.values, x.y.values, x.event_id.values, A["longshot_cut"])
        out.append({"volume_lo": lo, "volume_hi": hi, "n": ls["n"], "events": ls.get("clusters"),
                    "overpricing": ls["mean"], "se": ls["se"]})
    return pd.DataFrame(out)


def lookahead(df):
    """Share of measured prices already at >= extreme_hi or <= extreme_lo, and how often such a price matched."""
    ext = (df.price >= M["extreme_hi"]) | (df.price <= M["extreme_lo"])
    right = ext & ((df.price >= M["extreme_hi"]) == (df.y == 1))
    g = pd.DataFrame({"method": df.method, "horizon": df.horizon, "ext": ext, "right": right})
    return g.groupby(["method", "horizon"]).agg(n=("ext", "size"), share_extreme=("ext", "mean"),
                                                extreme_matching_outcome=("right", "sum")).reset_index()


def bins_table(d):
    rows = []
    for cat, x in groups(d).items():
        for lo, hi, n, mp, f, wl, wh in calibration_table(x.price.values, x.y.values):
            rows.append({"category": cat, "events": x.event_id.nunique(), "lo": lo, "hi": hi, "n": n,
                         "mean_price": mp, "freq": f, "wilson_lo": wl, "wilson_hi": wh})
    return pd.DataFrame(rows)


def write(name, frame):
    frame.to_csv(os.path.join(OUT, name), index=False, float_format="%.6g")


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    df = observations()
    print(f"{df.id.nunique()} markets, months {df.month.min()}..{df.month.max()}")
    s = summarize(df)
    d = primary(df)
    age = d.age / 3600
    write("calibration_summary.csv", s)
    write("calibration_bins_7d.csv", bins_table(d))
    write("binning_sensitivity.csv", binning(d))
    write("longshot_by_volume.csv", longshot_by_volume(d))
    write("lookahead.csv", lookahead(df))
    write("staleness.csv", pd.DataFrame([{"n": len(d), "median_age_hours": age.median(),
                                          "share_older_than_max_age": float((age > M["max_age_hours"]).mean())}]))
    pd.set_option("display.width", 250)
    cols = ["role", "prices", "sample", "horizon", "category", "n", "events", "brier", "climatology_brier",
            "reliability", "b", "se_b", "p_b1", "p_b1_holm", "p_joint", "longshot_overpricing", "longshot_se"]
    print(s[(s.method == "scheduled")][cols].round(4).to_string(index=False))
