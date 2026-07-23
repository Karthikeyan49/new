"""Dependency-free SVG visualizations of the honest US30 results.

Backlog item #8. Reads the replay/model artifacts in ``results/`` and writes four
self-contained, theme-agnostic SVG charts (white background, no external libs,
no matplotlib). Only pandas / numpy / stdlib are used.

Charts
------
1. equity_curve.svg   - cumulative realized_R over traded (non-flat) setups.
2. calibration.svg    - confidence bucket vs realized win-rate + break-even line.
3. yearly_R.svg       - cost-adjusted total R per year (from walkforward.json).
4. volatility_r2.svg  - walk-forward R2: model vs baselines (from volatility.json).
"""
from __future__ import annotations

import json
import os
from html import escape

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RESULTS = os.path.join(ROOT, "results")

W, H = 720, 300
PAD_L, PAD_R, PAD_T, PAD_B = 56, 24, 44, 46

# theme-agnostic palette (readable on white)
INK = "#111827"
MUTE = "#6b7280"
GRID = "#e5e7eb"
AXIS = "#9ca3af"
RED = "#d73027"
GREEN = "#1a9850"
BLUE = "#2b6cb0"
AMBER = "#d99000"


# --------------------------------------------------------------------------- #
# render helper
# --------------------------------------------------------------------------- #
def render(body: str, width: int = W, height: int = H) -> str:
    """Wrap chart ``body`` markup in a valid, self-contained SVG document."""
    return (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' "
        f"viewBox='0 0 {width} {height}' font-family='sans-serif'>"
        f"<rect width='{width}' height='{height}' fill='#ffffff'/>"
        f"{body}</svg>"
    )


def _txt(x, y, s, size=11, fill=MUTE, anchor="start", weight="normal"):
    return (
        f"<text x='{x:.1f}' y='{y:.1f}' font-size='{size}' fill='{fill}' "
        f"text-anchor='{anchor}' font-weight='{weight}'>{escape(str(s))}</text>"
    )


def _title(s):
    return _txt(PAD_L, 24, s, size=15, fill=INK, weight="600")


# --------------------------------------------------------------------------- #
# 1. equity curve
# --------------------------------------------------------------------------- #
def equity_curve_svg(df: pd.DataFrame) -> str:
    nf = df[df["direction"] != "flat"].copy()
    nf = nf.sort_values("ts")
    r = nf["realized_R"].astype(float).tolist()
    cum, run = [], 0.0
    for v in r:
        run += v
        cum.append(run)
    if len(cum) < 2:
        return render(_title("Equity curve (no trades)"))

    iw = W - PAD_L - PAD_R
    ih = H - PAD_T - PAD_B
    lo, hi = min(cum + [0.0]), max(cum + [0.0])
    rng = (hi - lo) or 1.0
    n = len(cum)

    def X(i):
        return PAD_L + iw * i / (n - 1)

    def Y(v):
        return PAD_T + ih * (1 - (v - lo) / rng)

    body = [_title("Equity curve  -  cumulative realized R (traded setups)")]
    # gridlines
    for f in (0, 0.25, 0.5, 0.75, 1):
        yy = PAD_T + ih * f
        body.append(
            f"<line x1='{PAD_L}' y1='{yy:.1f}' x2='{W-PAD_R}' y2='{yy:.1f}' "
            f"stroke='{GRID}' stroke-width='1'/>"
        )
        val = hi - (hi - lo) * f
        body.append(_txt(PAD_L - 6, yy + 3, f"{val:.0f}R", size=10, anchor="end"))
    # zero baseline
    y0 = Y(0.0)
    body.append(
        f"<line x1='{PAD_L}' y1='{y0:.1f}' x2='{W-PAD_R}' y2='{y0:.1f}' "
        f"stroke='{AXIS}' stroke-dasharray='4 4' stroke-width='1'/>"
    )
    # area under curve to zero (shaded loss)
    pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(cum))
    area = f"{PAD_L:.1f},{y0:.1f} {pts} {W-PAD_R:.1f},{y0:.1f}"
    color = GREEN if cum[-1] >= 0 else RED
    fill = "#1a985022" if cum[-1] >= 0 else "#d7302722"
    body.append(f"<polygon points='{area}' fill='{fill}' stroke='none'/>")
    body.append(f"<polyline points='{pts}' fill='none' stroke='{color}' stroke-width='2'/>")
    # endpoint marker
    body.append(f"<circle cx='{X(n-1):.1f}' cy='{Y(cum[-1]):.1f}' r='3' fill='{color}'/>")
    # labels
    body.append(_txt(PAD_L, H - 14, f"{n} trades, ordered by time", size=11))
    body.append(
        _txt(
            W - PAD_R,
            H - 14,
            f"ends {cum[-1]:.1f}R",
            size=12,
            fill=color,
            anchor="end",
            weight="600",
        )
    )
    return render("".join(body))


