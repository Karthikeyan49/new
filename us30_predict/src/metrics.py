"""
Stage 3 — HONEST SCORECARD.

`scorecard(calls)` turns a list of evaluated AnalystCalls into the numbers that
tell you whether the analyst has a *real*, cost-adjusted edge — not a flattering
story. It deliberately reports:

  * headline stats over actual trades (hit-rate, avg R, profit factor, net R)
  * a CONFIDENT-only hit-rate (confidence >= 7) — does conviction mean anything?
  * a CALIBRATION table (confidence bucket -> realised win rate)
  * BASELINES to beat: random-direction, always-flat, and buy-and-hold
  * the abstention rate — how often the analyst honestly stood aside

Depends only on duck-typed AnalystCall attributes (and, optionally, a df for the
buy-and-hold baseline).
"""
from __future__ import annotations

import json
import math
from typing import Optional

import pandas as pd


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _is_trade(call) -> bool:
    return (str(getattr(call, "direction", "flat")).lower() in ("long", "short")
            and str(getattr(call, "outcome", "")) in ("win", "loss", "timeout"))


def _R(call) -> float:
    r = getattr(call, "realized_R", float("nan"))
    try:
        r = float(r)
    except (TypeError, ValueError):
        return float("nan")
    return r


def _won(call) -> bool:
    r = _R(call)
    return r == r and r > 0.0


def _rr(call) -> Optional[float]:
    """Reward:risk implied by the call's geometry (for the random baseline)."""
    entry = float(getattr(call, "entry", float("nan")))
    stop = float(getattr(call, "stop", float("nan")))
    target = float(getattr(call, "target", float("nan")))
    if any(math.isnan(x) for x in (entry, stop, target)):
        return None
    risk = abs(entry - stop)
    reward = abs(target - entry)
    if risk <= 0:
        return None
    return reward / risk


def _bucket(conf: int) -> str:
    conf = int(conf)
    if conf <= 2:
        return "0-2"
    if conf <= 4:
        return "3-4"
    if conf <= 6:
        return "5-6"
    if conf <= 8:
        return "7-8"
    return "9-10"


def _safe(x):
    """JSON-safe: NaN/inf -> None, numpy scalars -> python floats."""
    if x is None:
        return None
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return x
    if math.isnan(xf) or math.isinf(xf):
        return None
    return xf


# --------------------------------------------------------------------------- #
# baselines
# --------------------------------------------------------------------------- #
def _buy_and_hold_return(calls, df: Optional[pd.DataFrame]) -> Optional[float]:
    """Fractional return of simply holding US30 across the decision span."""
    tss = [str(getattr(c, "ts", "")) for c in calls if getattr(c, "ts", "")]
    if df is not None and len(df) and tss:
        ts = pd.to_datetime(df["timestamp"], utc=True)
        lo, hi = pd.to_datetime(min(tss), utc=True), pd.to_datetime(max(tss), utc=True)
        span = df.loc[(ts >= lo) & (ts <= hi)]
        if len(span) >= 2:
            first, last = float(span["close"].iloc[0]), float(span["close"].iloc[-1])
            if first:
                return last / first - 1.0
    # fallback: use the calls' own entry prices as a price proxy
    prices = [float(getattr(c, "entry", float("nan"))) for c in calls]
    prices = [p for p in prices if p == p]
    if len(prices) >= 2 and prices[0]:
        return prices[-1] / prices[0] - 1.0
    return None


def _random_direction_win_rate(trades) -> Optional[float]:
    """Expected win rate of a random entry that uses each trade's OWN target/stop
    geometry. With reward:risk = k and no drift, a random entry wins ~1/(1+k),
    so a 1:2 setup 'should' win ~33% by luck alone — the bar real skill must clear."""
    ps = []
    for c in trades:
        k = _rr(c)
        if k is not None:
            ps.append(1.0 / (1.0 + k))
    if not ps:
        return None
    return sum(ps) / len(ps)


