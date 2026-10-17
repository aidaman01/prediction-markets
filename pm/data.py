"""Polymarket public API (read-only, no key) and parsing of its records.

Endpoints and limits from docs.polymarket.com (api-reference/rate-limits): Gamma /markets 300 req/10s,
data-api /v2/prices-history 200 req/10s, CLOB /books 500 req/10s. We stay far below them.
"""
import json
import re
import time
from collections import Counter
from datetime import datetime, timezone

import numpy as np
import requests

GAMMA = "https://gamma-api.polymarket.com"
DATA = "https://data-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
DAY = 86400

# Fixed category mapping, checked in order; first match wins. Inputs: tag slugs of the market and its events,
# the old free-text `category` field and the fee type prefix (e.g. "sports_fees_v2" -> "sports").
CATEGORIES = [
    ("sports", {"sports", "nba", "nfl", "mlb", "nhl", "soccer", "tennis", "golf", "ufc", "mma", "boxing", "f1",
                "cricket", "esports", "ncaa", "basketball", "football", "baseball", "hockey", "olympics"}),
    ("crypto", {"crypto", "bitcoin", "ethereum", "solana", "xrp", "crypto-prices"}),
    ("weather", {"weather", "climate", "temperature", "hurricanes", "climate-weather"}),
    ("economics", {"economy", "economics", "fed", "fed-rates", "inflation", "cpi", "jobs", "gdp", "finance",
                   "business", "stocks", "economic-policy", "interest-rates", "earnings"}),
    ("politics", {"politics", "elections", "us-presidential-election", "geopolitics", "world-elections",
                  "us-politics", "global-elections", "congress", "trump", "us-current-affairs"}),
]


def category(labels):
    labels = {str(s).lower().replace(" ", "-") for s in labels if s}
    for name, keys in CATEGORIES:
        if labels & keys:
            return name
    return "other"


def _ts(s):
    if not s:
        return None
    s = s.replace(" ", "T").replace("Z", "+00:00")
    if s.endswith("+00"):
        s += ":00"
    return datetime.fromisoformat(s).astimezone(timezone.utc).timestamp()


def _json(x):
    return json.loads(x) if isinstance(x, str) else (x or [])


def parse_market(m):
    """Flat record for a Gamma market. y = 1 if the first outcome won, 0 if it lost, None otherwise."""
    prices, tokens = _json(m.get("outcomePrices")), _json(m.get("clobTokenIds"))
    y = {("1", "0"): 1, ("0", "1"): 0}.get(tuple(prices)) if len(prices) == 2 else None
    events = m.get("events") or [{}]
    labels = [t.get("slug") for t in (m.get("tags") or [])]
    labels += [t.get("slug") for e in events for t in (e.get("tags") or [])]
    labels += [m.get("category"), (m.get("feeType") or "").split("_fees")[0]]
    end, closed = _ts(m.get("endDate")), _ts(m.get("closedTime"))
    return {
        "id": str(m.get("id")), "question": m.get("question"), "event_id": str(events[0].get("id") or m.get("id")),
        "token0": tokens[0] if tokens else None, "y": y, "n_outcomes": len(prices),
        "start": _ts(m.get("startDate") or m.get("createdAt")), "end": end, "closed": closed,
        "T": min(t for t in (end, closed) if t is not None) if (end or closed) else None,
        "volume": float(m.get("volumeNum") or 0), "neg_risk": bool(m.get("negRisk")),
        "order_book": bool(m.get("enableOrderBook")), "category": category(labels),
    }


_MONTHS = ("january|february|march|april|may|june|july|august|september|october|november|december|"
           "jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec|monday|tuesday|wednesday|thursday|friday|saturday|sunday")


def template(question):
    """Question with dates, times and numbers removed: 'Bitcoin Up or Down - Oct 17, 8:15AM ET' -> 'bitcoin up or down'."""
    q = re.sub(rf"\b({_MONTHS})\b", "#", question.lower())
    q = re.sub(r"\d+([.,:]\d+)*(st|nd|rd|th|am|pm|k|m|%)?", "#", q)
    q = re.sub(r"\b(am|pm|et|utc)\b", "", q)
    return re.sub(r"[#\s\-\u2013/,$]+", " ", q).strip()


def recurring_templates(questions, min_count=100):
    """Templates shared by at least min_count markets: machine-generated recurring series (crypto up/down,
    price and temperature ladders, ...). Uses question text only, never outcomes or prices."""
    return {t for t, n in Counter(map(template, questions)).items() if n >= min_count}


def measure_time(end, closed, h):
    """Non-anticipating measuring time: h before the scheduled end, if the market was still open then; else None.
    Whether a market is open at a fixed time is known at that time, so prices measured this way stay calibrated
    for an efficient market. Anchoring on the actual close or on the moment prices settle looks into the future."""
    t = end - h
    return t if closed > t else None


def resolution_time(ts, px, close, hi=0.97, lo=0.03):
    """When prices show the outcome was known: the start of the final run of prices at or beyond hi (or at or
    below lo, on the same side as the last price) that lasts to the end of the history; capped by the close
    time and the last recorded price. If the last price is not extreme, the close (or last price) time."""
    end = min(close, ts[-1]) if len(ts) else close
    if not len(px) or lo < px[-1] < hi:
        return end
    up, k = px[-1] >= hi, len(px)
    while k > 0 and ((px[k - 1] >= hi) if up else (px[k - 1] <= lo)):
        k -= 1
    return min(end, ts[k])


def price_at(ts, px, t, max_stale=DAY):
    """Last price at or before t, if recorded within max_stale seconds; else None. ts ascending."""
    i = int(np.searchsorted(ts, t, side="right")) - 1
    if i < 0 or t - ts[i] > max_stale:
        return None
    return float(px[i])


class Client:
    """requests session with a minimum spacing between calls and bounded exponential backoff on errors."""

    def __init__(self, min_interval=0.2, retries=6, timeout=30):
        self.s, self.min_interval, self.retries, self.timeout, self.last = requests.Session(), min_interval, retries, timeout, 0.0

    def call(self, method, url, **kw):
        for k in range(self.retries):
            wait = self.min_interval - (time.monotonic() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.monotonic()
            try:
                r = self.s.request(method, url, timeout=self.timeout, **kw)
                if r.status_code == 200:
                    return r.json()
                if r.status_code < 500 and r.status_code != 429:
                    r.raise_for_status()
            except (requests.ConnectionError, requests.Timeout):
                pass
            time.sleep(min(60, 2 ** k))
        raise RuntimeError(f"{method} {url} failed after {self.retries} tries")

    def market_pages(self, cursor=None, **params):
        """Iterate Gamma market pages (keyset pagination) as (markets, next_cursor); next_cursor None at the end."""
        params = {"limit": 100, **params}
        while True:
            if cursor:
                params["after_cursor"] = cursor
            d = self.call("GET", f"{GAMMA}/markets/keyset", params=params)
            cursor = d.get("next_cursor")
            yield d.get("markets") or [], cursor
            if not cursor:
                return

    def price_history(self, token_id, bucket=10800):
        """Full price history at 3-hour buckets (permanent per docs). Returns (timestamps, prices) arrays."""
        d = self.call("GET", f"{DATA}/v2/prices-history",
                      params={"token_id": token_id, "interval": "max", "bucket_seconds": bucket})
        pts = d.get("data") or []
        return np.array([x["timestamp"] for x in pts], float), np.array([x["price"] for x in pts], float)

    def books(self, token_ids):
        return self.call("POST", f"{CLOB}/books", json=[{"token_id": t} for t in token_ids])
