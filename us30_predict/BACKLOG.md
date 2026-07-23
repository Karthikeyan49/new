# US30 Analyst — Continuous Work Backlog

This is the queue that feeds the two scheduled autonomous sessions. Each session
runs a loop: spawn **2 agents in parallel** on the next unstarted items, integrate
+ commit + push their work, mark the items done, then spawn the next two — keeping
both agents busy for the whole 5-hour window. Real deliverables only; if the queue
empties, deepen quality (more data span, more robustness) — never fabricate results.

Status keys: [ ] todo · [~] in progress · [x] done

## Priority queue

- [ ] **1. Full-dataset replay.** Run `src/run_agent.py` on the ENTIRE downloaded
  1-min history with dense sampling (step 15). Save `results/scorecard_full.json`.
- [ ] **2. Walk-forward by period & regime.** Split by year/quarter and by
  vol_regime/session; report per-slice hit-rate, PF, avg R. Save
  `results/walkforward.json`. Shows whether any edge is stable or noise.
- [ ] **3. Volatility & range model (the predictable target).** Train LightGBM to
  predict next-60-min realized volatility / range from past features; walk-forward
  R²/MAE vs a naive "last vol" baseline. Save `results/volatility.json`. This is
  where genuine accuracy should appear.
- [ ] **4. Meta-labeling filter.** Train a classifier on the analyst's setup
  features -> P(win); walk-forward; measure if filtering by it lifts confident
  hit-rate / PF. Save `results/meta_label.json`. No leakage (purged splits).
- [ ] **5. Statistical significance.** Permutation / bootstrap test on the
  analyst's R distribution vs random-entry; report p-value and confidence
  interval. Save `results/significance.json`. Reality check on any apparent edge.
- [ ] **6. Regime-conditional analyst tuning.** Measure analyst performance by
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
- (sessions append one line per completed item here)
