"""Build reports/02_ichimoku_rsi.md: reconstruction and validation of the TPW08 strategy."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from .backtest import BacktestConfig, CostModel
from .data import DataMeta
from .metrics import cagr, equity_from_r, max_drawdown, summarize
from .plotting import CRITICAL, INK_2, MUTED, SERIES, heatmap, plt, save, setup_style
from .report_utils import md_table, num, pct, pval, rr
from .strategy_ichimoku_rsi import TPW08_PARAMS, StrategyParams, generate_signals
from .validation import (backtest_window, grid_search, make_grid, monte_carlo_dd, random_entry_baseline, split_is_oos,
                         walk_forward)

CLAIM = {"win_rate": 0.65, "max_dd": 0.15, "profit_factor": 1.85, "trades": 200, "months": 24}

TRAIL_VARIANTS: list[tuple[str, StrategyParams]] = [
    ("A. Baseline: SL 1.5 ATR, TP 1R", TPW08_PARAMS),
    ("B. Trailing 1.5 ATR, tanpa TP", TPW08_PARAMS.with_(tp_r=None, trail_atr=1.5)),
    ("C. Trailing 2 ATR, tanpa TP", TPW08_PARAMS.with_(tp_r=None, trail_atr=2.0)),
    ("D. Trailing 3 ATR, tanpa TP", TPW08_PARAMS.with_(tp_r=None, trail_atr=3.0)),
    ("E. Trailing 2 ATR + TP 2R", TPW08_PARAMS.with_(tp_r=2.0, trail_atr=2.0)),
]

WF_AXES = dict(tenkan=[9, 12], kijun=[26, 30], rsi_delta=[0.0, 3.0, 5.0], sl_atr=[1.0, 1.5, 2.0], tp_r=[1.0, 2.0])


def _seg(df, sig, start, end, cfg):
    res = backtest_window(df, sig, start, end, cfg)
    s = summarize(res.trades, res.equity)
    t = res.trades
    s["exp_long"] = float(t.loc[t["direction"] == 1, "r_multiple"].mean()) if (t["direction"] == 1).any() else np.nan
    s["exp_short"] = float(t.loc[t["direction"] == -1, "r_multiple"].mean()) if (t["direction"] == -1).any() else np.nan
    return res, s


def _row(name: str, s: dict) -> dict:
    return {"Segmen": name, "Periode": f"{str(s.get('start', ''))[:10]} - {str(s.get('end', ''))[:10]}",
            "Trade (L/S)": f"{s['trades']} ({s['long_trades']}/{s['short_trades']})", "Win rate": pct(s["win_rate"]),
            "Expectancy": rr(s["expectancy_r"]),
            "CI95 expectancy": f"{rr(s['expectancy_ci_low'])} .. {rr(s['expectancy_ci_high'])}",
            "p (E>0)": pval(s["p_value_mean_r_gt_0"]), "PF": num(s["profit_factor"]), "MaxDD": pct(s.get("max_dd")),
            "CAGR": pct(s.get("cagr")), "Sharpe": num(s.get("sharpe")), "E long": rr(s["exp_long"]),
            "E short": rr(s["exp_short"]), "MAE/MFE rata2": f"{num(s['mae_r_mean'])} / {num(s['mfe_r_mean'])}"}


def _bh(close: pd.Series) -> dict:
    return {"return": float(close.iloc[-1] / close.iloc[0] - 1), "cagr": cagr(close), "max_dd": max_drawdown(close)}


def build(root: Path, data: dict[str, tuple[pd.DataFrame, DataMeta]], quick: bool = False) -> dict:
    reports = root / "reports"
    figs = reports / "figures"
    setup_style()
    cfg = BacktestConfig()
    P = TPW08_PARAMS
    n_null = 100 if quick else 500
    n_mc = 2000 if quick else 10000
    out: dict = {"params": P.to_dict(), "costs": cfg.costs.__dict__, "risk_pct": cfg.risk_pct, "timeframes": {}}
    configs_tested = 0

    # ------------------------------------------------------------------ baseline per timeframe
    base_rows, seg_results, splits, sigs = [], {}, {}, {}
    for tf in ("1d", "1h", "15m"):
        df, meta = data[tf]
        sig = generate_signals(df, P)
        sigs[tf] = sig
        b = split_is_oos(df.index, 0.7)
        splits[tf] = b
        segs = {"ALL": (None, None), "IS 70%": (None, b), "OOS 30%": (b, None)}
        tfo = {"ticker": meta.ticker, "bars": len(df), "first": meta.first, "last": meta.last, "split": str(b)}
        for name, (a, z) in segs.items():
            res, s = _seg(df, sig, a, z, cfg)
            seg_results[(tf, name)] = res
            base_rows.append({"TF": tf, **_row(name, s)})
            tfo[name] = {k: v for k, v in s.items() if not isinstance(v, np.ndarray)}
        tfo["buy_hold"] = _bh(df["close"])
        tfo["buy_hold_oos"] = _bh(df.loc[df.index >= b, "close"])
        out["timeframes"][tf] = tfo
    configs_tested += 1
    base_tab = pd.DataFrame(base_rows)

    # ------------------------------------------------------------------ random-entry null model
    null = {}
    for tf in ("1d", "1h"):
        df, _ = data[tf]
        sig = sigs[tf]
        n_sig = int(seg_results[(tf, "ALL")].trades.shape[0])
        obs = out["timeframes"][tf]["ALL"]["expectancy_r"]
        for mode in ("random", "long"):
            nb = random_entry_baseline(df, sig, n_sig, cfg, n_sims=n_null, mode=mode, seed=11)
            e = nb["expectancy_r"].dropna().to_numpy()
            p_emp = (np.sum(e >= obs) + 1) / (len(e) + 1)
            null[(tf, mode)] = {"mean": float(e.mean()), "p95": float(np.quantile(e, 0.95)), "p_emp": float(p_emp),
                                "samples": e, "obs": obs, "n": n_sig}
    out["null"] = {f"{k[0]}_{k[1]}": {kk: vv for kk, vv in v.items() if kk != "samples"} for k, v in null.items()}
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8))
    for ax, tf in zip(axes, ("1h", "1d")):
        for mode, col, lab in (("random", SERIES[0], "acak (arah 50/50)"), ("long", SERIES[1], "acak (long saja)")):
            ax.hist(null[(tf, mode)]["samples"], bins=30, alpha=0.55, color=col, label=f"Entry {lab}")
        ax.axvline(null[(tf, "random")]["obs"], color=CRITICAL, linewidth=2, label="Strategi TPW08")
        ax.set_title(f"{tf}: expectancy strategi vs entry acak (n={null[(tf, 'random')]['n']})")
        ax.set_xlabel("Expectancy per trade (R)")
        ax.set_ylabel("Jumlah simulasi")
        ax.legend(loc="upper left")
    save(fig, figs / "02_random_baseline.png")

    # ------------------------------------------------------------------ equity curves
    for tf in ("1h", "1d"):
        df, meta = data[tf]
        fig, ax = plt.subplots(figsize=(10, 4))
        eq = seg_results[(tf, "ALL")].equity
        ax.plot(eq.index, (eq / eq.iloc[0] - 1) * 100, color=SERIES[0], label=P.label())
        if tf == "1h":
            alt = TRAIL_VARIANTS[2][1]
            r2, _ = _seg(df, generate_signals(df, alt), None, None, cfg)
            ax.plot(r2.equity.index, (r2.equity / r2.equity.iloc[0] - 1) * 100, color=SERIES[2], label=TRAIL_VARIANTS[2][0])
        bh = df["close"]
        ax.plot(bh.index, (bh / bh.iloc[0] - 1) * 100, color=MUTED, linewidth=1.2, label=f"Buy & hold {meta.ticker} (100% modal)")
        ax.axvline(splits[tf], color=INK_2, linestyle="--", linewidth=1)
        ax.text(splits[tf], ax.get_ylim()[1], "  OOS ->", color=INK_2, fontsize=8, va="top")
        ax.set_ylabel("Return kumulatif (%)")
        ax.set_title(f"Kurva ekuitas {tf} (risk {cfg.risk_pct:g}% per trade, biaya termasuk)")
        ax.legend(loc="upper left")
        save(fig, figs / f"02_equity_{tf}.png")

    # ------------------------------------------------------------------ robustness grids
    df1h, _ = data["1h"]
    b1h = splits["1h"]
    cache: dict = {}
    tk_vals, kj_vals = [7, 9, 12, 15, 18], [22, 26, 30, 34, 40]
    g1 = make_grid(P, tenkan=tk_vals, kijun=kj_vals)
    is1 = grid_search(df1h, g1, None, b1h, cfg, cache)
    oos1 = grid_search(df1h, g1, b1h, None, cfg, cache)
    rd_vals, sl_vals = [0.0, 2.0, 5.0, 8.0, 10.0], [1.0, 1.5, 2.0, 2.5]
    g2 = make_grid(P, rsi_delta=rd_vals, sl_atr=sl_vals)
    is2 = grid_search(df1h, g2, None, b1h, cfg, cache)
    oos2 = grid_search(df1h, g2, b1h, None, cfg, cache)
    df1d, _ = data["1d"]
    g3 = make_grid(P, tenkan=tk_vals, kijun=kj_vals)
    all3 = grid_search(df1d, g3, None, None, cfg)
    configs_tested += len(g1) + len(g2) + len(g3)

    def mat(tab, xk, xv, yk, yv, col):
        m = np.full((len(yv), len(xv)), np.nan)
        for _, r in tab.iterrows():
            m[yv.index(r[yk]), xv.index(r[xk])] = r[col]
        return m

    vlim = 0.8
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    for ax, tab, nm in ((axes[0], is1, "IS 70%"), (axes[1], oos1, "OOS 30%")):
        heatmap(ax, mat(tab, "kijun", kj_vals, "tenkan", tk_vals, "expectancy_r"),
                mat(tab, "kijun", kj_vals, "tenkan", tk_vals, "trades"), kj_vals, tk_vals,
                f"1h {nm}: expectancy (R) per kombinasi", "Kijun (Senkou B = 2x Kijun)", "Tenkan", vlim)
    save(fig, figs / "02_heatmap_1h_ichimoku.png")
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.4))
    for ax, tab, nm in ((axes[0], is2, "IS 70%"), (axes[1], oos2, "OOS 30%")):
        heatmap(ax, mat(tab, "sl_atr", sl_vals, "rsi_delta", rd_vals, "expectancy_r"),
                mat(tab, "sl_atr", sl_vals, "rsi_delta", rd_vals, "trades"), sl_vals, rd_vals,
                f"1h {nm}: expectancy (R), Ichimoku 12/30/60", "SL (x ATR), TP = 1R", "Ambang RSI delta", vlim)
    save(fig, figs / "02_heatmap_1h_rsi_sl.png")
    fig, ax = plt.subplots(figsize=(6.5, 4.8))
    heatmap(ax, mat(all3, "kijun", kj_vals, "tenkan", tk_vals, "expectancy_r"),
            mat(all3, "kijun", kj_vals, "tenkan", tk_vals, "trades"), kj_vals, tk_vals,
            "Harian 2010-sekarang: expectancy (R)", "Kijun (Senkou B = 2x Kijun)", "Tenkan", vlim)
    save(fig, figs / "02_heatmap_1d_ichimoku.png")

    def rank_corr(a, b, min_n=5):
        m = (a["trades"] >= min_n) & (b["trades"] >= min_n)
        if m.sum() < 5:
            return float("nan"), int(m.sum())
        rho = stats.spearmanr(a.loc[m, "expectancy_r"], b.loc[m, "expectancy_r"]).statistic
        return float(rho), int(m.sum())

    rho1, n1 = rank_corr(is1, oos1)
    rho2, n2 = rank_corr(is2, oos2)
    best_is1 = is1.loc[is1["expectancy_r"].idxmax()]
    best_is1_oos = oos1.loc[best_is1.name]
    tpw_cell_oos = oos1[(oos1["tenkan"] == 12) & (oos1["kijun"] == 30)].iloc[0]
    out["grid"] = {
        "ichimoku_1h_spearman_is_oos": rho1, "ichimoku_1h_cells": n1,
        "rsi_sl_1h_spearman_is_oos": rho2, "rsi_sl_1h_cells": n2,
        "ichimoku_1h_share_oos_positive": float((oos1["expectancy_r"] > 0).mean()),
        "ichimoku_1h_share_is_positive": float((is1["expectancy_r"] > 0).mean()),
        "ichimoku_1d_share_positive": float((all3["expectancy_r"] > 0).mean()),
        "ichimoku_1d_median_trades": float(all3["trades"].median()),
        "best_is_1h": best_is1["params"].label(), "best_is_1h_is_exp": float(best_is1["expectancy_r"]),
        "best_is_1h_oos_exp": float(best_is1_oos["expectancy_r"]), "best_is_1h_oos_trades": int(best_is1_oos["trades"]),
    }

    # ------------------------------------------------------------------ walk-forward
    wf_grid = make_grid(P, **WF_AXES)
    configs_tested += len(wf_grid)
    wf = {}
    wf_specs = {"1h": (pd.DateOffset(months=6), pd.DateOffset(months=2), 10, "6 bulan latih / 2 bulan uji"),
                "1d": (pd.DateOffset(years=4), pd.DateOffset(years=1), 5, "4 tahun latih / 1 tahun uji")}
    for tf, (tr, te, mt, desc) in wf_specs.items():
        df, _ = data[tf]
        res = walk_forward(df, wf_grid, tr, te, cfg, objective="expectancy_r", min_trades=mt)
        r = res.oos_r
        s = summarize(res.oos_trades, None) if len(res.oos_trades) else {"trades": 0}
        wf[tf] = (res, s, desc, mt)
        out.setdefault("walk_forward", {})[tf] = {
            "desc": desc, "windows": len(res.windows), "oos_trades": int(len(r)),
            "oos_expectancy_r": float(r.mean()) if len(r) else float("nan"),
            "oos_win_rate": float((r > 0).mean()) if len(r) else float("nan"),
            "oos_p_value": s.get("p_value_mean_r_gt_0", float("nan")),
            "oos_ci": [s.get("expectancy_ci_low"), s.get("expectancy_ci_high")],
            "oos_max_dd_1pct": max_drawdown(equity_from_r(r, 1.0)) if len(r) else float("nan"),
        }
    fig, ax = plt.subplots(figsize=(10, 3.8))
    for (tf, col) in (("1h", SERIES[0]), ("1d", SERIES[1])):
        t = wf[tf][0].oos_trades
        if len(t):
            x = pd.to_datetime(t["exit_time"])
            if x.dt.tz is not None:
                x = x.dt.tz_convert(None)
            ax.step(x, t["r_multiple"].cumsum(), where="post", color=col, label=f"{tf} walk-forward OOS ({len(t)} trade)")
    ax.axhline(0, color=MUTED, linewidth=1)
    ax.set_ylabel("Kumulatif R")
    ax.set_title("Walk-forward: hanya trade out-of-sample, parameter dipilih ulang tiap jendela")
    ax.legend(loc="upper left")
    save(fig, figs / "02_walk_forward.png")

    # ------------------------------------------------------------------ ATR trailing variants
    trail_rows = []
    configs_tested += len(TRAIL_VARIANTS) - 1
    out["trailing"] = {}
    for tf in ("1h", "1d"):
        df, _ = data[tf]
        for name, p in TRAIL_VARIANTS:
            sg = generate_signals(df, p)
            for seg, (a, z) in {"IS": (None, splits[tf]), "OOS": (splits[tf], None)}.items():
                _, s = _seg(df, sg, a, z, cfg)
                trail_rows.append({"TF": tf, "Varian": name, "Segmen": seg, "Trade": s["trades"], "Win rate": pct(s["win_rate"]),
                                   "Expectancy": rr(s["expectancy_r"]), "PF": num(s["profit_factor"]),
                                   "MaxDD": pct(s.get("max_dd")), "MFE rata2": num(s["mfe_r_mean"])})
                out["trailing"][f"{tf}|{name}|{seg}"] = {"trades": s["trades"], "expectancy_r": s["expectancy_r"],
                                                         "win_rate": s["win_rate"], "max_dd": s.get("max_dd"),
                                                         "profit_factor": s["profit_factor"]}
    trail_tab = pd.DataFrame(trail_rows)

    # ------------------------------------------------------------------ Monte Carlo drawdown
    r1h = seg_results[("1h", "ALL")].r
    mc_rows = []
    mc_samples = None
    for lab, r in (("1h baseline (semua trade)", r1h), ("1h walk-forward OOS", wf["1h"][0].oos_r)):
        for risk in (0.5, 1.0, 2.0):
            mc = monte_carlo_dd(r, risk_pct=risk, n_sims=n_mc, seed=5)
            if lab.startswith("1h baseline") and risk == 1.0:
                mc_samples = mc["dd_samples"]
                out["monte_carlo_1h_1pct"] = {k: v for k, v in mc.items() if k != "dd_samples"}
            mc_rows.append({"Sampel trade": lab, "n": mc["n_trades"], "Risk/trade": f"{risk:g}%",
                            "DD historis": pct(mc["historical_dd"]), "DD median": pct(mc["dd_median"]),
                            "DD 95%": pct(mc["dd_95"]), "DD 99%": pct(mc["dd_99"]),
                            "P(rugi setelah n trade)": pct(mc["p_loss"])})
    risk_for_15 = float("nan")
    for risk in np.arange(0.25, 10.01, 0.25):
        if monte_carlo_dd(r1h, risk_pct=float(risk), n_sims=2000, seed=9)["dd_95"] >= 0.15:
            risk_for_15 = float(risk)
            break
    out["risk_pct_for_dd95_15pct"] = risk_for_15
    mc_tab = pd.DataFrame(mc_rows)
    fig, ax = plt.subplots(figsize=(8, 3.6))
    ax.hist(mc_samples * 100, bins=40, color=SERIES[0], alpha=0.8)
    q95 = np.quantile(mc_samples, 0.95) * 100
    ax.axvline(q95, color=INK_2, linestyle="--", linewidth=1.5)
    ax.text(q95, ax.get_ylim()[1] * 0.92, f" DD 95% = {q95:.1f}%", color=INK_2, fontsize=9)
    ax.set_xlabel("Max drawdown (%) pada risk 1% per trade")
    ax.set_ylabel("Jumlah simulasi")
    ax.set_title(f"Monte Carlo (bootstrap {len(r1h)} trade 1h, {n_mc:,} simulasi)")
    save(fig, figs / "02_monte_carlo_dd.png")

    # ------------------------------------------------------------------ cost sensitivity
    cost_rows = []
    for tf in ("1h", "15m"):
        df, _ = data[tf]
        for spread in (0.0, 0.2, 0.3, 0.4, 0.8, 2.0):
            c = BacktestConfig(costs=CostModel(spread=spread))
            res = backtest_window(df, sigs[tf], None, None, c)
            s = summarize(res.trades, res.equity)
            cost_rows.append({"TF": tf, "Spread (USD)": f"{spread:.1f}", "Trade": s["trades"],
                              "Expectancy": rr(s["expectancy_r"], 3), "PF": num(s["profit_factor"]), "Win rate": pct(s["win_rate"])})
    cost_tab = pd.DataFrame(cost_rows)
    sl_med = {tf: float((sigs[tf].loc[sigs[tf]["signal"] != 0, "sl_dist"]).median()) for tf in ("1d", "1h", "15m")}
    out["median_sl_usd"] = sl_med

    # ------------------------------------------------------------------ MAE / MFE figure
    t1h = seg_results[("1h", "ALL")].trades
    fig, ax = plt.subplots(figsize=(7, 4))
    win = t1h["r_multiple"] > 0
    ax.scatter(t1h.loc[win, "mae_r"], t1h.loc[win, "mfe_r"], s=36, color=SERIES[0], label="Trade untung", edgecolor="#fcfcfb")
    ax.scatter(t1h.loc[~win, "mae_r"], t1h.loc[~win, "mfe_r"], s=36, color=SERIES[1], label="Trade rugi", edgecolor="#fcfcfb")
    ax.set_xlabel("MAE (R)")
    ax.set_ylabel("MFE (R)")
    ax.set_title("1h baseline: excursion maksimum per trade")
    ax.legend(loc="upper left")
    save(fig, figs / "02_mae_mfe_1h.png")

    out["configs_tested"] = configs_tested

    # ------------------------------------------------------------------ verdict
    o1h = out["timeframes"]["1h"]["OOS 30%"]
    a1h = out["timeframes"]["1h"]["ALL"]
    a1d = out["timeframes"]["1d"]["ALL"]
    wf1h = out["walk_forward"]["1h"]
    crit = {
        "OOS 1h: batas bawah CI95 expectancy > 0": bool(np.isfinite(o1h["expectancy_ci_low"]) and o1h["expectancy_ci_low"] > 0),
        "Walk-forward 1h: expectancy OOS > 0 dengan p < 0.05": bool(np.isfinite(wf1h["oos_p_value"]) and wf1h["oos_p_value"] < 0.05
                                                                and wf1h["oos_expectancy_r"] > 0),
        "Mengalahkan 95% entry acak (1h)": bool(null[("1h", "random")]["p_emp"] < 0.05),
        "Mengalahkan 95% entry acak long-only (1h)": bool(null[("1h", "long")]["p_emp"] < 0.05),
        "Harian 2010-sekarang: >= 30 trade dan expectancy > 0": bool(a1d["trades"] >= 30 and a1d["expectancy_r"] > 0),
        "Peringkat IS dan OOS di grid berkorelasi positif (Spearman > 0.3)": bool(np.isfinite(rho1) and rho1 > 0.3),
    }
    passed = sum(crit.values())
    proven = all(crit.values())
    out["verdict"] = {"criteria": crit, "passed": passed, "total": len(crit), "edge_proven": proven}

    # ------------------------------------------------------------------ markdown
    tfs = out["timeframes"]
    claim_tab = pd.DataFrame([
        {"Metrik": "Win rate", "Klaim TPW08 (M15 2024-2026)": "65%", "1h IS": pct(tfs["1h"]["IS 70%"]["win_rate"]),
         "1h OOS": pct(o1h["win_rate"]), "1h walk-forward OOS": pct(wf1h["oos_win_rate"]), "Harian 2010-sekarang": pct(a1d["win_rate"])},
        {"Metrik": "Profit factor", "Klaim TPW08 (M15 2024-2026)": "1.85", "1h IS": num(tfs["1h"]["IS 70%"]["profit_factor"]),
         "1h OOS": num(o1h["profit_factor"]), "1h walk-forward OOS": "-", "Harian 2010-sekarang": num(a1d["profit_factor"])},
        {"Metrik": "Max drawdown", "Klaim TPW08 (M15 2024-2026)": "15% (risk/trade tidak disebut)",
         "1h IS": pct(tfs["1h"]["IS 70%"]["max_dd"]), "1h OOS": pct(o1h["max_dd"]),
         "1h walk-forward OOS": pct(wf1h["oos_max_dd_1pct"]), "Harian 2010-sekarang": pct(a1d["max_dd"])},
        {"Metrik": "Jumlah trade", "Klaim TPW08 (M15 2024-2026)": ">200 / 24 bulan",
         "1h IS": str(tfs["1h"]["IS 70%"]["trades"]), "1h OOS": str(o1h["trades"]),
         "1h walk-forward OOS": str(wf1h["oos_trades"]), "Harian 2010-sekarang": str(a1d["trades"])},
        {"Metrik": "Expectancy per trade", "Klaim TPW08 (M15 2024-2026)": "tidak dilaporkan",
         "1h IS": rr(tfs["1h"]["IS 70%"]["expectancy_r"]), "1h OOS": rr(o1h["expectancy_r"]),
         "1h walk-forward OOS": rr(wf1h["oos_expectancy_r"]), "Harian 2010-sekarang": rr(a1d["expectancy_r"])},
    ])
    crit_md = "\n".join(f"| {k} | {'LULUS' if v else 'GAGAL'} |" for k, v in crit.items())
    wf_tabs = ""
    for tf in ("1h", "1d"):
        res, s, desc, mt = wf[tf]
        w = res.windows.copy()
        for c in ("train_start", "train_end", "test_end"):
            w[c] = pd.to_datetime(w[c]).dt.strftime("%Y-%m-%d")
        w = w[["window", "train_start", "train_end", "test_end", "chosen", "is_trades", "is_expectancy_r", "oos_trades", "oos_expectancy_r"]]
        w.columns = ["#", "Latih mulai", "Uji mulai", "Uji selesai", "Parameter terpilih", "Trade IS", "E IS", "Trade OOS", "E OOS"]
        wo = out["walk_forward"][tf]
        wf_tabs += f"""
