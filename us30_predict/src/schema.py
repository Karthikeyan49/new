"""
Shared contract for the US30 human-like analyst system.

The whole system is three stages talking through these two objects:

    perception.py :  1-min data  ->  MarketSnapshot   (what a human sees)
    analyst.py    :  MarketSnapshot -> AnalystCall     (what a human decides)
    replay.py     :  AnalystCall + future bars -> scored AnalystCall (was it right)

Keeping the contract fixed lets each stage be built and tested independently.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

import pandas as pd


def load_m1(path: str) -> pd.DataFrame:
    """Load the canonical 1-minute file (timestamp,open,high,low,close,volume)."""
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df.sort_values("timestamp").reset_index(drop=True)


@dataclass
class MarketSnapshot:
    """A structured, causal read of the market at one decision time — the
    multi-timeframe 'chart view' a human analyst would form. Built only from
    data at or before `ts` (no look-ahead)."""
    ts: str
    price: float
    # per-timeframe structure: tf -> {trend, swing_high, swing_low, last_event}
    tfs: dict = field(default_factory=dict)
    # liquidity
    nearest_bsl: float = float("nan")     # nearest buy-side pool above
    nearest_ssl: float = float("nan")     # nearest sell-side pool below
    recent_sweep: str = "none"            # 'buyside'|'sellside'|'none'
    # volatility / regime
    atr_1m: float = float("nan")
    atr_pct: float = float("nan")
    vol_regime: str = "normal"            # 'low'|'normal'|'high'
    # premium / discount
    equilibrium: float = float("nan")
    pd_zone: str = "equilibrium"          # 'premium'|'discount'|'equilibrium'
    # time
    session: str = "off"                  # 'asia'|'london'|'ny_am'|'ny_pm'|'off'
    in_killzone: bool = False
    # momentum
    ret_15m: float = float("nan")
    ret_60m: float = float("nan")

    def to_prompt(self) -> str:
        """Render the snapshot the way a chart reads — fed to the analyst."""
        lines = [f"US30 @ {self.ts}  price={self.price:.1f}"]
        for tf, s in self.tfs.items():
            lines.append(f"  {tf:>3}: trend={s.get('trend')} "
                         f"swingH={s.get('swing_high')} swingL={s.get('swing_low')} "
                         f"event={s.get('last_event')}")
        lines.append(f"  liquidity: BSL above={self.nearest_bsl:.1f} "
                     f"SSL below={self.nearest_ssl:.1f} recent_sweep={self.recent_sweep}")
        lines.append(f"  volatility: ATR={self.atr_1m:.1f} ({self.atr_pct:.2f}%) "
                     f"regime={self.vol_regime}")
        lines.append(f"  pd: equilibrium={self.equilibrium:.1f} zone={self.pd_zone}")
        lines.append(f"  time: session={self.session} killzone={self.in_killzone}")
        lines.append(f"  momentum: 15m={self.ret_15m:+.2%} 60m={self.ret_60m:+.2%}")
        return "\n".join(lines)


@dataclass
class AnalystCall:
    """The analyst's decision for one snapshot — plus fields the replay fills in."""
    ts: str
    direction: str = "flat"      # 'long'|'short'|'flat'
    confidence: int = 0          # 0-10 (0 = no edge / abstain)
    thesis: str = ""             # natural-language reasoning
    entry: float = float("nan")
    stop: float = float("nan")   # invalidation
    target: float = float("nan")
    horizon_min: int = 60
    # --- filled by replay.py ---
    outcome: str = ""            # 'win'|'loss'|'flat'|'timeout'
    realized_R: float = float("nan")
    exit_ts: str = ""

    def as_row(self) -> dict:
        return asdict(self)
