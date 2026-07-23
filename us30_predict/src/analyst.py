"""
The ANALYST (reasoning) stage.

    perception.py :  1-min data       ->  MarketSnapshot   (what a human sees)
 >> analyst.py    :  MarketSnapshot   ->  AnalystCall      (what a human decides)
    replay.py     :  AnalystCall + future bars -> scored AnalystCall

This module turns a structured multi-timeframe read (MarketSnapshot) into a
discretionary decision (AnalystCall), reasoning the way a disciplined SMC/ICT
analyst would: weigh HTF trend against location (premium/discount), liquidity
sweeps, volatility regime and session/killzone timing — then either take a
trade with a confidence and a written thesis, or ABSTAIN (flat, confidence 0)
when there is no clean edge. Abstaining is the correct answer most of the time.

Two interchangeable backends, auto-selected:

  * LLM backend      — used when ANTHROPIC_API_KEY is set. Calls the Anthropic
                       Messages API and asks a strong SMC/ICT persona to return
                       strict JSON, which is parsed into an AnalystCall.
  * Heuristic backend — the runnable default with no key. Emulates the same
                       human reasoning deterministically from the snapshot,
                       including the natural-language thesis.

    from analyst import Analyst
    call = Analyst().analyze(snapshot)
"""
from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.request

from schema import MarketSnapshot, AnalystCall


# --------------------------------------------------------------------------- #
# Prompt (shared conceptually by both backends)                               #
# --------------------------------------------------------------------------- #
SYSTEM_PROMPT = """\
You are a disciplined, experienced discretionary US30 (Dow Jones) intraday \
analyst. You think in Smart-Money-Concepts / ICT terms and reason top-down \
across timeframes.

How you read a chart:
- HIGHER TIMEFRAMES SET DIRECTION. The 4h and 1h trend are your bias. You only
  look for trades that align with that bias, unless price is clearly reversing
  at a major liquidity extreme in a ranging market.
- LOCATION MATTERS. You buy in DISCOUNT (below equilibrium) and sell in PREMIUM
  (above equilibrium). Chasing price at the wrong side of equilibrium is a
  mistake you avoid.
- LIQUIDITY IS THE FUEL. Price seeks buy-side liquidity (BSL, resting above old
  highs) and sell-side liquidity (SSL, resting below old lows). A recent SWEEP
  of liquidity that then rejects is your entry trigger: a sell-side sweep in a
  bullish HTF context is a long signal; a buy-side sweep in a bearish context is
  a short signal. You target the opposing pool.
- REGIME AND TIMING. You prefer to act during killzones (London / NY AM) and in
  normal volatility. High-volatility, news-driven expansion or dead off-session
  chop is where you get chopped up, so you size down or stand aside.
- CONFLUENCE => CONVICTION. The more of these that line up (HTF trend + right
  side of equilibrium + aligned sweep + clean regime + good session), the higher
  your confidence. Few or conflicting signals => you PASS.

Discipline:
- ABSTAIN by default. If the read is muddy, timeframes conflict, price is mid-
  range at equilibrium, or there is no fresh liquidity event, you return
  direction "flat" with confidence 0. This is the majority of snapshots. A pass
  is a valid, professional decision — do not manufacture trades.
- When you do take a trade: entry near current price, stop at the true
  invalidation (beyond the swept wick / the opposing swing), target the next
  opposing liquidity pool, and a realistic time horizon.

Output contract — reply with STRICT JSON ONLY, no prose, no markdown fences:
{"direction": "long|short|flat",
 "confidence": <int 0-10>,
 "thesis": "<one or two sentences of plain-English reasoning>",
 "entry": <float>,
 "stop": <float>,
 "target": <float>,
 "horizon_min": <int>}

For a flat call, set confidence 0 and entry/stop/target to the current price."""

USER_PREFIX = (
    "Here is the current multi-timeframe read of US30. Decide like the analyst "
    "described. Remember: abstain unless there is a clean, confluent edge.\n\n"
)