### Walk-forward {tf} ({desc}, minimal {mt} trade di data latih)

Hasil gabungan OOS: **{wo['oos_trades']} trade, win rate {pct(wo['oos_win_rate'])}, expectancy {rr(wo['oos_expectancy_r'])}**
(CI95 {rr(wo['oos_ci'][0])} .. {rr(wo['oos_ci'][1])}, p = {pval(wo['oos_p_value'])}), MaxDD pada risk 1%: {pct(wo['oos_max_dd_1pct'])}.

<details><summary>Detail per jendela</summary>

{md_table(w, {"E IS": rr, "E OOS": rr})}

</details>
"""
    g = out["grid"]
    nr, nl = null[("1h", "random")], null[("1h", "long")]
    dr, dl = null[("1d", "random")], null[("1d", "long")]
    bh1h = tfs["1h"]["buy_hold"]
    if proven:
        verdict_line = "**Edge TERBUKTI menurut semua kriteria di bagian 10.** Tetap lakukan paper trading sebelum memakai uang nyata."
    elif passed >= len(crit) / 2:
        verdict_line = (f"**Edge BELUM TERBUKTI (bukti campuran).** {passed} dari {len(crit)} kriteria validasi lulus. Ada sinyal positif "
                        "pada data 1h 2024-2026, tetapi tidak konsisten di semua uji dan hanya berasal dari satu regime pasar (tren naik emas).")
    else:
        verdict_line = (f"**Edge TIDAK TERBUKTI.** Hanya {passed} dari {len(crit)} kriteria validasi yang lulus.")
    is1h = tfs["1h"]["IS 70%"]
    claim_line = (f"Angka klaim TPW08 (WR 65%, PF 1.85) hanya muncul **in-sample** (1h IS: WR {pct(is1h['win_rate'])}, PF {num(is1h['profit_factor'])}). "
                  f"Di out-of-sample turun ke WR {pct(o1h['win_rate'])} / PF {num(o1h['profit_factor'])}, dan walk-forward 1h WR {pct(wf1h['oos_win_rate'])}.")
    wf1d = out["walk_forward"]["1d"]
    sig_word = lambda pv: "tidak berbeda signifikan dari nol" if not (np.isfinite(pv) and pv < 0.05) else "positif secara signifikan (p < 0.05)"
    tr = out["trailing"]
    A_is, A_oos = tr["1h|" + TRAIL_VARIANTS[0][0] + "|IS"], tr["1h|" + TRAIL_VARIANTS[0][0] + "|OOS"]
    C_is, C_oos = tr["1h|" + TRAIL_VARIANTS[2][0] + "|IS"], tr["1h|" + TRAIL_VARIANTS[2][0] + "|OOS"]
    exp_better = C_is["expectancy_r"] > A_is["expectancy_r"] and C_oos["expectancy_r"] > A_oos["expectancy_r"]
    dd_lower = C_is["max_dd"] < A_is["max_dd"] and C_oos["max_dd"] < A_oos["max_dd"]
    mc1 = out["monte_carlo_1h_1pct"]
    d15 = (pd.Timestamp(tfs['15m']['last']) - pd.Timestamp(tfs['15m']['first'])).days
    rate15 = tfs['15m']['ALL']['trades'] / max(d15, 1) * 730
    conclusions = [
        f"**Frekuensi sinyal.** Aturan entry TPW08 menghasilkan {tfs['1h']['ALL']['trades']} trade dalam ~2,4 tahun di 1h, jauh dari "
        f"\">200 trade per 24 bulan\". Di data 15m (60 hari) ada {tfs['15m']['ALL']['trades']} trade, setara ~{rate15:.0f} trade per 24 bulan, "
        "jadi klaim jumlah trade masuk akal untuk M15, tetapi sampel 15m terlalu pendek untuk menilai kualitasnya.",
        f"**In-sample vs out-of-sample.** {claim_line} Parameter (12, 30, 60) menurut dokumen sudah \"dioptimasi\" pada 2024-2026, "
        "periode yang sama dengan seluruh data 1h. Jadi segmen OOS di sini pun belum sepenuhnya independen dari pemilihan parameter TPW08.",
        f"**Data independen (harian 2010-sekarang).** Aturan TPW08 hanya memberi {a1d['trades']} trade (expectancy {rr(a1d['expectancy_r'])}). "
        f"Walk-forward harian: {wf1d['oos_trades']} trade, expectancy {rr(wf1d['oos_expectancy_r'])}, p = {pval(wf1d['oos_p_value'])}, "
        f"artinya {sig_word(wf1d['oos_p_value'])}.",
        (f"**Temuan paling menjanjikan: 1h.** Strategi mengungguli entry acak (p empiris {pval(nr['p_emp'])}; long-only {pval(nl['p_emp'])}) "
         f"dan walk-forward 1h positif ({rr(wf1h['oos_expectancy_r'])}, p = {pval(wf1h['oos_p_value'])}). Namun data hanya ~2,4 tahun dalam satu regime, "
         f"p-value belum dikoreksi atas {configs_tested} konfigurasi, dan segmen OOS 30% saja ({o1h['trades']} trade) {sig_word(o1h['p_value_mean_r_gt_0'])}."
         if nr["p_emp"] < 0.05 else
         f"**1h tidak lebih baik dari entry acak** (p empiris {pval(nr['p_emp'])}; long-only {pval(nl['p_emp'])})."),
        f"**Trailing ATR (proposal UAS).** Varian C (trailing 2 ATR, tanpa TP) di 1h: expectancy IS/OOS {rr(C_is['expectancy_r'])}/{rr(C_oos['expectancy_r'])} "
        f"vs baseline {rr(A_is['expectancy_r'])}/{rr(A_oos['expectancy_r'])}; MaxDD {pct(C_is['max_dd'])}/{pct(C_oos['max_dd'])} vs "
        f"{pct(A_is['max_dd'])}/{pct(A_oos['max_dd'])}. Trailing {'meningkatkan' if exp_better else 'tidak konsisten meningkatkan'} expectancy dan "
        f"{'menurunkan' if dd_lower else 'tidak menurunkan'} drawdown. Drawdown terutama ditentukan oleh **risk per trade**: pada risk 1%, "
        f"DD Monte Carlo persentil 95 = {pct(mc1['dd_95'])}, sedangkan DD 15% setara risk sekitar {num(risk_for_15)}% per trade.",
    ]
    conclusions_md = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(conclusions))
    md = f"""# 02 - Rekonstruksi dan Validasi Strategi Ichimoku-RSI (XAUUSD)

