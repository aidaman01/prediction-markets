"""Questions (c) and (c') on the collected snapshots. Writes aggregates to results/.

  python scripts/scan_arb.py [YYYY-MM-DD ...]      # default: every day collected so far

(c)  one binary market: buy YES and NO. NO asks are the mirror of the YES bids (bid p -> ask 1 - p).
(c') one exhaustive multi-outcome event (negRisk, not augmented, every outcome in the snapshot):
     YES on every outcome pays 1; NO on every outcome pays n - 1.
A gap is counted as arbitrage only if, at the market's minimum order size and after each market's taker fees,
  1. every book in it passes the sanity checks (pm.arb.book_problems),
  2. its simple annualized return to the scheduled end beats the 3-month T-bill (FRED DTB3, bond-equivalent),
  3. it is still there in the next snapshot (reachable by someone who reacts one snapshot later).
For every gap: profit when deploying $100, $1,000 and $10,000 (empty if the books cannot absorb that much).
"""
import glob
import gzip
import io
import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime

import pandas as pd
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pm.arb import (annualized, at_budget, basket_cost, best_basket, book_problems, episodes, pm_leg, reachable,
                    tbill_yield)

SNAP, OUT = os.path.join(ROOT, "data", "snapshots"), os.path.join(ROOT, "results")
FRED = os.path.join(ROOT, "data", "fred_dtb3.csv")
INTERVAL, BUDGETS = 120, (100, 1000, 10000)
GAP = 2 * INTERVAL + 60                     # a missed snapshot or more breaks an episode


def dtb3():
    """FRED DTB3 (3-month T-bill, secondary market, discount basis, percent). Public, no key. Cached for a day."""
    if not os.path.exists(FRED) or time.time() - os.path.getmtime(FRED) > 86400:
        r = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DTB3", timeout=60)
        r.raise_for_status()
        open(FRED, "w").write(r.text)
    d = pd.read_csv(FRED)
    d.columns = ["date", "rate"]
    d["rate"] = pd.to_numeric(d.rate, errors="coerce")
    d = d.dropna()
    return pd.to_datetime(d.date).astype("int64").values // 10**9, d.rate.values


def read(path):
    with gzip.open(path, "rt") as f:
        for line in f:
            yield json.loads(line)


def leg(asks, m):
    fee = m.get("fee") or {}
    rate = fee.get("rate", 0) if m.get("fees_enabled") else 0
    return pm_leg(asks, rate, fee.get("exponent", 1))


def evaluate(kind, t, key, question, legs, payout, q, end, bill):
    at_min, best_q, best = best_basket(legs, payout, q)
    if at_min is None or best <= 0:
        return None
    cost = basket_cost(legs, q)
    days = max((datetime.fromisoformat(end.replace("Z", "+00:00")).timestamp() - t) / 86400, 1) if end else None
    ann = annualized(at_min, cost, days) if days and at_min > 0 else None
    caps = {f"profit_at_{b}": (lambda r: float(r[2]) if r else None)(at_budget(legs, payout, b)) for b in BUDGETS}
    return {"kind": kind, "t": t, "key": key, "question": question, "profit_at_min": float(at_min),
            "cost_at_min": float(cost), "best_q": float(best_q), "best_profit": float(best), "days_to_end": days,
            "annualized": ann, "tbill": bill, "beats_tbill": ann is not None and ann > bill, **caps}