# --------------------------------------------------------------------------- #
# Public class                                                                #
# --------------------------------------------------------------------------- #
class Analyst:
    """Reasons over a MarketSnapshot and returns an AnalystCall.

    Backend is auto-selected: the LLM backend is used when ANTHROPIC_API_KEY is
    present in the environment, otherwise the deterministic heuristic backend.
    Pass backend='heuristic' or backend='llm' to force one.
    """

    def __init__(
        self,
        backend: str = "auto",
        model: str = "claude-haiku-4-5-20251001",
        api_key: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
    ):
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        # Never store/log more than the presence of the key.
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")

        if backend == "auto":
            backend = "llm" if self._api_key else "heuristic"
        if backend not in ("llm", "heuristic"):
            raise ValueError(f"unknown backend {backend!r}")
        if backend == "llm" and not self._api_key:
            backend = "heuristic"
        self.backend = backend

    # -- entry point ------------------------------------------------------- #
    def analyze(self, snapshot: MarketSnapshot, memory_context: str = "") -> AnalystCall:
        if self.backend == "llm":
            try:
                return self._analyze_llm(snapshot, memory_context)
            except Exception as exc:  # graceful degradation, never crash the pipeline
                call = self._analyze_heuristic(snapshot, memory_context)
                call.thesis = f"[llm unavailable: {exc}] " + call.thesis
                return call
        return self._analyze_heuristic(snapshot, memory_context)

    # ===================================================================== #
    # LLM backend                                                           #
    # ===================================================================== #
    def _analyze_llm(self, snapshot: MarketSnapshot, memory_context: str) -> AnalystCall:
        user_msg = USER_PREFIX + snapshot.to_prompt()
        if memory_context:
            user_msg += "\n\nRelevant context / recent memory:\n" + memory_context

        payload = json.dumps({
            "model": self.model,
            "max_tokens": 700,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_msg}],
        }).encode("utf-8")

        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        raw = self._post_with_retries("https://api.anthropic.com/v1/messages",
                                      payload, headers)
        data = json.loads(raw)
        # Concatenate any text blocks in the response.
        text = "".join(
            b.get("text", "") for b in data.get("content", [])
            if b.get("type") == "text"
        ).strip()
        return self._parse_call(text, snapshot)

    def _post_with_retries(self, url: str, payload: bytes, headers: dict) -> str:
        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                req = urllib.request.Request(url, data=payload, headers=headers,
                                             method="POST")
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return resp.read().decode("utf-8")
            except urllib.error.HTTPError as exc:
                body = ""
                try:
                    body = exc.read().decode("utf-8", "replace")[:300]
                except Exception:
                    pass
                last_exc = RuntimeError(f"HTTP {exc.code}: {body}")
                # Don't retry unrecoverable client errors (except rate limit).
                if exc.code in (400, 401, 403, 404) and exc.code != 429:
                    break
            except Exception as exc:  # timeout, connection reset, etc.
                last_exc = exc
            if attempt < self.max_retries - 1:
                time.sleep(1.5 * (2 ** attempt))  # 1.5s, 3s, 6s backoff
        raise last_exc or RuntimeError("request failed")

    def _parse_call(self, text: str, snapshot: MarketSnapshot) -> AnalystCall:
        """Parse the model's JSON reply into an AnalystCall, tolerating fences."""
        obj = _extract_json(text)
        if obj is None:
            # Model didn't return usable JSON — treat as an abstain rather than error.
            return AnalystCall(ts=snapshot.ts, direction="flat", confidence=0,
                               thesis=f"[unparseable llm reply] {text[:160]}",
                               entry=snapshot.price, stop=snapshot.price,
                               target=snapshot.price, horizon_min=60)

        direction = str(obj.get("direction", "flat")).lower().strip()
        if direction not in ("long", "short", "flat"):
            direction = "flat"
        try:
            confidence = int(round(float(obj.get("confidence", 0))))
        except (TypeError, ValueError):
            confidence = 0
        confidence = max(0, min(10, confidence))
        if direction == "flat":
            confidence = 0

        def _f(key, default):
            try:
                return float(obj.get(key, default))
            except (TypeError, ValueError):
                return default

        try:
            horizon = int(round(float(obj.get("horizon_min", 60))))
        except (TypeError, ValueError):
            horizon = 60

        return AnalystCall(
            ts=snapshot.ts,
            direction=direction,
            confidence=confidence,
            thesis=str(obj.get("thesis", "")).strip(),
            entry=_f("entry", snapshot.price),
            stop=_f("stop", snapshot.price),
            target=_f("target", snapshot.price),
            horizon_min=max(1, horizon),
        )

    # ===================================================================== #
    # Heuristic backend                                                     #
    # ===================================================================== #
    def _analyze_heuristic(self, snapshot: MarketSnapshot, memory_context: str = "") -> AnalystCall:
        s = snapshot
        price = s.price
        flat = AnalystCall(ts=s.ts, direction="flat", confidence=0,
                           entry=price, stop=price, target=price, horizon_min=60)

        # ---- gather higher-timeframe bias ---------------------------------
        htf_trends = [s.tfs.get(tf, {}).get("trend") for tf in ("4h", "1h")]
        htf_trends = [t for t in htf_trends if t]
        bull_htf = htf_trends and all(t == "bull" for t in htf_trends)
        bear_htf = htf_trends and all(t == "bear" for t in htf_trends)
        # If the HTFs disagree, there is no clean directional bias.

        # nearest opposing pools (fall back to a synthetic target if missing)
        bsl = s.nearest_bsl
        ssl = s.nearest_ssl
        atr = s.atr_1m if (isinstance(s.atr_1m, float) and not math.isnan(s.atr_1m)) else max(price * 0.0006, 5.0)

        # ------------------------------------------------------------------ #
        # PATH A — trend continuation (the primary, highest-quality setup)   #
        # ------------------------------------------------------------------ #
        if bull_htf or bear_htf:
            direction = "long" if bull_htf else "short"

            # Score the confluence (each aligned condition adds conviction).
            good_location = (s.pd_zone == "discount") if bull_htf else (s.pd_zone == "premium")
            aligned_sweep = (s.recent_sweep == "sellside") if bull_htf else (s.recent_sweep == "buyside")
            clean_regime = s.vol_regime != "high"
            good_timing = bool(s.in_killzone)

            conditions = {
                "HTF trend aligned": True,  # gate already passed
                "favorable pd zone": good_location,
                "aligned liquidity sweep": aligned_sweep,
                "non-high volatility": clean_regime,
                "in killzone": good_timing,
            }
            score = sum(1 for v in conditions.values() if v)

            # Require a real trigger: we need to be on the right side of
            # equilibrium OR have a fresh aligned sweep. Otherwise it's just a
            # trend with no location/trigger — we pass.
            if aligned_sweep or good_location:
                # confidence: map score 2..5 -> ~4..9, clamp 0-10
                confidence = int(round(2 + 1.6 * score))
                # penalise missing the trigger-quality pieces
                if not aligned_sweep:
                    confidence -= 1
                if not clean_regime:
                    confidence -= 2
                confidence = max(3, min(10, confidence))

                htf_desc = "/".join(f"{tf} {s.tfs.get(tf, {}).get('trend')}"
                                    for tf in ("4h", "1h") if s.tfs.get(tf, {}).get("trend"))
                if bull_htf:
                    # stop beyond swept low / recent swing low
                    swing_low = _nearest_swing(s, "swing_low", below=price)
                    sweep_ref = ssl if aligned_sweep and not math.isnan(ssl) else swing_low
                    stop = (min(x for x in (sweep_ref, swing_low) if _ok(x)) - 0.5 * atr) \
                        if _ok(sweep_ref) or _ok(swing_low) else price - 3 * atr
                    target = bsl if _ok(bsl) else price + 3 * (price - stop) / 3 + 4 * atr
                    thesis = (
                        f"HTF bullish ({htf_desc}); "
                        f"price in {s.pd_zone} at {price:.1f}"
                        + (f", swept sell-side liquidity (SSL {ssl:.1f})" if aligned_sweep else "")
                        + (f", {s.session} killzone" if good_timing else f", {s.session} session")
                        + f". {score}/5 confluences -> lean LONG continuation. "
                        f"Invalid below {stop:.1f}; target buy-side pool at {target:.1f}."
                    )
                else:
                    swing_high = _nearest_swing(s, "swing_high", below=None, above=price)
                    sweep_ref = bsl if aligned_sweep and not math.isnan(bsl) else swing_high
                    stop = (max(x for x in (sweep_ref, swing_high) if _ok(x)) + 0.5 * atr) \
                        if _ok(sweep_ref) or _ok(swing_high) else price + 3 * atr
                    target = ssl if _ok(ssl) else price - 4 * atr
                    thesis = (
                        f"HTF bearish ({htf_desc}); "
                        f"price in {s.pd_zone} at {price:.1f}"
                        + (f", swept buy-side liquidity (BSL {bsl:.1f})" if aligned_sweep else "")
                        + (f", {s.session} killzone" if good_timing else f", {s.session} session")
                        + f". {score}/5 confluences -> lean SHORT continuation. "
                        f"Invalid above {stop:.1f}; target sell-side pool at {target:.1f}."
                    )

                return AnalystCall(ts=s.ts, direction=direction, confidence=confidence,
                                   thesis=thesis, entry=price, stop=round(stop, 1),
                                   target=round(target, 1), horizon_min=60)

            # HTF trend but no location/trigger -> stand aside.
            flat.thesis = (
                f"HTF {'bullish' if bull_htf else 'bearish'} but price is "
                f"{s.pd_zone} with no aligned sweep (recent_sweep={s.recent_sweep}) "
                f"and no discount/premium edge -> no trigger, stand aside."
            )
            return flat

        # ------------------------------------------------------------------ #
        # PATH B — range fade (reversal at a swept edge in a ranging market)  #
        # ------------------------------------------------------------------ #
        # A ranging market: HTFs flat/disagree. If price just swept an edge
        # liquidity pool and volatility isn't blowing out, fade it back toward
        # the opposite edge with modest conviction.
        ranging = _is_range(s)
        if ranging and s.recent_sweep in ("buyside", "sellside") and s.vol_regime != "high":
            if s.recent_sweep == "buyside":
                # swept highs -> expect reversal down (fade the sweep)
                direction = "short"
                swing_high = _nearest_swing(s, "swing_high", above=price)
                ref = bsl if _ok(bsl) else swing_high
                stop = (ref + 0.7 * atr) if _ok(ref) else price + 2.5 * atr
                target = ssl if _ok(ssl) else s.equilibrium if _ok(s.equilibrium) else price - 3 * atr
                thesis = (
                    f"Range regime (no HTF trend); price swept buy-side liquidity "
                    f"(BSL {bsl:.1f}) at the range high and rejected -> fade SHORT "
                    f"back into the range. Invalid above {stop:.1f}; "
                    f"target sell-side/mid at {target:.1f}."
                )
            else:
                direction = "long"
                swing_low = _nearest_swing(s, "swing_low", below=price)
                ref = ssl if _ok(ssl) else swing_low
                stop = (ref - 0.7 * atr) if _ok(ref) else price - 2.5 * atr
                target = bsl if _ok(bsl) else s.equilibrium if _ok(s.equilibrium) else price + 3 * atr
                thesis = (
                    f"Range regime (no HTF trend); price swept sell-side liquidity "
                    f"(SSL {ssl:.1f}) at the range low and rejected -> fade LONG "
                    f"back into the range. Invalid below {stop:.1f}; "
                    f"target buy-side/mid at {target:.1f}."
                )
            # modest conviction for counter-move fades; bump if killzone
            confidence = 4 + (1 if s.in_killzone else 0)
            return AnalystCall(ts=s.ts, direction=direction, confidence=confidence,
                               thesis=thesis, entry=price, stop=round(stop, 1),
                               target=round(target, 1), horizon_min=45)

        # ------------------------------------------------------------------ #
        # PATH C — no clean edge -> ABSTAIN (the common case)                 #
        # ------------------------------------------------------------------ #
        reasons = []
        if not htf_trends:
            reasons.append("no HTF structure")
        elif not (bull_htf or bear_htf):
            reasons.append(f"HTF timeframes conflict ({', '.join(htf_trends)})")
        if s.recent_sweep == "none":
            reasons.append("no fresh liquidity sweep")
        if s.pd_zone == "equilibrium":
            reasons.append("price at equilibrium (no premium/discount edge)")
        if s.vol_regime == "high":
            reasons.append("high-volatility regime (chop risk)")
        if not s.in_killzone:
            reasons.append(f"outside killzone ({s.session})")
        if not reasons:
            reasons.append("signals present but not confluent enough")
        flat.thesis = "No clean edge -> ABSTAIN: " + "; ".join(reasons) + "."
        return flat