*Dibuat otomatis oleh `scripts/run_all.py`. Semua angka berasal dari run ini. Data: Yahoo Finance `{tfs['1h']['ticker']}`
(spot `XAUUSD=X` tidak tersedia di Yahoo). Modal awal {num(cfg.initial_equity, 0)} USD, risk {cfg.risk_pct:g}% equity per trade.*

## TL;DR

{verdict_line}

{claim_line}

* **1h ({tfs['1h']['first'][:10]} - {tfs['1h']['last'][:10]}), parameter TPW08:** in-sample {tfs['1h']['IS 70%']['trades']} trade,
  WR {pct(tfs['1h']['IS 70%']['win_rate'])}, expectancy {rr(tfs['1h']['IS 70%']['expectancy_r'])}. Out-of-sample {o1h['trades']} trade,
  WR {pct(o1h['win_rate'])}, expectancy {rr(o1h['expectancy_r'])} (CI95 {rr(o1h['expectancy_ci_low'])} .. {rr(o1h['expectancy_ci_high'])}).
* **Walk-forward 1h:** {wf1h['oos_trades']} trade OOS, expectancy {rr(wf1h['oos_expectancy_r'])}, p = {pval(wf1h['oos_p_value'])}.
* **Harian 2010-sekarang:** aturan TPW08 hanya menghasilkan **{a1d['trades']} trade dalam ~{(pd.Timestamp(tfs['1d']['last']) - pd.Timestamp(tfs['1d']['first'])).days / 365.25:.0f} tahun**,
  dengan expectancy {rr(a1d['expectancy_r'])}. Ini satu-satunya data yang benar-benar independen dari periode
  "optimasi" TPW08 (2024-2026).
