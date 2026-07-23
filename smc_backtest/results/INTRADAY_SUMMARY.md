# Intraday SMC Results

_The timeframe SMC is designed for. `baseline` = single-timeframe engine; `MTF_htf` = bias from the finest higher timeframe; `MTF_all` = all higher timeframes must agree. HTF bias aligned with a backward merge_asof (no look-ahead). EUR/USD uses NY killzones; Bank Nifty does not (Indian session)._

| Instrument | Variant | Trades | Win% | Avg R | Profit Factor | Total R | Return % |
|---|---|--:|--:|--:|--:|--:|--:|
| Forex EUR/USD 15m | M15_baseline | 19 | 15.79 | -0.329 | 0.609 | -6.26 | -6.29 |
| Forex EUR/USD 15m | M15_MTF_htf | 18 | 16.67 | -0.297 | 0.644 | -5.34 | -5.41 |
| Forex EUR/USD 15m | M15_MTF_all | 3 | 0.0 | -1.0 | 0.0 | -3.0 | -2.97 |
| Indian Bank Nifty 1m | M1_baseline | 72 | 26.39 | 0.145 | 1.197 | 10.43 | 9.52 |
| Indian Bank Nifty 1m | M1_MTF_htf | 118 | 20.34 | -0.137 | 0.828 | -16.2 | -16.41 |
| Indian Bank Nifty 1m | M1_MTF_all | 81 | 18.52 | -0.214 | 0.738 | -17.3 | -16.82 |