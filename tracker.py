#!/usr/bin/env python3
"""Per-cat litter box weight tracker for Roman and Morty."""
from __future__ import annotations

import base64
import json
import statistics
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"
VISITS = HERE / "visits.json"
LOG = HERE / "litter-log.json"
STATUS = HERE / "status.json"
OUT = HERE / "public" / "index.html"
TZ = ZoneInfo("America/New_York")

# Pee/poop is a duration heuristic, not measured waste. <= this many seconds = likely pee.
PEE_MAX_SECONDS = 45
BAND_HALF = 0.25  # usual-range band = median ± this many lb
IDLE_SCALE = 2  # integer scale so crisp pixels stay on the grid

CAT_COLORS = {
    "Roman": "#5b6b7a",
    "Morty": "#a9794a",
}


def b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def load_sprite_meta() -> dict:
    return json.loads((ASSETS / "sprites.json").read_text())


def classify(weight_lb):
    return min(CAT_COLORS, key=lambda c: abs(weight_lb - (13.0 if c == "Roman" else 16.0)))


def load_log():
    if LOG.is_file():
        return {v["timestamp"]: v for v in json.loads(LOG.read_text())}
    return {}


def fmt_dur(seconds: int) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m {seconds % 60:02d}s"


def guess_waste(seconds: int) -> dict:
    if int(seconds) <= PEE_MAX_SECONDS:
        return {"key": "pee", "icon": "\U0001f4a7", "text": "likely pee"}
    return {"key": "poop", "icon": "\U0001f4a9", "text": "likely poop"}


def fmt_iso_et(iso) -> str:
    if not iso:
        return "unknown"
    try:
        dt = datetime.fromisoformat(str(iso))
    except ValueError:
        return str(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ).strftime("%b %-d, %Y at %-I:%M %p ET")


def bits_phrase(value, bits) -> str:
    if value is None:
        return "unknown"
    try:
        n = int(value)
    except (TypeError, ValueError):
        return f"raw value {value}"
    bits = list(bits or [])
    if not bits:
        return f"value {n} (binary {n:08b}) — no bits set"
    labels = ", ".join(f"bit {b}" for b in bits)
    return f"value {n} (binary {n:08b}) — {labels} on"


def load_latest_status():
    for path in (STATUS, HERE / "public" / "status.json"):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text())
        except Exception:
            continue
        hist = data.get("history") if isinstance(data, dict) else data
        if hist:
            return hist[-1]
    return None


def waste_card_html() -> str:
    latest = load_latest_status()
    if not latest:
        return (
            '<div class="card waste">'
            '<div class="head"><div><div class="name">Waste bin</div>'
            '<div class="sub">Experimental &middot; waiting for the next cloud refresh</div></div></div>'
            '<div class="caption">Notification flags will show up here after the box is queried. '
            "This is a best-guess channel and still needs calibration.</div></div>"
        )
    dp21, dp22, dp7 = latest.get("dp21"), latest.get("dp22"), latest.get("dp7")
    b21, b22 = latest.get("dp21_bits") or [], latest.get("dp22_bits") or []
    updated = fmt_iso_et(latest.get("recorded_at"))
    changed = fmt_iso_et(latest.get("dp21_changed_at"))
    visits = "—" if dp7 is None else str(dp7)
    bit_pills = (
        "".join(f'<span class="pill on">bit {b} on</span>' for b in b21)
        if b21
        else '<span class="pill">no notification bits set</span>'
    )
    fault = bits_phrase(dp22, b22)
    return (
        '<div class="card waste">'
        '<div class="head"><div><div class="name">Waste bin</div>'
        '<div class="sub">Experimental best-guess &middot; needs calibration</div></div></div>'
        '<div class="wastegrid">'
        f'<div class="stat"><div class="num">{visits}</div><div class="lbl">visits today</div></div>'
        f'<div class="stat"><div class="num">DP 21</div><div class="lbl">notify flags</div></div>'
        f'<div class="stat"><div class="num">DP 22</div><div class="lbl">fault flags</div></div>'
        "</div>"
        f'<div class="flagrow">{bit_pills}</div>'
        f'<div class="bits">Notification flags: {bits_phrase(dp21, b21)}</div>'
        f'<div class="bits">Fault flags: {fault}</div>'
        '<div class="warn">We do not yet know which DP 21 bit means the waste bin is full. '
        "When the box says it is full, note the time so the exact bit can be locked in.</div>"
        f'<div class="last">Flags last changed {changed} &middot; Snapshot {updated}</div>'
        "</div>"
    )


def fight_payload(meta: dict) -> dict:
    ri, mi, rf = meta["roman_idle"], meta["morty_idle"], meta["roman_fight"]
    return {
        "stage": b64(ASSETS / "omega_stage.jpg"),
        "roman": {
            "sheet": b64(ASSETS / rf["file"]),
            "sprite_w": rf["sprite_w"],
            "sprite_h": rf["sprite_h"],
            "frames": rf["frames"],
            "anchor_x": rf["anchor_x"],
            "anchor_y": rf["anchor_y"],
            "display": 1,
        },
        "morty": {
            "sheet": b64(ASSETS / mi["file"]),
            "sprite_w": mi["sprite_w"],
            "sprite_h": mi["sprite_h"],
            "frames": mi["frames"],
            "anchor_x": mi["anchor_x"],
            "anchor_y": mi["anchor_y"],
            "display": 2,
        },
        "idle": {
            "roman": b64(ASSETS / ri["file"]),
            "morty": b64(ASSETS / mi["file"]),
        },
    }