* **Pembanding:** buy & hold emas selama periode 1h memberi {pct(bh1h['return'])} (MaxDD {pct(bh1h['max_dd'])}),
  sedangkan strategi pada risk 1% memberi {pct(tfs['1h']['ALL']['total_return'])} (MaxDD {pct(tfs['1h']['ALL']['max_dd'])}).
* **Multiple testing:** laporan ini mencoba {configs_tested} konfigurasi. Nilai p yang tidak dikoreksi akan terlihat lebih
  bagus dari kenyataannya.

## 1. Aturan yang diekstrak dari dokumen TPW08

| Aspek | Isi dokumen | Implementasi di repo |
|---|---|---|
| Instrumen / timeframe | XAUUSD, M15, backtest 24 bulan (2024-2026), >200 trade | 1h (~2,4 tahun) dan harian (2010-sekarang). M15 Yahoo hanya 60 hari (lihat bagian 9) |
| Ichimoku | Parameter "dioptimasi" ke (12, 30, 60) | Tenkan 12, Kijun 30, Senkou B 60, displacement 30 |
| Filter tren | Buy hanya di atas Kumo, Sell hanya di bawah Kumo | `close > max(SpanA, SpanB)` / `close < min(...)` (awan yang sudah digeser = kausal) |
| Trigger | Tenkan memotong Kijun | Cross terjadi di bar yang sama dengan sinyal |
| Momentum | RSI(14), `RSI_t - RSI_t-1 > threshold` (contoh 5) | Ambang 5. Untuk short memakai cermin `< -5` (**asumsi**) |
| Stop loss / take profit | Tidak disebut | **Asumsi:** SL = 1,5 x ATR(14), TP = 1R. WR 65% + PF 1,85 menyiratkan payoff ~1,0 |
| ATR | `ATR = SMA(TR, n)` | ATR SMA 14 (sama dengan iATR di MT5) |
| Position sizing | Risk 1% equity / jarak SL | Risk 1% equity / jarak SL (unit fraksional) |
| Trailing stop (UAS) | `TS = harga - k x ATR` | Diperbarui di close bar, aktif bar berikutnya, hanya bergerak searah profit |
| Eksekusi | MT5, verifikasi latensi tick | Sinyal di close bar t, eksekusi di open bar t+1 |

