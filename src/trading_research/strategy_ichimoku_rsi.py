"""Ichimoku + RSI-Delta strategy, reconstructed from the TPW08 documents.

Rules taken from the documents (UTS report, section 3.2; UAS proposal 3.2)
-------------------------------------------------------------------------
* Instrument XAUUSD, original timeframe M15, backtest window 2024-2026.
* Ichimoku parameters "optimised" to (12, 30, 60).
* Long only when price is ABOVE the Kumo, short only when BELOW the Kumo.
* Entry trigger: Tenkan-sen crosses Kijun-sen (up for long, down for short).
* Momentum filter: RSI(14); ``RSI_t - RSI_{t-1} > threshold`` (example: 5).
  For shorts we use the mirror condition ``RSI_t - RSI_{t-1} < -threshold``.
* Risk: 1 % of equity per trade (dynamic position sizing).
* Optimisation proposal: ATR trailing stop ``stop = price - k * ATR``.

Assumptions we had to add (NOT specified in the documents)
----------------------------------------------------------
* Initial stop loss = ``sl_atr * ATR(14)`` from the entry price (default 1.5).
* Take profit = ``tp_r`` times the stop distance (default 1.0R). A 65 % win
  rate together with profit factor 1.85 implies average win / average loss
  of about 1.85 * 0.35 / 0.65 = 1.0, so 1R is the payoff consistent with
  the claimed statistics.
* The cross and the RSI-delta condition must occur on the same bar
  (``cross_window = 1``); a looser window is available as a parameter.
* Signals are evaluated on the bar close; orders fill at the NEXT bar open.
* One position at a time; new signals are ignored while a trade is open;
  opposite signals do not close the position (only SL / TP / trailing stop).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace

import numpy as np
import pandas as pd

from .indicators import atr, ichimoku, rsi


@dataclass(frozen=True)
class StrategyParams:
    tenkan: int = 12
    kijun: int = 30
    senkou: int = 60
    displacement: int | None = None  # None -> kijun
    rsi_period: int = 14
    rsi_delta: float = 5.0
    cross_window: int = 1
    atr_period: int = 14
    atr_method: str = "sma"
    sl_atr: float = 1.5
    tp_r: float | None = 1.0  # None -> no fixed TP
    trail_atr: float | None = None  # None -> no trailing stop
    allow_long: bool = True
    allow_short: bool = True

    def with_(self, **kw) -> "StrategyParams":
        return replace(self, **kw)

    def to_dict(self) -> dict:
        return asdict(self)

    def label(self) -> str:
        s = f"ichi({self.tenkan},{self.kijun},{self.senkou}) dRSI>{self.rsi_delta:g} SL{self.sl_atr:g}ATR"
        s += f" TP{self.tp_r:g}R" if self.tp_r else " noTP"
        if self.trail_atr:
            s += f" trail{self.trail_atr:g}ATR"
        if self.cross_window > 1:
            s += f" win{self.cross_window}"
        return s


TPW08_PARAMS = StrategyParams()  # 12/30/60, RSI14 delta>5, SL 1.5 ATR, TP 1R
CLASSIC_PARAMS = StrategyParams(tenkan=9, kijun=26, senkou=52)


def compute_indicators(df: pd.DataFrame, p: StrategyParams) -> pd.DataFrame:
    ich = ichimoku(df["high"], df["low"], p.tenkan, p.kijun, p.senkou, p.displacement)
    out = ich.copy()
    out["rsi"] = rsi(df["close"], p.rsi_period)
    out["rsi_delta"] = out["rsi"].diff()
    out["atr"] = atr(df["high"], df["low"], df["close"], p.atr_period, p.atr_method)
    return out


def generate_signals(df: pd.DataFrame, p: StrategyParams = TPW08_PARAMS) -> pd.DataFrame:
    """Return a frame aligned with ``df`` holding the signal and exit distances.

    Columns
    -------
    signal      +1 long, -1 short, 0 none (decided on the close of the bar)
    sl_dist     initial stop distance in price units (defined on every bar)
    tp_dist     take-profit distance (NaN = no TP)
    trail_dist  trailing-stop distance (NaN = no trailing)
    plus all indicator columns for inspection.
    """
    ind = compute_indicators(df, p)
    close = df["close"]
    tk, kj = ind["tenkan"], ind["kijun"]
    diff = tk - kj
    prev = diff.shift(1)
    cross_up = (diff > 0) & (prev <= 0)
    cross_dn = (diff < 0) & (prev >= 0)
    if p.cross_window > 1:
        cross_up = cross_up.astype(float).rolling(p.cross_window, min_periods=1).max().astype(bool) & (diff > 0)
        cross_dn = cross_dn.astype(float).rolling(p.cross_window, min_periods=1).max().astype(bool) & (diff < 0)

    above = close > ind["cloud_top"]
    below = close < ind["cloud_bottom"]
    mom_up = ind["rsi_delta"] > p.rsi_delta
    mom_dn = ind["rsi_delta"] < -p.rsi_delta

    long_sig = cross_up & above & mom_up & p.allow_long
    short_sig = cross_dn & below & mom_dn & p.allow_short
    sig = np.where(long_sig, 1, np.where(short_sig, -1, 0))

    out = ind.copy()
    out["signal"] = sig.astype(int)
    out["sl_dist"] = p.sl_atr * ind["atr"]
    out["tp_dist"] = out["sl_dist"] * p.tp_r if p.tp_r else np.nan
    out["trail_dist"] = p.trail_atr * ind["atr"] if p.trail_atr else np.nan
    # never trade before all indicators are warmed up
    warm = ind[["cloud_top", "rsi_delta", "atr"]].notna().all(axis=1)
    out.loc[~warm, "signal"] = 0
    return out
