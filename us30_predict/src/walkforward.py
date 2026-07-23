"""
Backlog #2 — WALK-FORWARD / REGIME breakdown of the analyst's performance.

Takes the shared labeled setups dataset (results/setups.csv — one row per analyst
decision) and slices it every honest way that matters for asking the real
question: *is any apparent edge stable across time and regime, or is it just
noise wobbling around a coin-flip?*

For every slice we report, over the NON-FLAT (traded) rows:
  * n_trades
  * hit_rate            wins / (wins + losses)          [timeouts excluded from denom]
  * avg_R               mean realized_R over trades
  * profit_factor       gross win R / gross loss R
  * cost_adjusted_total_R   sum of realized_R over trades (already cost-adjusted upstream)
  * abstain_rate        flats / all rows in the slice

Breakdowns: year, quarter (year+quarter), session, vol_regime, pd_zone,
in_killzone, and confidence bucket (0-2 / 3-4 / 5-6 / 7-8 / 9-10), plus an
OVERALL row and a short, honest 'stability' note.

Pure pandas/numpy; no replays, no heavy compute. Run directly to self-test on
results/setups.csv if present, else on a synthetic frame with the same columns.
"""
from __future__ import annotations

import json
import math
import os
from typing import Sequence, Union

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SETUPS = os.path.join(HERE, "..", "results", "setups.csv")
OUT = os.path.join(HERE, "..", "results", "walkforward.json")

# Columns the setups dataset is expected to carry.
COLUMNS = [
    "ts", "year", "quarter", "session", "in_killzone", "vol_regime", "pd_zone",
    "atr_pct", "ret_15m", "ret_60m", "recent_sweep", "trend_15m", "trend_1h",
    "trend_4h", "direction", "confidence", "outcome", "realized_R",
]

_TRADE_OUTCOMES = ("win", "loss", "timeout")
_CONF_ORDER = ["0-2", "3-4", "5-6", "7-8", "9-10"]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
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


def _conf_bucket(conf) -> str:
    try:
        c = int(round(float(conf)))
    except (TypeError, ValueError):
        return "0-2"
    if c <= 2:
        return "0-2"
    if c <= 4:
        return "3-4"
    if c <= 6:
        return "5-6"
    if c <= 8:
        return "7-8"
    return "9-10"


def _is_trade_mask(df: pd.DataFrame) -> pd.Series:
    """Non-flat rows: a real direction AND a real (settled) outcome."""
    if df.empty:
        return pd.Series([], dtype=bool)
    direction = df["direction"].astype(str).str.lower()
    outcome = df["outcome"].astype(str).str.lower()
    return direction.isin(("long", "short")) & outcome.isin(_TRADE_OUTCOMES)


def _metrics_for_frame(df: pd.DataFrame) -> dict:
    """Compute the slice metrics for one already-selected group frame.

    `df` is ALL rows in the group (flats included) so abstain_rate is honest.
    """
    n_all = int(len(df))
    trade_mask = _is_trade_mask(df)
    trades = df[trade_mask]
    n_trades = int(len(trades))

    if n_trades == 0:
        return {
            "n_all": n_all,
            "n_trades": 0,
            "hit_rate": None,
            "avg_R": None,
            "profit_factor": None,
            "cost_adjusted_total_R": 0.0,
            "abstain_rate": _safe(1.0) if n_all else None,
        }

    outcome = trades["outcome"].astype(str).str.lower()
    wins = int((outcome == "win").sum())
    losses = int((outcome == "loss").sum())

    R = pd.to_numeric(trades["realized_R"], errors="coerce")
    R_valid = R.dropna()
    gross_win = float(R_valid[R_valid > 0].sum())
    gross_loss = float(-R_valid[R_valid < 0].sum())

    decided = wins + losses
    if gross_loss > 0:
        pf = gross_win / gross_loss
    elif gross_win > 0:
        pf = float("inf")          # no losers -> undefined; _safe -> None below
    else:
        pf = None

    return {
        "n_all": n_all,
        "n_trades": n_trades,
        "hit_rate": _safe(wins / decided) if decided else None,
        "avg_R": _safe(R_valid.mean()) if len(R_valid) else None,
        "profit_factor": _safe(pf),
        "cost_adjusted_total_R": _safe(R_valid.sum()) if len(R_valid) else 0.0,
        "abstain_rate": _safe((n_all - n_trades) / n_all) if n_all else None,
    }


