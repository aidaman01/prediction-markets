"""Arbitrage detection on order books: walk the asks, add fees, compare with the guaranteed payout.

A basket is a set of legs bought in equal quantity q that pays `payout` per unit whatever happens:
  YES + NO of one binary market: payout 1;  YES on every outcome of an exhaustive event: payout 1;
  NO on every one of n outcomes: payout n - 1;  YES on one venue + NO on the other (same event): payout 1.
Each leg is (asks, cost) with asks [(price, size), ...] and cost(fills) -> (cash_out, fee) from pm.fees.
Marginal cost of a leg rises with q (asks ascend, fee per share p + r p(1-p) rises with p), so profit is concave
and piecewise linear in q: its maximum sits at a depth breakpoint of one of the legs.
"""
from decimal import Decimal

from pm.fees import kalshi_buy_cash, polymarket_buy_cash

D = Decimal


def _d(x):
    return x if isinstance(x, Decimal) else D(str(x))


def sorted_asks(levels):
    return sorted(((_d(p), _d(s)) for p, s in levels if _d(s) > 0), key=lambda l: l[0])


def walk(asks, qty):
    """Fills [(price, size)] to buy qty from ascending asks, or None if the book is too thin."""
    left, fills = _d(qty), []
    for p, s in asks:
        if left <= 0:
            break
        take = min(s, left)
        fills.append((p, take))
        left -= take
    return fills if left <= 0 else None


def basket_profit(legs, q, payout):
    """Net profit of buying q of every leg; None if any book is too thin."""
    q, cash = _d(q), D(0)
    for asks, cost in legs:
        fills = walk(asks, q)
        if fills is None:
            return None
        cash += cost(fills)[0]
    return q * _d(payout) - cash


def best_basket(legs, payout, min_qty=1):
    """(edge at min_qty, best q, best profit). Profit is evaluated at min_qty and every depth breakpoint."""
    depth = min(sum(s for _, s in asks) for asks, _ in legs)
    if depth < _d(min_qty):
        return None, D(0), D(0)
    qs = {_d(min_qty), depth}
    for asks, _ in legs:
        cum = D(0)
        for _, s in asks:
            cum += s
            if _d(min_qty) <= cum <= depth:
                qs.add(cum)
    at_min = basket_profit(legs, min_qty, payout)
    best_q, best = D(0), D(0)
    for q in sorted(qs):
        pr = basket_profit(legs, q, payout)
        if pr is not None and pr > best:
            best_q, best = q, pr
    return at_min, best_q, best


def pm_leg(asks, rate=0, exponent=1):
    return sorted_asks(asks), lambda f: polymarket_buy_cash(f, rate, exponent)


def kalshi_leg(asks, multiplier="0.07"):
    return sorted_asks(asks), lambda f: kalshi_buy_cash(f, multiplier)


def kalshi_asks(orderbook_fp):
    """Kalshi books list bids only. YES asks come from NO bids at 1 - price, and vice versa."""
    flip = lambda bids: sorted_asks((D(1) - _d(p), s) for p, s in bids or [])
    return {"yes": flip(orderbook_fp.get("no_dollars")), "no": flip(orderbook_fp.get("yes_dollars"))}


def episodes(times, flags, max_gap):
    """Runs of consecutive True snapshots. A gap longer than max_gap between snapshots breaks a run.

    Returns [(start, end, n, lower, upper)]: lower = end - start is the observed span; upper = time from the last
    False snapshot before the run to the first False after it (None when the run touches a gap or the series edge).
    The true duration lies in [lower, upper]."""
    out, i, n = [], 0, len(times)
    while i < n:
        if not flags[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and flags[j + 1] and times[j + 1] - times[j] <= max_gap:
            j += 1
        before = i > 0 and not flags[i - 1] and times[i] - times[i - 1] <= max_gap
        after = j + 1 < n and not flags[j + 1] and times[j + 1] - times[j] <= max_gap
        upper = times[j + 1] - times[i - 1] if before and after else None
        out.append((times[i], times[j], j - i + 1, times[j] - times[i], upper))
        i = j + 1
    return out


def basket_cost(legs, q):
    """Cash to buy q of every leg, or None if a book is too thin."""
    cash = D(0)
    for asks, cost in legs:
        fills = walk(asks, q)
        if fills is None:
            return None
        cash += cost(fills)[0]
    return cash


def at_budget(legs, payout, budget, step=D("0.01")):
    """Deploy up to `budget` dollars: the largest q (on a 0.01 grid) whose cost fits. Returns (q, cost, profit),
    or None if the books are too thin to spend the whole budget (capacity below budget)."""
    budget = _d(budget)
    depth = min(sum(s for _, s in asks) for asks, _ in legs)
    full = basket_cost(legs, depth)
    if full is None or full < budget:
        return None
    lo, hi = D(0), depth                              # cost is increasing in q: bisect
    while hi - lo > step:
        mid = ((lo + hi) / 2).quantize(step)
        if mid in (lo, hi):
            break
        lo, hi = (mid, hi) if basket_cost(legs, mid) <= budget else (lo, mid)
    cost = basket_cost(legs, lo)
    return lo, cost, lo * _d(payout) - cost


def annualized(profit, cost, days):
    """Simple annualized return to resolution: profit / cost * 365 / days."""
    return float(profit) / float(cost) * 365 / days


def tbill_yield(discount_pct, days=91):
    """FRED DTB3 is a discount-basis rate in percent; its simple (bond-equivalent) yield, as a fraction."""
    d = discount_pct / 100
    return 365 * d / (360 - d * days)


def book_problems(book, snapshot_t, max_ahead=120):
    """Sanity checks on a compact book [book_ms, bids best-first, asks best-first]. Empty list = book is usable.
    book_ms is the time of the book's last change (an untouched book can be hours old and still current), so the
    clock check only rejects a book stamped after the snapshot window."""
    ms, bids, asks = book
    out = []
    levels = [(float(p), float(s)) for p, s in bids + asks]
    if any(not 0 < p < 1 for p, _ in levels):
        out.append("price outside (0, 1)")
    if any(s <= 0 for _, s in levels):
        out.append("non-positive size")
    bp, ap = [float(p) for p, _ in bids], [float(p) for p, _ in asks]
    if bp != sorted(bp, reverse=True) or ap != sorted(ap) or len(set(bp)) < len(bp) or len(set(ap)) < len(ap):
        out.append("levels out of order or duplicated")
    if bp and ap and bp[0] >= ap[0]:
        out.append("crossed book")
    if ms and ms / 1000 > snapshot_t + max_ahead:
        out.append("timestamp after snapshot")
    return out


def reachable(times, flags, max_gap):
    """A gap counts only if it is still there in the next snapshot (taken within max_gap seconds): a trader who
    reacts one snapshot later could still have taken it."""
    return [bool(f and i + 1 < len(times) and flags[i + 1] and times[i + 1] - times[i] <= max_gap)
            for i, f in enumerate(flags)]
