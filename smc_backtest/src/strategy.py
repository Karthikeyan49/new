"""
The SMC entry engine.

Implements the cross-creator CONSENSUS model (ICT 2022 / Silver Bullet, TJR,
Photon, Casper, Fractal Flow — and the Alchemist's sweep+rejection variant),
which all reduce to the same four-step chain:

    1. HTF bias        — trade only with the prevailing market-structure trend
    2. Liquidity sweep — price wicks through a prior swing low/high and closes back
    3. MSS + displacement — a close breaks internal structure against the sweep,
                            leaving a Fair Value Gap (impulse / displacement)
    4. Entry on POI    — limit at the FVG 50% (CE); fallback to the order block

    Risk: SL beyond the swept wick (+ buffer); TP at the opposite liquidity pool,
          filtered to a minimum reward:risk.

The engine is a per-bar state machine (SCAN -> ARMED -> PENDING -> OPEN) and only
ever uses swings whose confirmation bar has already passed, so there is no
look-ahead. It is fully symmetric for longs and shorts.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from indicators import atr as atr_ind, ny_hour
from smc import (
    find_fvg_in_leg, order_block, is_displacement, is_sweep_low, is_sweep_high,
)
from structure import find_swings


@dataclass
class Params:
    n_major: int = 5          # fractal lookback for HTF structure / liquidity pools
    n_internal: int = 2       # fractal lookback for the MSS confirmation
    atr_period: int = 14
    disp_k_atr: float = 1.0   # displacement: body >= k*ATR ...
    disp_body_ratio: float = 0.6  # ... OR body/range >= ratio
    liq_lookback: int = 12    # how many recent swing lows/highs count as liquidity
    mss_window: int = 12      # bars after a sweep to allow the MSS to form
    entry_window: int = 18    # bars after MSS to allow the retrace fill
    sl_buffer_atr: float = 0.1  # stop buffer beyond the swept wick, in ATR
    min_rr: float = 3.0       # reject setups whose TP/SL reward:risk < this
    require_discount: bool = True   # longs only in discount, shorts only in premium
    use_killzone: bool = False      # intraday session filter (NY killzones)
    poi: str = "fvg"          # 'fvg' (50% CE) or 'ob' (order block proximal)


# NY killzones (hour-of-day, ET): London 02-05, NY-AM 07-11
_KILLZONE_HOURS = set(range(2, 5)) | set(range(7, 11))


@dataclass
class Trade:
    direction: int            # +1 long, -1 short
    setup_bar: int
    entry_bar: int
    entry: float
    sl: float
    tp: float
    exit_bar: int = -1
    exit: float = float("nan")
    r_multiple: float = float("nan")
    outcome: str = ""         # 'win' / 'loss'
    entry_time: pd.Timestamp = None
    exit_time: pd.Timestamp = None


class SMCStrategy:
    def __init__(self, df: pd.DataFrame, p: Params):
        self.df = df.reset_index(drop=True)
        self.p = p
        self.o = self.df["open"].to_numpy(float)
        self.h = self.df["high"].to_numpy(float)
        self.l = self.df["low"].to_numpy(float)
        self.c = self.df["close"].to_numpy(float)
        self.ts = self.df["timestamp"]
        self.atr = atr_ind(self.df, p.atr_period).to_numpy(float)
        self.major = find_swings(self.h, self.l, p.n_major)
        self.internal = find_swings(self.h, self.l, p.n_internal)

    # -- helpers ---------------------------------------------------------
    def _killzone_ok(self, i: int) -> bool:
        if not self.p.use_killzone:
            return True
        return ny_hour(self.ts.iloc[i]) in _KILLZONE_HOURS

    def run(self) -> list[Trade]:
        p = self.p
        n = len(self.df)
        trades: list[Trade] = []

        # per-bar "released" swing structures (confirm_idx <= current bar)
        maj_by_confirm: dict[int, list] = {}
        int_by_confirm: dict[int, list] = {}
        for s in self.major:
            maj_by_confirm.setdefault(s.confirm_idx, []).append(s)
        for s in self.internal:
            int_by_confirm.setdefault(s.confirm_idx, []).append(s)

        maj_highs: list[tuple[int, float]] = []   # (pivot_idx, price)
        maj_lows: list[tuple[int, float]] = []
        int_highs: list[tuple[int, float]] = []
        int_lows: list[tuple[int, float]] = []

        last_major_high = None   # (idx, price) for dealing range / bias
        last_major_low = None
        bias = None              # 'bull' / 'bear' / None

        phase = "SCAN"
        setup: dict = {}
        self.dbg = {"bias_bull": 0, "bias_bear": 0, "sweep": 0, "armed": 0,
                    "mss": 0, "fvg_ok": 0, "rr_ok": 0, "pending": 0, "filled": 0}

        for t in range(n):
            # release swings confirmed exactly at bar t
            for s in maj_by_confirm.get(t, []):
                (maj_highs if s.kind == "H" else maj_lows).append((s.pivot_idx, s.price))
                if s.kind == "H":
                    last_major_high = (s.pivot_idx, s.price)
                else:
                    last_major_low = (s.pivot_idx, s.price)
            for s in int_by_confirm.get(t, []):
                (int_highs if s.kind == "H" else int_lows).append((s.pivot_idx, s.price))

            # update HTF bias via close-based break of the last major swing (BOS/CHoCH)
            if last_major_high and self.c[t] > last_major_high[1]:
                bias = "bull"
            if last_major_low and self.c[t] < last_major_low[1]:
                bias = "bear"

            # dealing range / equilibrium from the most recent major high & low
            eq = None
            if last_major_high and last_major_low:
                eq = (last_major_high[1] + last_major_low[1]) / 2.0

            if bias == "bull":
                self.dbg["bias_bull"] += 1
            elif bias == "bear":
                self.dbg["bias_bear"] += 1

            atr_t = self.atr[t]
            if np.isnan(atr_t) or atr_t <= 0:
                continue

            # ================= state machine =================
            if phase == "SCAN":
                # ---- look for a liquidity sweep aligned with bias ----
                if bias == "bull":
                    # sweep of a recent swing low (sell-side liquidity)
                    cands = [pr for (_, pr) in (int_lows + maj_lows)[-p.liq_lookback:]
                             if pr > self.l[t]]
                    swept = [lv for lv in cands if is_sweep_low(self.h, self.l, self.c, t, lv)]
                    if swept and (eq is None or not p.require_discount or self.l[t] < eq):
                        ref_highs = [pr for (_, pr) in int_highs if pr > self.c[t]]
                        if ref_highs:
                            setup = dict(dir=1, sweep_bar=t, sweep_px=self.l[t],
                                         ref=min(ref_highs), eq=eq)
                            phase = "ARMED"
                            self.dbg["sweep"] += 1
                elif bias == "bear":
                    cands = [pr for (_, pr) in (int_highs + maj_highs)[-p.liq_lookback:]
                             if pr < self.h[t]]
                    swept = [lv for lv in cands if is_sweep_high(self.h, self.l, self.c, t, lv)]
                    if swept and (eq is None or not p.require_discount or self.h[t] > eq):
                        ref_lows = [pr for (_, pr) in int_lows if pr < self.c[t]]
                        if ref_lows:
                            setup = dict(dir=-1, sweep_bar=t, sweep_px=self.h[t],
                                         ref=max(ref_lows), eq=eq)
                            phase = "ARMED"
                            self.dbg["sweep"] += 1

            elif phase == "ARMED":
                # ---- wait for MSS (close breaks internal structure) + FVG ----
                if t - setup["sweep_bar"] > p.mss_window:
                    phase, setup = "SCAN", {}
                else:
                    d = setup["dir"]
                    mss = (self.c[t] > setup["ref"]) if d == 1 else (self.c[t] < setup["ref"])
                    disp = any(
                        is_displacement(self.o, self.h, self.l, self.c, j, self.atr[j],
                                        p.disp_k_atr, p.disp_body_ratio)
                        for j in range(setup["sweep_bar"], t + 1)
                    )
                    if mss and disp and self._killzone_ok(t):
                        self.dbg["mss"] += 1
                        fvg = find_fvg_in_leg(self.h, self.l, setup["sweep_bar"], t, d == 1)
                        entry = None
                        if p.poi == "fvg" and fvg is not None:
                            entry = fvg.mid
                        if entry is None:  # fallback to order block proximal edge
                            ob = order_block(self.o, self.h, self.l, self.c,
                                             setup["sweep_bar"], t, d == 1)
                            if ob is not None:
                                entry = ob.high if d == 1 else ob.low
                        if entry is not None:
                            self.dbg["fvg_ok"] += 1
                            sl = (setup["sweep_px"] - p.sl_buffer_atr * atr_t if d == 1
                                  else setup["sweep_px"] + p.sl_buffer_atr * atr_t)
                            risk = (entry - sl) if d == 1 else (sl - entry)
                            disc_ok = (not p.require_discount or setup["eq"] is None or
                                       (entry < setup["eq"] if d == 1 else entry > setup["eq"]))
                            tp = self._liquidity_target(d, entry, risk, maj_highs, maj_lows,
                                                        int_highs, int_lows)
                            if risk > 0 and disc_ok and tp is not None:
                                reward = (tp - entry) if d == 1 else (entry - tp)
                                if reward / risk >= p.min_rr:
                                    setup.update(mss_bar=t, entry=entry, sl=sl, tp=tp)
                                    phase = "PENDING"
                                    self.dbg["pending"] += 1
                    if phase == "ARMED" and t - setup["sweep_bar"] > p.mss_window:
                        phase, setup = "SCAN", {}

            elif phase == "PENDING":
                # ---- wait for retrace to fill the limit at the POI ----
                if t - setup["mss_bar"] > p.entry_window:
                    phase, setup = "SCAN", {}
                else:
                    d = setup["dir"]
                    # invalidation before fill
                    if (d == 1 and self.l[t] <= setup["sl"]) or (d == -1 and self.h[t] >= setup["sl"]):
                        phase, setup = "SCAN", {}
                    elif (d == 1 and self.l[t] <= setup["entry"]) or (d == -1 and self.h[t] >= setup["entry"]):
                        tr = Trade(direction=d, setup_bar=setup["sweep_bar"], entry_bar=t,
                                   entry=setup["entry"], sl=setup["sl"], tp=setup["tp"],
                                   entry_time=self.ts.iloc[t])
                        self._manage(tr)
                        trades.append(tr)
                        self.dbg["filled"] += 1
                        phase, setup = "SCAN", {}

        return trades

    def _liquidity_target(self, d, entry, risk, maj_highs, maj_lows, int_highs, int_lows):
        """Draw on liquidity: the nearest opposite pool that offers >= min_rr.

        Major swing pools are preferred (a genuine draw on liquidity); internal
        pools are only used if no qualifying major pool exists. Among qualifying
        pools we take the NEAREST (smallest sufficient reward) to stay conservative.
        """
        need = self.p.min_rr * risk
        if d == 1:
            maj = sorted(pr for (_, pr) in maj_highs if pr - entry >= need)
            if maj:
                return maj[0]
            inter = sorted(pr for (_, pr) in int_highs if pr - entry >= need)
            return inter[0] if inter else None
        maj = sorted((pr for (_, pr) in maj_lows if entry - pr >= need), reverse=True)
        if maj:
            return maj[0]
        inter = sorted((pr for (_, pr) in int_lows if entry - pr >= need), reverse=True)
        return inter[0] if inter else None

    def _manage(self, tr: Trade):
        """Walk forward from the entry bar to resolve SL/TP (SL-first on ties)."""
        d = tr.direction
        risk = (tr.entry - tr.sl) if d == 1 else (tr.sl - tr.entry)
        for j in range(tr.entry_bar, len(self.df)):
            hit_sl = self.l[j] <= tr.sl if d == 1 else self.h[j] >= tr.sl
            hit_tp = self.h[j] >= tr.tp if d == 1 else self.l[j] <= tr.tp
            if hit_sl:  # conservative: stop takes priority on same bar
                tr.exit_bar, tr.exit, tr.outcome = j, tr.sl, "loss"
                tr.r_multiple = -1.0
                tr.exit_time = self.ts.iloc[j]
                return
            if hit_tp:
                tr.exit_bar, tr.exit, tr.outcome = j, tr.tp, "win"
                tr.r_multiple = ((tr.tp - tr.entry) if d == 1 else (tr.entry - tr.tp)) / risk
                tr.exit_time = self.ts.iloc[j]
                return
        # unresolved at data end: mark open, mark-to-market R
        j = len(self.df) - 1
        tr.exit_bar, tr.exit = j, self.c[j]
        tr.r_multiple = ((tr.exit - tr.entry) if d == 1 else (tr.entry - tr.exit)) / risk
        tr.outcome = "open"
        tr.exit_time = self.ts.iloc[j]
