"""Trade-list -> performance metrics and an equity curve (fixed-fractional risk)."""
from __future__ import annotations

from dataclasses import asdict

import numpy as np
import pandas as pd


def trades_to_frame(trades) -> pd.DataFrame:
    rows = []
    for t in trades:
        d = asdict(t)
        d["direction"] = "long" if t.direction == 1 else "short"
        rows.append(d)
    return pd.DataFrame(rows)


def metrics(trades, risk_per_trade: float = 0.01, start_equity: float = 10_000.0) -> dict:
    closed = [t for t in trades if t.outcome in ("win", "loss")]
    n = len(closed)
    if n == 0:
        return {"trades": 0}, np.array([start_equity])

    r = np.array([t.r_multiple for t in closed], float)
    wins = r[r > 0]
    losses = r[r <= 0]
    win_rate = len(wins) / n

    gross_win = wins.sum()
    gross_loss = -losses.sum()
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
    expectancy_r = r.mean()

    # max consecutive losses
    mcl = cur = 0
    for x in r:
        cur = cur + 1 if x <= 0 else 0
        mcl = max(mcl, cur)

    # equity curve with fixed-fractional risk (compounding), + R-based curve
    eq = start_equity
    curve = [eq]
    for x in r:
        eq *= (1 + risk_per_trade * x)
        curve.append(eq)
    curve = np.array(curve)
    peak = np.maximum.accumulate(curve)
    max_dd_pct = float(((peak - curve) / peak).max() * 100)

    r_curve = np.concatenate([[0.0], np.cumsum(r)])
    r_peak = np.maximum.accumulate(r_curve)
    max_dd_r = float((r_peak - r_curve).max())

    return {
        "trades": n,
        "wins": int(len(wins)),
        "losses": int(len(losses)),
        "win_rate_pct": round(win_rate * 100, 2),
        "avg_R": round(expectancy_r, 3),
        "total_R": round(r.sum(), 2),
        "expectancy_R_per_trade": round(expectancy_r, 3),
        "profit_factor": round(profit_factor, 3) if np.isfinite(profit_factor) else None,
        "avg_win_R": round(wins.mean(), 3) if len(wins) else 0.0,
        "avg_loss_R": round(losses.mean(), 3) if len(losses) else 0.0,
        "max_consecutive_losses": mcl,
        "max_drawdown_R": round(max_dd_r, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "start_equity": start_equity,
        "end_equity": round(float(curve[-1]), 2),
        "return_pct": round((curve[-1] / start_equity - 1) * 100, 2),
        "risk_per_trade_pct": risk_per_trade * 100,
        "still_open_at_end": int(sum(1 for t in trades if t.outcome == "open")),
    }, curve
