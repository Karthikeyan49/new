# Trading System — active trading, done right

Evidence-based swing/trend trading research for Indian indices (Nifty 50, Bank
Nifty), built after proving that intraday direction prediction does not work.

- `src/trend_system.py` — trend-following backtest (200-SMA regime + 50-day
  breakout entry + 3xATR Chandelier trailing stop), 1%-risk or full-invest
  sizing, realistic costs, no look-ahead. Reports CAGR/Sharpe/maxDD/expectancy
  vs buy & hold.
- `data/` — 19 years daily OHLC (2007-2026), Nifty 50 & Bank Nifty (Yahoo).
- `results/` — per-instrument stats + trade lists.
- **`TRADING_PLAN.md`** — the honest, actionable plan and the evidence behind it.

## Headline finding
On Indian indices 2007-2026, buy & hold (Nifty 10.7% CAGR / Sharpe 0.62) beats
every active trend variant on return and Sharpe; the systems only reduce
drawdown. Trade actively only with a proven edge, strict 1% risk, and realistic
expectations — see TRADING_PLAN.md.

```bash
python3 src/trend_system.py --data data/NIFTY50_D1.csv --name NIFTY50 --mode risk
```
_Educational, not financial advice._
