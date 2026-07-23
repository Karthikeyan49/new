"""
INTRADAY study — the timeframe SMC is actually designed for.

  * EUR/USD 15m  : entry on M15, HTF bias resampled to H1/H4/D1, NY killzones
  * BANK NIFTY 1m: entry on M1, HTF bias resampled to M15/H1 (Indian session,
                   so NO New-York killzone filter)

Compares single-timeframe baseline vs the multi-timeframe cascade, saves
artifacts, and writes results/INTRADAY_SUMMARY.md.

    python3 src/run_intraday.py   (run src/prep_intraday.py first)
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict

import pandas as pd

from data_loader import load
from strategy import SMCStrategy, Params
from backtest import trades_to_frame, metrics
from plot_svg import write_equity_svg
from mtf import htf_bias_for_base

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "..", "results")

# name -> (file, killzone, htf tfs, notes)
INSTR = {
    "EURUSD_M15": ("EURUSD_M15.csv", True, ("1D", "4h", "1h"),
                   "Forex EUR/USD 15m, 2 months (2017), HTF bias D1/H4/H1"),
    "BANKNIFTY_M1": ("BANKNIFTY_M1.csv", False, ("1h", "15min"),
                     "Indian Bank Nifty 1m, Jan 2024 (22 days), HTF bias H1/M15"),
}


def run_variant(df, base, tag, htf, killzone):
    p = Params(use_killzone=killzone)
    trades = SMCStrategy(df, p, htf_bias=htf).run()
    m, curve = metrics(trades)
    name = f"{base}_{tag}"
    if m.get("trades", 0):
        trades_to_frame(trades).to_csv(os.path.join(RESULTS, f"{name}_trades.csv"), index=False)
        write_equity_svg(curve, f"{name}  ret={m.get('return_pct')}%",
                         os.path.join(RESULTS, f"{name}_equity.svg"))
    m.update(variant=name, killzone=killzone, params=asdict(p))
    with open(os.path.join(RESULTS, f"{name}_metrics.json"), "w") as fh:
        json.dump(m, fh, indent=2, default=str)
    return m


def main():
    os.makedirs(RESULTS, exist_ok=True)
    rows = []
    for base, (fname, kz, tfs, notes) in INSTR.items():
        df = load(os.path.join(HERE, "..", "data", fname))
        htf_all = htf_bias_for_base(df, tfs=tfs, n=3, mode="all")
        htf_fine = htf_bias_for_base(df, tfs=(tfs[0],), n=3, mode="any_daily")
        variants = [("baseline", None, False),
                    ("MTF_htf", htf_fine, kz),
                    ("MTF_all", htf_all, kz)]
        for tag, htf, k in variants:
            m = run_variant(df, base, tag, htf, k)
            m["notes"] = notes
            rows.append(m)
            print(f"{m['variant']:24s} n={m.get('trades'):>3} WR={m.get('win_rate_pct')}% "
                  f"avgR={m.get('avg_R')} PF={m.get('profit_factor')} totR={m.get('total_R')}")

    lines = [
        "# Intraday SMC Results\n",
        "_The timeframe SMC is designed for. `baseline` = single-timeframe engine; "
        "`MTF_htf` = bias from the finest higher timeframe; `MTF_all` = all higher "
        "timeframes must agree. HTF bias aligned with a backward merge_asof (no "
        "look-ahead). EUR/USD uses NY killzones; Bank Nifty does not (Indian session)._\n",
        "| Instrument | Variant | Trades | Win% | Avg R | Profit Factor | Total R | Return % |",
        "|---|---|--:|--:|--:|--:|--:|--:|",
    ]
    for m in rows:
        lines.append(
            f"| {m.get('notes','').split(',')[0]} | {m['variant'].split('_',1)[-1] if '_' in m['variant'] else m['variant']} "
            f"| {m.get('trades')} | {m.get('win_rate_pct')} | {m.get('avg_R')} "
            f"| {m.get('profit_factor')} | {m.get('total_R')} | {m.get('return_pct')} |")
    with open(os.path.join(RESULTS, "INTRADAY_SUMMARY.md"), "w") as fh:
        fh.write("\n".join(lines))
    print(f"\nWrote {os.path.join(RESULTS, 'INTRADAY_SUMMARY.md')}")


if __name__ == "__main__":
    main()
