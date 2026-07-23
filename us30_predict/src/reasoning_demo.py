"""
HUMAN-LIKE REASONING demo (US30 backlog item #7).

Showcases the analyst's human-style, natural-language reasoning on real US30
market snapshots — the "thinks like a human analyst" output. For a handful of
decision points spread across the full multi-year 1-minute history, it renders
the perceive -> reason chain in words:

    perception.build_snapshot(...)  ->  what the analyst SEES (multi-TF chart read)
    analyst.Analyst().analyze(...)  ->  what the analyst DECIDES (thesis + call)

Both traded calls ("here's my thesis") and abstentions ("no clean setup, stand
aside") are included, because standing aside is itself a professional decision.

Backend: the deterministic HEURISTIC reasoning engine (no ANTHROPIC_API_KEY
present). Its `thesis` text IS the human-like reasoning shown here; the analyst
module is LLM-pluggable — set the key and the same pipeline reasons via an LLM.

    python reasoning_demo.py
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

from schema import load_m1
from perception import build_snapshot
from analyst import Analyst

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data", "US30_M1.csv")
OUT = os.path.join(HERE, "..", "results", "llm_reasoning_samples.md")

WINDOW = 4000        # bars of history perception sees per decision (matches make_setups.py)
N_SAMPLES = 20       # target number of showcased samples
N_CANDIDATES = 64    # oversample so we can curate a mix of trades and abstains


def candidate_indices(n: int) -> list[int]:
    """Decision indices spread across the whole history (leaving warmup + horizon)."""
    lo = WINDOW
    hi = n - 61                      # leave room after the decision
    if hi <= lo:
        raise ValueError("not enough bars for the demo window")
    return sorted(set(int(x) for x in np.linspace(lo, hi, N_CANDIDATES)))


def curate(samples: list[dict], want: int) -> list[dict]:
    """Pick ~`want` samples, chronologically spread, keeping BOTH traded calls
    and abstentions represented so the demo shows thesis and stand-aside."""
    trades = [s for s in samples if s["call"].direction != "flat"]
    abstains = [s for s in samples if s["call"].direction == "flat"]

    # aim for a roughly even split, but adapt to what the market actually offered
    want_tr = min(len(trades), max(1, want // 2))
    want_ab = min(len(abstains), want - want_tr)
    want_tr = min(len(trades), want - want_ab)   # backfill if one side is short

    def spread(items, k):
        if k <= 0 or not items:
            return []
        if k >= len(items):
            return items
        picks = np.linspace(0, len(items) - 1, k)
        return [items[int(round(p))] for p in picks]

    chosen = spread(trades, want_tr) + spread(abstains, want_ab)
    chosen.sort(key=lambda s: s["index"])
    return chosen


def render(samples: list[dict], backend: str, model: str, total_bars: int,
           span: tuple[str, str]) -> str:
    n_tr = sum(1 for s in samples if s["call"].direction != "flat")
    n_ab = len(samples) - n_tr

    L = []
    L.append("# US30 Analyst — Human-Like Reasoning Samples")
    L.append("")
    L.append("This is the **human-like reasoning** of the US30 analyst over real "
             "multi-timeframe market state. Each sample is one decision point:")
    L.append("")
    L.append("1. **What the analyst sees** — a causal multi-timeframe read of the "
             "chart (`MarketSnapshot`), built only from bars at or before the "
             "decision time (no look-ahead): 5m/15m/1h/4h/1D structure, liquidity "
             "pools, a recent sweep, volatility regime, premium/discount location, "
             "session/killzone timing and momentum.")
    L.append("2. **What the analyst decides** — a discretionary call reasoned "
             "top-down the way a disciplined SMC/ICT analyst would: direction, a "
             "0-10 confidence, and a plain-English **thesis**. When timeframes "
             "conflict, price sits mid-range, or there is no fresh liquidity event, "
             "the analyst **abstains** (flat) — standing aside is a valid, "
             "professional decision and the majority answer.")
    L.append("")
    L.append(f"Backend: **{backend}** reasoning engine (model slot `{model}`). "
             "No `ANTHROPIC_API_KEY` is present, so the deterministic heuristic "
             "engine produces the thesis text below; the pipeline is "
             "**LLM-pluggable** — add the key and the identical perceive->reason "
             "chain runs through an LLM analyst instead.")
    L.append("")
    L.append(f"Data: {total_bars:,} 1-minute US30 bars spanning `{span[0]}` -> "
             f"`{span[1]}`. Perception runs on a rolling {WINDOW}-bar window per "
             "decision. Samples below are spread across the full history.")
    L.append("")
    L.append(f"**{len(samples)} samples shown: {n_tr} traded calls, {n_ab} "
             "abstentions.**")
    L.append("")
    L.append("---")
    L.append("")

    for k, s in enumerate(samples, 1):
        snap = s["snapshot"]
        call = s["call"]
        tag = call.direction.upper() if call.direction != "flat" else "ABSTAIN"
        L.append(f"## Sample {k} — {snap.ts}  ·  {tag}")
        L.append("")
        L.append("**What the analyst sees** (multi-timeframe read):")
        L.append("")
        L.append("```")
        L.append(snap.to_prompt())
        L.append("```")
        L.append("")
        L.append("**What the analyst decides:**")
        L.append("")
        L.append(f"- **Direction:** {call.direction}")
        L.append(f"- **Confidence:** {call.confidence}/10")
        if call.direction != "flat":
            L.append(f"- **Entry / Stop / Target:** {call.entry:.1f} / "
                     f"{call.stop:.1f} / {call.target:.1f}")
            L.append(f"- **Horizon:** {call.horizon_min} min")
        L.append(f"- **Thesis (reasoning):** {call.thesis}")
        L.append("")
        L.append("---")
        L.append("")

    return "\n".join(L)


def main():
    print(f"loading {DATA} ...", flush=True)
    df = load_m1(DATA)
    n = len(df)
    span = (str(df["timestamp"].iloc[0]), str(df["timestamp"].iloc[-1]))
    print(f"loaded {n:,} bars  {span[0]} -> {span[1]}", flush=True)

    analyst = Analyst()
    print(f"analyst backend: {analyst.backend}  (model={analyst.model})", flush=True)

    idx = candidate_indices(n)
    print(f"building {len(idx)} candidate snapshots (window={WINDOW}) ...", flush=True)

    samples = []
    for k, i in enumerate(idx):
        win = df.iloc[i - WINDOW:i + 1].reset_index(drop=True)
        snap = build_snapshot(win, len(win) - 1)
        call = analyst.analyze(snap, memory_context="")
        samples.append({"index": i, "snapshot": snap, "call": call})
        if k % 10 == 0:
            print(f"  {k}/{len(idx)}", flush=True)

    chosen = curate(samples, N_SAMPLES)
    n_tr = sum(1 for s in chosen if s["call"].direction != "flat")
    n_ab = len(chosen) - n_tr

    md = render(chosen, analyst.backend, analyst.model, n, span)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        f.write(md)

    print(f"DONE wrote {len(chosen)} samples -> {OUT}")
    print(f"      trades={n_tr}  abstains={n_ab}")


if __name__ == "__main__":
    main()
