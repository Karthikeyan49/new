"""
US30 backlog item #4 — META-LABELING filter.

The honest question this answers: the analyst already decides *direction*; can a
secondary model, looking only at the setup's CONTEXT, decide which of those calls
are worth TAKING — lifting the confident hit-rate / profit factor above the naive
"take every non-flat setup" baseline?

This is López de Prado's meta-labeling idea. The primary model (the analyst) sets
the side; a secondary binary classifier sets the *size* (here: take / skip). We
train that classifier WALK-FORWARD (expanding window, time-ordered, no shuffle,
no leakage) to predict P(win) out-of-sample, choose a take/skip threshold using
ONLY training-fold data, and then compare, purely out-of-sample:

    (a) take ALL non-flat setups            vs
    (b) take only setups with P(win) >= threshold-chosen-on-train

reporting n_trades / hit_rate / avg_R / profit_factor / cost_adjusted_total_R for
each, plus the meta-model's OOS AUC and its top feature importances. The verdict
is deliberately skeptical: with few trades or an AUC near 0.5 it reports
"insufficient data" / "no usable signal" rather than dressing up noise.

Note on costs: `realized_R` in setups.csv is ALREADY net of round-trip spread
(see replay.evaluate_call), so cost_adjusted_total_R is simply the sum of
realized_R over the taken trades.

Run:  python -m src.meta_label      (from us30_predict/)
      python src/meta_label.py
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

import lightgbm as lgb
from sklearn.metrics import roc_auc_score

HERE = os.path.dirname(os.path.abspath(__file__))
SETUPS_PATH = os.path.join(HERE, "..", "results", "setups.csv")
RESULTS_PATH = os.path.join(HERE, "..", "results", "meta_label.json")

# feature groups -------------------------------------------------------------
NUM_FEATURES = ["atr_pct", "ret_15m", "ret_60m", "confidence", "in_killzone"]
CAT_FEATURES = ["session", "vol_regime", "pd_zone", "recent_sweep",
                "trend_15m", "trend_1h", "trend_4h", "direction"]
FEATURES = NUM_FEATURES + CAT_FEATURES

N_SPLITS = 5              # walk-forward folds
MIN_ROWS = 80             # below this the exercise is meaningless -> insufficient
MIN_OOS_TRADES = 60       # below this the OOS comparison is noise
MIN_KEEP_FRAC = 0.10      # a threshold must keep at least this fraction of train


# --------------------------------------------------------------------------- #
# Data prep
# --------------------------------------------------------------------------- #
def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Filter to non-flat rows, build the meta-label y, sort by ts, coerce types.

    y = 1 if the trade made money, else 0. A 'win' outcome is a win; a 'timeout'
    counts as a win only if it closed with realized_R > 0 (i.e. it drifted the
    right way before the horizon expired). Losses and negative timeouts are 0.
    """
    df = df.copy()
    df["direction"] = df["direction"].astype(str).str.lower()
    df = df[df["direction"].isin(["long", "short"])].copy()

    df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts"]).sort_values("ts").reset_index(drop=True)

    outcome = df["outcome"].astype(str).str.lower()
    R = pd.to_numeric(df["realized_R"], errors="coerce")
    df["realized_R"] = R
    df = df[df["realized_R"].notna()].reset_index(drop=True)
    outcome = df["outcome"].astype(str).str.lower()

    y = ((outcome == "win") |
         ((outcome == "timeout") & (df["realized_R"] > 0))).astype(int)
    df["y"] = y

    # numeric features
    for c in NUM_FEATURES:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    # a modest amount of missingness is fine for LightGBM; fill only the numerics
    df[NUM_FEATURES] = df[NUM_FEATURES].astype(float)

    # categorical features: fixed category dtype so fold slices share codes
    for c in CAT_FEATURES:
        df[c] = df[c].astype(str).astype("category")

    return df


