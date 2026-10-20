"""Download and cache gold OHLC data from Yahoo Finance (yfinance).

Ticker resolution: ``XAUUSD=X`` (spot) is tried first; if Yahoo returns no
rows (it currently does not serve spot gold) we fall back to ``GC=F``, the
COMEX front-month gold future. The ticker actually used is stored in a
``.meta.json`` file next to the cached CSV so every report can state it.

Cached files live in ``<repo>/data/`` which is git-ignored.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"

DEFAULT_TICKERS: tuple[str, ...] = ("XAUUSD=X", "GC=F")

# yfinance limits: 1h history ~730 days, 15m history ~60 days.
TIMEFRAMES: dict[str, dict] = {
    "1d": {"interval": "1d", "start": "2010-01-01"},
    "1h": {"interval": "1h", "period": "730d"},
    "15m": {"interval": "15m", "period": "60d"},
}

OHLC = ["open", "high", "low", "close"]


@dataclass
class DataMeta:
    timeframe: str
    ticker: str
    downloaded_at: str
    rows: int
    first: str
    last: str
    dropped_rows: int
    fixed_envelope_rows: int

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def _flatten(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns={c: str(c).lower().replace(" ", "_") for c in df.columns})
    return df


def clean_ohlc(df: pd.DataFrame) -> tuple[pd.DataFrame, int, int]:
    """Basic sanity cleaning. Returns (clean_df, dropped_rows, fixed_rows).

    * drop rows with missing or non-positive OHLC
    * drop duplicated timestamps, sort index
    * enforce high >= max(open, close) and low <= min(open, close)
    """
    df = df.copy()
    n0 = len(df)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df.dropna(subset=OHLC)
    df = df[(df[OHLC] > 0).all(axis=1)]
    dropped = n0 - len(df)
    hi = df[OHLC].max(axis=1)
    lo = df[OHLC].min(axis=1)
    bad = (df["high"] < hi) | (df["low"] > lo)
    df.loc[:, "high"] = hi
    df.loc[:, "low"] = lo
    if "volume" not in df.columns:
        df["volume"] = np.nan
    return df[OHLC + ["volume"]], dropped, int(bad.sum())


def download_ohlc(timeframe: str, tickers: tuple[str, ...] = DEFAULT_TICKERS) -> tuple[pd.DataFrame, str]:
    """Download raw OHLC for ``timeframe`` trying ``tickers`` in order."""
    import yfinance as yf  # imported lazily so tests do not need network

    spec = TIMEFRAMES[timeframe]
    last_err: Exception | None = None
    for t in tickers:
        try:
            raw = yf.download(t, auto_adjust=False, progress=False, **spec)
        except Exception as e:  # pragma: no cover - network dependent
            last_err = e
            continue
        if raw is not None and len(raw) > 0:
            df = _flatten(raw)
            idx = pd.DatetimeIndex(df.index)
            if timeframe == "1d":
                idx = idx.tz_localize(None) if idx.tz is not None else idx
                idx = idx.normalize()
            else:
                idx = idx.tz_convert("UTC") if idx.tz is not None else idx.tz_localize("UTC")
            df.index = idx
            df.index.name = "time"
            return df, t
    raise RuntimeError(f"No data for {timeframe} from {tickers}: {last_err}")


def _paths(timeframe: str) -> tuple[Path, Path]:
    return DATA_DIR / f"xau_{timeframe}.csv", DATA_DIR / f"xau_{timeframe}.meta.json"


def load_ohlc(timeframe: str = "1d", refresh: bool = False) -> tuple[pd.DataFrame, DataMeta]:
    """Load cached OHLC (download on first use or when ``refresh``)."""
    csv, meta_path = _paths(timeframe)
    if refresh or not csv.exists() or not meta_path.exists():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        raw, ticker = download_ohlc(timeframe)
        df, dropped, fixed = clean_ohlc(raw)
        df.to_csv(csv)
        meta = DataMeta(
            timeframe=timeframe,
            ticker=ticker,
            downloaded_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            rows=len(df),
            first=str(df.index[0]),
            last=str(df.index[-1]),
            dropped_rows=dropped,
            fixed_envelope_rows=fixed,
        )
        meta_path.write_text(json.dumps(meta.to_dict(), indent=2), encoding="utf-8")
    df = pd.read_csv(csv, index_col=0)
    if timeframe == "1d":
        df.index = pd.to_datetime(df.index)
    else:
        df.index = pd.to_datetime(df.index, utc=True)
    df.index.name = "time"
    meta = DataMeta(**json.loads(meta_path.read_text(encoding="utf-8")))
    return df, meta
