"""Build reports/01_audit_jurnal_manual.md from journals/template-backtest.csv."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .backtest import CostModel
from .journal import audit_summary, data_issues, load_legacy, verify_with_prices
from .metrics import breakeven_win_rate
from .plotting import INK_2, MUTED, SERIES, plt, save, setup_style
from .report_utils import md_table, num, pct, rr


def build(root: Path, daily: pd.DataFrame, hourly: pd.DataFrame, ticker: str) -> dict:
    reports = root / "reports"
    fig_dir = reports / "figures"
    setup_style()
    j = load_legacy(root / "journals" / "template-backtest.csv")
    s = audit_summary(j)
    issues = data_issues(j)
    costs = CostModel()
    cost_per_oz = costs.spread + costs.commission_per_unit  # entry+exit spread and commission, TP exit no slippage
    j["r_net_est"] = (j["reward_usd"] - cost_per_oz - costs.slippage) / j["risk_usd"]

    # ---- market context from futures data ----
    d = daily.loc["2024-12-15":"2025-04-15"]
    q1 = daily.loc["2025-01-01":"2025-03-31", "close"]
    q1_ret = float(q1.iloc[-1] / q1.iloc[0] - 1)
    up_days = float((q1.diff().dropna() > 0).mean())
    jw = daily.loc[j["entry_date"].min():j["exit_date"].max(), "close"]
    window_ret = float(jw.iloc[-1] / jw.iloc[0] - 1)
    ver = verify_with_prices(j, hourly)

    # ---- figures ----
    fig, ax = plt.subplots(figsize=(9, 4.2))
    ax.plot(d.index, d["close"], color=SERIES[0], label=f"{ticker} close (harian)")
    for _, t in j.iterrows():
        y = daily["close"].asof(t["entry_date"])
        m = "^" if t["direction"] == 1 else "v"
        ax.scatter([t["entry_date"]], [y], marker=m, s=70, color=SERIES[1] if t["direction"] == 1 else SERIES[2],
                   edgecolor="#fcfcfb", linewidth=1.5, zorder=3)
        ax.annotate(f"#{t['trade_no']}", (t["entry_date"], y), textcoords="offset points", xytext=(0, 9),
                    ha="center", fontsize=8, color=INK_2)
    ax.scatter([], [], marker="^", color=SERIES[1], label="Entry BUY (jurnal)")
    ax.scatter([], [], marker="v", color=SERIES[2], label="Entry SELL (jurnal)")
    ax.set_title("Konteks pasar: 8 dari 9 trade adalah BUY di tengah tren naik kuat")
    ax.set_ylabel("USD/oz (futures)")
    ax.legend(loc="upper left")
    save(fig, fig_dir / "01_journal_context.png")

    fig, ax = plt.subplots(figsize=(8, 3.6))
    x = np.arange(len(j))
    ax.bar(x, j["r_planned"], color=SERIES[0], width=0.6, label="R rencana (= realisasi, semua TP)")
    ax.axhline(1.0, color=MUTED, linestyle="--", linewidth=1)
    ax.text(len(j) - 0.5, 1.02, "1R", color=MUTED, fontsize=8, ha="right", va="bottom")
    ax.set_xticks(x, [f"#{i}" for i in j["trade_no"]])
    ax.set_ylabel("R-multiple")
    ax.set_title(f"Rata-rata RR rencana {s['avg_planned_rr']:.2f}R: kebanyakan reward <= risk")
    save(fig, fig_dir / "01_journal_r.png")

    # ---- markdown ----
    tab = j[["trade_no", "direction", "entry_date", "entry_weekday", "exit_date", "exit_weekday", "entry", "sl", "tp",
             "risk_usd", "reward_usd", "r_planned", "r_realized", "r_net_est", "holding_days"]].copy()
    tab["direction"] = tab["direction"].map({1: "BUY", -1: "SELL"})
    tab["entry_date"] = tab["entry_date"].dt.strftime("%d-%b-%Y")
    tab["exit_date"] = tab["exit_date"].dt.strftime("%d-%b-%Y")
    tab.columns = ["#", "Arah", "Entry", "Hari", "Exit", "Hari exit", "Harga entry", "SL", "TP", "Risk $", "Reward $",
                   "R rencana", "R realisasi", "R neto (est.)", "Hold (hari)"]
    rfmt = {c: (lambda v: f"{v:.2f}") for c in ["R rencana", "R realisasi", "R neto (est.)"]}
    ver_tab = ver[["trade_no", "entry_in_range", "basis_est", "first_hit"]].copy()
    ver_tab["entry_in_range"] = ver_tab["entry_in_range"].map({True: "Ya", False: "Tidak"}).fillna("-")
    ver_tab.columns = ["#", "Entry di range futures hari itu?", "Futures - entry jurnal ($)", "Level pertama tersentuh (futures, digeser basis)"]

    lo, hi = s["win_rate_ci95"]
    n_tp_confirmed = int((ver["first_hit"] == "TP").sum())
    n_sl_first = int((ver["first_hit"] == "SL").sum())
    n_amb = int((ver["first_hit"] == "ambigu").sum())
    n_other = len(ver) - n_tp_confirmed - n_sl_first - n_amb
    be = breakeven_win_rate(s["avg_planned_rr"])

    md = f"""# 01 - Audit Jurnal Manual XAUUSD (Jan-Mar 2025)