# --------------------------------------------------------------------------- #
# 2. calibration
# --------------------------------------------------------------------------- #
def _breakeven_wr(df: pd.DataFrame) -> float:
    wl = df[df["outcome"].isin(["win", "loss"])]
    aw = wl.loc[wl["outcome"] == "win", "realized_R"].astype(float).mean()
    al = wl.loc[wl["outcome"] == "loss", "realized_R"].astype(float).mean()
    if pd.isna(aw) or pd.isna(al) or (aw - al) == 0:
        return 0.5
    return float(-al / (aw - al))


def calibration_svg(df: pd.DataFrame) -> str:
    nf = df[df["direction"] != "flat"]
    wl = nf[nf["outcome"].isin(["win", "loss"])].copy()
    be = _breakeven_wr(nf)

    buckets = [("3-4", 3, 4), ("5-6", 5, 6), ("7-8", 7, 8), ("9-10", 9, 10)]
    rows = []
    for lab, lo, hi in buckets:
        s = wl[(wl["confidence"] >= lo) & (wl["confidence"] <= hi)]
        n = len(s)
        wr = float((s["outcome"] == "win").mean()) if n else 0.0
        rows.append((lab, n, wr))

    iw = W - PAD_L - PAD_R
    ih = H - PAD_T - PAD_B
    body = [_title("Calibration  -  confidence bucket vs realized win-rate")]
    # y grid 0..1
    for f in (0, 0.25, 0.5, 0.75, 1):
        yy = PAD_T + ih * (1 - f)
        body.append(
            f"<line x1='{PAD_L}' y1='{yy:.1f}' x2='{W-PAD_R}' y2='{yy:.1f}' "
            f"stroke='{GRID}' stroke-width='1'/>"
        )
        body.append(_txt(PAD_L - 6, yy + 3, f"{int(f*100)}%", size=10, anchor="end"))

    def Y(v):
        return PAD_T + ih * (1 - v)

    slot = iw / len(rows)
    bw = slot * 0.5
    line_pts = []
    for i, (lab, n, wr) in enumerate(rows):
        cx = PAD_L + slot * (i + 0.5)
        bx = cx - bw / 2
        by = Y(wr)
        color = GREEN if wr >= be else RED
        body.append(
            f"<rect x='{bx:.1f}' y='{by:.1f}' width='{bw:.1f}' "
            f"height='{(PAD_T+ih-by):.1f}' fill='{color}' opacity='0.85'/>"
        )
        body.append(_txt(cx, by - 5, f"{wr*100:.0f}%", size=11, fill=INK, anchor="middle", weight="600"))
        body.append(_txt(cx, PAD_T + ih + 16, f"conf {lab}", size=11, anchor="middle"))
        body.append(_txt(cx, PAD_T + ih + 30, f"n={n}", size=10, anchor="middle"))
        line_pts.append(f"{cx:.1f},{by:.1f}")
    # connecting line to emphasise flat/uncorrelated trend
    body.append(f"<polyline points='{' '.join(line_pts)}' fill='none' stroke='{INK}' stroke-width='1.5' stroke-dasharray='2 3'/>")
    # break-even reference line
    yb = Y(be)
    body.append(
        f"<line x1='{PAD_L}' y1='{yb:.1f}' x2='{W-PAD_R}' y2='{yb:.1f}' "
        f"stroke='{AMBER}' stroke-width='2' stroke-dasharray='6 4'/>"
    )
    body.append(_txt(W - PAD_R, yb - 5, f"break-even {be*100:.0f}%", size=11, fill=AMBER, anchor="end", weight="600"))
    return render("".join(body))


# --------------------------------------------------------------------------- #
# 3. yearly R
# --------------------------------------------------------------------------- #
def yearly_R_svg(wf: dict) -> str:
    yr = wf.get("breakdowns", {}).get("year", {})
    items = sorted(yr.items(), key=lambda kv: kv[0])
    data = [(y, float(d.get("cost_adjusted_total_R", 0.0))) for y, d in items]
    if not data:
        return render(_title("Yearly cost-adjusted R (no data)"))

    iw = W - PAD_L - PAD_R
    ih = H - PAD_T - PAD_B
    vals = [v for _, v in data]
    lo, hi = min(vals + [0.0]), max(vals + [0.0])
    rng = (hi - lo) or 1.0

    def Y(v):
        return PAD_T + ih * (1 - (v - lo) / rng)

    y0 = Y(0.0)
    body = [_title("Cost-adjusted total R per year  (walk-forward)")]
    # horizontal grid
    for f in (0, 0.25, 0.5, 0.75, 1):
        yy = PAD_T + ih * f
        body.append(
            f"<line x1='{PAD_L}' y1='{yy:.1f}' x2='{W-PAD_R}' y2='{yy:.1f}' "
            f"stroke='{GRID}' stroke-width='1'/>"
        )
        val = hi - (hi - lo) * f
        body.append(_txt(PAD_L - 6, yy + 3, f"{val:.0f}", size=10, anchor="end"))
    # zero line
    body.append(
        f"<line x1='{PAD_L}' y1='{y0:.1f}' x2='{W-PAD_R}' y2='{y0:.1f}' "
        f"stroke='{AXIS}' stroke-width='1'/>"
    )
    slot = iw / len(data)
    bw = slot * 0.62
    for i, (y, v) in enumerate(data):
        cx = PAD_L + slot * (i + 0.5)
        bx = cx - bw / 2
        yv = Y(v)
        top = min(yv, y0)
        hgt = abs(yv - y0)
        color = GREEN if v >= 0 else RED
        body.append(
            f"<rect x='{bx:.1f}' y='{top:.1f}' width='{bw:.1f}' "
            f"height='{hgt:.1f}' fill='{color}' opacity='0.85'/>"
        )
        vlab_y = (top - 4) if v >= 0 else (top + hgt + 12)
        body.append(_txt(cx, vlab_y, f"{v:.0f}", size=9, fill=INK, anchor="middle"))
        body.append(_txt(cx, H - 14, str(y), size=10, anchor="middle"))
    return render("".join(body))