# --------------------------------------------------------------------------- #
# Trade-economics helpers
# --------------------------------------------------------------------------- #
def _trade_stats(R: np.ndarray) -> dict:
    """n_trades / hit_rate / avg_R / profit_factor / cost_adjusted_total_R over a
    set of realized_R values (already net of spread)."""
    R = np.asarray(R, dtype=float)
    R = R[~np.isnan(R)]
    n = int(R.size)
    if n == 0:
        return {"n_trades": 0, "hit_rate": None, "avg_R": None,
                "profit_factor": None, "cost_adjusted_total_R": 0.0}
    wins = R > 0.0
    gross_profit = float(R[R > 0].sum())
    gross_loss = float(-R[R < 0].sum())
    if gross_loss > 0:
        pf = gross_profit / gross_loss
    else:
        pf = None if gross_profit == 0 else float("inf")
    return {
        "n_trades": n,
        "hit_rate": float(wins.mean()),
        "avg_R": float(R.mean()),
        "profit_factor": (None if pf is None else
                          (None if np.isinf(pf) else float(pf))),
        "profit_factor_note": ("no losing trades (undefined)"
                               if pf == float("inf") else None),
        "cost_adjusted_total_R": float(R.sum()),
    }


def _new_model() -> lgb.LGBMClassifier:
    return lgb.LGBMClassifier(
        n_estimators=300,
        learning_rate=0.03,
        num_leaves=15,           # shallow: small, noisy tabular data
        max_depth=-1,
        min_child_samples=30,
        subsample=0.8,
        subsample_freq=1,
        colsample_bytree=0.8,
        reg_lambda=2.0,
        random_state=42,
        n_jobs=-1,
        verbose=-1,
    )


def _choose_threshold(train_prob: np.ndarray, train_R: np.ndarray,
                      n_train: int) -> float:
    """Pick a take/skip threshold using ONLY training-fold data.

    Scans candidate thresholds (quantiles of the train P(win) distribution) and
    keeps the one that maximizes the train set's total cost-adjusted R, subject
    to still taking at least MIN_KEEP_FRAC of the train trades. This targets the
    point where the marginal filtered-out trades have ~zero expectancy — the
    economically correct place to cut — without collapsing onto a lucky handful.
    """
    min_keep = max(10, int(MIN_KEEP_FRAC * n_train))
    qs = np.quantile(train_prob, np.linspace(0.0, 0.85, 18))
    candidates = np.unique(np.round(qs, 6))
    best_thr, best_score = float(candidates[0]), -np.inf
    for thr in candidates:
        mask = train_prob >= thr
        if int(mask.sum()) < min_keep:
            continue
        score = float(train_R[mask].sum())
        if score > best_score:
            best_score, best_thr = score, float(thr)
    return best_thr


