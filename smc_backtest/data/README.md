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

## Intraday datasets (built by `src/prep_intraday.py`)

| File | Instrument | TF | Span | Source repo |
|---|---|---|---|---|
| `EURUSD_M15.csv` | EUR/USD | 15 min | 2017-01 → 2017-03 (3,895 bars) | `liamdasilva/ForexDMEC` → `DMForex/data/EURUSD15.csv` |
| `BANKNIFTY_M1.csv` | Bank Nifty (spot) | 1 min | Jan 2024, 22 trading days (8,250 bars) | `Desi385/Strategy_Tested_data` → `trading/banknifty_spot*_01_2024.csv` |

Bank Nifty timestamps are NSE (IST) localised to Asia/Kolkata then converted to
UTC; EUR/USD 15m broker time is treated as UTC. `EURUSD_M15_raw.csv` is the
untouched download kept for reproducibility.
