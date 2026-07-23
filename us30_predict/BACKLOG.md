# US30 Analyst — Continuous Work Backlog

This is the queue that feeds the two scheduled autonomous sessions. Each session
runs a loop: spawn **2 agents in parallel** on the next unstarted items, integrate
+ commit + push their work, mark the items done, then spawn the next two — keeping
both agents busy for the whole 5-hour window. Real deliverables only; if the queue
empties, deepen quality (more data span, more robustness) — never fabricate results.

Status keys: [ ] todo · [~] in progress · [x] done

## Priority queue

- [x] **1. Full-dataset replay.** Run `src/run_agent.py` on the ENTIRE downloaded
  1-min history with dense sampling (step 15). Save `results/scorecard_full.json`.
- [x] **2. Walk-forward by period & regime.** Split by year/quarter and by
  vol_regime/session; report per-slice hit-rate, PF, avg R. Save
  `results/walkforward.json`. Shows whether any edge is stable or noise.
- [x] **3. Volatility & range model (the predictable target).** Train LightGBM to
  predict next-60-min realized volatility / range from past features; walk-forward
  R²/MAE vs a naive "last vol" baseline. Save `results/volatility.json`. This is
  where genuine accuracy should appear.
- [ ] **4. Meta-labeling filter.** Train a classifier on the analyst's setup
  features -> P(win); walk-forward; measure if filtering by it lifts confident
  hit-rate / PF. Save `results/meta_label.json`. No leakage (purged splits).
- [x] **5. Statistical significance.** Permutation / bootstrap test on the
  analyst's R distribution vs random-entry; report p-value and confidence
  interval. Save `results/significance.json`. Reality check on any apparent edge.
- [~] **6. Regime-conditional analyst tuning.** Measure analyst performance by
  session/regime; adapt confidence thresholds; re-evaluate. Document what adapts.
- [ ] **7. LLM-backend reasoning demo.** On ~20 sampled snapshots, produce full
  natural-language analyst reasoning (thesis/confidence/invalidation) and save
  transcripts to `results/llm_reasoning_samples.md` — shows the human-like output
  the pluggable LLM backend produces.
- [ ] **8. Visualizations.** Dependency-free SVGs: equity curve, calibration plot,
  per-regime hit-rate bars. Save under `results/`.
- [ ] **9. Final report / README.** `us30_predict/README.md`: architecture (the
  perceive→reason→replay→reflect loop), how it thinks like a human analyst, the
  memory loop, the HONEST results (what's predictable = volatility; what isn't =
  direction), data span, and limitations.

## Log
- #2 walkforward.py — 1500 snapshots/553 trades sliced by year/quarter/session/regime. Overall hit 59.9% but avg -0.14R, PF 0.67, cost-adjusted -78.6R; positive in only 2/11 years -> NO stable edge (noise). -> results/walkforward.json
- #1 full replay — 800 decisions / 313 trades on 603k-bar span (Oct 2024-Jul 2026): hit-rate 51%, PF 0.66, cost-adjusted -36R. Direction ~random, loses after costs. -> results/scorecard_full.json
- #3 volatility model — LightGBM, walk-forward OOS R2=0.54 (vs 0.08 persistence baseline), 6 folds / 24k OOS samples. Volatility IS predictable. -> results/volatility.json
- #5 significance.py — bootstrap + sign-flip permutation test; correctly distinguishes edge vs noise; real scorecard (n=43) mean R -0.35, p=0.134 -> NOT significant (no proven direction edge).
- (sessions append one line per completed item here)
