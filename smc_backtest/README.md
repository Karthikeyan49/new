# SMC Backtester — a theory-faithful engine for Smart Money Concepts

A from-scratch backtesting system for the **Smart Money Concepts / ICT**
consensus entry model. Every structural element — swings, BOS/CHoCH, order
blocks, fair value gaps, liquidity sweeps, premium/discount — is **detected
algorithmically from candle geometry per the published theory**, not eyeballed
or hard-coded. The engine then runs the model on real OHLC data and reports
honest performance statistics.

> **TL;DR result:** built rigorously and tested fairly, the SMC A+ model shows
> **no durable edge on EUR/USD daily**, a **positive but small-sample edge on
> NIFTY 50 and on EUR/USD intraday**, and is **sensitive to the structure
> lookback**. This matches the research consensus that SMC's edge is real as a
> *lens* but not statistically established as a mechanical system. See
> [`results/SUMMARY.md`](results/SUMMARY.md).

---

## What it implements

The cross-creator **consensus chain** (ICT 2022 / Silver Bullet, TJR, Photon
Trading, Casper SMC, Fractal Flow — and the Alchemist's sweep+rejection variant
all reduce to this):

```
1. HTF BIAS        trade only with the prevailing market-structure trend
2. LIQUIDITY SWEEP price wicks through a prior swing low/high and closes back
3. MSS + DISPLACE  a close breaks internal structure against the sweep,
                   leaving a Fair Value Gap (impulse / displacement)
4. ENTRY AT POI    limit at the FVG 50% (CE); fallback to the order block
   RISK            SL beyond the swept wick (+buffer); TP = next major
                   liquidity pool at >= min R:R; longs in discount only
```

## Theory → code mapping

Each rule is coded exactly as the SMC/ICT literature states it. Sources were
cross-checked across 4–6 references per concept (full list in
[`docs/THEORY.md`](docs/THEORY.md)).

| Concept | Rule as coded | Where |
|---|---|---|
| Swing fractal | `high[i] > high[i±1..N]` (strict), confirmed N bars later | `structure.py` |
| Market structure / bias | HH+HL → bull, LH+LL → bear; flip on close-break of last major swing | `strategy.py` |
| BOS vs CHoCH | **candle close** beyond swing; with-trend = BOS, first counter-trend = CHoCH | `strategy.py` |
| Order block | last opposing-close candle before the displacement leg | `smc.order_block` |
| Fair Value Gap | 3-candle imbalance `low[i] > high[i-2]` (bull); entry = 50% CE | `smc.bullish_fvg` |
| Displacement | body ≥ 1×ATR(14) **or** body/range ≥ 0.6, and leaves an FVG | `smc.is_displacement` |
| Liquidity sweep | wick pierces level **and** closes back (`low<L & close>L`) | `smc.is_sweep_low` |
| Premium/discount | `EQ = (rangeHigh+rangeLow)/2`; longs only below EQ | `strategy.py` |
| Killzones | London 02–05 ET, NY-AM 07–11 ET (DST-aware) | `indicators.ny_hour` |
| Stop / target | SL beyond swept wick +0.1 ATR; TP nearest major pool ≥ min R:R | `strategy.py` |

**No look-ahead:** a swing pivot is only released to the engine `N` bars after it
forms (`Swing.confirm_idx`), so the state machine never sees structure that
wouldn't exist yet in real time. Only trade *management* walks forward, which is
correct (it simulates the open position resolving).

---

## Layout

```
smc_backtest/
├── data/            real OHLC datasets (+ provenance README)
├── src/
│   ├── data_loader.py   normalise MT4 / TSV / yfinance formats → OHLCV
│   ├── indicators.py    ATR (Wilder), NY-hour helper
│   ├── structure.py     fractal swing detection (+ confirmation lag)
│   ├── smc.py           FVG, order block, displacement, sweep detectors
│   ├── strategy.py      the SMC entry state machine (SCAN→ARMED→PENDING→OPEN)
│   ├── mtf.py           multi-timeframe bias cascade (resample W1/D1/H4 → H1)
│   ├── backtest.py      trade list → metrics + equity curve
│   ├── plot_svg.py      dependency-free equity SVG
│   ├── sensitivity.py   parameter grid (is the edge stable?)
│   ├── run.py           single-instrument run
│   └── run_all.py       full study + SUMMARY.md
└── results/         trades, metrics, equity curves, sensitivity grids, SUMMARY.md
```

## Run it

