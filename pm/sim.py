"""Simulated markets with known answers, shared by the tests and scripts/simulate_lookahead.py."""
import numpy as np

from pm.calib import recalibration
from pm.data import DAY, measure_time, price_at, resolution_time


def simulate(n_events, rng, slope=1.0):
    """Events of 1-8 exclusive outcomes. Prices on [0.01, 0.99]; truth = logistic(slope * logit(price))."""
    p, y, ev = [], [], []
    for e in range(n_events):
        k = rng.integers(1, 9)
        if k == 1:
            pr = rng.uniform(0.01, 0.99, 1)
        else:
            pr = 0.01 + (1 - 0.01 * k) * rng.dirichlet(np.ones(k))
        lg = np.log(pr / (1 - pr))
        q = 1 / (1 + np.exp(-slope * lg))
        if k == 1:
            out = (rng.random(1) < q).astype(float)
        else:
            out = np.zeros(k)
            out[rng.choice(k, p=q / q.sum())] = 1           # exactly one winner per event
        p += list(pr); y += list(out); ev += [e] * k
    return np.array(p), np.array(y), np.array(ev)


def simulate_by_date(n, rng, E=60 * DAY, lag=2 * DAY):
    """Efficient 'will it happen by day 60' markets: hazard lam, price = P(event before E | none yet), calibrated at
    every fixed time. The event sends the price to 0.999 and the market closes `lag` later; with no event it
    decays to 0.001 and closes at E."""
    grid = np.arange(0, E + lag + 1, 10800.0)
    for _ in range(n):
        p0 = rng.uniform(0.05, 0.95)
        lam = -np.log(1 - p0) / E
        tau = rng.exponential(1 / lam)
        y = tau < E
        closed = tau + lag if y else E
        ts = grid[grid <= closed]
        px = np.clip(np.where(ts < min(tau, E), 1 - np.exp(-lam * np.clip(E - ts, 0, None)), float(y)), 0.001, 0.999)
        yield ts, px, E, closed, float(y)


def lookahead_slopes(n, seed, h=7 * DAY):
    """Fit the recalibration slope on simulated efficient markets for the three measuring rules: h before the
    actual close ("close"), h before prices settle ("resolution"), h before the scheduled end if still open
    ("scheduled"). True slope is 1 for every fixed-time measurement."""
    rng = np.random.default_rng(seed)
    obs = {"close": ([], []), "resolution": ([], []), "scheduled": ([], [])}
    for ts, px, end, closed, y in simulate_by_date(n, rng):
        T = min(end, closed)
        for k, t in (("close", T - h), ("resolution", resolution_time(ts, px, T) - h),
                     ("scheduled", measure_time(end, closed, h))):
            p = price_at(ts, px, t) if t is not None and t >= 0 else None
            if p is not None:
                obs[k][0].append(p)
                obs[k][1].append(y)
    return {k: recalibration(np.array(p), np.array(y), np.arange(len(p))) for k, (p, y) in obs.items()}
