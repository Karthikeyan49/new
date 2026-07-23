"""
SMC pattern detectors: Fair Value Gaps, Order Blocks, displacement, liquidity
sweeps. Pure functions over numpy OHLC arrays, coded directly from the research
spec (§5-§8). None of these invent levels — every zone is derived from candle
geometry.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class FVG:
    idx: int          # index of candle 3 (where the gap is complete)
    top: float
    bottom: float
    bullish: bool

    @property
    def mid(self) -> float:            # consequent encroachment (50% CE)
        return (self.top + self.bottom) / 2.0


@dataclass
class OrderBlock:
    idx: int
    low: float
    high: float
    body_low: float
    body_high: float
    bullish: bool


def bullish_fvg(high, low, i) -> FVG | None:
    """3-candle bullish FVG at candle i (uses i-2, i-1, i): low[i] > high[i-2]."""
    if i < 2:
        return None
    if low[i] > high[i - 2]:
        return FVG(i, top=float(low[i]), bottom=float(high[i - 2]), bullish=True)
    return None


def bearish_fvg(high, low, i) -> FVG | None:
    """3-candle bearish FVG at candle i: high[i] < low[i-2]."""
    if i < 2:
        return None
    if high[i] < low[i - 2]:
        return FVG(i, top=float(low[i - 2]), bottom=float(high[i]), bullish=False)
    return None


def find_fvg_in_leg(high, low, start, end, bullish: bool) -> FVG | None:
    """Most recent FVG of the required polarity within [start, end] (inclusive)."""
    fn = bullish_fvg if bullish else bearish_fvg
    for i in range(end, max(start + 1, 1), -1):
        fvg = fn(high, low, i)
        if fvg is not None:
            return fvg
    return None


def order_block(open_, high, low, close, leg_start, leg_end, bullish: bool) -> OrderBlock | None:
    """Last opposing-close candle before the displacement leg (§5).

    Bullish OB = last down-close candle before an up-move; scanned backward from
    the start of the impulse leg.
    """
    for i in range(leg_start, max(leg_start - 30, -1), -1):
        down = close[i] < open_[i]
        up = close[i] > open_[i]
        if bullish and down:
            return OrderBlock(
                i, float(low[i]), float(high[i]),
                float(min(open_[i], close[i])), float(max(open_[i], close[i])), True,
            )
        if not bullish and up:
            return OrderBlock(
                i, float(low[i]), float(high[i]),
                float(min(open_[i], close[i])), float(max(open_[i], close[i])), False,
            )
    return None


def is_displacement(open_, high, low, close, i, atr_i, k_atr=1.0, body_ratio=0.6) -> bool:
    """Impulsive candle: body >= k*ATR OR body/range >= body_ratio (§7)."""
    body = abs(close[i] - open_[i])
    rng = high[i] - low[i]
    if rng <= 0:
        return False
    return (body >= k_atr * atr_i) or (body / rng >= body_ratio)


def is_sweep_low(high, low, close, i, level) -> bool:
    """Bullish sweep of sell-side liquidity: wick pierces below level, closes back above."""
    return low[i] < level and close[i] > level


def is_sweep_high(high, low, close, i, level) -> bool:
    """Bearish sweep of buy-side liquidity: wick pierces above level, closes back below."""
    return high[i] > level and close[i] < level
