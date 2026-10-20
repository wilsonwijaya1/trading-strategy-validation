import numpy as np
import pandas as pd
import pytest

from trading_research.indicators import atr, ichimoku, rsi, sma, true_range


def test_sma_basic():
    s = pd.Series([1.0, 2, 3, 4, 5])
    out = sma(s, 3)
    assert np.isnan(out.iloc[1])
    assert out.iloc[2] == pytest.approx(2.0)
    assert out.iloc[4] == pytest.approx(4.0)


def test_rsi_matches_hand_computed_wilder():
    # diffs: +1 +1 -1 +1 +1 -1 ; period 3
    close = pd.Series([1.0, 2, 3, 2, 3, 4, 3])
    out = rsi(close, 3)
    assert out.iloc[:3].isna().all()
    # seed: avg gain 2/3, avg loss 1/3 -> RS 2 -> 66.67
    assert out.iloc[3] == pytest.approx(200 / 3)
    # ag = 7/9, al = 2/9 -> RS 3.5
    assert out.iloc[4] == pytest.approx(100 - 100 / 4.5)
    # ag = 23/27, al = 4/27 -> RS 5.75
    assert out.iloc[5] == pytest.approx(100 - 100 / 6.75)
    # ag = 46/81, al = 35/81 -> RS 46/35
    assert out.iloc[6] == pytest.approx(100 - 100 / (1 + 46 / 35))


def test_rsi_monotonic_up_is_100():
    out = rsi(pd.Series(np.arange(30, dtype=float)), 14)
    assert out.dropna().eq(100.0).all()


def test_true_range_and_sma_atr_hand_values():
    h = pd.Series([10.0, 12, 11, 15])
    l = pd.Series([8.0, 9, 7, 12])
    c = pd.Series([9.0, 11, 8, 14])
    tr = true_range(h, l, c)
    # bar0: 2 ; bar1: max(3, 3, 0)=3 ; bar2: max(4, 0, 4)=4 ; bar3: max(3, 7, 4)=7
    assert tr.tolist() == [2.0, 3.0, 4.0, 7.0]
    a = atr(h, l, c, period=2, method="sma")
    assert a.iloc[1] == pytest.approx(2.5)
    assert a.iloc[3] == pytest.approx(5.5)


def test_atr_wilder_hand_values():
    h = pd.Series([10.0, 12, 11, 15])
    l = pd.Series([8.0, 9, 7, 12])
    c = pd.Series([9.0, 11, 8, 14])
    a = atr(h, l, c, period=2, method="wilder")
    assert a.iloc[1] == pytest.approx(2.5)  # seed mean(2, 3)
    assert a.iloc[2] == pytest.approx((2.5 + 4) / 2)
    assert a.iloc[3] == pytest.approx((3.25 + 7) / 2)


def test_ichimoku_hand_values_and_forward_shift():
    h = pd.Series([10.0, 11, 12, 13, 14, 15, 16, 17])
    l = pd.Series([9.0, 10, 11, 12, 13, 14, 15, 16])
    ich = ichimoku(h, l, tenkan=2, kijun=3, senkou=4, displacement=2)
    # tenkan at 1: (max(10,11) + min(9,10)) / 2 = 10
    assert ich["tenkan"].iloc[1] == pytest.approx(10.0)
    # kijun at 2: (12 + 9) / 2 = 10.5
    assert ich["kijun"].iloc[2] == pytest.approx(10.5)
    # raw span A at 2 = (tenkan_2 + kijun_2)/2 = (11 + 10.5)/2 = 10.75, plotted at bar 4
    assert ich["senkou_a"].iloc[4] == pytest.approx(10.75)
    # raw span B at 3 = (13 + 9)/2 = 11, plotted at bar 5
    assert ich["senkou_b"].iloc[5] == pytest.approx(11.0)
    # raw span B needs 4 bars, so the value plotted at bar 4 (from bar 2) is undefined
    assert np.isnan(ich["senkou_b"].iloc[4])


def test_indicators_are_causal(random_walk):
    cut = 400
    full = ichimoku(random_walk["high"], random_walk["low"], 9, 26, 52)
    part = ichimoku(random_walk["high"].iloc[:cut], random_walk["low"].iloc[:cut], 9, 26, 52)
    pd.testing.assert_frame_equal(full.iloc[:cut], part)
    pd.testing.assert_series_equal(rsi(random_walk["close"], 14).iloc[:cut], rsi(random_walk["close"].iloc[:cut], 14))
    a_full = atr(random_walk["high"], random_walk["low"], random_walk["close"], 14)
    a_part = atr(random_walk["high"].iloc[:cut], random_walk["low"].iloc[:cut], random_walk["close"].iloc[:cut], 14)
    pd.testing.assert_series_equal(a_full.iloc[:cut], a_part)