# --------------------------------------------------------------------------- #
# public: per-slice metrics
# --------------------------------------------------------------------------- #
def slice_metrics(df: pd.DataFrame,
                  by: Union[str, Sequence[str]]) -> dict:
    """Per-group performance keyed by the value(s) of column(s) `by`.

    `by` may be a single column name or a list of column names. The special
    token 'confidence_bucket' is derived on the fly from the `confidence` column.

    Returns {group_label -> metrics dict}. Groups are ordered; the confidence
    bucket keeps its natural 0-2..9-10 order, everything else sorts by key.
    Empty input -> empty dict.
    """
    if df is None or len(df) == 0:
        return {}

    cols = [by] if isinstance(by, str) else list(by)

    work = df.copy()
    for c in cols:
        if c == "confidence_bucket":
            work[c] = work["confidence"].map(_conf_bucket)
        elif c not in work.columns:
            # Requested slice column absent -> nothing to break down on.
            return {}

    out: dict = {}
    # groupby(dropna=False) keeps rows whose key is NaN under a 'NA' label.
    grouped = work.groupby(cols, dropna=False)
    for key, gdf in grouped:
        # pandas may hand back a 1-tuple even for a single grouping column.
        if len(cols) == 1:
            k0 = key[0] if isinstance(key, tuple) else key
            label = _label(k0)
        else:
            label = " | ".join(_label(k) for k in key)
        out[label] = _metrics_for_frame(gdf)

    # Keep confidence buckets in their natural order.
    if cols == ["confidence_bucket"]:
        out = {b: out[b] for b in _CONF_ORDER if b in out}
    else:
        out = {k: out[k] for k in sorted(out.keys())}
    return out


