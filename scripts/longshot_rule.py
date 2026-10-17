"""HYPOTHETICAL rule: sell every longshot quoted at or below X, 7 days before the scheduled end. No trades placed.

  python scripts/longshot_rule.py

Data: the (a)/(b) primary observations from scripts/run_calibration.py (same sample and filters). Each
market contributes its cheaper side, price q = min(p, 1 - p).
Costs per contract: half-spread + taker fee (rate * q * (1 - q)).
  Half-spread: mean (best ask - best bid) / 2 of live order books with the cheaper side at <= 10 cents, from the
  snapshots collected before config rule.spread_snapshots_until, in three price buckets. Historical spreads are not available, so today's spreads in
  active markets stand in for them. Fee: today's Polymarket taker rate for the category, applied to every
  market even though most historical markets charged none (conservative).
Split: older half / newer half by scheduled end. X (1..10 cents) is chosen on the older half by mean net P&L
per bet at base costs; the newer half is evaluated once with that X, at base and at 2x costs.
P&L is per 1-contract bet, in dollars; drawdown is on cumulative P&L with bets in order of scheduled end.
"""
import glob
import gzip
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from pm.calib import _cluster_meat, longshot_side, max_drawdown, sell_pnl
from pm.config import CFG
from run_calibration import DATA, OUT, observations, primary

R = CFG["rule"]

BUCKETS = [(0.0, 0.02), (0.02, 0.05), (0.05, 0.10)]
FEE = {"crypto": 0.07, "recurring": 0.07, "sports": 0.05, "economics": 0.05, "weather": 0.05, "other": 0.05,
       "politics": 0.04}


def half_spreads(every=10):
    """Mean half-spread per cheaper-side price bucket, and the share of near-extreme books that are one-sided."""
    hs, one_sided, two_sided = defaultdict(list), 0, 0
    for f in sorted(glob.glob(os.path.join(ROOT, "data", "snapshots", "2*.jsonl.gz"))):
        for k, line in enumerate(gzip.open(f, "rt")):
            if k % every:
                continue
            snap = json.loads(line)
            if snap["t"] >= R["spread_snapshots_until"].timestamp():
                continue
            for _, bids, asks in snap["books"].values():
                if bids and asks:
                    b, a = float(bids[0][0]), float(asks[0][0])
                    q = min((a + b) / 2, 1 - (a + b) / 2)
                    for lo, hi in BUCKETS:
                        if lo < q <= hi:
                            hs[(lo, hi)].append((a - b) / 2)
                            two_sided += 1
                elif bids or asks:
                    p = float((bids or asks)[0][0])
                    one_sided += min(p, 1 - p) <= 0.10
    return {k: float(np.mean(v)) for k, v in hs.items()}, {k: len(v) for k, v in hs.items()}, \
        one_sided / max(1, one_sided + two_sided)


def evaluate(d, x, mult, hs, series=False):
    s = d[d.q <= x].sort_values("end", kind="stable")
    spread = np.select([s.q <= hi for _, hi in BUCKETS], [hs[b] for b in BUCKETS], hs[BUCKETS[-1]])
    pnl = sell_pnl(s.q.values, s.won.values, mult * spread, mult * s.category.map(FEE).values)
    if series:
        return pd.DataFrame({"costs": f"{mult}x", "bet": np.arange(1, len(pnl) + 1), "cum_pnl": np.cumsum(pnl)})
    if len(pnl) < 2:
        return None
    meat, G = _cluster_meat((pnl - pnl.mean())[:, None], s.event_id.values)
    se = math.sqrt(G / (G - 1) * meat[0, 0]) / len(pnl)
    return {"X": x, "costs": f"{mult}x", "bets": len(pnl), "events": G, "mean_price": s.q.mean(),
            "win_rate": s.won.mean(), "mean_pnl": pnl.mean(), "se_pnl": se, "t": pnl.mean() / se,
            "total_pnl": pnl.sum(), "max_drawdown": max_drawdown(pnl),
            "mean_return_on_collateral": float(np.mean(pnl / (1 - s.q.values + mult * spread)))}


if __name__ == "__main__":
    hs, n_hs, one = half_spreads()
    print("mean half-spread by bucket:", {f"{lo}-{hi}": round(v, 4) for (lo, hi), v in hs.items()},
          "books:", {f"{lo}-{hi}": n for (lo, hi), n in n_hs.items()}, f"one-sided share {one:.2f}")
    d = primary(observations()).copy()
    keep = set(d.id)
    ends = {r["id"]: r["end"] for r in map(json.loads, open(os.path.join(DATA, "markets.jsonl"))) if r["id"] in keep}
    d["end"] = d.id.map(ends)
    d["q"], d["won"] = longshot_side(d.price.values, d.y.values)
    cut = d.end.median()
    old, new = d[d.end <= cut], d[d.end > cut]
    print(f"split at {pd.to_datetime(cut, unit='s').date()}: older {len(old)}, newer {len(new)} markets")
    grid = [c / 100 for c in R["thresholds_cents"]]
    train = pd.DataFrame([r for x in grid if (r := evaluate(old, x, 1, hs)) and r["bets"] >= R["min_bets"]])
    X = float(train.loc[train.mean_pnl.idxmax(), "X"])
    test = pd.DataFrame([evaluate(new, X, m, hs) for m in R["cost_multipliers"]])
    pd.concat([evaluate(new, X, m, hs, series=True) for m in R["cost_multipliers"]]).to_csv(
        os.path.join(OUT, "longshot_rule_test_pnl.csv"), index=False, float_format="%.6g")
    os.makedirs(OUT, exist_ok=True)
    pd.concat([train.assign(half="older (choose X)"), test.assign(half="newer (test once)")]).to_csv(
        os.path.join(OUT, "longshot_rule.csv"), index=False, float_format="%.6g")
    pd.set_option("display.width", 250)
    print("older half:\n" + train.round(4).to_string(index=False))
    print(f"chosen X = {X}\nnewer half:\n" + test.round(4).to_string(index=False))
