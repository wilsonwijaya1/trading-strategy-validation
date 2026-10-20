"""Performance metrics. Everything that can be expressed in R is expressed in R.

R-multiple = trade P&L / initial risk (units * stop distance). A full stop-out
is therefore about -1R (slightly worse because of slippage and costs).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def win_rate(r: np.ndarray) -> float:
    r = np.asarray(r, float)
    return float((r > 0).mean()) if r.size else float("nan")


def expectancy_r(r: np.ndarray) -> float:
    r = np.asarray(r, float)
    return float(r.mean()) if r.size else float("nan")


def profit_factor(pnl: np.ndarray) -> float:
    pnl = np.asarray(pnl, float)
    gains = pnl[pnl > 0].sum()
    losses = -pnl[pnl < 0].sum()
    if losses == 0:
        return float("inf") if gains > 0 else float("nan")
    return float(gains / losses)


def payoff_ratio(r: np.ndarray) -> float:
    """Average win / |average loss| (both in R)."""
    r = np.asarray(r, float)
    w, l = r[r > 0], r[r <= 0]
    if not len(w) or not len(l) or l.mean() == 0:
        return float("nan")
    return float(w.mean() / -l.mean())


def breakeven_win_rate(avg_rr: float) -> float:
    """Win rate needed to break even when winners pay ``avg_rr`` R and losers cost 1R."""
    return 1.0 / (1.0 + avg_rr)


def drawdown_series(equity: pd.Series | np.ndarray) -> np.ndarray:
    e = np.asarray(equity, float)
    peak = np.maximum.accumulate(e)
    return e / peak - 1.0


def max_drawdown(equity: pd.Series | np.ndarray) -> float:
    """Maximum peak-to-trough decline as a positive fraction (0.15 = 15 %)."""
    e = np.asarray(equity, float)
    if e.size == 0:
        return float("nan")
    return float(-drawdown_series(e).min())


def cagr(equity: pd.Series) -> float:
    if len(equity) < 2:
        return float("nan")
    years = (equity.index[-1] - equity.index[0]).total_seconds() / (365.25 * 86400)
    if years <= 0 or equity.iloc[0] <= 0 or equity.iloc[-1] <= 0:
        return float("nan")
    return float((equity.iloc[-1] / equity.iloc[0]) ** (1.0 / years) - 1.0)


def daily_returns(equity: pd.Series) -> pd.Series:
    e = equity.copy()
    if e.index.tz is not None:
        e.index = e.index.tz_convert("UTC").tz_localize(None)
    return e.resample("1D").last().dropna().pct_change().dropna()


def sharpe(equity: pd.Series, periods: int = 252) -> float:
    """Annualised Sharpe ratio of daily equity returns (risk-free = 0)."""
    r = daily_returns(equity)  # flat days are kept: they are real exposure-free days
    if len(r) < 2 or r.std(ddof=1) == 0:
        return float("nan")
    return float(r.mean() / r.std(ddof=1) * math.sqrt(periods))


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95 % Wilson score interval for a proportion (good for small samples)."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, centre - half), min(1.0, centre + half))


def bootstrap_mean_ci(r: np.ndarray, n_boot: int = 10_000, alpha: float = 0.05, seed: int = 7) -> tuple[float, float]:
    r = np.asarray(r, float)
    if r.size < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    means = rng.choice(r, size=(n_boot, r.size), replace=True).mean(axis=1)
    return (float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2)))


def t_test_mean_gt_zero(r: np.ndarray) -> float:
    """One-sided p-value for H0: mean R <= 0 (Student t)."""
    r = np.asarray(r, float)
    if r.size < 3 or r.std(ddof=1) == 0:
        return float("nan")
    from scipy import stats

    t = r.mean() / (r.std(ddof=1) / math.sqrt(r.size))
    return float(stats.t.sf(t, df=r.size - 1))


def summarize(trades: pd.DataFrame, equity: pd.Series | None = None) -> dict:
    """Summary dictionary for a backtest (trades from ``run_backtest``)."""
    n = len(trades)
    r = trades["r_multiple"].to_numpy(float) if n else np.array([])
    pnl = trades["pnl"].to_numpy(float) if n else np.array([])
    out: dict = {
        "trades": n,
        "long_trades": int((trades["direction"] == 1).sum()) if n else 0,
        "short_trades": int((trades["direction"] == -1).sum()) if n else 0,
        "win_rate": win_rate(r),
        "expectancy_r": expectancy_r(r),
        "avg_win_r": float(r[r > 0].mean()) if (r > 0).any() else float("nan"),
        "avg_loss_r": float(r[r <= 0].mean()) if (r <= 0).any() else float("nan"),
        "payoff": payoff_ratio(r),
        "profit_factor": profit_factor(pnl),
        "total_r": float(r.sum()) if n else 0.0,
        "mae_r_mean": float(trades["mae_r"].mean()) if n else float("nan"),
        "mfe_r_mean": float(trades["mfe_r"].mean()) if n else float("nan"),
        "bars_held_mean": float(trades["bars_held"].mean()) if n else float("nan"),
        "p_value_mean_r_gt_0": t_test_mean_gt_zero(r),
    }
    lo, hi = bootstrap_mean_ci(r) if n >= 2 else (float("nan"), float("nan"))
    out["expectancy_ci_low"], out["expectancy_ci_high"] = lo, hi
    if equity is not None and len(equity) > 1:
        out.update({
            "start": str(equity.index[0]), "end": str(equity.index[-1]),
            "final_equity": float(equity.iloc[-1]),
            "total_return": float(equity.iloc[-1] / equity.iloc[0] - 1),
            "cagr": cagr(equity), "max_dd": max_drawdown(equity), "sharpe": sharpe(equity),
        })
    return out


def equity_from_r(r: np.ndarray, risk_pct: float = 1.0, start: float = 1.0) -> np.ndarray:
    """Compounded equity path when each trade risks ``risk_pct`` % of equity."""
    r = np.asarray(r, float)
    return start * np.concatenate([[1.0], np.cumprod(1.0 + r * risk_pct / 100.0)])
