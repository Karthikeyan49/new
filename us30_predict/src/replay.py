"""
Stage 3 — REPLAY / EVALUATION.

Takes the analyst's decisions (AnalystCall) and scores them *honestly* against
the future 1-minute bars: did the trade hit target or stop first, within its
horizon, after realistic (round-trip spread) cost? The scored calls flow back
into the Journal (reflective memory) so the analyst can learn from profit/loss.

This module depends ONLY on the shared contract in `schema.py`. Perception
(perception.py -> MarketSnapshot) and the analyst (analyst.py -> AnalystCall)
are built in parallel, so replay talks to them through duck-typed callables:

    snapshot_fn(df, i) -> MarketSnapshot        # what a human sees at bar i
    analyze_fn(snapshot, memory_context) -> AnalystCall

Everything here is tested against synthetic objects (see __main__), never by
importing the parallel modules.
"""
from __future__ import annotations

import math
from dataclasses import replace
from typing import Callable, Optional

import pandas as pd

try:                       # works as a package (from .schema) or as a script
    from .schema import AnalystCall, MarketSnapshot
except ImportError:        # pragma: no cover - script/import fallback
    from schema import AnalystCall, MarketSnapshot


# --------------------------------------------------------------------------- #
# Single-call evaluation
# --------------------------------------------------------------------------- #
def _ts_at(df: pd.DataFrame, idx: int) -> str:
    idx = max(0, min(idx, len(df) - 1))
    return str(df["timestamp"].iloc[idx])


def evaluate_call(df: pd.DataFrame, i: int, call, spread_pts: float = 1.0):
    """Simulate `call` forward from decision bar `i` over its horizon.

    Walks future bars i+1 .. i+horizon and decides the outcome:
      * long : 'win'  if high >= target reached before low <= stop
               'loss' if stop reached first
      * short: mirror image
      * 'timeout' if neither is touched inside the horizon (P&L marked from the
        close of the horizon bar)
      * direction == 'flat' (or invalid geometry) -> 'flat', realized_R 0

    Cost model (round trip): the full `spread_pts` is subtracted from the trade's
    point P&L before converting to R, so every trade pays the spread once.
    Same-bar ties (a bar whose range spans BOTH stop and target) resolve to the
    stop — the conservative assumption that you were stopped out first.

    Returns a COPY of the call with outcome / realized_R / exit_ts filled in;
    the input object is left untouched.
    """
    result = replace(call) if hasattr(call, "__dataclass_fields__") else call

    direction = str(getattr(call, "direction", "flat")).lower()
    horizon = int(getattr(call, "horizon_min", 60) or 0)
    entry = float(getattr(call, "entry", float("nan")))
    stop = float(getattr(call, "stop", float("nan")))
    target = float(getattr(call, "target", float("nan")))
    n = len(df)

    def _finish(outcome: str, realized_R: float, exit_idx: int):
        result.outcome = outcome
        result.realized_R = float(realized_R)
        result.exit_ts = _ts_at(df, exit_idx)
        return result

    # Flat / un-actionable calls -------------------------------------------- #
    invalid = (
        direction not in ("long", "short")
        or horizon <= 0
        or any(math.isnan(x) for x in (entry, stop, target))
    )
    if invalid:
        return _finish("flat", 0.0, i + max(horizon, 0))

    risk = (entry - stop) if direction == "long" else (stop - entry)
    if not (risk > 0):                      # geometry doesn't define a real trade
        return _finish("flat", 0.0, i + horizon)

    end = min(i + horizon, n - 1)
    highs, lows, closes = df["high"], df["low"], df["close"]

    outcome = None
    exit_idx = end
    pnl_pts = None
    for j in range(i + 1, end + 1):
        hi = float(highs.iloc[j])
        lo = float(lows.iloc[j])
        if direction == "long":
            if lo <= stop:                  # stop checked first -> SL-first tie
                outcome, exit_idx, pnl_pts = "loss", j, stop - entry
                break
            if hi >= target:
                outcome, exit_idx, pnl_pts = "win", j, target - entry
                break
        else:
            if hi >= stop:
                outcome, exit_idx, pnl_pts = "loss", j, entry - stop
                break
            if lo <= target:
                outcome, exit_idx, pnl_pts = "win", j, entry - target
                break

    if outcome is None:                     # never resolved -> timeout at horizon
        outcome, exit_idx = "timeout", end
        close_h = float(closes.iloc[end])
        pnl_pts = (close_h - entry) if direction == "long" else (entry - close_h)

    realized_R = (pnl_pts - spread_pts) / risk   # round-trip cost, then -> R
    return _finish(outcome, realized_R, exit_idx)


# --------------------------------------------------------------------------- #
# Decision-index sampling
# --------------------------------------------------------------------------- #
def sample_indices(df: pd.DataFrame, step: int, horizon_min: int = 60,
                   start: int = 0) -> list[int]:
    """Every `step` bars, leaving `horizon_min` bars of room at the end so each
    sampled decision has a full forward window to be evaluated over."""
    step = max(1, int(step))
    last = len(df) - int(horizon_min) - 1        # last index with a full horizon
    if last < start:
        return []
    return list(range(int(start), last + 1, step))


