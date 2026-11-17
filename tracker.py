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
 .fighter.ghost{opacity:.4;z-index:2}
 .ko-mark{position:absolute;z-index:6;font-weight:900;letter-spacing:.14em;color:#ff4a4a;font-size:18px;text-shadow:2px 2px 0 #000;opacity:0;pointer-events:none}
 .ko-mark.show{opacity:1;animation:calloutpop .3s ease-out}
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

  /* Random-roster engine. Each cat independently draws a fighter they have a sheet for.
     Mirror matches are allowed. Marth is Roman-only and Pikachu is Morty-only (original sheets).
     RULES:
     - No draws. Winner is chosen first so every fight is decisive; split is ~even over time.
     - No move-name labels. Only the % HUD, fighter names, and the winner banner.
     - Thunder (Pikachu down-B) only ever increments the DEFENDER's %. Never the user.
       Thunder is a ranged sky bolt, so Marth Counter is never used against it.
     - Counter (Marth down-B) is Marth-only and only fires against a close-range MELEE
       hit that reaches Marth's body. It is a standing sword swing, not a reflector.
     - A KO only comes from a finisher after damage has already been built. Never a raw hit at 0%. */

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
    hurt:function(n){ addDmg(s, def, n); },
    dir:function(){ const A=this.A(), D=this.D(); return A.x<=D.x?1:-1; }
   };
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

  KITS.marth={
   frames:F_MARTH,
   hasCounter:true,
   heavy:['dancing-blade','tipper-space'],
   openings:{ space:spaceOpen(), 'breaker-poke':slashOpen('white'), neutral:slashOpen('blue') },
   mids:{
    'dancing-blade':multiSlash(['red','green','blue','white'],3,4,true),
    'tipper-space':makeSeg('def', function(s,rng,ctx,add,marks){
     const fr=F_MARTH;
     resetStance(s); add(0);
     add(240, null, function(s){ const K=sides(s,ctx.atk); K.A().x=clampX(K.A().x-K.dir()*10,16,86); K.A().frame=fr.aerial; });
     const dmg=rng.ri(11,16);
     add(560, {impact:1, trail:{color:'white',x:sides(s,ctx.atk).D().x-sides(s,ctx.atk).dir()*10,y:14,rot:-6}, tipper:{x:sides(s,ctx.atk).D().x,y:16}}, function(s){
      const K=sides(s,ctx.atk); const A=K.A(), D=K.D(), d=K.dir();
      A.frame=fr.attack; A.x=clampX(A.x+d*22,16,86); K.hurt(dmg); D.x=clampX(D.x+d*8,12,92); D.y=10; D.rot=16*d;
     });
     add(900, null, function(s){ resetStance(s); });
     return 1060;
    })
   },
   finishers:{
    fsmash:finisherSmash('white', true),
    'db-tipper':makeSeg('def', function(s,rng,ctx,add,marks){
     const fr=F_MARTH;
     resetStance(s); add(0);
     add(160, null, function(s){ const K=sides(s,ctx.atk); K.A().frame=fr.attack; K.A().x=clampX(K.D().x-K.dir()*30,16,86); });
     const colors=['red','green','blue'];
     let t=160;
     for(let i=0;i<3;i++){
      t+=240;
      const dmg=rng.ri(6,10);
      add(t, {impact:1, trail:{color:colors[i],x:midX(s)+i*4,y:12+i*2,rot:i%2?-12:8}}, function(s){
       const K=sides(s,ctx.atk); const A=K.A(), D=K.D(), d=K.dir();
       A.frame=fr.attack; A.x+=d*5; K.hurt(dmg); D.x+=d*4; D.y=4+i*3; D.rot=(8+i*4)*d;
      });
     }
     const dmg=rng.ri(14,20);
     t+=280; marks.fsmash=t;
     add(t, {impact:1, trail:{color:'white',x:sides(s,ctx.atk).D().x,y:16,rot:-6}, tipper:{x:sides(s,ctx.atk).D().x,y:18}}, function(s){
      const K=sides(s,ctx.atk); const D=K.D(), d=K.dir();
      K.A().frame=fr.attack; K.hurt(dmg); D.x=clampX(D.x+d*16,8,110); D.y=18; D.rot=28*d; D.frame=0;
     });
     t+=340;
     add(t, null, function(s){ const K=sides(s,ctx.atk); const D=K.D(), d=K.dir(); D.x=clampX(D.x+d*22,-20,126); D.y=36; D.rot=60*d; D.scale=.9; });
     t+=360; marks.ko=t;
     add(t, {blast:koBlast(ctx.def), ko:ctx.def}, function(s){ const K=sides(s,ctx.atk); flyOff(K.D(), ctx.def); winPose(K.A(), fr); });
     t+=420; marks.banner=t;
     add(t, {banner:1, blast:koBlast(ctx.def), ko:ctx.def});
     return t;
    }),
    dolphin:makeSeg('def', function(s,rng,ctx,add,marks){
     const fr=F_MARTH;
     resetStance(s); add(0);
     const dmg=rng.ri(8,12);
     add(240, {impact:1, trail:{color:'white',x:midX(s),y:14,rot:-8}, tipper:{x:sides(s,ctx.atk).D().x,y:16}}, function(s){
      const K=sides(s,ctx.atk); const A=K.A(), D=K.D(), d=K.dir();
      A.frame=fr.attack; A.x=clampX(A.x+d*20,16,86); K.hurt(dmg); D.x=clampX(D.x+d*12,8,94); D.y=18; D.rot=20*d;
     });
     add(540, {qa:{x:sides(s,ctx.atk).D().x,y:16,w:26,rot:20}, afterimage:ctx.def}, function(s){
      const K=sides(s,ctx.atk); const A=K.A(), D=K.D(), d=K.dir();
      D.frame=0; D.y=22; A.frame=fr.aerial; A.x=clampX(D.x-d*16,16,86);
     });
     const spike=rng.ri(12,16);
     marks.spike=880;
     add(880, {impact:1, dolphin:{x:sides(s,ctx.atk).D().x,y:28}}, function(s){
      const K=sides(s,ctx.atk); const A=K.A(), D=K.D(), d=K.dir();
      A.frame=fr.victory; A.x=clampX(D.x-d*8,16,86); A.y=22; K.hurt(spike); D.y=8; D.rot=70*d; D.scale=.95;
     });
     add(1180, {blast:'bottom', ko:ctx.def}, function(s){ const K=sides(s,ctx.atk); K.D().y=-28; K.D().rot=120*K.dir(); K.D().scale=.85; K.A().y=10; });
     marks.ko=1480;
     add(1480, {blast:'bottom', ko:ctx.def}, function(s){ const K=sides(s,ctx.atk); K.D().y=-70; K.D().rot=150*K.dir(); K.D().scale=.7; winPose(K.A(), fr); K.A().x=clampX(K.A().x,20,80); });
     marks.banner=1900;
     add(1900, {banner:1, blast:'bottom', ko:ctx.def});
     return 1900;
    }),
    counter:makeSeg('def', function(s,rng,ctx,add,marks){
     const fr=F_MARTH;
     const ofr=frOf(ctx,'def');
     resetStance(s);
     pose(s,ctx.atk).x=ctx.atk==='roman'?30:70;
     pose(s,ctx.def).x=ctx.def==='roman'?30:76;
     faceSt(s); add(0);
     add(220, {qa:{x:midX(s),y:12,w:32,rot:-28}, afterimage:ctx.def}, function(s){
      const K=sides(s,ctx.atk); K.D().x=clampX(K.A().x+K.dir()*22,16,86); K.D().y=14; K.D().frame=ofr.attack||ofr.aerial;
     });
     add(460, {sparking:ctx.def}, function(s){
      const K=sides(s,ctx.atk); K.D().x=clampX(K.A().x+K.dir()*10,16,86); K.D().y=18; K.D().frame=ofr.aerial||ofr.attack; K.D().rot=-16*K.dir();
     });
     marks.counter=620;
     add(620, {counter:ctx.atk}, function(s){ const A=sides(s,ctx.atk).A(); A.frame=fr.aerial; A.y=0; });
     const dmg=rng.ri(12,18);
     marks.slash=860;
     add(860, {impact:1, counter:ctx.atk, trail:{color:'white',x:midX(s),y:16,rot:-8}, tipper:{x:midX(s)+4,y:18}}, function(s){
      const K=sides(s,ctx.atk); const A=K.A(), D=K.D(), d=K.dir();
      A.frame=fr.attack; K.hurt(dmg); D.x=clampX(D.x+d*16,8,94); D.y=14; D.rot=24*d; D.scale=.98;
     });
     add(1180, null, function(s){ const K=sides(s,ctx.atk); const D=K.D(), d=K.dir(); D.x=clampX(D.x+d*30,-20,126); D.y=32; D.rot=55*d; D.scale=.9; winPose(K.A(), fr); });
     marks.ko=1520;
     add(1520, {blast:koBlast(ctx.def), ko:ctx.def}, function(s){ const K=sides(s,ctx.atk); flyOff(K.D(), ctx.def); K.A().frame=fr.victory; });
     marks.banner=1960;
     add(1960, {banner:1, blast:koBlast(ctx.def), ko:ctx.def});
     return 1960;
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

   let winner=opts.winner;
   if(winner!=='roman' && winner!=='morty') winner=rng.chance(0.5)?'roman':'morty';
   const loser=winner==='roman'?'morty':'roman';
   const winId=winner==='roman'?romanId:mortyId;
   const loseId=loser==='roman'?romanId:mortyId;

   let finisher=opts.finisher;
   const finIds=kitMoveIds(winId, 'finishers');
   if(!finisher || finIds.indexOf(finisher)<0) finisher=rng.pick(finIds);

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

   let nMids=opts.nMids;
   if(!(nMids>=2 && nMids<=4)) nMids=rng.ri(2,4);
   const heavy=(KITS[winId] && KITS[winId].heavy) || [];

   function pickMid(avoid){
    const useWinner=rng.chance(0.7);
    const atk=useWinner?winner:loser;
    const atkId=atk==='roman'?romanId:mortyId;
    let ids=kitMoveIds(atkId,'mids').filter(function(id){ return id!==avoid; });
    if(!ids.length) ids=kitMoveIds(atkId,'mids');
    if(useWinner && heavy.length && rng.chance(0.45)){
     const h=heavy.filter(function(id){ return ids.indexOf(id)>=0 && id!==avoid; });
     if(h.length) ids=h;
    }
    const id=rng.pick(ids);
    return {id:id, atk:atk, atkId:atkId, defId:atk==='roman'?mortyId:romanId};
   }
   const midPicks=[];
   let last=null;
   for(let i=0;i<nMids;i++){
    const p=pickMid(last);
    midPicks.push(p);
    last=p.id;
   }
   if(heavy.length && !midPicks.some(function(p){ return p.atk===winner && heavy.indexOf(p.id)>=0; })){
    const hid=rng.pick(heavy);
    if(kitMove(winId,'mids',hid)){
     midPicks[midPicks.length-1]={id:hid, atk:winner, atkId:winId, defId:loseId};
    }
   }

   const out={
    keys:[], marks:{},
    opening:opening.id, mids:midPicks.map(function(p){ return p.id; }),
    finisher:finisher, winner:winner, seed:seed,
    romanFighter:romanId, mortyFighter:mortyId,
    cast:{
     roman:{id:romanId, name:fighterName(romanId), meta:fighterMeta('roman', romanId)},
     morty:{id:mortyId, name:fighterName(mortyId), meta:fighterMeta('morty', mortyId)}
    }
   };
   let st=freshState();
   let t=0;
   function runBound(pool, pick){
    const item=kitMove(pick.atkId, pool, pick.id);
    if(!item) return;
    const seg=item.run(st, rng, {winner:winner, id:pick.id, atk:pick.atk, def:otherSide(pick.atk), atkId:pick.atkId, defId:pick.defId});
    t=append(out, seg, t);
    st=seg.st;
   }
   runBound('openings', opening);
   midPicks.forEach(function(p){ runBound('mids', p); });

   const MIN_PCT=120;
   function loserPct(){ return loser==='morty'?st.mp:st.rp; }
   let pads=0;
   while(loserPct()<MIN_PCT && pads<12 && heavy.length){
    const hid=rng.pick(heavy);
    if(kitMove(winId,'mids',hid)){
     const p={id:hid, atk:winner, atkId:winId, defId:loseId};
     midPicks.push(p);
     out.mids.push(hid);
     runBound('mids', p);
    }
    pads++;
   }
   if(loserPct()<MIN_PCT){
    const bump=MIN_PCT+((typeof rng.ri==='function')?rng.ri(0,10):6);
    if(loser==='morty') st.mp=Math.max(st.mp, bump);
    else st.rp=Math.max(st.rp, bump);
    const bumpKey=snap(st,{impact:1});
    bumpKey.t=t;
    t+=180;
    out.keys.push(bumpKey);
   }

   out.marks.finisher=t;
   runBound('finishers', {id:finisher, atk:winner, atkId:winId, defId:loseId});

   const lastKey=out.keys[out.keys.length-1];
   if(!lastKey || !lastKey.banner){
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
 function juice(dmg, flash){
  if(reduce) return;
  const t=Math.max(0, Math.min(1, ((dmg||0)-3)/19));
  const amt=2+t*12;
  stage.style.setProperty('--shake', String(amt));
  stage.classList.remove('shake','flash');
  void stage.offsetWidth;
  stage.classList.add('shake');
  if(flash) stage.classList.add('flash');
 }
 function resetFx(){
  [callout,bolt,jolt,cloud,trail,arc,spark,qa,blast,romanKo,mortyKo,banner,sub].forEach(function(el){ showFx(el,false); });
  romanEl.classList.remove('sparking','countering');
  mortyEl.classList.remove('sparking','countering');
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
    if(k.impact && k.t<=now && k.t>lastImpact-10 && now-k.t<50){
     lastImpact=k.t;
     const prev=i>0?keys[i-1]:null;
     const dmg=prev?Math.max(0,(k.rp||0)-(prev.rp||0),(k.mp||0)-(prev.mp||0)):0;
     const flash=!!(outcome.marks && outcome.marks.finisher!=null && k.t>=outcome.marks.finisher);
     juice(dmg, flash);
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
  const outcome=composeFight(fightOptsFromUrl(optId, !!fromUrl));
  current=Object.assign({}, outcome, {keys:carry(outcome.keys)});
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
