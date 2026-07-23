"""
US30 backlog item #6 — REGIME-CONDITIONAL analyst tuning.

The honest question this answers: the analyst fires the same way in every market
context. Does it actually do BETTER in some regimes (a given session, volatility
state, or premium/discount zone) than others — and if so, does a simple ADAPTATION
rule ("only trade the regimes that looked good, and/or raise the confidence bar in
hostile ones") lift the real, cost-adjusted edge, or is any per-regime advantage
just small-sample noise that evaporates out-of-sample?

Two pieces:

1. regime_performance(df)
   For each regime dimension — session, vol_regime, pd_zone, in_killzone, and the
   session x vol_regime cross — compute over NON-FLAT trades: n_trades, hit_rate,
   avg_R, profit_factor, cost_adjusted_total_R. Regimes are ranked best->worst by
   avg_R. Any slice thinner than MIN_REGIME_N is flagged 'insufficient n' and kept
   OUT of the ranking rather than trusted — a 5-trade slice tells you nothing.

2. adaptation_test(df)
   The anti-curve-fit core. Time-order the trades, split in half. Derive a simple,
   few-parameter rule using ONLY the FIRST half (in-sample): keep trades whose
   regime had positive in-sample avg_R, and/or whose confidence >= k. Then apply
   that frozen rule to the SECOND half (out-of-sample) and compare baseline (take
   everything) vs adapted (filtered). A rule that only helps in-sample is noise;
   the walk-forward split is what tells the two apart. The verdict is deliberately
   skeptical.

Note on costs: `realized_R` in setups.csv is ALREADY net of round-trip spread
(see replay.evaluate_call), so cost_adjusted_total_R is simply the sum of
realized_R over the kept trades. hit_rate here is wins / n_trades where a win is
outcome == 'win' (losses and timeouts sit in the denominator).

Run:  python -m src.regime_tune        (from us30_predict/)
      python src/regime_tune.py
"""
from __future__ import annotations

import json
import math
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SETUPS_PATH = os.path.join(HERE, "..", "results", "setups.csv")
RESULTS_PATH = os.path.join(HERE, "..", "results", "regime_tune.json")

# --- guardrails against trusting tiny slices / noisy comparisons ------------
MIN_REGIME_N = 30        # a per-regime slice thinner than this is 'insufficient n'
MIN_OOS_TRADES = 40      # below this the OOS baseline-vs-adapted read is unreliable
MIN_KEEP_FRAC = 0.15     # an adapted rule must keep at least this share of trades
CONF_GRID = [4, 5, 6, 7, 8]   # candidate confidence thresholds for the rule search

# regime dimensions we break performance down by
SINGLE_DIMS = ["session", "vol_regime", "pd_zone", "in_killzone"]
COMBO_DIMS = [("session", "vol_regime")]