# --------------------------------------------------------------------------- #
# 4. volatility R2
# --------------------------------------------------------------------------- #
def volatility_r2_svg(vol: dict) -> str:
    wfd = vol.get("walk_forward", {})
    series = [
        ("Volatility model", float(wfd.get("model", {}).get("r2", 0.0)), BLUE),
        ("Persistence baseline", float(wfd.get("baseline_persistence", {}).get("r2", 0.0)), MUTE),
        ("Trailing-mean baseline", float(wfd.get("baseline_trailing_mean", {}).get("r2", 0.0)), MUTE),
    ]
    iw = W - PAD_L - PAD_R
    ih = H - PAD_T - PAD_B
    vals = [v for _, v, _ in series]
    lo, hi = min(vals + [0.0]), max(vals + [0.0])
    # pad the top a little so the tallest bar's label has headroom
    hi = hi + 0.08 * ((hi - lo) or 1.0)
    rng = (hi - lo) or 1.0

    def Y(v):
        return PAD_T + ih * (1 - (v - lo) / rng)

    y0 = Y(0.0)
    body = [_title("Walk-forward R2  -  volatility model vs baselines")]
    for f in (0, 0.25, 0.5, 0.75, 1):
        yy = PAD_T + ih * f
        body.append(
            f"<line x1='{PAD_L}' y1='{yy:.1f}' x2='{W-PAD_R}' y2='{yy:.1f}' "
            f"stroke='{GRID}' stroke-width='1'/>"
        )
        val = hi - (hi - lo) * f
        body.append(_txt(PAD_L - 6, yy + 3, f"{val:.2f}", size=10, anchor="end"))
    body.append(
        f"<line x1='{PAD_L}' y1='{y0:.1f}' x2='{W-PAD_R}' y2='{y0:.1f}' "
        f"stroke='{AXIS}' stroke-width='1'/>"
    )
    slot = iw / len(series)
    bw = slot * 0.5
    for i, (lab, v, color) in enumerate(series):
        cx = PAD_L + slot * (i + 0.5)
        bx = cx - bw / 2
        yv = Y(v)
        top = min(yv, y0)
        hgt = abs(yv - y0)
        body.append(
            f"<rect x='{bx:.1f}' y='{top:.1f}' width='{bw:.1f}' "
            f"height='{hgt:.1f}' fill='{color}' opacity='0.9'/>"
        )
        vlab_y = (top - 5) if v >= 0 else (top + hgt + 13)
        body.append(_txt(cx, vlab_y, f"{v:.3f}", size=11, fill=INK, anchor="middle", weight="600"))
        # wrap label onto axis
        for j, part in enumerate(lab.split(" ")):
            body.append(_txt(cx, H - 26 + j * 12, part, size=10, anchor="middle"))
    return render("".join(body))


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def _write(path: str, svg: str) -> None:
    with open(path, "w") as fh:
        fh.write(svg)
    print(f"wrote {path} ({len(svg)} bytes)")


def _load_json(path: str):
    if not os.path.exists(path):
        print(f"WARN: missing {path}")
        return None
    with open(path) as fh:
        return json.load(fh)


def main() -> None:
    os.makedirs(RESULTS, exist_ok=True)
    setups_path = os.path.join(RESULTS, "setups.csv")
    wf_path = os.path.join(RESULTS, "walkforward.json")
    vol_path = os.path.join(RESULTS, "volatility.json")

    # 1 & 2 depend on setups.csv
    if os.path.exists(setups_path):
        df = pd.read_csv(setups_path)
        _write(os.path.join(RESULTS, "equity_curve.svg"), equity_curve_svg(df))
        _write(os.path.join(RESULTS, "calibration.svg"), calibration_svg(df))
    else:
        print(f"WARN: missing {setups_path}; skipping equity_curve + calibration")

    # 3 depends on walkforward.json
    wf = _load_json(wf_path)
    if wf is not None:
        _write(os.path.join(RESULTS, "yearly_R.svg"), yearly_R_svg(wf))

    # 4 depends on volatility.json
    vol = _load_json(vol_path)
    if vol is not None:
        _write(os.path.join(RESULTS, "volatility_r2.svg"), volatility_r2_svg(vol))


if __name__ == "__main__":
    main()
