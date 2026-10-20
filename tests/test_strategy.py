import pandas as pd

from trading_research.backtest import run_backtest
from trading_research.strategy_ichimoku_rsi import CLASSIC_PARAMS, StrategyParams, generate_signals


def test_signals_have_no_lookahead(random_walk):
    p = CLASSIC_PARAMS.with_(rsi_delta=0.0)
    full = generate_signals(random_walk, p)
    for cut in (250, 400, 550):
        part = generate_signals(random_walk.iloc[:cut], p)
        assert (full["signal"].iloc[:cut].to_numpy() == part["signal"].to_numpy()).all()
    assert (full["signal"] != 0).sum() > 0  # the test is not vacuous


def test_signal_rows_satisfy_all_rules(random_walk):
    p = StrategyParams(tenkan=9, kijun=26, senkou=52, rsi_delta=1.0)
    s = generate_signals(random_walk, p)
    c = random_walk["close"]
    longs = s["signal"] == 1
    shorts = s["signal"] == -1
    assert (longs | shorts).sum() > 0
    assert (c[longs] > s.loc[longs, "cloud_top"]).all()
    assert (s.loc[longs, "tenkan"] > s.loc[longs, "kijun"]).all()
    assert (s.loc[longs, "rsi_delta"] > 1.0).all()
    assert (c[shorts] < s.loc[shorts, "cloud_bottom"]).all()
    assert (s.loc[shorts, "rsi_delta"] < -1.0).all()
    # the cross must be fresh: on the previous bar tenkan <= kijun for longs
    prev = (s["tenkan"] - s["kijun"]).shift(1)
    assert (prev[longs] <= 0).all()
    assert (prev[shorts] >= 0).all()


def test_backtest_completed_trades_unchanged_by_future_data(random_walk):
    p = CLASSIC_PARAMS.with_(rsi_delta=0.0)
    full = run_backtest(random_walk, generate_signals(random_walk, p)).trades
    cut = 450
    part_df = random_walk.iloc[:cut]
    part = run_backtest(part_df, generate_signals(part_df, p)).trades
    done = part[part["exit_reason"] != "end"]
    assert len(done) > 0
    cols = ["entry_time", "exit_time", "r_multiple"]
    pd.testing.assert_frame_equal(full.iloc[: len(done)][cols].reset_index(drop=True), done[cols].reset_index(drop=True))
