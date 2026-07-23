"""Small technical helpers used by the SMC engine."""
from __future__ import annotations

import numpy as np
import pandas as pd


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder's Average True Range."""
    h, l, c = df["high"], df["low"], df["close"]
    prev_c = c.shift(1)
    tr = pd.concat(
        [(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1
    ).max(axis=1)
    # Wilder smoothing == EMA with alpha = 1/period
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def ny_hour(ts: pd.Timestamp) -> int:
    """Hour-of-day in America/New_York (DST-aware) for a tz-aware UTC stamp."""
    return ts.tz_convert("America/New_York").hour
