"""
PERCEPTION stage of the US30 human-like analyst system.

Turns the raw 1-minute OHLCV series into a structured, CAUSAL `MarketSnapshot`
at any decision index `i` — the way a human reads a multi-timeframe chart.

Causality rule: only bars with index <= i are ever used. Every computation
starts from `df.iloc[:i+1]`, so there is no look-ahead.

The heavy lifting (resampling to 5m/15m/1h/4h/1D, fractal swing detection,
market-structure events, liquidity pools, volatility regime, premium/discount,
session/killzone timing, momentum) is done per-snapshot. That is fine because
we only ever snapshot a handful of sampled decision points, not all ~100k bars.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from schema import MarketSnapshot, load_m1


# ----------------------------------------------------------------------------
# config
# ----------------------------------------------------------------------------
FRACTAL_N = 2          # a swing needs N strictly-higher/lower neighbours each side
ATR_PERIOD = 14        # 1m ATR lookback
RECENT_VOL_BARS = 60   # window for "recent" realized vol
VOL_MEDIAN_BARS = 1500 # rolling window whose median defines the normal vol level
SWEEP_LOOKBACK = 5     # how many recent 1m bars can carry a liquidity sweep
EQ_BAND_PCT = 0.05     # +/- band around equilibrium that still counts as 'equilibrium'

# pandas resample rules per timeframe label
_TF_RULES = {
    "5m":  "5min",
    "15m": "15min",
    "1h":  "1h",
    "4h":  "4h",
    "1D":  "1D",
}


# ----------------------------------------------------------------------------
# low-level helpers
# ----------------------------------------------------------------------------
def _resample(df1m: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample a 1m OHLCV frame (indexed by timestamp) to `rule`.

    Only complete information available up to bar i is present in df1m, so the
    final (possibly partial) higher-TF candle is a legitimate causal read of
    "the candle currently forming".
    """
    agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }
    out = df1m.resample(rule, label="left", closed="left").agg(agg)
    return out.dropna(subset=["open"])


def _fractal_swings(highs: np.ndarray, lows: np.ndarray, n: int = FRACTAL_N):
    """Return (swing_high_idx, swing_low_idx) lists using an N-neighbour fractal.

    A swing high at position p means highs[p] is strictly greater than the N bars
    on each side. Swing low is the mirror. Endpoints (first/last N bars) can never
    be confirmed as fractals — which is correct causally, a swing is only known
    once N bars have printed after it.
    """
    sh, sl = [], []
    m = len(highs)
    for p in range(n, m - n):
        hp = highs[p]
        if hp == max(highs[p - n:p + n + 1]) and \
           hp > highs[p - n:p].max() and hp > highs[p + 1:p + n + 1].max():
            sh.append(p)
        lp = lows[p]
        if lp == min(lows[p - n:p + n + 1]) and \
           lp < lows[p - n:p].min() and lp < lows[p + 1:p + n + 1].min():
            sl.append(p)
    return sh, sl


