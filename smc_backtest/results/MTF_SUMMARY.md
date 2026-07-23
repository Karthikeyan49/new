# Multi-Timeframe Cascade — EUR/USD H1

_Top-down SMC: bias read on resampled higher timeframes (Weekly/Daily/H4),
entry executed on H1. HTF bias is aligned with a backward merge_asof so a
base bar only ever sees HTF candles that already closed (no look-ahead)._

`MTF_D1` = daily bias only. `MTF_W1_D1` / `MTF_W1_D1_H4` require ALL listed
timeframes to agree, else flat (no trade).

| Variant | Trades | Win% | Avg R | Profit Factor | Total R | Return % |
|---|--:|--:|--:|--:|--:|--:|
| baseline_single_TF_noKZ | 15 | 26.67 | 0.166 | 1.226 | 2.49 | 2.23 |
| MTF_D1_noKZ | 32 | 34.38 | 0.466 | 1.711 | 14.92 | 15.31 |
| MTF_W1_D1_noKZ | 5 | 40.0 | 0.758 | 2.263 | 3.79 | 3.73 |
| MTF_W1_D1_H4_noKZ | 3 | 33.33 | 0.367 | 1.551 | 1.1 | 1.05 |
| baseline_single_TF_KZ | 6 | 16.67 | -0.312 | 0.625 | -1.87 | -1.93 |
| MTF_D1_KZ | 18 | 33.33 | 0.429 | 1.643 | 7.72 | 7.61 |
| MTF_W1_D1_KZ | 4 | 50.0 | 1.197 | 3.395 | 4.79 | 4.78 |
| MTF_W1_D1_H4_KZ | 2 | 50.0 | 1.051 | 3.102 | 2.1 | 2.07 |

## Read-out

- The **Daily-bias cascade (`MTF_D1`) beats the single-timeframe baseline** on
  both sample size and expectancy — the clean daily trend gate admits more
  valid setups than a 5-bar hourly proxy and filters counter-trend noise.
- Adding the **Weekly** filter raises win rate / profit factor but shrinks the
  sample sharply (only ~27 weekly bars in 6 months), so those high PFs sit on
  very few trades — promising, not proven.
- Takeaway: **multi-timeframe structure genuinely helps**; confirming it at
  scale needs a longer intraday history (2-3+ years of H1).