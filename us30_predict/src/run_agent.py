"""
Wire the three stages into the full human-like analyst and replay it on US30.

    perception.build_snapshot  ->  analyst.Analyst.analyze  ->  replay.evaluate_call
    with a reflective Journal feeding memory back into the analyst each step.

    python3 src/run_agent.py --data data/US30_M1.csv --step 30 --max-points 400
"""
from __future__ import annotations

import argparse, json, os

from schema import load_m1
from perception import build_snapshot
from analyst import Analyst
from replay import run_replay, sample_indices
from journal import Journal
from metrics import scorecard, save_scorecard

RESULTS = os.path.join(os.path.dirname(__file__), "..", "results")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/US30_M1.csv")
    ap.add_argument("--step", type=int, default=30, help="minutes between decisions")
    ap.add_argument("--max-points", type=int, default=400, help="cap decision points")
    ap.add_argument("--warmup", type=int, default=3000, help="bars before first decision")
    ap.add_argument("--spread", type=float, default=1.0, help="round-trip cost in points")
    ap.add_argument("--horizon", type=int, default=60)
    a = ap.parse_args()

    df = load_m1(a.data)
    idx = sample_indices(df, a.step, horizon_min=a.horizon, start=a.warmup)
    if len(idx) > a.max_points:                       # evenly thin to the cap
        keep = max(1, len(idx) // a.max_points)
        idx = idx[::keep][:a.max_points]

    analyst = Analyst()
    journal = Journal()
    print(f"data={len(df)} bars  decisions={len(idx)}  backend={analyst.backend} "
          f"spread={a.spread}pt")

    calls = run_replay(df, build_snapshot,
                       lambda snap, mem: analyst.analyze(snap, mem),
                       idx, journal=journal, spread_pts=a.spread)

    card = scorecard(calls, df=df)
    os.makedirs(RESULTS, exist_ok=True)
    save_scorecard(calls, os.path.join(RESULTS, "scorecard.json"), df=df)
    # per-trade dump so significance.py can use the true R series
    with open(os.path.join(RESULTS, "calls.json"), "w") as fh:
        json.dump([c.as_row() for c in calls], fh, default=str)

    print("\n===== HONEST SCORECARD =====")
    for k in ("n_snapshots", "n_trades", "abstain_rate", "hit_rate",
              "confident_hit_rate", "avg_R", "profit_factor",
              "cost_adjusted_total_R"):
        if k in card:
            print(f"  {k:22s}: {card[k]}")
    if "baselines" in card:
        print("  baselines:", card["baselines"])
    if "calibration" in card:
        print("  calibration:", card["calibration"])
    return card


if __name__ == "__main__":
    main()