# --------------------------------------------------------------------------- #
# Walk-forward meta-labeling
# --------------------------------------------------------------------------- #
def walk_forward(df: pd.DataFrame, n_splits: int = N_SPLITS) -> dict:
    """Expanding-window walk-forward. Returns aligned OOS arrays (prob, y, R,
    take-mask) plus per-fold diagnostics. No row is ever used in its own training
    set, and every train set is strictly earlier in time than its test set."""
    n = len(df)
    X = df[FEATURES]
    y = df["y"].to_numpy()
    R = df["realized_R"].to_numpy()

    bounds = np.linspace(0, n, n_splits + 2, dtype=int)

    oos_prob, oos_y, oos_R, oos_take = [], [], [], []
    folds = []
    for k in range(1, n_splits + 1):
        tr_end = bounds[k]
        te_start = bounds[k]
        te_end = bounds[k + 1]
        if te_end <= te_start or tr_end < 40:
            continue
        Xtr, Xte = X.iloc[:tr_end], X.iloc[te_start:te_end]
        ytr = y[:tr_end]
        Rtr = R[:tr_end]
        Rte = R[te_start:te_end]
        yte = y[te_start:te_end]
        if len(np.unique(ytr)) < 2:      # can't train a classifier on one class
            continue

        model = _new_model()
        model.fit(Xtr, ytr, categorical_feature=CAT_FEATURES)
        p_tr = model.predict_proba(Xtr)[:, 1]
        p_te = model.predict_proba(Xte)[:, 1]

        thr = _choose_threshold(p_tr, Rtr, len(ytr))
        take = p_te >= thr

        oos_prob.extend(p_te.tolist())
        oos_y.extend(yte.tolist())
        oos_R.extend(Rte.tolist())
        oos_take.extend(take.tolist())

        fold_auc = (float(roc_auc_score(yte, p_te))
                    if len(np.unique(yte)) == 2 else None)
        folds.append({
            "fold": k,
            "train_end": int(tr_end),
            "test_start": int(te_start),
            "test_end": int(te_end),
            "n_train": int(tr_end),
            "n_test": int(len(yte)),
            "threshold": round(thr, 4),
            "n_taken": int(take.sum()),
            "test_auc": fold_auc,
        })

    return {
        "prob": np.array(oos_prob),
        "y": np.array(oos_y, dtype=int),
        "R": np.array(oos_R, dtype=float),
        "take": np.array(oos_take, dtype=bool),
        "folds": folds,
    }


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def run(df: pd.DataFrame) -> dict:
    prepared = prepare(df)
    n_nonflat = len(prepared)

    base = {
        "task": "meta-labeling filter (analyst picks side; model picks take/skip)",
        "meta_label": "y=1 if outcome=='win' or (timeout with realized_R>0), else 0",
        "features": {"numeric": NUM_FEATURES, "categorical": CAT_FEATURES},
        "n_nonflat_setups": int(n_nonflat),
        "walk_forward_folds_requested": N_SPLITS,
    }

    if n_nonflat < MIN_ROWS:
        base.update({
            "status": "insufficient_data",
            "verdict": (f"Only {n_nonflat} non-flat setups (< {MIN_ROWS}). "
                        "Too few to train/evaluate a meta-model without "
                        "overfitting noise."),
        })
        return base

    wf = walk_forward(prepared)
    prob, yv, Rv, take = wf["prob"], wf["y"], wf["R"], wf["take"]
    n_oos = int(prob.size)

    # OOS AUC of the meta-model (pooled across folds)
    oos_auc = (float(roc_auc_score(yv, prob))
               if n_oos and len(np.unique(yv)) == 2 else None)

    # (a) take ALL non-flat setups (OOS)  vs  (b) filtered by threshold (OOS)
    all_stats = _trade_stats(Rv)
    filt_stats = _trade_stats(Rv[take])

    # final model on all data for readable feature importances
    top_imp = []
    if len(np.unique(prepared["y"])) == 2:
        final = _new_model()
        final.fit(prepared[FEATURES], prepared["y"],
                  categorical_feature=CAT_FEATURES)
        imp = sorted(zip(FEATURES, final.feature_importances_.tolist()),
                     key=lambda kv: kv[1], reverse=True)
        top_imp = [{"feature": f, "importance": int(v)} for f, v in imp[:12]]

    # --- honest verdict ---------------------------------------------------- #
    status = "ok"
    if n_oos < MIN_OOS_TRADES:
        status = "insufficient_data"
        verdict = (f"Only {n_oos} out-of-sample trades (< {MIN_OOS_TRADES}). "
                   "Comparison would be noise; no reliable conclusion.")
    elif oos_auc is None:
        status = "insufficient_data"
        verdict = "OOS labels are single-class; AUC undefined."
    else:
        n_taken = filt_stats["n_trades"]
        edge_improved = (
            filt_stats["avg_R"] is not None and all_stats["avg_R"] is not None
            and filt_stats["avg_R"] > all_stats["avg_R"])
        total_improved = (filt_stats["cost_adjusted_total_R"]
                          > all_stats["cost_adjusted_total_R"])
        auc_signal = oos_auc >= 0.53
        kept_enough = n_taken >= max(20, int(0.15 * n_oos))

        if not kept_enough:
            verdict = (f"Filter keeps only {n_taken}/{n_oos} trades — too "
                       "aggressive to trust; treat as no usable signal.")
        elif auc_signal and edge_improved:
            dR = filt_stats["avg_R"] - all_stats["avg_R"]
            verdict = (
                f"Meta-labeling HELPS: OOS AUC {oos_auc:.3f} (> 0.5), and "
                f"filtering lifts avg_R by {dR:+.3f}R "
                f"({all_stats['avg_R']:+.3f} -> {filt_stats['avg_R']:+.3f}) "
                f"while keeping {n_taken}/{n_oos} trades"
                f"{' and raising total R' if total_improved else ''}. "
                "The context features carry a usable win/skip signal.")
        elif auc_signal and not edge_improved:
            verdict = (
                f"Marginal: OOS AUC {oos_auc:.3f} shows faint ranking signal, "
                "but the chosen threshold does not improve OOS avg_R — the edge "
                "is too thin to convert into a profitable filter.")
        else:
            verdict = (
                f"Meta-labeling does NOT help: OOS AUC {oos_auc:.3f} is ~0.5 "
                "(no real signal in the context features), and filtering fails "
                "to improve the cost-adjusted edge. Take-all is as good as "
                "filtering here.")

    base.update({
        "status": status,
        "n_oos_trades": n_oos,
        "n_walk_forward_folds": len(wf["folds"]),
        "oos_auc": oos_auc,
        "compare": {
            "take_all_nonflat": all_stats,
            "take_filtered": filt_stats,
        },
        "improvement": {
            "avg_R_delta": (None if (filt_stats["avg_R"] is None
                                     or all_stats["avg_R"] is None)
                            else filt_stats["avg_R"] - all_stats["avg_R"]),
            "total_R_delta": (filt_stats["cost_adjusted_total_R"]
                              - all_stats["cost_adjusted_total_R"]),
            "trades_kept": filt_stats["n_trades"],
            "trades_total": all_stats["n_trades"],
        },
        "per_fold": wf["folds"],
        "feature_importances_top": top_imp,
        "verdict": verdict,
    })
    return base


