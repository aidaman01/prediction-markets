"""Questions (c) and (c') on the collected snapshots. Writes aggregates to results/.

  python scripts/scan_arb.py [YYYY-MM-DD ...]      # default: every day collected so far

(c)  one binary market: buy YES and NO. NO asks are the mirror of the YES bids (bid p -> ask 1 - p).
(c') one exhaustive multi-outcome event (negRisk, not augmented, every outcome in the snapshot):
     YES on every outcome pays 1; NO on every outcome pays n - 1.
Fees: each market's own fee schedule (taker). Edge is reported at the market's minimum order size.
A cheap float pre-check skips baskets whose best prices alone already cost at least the payout (fees only add).
"""
import glob
import gzip
import json
import os
import sys
from collections import defaultdict

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pm.arb import best_basket, episodes, pm_leg

SNAP, OUT = os.path.join(ROOT, "data", "snapshots"), os.path.join(ROOT, "results")


def read(path):
    with gzip.open(path, "rt") as f:
        for line in f:
            yield json.loads(line)


def leg(asks, m):
    fee = m.get("fee") or {}
    rate = fee.get("rate", 0) if m.get("fees_enabled") else 0
    return pm_leg(asks, rate, fee.get("exponent", 1))


def scan(days):
    unis = sorted((u["t"], u["markets"]) for d in days for u in read(os.path.join(SNAP, f"universe-{d}.jsonl.gz")))
    hits, flags, times, n_checked = [], defaultdict(dict), [], defaultdict(int)
    for d in days:
        for s in read(os.path.join(SNAP, f"{d}.jsonl.gz")):
            t, books = s["t"], s["books"]
            uni = [u for ut, u in unis if ut <= t][-1]
            times.append(t)
            events = defaultdict(list)
            for m in uni:
                b = books.get(m["tokens"][0])
                if not b:
                    continue
                yes_asks, no_asks = b[2], [(1 - float(p), s_) for p, s_ in b[1]]
                q = float(m.get("min_size") or 1)
                if yes_asks and no_asks:
                    n_checked["c"] += 1
                    hit = False
                    if float(yes_asks[0][0]) + no_asks[0][0] < 1:
                        at_min, bq, bp = best_basket([leg(yes_asks, m), leg(no_asks, m)], 1, q)
                        hit = at_min is not None and bp > 0
                        if hit:
                            hits.append(("c", t, m["id"], m["question"], float(at_min), float(bq), float(bp)))
                    flags["c"][m["id"]] = flags["c"].get(m["id"], {}) | {t: hit}
                if m["neg_risk"] and not m["augmented"]:
                    events[m["event_id"]].append((m, yes_asks, no_asks))
            for ev, legs in events.items():
                if len(legs) != legs[0][0]["n_event_markets"] or len(legs) < 2:
                    continue                                   # not every outcome is open and in the snapshot
                q = max(float(m.get("min_size") or 1) for m, _, _ in legs)
                for side, payout, k in (("yes", 1, 1), ("no", len(legs) - 1, 2)):
                    asks = [x[k] for x in legs]
                    if not all(asks):
                        continue
                    n_checked[f"c'-{side}"] += 1
                    hit = False
                    if sum(float(a[0][0]) for a in asks) < payout:
                        at_min, bq, bp = best_basket([leg(a, m) for (m, _, _), a in zip(legs, asks)], payout, q)
                        hit = at_min is not None and bp > 0
                        if hit:
                            hits.append((f"c'-{side}", t, ev, legs[0][0]["question"], float(at_min), float(bq), float(bp)))
                    flags[f"c'-{side}"][ev] = flags[f"c'-{side}"].get(ev, {}) | {t: hit}
    return hits, flags, times, n_checked


if __name__ == "__main__":
    days = sys.argv[1:] or sorted(os.path.basename(p)[:10] for p in glob.glob(os.path.join(SNAP, "2*.jsonl.gz")))
    hits, flags, times, n = scan(days)
    gap = 2 * 120 + 60                                          # a missed snapshot or more breaks an episode
    rows = []
    for kind, per in flags.items():
        for key, series in per.items():
            ts = sorted(series)
            for e in episodes(ts, [series[x] for x in ts], gap):
                rows.append({"kind": kind, "key": key, "start": e[0], "end": e[1], "snapshots": e[2],
                             "min_seconds": e[3], "max_seconds": e[4]})
    ep = pd.DataFrame(rows, columns=["kind", "key", "start", "end", "snapshots", "min_seconds", "max_seconds"])
    h = pd.DataFrame(hits, columns=["kind", "t", "key", "question", "edge_at_min", "best_q", "best_profit"])
    os.makedirs(OUT, exist_ok=True)
    summary = pd.DataFrame([{"kind": k, "checks": n[k], "positive": int((h.kind == k).sum()),
                             "episodes": int((ep.kind == k).sum()),
                             "median_profit_usd": h[h.kind == k].best_profit.median()} for k in sorted(n)])
    summary.to_csv(os.path.join(OUT, "arbitrage_summary.csv"), index=False)
    print(f"{len(times)} snapshots, {days[0]}..{days[-1]}")
    print(summary.to_string(index=False))
    if len(h):
        print(h.sort_values("best_profit", ascending=False).head(20).to_string(index=False))