def scan(days):
    bt, br = dtb3()
    unis = sorted((u["t"], u["markets"]) for d in days for u in read(os.path.join(SNAP, f"universe-{d}.jsonl.gz")))
    gaps, series, checks, bad = [], defaultdict(dict), Counter(), Counter()
    for d in days:
        for s in read(os.path.join(SNAP, f"{d}.jsonl.gz")):
            t, books = s["t"], s["books"]
            uni = [u for ut, u in unis if ut <= t][-1]
            bill = tbill_yield(float(br[bt <= t][-1]))
            events = defaultdict(list)
            for m in uni:
                b = books.get(m["tokens"][0])
                if not b:
                    continue
                problems = book_problems(b, t)
                bad.update(problems)
                yes_asks, no_asks = b[2], [(1 - float(p), s_) for p, s_ in b[1]]
                q = float(m.get("min_size") or 1)
                if yes_asks and no_asks and not problems:
                    checks["c"] += 1
                    g = None
                    if float(yes_asks[0][0]) + no_asks[0][0] < 1:          # fees only add: skip hopeless baskets
                        g = evaluate("c", t, m["id"], m["question"], [leg(yes_asks, m), leg(no_asks, m)], 1, q,
                                     m.get("end"), bill)
                    gaps += [g] if g else []
                    series[("c", m["id"])][t] = bool(g and g["beats_tbill"])
                if m["neg_risk"] and not m["augmented"]:
                    events[m["event_id"]].append((m, yes_asks, no_asks, problems))
            for ev, legs in events.items():
                if len(legs) != legs[0][0]["n_event_markets"] or len(legs) < 2 or any(x[3] for x in legs):
                    continue                    # an outcome is missing (not open / not in snapshot) or a book is bad
                q = max(float(m.get("min_size") or 1) for m, *_ in legs)
                for side, payout, k in (("yes", 1, 1), ("no", len(legs) - 1, 2)):
                    asks = [x[k] for x in legs]
                    if not all(asks):
                        continue
                    checks[f"c'-{side}"] += 1
                    g = None
                    if sum(float(a[0][0]) for a in asks) < payout:
                        g = evaluate(f"c'-{side}", t, ev, legs[0][0]["question"],
                                     [leg(a, x[0]) for x, a in zip(legs, asks)], payout, q, legs[0][0].get("end"), bill)
                    gaps += [g] if g else []
                    series[(f"c'-{side}", ev)][t] = bool(g and g["beats_tbill"])
    return pd.DataFrame(gaps), series, checks, bad


if __name__ == "__main__":
    days = sys.argv[1:] or sorted(os.path.basename(p)[:10] for p in glob.glob(os.path.join(SNAP, "2*.jsonl.gz")))
    gaps, series, checks, bad = scan(days)
    reach, rows = set(), []
    for (kind, key), s in series.items():
        ts = sorted(s)
        fl = [s[x] for x in ts]
        reach |= {(kind, key, x) for x, r in zip(ts, reachable(ts, fl, GAP)) if r}
        rows += [{"kind": kind, "key": key, "start": e[0], "snapshots": e[2], "min_seconds": e[3], "max_seconds": e[4]}
                 for e in episodes(ts, fl, GAP)]
    ep = pd.DataFrame(rows, columns=["kind", "key", "start", "snapshots", "min_seconds", "max_seconds"])
    if len(gaps):
        gaps["reachable"] = [(k, key, t) in reach for k, key, t in zip(gaps.kind, gaps.key, gaps.t)]
    summary = []
    for k in sorted(checks):
        g = gaps[gaps.kind == k] if len(gaps) else gaps
        arb = g[g.beats_tbill & g.reachable] if len(g) else g
        summary.append({"kind": k, "checks": checks[k], "gaps_after_fees": len(g),
                        "beat_tbill": int(g.beats_tbill.sum()) if len(g) else 0, "arbitrage": len(arb),
                        "arbitrage_episodes": int(((ep.kind == k) & (ep.snapshots >= 2)).sum()),
                        "median_profit_at_100": arb.profit_at_100.median() if len(arb) else None,
                        "median_profit_at_1000": arb.profit_at_1000.median() if len(arb) else None,
                        "median_profit_at_10000": arb.profit_at_10000.median() if len(arb) else None})
    summary = pd.DataFrame(summary)
    os.makedirs(OUT, exist_ok=True)
    summary.to_csv(os.path.join(OUT, "arbitrage_summary.csv"), index=False)
    n_snap = len({t for s in series.values() for t in s})
    print(f"{n_snap} snapshots, {days[0]}..{days[-1]}; book problems: {dict(bad)}")
    print(summary.to_string(index=False))
    if len(gaps):
        pd.set_option("display.width", 250)
        cols = ["kind", "key", "question", "profit_at_min", "days_to_end", "annualized", "tbill", "beats_tbill",
                "reachable", "profit_at_100", "profit_at_1000", "profit_at_10000"]
        print(gaps.drop_duplicates(["kind", "key"], keep="last")[cols].round(4).to_string(index=False))
