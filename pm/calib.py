"""Calibration and favorite-longshot statistics with event-clustered inference."""
import math

import numpy as np

EPS = 0.001          # smallest Polymarket tick; prices of exactly 0 or 1 are clipped to it before taking logits


def brier(p, y):
    p, y = np.asarray(p, float), np.asarray(y, float)
    return float(np.mean((p - y) ** 2))


def wilson(k, n, z=1.959964):
    if n == 0:
        return math.nan, math.nan
    f = k / n
    c = (f + z * z / (2 * n)) / (1 + z * z / n)
    h = z * math.sqrt(f * (1 - f) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return c - h, c + h


def _bins(p, bins):
    return np.minimum((np.asarray(p, float) * bins).astype(int), bins - 1)


def calibration_table(p, y, bins=10):
    """Rows (lo, hi, n, mean price, observed frequency, wilson lo, wilson hi) for equal-width price bins."""
    p, y = np.asarray(p, float), np.asarray(y, float)
    k, rows = _bins(p, bins), []
    for b in range(bins):
        m = k == b
        n = int(m.sum())
        lo, hi = wilson(float(y[m].sum()), n)
        rows.append((b / bins, (b + 1) / bins, n, float(p[m].mean()) if n else math.nan,
                     float(y[m].mean()) if n else math.nan, lo, hi))
    return rows


def murphy(p, y, bins=10):
    """Brier = reliability - resolution + uncertainty (exact when the price is constant within each bin)."""
    p, y = np.asarray(p, float), np.asarray(y, float)
    k, n, ob = _bins(p, bins), len(p), y.mean()
    rel = res = 0.0
    for b in np.unique(k):
        m = k == b
        rel += m.sum() * (p[m].mean() - y[m].mean()) ** 2
        res += m.sum() * (y[m].mean() - ob) ** 2
    return {"reliability": rel / n, "resolution": res / n, "uncertainty": ob * (1 - ob)}


def _cluster_meat(scores, clusters):
    """Sum over clusters of (sum of scores)(sum of scores)'. scores: n x k."""
    _, g = np.unique(clusters, return_inverse=True)
    s = np.zeros((g.max() + 1, scores.shape[1]))
    np.add.at(s, g, scores)
    return s.T @ s, len(s)


def recalibration(p, y, clusters):
    """Logistic fit logit P(y=1) = a + b logit(p) with event-clustered sandwich errors.

    Calibrated: a = 0, b = 1. b > 1: favorite-longshot bias (longshots overpriced). Returns a, b, their standard
    errors, the two-sided p-value of b = 1 and the joint Wald p-value of (a, b) = (0, 1)."""
    p, y = np.clip(np.asarray(p, float), EPS, 1 - EPS), np.asarray(y, float)
    X = np.column_stack([np.ones_like(p), np.log(p / (1 - p))])
    beta = np.array([0.0, 1.0])
    for _ in range(50):
        mu = 1 / (1 + np.exp(-X @ beta))
        H = X.T @ (X * (mu * (1 - mu))[:, None])
        step = np.linalg.solve(H, X.T @ (y - mu))
        beta += step
        if np.abs(step).max() < 1e-10:
            break
    mu = 1 / (1 + np.exp(-X @ beta))
    bread = np.linalg.inv(X.T @ (X * (mu * (1 - mu))[:, None]))
    meat, G = _cluster_meat(X * (y - mu)[:, None], clusters)
    V = G / (G - 1) * bread @ meat @ bread
    se = np.sqrt(np.diag(V))
    d = beta - np.array([0.0, 1.0])
    wald = float(d @ np.linalg.solve(V, d))
    return {"a": beta[0], "b": beta[1], "se_a": se[0], "se_b": se[1],
            "p_b1": math.erfc(abs(d[1] / se[1]) / math.sqrt(2)), "p_joint": math.exp(-wald / 2),
            "n": len(p), "clusters": G}


def longshot(p, y, clusters, cut=0.10):
    """Mean overpricing (price - outcome) of contracts priced <= cut, with an event-clustered standard error."""
    p, y, c = np.asarray(p, float), np.asarray(y, float), np.asarray(clusters)
    m = p <= cut
    d = p[m] - y[m]
    if len(d) < 2:
        return {"mean": math.nan, "se": math.nan, "n": int(len(d))}
    meat, G = _cluster_meat((d - d.mean())[:, None], c[m])
    return {"mean": float(d.mean()), "se": float(math.sqrt(G / (G - 1) * meat[0, 0]) / len(d)), "n": int(len(d)),
            "clusters": G}
