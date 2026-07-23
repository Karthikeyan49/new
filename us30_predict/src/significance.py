"""
Backlog item #5 — STATISTICAL SIGNIFICANCE.

A reality check on the analyst's apparent trading edge: given the per-trade
R-multiple outcomes, is the mean R distinguishable from *zero-edge noise*, or is
it the kind of number a coin-flip system throws off by luck?

Three complementary tests, all on a 1-D array of per-trade R multiples:

  1. bootstrap_mean_R   — resample trades with replacement to get a confidence
                          interval on the mean R and P(mean > 0).
  2. permutation_test   — the fair null for a symmetric-risk, zero-edge system is
                          "the sign of each trade's R was a coin flip". We flip
                          signs at random and ask how often pure luck produces a
                          |mean R| as extreme as observed -> two-sided p-value.
  3. sharpe_like        — mean/std of R per trade (a unit-free effect size), with
                          an annualised-ish note.

`assess` combines them into a one-line verdict. `from_scorecard` pulls R values
out of whatever artefact is lying around (a per-trade list, a calls dump, a CSV,
or — failing that — reconstructs an approximate R vector from the scorecard's
outcome counts so the module can still be demoed end-to-end).

Dependency-light: bootstrap + permutation are plain numpy. scipy is used only for
an optional cross-check (one-sample t-test) when it happens to be installed.

    python3 src/significance.py
"""
from __future__ import annotations

import csv
import json
import math
import os
from typing import Optional, Sequence

import numpy as np

# scipy is nice-to-have, never required.
try:
    from scipy import stats as _scipy_stats  # type: ignore
    _HAVE_SCIPY = True
except Exception:                            # pragma: no cover
    _scipy_stats = None
    _HAVE_SCIPY = False


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def _clean(r: Sequence[float]) -> np.ndarray:
    """Coerce to a 1-D float array of finite R multiples (drops NaN/inf)."""
    a = np.asarray(list(r), dtype=float).ravel()
    return a[np.isfinite(a)]


def _safe(x):
    """JSON-safe scalar: numpy -> python float, NaN/inf -> None."""
    if x is None:
        return None
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return x
    if math.isnan(xf) or math.isinf(xf):
        return None
    return xf


# --------------------------------------------------------------------------- #
# 1. bootstrap the mean R
# --------------------------------------------------------------------------- #
def bootstrap_mean_R(r: Sequence[float], n: int = 10000, seed: int = 0) -> dict:
    """Bootstrap a confidence interval for the mean per-trade R.

    Resamples the trades with replacement `n` times and looks at the sampling
    distribution of the mean. Returns the point estimate, a 95% percentile CI,
    and the fraction of resamples whose mean is above zero (a Bayesian-flavoured
    'probability the edge is positive').
    """
    a = _clean(r)
    m = len(a)
    if m == 0:
        return {"n_trades": 0, "mean_R": None, "ci95": [None, None],
                "frac_mean_gt_0": None, "n_boot": int(n), "seed": int(seed)}

    rng = np.random.default_rng(seed)
    mean_obs = float(a.mean())
    if m == 1:                                   # nothing to resample meaningfully
        return {"n_trades": 1, "mean_R": _safe(mean_obs),
                "ci95": [_safe(mean_obs), _safe(mean_obs)],
                "frac_mean_gt_0": 1.0 if mean_obs > 0 else 0.0,
                "n_boot": int(n), "seed": int(seed)}

    # index resampling keeps memory to n*m ints even for large n.
    idx = rng.integers(0, m, size=(int(n), m))
    boot_means = a[idx].mean(axis=1)
    lo, hi = np.percentile(boot_means, [2.5, 97.5])
    frac_pos = float((boot_means > 0.0).mean())
    return {
        "n_trades": int(m),
        "mean_R": _safe(mean_obs),
        "ci95": [_safe(lo), _safe(hi)],
        "frac_mean_gt_0": _safe(frac_pos),
        "n_boot": int(n),
        "seed": int(seed),
    }