## 2. Model eksekusi dan biaya

* Harga Yahoo dianggap harga **mid**. Spread {cfg.costs.spread:.2f} USD (beli di ask, jual di bid), slippage
  {cfg.costs.slippage:.2f} USD per order market/stop, komisi {cfg.costs.commission_per_lot:.0f} USD per lot round-turn,
  swap {cfg.costs.swap_long_annual_pct:g}%/tahun (long) dan {cfg.costs.swap_short_annual_pct:g}%/tahun (short) dari nilai nosional.
* SL/TP diperiksa terhadap high/low bar. **Jika SL dan TP tersentuh di bar yang sama, SL dianggap lebih dulu** (konservatif).
  Gap melewati SL diisi di harga open.
* Median jarak SL saat entry: harian {num(sl_med['1d'])} USD, 1h {num(sl_med['1h'])} USD, 15m {num(sl_med['15m'])} USD.
  Biaya round-trip (~{cfg.costs.spread + 2 * cfg.costs.slippage + cfg.costs.commission_per_unit:.2f} USD) setara
  ~{(cfg.costs.spread + 2 * cfg.costs.slippage + cfg.costs.commission_per_unit) / sl_med['1h'] * 100:.1f}% R di 1h dan
  ~{(cfg.costs.spread + 2 * cfg.costs.slippage + cfg.costs.commission_per_unit) / sl_med['15m'] * 100:.1f}% R di 15m.

