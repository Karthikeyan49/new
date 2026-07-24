"""
Institutional / professional strategy backtest on US30 (2016-2026, 1-min).

Retail tries to predict intraday direction (proven random here). Professionals
instead harvest *structural* edges. This backtests the ones testable on our data:

  1. Buy & hold            — the equity risk premium (benchmark)
  2. Overnight-only        — hold close(16:00 ET) -> next open(09:30 ET). The
                             documented 'night effect': indices earn their return
                             overnight, not intraday.
  3. Intraday-only         — hold open -> close (the other half).
  4. Trend-filtered long   — long only when close > 200-day MA (CTA trend filter).
  5. Overnight + trend     — overnight capture, gated by the trend filter.
  6. Vol-targeted long     — buy&hold scaled to a constant volatility target.

All net of a round-trip spread cost, reported with CAGR, annualised Sharpe, and
max drawdown. Daily frequency, built from the 1-minute session anchors.
"""
from __future__ import annotations
import json, os
import numpy as np
import pandas as pd

from schema import load_m1

HERE = os.path.dirname(__file__)
RES = os.path.join(HERE, "..", "results")
COST_PTS = 2.0            # round-trip spread cost, index points
VOL_TARGET = 0.10         # 10% annualised for the vol-target strategy


def session_frame(df):
    """Daily open(09:30 ET) & close(16:00 ET) prices from 1-min bars."""
    et = df["timestamp"].dt.tz_convert("America/New_York")
    d = pd.DataFrame({"date": et.dt.date, "hm": et.dt.hour * 60 + et.dt.minute,
                      "px": df["close"].to_numpy(float)})
    opens = d[(d.hm >= 570) & (d.hm <= 576)].groupby("date").px.first()   # ~09:30
    closes = d[(d.hm >= 955) & (d.hm <= 961)].groupby("date").px.last()   # ~16:00
    s = pd.concat([opens.rename("open"), closes.rename("close")], axis=1).dropna()
    s = s.sort_index()
    s["prev_close"] = s["close"].shift(1)
    s = s.dropna()
    s["overnight"] = s["open"] / s["prev_close"] - 1.0     # close(d-1)->open(d)
    s["intraday"] = s["close"] / s["open"] - 1.0           # open(d)->close(d)
    s["c2c"] = s["close"] / s["prev_close"] - 1.0          # close(d-1)->close(d)
    s["cost"] = COST_PTS / s["close"]                      # per round-trip, in return
    return s


def metrics(daily_ret, n_trades, label):
    r = np.asarray(daily_ret, float)
    eq = np.cumprod(1 + r)
    peak = np.maximum.accumulate(eq)
    max_dd = float(((peak - eq) / peak).max()) if len(eq) else 0.0
    yrs = len(r) / 252.0
    cagr = float(eq[-1] ** (1 / yrs) - 1) if len(eq) and yrs > 0 else 0.0
    sharpe = float(r.mean() / (r.std() + 1e-12) * np.sqrt(252)) if len(r) else 0.0
    return {"strategy": label, "total_return_pct": round((eq[-1] - 1) * 100, 1) if len(eq) else 0.0,
            "CAGR_pct": round(cagr * 100, 2), "sharpe": round(sharpe, 2),
            "max_drawdown_pct": round(max_dd * 100, 1), "n_trades": int(n_trades)}, eq