# --------------------------------------------------------------------------- #
# 2. sign-flip permutation test  (H0: expected R == 0)
# --------------------------------------------------------------------------- #
def permutation_test(r: Sequence[float], n: int = 10000, seed: int = 0) -> dict:
    """Two-sided permutation test of H0: E[R] = 0.

    The null model is a zero-edge system with symmetric risk: each trade's
    magnitude |R| is real, but whether it landed as a win or a loss was a fair
    coin. We draw `n` random sign vectors, recompute the mean, and count how
    often pure luck reaches a |mean| >= |observed|. The (+1)/(+1) correction
    keeps the Monte-Carlo p-value strictly positive (never a fake p=0).
    """
    a = _clean(r)
    m = len(a)
    if m == 0:
        return {"n_trades": 0, "observed_mean_R": None, "p_value": None,
                "n_perm": int(n), "seed": int(seed)}

    mean_obs = float(a.mean())
    rng = np.random.default_rng(seed)
    signs = rng.choice(np.array([-1.0, 1.0]), size=(int(n), m))
    null_means = (signs * a).mean(axis=1)
    # two-sided: as-or-more-extreme than the observed |mean|
    count = int(np.sum(np.abs(null_means) >= abs(mean_obs) - 1e-15))
    p_value = (count + 1) / (int(n) + 1)

    out = {
        "n_trades": int(m),
        "observed_mean_R": _safe(mean_obs),
        "p_value": _safe(p_value),
        "n_perm": int(n),
        "seed": int(seed),
    }
    # optional scipy cross-check — a one-sample t-test against 0.
    if _HAVE_SCIPY and m >= 2 and a.std(ddof=1) > 0:
        try:
            t = _scipy_stats.ttest_1samp(a, 0.0)
            out["scipy_ttest_p"] = _safe(float(t.pvalue))
        except Exception:                        # pragma: no cover
            pass
    return out


# --------------------------------------------------------------------------- #
# 3. Sharpe-like per-trade effect size
# --------------------------------------------------------------------------- #
def sharpe_like(r: Sequence[float]) -> float:
    """Per-trade Sharpe = mean(R) / std(R).

    Unit-free effect size: how large the average edge is relative to trade-to-
    trade noise. Returns NaN for <2 trades or zero dispersion.

    Annualised-ish note: if the analyst takes ~T trades per year, the annualised
    Sharpe scales as this value * sqrt(T) (see `annualized_sharpe_note`).
    """
    a = _clean(r)
    if len(a) < 2:
        return float("nan")
    sd = float(a.std(ddof=1))
    if sd == 0.0:
        return float("nan")
    return float(a.mean()) / sd


def annualized_sharpe_note(r: Sequence[float], trades_per_year: float = 252.0) -> str:
    """A human-readable annualisation note for the per-trade Sharpe."""
    s = sharpe_like(r)
    if not math.isfinite(s):
        return "sharpe (per-trade): n/a (need >=2 trades with nonzero dispersion)"
    ann = s * math.sqrt(trades_per_year)
    return (f"sharpe (per-trade) = {s:+.3f}; "
            f"annualised-ish ~ {ann:+.2f} if ~{int(trades_per_year)} trades/yr "
            f"(x sqrt(N)) — indicative only")


# --------------------------------------------------------------------------- #
# 4. combined assessment / verdict
# --------------------------------------------------------------------------- #
def assess(r: Sequence[float], n: int = 10000, seed: int = 0,
           alpha: float = 0.05) -> dict:
    """Run all three tests and render a plain-English verdict on the edge."""
    a = _clean(r)
    boot = bootstrap_mean_R(a, n=n, seed=seed)
    perm = permutation_test(a, n=n, seed=seed)
    s = sharpe_like(a)

    m = len(a)
    mean_R = boot["mean_R"]
    ci = boot["ci95"]
    p = perm["p_value"]

    # ---- verdict logic ------------------------------------------------- #
    if m == 0:
        verdict = "no trades — nothing to assess"
        label = "NO DATA"
    else:
        ci_lo, ci_hi = ci
        significant = (p is not None and p < alpha)
        ci_excludes_zero = (ci_lo is not None and ci_hi is not None
                            and (ci_lo > 0.0 or ci_hi < 0.0))
        if significant and mean_R is not None and mean_R > 0 and ci_excludes_zero:
            label = "REAL EDGE"
            tail = "-> SIGNIFICANT positive edge"
        elif significant and mean_R is not None and mean_R < 0 and ci_excludes_zero:
            label = "NEGATIVE EDGE"
            tail = "-> SIGNIFICANT but LOSING (a real anti-edge)"
        else:
            label = "NOT SIGNIFICANT"
            tail = "-> NOT significant / consistent with no edge"

        def _f(x):
            return "n/a" if x is None else f"{x:+.2f}"

        verdict = (f"n={m}, mean R {_f(mean_R)}, "
                   f"95% CI [{_f(ci_lo)}, {_f(ci_hi)}], "
                   f"p={p:.3f}, sharpe {_f(s)} {tail}")

    return {
        "n_trades": int(m),
        "mean_R": mean_R,
        "ci95": ci,
        "frac_mean_gt_0": boot["frac_mean_gt_0"],
        "p_value": p,
        "sharpe_like": _safe(s),
        "annualized_note": annualized_sharpe_note(a),
        "label": label,
        "verdict": verdict,
        "alpha": alpha,
        "scipy_ttest_p": perm.get("scipy_ttest_p"),
    }


