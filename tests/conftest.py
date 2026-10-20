import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture
def random_walk() -> pd.DataFrame:
    """Synthetic OHLC random walk (deterministic) for causality tests."""
    rng = np.random.default_rng(0)
    n = 600
    close = 1800 + np.cumsum(rng.normal(0, 5, n))
    open_ = np.concatenate([[close[0]], close[:-1]]) + rng.normal(0, 1, n)
    high = np.maximum(open_, close) + rng.uniform(0, 4, n)
    low = np.minimum(open_, close) - rng.uniform(0, 4, n)
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": 0.0}, index=idx)


def make_bars(rows, start="2024-01-01", freq="h"):
    """rows: list of (open, high, low, close) tuples."""
    idx = pd.date_range(start, periods=len(rows), freq=freq)
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx, dtype=float)


def make_sig(df, signals: dict, sl=2.0, tp=2.0, trail=np.nan):
    s = pd.DataFrame(index=df.index)
    sig = np.zeros(len(df), dtype=int)
    for i, v in signals.items():
        sig[i] = v
    s["signal"] = sig
    s["sl_dist"] = float(sl)
    s["tp_dist"] = float(tp)
    s["trail_dist"] = float(trail)
    return s
