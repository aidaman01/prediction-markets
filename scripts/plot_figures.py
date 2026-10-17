"""All README figures, drawn only from results/*.csv (the same run as the README tables).

  python scripts/plot_figures.py
    calibration.png         calibration small multiples by category (categories with >= min_events events)
    longshot_by_volume.png  longshot overpricing (<= 10 cents) by volume bucket, +-1 SE
    lookahead_trap.png      simulated efficient markets: slope b for the three measuring rules, +-1 SE, true b = 1
    longshot_rule_oos.png   hypothetical longshot-selling rule, cumulative P&L on the test half
"""
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pm.config import CFG

RES = os.path.join(ROOT, "results")
INK, MUTED, GRID, BLUE, ORANGE = "#0b0b0b", "#52514e", "#d9d8d4", "#2a78d6", "#eb6834"
H = CFG["measure"]["primary_horizon"].replace("d", " days")


def style(ax):
    ax.grid(color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9)


def title(fig, text):
    fig.suptitle(text, x=0.01, ha="left", fontsize=12, color=INK)


def save(fig, name):
    fig.tight_layout()
    fig.savefig(os.path.join(ROOT, name), dpi=150, facecolor="white")
    plt.close(fig)


def calibration():
    b = pd.read_csv(os.path.join(RES, "calibration_bins_7d.csv"))
    order = ["all", "politics", "sports", "crypto", "economics", "weather", "recurring", "other"]
    cats = [c for c in order if c in set(b.category) and b[b.category == c].events.iloc[0] >= CFG["analysis"]["min_events"]]
    fig, axes = plt.subplots(2, 4, figsize=(13, 6.6), sharex=True, sharey=True)
    for ax in axes.flat[len(cats):]:
        ax.axis("off")
    for ax, cat in zip(axes.flat, cats):
        d = b[(b.category == cat) & (b.n > 0)]
        ax.plot([0, 1], [0, 1], color=MUTED, lw=1, ls=(0, (3, 3)), zorder=1)
        ax.vlines(d.mean_price, d.wilson_lo, d.wilson_hi, color=BLUE, lw=2, alpha=0.45, zorder=2)
        ax.scatter(d.mean_price, d.freq, s=34, color=BLUE, edgecolor="white", linewidth=1.5, zorder=3)
        ax.set_title(f"{cat}  (n = {int(d.n.sum()):,})", fontsize=11, color=INK, loc="left")
        style(ax)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
    for ax in axes[1]:
        ax.set_xlabel(f"price {H} before scheduled end", color=MUTED, fontsize=9)
    for ax in axes[:, 0]:
        ax.set_ylabel("share that resolved YES", color=MUTED, fontsize=9)
    title(fig, f"Polymarket calibration, {H} before the scheduled end (stratified sample; 10 price bins, 95% Wilson "
               "intervals; dashed = perfect)")
    save(fig, "calibration.png")


def longshot_by_volume():
    d = pd.read_csv(os.path.join(RES, "longshot_by_volume.csv"))
    lab = lambda v: f"\\${v / 1000:.0f}k" if v < float("inf") else ""          # \$: not mathtext
    names = [f"{lab(lo)}-{lab(hi)}" if hi < float("inf") else f"{lab(lo)}+" for lo, hi in zip(d.volume_lo, d.volume_hi)]
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    x = range(len(d))
    ax.axhline(0, color=MUTED, lw=1)
    ax.errorbar(x, d.overpricing * 100, yerr=d.se * 100, fmt="o", color=BLUE, ms=8, mec="white", mew=1.5,
                elinewidth=2, ecolor=BLUE, capsize=0)
    for i, r in d.iterrows():
        ax.annotate(f"{r.overpricing * 100:+.2f}c\nn = {int(r.n):,}", (i, r.overpricing * 100), xytext=(12, 0),
                    textcoords="offset points", va="center", fontsize=9, color=INK)
    ax.set_xticks(list(x), names)
    ax.set_xlim(-0.4, len(d) - 0.2)
    ax.set_xlabel("market lifetime volume", color=MUTED, fontsize=9)
    ax.set_ylabel("price - outcome, cents per contract", color=MUTED, fontsize=9)
    style(ax)
    title(fig, f"Longshot overpricing by volume: contracts <= 10 cents, {H} before end, +-1 SE")
    save(fig, "longshot_by_volume.png")


def lookahead_trap():
    d = pd.read_csv(os.path.join(RES, "lookahead_simulation.csv")).set_index("rule").loc[["close", "resolution", "scheduled"]]
    names = ["h before actual close\n(pre-registered)", "h before prices settle", "h before scheduled end,\nif still open"]
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    ax.axhline(1, color=MUTED, lw=1, ls=(0, (3, 3)))
    ax.annotate("true b = 1", (-0.35, 1), xytext=(0, 4), textcoords="offset points", va="bottom", fontsize=9,
                color=MUTED)
    ax.errorbar(range(3), d.b, yerr=d.se_b, fmt="o", color=BLUE, ms=8, mec="white", mew=1.5, elinewidth=2, capsize=0)
    for i, (_, r) in enumerate(d.iterrows()):
        ax.annotate(f"b = {r.b:.2f}", (i, r.b), xytext=(12, -12 if r.b < 1 else 0), textcoords="offset points",
                    va="center", fontsize=9, color=INK)
    ax.set_xticks(range(3), names)
    ax.set_xlim(-0.4, 2.7)
    ax.set_ylim(0, max(d.b) * 1.15)
    ax.set_ylabel("estimated slope b (+-1 SE, smaller than the dots)", color=MUTED, fontsize=9)
    style(ax)
    c = CFG["simulation"]
    title(fig, f"Look-ahead trap: {c['markets']:,} simulated efficient markets, h = {c['horizon_days']} days")
    save(fig, "lookahead_trap.png")


def longshot_rule():
    d = pd.read_csv(os.path.join(RES, "longshot_rule_test_pnl.csv"))
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    ax.axhline(0, color=MUTED, lw=1)
    for (costs, g), color in zip(d.groupby("costs", sort=True), (BLUE, ORANGE)):
        ax.plot(g.bet, g.cum_pnl, color=color, lw=2, label=f"{costs} costs")
        ax.annotate(f"{costs}: {g.cum_pnl.iloc[-1]:+.2f}", (g.bet.iloc[-1], g.cum_pnl.iloc[-1]), xytext=(6, 0),
                    textcoords="offset points", ha="left", va="center", fontsize=9, color=INK)
    ax.set_xlim(0, d.bet.max() * 1.12)
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    ax.set_xlabel("bets on the test half, in order of scheduled end (1 contract each)", color=MUTED, fontsize=9)
    ax.set_ylabel("cumulative P&L, $", color=MUTED, fontsize=9)
    style(ax)
    r = pd.read_csv(os.path.join(RES, "longshot_rule.csv"))
    x = r[r.half.str.startswith("newer")].X.iloc[0]
    title(fig, f"HYPOTHETICAL: sell longshots at or below {x * 100:.0f} cents, out-of-sample half, no trades placed")
    save(fig, "longshot_rule_oos.png")


if __name__ == "__main__":
    calibration()
    longshot_by_volume()
    lookahead_trap()
    longshot_rule()
