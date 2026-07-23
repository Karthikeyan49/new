# US30 (Dow Jones) 1-Minute Prediction — research project

Goal: build an honest, rigorously-validated forecasting model for US30 on a
large multi-year 1-minute dataset — predicting the parts of the market that are
genuinely predictable (volatility/range, regime) and measuring directional edge
honestly (with abstention + walk-forward + realistic costs), rather than
pretending to predict price direction with false precision.

## Data pipeline (built)
- `src/dukascopy.py` — fetch + LZMA-decode Dukascopy US30 (USA30IDXUSD) tick
  files and aggregate to 1-minute OHLCV (price = tick mid; volume = tick count).
- `src/download.py` — stream years of 1-minute bars, newest-first, with a
  runtime cap and resume; keeps only compact bars on disk, never raw ticks.

```bash
python3 src/download.py --start 2016-01-01 --end 2026-07-22 \
        --out data/US30_M1.csv --minutes 60 --workers 10
```

Data is not committed (large, regenerable) — see `.gitignore`. Dukascopy's Dow
history is dense from ~2016 (no free source has 20 years of 1-minute index data).

## Model (in progress)
A multi-task temporal model (deep TCN/Transformer + gradient-boosting baseline)
predicting volatility/range, direction-with-abstention, and regime, validated
with purged walk-forward splits and transaction costs. Honest scorecard to follow.
