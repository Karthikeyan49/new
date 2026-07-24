# US30 Human-Like Analyst — an honest AI market-reasoning system

A from-scratch system that reads the US30 (Dow Jones) market the way a human
discretionary analyst does — perceiving multi-timeframe structure, reasoning in
natural language, deciding with confidence and invalidation, abstaining when
there's no edge, and learning from a reflective journal — then **replays itself
over 10.6 years of 1-minute data and scores its own calls honestly.**

> **Bottom line, proven with data:** the analyst reasons like a competent human
> and abstains ~60% of the time — but its **directional calls have no exploitable
> edge on US30** (walk-forward cost-adjusted **−78.6R**, positive in only 2 of 11
> years; meta-label OOS AUC **0.500**; on the full 553-trade series the loss is
> statistically significant, **p=0.001** — a real anti-edge). What *is*
> genuinely predictable is **volatility** (walk-forward OOS **R² 0.54**). This is
> the honest fingerprint of a near-efficient market: *direction ≈ random, size
> ≈ forecastable.*

---

## Why this design (not "normal ML")

A standard model predicts "next candle up or down?" — a coin flip on a liquid
index. This system instead **thinks like an analyst** and is built to tell the
truth about its own edge:

- **Perceive → Reason → Replay → Reflect**, not features → label.
- It **abstains** ("no clean setup, stand aside") the majority of the time.
- It predicts what markets actually leak (**volatility**), and only *bets* on
  direction when its reasoning finds conviction — which we then measure honestly.
- Every result is **walk-forward, cost-adjusted, and compared to dumb baselines**
  (random / predict-last / buy-hold). No look-ahead, no curve-fit.

## The pipeline

```
dukascopy.py / download.py   fetch + decode Dukascopy ticks -> 1-min OHLCV
schema.py                    MarketSnapshot + AnalystCall contract
perception.py   PERCEIVE     1-min -> multi-timeframe snapshot (structure,
                             liquidity, volatility, regime, session)  [causal]
analyst.py      REASON       snapshot -> thesis + confidence + invalidation,
                             abstains when unclear (LLM-pluggable; heuristic
                             reasoning engine is the runnable default)
replay.py       REPLAY       score each call forward with realistic spread cost
journal.py      REFLECT      memory of past calls/outcomes fed back to the analyst
metrics.py                   honest scorecard vs baselines
run_agent.py                 wire it all together
```
**Analyses** (all on the same shared labeled dataset `results/setups.csv`):
`volatility_model.py` (#3) · `walkforward.py` (#2) · `meta_label.py` (#4) ·
`significance.py` (#5) · `regime_tune.py` (#6) · `visualize.py` (#8) ·
`reasoning_demo.py` (#7).

**No look-ahead:** swing structure is only released N bars after it forms;
perception slices `df[:i+1]`; only trade *management* walks forward. Walk-forward
splits are strictly time-ordered.

## Data

- **Instrument:** US30 / Dow Jones (Dukascopy `USA30IDXUSD`), mid price.
- **3,269,771 one-minute bars · 2016-01-04 → 2026-07-22 · 10.6 years** (214 MB).
- This is the *maximum* free 1-minute history available (Dukascopy's Dow is empty
  before ~2016; 20-year 1-min index data is a paid product). Every higher
  timeframe is resampled from this one file. Data is gitignored (large,
  regenerable via `download.py`).

## How to run

```bash
pip install pandas numpy scikit-learn lightgbm
python3 src/download.py --start 2016-01-01 --end 2026-07-22 --out data/US30_M1.csv --minutes 60
python3 src/make_setups.py          # build the shared labeled dataset
python3 src/run_agent.py            # full perceive->reason->replay + scorecard
python3 src/walkforward.py ; python3 src/meta_label.py ; python3 src/regime_tune.py
python3 src/volatility_model.py ; python3 src/significance.py ; python3 src/visualize.py
python3 src/reasoning_demo.py       # human-like reasoning transcripts
```

---

## Honest results

**Direction (the analyst's trades)** — 1,500 decisions, **553 traded** (63% abstain),
full 10.6-year data:

| Test | Result | Verdict |
|---|---|---|
| Overall economics | avg **−0.14R**, PF **0.67**, cost-adj **−78.6R** | loses after costs |
| Walk-forward by year | positive in **2 / 11** years only | no stable edge |
| Calibration | win-rate flat across confidence buckets, below break-even | confidence ≠ skill |
| Meta-labeling filter | OOS **AUC 0.500** | nothing learnable to filter on |
| Regime adaptation | OOS baseline −0.12R vs adapted −0.19R | doesn't generalize |
| Significance (n=553) | mean R −0.14, 95% CI [−0.23, −0.05], **p=0.001** | significantly *losing* after costs |

**Reality check:** over the same 10.6 years, **buy-and-hold returned +202%** —
passively holding the index vastly outperformed the analyst's active trading
(−78.6R). Definitive scorecard: `results/final_scorecard.json`.

**Volatility (the predictable target)** — walk-forward, 6 folds, 24k OOS samples:

| Model | OOS R² |
|---|--:|
| **LightGBM (ours)** | **0.537** |
| persistence baseline | 0.083 |
| trailing-mean baseline | −0.035 |

Charts in `results/`: `equity_curve.svg`, `calibration.svg`, `yearly_R.svg`,
`volatility_r2.svg`. Human-like reasoning transcripts in
`results/llm_reasoning_samples.md`.

## What this proves

1. **A more "human-like" or "intelligent" system does not beat a near-random
   market.** Better reasoning buys better *analysis and adaptivity*, not
   directional *prediction* — because the signal isn't there, not because the
   model was too simple.
2. **Volatility is genuinely forecastable** (R² 0.54) — the honest place where AI
   adds real value on US30.
3. The system's worth is that it **finds whatever edge exists and proves how
   small it is**, instead of hiding a curve-fit behind a confident narrative.

## Limitations
- No LLM API key in this environment, so the analyst runs its **heuristic**
  reasoning engine (LLM-pluggable — the interface and prompt are ready).
- Replay samples decision points (every ~30 min) rather than every bar, for
  tractability on 3.3M bars.
- Costs modeled as a fixed spread; real slippage/commission would be worse.
- **Research tool, not trading advice.** The honest conclusion is that US30
  intraday direction is not a tradeable edge here.