def _classify_structure(tf: pd.DataFrame):
    """Read trend, last swing high/low and last structure event for one TF.

    trend:  HH+HL -> 'bull', LH+LL -> 'bear', otherwise 'range'
            (compares the last two confirmed swing highs and last two swing lows)
    event:  the most recent break of structure / change of character:
            BOS_up   = close breaks the prior swing high, trend was already up
            BOS_down = close breaks the prior swing low, trend was already down
            CHoCH_up = close breaks prior swing high while structure was bearish
            CHoCH_down = close breaks prior swing low while structure was bullish
    """
    highs = tf["high"].to_numpy(dtype=float)
    lows = tf["low"].to_numpy(dtype=float)
    closes = tf["close"].to_numpy(dtype=float)
    sh_idx, sl_idx = _fractal_swings(highs, lows)

    last_sh = float(highs[sh_idx[-1]]) if sh_idx else float("nan")
    last_sl = float(lows[sl_idx[-1]]) if sl_idx else float("nan")

    # trend from the last two confirmed swings on each side
    trend = "range"
    if len(sh_idx) >= 2 and len(sl_idx) >= 2:
        hh = highs[sh_idx[-1]] > highs[sh_idx[-2]]
        hl = lows[sl_idx[-1]] > lows[sl_idx[-2]]
        lh = highs[sh_idx[-1]] < highs[sh_idx[-2]]
        ll = lows[sl_idx[-1]] < lows[sl_idx[-2]]
        if hh and hl:
            trend = "bull"
        elif lh and ll:
            trend = "bear"

    # structure event: walk bars after the most recent confirmed swings and see
    # which reference level (prior swing high / low) the close broke last.
    event = "none"
    # reference swing high/low that existed *before* the breaking bar
    if sh_idx or sl_idx:
        # candidate break of the last confirmed swing high (buy-side break)
        up_break_pos = None
        if sh_idx:
            ref_h = highs[sh_idx[-1]]
            start = sh_idx[-1] + 1
            for p in range(start, len(closes)):
                if closes[p] > ref_h:
                    up_break_pos = p
                    break
        # candidate break of the last confirmed swing low (sell-side break)
        dn_break_pos = None
        if sl_idx:
            ref_l = lows[sl_idx[-1]]
            start = sl_idx[-1] + 1
            for p in range(start, len(closes)):
                if closes[p] < ref_l:
                    dn_break_pos = p
                    break

        # whichever break happened most recently defines the last event
        pick = None
        if up_break_pos is not None and dn_break_pos is not None:
            pick = "up" if up_break_pos >= dn_break_pos else "dn"
        elif up_break_pos is not None:
            pick = "up"
        elif dn_break_pos is not None:
            pick = "dn"

        if pick == "up":
            # continuation if we were already bullish, else change of character
            event = "BOS_up" if trend == "bull" else "CHoCH_up"
        elif pick == "dn":
            event = "BOS_down" if trend == "bear" else "CHoCH_down"

    return {
        "trend": trend,
        "swing_high": round(last_sh, 1) if last_sh == last_sh else last_sh,
        "swing_low": round(last_sl, 1) if last_sl == last_sl else last_sl,
        "last_event": event,
    }


def _all_swings(tf: pd.DataFrame):
    """Return (swing_high_prices, swing_low_prices) arrays for a TF."""
    highs = tf["high"].to_numpy(dtype=float)
    lows = tf["low"].to_numpy(dtype=float)
    sh_idx, sl_idx = _fractal_swings(highs, lows)
    return highs[sh_idx], lows[sl_idx]


def _atr(df1m: pd.DataFrame, period: int = ATR_PERIOD) -> float:
    """Wilder-style ATR on the 1m frame (last value)."""
    if len(df1m) < 2:
        return float("nan")
    high = df1m["high"].to_numpy(dtype=float)
    low = df1m["low"].to_numpy(dtype=float)
    close = df1m["close"].to_numpy(dtype=float)
    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]
    tr = np.maximum.reduce([
        high - low,
        np.abs(high - prev_close),
        np.abs(low - prev_close),
    ])
    tr = tr[1:]  # first TR is degenerate
    if len(tr) < period:
        return float(np.mean(tr)) if len(tr) else float("nan")
    # Wilder smoothing
    atr = np.mean(tr[:period])
    for t in tr[period:]:
        atr = (atr * (period - 1) + t) / period
    return float(atr)


def _session_and_killzone(ts_ny: pd.Timestamp):
    """Map a New-York-local timestamp to a session and killzone flag."""
    h = ts_ny.hour
    if 20 <= h < 24:
        session = "asia"
    elif 2 <= h < 5:
        session = "london"
    elif 7 <= h < 11:
        session = "ny_am"
    elif 13 <= h < 16:
        session = "ny_pm"
    else:
        session = "off"
    in_kz = session in ("london", "ny_am")
    return session, in_kz


