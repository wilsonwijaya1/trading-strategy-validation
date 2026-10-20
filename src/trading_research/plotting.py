"""Matplotlib helpers with a consistent, colour-blind-aware style.

Palette: validated categorical order (blue, orange, aqua) for series, a
blue <-> grey <-> red diverging map for signed values such as expectancy.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm  # noqa: E402

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
CRITICAL = "#d03b3b"
GOOD = "#0ca30c"

DIVERGING = LinearSegmentedColormap.from_list("red_grey_blue", ["#c43a3a", "#e79a92", "#f0efec", "#86b6ef", "#1c5cab"])


def setup_style() -> None:
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.edgecolor": AXIS, "axes.labelcolor": INK_2, "axes.titlecolor": INK,
        "axes.titlesize": 12, "axes.titleweight": "bold", "axes.labelsize": 10,
        "xtick.color": MUTED, "ytick.color": MUTED, "xtick.labelsize": 9, "ytick.labelsize": 9,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
        "axes.spines.top": False, "axes.spines.right": False, "lines.linewidth": 2.0,
        "legend.frameon": False, "legend.fontsize": 9, "font.family": ["Segoe UI", "DejaVu Sans"],
        "text.color": INK,
    })


def save(fig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=144)
    plt.close(fig)


def heatmap(ax, values: np.ndarray, counts: np.ndarray | None, xlabels, ylabels, title: str,
            xlabel: str, ylabel: str, vlim: float | None = None):
    v = np.array(values, dtype=float)
    lim = vlim if vlim is not None else max(0.05, np.nanmax(np.abs(v)) if np.isfinite(v).any() else 0.05)
    norm = TwoSlopeNorm(vmin=-lim, vcenter=0.0, vmax=lim)
    im = ax.imshow(np.ma.masked_invalid(v), cmap=DIVERGING, norm=norm, aspect="auto")
    ax.set_xticks(range(len(xlabels)), [str(x) for x in xlabels])
    ax.set_yticks(range(len(ylabels)), [str(y) for y in ylabels])
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(False)
    for i in range(v.shape[0]):
        for j in range(v.shape[1]):
            txt = "n/a" if not np.isfinite(v[i, j]) else f"{v[i, j]:+.2f}"
            if counts is not None:
                txt += f"\n(n={int(counts[i, j])})"
            ax.text(j, i, txt, ha="center", va="center", fontsize=7.5, color=INK)
    return im