## 3. Hasil baseline (parameter TPW08), split kronologis IS 70% / OOS 30%

{md_table(base_tab)}

![Equity 1h](figures/02_equity_1h.png)
![Equity harian](figures/02_equity_1d.png)

### Perbandingan dengan klaim TPW08

{md_table(claim_tab)}

Catatan: drawdown bergantung pada risk per trade, yang tidak disebutkan di TPW08. Dengan sampel trade 1h di atas,
risk per trade yang dibutuhkan agar DD Monte Carlo persentil 95 mencapai 15% adalah sekitar **{num(risk_for_15)}%**.

## 4. Apakah lebih baik dari entry acak?

Model nol: exit tetap sama (SL 1,5 ATR, TP 1R, biaya sama), tetapi bar entry dipilih acak dengan jumlah trade yang sama
({n_null} simulasi). Versi "long saja" mengukur seberapa besar hasil yang hanya berasal dari tren naik emas.

| TF | Expectancy strategi | Mean acak (50/50) | Persentil 95 acak | p empiris | Mean acak long | Persentil 95 long | p empiris long |
|---|---|---|---|---|---|---|---|
| 1h | {rr(nr['obs'])} | {rr(nr['mean'])} | {rr(nr['p95'])} | {pval(nr['p_emp'])} | {rr(nl['mean'])} | {rr(nl['p95'])} | {pval(nl['p_emp'])} |
| 1d | {rr(dr['obs'])} | {rr(dr['mean'])} | {rr(dr['p95'])} | {pval(dr['p_emp'])} | {rr(dl['mean'])} | {rr(dl['p95'])} | {pval(dl['p_emp'])} |