def main():
    df = load_m1(os.path.join(HERE, "..", "data", "US30_M1.csv"))
    s = session_frame(df)
    c = s["cost"].to_numpy()
    n = len(s)
    ma200 = s["close"].rolling(200).mean()
    up = (s["close"] > ma200).to_numpy()            # trend filter (long-only regime)
    up_prev = np.concatenate([[False], up[:-1]])    # decide with yesterday's close (causal)

    strategies = {}
    curves = {}

    # 1. buy & hold (one trade)
    m, eq = metrics(s["c2c"].to_numpy(), 1, "buy_and_hold"); strategies["buy_hold"] = m; curves["Buy & Hold"] = eq
    # 2. overnight-only (trade every day)
    m, eq = metrics(s["overnight"].to_numpy() - c, n, "overnight_only"); strategies["overnight"] = m; curves["Overnight only"] = eq
    # 3. intraday-only
    m, eq = metrics(s["intraday"].to_numpy() - c, n, "intraday_only"); strategies["intraday"] = m; curves["Intraday only"] = eq
    # 4. trend-filtered long (c2c when in uptrend; cost on regime switches)
    switch = np.abs(np.diff(np.concatenate([[0], up_prev.astype(int)]))) > 0
    tf_ret = np.where(up_prev, s["c2c"].to_numpy(), 0.0) - switch * c
    m, eq = metrics(tf_ret, int(switch.sum()), "trend_filtered_long"); strategies["trend_long"] = m; curves["Trend-filtered long"] = eq
    # 5. overnight + trend filter
    on_tf = np.where(up_prev, s["overnight"].to_numpy() - c, 0.0)
    m, eq = metrics(on_tf, int(up_prev.sum()), "overnight_plus_trend"); strategies["overnight_trend"] = m; curves["Overnight + trend"] = eq
    # 6. vol-targeted long (scale c2c to constant vol using trailing 20d realised vol)
    rv = s["c2c"].rolling(20).std().to_numpy()
    lev = np.clip(VOL_TARGET / (rv * np.sqrt(252) + 1e-9), 0, 3.0)
    lev_prev = np.concatenate([[0], lev[:-1]])
    vt_ret = lev_prev * s["c2c"].to_numpy() - np.abs(np.diff(np.concatenate([[0], lev_prev]))) * c
    m, eq = metrics(np.nan_to_num(vt_ret), int((np.abs(np.diff(np.concatenate([[0], lev_prev]))) > 0.05).sum()), "vol_targeted_long")
    strategies["vol_target"] = m; curves["Vol-targeted long"] = eq

    # 7. INTELLIGENT combo: long only in uptrend, sized to constant vol
    combo_lev = np.where(up_prev, lev_prev, 0.0)
    combo_ret = combo_lev * s["c2c"].to_numpy() - np.abs(np.diff(np.concatenate([[0], combo_lev]))) * c
    m, eq = metrics(np.nan_to_num(combo_ret),
                    int((np.abs(np.diff(np.concatenate([[0], combo_lev]))) > 0.05).sum()),
                    "intelligent_trend_x_voltarget")
    strategies["intelligent"] = m; curves["Intelligent (trend x vol-target)"] = eq

    report = {
        "data_span": f"{s.index.min()} -> {s.index.max()} ({n} trading days)",
        "cost_per_trade_pts": COST_PTS,
        "annual_overnight_vs_intraday": {
            "overnight_total_%": strategies["overnight"]["total_return_pct"],
            "intraday_total_%": strategies["intraday"]["total_return_pct"],
            "insight": "if overnight >> intraday, the index earns its return overnight (the night effect)",
        },
        "strategies": strategies,
        "verdict": "",
    }
    # rank by Sharpe
    best = max(strategies.values(), key=lambda x: x["sharpe"])
    report["verdict"] = (f"Best risk-adjusted: {best['strategy']} "
                         f"(Sharpe {best['sharpe']}, CAGR {best['CAGR_pct']}%, maxDD {best['max_drawdown_pct']}%). "
                         f"vs buy&hold Sharpe {strategies['buy_hold']['sharpe']}, "
                         f"maxDD {strategies['buy_hold']['max_drawdown_pct']}%.")

    with open(os.path.join(RES, "institutional.json"), "w") as fh:
        json.dump(report, fh, indent=2, default=str)
    _equity_svg(curves, os.path.join(RES, "institutional_equity.svg"))

    print(f"US30 institutional backtest  {report['data_span']}\n")
    print(f"{'strategy':22s} {'return%':>9} {'CAGR%':>7} {'Sharpe':>7} {'maxDD%':>7} {'trades':>7}")
    for m in strategies.values():
        print(f"{m['strategy']:22s} {m['total_return_pct']:>9} {m['CAGR_pct']:>7} "
              f"{m['sharpe']:>7} {m['max_drawdown_pct']:>7} {m['n_trades']:>7}")
    print("\n" + report["verdict"])


def _equity_svg(curves, path, W=820, H=380, pad=54):
    allv = np.concatenate([c for c in curves.values()])
    lo, hi = float(np.nanmin(allv)), float(np.nanmax(allv))
    rng = (hi - lo) or 1.0
    cols = ["#2166ac", "#1a9850", "#d73027", "#762a83", "#e08214", "#0097a7"]
    N = max(len(c) for c in curves.values())
    def X(i, n): return pad + (W - 2 * pad) * i / (n - 1)
    def Y(v): return pad + (H - 2 * pad) * (1 - (v - lo) / rng)
    lines, legend = [], []
    for k, (name, c) in enumerate(curves.items()):
        pts = " ".join(f"{X(i,len(c)):.1f},{Y(v):.1f}" for i, v in enumerate(c))
        col = cols[k % len(cols)]
        lines.append(f"<polyline fill='none' stroke='{col}' stroke-width='1.8' points='{pts}'/>")
        ly = pad + 14 * k
        legend.append(f"<rect x='{W-pad-150}' y='{ly-9}' width='11' height='11' fill='{col}'/>"
                      f"<text x='{W-pad-134}' y='{ly}' font-size='11' fill='#333'>{name} ({c[-1]:.2f}x)</text>")
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' width='{W}' height='{H}' font-family='sans-serif'>"
           f"<rect width='{W}' height='{H}' fill='white'/>"
           f"<line x1='{pad}' y1='{Y(1):.1f}' x2='{W-pad}' y2='{Y(1):.1f}' stroke='#bbb' stroke-dasharray='4 4'/>"
           f"<text x='{pad}' y='26' font-size='15' font-weight='600'>US30 institutional strategies — growth of 1 (2016-2026, cost-adj)</text>"
           + "".join(lines) + "".join(legend) + "</svg>")
    open(path, "w").write(svg)


if __name__ == "__main__":
    main()