def _label(v) -> str:
    """Stable, readable string key for a group value."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "NA"
    if isinstance(v, (np.integer,)):
        return str(int(v))
    if isinstance(v, (np.floating,)):
        f = float(v)
        return str(int(f)) if f.is_integer() else str(f)
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


# --------------------------------------------------------------------------- #
# public: full report
# --------------------------------------------------------------------------- #
def _stability_note(overall: dict, year_slices: dict, quarter_slices: dict) -> str:
    """Honest, plain-English read on whether any edge is stable or noise."""
    n_trades = overall.get("n_trades") or 0
    if n_trades == 0:
        return ("No non-flat trades in the dataset — the analyst abstained on "
                "everything, so there is nothing to judge for stability.")

    hr = overall.get("hit_rate")
    avg_R = overall.get("avg_R")
    total_R = overall.get("cost_adjusted_total_R")

    # Per-year direction of edge (cost-adjusted).
    year_R = {k: v.get("cost_adjusted_total_R") for k, v in year_slices.items()
              if (v.get("n_trades") or 0) > 0}
    pos_years = [k for k, r in year_R.items() if r is not None and r > 0]
    neg_years = [k for k, r in year_R.items() if r is not None and r < 0]

    # Per-quarter, to gauge how noisy the sign is.
    q_R = [v.get("cost_adjusted_total_R") for v in quarter_slices.values()
           if (v.get("n_trades") or 0) > 0 and v.get("cost_adjusted_total_R") is not None]
    q_pos = sum(1 for r in q_R if r > 0)
    q_neg = sum(1 for r in q_R if r < 0)

    parts = []
    hr_txt = f"{hr:.1%}" if hr is not None else "n/a"
    ar_txt = f"{avg_R:+.3f}R" if avg_R is not None else "n/a"
    tr_txt = f"{total_R:+.1f}R" if total_R is not None else "n/a"
    parts.append(
        f"Overall across {n_trades} trades: hit-rate {hr_txt}, avg {ar_txt}, "
        f"cost-adjusted total {tr_txt}.")

    coin_flip = hr is not None and abs(hr - 0.5) < 0.03
    if coin_flip:
        parts.append("Hit-rate sits within ~3pts of a coin flip (~50%).")

    if year_R:
        parts.append(
            f"Yearly cost-adjusted R is positive in {len(pos_years)}/"
            f"{len(year_R)} years ({', '.join(sorted(pos_years)) or 'none'}) "
            f"and negative in {len(neg_years)}.")
    if q_R:
        parts.append(f"Quarter signs flip {q_pos} positive / {q_neg} negative.")

    # The honest verdict.
    edge_positive = (total_R is not None and total_R > 0
                     and avg_R is not None and avg_R > 0)
    stable = (year_R and len(pos_years) == len(year_R) and len(year_R) >= 2
              and not coin_flip)

    if stable and edge_positive:
        verdict = ("VERDICT: the edge is positive in EVERY year sampled — this "
                   "looks like a genuine, time-stable signal rather than noise. "
                   "Still worth a significance test before trusting it.")
    elif edge_positive and not coin_flip:
        verdict = ("VERDICT: net-positive overall but the sign is NOT consistent "
                   "across every period — treat as a weak/unproven edge, likely "
                   "sensitive to which years you sample.")
    else:
        verdict = ("VERDICT: no stable edge. Direction performance is essentially "
                   "noise around a coin-flip and net cost-adjusted R is not "
                   "reliably positive. Any single good slice is most plausibly "
                   "luck, not skill — do not trade the direction call on this.")
    parts.append(verdict)
    return " ".join(parts)


def walkforward_report(df: pd.DataFrame) -> dict:
    """Assemble the OVERALL row + every breakdown + an honest stability note."""
    if df is None:
        df = pd.DataFrame(columns=COLUMNS)

    n_rows = int(len(df))
    overall = _metrics_for_frame(df) if n_rows else _metrics_for_frame(
        pd.DataFrame(columns=COLUMNS))
    # Drop the internal n_all bookkeeping from the surfaced overall row but keep
    # a friendly n_snapshots.
    overall_out = dict(overall)
    overall_out["n_snapshots"] = n_rows

    breakdowns = {
        "year": slice_metrics(df, "year"),
        "quarter": slice_metrics(df, ["year", "quarter"]),
        "session": slice_metrics(df, "session"),
        "vol_regime": slice_metrics(df, "vol_regime"),
        "pd_zone": slice_metrics(df, "pd_zone"),
        "in_killzone": slice_metrics(df, "in_killzone"),
        "confidence_bucket": slice_metrics(df, "confidence_bucket"),
    }

    note = _stability_note(overall, breakdowns["year"], breakdowns["quarter"])

    return {
        "meta": {
            "n_snapshots": n_rows,
            "n_trades": overall.get("n_trades", 0),
            "abstain_rate": overall.get("abstain_rate"),
            "metric_defs": {
                "hit_rate": "wins / (wins + losses); timeouts excluded from denominator",
                "avg_R": "mean realized_R over non-flat trades",
                "profit_factor": "gross win R / gross loss R (None if no losers)",
                "cost_adjusted_total_R": "sum of realized_R over non-flat trades",
                "abstain_rate": "flats / all rows in the slice",
            },
        },
        "overall": overall_out,
        "breakdowns": breakdowns,
        "stability": note,
    }


def save_report(df: pd.DataFrame, path: str = OUT) -> dict:
    """Compute the walk-forward report and write it to `path` as JSON."""
    report = walkforward_report(df)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(report, fh, indent=2, default=str)
    return report


# --------------------------------------------------------------------------- #
# synthetic self-test data
# --------------------------------------------------------------------------- #
def _synthetic(n: int = 600, seed: int = 7) -> pd.DataFrame:
    """A small frame with the SAME columns as setups.csv, for self-testing.

    Direction is deliberately near-random (edge ~ coin flip) so the stability
    note has to be honest about noise — matching the project's real finding.
    """
    rng = np.random.default_rng(seed)
    sessions = ["asia", "london", "ny_am", "ny_pm"]
    vol_regimes = ["low", "normal", "high"]
    pd_zones = ["discount", "equilibrium", "premium"]
    trends = ["up", "down", "flat", "na"]

    rows = []
    start = pd.Timestamp("2024-01-02 08:00", tz="UTC")
    for k in range(n):
        ts = start + pd.Timedelta(minutes=30 * k)
        conf = int(rng.integers(0, 11))
        # ~35% abstain; abstain more likely when confidence is low.
        p_flat = 0.55 if conf <= 3 else 0.20
        if rng.random() < p_flat:
            direction, outcome, R = "flat", "flat", 0.0
        else:
            direction = rng.choice(["long", "short"])
            # essentially a coin flip on direction, tiny reward:risk asymmetry
            roll = rng.random()
            if roll < 0.06:
                outcome, R = "timeout", float(rng.normal(-0.1, 0.2))
            elif roll < 0.53:
                outcome, R = "win", float(abs(rng.normal(1.9, 0.4)))
            else:
                outcome, R = "loss", float(-abs(rng.normal(1.0, 0.1)))
        rows.append(dict(
            ts=str(ts), year=ts.year, quarter=(ts.month - 1) // 3 + 1,
            session=rng.choice(sessions), in_killzone=int(rng.random() < 0.4),
            vol_regime=rng.choice(vol_regimes), pd_zone=rng.choice(pd_zones),
            atr_pct=float(rng.uniform(0.02, 0.20)),
            ret_15m=float(rng.normal(0, 0.001)), ret_60m=float(rng.normal(0, 0.002)),
            recent_sweep=int(rng.random() < 0.3),
            trend_15m=rng.choice(trends), trend_1h=rng.choice(trends),
            trend_4h=rng.choice(trends),
            direction=direction, confidence=conf, outcome=outcome,
            realized_R=round(R, 4),
        ))
    return pd.DataFrame(rows, columns=COLUMNS)


def _print_summary(report: dict) -> None:
    m = report["meta"]
    o = report["overall"]
    print("=== WALK-FORWARD / REGIME REPORT ===")
    print(f"snapshots={m['n_snapshots']}  trades={m['n_trades']}  "
          f"abstain_rate={_fmt(m['abstain_rate'])}")
    print(f"OVERALL  hit_rate={_fmt(o['hit_rate'])}  avg_R={_fmt(o['avg_R'])}  "
          f"PF={_fmt(o['profit_factor'])}  total_R={_fmt(o['cost_adjusted_total_R'])}")
    for name, slc in report["breakdowns"].items():
        print(f"\n-- by {name} ({len(slc)} groups) --")
        for label, met in slc.items():
            print(f"   {label:<24} n={met['n_trades']:<4} "
                  f"hit={_fmt(met['hit_rate'])}  avgR={_fmt(met['avg_R'])}  "
                  f"PF={_fmt(met['profit_factor'])}  "
                  f"totR={_fmt(met['cost_adjusted_total_R'])}  "
                  f"abst={_fmt(met['abstain_rate'])}")
    print("\n-- stability --")
    print("  " + report["stability"])


def _fmt(x) -> str:
    if x is None:
        return "n/a"
    try:
        return f"{float(x):.3f}"
    except (TypeError, ValueError):
        return str(x)


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    if os.path.exists(SETUPS):
        df = pd.read_csv(SETUPS)
        src = f"real setups.csv ({len(df)} rows)"
    else:
        df = _synthetic()
        src = f"SYNTHETIC self-test ({len(df)} rows) — setups.csv not found yet"
    print(f"[walkforward] source: {src}\n")

    report = save_report(df, OUT)
    _print_summary(report)
    print(f"\nsaved -> {OUT}")