![Random baseline](figures/02_random_baseline.png)

## 5. Robustness parameter (grid kecil) dan tanda overfitting

* Grid Tenkan x Kijun di 1h: {pct(g['ichimoku_1h_share_is_positive'], 0)} sel positif di IS dan {pct(g['ichimoku_1h_share_oos_positive'], 0)} sel positif di OOS.
  Korelasi peringkat (Spearman) IS vs OOS = **{num(g['ichimoku_1h_spearman_is_oos'])}** (n = {g['ichimoku_1h_cells']} sel dengan >= 5 trade).
  Nilai mendekati 0 atau negatif berarti parameter terbaik di masa lalu **tidak** memprediksi yang terbaik di masa depan.
* Kombinasi terbaik di IS: `{g['best_is_1h']}` dengan expectancy IS {rr(g['best_is_1h_is_exp'])}, lalu
  {rr(g['best_is_1h_oos_exp'])} di OOS ({g['best_is_1h_oos_trades']} trade). Sel TPW08 (12/30) di OOS: {rr(float(tpw_cell_oos['expectancy_r']))} ({int(tpw_cell_oos['trades'])} trade).
* Grid ambang RSI delta x SL (ATR): Spearman IS vs OOS = {num(g['rsi_sl_1h_spearman_is_oos'])} (n = {g['rsi_sl_1h_cells']}).
* Harian: {pct(g['ichimoku_1d_share_positive'], 0)} sel positif, median hanya {num(g['ichimoku_1d_median_trades'], 0)} trade per sel
  sejak 2010. Terlalu sedikit untuk kesimpulan apa pun.

