"""
Build clean intraday datasets in canonical schema (timestamp,open,high,low,close,
volume) with tz-aware UTC timestamps.

Sources (public GitHub mirrors, the only reachable data host):
  * EUR/USD 15m  — liamdasilva/ForexDMEC (2 months, 2017)  [broker time -> treated UTC]
  * BANKNIFTY 1m — Desi385/Strategy_Tested_data (Jan 2024, ~22 trading days)
                   [NSE time is IST -> localised Asia/Kolkata then converted UTC]

Run once to (re)create data/EURUSD_M15.csv and data/BANKNIFTY_M1.csv.
"""
from __future__ import annotations

import io
import os
import urllib.request

import pandas as pd

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "..", "data")

BNF_REF = "0cd8bbee2ac46ada652beddfe293a4d37d652589"
BNF_URL = ("https://raw.githubusercontent.com/Desi385/Strategy_Tested_data/"
           f"{BNF_REF}/trading/banknifty_spot{{dd}}_01_2024.csv")


def _get(url: str) -> bytes | None:
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return r.read() if r.status == 200 else None
    except Exception:
        return None


def build_banknifty():
    frames = []
    for dd in range(1, 32):
        raw = _get(BNF_URL.format(dd=f"{dd:02d}"))
        if not raw:
            continue
        d = pd.read_csv(io.BytesIO(raw))
        # columns: date,time,symbol,open,high,low,close  (no volume)
        ts = pd.to_datetime(d["date"] + " " + d["time"])
        d["timestamp"] = ts.dt.tz_localize("Asia/Kolkata").dt.tz_convert("UTC")
        d["volume"] = 0
        frames.append(d[["timestamp", "open", "high", "low", "close", "volume"]])
    if not frames:
        print("BANKNIFTY: no files fetched")
        return
    out = pd.concat(frames).sort_values("timestamp").drop_duplicates("timestamp")
    path = os.path.join(DATA, "BANKNIFTY_M1.csv")
    out.to_csv(path, index=False)
    print(f"BANKNIFTY_M1: {len(out)} bars ({len(frames)} days) "
          f"{out.timestamp.iloc[0]} -> {out.timestamp.iloc[-1]} -> {path}")


def build_eurusd_m15():
    src = os.path.join(DATA, "EURUSD_M15_raw.csv")
    if not os.path.exists(src):
        print("EURUSD_M15: raw file missing, skipping")
        return
    d = pd.read_csv(src, usecols=range(7),
                    names=["date", "time", "open", "high", "low", "close", "volume"],
                    header=0)
    ts = pd.to_datetime(d["date"] + " " + d["time"], format="%Y.%m.%d %H:%M")
    d["timestamp"] = ts.dt.tz_localize("UTC")
    out = d[["timestamp", "open", "high", "low", "close", "volume"]].sort_values("timestamp")
    path = os.path.join(DATA, "EURUSD_M15.csv")
    out.to_csv(path, index=False)
    print(f"EURUSD_M15: {len(out)} bars {out.timestamp.iloc[0]} -> {out.timestamp.iloc[-1]} -> {path}")


if __name__ == "__main__":
    build_eurusd_m15()
    build_banknifty()
