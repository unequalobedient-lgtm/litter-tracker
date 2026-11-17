#!/usr/bin/env python3
"""Per-cat litter box weight tracker for Roman and Morty."""
from __future__ import annotations

import base64
import json
import statistics
from datetime import datetime, timedelta
import shutil
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


def _pack_fighter(info: dict, display: float = 1) -> dict:
    return {
        "src": "assets/" + info["file"],
        "sprite_w": info["sprite_w"],
        "sprite_h": info["sprite_h"],
        "frames": info["frames"],
        "anchor_x": info["anchor_x"],
        "anchor_y": info["anchor_y"],
        "display": display,
    }


def fight_payload(meta: dict) -> dict:
    fighters = json.loads((ASSETS / "fighters.json").read_text())
    # Aegis figures are taller; keep them a bit bigger than the chibi cats
    # but inside the 16:9 stage.
    aegis = 0.92

    def both(fid, display=1):
        rec = {"name": fid.upper()}
        rk, mk = f"roman_{fid}", f"morty_{fid}"
        if rk in fighters:
            rec["roman"] = _pack_fighter(fighters[rk], display)
        if mk in fighters:
            rec["morty"] = _pack_fighter(fighters[mk], display)
        return rec

    roster = {
        "marth": both("marth"),
        "pikachu": both("pikachu"),
        "luigi": both("luigi"),
        "steve": both("steve"),
        "sonic": both("sonic"),
        "snake": both("snake"),
        "pyra": both("pyra", aegis),
        "mythra": both("mythra", aegis),
    }
    return {
        "stage": "assets/omega_stage.jpg",
        "roster": roster,
    }


