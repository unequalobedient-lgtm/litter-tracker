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
    rf, mf = meta["roman_fight"], meta["morty_fight"]
    def pack(info, display=1):
        return {
            "sheet": b64(ASSETS / info["file"]),
            "sprite_w": info["sprite_w"],
            "sprite_h": info["sprite_h"],
            "frames": info["frames"],
            "anchor_x": info["anchor_x"],
            "anchor_y": info["anchor_y"],
            "display": display,
        }
    return {
        "stage": b64(ASSETS / "omega_stage.jpg"),
        "roman": pack(rf, 1),
        "morty": pack(mf, 1),
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
 .fight-modal{position:relative;width:100%;max-width:520px;max-height:100vh;max-height:100dvh;overflow:auto;background:#0b0614;border:2px solid #e8c56b;border-radius:16px;padding:8px 12px 12px;box-sizing:border-box;-webkit-overflow-scrolling:touch;container-type:inline-size;container-name:fightmodal;-webkit-text-size-adjust:100%;text-size-adjust:100%}
 .fight-toolbar{height:32px;position:relative;margin-bottom:6px}
 .fight-close{position:absolute;top:0;right:0;width:32px;height:32px;border:0;border-radius:8px;background:#2a3240;color:#e8ecf1;font-size:22px;line-height:1;cursor:pointer;z-index:8}
 .fight-stage{position:relative;width:100%;aspect-ratio:16/9;border-radius:10px;overflow:hidden;background:#040014 center/100% 100% no-repeat;image-rendering:auto;box-shadow:inset 0 0 40px rgba(0,0,0,.45);container-type:size;container-name:fight}
 .fight-world{position:absolute;left:0;top:0;width:492px;height:276.75px;transform-origin:0 0;transform:scale(calc(100cqw / 492));-webkit-text-size-adjust:100%;text-size-adjust:100%}
 .fight-stage.shake{animation:fightshake .35s}
 .fight-flash{position:absolute;inset:0;background:#fff6c0;opacity:0;pointer-events:none;z-index:7}
 .fight-stage.flash .fight-flash{animation:fightflash .28s}
 @keyframes fightshake{0%,100%{transform:translate(0,0)}20%{transform:translate(-7px,3px)}40%{transform:translate(7px,-4px)}60%{transform:translate(-5px,-2px)}80%{transform:translate(5px,3px)}}
 @keyframes fightflash{0%{opacity:.85}100%{opacity:0}}
 .smash-hud{position:absolute;bottom:6px;left:8px;right:8px;display:flex;justify-content:space-between;gap:8px;pointer-events:none;z-index:8}
 .p-hud{background:rgba(8,6,18,.82);border:2px solid #e8e8f0;border-radius:8px;padding:3px 10px 2px;min-width:100px;max-width:38%;box-sizing:border-box;flex:0 1 auto;box-shadow:0 2px 0 #000;-webkit-text-size-adjust:100%;text-size-adjust:100%}
 .p-hud.p1{border-color:#7ec8ff}
 .p-hud.p2{border-color:#ffd36b;text-align:right}
 .p-tag{font-size:9px;letter-spacing:.14em;color:#9aa;font-weight:800}
 .p-name{font-size:11px;font-weight:800;letter-spacing:.08em}
 .p-pct{font-size:28px;font-weight:900;font-style:italic;line-height:1;font-family:Impact,Haettenschweiler,Arial Black,sans-serif;color:#fff;text-shadow:2px 2px 0 #000}
 .p-pct.mid{color:#ffe566}
 .p-pct.high{color:#ff9a3c}
 .p-pct.ko{color:#ff3b3b}
 .p-pct.pop{animation:pctpop .18s ease-out}
 @keyframes pctpop{from{transform:scale(1.35)}to{transform:scale(1)}}
 .move-callout{position:absolute;top:16%;left:50%;transform:translate(-50%,0);text-align:center;font-weight:900;letter-spacing:.16em;font-size:13px;color:#fff;text-shadow:0 0 10px #7af,2px 2px 0 #000;z-index:6;pointer-events:none;opacity:0;background:rgba(0,0,0,.5);border-radius:8px;padding:4px 12px;white-space:nowrap}
 .move-callout.show{opacity:1;animation:calloutpopx .3s ease-out}
 @keyframes calloutpop{from{transform:scale(.6);opacity:0}to{transform:scale(1);opacity:1}}
 @keyframes calloutpopx{from{transform:translate(-50%,0) scale(.6);opacity:0}to{transform:translate(-50%,0) scale(1);opacity:1}}
 .fighter{position:absolute;width:0;height:0;z-index:3;pointer-events:none}
 .fighter-art{position:absolute;left:0;bottom:0;background-repeat:no-repeat;image-rendering:pixelated;image-rendering:crisp-edges;transform-origin:var(--ax) var(--ay)}
 .fighter.sparking .fighter-art{filter:drop-shadow(0 0 6px #ffe56a) drop-shadow(0 0 12px #39f)}
.fighter.countering .fighter-art{filter:drop-shadow(0 0 8px #e8f0ff) drop-shadow(0 0 16px #8bf)}
 .fighter.ghost{opacity:.4;z-index:2}
 .ko-mark{position:absolute;z-index:6;font-weight:900;letter-spacing:.14em;color:#ff4a4a;font-size:18px;text-shadow:2px 2px 0 #000;opacity:0;pointer-events:none}
 .ko-mark.show{opacity:1;animation:calloutpop .3s ease-out}
 .blade-trail{position:absolute;width:90px;height:16px;border-radius:6px 40px 40px 6px;opacity:0;z-index:4;pointer-events:none;transform-origin:10% 50%;filter:blur(.3px)}
 .blade-trail.red{background:linear-gradient(90deg,transparent,#ff3a3a 25%,#ffd0d0);box-shadow:0 0 12px #f33}
 .blade-trail.green{background:linear-gradient(90deg,transparent,#3dff6b 25%,#d0ffd8);box-shadow:0 0 12px #3d6}
 .blade-trail.blue{background:linear-gradient(90deg,transparent,#3da9ff 25%,#d0e8ff);box-shadow:0 0 12px #3af}
 .blade-trail.white{background:linear-gradient(90deg,transparent,#fff 20%,#ffe56a);box-shadow:0 0 16px #fff,0 0 28px #ffe56a}
 .blade-trail.show{opacity:1;animation:trailfade .32s ease-out forwards}
 @keyframes trailfade{0%{opacity:1;transform:scaleX(.6)}100%{opacity:0;transform:scaleX(1.15)}}
 .dolphin-arc{position:absolute;width:70px;height:90px;border:3px solid transparent;border-left-color:#7cf;border-top-color:#cfefff;border-radius:50%;opacity:0;z-index:4;pointer-events:none;filter:drop-shadow(0 0 8px #4af);transform-origin:50% 100%}
 .dolphin-arc.show{opacity:1;animation:dolphinarce .45s ease-out forwards}
 @keyframes dolphinarce{0%{opacity:1;transform:rotate(-20deg) scale(.7)}100%{opacity:0;transform:rotate(20deg) scale(1.15)}}
 .tipper-spark{position:absolute;width:52px;height:52px;margin-left:-26px;margin-bottom:-26px;background:radial-gradient(circle,#fff 0 18%,#ffe56a 38%,transparent 70%);box-shadow:0 0 18px 8px #fff,0 0 36px 12px #ffe56a;opacity:0;z-index:5;pointer-events:none}
 .tipper-spark.show{opacity:1;animation:sparkpop .4s ease-out forwards}
 @keyframes sparkpop{0%{transform:scale(.3);opacity:1}100%{transform:scale(1.8);opacity:0}}
 .qa-streak{position:absolute;height:4px;border-radius:4px;background:linear-gradient(90deg,transparent,#fff,#ffe56a,#fff,transparent);box-shadow:0 0 8px #ffe56a;opacity:0;z-index:4;pointer-events:none;transform-origin:0 50%}
 .qa-streak.show{opacity:.95;animation:qafade .28s ease-out forwards}
 @keyframes qafade{0%{opacity:.95}100%{opacity:0}}
 .fx-bolt{position:absolute;width:28px;top:0;height:0;margin-left:-14px;opacity:0;z-index:4;pointer-events:none;filter:drop-shadow(0 0 8px #fff) drop-shadow(0 0 18px #4af) drop-shadow(0 0 28px #ffe56a)}
 .fx-bolt.show{opacity:1;height:70%}
 .bolt-core{width:100%;height:100%;background:linear-gradient(#fff 0%,#cfe9ff 25%,#7cf 55%,#ffe56a 100%);clip-path:polygon(48% 0,72% 16%,56% 16%,88% 46%,60% 46%,78% 100%,28% 52%,50% 52%,22% 24%,44% 24%)}
 .fx-jolt{position:absolute;width:18px;height:18px;border-radius:50%;background:radial-gradient(circle at 35% 35%,#fff,#ffe56a 40%,#39f 70%,transparent 75%);box-shadow:0 0 12px 5px #ffe56a;opacity:0;z-index:4;pointer-events:none;margin-left:-9px;margin-bottom:-9px}
 .fx-jolt.show{opacity:1}
 .fx-cloud{position:absolute;top:4%;width:58px;height:20px;margin-left:-29px;border-radius:20px;background:#e8eef8;box-shadow:16px 4px 0 #cfd8e8,-14px 5px 0 #dfe6f2,0 0 16px #fff;opacity:0;z-index:4;pointer-events:none}
 .fx-cloud.show{opacity:.92}
 .blast{position:absolute;width:90px;height:90px;margin-left:-45px;margin-top:-45px;border-radius:50%;background:radial-gradient(circle,#fff 0 8%,#ffe56a 18%,#ff6a3a 40%,transparent 70%);opacity:0;z-index:6;pointer-events:none}
 .blast.show{animation:blastpop .5s ease-out forwards}
 @keyframes blastpop{0%{transform:scale(.4);opacity:1}100%{transform:scale(1.6);opacity:0}}
 .fight-banner{display:none;text-align:center;margin:2cqi 0 0.8cqi;font-size:clamp(16px,5cqi,26px);font-weight:900;letter-spacing:.08em;color:#ffe56a;text-shadow:3px 3px 0 #6b1d1d,0 0 12px rgba(255,229,106,.4);animation:bannerpop .35s ease-out}
 .fight-banner.show{display:block}
  .fight-sub,.move-callout{display:none!important}
 @keyframes bannerpop{from{transform:scale(.6);opacity:0}to{transform:scale(1);opacity:1}}
 .fight-replay{display:block;margin:2.3cqi auto 0;padding:2cqi 3.5cqi;border-radius:999px;border:1px solid #e8c56b;background:#2a3240;color:#ffe9a3;font-weight:700;font-size:clamp(12px,2.7cqi,14px);cursor:pointer}
 @media (prefers-reduced-motion:reduce){
   .fight-stage.shake,.fight-stage.flash .fight-flash,.fight-banner,.move-callout,.ko-mark,.blade-trail,.tipper-spark,.dolphin-arc,.qa-streak,.blast,.p-pct.pop{animation:none!important}
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
   <div class="fight-world">
   <div class="fighter roman"><div class="fighter-art"></div></div>
   <div class="fighter morty"><div class="fighter-art"></div></div>
   <div class="blade-trail"></div>
   <div class="dolphin-arc"></div>
   <div class="tipper-spark"></div>
   <div class="qa-streak"></div>
   <div class="fx-cloud"></div>
   <div class="fx-bolt"><div class="bolt-core"></div></div>
   <div class="fx-jolt"></div>
   <div class="blast"></div>
   <div class="fight-flash"></div>
   <div class="move-callout"></div>
   <div class="ko-mark roman-ko">KO</div>
   <div class="ko-mark morty-ko">KO</div>
   <div class="smash-hud">
    <div class="p-hud p1"><div class="p-tag">P1</div><div class="p-name">ROMAN</div><div class="p-pct" id="roman-pct">0%</div></div>
    <div class="p-hud p2"><div class="p-tag">P2</div><div class="p-name">MORTY</div><div class="p-pct" id="morty-pct">0%</div></div>
   </div>
   </div>
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
 const world=stage.querySelector('.fight-world');
 const FIGHT_REF_W=492;
 function scaleFightWorld(){
  if(!world) return;
  const w=stage.clientWidth||0;
  if(!w) return;
  world.style.transform='scale('+(w/FIGHT_REF_W)+')';
 }
 if(window.ResizeObserver) new ResizeObserver(scaleFightWorld).observe(stage);
 window.addEventListener('resize', scaleFightWorld);
 const banner=overlay.querySelector('.fight-banner');
 const sub=overlay.querySelector('.fight-sub');
 const callout=overlay.querySelector('.move-callout');
 const bolt=overlay.querySelector('.fx-bolt');
 const jolt=overlay.querySelector('.fx-jolt');
 const cloud=overlay.querySelector('.fx-cloud');
 const trail=overlay.querySelector('.blade-trail');
 const arc=overlay.querySelector('.dolphin-arc');
 const spark=overlay.querySelector('.tipper-spark');
 const qa=overlay.querySelector('.qa-streak');
 const blast=overlay.querySelector('.blast');
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
  art.dataset.w=String(w);
  art.dataset.face=String(face);
 }

 prepFighter(romanEl, romanArt, FIGHT.roman, 1);
 prepFighter(mortyEl, mortyArt, FIGHT.morty, -1);

 /* Frame maps:
    Roman: 0 ready, 1 sword-up, 2 slash/thrust, 3 victory/high
    Morty: 0 crouch/ready, 1 lunge, 2 buzzsaw, 3 jolt throw, 4 victory/spark */
 const FINISHERS_ROMAN=['fsmash','db-tipper','dolphin','counter'];
 const FINISHERS_MORTY=['thunder','aerial','skullbash'];
 const ALL_FINISHERS=FINISHERS_ROMAN.concat(FINISHERS_MORTY);
 /* Modular Smash-style fight engine.
    Unique fights are stitched from opening / mid / finisher pools.
    RULES (must stay accurate):
    - No draws. Winner is chosen first so every fight is decisive; split is ~even over time.
    - No move-name labels. Only the % HUD and the winner banner.
    - Thunder (Pikachu down-B) only ever increments Roman's % (rp). Never Morty's (mp).
      Thunder is a ranged sky bolt, so Marth Counter is never used against it.
    - Counter (Marth down-B) only fires against a close-range MELEE hit that reaches
      Roman's body (e.g. Morty's spinning aerial). It is a standing sword swing, not a reflector.
    - A KO only comes from a finisher after damage has already been built. Never a raw hit at 0%. */

 function mulberry(seed){
  let s=((seed>>>0)||1);
  return {
   seed:s,
   next:function(){ s=(s+0x6D2B79F5)>>>0; let t=s; t=Math.imul(t^t>>>15,t|1); t^=t+Math.imul(t^t>>>7,t|61); return ((t^t>>>14)>>>0)/4294967296; },
   ri:function(a,b){ return a+Math.floor(this.next()*(b-a+1)); },
   pick:function(arr){ return arr[Math.floor(this.next()*arr.length)]; },
   chance:function(p){ return this.next()<p; }
  };
 }
 function copySt(st){ return {r:Object.assign({},st.r), m:Object.assign({},st.m), rp:st.rp, mp:st.mp}; }
 function faceSt(st){
  if(st.r.x<=st.m.x){ st.r.face=1; st.m.face=-1; }
  else { st.r.face=-1; st.m.face=1; }
 }
 function snap(st, extra){
  faceSt(st);
  return Object.assign({r:Object.assign({},st.r), m:Object.assign({},st.m), rp:st.rp, mp:st.mp}, extra||{});
 }
 function freshState(){
  return {r:{x:26,y:0,rot:0,frame:0,scale:1,face:1}, m:{x:74,y:0,rot:0,frame:0,scale:1,face:-1}, rp:0, mp:0};
 }
 function clampX(v, lo, hi){ return Math.max(lo, Math.min(hi, v)); }
 function midX(st){ return (st.r.x+st.m.x)/2; }
 function resetStance(st){
  st.r.y=0; st.r.rot=0; st.r.frame=0; st.r.scale=1;
  st.m.y=0; st.m.rot=0; st.m.frame=0; st.m.scale=1;
  st.r.x=clampX(st.r.x,18,82); st.m.x=clampX(st.m.x,18,82);
  if(Math.abs(st.m.x-st.r.x)<18){
   if(st.r.x<=st.m.x){ st.r.x=clampX(st.r.x-6,16,80); st.m.x=clampX(st.m.x+6,20,86); }
   else { st.m.x=clampX(st.m.x-6,16,80); st.r.x=clampX(st.r.x+6,20,86); }
  }
  faceSt(st);
 }
 function makeSeg(hit, fn){
  return {hit:hit, run:function(st, rng, ctx){
   const keys=[], marks={};
   const s=copySt(st);
   function add(t, extra, mut){ if(mut) mut(s); const k=snap(s, extra); k.t=t; keys.push(k); return k; }
   const duration=fn(s, rng, ctx, add, marks);
   const scale=0.8;
   keys.forEach(function(k){ k.t=Math.round(k.t*scale); });
   Object.keys(marks).forEach(function(k){ marks[k]=Math.round((marks[k]||0)*scale); });
   return {keys:keys, duration:Math.round(duration*scale), st:s, marks:marks};
  }};
 }

 const OPENINGS={
  space: makeSeg('none', function(s,rng,ctx,add,marks){
   marks.opening=0;
   add(0);
   add(240, null, function(s){ s.r.x=clampX(s.r.x+16,20,50); s.r.frame=0; });
   add(520, null, function(s){ s.r.x=clampX(s.r.x-20,16,40); });
   add(820, null, function(s){ s.r.x=26; resetStance(s); });
   return 980;
  }),
  'qa-rush': makeSeg('roman', function(s,rng,ctx,add,marks){
   marks.opening=0;
   add(0);
   add(220, {qa:{x:60,y:10,w:36,rot:-30}, afterimage:'morty'}, function(s){ s.m.x=48; s.m.y=12; s.m.frame=1; });
   const hit=rng.chance(0.7);
   if(hit){
    const dmg=rng.ri(3,6);
    add(480, {impact:1}, function(s){ s.rp+=dmg; s.m.x=40; s.m.y=4; s.m.frame=1; s.r.rot=8; s.r.x=clampX(s.r.x-3,16,40); });
   } else {
    add(480, {qa:{x:44,y:8,w:28,rot:-10}, afterimage:'morty'}, function(s){ s.m.x=38; s.m.y=8; s.m.frame=1; });
   }
   add(860, null, function(s){ s.m.x=70; s.m.y=0; s.m.frame=0; s.r.rot=0; resetStance(s); });
   return 1000;
  }),
  'jolt-poke': makeSeg('roman', function(s,rng,ctx,add,marks){
   marks.opening=0;
   add(0);
   add(180, {jolt:{show:1,x:s.m.x-6,y:10}}, function(s){ s.m.frame=3; });
   add(380, {jolt:{show:1,x:midX(s),y:8}});
   const dmg=rng.ri(6,8);
   add(560, {impact:1, jolt:{show:1,x:s.r.x+6,y:6}}, function(s){ s.rp+=dmg; s.r.rot=-10; s.r.x=clampX(s.r.x-4,16,40); });
   add(900, {jolt:{show:0}}, function(s){ s.m.frame=0; s.r.rot=0; resetStance(s); });
   return 1040;
  }),
  'breaker-poke': makeSeg('morty', function(s,rng,ctx,add,marks){
   marks.opening=0;
   add(0);
   add(260, {sparking:'roman'}, function(s){ s.r.frame=1; s.r.x=clampX(s.r.x-4,16,36); });
   const dmg=rng.ri(8,13);
   add(560, {impact:1, trail:{color:'white',x:midX(s)+4,y:12,rot:-8}}, function(s){
    s.r.frame=2; s.r.x=clampX(s.r.x+18,30,52); s.mp+=dmg; s.m.rot=10; s.m.x=clampX(s.m.x+6,70,86);
   });
   add(960, null, function(s){ s.r.frame=0; s.m.rot=0; resetStance(s); });
   return 1100;
  }),
  neutral: makeSeg('morty', function(s,rng,ctx,add,marks){
   marks.opening=0;
   add(0);
   add(280, null, function(s){ s.r.x=36; s.m.x=66; });
   const dmg=rng.ri(6,9);
   add(560, {impact:1, trail:{color:'blue',x:50,y:12,rot:-12}}, function(s){ s.r.frame=2; s.r.x=44; s.mp+=dmg; s.m.x=78; s.m.rot=8; });
   add(920, null, function(s){ s.r.frame=0; s.r.x=28; s.m.rot=0; s.m.x=74; resetStance(s); });
   return 1040;
  })
 };
 const OPENING_IDS=Object.keys(OPENINGS);

 const MIDS={
  'dancing-blade': makeSeg('morty', function(s,rng,ctx,add,marks){
   marks.dance=0;
   resetStance(s); add(0);
   add(160, null, function(s){ s.r.frame=2; s.r.x=clampX(s.m.x-32,22,50); });
   const hits=rng.chance(0.45)?4:3;
   const colors=['red','green','blue','white'];
   let t=160;
   for(let i=0;i<hits;i++){
    t+=rng.ri(220,270);
    const tip=(i===hits-1 && rng.chance(0.5));
    const dmg=tip?rng.ri(11,16):rng.ri(6,10);
    const color=tip?'white':colors[i];
    const extra={impact:1, trail:{color:color,x:s.r.x+16+i*3,y:12+i*2,rot:i%2?-14:10}};
    if(tip) extra.tipper={x:s.m.x-2,y:16};
    add(t, extra, function(s){
     s.r.frame=2; s.r.x=clampX(s.r.x+5,24,58);
     s.mp+=dmg; s.m.x=clampX(s.m.x+4,70,88); s.m.y=i===hits-1?8:4; s.m.rot=8+i*5; s.m.frame=0;
    });
    if(i===0) marks.dance=t;
   }
   t+=280;
   add(t, null, function(s){ s.m.y=0; s.m.rot=0; s.r.frame=0; resetStance(s); });
   return t+160;
  }),
  'tipper-space': makeSeg('morty', function(s,rng,ctx,add,marks){
   resetStance(s); add(0);
   add(240, null, function(s){ s.r.x=clampX(s.r.x-10,16,36); s.r.frame=1; });
   const dmg=rng.ri(11,16);
   add(560, {impact:1, trail:{color:'white',x:s.m.x-10,y:14,rot:-6}, tipper:{x:s.m.x,y:16}}, function(s){
    s.r.frame=2; s.r.x=clampX(s.r.x+22,34,56); s.mp+=dmg; s.m.x=clampX(s.m.x+8,74,88); s.m.y=10; s.m.rot=16;
   });
   add(900, null, function(s){ s.m.y=0; s.m.rot=0; s.r.frame=0; resetStance(s); });
   return 1060;
  }),
  'grab-aerial': makeSeg('roman', function(s,rng,ctx,add,marks){
   resetStance(s); add(0);
   add(200, {qa:{x:midX(s)+8,y:6,w:30,rot:-20}, afterimage:'morty'}, function(s){ s.m.x=s.r.x+14; s.m.y=4; s.m.frame=1; });
   add(400, null, function(s){ s.m.x=s.r.x+8; s.m.y=2; s.m.frame=0; s.r.rot=6; });
   const dthrow=rng.ri(5,7);
   add(620, {impact:1}, function(s){ s.rp+=dthrow; s.r.y=22; s.r.x=clampX(s.r.x+6,20,50); s.r.rot=12; s.m.frame=1; });
   let t=620;
   const nairs=rng.ri(2,3);
   for(let i=0;i<nairs;i++){
    t+=rng.ri(240,280);
    const dmg=rng.ri(8,12);
    add(t, {impact:1, sparking:'morty'}, function(s){
     s.m.frame=2; s.m.y=18+i*4; s.m.x=s.r.x-4; s.m.rot=i%2?-16:14;
     s.rp+=dmg; s.r.y=20+i*5; s.r.rot=10+i*6;
    });
   }
   t+=300;
   add(t, null, function(s){ s.r.y=0; s.r.rot=0; s.m.y=0; s.m.rot=0; s.m.frame=0; s.m.x=70; resetStance(s); });
   return t+160;
  }),
  'qa-pressure': makeSeg('roman', function(s,rng,ctx,add,marks){
   resetStance(s); add(0);
   add(180, {qa:{x:64,y:12,w:32,rot:200}, afterimage:'morty'}, function(s){ s.m.x=50; s.m.y=14; s.m.frame=1; });
   add(380, {qa:{x:36,y:8,w:28,rot:160}, afterimage:'morty'}, function(s){ s.m.x=32; s.m.y=8; s.m.frame=1; });
   const dmg=rng.ri(4,7);
   add(600, {impact:1, qa:{x:28,y:4,w:24,rot:10}}, function(s){ s.rp+=dmg; s.m.x=s.r.x+10; s.m.y=2; s.r.rot=8; s.r.x=clampX(s.r.x-4,16,40); });
   if(rng.chance(0.6)){
    const dmg2=rng.ri(6,10);
    add(840, {impact:1, sparking:'morty'}, function(s){ s.m.frame=2; s.m.y=16; s.rp+=dmg2; s.r.y=10; s.r.rot=12; });
    add(1120, null, function(s){ s.r.y=0; s.r.rot=0; s.m.y=0; s.m.rot=0; s.m.frame=0; s.m.x=72; resetStance(s); });
    return 1260;
   }
   add(920, null, function(s){ s.r.rot=0; s.m.y=0; s.m.frame=0; s.m.x=72; resetStance(s); });
   return 1080;
  }),
  'jolt-bounce': makeSeg('roman', function(s,rng,ctx,add,marks){
   resetStance(s); add(0);
   add(160, {jolt:{show:1,x:s.m.x-8,y:6}}, function(s){ s.m.frame=3; });
   add(340, {jolt:{show:1,x:midX(s)+6,y:14}});
   add(500, {jolt:{show:1,x:midX(s)-8,y:4}});
   const dmg=rng.ri(6,9);
   add(680, {impact:1, jolt:{show:1,x:s.r.x+6,y:8}}, function(s){ s.rp+=dmg; s.r.rot=-8; s.r.x=clampX(s.r.x-3,16,40); });
   add(960, {jolt:{show:0}}, function(s){ s.m.frame=0; s.r.rot=0; resetStance(s); });
   return 1100;
  }),
  scramble: makeSeg('none', function(s,rng,ctx,add,marks){
   resetStance(s); add(0);
   add(200, null, function(s){ s.r.x=clampX(s.r.x+14,28,50); s.r.frame=2; s.m.x=clampX(s.m.x-14,50,70); s.m.y=16; s.m.frame=2; });
   const trade=rng.chance(0.4);
   if(trade){
    const a=rng.ri(3,6), b=rng.ri(3,6);
    add(480, {impact:1, trail:{color:'blue',x:midX(s),y:14,rot:0}}, function(s){ s.rp+=a; s.mp+=b; s.r.rot=-6; s.m.rot=8; });
   } else {
    add(480, null, function(s){ s.r.x=20; s.r.frame=0; s.m.x=80; s.m.y=8; });
   }
   add(820, null, function(s){ s.r.rot=0; s.m.rot=0; s.m.y=0; s.m.frame=0; resetStance(s); });
   return 980;
  }),
  'spin-nair': makeSeg('roman', function(s,rng,ctx,add,marks){
   resetStance(s); add(0);
   add(200, {qa:{x:midX(s),y:10,w:28,rot:-24}, afterimage:'morty'}, function(s){ s.m.x=s.r.x+18; s.m.y=16; s.m.frame=2; });
   const dmg=rng.ri(8,12);
   add(440, {impact:1, sparking:'morty'}, function(s){ s.m.x=s.r.x+6; s.m.y=14; s.m.frame=2; s.m.rot=-18; s.rp+=dmg; s.r.rot=10; s.r.y=8; });
   const dmg2=rng.ri(7,11);
   add(700, {impact:1, sparking:'morty'}, function(s){ s.m.rot=16; s.m.y=18; s.rp+=dmg2; s.r.y=14; s.r.x=clampX(s.r.x-6,16,44); });
   add(1020, null, function(s){ s.r.y=0; s.r.rot=0; s.m.y=0; s.m.rot=0; s.m.frame=0; s.m.x=70; resetStance(s); });
   return 1160;
  })
 };
 const MID_IDS=Object.keys(MIDS);

 const FINISHERS={
  fsmash: makeSeg('morty', function(s,rng,ctx,add,marks){
   resetStance(s); add(0);
   add(240, {sparking:'roman'}, function(s){ s.r.frame=1; s.r.x=clampX(s.r.x-8,16,32); s.m.x=70; });
   add(620, {sparking:'roman'}, function(s){ s.r.frame=1; });
   const dmg=rng.ri(18,22);
   marks.fsmash=900;
   add(900, {impact:1, trail:{color:'white',x:s.m.x-8,y:16,rot:-8}, tipper:{x:s.m.x,y:18}}, function(s){
    s.r.frame=2; s.r.x=clampX(s.m.x-22,30,54); s.mp+=dmg; s.m.rot=24; s.m.y=16; s.m.x=clampX(s.m.x+6,76,88);
   });
   add(1240, null, function(s){ s.m.x=108; s.m.y=34; s.m.rot=55; s.m.scale=.95; s.m.frame=1; });
   marks.ko=1600;
   add(1600, {blast:'right', ko:'morty'}, function(s){ s.m.x=126; s.m.y=48; s.m.rot=80; s.m.scale=.8; s.m.frame=2; s.r.frame=3; s.r.x=46; s.r.y=0; s.r.rot=0; });
   marks.banner=2040;
   add(2040, {banner:1, blast:'right', ko:'morty'});
   return 2040;
  }),
  'db-tipper': makeSeg('morty', function(s,rng,ctx,add,marks){
   resetStance(s); add(0);
   add(160, null, function(s){ s.r.frame=2; s.r.x=clampX(s.m.x-30,22,50); });
   const colors=['red','green','blue'];
   let t=160;
   for(let i=0;i<3;i++){
    t+=240;
    const dmg=rng.ri(6,10);
    add(t, {impact:1, trail:{color:colors[i],x:s.r.x+14+i*4,y:12+i*2,rot:i%2?-12:8}}, function(s){
     s.r.frame=2; s.r.x+=5; s.mp+=dmg; s.m.x+=4; s.m.y=4+i*3; s.m.rot=8+i*4;
    });
   }
   const dmg=rng.ri(14,20);
   t+=280;
   marks.fsmash=t;
   add(t, {impact:1, trail:{color:'white',x:s.m.x-6,y:16,rot:-6}, tipper:{x:s.m.x,y:18}}, function(s){
    s.r.frame=2; s.mp+=dmg; s.m.x=90; s.m.y=18; s.m.rot=28; s.m.frame=1;
   });
   t+=340;
   add(t, null, function(s){ s.m.x=112; s.m.y=36; s.m.rot=60; s.m.scale=.9; });
   t+=360;
   marks.ko=t;
   add(t, {blast:'right', ko:'morty'}, function(s){ s.m.x=128; s.m.y=50; s.m.rot=90; s.m.scale=.8; s.m.frame=2; s.r.frame=3; s.r.y=0; s.r.rot=0; });
   t+=420;
   marks.banner=t;
   add(t, {banner:1, blast:'right', ko:'morty'});
   return t;
  }),
  dolphin: makeSeg('morty', function(s,rng,ctx,add,marks){
   resetStance(s); add(0);
   const dmg=rng.ri(8,12);
   add(240, {impact:1, trail:{color:'white',x:s.m.x-8,y:14,rot:-8}, tipper:{x:s.m.x,y:16}}, function(s){
    s.r.frame=2; s.r.x=50; s.mp+=dmg; s.m.x=88; s.m.y=18; s.m.rot=20;
   });
   add(540, {qa:{x:90,y:16,w:26,rot:20}, afterimage:'morty'}, function(s){ s.m.x=84; s.m.y=22; s.m.frame=1; s.m.rot=0; s.r.frame=1; s.r.x=62; });
   const spike=rng.ri(12,16);
   marks.spike=880;
   add(880, {impact:1, dolphin:{x:86,y:28}}, function(s){
    s.r.frame=3; s.r.x=78; s.r.y=22; s.mp+=spike; s.m.x=92; s.m.y=8; s.m.rot=70; s.m.frame=2; s.m.scale=.95;
   });
   add(1180, {blast:'bottom', ko:'morty'}, function(s){ s.m.x=94; s.m.y=-28; s.m.rot=120; s.m.scale=.85; s.r.y=10; });
   marks.ko=1480;
   add(1480, {blast:'bottom', ko:'morty'}, function(s){ s.m.x=96; s.m.y=-70; s.m.rot=150; s.m.scale=.7; s.r.x=70; s.r.y=0; s.r.frame=3; });
   marks.banner=1900;
   add(1900, {banner:1, blast:'bottom', ko:'morty'});
   return 1900;
  }),
  /* Counter is close-range only. The incoming hit is always Morty's spinning aerial
     (melee). Thunder is never part of this sequence. */
  counter: makeSeg('morty', function(s,rng,ctx,add,marks){
   resetStance(s);
   s.r.x=30; s.m.x=76; faceSt(s);
   add(0);
   add(220, {qa:{x:58,y:12,w:32,rot:-28}, afterimage:'morty'}, function(s){ s.m.x=52; s.m.y=14; s.m.frame=1; });
   /* Morty commits to a spinning aerial that will reach Roman's body. */
   add(460, {sparking:'morty'}, function(s){ s.m.x=40; s.m.y=18; s.m.frame=2; s.m.rot=-16; });
   marks.counter=620;
   add(620, {counter:'roman'}, function(s){ s.r.frame=1; s.r.x=28; s.r.y=0; /* stance, no % taken */ });
   const dmg=rng.ri(12,18);
   marks.slash=860;
   add(860, {impact:1, counter:'roman', trail:{color:'white',x:44,y:16,rot:-8}, tipper:{x:48,y:18}}, function(s){
    s.r.frame=2; s.mp+=dmg; s.m.x=56; s.m.y=14; s.m.rot=24; s.m.frame=2; s.m.scale=.98;
   });
   add(1180, null, function(s){ s.m.x=108; s.m.y=32; s.m.rot=55; s.m.scale=.9; s.r.frame=3; s.r.x=36; });
   marks.ko=1520;
   add(1520, {blast:'right', ko:'morty'}, function(s){ s.m.x=126; s.m.y=48; s.m.rot=85; s.m.scale=.78; s.m.frame=2; s.r.frame=3; });
   marks.banner=1960;
   add(1960, {banner:1, blast:'right', ko:'morty'});
   return 1960;
  }),
  /* Thunder only damages Roman. Bolt is placed on Roman's x. Morty's % does not change. */
  thunder: makeSeg('roman', function(s,rng,ctx,add,marks){
   resetStance(s);
   s.r.x=28; s.m.x=72; faceSt(s);
   add(0);
   add(220, null, function(s){ s.m.frame=4; s.m.x=70; });
   marks.thunder=480;
   add(480, {cloud:{show:1,x:s.r.x}}, function(s){ s.m.frame=4; });
   const dmg=rng.ri(12,16);
   marks.bolt=820;
   add(820, {cloud:{show:1,x:s.r.x}, bolt:{show:1,x:s.r.x}, impact:1}, function(s){
    s.rp+=dmg; s.r.rot=16; s.r.y=8; s.r.frame=0;
    /* mp is intentionally left unchanged */
   });
   add(1120, {cloud:{show:0}, bolt:{show:0}}, function(s){ s.r.x=10; s.r.y=28; s.r.rot=50; s.r.scale=.95; });
   marks.ko=1480;
   add(1480, {blast:'left', ko:'roman'}, function(s){ s.r.x=-16; s.r.y=48; s.r.rot=90; s.r.scale=.75; s.m.frame=4; s.m.x=68; s.m.y=0; });
   marks.banner=1920;
   add(1920, {banner:1, blast:'left', ko:'roman'});
   return 1920;
  }),
  aerial: makeSeg('roman', function(s,rng,ctx,add,marks){
   resetStance(s); add(0);
   add(200, {qa:{x:midX(s),y:10,w:30,rot:-20}, afterimage:'morty'}, function(s){ s.m.x=s.r.x+16; s.m.y=16; s.m.frame=2; });
   let t=200;
   const hits=3;
   for(let i=0;i<hits;i++){
    t+=rng.ri(230,270);
    const last=i===hits-1;
    const dmg=last?rng.ri(12,16):rng.ri(8,12);
    add(t, {impact:1, sparking:'morty'}, function(s){
     s.m.frame=2; s.m.y=16+i*4; s.m.x=s.r.x+(last?2:-2); s.m.rot=i%2?-20:16;
     s.rp+=dmg; s.r.y=12+i*6; s.r.rot=12+i*8; if(last) s.r.x=clampX(s.r.x-4,16,40);
    });
    if(last) marks.aerial=t;
   }
   t+=340;
   add(t, null, function(s){ s.r.x=-4; s.r.y=36; s.r.rot=70; s.r.scale=.9; s.m.y=0; s.m.frame=4; s.m.rot=0; });
   t+=340;
   marks.ko=t;
   add(t, {blast:'left', ko:'roman'}, function(s){ s.r.x=-22; s.r.y=56; s.r.rot=110; s.r.scale=.72; s.m.frame=4; });
   t+=420;
   marks.banner=t;
   add(t, {banner:1, blast:'left', ko:'roman'});
   return t;
  }),
  skullbash: makeSeg('roman', function(s,rng,ctx,add,marks){
   resetStance(s);
   s.r.x=30; s.m.x=76; faceSt(s);
   add(0);
   add(240, {sparking:'morty'}, function(s){ s.m.frame=0; s.m.x=78; s.m.scale=1; });
   add(560, {sparking:'morty'}, function(s){ s.m.frame=0; s.m.x=80; });
   marks.bash=860;
   const dmg=rng.ri(16,22);
   add(860, {impact:1, afterimage:'morty', sparking:'morty'}, function(s){
    s.m.frame=1; s.m.x=s.r.x+8; s.m.y=4; s.rp+=dmg; s.r.rot=18; s.r.x=20; s.r.y=10;
   });
   add(1180, null, function(s){ s.r.x=4; s.r.y=32; s.r.rot=60; s.r.scale=.92; s.m.x=36; s.m.frame=1; });
   marks.ko=1520;
   add(1520, {blast:'left', ko:'roman'}, function(s){ s.r.x=-20; s.r.y=52; s.r.rot=100; s.r.scale=.74; s.m.x=42; s.m.y=0; s.m.frame=4; s.m.rot=0; });
   marks.banner=1960;
   add(1960, {banner:1, blast:'left', ko:'roman'});
   return 1960;
  })
 };

 function winnerOfFinisher(id){
  if(FINISHERS_ROMAN.indexOf(id)>=0) return 'roman';
  if(FINISHERS_MORTY.indexOf(id)>=0) return 'morty';
  return null;
 }
 function offsetSeg(seg, t0){
  const marks={};
  Object.keys(seg.marks||{}).forEach(function(k){ marks[k]=(seg.marks[k]||0)+t0; });
  const keys=seg.keys.map(function(k){ return Object.assign({},k,{t:k.t+t0}); });
  return {keys:keys, marks:marks, duration:seg.duration, st:seg.st};
 }
 function append(out, seg, t0){
  const shifted=offsetSeg(seg, t0);
  out.keys.push.apply(out.keys, shifted.keys);
  Object.assign(out.marks, shifted.marks);
  return t0+seg.duration;
 }
 function pickMidId(rng, avoid, preferHit){
  let pool=MID_IDS.filter(function(id){ return id!==avoid; });
  if(preferHit){
   const biased=pool.filter(function(id){ return MIDS[id].hit===preferHit || MIDS[id].hit==='both'; });
   if(biased.length && rng.chance(0.75)) pool=biased;
  }
  return rng.pick(pool);
 }
 function composeFight(opts){
  opts=opts||{};
  let seed=opts.seed;
  if(!(seed>0)) seed=1+Math.floor(Math.random()*0xfffffffe);
  const rng=mulberry(seed);
  let winner=opts.winner;
  let finisher=opts.finisher;
  if(finisher && ALL_FINISHERS.indexOf(finisher)<0) finisher=null;
  if(finisher){
   winner=winnerOfFinisher(finisher);
  } else {
   if(winner!=='roman' && winner!=='morty') winner=rng.chance(0.5)?'roman':'morty';
   finisher=rng.pick(winner==='roman'?FINISHERS_ROMAN:FINISHERS_MORTY);
  }
  const opening=opts.opening && OPENINGS[opts.opening]?opts.opening:rng.pick(OPENING_IDS);
  let nMids=opts.nMids;
  if(!(nMids>=2 && nMids<=4)) nMids=rng.ri(2,4);
  const loser=winner==='roman'?'morty':'roman';
  const HEAVY={morty:['dancing-blade','tipper-space'], roman:['grab-aerial','spin-nair']};
  const midIds=[];
  let last=null;
  for(let i=0;i<nMids;i++){
   const id=pickMidId(rng, last, loser);
   midIds.push(id);
   last=id;
  }
  if(!midIds.some(function(id){ return (HEAVY[loser]||[]).indexOf(id)>=0; })){
   midIds[midIds.length-1]=rng.pick(HEAVY[loser]);
  }

  const out={keys:[], marks:{}, opening:opening, mids:midIds.slice(), finisher:finisher, winner:winner, seed:seed};
  let st=freshState();
  let t=0;
  function runPool(item, id){
   const seg=item.run(st, rng, {winner:winner, id:id});
   t=append(out, seg, t);
   st=seg.st;
  }
  runPool(OPENINGS[opening], opening);
  midIds.forEach(function(id){ runPool(MIDS[id], id); });

  /* Guarantee the loser has built enough % for a KO finisher. Never finish at 0%. */
  const MIN_PCT=48;
  function loserPct(){ return loser==='morty'?st.mp:st.rp; }
  let pads=0;
  while(loserPct()<MIN_PCT && pads<1){
   const id=rng.pick(HEAVY[loser]);
   midIds.push(id);
   out.mids.push(id);
   runPool(MIDS[id], id);
   last=id;
   pads++;
  }
  if(loserPct()<MIN_PCT){
   /* Failsafe bump so a smash/thunder can actually KO, still after built damage. */
   const bump=MIN_PCT+((typeof rng.ri==='function')?rng.ri(0,10):6);
   if(loser==='morty') st.mp=Math.max(st.mp, bump);
   else st.rp=Math.max(st.rp, bump);
  }

  out.marks.finisher=t;
  runPool(FINISHERS[finisher], finisher);

  const lastKey=out.keys[out.keys.length-1];
  if(!lastKey || !lastKey.banner){
   const k=snap(st, {banner:1});
   k.t=t;
   if(winner==='roman'){ k.ko='morty'; k.blast=k.blast||'right'; }
   else { k.ko='roman'; k.blast=k.blast||'left'; }
   out.keys.push(k);
   out.marks.banner=t;
  }
  out.id=finisher;
  out.banner=winner==='roman'?'ROMAN WINS!':'MORTY WINS!';
  out.duration=out.keys[out.keys.length-1].t;
  return out;
 }
 function parseSeek(raw, outcome){
  if(raw==null || raw==='') return null;
  if(raw==='end' || raw==='banner'){
   if(outcome.marks && outcome.marks.banner!=null) return outcome.marks.banner;
   for(let i=outcome.keys.length-1;i>=0;i--) if(outcome.keys[i].banner) return outcome.keys[i].t;
   return outcome.keys[outcome.keys.length-1].t;
  }
  if(outcome.marks && outcome.marks[raw]!=null) return outcome.marks[raw];
  const n=parseInt(raw,10);
  return isNaN(n)?null:n;
 }
 function fightOptsFromUrl(optId, fromUrl){
  const p=new URLSearchParams(location.search);
  const opts={};
  if(fromUrl){
   if(p.get('seed')) opts.seed=parseInt(p.get('seed'),10);
   if(p.get('winner')==='roman'||p.get('winner')==='morty') opts.winner=p.get('winner');
   if(p.get('finisher')) opts.finisher=p.get('finisher');
   if(p.get('opening')) opts.opening=p.get('opening');
   if(p.get('mids')) opts.nMids=parseInt(p.get('mids'),10);
   if(optId && optId!=='1' && optId!=='random'){
    if(ALL_FINISHERS.indexOf(optId)>=0){ opts.finisher=optId; opts.winner=winnerOfFinisher(optId); }
    else if(optId==='roman'||optId==='morty') opts.winner=optId;
    else if(OPENINGS[optId]) opts.opening=optId;
   }
  }
  return opts;
 }
 function publishMeta(outcome){
  const meta={
   seed:outcome.seed, opening:outcome.opening, mids:outcome.mids, finisher:outcome.finisher,
   winner:outcome.winner, duration:outcome.duration, marks:outcome.marks,
   endRp:(outcome.keys[outcome.keys.length-1]||{}).rp,
   endMp:(outcome.keys[outcome.keys.length-1]||{}).mp
  };
  try{ document.body.dataset.fightMeta=JSON.stringify(meta); window.__FIGHT_META__=meta; }catch(e){}
  return meta;
 }


 let raf=0, playing=false, t0=0, current=null, lastImpact=-999, lastRp=-1, lastMp=-1;

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
  const prev=node.dataset.v!=null?parseInt(node.dataset.v,10):0;
  node.textContent=v+'%';
  node.dataset.v=String(v);
  node.classList.remove('mid','high','ko');
  if(v>=150) node.classList.add('ko');
  else if(v>=100) node.classList.add('high');
  else if(v>=50) node.classList.add('mid');
  if(v>prev){
   node.classList.remove('pop');
   void node.offsetWidth;
   if(!reduce) node.classList.add('pop');
  }
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
 function spawnGhost(fromEl){
  const g=fromEl.cloneNode(true);
  g.classList.add('ghost');
  (world||stage).appendChild(g);
  ghosts.push(g);
  setTimeout(function(){ if(g.parentNode) g.parentNode.removeChild(g); }, 260);
 }
 function juice(){
  if(reduce) return;
  stage.classList.remove('shake','flash');
  void stage.offsetWidth;
  stage.classList.add('shake','flash');
 }
 function resetFx(){
  [callout,bolt,jolt,cloud,trail,arc,spark,qa,blast,romanKo,mortyKo,banner,sub].forEach(function(el){ showFx(el,false); });
  romanEl.classList.remove('sparking','countering');
  mortyEl.classList.remove('sparking','countering');
  stage.classList.remove('shake','flash');
  clearGhosts();
  trail.className='blade-trail';
  lastRp=-1; lastMp=-1;
  rPct.dataset.v='0'; mPct.dataset.v='0';
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

  let rp=0, mp=0;
  keys.forEach(function(k){
   if(k.rp!=null && k.t<=now) rp=k.rp;
   if(k.mp!=null && k.t<=now) mp=k.mp;
  });
  setPct(rPct, rp);
  setPct(mPct, mp);

  showFx(callout,false);

  const tr=lastKey(keys,'trail',now);
  if(tr && tr.trail && now-tr.t<320){
   trail.className='blade-trail '+tr.trail.color+' show';
   placeAbs(trail, tr.trail.x, tr.trail.y);
   trail.style.transform='rotate('+(tr.trail.rot||0)+'deg)';
  } else { trail.className='blade-trail'; showFx(trail,false); }

  const tp=lastKey(keys,'tipper',now);
  if(tp && tp.tipper && now-tp.t<400){ placeAbs(spark, tp.tipper.x, tp.tipper.y); showFx(spark,true); }
  else showFx(spark,false);

  const dl=lastKey(keys,'dolphin',now);
  if(dl && dl.dolphin && now-dl.t<450){ placeAbs(arc, dl.dolphin.x, dl.dolphin.y); showFx(arc,true); }
  else showFx(arc,false);

  const jt=lastKey(keys,'jolt',now);
  if(jt && jt.jolt && jt.jolt.show){ placeAbs(jolt, jt.jolt.x, jt.jolt.y); showFx(jolt,true); }
  else showFx(jolt,false);

  const bl=lastKey(keys,'bolt',now);
  if(bl && bl.bolt && bl.bolt.show){ bolt.style.left=bl.bolt.x+'%'; showFx(bolt,true); }
  else showFx(bolt,false);

  const cl=lastKey(keys,'cloud',now);
  if(cl && cl.cloud && cl.cloud.show){ cloud.style.left=cl.cloud.x+'%'; showFx(cloud,true); }
  else showFx(cloud,false);

  const qk=lastKey(keys,'qa',now);
  if(qk && qk.qa && now-qk.t<280){
   const q=qk.qa;
   qa.style.left=q.x+'%';
   qa.style.bottom='calc(31.1% + '+(q.y||0)+'px)';
   qa.style.width=(q.w||28)+'px';
   qa.style.transform='rotate('+(q.rot||0)+'deg)';
   showFx(qa,true);
  } else showFx(qa,false);

  const sp=lastKey(keys,'sparking',now);
  romanEl.classList.toggle('sparking', !!(sp && sp.sparking==='roman' && now-sp.t<500));
  mortyEl.classList.toggle('sparking', !!(sp && sp.sparking==='morty' && now-sp.t<500));
  const cn=lastKey(keys,'counter',now);
  romanEl.classList.toggle('countering', !!(cn && cn.counter==='roman' && now-cn.t<900));
  mortyEl.classList.toggle('countering', !!(cn && cn.counter==='morty' && now-cn.t<900));

  const ko=lastKey(keys,'ko',now);
  showFx(romanKo, !!(ko && (ko.ko==='roman'||ko.ko==='both')));
  showFx(mortyKo, !!(ko && (ko.ko==='morty'||ko.ko==='both')));
  if(ko && (ko.ko==='roman'||ko.ko==='both')){
    romanKo.style.left='calc('+(r.x)+'% - 14px)';
    romanKo.style.bottom='calc(31.1% + '+((r.y||0)+36)+'px)';
  }
  if(ko && (ko.ko==='morty'||ko.ko==='both')){
    mortyKo.style.left='calc('+(m.x)+'% - 14px)';
    mortyKo.style.bottom='calc(31.1% + '+((m.y||0)+36)+'px)';
  }

  const bs=lastKey(keys,'blast',now);
  if(bs && now-bs.t<500){
   blast.className='blast show';
   if(bs.blast==='right'){ blast.style.left='92%'; blast.style.top='38%'; }
   else if(bs.blast==='left'){ blast.style.left='8%'; blast.style.top='38%'; }
   else if(bs.blast==='bottom'){ blast.style.left='70%'; blast.style.top='88%'; }
   else { blast.style.left='50%'; blast.style.top='40%'; }
  } else { blast.className='blast'; }

  if(impactsOk){
   keys.forEach(function(k){
    if(k.impact && k.t<=now && k.t>lastImpact-10 && now-k.t<50){
     lastImpact=k.t;
     juice();
    }
    if(k.afterimage && k.t<=now && now-k.t<40){
     spawnGhost(k.afterimage==='morty'?mortyEl:romanEl);
    }
   });
  }

  if(lastKey(keys,'banner',now)){
   banner.textContent=outcome.banner;
   showFx(banner,true);
   showFx(sub,false);
  } else {
   showFx(banner,false);
   showFx(sub,false);
  }
 }

 function endTime(outcome){ return outcome.keys[outcome.keys.length-1].t+500; }
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
 function play(optId, seek, paused, fromUrl){
  stop();
  resetFx();
  lastImpact=-999;
  current=Object.assign({}, composeFight(fightOptsFromUrl(optId, !!fromUrl)), {});
  current=Object.assign({},current,{keys:carry(current.keys)});
  publishMeta(current);
  const last=endTime(current);
  const seekMs=parseSeek(seek, current);
  if(reduce){
   applyAt(current, last, false);
   banner.textContent=current.banner;
   showFx(banner,true);
   showFx(sub,false);
   return;
  }
  if(paused && seekMs!=null){
   applyAt(current, seekMs, false);
   playing=false;
   return;
  }
  playing=true;
  const startSeek=seekMs||0;
  t0=performance.now()-startSeek;
  raf=requestAnimationFrame(tick);
 }
 function openFight(optId, seek, paused, fromUrl){
  overlay.hidden=false;
  document.body.style.overflow='hidden';
  scaleFightWorld();
  play(optId, seek, paused, fromUrl);
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
  const at=params.get('at');
  const paused=params.get('pause')==='1' || at!=null;
  openFight(id==='1'?null:id, at, paused, true);
 }
})();

</script>
</body></html>
"""


if __name__ == "__main__":
    main()
