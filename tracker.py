#!/usr/bin/env python3
"""Per-cat litter box weight tracker for Roman and Morty."""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
VISITS = HERE / "visits.json"
LOG = HERE / "litter-log.json"
OUT = HERE / "public" / "index.html"
TZ = ZoneInfo("America/New_York")

CATS = {
    "Roman": {"baseline": 13.0, "color": "#5b6b7a", "sprite": "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"},
    "Morty": {"baseline": 16.0, "color": "#a9794a", "sprite": "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"},
}


def classify(weight_lb):
    return min(CATS, key=lambda c: abs(weight_lb - CATS[c]["baseline"]))


def load_log():
    if LOG.is_file():
        return {v["timestamp"]: v for v in json.loads(LOG.read_text())}
    return {}


def make_chart(pts, color):
    w, h, pad = 420, 150, 24
    xs = [p[0].timestamp() for p in pts]
    ys = [p[1] for p in pts]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys) - 0.3, max(ys) + 0.3

    def X(x):
        return pad + (x - xmin) / (xmax - xmin or 1) * (w - 2 * pad)

    def Y(y):
        return h - pad - (y - ymin) / (ymax - ymin or 1) * (h - 2 * pad)

    pline = " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in zip(xs, ys))
    dots = "".join(
        f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="2.5" fill="{color}"/>'
        for x, y in zip(xs, ys)
    )
    return (
        f'<svg viewBox="0 0 {w} {h}" class="chart">'
        f'<polyline points="{pline}" fill="none" stroke="{color}" stroke-width="2"/>'
        f'{dots}'
        f'<text x="{pad}" y="12" class="axl">{ymax:.1f} lb</text>'
        f'<text x="{pad}" y="{h-6}" class="axl">{ymin:.1f} lb</text>'
        f'</svg>'
    )


def main():
    if not VISITS.is_file():
        raise SystemExit("visits.json not found. Run fetch_ci.py first.")
    log = load_log()
    new = 0
    for v in json.loads(VISITS.read_text()):
        if v["timestamp"] not in log:
            log[v["timestamp"]] = v
            new += 1
    LOG.write_text(json.dumps(sorted(log.values(), key=lambda x: x["timestamp"]), indent=2))

    visits = sorted(log.values(), key=lambda x: x["timestamp"])
    for v in visits:
        v["cat"] = classify(v["weight_lb"])
        v["dt"] = datetime.fromisoformat(v["timestamp"]).astimezone(TZ)

    now = datetime.now(TZ)
    today = now.date()
    week_ago = now - timedelta(days=7)

    cards = []
    for name, meta in CATS.items():
        cv = [v for v in visits if v["cat"] == name]
        weights = [v["weight_lb"] for v in cv]
        latest = cv[-1] if cv else None
        median_all = round(statistics.median(weights), 2) if weights else 0
        recent = [v["weight_lb"] for v in cv if v["dt"] >= week_ago]
        recent_med = round(statistics.median(recent), 2) if recent else median_all
        visits_today = sum(1 for v in cv if v["dt"].date() == today)
        visits_week = len(recent)
        delta = round(recent_med - median_all, 2) if weights else 0
        flag = ""
        if weights and abs(delta) >= 0.4:
            arrow = "up" if delta > 0 else "down"
            flag = f'<div class="flag {arrow}">Recent weight {arrow} {abs(delta):.2f} lb vs usual</div>'
        pts = [(v["dt"], v["weight_lb"]) for v in cv]
        chart = make_chart(pts, meta["color"]) if len(pts) >= 2 else '<div class="nochart">Not enough data yet</div>'
        latest_w = f"{latest['weight_lb']:.2f}" if latest else "-"
        last_seen = latest["dt"].strftime("%b %-d, %-I:%M %p") if latest else "-"
        cards.append(
            '<div class="card">'
            '<div class="head">'
            f'<img class="sprite" src="data:image/png;base64,{meta["sprite"]}" alt="{name}">'
            f'<div><div class="name">{name}</div><div class="sub">usual weight {median_all:.2f} lb</div></div>'
            '</div>'
            '<div class="stats">'
            f'<div class="stat"><div class="num">{latest_w}</div><div class="lbl">latest lb</div></div>'
            f'<div class="stat"><div class="num">{visits_today}</div><div class="lbl">today</div></div>'
            f'<div class="stat"><div class="num">{visits_week}</div><div class="lbl">last 7 days</div></div>'
            f'<div class="stat"><div class="num">{len(cv)}</div><div class="lbl">total</div></div>'
            '</div>'
            f'{flag}'
            f'<div class="chartbox">{chart}</div>'
            f'<div class="last">Last seen {last_seen}</div>'
            '</div>'
        )

    html = (
        PAGE.replace("__CARDS__", "\n".join(cards))
        .replace("__UPDATED__", now.strftime("%b %-d, %Y at %-I:%M %p"))
        .replace("__NEW__", str(new))
        .replace("__TOTAL__", str(len(visits)))
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html)
    print(f"Added {new} new visits ({len(visits)} total). Wrote {OUT.relative_to(HERE)}.")
    print(f"Open it: {OUT}")


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Litter Box Tracker</title>
<style>
 body{margin:0;font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#12151a;color:#e8ecf1}
 .wrap{max-width:720px;margin:0 auto;padding:24px}
 h1{font-size:22px;margin:0 0 4px}
 .meta{color:#8b96a5;font-size:13px;margin-bottom:20px}
 .card{background:#1b212b;border:1px solid #2a3240;border-radius:16px;padding:18px;margin-bottom:18px}
 .head{display:flex;align-items:center;gap:14px;margin-bottom:14px}
 .sprite{width:64px;height:64px;image-rendering:pixelated;background:#0d0f13;border-radius:12px;padding:4px}
 .name{font-size:20px;font-weight:700}
 .sub{color:#8b96a5;font-size:13px}
 .stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:12px}
 .stat{background:#131821;border-radius:10px;padding:10px;text-align:center}
 .num{font-size:20px;font-weight:700}
 .lbl{font-size:11px;color:#8b96a5;margin-top:2px}
 .flag{font-size:13px;padding:8px 12px;border-radius:8px;margin-bottom:12px}
 .flag.up{background:#3a2a16;color:#f0b36b}
 .flag.down{background:#16263a;color:#6bb3f0}
 .chartbox{background:#131821;border-radius:10px;padding:8px}
 .chart{width:100%;height:auto}
 .axl{fill:#6b7684;font-size:9px}
 .nochart{color:#6b7684;font-size:13px;text-align:center;padding:30px}
 .last{color:#8b96a5;font-size:12px;margin-top:10px}
</style></head><body><div class="wrap">
 <h1>&#128062; Litter Box Tracker</h1>
 <div class="meta">Updated __UPDATED__ &middot; __NEW__ new visits this run &middot; __TOTAL__ logged</div>
 __CARDS__
 <div class="meta">Weights read from the box scale, sorted to the nearest cat. The box can't tell them apart on its own, so an occasional visit may land on the wrong cat.</div>
</div></body></html>"""


if __name__ == "__main__":
    main()