def save(results: dict, path: str = RESULTS_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)

    def _clean(o):
        if isinstance(o, float):
            return None if (np.isnan(o) or np.isinf(o)) else o
        if isinstance(o, dict):
            return {k: _clean(v) for k, v in o.items()}
        if isinstance(o, list):
            return [_clean(v) for v in o]
        if isinstance(o, (np.floating,)):
            return _clean(float(o))
        if isinstance(o, (np.integer,)):
            return int(o)
        return o

    with open(path, "w") as fh:
        json.dump(_clean(results), fh, indent=2)


# --------------------------------------------------------------------------- #
# Synthetic self-test data (same schema, faint learnable signal)
# --------------------------------------------------------------------------- #
def synthetic_setups(n: int = 1300, seed: int = 11) -> pd.DataFrame:
    """A same-schema setups frame with a FAINT but real take/skip signal, so the
    pipeline can self-test when results/setups.csv is not present. Win prob
    depends weakly on killzone, confidence, trend alignment and vol regime; the
    rest is noise. Trades are ~2:1 reward:risk so a modest win-rate lift moves
    the profit factor materially — exactly what a working meta-filter should
    exploit."""
    rng = np.random.default_rng(seed)
    sessions = np.array(["asia", "london", "ny_am", "ny_pm", "off"])
    regimes = np.array(["low", "normal", "high"])
    zones = np.array(["premium", "discount", "equilibrium"])
    sweeps = np.array(["buyside", "sellside", "none"])
    trends = np.array(["up", "down", "range"])
    dirs = np.array(["long", "short"])

    ts = pd.date_range("2024-01-01", periods=n, freq="30min", tz="UTC")
    session = rng.choice(sessions, n, p=[.2, .25, .25, .2, .1])
    vol_regime = rng.choice(regimes, n, p=[.3, .5, .2])
    pd_zone = rng.choice(zones, n)
    recent_sweep = rng.choice(sweeps, n, p=[.25, .25, .5])
    trend_15m = rng.choice(trends, n)
    trend_1h = rng.choice(trends, n)
    trend_4h = rng.choice(trends, n)
    direction = rng.choice(dirs, n)
    in_killzone = rng.integers(0, 2, n)
    confidence = rng.integers(0, 11, n)
    atr_pct = np.abs(rng.normal(0.05, 0.02, n)) + 0.01
    ret_15m = rng.normal(0, 0.0015, n)
    ret_60m = rng.normal(0, 0.003, n)

    # latent win logit — faint signal + noise
    want = np.where(direction == "long", "up", "down")
    align = (trend_1h == want).astype(float) - 0.5      # +/-0.5
    vol_pen = np.where(vol_regime == "high", -0.45, 0.0)
    logit = (-0.55
             + 0.55 * in_killzone
             + 0.08 * (confidence - 5)
             + 0.9 * align
             + vol_pen
             + rng.normal(0, 0.7, n))
    p_win = 1.0 / (1.0 + np.exp(-logit))
    u = rng.random(n)
    is_win = u < p_win

    outcome = np.empty(n, dtype=object)
    realized_R = np.empty(n, dtype=float)
    for i in range(n):
        if is_win[i]:
            outcome[i] = "win"
            realized_R[i] = 2.0 - 0.05 + rng.normal(0, 0.05)
        else:
            # 80% clean loss, 20% timeout drifting slightly either way
            if rng.random() < 0.8:
                outcome[i] = "loss"
                realized_R[i] = -1.0 - 0.03 + rng.normal(0, 0.03)
            else:
                outcome[i] = "timeout"
                realized_R[i] = rng.normal(0.0, 0.35)

    df = pd.DataFrame({
        "ts": ts,
        "year": ts.year, "quarter": (ts.month - 1) // 3 + 1,
        "session": session, "in_killzone": in_killzone,
        "vol_regime": vol_regime, "pd_zone": pd_zone, "atr_pct": atr_pct,
        "ret_15m": ret_15m, "ret_60m": ret_60m, "recent_sweep": recent_sweep,
        "trend_15m": trend_15m, "trend_1h": trend_1h, "trend_4h": trend_4h,
        "direction": direction, "confidence": confidence,
        "outcome": outcome, "realized_R": realized_R,
    })
    # sprinkle some flat rows to prove they get filtered out
    n_flat = n // 10
    flat = df.sample(n_flat, random_state=seed).copy()
    flat["direction"] = "flat"
    flat["outcome"] = "flat"
    flat["realized_R"] = 0.0
    return pd.concat([df, flat]).sort_values("ts").reset_index(drop=True)


