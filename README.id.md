# trading-research (ringkasan Bahasa Indonesia)

Riset yang dapat direproduksi dan sengaja dibuat skeptis untuk **strategi Ichimoku + RSI delta pada XAUUSD**, ditambah
audit jurnal trading manual. Titik awalnya adalah laporan UTS/UAS TPW08 yang mengklaim win rate 65%, profit factor 1,85,
dan drawdown 15%. Repo ini merekonstruksi aturan tersebut, mengujinya dengan biaya realistis dan validasi
out-of-sample, lalu melaporkan hasilnya apa adanya.

> **Disclaimer:** repo ini hanya untuk riset dan edukasi, **bukan nasihat investasi**. Hasil simulasi tidak menjamin
> hasil di masa depan.

## Hasil utama (run 20-10-2026, data Yahoo `GC=F`)

| Uji | Trade | Win rate | Expectancy | Max DD |
|---|---|---|---|---|
| Klaim TPW08 (M15) | >200 | 65% | - | 15% |
| 1h in-sample 70% | 41 | 65,9% | +0,30R | 4,2% |
| 1h out-of-sample 30% | 16 | 56,2% | +0,12R (CI95 -0,38..+0,62) | 4,0% |
| 1h walk-forward OOS | 68 | 48,5% | +0,41R (p = 0,013) | 5,9% |
| Harian 2010-2026 (aturan TPW08) | 8 | 50,0% | -0,02R | 4,3% |

**Kesimpulan: edge BELUM TERBUKTI (bukti campuran, 3 dari 6 kriteria lulus).** Angka klaim hanya muncul in-sample.
Data 1h hanya ~2,4 tahun dalam satu fase tren naik emas, dan parameter (12, 30, 60) dioptimasi pada periode yang sama.
Di data harian sejak 2010, aturan ini hanya memberi 8 sinyal dan tidak menunjukkan edge. Trailing ATR menaikkan
expectancy di 1h, tetapi tidak menurunkan drawdown. Drawdown terutama ditentukan oleh risk per trade (DD 15% kira-kira
setara risk 2% per trade).

**Audit jurnal manual (9 trade, Jan-Mar 2025):** 9/9 TP, tetapi RR rata-rata hanya 0,93R (win rate impas 52%), 8/9 BUY
saat emas naik 17%, satu tanggal exit jatuh di hari Sabtu (1 Feb 2025), dan hanya 4 dari 9 TP yang bisa dikonfirmasi
dengan data futures.

Laporan lengkap: [`reports/01_audit_jurnal_manual.md`](reports/01_audit_jurnal_manual.md),
[`reports/02_ichimoku_rsi.md`](reports/02_ichimoku_rsi.md).

## Cara menjalankan

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m pytest -q
.venv/Scripts/python scripts/run_all.py
```

## Langkah berikutnya

1. Ekspor data M15 XAUUSD dari MT5 lalu jalankan ulang pipeline dengan data broker.
2. Bekukan aturan, lalu paper trading di akun demo MT5 minimal 3 bulan atau 50 trade.
3. Catat setiap trade di `templates/jurnal_trading_v2.csv` dan bandingkan expectancy live dengan backtest.