def main():
    meta = load_sprite_meta()
    log = load_log()
    new = 0
    if VISITS.is_file():
        for v in json.loads(VISITS.read_text()):
            if v["timestamp"] not in log:
                log[v["timestamp"]] = v
                new += 1
    elif not log:
        raise SystemExit("visits.json not found. Run fetch_ci.py first.")

    LOG.write_text(json.dumps(sorted(log.values(), key=lambda x: x["timestamp"]), indent=2))

    visits = sorted(log.values(), key=lambda x: x["timestamp"])
    for v in visits:
        v["cat"] = classify(v["weight_lb"])
        v["dt"] = datetime.fromisoformat(v["timestamp"]).astimezone(TZ)

    now = datetime.now(TZ)
    today = now.date()
    week_ago = now - timedelta(days=7)

    charts = {}
    cards = []
    baselines = {"Roman": 13.0, "Morty": 16.0}
    idle_files = {"Roman": meta["roman_idle"], "Morty": meta["morty_idle"]}
    for name, color in CAT_COLORS.items():
        sm = idle_files[name]
        cv = [v for v in visits if v["cat"] == name]
        weights = [v["weight_lb"] for v in cv]
        latest = cv[-1] if cv else None
        median_all = round(statistics.median(weights), 2) if weights else baselines[name]
        recent = [v["weight_lb"] for v in cv if v["dt"] >= week_ago]
        recent_med = round(statistics.median(recent), 2) if recent else median_all
        visits_today = sum(1 for v in cv if v["dt"].date() == today)
        visits_week = len(recent)
        delta = round(recent_med - median_all, 2) if weights else 0
        flag = ""
        if weights and abs(delta) >= 0.4:
            arrow = "up" if delta > 0 else "down"
            flag = f'<div class="flag {arrow}">Recent weight {arrow} {abs(delta):.2f} lb vs usual</div>'

        rows = []
        for v in cv:
            g = guess_waste(v["duration_seconds"])
            rows.append({
                "ts": int(v["dt"].timestamp()),
                "day": v["dt"].strftime("%Y-%m-%d"),
                "w": round(v["weight_lb"], 3),
                "dur": int(v["duration_seconds"]),
                "dur_txt": fmt_dur(v["duration_seconds"]),
                "guess": g["key"],
                "icon": g["icon"],
                "gtext": g["text"],
                "when": v["dt"].strftime("%b %-d, %-I:%M %p ET"),
            })
        charts[name] = {
            "color": color,
            "median": median_all,
            "band": [round(median_all - BAND_HALF, 2), round(median_all + BAND_HALF, 2)],
            "visits": rows,
        }

        latest_w = f"{latest['weight_lb']:.2f}" if latest else "-"
        last_seen = latest["dt"].strftime("%b %-d, %-I:%M %p ET") if latest else "-"
        sw = sm["sprite_w"] * IDLE_SCALE
        sh = sm["sprite_h"] * IDLE_SCALE
        nf = sm["frames"]
        idle_s = 1.6 if nf >= 10 else 2.2
        sheet = b64(ASSETS / sm["file"])
        cards.append(
            f'<div class="card" data-cat="{name}">'
            '<div class="head">'
            f'<div class="sprite" role="img" aria-label="{name}" style="'
            f'width:{sw}px;height:{sh}px;--sheet-w:{sw * nf}px;'
            f'background-size:{sw * nf}px {sh}px;'
            f'animation:idle {idle_s}s steps({nf}) infinite;'
            f'background-image:url(data:image/png;base64,{sheet})">'
            "</div>"
            f'<div><div class="name">{name}</div>'
            f'<div class="sub">usual weight {median_all:.2f} lb'
            f' &middot; range {median_all - BAND_HALF:.2f}\u2013{median_all + BAND_HALF:.2f} lb</div></div>'
            "</div>"
            '<div class="stats">'
            f'<div class="stat"><div class="num">{latest_w}</div><div class="lbl">latest lb</div></div>'
            f'<div class="stat"><div class="num">{visits_today}</div><div class="lbl">today</div></div>'
            f'<div class="stat"><div class="num">{visits_week}</div><div class="lbl">last 7 days</div></div>'
            f'<div class="stat"><div class="num">{len(cv)}</div><div class="lbl">total</div></div>'
            "</div>"
            f"{flag}"
            '<div class="ranges" role="tablist" aria-label="Chart range">'
            '<button type="button" class="rangebtn" data-days="1">1 day</button>'
            '<button type="button" class="rangebtn" data-days="7">1 week</button>'
            '<button type="button" class="rangebtn active" data-days="30">30 days</button>'
            '<button type="button" class="rangebtn" data-days="90">90 days</button>'
            '<button type="button" class="rangebtn" data-days="180">6 months</button>'
            '<button type="button" class="rangebtn" data-days="365">1 year</button>'
            "</div>"
            '<div class="chartbox"><svg class="chart" viewBox="0 0 440 180" preserveAspectRatio="xMidYMid meet"></svg></div>'
            '<div class="dailynote"></div>'
            '<div class="hinttxt">Tap a dot for exact time, weight, duration, and a pee/poop guess</div>'
            '<div class="visitlist"></div>'
            '<div class="caption">Pee/poop is estimated from time on the box (about 45 seconds or less = likely pee, longer = likely poop). It is not a measured waste weight.</div>'
            f'<div class="last">Last seen {last_seen}</div>'
            "</div>"
        )

    chart_json = json.dumps(charts, ensure_ascii=False).replace("<", "\u003c")
    fight_json = json.dumps(fight_payload(meta)).replace("<", "\u003c")
    html = (
        PAGE.replace("__CARDS__", "\n".join(cards))
        .replace("__WASTE__", waste_card_html())
        .replace("__UPDATED__", now.strftime("%b %-d, %Y at %-I:%M %p ET"))
        .replace("__NEW__", str(new))
        .replace("__TOTAL__", str(len(visits)))
        .replace("__CHARTS__", chart_json)
        .replace("__FIGHT__", fight_json)
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html)
    print(f"Added {new} new visits ({len(visits)} total). Wrote {OUT.relative_to(HERE)}.")
    print(f"Open it: {OUT}")


