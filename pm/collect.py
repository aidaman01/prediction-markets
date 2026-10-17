"""Order-book snapshot collector for questions (c) and (c'). Polymarket only (Kalshi: see README, terms).

  python -m pm.collect                 # runs forever: snapshot every --interval seconds
  python -m pm.collect --once          # one snapshot, then exit

Universe (refreshed hourly): every open, order-book market of every event with >= $10,000 traded in the last
24 hours, so multi-outcome events are complete. Only the first outcome's book is requested: Polymarket mirrors
the second outcome's book from it (YES bid at p == NO ask at 1 - p; checked by `--check-mirror`).
Files (local only): data/snapshots/YYYY-MM-DD.jsonl.gz, one gzip member per snapshot:
  {"t": unix time, "books": {token: [book_ms, [[bid, size], ...best first], [[ask, size], ...best first]]}}
data/snapshots/universe-YYYY-MM-DD.jsonl.gz holds the market metadata of each refresh.
"""
import argparse
import gzip
import json
import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler

from pm.config import CFG
from pm.data import GAMMA, Client

C = CFG["collector"]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP, LOGS = os.path.join(ROOT, "data", "snapshots"), os.path.join(ROOT, "logs")
log = logging.getLogger("collector")


def universe(c, min_vol24h=C["min_event_volume_24h"]):
    out, params = [], {"limit": 100, "closed": "false", "order": "volume24hr", "ascending": "false"}
    while True:
        d = c.call("GET", f"{GAMMA}/events/keyset", params=params)
        for e in d.get("events") or []:
            if (e.get("volume24hr") or 0) < min_vol24h:
                return out
            for m in e.get("markets") or []:
                tokens = json.loads(m.get("clobTokenIds") or "[]")
                if m.get("enableOrderBook") and m.get("acceptingOrders") and not m.get("closed") and len(tokens) == 2:
                    out.append({"id": m["id"], "event_id": e["id"], "tokens": tokens, "question": m.get("question"),
                                "neg_risk": bool(e.get("negRisk")), "augmented": bool(e.get("negRiskAugmented")),
                                "neg_risk_other": bool(m.get("negRiskOther")), "fee": m.get("feeSchedule"),
                                "fees_enabled": m.get("feesEnabled"), "min_size": m.get("orderMinSize"),
                                "tick": m.get("orderPriceMinTickSize"), "end": m.get("endDate"),
                                "n_event_markets": len(e.get("markets") or []), "event_vol24h": e.get("volume24hr")})
        if not d.get("next_cursor"):
            return out
        params["after_cursor"] = d["next_cursor"]


def compact(book, depth):
    bids = sorted(book.get("bids") or [], key=lambda l: -float(l["price"]))[:depth]
    asks = sorted(book.get("asks") or [], key=lambda l: float(l["price"]))[:depth]
    return [int(book.get("timestamp") or 0), [[l["price"], l["size"]] for l in bids],
            [[l["price"], l["size"]] for l in asks]]


def snapshot(c, tokens, depth=C["depth"], batch=500):
    books = {}
    for i in range(0, len(tokens), batch):
        for b in c.books(tokens[i:i + batch]):
            books[b["asset_id"]] = compact(b, depth)
    return books


def append(path, obj):
    with gzip.open(path, "at") as f:              # each call adds one gzip member; readers see one stream
        f.write(json.dumps(obj, separators=(",", ":")) + "\n")


def run(interval, refresh, depth, once=False):
    os.makedirs(SNAP, exist_ok=True)
    c, uni, uni_t = Client(min_interval=0.25), [], 0
    while True:
        start = time.time()
        day = time.strftime("%Y-%m-%d", time.gmtime(start))
        try:
            if start - uni_t >= refresh or not uni:
                uni, uni_t = universe(c), start
                append(os.path.join(SNAP, f"universe-{day}.jsonl.gz"), {"t": int(start), "markets": uni})
                log.info("universe: %d markets, %d events", len(uni), len({m["event_id"] for m in uni}))
            books = snapshot(c, [m["tokens"][0] for m in uni], depth)
            append(os.path.join(SNAP, f"{day}.jsonl.gz"), {"t": int(start), "books": books})
            log.info("snapshot: %d books in %.1fs", len(books), time.time() - start)
        except Exception:
            log.exception("snapshot failed")
        if once:
            return
        time.sleep(max(1.0, interval - (time.time() - start)))


def check_mirror(n=500):
    """Fetch both outcomes' books for n markets and count those where the second is not the first's mirror."""
    c = Client(min_interval=0.25)
    uni = universe(c)[:n]
    a = b = snapshot(c, [t for m in uni for t in m["tokens"]], depth=1000)    # pairs in the same request
    flip = lambda lv: sorted([round(1 - float(p), 6), float(s)] for p, s in lv)
    both = [m for m in uni if m["tokens"][0] in a and m["tokens"][1] in b]
    side = lambda lv: sorted([float(p), float(s)] for p, s in lv)
    bad = [m["id"] for m in both if flip(a[m["tokens"][0]][1]) != side(b[m["tokens"][1]][2])
           or flip(a[m["tokens"][0]][2]) != side(b[m["tokens"][1]][1])]
    print(f"{len(uni)} markets, {len(both)} with both books, {len(bad)} not mirrored: {bad[:10]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=C["interval_seconds"])
    ap.add_argument("--refresh", type=int, default=C["refresh_seconds"])
    ap.add_argument("--depth", type=int, default=C["depth"])
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--check-mirror", action="store_true")
    a = ap.parse_args()
    os.makedirs(LOGS, exist_ok=True)
    h = RotatingFileHandler(os.path.join(LOGS, "collector.log"), maxBytes=5_000_000, backupCount=3)
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[h] + ([logging.StreamHandler()] if sys.stderr.isatty() else []))
    if a.check_mirror:
        check_mirror()
    else:
        run(a.interval, a.refresh, a.depth, a.once)
