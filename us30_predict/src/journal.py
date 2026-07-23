"""
Stage 3 — REFLECTIVE MEMORY.

The Journal is the analyst's *experience*: every scored decision is stored, and
`memory_context()` distills recent performance into a short natural-language
block that is handed back to the analyst on the next decision. That closes the
'learn from profit/loss' loop — e.g. after a run of failed NY high-vol longs the
analyst reads "3/9 win (33%) — be cautious" and adjusts.

Depends only on duck-typed AnalystCall / MarketSnapshot attributes:
    call     : .direction .confidence .outcome .realized_R
    snapshot : .session .vol_regime          (optional; grouped on if present)
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional


def _is_trade(call) -> bool:
    """A real (non-flat) trade that was actually evaluated."""
    return (str(getattr(call, "direction", "flat")).lower() in ("long", "short")
            and str(getattr(call, "outcome", "")) in ("win", "loss", "timeout"))


def _won(call) -> bool:
    r = getattr(call, "realized_R", float("nan"))
    return r == r and float(r) > 0.0        # profitable after costs (NaN-safe)


class Journal:
    """Append-only reflective memory over scored AnalystCalls."""

    def __init__(self, max_recent: int = 300):
        # each item: (call, snapshot_or_None)
        self._entries: list[tuple] = []
        self.max_recent = int(max_recent)

    # -- storage --------------------------------------------------------- #
    def add(self, call, snapshot=None) -> None:
        """Store a scored call (and, if available, the snapshot it was made on)."""
        self._entries.append((call, snapshot))

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def calls(self) -> list:
        return [c for c, _ in self._entries]

    def recent(self, lookback: Optional[int] = None) -> list[tuple]:
        if lookback is None:
            return list(self._entries)
        return self._entries[-lookback:]

    # -- reflection ------------------------------------------------------ #
    def memory_context(self, lookback: int = 60, max_lines: int = 5) -> str:
        """A short text block the analyst can 'read' before deciding.

        Summarises recent trades overall and by (direction, session, vol_regime),
        flagging setups that have been weak or strong lately.
        """
        window = self.recent(lookback)
        trades = [(c, s) for c, s in window if _is_trade(c)]

        if not trades:
            return ("EXPERIENCE: no evaluated trades yet — no edge proven. "
                    "Only act on your highest-conviction setups; otherwise stand aside.")

        n = len(trades)
        wins = sum(1 for c, _ in trades if _won(c))
        total_R = sum(float(getattr(c, "realized_R", 0.0) or 0.0) for c, _ in trades)
        lines = [
            f"EXPERIENCE (last {n} trades): {wins}/{n} won "
            f"({wins / n:.0%}), net {total_R:+.1f}R after costs."
        ]

        # group by (direction, session, vol_regime) --------------------- #
        groups: dict = defaultdict(list)
        for c, s in trades:
            direction = str(getattr(c, "direction", "?")).lower()
            session = str(getattr(s, "session", "?")) if s is not None else "?"
            vol = str(getattr(s, "vol_regime", "?")) if s is not None else "?"
            groups[(direction, session, vol)].append(c)

        # confident sub-view helps the analyst trust/distrust its conviction
        def _fmt(name: str, gcalls: list) -> str:
            gn = len(gcalls)
            gw = sum(1 for c in gcalls if _won(c))
            wr = gw / gn
            gR = sum(float(getattr(c, "realized_R", 0.0) or 0.0) for c in gcalls)
            if gn >= 4 and wr <= 0.40:
                tag = "— weak lately, be cautious"
            elif gn >= 4 and wr >= 0.60:
                tag = "— this edge is working, press it"
            else:
                tag = "— small sample, stay honest"
            return f"  {name}: {gw}/{gn} win ({wr:.0%}), {gR:+.1f}R {tag}"

        ranked = sorted(groups.items(), key=lambda kv: len(kv[1]), reverse=True)
        for (direction, session, vol), gcalls in ranked[: max_lines]:
            name = f"{direction}s in {session}/{vol}-vol"
            lines.append(_fmt(name, gcalls))

        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Synthetic proof
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    try:
        from .schema import AnalystCall, MarketSnapshot
    except ImportError:
        from schema import AnalystCall, MarketSnapshot

    import random

    rng = random.Random(1)
    j = Journal()
    sessions = ["ny_am", "london", "asia"]
    for k in range(30):
        direction = rng.choice(["long", "short", "flat"])
        session = rng.choice(sessions)
        vol = rng.choice(["low", "normal", "high"])
        if direction == "flat":
            j.add(AnalystCall(ts=f"t{k}", direction="flat", outcome="flat",
                              realized_R=0.0),
                  MarketSnapshot(ts=f"t{k}", price=38000, session=session,
                                 vol_regime=vol))
            continue
        # NY high-vol longs are rigged to lose, to show the reflection working
        rigged_loss = (direction == "long" and session == "ny_am" and vol == "high")
        win = (not rigged_loss) and rng.random() < 0.5
        j.add(
            AnalystCall(ts=f"t{k}", direction=direction,
                        confidence=rng.randint(5, 9),
                        outcome="win" if win else "loss",
                        realized_R=2.0 if win else -1.05),
            MarketSnapshot(ts=f"t{k}", price=38000, session=session, vol_regime=vol),
        )

    print(f"journal size: {len(j)}")
    print("\n=== MEMORY CONTEXT ===")
    print(j.memory_context())
