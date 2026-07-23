"""Dependency-free SVG line chart for equity / cumulative-R curves."""
from __future__ import annotations


def equity_svg(values, title: str, width=720, height=280, pad=40) -> str:
    n = len(values)
    if n < 2:
        return f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}'></svg>"
    lo, hi = min(values), max(values)
    rng = (hi - lo) or 1.0
    iw, ih = width - 2 * pad, height - 2 * pad

    def X(i):
        return pad + iw * i / (n - 1)

    def Y(v):
        return pad + ih * (1 - (v - lo) / rng)

    pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(values))
    base_y = Y(values[0])
    up = values[-1] >= values[0]
    color = "#1a9850" if up else "#d73027"
    grid = "".join(
        f"<line x1='{pad}' y1='{pad+ih*f:.1f}' x2='{width-pad}' y2='{pad+ih*f:.1f}' "
        f"stroke='#e5e7eb' stroke-width='1'/>" for f in (0, .25, .5, .75, 1)
    )
    return f"""<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' font-family='sans-serif'>
<rect width='{width}' height='{height}' fill='white'/>
{grid}
<line x1='{pad}' y1='{base_y:.1f}' x2='{width-pad}' y2='{base_y:.1f}' stroke='#9ca3af' stroke-dasharray='4 4' stroke-width='1'/>
<polyline fill='none' stroke='{color}' stroke-width='2' points='{pts}'/>
<text x='{pad}' y='24' font-size='15' font-weight='600' fill='#111'>{title}</text>
<text x='{pad}' y='{height-12}' font-size='11' fill='#6b7280'>start {values[0]:.2f}</text>
<text x='{width-pad}' y='{height-12}' font-size='11' fill='#6b7280' text-anchor='end'>end {values[-1]:.2f}</text>
</svg>"""


def write_equity_svg(values, title, path):
    with open(path, "w") as fh:
        fh.write(equity_svg(list(values), title))