# --------------------------------------------------------------------------- #
# Data prep
# --------------------------------------------------------------------------- #
def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Non-flat, time-ordered trades with clean realized_R and a win flag."""
    df = df.copy()
    df["direction"] = df["direction"].astype(str).str.lower()
    df = df[df["direction"].isin(["long", "short"])].copy()

    df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts"]).sort_values("ts").reset_index(drop=True)

    df["realized_R"] = pd.to_numeric(df["realized_R"], errors="coerce")
    df = df[df["realized_R"].notna()].reset_index(drop=True)

    df["confidence"] = pd.to_numeric(df["confidence"], errors="coerce")
    df["outcome"] = df["outcome"].astype(str).str.lower()
    df["is_win"] = (df["outcome"] == "win")
    return df


# --------------------------------------------------------------------------- #
# Trade-economics helpers
# --------------------------------------------------------------------------- #
def _safe(x):
    """JSON-safe float: None for nan/inf, plain float otherwise."""
    if x is None:
        return None
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(xf) or math.isinf(xf):
        return None
    return xf


def _trade_stats(sub: pd.DataFrame, min_n: int = MIN_REGIME_N) -> dict:
    """n_trades / hit_rate / avg_R / profit_factor / cost_adjusted_total_R over a
    frame of non-flat trades (realized_R already net of spread).

    Slices thinner than `min_n` are marked insufficient_n=True: their numbers are
    still reported for transparency but callers should not rank or act on them.
    """
    R = pd.to_numeric(sub["realized_R"], errors="coerce").dropna().to_numpy(dtype=float)
    n = int(R.size)
    if n == 0:
        return {"n_trades": 0, "hit_rate": None, "avg_R": None,
                "profit_factor": None, "cost_adjusted_total_R": 0.0,
                "insufficient_n": True}

    wins = int(sub["is_win"].sum())
    gross_profit = float(R[R > 0].sum())
    gross_loss = float(-R[R < 0].sum())
    if gross_loss > 0:
        pf = gross_profit / gross_loss
    elif gross_profit > 0:
        pf = float("inf")           # no losers -> undefined; _safe -> None
    else:
        pf = None

    out = {
        "n_trades": n,
        "hit_rate": _safe(wins / n),
        "avg_R": _safe(R.mean()),
        "profit_factor": _safe(pf),
        "cost_adjusted_total_R": _safe(R.sum()),
        "insufficient_n": bool(n < min_n),
    }
    if pf == float("inf"):
        out["profit_factor_note"] = "no losing trades (undefined)"
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
    if isinstance(v, bool):
        return str(v)
    return str(v)


def _group_key(dim) -> list:
    return [dim] if isinstance(dim, str) else list(dim)


def _dim_name(dim) -> str:
    return dim if isinstance(dim, str) else " x ".join(dim)


# --------------------------------------------------------------------------- #
# 1. Per-regime performance
# --------------------------------------------------------------------------- #
def regime_performance(df: pd.DataFrame) -> dict:
    """Per-regime trade economics for each dimension, plus a best->worst ranking
    by avg_R (insufficient-n slices excluded from the ranking)."""
    trades = prepare(df)

    result: dict = {
        "n_non_flat_trades": int(len(trades)),
        "min_regime_n": MIN_REGIME_N,
        "overall": _trade_stats(trades, min_n=0),
        "dimensions": {},
    }
    if len(trades) == 0:
        result["ranking"] = []
        return result

    ranking_rows = []
    for dim in SINGLE_DIMS + COMBO_DIMS:
        cols = _group_key(dim)
        if any(c not in trades.columns for c in cols):
            continue
        name = _dim_name(dim)
        per_regime: dict = {}
        for key, gdf in trades.groupby(cols, dropna=False):
            if len(cols) == 1:
                k0 = key[0] if isinstance(key, tuple) else key
                label = _label(k0)
            else:
                label = " | ".join(_label(k) for k in key)
            stats = _trade_stats(gdf)
            per_regime[label] = stats
            if not stats["insufficient_n"] and stats["avg_R"] is not None:
                ranking_rows.append({
                    "dimension": name, "regime": label,
                    "n_trades": stats["n_trades"],
                    "avg_R": stats["avg_R"],
                    "hit_rate": stats["hit_rate"],
                    "profit_factor": stats["profit_factor"],
                    "cost_adjusted_total_R": stats["cost_adjusted_total_R"],
                })
        # order regimes within the dimension best->worst by avg_R (None last)
        ordered = dict(sorted(
            per_regime.items(),
            key=lambda kv: (kv[1]["avg_R"] is None,
                            -(kv[1]["avg_R"] or 0.0))))
        result["dimensions"][name] = ordered

    ranking_rows.sort(key=lambda r: -r["avg_R"])
    result["ranking"] = ranking_rows
    result["n_regimes_ranked"] = len(ranking_rows)
    return result


# --------------------------------------------------------------------------- #
# 2. Walk-forward adaptation test
# --------------------------------------------------------------------------- #
def _favorable_regimes(train: pd.DataFrame, dim: str) -> list:
    """Regimes on `dim` whose in-sample avg_R > 0 AND that have >= MIN_REGIME_N
    in-sample trades (positive avg_R on a handful of trades is not a signal)."""
    good = []
    for key, gdf in train.groupby(dim, dropna=False):
        R = gdf["realized_R"]
        if len(R) >= MIN_REGIME_N and R.mean() > 0:
            good.append(_label(key[0] if isinstance(key, tuple) else key))
    return good


def _apply_regime_filter(frame: pd.DataFrame, dim: str, keep: list) -> pd.DataFrame:
    lab = frame[dim].map(lambda v: _label(v))
    return frame[lab.isin(keep)]


def _keep_frac(kept: pd.DataFrame, base: pd.DataFrame) -> float:
    return (len(kept) / len(base)) if len(base) else 0.0


def adaptation_test(df: pd.DataFrame) -> dict:
    """Derive a few-parameter rule on the FIRST half, evaluate it on the SECOND.

    Candidate rules (all fitted only on in-sample data):
      * conf>=k          : take only setups with confidence >= k
      * fav_session      : take only sessions with positive in-sample avg_R
      * fav_session+conf : both filters combined
    We pick the rule with the best in-sample avg_R that still keeps >= MIN_KEEP_FRAC
    of in-sample trades, freeze it, and report baseline-vs-adapted on BOTH halves.
    """
    trades = prepare(df)
    n = len(trades)
    result: dict = {
        "min_oos_trades": MIN_OOS_TRADES,
        "min_keep_frac": MIN_KEEP_FRAC,
        "conf_grid": CONF_GRID,
    }
    if n < 2 * MIN_OOS_TRADES:
        result["status"] = "insufficient_data"
        result["n_non_flat_trades"] = n
        result["note"] = (
            f"Only {n} non-flat trades; need >= {2 * MIN_OOS_TRADES} to split into "
            "two halves each large enough to judge. No adaptation rule fitted.")
        return result

    split = n // 2
    train = trades.iloc[:split].reset_index(drop=True)
    test = trades.iloc[split:].reset_index(drop=True)
    result["status"] = "ok"
    result["split"] = {
        "n_total": n,
        "n_in_sample": int(len(train)),
        "n_out_of_sample": int(len(test)),
        "in_sample_span": [str(train["ts"].iloc[0]), str(train["ts"].iloc[-1])],
        "out_of_sample_span": [str(test["ts"].iloc[0]), str(test["ts"].iloc[-1])],
    }

    fav_sessions = _favorable_regimes(train, "session")

    # ---- assemble candidate rules and score each in-sample -----------------
    candidates = []

    for k in CONF_GRID:
        kept = train[train["confidence"] >= k]
        candidates.append({
            "name": f"conf>={k}",
            "type": "confidence",
            "params": {"k": k},
            "mask": lambda f, k=k: f["confidence"] >= k,
        })

    if fav_sessions:
        candidates.append({
            "name": "favorable_session",
            "type": "regime",
            "params": {"dimension": "session", "keep": fav_sessions},
            "mask": lambda f, keep=fav_sessions: f["session"].map(_label).isin(keep),
        })
        for k in CONF_GRID:
            candidates.append({
                "name": f"favorable_session & conf>={k}",
                "type": "regime+confidence",
                "params": {"dimension": "session", "keep": fav_sessions, "k": k},
                "mask": lambda f, keep=fav_sessions, k=k: (
                    f["session"].map(_label).isin(keep) & (f["confidence"] >= k)),
            })

    # ---- score candidates on in-sample, respecting the keep-fraction floor --
    scored = []
    for c in candidates:
        kept = train[c["mask"](train)]
        frac = _keep_frac(kept, train)
        stats = _trade_stats(kept, min_n=0)
        scored.append({
            "name": c["name"], "type": c["type"], "params": c["params"],
            "in_sample_keep_frac": _safe(frac),
            "in_sample_avg_R": stats["avg_R"], "in_sample_n": stats["n_trades"],
            "eligible": bool(frac >= MIN_KEEP_FRAC and stats["n_trades"] >= MIN_REGIME_N),
            "_mask": c["mask"],
        })
    result["candidate_rules"] = [
        {k: v for k, v in s.items() if k != "_mask"} for s in scored]

    eligible = [s for s in scored if s["eligible"] and s["in_sample_avg_R"] is not None]
    baseline_in = _trade_stats(train, min_n=0)

    if not eligible:
        # nothing beat the keep-fraction / n floor -> honest no-op adaptation
        result["chosen_rule"] = {
            "name": "none",
            "reason": ("No candidate rule kept >= "
                       f"{MIN_KEEP_FRAC:.0%} of in-sample trades with >= "
                       f"{MIN_REGIME_N} trades; adaptation declined."),
        }
        adapted_in = baseline_in
        adapted_out = _trade_stats(test, min_n=0)
        chosen_mask = None
    else:
        best = max(eligible, key=lambda s: s["in_sample_avg_R"])
        result["chosen_rule"] = {
            "name": best["name"], "type": best["type"], "params": best["params"],
            "in_sample_avg_R": best["in_sample_avg_R"],
            "in_sample_keep_frac": best["in_sample_keep_frac"],
            "selection": "best in-sample avg_R among rules keeping >= "
                         f"{MIN_KEEP_FRAC:.0%} of trades",
        }
        chosen_mask = best["_mask"]
        adapted_in = _trade_stats(train[chosen_mask(train)], min_n=0)
        adapted_out = _trade_stats(test[chosen_mask(test)], min_n=0)

    baseline_out = _trade_stats(test, min_n=0)

    result["in_sample"] = {"baseline": baseline_in, "adapted": adapted_in}
    result["out_of_sample"] = {"baseline": baseline_out, "adapted": adapted_out}

    # ---- honest verdict ----------------------------------------------------
    result["out_of_sample_reliable"] = bool(len(test) >= MIN_OOS_TRADES)
    result["verdict"] = _verdict(result, chosen_mask is not None,
                                 adapted_out, baseline_out)
    return result


def _verdict(result: dict, adapted: bool, adapted_out: dict,
             baseline_out: dict) -> str:
    if not adapted:
        return ("No adaptation rule cleared the sample-size / keep-fraction floor "
                "in-sample, so none was applied. On this data the analyst offers "
                "no regime that is both favorable and populated enough to trust.")

    b_avg = baseline_out["avg_R"]
    a_avg = adapted_out["avg_R"]
    a_n = adapted_out["n_trades"]
    b_tot = baseline_out["cost_adjusted_total_R"]
    a_tot = adapted_out["cost_adjusted_total_R"]

    if a_n is None or a_n < MIN_REGIME_N:
        return (f"The chosen rule keeps only {a_n} out-of-sample trades — too few "
                "to conclude anything. Treat as insufficient, not as an edge.")

    if a_avg is None or b_avg is None:
        return "Out-of-sample metrics undefined; no conclusion."

    d_avg = a_avg - b_avg
    helped = d_avg > 0 and a_avg > 0
    marginal = d_avg > 0 and a_avg <= 0

    lead = (f"Out-of-sample: baseline avg {b_avg:+.3f}R over "
            f"{baseline_out['n_trades']} trades vs adapted avg {a_avg:+.3f}R over "
            f"{a_n} trades (delta {d_avg:+.3f}R; total {b_tot:+.1f}R -> {a_tot:+.1f}R). ")

    if helped:
        return lead + ("Adaptation turned the out-of-sample edge positive and beat "
                       "baseline. Encouraging, but with direction ~random treat one "
                       "favorable split as suggestive, not proof — re-test on more data.")
    if marginal:
        return lead + ("Adaptation improved avg_R relative to baseline but the edge "
                       "is still negative out-of-sample: it cut losers, it did not "
                       "create a winner. Marginal, consistent with in-sample noise "
                       "rather than a durable regime edge.")
    return lead + ("Adaptation did NOT help out-of-sample — the in-sample regime "
                   "advantage did not generalize. This is the expected result when "
                   "trade direction is essentially random: per-regime avg_R rankings "
                   "are small-sample noise that reshuffles in the next period.")


# --------------------------------------------------------------------------- #
# 3. Save
# --------------------------------------------------------------------------- #
def save(df: pd.DataFrame, path: str = RESULTS_PATH) -> dict:
    """Run both analyses and write the combined JSON report."""
    payload = {
        "backlog_item": 6,
        "title": "Regime-conditional analyst tuning",
        "metrics_note": (
            "realized_R is already net of round-trip spread; "
            "cost_adjusted_total_R is its sum. hit_rate = wins / n_trades "
            "(win = outcome 'win'). Slices under "
            f"{MIN_REGIME_N} trades are flagged 'insufficient n'."),
        "regime_performance": regime_performance(df),
        "adaptation": adaptation_test(df),
    }
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(payload, fh, indent=2, default=str)
    return payload


# --------------------------------------------------------------------------- #
# Synthetic fallback (same schema) — only used when setups.csv is absent
# --------------------------------------------------------------------------- #
def _synthetic(n: int = 800, seed: int = 6) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    sessions = ["asia", "london", "ny_am", "ny_pm", "off"]
    vols = ["low", "normal", "high"]
    zones = ["premium", "discount", "equilibrium"]
    ts = pd.date_range("2016-01-01", periods=n, freq="6h", tz="UTC")
    session = rng.choice(sessions, n)
    vol = rng.choice(vols, n, p=[0.25, 0.5, 0.25])
    zone = rng.choice(zones, n, p=[0.45, 0.45, 0.10])
    direction = rng.choice(["long", "short", "flat"], n, p=[0.2, 0.2, 0.6])
    conf = np.where(direction == "flat", 0, rng.integers(3, 9, n))
    # direction ~random: realized_R centered slightly negative (costs), no regime edge
    R = np.where(direction == "flat", 0.0,
                 rng.normal(-0.12, 1.0, n)).astype(float)
    outcome = np.where(direction == "flat", "flat",
                       np.where(R > 0, "win", np.where(R < 0, "loss", "timeout")))
    return pd.DataFrame({
        "ts": ts, "year": ts.year, "quarter": ts.quarter,
        "session": session, "in_killzone": rng.integers(0, 2, n),
        "vol_regime": vol, "pd_zone": zone,
        "atr_pct": rng.uniform(0.02, 0.15, n),
        "ret_15m": rng.normal(0, 0.002, n), "ret_60m": rng.normal(0, 0.004, n),
        "recent_sweep": rng.choice(["none", "buyside", "sellside"], n),
        "trend_15m": rng.choice(["bull", "bear", "range", "na"], n),
        "trend_1h": rng.choice(["bull", "bear", "range"], n),
        "trend_4h": rng.choice(["bull", "bear", "range"], n),
        "direction": direction, "confidence": conf,
        "outcome": outcome, "realized_R": R,
    })


def _fmt(x, spec="{:+.3f}"):
    return "n/a" if x is None else spec.format(x)


def _print_summary(payload: dict) -> None:
    rp = payload["regime_performance"]
    ad = payload["adaptation"]
    print("=" * 70)
    print("REGIME-CONDITIONAL ANALYST TUNING (backlog #6)")
    print("=" * 70)
    ov = rp["overall"]
    print(f"Non-flat trades: {rp['n_non_flat_trades']}   "
          f"overall avg_R={_fmt(ov['avg_R'])}  "
          f"hit={_fmt(ov['hit_rate'], '{:.1%}')}  "
          f"PF={_fmt(ov['profit_factor'], '{:.2f}')}  "
          f"totR={_fmt(ov['cost_adjusted_total_R'], '{:+.1f}')}")

    print("\nBest regimes by avg_R (>= "
          f"{rp['min_regime_n']} trades):")
    for row in rp.get("ranking", [])[:6]:
        print(f"  {row['dimension']:>18} = {row['regime']:<22} "
              f"n={row['n_trades']:<4} avg_R={_fmt(row['avg_R'])} "
              f"hit={_fmt(row['hit_rate'], '{:.1%}')} "
              f"PF={_fmt(row['profit_factor'], '{:.2f}')}")
    worst = rp.get("ranking", [])
    if worst:
        w = worst[-1]
        print(f"  worst: {w['dimension']} = {w['regime']} "
              f"(n={w['n_trades']}, avg_R={_fmt(w['avg_R'])})")

    print("\nAdaptation (walk-forward, first half -> second half):")
    if ad.get("status") != "ok":
        print(f"  {ad.get('note', ad.get('status'))}")
    else:
        cr = ad["chosen_rule"]
        print(f"  chosen rule: {cr['name']}")
        bo = ad["out_of_sample"]["baseline"]
        ao = ad["out_of_sample"]["adapted"]
        print(f"  OOS baseline: n={bo['n_trades']} avg_R={_fmt(bo['avg_R'])} "
              f"totR={_fmt(bo['cost_adjusted_total_R'], '{:+.1f}')}")
        print(f"  OOS adapted : n={ao['n_trades']} avg_R={_fmt(ao['avg_R'])} "
              f"totR={_fmt(ao['cost_adjusted_total_R'], '{:+.1f}')}")
    print(f"\n  VERDICT: {ad.get('verdict', 'n/a')}")
    print("=" * 70)


def main() -> None:
    if os.path.exists(SETUPS_PATH):
        df = pd.read_csv(SETUPS_PATH)
        src = SETUPS_PATH
    else:
        df = _synthetic()
        src = "synthetic (setups.csv not found)"
    print(f"[regime_tune] source: {src}  rows={len(df)}")
    payload = save(df, RESULTS_PATH)
    _print_summary(payload)
    print(f"[regime_tune] wrote {RESULTS_PATH}")


if __name__ == "__main__":
    main()
