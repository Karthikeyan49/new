"""
Market-structure primitives: swing fractals.

Everything downstream (BOS/CHoCH, dealing range, liquidity pools) is built on
confirmed swing points, so this module deliberately encodes the fractal rule
exactly as the SMC/ICT literature states it (§1 of the research spec):

    SwingHigh(i, N):  high[i] > high[i-k] AND high[i] > high[i+k]  for all k in 1..N
    SwingLow(i, N):   low[i]  < low[i-k]  AND low[i]  < low[i+k]   for all k in 1..N

A pivot at bar `i` is only *confirmed* N bars later (you need N candles to its
right). We record that confirmation lag so the backtest never "sees" a swing
before it could exist in real time (no look-ahead).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Swing:
    pivot_idx: int      # bar index of the pivot
    confirm_idx: int    # bar index at which it becomes known (pivot_idx + N)
    price: float
    kind: str           # 'H' or 'L'


def find_swings(high: np.ndarray, low: np.ndarray, n: int) -> list[Swing]:
    """Return all confirmed fractal swings, ordered by confirmation time.

    Uses strict inequalities (standard SMC convention); a pivot must strictly
    exceed all N neighbours on both sides.
    """
    swings: list[Swing] = []
    m = len(high)
    for i in range(n, m - n):
        hi = high[i]
        lo = low[i]
        is_high = True
        is_low = True
        for k in range(1, n + 1):
            if not (hi > high[i - k] and hi > high[i + k]):
                is_high = False
            if not (lo < low[i - k] and lo < low[i + k]):
                is_low = False
            if not is_high and not is_low:
                break
        if is_high:
            swings.append(Swing(i, i + n, float(hi), "H"))
        if is_low:
            swings.append(Swing(i, i + n, float(lo), "L"))
    swings.sort(key=lambda s: (s.confirm_idx, s.pivot_idx))
    return swings
