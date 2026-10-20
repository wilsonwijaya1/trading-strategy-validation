"""Manual trading journal: loading, R-multiple recomputation and data audit.

Two formats are supported:

* the legacy sheet ``template-backtest.csv`` with columns
  ``Pair, Action, Tanggal Entry, Tanggal Exit, Entry, TP, SL, Keterangan``
* the v2 template ``templates/jurnal_trading_v2.csv`` (see README)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .metrics import breakeven_win_rate, wilson_interval

V2_COLUMNS = [
    "trade_id", "tanggal_entry", "jam_entry", "tanggal_exit", "jam_exit", "pair", "arah", "setup", "timeframe",
    "sesi", "entry", "sl", "tp", "exit", "lot", "risk_pct", "r_rencana", "r_realisasi", "mae_r", "mfe_r",
    "spread", "biaya", "alasan_entry", "alasan_exit", "screenshot_url", "catatan", "emosi_1_5",
]

DAY_NAMES = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]


def _dir(action: str) -> int:
    a = str(action).strip().lower()
    if a in ("buy", "long", "b"):
        return 1
    if a in ("sell", "short", "s"):
        return -1
    raise ValueError(f"unknown direction {action!r}")


def planned_r(entry: float, sl: float, tp: float, direction: int) -> float:
    risk = (entry - sl) * direction
    reward = (tp - entry) * direction
    if risk <= 0:
        return float("nan")
    return reward / risk


def realized_r(entry: float, sl: float, exit_px: float, direction: int) -> float:
    risk = (entry - sl) * direction
    if risk <= 0:
        return float("nan")
    return (exit_px - entry) * direction / risk


def load_legacy(path: str | Path) -> pd.DataFrame:
    """Load ``template-backtest.csv`` and compute planned/realised R per trade.

    Realised exit price is inferred from ``Keterangan``: TP -> exit at TP,
    SL -> exit at SL, anything else -> unknown (NaN). No spread or commission
    is included because the sheet does not record them.
    """
    raw = pd.read_csv(path)
    raw.columns = [c.strip() for c in raw.columns]
    df = pd.DataFrame({
        "trade_no": np.arange(1, len(raw) + 1),
        "pair": raw["Pair"].str.strip(),
        "direction": raw["Action"].map(_dir),
        "entry_date": pd.to_datetime(raw["Tanggal Entry"].str.strip(), format="%d-%b-%y"),
        "exit_date": pd.to_datetime(raw["Tanggal Exit"].str.strip(), format="%d-%b-%y"),
        "entry": raw["Entry"].astype(float),
        "tp": raw["TP"].astype(float),
        "sl": raw["SL"].astype(float),
        "result": raw["Keterangan"].str.strip().str.upper(),
    })
    df["risk_usd"] = (df["entry"] - df["sl"]) * df["direction"]
    df["reward_usd"] = (df["tp"] - df["entry"]) * df["direction"]
    df["r_planned"] = [planned_r(e, s, t, d) for e, s, t, d in zip(df.entry, df.sl, df.tp, df.direction)]
    exit_px = np.where(df["result"] == "TP", df["tp"], np.where(df["result"] == "SL", df["sl"], np.nan))
    df["exit_price_inferred"] = exit_px
    df["r_realized"] = [realized_r(e, s, x, d) if np.isfinite(x) else np.nan
                        for e, s, x, d in zip(df.entry, df.sl, exit_px, df.direction)]
    df["entry_weekday"] = df["entry_date"].dt.dayofweek.map(lambda i: DAY_NAMES[i])
    df["exit_weekday"] = df["exit_date"].dt.dayofweek.map(lambda i: DAY_NAMES[i])
    df["holding_days"] = (df["exit_date"] - df["entry_date"]).dt.days
    return df


def data_issues(df: pd.DataFrame) -> list[str]:
    """Human-readable list of data-quality problems in a legacy journal."""
    issues = []
    for _, t in df.iterrows():
        for col, wd in (("entry_date", "entry_weekday"), ("exit_date", "exit_weekday")):
            if t[col].dayofweek >= 5:
                kind = "entry" if col == "entry_date" else "exit"
                issues.append(f"Trade #{t.trade_no}: tanggal {kind} {t[col]:%d-%b-%Y} jatuh pada hari {t[wd]} "
                              "(pasar emas spot/futures tutup pada Sabtu; Minggu hanya buka malam waktu Asia).")
        if t["exit_date"] < t["entry_date"]:
            issues.append(f"Trade #{t.trade_no}: tanggal exit sebelum tanggal entry.")
        if not np.isfinite(t["r_planned"]):
            issues.append(f"Trade #{t.trade_no}: SL berada di sisi yang salah dari entry.")
    if df["result"].isin(["TP"]).all():
        issues.append(f"Semua {len(df)} trade tercatat TP (0 loss). Ini sangat jarang terjadi pada data nyata dan "
                      "mengindikasikan seleksi/hindsight bias atau trade loss yang tidak dicatat.")
    return issues


def audit_summary(df: pd.DataFrame) -> dict:
    n = len(df)
    r = df["r_realized"].dropna().to_numpy(float)
    wins = int((r > 0).sum())
    avg_rr = float(df["r_planned"].mean())
    lo, hi = wilson_interval(wins, len(r))
    return {
        "n_trades": n,
        "n_long": int((df["direction"] == 1).sum()),
        "n_short": int((df["direction"] == -1).sum()),
        "period_start": df["entry_date"].min(),
        "period_end": df["exit_date"].max(),
        "wins": wins,
        "win_rate": wins / len(r) if len(r) else float("nan"),
        "win_rate_ci95": (lo, hi),
        "avg_planned_rr": avg_rr,
        "median_planned_rr": float(df["r_planned"].median()),
        "min_planned_rr": float(df["r_planned"].min()),
        "expectancy_r": float(r.mean()) if len(r) else float("nan"),
        "total_r": float(r.sum()),
        "breakeven_wr_at_avg_rr": breakeven_win_rate(avg_rr),
        "same_day_trades": int((df["holding_days"] == 0).sum()),
    }


def verify_with_prices(df: pd.DataFrame, bars: pd.DataFrame) -> pd.DataFrame:
    """Check each journal trade against an OHLC series (e.g. GC=F 1h, UTC).

    The journal has no times and the reference series is COMEX futures, not the
    broker's spot CFD, so this is only an approximate plausibility check:

    * ``entry_in_range``: is the journal entry inside the futures [low, high]
      of the entry day (UTC calendar day), unadjusted?
    * ``basis_est``: futures close of the entry day minus the journal entry.
      The median across trades is used as a single futures-spot offset.
    * ``first_hit``: after shifting entry/TP/SL by that offset, scan the bars
      from the first touch of the entry price until the end of the exit day and
      report which level is touched first (``ambiguous`` if both in one bar).
    """
    b = bars.copy()
    if b.index.tz is not None:
        b.index = b.index.tz_convert("UTC").tz_localize(None)
    one = pd.Timedelta(days=1)
    rows = []
    for _, t in df.iterrows():
        day = b[(b.index >= t["entry_date"]) & (b.index < t["entry_date"] + one)]
        row = {"trade_no": t["trade_no"], "bars_entry_day": len(day)}
        if len(day):
            row["day_low"] = float(day["low"].min())
            row["day_high"] = float(day["high"].max())
            row["entry_in_range"] = bool(row["day_low"] <= t["entry"] <= row["day_high"])
            row["basis_est"] = float(day["close"].iloc[-1] - t["entry"])
        else:
            row.update(day_low=np.nan, day_high=np.nan, entry_in_range=None, basis_est=np.nan)
        rows.append(row)
    res = pd.DataFrame(rows)
    basis = float(res["basis_est"].median()) if res["basis_est"].notna().any() else float("nan")
    res["basis_used"] = basis
    hits = []
    for _, t in df.iterrows():
        win = b[(b.index >= t["entry_date"]) & (b.index < t["exit_date"] + one)]
        if not len(win) or not np.isfinite(basis):
            hits.append("tidak ada data")
            continue
        d = t["direction"]
        entry_f, tp, sl = t["entry"] + basis, t["tp"] + basis, t["sl"] + basis
        touched = np.flatnonzero((win["low"].to_numpy() <= entry_f) & (win["high"].to_numpy() >= entry_f))
        if not len(touched):
            hits.append("harga entry tidak tercapai")
            continue
        verdict = "belum tersentuh s.d. tanggal exit"
        for _, bar in win.iloc[touched[0]:].iterrows():
            tp_hit = bar["high"] >= tp if d == 1 else bar["low"] <= tp
            sl_hit = bar["low"] <= sl if d == 1 else bar["high"] >= sl
            if tp_hit and sl_hit:
                verdict = "ambigu"
                break
            if tp_hit or sl_hit:
                verdict = "TP" if tp_hit else "SL"
                break
        hits.append(verdict)
    res["first_hit"] = hits
    return res


def load_v2(path: str | Path, drop_examples: bool = True) -> pd.DataFrame:
    """Load a v2 journal and recompute r_rencana / r_realisasi from prices."""
    df = pd.read_csv(path, dtype={"trade_id": str})
    missing = [c for c in V2_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"missing columns: {missing}")
    if drop_examples:
        df = df[~df["trade_id"].astype(str).str.upper().str.startswith("EXAMPLE")]
    df = df.copy()
    d = df["arah"].map(_dir)
    for c in ("entry", "sl", "tp", "exit"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["r_rencana_calc"] = [planned_r(e, s, t, k) for e, s, t, k in zip(df.entry, df.sl, df.tp, d)]
    df["r_realisasi_calc"] = [realized_r(e, s, x, k) for e, s, x, k in zip(df.entry, df.sl, df.exit, d)]
    return df


def v2_summary(df: pd.DataFrame) -> dict:
    r = df["r_realisasi_calc"].dropna().to_numpy(float)
    wins = int((r > 0).sum())
    return {
        "n_trades": len(r),
        "win_rate": wins / len(r) if len(r) else float("nan"),
        "win_rate_ci95": wilson_interval(wins, len(r)),
        "expectancy_r": float(r.mean()) if len(r) else float("nan"),
        "avg_planned_rr": float(df["r_rencana_calc"].mean()) if len(df) else float("nan"),
        "total_r": float(r.sum()),
    }
