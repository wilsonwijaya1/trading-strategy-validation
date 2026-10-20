# trading-research

Reproducible, deliberately sceptical research on an **Ichimoku + RSI-delta strategy for XAUUSD (gold)**, plus an audit
of a manual trade journal. The repo started from a university write-up (TPW08, Universitas Cakrawala) that claimed a
65% win rate, a profit factor of 1.85 and a 15% max drawdown for an MT5/Python trading bot. The goal here is to rebuild that
strategy from its written rules, test it with realistic costs and proper out-of-sample validation, and report the
numbers whether or not they look good.

> **Disclaimer:** this repository is for research and education only. It is **not investment advice** and not a
> recommendation to trade any instrument. Past or simulated performance does not predict future results. Trading
> leveraged products such as gold CFDs can lose more than your deposit.

## Key results (run of 2026-10-20)

Data: Yahoo Finance `GC=F` (COMEX gold futures, continuous front month). Spot `XAUUSD=X` is not served by Yahoo.
Costs: 0.30 USD spread, 0.05 USD slippage per market/stop fill, 7 USD per lot commission, financing on notional.
Sizing: 1% of equity risked per trade. Strategy parameters are the TPW08 ones (Ichimoku 12/30/60, RSI(14) delta > 5).
SL 1.5 x ATR(14) and TP 1R are assumptions, because the documents do not specify exits.

| Test | Trades | Win rate | Expectancy | Profit factor | Max DD |
|---|---|---|---|---|---|
| TPW08 claim (M15, 2024-2026) | >200 | 65% | n/a | 1.85 | 15% |
| 1h in-sample (70%, May 2024 - Feb 2026) | 41 | 65.9% | +0.30R | 1.83 | 4.2% |
| 1h out-of-sample (30%, Feb - Oct 2026) | 16 | 56.2% | +0.12R (95% CI -0.38 .. +0.62) | 1.26 | 4.0% |
| 1h walk-forward OOS (6m train / 2m test, 72-config grid) | 68 | 48.5% | +0.41R (95% CI +0.07 .. +0.76, p = 0.013) | n/a | 5.9% |
| Daily 2010-2026, TPW08 rules | 8 | 50.0% | -0.02R | 0.96 | 4.3% |
| Daily walk-forward OOS (4y train / 1y test) | 26 | 42.3% | +0.12R (p = 0.33) | n/a | 6.1% |

**Verdict: edge not proven (mixed evidence, 3 of 6 validation criteria pass).**

* The headline TPW08 numbers reappear **only in-sample** on 1h data. Out-of-sample the win rate drops to 56% and the
  confidence interval of the expectancy includes zero.
* The (12, 30, 60) parameters were reportedly optimised on 2024-2026, the same period as all available 1h data. Even
  our out-of-sample segment is therefore not fully independent of the parameter choice.
* On the only truly independent history (daily since 2010) the written rules fire just 8 times in ~17 years, with
  expectancy indistinguishable from zero.
* The most encouraging evidence: on 1h the strategy beats 500 random-entry simulations that use the same exits
  (empirical p = 0.028; long-only random p = 0.018), and the 1h walk-forward is positive. However, this covers ~2.4 years
  of a single strong gold bull market, and the p-values are not corrected for the 147 configurations tested.
* Parameter robustness is weak. In the 1h Tenkan x Kijun grid, 72% of cells are positive in-sample but only 36%
  out-of-sample, and the IS/OOS rank correlation is 0.23.
* An ATR trailing stop (2 x ATR, no fixed TP) raised 1h expectancy (IS/OOS +0.41R/+0.46R vs +0.30R/+0.12R) but did
  **not** reduce drawdown (5.0%/5.4% vs 4.2%/4.0%). Drawdown is driven mainly by risk per trade: Monte Carlo 95th-percentile
  DD is 8.0% at 1% risk, and the claimed 15% corresponds to roughly 2% risk per trade.
* For context, buying and holding gold over the 1h window returned +76% (max DD 29%), while the strategy returned
  +15% at 1% risk (max DD 4.2%).

**Manual journal audit** (`journals/template-backtest.csv`, 9 trades, Jan-Mar 2025): 9/9 recorded take-profits
(Wilson 95% CI 70-100%). The average planned reward:risk is only 0.93R, so the break-even win rate is 52%. 8 of 9
trades are longs while gold rose 17% that quarter. One exit date (1 Feb 2025) falls on a Saturday. A rough check
against futures 1h data confirms the TP was hit first for only 4 of the 9 trades, and SL first for 1.

