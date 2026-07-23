"""
Build one shared, labeled setups dataset the downstream analyses consume:
each sampled decision -> snapshot-derived features + analyst call + forward outcome.

Perception runs on a rolling WINDOW (not all history) so it stays fast on the
full multi-year 1-minute file. Output: results/setups.csv.
"""
from __future__ import annotations
import os
import pandas as pd

from schema import load_m1
from perception import build_snapshot
from analyst import Analyst
from replay import evaluate_call, sample_indices

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "..", "data", "US30_M1.csv")
OUT = os.path.join(HERE, "..", "results", "setups.csv")
WINDOW = 4000          # bars of history perception sees per decision
MAX_POINTS = 1500
STEP = 30              # minutes between decisions


def trend(s, tf):
    return s.tfs.get(tf, {}).get("trend", "na")


def main():
    df = load_m1(DATA)
    idx = [i for i in sample_indices(df, STEP, horizon_min=60, start=WINDOW)]
    if len(idx) > MAX_POINTS:
        idx = idx[:: max(1, len(idx) // MAX_POINTS)][:MAX_POINTS]
    an = Analyst()
    rows = []
    for k, i in enumerate(idx):
        win = df.iloc[i - WINDOW:i + 1].reset_index(drop=True)
        s = build_snapshot(win, len(win) - 1)
        c = an.analyze(s, "")
        c = evaluate_call(df, i, c, spread_pts=1.0)
        ts = pd.Timestamp(s.ts)
        rows.append(dict(
            ts=s.ts, year=ts.year, quarter=(ts.month - 1) // 3 + 1,
            session=s.session, in_killzone=int(s.in_killzone),
            vol_regime=s.vol_regime, pd_zone=s.pd_zone, atr_pct=s.atr_pct,
            ret_15m=s.ret_15m, ret_60m=s.ret_60m, recent_sweep=s.recent_sweep,
            trend_15m=trend(s, "15min"), trend_1h=trend(s, "1h"),
            trend_4h=trend(s, "4h"),
            direction=c.direction, confidence=c.confidence,
            outcome=c.outcome, realized_R=c.realized_R))
        if k % 200 == 0:
            print(f"  {k}/{len(idx)}", flush=True)
    out = pd.DataFrame(rows)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    out.to_csv(OUT, index=False)
    nf = (out.direction != "flat").sum()
    print(f"DONE setups={len(out)} non_flat={nf} -> {OUT}")


if __name__ == "__main__":
    main()