# --------------------------------------------------------------------------- #
# 5. loaders
# --------------------------------------------------------------------------- #
def _R_from_calls(calls) -> list[float]:
    """Pull realized_R out of a list of call dicts (only real, evaluated trades)."""
    out = []
    for c in calls:
        if not isinstance(c, dict):
            continue
        direction = str(c.get("direction", "flat")).lower()
        outcome = str(c.get("outcome", ""))
        if direction in ("long", "short") and outcome in ("win", "loss", "timeout"):
            r = c.get("realized_R", None)
            try:
                rf = float(r)
            except (TypeError, ValueError):
                continue
            if math.isfinite(rf):
                out.append(rf)
    return out


def _reconstruct_R_from_scorecard(card: dict) -> Optional[list[float]]:
    """Last resort: rebuild an *approximate* per-trade R vector from a scorecard's
    aggregates (outcome counts + avg_R). Wins/losses are set to typical 1:2 magnitudes
    then scaled so the reconstructed mean matches the reported avg_R exactly. This is
    an approximation for demo/QA — not the true per-trade series."""
    oc = card.get("outcome_counts") or {}
    n_win = int(oc.get("win", 0))
    n_loss = int(oc.get("loss", 0))
    n_to = int(oc.get("timeout", 0))
    n_trades = n_win + n_loss + n_to
    if n_trades == 0:
        return None
    avg_R = card.get("avg_R", None)
    # typical geometry: ~1:2 winner, ~1R loser, timeouts near flat.
    base = [2.0] * n_win + [-1.0] * n_loss + [-0.1] * n_to
    base = np.asarray(base, dtype=float)
    if avg_R is not None and math.isfinite(float(avg_R)):
        cur = base.mean()
        target = float(avg_R)
        # shift every trade by a constant so the mean lands on the reported avg_R,
        # preserving win/loss dispersion.
        base = base + (target - cur)
    return base.tolist()


