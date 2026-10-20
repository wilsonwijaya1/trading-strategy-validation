from pathlib import Path

import pytest

from trading_research.journal import audit_summary, data_issues, load_legacy, load_v2, planned_r, realized_r

ROOT = Path(__file__).resolve().parents[1]


def test_planned_and_realized_r():
    assert planned_r(100, 98, 104, 1) == pytest.approx(2.0)
    assert planned_r(100, 102, 97, -1) == pytest.approx(1.5)
    assert realized_r(100, 98, 99, 1) == pytest.approx(-0.5)


def test_legacy_journal_r_and_saturday_flag():
    df = load_legacy(ROOT / "journals" / "template-backtest.csv")
    assert len(df) == 9
    assert df.loc[0, "r_planned"] == pytest.approx(39.5 / 33.5)
    assert (df["r_realized"] == df["r_planned"]).all()  # every trade is marked TP
    issues = " ".join(data_issues(df))
    assert "01-Feb-2025" in issues and "Sabtu" in issues
    s = audit_summary(df)
    assert s["n_long"] == 8 and s["n_short"] == 1
    assert s["avg_planned_rr"] < 1.0


def test_v2_template_loads_and_skips_examples():
    path = ROOT / "templates" / "jurnal_trading_v2.csv"
    df = load_v2(path, drop_examples=False)
    assert len(df) == 2
    assert df["trade_id"].str.startswith("EXAMPLE").all()
    assert df["r_rencana_calc"].notna().all()
    assert len(load_v2(path)) == 0
