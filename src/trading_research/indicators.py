"""Technical indicators implemented from scratch (no TA-Lib dependency).

All indicators are *causal*: the value at bar ``t`` only uses data up to and
including bar ``t``. The Ichimoku cloud (Senkou A/B) is shifted *forward* by
``displacement`` bars, so the cloud value aligned with bar ``t`` was computed
from data available at ``t - displacement``. The Chikou span (close shifted
backwards) is intentionally NOT returned because using it as a signal at bar
``t`` is a classic lookahead bug.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(x: pd.Series, n: int) -> pd.Series:
    return x.rolling(n, min_periods=n).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI (same definition as MT5 / TradingView ``ta.rsi``).

    Seed: simple average of the first ``period`` gains/losses, then Wilder
    smoothing ``avg = (avg * (period - 1) + x) / period``. First valid value
    is at index ``period``.
    """
    c = np.asarray(close, dtype=float)
    n = len(c)
    out = np.full(n, np.nan)
    if n <= period:
        return pd.Series(out, index=close.index, name="rsi")
    if np.isnan(c).any():
        raise ValueError("rsi: close contains NaN")
    d = np.diff(c)
    gain = np.where(d > 0, d, 0.0)
    loss = np.where(d < 0, -d, 0.0)
    ag = gain[:period].mean()
    al = loss[:period].mean()

    def _val(ag: float, al: float) -> float:
        if al == 0.0:
            return 50.0 if ag == 0.0 else 100.0
        return 100.0 - 100.0 / (1.0 + ag / al)

    out[period] = _val(ag, al)
    for i in range(period + 1, n):
        ag = (ag * (period - 1) + gain[i - 1]) / period
        al = (al * (period - 1) + loss[i - 1]) / period
        out[i] = _val(ag, al)
    return pd.Series(out, index=close.index, name="rsi")


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """TR = max(H-L, |H-C_prev|, |L-C_prev|); first bar uses H-L."""
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    tr.iloc[0] = high.iloc[0] - low.iloc[0]
    return tr.rename("tr")


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14, method: str = "sma") -> pd.Series:
    """Average True Range.

    ``method="sma"`` matches the TPW08 proposal formula ``ATR = SMA(TR, n)``
    and MT5's built-in iATR. ``method="wilder"`` uses Wilder's RMA.
    """
    tr = true_range(high, low, close)
    if method == "sma":
        return sma(tr, period).rename("atr")
    if method == "wilder":
        v = tr.to_numpy(dtype=float)
        out = np.full(len(v), np.nan)
        if len(v) >= period:
            out[period - 1] = v[:period].mean()
            for i in range(period, len(v)):
                out[i] = (out[i - 1] * (period - 1) + v[i]) / period
        return pd.Series(out, index=tr.index, name="atr")
    raise ValueError(f"unknown ATR method {method!r}")


def donchian_mid(high: pd.Series, low: pd.Series, n: int) -> pd.Series:
    return (high.rolling(n, min_periods=n).max() + low.rolling(n, min_periods=n).min()) / 2.0


def ichimoku(
    high: pd.Series,
    low: pd.Series,
    tenkan: int = 9,
    kijun: int = 26,
    senkou: int = 52,
    displacement: int | None = None,
) -> pd.DataFrame:
    """Ichimoku Kinko Hyo lines aligned so that row ``t`` is causal.

    Returns columns: tenkan, kijun, senkou_a, senkou_b, cloud_top, cloud_bottom.
    ``displacement`` defaults to ``kijun`` (classic: 26 for 9/26/52).
    """
    disp = kijun if displacement is None else displacement
    t = donchian_mid(high, low, tenkan)
    k = donchian_mid(high, low, kijun)
    span_a_raw = (t + k) / 2.0
    span_b_raw = donchian_mid(high, low, senkou)
    a = span_a_raw.shift(disp)
    b = span_b_raw.shift(disp)
    out = pd.DataFrame(
        {
            "tenkan": t,
            "kijun": k,
            "senkou_a": a,
            "senkou_b": b,
        },
        index=high.index,
    )
    out["cloud_top"] = out[["senkou_a", "senkou_b"]].max(axis=1, skipna=False)
    out["cloud_bottom"] = out[["senkou_a", "senkou_b"]].min(axis=1, skipna=False)
    return out
