import numpy as np
import pandas as pd

from trading_research.strategy_ichimoku_rsi import CLASSIC_PARAMS
from trading_research.validation import make_grid, monte_carlo_dd, split_is_oos, walk_forward


def test_split_is_oos_70_30():
    idx = pd.date_range("2020-01-01", periods=100, freq="D")
    b = split_is_oos(idx, 0.7)
    assert (idx < b).sum() == 70 and (idx >= b).sum() == 30


def test_monte_carlo_all_winners_has_zero_dd_and_is_reproducible():
    mc = monte_carlo_dd(np.ones(50), risk_pct=1.0, n_sims=200)
    assert mc["dd_95"] == 0.0 and mc["p_loss"] == 0.0
    r = np.array([1.0, -1.0, 1.5, -1.0, 0.5])
    a = monte_carlo_dd(r, n_sims=500, seed=3)
    b = monte_carlo_dd(r, n_sims=500, seed=3)
    assert a["dd_95"] == b["dd_95"]
    assert a["dd_95"] >= a["dd_median"]


def test_make_grid_sets_senkou_to_twice_kijun():
    g = make_grid(CLASSIC_PARAMS, tenkan=[7, 9], kijun=[20, 30])
    assert len(g) == 4
    assert all(p.senkou == 2 * p.kijun for p in g)


def test_walk_forward_test_windows_follow_train_and_do_not_overlap(random_walk):
    grid = make_grid(CLASSIC_PARAMS.with_(rsi_delta=0.0), tenkan=[7, 9])
    wf = walk_forward(random_walk, grid, train=pd.DateOffset(months=6), test=pd.DateOffset(months=3), min_trades=1)
    w = wf.windows
    assert len(w) >= 3
    # each test window starts where its training window ends, and the next one starts where it ends
    assert (w["train_end"].iloc[1:].to_numpy() == w["test_end"].iloc[:-1].to_numpy()).all()
    assert len(wf.oos_trades) > 0
    for _, row in w.iterrows():
        t = wf.oos_trades[wf.oos_trades["window"] == row["window"]]
        assert (t["entry_time"] >= row["train_end"]).all()
        assert (t["entry_time"] < row["test_end"]).all()