# --------------------------------------------------------------------------- #
# Full replay loop
# --------------------------------------------------------------------------- #
def run_replay(
    df: pd.DataFrame,
    snapshot_fn: Callable[[pd.DataFrame, int], MarketSnapshot],
    analyze_fn: Callable[[MarketSnapshot, str], AnalystCall],
    indices,
    journal=None,
    spread_pts: float = 1.0,
) -> list:
    """Replay the analyst across `indices`.

    For each decision bar i:
      1. build the snapshot the analyst sees        -> snapshot_fn(df, i)
      2. pull the reflective memory block           -> journal.memory_context()
      3. get the decision                           -> analyze_fn(snapshot, mem)
      4. score it against the future bars           -> evaluate_call(...)
      5. push the scored call (+snapshot) to memory -> journal.add(...)

    Returns the list of scored AnalystCall objects.
    """
    calls = []
    for i in indices:
        snapshot = snapshot_fn(df, i)
        memory_context = journal.memory_context() if journal is not None else ""
        call = analyze_fn(snapshot, memory_context)
        scored = evaluate_call(df, i, call, spread_pts=spread_pts)
        if journal is not None:
            # add(call, snapshot) if supported, else add(call)
            try:
                journal.add(scored, snapshot)
            except TypeError:
                journal.add(scored)
        calls.append(scored)
    return calls


# --------------------------------------------------------------------------- #
# End-to-end synthetic proof
# --------------------------------------------------------------------------- #
def _synthetic_df(n_bars: int = 4000, seed: int = 7) -> pd.DataFrame:
    """A random-walk 1-minute US30-ish OHLCV frame — no real edge in it."""
    import numpy as np

    rng = np.random.default_rng(seed)
    steps = rng.normal(0.0, 4.0, size=n_bars)          # ~4pt per-minute vol
    close = 38000.0 + np.cumsum(steps)
    open_ = np.empty(n_bars)
    open_[0] = 38000.0
    open_[1:] = close[:-1]
    wick = np.abs(rng.normal(0.0, 3.0, size=n_bars)) + 1.0
    high = np.maximum(open_, close) + wick
    low = np.minimum(open_, close) - wick
    ts = pd.date_range("2024-01-01 00:00", periods=n_bars, freq="1min", tz="UTC")
    return pd.DataFrame(
        {"timestamp": ts, "open": open_, "high": high, "low": low,
         "close": close, "volume": rng.integers(50, 500, size=n_bars)}
    )


def _synthetic_snapshot_fn(df, i):
    """Cheap causal snapshot (only bars <= i) for the demo."""
    import numpy as np

    lo = max(0, i - 14)
    rng_bars = df.iloc[lo:i + 1]
    atr = float((rng_bars["high"] - rng_bars["low"]).mean())
    price = float(df["close"].iloc[i])
    ret15 = (price / float(df["close"].iloc[i - 15]) - 1.0) if i >= 15 else 0.0
    ret60 = (price / float(df["close"].iloc[i - 60]) - 1.0) if i >= 60 else 0.0
    hour = df["timestamp"].iloc[i].hour
    session = ("ny_am" if 13 <= hour < 16 else
               "london" if 7 <= hour < 13 else
               "ny_pm" if 16 <= hour < 21 else
               "asia" if (hour >= 23 or hour < 7) else "off")
    vol_regime = "high" if atr > 9 else "low" if atr < 5 else "normal"
    return MarketSnapshot(
        ts=str(df["timestamp"].iloc[i]), price=price, atr_1m=atr,
        vol_regime=vol_regime, session=session, ret_15m=ret15, ret_60m=ret60,
    )


def _toy_analyze_fn(snapshot, memory_context):
    """A deliberately naive momentum analyst — trades 15m drift, abstains when
    flat. It should score ~random after costs, which is exactly the point of an
    honest evaluator."""
    atr = snapshot.atr_1m if snapshot.atr_1m == snapshot.atr_1m else 5.0
    price = snapshot.price
    drift = snapshot.ret_15m
    thresh = 0.0008
    if drift > thresh:
        direction, conf = "long", min(10, 5 + int(drift / thresh))
        stop, target = price - 1.5 * atr, price + 3.0 * atr
    elif drift < -thresh:
        direction, conf = "short", min(10, 5 + int(-drift / thresh))
        stop, target = price + 1.5 * atr, price - 3.0 * atr
    else:
        return AnalystCall(ts=snapshot.ts, direction="flat", confidence=0,
                           thesis="no drift edge — stand aside")
    return AnalystCall(
        ts=snapshot.ts, direction=direction, confidence=conf,
        thesis=f"15m drift {drift:+.2%} in {snapshot.session}",
        entry=price, stop=stop, target=target, horizon_min=30,
    )


if __name__ == "__main__":
    try:
        from .journal import Journal
        from .metrics import scorecard
    except ImportError:
        from journal import Journal
        from metrics import scorecard

    df = _synthetic_df()
    journal = Journal()
    idx = sample_indices(df, step=15, horizon_min=30)
    print(f"synthetic df: {len(df)} bars | decisions: {len(idx)}")

    calls = run_replay(df, _synthetic_snapshot_fn, _toy_analyze_fn, idx,
                       journal=journal, spread_pts=1.0)

    card = scorecard(calls, df=df)
    print("\n=== SCORECARD (replay.py end-to-end) ===")
    import json
    print(json.dumps(card, indent=2, default=str))
    print("\n=== MEMORY CONTEXT (fed back to the analyst) ===")
    print(journal.memory_context())
