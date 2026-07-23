"""
Data loading and normalisation.

Two very different source formats are supported and normalised to a single
canonical schema:

    timestamp (tz-aware, UTC) | open | high | low | close | volume

1. MT4 export (e.g. EURUSD_H1.csv), no header:
       2013.11.29,12:00,1.36171,1.36183,1.35966,1.36066,3593
       date=%Y.%m.%d, time=%H:%M, then O,H,L,C,V

2. yfinance multi-row header (e.g. NIFTY_D1.csv):
       Price,Close,High,Low,Open,Volume
       Ticker,^NSEI,^NSEI,^NSEI,^NSEI,^NSEI
       Date,,,,,
       2021-01-01,14018.5,14049.8...,13991.3...,13996.0...,358100
   Note the column ORDER is Close,High,Low,Open,Volume (Open is 4th).

The loader auto-detects which format a file is and returns a clean,
ascending-sorted pandas DataFrame with a RangeIndex plus a 'timestamp' column.
"""
from __future__ import annotations

import pandas as pd


CANON = ["timestamp", "open", "high", "low", "close", "volume"]


def _load_ohlcv(path: str, tz: str) -> pd.DataFrame:
    """Headerless OHLCV feeds (MT4 comma or tab-separated), standard column order.

    Handles both column layouts seen in the wild:
      * date, time, O, H, L, C, V          (7 fields; date like 2013.11.29 or 06/26/89)
      * "YYYY-MM-DD HH:MM", O, H, L, C, V   (6 fields; combined datetime)
    Delimiter (comma vs tab) is sniffed from the first line.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        first = fh.readline().rstrip("\n")
    sep = "\t" if "\t" in first else ","
    ncols = len(first.split(sep))

    if ncols >= 7:  # separate date & time columns
        df = pd.read_csv(path, header=None, sep=sep,
                         names=["date", "time", "open", "high", "low", "close", "volume"],
                         usecols=range(7))
        ts = pd.to_datetime(df["date"].astype(str) + " " + df["time"].astype(str),
                            format="mixed", dayfirst=False)
    else:            # combined datetime column
        df = pd.read_csv(path, header=None, sep=sep,
                         names=["datetime", "open", "high", "low", "close", "volume"],
                         usecols=range(6))
        ts = pd.to_datetime(df["datetime"], format="mixed")

    df["timestamp"] = ts.dt.tz_localize(tz).dt.tz_convert("UTC")
    return df[CANON]


def _load_yf_multiheader(path: str, tz: str) -> pd.DataFrame:
    # Row 0 gives the true column order after the index column.
    header = pd.read_csv(path, nrows=1, header=None).iloc[0].tolist()
    cols = [str(c).strip().lower() for c in header[1:]]  # drop 'Price'/'Date' label
    df = pd.read_csv(path, skiprows=3, header=None)
    df.columns = ["timestamp"] + cols
    ts = pd.to_datetime(df["timestamp"])
    # Localise naive daily stamps; some files already carry an offset.
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize(tz)
    df["timestamp"] = ts.dt.tz_convert("UTC")
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df[CANON]


def _detect(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        first = fh.readline().strip()
    head = first.split(",")[0].strip().lower()
    if head in ("price", "date", "datetime") or "=" in first:
        return "yf"
    # MT4 first token looks like 2013.11.29
    if first[:4].isdigit() and first.count(".") >= 2:
        return "mt4"
    return "yf"


def load(path: str, source_tz: str = "UTC") -> pd.DataFrame:
    """Load `path` into the canonical OHLCV schema.

    `source_tz` is the timezone the *source timestamps* are stated in
    (MT4 broker feeds are typically UTC/GMT; the NIFTY file is naive daily).
    """
    kind = _detect(path)
    df = _load_ohlcv(path, source_tz) if kind == "mt4" else _load_yf_multiheader(path, source_tz)
    df = df.dropna(subset=["open", "high", "low", "close"]).copy()
    df = df.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    # Basic sanity: high is the max, low is the min of the bar.
    df["high"] = df[["open", "high", "low", "close"]].max(axis=1)
    df["low"] = df[["open", "high", "low", "close"]].min(axis=1)
    return df


if __name__ == "__main__":
    import sys

    for p in sys.argv[1:]:
        d = load(p)
        print(f"{p}: {len(d)} bars  {d.timestamp.iloc[0]} -> {d.timestamp.iloc[-1]}")
        print(d.head(3).to_string())
