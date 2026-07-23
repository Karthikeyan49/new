# SMC / ICT — the theory the engine encodes

Every detector in this project is coded from these definitions. They were
cross-checked across multiple sources (web references + how popular ICT/SMC
educators — ICT, TJR, Photon Trading, Casper SMC, Fractal Flow, and
"The Alchemist" / MSNR — actually trade the model). Where sources diverge, the
**most common convention** is used and the alternative is exposed as a `Params`
toggle.

---

## 1. Swing fractals  →  `structure.find_swings`
```
SwingHigh(i,N): high[i] > high[i-k] AND high[i] > high[i+k]  for all k in 1..N
SwingLow(i,N):  low[i]  < low[i-k]  AND low[i]  < low[i+k]   for all k in 1..N
```
Strict inequalities; wick extremes (not closes). Base `N=2` (Bill Williams
5-candle fractal). A pivot is **confirmed only N bars later** — encoded as
`Swing.confirm_idx = pivot_idx + N` so the backtest has no look-ahead. Two-tier:
`n_major=5` for HTF structure/liquidity, `n_internal=2` for the MSS.

## 2. Market structure / bias  →  `strategy` state machine
```
Bullish: HH + HL   (last swing high > prev, last swing low > prev)
Bearish: LH + LL
```
Trend flips when a **close** breaks the last major swing (break of the last
higher-low is the decisive event). Maintained incrementally per bar.

## 3. BOS vs CHoCH
Identical mechanic — a **candle close** beyond a swing point — distinguished by
direction relative to the current trend:
- **BOS** = close beyond a swing *with* the trend → continuation.
- **CHoCH** = first close beyond a swing *against* the trend → reversal / flip.

Close-based confirmation is the standard; a wick through that closes back is a
*sweep*, not a break (see §8). This distinction is why the sweep and the break
use different conditions in code.

## 4. Order block  →  `smc.order_block`
The **last opposing-close candle before the displacement leg** that breaks
structure. Bullish OB = last down-close candle before the up-move. Zone stored
both as full range `[low, high]` and body `[min(o,c), max(o,c)]`. Validity: it
must originate a move that breaks structure (an OB that causes no BOS/CHoCH is
not an OB) and ideally leaves an FVG ("no displacement, no order block").

## 5. Fair Value Gap  →  `smc.bullish_fvg` / `bearish_fvg`
3-candle imbalance (candles i-2, i-1, i):
```
Bullish FVG:  low[i]  > high[i-2]   → gap [high[i-2], low[i]]
Bearish FVG:  high[i] < low[i-2]    → gap [high[i], low[i-2]]
```
Entry = **50% of the gap (consequent encroachment / CE)**.

## 6. Displacement  →  `smc.is_displacement`
Objective impulse test:
```
body = |close-open|;  range = high-low
isDisplacement = (body >= 1.0*ATR(14)) OR (body/range >= 0.60)
```
plus the leg must leave an FVG. Captures the "violent move" ICT requires without
subjective judgement.

## 7. Liquidity & sweep  →  `smc.is_sweep_low` / `is_sweep_high`
Liquidity = clustered stops at prior swing highs (buy-side) / lows (sell-side),
equal highs/lows, PDH/PDL, session extremes. Sweep:
```
Bullish sweep of a low L:   low[i]  < L AND close[i] > L
Bearish sweep of a high L:  high[i] > L AND close[i] < L
```
Wick through **and close back** — the non-negotiable trigger of the model.

## 8. Premium / discount / equilibrium
```
EQ = (rangeHigh + rangeLow)/2   from the most recent major swing high & low
price > EQ → premium → sells only ;  price < EQ → discount → buys only
```

## 9. OTE (available as a refinement)
Fib retracement of the impulse leg, entry band **0.62 → 0.79** (sweet spot
0.705); SL beyond 0.79 / the origin swing. The default engine enters at the FVG
CE; OTE is the documented alternative POI.

## 10. Killzones (NY / ET, DST-aware)  →  `indicators.ny_hour`
London 02:00–05:00, NY-AM 07:00–11:00 (Silver Bullet 10:00–11:00). Converted
from tz-aware UTC via `America/New_York` so the London↔IST gap shifts correctly
across daylight saving. IST equivalents: London KZ ≈ 11:30–14:30 (summer) /
12:30–15:30 (winter); NY-AM KZ ≈ 16:30–19:30 / 17:30–20:30.

## 11. Risk
SL at the **structural invalidation** — beyond the swept wick +0.1×ATR buffer.
TP = the **opposite/next liquidity pool** (draw on liquidity), filtered to a
minimum reward:risk (default 3:1, per Casper's explicit rule and the ICT
"one repricing leg" target).

---

### Where the creators genuinely differ (→ these are the tunable `Params`)
| Dimension | Default | Divergence |
|---|---|---|
| Primary POI | FVG 50% CE | TJR/Fractal Flow = OB-first; UKspreadbetting adds OTE; Alchemist = MSNR body-to-body S/R |
| Structure lookback | N=5 / 2 | shorter for faster intraday structure |
| Min R:R | 3.0 | 2.0 also common |
| Session gating | killzone (intraday) | Casper = NY 09:30 ORB; Silver Bullet = 10–11 ET |

### Evidence quality
No creator publishes a verified, reproducible backtested win rate; claims are
anecdotal/marketing. The one recurring quantified claim — "FVGs fill ~70% of the
time" — is a community figure, not independently verified. That absence of hard
evidence is exactly why this backtester exists.