# --------------------------------------------------------------------------- #
# Small helpers                                                               #
# --------------------------------------------------------------------------- #
def _ok(x) -> bool:
    """True for a real, usable float."""
    return isinstance(x, (int, float)) and not (isinstance(x, float) and math.isnan(x))


def _nearest_swing(s: MarketSnapshot, key: str, below=None, above=None):
    """Best swing level across timeframes on the requested side of price."""
    vals = []
    for tf in ("1h", "15m", "5m", "4h"):
        v = s.tfs.get(tf, {}).get(key)
        if _ok(v):
            if below is not None and v >= below:
                continue
            if above is not None and v <= above:
                continue
            vals.append(v)
    if not vals:
        return float("nan")
    # nearest to price: if below, take the max; if above, take the min
    return max(vals) if below is not None else min(vals)


def _is_range(s: MarketSnapshot) -> bool:
    """A ranging market: HTFs are flat/ranging or disagree, not cleanly trending."""
    htf = [s.tfs.get(tf, {}).get("trend") for tf in ("4h", "1h")]
    htf = [t for t in htf if t]
    if not htf:
        return True
    if all(t == "bull" for t in htf) or all(t == "bear" for t in htf):
        return False
    return True


def _extract_json(text: str):
    """Pull the first JSON object out of a possibly-fenced model reply."""
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        # strip ```json ... ``` fences
        t = t.split("```", 2)[1] if t.count("```") >= 2 else t.strip("`")
        if t.lstrip().lower().startswith("json"):
            t = t.lstrip()[4:]
    # first try the whole thing, then a brace-slice
    for candidate in (t, _brace_slice(t)):
        if not candidate:
            continue
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def _brace_slice(t: str):
    i = t.find("{")
    j = t.rfind("}")
    if i != -1 and j != -1 and j > i:
        return t[i:j + 1]
    return None


