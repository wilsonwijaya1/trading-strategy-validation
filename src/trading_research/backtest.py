"""Bar-by-bar (event-driven) backtest engine for a single instrument.

Execution model (conservative by design)
----------------------------------------
* Input prices are treated as MID prices. Bid = mid - spread/2, Ask = mid + spread/2.
* A signal on bar ``t`` (decided on its close) is filled at the OPEN of bar ``t+1``
  plus half the spread plus slippage (long pays the ask, short sells the bid).
* Stop loss / take profit are checked against the bar's high/low on the side
  that would close the trade (long exits on bid, short exits on ask).
* If both SL and TP are touched inside the same bar we assume the STOP was hit
  first (we cannot know the intrabar path from OHLC data).
* If the bar opens beyond the stop (gap) the exit fills at the open (worse
  than the stop), minus slippage. If it gaps beyond the TP, fill at the open.
* Stop exits pay slippage; TP exits are limit orders (no slippage).
* Trailing stops are updated on the bar CLOSE and become active on the next bar
  (no intrabar trailing, which would require tick data).
* Commission is charged per round turn per lot; a simple financing (swap) cost
  proportional to holding time is charged as an annual percentage of notional.
* Position size = ``equity * risk_pct / stop_distance`` units (oz). ``lot_step``
  optionally rounds down to broker lot increments (1 lot = 100 oz).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class CostModel:
    spread: float = 0.30  # full bid/ask spread in USD per oz
    slippage: float = 0.05  # USD per oz per market fill (entry and stop exit)
    commission_per_lot: float = 7.0  # USD per 100 oz round turn
    contract_size: float = 100.0  # oz per lot
    swap_long_annual_pct: float = 5.0  # financing charged on long notional
    swap_short_annual_pct: float = 1.0  # financing charged on short notional

    @property
    def commission_per_unit(self) -> float:
        return self.commission_per_lot / self.contract_size


ZERO_COSTS = CostModel(0.0, 0.0, 0.0, 100.0, 0.0, 0.0)


@dataclass(frozen=True)
class BacktestConfig:
    initial_equity: float = 10_000.0
    risk_pct: float = 1.0
    costs: CostModel = field(default_factory=CostModel)
    lot_step: float | None = None  # e.g. 0.01 to round to broker lots; None = fractional
    max_bars_in_trade: int | None = None


@dataclass
class BacktestResult:
    trades: pd.DataFrame
    equity: pd.Series
    config: BacktestConfig

    @property
    def r(self) -> np.ndarray:
        return self.trades["r_multiple"].to_numpy(dtype=float) if len(self.trades) else np.array([])


TRADE_COLUMNS = [
    "entry_time", "exit_time", "direction", "entry_price", "exit_price", "sl_initial", "sl_final",
    "tp", "sl_dist", "units", "lots", "risk_cash", "gross_pnl", "commission", "swap", "pnl",
    "r_multiple", "mae_r", "mfe_r", "bars_held", "exit_reason", "equity_after",
]


def run_backtest(df: pd.DataFrame, sig: pd.DataFrame, cfg: BacktestConfig = BacktestConfig()) -> BacktestResult:
    """Run the engine. ``sig`` must be index-aligned with ``df`` and contain
    ``signal``, ``sl_dist``, ``tp_dist`` and ``trail_dist`` columns."""
    if not df.index.equals(sig.index):
        raise ValueError("df and sig must share the same index")
    o = df["open"].to_numpy(float)
    h = df["high"].to_numpy(float)
    lo = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    idx = df.index
    s = sig["signal"].to_numpy()
    sl_d = sig["sl_dist"].to_numpy(float)
    tp_d = sig["tp_dist"].to_numpy(float) if "tp_dist" in sig else np.full(len(df), np.nan)
    tr_d = sig["trail_dist"].to_numpy(float) if "trail_dist" in sig else np.full(len(df), np.nan)

    cm = cfg.costs
    half = cm.spread / 2.0
    slip = cm.slippage
    n = len(df)
    eq = np.empty(n)
    cash = cfg.initial_equity
    trades: list[dict] = []
    pos: dict | None = None

    def close_trade(i: int, exit_px: float, reason: str) -> None:
        nonlocal cash, pos
        d = pos["dir"]
        units = pos["units"]
        gross = units * (exit_px - pos["entry"]) * d
        comm = units * cm.commission_per_unit
        days = (idx[i] - pos["entry_time"]).total_seconds() / 86400.0
        rate = cm.swap_long_annual_pct if d == 1 else cm.swap_short_annual_pct
        swap = units * pos["entry"] * rate / 100.0 * max(days, 0.0) / 365.0
        pnl = gross - comm - swap
        cash += pnl
        risk_cash = units * pos["sl_dist"]
        trades.append({
            "entry_time": pos["entry_time"], "exit_time": idx[i], "direction": d,
            "entry_price": pos["entry"], "exit_price": exit_px, "sl_initial": pos["sl0"],
            "sl_final": pos["stop"], "tp": pos["tp"], "sl_dist": pos["sl_dist"], "units": units,
            "lots": units / cm.contract_size, "risk_cash": risk_cash, "gross_pnl": gross,
            "commission": comm, "swap": swap, "pnl": pnl, "r_multiple": pnl / risk_cash,
            "mae_r": pos["mae"] / pos["sl_dist"], "mfe_r": pos["mfe"] / pos["sl_dist"],
            "bars_held": i - pos["i0"] + 1, "exit_reason": reason, "equity_after": cash,
        })
        pos = None

    for i in range(n):
        # ---- 1. entry at the open of bar i from a signal on bar i-1 ----
        if pos is None and i > 0 and s[i - 1] != 0:
            dist = sl_d[i - 1]
            if np.isfinite(dist) and dist > 0:
                d = int(s[i - 1])
                entry = o[i] + d * (half + slip)
                units = cash * cfg.risk_pct / 100.0 / dist
                if cfg.lot_step:
                    step_units = cfg.lot_step * cm.contract_size
                    units = np.floor(units / step_units + 1e-9) * step_units
                if units > 0 and cash > 0:
                    tpd = tp_d[i - 1]
                    pos = {
                        "dir": d, "entry": entry, "entry_time": idx[i], "i0": i, "units": units,
                        "sl_dist": dist, "sl0": entry - d * dist, "stop": entry - d * dist,
                        "tp": entry + d * tpd if np.isfinite(tpd) and tpd > 0 else np.nan,
                        "mae": 0.0, "mfe": 0.0,
                    }
        # ---- 2. manage open position inside bar i ----
        if pos is not None:
            d = pos["dir"]
            stop, tp = pos["stop"], pos["tp"]
            first_bar = pos["i0"] == i
            # exit-side prices: long closes at bid, short closes at ask
            px_open = o[i] - d * half
            px_hi = (h[i] - half) if d == 1 else (h[i] + half)
            px_lo = (lo[i] - half) if d == 1 else (lo[i] + half)
            fav = px_hi if d == 1 else px_lo
            adv = px_lo if d == 1 else px_hi
            exit_px, reason = None, None
            if not first_bar and (px_open - stop) * d <= 0:
                exit_px, reason = px_open - d * slip, "stop_gap"
            elif not first_bar and np.isfinite(tp) and (px_open - tp) * d >= 0:
                exit_px, reason = px_open, "tp_gap"
            else:
                hit_sl = (adv - stop) * d <= 0
                hit_tp = np.isfinite(tp) and (fav - tp) * d >= 0
                if hit_sl:  # conservative: stop first when both touched
                    exit_px = stop - d * slip
                    reason = "stop" if stop == pos["sl0"] else "trail"
                elif hit_tp:
                    exit_px, reason = tp, "tp"
            # excursions (per unit, signed relative to entry)
            adv_x = (adv - pos["entry"]) * d
            fav_x = (fav - pos["entry"]) * d
            if exit_px is not None:
                # nothing after the exit belongs to the trade: clip the extreme
                # on the exit side to the realised exit price
                ex = (exit_px - pos["entry"]) * d
                if reason in ("stop", "trail", "stop_gap"):
                    adv_x = ex
                else:  # tp / tp_gap
                    fav_x = ex
            pos["mae"] = min(pos["mae"], adv_x)
            pos["mfe"] = max(pos["mfe"], fav_x)
            if exit_px is None and cfg.max_bars_in_trade and i - pos["i0"] + 1 >= cfg.max_bars_in_trade:
                exit_px, reason = c[i] - d * (half + slip), "time"
            if exit_px is not None:
                close_trade(i, exit_px, reason)
            else:
                td = tr_d[i]
                if np.isfinite(td) and td > 0:
                    new_stop = (c[i] - d * half) - d * td
                    pos["stop"] = max(stop, new_stop) if d == 1 else min(stop, new_stop)
        # ---- 3. mark to market at the close ----
        if pos is not None:
            d = pos["dir"]
            eq[i] = cash + pos["units"] * ((c[i] - d * half) - pos["entry"]) * d
        else:
            eq[i] = cash

    if pos is not None:  # close any open trade at the final close
        d = pos["dir"]
        close_trade(n - 1, c[-1] - d * (half + slip), "end")
        eq[-1] = cash

    tdf = pd.DataFrame(trades, columns=TRADE_COLUMNS)
    return BacktestResult(trades=tdf, equity=pd.Series(eq, index=idx, name="equity"), config=cfg)
