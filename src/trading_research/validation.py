"""Out-of-sample validation tools.

* ``split_is_oos``      chronological 70/30 split
* ``grid_search``       evaluate a parameter grid on one window
* ``walk_forward``      rolling optimise-on-train / trade-on-test
* ``monte_carlo_dd``    bootstrap trade R-multiples -> drawdown distribution
* ``random_entry_baseline``  same exits, random entries -> null distribution

Signals are always computed on the FULL history (indicators are causal, see
tests/test_no_lookahead.py) and the backtest is then run on a time slice. This
avoids losing a warm-up period at the start of every window without leaking
future information.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .backtest import BacktestConfig, BacktestResult, run_backtest
from .metrics import equity_from_r, max_drawdown, summarize
from .strategy_ichimoku_rsi import StrategyParams, generate_signals


def split_is_oos(index: pd.DatetimeIndex, is_frac: float = 0.7) -> pd.Timestamp:
    """Timestamp of the first out-of-sample bar (chronological split by bar count)."""
    k = int(len(index) * is_frac)
    return index[k]


def backtest_window(df: pd.DataFrame, sig: pd.DataFrame, start=None, end=None,
                    cfg: BacktestConfig = BacktestConfig()) -> BacktestResult:
    """Backtest on ``[start, end)``; ``sig`` was computed on the full history."""
    mask = np.ones(len(df), bool)
    if start is not None:
        mask &= df.index >= start
    if end is not None:
        mask &= df.index < end
    return run_backtest(df[mask], sig[mask], cfg)


def make_grid(base: StrategyParams, **axes) -> list[StrategyParams]:
    """Cartesian product of parameter axes on top of ``base``.

    If ``kijun`` is varied and ``senkou`` is not, senkou is set to 2 * kijun.
    """
    keys = list(axes)
    out = []
    for combo in itertools.product(*(axes[k] for k in keys)):
        kw = dict(zip(keys, combo))
        if "kijun" in kw and "senkou" not in kw:
            kw["senkou"] = 2 * kw["kijun"]
        out.append(base.with_(**kw))
    return out


def grid_search(df: pd.DataFrame, grid: list[StrategyParams], start=None, end=None,
                cfg: BacktestConfig = BacktestConfig(), signals_cache: dict | None = None) -> pd.DataFrame:
    rows = []
    cache = signals_cache if signals_cache is not None else {}
    for p in grid:
        if p not in cache:
            cache[p] = generate_signals(df, p)
        res = backtest_window(df, cache[p], start, end, cfg)
        s = summarize(res.trades, res.equity)
        rows.append({**p.to_dict(), **{k: s.get(k) for k in (
            "trades", "win_rate", "expectancy_r", "profit_factor", "max_dd", "cagr", "sharpe", "total_r")}, "params": p})
    return pd.DataFrame(rows)


def _score(row: pd.Series, objective: str, min_trades: int) -> float:
    if row["trades"] < min_trades or not np.isfinite(row[objective]):
        return -np.inf
    return float(row[objective])


@dataclass
class WalkForwardResult:
    windows: pd.DataFrame
    oos_trades: pd.DataFrame

    @property
    def oos_r(self) -> np.ndarray:
        return self.oos_trades["r_multiple"].to_numpy(float) if len(self.oos_trades) else np.array([])


def walk_forward(df: pd.DataFrame, grid: list[StrategyParams], train: pd.DateOffset, test: pd.DateOffset,
                 cfg: BacktestConfig = BacktestConfig(), objective: str = "expectancy_r",
                 min_trades: int = 10, signals_cache: dict | None = None) -> WalkForwardResult:
    """Rolling walk-forward: optimise on ``train``, trade the next ``test`` window, roll by ``test``."""
    cache = signals_cache if signals_cache is not None else {}
    for p in grid:
        if p not in cache:
            cache[p] = generate_signals(df, p)
    t0 = df.index[0]
    end_all = df.index[-1]
    rows, oos = [], []
    w = 0
    while True:
        tr_start = t0 + test * w
        tr_end = tr_start + train
        te_end = tr_end + test
        if tr_end >= end_all:
            break
        is_tab = grid_search(df, grid, tr_start, tr_end, cfg, cache)
        scores = is_tab.apply(lambda r: _score(r, objective, min_trades), axis=1)
        if np.isfinite(scores.max()):
            best = is_tab.loc[scores.idxmax()]
            p = best["params"]
            res = backtest_window(df, cache[p], tr_end, te_end, cfg)
            s = summarize(res.trades, res.equity)
            t = res.trades.copy()
            t["window"] = w
            oos.append(t)
            rows.append({"window": w, "train_start": tr_start, "train_end": tr_end, "test_end": min(te_end, end_all),
                         "chosen": p.label(), "is_trades": int(best["trades"]), "is_expectancy_r": best["expectancy_r"],
                         "oos_trades": s["trades"], "oos_expectancy_r": s["expectancy_r"],
                         "oos_win_rate": s["win_rate"], "oos_total_r": s["total_r"]})
        else:
            rows.append({"window": w, "train_start": tr_start, "train_end": tr_end, "test_end": min(te_end, end_all),
                         "chosen": "none (too few IS trades)", "is_trades": int(is_tab["trades"].max()),
                         "is_expectancy_r": np.nan, "oos_trades": 0, "oos_expectancy_r": np.nan,
                         "oos_win_rate": np.nan, "oos_total_r": 0.0})
        w += 1
        if te_end >= end_all:
            break
    trades = pd.concat(oos, ignore_index=True) if oos else pd.DataFrame()
    return WalkForwardResult(pd.DataFrame(rows), trades)


def monte_carlo_dd(r: np.ndarray, risk_pct: float = 1.0, n_sims: int = 10_000, n_trades: int | None = None,
                   seed: int = 42) -> dict:
    """Bootstrap (with replacement) the trade sequence and record max drawdown.

    Returns percentiles of the max-drawdown distribution (fractions) plus the
    probability that the resampled sequence ends below the start.
    """
    r = np.asarray(r, float)
    if r.size == 0:
        return {"n_trades": 0}
    m = n_trades or r.size
    rng = np.random.default_rng(seed)
    samples = rng.choice(r, size=(n_sims, m), replace=True)
    eq = np.cumprod(1.0 + samples * risk_pct / 100.0, axis=1)
    eq = np.concatenate([np.ones((n_sims, 1)), eq], axis=1)
    peak = np.maximum.accumulate(eq, axis=1)
    dd = (1 - eq / peak).max(axis=1)
    final = eq[:, -1] - 1
    return {
        "n_trades": int(m), "n_sims": n_sims, "risk_pct": risk_pct,
        "dd_median": float(np.median(dd)), "dd_95": float(np.quantile(dd, 0.95)), "dd_99": float(np.quantile(dd, 0.99)),
        "historical_dd": max_drawdown(equity_from_r(r, risk_pct)),
        "return_median": float(np.median(final)), "return_p05": float(np.quantile(final, 0.05)),
        "p_loss": float((final < 0).mean()), "dd_samples": dd,
    }


def random_entry_baseline(df: pd.DataFrame, sig: pd.DataFrame, n_signals: int, cfg: BacktestConfig = BacktestConfig(),
                          n_sims: int = 300, mode: str = "random", start=None, end=None, seed: int = 123) -> pd.DataFrame:
    """Null model: keep the strategy's exits (sl/tp/trail distances) but replace
    entries with random bars. ``mode='random'`` draws direction 50/50,
    ``mode='long'`` is long-only (captures gold's upward drift)."""
    rng = np.random.default_rng(seed)
    mask = np.ones(len(df), bool)
    if start is not None:
        mask &= df.index >= start
    if end is not None:
        mask &= df.index < end
    d, s0 = df[mask], sig[mask]
    valid = np.flatnonzero(s0["sl_dist"].notna().to_numpy())
    rows = []
    for k in range(n_sims):
        s = s0.copy()
        sigv = np.zeros(len(s), int)
        if n_signals > 0 and len(valid):
            pick = rng.choice(valid, size=min(n_signals, len(valid)), replace=False)
            sigv[pick] = rng.choice([-1, 1], size=len(pick)) if mode == "random" else 1
        s["signal"] = sigv
        res = run_backtest(d, s, cfg)
        sm = summarize(res.trades, res.equity)
        rows.append({"sim": k, "trades": sm["trades"], "expectancy_r": sm["expectancy_r"],
                     "win_rate": sm["win_rate"], "max_dd": sm.get("max_dd"), "total_return": sm.get("total_return")})
    return pd.DataFrame(rows)
