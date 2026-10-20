"""Small helpers to render markdown tables and numbers for the reports."""
from __future__ import annotations

import math
from typing import Callable

import pandas as pd


def is_num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def pct(x, d: int = 1) -> str:
    return f"{x * 100:.{d}f}%" if is_num(x) else "n/a"


def rr(x, d: int = 2) -> str:
    return f"{x:+.{d}f}R" if is_num(x) else "n/a"


def num(x, d: int = 2) -> str:
    if isinstance(x, (int,)) and not isinstance(x, bool):
        return f"{x:,}"
    if is_num(x):
        return "inf" if x == float("inf") else f"{x:,.{d}f}"
    return "n/a"


def pval(x) -> str:
    return f"{x:.3f}" if is_num(x) else "n/a"


def md_table(df: pd.DataFrame, fmt: dict[str, Callable] | None = None) -> str:
    fmt = fmt or {}
    cols = list(df.columns)
    lines = ["| " + " | ".join(str(c) for c in cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for _, row in df.iterrows():
        cells = []
        for c in cols:
            v = row[c]
            if c in fmt:
                cells.append(fmt[c](v))
            elif isinstance(v, float):
                cells.append(num(v))
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)
