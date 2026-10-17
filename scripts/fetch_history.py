"""Download resolved Polymarket markets and their price histories into data/polymarket/ (local only, not committed).

  python scripts/fetch_history.py markets     # closed markets with volume >= $1,000 -> markets.jsonl
  python scripts/fetch_history.py prices [markets.jsonl] [N]  # 3-hour price history of the first outcome -> history.jsonl
                                              # (resumable; random order, so a partial download is a random sample)
"""
import json
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pm.data import DAY, Client, parse_market

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "polymarket")
MARKETS, HISTORY = os.path.join(OUT, "markets.jsonl"), os.path.join(OUT, "history.jsonl")


def fetch_markets():
    """Resumable: the cursor of the next page is saved after every page."""
    os.makedirs(OUT, exist_ok=True)
    part, cfile = MARKETS + ".part", MARKETS + ".cursor"
    cursor = open(cfile).read().strip() if os.path.exists(cfile) and os.path.exists(part) else None
    n = sum(1 for _ in open(part)) if cursor else 0
    c, t0 = Client(min_interval=0.2, retries=10), time.time()
    with open(part, "a" if cursor else "w") as f:
        for page, cursor in c.market_pages(cursor, closed="true", volume_num_min=1000, include_tag="true"):
            f.writelines(json.dumps(parse_market(m)) + "\n" for m in page)
            f.flush()
            with open(cfile, "w") as cf:
                cf.write(cursor or "")
            n += len(page)
            if n % 5000 < len(page):
                print(f"{n} markets, {time.time() - t0:.0f}s", flush=True)
    os.replace(part, MARKETS)
    os.remove(cfile)
    print(f"done: {n} markets", flush=True)


def wanted(r):
    """Binary, resolved YES/NO, traded on the order book, alive at least one day before T."""
    return (r["order_book"] and r["y"] is not None and r["n_outcomes"] == 2 and r["token0"] and r["T"]
            and r["start"] and r["T"] - r["start"] >= DAY)


def fetch_prices(markets=MARKETS, limit=None):
    rows = list({r["id"]: r for r in map(json.loads, open(markets)) if wanted(r)}.values())   # dedupe resumed pages
    done = {json.loads(l)["id"] for l in open(HISTORY)} if os.path.exists(HISTORY) else set()
    todo = [r for r in rows if r["id"] not in done]
    random.Random(0).shuffle(todo)          # random order: whatever has been fetched so far is a random sample
    todo = todo[:int(limit)] if limit else todo
    print(f"{len(rows)} eligible, {len(done)} done, {len(todo)} to fetch", flush=True)
    workers = 8                             # each worker <= 1.25 req/s -> <= 10 req/s total; published limit 20 req/s
    clients, t0 = [Client(min_interval=0.8) for _ in range(workers)], time.time()

    def get(k_r):
        k, r = k_r
        try:
            return r, clients[k % workers].price_history(r["token0"])
        except RuntimeError as e:
            print("skip", r["id"], e, flush=True)
            return r, None

    with open(HISTORY, "a") as f, ThreadPoolExecutor(workers) as ex:
        for i, (r, h) in enumerate(ex.map(get, enumerate(todo)), 1):
            if h is not None:
                f.write(json.dumps({"id": r["id"], "t": h[0].astype(int).tolist(), "p": h[1].tolist()}) + "\n")
            if i % 1000 == 0:
                f.flush()
                print(f"{i}/{len(todo)}, {time.time() - t0:.0f}s", flush=True)
    print("done", flush=True)


if __name__ == "__main__":
    {"markets": fetch_markets, "prices": fetch_prices}[sys.argv[1]](*sys.argv[2:])