Full reports (in Indonesian):
[`reports/01_audit_jurnal_manual.md`](reports/01_audit_jurnal_manual.md) and
[`reports/02_ichimoku_rsi.md`](reports/02_ichimoku_rsi.md).

## Repository layout

```
src/trading_research/
  data.py                   download + cache OHLC from Yahoo (XAUUSD=X, fallback GC=F) into data/ (git-ignored)
  indicators.py             Ichimoku, Wilder RSI, ATR (SMA or Wilder), all causal, no TA-Lib
  strategy_ichimoku_rsi.py  TPW08 rules -> signal / stop / target / trailing distances
  backtest.py               bar-by-bar engine: next-bar-open fills, bid/ask, conservative intrabar SL/TP,
                            gap fills, slippage, commission, swap, %-risk sizing, optional lot rounding
  metrics.py                R-multiples, expectancy, win rate, PF, payoff, MaxDD, CAGR, Sharpe, MAE/MFE,
                            Wilson CI, bootstrap CI, t-test
  validation.py             IS/OOS split, grid search, rolling walk-forward, Monte Carlo DD, random-entry null model
  journal.py                legacy journal audit, price cross-check, v2 journal loader
  report_*.py, plotting.py  report generation
scripts/run_all.py          regenerates every report, figure and reports/summary.json
tests/                      34 pytest tests (indicators vs hand-computed values, SL/TP logic, no-lookahead, ...)
reports/                    generated markdown + PNG figures + summary.json
templates/jurnal_trading_v2.csv   trade-journal template (2 rows marked EXAMPLE)
journals/template-backtest.csv    the original manual journal
```

## How to run

Tested on Windows 11 with Python 3.12.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt     # Linux/macOS: .venv/bin/python
.venv/Scripts/python -m pip install -e .                    # makes `import trading_research` work anywhere
.venv/Scripts/python -m pytest -q                           # 34 tests
.venv/Scripts/python scripts/run_all.py                     # ~2-3 minutes; downloads data on first run
.venv/Scripts/python scripts/run_all.py --refresh           # re-download data (numbers will change)
.venv/Scripts/python scripts/run_all.py --quick             # fewer simulations
```

Using the library on your own data (for example an MT5 export):

```python
import pandas as pd
from trading_research.strategy_ichimoku_rsi import TPW08_PARAMS, generate_signals
from trading_research.backtest import run_backtest, BacktestConfig, CostModel
from trading_research.metrics import summarize

df = pd.read_csv("XAUUSD_M15.csv", index_col=0, parse_dates=True)  # columns: open, high, low, close
sig = generate_signals(df, TPW08_PARAMS.with_(trail_atr=2.0, tp_r=None))
res = run_backtest(df, sig, BacktestConfig(risk_pct=0.5, costs=CostModel(spread=0.25)))
print(summarize(res.trades, res.equity))
```

## Methodology notes

* **No lookahead.** Signals are decided on a bar's close and filled at the next bar's open. The Ichimoku cloud is
  shifted forward, so the cloud at bar *t* only uses data up to *t - displacement*. The Chikou span is never used.
  Tests recompute indicators, signals and trades on truncated data and require identical history.
* **Conservative fills.** If a bar touches both the stop and the target, the stop is assumed to come first. Gaps
  through the stop fill at the open. Trailing stops update on the close and become active on the next bar.
* **Validation.** Chronological 70/30 split, rolling walk-forward with re-optimisation, bootstrap confidence intervals,
  a random-entry null model with identical exits (both 50/50 and long-only), and a Monte Carlo resample of trade order
  for the drawdown distribution. The report counts how many configurations were tried.

## Limitations

* `GC=F` is a futures series, not the spot/CFD price at an MT5 broker. Basis, contract rolls, session hours and daily
  candle cut-off times differ.
* Yahoo only provides about 730 days of 1h data and 60 days of 15m data, so the original M15 2024-2026 test cannot be
  reproduced here. There is no tick data, so the intrabar path is unknown.
* Spreads are constant in the model. Real spreads widen around news and rollover. Swap is approximated pro rata.
* Stop-loss/take-profit rules, the short-side RSI condition and the cross definition had to be assumed.
* Most of the 1h sample is a single strong uptrend regime.
* Uncorrected multiple testing: 147 configurations.

## License

MIT, see [LICENSE](LICENSE). Indonesian summary: [README.id.md](README.id.md).