![Heatmap Ichimoku 1h](figures/02_heatmap_1h_ichimoku.png)
![Heatmap RSI x SL 1h](figures/02_heatmap_1h_rsi_sl.png)
![Heatmap harian](figures/02_heatmap_1d_ichimoku.png)

## 6. Walk-forward

Grid {len(wf_grid)} kombinasi (Tenkan {WF_AXES['tenkan']}, Kijun {WF_AXES['kijun']}, RSI delta {WF_AXES['rsi_delta']},
SL {WF_AXES['sl_atr']} ATR, TP {WF_AXES['tp_r']}R). Parameter dengan expectancy tertinggi di jendela latih dipakai
pada jendela uji berikutnya, lalu jendela digeser.
{wf_tabs}
![Walk-forward](figures/02_walk_forward.png)

## 7. Varian ATR trailing stop (proposal UAS)

{md_table(trail_tab)}

Bandingkan kolom MaxDD dan Expectancy per segmen. Klaim UAS bahwa trailing ATR "menurunkan DD dari 15% ke <10%"
hanya bermakna jika diukur pada risk per trade yang sama. Di sini semua varian memakai risk 1%.

![MAE/MFE](figures/02_mae_mfe_1h.png)

## 8. Monte Carlo drawdown (bootstrap urutan trade)

{md_table(mc_tab)}

![Monte Carlo](figures/02_monte_carlo_dd.png)

## 9. Sensitivitas biaya (spread)

{md_table(cost_tab)}

Karena SL dan TP dipasang relatif terhadap harga fill (seperti di MT5), biaya tidak mengurangi R secara langsung.
Biaya mengubah **peluang** SL vs TP tersentuh (TP butuh gerakan harga lebih jauh, SL lebih dekat). Dengan SL ~18 USD di 1h,
spread 0,2-0,4 USD hampir tidak berpengaruh; spread 2 USD (kondisi berita) mulai menggerus expectancy.

Data 15m Yahoo hanya mencakup ~60 hari terakhir ({tfs['15m']['first'][:10]} - {tfs['15m']['last'][:10]}, {tfs['15m']['ALL']['trades']} trade).
Data ini paling dekat dengan timeframe TPW08 (M15), tetapi terlalu pendek untuk kesimpulan.

## 10. Kriteria validasi edge

| Kriteria | Hasil |
|---|---|
{crit_md}

## 11. Kesimpulan

{verdict_line}

{conclusions_md}

## 12. Keterbatasan

* **Futures vs spot broker.** `GC=F` adalah kontrak futures COMEX bulan terdekat (continuous). Harganya berbeda dari
  XAUUSD spot/CFD di broker MT5: ada basis/contango, lonjakan saat pergantian kontrak (roll), jam sesi yang berbeda,
  dan candle harian yang dipotong pada jam berbeda (server MT5 umumnya GMT+2/+3).
* **Kualitas dan panjang data Yahoo.** Data 1h hanya ~730 hari, 15m hanya 60 hari. Tidak ada data tick, sehingga urutan
  harga di dalam bar tidak diketahui (diasumsikan konservatif). Yahoo bukan sumber data resmi dan bisa direvisi.
* **Biaya disederhanakan.** Spread dianggap konstan, padahal saat berita/rollover bisa melebar beberapa kali lipat.
  Swap dihitung proporsional waktu, tidak mengikuti jadwal rollover dan triple-swap broker.
* **Rekonstruksi aturan.** SL/TP, perlakuan short, dan definisi cross tidak dijelaskan dokumen. Hasil bisa berbeda dari
  kode asli TPW08 (yang tidak tersedia di repo ini).
* **Regime tunggal.** Periode 1h (2024-2026) didominasi tren naik emas yang kuat. Kinerja di regime sideways/turun tidak teruji.
* **Multiple testing.** {configs_tested} konfigurasi diuji. Tanpa koreksi (mis. Bonferroni atau deflated Sharpe),
  sebagian hasil "signifikan" kemungkinan hanya kebetulan.
* **Ukuran lot fraksional.** Simulasi memakai unit fraksional. Di akun kecil, pembulatan ke 0,01 lot bisa membuat risk
  aktual berbeda dari 1%.

## 13. Langkah berikutnya

1. Ekspor data M15 XAUUSD dari broker MT5 (2020-sekarang) dan jalankan ulang pipeline ini. Paket `trading_research`
   menerima DataFrame OHLC apa pun.
2. **Bekukan aturan** (parameter, SL/TP, filter) sebelum melihat data baru. Jangan mengoptimasi ulang setelah melihat hasil OOS.
3. Paper trading di akun demo MT5 minimal 3 bulan atau 50 trade, catat di `templates/jurnal_trading_v2.csv`, lalu
   bandingkan expectancy live dengan backtest.
4. Gunakan risk kecil (0,25-0,5%) jika nanti live. Target "3 miliar dalam 3 tahun" (CAGR ~130%) tidak didukung oleh data ini.
"""
    (reports / "02_ichimoku_rsi.md").write_text(md, encoding="utf-8", newline="\n")
    return out
