"""Calibration curves (7 days before close, main sample) from results/calibration_bins_7d.csv -> calibration.png"""
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INK, MUTED, GRID, BLUE = "#0b0b0b", "#52514e", "#d9d8d4", "#2a78d6"

b = pd.read_csv(os.path.join(ROOT, "results", "calibration_bins_7d.csv"))
cats = ["all"] + [c for c in ("politics", "sports", "crypto", "economics", "weather", "other") if c in set(b.category)]
fig, axes = plt.subplots(2, 4, figsize=(13, 6.6), sharex=True, sharey=True)
for ax in axes.flat[len(cats):]:
    ax.axis("off")
for ax, cat in zip(axes.flat, cats):
    d = b[(b.category == cat) & (b.n > 0)]
    ax.plot([0, 1], [0, 1], color=MUTED, lw=1, ls=(0, (3, 3)), zorder=1)
    ax.vlines(d.mean_price, d.wilson_lo, d.wilson_hi, color=BLUE, lw=2, alpha=0.45, zorder=2)
    ax.scatter(d.mean_price, d.freq, s=34, color=BLUE, edgecolor="white", linewidth=1.5, zorder=3)
    ax.set_title(f"{cat}  (n = {int(d.n.sum()):,})", fontsize=11, color=INK, loc="left")
    ax.grid(color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
for ax in axes[1]:
    ax.set_xlabel("price 7 days before close", color=MUTED, fontsize=9)
for ax in axes[:, 0]:
    ax.set_ylabel("share that resolved YES", color=MUTED, fontsize=9)
fig.suptitle("Polymarket calibration: price vs. outcome (10 price bins, 95% Wilson intervals; dashed = perfect)",
             x=0.01, ha="left", fontsize=12, color=INK)
fig.tight_layout()
fig.savefig(os.path.join(ROOT, "calibration.png"), dpi=150, facecolor="white")
