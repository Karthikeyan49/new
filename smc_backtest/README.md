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
