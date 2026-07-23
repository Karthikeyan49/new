"""
Parameter-sensitivity grid.

A single backtest number is meaningless if it only holds at one parameter set.
This sweeps the parameters the creators actually disagree on (POI type, structure
lookback, min R:R) and reports whether the edge is stable or an artifact of
one lucky setting. Saves a CSV per instrument.
"""
from __future__ import annotations

import csv
import itertools
import os

from data_loader import load
from strategy import SMCStrategy, Params
from backtest import metrics

RESULTS = os.path.join(os.path.dirname(__file__), "..", "results")

GRID = {
    "n_major": [3, 5, 8],
    "min_rr": [2.0, 3.0],
    "poi": ["fvg", "ob"],
}


def run(data_path: str, name: str, killzone: bool = False) -> list[dict]:
    df = load(data_path)
    rows = []
    keys = list(GRID)
    for combo in itertools.product(*(GRID[k] for k in keys)):
        kw = dict(zip(keys, combo))
        p = Params(use_killzone=killzone, **kw)
        trades = SMCStrategy(df, p).run()
        m, _ = metrics(trades)
        row = {"dataset": name, **kw}
        if m.get("trades", 0) == 0:
            row.update(trades=0, win_rate_pct=None, avg_R=None,
                       profit_factor=None, total_R=0)
        else:
            row.update(trades=m["trades"], win_rate_pct=m["win_rate_pct"],
                       avg_R=m["avg_R"], profit_factor=m["profit_factor"],
                       total_R=m["total_R"], max_dd_pct=m["max_drawdown_pct"])
        rows.append(row)
    os.makedirs(RESULTS, exist_ok=True)
    out = os.path.join(RESULTS, f"sensitivity_{name}.csv")
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return rows


if __name__ == "__main__":
    import sys
    run(sys.argv[1], sys.argv[2], killzone="--killzone" in sys.argv)
