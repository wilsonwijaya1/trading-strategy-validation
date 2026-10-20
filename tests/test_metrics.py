import numpy as np
import pandas as pd
import pytest

from trading_research.metrics import (breakeven_win_rate, cagr, equity_from_r, expectancy_r, max_drawdown,
                                      payoff_ratio, profit_factor, sharpe, wilson_interval, win_rate)


def test_max_drawdown_known_curve():
    assert max_drawdown([100, 120, 90, 130, 65]) == pytest.approx(0.5)
    assert max_drawdown([1, 2, 3]) == 0.0


def test_r_metrics_on_synthetic_trades():
    r = np.array([2.0, -1.0, 2.0, -1.0, -1.0])
    assert win_rate(r) == pytest.approx(0.4)
    assert expectancy_r(r) == pytest.approx(0.2)
    assert profit_factor(r) == pytest.approx(4 / 3)
    assert payoff_ratio(r) == pytest.approx(2.0)


def test_breakeven_win_rate():
    assert breakeven_win_rate(1.0) == pytest.approx(0.5)
    assert breakeven_win_rate(2.0) == pytest.approx(1 / 3)


def test_cagr_two_years():
    idx = pd.to_datetime(["2020-01-01", "2022-01-01"])
    eq = pd.Series([100.0, 121.0], index=idx)
    assert cagr(eq) == pytest.approx(0.10, abs=1e-3)


def test_sharpe_steady_growth_is_large_and_flat_is_nan():
    idx = pd.date_range("2020-01-01", periods=300, freq="D")
    rng = np.random.default_rng(1)
    eq = pd.Series(100 * np.cumprod(1 + 0.001 + rng.normal(0, 0.0001, 300)), index=idx)
    assert sharpe(eq) > 10
    assert np.isnan(sharpe(pd.Series(100.0, index=idx)))


def test_wilson_interval_small_sample():
    lo, hi = wilson_interval(9, 9)
    assert lo == pytest.approx(0.701, abs=1e-3)
    assert hi == 1.0


def test_equity_from_r_compounds():
    eq = equity_from_r(np.array([1.0, -1.0]), risk_pct=10)
    assert eq.tolist() == pytest.approx([1.0, 1.1, 0.99])
