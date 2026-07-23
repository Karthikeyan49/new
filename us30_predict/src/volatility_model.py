"""
US30 backlog item #3 — VOLATILITY & RANGE prediction model.

The honest 'what IS predictable' result. Direction of US30 is ~unpredictable
(a coin flip), but *how much it will move* over the next hour is not: volatility
clusters and is strongly time-of-day dependent. This module predicts the NEXT
60-minute realized volatility (and forward range) from past-only features and
shows — via a strict walk-forward evaluation against naive baselines — that it
is meaningfully predictable.

Design (all causal, no look-ahead):

  working grid : 15-minute bars (tractable; ~24k rows from the 1m file).
  target y     : realized volatility over the NEXT 60 min = std of the 1-min
                 log returns falling in (t, t+60min]. Computed by pooling the
                 squared 1-min returns of the four forward 15-min buckets:
                     y(t) = sqrt( sum_{next 4 buckets} r^2 / count )
                 (a secondary target — forward high-low range / price — is also
                 built and reported.)
  features X   : built only from buckets at or before t. There is NO overlap
                 between the buckets used for X (<= t) and those used for y (> t),
                 so there is no leakage at any row.

  model        : LightGBM regressor, validated WALK-FORWARD (expanding window).
  baselines    : persistence ("next vol = last realized 60m vol") and
                 trailing-mean ("next vol = mean vol seen in training so far").

Run:  python -m src.volatility_model      (from us30_predict/)
      python src/volatility_model.py
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

# Allow both "python src/volatility_model.py" and "python -m src.volatility_model".
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schema import load_m1  # noqa: E402

import lightgbm as lgb  # noqa: E402
from sklearn.metrics import mean_absolute_error, r2_score  # noqa: E402


HERE = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(HERE, "..", "data", "US30_M1.csv")
RESULTS_PATH = os.path.join(HERE, "..", "results", "volatility.json")

BAR = "15min"           # working frequency
BUCKETS_PER_HOUR = 4    # 60 / 15
# feature lookbacks in minutes -> number of 15-min buckets
LOOKBACKS_MIN = [15, 30, 60, 120, 240]
ATR_PERIOD = 14         # bars, on the 15-min grid
N_SPLITS = 6            # walk-forward folds


# --------------------------------------------------------------------------- #
# Feature / target construction (all causal)
# --------------------------------------------------------------------------- #
def build_dataset(df1m: pd.DataFrame) -> pd.DataFrame:
    """From the 1-min frame build a 15-min feature/target table.

    Every feature is a function of buckets <= t; every target of buckets > t.
    """
    s = df1m.set_index("timestamp").sort_index()

    # 1-min log returns and their squares (the raw material for realized vol).
    close_1m = s["close"].astype(float)
    r1m = np.log(close_1m).diff()
    r1m_sq = r1m ** 2

    # --- resample the 1m file onto the 15-min grid ----------------------- #
    # Squared-return sum and count per bucket -> lets us pool returns over any
    # multi-bucket window to get a proper std (realized vol).
    sumsq = r1m_sq.resample(BAR, label="right", closed="right").sum()
    cnt = r1m.resample(BAR, label="right", closed="right").count()

    o = s["open"].resample(BAR, label="right", closed="right").first()
    h = s["high"].resample(BAR, label="right", closed="right").max()
    l = s["low"].resample(BAR, label="right", closed="right").min()
    c = s["close"].resample(BAR, label="right", closed="right").last()

    g = pd.DataFrame({"open": o, "high": h, "low": l, "close": c,
                      "sumsq": sumsq, "cnt": cnt})
    # Drop empty buckets (weekends / market-closed gaps).
    g = g[g["cnt"] > 0].copy()

    def pooled_std(win_buckets: int, forward: bool) -> pd.Series:
        """std of the 1-min returns pooled over `win_buckets` buckets.

        forward=False -> trailing window ending at t (buckets t-win+1..t).
        forward=True  -> window strictly after t (buckets t+1..t+win).
        Uses zero-mean pooled variance = sum(r^2)/count, the canonical
        realized-vol estimator.
        """
        ss = g["sumsq"].rolling(win_buckets).sum()
        nn = g["cnt"].rolling(win_buckets).sum()
        if forward:
            ss = ss.shift(-win_buckets)
            nn = nn.shift(-win_buckets)
        return np.sqrt(ss / nn.replace(0, np.nan))

    # ---------------- TARGETS (future only) ------------------------------ #
    # Primary: realized vol of 1-min returns over the next 60 min.
    g["y_vol"] = pooled_std(BUCKETS_PER_HOUR, forward=True)
    # Secondary: forward high-low range over next 60 min, as a fraction of price.
    fwd_high = g["high"].rolling(BUCKETS_PER_HOUR).max().shift(-BUCKETS_PER_HOUR)
    fwd_low = g["low"].rolling(BUCKETS_PER_HOUR).min().shift(-BUCKETS_PER_HOUR)
    g["y_range"] = (fwd_high - fwd_low) / g["close"]

    # ---------------- FEATURES (past only) ------------------------------- #
    feats = {}

    # Realized vol over multiple trailing lookbacks.
    for m in LOOKBACKS_MIN:
        wb = max(1, m // 15)
        feats[f"rv_{m}m"] = pooled_std(wb, forward=False)

    # 15-min log return, absolute return, trailing mean abs return.
    ret15 = np.log(g["close"]).diff()
    feats["ret_15m"] = ret15
    feats["abs_ret_15m"] = ret15.abs()
    feats["mean_absret_60m"] = ret15.abs().rolling(BUCKETS_PER_HOUR).mean()
    feats["mean_absret_240m"] = ret15.abs().rolling(16).mean()

    # True range / ATR on the 15-min grid.
    prev_close = g["close"].shift(1)
    tr = pd.concat([
        (g["high"] - g["low"]),
        (g["high"] - prev_close).abs(),
        (g["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    feats["atr_14"] = tr.rolling(ATR_PERIOD).mean()
    feats["atr_pct"] = feats["atr_14"] / g["close"]

    # Bar range and range ratios / rolling range stats.
    bar_range = (g["high"] - g["low"]) / g["close"]
    feats["range_15m"] = bar_range
    feats["range_mean_60m"] = bar_range.rolling(BUCKETS_PER_HOUR).mean()
    feats["range_mean_240m"] = bar_range.rolling(16).mean()
    feats["range_max_60m"] = bar_range.rolling(BUCKETS_PER_HOUR).max()
    feats["range_max_240m"] = bar_range.rolling(16).max()
    # short-vs-long range ratio: is the market heating up or cooling down?
    feats["range_ratio_60_240"] = (
        feats["range_mean_60m"] / feats["range_mean_240m"].replace(0, np.nan))
    # short-vs-long realized-vol ratio.
    feats["rv_ratio_60_240"] = (
        feats["rv_60m"] / feats["rv_240m"].replace(0, np.nan))

    # Time-of-day (NY) — volatility is strongly session dependent.
    ny = g.index.tz_convert("America/New_York")
    feats["hour_ny"] = ny.hour.astype(float)
    feats["minute_ny"] = ny.minute.astype(float)
    feats["dow"] = ny.dayofweek.astype(float)

    fdf = pd.DataFrame(feats, index=g.index)
    out = pd.concat([fdf, g[["y_vol", "y_range"]]], axis=1)

    # Replace infinities, then drop rows with any NaN (warmup + forward edge).
    out = out.replace([np.inf, -np.inf], np.nan).dropna()
    out.attrs["feature_cols"] = list(fdf.columns)
    return out


# --------------------------------------------------------------------------- #
# Walk-forward evaluation
# --------------------------------------------------------------------------- #
def walk_forward(X: pd.DataFrame, y: pd.Series, feature_cols: list[str],
                 n_splits: int = N_SPLITS):
    """Expanding-window walk-forward. Returns concatenated OOS predictions for
    the model and both baselines, aligned to the same rows, plus per-fold info.
    """
    n = len(X)
    # Expanding folds: first block trains, each subsequent block is one OOS fold.
    # Boundaries split the series into n_splits+1 equal parts; part 0 is the
    # initial train set, parts 1..n_splits are successive OOS test folds.
    bounds = np.linspace(0, n, n_splits + 2, dtype=int)

    oos_idx, oos_true = [], []
    oos_model, oos_persist, oos_mean = [], [], []
    fold_rows = []

    # persistence prediction = trailing realized 60m vol (the "last" vol).
    persist_all = X["rv_60m"].values

    for k in range(1, n_splits + 1):
        tr_end = bounds[k]
        te_start = bounds[k]
        te_end = bounds[k + 1]
        if te_end <= te_start or tr_end < 50:
            continue

        Xtr = X.iloc[:tr_end][feature_cols]
        ytr = y.iloc[:tr_end]
        Xte = X.iloc[te_start:te_end][feature_cols]
        yte = y.iloc[te_start:te_end]

        model = lgb.LGBMRegressor(
            n_estimators=400,
            learning_rate=0.03,
            num_leaves=31,
            max_depth=-1,
            min_child_samples=40,
            subsample=0.8,
            subsample_freq=1,
            colsample_bytree=0.8,
            reg_lambda=1.0,
            random_state=42,
            n_jobs=-1,
            verbose=-1,
        )
        model.fit(Xtr, ytr)
        pred = model.predict(Xte)

        oos_idx.extend(Xte.index)
        oos_true.extend(yte.values)
        oos_model.extend(pred)
        oos_persist.extend(persist_all[te_start:te_end])
        oos_mean.extend(np.full(len(yte), ytr.mean()))  # trailing-mean baseline

        fold_rows.append({
            "fold": k,
            "train_end": int(tr_end),
            "test_start": int(te_start),
            "test_end": int(te_end),
            "n_test": int(len(yte)),
            "model_r2": float(r2_score(yte.values, pred)),
        })

    res = {
        "index": oos_idx,
        "y_true": np.array(oos_true),
        "model": np.array(oos_model),
        "persist": np.array(oos_persist),
        "mean": np.array(oos_mean),
        "folds": fold_rows,
    }
    return res


def _score(y_true, y_pred):
    return {
        "r2": float(r2_score(y_true, y_pred)),
        "mae": float(mean_absolute_error(y_true, y_pred)),
    }


def run(data_path: str = DATA_PATH) -> dict:
    df1m = load_m1(data_path)
    ds = build_dataset(df1m)
    feature_cols = ds.attrs["feature_cols"]
    # rv_60m is one of the features; walk_forward reads it off `ds` directly
    # for the persistence baseline.
    y = ds["y_vol"]

    wf = walk_forward(ds, y, feature_cols)

    model_scores = _score(wf["y_true"], wf["model"])
    persist_scores = _score(wf["y_true"], wf["persist"])
    mean_scores = _score(wf["y_true"], wf["mean"])

    # Feature importances from a final model fit on the full history (for report).
    final = lgb.LGBMRegressor(
        n_estimators=400, learning_rate=0.03, num_leaves=31,
        min_child_samples=40, subsample=0.8, subsample_freq=1,
        colsample_bytree=0.8, reg_lambda=1.0, random_state=42,
        n_jobs=-1, verbose=-1,
    )
    final.fit(ds[feature_cols], y)
    imp = sorted(zip(feature_cols, final.feature_importances_.tolist()),
                 key=lambda kv: kv[1], reverse=True)
    top_imp = [{"feature": f, "importance": int(v)} for f, v in imp[:10]]

    results = {
        "target": "next_60min_realized_volatility (std of 1-min log returns, causal)",
        "timeframe": BAR,
        "horizon_min": 60,
        "n_samples": int(len(ds)),
        "n_oos_samples": int(len(wf["y_true"])),
        "n_walk_forward_folds": len(wf["folds"]),
        "target_mean": float(y.mean()),
        "target_std": float(y.std()),
        "features_used": feature_cols,
        "walk_forward": {
            "model": model_scores,
            "baseline_persistence": persist_scores,
            "baseline_trailing_mean": mean_scores,
            "model_improvement_over_persistence_r2":
                float(model_scores["r2"] - persist_scores["r2"]),
            "per_fold": wf["folds"],
        },
        "feature_importances_top10": top_imp,
    }

    os.makedirs(os.path.dirname(RESULTS_PATH), exist_ok=True)
    with open(RESULTS_PATH, "w") as fh:
        json.dump(results, fh, indent=2)

    return results


def _fmt(s):
    return f"R2={s['r2']:+.3f}  MAE={s['mae']:.6f}"


if __name__ == "__main__":
    res = run()
    wf = res["walk_forward"]
    print("=" * 66)
    print("US30 VOLATILITY & RANGE PREDICTION  —  walk-forward out-of-sample")
    print("=" * 66)
    print(f"target        : {res['target']}")
    print(f"timeframe     : {res['timeframe']}   horizon: {res['horizon_min']} min")
    print(f"samples       : {res['n_samples']}  (OOS: {res['n_oos_samples']}"
          f" over {res['n_walk_forward_folds']} folds)")
    print(f"target mean/std: {res['target_mean']:.6f} / {res['target_std']:.6f}")
    print("-" * 66)
    print(f"  LightGBM model     : {_fmt(wf['model'])}")
    print(f"  baseline persist   : {_fmt(wf['baseline_persistence'])}")
    print(f"  baseline trail-mean: {_fmt(wf['baseline_trailing_mean'])}")
    print(f"  model gain vs persist (R2): "
          f"{wf['model_improvement_over_persistence_r2']:+.3f}")
    print("-" * 66)
    print("  top features:")
    for row in res["feature_importances_top10"]:
        print(f"    {row['feature']:<22} {row['importance']}")
    print("-" * 66)
    print(f"  wrote {os.path.relpath(RESULTS_PATH)}")
    print("=" * 66)