def publish_fight_assets() -> None:
    """Copy stage + fighter sheets into public/ so GitHub Pages can serve them."""
    dest = HERE / "public" / "assets"
    fighters_dest = dest / "fighters"
    fighters_dest.mkdir(parents=True, exist_ok=True)
    stage = ASSETS / "omega_stage.jpg"
    if stage.is_file():
        shutil.copy2(stage, dest / "omega_stage.jpg")
    src_dir = ASSETS / "fighters"
    if src_dir.is_dir():
        for png in sorted(src_dir.glob("*.png")):
            shutil.copy2(png, fighters_dest / png.name)


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
    publish_fight_assets()
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
 .fight-stage{position:relative;width:100%;aspect-ratio:16/9;border-radius:10px;overflow:hidden;background:#040014 center/100% 100% no-repeat;image-rendering:auto;box-shadow:inset 0 0 40px rgba(0,0,0,.45);container-type:size;container-name:fight;--shake:7}
 .fight-world{position:absolute;left:0;top:0;width:492px;height:276.75px;transform-origin:0 0;transform:scale(calc(100cqw / 492));-webkit-text-size-adjust:100%;text-size-adjust:100%}
 .fight-stage.shake{animation:fightshake .35s}
 .fight-flash{position:absolute;inset:0;background:#fff6c0;opacity:0;pointer-events:none;z-index:7}
 .fight-stage.flash .fight-flash{animation:fightflash .28s}
 @keyframes fightshake{0%,100%{transform:translate(0,0)}20%{transform:translate(calc(var(--shake) * -1px),calc(var(--shake) * .43px))}40%{transform:translate(calc(var(--shake) * 1px),calc(var(--shake) * -.57px))}60%{transform:translate(calc(var(--shake) * -.71px),calc(var(--shake) * -.29px))}80%{transform:translate(calc(var(--shake) * .71px),calc(var(--shake) * .43px))}}
 @keyframes fightflash{0%{opacity:.85}100%{opacity:0}}
 .smash-hud{position:absolute;bottom:6px;left:8px;right:8px;display:flex;justify-content:space-between;gap:8px;pointer-events:none;z-index:8}
 .p-hud{background:rgba(8,6,18,.82);border:2px solid #e8e8f0;border-radius:8px;padding:3px 10px 2px;min-width:100px;max-width:38%;box-sizing:border-box;flex:0 1 auto;box-shadow:0 2px 0 #000;-webkit-text-size-adjust:100%;text-size-adjust:100%}
 .p-hud.p1{border-color:#7ec8ff}
 .p-hud.p2{border-color:#ffd36b;text-align:right}
 .p-tag{font-size:9px;letter-spacing:.14em;color:#9aa;font-weight:800}
 .p-name{font-size:11px;font-weight:800;letter-spacing:.08em}
 .p-fighter{font-size:9px;letter-spacing:.12em;color:#c9a36a;font-weight:700;line-height:1.2;margin-top:1px;min-height:11px}
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
 .shield-bubble{position:absolute;left:0;bottom:8px;width:72px;height:72px;margin-left:-36px;border-radius:50%;border:2.5px solid rgba(160,220,255,.95);background:radial-gradient(circle at 40% 35%,rgba(220,245,255,.35),rgba(80,170,255,.22) 55%,rgba(40,120,220,.08));box-shadow:0 0 12px rgba(120,200,255,.8),inset 0 0 10px rgba(200,240,255,.55);opacity:0;pointer-events:none;z-index:4;transform:scale(.7);transform-origin:50% 70%}
 .fighter.shielding .shield-bubble{opacity:1;animation:shieldhold .75s ease-out forwards}
 @keyframes shieldhold{0%{transform:scale(.86);opacity:.4}22%{transform:scale(1.08);opacity:1}100%{transform:scale(.8);opacity:.82}}
 .fighter.shield-pop .shield-bubble{opacity:1;animation:shieldpop .28s ease-out forwards}
 @keyframes shieldpop{0%{transform:scale(.82);opacity:.95}35%{transform:scale(1.28);opacity:.65}100%{transform:scale(1.7);opacity:0}}
 .shield-spark{position:absolute;width:18px;height:18px;margin-left:-9px;border-radius:50%;background:radial-gradient(circle,#fff 0%,#b8e4ff 42%,transparent 72%);box-shadow:0 0 10px #c4f0ff;opacity:0;pointer-events:none;z-index:5}
 .shield-spark.show{opacity:1;animation:blockspark .28s ease-out}
 @keyframes blockspark{0%{transform:scale(.35);opacity:1}100%{transform:scale(1.85);opacity:0}}
 .fighter.dodging .fighter-art{filter:drop-shadow(0 0 5px #fff)}
 .fighter.grabbing .fighter-art{filter:drop-shadow(0 0 6px #ffe9a3)}
 .fighter.thrown .fighter-art{animation:tosspin .38s ease-out}
 @keyframes tosspin{0%{filter:drop-shadow(0 0 0 transparent)}40%{filter:drop-shadow(0 6px 8px rgba(0,0,0,.45))}100%{filter:drop-shadow(0 0 0 transparent)}}
 .fighter.ghost{opacity:.4;z-index:2}
 .ko-mark{position:absolute;z-index:6;font-weight:900;letter-spacing:.14em;color:#ff4a4a;font-size:18px;text-shadow:2px 2px 0 #000;opacity:0;pointer-events:none}
 .ko-mark.show{opacity:1;animation:calloutpop .3s ease-out}
 .fx-canvas{position:absolute;left:0;top:0;width:492px;height:276.75px;z-index:4;pointer-events:none}
 .blade-trail{position:absolute;width:90px;height:16px;border-radius:6px 40px 40px 6px;opacity:0;z-index:4;pointer-events:none;transform-origin:10% 50%;filter:blur(.3px)}
 .blade-trail.red{background:linear-gradient(90deg,transparent,#ff3a3a 25%,#ffd0d0);box-shadow:0 0 12px #f33}
 .blade-trail.green{background:linear-gradient(90deg,transparent,#3dff6b 25%,#d0ffd8);box-shadow:0 0 12px #3d6}
 .blade-trail.blue{background:linear-gradient(90deg,transparent,#3da9ff 25%,#d0e8ff);box-shadow:0 0 12px #3af}
 .blade-trail.white{background:linear-gradient(90deg,transparent,#fff 20%,#ffe56a);box-shadow:0 0 16px #fff,0 0 28px #ffe56a}
 .blade-trail.gold{background:linear-gradient(90deg,transparent,#ffe56a 25%,#fff);box-shadow:0 0 12px #ffe56a}
 .blade-trail.flame{background:linear-gradient(90deg,transparent,#ff6a3a 25%,#ffe56a);box-shadow:0 0 14px #ff6a3a}
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
 .blast.green{background:radial-gradient(circle,#fff 0 8%,#9dff6a 18%,#3dff6b 40%,transparent 70%)}
 .blast.show{animation:blastpop .5s ease-out forwards}
 @keyframes blastpop{0%{transform:scale(.4);opacity:1}100%{transform:scale(1.6);opacity:0}}
 .fight-banner{display:none;text-align:center;margin:2cqi 0 0.8cqi;font-size:clamp(16px,5cqi,26px);font-weight:900;letter-spacing:.08em;color:#ffe56a;text-shadow:3px 3px 0 #6b1d1d,0 0 12px rgba(255,229,106,.4);animation:bannerpop .35s ease-out}
 .fight-banner.show{display:block}
  .fight-sub,.move-callout{display:none!important}
 @keyframes bannerpop{from{transform:scale(.6);opacity:0}to{transform:scale(1);opacity:1}}
 .fight-replay{display:block;margin:2.3cqi auto 0;padding:2cqi 3.5cqi;border-radius:999px;border:1px solid #e8c56b;background:#2a3240;color:#ffe9a3;font-weight:700;font-size:clamp(12px,2.7cqi,14px);cursor:pointer}
 @media (prefers-reduced-motion:reduce){
   .fight-stage.shake,.fight-stage.flash .fight-flash,.fight-banner,.move-callout,.ko-mark,.blade-trail,.tipper-spark,.dolphin-arc,.qa-streak,.blast,.p-pct.pop,.fighter.shielding .shield-bubble,.fighter.shield-pop .shield-bubble,.fighter.thrown .fighter-art,.shield-spark.show{animation:none!important}
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
   <div class="fighter roman"><div class="shield-bubble"></div><div class="fighter-art"></div></div>
   <div class="fighter morty"><div class="shield-bubble"></div><div class="fighter-art"></div></div>
   <canvas class="fx-canvas" width="984" height="554"></canvas>
   <div class="blade-trail"></div>
   <div class="dolphin-arc"></div>
   <div class="tipper-spark"></div>
   <div class="shield-spark"></div>
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
    <div class="p-hud p1"><div class="p-tag">P1</div><div class="p-name">ROMAN</div><div class="p-fighter" id="roman-fighter"></div><div class="p-pct" id="roman-pct">0%</div></div>
    <div class="p-hud p2"><div class="p-tag">P2</div><div class="p-name">MORTY</div><div class="p-fighter" id="morty-fighter"></div><div class="p-pct" id="morty-pct">0%</div></div>
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
 if(!overlay||!FIGHT||!FIGHT.roster) return;
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
const fxCanvas=overlay.querySelector('.fx-canvas');
const fxCtx=(fxCanvas && fxCanvas.getContext)?fxCanvas.getContext('2d'):null;
 const arc=overlay.querySelector('.dolphin-arc');
 const spark=overlay.querySelector('.tipper-spark');
 const shieldSpark=overlay.querySelector('.shield-spark');
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
 const rFighterLabel=document.getElementById('roman-fighter');
 const mFighterLabel=document.getElementById('morty-fighter');
 const ghosts=[];

 if(FIGHT.stage){
  const stg=FIGHT.stage;
  stage.style.backgroundImage=(stg.indexOf('assets/')===0||stg.indexOf('/')===0||stg.indexOf('data:')===0)
   ? 'url('+stg+')'
   : 'url(data:image/jpeg;base64,'+stg+')';
 }

 function prepFighter(el, art, meta, face){
  const d=meta.display||1;
  const w=meta.sprite_w*d, h=meta.sprite_h*d;
  const ax=(meta.anchor_x||0.42), ay=(meta.anchor_y||1);
  art.style.width=w+'px';
  art.style.height=h+'px';
  const src=meta.src || (meta.sheet?('data:image/png;base64,'+meta.sheet):'');
  art.style.backgroundImage=src?('url('+src+')'):'none';
  art.style.backgroundSize=(w*meta.frames)+'px '+h+'px';
  art.style.backgroundRepeat='no-repeat';
  art.style.setProperty('--ax', (ax*100)+'%');
  art.style.setProperty('--ay', (ay*100)+'%');
  art.style.marginLeft=(-(ax*w))+'px';
  art.style.marginBottom=(-((1-ay)*h))+'px';
  art.dataset.w=String(w);
  art.dataset.face=String(face);
 }
 function loadImg(src){
  return new Promise(function(resolve){
   if(!src){ resolve(); return; }
   const im=new Image();
   im.onload=function(){ resolve(); };
   im.onerror=function(){ resolve(); };
   im.src=src;
  });
 }
 function applyCast(cast){
  if(rFighterLabel) rFighterLabel.textContent=cast.roman.name;
  if(mFighterLabel) mFighterLabel.textContent=cast.morty.name;
  prepFighter(romanEl, romanArt, cast.roman.meta, 1);
  prepFighter(mortyEl, mortyArt, cast.morty.meta, -1);
 }
 function loadCast(cast){
  const rs=cast.roman.meta && (cast.roman.meta.src||'');
  const ms=cast.morty.meta && (cast.morty.meta.src||'');
  return Promise.all([loadImg(rs), loadImg(ms)]).then(function(){ applyCast(cast); });
 }

 /* Frame maps:
    Roman: 0 ready, 1 sword-up, 2 slash/thrust, 3 victory/high
    Morty: 0 crouch/ready, 1 lunge, 2 buzzsaw, 3 jolt throw, 4 victory/spark */
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
 function copySt(st){
  const o={r:Object.assign({},st.r), m:Object.assign({},st.m), rp:st.rp, mp:st.mp};
  o._defend=st._defend; o._shieldDmg=st._shieldDmg; o._hitDmg=st._hitDmg;
  o._hitApplied=st._hitApplied; o._finisherMove=st._finisherMove;
  return o;
 }
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
  st.r.y=0; st.r.rot=0; st.r.frame=0; st.r.scale=1; st.r.sx=1; st.r.sy=1;
  st.m.y=0; st.m.rot=0; st.m.frame=0; st.m.scale=1; st.m.sx=1; st.m.sy=1;
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
   const scale=0.68;
   keys.forEach(function(k){ k.t=Math.round(k.t*scale); });
   Object.keys(marks).forEach(function(k){ marks[k]=Math.round((marks[k]||0)*scale); });
   return {keys:keys, duration:Math.round(duration*scale), st:s, marks:marks};
  }};
 }

  /* Random-roster engine. Each cat independently draws a fighter they have a sheet for.
     Mirror matches are allowed. Both cats can roll all eight fighters, including Marth and Pikachu.
     RULES:
     - No draws. The winner is whoever lands the KO; a failsafe cap guarantees one.
     - Fights trade back and forth. Consecutive attacks by one side are capped at 3.
     - Regular hits deal a random 1–35. Shields take 0–3; dodges take 0.
     - A KO becomes possible at 120%+, with odds climbing toward ~200% and guaranteed by 220%.
     - No move-name labels. Only the % HUD, fighter names, and the winner banner.
     - Thunder (Pikachu down-B) only ever increments the DEFENDER's %. Never the user.
       Thunder is a ranged sky bolt, so Marth Counter is never used against it.
     - Counter (Marth down-B) is Marth-only and only fires against a close-range MELEE
       hit that reaches Marth's body. It is a standing sword swing, not a reflector. */

  const F5={ready:0,attack:1,aerial:2,special:3,victory:4};
  const F_MARTH={ready:0,attack:2,aerial:1,special:2,victory:3};
  const F_PIKA={ready:0,attack:1,aerial:2,special:3,victory:4};

  function rosterIdsFor(cat){
   const out=[];
   const roster=FIGHT.roster||{};
   Object.keys(roster).forEach(function(id){ if(roster[id] && roster[id][cat]) out.push(id); });
   return out;
  }
  function fighterMeta(cat, id){
   const rec=(FIGHT.roster||{})[id];
   return rec && rec[cat] ? rec[cat] : null;
  }
  function fighterName(id){
   const rec=(FIGHT.roster||{})[id];
   return (rec && rec.name) || String(id).toUpperCase();
  }
  function pose(st, side){ return side==='roman'?st.r:st.m; }
  function otherSide(side){ return side==='roman'?'morty':'roman'; }
  function addDmg(st, side, n){ if(side==='roman') st.rp+=n; else st.mp+=n; }
  function sides(s, atk){
   const def=otherSide(atk);
   return {
    atk:atk, def:def,
    A:function(){ return pose(s, atk); },
    D:function(){ return pose(s, def); },
    hurt:function(n){
     let dmg=n;
     if(s._defend==='dodge' || s._defend==='shield') dmg=0;
     else if(s._hitDmg!=null && !s._finisherMove){
      if(!s._hitApplied){ dmg=s._hitDmg; s._hitApplied=1; }
      else dmg=0;
     }
     if(dmg>0) addDmg(s, def, dmg);
    },
    dir:function(){ const A=this.A(), D=this.D(); return A.x<=D.x?1:-1; }
   };
  }
  const KO_MIN=120, KO_SURE=200, KO_CAP=220;
  function koChance(pct){
   if(pct<KO_MIN) return 0;
   if(pct>=KO_CAP) return 1;
   if(pct>=KO_SURE) return 0.88+0.12*(pct-KO_SURE)/(KO_CAP-KO_SURE);
   return 0.08+0.80*(pct-KO_MIN)/(KO_SURE-KO_MIN);
  }
  function decorateDefense(seg, defend, defSide){
   if(!defend || !seg || !seg.keys) return;
   const times=[];
   seg.keys.forEach(function(k){ if(k.impact) times.push(k.t); });
   const t0=times.length?Math.min.apply(null,times)-80:0;
   const t1=times.length?Math.max.apply(null,times)+200:(seg.duration||0);
   seg.keys.forEach(function(k){
    if(k.t>=t0 && k.t<=t1){
     if(defend==='shield') k.shield=defSide;
     if(defend==='dodge') k.dodge=defSide;
    }
    if(k.impact){
     const P=defSide==='roman'?k.r:k.m;
     if(!P) return;
     const face=P.face||(defSide==='roman'?1:-1);
     if(defend==='dodge'){ P.y=8; P.rot=face*-40; P.x=clampX(P.x-face*14,8,94); P.scale=.92; }
     else if(defend==='shield'){ P.y=0; P.rot=face*4; P.x=clampX(P.x+face*4,12,90); P.scale=1; k.blockSpark={x:P.x,y:22}; }
    }
   });
  }
  function frOf(ctx, who){
   const id=who==='atk'?ctx.atkId:ctx.defId;
   const kit=KITS[id];
   return (kit && kit.frames) || F5;
  }
  function koBlast(loser){ return loser==='roman'?'left':'right'; }
  function flyOff(P, loser){
   P.x=loser==='roman'?-20:126;
   P.y=48; P.rot=loser==='roman'?-90:90; P.scale=.76;
  }
  function winPose(P, fr){ P.frame=fr.victory; P.y=0; P.rot=0; P.scale=1; }

  const KITS={};

  function slashOpen(color){
   return makeSeg('def', function(s,rng,ctx,add,marks){
    const fr=frOf(ctx,'atk');
    resetStance(s); add(0);
    add(260, {sparking:ctx.atk}, function(s){ const K=sides(s,ctx.atk); K.A().frame=fr.ready; K.A().x=clampX(K.A().x-K.dir()*4,16,86); });
    const dmg=rng.ri(8,13);
    add(560, {impact:1, trail:{color:color||'white',x:midX(s)+4,y:12,rot:-8}}, function(s){
     const K=sides(s,ctx.atk); const A=K.A(), D=K.D(), d=K.dir();
     A.frame=fr.attack; A.x=clampX(A.x+d*18,16,86); K.hurt(dmg); D.rot=10*d; D.x=clampX(D.x+d*6,12,90);
    });
    add(960, null, function(s){ resetStance(s); });
    return 1100;
   });
  }
  function pokeOpen(frameKey){
   return makeSeg('def', function(s,rng,ctx,add,marks){
    const fr=frOf(ctx,'atk');
    resetStance(s); add(0);
    add(220, null, function(s){ sides(s,ctx.atk).A().frame=fr[frameKey]||fr.attack; });
    const dmg=rng.ri(6,9);
    add(540, {impact:1}, function(s){
     const K=sides(s,ctx.atk); const A=K.A(), D=K.D(), d=K.dir();
     A.frame=fr[frameKey]||fr.attack; A.x=clampX(D.x-d*16,16,86); K.hurt(dmg); D.rot=8*d; D.x=clampX(D.x+d*6,12,90);
    });
    add(900, null, function(s){ resetStance(s); });
    return 1040;
   });
  }
  function spaceOpen(){
   return makeSeg('none', function(s,rng,ctx,add,marks){
    resetStance(s); add(0);
    add(240, null, function(s){ const K=sides(s,ctx.atk); K.A().x=clampX(K.A().x+K.dir()*16,16,86); K.A().frame=0; });
    add(520, null, function(s){ const K=sides(s,ctx.atk); K.A().x=clampX(K.A().x-K.dir()*20,16,86); });
    add(820, null, function(s){ resetStance(s); });
    return 980;
   });
  }
  function multiSlash(colorCycle, hitsMin, hitsMax, tipLast){
   return makeSeg('def', function(s,rng,ctx,add,marks){
    const fr=frOf(ctx,'atk');
    resetStance(s); add(0);
    add(160, null, function(s){ const K=sides(s,ctx.atk); K.A().frame=fr.attack; K.A().x=clampX(K.D().x-K.dir()*32,16,86); });
    const hits=rng.ri(hitsMin, hitsMax);
    let t=160;
    for(let i=0;i<hits;i++){
     t+=rng.ri(220,270);
     const tip=tipLast && i===hits-1 && rng.chance(0.5);
     const dmg=tip?rng.ri(11,16):rng.ri(6,10);
     const color=tip?'white':colorCycle[i%colorCycle.length];
     add(t, {impact:1, trail:{color:color,x:midX(s)+i*2,y:12+i*2,rot:i%2?-14:10}, tipper:tip?{x:sides(s,ctx.atk).D().x,y:16}:null}, function(s){
      const K=sides(s,ctx.atk); const A=K.A(), D=K.D(), d=K.dir();
      A.frame=fr.attack; A.x=clampX(A.x+d*5,16,86); K.hurt(dmg); D.x=clampX(D.x+d*4,12,92); D.y=i===hits-1?8:4; D.rot=(8+i*5)*d; D.frame=0;
     });
    }
    t+=280;
    add(t, null, function(s){ resetStance(s); });
    return t+160;
   });
  }
  function finisherSmash(color, useTipper){
   return makeSeg('def', function(s,rng,ctx,add,marks){
    const fr=frOf(ctx,'atk');
    resetStance(s); add(0);
    add(240, {sparking:ctx.atk}, function(s){ const K=sides(s,ctx.atk); K.A().frame=fr.special||fr.attack; K.A().x=clampX(K.A().x-K.dir()*8,16,86); });
    add(620, {sparking:ctx.atk}, function(s){ sides(s,ctx.atk).A().frame=fr.special||fr.attack; });
    const dmg=rng.ri(18,22);
    marks.fsmash=900;
    add(900, {impact:1, trail:{color:color||'white',x:midX(s),y:16,rot:-8}, tipper:useTipper?{x:sides(s,ctx.atk).D().x,y:18}:null}, function(s){
     const K=sides(s,ctx.atk); const A=K.A(), D=K.D(), d=K.dir();
     A.frame=fr.attack; A.x=clampX(K.D().x-d*22,16,86); K.hurt(dmg); D.rot=24*d; D.y=16; D.x=clampX(D.x+d*8,8,94);
    });
    add(1240, null, function(s){ const K=sides(s,ctx.atk); const D=K.D(), d=K.dir(); D.x=clampX(D.x+d*28, -20, 126); D.y=34; D.rot=55*d; D.scale=.95; });
    marks.ko=1600;
    add(1600, {blast:koBlast(ctx.def), ko:ctx.def}, function(s){ const K=sides(s,ctx.atk); flyOff(K.D(), ctx.def); winPose(K.A(), fr); });
    marks.banner=2040;
    add(2040, {banner:1, blast:koBlast(ctx.def), ko:ctx.def});
    return 2040;
   });
  }
  function finisherBlast(frameKey, blastColor){
   return makeSeg('def', function(s,rng,ctx,add,marks){
    const fr=frOf(ctx,'atk');
    resetStance(s); add(0);
    add(240, {sparking:ctx.atk}, function(s){ sides(s,ctx.atk).A().frame=fr[frameKey]||fr.special; });
    const dmg=rng.ri(16,22);
    marks.boom=820;
    add(820, {impact:1, blast:{x:sides(s,ctx.atk).D().x, top:42, color:blastColor||''}}, function(s){
     const K=sides(s,ctx.atk); const D=K.D(), d=K.dir();
     K.A().frame=fr[frameKey]||fr.special; K.hurt(dmg); D.rot=20*d; D.y=14; D.x=clampX(D.x+d*10,8,94);
    });
    add(1160, null, function(s){ const K=sides(s,ctx.atk); const D=K.D(), d=K.dir(); D.x=clampX(D.x+d*26,-20,126); D.y=36; D.rot=70*d; D.scale=.9; });
    marks.ko=1500;
    add(1500, {blast:koBlast(ctx.def), ko:ctx.def}, function(s){ const K=sides(s,ctx.atk); flyOff(K.D(), ctx.def); winPose(K.A(), fr); });
    marks.banner=1940;
    add(1940, {banner:1, blast:koBlast(ctx.def), ko:ctx.def});
    return 1940;
   });
  }
  function finisherRush(frameKey){
   return makeSeg('def', function(s,rng,ctx,add,marks){
    const fr=frOf(ctx,'atk');
    resetStance(s); add(0);
    add(220, {qa:{x:midX(s),y:10,w:36,rot:-20}, afterimage:ctx.atk, sparking:ctx.atk}, function(s){
     const K=sides(s,ctx.atk); K.A().frame=fr[frameKey]||fr.aerial; K.A().y=8; K.A().x=clampX(K.A().x+K.dir()*12,16,86);
    });
    const dmg=rng.ri(16,22);
    add(700, {impact:1, qa:{x:midX(s),y:8,w:40,rot:0}, afterimage:ctx.atk}, function(s){
     const K=sides(s,ctx.atk); const A=K.A(), D=K.D(), d=K.dir();
     A.frame=fr[frameKey]||fr.attack; A.x=clampX(D.x-d*10,16,86); K.hurt(dmg); D.rot=22*d; D.y=16; D.x=clampX(D.x+d*10,8,94);
    });
    add(1080, null, function(s){ const K=sides(s,ctx.atk); const D=K.D(), d=K.dir(); D.x=clampX(D.x+d*28,-20,126); D.y=36; D.rot=70*d; D.scale=.9; });
    marks.ko=1440;
    add(1440, {blast:koBlast(ctx.def), ko:ctx.def}, function(s){ const K=sides(s,ctx.atk); flyOff(K.D(), ctx.def); winPose(K.A(), fr); });
    marks.banner=1880;
    add(1880, {banner:1, blast:koBlast(ctx.def), ko:ctx.def});
    return 1880;
   });
  }

  /* ===== Animation v2 (pilot fighter: Marth) =====
     Timing is taken from SSBU frame data (startup / active / endlag, ultimateframedata.com),
     played back at ANIM_SLOW so it still reads on a phone.
     Every strike runs: anticipation (squash + lean back, sword drawn) -> snap into the active
     frame (stretch + lunge + sword-arc swipe on the fx canvas) -> follow-through hold -> eased recovery.
     The defender gets hitlag (renderer freeze + jitter), recoil scaled by THIS hit's damage,
     and a tumble spin on big hits, then lands with a squash.
     To move another fighter onto this system: give its kit anim:2 and build its moves with
     strike() / jumpIn() / koLaunch() and a per-fighter swipe palette. Mechanics stay in composeFight. */
  const ANIM_SLOW=1.5;
  function fdt(n){ return n*(1000/60)*ANIM_SLOW/0.68; }   // SSBU frames -> pre-scale segment ms
  function EZ(ctx, atkEase, defEase){ const o={}; o[ctx.atk==='roman'?'ezr':'ezm']=atkEase; o[ctx.atk==='roman'?'ezm':'ezr']=defEase; return o; }
  function isBlocked(s){ return s._defend==='shield' || s._defend==='dodge'; }
  function hitKb(dmg){ return Math.max(0, Math.min(1, ((+dmg||0)-1)/34)); }
  // Split one attack's single 1-35 roll across a multi-hit move (Dancing Blade, Nair) so each slash adds its own %.
  function splitHit(s, weights, fallback){
   let total;
   if(s._hitDmg!=null && !s._finisherMove){ total=s._hitDmg; s._hitApplied=1; }
   else total=fallback;
   const sum=weights.reduce(function(a,b){ return a+b; },0);
   const parts=weights.map(function(w){ return Math.floor(total*w/sum); });
   parts[parts.length-1]+=total-parts.reduce(function(a,b){ return a+b; },0);
   return parts;
  }
  function dealPart(s, ctx, n){
   if(isBlocked(s) || !(n>0)) return;
   addDmg(s, otherSide(ctx.atk), n);
  }
  function defKey(ctx){ return ctx.atk==='roman'?'m':'r'; }
  function atkKey(ctx){ return ctx.atk==='roman'?'r':'m'; }

  /* One SSBU-timed strike. o: {S,A,E frames, wind, hit, rec frame keys, lean, lunge, hop, sw swipe,
     tip, dmg (single-hit roll fallback), part (split damage for multi-hits), kb (0-1 override), launch, dust, keep (stay airborne)} */
  function strike(add, s, ctx, t, o){
   const fr=frOf(ctx,'atk');
   const S=fdt(o.S||8), A=fdt(o.A||3), E=fdt(Math.min(o.E!=null?o.E:20, 18));
   const blocked=isBlocked(s);
   const kb=o.kb!=null?o.kb:hitKb(o.part!=null?o.part:((s._hitDmg!=null && !s._finisherMove)?s._hitDmg:(o.dmg||10)));
   const hop=o.hop||0;
   add(t+S*0.6, Object.assign({fs:0}, EZ(ctx,'out','inout'), o.dust?{dust:{by:ctx.atk}}:{}), function(s){
    const K=sides(s,ctx.atk), P=K.A(), d=K.dir();
    P.frame=fr[o.wind||'aerial']; P.x=clampX(P.x-d*(o.lean!=null?o.lean:3),12,88);
    P.sx=1.08; P.sy=.9; P.rot=-(o.tilt!=null?o.tilt:4)*d; P.y=hop?hop:0;
   });
   add(t+S, Object.assign({}, EZ(ctx,'inout','inout'), o.sw?{sw:Object.assign({by:ctx.atk, dur:Math.round(A*0.68)+60}, o.sw)}:{}), function(s){
    const K=sides(s,ctx.atk), P=K.A(), d=K.dir();
    P.sx=1.03; P.sy=.96; P.rot=-(o.tilt!=null?o.tilt+2:6)*d;
   });
   const hitT=t+S+fdt(1);
   const k=add(hitT, Object.assign({impact:1, fs:0, hl:otherSide(ctx.atk)}, EZ(ctx,'snap','snap'), o.extra||{}), function(s){
    const K=sides(s,ctx.atk), P=K.A(), D=K.D(), d=K.dir();
    P.frame=fr[o.hit||'attack']; P.x=clampX(P.x+d*(o.lunge!=null?o.lunge:8),12,88);
    const gap=o.minGap!=null?o.minGap:12;
    if((D.x-P.x)*d<gap) P.x=clampX(D.x-d*gap,12,88);
    P.sx=1.13; P.sy=.9; P.rot=3*d;
    if(o.part!=null) dealPart(s, ctx, o.part); else K.hurt(o.dmg||10);
    if(!blocked){ D.x=clampX(D.x+d*(1.5+3*kb),8,92); D.rot=(6+14*kb)*d; D.sx=.88; D.sy=1.1; D.y=Math.max(D.y||0, hop*0.6); }
   });
   if(o.tip){ const D=k[defKey(ctx)]; k.tipper={x:D.x, y:(D.y||0)+18}; }
   add(hitT+A, EZ(ctx,'out','out'), function(s){
    const K=sides(s,ctx.atk), P=K.A(), D=K.D(), d=K.dir();
    P.sx=1.05; P.sy=.97; P.rot=0;
    if(!blocked && !o.keep){
     D.x=clampX(D.x+d*(2+9*kb),8,92);
     D.y=o.launch?(10+34*kb):(hop?hop*0.6:0)+2+6*kb;
     D.rot=(kb>0.62?(200+150*kb):(10+22*kb))*d; D.sx=1; D.sy=1;
    }
   });
   if(o.keep) return {t:hitT+A, hitT:hitT, key:k};
   const endT=hitT+A+E;
   add(hitT+A+E*0.55, EZ(ctx,'inout','in'), function(s){
    const K=sides(s,ctx.atk), P=K.A(), D=K.D(), d=K.dir();
    P.frame=fr[o.rec||'ready']; P.y=hop?hop*0.25:0; P.sx=.97; P.sy=1.03;
    if(!blocked){ D.y=0; D.rot=Math.round((D.rot||0)/360)*360; D.sx=1.1; D.sy=.88; }
   });
   add(endT, Object.assign({}, EZ(ctx,'back','back'), hop?{dust:{by:ctx.atk}}:{}), function(s){
    const K=sides(s,ctx.atk), P=K.A(), D=K.D();
    P.y=0; P.sx=1; P.sy=1; P.rot=0;
    if(!blocked){ D.sx=1; D.sy=1; }
   });
   add(endT+2, EZ(ctx,'hold','hold'), function(s){ const D=sides(s,ctx.atk).D(); if(Math.abs(D.rot||0)%360===0) D.rot=0; });
   return {t:endT+2, hitT:hitT, key:k};
  }
  // Jumpsquat (3f) + rise to a short-hop height.
  function jumpIn(add, s, ctx, t, height, fwd){
   add(t+fdt(3), Object.assign({dust:{by:ctx.atk}}, EZ(ctx,'out','inout')), function(s){ const P=sides(s,ctx.atk).A(); P.sx=1.14; P.sy=.84; P.frame=0; });
   add(t+fdt(3)+fdt(7), EZ(ctx,'out','inout'), function(s){ const K=sides(s,ctx.atk), P=K.A(); P.y=height; P.sx=.93; P.sy=1.09; P.x=clampX(P.x+K.dir()*(fwd||6),12,88); });
   return t+fdt(10);
  }
  // Dash in with dust + slight forward lean (SSBU initial dash).
  function dashTo(add, s, ctx, t, gapPct, frames){
   add(t+fdt(frames||8), Object.assign({dust:{by:ctx.atk}}, EZ(ctx,'out','inout')), function(s){
    const K=sides(s,ctx.atk), P=K.A(), D=K.D(), d=K.dir();
    P.x=clampX(D.x-d*gapPct,12,88); P.rot=8*d; P.sx=1.06; P.sy=.95; P.frame=0;
   });
   return t+fdt(frames||8);
  }
  // Killing blow follow-up: tumble off the blast zone, attacker strikes a victory pose.
  function koLaunch(add, s, ctx, t, marks, up){
   const fr=frOf(ctx,'atk');
   add(t+fdt(12), EZ(ctx,'out','out'), function(s){
    const K=sides(s,ctx.atk), D=K.D(), d=K.dir();
    if(up){ D.y=110; D.x=clampX(D.x+d*8,-20,126); D.rot=300*d; const P=K.A(); P.y=72; P.frame=fr.victory; P.sx=.94; P.sy=1.08; }
    else { D.x=clampX(D.x+d*30,-20,126); D.y=42; D.rot=280*d; }
    D.scale=.88; D.sx=1; D.sy=1;
   });
   t+=fdt(26); marks.ko=t;
   add(t, Object.assign({blast:up?{x:sides(s,ctx.atk).D().x, top:6}:koBlast(ctx.def), ko:ctx.def}, EZ(ctx,up?'in':'back','in'), up?{dust:{by:ctx.atk}}:{}), function(s){
    const K=sides(s,ctx.atk), D=K.D(), d=K.dir();
    if(up){ D.y=240; D.rot=560*d; D.scale=.7; } else { flyOff(D, ctx.def); D.rot=(ctx.def==='roman'?-1:1)*540; }
    winPose(K.A(), fr); K.A().sx=1; K.A().sy=1;
   });
   t+=440; marks.banner=t;
   add(t, {banner:1, blast:up?'bottom':koBlast(ctx.def), ko:ctx.def});
   return t;
  }

  /* Marth, per SSBU frame data + how top Marth players use him:
     - Neutral: dash-dance spacing, short-hop fast-fall Fair / Nair, Dtilt pokes at max range (tipper).
     - Pressure: Dancing Blade (DB4 delayed for the tipper, like MkLeo), Ftilt, Utilt, Shield Breaker vs shields.
     - KOs: tipper Fsmash (Nair -> Fsmash confirm), DB4 tipper, Up-B (Dolphin Slash) out of shield, Counter, tipper Shield Breaker.
     Swipe colours: Falchion arcs are blue-white; tippers flash white/gold. Dancing Blade cycles blue/red/green by path. */
  const MARTH_ARC={col:'#7cc6ff', r:60, dx:6, dy:44, w:15};
  function marc(a0, a1, extra){ return Object.assign({}, MARTH_ARC, {a0:a0, a1:a1}, extra||{}); }

  function marthDtilt(){
   return makeSeg('def', function(s,rng,ctx,add,marks){
    resetStance(s); add(0);
    let t=dashTo(add, s, ctx, 0, 15, 7);
    const r=strike(add, s, ctx, t, {S:7, A:2, E:15, wind:'ready', hit:'attack', lean:2, lunge:3, tilt:-2, sw:marc(-8,-22,{r:66, dy:14, w:10}), tip:true, dmg:rng.ri(7,10)});
    marks.swing=r.hitT;
    return r.t+fdt(4);
   });
  }
  function marthFair(){
   return makeSeg('def', function(s,rng,ctx,add,marks){
    resetStance(s); add(0);
    let t=dashTo(add, s, ctx, 0, 22, 6);
    t=jumpIn(add, s, ctx, t, 30, 5);
    const r=strike(add, s, ctx, t, {S:6, A:3, E:20, wind:'aerial', hit:'attack', hop:30, lean:1, lunge:4, sw:marc(115,-40,{dy:40}), tip:true, dmg:rng.ri(8,12)});
    marks.swing=r.hitT;
    return r.t+fdt(3);
   });
  }
  function marthNair(){
   return makeSeg('def', function(s,rng,ctx,add,marks){
    resetStance(s); add(0);
    let t=dashTo(add, s, ctx, 0, 18, 6);
    t=jumpIn(add, s, ctx, t, 28, 4);
    const parts=splitHit(s, [0.4,0.6], rng.ri(9,13));
    const h1=strike(add, s, ctx, t, {S:6, A:2, wind:'aerial', hit:'attack', hop:28, lean:1, lunge:2, sw:marc(-60,200,{r:54, dy:36, w:12}), part:parts[0], kb:.12, keep:true});
    marks.swing=h1.hitT;
    const r=strike(add, s, ctx, h1.t+fdt(3), {S:6, A:3, E:18, wind:'aerial', hit:'attack', hop:14, lean:0, lunge:3, sw:marc(200,-40,{r:62, dy:30}), tip:true, part:parts[1]});
    return r.t+fdt(3);
   });
  }
  function marthFtilt(){
   return makeSeg('def', function(s,rng,ctx,add,marks){
    resetStance(s); add(0);
    let t=dashTo(add, s, ctx, 0, 16, 7);
    const r=strike(add, s, ctx, t, {S:8, A:4, E:20, wind:'ready', hit:'aerial', lean:3, lunge:5, tilt:-6, sw:marc(-30,85,{r:64}), tip:true, dmg:rng.ri(9,13)});
    marks.swing=r.hitT;
    return r.t+fdt(3);
   });
  }
  function marthUtilt(){
   return makeSeg('def', function(s,rng,ctx,add,marks){
    resetStance(s); add(0);
    let t=dashTo(add, s, ctx, 0, 12, 6);
    const r=strike(add, s, ctx, t, {S:6, A:6, E:20, wind:'ready', hit:'victory', lean:1, lunge:2, sw:marc(-20,190,{r:58, dy:40}), dmg:rng.ri(6,10), launch:true});
    marks.swing=r.hitT;
    return r.t+fdt(3);
   });
  }
  function marthBreaker(tipChance){
   return makeSeg('def', function(s,rng,ctx,add,marks){
    resetStance(s); add(0);
    const charge=rng.ri(0,18);
    // Charge: sword drawn back and low, crouched, glowing (Shield Breaker hold).
    add(fdt(8), Object.assign({fs:0, sparking:ctx.atk}, EZ(ctx,'out','inout')), function(s){ const K=sides(s,ctx.atk), P=K.A(), d=K.dir(); P.frame=0; P.x=clampX(P.x-d*4,12,88); P.sx=1.12; P.sy=.86; P.rot=-6*d; });
    add(fdt(17+charge), Object.assign({sparking:ctx.atk}, EZ(ctx,'inout','inout')), function(s){ const K=sides(s,ctx.atk), P=K.A(); P.sx=1.14; P.sy=.84; });
    const t=fdt(19+charge);
    const tip=rng.chance(tipChance==null?0.5:tipChance);
    add(t, Object.assign({}, EZ(ctx,'snap','inout'), {afterimage:ctx.atk}), function(s){ const K=sides(s,ctx.atk), P=K.A(), D=K.D(), d=K.dir(); P.x=clampX(D.x-d*(tip?15:12),12,88); });
    const r=strike(add, s, ctx, t, {S:1, A:2, E:22, wind:'ready', hit:'attack', lean:0, lunge:3, tilt:0, sw:{kind:'stab', col:'#9fd8ff', r:30, len:70, dx:0, dy:30, w:7}, tip:tip, dmg:rng.ri(8,14)});
    marks.swing=r.hitT;
    return r.t+fdt(3);
   });
  }
  function marthDancingBlade(asFinisher){
   return makeSeg('def', function(s,rng,ctx,add,marks){
    resetStance(s); add(0);
    let t=dashTo(add, s, ctx, 0, 17, 6);
    const path=asFinisher?'side':rng.pick(['side','side','up','down']);
    const cols=path==='up'?['#7cc6ff','#ff5a5a','#ff5a5a','#ff5a5a']:(path==='down'?['#7cc6ff','#7cc6ff','#3dff8a','#3dff8a']:['#7cc6ff','#7cc6ff','#7cc6ff','#7cc6ff']);
    // DB1 9f, DB2 5f, DB3 4f, DB4 7f startup; DB4 is delayed a beat so it lands the tipper.
    const S=[9,5,4,7];
    const arcs=[marc(-25,70),marc(70,-30),path==='up'?marc(-40,140):marc(-30,60),path==='down'?marc(160,-60,{dy:20}):marc(120,-35,{r:66})];
    const frames=[['ready','aerial'],['aerial','attack'],['ready','aerial'],['aerial','attack']];
    const parts=asFinisher?[rng.ri(2,4),rng.ri(2,4),rng.ri(3,5),rng.ri(6,9)]:splitHit(s,[0.18,0.2,0.24,0.38],10);
    for(let i=0;i<4;i++){
     const last=i===3;
     if(last) t+=fdt(6);
     const tip=last && (asFinisher || rng.chance(0.55));
     const r=strike(add, s, ctx, t, {S:S[i], A:last?3:2, E:last?24:0, wind:frames[i][0], hit:frames[i][1], lean:i===0?3:1, lunge:last?5:3, tilt:i%2?-3:5,
      sw:Object.assign({}, arcs[i], {col:cols[i]}, tip?{col:'#ffffff', glow:'#ffe56a'}:{}), tip:tip, part:parts[i], kb:last?null:.14, keep:!last});
     if(i===0) marks.swing=r.hitT;
     if(last) marks.fsmash=r.hitT;
     t=r.t+(last?0:fdt(5));
    }
    return t+fdt(3);
   });
  }

  function marthDashDance(){
   return makeSeg('none', function(s,rng,ctx,add,marks){
    resetStance(s); add(0);
    // Dash dance at the edge of sword range: dash in, pivot out, dash back in, stop just outside tipper range.
    add(fdt(9), Object.assign({dust:{by:ctx.atk}}, EZ(ctx,'out','inout')), function(s){ const K=sides(s,ctx.atk), P=K.A(), d=K.dir(); P.x=clampX(P.x+d*11,12,88); P.rot=8*d; P.sx=1.06; P.sy=.95; });
    add(fdt(14), Object.assign({}, EZ(ctx,'inout','inout')), function(s){ const K=sides(s,ctx.atk), P=K.A(), d=K.dir(); P.rot=-6*d; P.sx=.95; P.sy=1.05; });
    add(fdt(24), Object.assign({dust:{by:ctx.atk}}, EZ(ctx,'out','inout')), function(s){ const K=sides(s,ctx.atk), P=K.A(), d=K.dir(); P.x=clampX(P.x-d*9,12,88); P.rot=-8*d; P.sx=1.05; P.sy=.96; });
    add(fdt(34), Object.assign({dust:{by:ctx.atk}}, EZ(ctx,'out','inout')), function(s){ const K=sides(s,ctx.atk), P=K.A(), d=K.dir(); P.x=clampX(P.x+d*6,12,88); P.rot=6*d; });
    add(fdt(44), Object.assign({}, EZ(ctx,'back','inout')), function(s){ const P=sides(s,ctx.atk).A(); P.rot=0; P.sx=1; P.sy=1; });
    return fdt(50);
   });
  }

  KITS.marth={
   frames:F_MARTH,
   anim:2,
   hasCounter:true,
   heavy:['dancing-blade','tipper-space'],
   openings:{ space:marthDashDance(), 'breaker-poke':marthDtilt(), neutral:marthFair() },
   mids:{
    'dancing-blade':marthDancingBlade(false),
    'tipper-space':marthFair(),
    'ff-nair':marthNair(),
    ftilt:marthFtilt(),
    utilt:marthUtilt(),
    'shield-breaker':marthBreaker(0.45)
   },
   finishers:{
    fsmash:makeSeg('def', function(s,rng,ctx,add,marks){
     // Short-hop fast-fall Nair (1 hit) -> tipper Fsmash: the classic Marth kill confirm.
     resetStance(s); add(0);
     let t=dashTo(add, s, ctx, 0, 17, 6);
     t=jumpIn(add, s, ctx, t, 24, 3);
     const n1=strike(add, s, ctx, t, {S:6, A:2, wind:'aerial', hit:'attack', hop:24, lean:0, lunge:1, sw:marc(-60,180,{r:52, dy:34, w:11}), dmg:rng.ri(3,5), kb:.12, keep:true});
     // fast-fall + land
     add(n1.t+fdt(5), Object.assign({dust:{by:ctx.atk}}, EZ(ctx,'in','out')), function(s){ const K=sides(s,ctx.atk), P=K.A(), D=K.D(), d=K.dir(); P.y=0; P.sx=1.14; P.sy=.86; P.frame=0; P.x=clampX(D.x-d*15,12,88); });
     t=n1.t+fdt(8);
     // Fsmash: 10f startup with a short charge hold (sword cocked high behind).
     add(t+fdt(4), Object.assign({fs:0, sparking:ctx.atk}, EZ(ctx,'out','inout')), function(s){ const K=sides(s,ctx.atk), P=K.A(), d=K.dir(); P.frame=1; P.sx=1.1; P.sy=.88; P.rot=-10*d; P.x=clampX(P.x-d*3,12,88); });
     add(t+fdt(22), Object.assign({sparking:ctx.atk}, EZ(ctx,'inout','inout')), function(s){ const K=sides(s,ctx.atk), P=K.A(), d=K.dir(); P.sx=1.12; P.sy=.86; P.rot=-12*d; });
     const r=strike(add, s, ctx, t+fdt(22), {S:6, A:4, E:0, wind:'aerial', hit:'attack', lean:0, lunge:6, tilt:12, sw:marc(130,-45,{r:70, col:'#ffffff', glow:'#ffe56a', w:18}), tip:true, dmg:rng.ri(17,22), kb:1, keep:true, extra:{kohit:1}});
     marks.fsmash=r.hitT;
     return koLaunch(add, s, ctx, r.t, marks, false);
    }),
    'db-tipper':makeSeg('def', function(s,rng,ctx,add,marks){
     // inline the DB string, then launch off the delayed DB4 tipper
     resetStance(s); add(0);
     let t=dashTo(add, s, ctx, 0, 15, 6);
     const S=[9,5,4,7];
     const arcs=[marc(-25,70),marc(70,-30),marc(-30,60),marc(120,-35,{r:68, col:'#ffffff', glow:'#ffe56a', w:18})];
     const frames=[['ready','aerial'],['aerial','attack'],['ready','aerial'],['aerial','attack']];
     for(let i=0;i<4;i++){
      const last=i===3;
      if(last) t+=fdt(8);
      const r=strike(add, s, ctx, t, {S:S[i], A:last?4:2, E:0, wind:frames[i][0], hit:frames[i][1], lean:i===0?3:1, lunge:last?5:3, tilt:i%2?-3:5,
       sw:Object.assign({}, arcs[i]), tip:last, dmg:last?rng.ri(10,14):rng.ri(2,4), kb:last?1:.14, keep:true, extra:last?{kohit:1}:null});
      if(last){ marks.fsmash=r.hitT; return koLaunch(add, s, ctx, r.t, marks, false); }
      t=r.t+fdt(5);
     }
     return t;
    }),
    dolphin:makeSeg('def', function(s,rng,ctx,add,marks){
     // Up-B out of shield: shield up, drop it on frame 5, rising slash with the hit on the way up.
     resetStance(s);
     const K0=sides(s,ctx.atk);
     K0.A().x=clampX(K0.D().x-K0.dir()*13,12,88);
     add(0, {shield:ctx.atk});
     add(fdt(10), Object.assign({shield:ctx.atk}, EZ(ctx,'inout','inout')), function(s){ const K=sides(s,ctx.atk), P=K.A(); P.sx=1.05; P.sy=.94; });
     add(fdt(10)+fdt(1), Object.assign({shield:'none'}, EZ(ctx,'snap','inout')), function(s){ const P=sides(s,ctx.atk).A(); P.sx=1.1; P.sy=.88; });
     const r=strike(add, s, ctx, fdt(11), {S:4, A:6, E:0, wind:'ready', hit:'victory', lean:0, lunge:3, tilt:-4, hop:30, sw:marc(-70,95,{r:58, dy:30, col:'#ffffff', glow:'#9fd8ff', w:16}), dmg:rng.ri(11,14), kb:1, keep:true, extra:{kohit:1}});
     marks.spike=r.hitT; marks.fsmash=r.hitT;
     return koLaunch(add, s, ctx, r.t, marks, true);
    }),
    counter:makeSeg('def', function(s,rng,ctx,add,marks){
     // Opponent swings in; Marth's Counter (6f start, window 6-27) catches it, then the 4f counter-slash.
     const fr=F_MARTH;
     const ofr=frOf(ctx,'def');
     resetStance(s);
     pose(s,ctx.atk).x=ctx.atk==='roman'?30:70;
     pose(s,ctx.def).x=ctx.def==='roman'?30:76;
     faceSt(s); add(0);
     add(fdt(10), Object.assign({fs:0, qa:{x:midX(s),y:12,w:32,rot:-28}, afterimage:ctx.def}, EZ(ctx,'inout','out')), function(s){
      const K=sides(s,ctx.atk); K.D().x=clampX(K.A().x+K.dir()*22,16,86); K.D().y=14; K.D().frame=ofr.attack||ofr.aerial; K.D().sx=1.08; K.D().sy=.94;
     });
     add(fdt(16), Object.assign({fs:0}, EZ(ctx,'out','inout')), function(s){ const K=sides(s,ctx.atk), P=K.A(), d=K.dir(); P.frame=fr.aerial; P.sx=.96; P.sy=1.05; P.rot=-4*d; });
     add(fdt(20), Object.assign({sparking:ctx.def}, EZ(ctx,'inout','in')), function(s){
      const K=sides(s,ctx.atk); K.D().x=clampX(K.A().x+K.dir()*11,16,86); K.D().y=16; K.D().frame=ofr.aerial||ofr.attack; K.D().rot=-16*K.dir();
     });
     marks.counter=Math.round(fdt(22));
     add(fdt(22), Object.assign({counter:ctx.atk, hl:ctx.def, freeze:1}, EZ(ctx,'snap','snap')), function(s){ const K=sides(s,ctx.atk), P=K.A(); P.frame=fr.aerial; P.y=0; P.sx=1.06; P.sy=.94; K.D().sx=1; K.D().sy=1; });
     const r=strike(add, s, ctx, fdt(30), {S:4, A:4, E:0, wind:'aerial', hit:'attack', lean:0, lunge:4, tilt:6, sw:marc(120,-40,{r:66, col:'#ffffff', glow:'#9fd8ff', w:17}), tip:true, dmg:rng.ri(12,18), kb:1, keep:true, extra:{counter:ctx.atk, kohit:1}});
     marks.slash=r.hitT;
     return koLaunch(add, s, ctx, r.t, marks, false);
    }),
    'breaker-tipper':makeSeg('def', function(s,rng,ctx,add,marks){
     resetStance(s); add(0);
     add(fdt(8), Object.assign({fs:0, sparking:ctx.atk}, EZ(ctx,'out','inout')), function(s){ const K=sides(s,ctx.atk), P=K.A(), d=K.dir(); P.frame=0; P.x=clampX(P.x-d*4,12,88); P.sx=1.12; P.sy=.86; P.rot=-6*d; });
     add(fdt(40), Object.assign({sparking:ctx.atk}, EZ(ctx,'inout','inout')), function(s){ const P=sides(s,ctx.atk).A(); P.sx=1.16; P.sy=.82; });
     add(fdt(46), Object.assign({afterimage:ctx.atk}, EZ(ctx,'snap','inout')), function(s){ const K=sides(s,ctx.atk), P=K.A(), D=K.D(), d=K.dir(); P.x=clampX(D.x-d*15,12,88); });
     const r=strike(add, s, ctx, fdt(46), {S:1, A:3, E:0, wind:'ready', hit:'attack', lean:0, lunge:3, tilt:0, sw:{kind:'stab', col:'#ffffff', glow:'#ffe56a', r:30, len:80, dx:0, dy:30, w:9}, tip:true, dmg:rng.ri(18,24), kb:1, keep:true, extra:{kohit:1}});
     marks.fsmash=r.hitT;
     return koLaunch(add, s, ctx, r.t, marks, false);
    })
   }
  };

  KITS.pikachu={
   frames:F_PIKA,
   heavy:['grab-aerial','spin-nair'],
   openings:{
    'qa-rush':makeSeg('def', function(s,rng,ctx,add,marks){
     const fr=F_PIKA;
     resetStance(s); add(0);
     add(220, {qa:{x:midX(s),y:10,w:36,rot:-30}, afterimage:ctx.atk}, function(s){
      const K=sides(s,ctx.atk); K.A().x=clampX(midX(s),16,86); K.A().y=12; K.A().frame=fr.attack;
     });
     const hit=rng.chance(0.7);
     if(hit){
      const dmg=rng.ri(3,6);
      add(480, {impact:1}, function(s){
       const K=sides(s,ctx.atk); const A=K.A(), D=K.D(), d=K.dir();
       K.hurt(dmg); A.x=clampX(D.x-d*12,16,86); A.y=4; A.frame=fr.attack; D.rot=8*d; D.x=clampX(D.x-d*3,16,86);
      });
     } else {
      add(480, {qa:{x:midX(s)-8,y:8,w:28,rot:-10}, afterimage:ctx.atk}, function(s){
       const K=sides(s,ctx.atk); K.A().x=clampX(K.D().x-K.dir()*18,16,86); K.A().y=8; K.A().frame=fr.attack;
      });
     }
     add(860, null, function(s){ resetStance(s); });
     return 1000;
    }),
    'jolt-poke':makeSeg('def', function(s,rng,ctx,add,marks){
     const fr=F_PIKA;
     resetStance(s); add(0);
     add(180, {jolt:{show:1,x:sides(s,ctx.atk).A().x,y:10}}, function(s){ sides(s,ctx.atk).A().frame=fr.special; });
     add(380, {jolt:{show:1,x:midX(s),y:8}});
     const dmg=rng.ri(6,8);
     add(560, {impact:1, jolt:{show:1,x:sides(s,ctx.atk).D().x,y:6}}, function(s){
      const K=sides(s,ctx.atk); K.hurt(dmg); K.D().rot=-10*K.dir(); K.D().x=clampX(K.D().x+K.dir()*4,16,90);
     });
     add(900, {jolt:{show:0}}, function(s){ resetStance(s); });
     return 1040;
    })
   },
   mids:{
    'grab-aerial':makeSeg('def', function(s,rng,ctx,add,marks){
     const fr=F_PIKA;
     resetStance(s); add(0);
     add(200, {qa:{x:midX(s)+8,y:6,w:30,rot:-20}, afterimage:ctx.atk}, function(s){
      const K=sides(s,ctx.atk); K.A().x=K.D().x-K.dir()*14; K.A().y=4; K.A().frame=fr.attack;
     });
     add(400, null, function(s){ const K=sides(s,ctx.atk); K.A().x=K.D().x-K.dir()*8; K.A().y=2; K.A().frame=fr.ready; K.D().rot=6*K.dir(); });
     const dthrow=rng.ri(5,7);
     add(620, {impact:1}, function(s){ const K=sides(s,ctx.atk); K.hurt(dthrow); K.D().y=22; K.D().x=clampX(K.D().x+K.dir()*6,16,86); K.D().rot=12*K.dir(); K.A().frame=fr.attack; });
     let t=620;
     const nairs=rng.ri(2,3);
     for(let i=0;i<nairs;i++){
      t+=rng.ri(240,280);
      const dmg=rng.ri(8,12);
      add(t, {impact:1, sparking:ctx.atk}, function(s){
       const K=sides(s,ctx.atk); const A=K.A(), D=K.D(), d=K.dir();
       A.frame=fr.aerial; A.y=18+i*4; A.x=D.x-d*4; A.rot=(i%2?-16:14)*d;
       K.hurt(dmg); D.y=20+i*5; D.rot=(10+i*6)*d;
      });
     }
     t+=300;
     add(t, null, function(s){ resetStance(s); });
     return t+160;
    }),
    'qa-pressure':makeSeg('def', function(s,rng,ctx,add,marks){
     const fr=F_PIKA;
     resetStance(s); add(0);
     add(180, {qa:{x:midX(s)+10,y:12,w:32,rot:200}, afterimage:ctx.atk}, function(s){ const K=sides(s,ctx.atk); K.A().x=clampX(midX(s),16,86); K.A().y=14; K.A().frame=fr.attack; });
     add(380, {qa:{x:midX(s)-8,y:8,w:28,rot:160}, afterimage:ctx.atk}, function(s){ const K=sides(s,ctx.atk); K.A().x=clampX(K.D().x-K.dir()*8,16,86); K.A().y=8; K.A().frame=fr.attack; });
     const dmg=rng.ri(4,7);
     add(600, {impact:1, qa:{x:sides(s,ctx.atk).D().x,y:4,w:24,rot:10}}, function(s){
      const K=sides(s,ctx.atk); K.hurt(dmg); K.A().x=K.D().x-K.dir()*10; K.A().y=2; K.D().rot=8*K.dir(); K.D().x=clampX(K.D().x-K.dir()*4,16,86);
     });
     if(rng.chance(0.6)){
      const dmg2=rng.ri(6,10);
      add(840, {impact:1, sparking:ctx.atk}, function(s){ const K=sides(s,ctx.atk); K.A().frame=fr.aerial; K.A().y=16; K.hurt(dmg2); K.D().y=10; K.D().rot=12*K.dir(); });
      add(1120, null, function(s){ resetStance(s); });
      return 1260;
     }
     add(920, null, function(s){ resetStance(s); });
     return 1080;
    }),
    'jolt-bounce':makeSeg('def', function(s,rng,ctx,add,marks){
     const fr=F_PIKA;
     resetStance(s); add(0);
     add(160, {jolt:{show:1,x:sides(s,ctx.atk).A().x,y:6}}, function(s){ sides(s,ctx.atk).A().frame=fr.special; });
     add(340, {jolt:{show:1,x:midX(s)+6,y:14}});
     add(500, {jolt:{show:1,x:midX(s)-8,y:4}});
     const dmg=rng.ri(6,9);
     add(680, {impact:1, jolt:{show:1,x:sides(s,ctx.atk).D().x,y:8}}, function(s){ const K=sides(s,ctx.atk); K.hurt(dmg); K.D().rot=-8*K.dir(); K.D().x=clampX(K.D().x+K.dir()*3,16,90); });
     add(960, {jolt:{show:0}}, function(s){ resetStance(s); });
     return 1100;
    }),
    'spin-nair':makeSeg('def', function(s,rng,ctx,add,marks){
     const fr=F_PIKA;
     resetStance(s); add(0);
     add(200, {qa:{x:midX(s),y:10,w:28,rot:-24}, afterimage:ctx.atk}, function(s){ const K=sides(s,ctx.atk); K.A().x=K.D().x-K.dir()*18; K.A().y=16; K.A().frame=fr.aerial; });
     const dmg=rng.ri(8,12);
     add(440, {impact:1, sparking:ctx.atk}, function(s){ const K=sides(s,ctx.atk); K.A().x=K.D().x-K.dir()*6; K.A().y=14; K.A().frame=fr.aerial; K.A().rot=-18*K.dir(); K.hurt(dmg); K.D().rot=10*K.dir(); K.D().y=8; });
     const dmg2=rng.ri(7,11);
     add(700, {impact:1, sparking:ctx.atk}, function(s){ const K=sides(s,ctx.atk); K.A().rot=16*K.dir(); K.A().y=18; K.hurt(dmg2); K.D().y=14; K.D().x=clampX(K.D().x-K.dir()*6,16,86); });
     add(1020, null, function(s){ resetStance(s); });
     return 1160;
    })
   },
   finishers:{
    thunder:makeSeg('def', function(s,rng,ctx,add,marks){
     const fr=F_PIKA;
     resetStance(s);
     pose(s,ctx.atk).x=ctx.atk==='roman'?28:72;
     pose(s,ctx.def).x=ctx.def==='roman'?28:72;
     faceSt(s); add(0);
     add(220, null, function(s){ sides(s,ctx.atk).A().frame=fr.victory; });
     marks.thunder=480;
     add(480, {cloud:{show:1,x:sides(s,ctx.atk).D().x}}, function(s){ sides(s,ctx.atk).A().frame=fr.victory; });
     const dmg=rng.ri(12,16);
     marks.bolt=820;
     add(820, {cloud:{show:1,x:sides(s,ctx.atk).D().x}, bolt:{show:1,x:sides(s,ctx.atk).D().x}, impact:1}, function(s){
      const K=sides(s,ctx.atk); K.hurt(dmg); K.D().rot=16*K.dir(); K.D().y=8; K.D().frame=0;
     });
     add(1120, {cloud:{show:0}, bolt:{show:0}}, function(s){ const K=sides(s,ctx.atk); K.D().x=clampX(K.D().x-K.dir()*18,0,100); K.D().y=28; K.D().rot=50*K.dir(); K.D().scale=.95; });
     marks.ko=1480;
     add(1480, {blast:koBlast(ctx.def), ko:ctx.def}, function(s){ const K=sides(s,ctx.atk); flyOff(K.D(), ctx.def); winPose(K.A(), fr); });
     marks.banner=1920;
     add(1920, {banner:1, blast:koBlast(ctx.def), ko:ctx.def});
     return 1920;
    }),
    aerial:makeSeg('def', function(s,rng,ctx,add,marks){
     const fr=F_PIKA;
     resetStance(s); add(0);
     add(200, {qa:{x:midX(s),y:10,w:30,rot:-20}, afterimage:ctx.atk}, function(s){ const K=sides(s,ctx.atk); K.A().x=K.D().x-K.dir()*16; K.A().y=16; K.A().frame=fr.aerial; });
     let t=200;
     const hits=3;
     for(let i=0;i<hits;i++){
      t+=rng.ri(230,270);
      const last=i===hits-1;
      const dmg=last?rng.ri(12,16):rng.ri(8,12);
      add(t, {impact:1, sparking:ctx.atk}, function(s){
       const K=sides(s,ctx.atk); const A=K.A(), D=K.D(), d=K.dir();
       A.frame=fr.aerial; A.y=16+i*3; A.rot=(i%2?-18:16)*d; A.x=D.x-d*6;
       K.hurt(dmg); D.y=8+i*6; D.rot=(10+i*8)*d; if(last) D.x=clampX(D.x+d*8,8,94);
      });
     }
     t+=320;
     add(t, null, function(s){ const K=sides(s,ctx.atk); const D=K.D(), d=K.dir(); D.x=clampX(D.x+d*24,-20,126); D.y=36; D.rot=70*d; D.scale=.9; });
     t+=360; marks.ko=t;
     add(t, {blast:koBlast(ctx.def), ko:ctx.def}, function(s){ const K=sides(s,ctx.atk); flyOff(K.D(), ctx.def); winPose(K.A(), fr); });
     t+=420; marks.banner=t;
     add(t, {banner:1, blast:koBlast(ctx.def), ko:ctx.def});
     return t;
    }),
    skullbash:makeSeg('def', function(s,rng,ctx,add,marks){
     const fr=F_PIKA;
     resetStance(s); add(0);
     add(200, {sparking:ctx.atk}, function(s){ const K=sides(s,ctx.atk); K.A().frame=fr.special; K.A().x=clampX(K.A().x-K.dir()*8,16,86); });
     add(520, {sparking:ctx.atk, qa:{x:midX(s),y:8,w:40,rot:0}}, function(s){ const K=sides(s,ctx.atk); K.A().frame=fr.attack; K.A().x=clampX(K.A().x+K.dir()*20,16,86); });
     const dmg=rng.ri(16,22);
     add(820, {impact:1, qa:{x:sides(s,ctx.atk).D().x,y:6,w:28,rot:0}}, function(s){
      const K=sides(s,ctx.atk); const A=K.A(), D=K.D(), d=K.dir();
      A.x=clampX(D.x-d*8,16,86); A.frame=fr.attack; K.hurt(dmg); D.rot=24*d; D.y=14; D.x=clampX(D.x+d*10,8,94);
     });
     add(1180, null, function(s){ const K=sides(s,ctx.atk); const D=K.D(), d=K.dir(); D.x=clampX(D.x+d*28,-20,126); D.y=32; D.rot=60*d; D.scale=.92; });
     marks.ko=1520;
     add(1520, {blast:koBlast(ctx.def), ko:ctx.def}, function(s){ const K=sides(s,ctx.atk); flyOff(K.D(), ctx.def); winPose(K.A(), fr); });
     marks.banner=1960;
     add(1960, {banner:1, blast:koBlast(ctx.def), ko:ctx.def});
     return 1960;
    })
   }
  };

  KITS.luigi={
   frames:F5,
   heavy:['cyclone','green-missile'],
   openings:{
    'fireball-poke':makeSeg('def', function(s,rng,ctx,add,marks){
     const fr=F5; resetStance(s); add(0);
     add(200, {jolt:{show:1,x:sides(s,ctx.atk).A().x+sides(s,ctx.atk).dir()*8,y:10}}, function(s){ sides(s,ctx.atk).A().frame=fr.special; });
     add(400, {jolt:{show:1,x:midX(s),y:8}});
     const dmg=rng.ri(6,9);
     add(620, {impact:1, blast:{x:sides(s,ctx.atk).D().x, top:48, color:'green'}}, function(s){
      const K=sides(s,ctx.atk); K.hurt(dmg); K.D().rot=10*K.dir(); K.D().x=clampX(K.D().x+K.dir()*6,12,90);
     });
     add(960, {jolt:{show:0}}, function(s){ resetStance(s); });
     return 1100;
    }),
    'cyclone-nudge':pokeOpen('aerial')
   },
   mids:{
    'fireball-pressure':makeSeg('def', function(s,rng,ctx,add,marks){
     const fr=F5; resetStance(s); add(0);
     add(180, null, function(s){ sides(s,ctx.atk).A().frame=fr.special; });
     add(360, {jolt:{show:1,x:midX(s),y:8}});
     const dmg=rng.ri(5,8);
     add(560, {impact:1, jolt:{show:1,x:sides(s,ctx.atk).D().x,y:8}}, function(s){ const K=sides(s,ctx.atk); K.hurt(dmg); K.D().rot=8*K.dir(); });
     if(rng.chance(0.6)){
      const dmg2=rng.ri(6,10);
      add(820, {impact:1, blast:{x:sides(s,ctx.atk).D().x, top:48, color:'green'}}, function(s){ const K=sides(s,ctx.atk); K.A().frame=fr.special; K.hurt(dmg2); K.D().x=clampX(K.D().x+K.dir()*8,12,92); K.D().y=6; });
      add(1120, {jolt:{show:0}}, function(s){ resetStance(s); });
      return 1260;
     }
     add(900, {jolt:{show:0}}, function(s){ resetStance(s); });
     return 1060;
    }),
    cyclone:makeSeg('def', function(s,rng,ctx,add,marks){
     const fr=F5; resetStance(s); add(0);
     add(200, {afterimage:ctx.atk}, function(s){ const K=sides(s,ctx.atk); K.A().frame=fr.aerial; K.A().x=clampX(K.D().x-K.dir()*18,16,86); K.A().y=8; });
     const dmg=rng.ri(7,11);
     add(440, {impact:1, sparking:ctx.atk}, function(s){ const K=sides(s,ctx.atk); K.A().rot=-20*K.dir(); K.hurt(dmg); K.D().y=8; K.D().rot=10*K.dir(); });
     const dmg2=rng.ri(7,11);
     add(700, {impact:1, sparking:ctx.atk}, function(s){ const K=sides(s,ctx.atk); K.A().rot=18*K.dir(); K.A().y=12; K.hurt(dmg2); K.D().x=clampX(K.D().x+K.dir()*6,12,92); });
     add(1020, null, function(s){ resetStance(s); });
     return 1160;
    }),
    'green-missile':makeSeg('def', function(s,rng,ctx,add,marks){
     const fr=F5; resetStance(s); add(0);
     add(220, {sparking:ctx.atk}, function(s){ const K=sides(s,ctx.atk); K.A().frame=fr.aerial; K.A().x=clampX(K.A().x-K.dir()*8,16,86); });
     const dmg=rng.ri(10,15);
     add(600, {impact:1, qa:{x:midX(s),y:6,w:40,rot:0}, afterimage:ctx.atk}, function(s){
      const K=sides(s,ctx.atk); K.A().x=clampX(K.D().x-K.dir()*10,16,86); K.A().frame=fr.aerial; K.hurt(dmg); K.D().rot=18*K.dir(); K.D().x=clampX(K.D().x+K.dir()*10,8,94);
     });
     add(960, null, function(s){ resetStance(s); });
     return 1100;
    })
   },
   finishers:{
    'super-jump-punch':makeSeg('def', function(s,rng,ctx,add,marks){
     const fr=F5; resetStance(s); add(0);
     add(240, {sparking:ctx.atk}, function(s){ sides(s,ctx.atk).A().frame=fr.attack; });
     const dmg=rng.ri(10,14);
     add(560, {impact:1, tipper:{x:sides(s,ctx.atk).D().x,y:18}}, function(s){
      const K=sides(s,ctx.atk); K.A().frame=fr.attack; K.A().x=clampX(K.D().x-K.dir()*12,16,86); K.A().y=16; K.hurt(dmg); K.D().y=20; K.D().rot=16*K.dir();
     });
     const spike=rng.ri(12,18);
     marks.spike=960;
     add(960, {impact:1, dolphin:{x:sides(s,ctx.atk).D().x,y:28}, sparking:ctx.atk}, function(s){
      const K=sides(s,ctx.atk); K.A().frame=fr.victory; K.A().y=28; K.hurt(spike); K.D().y=36; K.D().rot=50*K.dir(); K.D().scale=.92;
     });
     add(1280, null, function(s){ const K=sides(s,ctx.atk); K.D().x=clampX(K.D().x+K.dir()*24,-20,126); K.D().y=48; K.D().rot=80*K.dir(); });
     marks.ko=1620;
     add(1620, {blast:koBlast(ctx.def), ko:ctx.def}, function(s){ const K=sides(s,ctx.atk); flyOff(K.D(), ctx.def); winPose(K.A(), fr); });
     marks.banner=2060;
     add(2060, {banner:1, blast:koBlast(ctx.def), ko:ctx.def});
     return 2060;
    }),
    'green-missile-ko':finisherRush('aerial'),
    'cyclone-ko':finisherSmash('green', false)
   }
  };

  KITS.steve={
   frames:F5,
   heavy:['mine-combo','anvil-drop'],
   openings:{ 'pickaxe-poke':pokeOpen('attack') },
   mids:{
    'mine-combo':makeSeg('def', function(s,rng,ctx,add,marks){
     const fr=F5; resetStance(s); add(0);
     add(180, null, function(s){ const K=sides(s,ctx.atk); K.A().frame=fr.attack; K.A().x=clampX(K.D().x-K.dir()*24,16,86); });
     let t=180;
     const hits=rng.ri(2,3);
     for(let i=0;i<hits;i++){
      t+=rng.ri(220,260);
      const dmg=rng.ri(6,10);
      add(t, {impact:1, sparking:ctx.atk}, function(s){
       const K=sides(s,ctx.atk); K.A().frame=i%2?fr.aerial:fr.attack; K.A().y=i%2?10:0; K.hurt(dmg); K.D().rot=(8+i*4)*K.dir(); K.D().x=clampX(K.D().x+K.dir()*4,12,92);
      });
     }
     t+=280; add(t, null, function(s){ resetStance(s); });
     return t+140;
    }),
    'block-wall':makeSeg('def', function(s,rng,ctx,add,marks){
     const fr=F5; resetStance(s); add(0);
     add(240, null, function(s){ sides(s,ctx.atk).A().frame=fr.special; });
     const dmg=rng.ri(8,12);
     add(560, {impact:1, sparking:ctx.atk}, function(s){
      const K=sides(s,ctx.atk); K.A().frame=fr.special; K.A().x=clampX(K.D().x-K.dir()*16,16,86); K.hurt(dmg); K.D().rot=12*K.dir(); K.D().x=clampX(K.D().x+K.dir()*8,12,92);
     });
     add(920, null, function(s){ resetStance(s); });
     return 1080;
    }),
    'anvil-drop':makeSeg('def', function(s,rng,ctx,add,marks){
     const fr=F5; resetStance(s); add(0);
     add(200, {cloud:{show:1,x:sides(s,ctx.atk).D().x}}, function(s){ sides(s,ctx.atk).A().frame=fr.aerial; sides(s,ctx.atk).A().y=16; });
     const dmg=rng.ri(10,15);
     add(620, {impact:1, blast:{x:sides(s,ctx.atk).D().x, top:55}}, function(s){
      const K=sides(s,ctx.atk); K.A().frame=fr.special; K.A().y=0; K.hurt(dmg); K.D().y=6; K.D().rot=14*K.dir();
     });
     add(960, {cloud:{show:0}}, function(s){ resetStance(s); });
     return 1120;
    })
   },
   finishers:{
    'tnt-boom':finisherBlast('special', ''),
    'anvil-ko':makeSeg('def', function(s,rng,ctx,add,marks){
     const fr=F5; resetStance(s); add(0);
     add(240, {cloud:{show:1,x:sides(s,ctx.atk).D().x}}, function(s){ sides(s,ctx.atk).A().frame=fr.aerial; sides(s,ctx.atk).A().y=18; });
     const dmg=rng.ri(18,22);
     marks.boom=820;
     add(820, {impact:1, cloud:{show:1,x:sides(s,ctx.atk).D().x}, blast:{x:sides(s,ctx.atk).D().x, top:50}}, function(s){
      const K=sides(s,ctx.atk); K.A().frame=fr.special; K.A().y=0; K.hurt(dmg); K.D().rot=24*K.dir(); K.D().y=12;
     });
     add(1180, {cloud:{show:0}}, function(s){ const K=sides(s,ctx.atk); const D=K.D(), d=K.dir(); D.x=clampX(D.x+d*24,-20,126); D.y=36; D.rot=70*d; D.scale=.9; });
     marks.ko=1520;
     add(1520, {blast:koBlast(ctx.def), ko:ctx.def}, function(s){ const K=sides(s,ctx.atk); flyOff(K.D(), ctx.def); winPose(K.A(), fr); });
     marks.banner=1960;
     add(1960, {banner:1, blast:koBlast(ctx.def), ko:ctx.def});
     return 1960;
    }),
    'mine-smash':finisherSmash('white', false)
   }
  };

  KITS.sonic={
   frames:F5,
   heavy:['spin-dash','homing-attack'],
   openings:{
    'kick-poke':pokeOpen('attack'),
    'homing-tease':makeSeg('none', function(s,rng,ctx,add,marks){
     const fr=F5; resetStance(s); add(0);
     add(220, {qa:{x:midX(s),y:14,w:28,rot:-30}, afterimage:ctx.atk}, function(s){ const K=sides(s,ctx.atk); K.A().frame=fr.aerial; K.A().y=16; K.A().x=clampX(K.A().x+K.dir()*14,16,86); });
     add(560, null, function(s){ const K=sides(s,ctx.atk); K.A().x=clampX(K.A().x-K.dir()*10,16,86); K.A().y=0; K.A().frame=fr.ready; });
     add(860, null, function(s){ resetStance(s); });
     return 1000;
    })
   },
   mids:{
    'homing-attack':makeSeg('def', function(s,rng,ctx,add,marks){
     const fr=F5; resetStance(s); add(0);
     add(200, {qa:{x:midX(s),y:16,w:30,rot:-28}, afterimage:ctx.atk}, function(s){ const K=sides(s,ctx.atk); K.A().frame=fr.aerial; K.A().y=20; });
     const dmg=rng.ri(10,15);
     add(560, {impact:1, qa:{x:sides(s,ctx.atk).D().x,y:8,w:28,rot:20}, afterimage:ctx.atk}, function(s){
      const K=sides(s,ctx.atk); K.A().frame=fr.special; K.A().y=4; K.A().x=clampX(K.D().x-K.dir()*10,16,86); K.hurt(dmg); K.D().rot=16*K.dir(); K.D().x=clampX(K.D().x+K.dir()*8,12,92);
     });
     add(920, null, function(s){ resetStance(s); });
     return 1080;
    }),
    'spin-dash':makeSeg('def', function(s,rng,ctx,add,marks){
     const fr=F5; resetStance(s); add(0);
     add(200, {sparking:ctx.atk}, function(s){ sides(s,ctx.atk).A().frame=fr.special; });
     add(420, {qa:{x:midX(s),y:4,w:40,rot:0}, afterimage:ctx.atk}, function(s){ const K=sides(s,ctx.atk); K.A().frame=fr.special; K.A().x=clampX(K.A().x+K.dir()*18,16,86); });
     const dmg=rng.ri(9,14);
     add(680, {impact:1, qa:{x:sides(s,ctx.atk).D().x,y:4,w:28,rot:0}, afterimage:ctx.atk}, function(s){
      const K=sides(s,ctx.atk); K.A().frame=fr.special; K.A().x=clampX(K.D().x-K.dir()*8,16,86); K.hurt(dmg); K.D().rot=14*K.dir(); K.D().x=clampX(K.D().x+K.dir()*10,8,94);
     });
     add(1020, null, function(s){ resetStance(s); });
     return 1160;
    }),
    'spring-hop':makeSeg('def', function(s,rng,ctx,add,marks){
     const fr=F5; resetStance(s); add(0);
     add(200, null, function(s){ const K=sides(s,ctx.atk); K.A().frame=fr.aerial; K.A().y=22; });
     const dmg=rng.ri(8,12);
     add(520, {impact:1, tipper:{x:sides(s,ctx.atk).D().x,y:20}}, function(s){
      const K=sides(s,ctx.atk); K.A().frame=fr.attack; K.A().x=clampX(K.D().x-K.dir()*12,16,86); K.A().y=10; K.hurt(dmg); K.D().y=12; K.D().rot=12*K.dir();
     });
     add(880, null, function(s){ resetStance(s); });
     return 1040;
    })
   },
   finishers:{
    'spindash-ko':finisherRush('special'),
    'homing-ko':makeSeg('def', function(s,rng,ctx,add,marks){
     const fr=F5; resetStance(s); add(0);
     add(220, {qa:{x:midX(s),y:18,w:32,rot:-30}, afterimage:ctx.atk, sparking:ctx.atk}, function(s){ const K=sides(s,ctx.atk); K.A().frame=fr.aerial; K.A().y=24; });
     add(520, {afterimage:ctx.atk}, function(s){ const K=sides(s,ctx.atk); K.A().frame=fr.special; K.A().y=8; K.A().x=clampX(midX(s),16,86); });
     const dmg=rng.ri(16,22);
     add(840, {impact:1, qa:{x:sides(s,ctx.atk).D().x,y:6,w:32,rot:0}, afterimage:ctx.atk}, function(s){
      const K=sides(s,ctx.atk); K.A().frame=fr.special; K.A().x=clampX(K.D().x-K.dir()*8,16,86); K.A().y=2; K.hurt(dmg); K.D().rot=24*K.dir(); K.D().y=16;
     });
     add(1180, null, function(s){ const K=sides(s,ctx.atk); const D=K.D(), d=K.dir(); D.x=clampX(D.x+d*26,-20,126); D.y=36; D.rot=70*d; D.scale=.9; });
     marks.ko=1520;
     add(1520, {blast:koBlast(ctx.def), ko:ctx.def}, function(s){ const K=sides(s,ctx.atk); flyOff(K.D(), ctx.def); winPose(K.A(), fr); });
     marks.banner=1960;
     add(1960, {banner:1, blast:koBlast(ctx.def), ko:ctx.def});
     return 1960;
    }),
    'spring-spike':makeSeg('def', function(s,rng,ctx,add,marks){
     const fr=F5; resetStance(s); add(0);
     add(240, null, function(s){ sides(s,ctx.atk).A().frame=fr.aerial; sides(s,ctx.atk).A().y=26; });
     const dmg=rng.ri(16,20);
     marks.spike=800;
     add(800, {impact:1, dolphin:{x:sides(s,ctx.atk).D().x,y:24}}, function(s){
      const K=sides(s,ctx.atk); K.A().frame=fr.attack; K.A().x=clampX(K.D().x-K.dir()*8,16,86); K.A().y=12; K.hurt(dmg); K.D().rot=60*K.dir(); K.D().y=8; K.D().scale=.95;
     });
     add(1140, {blast:'bottom', ko:ctx.def}, function(s){ const K=sides(s,ctx.atk); K.D().y=-28; K.D().rot=120*K.dir(); K.D().scale=.85; });
     marks.ko=1480;
     add(1480, {blast:'bottom', ko:ctx.def}, function(s){ const K=sides(s,ctx.atk); K.D().y=-70; K.D().scale=.7; winPose(K.A(), fr); });
     marks.banner=1900;
     add(1900, {banner:1, blast:'bottom', ko:ctx.def});
     return 1900;
    })
   }
  };

  KITS.snake={
   frames:F5,
   heavy:['rpg','grenade-pressure'],
   openings:{
    'grenade-toss':makeSeg('def', function(s,rng,ctx,add,marks){
     const fr=F5; resetStance(s); add(0);
     add(200, null, function(s){ sides(s,ctx.atk).A().frame=fr.attack; });
     add(420, {jolt:{show:1,x:midX(s),y:12}});
     const dmg=rng.ri(8,12);
     add(700, {impact:1, blast:{x:sides(s,ctx.atk).D().x, top:50}}, function(s){
      const K=sides(s,ctx.atk); K.hurt(dmg); K.D().rot=12*K.dir(); K.D().y=8; K.D().x=clampX(K.D().x+K.dir()*8,12,92);
     });
     add(1040, {jolt:{show:0}}, function(s){ resetStance(s); });
     return 1180;
    })
   },
   mids:{
    'grenade-pressure':makeSeg('def', function(s,rng,ctx,add,marks){
     const fr=F5; resetStance(s); add(0);
     add(180, null, function(s){ sides(s,ctx.atk).A().frame=fr.attack; });
     const dmg=rng.ri(6,9);
     add(500, {impact:1, blast:{x:sides(s,ctx.atk).D().x, top:52}}, function(s){ const K=sides(s,ctx.atk); K.hurt(dmg); K.D().rot=8*K.dir(); });
     if(rng.chance(0.55)){
      const dmg2=rng.ri(7,11);
      add(820, {impact:1, blast:{x:sides(s,ctx.atk).D().x, top:50}}, function(s){ const K=sides(s,ctx.atk); K.A().frame=fr.attack; K.hurt(dmg2); K.D().x=clampX(K.D().x+K.dir()*8,12,92); K.D().y=6; });
      add(1140, null, function(s){ resetStance(s); });
      return 1280;
     }
     add(860, null, function(s){ resetStance(s); });
     return 1020;
    }),
    'box-ambush':makeSeg('def', function(s,rng,ctx,add,marks){
     const fr=F5; resetStance(s); add(0);
     add(200, null, function(s){ sides(s,ctx.atk).A().frame=fr.special; });
     add(480, {afterimage:ctx.atk}, function(s){ const K=sides(s,ctx.atk); K.A().frame=fr.attack; K.A().x=clampX(K.D().x-K.dir()*14,16,86); });
     const dmg=rng.ri(9,14);
     add(760, {impact:1}, function(s){ const K=sides(s,ctx.atk); K.A().frame=fr.attack; K.hurt(dmg); K.D().rot=14*K.dir(); K.D().x=clampX(K.D().x+K.dir()*8,12,92); });
     add(1080, null, function(s){ resetStance(s); });
     return 1220;
    }),
    'cypher-float':makeSeg('def', function(s,rng,ctx,add,marks){
     const fr=F5; resetStance(s); add(0);
     add(220, null, function(s){ sides(s,ctx.atk).A().frame=fr.ready; sides(s,ctx.atk).A().y=20; });
     const dmg=rng.ri(8,12);
     add(600, {impact:1, qa:{x:midX(s),y:14,w:24,rot:90}}, function(s){
      const K=sides(s,ctx.atk); K.A().frame=fr.attack; K.A().x=clampX(K.D().x-K.dir()*12,16,86); K.A().y=10; K.hurt(dmg); K.D().y=8; K.D().rot=12*K.dir();
     });
     add(960, null, function(s){ resetStance(s); });
     return 1100;
    }),
    rpg:makeSeg('def', function(s,rng,ctx,add,marks){
     const fr=F5; resetStance(s); add(0);
     add(220, {sparking:ctx.atk}, function(s){ sides(s,ctx.atk).A().frame=fr.aerial; });
     add(480, {qa:{x:midX(s),y:10,w:36,rot:0}});
     const dmg=rng.ri(11,16);
     add(720, {impact:1, blast:{x:sides(s,ctx.atk).D().x, top:46}}, function(s){
      const K=sides(s,ctx.atk); K.A().frame=fr.aerial; K.hurt(dmg); K.D().rot=18*K.dir(); K.D().y=10; K.D().x=clampX(K.D().x+K.dir()*10,8,94);
     });
     add(1060, null, function(s){ resetStance(s); });
     return 1200;
    })
   },
   finishers:{
    'rpg-ko':finisherBlast('aerial', ''),
    'c4-boom':finisherBlast('special', ''),
    'grenade-ko':finisherBlast('attack', '')
   }
  };

  KITS.pyra={
   frames:F5,
   heavy:['flame-combo','flame-nova'],
   openings:{ 'flame-slash':slashOpen('flame') },
   mids:{
    'flame-combo':multiSlash(['flame','red','flame','white'],3,4,true),
    'flame-nova':makeSeg('def', function(s,rng,ctx,add,marks){
     const fr=F5; resetStance(s); add(0);
     add(220, {sparking:ctx.atk}, function(s){ sides(s,ctx.atk).A().frame=fr.special; });
     const dmg=rng.ri(10,15);
     add(620, {impact:1, blast:{x:sides(s,ctx.atk).D().x, top:48, color:''}, trail:{color:'flame',x:midX(s),y:12,rot:0}}, function(s){
      const K=sides(s,ctx.atk); K.A().frame=fr.special; K.hurt(dmg); K.D().rot=16*K.dir(); K.D().y=8; K.D().x=clampX(K.D().x+K.dir()*8,12,92);
     });
     add(980, null, function(s){ resetStance(s); });
     return 1140;
    }),
    'blazing-end':makeSeg('def', function(s,rng,ctx,add,marks){
     const fr=F5; resetStance(s); add(0);
     add(200, null, function(s){ sides(s,ctx.atk).A().frame=fr.attack; });
     add(420, {trail:{color:'flame',x:midX(s),y:12,rot:-8}, tipper:{x:midX(s)+6,y:14}});
     const dmg=rng.ri(9,14);
     add(680, {impact:1, trail:{color:'flame',x:sides(s,ctx.atk).D().x,y:12,rot:-6}, tipper:{x:sides(s,ctx.atk).D().x,y:16}}, function(s){
      const K=sides(s,ctx.atk); K.A().frame=fr.special; K.hurt(dmg); K.D().rot=14*K.dir(); K.D().x=clampX(K.D().x+K.dir()*8,12,92);
     });
     add(1020, null, function(s){ resetStance(s); });
     return 1160;
    })
   },
   finishers:{
    'prominence-revolt':makeSeg('def', function(s,rng,ctx,add,marks){
     const fr=F5; resetStance(s); add(0);
     const dmg=rng.ri(8,12);
     add(240, {impact:1, trail:{color:'flame',x:midX(s),y:14,rot:-8}, tipper:{x:sides(s,ctx.atk).D().x,y:16}}, function(s){
      const K=sides(s,ctx.atk); K.A().frame=fr.attack; K.A().x=clampX(K.D().x-K.dir()*16,16,86); K.hurt(dmg); K.D().y=16; K.D().rot=16*K.dir();
     });
     add(540, {sparking:ctx.atk}, function(s){ const K=sides(s,ctx.atk); K.A().frame=fr.aerial; K.A().y=18; });
     const spike=rng.ri(14,20);
     marks.spike=900;
     add(900, {impact:1, dolphin:{x:sides(s,ctx.atk).D().x,y:28}, trail:{color:'flame',x:sides(s,ctx.atk).D().x,y:20,rot:-20}}, function(s){
      const K=sides(s,ctx.atk); K.A().frame=fr.special; K.A().y=24; K.hurt(spike); K.D().y=8; K.D().rot=70*K.dir(); K.D().scale=.95;
     });
     add(1220, {blast:'bottom', ko:ctx.def}, function(s){ const K=sides(s,ctx.atk); K.D().y=-28; K.D().rot=120*K.dir(); K.D().scale=.85; K.A().y=10; });
     marks.ko=1560;
     add(1560, {blast:'bottom', ko:ctx.def}, function(s){ const K=sides(s,ctx.atk); K.D().y=-70; K.D().scale=.7; winPose(K.A(), fr); });
     marks.banner=2000;
     add(2000, {banner:1, blast:'bottom', ko:ctx.def});
     return 2000;
    }),
    'blazing-smash':finisherSmash('flame', true),
    'nova-ko':finisherBlast('special', '')
   }
  };

  KITS.mythra={
   frames:F5,
   heavy:['photon-edge','speed-combo'],
   openings:{ 'light-slash':slashOpen('gold') },
   mids:{
    'speed-combo':multiSlash(['gold','white','gold','white'],3,4,true),
    'photon-edge':makeSeg('def', function(s,rng,ctx,add,marks){
     const fr=F5; resetStance(s); add(0);
     let t=0;
     const hits=rng.ri(3,4);
     for(let i=0;i<hits;i++){
      t+=rng.ri(180,220);
      const dmg=rng.ri(5,9);
      add(t, {impact:1, afterimage:ctx.atk, qa:{x:midX(s),y:8,w:34,rot:i%2?-16:12}, trail:{color:'gold',x:midX(s),y:12,rot:i%2?-12:8}}, function(s){
       const K=sides(s,ctx.atk); K.A().frame=i%2?fr.aerial:fr.attack; K.A().x=clampX(K.D().x-K.dir()*(18-i*2),16,86); K.A().y=i%2?10:0; K.hurt(dmg); K.D().rot=(8+i*3)*K.dir(); K.D().x=clampX(K.D().x+K.dir()*3,12,92);
      });
     }
     t+=280; add(t, null, function(s){ resetStance(s); });
     return t+140;
    }),
    'ray-punish':makeSeg('def', function(s,rng,ctx,add,marks){
     const fr=F5; resetStance(s); add(0);
     add(220, {sparking:ctx.atk}, function(s){ sides(s,ctx.atk).A().frame=fr.special; });
     const dmg=rng.ri(10,15);
     add(600, {impact:1, tipper:{x:sides(s,ctx.atk).D().x,y:16}, trail:{color:'gold',x:midX(s),y:12,rot:0}}, function(s){
      const K=sides(s,ctx.atk); K.A().frame=fr.special; K.hurt(dmg); K.D().rot=16*K.dir(); K.D().x=clampX(K.D().x+K.dir()*8,12,92);
     });
     add(960, null, function(s){ resetStance(s); });
     return 1120;
    })
   },
   finishers:{
    'lightning-buster':makeSeg('def', function(s,rng,ctx,add,marks){
     const fr=F5; resetStance(s); add(0);
     add(240, {sparking:ctx.atk}, function(s){ sides(s,ctx.atk).A().frame=fr.special; });
     add(560, {sparking:ctx.atk, tipper:{x:sides(s,ctx.atk).A().x,y:16}}, function(s){ sides(s,ctx.atk).A().frame=fr.special; });
     const dmg=rng.ri(18,22);
     marks.fsmash=900;
     add(900, {impact:1, trail:{color:'white',x:midX(s),y:16,rot:-8}, tipper:{x:sides(s,ctx.atk).D().x,y:18}}, function(s){
      const K=sides(s,ctx.atk); K.A().frame=fr.special; K.A().x=clampX(K.D().x-K.dir()*16,16,86); K.hurt(dmg); K.D().rot=24*K.dir(); K.D().y=16; K.D().x=clampX(K.D().x+K.dir()*10,8,94);
     });
     add(1260, null, function(s){ const K=sides(s,ctx.atk); const D=K.D(), d=K.dir(); D.x=clampX(D.x+d*26,-20,126); D.y=36; D.rot=70*d; D.scale=.9; });
     marks.ko=1600;
     add(1600, {blast:koBlast(ctx.def), ko:ctx.def}, function(s){ const K=sides(s,ctx.atk); flyOff(K.D(), ctx.def); winPose(K.A(), fr); });
     marks.banner=2040;
     add(2040, {banner:1, blast:koBlast(ctx.def), ko:ctx.def});
     return 2040;
    }),
    'photon-edge-ko':finisherRush('attack'),
    'ray-ko':finisherBlast('special', '')
   }
  };

  function kitMove(kitId, pool, moveId){
   const kit=KITS[kitId];
   return kit && kit[pool] && kit[pool][moveId];
  }
  function kitMoveIds(kitId, pool){
   const kit=KITS[kitId];
   return kit && kit[pool] ? Object.keys(kit[pool]) : [];
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

  function composeFight(opts){
   opts=opts||{};
   let seed=opts.seed;
   if(!(seed>0)) seed=1+Math.floor(Math.random()*0xfffffffe);
   const rng=mulberry(seed);

   const romanPool=rosterIdsFor('roman');
   const mortyPool=rosterIdsFor('morty');
   let romanId=opts.romanFighter || opts.rf;
   let mortyId=opts.mortyFighter || opts.mf;
   if(!romanId || romanPool.indexOf(romanId)<0) romanId=rng.pick(romanPool);
   if(!mortyId || mortyPool.indexOf(mortyId)<0) mortyId=rng.pick(mortyPool);

   const forcedWinner=(opts.winner==='roman'||opts.winner==='morty')?opts.winner:null;
   let winner=null;

   function pickOpening(){
    if(opts.opening){
     if(kitMove(romanId,'openings',opts.opening)) return {id:opts.opening, atk:'roman', atkId:romanId, defId:mortyId};
     if(kitMove(mortyId,'openings',opts.opening)) return {id:opts.opening, atk:'morty', atkId:mortyId, defId:romanId};
    }
    const atk=rng.chance(0.5)?'roman':'morty';
    const atkId=atk==='roman'?romanId:mortyId;
    const ids=kitMoveIds(atkId,'openings');
    return {id:rng.pick(ids), atk:atk, atkId:atkId, defId:atk==='roman'?mortyId:romanId};
   }
   const opening=pickOpening();

   const out={
    keys:[], marks:{},
    opening:opening.id, mids:[],
    finisher:null, winner:null, seed:seed,
    romanFighter:romanId, mortyFighter:mortyId,
    exchanges:[], hitDmgs:[], koPct:null, grabs:0, grabsThrough:0, throws:0,
    cast:{
     roman:{id:romanId, name:fighterName(romanId), meta:fighterMeta('roman', romanId)},
     morty:{id:mortyId, name:fighterName(mortyId), meta:fighterMeta('morty', mortyId)}
    }
   };
   let st=freshState();
   let t=0;
   function runBound(pool, pick, defend){
    const item=kitMove(pick.atkId, pool, pick.id);
    if(!item) return {dmg:0, rp:st.rp, mp:st.mp};
    const isFin=pool==='finishers';
    st._defend=(!isFin && defend)||null;
    st._shieldDmg=0;
    st._hitDmg=isFin?null:rng.ri(1,35);
    st._hitApplied=0;
    st._finisherMove=!!isFin;
    const rp0=st.rp, mp0=st.mp;
    const seg=item.run(st, rng, {winner:winner, id:pick.id, atk:pick.atk, def:otherSide(pick.atk), atkId:pick.atkId, defId:pick.defId});
    decorateDefense(seg, st._defend, otherSide(pick.atk));
    t=append(out, seg, t);
    st=seg.st;
    st._defend=null; st._shieldDmg=null; st._hitDmg=null; st._hitApplied=0; st._finisherMove=false;
    const dmg=pick.atk==='roman'?(st.mp-mp0):(st.rp-rp0);
    return {dmg:dmg, rp:st.rp, mp:st.mp};
   }
   function runGrabThrow(grabber, kind){
    kind=kind||'standing';
    const grabId=grabber==='roman'?romanId:mortyId;
    const victim=otherSide(grabber);
    const dmgRoll=rng.ri(1,35);
    const item=makeSeg('def', function(s,rng,ctx,add,marks){
     const f=frOf(ctx,'atk');
     resetStance(s);
     if(kind==='through'){
      add(0, {shield:ctx.def});
      add(140, {shieldPop:ctx.def, grab:ctx.atk}, function(s){
       const K=sides(s,ctx.atk); const d=K.dir();
       K.A().frame=f.attack; K.A().x=clampX(K.D().x-d*12,16,86);
      });
     } else if(kind==='oos'){
      add(0, {shield:ctx.atk});
      add(120, {grab:ctx.atk}, function(s){
       const K=sides(s,ctx.atk); const d=K.dir();
       K.A().frame=f.attack; K.A().x=clampX(K.D().x-d*10,16,86);
      });
     } else {
      add(0);
      add(120, {grab:ctx.atk}, function(s){
       const K=sides(s,ctx.atk); const d=K.dir();
       K.A().frame=f.attack; K.A().x=clampX(K.D().x-d*10,16,86);
      });
     }
     add(340, {grab:ctx.atk}, function(s){
      const K=sides(s,ctx.atk); const d=K.dir();
      K.A().frame=f.special||f.attack;
      K.A().x=clampX(K.D().x-d*8,16,86);
      K.D().x=clampX(K.A().x+d*7,12,90);
      K.D().y=6; K.D().rot=8*d; K.D().scale=.96;
     });
     add(600, {impact:1, grab:ctx.atk, thrown:ctx.def}, function(s){
      const K=sides(s,ctx.atk); const d=K.dir();
      K.A().frame=f.attack; K.A().rot=-12*d;
      K.hurt(dmgRoll);
      K.D().x=clampX(K.D().x+d*18,8,94);
      K.D().y=22; K.D().rot=55*d; K.D().scale=.9;
     });
     add(920, null, function(s){ resetStance(s); });
     return 1040;
    });
    st._defend=null; st._hitDmg=dmgRoll; st._hitApplied=0; st._finisherMove=false;
    const rp0=st.rp, mp0=st.mp;
    const seg=item.run(st, rng, {atk:grabber, def:victim, atkId:grabId, defId:grabber==='roman'?mortyId:romanId});
    t=append(out, seg, t);
    st=seg.st;
    st._defend=null; st._hitDmg=null; st._hitApplied=0; st._finisherMove=false;
    const dmg=grabber==='roman'?(st.mp-mp0):(st.rp-rp0);
    return {dmg:dmg, rp:st.rp, mp:st.mp, throughShield:kind==='through', threw:dmg>0, kind:kind};
   }

   let lastAtk=null, streak=0, leadChanges=0, lastLead=null;
   function noteLead(){
    const lead=st.rp===st.mp?null:(st.rp>st.mp?'roman':'morty');
    if(lead && lastLead && lead!==lastLead) leadChanges++;
    if(lead) lastLead=lead;
   }
   function record(pick, defend, res, pool){
    const ex={atk:pick.atk, id:pick.id, defend:defend||null, dmg:res.dmg, rp:res.rp, mp:res.mp, pool:pool, throughShield:!!(res&&res.throughShield), threw:!!(res&&res.threw)};
    out.exchanges.push(ex);
    if(res.dmg>0 && pool!=='finishers' && (pool==='grab' || !defend)) out.hitDmgs.push(res.dmg);
    if(pool==='grab') out.grabs=(out.grabs||0)+1;
    if(res && res.throughShield) out.grabsThrough=(out.grabsThrough||0)+1;
    if(res && res.threw) out.throws=(out.throws||0)+1;
    if(pick.atk===lastAtk) streak++;
    else { lastAtk=pick.atk; streak=1; }
    if(pool==='mids'){ out.mids.push(pick.id); }
    noteLead();
    return ex;
   }
   function pickAtk(){
    if(!lastAtk) return rng.chance(0.5)?'roman':'morty';
    if(streak>=3) return otherSide(lastAtk);
    // Open with a clean trade so the lead can actually change hands.
    if(out.exchanges.length<4) return otherSide(lastAtk);
    if(leadChanges===0){
     const behind=st.rp===st.mp?otherSide(lastAtk):(st.rp>st.mp?'roman':'morty');
     return (behind===lastAtk && streak>=3)?otherSide(behind):behind;
    }
    if(streak>=2 && rng.chance(0.7)) return otherSide(lastAtk);
    const atk=rng.chance(0.55)?otherSide(lastAtk):lastAtk;
    return (atk===lastAtk && streak>=3)?otherSide(atk):atk;
   }
   function maybeDefend(atk){
    if(out.exchanges.length<1) return rng.chance(0.14)?'shield':null;
    if(!rng.chance(0.30)) return null;
    return rng.chance(0.58)?'shield':'dodge';
   }
   function markKO(atk){
    ko=true;
    winner=atk;
    out.koPct=otherSide(atk)==='roman'?st.rp:st.mp;
   }
   function doGrab(grabber, kind, turns, minMids){
    const grabId=grabber==='roman'?romanId:mortyId;
    const res=runGrabThrow(grabber, kind);
    const pick={id:kind==='oos'?'oos-grab':(kind==='through'?'grab-shield':'grab'), atk:grabber, atkId:grabId, defId:grabber==='roman'?mortyId:romanId};
    record(pick, kind==='through'?'shield':null, res, 'grab');
    if(canKO(grabber, res.dmg, Math.max(turns, minMids), minMids)){ markKO(grabber); return true; }
    return false;
   }
   function tryShieldGrab(defend, afterAtk, turns, minMids){
    if(defend!=='shield' || ko) return false;
    if(!rng.chance(0.55)) return false;
    return doGrab(otherSide(afterAtk), 'oos', turns, minMids);
   }
   function canKO(atk, dmg, turns, minMids){
    if(!(dmg>0)) return false;
    const def=otherSide(atk);
    const pct=def==='roman'?st.rp:st.mp;
    if(pct<KO_MIN) return false;
    if(forcedWinner && atk!==forcedWinner) return false;
    if(turns<minMids && pct<KO_CAP) return false;
    // Give the lead a chance to change hands before an early lucky KO.
    if(leadChanges<1 && pct<KO_CAP) return false;
    return rng.next()<koChance(pct);
   }
   function midPick(atk){
    const atkId=atk==='roman'?romanId:mortyId;
    const defId=atk==='roman'?mortyId:romanId;
    const ids=kitMoveIds(atkId,'mids');
    return {id:rng.pick(ids), atk:atk, atkId:atkId, defId:defId};
   }

   const minMids=(opts.nMids>=1)?opts.nMids:2;
   const MAX_TURNS=28;
   let turns=0, ko=false;

   function resolveExchange(pick, pool, turns, minMids, force){
    let defend=force&&force.defend!==undefined?force.defend:maybeDefend(pick.atk);
    let offense=force&&force.offense?force.offense:'attack';
    if(!force){
     if(defend==='shield' && rng.chance(0.5)) offense='grab';
     else if(rng.chance(0.16)) offense='grab';
    }
    if(offense==='grab'){
     if(defend==='dodge'){
      // Grab whiffs a dodge.
      const grabId=pick.atk==='roman'?romanId:mortyId;
      record({id:'grab-whiff', atk:pick.atk, atkId:grabId, defId:pick.atk==='roman'?mortyId:romanId}, 'dodge', {dmg:0, rp:st.rp, mp:st.mp, threw:false}, 'grab');
      return;
     }
     if(defend==='shield'){
      doGrab(pick.atk, 'through', turns, minMids);
      return;
     }
     // Standing opponent: attacks beat grabs some of the time,
     // unless the other cat just landed a 3-hit string (let the grab break it).
     const counterAtk=otherSide(pick.atk);
     if(rng.chance(0.32) && !(lastAtk===counterAtk && streak>=3)){
      out.grabs=(out.grabs||0)+1;
      const counter=midPick(counterAtk);
      const res=runBound('mids', counter, null);
      record(counter, null, res, 'mids');
      if(canKO(counter.atk, res.dmg, turns, minMids)) markKO(counter.atk);
      return;
     }
     doGrab(pick.atk, 'standing', turns, minMids);
     return;
    }
    const res=runBound(pool, pick, defend);
    record(pick, defend, res, pool);
    if(canKO(pick.atk, res.dmg, turns, minMids)) markKO(pick.atk);
    else tryShieldGrab(defend, pick.atk, turns, minMids);
   }

   resolveExchange(opening, 'openings', turns, minMids, null);

   while(!ko && turns<MAX_TURNS){
    let atk=pickAtk();
    if(lastAtk && streak>=3) atk=otherSide(lastAtk);
    let force=null;
    // If the lead still hasn't flipped, the trailer grabs a shielding lead — the triangle's punish.
    if(leadChanges===0 && out.exchanges.length>=4){
     const behind=st.rp===st.mp?otherSide(lastAtk):(st.rp>st.mp?'roman':'morty');
     if(!(behind===lastAtk && streak>=3)){
      atk=behind;
      force={offense:'grab', defend:'shield'};
     }
    }
    const pick=midPick(atk);
    turns++;
    resolveExchange(pick, 'mids', turns, minMids, force);
    if(!ko && leadChanges===0 && force && streak<3){
     // One more clean hit if the throw wasn't enough to take the lead.
     const extra=midPick(atk);
     const res=runBound('mids', extra, null);
     record(extra, null, res, 'mids');
     turns++;
     if(canKO(atk, res.dmg, turns, minMids)) markKO(atk);
    }
   }

   if(!ko){
    // Failsafe: keep trading until someone in range is KO'd, then force it.
    for(let i=0;i<8 && !ko;i++){
     const pick=midPick(pickAtk());
     const res=runBound('mids', pick, null);
     record(pick, null, res, 'mids');
     turns++;
     const def=otherSide(pick.atk);
     const pct=def==='roman'?st.rp:st.mp;
     const allowed=!forcedWinner || pick.atk===forcedWinner;
     if(allowed && pct>=KO_MIN && (pct>=KO_CAP || i>=2)){
      ko=true;
      winner=pick.atk;
      out.koPct=pct;
     }
    }
   }
   if(!ko){
    // Last resort: the cat with more damage (or the forced winner's opponent) is KO'd.
    if(forcedWinner) winner=forcedWinner;
    else winner=(st.rp>=st.mp)?'morty':'roman';
    const def=otherSide(winner);
    const pct=def==='roman'?st.rp:st.mp;
    if(pct<KO_MIN){
     if(def==='roman') st.rp=KO_MIN; else st.mp=KO_MIN;
     const bump=snap(st,{impact:1});
     bump.t=t; t+=140;
     out.keys.push(bump);
     out.koPct=KO_MIN;
    } else out.koPct=pct;
    ko=true;
   }

   const loser=otherSide(winner);
   const winId=winner==='roman'?romanId:mortyId;
   const loseId=loser==='roman'?romanId:mortyId;
   let finisher=opts.finisher;
   const finIds=kitMoveIds(winId, 'finishers');
   if(!finisher || finIds.indexOf(finisher)<0) finisher=rng.pick(finIds);

   out.winner=winner;
   out.finisher=finisher;
   out.leadChanges=leadChanges;
   out.marks.finisher=t;
   runBound('finishers', {id:finisher, atk:winner, atkId:winId, defId:loseId}, null);

   const lastK=out.keys[out.keys.length-1];
   if(!lastK || !lastK.banner){
    const k=snap(st, {banner:1});
    k.t=t;
    k.ko=loser;
    k.blast=k.blast||koBlast(loser);
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
   if(p.get('rf')||p.get('roman')) opts.rf=p.get('rf')||p.get('roman');
   if(p.get('mf')||p.get('morty')) opts.mf=p.get('mf')||p.get('morty');
   if(optId && optId!=='1' && optId!=='random'){
    if(optId==='roman'||optId==='morty') opts.winner=optId;
    else opts.finisher=optId;
   }
  } else if(optId && typeof optId==='object'){
   return optId;
  } else if(optId && optId!=='1' && optId!=='random'){
   opts.finisher=optId;
  }
  return opts;
 }
 function publishMeta(outcome){
  const meta={
   seed:outcome.seed, opening:outcome.opening, mids:outcome.mids, finisher:outcome.finisher,
   winner:outcome.winner, duration:outcome.duration, marks:outcome.marks,
   romanFighter:outcome.romanFighter, mortyFighter:outcome.mortyFighter,
   endRp:(outcome.keys[outcome.keys.length-1]||{}).rp,
   endMp:(outcome.keys[outcome.keys.length-1]||{}).mp
  };
  try{ document.body.dataset.fightMeta=JSON.stringify(meta); window.__FIGHT_META__=meta; }catch(e){}
  return meta;
 }


 let raf=0, playing=false, t0=0, current=null, lastImpact=-999, lastRp=-1, lastMp=-1;
/* Animation v2 renderer state: a key-time clock that can pause for hitlag. */
let kclock=0, lastReal=0, freezeLeft=0, freezeSide=null, freezeAmp=0;
const firedImpacts=new Set();

 function lerp(a,b,t){ return a+(b-a)*t; }
 function ease(t){ return t<.5 ? 2*t*t : 1-Math.pow(-2*t+2,2)/2; }
const EASES={
 inout:ease,
 linear:function(t){ return t; },
 out:function(t){ return 1-Math.pow(1-t,3); },
 in:function(t){ return t*t*t; },
 snap:function(t){ return 1-Math.pow(1-t,5); },
 back:function(t){ const c1=1.4, c3=c1+1; return 1+c3*Math.pow(t-1,3)+c1*Math.pow(t-1,2); },
 hold:function(t){ return t<1?0:1; }
};
function animLevel(side){
 const c=current && current.cast && current.cast[side];
 const k=c && KITS[c.id];
 return (k && k.anim) || 1;
}
function readyFrame(side){
 const c=current && current.cast && current.cast[side];
 const k=c && KITS[c.id];
 return (k && k.frames && k.frames.ready!=null)?k.frames.ready:0;
}
function hitlagMs(dmg, ko){
 // SSBU-style hitlag: grows with the hit's own damage; killing blows hang a beat longer.
 return Math.round((3+Math.max(0,+dmg||0)*0.32)*16.7)+(ko?230:0);
}

 function carry(keys){
  var r={x:26,y:0,rot:0,frame:0,scale:1,face:1};
  var m={x:74,y:0,rot:0,frame:0,scale:1,face:-1};
  return keys.map(function(k){
   if(k.r) r=Object.assign({},r,k.r);
   if(k.m) m=Object.assign({},m,k.m);
   return Object.assign({},k,{r:Object.assign({},r),m:Object.assign({},m)});
  });
 }
 function mergeState(prev, next, t, raw, fs){
  const o={};
  if(raw==null) raw=t;
  if(fs==null) fs=1;
  ['x','y','rot','scale','sx','sy'].forEach(function(k){
   const a=prev&&prev[k], b=next&&next[k];
   if(a==null && b==null) return;
   const one=(k==='scale'||k==='sx'||k==='sy');
   const av=a==null?(one?1:0):a;
   const bv=b==null?av:b;
   o[k]=lerp(av,bv,t);
  });
  o.frame=(raw<fs && prev && prev.frame!=null)?prev.frame:((next&&next.frame!=null)?next.frame:(prev&&prev.frame)||0);
  o.face=(next&&next.face!=null)?next.face:((prev&&prev.face)!=null?prev.face:null);
  return o;
 }

 function setFrame(art, frame){
  const w=parseFloat(art.dataset.w)||0;
  art.style.backgroundPosition=(-frame*w)+'px 0';
 }
 function place(el, art, st, defaultFace, jx){
  const face=st.face!=null?st.face:defaultFace;
  const sc=st.scale!=null?st.scale:1;
  const sx=st.sx!=null?st.sx:1, sy=st.sy!=null?st.sy:1;
  el.style.left=jx?('calc('+st.x+'% + '+jx.toFixed(2)+'px)'):(st.x+'%');
  el.style.bottom='calc(31.1% + '+(st.y||0)+'px)';
  art.style.transform='rotate('+(+(st.rot||0)).toFixed(2)+'deg) scale('+(face*sc*sx).toFixed(4)+','+(sc*sy).toFixed(4)+')';
  if(st.frame!=null) setFrame(art, st.frame);
 }
 function setPct(node, v){
  v=Math.max(0, Math.round(v));
  const prev=node.dataset.v!=null?parseInt(node.dataset.v,10):0;
  node.textContent=v+'%';
  node.dataset.v=String(v);
  node.classList.remove('mid','high','ko');
  if(v>=120) node.classList.add('ko');
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
 function shakeAmt(dmg){
  // Intensity comes only from this hit's damage, never the running total %.
  const n=Math.max(0, +dmg||0);
  const t=Math.max(0, Math.min(1, (n-1)/34));
  return 1+t*13;
 }
 function juice(dmg, flash){
  if(reduce) return;
  if(!(dmg>0) && !flash) return;
  stage.style.setProperty('--shake', String(shakeAmt(dmg)));
  stage.classList.remove('shake','flash');
  void stage.offsetWidth;
  stage.classList.add('shake');
  if(flash) stage.classList.add('flash');
 }
 function resetFx(){
  [callout,bolt,jolt,cloud,trail,arc,spark,shieldSpark,qa,blast,romanKo,mortyKo,banner,sub].forEach(function(el){ showFx(el,false); });
  if(fxCtx) fxCtx.clearRect(0,0,fxCanvas.width,fxCanvas.height);
  firedImpacts.clear(); freezeLeft=0; freezeSide=null;
  romanEl.classList.remove('sparking','countering','shielding','dodging','grabbing','thrown','shield-pop');
  mortyEl.classList.remove('sparking','countering','shielding','dodging','grabbing','thrown','shield-pop');
  stage.classList.remove('shake','flash');
  clearGhosts();
  trail.className='blade-trail';
  blast.className='blast';
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

 function breathe(P, side, now){
 // Idle breathing for v2 fighters: a slow squash/stretch while standing in the ready frame.
 if(animLevel(side)<2 || P.frame!==readyFrame(side) || Math.abs(P.rot||0)>2 || (P.y||0)>1) return;
 const ph=Math.sin(now/1000*Math.PI*2*0.85+(side==='morty'?1.9:0));
 P.sy=(P.sy!=null?P.sy:1)*(1+0.026*ph);
 P.sx=(P.sx!=null?P.sx:1)*(1-0.013*ph);
}
const FX_W=492, FX_H=276.75, FX_GROUND=FX_H*(1-0.311);
function fxPt(cx, cy, face, deg, rad){
 const a=deg*Math.PI/180;
 return [cx+face*Math.cos(a)*rad, cy-Math.sin(a)*rad];
}
function drawSwipe(g, P, sw, age){
 const dur=Math.max(30, sw.dur||120);
 const p=age/dur;
 const fade=p<=1?1:Math.max(0, 1-(age-dur)/240);
 if(fade<=0) return;
 const face=P.face||1;
 const cx=(P.x/100)*FX_W+face*(sw.dx||0);
 const cy=FX_GROUND-(P.y||0)-(sw.dy!=null?sw.dy:40);
 const e=1-Math.pow(1-Math.min(1,p),3);
 const col=sw.col||'#7cc6ff', glow=sw.glow||col;
 g.save();
 g.globalCompositeOperation='lighter';
 if(sw.kind==='stab'){
  const len=(sw.len||70)*e;
  const x0=cx+face*(sw.r||28), x1=x0+face*len;
  const w=(sw.w||7);
  const grd=g.createLinearGradient(x0,cy,x1,cy);
  grd.addColorStop(0,'rgba(255,255,255,0)');
  grd.addColorStop(0.6,col);
  grd.addColorStop(1,'#ffffff');
  g.globalAlpha=0.9*fade;
  g.shadowColor=glow; g.shadowBlur=14;
  g.fillStyle=grd;
  g.beginPath();
  g.moveTo(x0,cy-w*0.25); g.lineTo(x1,cy-w*0.5); g.lineTo(x1+face*w*1.2,cy); g.lineTo(x1,cy+w*0.5); g.lineTo(x0,cy+w*0.25);
  g.closePath(); g.fill();
  g.restore();
  return;
 }
 const a0=sw.a0, a1=sw.a1;
 const lead=a0+(a1-a0)*e;
 const tailF=p<=1?Math.max(0,e-0.85):Math.min(1,0.1+0.9*(age-dur)/240);
 const tail=a0+(lead-a0)*tailF;
 const R=sw.r||60, W=sw.w||14;
 const N=18;
 g.shadowColor=glow; g.shadowBlur=12;
 for(let pass=0;pass<2;pass++){
  for(let i=0;i<N;i++){
   const f0=i/N, f1=(i+1)/N;
   const b0=tail+(lead-tail)*f0, b1=tail+(lead-tail)*f1;
   const w1=(pass?0.38:1)*W*(0.25+0.75*f1), w0=(pass?0.38:1)*W*(0.25+0.75*f0);
   g.globalAlpha=fade*(pass?0.95:0.55)*(0.12+0.88*f1);
   g.fillStyle=pass?'#ffffff':col;
   const o0=fxPt(cx,cy,face,b0,R), o1=fxPt(cx,cy,face,b1,R);
   const i1=fxPt(cx,cy,face,b1,R-w1), i0=fxPt(cx,cy,face,b0,R-w0);
   g.beginPath(); g.moveTo(o0[0],o0[1]); g.lineTo(o1[0],o1[1]); g.lineTo(i1[0],i1[1]); g.lineTo(i0[0],i0[1]); g.closePath(); g.fill();
  }
 }
 g.restore();
}
function drawDust(g, P, age){
 const p=age/360; if(p>1) return;
 const face=P.face||1;
 const x=(P.x/100)*FX_W, y=FX_GROUND-(P.y||0)+2;
 g.save();
 for(let i=0;i<3;i++){
  const dx=-face*(4+i*7)*(0.4+p), dy=-(2+i*1.5)*p;
  g.globalAlpha=(1-p)*0.5;
  g.fillStyle='#e9e2d4';
  g.beginPath(); g.arc(x+dx, y+dy, 2.5+i*1.2+p*5, 0, Math.PI*2); g.fill();
 }
 g.restore();
}
function drawFx(keys, now, r, m){
 if(!fxCtx) return;
 const g=fxCtx;
 g.setTransform(1,0,0,1,0,0);
 g.clearRect(0,0,fxCanvas.width,fxCanvas.height);
 g.setTransform(fxCanvas.width/FX_W,0,0,fxCanvas.height/FX_H,0,0);
 for(let i=0;i<keys.length;i++){
  const k=keys[i];
  if(k.t>now) break;
  const age=now-k.t;
  if(k.sw && age<(k.sw.dur||120)+260) drawSwipe(g, k.sw.by==='morty'?m:r, k.sw, age);
  if(k.dust && age<360) drawDust(g, k.dust.by==='morty'?m:r, age);
 }
}
function applyAt(outcome, now, impactsOk){
  const keys=outcome.keys;
  let i=0;
  while(i+1<keys.length && keys[i+1].t<=now) i++;
  const a=keys[i], b=keys[Math.min(i+1,keys.length-1)];
  const span=Math.max(1, b.t-a.t);
  const u=b===a?1:Math.max(0, Math.min(1, (now-a.t)/span));
  const ezR=EASES[b.ezr||b.ez]||ease, ezM=EASES[b.ezm||b.ez]||ease;
  const r=mergeState(a.r||{}, b.r||{}, b===a?1:ezR(u), u, b.fs);
  const m=mergeState(a.m||{}, b.m||{}, b===a?1:ezM(u), u, b.fs);
  breathe(r, 'roman', now); breathe(m, 'morty', now);
  const jit=(freezeLeft>0 && freezeSide)?(((Math.floor(performance.now()/34)%2)?1:-1)*freezeAmp):0;
  place(romanEl, romanArt, r, 1, freezeSide==='roman'?jit:0);
  place(mortyEl, mortyArt, m, -1, freezeSide==='morty'?jit:0);
  drawFx(keys, now, r, m);

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
  const pop=lastKey(keys,'shieldPop',now);
  const sh=lastKey(keys,'shield',now);
  const romanPop=!!(pop && pop.shieldPop==='roman' && now-pop.t<280);
  const mortyPop=!!(pop && pop.shieldPop==='morty' && now-pop.t<280);
  romanEl.classList.toggle('shield-pop', romanPop);
  mortyEl.classList.toggle('shield-pop', mortyPop);
  romanEl.classList.toggle('shielding', !romanPop && !!(sh && sh.shield==='roman' && now-sh.t<420));
  mortyEl.classList.toggle('shielding', !mortyPop && !!(sh && sh.shield==='morty' && now-sh.t<420));
  const bk=lastKey(keys,'blockSpark',now);
  if(bk && bk.blockSpark && now-bk.t<280){
   placeAbs(shieldSpark, bk.blockSpark.x, bk.blockSpark.y||22);
   showFx(shieldSpark,true);
  } else showFx(shieldSpark,false);
  const dg=lastKey(keys,'dodge',now);
  romanEl.classList.toggle('dodging', !!(dg && dg.dodge==='roman' && now-dg.t<420));
  mortyEl.classList.toggle('dodging', !!(dg && dg.dodge==='morty' && now-dg.t<420));
  const gb=lastKey(keys,'grab',now);
  romanEl.classList.toggle('grabbing', !!(gb && gb.grab==='roman' && now-gb.t<500));
  mortyEl.classList.toggle('grabbing', !!(gb && gb.grab==='morty' && now-gb.t<500));
  const th=lastKey(keys,'thrown',now);
  romanEl.classList.toggle('thrown', !!(th && th.thrown==='roman' && now-th.t<400));
  mortyEl.classList.toggle('thrown', !!(th && th.thrown==='morty' && now-th.t<400));

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
   const b=bs.blast;
   const color=(b && typeof b==='object' && b.color)?b.color:'';
   blast.className='blast show'+(color?(' '+color):'');
   if(b && typeof b==='object' && b.x!=null){
    blast.style.left=b.x+'%';
    blast.style.top=(b.top!=null?b.top:38)+'%';
   } else if(b==='right'){ blast.style.left='92%'; blast.style.top='38%'; }
   else if(b==='left'){ blast.style.left='8%'; blast.style.top='38%'; }
   else if(b==='bottom'){ blast.style.left='70%'; blast.style.top='88%'; }
   else { blast.style.left='50%'; blast.style.top='40%'; }
  } else { blast.className='blast'; }

  if(impactsOk){
   keys.forEach(function(k,i){
    if((k.impact||k.freeze) && k.t<=now && !firedImpacts.has(i) && now-k.t<50){
     firedImpacts.add(i);
     lastImpact=k.t;
     const prev=i>0?keys[i-1]:null;
     const dmg=prev?Math.max(0,(k.rp||0)-(prev.rp||0),(k.mp||0)-(prev.mp||0)):0;
     const inFin=!!(outcome.marks && outcome.marks.finisher!=null && k.t>=outcome.marks.finisher);
     // Finishers flash; a v2 finisher that tags its killing blow (kohit) flashes only on that blow.
     const flash=inFin && (!outcome.koTagged || !!k.kohit);
     if(k.impact) juice(dmg, flash);
     if(k.hl){
      freezeLeft=Math.max(freezeLeft, hitlagMs(dmg, !!k.kohit));
      freezeSide=k.hl; freezeAmp=1+Math.min(3.5, dmg/9)+(k.kohit?2:0);
     }
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
  const dt=Math.max(0, Math.min(50, now-lastReal));
  lastReal=now;
  if(freezeLeft>0){ freezeLeft-=dt; if(freezeLeft<=0){ freezeLeft=0; freezeSide=null; } }
  else kclock+=dt;
  const t=kclock;
  applyAt(current, t, true);
  if(t>=endTime(current)){ playing=false; applyAt(current, endTime(current), false); return; }
  raf=requestAnimationFrame(tick);
 }
 function play(optId, seek, paused, fromUrl){
  stop();
  resetFx();
  lastImpact=-999;
  const outcome=composeFight(fightOptsFromUrl(optId, !!fromUrl));
  current=Object.assign({}, outcome, {keys:carry(outcome.keys)});
 current.koTagged=current.keys.some(function(k){ return k.kohit && outcome.marks && k.t>=outcome.marks.finisher; });
  publishMeta(current);
  const go=function(){
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
  kclock=startSeek; lastReal=performance.now(); freezeLeft=0; freezeSide=null;
   raf=requestAnimationFrame(tick);
  };
  const p=loadCast(current.cast);
  if(p && p.then) p.then(go); else go();
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