# ----------------------------------------------------------------------------
# main builder
# ----------------------------------------------------------------------------
def build_snapshot(df: pd.DataFrame, i: int) -> MarketSnapshot:
    """Build a causal MarketSnapshot at decision index `i`.

    Uses only df.iloc[:i+1]. Everything a human would glean from flipping across
    the 5m/15m/1h/4h/1D charts is condensed into the snapshot.
    """
    if i < 0:
        i += len(df)
    hist = df.iloc[:i + 1]
    if len(hist) == 0:
        raise ValueError("no data at or before index i")

    row = hist.iloc[-1]
    ts = row["timestamp"]
    price = float(row["close"])

    # index by timestamp for resampling
    h1m = hist.set_index("timestamp")[["open", "high", "low", "close", "volume"]]

    snap = MarketSnapshot(ts=str(ts), price=price)

    # --- multi-timeframe structure ------------------------------------------
    tf_frames = {}
    for tf_label, rule in _TF_RULES.items():
        rs = _resample(h1m, rule)
        tf_frames[tf_label] = rs
        if len(rs) >= (2 * FRACTAL_N + 1):
            snap.tfs[tf_label] = _classify_structure(rs)
        else:
            snap.tfs[tf_label] = {
                "trend": "range",
                "swing_high": float("nan"),
                "swing_low": float("nan"),
                "last_event": "none",
            }

    # --- liquidity: nearest un-swept pools from 15m/1h swings ----------------
    pool_highs, pool_lows = [], []
    for tf_label in ("15m", "1h"):
        sh_prices, sl_prices = _all_swings(tf_frames[tf_label])
        pool_highs.extend(sh_prices.tolist())
        pool_lows.extend(sl_prices.tolist())

    highs_above = [h for h in pool_highs if h > price]
    lows_below = [l for l in pool_lows if l < price]
    snap.nearest_bsl = float(min(highs_above)) if highs_above else float("nan")
    snap.nearest_ssl = float(max(lows_below)) if lows_below else float("nan")

    # --- recent sweep on the 1m series --------------------------------------
    snap.recent_sweep = _detect_sweep(h1m)

    # --- volatility ----------------------------------------------------------
    atr = _atr(h1m)
    snap.atr_1m = atr
    snap.atr_pct = (atr / price * 100.0) if (price and atr == atr) else float("nan")
    snap.vol_regime = _vol_regime(h1m)

    # --- premium / discount from most recent 1h dealing range ---------------
    eq, zone = _premium_discount(tf_frames["1h"], price)
    snap.equilibrium = eq
    snap.pd_zone = zone

    # --- time ----------------------------------------------------------------
    ts_ny = ts.tz_convert("America/New_York")
    snap.session, snap.in_killzone = _session_and_killzone(ts_ny)

    # --- momentum ------------------------------------------------------------
    snap.ret_15m = _pct_return(h1m["close"], 15)
    snap.ret_60m = _pct_return(h1m["close"], 60)

    return snap


def _detect_sweep(h1m: pd.DataFrame) -> str:
    """Detect a liquidity sweep in the last few 1m bars.

    buyside sweep  = a recent bar wicked ABOVE a prior 1m swing high but CLOSED
                     back below it (stop-run above, rejection).
    sellside sweep = a recent bar wicked BELOW a prior 1m swing low but CLOSED
                     back above it.
    """
    highs = h1m["high"].to_numpy(dtype=float)
    lows = h1m["low"].to_numpy(dtype=float)
    closes = h1m["close"].to_numpy(dtype=float)
    n = len(highs)
    if n < (2 * FRACTAL_N + 2 + SWEEP_LOOKBACK):
        return "none"

    sh_idx, sl_idx = _fractal_swings(highs, lows)

    for p in range(n - 1, n - 1 - SWEEP_LOOKBACK, -1):
        # prior swing highs confirmed before this bar (need FRACTAL_N bars after
        # the swing, so swing pos <= p - FRACTAL_N - 1)
        prior_sh = [s for s in sh_idx if s <= p - FRACTAL_N - 1]
        if prior_sh:
            ref = highs[prior_sh[-1]]
            if highs[p] > ref and closes[p] < ref:
                return "buyside"
        prior_sl = [s for s in sl_idx if s <= p - FRACTAL_N - 1]
        if prior_sl:
            ref = lows[prior_sl[-1]]
            if lows[p] < ref and closes[p] > ref:
                return "sellside"
    return "none"