*Dibuat otomatis oleh `scripts/run_all.py`. Sumber: `journals/template-backtest.csv` (salinan dari Google Drive
`02_Proyek/Trading/template-backtest.csv`). Data harga pembanding: `{ticker}` (Yahoo Finance) harian dan 1 jam.*

## Ringkasan

| Metrik | Nilai |
|---|---|
| Jumlah trade | {s['n_trades']} ({s['n_long']} BUY, {s['n_short']} SELL) |
| Periode | {s['period_start']:%d %b %Y} - {s['period_end']:%d %b %Y} |
| Win rate tercatat | {pct(s['win_rate'], 0)} ({s['wins']}/{s['n_trades']}) |
| Interval kepercayaan 95% win rate (Wilson) | {pct(lo, 0)} - {pct(hi, 0)} |
| RR rencana rata-rata / median / minimum | {s['avg_planned_rr']:.2f}R / {s['median_planned_rr']:.2f}R / {s['min_planned_rr']:.2f}R |
| Expectancy realisasi (tanpa biaya) | {rr(s['expectancy_r'])} per trade |
| Total R | {s['total_r']:.2f}R |
| Win rate impas pada RR {s['avg_planned_rr']:.2f} | {pct(be)} |
| Trade yang dibuka dan ditutup di hari yang sama | {s['same_day_trades']} |
| Perubahan harga {ticker} 1 Jan - 31 Mar 2025 | {pct(q1_ret)} ({pct(up_days, 0)} hari naik) |
| Perubahan harga selama rentang jurnal ({j['entry_date'].min():%d %b} - {j['exit_date'].max():%d %b %Y}) | {pct(window_ret)} |

**Kesimpulan singkat:** angka 9/9 TP terlihat sempurna, tetapi secara statistik belum membuktikan apa pun. Sampelnya terlalu
kecil, hampir semua posisi searah dengan tren naik yang sangat kuat, dan tidak ada satu pun trade rugi yang tercatat.
Rata-rata RR rencana di bawah 1 ({s['avg_planned_rr']:.2f}R), sehingga sistem ini butuh win rate di atas {pct(be, 0)} hanya untuk
impas. Bahkan jika 9 trade ini dianggap sampel acak yang jujur (padahal kemungkinan besar tidak, lihat bagian masalah data),
interval kepercayaan 95% win rate-nya masih {pct(lo, 0)}-{pct(hi, 0)}: terlalu lebar untuk dijadikan dasar sistem.

![Konteks pasar](figures/01_journal_context.png)

## Tabel per trade

R rencana = |TP - entry| / |entry - SL|. R realisasi dihitung dari kolom `Keterangan` (TP berarti exit di TP).
R neto (est.) mengurangi asumsi biaya: spread {costs.spread:.2f} USD, komisi {costs.commission_per_unit:.2f} USD/oz, dan
slippage entry {costs.slippage:.2f} USD. Jurnal tidak mencatat biaya, jadi angka ini hanya perkiraan.

{md_table(tab, {**rfmt, "Harga entry": lambda v: f"{v:.2f}", "SL": lambda v: f"{v:.2f}", "TP": lambda v: f"{v:.2f}",
                 "Risk $": lambda v: f"{v:.1f}", "Reward $": lambda v: f"{v:.1f}"})}

![R per trade](figures/01_journal_r.png)

## Masalah data yang ditemukan

