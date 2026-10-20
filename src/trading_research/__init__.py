"""Honest, reproducible research tools for XAUUSD (gold) trading strategies.

Modules
-------
data        download and cache OHLC data (yfinance)
indicators  Ichimoku, RSI, ATR (own implementations)
strategy_ichimoku_rsi  signal generation for the Ichimoku-RSI-Delta strategy
backtest    bar-by-bar engine with conservative intrabar SL/TP, costs, %-risk sizing
metrics     R-multiples, expectancy, PF, MaxDD, CAGR, Sharpe, MAE/MFE
validation  IS/OOS split, walk-forward, Monte Carlo, random-entry baseline
journal     manual trade journal loading and audit
"""

__version__ = "0.1.0"