# --------------------------------------------------------------------------- #
# main scorecard
# --------------------------------------------------------------------------- #
def scorecard(calls, df: Optional[pd.DataFrame] = None) -> dict:
    """Compute the honest performance scorecard over `calls`.

    `df` (optional) is only used to compute the buy-and-hold baseline from real
    close prices; without it, buy-and-hold falls back to the calls' entry prices.
    """
    calls = list(calls)
    n_snapshots = len(calls)
    trades = [c for c in calls if _is_trade(c)]
    n_trades = len(trades)
    n_abstained = sum(
        1 for c in calls
        if str(getattr(c, "direction", "flat")).lower() == "flat"
        or str(getattr(c, "outcome", "")) == "flat"
    )

    Rs = [_R(c) for c in trades]
    Rs = [r for r in Rs if r == r]                     # drop NaN
    wins = [c for c in trades if _won(c)]
    gross_profit = sum(r for r in Rs if r > 0)
    gross_loss = sum(-r for r in Rs if r < 0)

    confident = [c for c in trades if int(getattr(c, "confidence", 0)) >= 7]
    conf_wins = [c for c in confident if _won(c)]

    # calibration: confidence bucket -> realised win rate ------------------ #
    order = ["0-2", "3-4", "5-6", "7-8", "9-10"]
    buckets: dict = {b: [] for b in order}
    for c in trades:
        buckets[_bucket(int(getattr(c, "confidence", 0)))].append(c)
    calibration = {}
    for b in order:
        gc = buckets[b]
        if not gc:
            continue
        gw = sum(1 for c in gc if _won(c))
        gR = [_R(c) for c in gc if _R(c) == _R(c)]
        calibration[b] = {
            "n": len(gc),
            "win_rate": _safe(gw / len(gc)),
            "avg_R": _safe(sum(gR) / len(gR)) if gR else None,
        }

    outcome_counts = {"win": 0, "loss": 0, "timeout": 0, "flat": 0}
    for c in calls:
        o = str(getattr(c, "outcome", "")) or "flat"
        outcome_counts[o] = outcome_counts.get(o, 0) + 1

    card = {
        "n_snapshots": n_snapshots,
        "n_trades": n_trades,
        "abstain_rate": _safe(n_abstained / n_snapshots) if n_snapshots else None,
        "outcome_counts": outcome_counts,
        "hit_rate": _safe(len(wins) / n_trades) if n_trades else None,
        "confident_hit_rate": _safe(len(conf_wins) / len(confident)) if confident else None,
        "confident_n": len(confident),
        "avg_R": _safe(sum(Rs) / len(Rs)) if Rs else None,
        "profit_factor": (
            _safe(gross_profit / gross_loss) if gross_loss > 0
            else (None if gross_profit == 0 else float("inf"))
        ),
        "cost_adjusted_total_R": _safe(sum(Rs)) if Rs else 0.0,
        "calibration": calibration,
        "baselines": {
            "random_direction_win_rate": _safe(_random_direction_win_rate(trades)),
            "always_flat_total_R": 0.0,
            "buy_and_hold_return": _safe(_buy_and_hold_return(calls, df)),
        },
    }
    # profit_factor may still be inf -> make JSON-safe
    if card["profit_factor"] == float("inf"):
        card["profit_factor"] = None
        card["profit_factor_note"] = "no losing trades (undefined / infinite)"
    return card


def save_scorecard(calls, path: str, df: Optional[pd.DataFrame] = None) -> dict:
    """Compute and write the scorecard to `path` as JSON. Returns the dict."""
    card = scorecard(calls, df=df)
    with open(path, "w") as fh:
        json.dump(card, fh, indent=2, default=str)
    return card


# --------------------------------------------------------------------------- #
# synthetic proof
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    try:
        from .schema import AnalystCall
    except ImportError:
        from schema import AnalystCall

    import random

    rng = random.Random(3)
    calls = []
    for k in range(40):
        direction = rng.choice(["long", "short", "flat"])
        if direction == "flat":
            calls.append(AnalystCall(ts=f"t{k}", direction="flat", confidence=0,
                                     outcome="flat", realized_R=0.0))
            continue
        conf = rng.randint(3, 10)
        # higher confidence -> slightly better odds, so calibration shows a slope
        win = rng.random() < (0.30 + 0.03 * conf)
        entry, risk = 38000.0, 30.0
        if direction == "long":
            stop, target = entry - risk, entry + 2 * risk
        else:
            stop, target = entry + risk, entry - 2 * risk
        calls.append(AnalystCall(
            ts=f"t{k}", direction=direction, confidence=conf,
            entry=entry, stop=stop, target=target,
            outcome="win" if win else "loss",
            realized_R=(2.0 - 1.0 / 30.0) if win else -(1.0 + 1.0 / 30.0),
        ))

    card = scorecard(calls)
    print("=== SCORECARD (metrics.py synthetic) ===")
    print(json.dumps(card, indent=2, default=str))