# --------------------------------------------------------------------------- #
def _fmt_stats(s: dict) -> str:
    def g(k, f="{:+.3f}"):
        v = s.get(k)
        return "  n/a" if v is None else f.format(v)
    return (f"n={s['n_trades']:>4}  hit={g('hit_rate','{:.3f}')}  "
            f"avgR={g('avg_R')}  PF={g('profit_factor','{:.3f}')}  "
            f"totR={g('cost_adjusted_total_R')}")


if __name__ == "__main__":
    if os.path.exists(SETUPS_PATH):
        src = f"results/setups.csv"
        raw = pd.read_csv(SETUPS_PATH)
    else:
        src = "SYNTHETIC self-test (setups.csv not found)"
        raw = synthetic_setups()

    results = run(raw)
    save(results)

    print("=" * 70)
    print("US30 META-LABELING FILTER  —  walk-forward, out-of-sample")
    print("=" * 70)
    print(f"source        : {src}")
    print(f"non-flat setups: {results['n_nonflat_setups']}")
    print(f"status        : {results['status']}")
    if results["status"] != "insufficient_data" or "oos_auc" in results:
        if results.get("oos_auc") is not None:
            print(f"OOS meta AUC  : {results['oos_auc']:.4f}   "
                  f"(OOS trades: {results.get('n_oos_trades')}, "
                  f"folds: {results.get('n_walk_forward_folds')})")
    if "compare" in results:
        print("-" * 70)
        print(f"  take ALL non-flat : {_fmt_stats(results['compare']['take_all_nonflat'])}")
        print(f"  take FILTERED     : {_fmt_stats(results['compare']['take_filtered'])}")
        print("-" * 70)
        print("  top features:")
        for row in results.get("feature_importances_top", [])[:8]:
            print(f"    {row['feature']:<14} {row['importance']}")
        print("-" * 70)
    print("VERDICT:")
    print("  " + results["verdict"])
    print("-" * 70)
    print(f"  wrote {os.path.relpath(RESULTS_PATH, os.getcwd())}")
    print("=" * 70)
