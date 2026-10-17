"""Download resolved Polymarket markets and their price histories into data/polymarket/ (local only, not committed).

  python scripts/fetch_history.py markets     # closed markets with volume >= $1,000 -> markets.jsonl
  python scripts/fetch_history.py prices      # 3-hour price history of the first outcome -> history.jsonl (resumable)
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pm.data import DAY, Client, parse_market

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "polymarket")
MARKETS, HISTORY = os.path.join(OUT, "markets.jsonl"), os.path.join(OUT, "history.jsonl")


def fetch_markets():
    os.makedirs(OUT, exist_ok=True)
    c, n, t0 = Client(min_interval=0.2), 0, time.time()
    with open(MARKETS + ".part", "w") as f:
        for m in c.markets(closed="true", volume_num_min=1000, include_tag="true"):
            f.write(json.dumps(parse_market(m)) + "\n")
            n += 1
            if n % 5000 == 0:
                print(f"{n} markets, {time.time() - t0:.0f}s", flush=True)
    os.replace(MARKETS + ".part", MARKETS)
    print(f"done: {n} markets", flush=True)


def wanted(r):
    """Binary, resolved YES/NO, traded on the order book, alive at least one day before T."""
    return (r["order_book"] and r["y"] is not None and r["n_outcomes"] == 2 and r["token0"] and r["T"]
            and r["start"] and r["T"] - r["start"] >= DAY)


def fetch_prices():
    rows = [r for r in map(json.loads, open(MARKETS)) if wanted(r)]
    done = {json.loads(l)["id"] for l in open(HISTORY)} if os.path.exists(HISTORY) else set()
    todo = [r for r in rows if r["id"] not in done]
    print(f"{len(rows)} eligible, {len(done)} done, {len(todo)} to fetch", flush=True)
    c, t0 = Client(min_interval=0.15), time.time()
    with open(HISTORY, "a") as f:
        for i, r in enumerate(todo, 1):
            try:
                ts, px = c.price_history(r["token0"])
            except RuntimeError as e:
                print("skip", r["id"], e, flush=True)
                continue
            f.write(json.dumps({"id": r["id"], "t": ts.astype(int).tolist(), "p": px.tolist()}) + "\n")
            if i % 1000 == 0:
                f.flush()
                print(f"{i}/{len(todo)}, {time.time() - t0:.0f}s", flush=True)
    print("done", flush=True)


if __name__ == "__main__":
    {"markets": fetch_markets, "prices": fetch_prices}[sys.argv[1]]()