```bash
pip install -r requirements.txt

# full study (all instruments + sensitivity + SUMMARY.md)
python3 src/run_all.py

# multi-timeframe cascade study (W1/D1/H4 bias -> H1 entry) + MTF_SUMMARY.md
python3 src/run_mtf.py

# intraday study on M15 / M1 (fetches + builds the intraday data first)
python3 src/prep_intraday.py
python3 src/run_intraday.py

# single instrument
python3 src/run.py --data data/EURUSD_H1.csv --name EURUSD_H1 --killzone
python3 src/run.py --data data/NIFTY_D1.csv  --name NIFTY_D1 --min-rr 3 --poi fvg
```

Outputs per instrument in `results/`: `*_trades.csv`, `*_metrics.json`,
`*_equity.csv`, `*_equity.svg`, and `sensitivity_*.csv`.

---

## Headline results (theory-default params)

| Instrument | Trades | Win% | Avg R | Profit Factor | Return % (1% risk) |
|---|--:|--:|--:|--:|--:|
| EUR/USD daily (2007–2020) | 32 | 9.4 | −0.61 | 0.33 | −18.0 |
| EUR/USD 1h (6 mo, killzone) | 6 | 16.7 | −0.31 | 0.63 | −1.9 |
| NIFTY 50 daily (2021–2026) | 9 | 44.4 | +1.09 | 2.97 | +10.0 |

### Intraday — the timeframe SMC is built for (`results/INTRADAY_SUMMARY.md`)

| Instrument | Variant | Trades | Win% | Profit Factor | Total R |
|---|---|--:|--:|--:|--:|
| EUR/USD 15m (2 mo) | baseline | 19 | 15.8 | 0.61 | −6.3 |
| EUR/USD 15m (2 mo) | + MTF bias | 18 | 16.7 | 0.64 | −5.3 |
| **Bank Nifty 1m (Jan 2024)** | **baseline** | **72** | **26.4** | **1.20** | **+10.4** |
| Bank Nifty 1m (Jan 2024) | + MTF bias | 118 | 20.3 | 0.83 | −16.2 |

Two honest findings: **(1)** SMC shows no edge on EUR/USD 15m here; **(2)** on
**Bank Nifty 1-minute the baseline is positive over the largest sample in the
study (72 trades, PF 1.20)** — but the multi-timeframe bias filter *hurt* it.
So MTF is not universally good: it helped trending FX on H1 but degraded
short-sample, mean-reverting index scalping. Filters must match the market.

### Multi-timeframe cascade (top-down bias → H1 entry, `results/MTF_SUMMARY.md`)

Reading structure on resampled **higher timeframes** for bias and entering on H1
clearly beats the single-timeframe engine (HTF bias aligned by backward
`merge_asof` — no look-ahead):

| Variant (EUR/USD H1) | Trades | Win% | Profit Factor | Total R |
|---|--:|--:|--:|--:|
| baseline single-TF | 15 | 26.7 | 1.23 | +2.5 |
| **MTF Daily bias** | **32** | **34.4** | **1.71** | **+14.9** |
| MTF Weekly+Daily (must agree) | 5 | 40.0 | 2.26 | +3.8 |
| MTF Weekly+Daily + killzone | 4 | 50.0 | 3.40 | +4.8 |

The daily-bias gate roughly **doubles the trade count and the profit factor** vs.
the single-timeframe proxy; adding the weekly filter lifts quality but thins the
sample (only ~27 weekly bars in 6 months). Multi-timeframe structure genuinely
helps — proving it at scale just needs a longer intraday history.

### The important part — sensitivity (full grid in `results/SUMMARY.md`)

- **EUR/USD daily:** negative in 10 of 12 parameter sets → **no edge**, the two
  positive corners are noise.
- **EUR/USD intraday:** with a *shorter* structure lookback (`n_major=3`) it turns
  strongly positive (PF up to 3.5, +22R / 6 mo) but only 15–18 trades — **promising
  but unproven**, and the fact that the best result needs a different parameter
  than daily is itself a warning about overfitting.
- **NIFTY 50:** positive in 10 of 12 sets (PF often > 2) → the **most stable**,
  but 4–10 trades per config is too few to bank on.

## Honest limitations

- **Small samples.** Public free data capped the spans (esp. intraday). 6–32
  trades is not enough for statistical significance; treat directionally.
- **Retail data, not tick feeds.** Fills at exact FVG/SL/TP prices; no spread,
  slippage, commission, or swap. Real-world results would be worse.
- **SL-first on same-bar SL+TP** (conservative) and no intrabar path modelling.
- **One position at a time**; no pyramiding, no partials, fixed 1% risk.
- This is a **research tool**, not trading advice. It is designed to test SMC
  fairly — including the possibility that it doesn't beat random.

## Extending

`Params` in `src/strategy.py` exposes every knob the SMC creators disagree on
(POI type, structure lookback, min R:R, killzone, discount gate, displacement
thresholds). Drop a new CSV in `data/` (loader auto-detects MT4 / TSV / yfinance
formats) and point `run.py` at it.
