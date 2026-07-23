"""
Run the SMC backtest on a dataset and save all artifacts.

Usage:
    python3 src/run.py --data data/EURUSD_H1.csv --name EURUSD_H1 --killzone
    python3 src/run.py --data data/NIFTY_D1.csv --name NIFTY_D1

Outputs (into results/):
    <name>_trades.csv     every trade with entry/exit/R
    <name>_metrics.json   summary performance metrics + parameters
    <name>_equity.csv     equity curve
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict

import pandas as pd

from data_loader import load
from strategy import SMCStrategy, Params
from backtest import trades_to_frame, metrics

RESULTS = os.path.join(os.path.dirname(__file__), "..", "results")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--source-tz", default="UTC")
    ap.add_argument("--killzone", action="store_true", help="apply NY killzone session filter")
    ap.add_argument("--poi", default="fvg", choices=["fvg", "ob"])
    ap.add_argument("--min-rr", type=float, default=3.0)
    ap.add_argument("--risk", type=float, default=0.01)
    args = ap.parse_args()

    os.makedirs(RESULTS, exist_ok=True)
    df = load(args.data, source_tz=args.source_tz)

    p = Params(use_killzone=args.killzone, poi=args.poi, min_rr=args.min_rr)
    strat = SMCStrategy(df, p)
    trades = strat.run()

    tf = trades_to_frame(trades)
    m, curve = metrics(trades, risk_per_trade=args.risk)
    m["dataset"] = args.name
    m["bars"] = len(df)
    m["period"] = f"{df.timestamp.iloc[0]} -> {df.timestamp.iloc[-1]}"
    m["params"] = asdict(p)

    tf.to_csv(os.path.join(RESULTS, f"{args.name}_trades.csv"), index=False)
    with open(os.path.join(RESULTS, f"{args.name}_metrics.json"), "w") as fh:
        json.dump(m, fh, indent=2, default=str)
    pd.DataFrame({"equity": curve}).to_csv(
        os.path.join(RESULTS, f"{args.name}_equity.csv"), index=False)

    print(f"\n===== {args.name}  ({len(df)} bars, {m['period']}) =====")
    for k in ["trades", "win_rate_pct", "avg_R", "total_R", "profit_factor",
              "avg_win_R", "avg_loss_R", "max_consecutive_losses",
              "max_drawdown_pct", "return_pct", "still_open_at_end"]:
        if k in m:
            print(f"  {k:26s}: {m[k]}")
    return m


if __name__ == "__main__":
    main()
