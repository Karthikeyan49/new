"""
Multi-timeframe market structure.

True top-down SMC: read structure on the high timeframes (Weekly -> Daily -> H4)
to set directional BIAS, then execute on the base timeframe (H1). Higher
timeframes are RESAMPLED from the base feed, so a single H1 file yields the whole
cascade.

No look-ahead: an HTF bar's bias is only made available to a base bar once that
HTF candle has fully CLOSED. We stamp each HTF bar with its close time
(bar_start + timeframe) and align to the base series with a *backward*
merge_asof, so a base bar at time t only ever sees HTF structure that was
complete at or before t.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from structure import find_swings

# timeframe -> its duration (for computing an HTF bar's close time)
_TF_DELTA = {
    "4h": pd.Timedelta(hours=4),
    "1D": pd.Timedelta(days=1),
    "1W": pd.Timedelta(weeks=1),
}


def resample_ohlc(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample the canonical OHLCV frame to a higher timeframe."""
    s = df.set_index("timestamp")
    out = s.resample(rule, label="left", closed="left").agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"), volume=("volume", "sum"),
    ).dropna(subset=["open", "high", "low", "close"])
    return out.reset_index()


def causal_bias(df: pd.DataFrame, n: int) -> np.ndarray:
    """Per-bar market-structure bias (+1 bull / -1 bear / 0 none), computed
    causally: bar i's value uses only swings confirmed by bar i and close-breaks
    seen up to bar i (identical logic to the base engine's bias)."""
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    swings = find_swings(h, l, n)
    by_confirm: dict[int, list] = {}
    for sw in swings:
        by_confirm.setdefault(sw.confirm_idx, []).append(sw)

    last_high = last_low = None
    bias = 0
    out = np.zeros(len(df), dtype=int)
    for i in range(len(df)):
        for sw in by_confirm.get(i, []):
            if sw.kind == "H":
                last_high = sw.price
            else:
                last_low = sw.price
        if last_high is not None and c[i] > last_high:
            bias = 1
        if last_low is not None and c[i] < last_low:
            bias = -1
        out[i] = bias
    return out


def htf_bias_for_base(base_df: pd.DataFrame, tfs=("1W", "1D"), n: int = 3,
                      mode: str = "all") -> np.ndarray:
    """Combined HTF bias aligned to every base bar (no look-ahead).

    mode='all'  -> all listed timeframes must agree, else 0 (flat/conflict)
    mode='any_daily' -> use the finest listed TF only
    """
    base_ts = base_df[["timestamp"]].sort_values("timestamp").reset_index(drop=True)
    cols = []
    for tf in tfs:
        htf = resample_ohlc(base_df, tf)
        b = causal_bias(htf, n)
        close_time = htf["timestamp"] + _TF_DELTA[tf]
        ref = pd.DataFrame({"close_time": close_time, "bias": b}).sort_values("close_time")
        merged = pd.merge_asof(base_ts, ref, left_on="timestamp",
                               right_on="close_time", direction="backward")
        cols.append(merged["bias"].fillna(0).to_numpy(int))

    stack = np.vstack(cols) if cols else np.zeros((1, len(base_df)), int)
    if mode == "any_daily":
        return stack[-1]
    # 'all': agreement -> that direction, else 0
    agree = np.all(stack == stack[0], axis=0)
    return np.where(agree, stack[0], 0)