PAGE = r"""
<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Litter Box Tracker</title>
<style>
 body{margin:0;font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#12151a;color:#e8ecf1}
 .wrap{max-width:720px;margin:0 auto;padding:24px}
 h1{font-size:22px;margin:0 0 4px}
 .meta{color:#8b96a5;font-size:13px;margin-bottom:20px}
 .card{background:#1b212b;border:1px solid #2a3240;border-radius:16px;padding:18px;margin-bottom:18px}
 .head{display:flex;align-items:center;gap:14px;margin-bottom:14px}
 .sprite{flex:0 0 auto;flex-shrink:0;overflow:hidden;image-rendering:pixelated;image-rendering:crisp-edges;background-color:#0d0f13;background-repeat:no-repeat;background-position:0 0;border-radius:12px}
 .fightbar{display:flex;justify-content:center;margin:0 0 18px}
 .fightbtn{appearance:none;width:100%;max-width:280px;padding:12px 18px;border-radius:10px;border:2px solid #e8c56b;background:#6b1d1d;color:#ffe9a3;font-size:16px;font-weight:800;letter-spacing:.14em;cursor:pointer;-webkit-tap-highlight-color:transparent}
 .fightbtn:active{transform:scale(.98);background:#561616}
 .card.waste{border-color:#3d5340}
 .wastegrid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:10px}
 .waste .bits{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;color:#c5cdd8;margin:4px 0;line-height:1.45}
 .waste .flagrow{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}
 .waste .pill{background:#131821;border:1px solid #2a3240;border-radius:999px;padding:4px 10px;font-size:12px;color:#c5cdd8}
 .waste .pill.on{border-color:#c9a36a;color:#f0d59a;background:#2a2316}
 .waste .warn{color:#c9a36a;font-size:12px;line-height:1.45;margin:8px 0 4px}
 .fight-overlay{position:fixed;inset:0;background:rgba(0,0,0,.82);z-index:50;display:flex;align-items:center;justify-content:center;padding:12px;box-sizing:border-box}
 .fight-overlay[hidden]{display:none!important}
 .fight-modal{position:relative;width:100%;max-width:520px;max-height:100vh;max-height:100dvh;overflow:auto;background:#0b0614;border:2px solid #e8c56b;border-radius:16px;padding:8px 12px 12px;box-sizing:border-box;-webkit-overflow-scrolling:touch}
 .fight-toolbar{height:32px;position:relative;margin-bottom:6px}
 .fight-close{position:absolute;top:0;right:0;width:32px;height:32px;border:0;border-radius:8px;background:#2a3240;color:#e8ecf1;font-size:22px;line-height:1;cursor:pointer;z-index:8}
 .fight-stage{position:relative;width:100%;aspect-ratio:16/9;border-radius:10px;overflow:hidden;background:#040014 center/100% 100% no-repeat;image-rendering:auto;box-shadow:inset 0 0 40px rgba(0,0,0,.45)}
 .fight-stage.shake{animation:fightshake .35s}
 .fight-flash{position:absolute;inset:0;background:#fff6c0;opacity:0;pointer-events:none;z-index:7}
 .fight-stage.flash .fight-flash{animation:fightflash .28s}
 @keyframes fightshake{0%,100%{transform:translate(0,0)}20%{transform:translate(-7px,3px)}40%{transform:translate(7px,-4px)}60%{transform:translate(-5px,-2px)}80%{transform:translate(5px,3px)}}
 @keyframes fightflash{0%{opacity:.85}100%{opacity:0}}
 .smash-hud{position:absolute;top:8px;left:8px;right:8px;display:flex;justify-content:space-between;gap:8px;pointer-events:none;z-index:8}
 .p-hud{background:rgba(8,6,18,.78);border:2px solid #e8e8f0;border-radius:8px;padding:4px 10px 3px;min-width:104px;box-shadow:0 2px 0 #000}
 .p-hud.p1{border-color:#7ec8ff}
 .p-hud.p2{border-color:#ffd36b;text-align:right}
 .p-tag{font-size:9px;letter-spacing:.14em;color:#9aa;font-weight:800}
 .p-name{font-size:11px;font-weight:800;letter-spacing:.08em}
 .p-pct{font-size:28px;font-weight:900;font-style:italic;line-height:1;font-family:Impact,Haettenschweiler,Arial Black,sans-serif;color:#fff;text-shadow:2px 2px 0 #000}
 .p-pct.mid{color:#ffe566}
 .p-pct.high{color:#ff9a3c}
 .p-pct.ko{color:#ff3b3b}
 .move-callout{position:absolute;top:38%;left:50%;transform:translate(-50%,0);text-align:center;font-weight:900;letter-spacing:.16em;font-size:14px;color:#fff;text-shadow:0 0 10px #7af,2px 2px 0 #000;z-index:6;pointer-events:none;opacity:0;background:rgba(0,0,0,.45);border-radius:8px;padding:4px 12px;white-space:nowrap}
 .move-callout.show{opacity:1;animation:calloutpopx .3s ease-out}
 @keyframes calloutpop{from{transform:translate(-50%,0) scale(.6);opacity:0}to{transform:translate(-50%,0) scale(1);opacity:1}}
 .fighter{position:absolute;width:0;height:0;z-index:3;pointer-events:none}
 .fighter-art{position:absolute;left:0;bottom:0;background-repeat:no-repeat;image-rendering:pixelated;image-rendering:crisp-edges;transform-origin:var(--ax) var(--ay)}
 .fighter.charging .fighter-art{filter:drop-shadow(0 0 6px #ffe56a) drop-shadow(0 0 14px #39f)}
 .fighter.countering .fighter-art{filter:drop-shadow(0 0 8px #cde) drop-shadow(0 0 14px #8bf)}
 .fighter.ghost .fighter-art{opacity:.35}
 .ko-mark{position:absolute;z-index:6;font-weight:900;letter-spacing:.12em;color:#ff4a4a;font-size:18px;text-shadow:2px 2px 0 #000;opacity:0;pointer-events:none}
 .ko-mark.show{opacity:1;animation:calloutpop .3s ease-out}
 .fx-bolt{position:absolute;width:18px;top:0;height:0;left:50%;margin-left:-9px;background:linear-gradient(#fff,#ffe56a,#fff);box-shadow:0 0 16px 6px #ffe56a,0 0 40px 10px #39f;clip-path:polygon(50% 0,78% 28%,58% 28%,85% 100%,28% 48%,48% 48%,20% 0);opacity:0;z-index:4;pointer-events:none}
 .fx-bolt.show{opacity:1;height:72%}
 .fx-jolt{position:absolute;width:16px;height:16px;border-radius:50%;background:radial-gradient(circle at 35% 35%,#fff,#ffe56a 40%,#39f 70%,transparent 75%);box-shadow:0 0 10px 4px #ffe56a;opacity:0;z-index:4;pointer-events:none;margin-left:-8px;margin-bottom:-8px}
 .fx-jolt.show{opacity:1}
 .fx-slash{position:absolute;width:72px;height:72px;border:4px solid transparent;border-top-color:#fff;border-right-color:#cdefff;border-radius:50%;opacity:0;z-index:4;pointer-events:none;filter:drop-shadow(0 0 6px #fff);margin-left:-36px;margin-bottom:-36px}
 .fx-slash.show{opacity:1;animation:slashpop .35s ease-out}
 @keyframes slashpop{from{transform:scale(.4) rotate(-20deg);opacity:1}to{transform:scale(1.3) rotate(25deg);opacity:0}}
 .fx-cloud{position:absolute;top:16%;width:54px;height:22px;margin-left:-27px;border-radius:20px;background:#e8eef8;box-shadow:18px 4px 0 #cfd8e8,-16px 6px 0 #dfe6f2,0 0 16px #fff;opacity:0;z-index:4;pointer-events:none}
 .fx-cloud.show{opacity:.92}
 .fight-banner{display:none;text-align:center;margin:10px 0 4px;font-size:26px;font-weight:900;letter-spacing:.08em;color:#ffe56a;text-shadow:3px 3px 0 #6b1d1d,0 0 12px rgba(255,229,106,.4);animation:bannerpop .35s ease-out}
 .fight-banner.show{display:block}
 .fight-banner.draw{color:#e8ecf1;text-shadow:3px 3px 0 #2a3240,0 0 12px rgba(200,210,255,.4)}
 .fight-sub{display:none;text-align:center;color:#c5cdd8;font-size:11px;letter-spacing:.12em;font-weight:700;margin-top:2px}
 .fight-sub.show{display:block}
 @keyframes bannerpop{from{transform:scale(.6);opacity:0}to{transform:scale(1);opacity:1}}
 .fight-replay{display:block;margin:12px auto 0;padding:10px 18px;border-radius:999px;border:1px solid #e8c56b;background:#2a3240;color:#ffe9a3;font-weight:700;font-size:14px;cursor:pointer}
 @media (prefers-reduced-motion:reduce){
   .fight-stage.shake,.fight-stage.flash .fight-flash,.fight-banner,.move-callout,.ko-mark,.fx-slash{animation:none!important}
   .sprite{animation:none!important}
 }
 @keyframes idle{from{background-position:0 0}to{background-position:calc(-1 * var(--sheet-w)) 0}}
 .name{font-size:20px;font-weight:700}
 .sub{color:#8b96a5;font-size:13px}
 .stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:12px}
 .stat{background:#131821;border-radius:10px;padding:10px;text-align:center}
 .num{font-size:20px;font-weight:700}
 .lbl{font-size:11px;color:#8b96a5;margin-top:2px}
 .flag{font-size:13px;padding:8px 12px;border-radius:8px;margin-bottom:12px}
 .flag.up{background:#3a2a16;color:#f0b36b}
 .flag.down{background:#16263a;color:#6bb3f0}
 .ranges{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 10px}
 .rangebtn{appearance:none;border:1px solid #2a3240;background:#131821;color:#c5cdd8;border-radius:999px;padding:6px 12px;font-size:12px;cursor:pointer}
 .rangebtn.active{background:#2a3546;border-color:#6b8caf;color:#fff;font-weight:600}
 .chartbox{background:#131821;border-radius:10px;padding:8px}
 .chart{width:100%;height:auto;touch-action:manipulation;display:block}
 .hit{cursor:pointer}
 .axl{fill:#6b7684;font-size:9px}
 .bandlab{fill:#8b96a5;font-size:8px}
 .tipbg{fill:#0b0d11;stroke:#3a4452;stroke-width:1}
 .tiptx{fill:#e8ecf1;font-size:10px;font-weight:600}
 .nochart{color:#6b7684;font-size:13px;text-align:center;padding:30px}
 .last{color:#8b96a5;font-size:12px;margin-top:10px}
 .hinttxt{color:#6b7684;font-size:11px;margin-top:6px}
 .dailynote{color:#c9a36a;font-size:11px;margin-top:6px;min-height:0}
 .caption{color:#6b7684;font-size:11px;margin-top:8px;line-height:1.4}
 .visitlist{margin-top:10px;max-height:220px;overflow:auto;-webkit-overflow-scrolling:touch;border:1px solid #2a3240;border-radius:10px;background:#131821}
 .visit{padding:8px 10px;border-bottom:1px solid #2a3240;font-size:13px}
 .visit:last-child{border-bottom:0}
 .visit .when{color:#e8ecf1;font-weight:600}
 .visit .detail{color:#8b96a5;font-size:12px;margin-top:2px}
 .visit .pee{color:#7ec8e3}
 .visit .poop{color:#d6b07a}
 .empty-list{color:#6b7684;font-size:13px;padding:16px;text-align:center}
</style></head><body><div class="wrap">
 <h1>&#128062; Litter Box Tracker</h1>
 <div class="meta">Updated __UPDATED__ &middot; __NEW__ new visits this run &middot; __TOTAL__ logged</div>
 __WASTE__
 <div class="fightbar"><button type="button" id="fight-btn" class="fightbtn">&#9876; FIGHT</button></div>
 __CARDS__
 <div class="meta">Weights read from the box scale, sorted to the nearest cat. The box can't tell them apart on its own, so an occasional visit may land on the wrong cat.</div>
</div>
<div id="fight-overlay" class="fight-overlay" hidden>
 <div class="fight-modal" role="dialog" aria-modal="true" aria-label="Fight">
  <div class="fight-toolbar"><button type="button" class="fight-close" aria-label="Close">&times;</button></div>
  <div class="fight-stage">
   <div class="smash-hud">
    <div class="p-hud p1"><div class="p-tag">P1</div><div class="p-name">ROMAN</div><div class="p-pct" id="roman-pct">0%</div></div>
    <div class="p-hud p2"><div class="p-tag">P2</div><div class="p-name">MORTY</div><div class="p-pct" id="morty-pct">0%</div></div>
   </div>
   <div class="fighter roman"><div class="fighter-art"></div></div>
   <div class="fighter morty"><div class="fighter-art"></div></div>
   <div class="fx-cloud"></div>
   <div class="fx-bolt"></div>
   <div class="fx-jolt"></div>
   <div class="fx-slash"></div>
   <div class="fight-flash"></div>
   <div class="move-callout"></div>
   <div class="ko-mark roman-ko">KO</div>
   <div class="ko-mark morty-ko">KO</div>
  </div>
  <div class="fight-banner">ROMAN WINS!</div>
  <div class="fight-sub"></div>
  <button type="button" class="fight-replay">Replay</button>
 </div>
</div>
<script>
const CHARTS = __CHARTS__;
const FIGHT = __FIGHT__;
(function(){
 const W=440,H=180,PADL=36,PADR=14,PADT=16,PADB=28;

 function hideAll(){document.querySelectorAll('svg .tip').forEach(function(t){t.style.display='none';});}

 function dailyAvg(visits){
  const map={};
  visits.forEach(function(v){ (map[v.day]=map[v.day]||[]).push(v); });
  const days=Object.keys(map).sort();
  return days.map(function(day){
   const vs=map[day];
   const w=vs.reduce(function(s,v){return s+v.w;},0)/vs.length;
   const mid=vs[Math.floor(vs.length/2)];
   const months=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
   const p=day.split('-');
   const label=months[parseInt(p[1],10)-1]+' '+parseInt(p[2],10)+' (daily avg) \u2022 '+w.toFixed(2)+' lb \u2022 '+vs.length+' visit'+(vs.length===1?'':'s');
   return {ts:mid.ts,w:w,daily:true,n:vs.length,label:label};
  });
 }

 function tipLabel(p){
  if(p.label) return p.label;
  return p.when+' \u2022 '+p.w.toFixed(2)+' lb \u2022 '+p.dur_txt+' \u2022 '+p.icon+' '+p.gtext;
 }

 function draw(card){
  const name=card.getAttribute('data-cat');
  const data=CHARTS[name];
  const btn=card.querySelector('.rangebtn.active');
  const days=parseInt(btn.getAttribute('data-days'),10);
  const cutoff=(Date.now()/1000) - days*86400;
  const visits=data.visits.filter(function(v){return v.ts>=cutoff;});
  const note=card.querySelector('.dailynote');
  let points=visits, daily=false;
  if(visits.length>50){ points=dailyAvg(visits); daily=true; }
  note.textContent=daily?'Showing daily averages \u2014 list below still has each visit.':'';

  const svg=card.querySelector('svg.chart');
  const now=Date.now()/1000;
  const xmin=now-days*86400, xmax=now;
  let ymin=data.band[0]-0.2, ymax=data.band[1]+0.2;
  points.forEach(function(p){ ymin=Math.min(ymin,p.w-0.2); ymax=Math.max(ymax,p.w+0.2); });
  if(ymax-ymin<0.6){ const mid=(ymin+ymax)/2; ymin=mid-0.3; ymax=mid+0.3; }

  function X(t){ return PADL + (t-xmin)/((xmax-xmin)||1)*(W-PADL-PADR); }
  function Y(y){ return H-PADB - (y-ymin)/((ymax-ymin)||1)*(H-PADT-PADB); }

  const yBand1=Y(data.band[1]), yBand0=Y(data.band[0]);
  const bandH=Math.max(2, yBand0-yBand1);
  const start=new Date((xmin)*1000);
  const end=new Date(xmax*1000);
  function md(d){ return d.toLocaleDateString('en-US',{month:'short',day:'numeric',timeZone:'America/New_York'}); }

  let dots='';
  points.forEach(function(p){
   const cx=X(p.ts), cy=Y(p.w);
   const label=tipLabel(p);
   dots += '<circle cx="'+cx.toFixed(1)+'" cy="'+cy.toFixed(1)+'" r="3.2" fill="'+data.color+'" stroke="#e8ecf1" stroke-width="0.8"/>';
   dots += '<circle class="hit" cx="'+cx.toFixed(1)+'" cy="'+cy.toFixed(1)+'" r="12" fill="transparent" data-label="'+
     label.replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;')+
     '" data-cx="'+cx.toFixed(1)+'" data-cy="'+cy.toFixed(1)+'"/>';
  });

  const inner = points.length===0
    ? '<text x="'+ (W/2) +'" y="'+ (H/2) +'" class="axl" text-anchor="middle">No visits in this range</text>'
    : dots;

  svg.innerHTML =
    '<rect x="'+PADL.toFixed(1)+'" y="'+yBand1.toFixed(1)+'" width="'+(W-PADL-PADR)+'" height="'+bandH.toFixed(1)+'" fill="'+data.color+'" opacity="0.18"/>' +
    '<line x1="'+PADL+'" y1="'+Y(data.median).toFixed(1)+'" x2="'+(W-PADR)+'" y2="'+Y(data.median).toFixed(1)+'" stroke="'+data.color+'" stroke-width="1" stroke-dasharray="3 3" opacity="0.7"/>' +
    inner +
    '<text x="'+PADL+'" y="12" class="axl">'+ymax.toFixed(1)+' lb</text>' +
    '<text x="'+(W-PADR)+'" y="12" class="axl" text-anchor="end">usual '+data.band[0].toFixed(2)+'\u2013'+data.band[1].toFixed(2)+'</text>' +
    '<text x="'+PADL+'" y="'+(H-PADB+16)+'" class="axl">'+md(start)+'</text>' +
    '<text x="'+(W-PADR)+'" y="'+(H-PADB+16)+'" class="axl" text-anchor="end">'+md(end)+'</text>' +
    '<g class="tip" style="display:none"><rect class="tipbg" rx="4" x="0" y="0" width="10" height="10"/><text class="tiptx" x="0" y="0"></text></g>';

  svg.querySelectorAll('.hit').forEach(function(h){
   h.addEventListener('click',function(e){e.stopPropagation();show(h);});
   h.addEventListener('mouseenter',function(){show(h);});
  });

  const list=card.querySelector('.visitlist');
  if(visits.length===0){
   list.innerHTML='<div class="empty-list">No visits in this range</div>';
  } else {
   const newest=visits.slice().reverse();
   list.innerHTML=newest.map(function(v){
    return '<div class="visit"><div class="when">'+v.when+'</div><div class="detail">'+
      v.w.toFixed(2)+' lb \u00b7 '+v.dur_txt+' \u00b7 <span class="'+v.guess+'">'+v.icon+' '+v.gtext+'</span></div></div>';
   }).join('');
  }
 }

 function show(hit){
  var svg=hit.ownerSVGElement;var tip=svg.querySelector('.tip');
  var tx=tip.querySelector('.tiptx');var bg=tip.querySelector('.tipbg');
  hideAll();
  tx.textContent=hit.getAttribute('data-label');
  var cx=parseFloat(hit.getAttribute('data-cx'));var cy=parseFloat(hit.getAttribute('data-cy'));
  tip.style.display='';
  var b=tx.getBBox();var padx=6,pady=4;
  var wbox=b.width+padx*2, hbox=b.height+pady*2;
  var x=cx-wbox/2; var vb=svg.viewBox.baseVal;
  if(x<2)x=2; if(x+wbox>vb.width-2)x=vb.width-2-wbox;
  var y=cy-hbox-8; if(y<2)y=cy+10;
  bg.setAttribute('x',x);bg.setAttribute('y',y);
  bg.setAttribute('width',wbox);bg.setAttribute('height',hbox);
  tx.setAttribute('x',x+padx);tx.setAttribute('y',y+pady+b.height*0.8);
 }

 document.querySelectorAll('.card').forEach(function(card){
  if(!card.querySelector('svg.chart')) return;
  card.querySelectorAll('.rangebtn').forEach(function(btn){
   btn.addEventListener('click',function(e){
    e.stopPropagation();
    card.querySelectorAll('.rangebtn').forEach(function(b){b.classList.remove('active');});
    btn.classList.add('active');
    hideAll();
    draw(card);
   });
  });
  draw(card);
 });
 document.addEventListener('click',hideAll);
})();
(function(){
 const overlay=document.getElementById('fight-overlay');
 if(!overlay||!FIGHT||!FIGHT.roman) return;
 const reduce=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;
 const stage=overlay.querySelector('.fight-stage');
 const banner=overlay.querySelector('.fight-banner');
 const sub=overlay.querySelector('.fight-sub');
 const callout=overlay.querySelector('.move-callout');
 const flashEl=overlay.querySelector('.fight-flash');
 const bolt=overlay.querySelector('.fx-bolt');
 const jolt=overlay.querySelector('.fx-jolt');
 const slash=overlay.querySelector('.fx-slash');
 const cloud=overlay.querySelector('.fx-cloud');
 const romanEl=overlay.querySelector('.fighter.roman');
 const mortyEl=overlay.querySelector('.fighter.morty');
 const romanArt=romanEl.querySelector('.fighter-art');
 const mortyArt=mortyEl.querySelector('.fighter-art');
 const rPct=document.getElementById('roman-pct');
 const mPct=document.getElementById('morty-pct');
 const romanKo=overlay.querySelector('.ko-mark.roman-ko');
 const mortyKo=overlay.querySelector('.ko-mark.morty-ko');
 const ghosts=[];

 stage.style.backgroundImage='url(data:image/jpeg;base64,'+FIGHT.stage+')';

 function prepFighter(el, art, meta, face){
  const d=meta.display||1;
  const w=meta.sprite_w*d, h=meta.sprite_h*d;
  const ax=(meta.anchor_x||0.42), ay=(meta.anchor_y||1);
  art.style.width=w+'px';
  art.style.height=h+'px';
  art.style.backgroundImage='url(data:image/png;base64,'+meta.sheet+')';
  art.style.backgroundSize=(w*meta.frames)+'px '+h+'px';
  art.style.backgroundRepeat='no-repeat';
  art.style.setProperty('--ax', (ax*100)+'%');
  art.style.setProperty('--ay', (ay*100)+'%');
  art.style.marginLeft=(-(ax*w))+'px';
  art.style.marginBottom=(-((1-ay)*h))+'px';
  art.dataset.face=String(face);
  art.dataset.w=String(w);
  art.dataset.frames=String(meta.frames);
 }

 prepFighter(romanEl, romanArt, FIGHT.roman, 1);
 prepFighter(mortyEl, mortyArt, FIGHT.morty, -1);

 const OUTCOMES=[
  {
   id:'dolphin-slash', banner:'ROMAN WINS!', sub:'DOLPHIN SLASH', winner:'roman',
   keys:[
    {t:0, r:{x:26,y:0,rot:0,frame:0}, m:{x:74,y:0,rot:0,frame:0}, rp:0, mp:0},
    {t:180, callout:'DOLPHIN SLASH', r:{x:26,y:-4,rot:-16,frame:0}},
    {t:420, r:{x:40,y:28,rot:-42,frame:1}},
    {t:680, r:{x:56,y:48,rot:-8,frame:3}},
    {t:720, impact:1, slash:{x:66,y:36}, mp:52, m:{x:80,y:28,rot:24,frame:2}},
    {t:980, mp:104, m:{x:86,y:62,rot:90,frame:4}, r:{x:52,y:20,rot:0,frame:3}},
    {t:1500, mp:124, m:{x:88,y:18,rot:140,frame:5}},
    {t:2000, r:{x:48,y:0,rot:0,frame:3}, m:{x:84,y:-4,rot:95,frame:6}, ko:'morty'},
    {t:2500, banner:1}
   ]
  },
  {
   id:'skull-bash', banner:'MORTY WINS!', sub:'SKULL BASH', winner:'morty',
   keys:[
    {t:0, r:{x:26,y:0,rot:0,frame:0}, m:{x:74,y:0,rot:0,frame:0}, rp:0, mp:0},
    {t:200, callout:'SKULL BASH', charge:'morty', m:{x:76,y:0,rot:8,frame:2,scale:1.05}},
    {t:800, charge:'morty', m:{x:74,y:2,rot:0,frame:3,scale:1.12}},
    {t:920, afterimage:'morty', m:{x:42,y:10,rot:-16,frame:1,scale:1.18}},
    {t:1080, impact:1, slash:{x:32,y:16}, rp:48, r:{x:16,y:22,rot:-28,frame:0}, m:{x:34,y:6,rot:-8,frame:1,scale:1.1}},
    {t:1280, rp:112, r:{x:8,y:54,rot:-80,frame:0}, m:{x:36,y:0,rot:0,frame:0,scale:1}},
    {t:1800, rp:138, r:{x:8,y:16,rot:-120,frame:0}},
    {t:2200, r:{x:10,y:-4,rot:-95,frame:0}, m:{x:40,y:0,rot:0,frame:0}, ko:'roman'},
    {t:2600, banner:1}
   ]
  },
  {
   id:'double-ko', banner:'DRAW!', sub:'SHIELD BREAKER  VS  THUNDER', winner:'draw',
   keys:[
    {t:0, r:{x:26,y:0,rot:0,frame:0}, m:{x:74,y:0,rot:0,frame:0}, rp:0, mp:0},
    {t:180, callout:'SHIELD BREAKER', r:{x:24,y:0,rot:8,frame:0}, counter:'roman'},
    {t:420, callout:'THUNDER', cloud:{x:50,show:1}, m:{x:74,y:0,rot:0,frame:2}},
    {t:900, r:{x:42,y:4,rot:0,frame:2}, bolt:{x:50,show:1}},
    {t:1050, impact:1, slash:{x:50,y:20}, rp:78, mp:78, r:{x:38,y:24,rot:-20,frame:2}, m:{x:62,y:24,rot:20,frame:4}},
    {t:1250, rp:148, mp:148, r:{x:12,y:56,rot:-70,frame:0}, m:{x:88,y:56,rot:70,frame:4}, bolt:{show:0}, cloud:{show:0}},
    {t:1900, r:{x:10,y:14,rot:-110,frame:0}, m:{x:90,y:14,rot:110,frame:6}},
    {t:2400, r:{x:12,y:-4,rot:-95,frame:0}, m:{x:88,y:-4,rot:95,frame:6}, ko:'both'},
    {t:2800, banner:1}
   ]
  },
  {
   id:'shield-breaker', banner:'ROMAN WINS!', sub:'SHIELD BREAKER', winner:'roman',
   keys:[
    {t:0, r:{x:26,y:0,rot:0,frame:0}, m:{x:74,y:0,rot:0,frame:0}, rp:0, mp:0},
    {t:200, callout:'SHIELD BREAKER', counter:'roman', r:{x:24,y:0,rot:6,frame:0}},
    {t:700, r:{x:44,y:4,rot:0,frame:2}},
    {t:880, impact:1, slash:{x:66,y:16}, mp:38, m:{x:86,y:20,rot:16,frame:1}},
    {t:1100, mp:92, m:{x:110,y:48,rot:28,frame:2}},
    {t:1500, mp:128, m:{x:138,y:90,rot:80,frame:4,scale:0.85}},
    {t:2000, r:{x:46,y:0,rot:0,frame:2}, m:{x:160,y:130,rot:120,frame:4,scale:0.55}, ko:'morty'},
    {t:2300, banner:1}
   ]
  },
  {
   id:'thunder', banner:'MORTY WINS!', sub:'THUNDER', winner:'morty',
   keys:[
    {t:0, r:{x:26,y:0,rot:0,frame:0}, m:{x:74,y:0,rot:0,frame:0}, rp:0, mp:0},
    {t:160, callout:'THUNDER JOLT', jolt:{x:70,y:8,show:1}, m:{x:74,y:0,rot:0,frame:1}},
    {t:360, jolt:{x:56,y:28,show:1}},
    {t:520, jolt:{x:44,y:4,show:1}},
    {t:680, jolt:{x:30,y:22,show:1}, impact:1, rp:16, r:{x:24,y:0,rot:10,frame:0}},
    {t:740, jolt:{show:0}},
    {t:860, callout:'QUICK ATTACK', afterimage:'morty', m:{x:50,y:40,frame:0}},
    {t:1020, afterimage:'morty', m:{x:28,y:8,frame:1}, impact:1, rp:40, r:{x:20,y:8,rot:-12,frame:0}},
    {t:1180, m:{x:62,y:0,frame:0}},
    {t:1320, callout:'THUNDER', cloud:{x:28,show:1}, m:{x:64,y:0,frame:2}},
    {t:1600, bolt:{x:28,show:1}, impact:1, rp:78, r:{x:22,y:16,rot:-20,frame:0}},
    {t:1760, rp:158, r:{x:12,y:58,rot:-90,frame:0}, bolt:{show:0}, cloud:{show:0}},
    {t:2300, r:{x:14,y:-4,rot:-100,frame:0}, m:{x:62,y:0,rot:0,frame:0}, ko:'roman'},
    {t:2700, banner:1}
   ]
  }
 ];

 let raf=0, playing=false, t0=0, current=null, lastImpact=0;

 function lerp(a,b,t){ return a+(b-a)*t; }
 function ease(t){ return t<.5 ? 2*t*t : 1-Math.pow(-2*t+2,2)/2; }

 function carry(keys){
  var r={x:26,y:0,rot:0,frame:0,scale:1,face:1};
  var m={x:74,y:0,rot:0,frame:0,scale:1,face:-1};
  return keys.map(function(k){
   if(k.r) r=Object.assign({},r,k.r);
   if(k.m) m=Object.assign({},m,k.m);
   return Object.assign({},k,{r:Object.assign({},r),m:Object.assign({},m)});
  });
 }
 function mergeState(prev, next, t){
  const o={};
  ['x','y','rot','scale'].forEach(function(k){
   const a=prev&&prev[k], b=next&&next[k];
   if(a==null && b==null) return;
   const av=a==null?(k==='scale'?1:0):a;
   const bv=b==null?av:b;
   o[k]=lerp(av,bv,t);
  });
  o.frame=(t<1 && prev && prev.frame!=null)?prev.frame:((next&&next.frame!=null)?next.frame:(prev&&prev.frame)||0);
  o.face=(next&&next.face!=null)?next.face:((prev&&prev.face)!=null?prev.face:null);
  return o;
 }

 function setFrame(art, frame){
  const w=parseFloat(art.dataset.w)||0;
  art.style.backgroundPosition=(-frame*w)+'px 0';
 }

 function place(el, art, st, defaultFace){
  const face=st.face!=null?st.face:defaultFace;
  const sc=st.scale!=null?st.scale:1;
  el.style.left=st.x+'%';
  el.style.bottom='calc(31.1% + '+(st.y||0)+'px)';
  art.style.transform='rotate('+(st.rot||0)+'deg) scale('+(face*sc)+','+sc+')';
  if(st.frame!=null) setFrame(art, st.frame);
 }

 function setPct(node, v){
  v=Math.max(0, Math.round(v));
  node.textContent=v+'%';
  node.classList.remove('mid','high','ko');
  if(v>=150) node.classList.add('ko');
  else if(v>=100) node.classList.add('high');
  else if(v>=50) node.classList.add('mid');
 }

 function showFx(el, on){
  if(!el) return;
  if(on) el.classList.add('show'); else el.classList.remove('show');
 }

 function placeAbs(el, xPct, yPx){
  el.style.left=xPct+'%';
  el.style.bottom='calc(31.1% + '+(yPx||0)+'px)';
 }

 function clearGhosts(){
  ghosts.forEach(function(g){ if(g.parentNode) g.parentNode.removeChild(g); });
  ghosts.length=0;
 }

 function spawnGhost(fromEl, fromArt, meta){
  const g=fromEl.cloneNode(true);
  g.classList.add('ghost');
  g.style.opacity='';
  stage.appendChild(g);
  ghosts.push(g);
  setTimeout(function(){ if(g.parentNode) g.parentNode.removeChild(g); }, 280);
 }

 function juice(){
  if(reduce) return;
  stage.classList.remove('shake','flash');
  void stage.offsetWidth;
  stage.classList.add('shake','flash');
 }

 function resetFx(){
  showFx(callout,false);
  showFx(bolt,false);
  showFx(jolt,false);
  showFx(slash,false);
  showFx(cloud,false);
  showFx(romanKo,false);
  showFx(mortyKo,false);
  showFx(banner,false);
  showFx(sub,false);
  romanEl.classList.remove('charging','countering');
  mortyEl.classList.remove('charging','countering');
  stage.classList.remove('shake','flash');
  clearGhosts();
  banner.classList.remove('draw');
 }

 function lastKey(keys, field, now){
  let found=null;
  for(let i=0;i<keys.length;i++){
   if(keys[i].t<=now && keys[i][field]!=null) found=keys[i];
  }
  return found;
 }

 function applyAt(outcome, now, impactsOk){
  const keys=outcome.keys;
  let i=0;
  while(i+1<keys.length && keys[i+1].t<=now) i++;
  const a=keys[i], b=keys[Math.min(i+1,keys.length-1)];
  const span=Math.max(1, b.t-a.t);
  const t=b===a?1:ease(Math.max(0, Math.min(1, (now-a.t)/span)));
  const r=mergeState(a.r||{}, b.r||{}, t);
  const m=mergeState(a.m||{}, b.m||{}, t);
  place(romanEl, romanArt, r, 1);
  place(mortyEl, mortyArt, m, -1);

  const rpKeyA=lastKey(keys,'rp',now), rpKeyB=keys.find(function(k,idx){return idx>0 && k.t>now && k.rp!=null;});
  // step percents to the last reached key (Smash meters jump on hit, with a short lerp)
  let rp=0, mp=0;
  let prevRp=0, prevMp=0, rpT=0, mpT=0, rpFrom=0, mpFrom=0;
  keys.forEach(function(k){
   if(k.rp!=null){
     if(k.t<=now){ prevRp=rp; rp=k.rp; rpFrom=prevRp; rpT=k.t; }
   }
   if(k.mp!=null){
     if(k.t<=now){ prevMp=mp; mp=k.mp; mpFrom=prevMp; mpT=k.t; }
   }
  });
  setPct(rPct, rp);
  setPct(mPct, mp);

  const co=lastKey(keys,'callout',now);
  if(co && now-co.t<700){ callout.textContent=co.callout; showFx(callout,true); }
  else showFx(callout,false);

  const sl=lastKey(keys,'slash',now);
  if(sl && sl.slash && now-sl.t<360){ placeAbs(slash, sl.slash.x, sl.slash.y); showFx(slash,true); }
  else showFx(slash,false);

  const jt=lastKey(keys,'jolt',now);
  if(jt && jt.jolt && jt.jolt.show){ placeAbs(jolt, jt.jolt.x, jt.jolt.y); showFx(jolt,true); }
  else showFx(jolt,false);

  const bl=lastKey(keys,'bolt',now);
  if(bl && bl.bolt && bl.bolt.show){ bolt.style.left=bl.bolt.x+'%'; showFx(bolt,true); }
  else showFx(bolt,false);

  const cl=lastKey(keys,'cloud',now);
  if(cl && cl.cloud && cl.cloud.show){ cloud.style.left=cl.cloud.x+'%'; showFx(cloud,true); }
  else showFx(cloud,false);

  romanEl.classList.toggle('countering', !!(lastKey(keys,'counter',now) && lastKey(keys,'counter',now).counter==='roman' && now-(lastKey(keys,'counter',now).t)<900));
  mortyEl.classList.toggle('charging', !!(lastKey(keys,'charge',now) && lastKey(keys,'charge',now).charge==='morty' && now-(lastKey(keys,'charge',now).t)<900));

  const ko=lastKey(keys,'ko',now);
  showFx(romanKo, !!(ko && (ko.ko==='roman'||ko.ko==='both')));
  showFx(mortyKo, !!(ko && (ko.ko==='morty'||ko.ko==='both')));
  if(ko && (ko.ko==='roman'||ko.ko==='both')){
    romanKo.style.left='calc('+(r.x)+'% - 16px)';
    romanKo.style.bottom='calc(31.1% + '+((r.y||0)+40)+'px)';
  }
  if(ko && (ko.ko==='morty'||ko.ko==='both')){
    mortyKo.style.left='calc('+(m.x)+'% - 16px)';
    mortyKo.style.bottom='calc(31.1% + '+((m.y||0)+40)+'px)';
  }

  if(impactsOk){
   keys.forEach(function(k){
    if(k.impact && k.t<=now && k.t>lastImpact-10 && now-k.t<50){
     lastImpact=k.t;
     juice();
    }
    if(k.afterimage && k.t<=now && now-k.t<40){
     spawnGhost(k.afterimage==='morty'?mortyEl:romanEl, null, null);
    }
   });
  }

  if(lastKey(keys,'banner',now)){
   banner.textContent=outcome.banner;
   banner.classList.toggle('draw', outcome.winner==='draw');
   showFx(banner,true);
   sub.textContent=outcome.sub||'';
   showFx(sub,true);
  } else {
   showFx(banner,false);
   showFx(sub,false);
  }
 }

 function endTime(outcome){
  return outcome.keys[outcome.keys.length-1].t+400;
 }

 function pickOutcome(id){
  if(id){
   for(let i=0;i<OUTCOMES.length;i++) if(OUTCOMES[i].id===id) return OUTCOMES[i];
  }
  return OUTCOMES[Math.floor(Math.random()*OUTCOMES.length)];
 }

 function stop(){
  playing=false;
  if(raf){ cancelAnimationFrame(raf); raf=0; }
 }

 function tick(now){
  if(!playing||!current) return;
  const t=now-t0;
  applyAt(current, t, true);
  if(t>=endTime(current)){ playing=false; applyAt(current, endTime(current), false); return; }
  raf=requestAnimationFrame(tick);
 }

 function play(optId, seek, paused){
  stop();
  resetFx();
  lastImpact=-999;
  current=pickOutcome(optId);
  current=Object.assign({},current,{keys:carry(current.keys)});
  const last=endTime(current);
  if(reduce){
   applyAt(current, last, false);
   banner.textContent=current.banner;
   banner.classList.toggle('draw', current.winner==='draw');
   showFx(banner,true);
   sub.textContent=current.sub||'';
   showFx(sub,true);
   return;
  }
  if(paused && seek!=null){
   applyAt(current, seek, false);
   // If the seek is at/after the banner, show it
   playing=false;
   return;
  }
  playing=true;
  const startSeek=seek||0;
  t0=performance.now()-startSeek;
  raf=requestAnimationFrame(tick);
 }

 function openFight(optId, seek, paused){
  overlay.hidden=false;
  document.body.style.overflow='hidden';
  play(optId, seek, paused);
 }
 function closeFight(){
  stop();
  resetFx();
  overlay.hidden=true;
  document.body.style.overflow='';
 }

 document.getElementById('fight-btn').addEventListener('click', function(e){ e.preventDefault(); e.stopPropagation(); openFight(); });
 overlay.querySelector('.fight-close').addEventListener('click', function(e){ e.preventDefault(); e.stopPropagation(); closeFight(); });
 overlay.querySelector('.fight-replay').addEventListener('click', function(e){ e.preventDefault(); e.stopPropagation(); play(); });
 overlay.addEventListener('click', function(e){ if(e.target===overlay) closeFight(); });

 const params=new URLSearchParams(location.search);
 if(params.get('fight')){
  const id=params.get('fight');
  const at=params.get('at')!=null?parseInt(params.get('at'),10):null;
  const paused=params.get('pause')==='1' || at!=null;
  openFight(id==='1'?null:id, isNaN(at)?null:at, paused);
 }
})();
</script>
</body></html>
"""


if __name__ == "__main__":
    main()
