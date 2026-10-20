import numpy as np
import pytest

from conftest import make_bars, make_sig
from trading_research.backtest import ZERO_COSTS, BacktestConfig, CostModel, run_backtest

CFG0 = BacktestConfig(initial_equity=10_000, risk_pct=1.0, costs=ZERO_COSTS)


def test_entry_is_next_bar_open_and_tp_hit():
    df = make_bars([(99, 100, 98, 100), (100, 101, 99.5, 100.5), (100.5, 103, 100, 102.5)])
    res = run_backtest(df, make_sig(df, {0: 1}), CFG0)
    t = res.trades.iloc[0]
    assert t["entry_price"] == 100  # open of bar 1, not close of bar 0
    assert t["exit_reason"] == "tp" and t["exit_price"] == 102
    assert t["r_multiple"] == pytest.approx(1.0)
    assert t["units"] == pytest.approx(50)  # 1% of 10k / 2 USD stop
    assert res.equity.iloc[-1] == pytest.approx(10_100)


def test_long_stop_loss_hit():
    df = make_bars([(99, 100, 98, 100), (100, 100.5, 97.5, 98)])
    t = run_backtest(df, make_sig(df, {0: 1}), CFG0).trades.iloc[0]
    assert t["exit_reason"] == "stop" and t["exit_price"] == 98
    assert t["r_multiple"] == pytest.approx(-1.0)
    assert t["mae_r"] == pytest.approx(-1.0)


def test_both_levels_in_same_bar_assumes_stop_first():
    df = make_bars([(99, 100, 98, 100), (100, 103, 97, 101)])
    t = run_backtest(df, make_sig(df, {0: 1}), CFG0).trades.iloc[0]
    assert t["exit_reason"] == "stop"
    assert t["r_multiple"] == pytest.approx(-1.0)


def test_gap_through_stop_fills_at_open():
    df = make_bars([(99, 100, 98, 100), (100, 100.5, 99.5, 100), (95, 96, 94, 95)])
    t = run_backtest(df, make_sig(df, {0: 1}), CFG0).trades.iloc[0]
    assert t["exit_reason"] == "stop_gap" and t["exit_price"] == 95
    assert t["r_multiple"] == pytest.approx(-2.5)


def test_short_take_profit():
    df = make_bars([(101, 102, 100, 100), (100, 100.5, 99, 99.5), (99.5, 99.8, 97.5, 98)])
    t = run_backtest(df, make_sig(df, {0: -1}), CFG0).trades.iloc[0]
    assert t["direction"] == -1 and t["exit_reason"] == "tp"
    assert t["exit_price"] == 98
    assert t["r_multiple"] == pytest.approx(1.0)


def test_short_stop_loss_hit():
    df = make_bars([(101, 102, 100, 100), (100, 102.5, 99.5, 102)])
    t = run_backtest(df, make_sig(df, {0: -1}), CFG0).trades.iloc[0]
    assert t["exit_reason"] == "stop" and t["exit_price"] == 102
    assert t["r_multiple"] == pytest.approx(-1.0)


def test_costs_reduce_r_by_expected_amount():
    costs = CostModel(spread=0.4, slippage=0.1, commission_per_lot=10.0, contract_size=100,
                      swap_long_annual_pct=0.0, swap_short_annual_pct=0.0)
    df = make_bars([(99, 100, 98, 100), (100, 100.5, 97, 98)])
    t = run_backtest(df, make_sig(df, {0: 1}), BacktestConfig(costs=costs)).trades.iloc[0]
    entry = 100 + 0.2 + 0.1  # open + half spread + slippage
    assert t["entry_price"] == pytest.approx(entry)
    assert t["exit_price"] == pytest.approx(entry - 2 - 0.1)
    # loss per oz = 2 (stop) + 0.1 (exit slippage) + 0.1 (commission per oz)
    assert t["r_multiple"] == pytest.approx(-(2 + 0.1 + 0.1) / 2)


def test_lot_step_rounds_position_down():
    df = make_bars([(99, 100, 98, 100), (100, 103, 99.5, 102)])
    cfg = BacktestConfig(initial_equity=10_000, risk_pct=1.0, costs=ZERO_COSTS, lot_step=0.01)
    t = run_backtest(df, make_sig(df, {0: 1}, sl=3.0, tp=6.0), cfg).trades.iloc[0]
    # 100 USD / 3 USD = 33.3 oz -> rounded down to 33 oz = 0.33 lot
    assert t["units"] == pytest.approx(33)
    assert t["lots"] == pytest.approx(0.33)


def test_trailing_stop_ratchets_and_exits():
    rows = [(99, 100, 98, 100), (100, 101, 99.5, 101), (101, 105, 100.8, 105), (105, 105.5, 102, 103)]
    df = make_bars(rows)
    sig = make_sig(df, {0: 1}, sl=2.0, tp=np.nan, trail=2.0)
    t = run_backtest(df, sig, CFG0).trades.iloc[0]
    # stop after bar 2 close = 105 - 2 = 103 ; bar 3 low 102 -> exit at 103
    assert t["exit_reason"] == "trail"
    assert t["exit_price"] == pytest.approx(103)
    assert t["r_multiple"] == pytest.approx(1.5)
    # bar 3 high 105.5 may precede the stop inside the bar, so it counts as MFE: 5.5 / 2
    assert t["mfe_r"] == pytest.approx(2.75)


def test_only_one_position_at_a_time():
    df = make_bars([(99, 100, 98, 100), (100, 100.5, 99.5, 100), (100, 100.5, 99.5, 100), (100, 103, 99.5, 102)])
    res = run_backtest(df, make_sig(df, {0: 1, 1: 1, 2: -1}), CFG0)
    assert len(res.trades) == 1