""" + "\n".join(f"{i + 1}. {x}" for i, x in enumerate(issues)) + f"""
{len(issues) + 1}. **Sampel sangat kecil.** Dengan 9 trade, satu trade rugi saja mengubah win rate sebesar 10 poin persen.
   Sebagai patokan kasar, minimal 100 trade dibutuhkan sebelum win rate dan expectancy layak diandalkan.
{len(issues) + 2}. **Bias tren dan arah.** {s['n_long']} dari {s['n_trades']} trade adalah BUY, sementara emas naik {pct(q1_ret)} pada
   kuartal tersebut. Hasil ini lebih banyak mencerminkan arah pasar (beta) daripada keunggulan setup (alpha).
   Kita tidak tahu bagaimana setup yang sama bekerja saat pasar turun atau sideways.
{len(issues) + 3}. **Kolom penting tidak ada:** jam entry/exit, ukuran lot, risk %, spread/biaya, MAE/MFE, alasan entry,
   dan screenshot. Tanpa jam, urutan SL vs TP tidak bisa diverifikasi untuk trade yang dibuka dan ditutup di hari yang sama.
{len(issues) + 4}. **RR < 1 pada {int((j['r_planned'] < 1).sum())} trade** (RR terendah {s['min_planned_rr']:.2f}). Struktur ini rawan.
   Satu kali SL menghapus profit dari 1-2 trade TP.
{len(issues) + 5}. **Risiko hindsight bias.** Jurnal backtest manual yang dibuat dengan melihat chart historis cenderung memilih
   setup yang "jelas" setelah hasilnya diketahui. Aturan entry perlu ditulis sebelum melihat data.

## Verifikasi kasar terhadap data harga ({ticker} 1 jam)

Data pembanding adalah **futures COMEX**, bukan spot broker, dan jurnal tidak memuat jam. Karena itu harga entry jurnal
dibandingkan dengan range futures pada hari yang sama, lalu level entry/TP/SL digeser oleh selisih median futures-spot
({num(float(ver['basis_used'].iloc[0]))} USD) untuk melihat level mana yang tersentuh lebih dulu.
Hasilnya **indikatif saja**.

{md_table(ver_tab, {"Futures - entry jurnal ($)": lambda v: num(v, 1)})}

Ringkasan: hanya **{n_tp_confirmed} dari {len(ver)}** trade yang TP-nya dapat dikonfirmasi tersentuh lebih dulu dengan data
futures. SL lebih dulu = {n_sl_first}, ambigu (keduanya dalam 1 bar) = {n_amb}, belum tersentuh/tidak dapat diverifikasi = {n_other}. Selisih futures terhadap spot pada awal 2025 sempat melebar tidak biasa (puluhan USD), sehingga
pergeseran satu angka median tidak akurat untuk semua trade. Jika ada trade yang menurut data futures terkena SL lebih
dulu, cek ulang di chart broker (MT5) dengan timeframe M15/M5.

## Rekomendasi

1. Catat **semua** trade, termasuk yang rugi dan yang dibatalkan, menggunakan `templates/jurnal_trading_v2.csv`
   (lengkap dengan jam, lot, risk %, spread, MAE/MFE, dan screenshot).
2. Tulis aturan setup secara tertulis **sebelum** backtest manual berikutnya, lalu uji pada periode turun/sideways
   (misalnya 2022 atau Q2 2013) agar bias tren terlihat.
3. Targetkan RR rencana >= 1.5 atau buktikan dengan data bahwa win rate > {pct(be, 0)} bisa dipertahankan.
4. Kumpulkan >= 100 trade, lalu hitung ulang dengan `trading_research.journal.load_v2` dan `v2_summary`.
"""
    (reports / "01_audit_jurnal_manual.md").write_text(md, encoding="utf-8", newline="\n")
    return {
        "n_trades": s["n_trades"], "n_long": s["n_long"], "n_short": s["n_short"], "win_rate": s["win_rate"],
        "win_rate_ci95": [lo, hi], "avg_planned_rr": s["avg_planned_rr"], "expectancy_r": s["expectancy_r"],
        "expectancy_r_net_est": float(j["r_net_est"].mean()), "breakeven_wr": be, "q1_2025_gold_return": q1_ret,
        "issues": len(issues) + 5, "verify_first_hit": ver["first_hit"].value_counts().to_dict(),
    }
