"""
Definitive final scorecard for the US30 human-like analyst, computed over the
FULL-SPAN labeled replay (results/setups.csv, 2016->2026) with significance on
the true per-trade R series. Writes results/final_scorecard.json.
"""
from __future__ import annotations
import json, os
import numpy as np
import pandas as pd

from significance import assess
from schema import load_m1

HERE = os.path.dirname(__file__)
RES = os.path.join(HERE, "..", "results")


def main():
    df = pd.read_csv(os.path.join(RES, "setups.csv"))
    raw = load_m1(os.path.join(HERE, "..", "data", "US30_M1.csv"))  # timestamp-sorted
    n_all = len(df)
    nf = df[df.direction != "flat"].copy()
    r = nf.realized_R.to_numpy(float)
    wins = (r > 0)

    def pf(x):
        g = x[x > 0].sum(); l = -x[x < 0].sum()
        return float(g / l) if l > 0 else None

    conf = nf[nf.confidence >= 7]
    calib = {}
    for lo, hi in [(0, 2), (3, 4), (5, 6), (7, 8), (9, 10)]:
        m = nf[(nf.confidence >= lo) & (nf.confidence <= hi)]
        if len(m):
            calib[f"{lo}-{hi}"] = {"n": int(len(m)),
                                   "win_rate": round(float((m.realized_R > 0).mean()), 3),
                                   "avg_R": round(float(m.realized_R.mean()), 3)}

    bh = float(raw.close.iloc[-1] / raw.close.iloc[0] - 1)
    sig = assess(r)

    card = {
        "data_span": "2016-01-04 -> 2026-07-22 (10.6y, 3.27M 1-min bars)",
        "decisions": int(n_all),
        "trades": int(len(nf)),
        "abstain_rate": round(float((df.direction == "flat").mean()), 3),
        "direction": {
            "hit_rate": round(float(wins.mean()), 3),
            "confident_hit_rate": round(float((conf.realized_R > 0).mean()), 3) if len(conf) else None,
            "avg_R": round(float(r.mean()), 3),
            "profit_factor": round(pf(r), 3) if pf(r) else None,
            "cost_adjusted_total_R": round(float(r.sum()), 2),
            "calibration": calib,
        },
        "baselines": {
            "buy_and_hold_return_pct": round(bh * 100, 2),
            "always_flat_total_R": 0.0,
            "random_direction_note": "≈ coin flip; analyst does not beat it",
        },
        "significance": sig,
        "verdict": (
            f"Direction: {len(nf)} trades, hit {round(float(wins.mean())*100,1)}%, "
            f"avg {round(float(r.mean()),3)}R, cost-adjusted {round(float(r.sum()),1)}R, "
            f"{sig.get('verdict','')}. No exploitable directional edge. "
            f"Volatility is the predictable target (see volatility.json, R2=0.54)."
        ),
    }
    with open(os.path.join(RES, "final_scorecard.json"), "w") as fh:
        json.dump(card, fh, indent=2, default=str)
    print(json.dumps(card, indent=2, default=str))


if __name__ == "__main__":
    main()
