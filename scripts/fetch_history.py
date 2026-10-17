"""Download resolved Polymarket markets and their price histories into data/polymarket/ (local only, not committed).

  python scripts/fetch_history.py markets     # closed markets with volume >= $1,000 -> markets.jsonl
  python scripts/fetch_history.py sample [K]   # stratified sample: up to K (default 1000) markets per month -> sample_ids.txt
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
SAMPLE = os.path.join(OUT, "sample_ids.txt")


# Disjoint scheduled-end windows, fetched in parallel (the API is latency-bound at ~1 page/s per connection).
WINDOWS = ["2000-01-01", "2024-01-01", "2024-07-01", "2025-01-01"] + [
    f"{y}-{m:02d}-01" for y, m in [(2025, m) for m in range(7, 13)] + [(2026, m) for m in range(1, 13)]] + ["2100-01-01"]


def fetch_window(lo, hi):
    """One window, resumable: the cursor of the next page is saved after every page."""
    part = os.path.join(OUT, f"markets-{lo}.jsonl.part")
    cfile, done = part.replace(".part", ".cursor"), part.replace(".part", "")
    if os.path.exists(done):
        return sum(1 for _ in open(done))
    cursor = open(cfile).read().strip() if os.path.exists(cfile) and os.path.exists(part) else None
    n = sum(1 for _ in open(part)) if cursor else 0
    c = Client(min_interval=0.2, retries=10)
    with open(part, "a" if cursor else "w") as f:
        for page, cursor in c.market_pages(cursor, closed="true", volume_num_min=1000, include_tag="true",
                                           end_date_min=f"{lo}T00:00:00Z", end_date_max=f"{hi}T00:00:00Z"):
            f.writelines(json.dumps(parse_market(m)) + "\n" for m in page)
            f.flush()
            with open(cfile, "w") as cf:
                cf.write(cursor or "")
            n += len(page)
            if n % 20000 < len(page):
                print(f"{lo}: {n} markets", flush=True)
    os.replace(part, done)
    os.remove(cfile)
    print(f"{lo}: done, {n} markets", flush=True)
    return n


def fetch_markets():
    """All closed markets with volume >= $1,000, 12 windows at a time (~16 req/s; Gamma /markets limit 30 req/s)."""
    os.makedirs(OUT, exist_ok=True)
    with ThreadPoolExecutor(12) as ex:
        counts = list(ex.map(lambda w: fetch_window(*w), zip(WINDOWS, WINDOWS[1:])))
    seen = set()
    with open(MARKETS + ".tmp", "w") as f:                  # windows share boundaries: dedupe by id
        for lo in WINDOWS[:-1]:
            for line in open(os.path.join(OUT, f"markets-{lo}.jsonl")):
                i = json.loads(line)["id"]
                if i not in seen:
                    seen.add(i)
                    f.write(line)
    os.replace(MARKETS + ".tmp", MARKETS)
    print(f"done: {len(seen)} markets ({sum(counts)} rows over windows)", flush=True)


def wanted(r):
    """Binary, resolved YES/NO, traded on the order book, alive at least one day before T."""
    return (r["order_book"] and r["y"] is not None and r["n_outcomes"] == 2 and r["token0"] and r["T"]
            and r["start"] and r["T"] - r["start"] >= DAY)


def stratified_sample(k=1000, seed=0):
    """Up to k eligible markets drawn at random from every calendar month (UTC) of resolution T."""
    by_month = {}
    for r in {r["id"]: r for r in map(json.loads, open(MARKETS)) if wanted(r)}.values():
        by_month.setdefault(time.strftime("%Y-%m", time.gmtime(r["T"])), []).append(r["id"])
    rng, ids = random.Random(seed), []
    for month in sorted(by_month):
        pool = sorted(by_month[month])
        pick = rng.sample(pool, min(int(k), len(pool)))
        ids += pick
        print(month, len(pool), len(pick), flush=True)
    open(SAMPLE, "w").write("\n".join(ids) + "\n")
    print(f"{len(ids)} markets in {len(by_month)} months -> {SAMPLE}", flush=True)


def fetch_prices(markets=MARKETS, limit=None, ids=None):
    rows = list({r["id"]: r for r in map(json.loads, open(markets)) if wanted(r)}.values())   # dedupe resumed pages
    if ids:
        keep = {l.strip() for l in open(ids)}
        rows = [r for r in rows if r["id"] in keep]
    done = {json.loads(l)["id"] for l in open(HISTORY)} if os.path.exists(HISTORY) else set()
    todo = [r for r in rows if r["id"] not in done]
    random.Random(0).shuffle(todo)          # random order: whatever has been fetched so far is a random sample
    todo = todo[:int(limit)] if limit else todo
    print(f"{len(rows)} eligible, {len(done)} done, {len(todo)} to fetch", flush=True)
    workers = 12                            # each worker <= 1.25 req/s -> <= 15 req/s total; published limit 20 req/s
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
    {"markets": fetch_markets, "prices": fetch_prices, "sample": stratified_sample,
     "sample_prices": lambda: fetch_prices(MARKETS, None, SAMPLE)}[sys.argv[1]](*sys.argv[2:])
