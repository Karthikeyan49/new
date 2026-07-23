# Data provenance

All datasets are public OHLC exports mirrored from open GitHub repositories
(the only outbound data host reachable from the build environment). They are
included here for reproducibility. Credit to the original uploaders.

| File | Instrument | TF | Span | Source repo (raw GitHub) |
|---|---|---|---|---|
| `EURUSD_D1.csv` | EUR/USD | Daily | 2007–2020 (4,371 bars) | `giorgosfatouros/DeepVaR` → `data/EURUSD1440.csv` |
| `EURUSD_H1.csv` | EUR/USD | 1 hour | 2013-11 → 2014-05 (3,070 bars) | `AdrianP-/gym_trading` → `data/EURUSD60.csv` |
| `NIFTY_D1.csv`  | NIFTY 50 | Daily | 2021–2026 (1,266 bars) | `rudradeep-me/Financial-Investment-Simulator` → `nifty_50_historical.csv` (yfinance `^NSEI`) |

These are third-party retail exports, not tick-accurate broker feeds. Treat the
absolute numbers as indicative; the point of the study is the *relative,
parameter-stable* behaviour of the strategy, not a certified P&L.