def _vol_regime(h1m: pd.DataFrame) -> str:
    """Classify volatility regime by comparing recent realized vol to its
    rolling median over ~VOL_MEDIAN_BARS."""
    close = h1m["close"].to_numpy(dtype=float)
    if len(close) < RECENT_VOL_BARS + 5:
        return "normal"
    logret = np.diff(np.log(close))
    # rolling std of returns over RECENT_VOL_BARS
    s = pd.Series(logret)
    rv = s.rolling(RECENT_VOL_BARS).std()
    recent = rv.iloc[-1]
    baseline = rv.iloc[-VOL_MEDIAN_BARS:].median()
    if not (recent == recent) or not (baseline == baseline) or baseline == 0:
        return "normal"
    ratio = recent / baseline
    if ratio > 1.4:
        return "high"
    if ratio < 0.7:
        return "low"
    return "normal"


def _premium_discount(tf1h: pd.DataFrame, price: float):
    """Dealing range from most recent 1h swing high & low -> eq + zone."""
    sh_prices, sl_prices = _all_swings(tf1h)
    if len(sh_prices) == 0 or len(sl_prices) == 0:
        # fall back to the visible 1h range
        if len(tf1h) == 0:
            return float("nan"), "equilibrium"
        hi = float(tf1h["high"].max())
        lo = float(tf1h["low"].min())
    else:
        hi = float(sh_prices[-1])
        lo = float(sl_prices[-1])
    if hi <= lo:
        return float("nan"), "equilibrium"
    eq = (hi + lo) / 2.0
    band = (hi - lo) * EQ_BAND_PCT
    if abs(price - eq) <= band:
        zone = "equilibrium"
    elif price > eq:
        zone = "premium"
    else:
        zone = "discount"
    return round(eq, 1), zone


def _pct_return(close: pd.Series, lookback: int) -> float:
    """Percent return over `lookback` 1m bars (as a fraction, e.g. 0.012)."""
    if len(close) <= lookback:
        return float("nan")
    now = float(close.iloc[-1])
    then = float(close.iloc[-1 - lookback])
    if then == 0:
        return float("nan")
    return (now - then) / then


# ----------------------------------------------------------------------------
# batch
# ----------------------------------------------------------------------------
def iter_snapshots(df: pd.DataFrame, indices) -> list[MarketSnapshot]:
    """Build snapshots for a list of decision indices."""
    return [build_snapshot(df, int(i)) for i in indices]


# ----------------------------------------------------------------------------
# smoke test
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    import os

    here = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(here, "..", "data", "US30_M1.csv")
    df = load_m1(csv_path)
    print(f"loaded {len(df)} bars  "
          f"{df['timestamp'].iloc[0]}  ->  {df['timestamp'].iloc[-1]}\n")

    n = len(df)
    # a few sample decision points spread across the data (skip the warmup head)
    start = min(3000, n // 5)
    sample = sorted(set(int(x) for x in np.linspace(start, n - 1, 4)))

    for idx in sample:
        snap = build_snapshot(df, idx)
        print(f"=== snapshot @ index {idx} / {n - 1} ===")
        print(snap.to_prompt())
        print()

    # sanity: iter_snapshots returns the same count
    snaps = iter_snapshots(df, sample)
    print(f"iter_snapshots built {len(snaps)} snapshots for {len(sample)} indices")
