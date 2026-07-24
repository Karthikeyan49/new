# Active Trading, Done Right — an evidence-based plan

You chose to trade actively. This plan is built on what the **backtests actually
showed** on 19 years of Nifty & Bank Nifty (2007–2026), not on what sells courses.
The honest findings shape every rule below.

---

## 1. What the evidence says (read this first)

**Backtest — trend systems vs buy & hold (Nifty 50, 2007–2026, cost-adjusted):**

| Approach | CAGR | Sharpe | Max DD | In-market |
|---|--:|--:|--:|--:|
| **Buy & hold** | **10.7%** | **0.62** | −45% | 100% |
| 200-day SMA timing | 6.1% | 0.52 | −26% | 72% |
| Breakout trend (fully invested) | 3.2% | 0.47 | −23% | 39% |
| Breakout trend (1% risk sizing) | 1.0% | 0.56 | −5% | 39% |

(Bank Nifty is the same shape: buy & hold 14.8% CAGR / 0.66 Sharpe beats every
active variant on return and Sharpe; the systems only reduce drawdown.)

**Three conclusions that must anchor your behaviour:**
1. **Intraday direction is unpredictable** — proven separately (US30: random-walk,
   variance-ratio z≈0; SEBI: 93% of F&O traders lose). *Do not day-trade the index.*
2. **On a single equity index, buy & hold is very hard to beat.** The upward drift
   is so strong that time out of the market costs more than it saves. Active
   trend-timing here mainly **reduces drawdown**, at a large cost to returns.
3. **The trade-level edge (PF ~2, +0.4R) is real but too infrequent** (≈49 trades
   in 19 years, in-market ~39%) to compound past buy & hold.

---

## 2. So what should you actually do?

Pick the honest role for active trading:

### Option A — Hold the index, trade only to control risk (recommended for indices)
- **Core:** stay invested in Nifty (index fund / ETF / futures).
- **Overlay (optional):** move to cash when Nifty closes below its 200-day average;
  re-enter when it closes back above. You give up ~4% CAGR but cut max drawdown
  from −45% to ~−26%. This is a *risk-tolerance* choice, not a return edge — only
  do it if you genuinely can't hold through a −45% fall.

### Option B — If you want trend-following to *add return*, trade the right vehicle
Trend-following works on **diversified, low-drift markets (FX majors, commodities,
a basket of futures)** — NOT a single long-biased equity index. If you love this
style, apply it across many uncorrelated markets, not just Nifty. That's the real
CTA/managed-futures edge; a single index is the wrong tool.

### Option C — Swing-trade individual stocks (higher skill, higher variance)
Stock dispersion/momentum can beat the index, but it needs real edge, discipline,
and far more work. Only after you've proven it in backtest + paper trading.

---

## 3. Hard rules (whatever you trade)

- **Timeframe: daily/swing, never intraday scalping.** The edge that exists lives
  on higher timeframes; intraday is noise + costs.
- **Risk ≤ 1% of capital per trade.** Position size = (1% × equity) ÷ (entry − stop).
- **Every trade has a pre-defined stop** (e.g. 3×ATR, or below structure) *before* you enter.
- **Max 3–5% portfolio heat** (sum of open risk) at any time.
- **Trade with the higher-timeframe trend** (long only above the 200-day average).
- **Let winners run, cut losers fast** — the +1.7R avg win vs −0.7R avg loss is the
  whole edge; don't cap winners or widen losers.
- **Costs are real** — model ~0.1% round-trip; avoid high-frequency churn.

## 4. Process rules (this is what separates the 7% from the 93%)

1. **Backtest first.** Any idea gets tested on ≥10 years / ≥100 trades with costs and
   walk-forward *before* real money. Use the tools in this repo (`src/trend_system.py`).
2. **Paper-trade or trade minimum size** for 3–6 months to prove *you* can execute it.
3. **Journal every trade** (thesis, entry, stop, exit, R, mistake). Review monthly.
4. **Fixed daily/weekly loss limit** — stop after −3% in a day / −6% in a week.
5. **One system, followed mechanically.** No improvising, no revenge trades.
6. **Expect drawdowns and long flat periods.** Even a good system spends most of its
   time going sideways.

## 5. Realistic expectations
- A *good* retail outcome is **beating buy & hold on risk-adjusted terms** (lower
  drawdown for similar return), not 10×-ing your account.
- Most people who "trade actively" underperform an index fund. The backtests above
  show why. Your goal is to be the disciplined exception — or to accept that holding
  the index is a perfectly good answer.

---

## 6. How to use this repo
```bash
# backtest the trend system on any daily OHLC file
python3 src/trend_system.py --data data/NIFTY50_D1.csv --name NIFTY50 --mode risk
python3 src/trend_system.py --data data/NIFTY50_D1.csv --name NIFTY50_full --mode full
```
Outputs full stats (CAGR, Sharpe, max DD, win rate, expectancy, profit factor) vs
buy & hold into `results/`. Test every idea here before you risk a rupee.

_Educational, not financial advice. The most honest takeaway: for Indian indices,
holding beats active trading on return — trade actively only with a proven edge,
strict risk control, and realistic expectations._