def from_scorecard(path: str) -> list[float]:
    """Best-effort extraction of a per-trade R-multiple list from `path`.

    Handles, in order of preference:
      * a plain JSON list of numbers              -> used directly
      * a JSON dict carrying an explicit R list   ('realized_R'/'r_multiples'/'R'/'Rs')
      * a JSON dict with a 'trades'/'calls' list of call dicts -> pull realized_R
      * a scorecard-style aggregate dict          -> reconstruct approximate R (with note)
      * a CSV with a 'realized_R'/'R' column, or a single column / one-per-line of floats

    Returns a list of floats (possibly empty). Raises FileNotFoundError if missing.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    lower = path.lower()
    # ---- CSV ----------------------------------------------------------- #
    if lower.endswith(".csv"):
        with open(path, newline="") as fh:
            rows = list(csv.reader(fh))
        if not rows:
            return []
        header = rows[0]
        # find an R-ish column by name
        col = None
        for i, name in enumerate(header):
            if str(name).strip().lower() in ("realized_r", "r", "r_multiple", "rmultiple"):
                col = i
                break
        vals: list[float] = []
        if col is not None:
            for row in rows[1:]:
                if col < len(row):
                    try:
                        v = float(row[col])
                    except (TypeError, ValueError):
                        continue
                    if math.isfinite(v):
                        vals.append(v)
            return vals
        # no header match: treat file as a bare column / list of floats
        for row in rows:
            for cell in row:
                try:
                    v = float(cell)
                except (TypeError, ValueError):
                    continue
                if math.isfinite(v):
                    vals.append(v)
        return vals

    # ---- JSON ---------------------------------------------------------- #
    with open(path) as fh:
        data = json.load(fh)

    if isinstance(data, list):
        # either a list of numbers or a list of call dicts
        if data and isinstance(data[0], dict):
            return _R_from_calls(data)
        out = []
        for x in data:
            try:
                v = float(x)
            except (TypeError, ValueError):
                continue
            if math.isfinite(v):
                out.append(v)
        return out

    if isinstance(data, dict):
        for key in ("realized_R", "r_multiples", "R", "Rs", "r"):
            v = data.get(key)
            if isinstance(v, list) and v and not isinstance(v[0], dict):
                out = []
                for x in v:
                    try:
                        fv = float(x)
                    except (TypeError, ValueError):
                        continue
                    if math.isfinite(fv):
                        out.append(fv)
                if out:
                    return out
        for key in ("trades", "calls"):
            v = data.get(key)
            if isinstance(v, list):
                got = _R_from_calls(v)
                if got:
                    return got
        # scorecard aggregate -> approximate reconstruction
        recon = _reconstruct_R_from_scorecard(data)
        if recon is not None:
            return recon
        return []

    return []


# --------------------------------------------------------------------------- #
# 6. demo / self-proof
# --------------------------------------------------------------------------- #
def _synthetic_no_edge(n_trades: int = 200, seed: int = 1) -> np.ndarray:
    """A genuine zero-edge system: fair 50/50 coin on a 1:2 RR setup.
    A win pays +2R, a loss pays -1R, entered at random -> expected R < 0 only by
    RR asymmetry... so to make it a TRUE zero-edge series we set win prob = 1/3
    (the break-even rate for 1:2), giving E[R] ~ 0."""
    rng = np.random.default_rng(seed)
    wins = rng.random(n_trades) < (1.0 / 3.0)      # break-even hit rate for 1:2
    r = np.where(wins, 2.0, -1.0).astype(float)
    return r


def _synthetic_real_edge(n_trades: int = 200, seed: int = 2) -> np.ndarray:
    """A real edge: same 1:2 RR geometry but a genuinely elevated win rate (~48%),
    comfortably above the 33% break-even -> clearly positive E[R]."""
    rng = np.random.default_rng(seed)
    wins = rng.random(n_trades) < 0.48
    r = np.where(wins, 2.0, -1.0).astype(float)
    return r


def _find_input() -> Optional[str]:
    here = os.path.dirname(os.path.abspath(__file__))
    results = os.path.join(here, "..", "results")
    for name in ("calls.json", "replay_calls.json", "trades.json",
                 "calls.csv", "scorecard.json"):
        p = os.path.join(results, name)
        if os.path.exists(p):
            return p
    return None


def main() -> dict:
    here = os.path.dirname(os.path.abspath(__file__))
    results_dir = os.path.join(here, "..", "results")
    os.makedirs(results_dir, exist_ok=True)

    print("=" * 70)
    print("STATISTICAL SIGNIFICANCE — is the edge real or noise?")
    print(f"(scipy {'available' if _HAVE_SCIPY else 'NOT installed — numpy only'})")
    print("=" * 70)

    out: dict = {"scipy_available": _HAVE_SCIPY}

    # ---- synthetic sanity check --------------------------------------- #
    no_edge = _synthetic_no_edge()
    real_edge = _synthetic_real_edge()

    a_no = assess(no_edge)
    a_real = assess(real_edge)

    print("\n[A] SYNTHETIC NO-EDGE (fair 1:2 coin, break-even hit rate)")
    print("    " + a_no["verdict"])
    print("\n[B] SYNTHETIC REAL-EDGE (1:2 geometry, ~48% hit rate)")
    print("    " + a_real["verdict"])

    no_edge_ok = a_no["p_value"] is not None and a_no["p_value"] > 0.05
    real_edge_ok = a_real["p_value"] is not None and a_real["p_value"] < 0.05
    print("\n    sanity check: "
          f"no-edge p>0.05 ? {no_edge_ok} (p={a_no['p_value']:.3f}); "
          f"real-edge p<0.05 ? {real_edge_ok} (p={a_real['p_value']:.4f})")
    print(f"    => module {'CORRECTLY' if (no_edge_ok and real_edge_ok) else 'FAILS TO'} "
          "distinguish edge from noise")

    out["synthetic"] = {
        "no_edge": a_no,
        "real_edge": a_real,
        "distinguishes_correctly": bool(no_edge_ok and real_edge_ok),
    }

    # ---- real artefact, if any ---------------------------------------- #
    inp = _find_input()
    if inp:
        rvals = from_scorecard(inp)
        reconstructed = (inp.lower().endswith("scorecard.json"))
        print(f"\n[C] REAL DATA from {os.path.relpath(inp, here)}"
              + ("  (R reconstructed from scorecard aggregates — approximate)"
                 if reconstructed else ""))
        if rvals:
            a_real_data = assess(rvals)
            print("    " + a_real_data["verdict"])
            print("    " + a_real_data["annualized_note"])
            out["scorecard_source"] = os.path.relpath(inp, os.path.dirname(here))
            out["scorecard_reconstructed_R"] = reconstructed
            out["scorecard_assessment"] = a_real_data
        else:
            print("    (no per-trade R multiples could be extracted)")
            out["scorecard_source"] = os.path.relpath(inp, os.path.dirname(here))
            out["scorecard_assessment"] = None
    else:
        print("\n[C] no scorecard / calls artefact found — skipping real-data assess")
        out["scorecard_assessment"] = None

    # ---- persist ------------------------------------------------------ #
    out_path = os.path.join(results_dir, "significance.json")
    with open(out_path, "w") as fh:
        json.dump(out, fh, indent=2, default=str)
    print(f"\nsaved -> {os.path.relpath(out_path, os.path.dirname(here))}")
    return out


if __name__ == "__main__":
    main()
