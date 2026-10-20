"""Regenerate every report and figure from scratch.

Usage (from the repo root, with the virtualenv active):

    python scripts/run_all.py            # use cached data in data/ (download on first run)
    python scripts/run_all.py --refresh  # re-download data from Yahoo Finance
    python scripts/run_all.py --quick    # fewer Monte Carlo / null simulations
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402

from trading_research import report_ichimoku, report_journal  # noqa: E402
from trading_research.data import load_ohlc  # noqa: E402


def _jsonable(o):
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if hasattr(o, "isoformat"):
        return o.isoformat()
    return o


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true", help="re-download market data")
    ap.add_argument("--quick", action="store_true", help="fewer simulations (faster, noisier)")
    args = ap.parse_args()
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)

    t0 = time.time()
    data = {tf: load_ohlc(tf, refresh=args.refresh) for tf in ("1d", "1h", "15m")}
    for tf, (df, meta) in data.items():
        print(f"[data] {tf}: {meta.ticker} {len(df):,} bars {meta.first} -> {meta.last} (downloaded {meta.downloaded_at})")

    (ROOT / "reports" / "figures").mkdir(parents=True, exist_ok=True)
    j = report_journal.build(ROOT, data["1d"][0], data["1h"][0], data["1d"][1].ticker)
    print(f"[01] journal audit written ({time.time() - t0:.0f}s)")
    ich = report_ichimoku.build(ROOT, data, quick=args.quick)
    print(f"[02] ichimoku report written ({time.time() - t0:.0f}s)")

    summary = {"data": {tf: m.to_dict() for tf, (_, m) in data.items()}, "journal": j, "ichimoku": ich}
    (ROOT / "reports" / "summary.json").write_text(json.dumps(_jsonable(summary), indent=2), encoding="utf-8", newline="\n")
    v = ich["verdict"]
    print(f"[done] edge proven: {v['edge_proven']} ({v['passed']}/{v['total']} criteria) in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
