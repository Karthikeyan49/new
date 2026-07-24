"""
Trend-following swing system — "active trading, done right".

The ONE style with durable published evidence (managed futures / CTA trend), built
with strict risk control and NO look-ahead:

  Regime filter : trade long only when close > 200-day SMA (ride the equity drift)
  Entry         : breakout of the 50-day high  -> signal on close, FILL next open
  Exit          : 3x ATR Chandelier trailing stop (ratchets up, lets winners run)
  Risk          : 1% of equity per trade; size = risk / (entry - stop); no leverage
  Costs         : round-trip cost applied on entry and exit

Long-only (shorting an index carries drift + borrow headwinds for retail). Runs on
any daily OHLC file (Nifty, Bank Nifty, US30...). Reports full stats vs buy & hold.
"""
from __future__ import annotations
import argparse, json, os
import numpy as np
import pandas as pd

HERE = os.path.dirname(__file__)


def load(path):
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df.sort_values("timestamp").reset_index(drop=True)


def atr(df, n=14):
    h, l, c = df.high, df.low, df.close.shift(1)
    tr = pd.concat([h - l, (h - c).abs(), (l - c).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def backtest(df, sma_n=200, breakout_n=50, atr_n=14, chand_mult=3.0,
             risk_pct=0.01, cost_pct=0.001, start_equity=100_000.0,
             size_mode="risk"):
    o, h, l, c = df.open.values, df.high.values, df.low.values, df.close.values
    sma = df.close.rolling(sma_n).mean().values
    donch = df.high.rolling(breakout_n).max().shift(1).values     # prior 50-day high
    a = atr(df, atr_n).values
    n = len(df)

    equity = start_equity
    eq_curve = [start_equity]
    daily_ret = []
    pos = 0.0            # shares held
    entry = stop = hh = 0.0
    trades = []
    in_pos = False

    for t in range(sma_n + 1, n - 1):
        # mark-to-market daily return of equity (close t-1 -> close t) while in position
        if in_pos:
            daily_ret.append(pos * (c[t] - c[t - 1]) / equity)
        else:
            daily_ret.append(0.0)

        if not in_pos:
            if c[t] > sma[t] and c[t] > donch[t]:           # breakout in uptrend
                entry = o[t + 1]                             # fill NEXT open (no look-ahead)
                stop = entry - chand_mult * a[t]
                risk_ps = entry - stop
                if risk_ps <= 0:
                    continue
                if size_mode == "full":                      # ride the trend near-fully
                    shares = 0.99 * equity / entry
                else:                                        # risk-defined sizing
                    shares = min((risk_pct * equity) / risk_ps, equity / entry)
                cost = shares * entry * cost_pct
                equity -= cost
                pos, hh, in_pos = shares, entry, True
                trades.append({"entry_date": str(df.timestamp[t + 1].date()),
                               "entry": round(entry, 2), "stop": round(stop, 2),
                               "shares": round(shares, 4)})
        else:
            hh = max(hh, c[t])
            stop = max(stop, hh - chand_mult * a[t])         # ratchet the trailing stop
            if c[t] < stop:                                  # exit signal -> fill next open
                px = o[t + 1]
                pnl = pos * (px - entry) - pos * px * cost_pct
                equity_before = equity + pos * (c[t] - entry) - pos * entry * cost_pct
                equity += pnl
                tr = trades[-1]
                tr.update(exit_date=str(df.timestamp[t + 1].date()), exit=round(px, 2),
                          pnl=round(pnl, 2),
                          R=round((px - entry) / (entry - tr["stop"]), 2))
                pos, in_pos = 0.0, False
        eq_curve.append(equity)

    return np.array(eq_curve), np.array(daily_ret), trades


def eq_at_entry(tr, s):  # placeholder (R computed from price geometry instead)
    return s


def stats(eq, dr, trades, df, label):
    yrs = len(dr) / 252.0
    cagr = (eq[-1] / eq[0]) ** (1 / yrs) - 1 if yrs > 0 else 0
    sharpe = dr.mean() / (dr.std() + 1e-12) * np.sqrt(252)
    peak = np.maximum.accumulate(eq)
    maxdd = ((peak - eq) / peak).max()
    closed = [t for t in trades if "pnl" in t]
    wins = [t for t in closed if t["pnl"] > 0]
    losses = [t for t in closed if t["pnl"] <= 0]
    exposure = float((dr != 0).mean())
    # buy & hold
    bh = df.close.values[200:]
    bh_ret = np.diff(bh) / bh[:-1]
    bh_cagr = (bh[-1] / bh[0]) ** (1 / (len(bh_ret) / 252)) - 1
    bh_peak = np.maximum.accumulate(bh)
    bh_dd = ((bh_peak - bh) / bh_peak).max()
    bh_sharpe = bh_ret.mean() / (bh_ret.std() + 1e-12) * np.sqrt(252)
    return {
        "instrument": label,
        "period": f"{df.timestamp.iloc[0].date()} -> {df.timestamp.iloc[-1].date()}",
        "trades": len(closed),
        "win_rate_pct": round(len(wins) / len(closed) * 100, 1) if closed else 0,
        "avg_win_R": round(np.mean([t["R"] for t in wins]), 2) if wins else 0,
        "avg_loss_R": round(np.mean([t["R"] for t in losses]), 2) if losses else 0,
        "expectancy_R": round(np.mean([t["R"] for t in closed]), 3) if closed else 0,
        "profit_factor": round(sum(t["pnl"] for t in wins) / abs(sum(t["pnl"] for t in losses)), 2) if losses else None,
        "exposure_pct": round(exposure * 100, 1),
        "strategy": {"CAGR_pct": round(cagr * 100, 2), "sharpe": round(sharpe, 2),
                     "max_drawdown_pct": round(maxdd * 100, 1),
                     "total_return_pct": round((eq[-1] / eq[0] - 1) * 100, 1)},
        "buy_hold": {"CAGR_pct": round(bh_cagr * 100, 2), "sharpe": round(bh_sharpe, 2),
                     "max_drawdown_pct": round(bh_dd * 100, 1),
                     "total_return_pct": round((bh[-1] / bh[0] - 1) * 100, 1)},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--cost", type=float, default=0.001)
    ap.add_argument("--mode", default="risk", choices=["risk", "full"])
    a = ap.parse_args()
    df = load(a.data)
    eq, dr, trades = backtest(df, cost_pct=a.cost, size_mode=a.mode)
    s = stats(eq, dr, trades, df, a.name)
    os.makedirs(os.path.join(HERE, "..", "results"), exist_ok=True)
    json.dump({"stats": s, "trades": trades},
              open(os.path.join(HERE, "..", "results", f"{a.name}_trend.json"), "w"),
              indent=2, default=str)
    print(json.dumps(s, indent=2, default=str))
    return s, eq, df


if __name__ == "__main__":
    main()
