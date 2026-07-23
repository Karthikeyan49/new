"""
Stream years of 1-minute US30 from Dukascopy, newest-first, with a runtime cap
and resume. Downloads each UTC hour, decodes ticks, aggregates to 1-minute bars,
and appends to a CSV — keeping only the compact bars on disk, never the raw ticks.

Newest-first + progressive append means a capped/interrupted run still leaves a
usable recent dataset; re-running extends further back (skips days already saved).

    python3 src/download.py --start 2016-01-01 --end 2026-07-22 \
                            --out data/US30_M1.csv --minutes 45 --workers 12
"""
from __future__ import annotations
import argparse, datetime as dt, os, time
from concurrent.futures import ThreadPoolExecutor

import dukascopy as dk


def existing_days(path: str) -> set[str]:
    days = set()
    if os.path.exists(path):
        with open(path) as fh:
            next(fh, None)
            for line in fh:
                days.add(line[:10])
    return days


def fetch_day(day: dt.date) -> list[tuple]:
    """All 1-minute bars for one UTC day (24 hours fetched concurrently)."""
    merged: dict = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        raws = list(ex.map(lambda h: (h, dk.fetch_hour(day, h)), range(24)))
    for h, raw in raws:
        if raw:
            merged.update(dk.hour_to_minutes(raw, day, h))
    return [(ts, *merged[ts]) for ts in sorted(merged)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--minutes", type=float, default=45.0, help="runtime cap")
    ap.add_argument("--workers", type=int, default=12, help="days fetched in parallel")
    a = ap.parse_args()

    start = dt.date.fromisoformat(a.start)
    end = dt.date.fromisoformat(a.end)
    done = existing_days(a.out)
    new_file = not os.path.exists(a.out)
    fh = open(a.out, "a")
    if new_file:
        fh.write("timestamp,open,high,low,close,volume\n")

    # newest-first list of days still needed, skipping weekends and saved days
    days = []
    d = end
    while d >= start:
        if d.weekday() < 5 and d.isoformat() not in done:
            days.append(d)
        d -= dt.timedelta(days=1)

    t0 = time.monotonic()
    saved_days = saved_bars = 0
    # process a batch of days concurrently, then flush
    for i in range(0, len(days), a.workers):
        if (time.monotonic() - t0) / 60.0 > a.minutes:
            print(f"[cap] runtime limit hit after {saved_days} days"); break
        batch = days[i:i + a.workers]
        with ThreadPoolExecutor(max_workers=a.workers) as ex:
            results = list(ex.map(fetch_day, batch))
        for day, bars in sorted(zip(batch, results)):     # write chronologically
            for ts, o, h, l, c, v in bars:
                fh.write(f"{ts:%Y-%m-%d %H:%M:%S+00:00},{o:.2f},{h:.2f},{l:.2f},{c:.2f},{v}\n")
            if bars:
                saved_days += 1; saved_bars += len(bars)
        fh.flush()
        el = (time.monotonic() - t0) / 60.0
        print(f"  {batch[-1]}..{batch[0]}  total_days={saved_days} bars={saved_bars} "
              f"elapsed={el:.1f}m", flush=True)
    fh.close()
    print(f"DONE days={saved_days} bars={saved_bars} out={a.out}")


if __name__ == "__main__":
    main()
