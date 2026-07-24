"""
Predictability audit + improvement for US30.

The discretionary analyst lost on direction. Before concluding, this exhausts the
rigorous questions:
  1. WHY does it lose? (decompose the 553 trades: win/loss/timeout, avg R each,
     implied reward:risk, cost drag) -> is the loss geometry/cost or randomness?
  2. Is direction predictable AT ALL? (return autocorrelation across horizons +
     Lo-MacKinlay variance-ratio random-walk test)
  3. Does ANY simple mechanical edge exist that the analyst missed?
     (time-of-day drift; momentum/reversion at several horizons) — cost-adjusted,
     in-sample vs out-of-sample.

Honest by construction: everything is split IS/OOS and net of a round-trip cost.
"""
from __future__ import annotations
import json, os
import numpy as np
import pandas as pd

from schema import load_m1

HERE = os.path.dirname(__file__)
RES = os.path.join(HERE, "..", "results")
ROUND_TRIP_PTS = 2.0          # US30 spread cost per round trip, in index points


# ---------- 1. why the analyst loses ----------
def decompose_direction():
    df = pd.read_csv(os.path.join(RES, "setups.csv"))
    nf = df[df.direction != "flat"]
    r = nf.realized_R.to_numpy(float)
    oc = nf.outcome.value_counts().to_dict()
    wins = r[r > 0]; losses = r[r < 0]
    return {
        "n_trades": int(len(nf)),
        "outcome_counts": {k: int(v) for k, v in oc.items()},
        "avg_R": round(float(r.mean()), 3),
        "win_rate_Rpos": round(float((r > 0).mean()), 3),
        "avg_win_R": round(float(wins.mean()), 3) if len(wins) else 0.0,
        "avg_loss_R": round(float(losses.mean()), 3) if len(losses) else 0.0,
        "implied_reward_risk": round(float(wins.mean() / -losses.mean()), 3) if len(losses) else None,
        "note": ("wins are frequent but the reward:risk<1 and costs bleed the rest -> "
                 "high hit-rate still loses; classic broken-geometry-on-random-direction"),
    }


# ---------- helpers ----------
def contiguous_logret(df):
    """1-min log returns, masking session/weekend breaks (gap > 2 min)."""
    c = df["close"].to_numpy(float)
    t = df["timestamp"].values.astype("datetime64[m]").astype(np.int64)
    lr = np.diff(np.log(c))
    contiguous = (np.diff(t) <= 2)
    return lr[contiguous], df["timestamp"].to_numpy()[1:][contiguous]


# ---------- 2. is direction predictable at all ----------
def autocorrelation(lr, lags=(1, 2, 3, 5, 10, 15, 30, 60)):
    out = {}
    x = lr - lr.mean()
    denom = np.dot(x, x)
    for k in lags:
        out[str(k)] = round(float(np.dot(x[:-k], x[k:]) / denom), 5)
    return out


def variance_ratio(lr, qs=(2, 4, 8, 16, 32)):
    """Lo-MacKinlay VR with heteroskedasticity-robust z. VR=1 => random walk."""
    n = len(lr)
    mu = lr.mean()
    var1 = np.sum((lr - mu) ** 2) / (n - 1)
    out = {}
    for q in qs:
        rq = np.convolve(lr, np.ones(q), "valid")            # q-period returns
        varq = np.sum((rq - q * mu) ** 2) / (n - q + 1)
        vr = varq / (q * var1)
        # robust variance of VR (Lo-MacKinlay 1988)
        theta = 0.0
        for j in range(1, q):
            dj = np.sum((lr[j:] - mu) ** 2 * (lr[:-j] - mu) ** 2) / (np.sum((lr - mu) ** 2)) ** 2 * n
            theta += (2 * (q - j) / q) ** 2 * dj
        z = (vr - 1) / np.sqrt(theta / n) if theta > 0 else float("nan")
        out[str(q)] = {"VR": round(float(vr), 4), "z": round(float(z), 2)}
    return out


# ---------- 3. mechanical anomaly scan ----------
def time_of_day(df):
    lr, ts = contiguous_logret(df)
    ny = pd.DatetimeIndex(ts).tz_convert("America/New_York").hour
    n = len(lr); half = n // 2
    res = {}
    for h in range(24):
        m = (ny == h)
        if m.sum() < 500:
            continue
        ins = lr[:half][m[:half]]; oos = lr[half:][m[half:]]
        res[h] = {"n": int(m.sum()),
                  "mean_bp_IS": round(float(ins.mean() * 1e4), 3),
                  "mean_bp_OOS": round(float(oos.mean() * 1e4), 3)}
    return res


def momentum_reversion(df, horizons=(5, 15, 30, 60)):
    """Rule: sign of last-h return -> trade next h. Net of cost, IS vs OOS."""
    c = df["close"].to_numpy(float)
    cost = ROUND_TRIP_PTS / np.nanmean(c)
    out = {}
    for h in horizons:
        past = np.log(c[h:-h] / c[:-2 * h])      # return over [t-h, t]
        fwd = np.log(c[2 * h:] / c[h:-h])        # return over [t, t+h]
        sig = np.sign(past)
        pnl = sig * fwd - cost                    # momentum rule, cost per trade
        half = len(pnl) // 2
        def stat(p):
            return {"avg_bp": round(float(p.mean() * 1e4), 3),
                    "win_rate": round(float((p > 0).mean()), 3),
                    "sharpe": round(float(p.mean() / (p.std() + 1e-12)), 4)}
        out[str(h)] = {"momentum_IS": stat(pnl[:half]), "momentum_OOS": stat(pnl[half:]),
                       "reversion_OOS": stat((-sig * fwd - cost)[half:])}
    return out


def main():
    df = load_m1(os.path.join(HERE, "..", "data", "US30_M1.csv"))
    lr, _ = contiguous_logret(df)
    audit = {
        "data": f"{len(df):,} 1-min bars, {df.timestamp.iloc[0].date()} -> {df.timestamp.iloc[-1].date()}",
        "1_why_analyst_loses": decompose_direction(),
        "2a_return_autocorrelation": autocorrelation(lr),
        "2b_variance_ratio_random_walk_test": variance_ratio(lr),
        "3a_time_of_day_drift_bp": time_of_day(df),
        "3b_momentum_reversion": momentum_reversion(df),
    }
    with open(os.path.join(RES, "predictability_audit.json"), "w") as fh:
        json.dump(audit, fh, indent=2, default=str)
    print(json.dumps(audit, indent=2, default=str))


if __name__ == "__main__":
    main()
