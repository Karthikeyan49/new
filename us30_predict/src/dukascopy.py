"""Dukascopy tick-data fetch + decode + 1-minute aggregation for US30 (USA30IDXUSD).

.bi5 files are LZMA-compressed arrays of 20-byte big-endian records:
    >I I I f f  = (ms_since_hour, ask*1000, bid*1000, askVolume, bidVolume)
Price = integer / 1000. One file per UTC hour at:
    /datafeed/{SYM}/{YYYY}/{MM0}/{DD}/{HH}h_ticks.bi5   (MM0 is 0-indexed month)
"""
from __future__ import annotations
import lzma, struct, urllib.request, datetime as dt

SYM = "USA30IDXUSD"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0"
BASE = "https://datafeed.dukascopy.com/datafeed"


def _decode(raw: bytes) -> bytes:
    for fmt in (lzma.FORMAT_AUTO, lzma.FORMAT_ALONE):
        try:
            out = lzma.LZMADecompressor(format=fmt).decompress(raw)
            if out:
                return out
        except Exception:
            continue
    return b""


def fetch_hour(day: dt.date, hour: int, tries: int = 3) -> bytes:
    url = f"{BASE}/{SYM}/{day.year}/{day.month-1:02d}/{day.day:02d}/{hour:02d}h_ticks.bi5"
    for a in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return b""
        except Exception:
            pass
    return b""


def hour_to_minutes(raw: bytes, day: dt.date, hour: int) -> dict:
    """Decode one hour's raw bytes into {minute_ts: [o,h,l,c,vol]} using mid price."""
    data = _decode(raw)
    if not data:
        return {}
    base = dt.datetime(day.year, day.month, day.day, hour, tzinfo=dt.timezone.utc)
    out: dict = {}
    for i in range(len(data) // 20):
        ms, ask, bid, av, bv = struct.unpack_from(">IIIff", data, i * 20)
        price = (ask + bid) / 2000.0            # (ask/1000 + bid/1000)/2
        ts = base + dt.timedelta(minutes=ms // 60000)
        if ts not in out:
            out[ts] = [price, price, price, price, 1]   # vol = tick count
        else:
            b = out[ts]
            b[1] = max(b[1], price); b[2] = min(b[2], price); b[3] = price; b[4] += 1
    return out