# --------------------------------------------------------------------------- #
# Demo — three hand-made snapshots showing the reasoning                       #
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    analyst = Analyst()
    print(f"active backend: {analyst.backend}  (model={analyst.model})")
    print("=" * 74)

    examples = []

    # 1) Clean trend-continuation LONG: HTFs bullish, price in discount,
    #    swept sell-side liquidity, normal vol, London killzone.
    examples.append(("clean trend-continuation long", MarketSnapshot(
        ts="2026-07-23T08:15:00Z",
        price=39850.0,
        tfs={
            "4h":  {"trend": "bull", "swing_high": 40200.0, "swing_low": 39400.0, "last_event": "HH"},
            "1h":  {"trend": "bull", "swing_high": 39980.0, "swing_low": 39760.0, "last_event": "HL"},
            "15m": {"trend": "bull", "swing_high": 39905.0, "swing_low": 39820.0, "last_event": "sweep"},
        },
        nearest_bsl=40200.0,
        nearest_ssl=39790.0,
        recent_sweep="sellside",
        atr_1m=18.0, atr_pct=0.045, vol_regime="normal",
        equilibrium=39900.0, pd_zone="discount",
        session="london", in_killzone=True,
        ret_15m=0.0012, ret_60m=0.0035,
    )))

    # 2) Range fade SHORT: HTFs conflict (range), price swept buy-side at the
    #    top of the range and is rejecting, normal vol, NY AM.
    examples.append(("range-fade short", MarketSnapshot(
        ts="2026-07-23T14:05:00Z",
        price=40160.0,
        tfs={
            "4h":  {"trend": "bull", "swing_high": 40200.0, "swing_low": 39600.0, "last_event": "range"},
            "1h":  {"trend": "bear", "swing_high": 40180.0, "swing_low": 39950.0, "last_event": "sweep"},
            "15m": {"trend": "bear", "swing_high": 40175.0, "swing_low": 40010.0, "last_event": "BOS"},
        },
        nearest_bsl=40180.0,
        nearest_ssl=39960.0,
        recent_sweep="buyside",
        atr_1m=22.0, atr_pct=0.055, vol_regime="normal",
        equilibrium=40060.0, pd_zone="premium",
        session="ny_am", in_killzone=True,
        ret_15m=-0.0006, ret_60m=0.0009,
    )))

    # 3) No-edge ABSTAIN: HTFs conflict, no sweep, price at equilibrium,
    #    off-session, high volatility.
    examples.append(("no-edge abstain", MarketSnapshot(
        ts="2026-07-23T22:40:00Z",
        price=40005.0,
        tfs={
            "4h":  {"trend": "bull", "swing_high": 40300.0, "swing_low": 39700.0, "last_event": "inside"},
            "1h":  {"trend": "bear", "swing_high": 40090.0, "swing_low": 39930.0, "last_event": "inside"},
        },
        nearest_bsl=40090.0,
        nearest_ssl=39930.0,
        recent_sweep="none",
        atr_1m=41.0, atr_pct=0.10, vol_regime="high",
        equilibrium=40000.0, pd_zone="equilibrium",
        session="off", in_killzone=False,
        ret_15m=-0.0002, ret_60m=0.0001,
    )))

    for name, snap in examples:
        call = analyst.analyze(snap)
        print(f"\n### {name}")
        print(snap.to_prompt())
        print("-> decision:")
        print(f"   direction  : {call.direction}")
        print(f"   confidence : {call.confidence}/10")
        print(f"   entry/stop/target : {call.entry} / {call.stop} / {call.target}")
        print(f"   horizon_min: {call.horizon_min}")
        print(f"   thesis     : {call.thesis}")
