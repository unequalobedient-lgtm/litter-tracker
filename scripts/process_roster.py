#!/usr/bin/env python3
"""Chroma-key and pack the 5-frame roster sheets for the fight engine."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

# Reuse chroma + pack helpers from the existing pipeline.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from crisp_sprites import (  # type: ignore
    PREVIEW,
    chroma_rgba,
    autocrop,
    foot_baseline,
    nn_downscale,
    quantize_sheet,
    pack_sheet,
)

ROOT = Path("/workspace")
OUT = Path("/workspace/litterapp/assets/fighters")
PREVIEW_DIR = Path("/tmp/roster_preview")
OUT.mkdir(parents=True, exist_ok=True)
PREVIEW_DIR.mkdir(parents=True, exist_ok=True)

# Cat fighters are compact; Aegis figures are taller. Match Marth/Pikachu scale.
CAT_DIV = 3
AEGIS_DIV = 4
CAT_COLORS = 24
AEGIS_COLORS = 40


def _largest_component_centroid(alpha: np.ndarray) -> tuple[float, float] | None:
    """Centroid of the largest 8-connected opaque component."""
    h, w = alpha.shape
    seen = np.zeros((h, w), dtype=bool)
    best = None
    best_area = 0
    ys, xs = np.where(alpha)
    for y0, x0 in zip(ys, xs):
        if seen[y0, x0]:
            continue
        # flood fill
        stack = [(int(y0), int(x0))]
        seen[y0, x0] = True
        pts = []
        while stack:
            y, x = stack.pop()
            pts.append((y, x))
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dy == 0 and dx == 0:
                        continue
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and alpha[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
        if len(pts) > best_area:
            best_area = len(pts)
            arr = np.array(pts)
            best = (float(arr[:, 1].mean()), float(arr[:, 0].mean()))  # x, y
    return best



def _drop_specks(rgba: np.ndarray, min_area: int = 40) -> np.ndarray:
    alpha = rgba[:, :, 3] > 0
    h, w = alpha.shape
    seen = np.zeros((h, w), dtype=bool)
    ys, xs = np.where(alpha)
    out = rgba.copy()
    comps = []
    for y0, x0 in zip(ys, xs):
        if seen[y0, x0]:
            continue
        stack = [(int(y0), int(x0))]
        seen[y0, x0] = True
        pts = []
        while stack:
            y, x = stack.pop()
            pts.append((y, x))
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dy == 0 and dx == 0:
                        continue
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and alpha[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
        comps.append((len(pts), pts))
    if not comps:
        return out
    comps.sort(key=lambda c: c[0], reverse=True)
    main = np.array(comps[0][1])
    minx, maxx = int(main[:, 1].min()), int(main[:, 1].max())
    miny, maxy = int(main[:, 0].min()), int(main[:, 0].max())
    for area, pts in comps[1:]:
        arr = np.array(pts)
        cx0, cx1 = int(arr[:, 1].min()), int(arr[:, 1].max())
        cy0, cy1 = int(arr[:, 0].min()), int(arr[:, 0].max())
        gap_x = max(0, cx0 - maxx, minx - cx1)
        gap_y = max(0, cy0 - maxy, miny - cy1)
        gap = max(gap_x, gap_y)
        if area < min_area:
            drop = True
        elif area < 320:
            # Pixel distance to the main body, not just bbox gap — catches
            # gutter crumbs that sit inside the body's bounding box.
            dmin = 1e18
            for i in range(0, len(arr), 32):
                chunk = arr[i:i + 32].astype(np.float64)
                d2 = ((chunk[:, None, :] - main[None, :, :].astype(np.float64)) ** 2).sum(axis=2).min()
                if d2 < dmin:
                    dmin = d2
            drop = (dmin ** 0.5) > 20
        else:
            drop = False
        if drop:
            for y, x in pts:
                out[y, x, 3] = 0
    return out


def _label_components(alpha: np.ndarray) -> tuple[np.ndarray, list[np.ndarray]]:
    """8-connected component labels and (N,2) y,x point arrays."""
    h, w = alpha.shape
    labels = np.full((h, w), -1, dtype=np.int32)
    comps: list[np.ndarray] = []
    ys, xs = np.where(alpha)
    cid = 0
    for y0, x0 in zip(ys, xs):
        if labels[y0, x0] >= 0:
            continue
        stack = [(int(y0), int(x0))]
        labels[y0, x0] = cid
        pts = []
        while stack:
            y, x = stack.pop()
            pts.append((y, x))
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dy == 0 and dx == 0:
                        continue
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and alpha[ny, nx] and labels[ny, nx] < 0:
                        labels[ny, nx] = cid
                        stack.append((ny, nx))
        comps.append(np.array(pts, dtype=np.int32))
        cid += 1
    return labels, comps


def equal_frames(rgba: np.ndarray, n: int = 5) -> list[np.ndarray]:
    """Split a 5-pose sheet, keeping each prop/body component intact.

    Overflow (swords, tails, capes, fireballs) stays with the body it
    belongs to. Components that accidentally bridge two bodies are
    Voronoi-split only between those bodies.
    """
    h, w = rgba.shape[:2]
    alpha = rgba[:, :, 3] > 0
    edges = np.array([int(round(w * i / n)) for i in range(n + 1)])

    centers = []
    for i in range(n):
        x0, x1 = int(edges[i]), int(edges[i + 1])
        c = _largest_component_centroid(alpha[:, x0:x1])
        if c is None:
            centers.append((0.5 * (x0 + x1), h * 0.6))
        else:
            centers.append((c[0] + x0, c[1]))
    centers_arr = np.array(centers)  # (n, 2) x,y

    ys, xs = np.where(alpha)
    if len(xs) == 0:
        return [rgba[:1, :1] for _ in range(n)]

    _comp_labels, comps = _label_components(alpha)

    # Body of a cell = component with the most pixels in the inner 70% of that cell.
    # Using the interior avoids overflow tips electing a neighbor's body.
    body_of = [None] * n
    for i in range(n):
        x0, x1 = int(edges[i]), int(edges[i + 1])
        pad = int(0.15 * (x1 - x0))
        inner0, inner1 = x0 + pad, x1 - pad
        best_cid, best_n = None, 0
        for cid, pts in enumerate(comps):
            px = pts[:, 1]
            count = int(np.count_nonzero((px >= inner0) & (px < inner1)))
            if count > best_n:
                best_n, best_cid = count, cid
        body_of[i] = best_cid

    owners_of: dict[int, list[int]] = {}
    for i, cid in enumerate(body_of):
        if cid is None:
            continue
        owners_of.setdefault(cid, []).append(i)

    assign = np.full((h, w), -1, dtype=np.int16)
    for cid, pts in enumerate(comps):
        py, px = pts[:, 0], pts[:, 1]
        owners = owners_of.get(cid, [])
        if len(owners) == 1:
            labels = np.full(len(pts), owners[0], dtype=np.int16)
        elif len(owners) > 1:
            pts_xy = np.stack([px, py], axis=1).astype(np.float64)
            own = np.array(owners)
            d2 = ((pts_xy[:, None, :] - centers_arr[None, own, :]) ** 2).sum(axis=2)
            home = np.searchsorted(edges, px, side="right") - 1
            home = np.clip(home, 0, n - 1)
            for j, o in enumerate(owners):
                d2[home == o, j] -= 55.0 ** 2
            labels = own[d2.argmin(axis=1)].astype(np.int16)
        else:
            # Disconnected prop (fireball, block, muzzle flash, leftover crumb).
            home = np.searchsorted(edges, px, side="right") - 1
            home = np.clip(home, 0, n - 1)
            # Tiny crumbs: give them to the nearest body so sword tips rejoin
            # their blade. Larger props stay with the cell they mostly live in.
            if len(pts) < 250:
                pts_xy = np.stack([px, py], axis=1).astype(np.float64)
                d2 = ((pts_xy[:, None, :] - centers_arr[None, :, :]) ** 2).sum(axis=2)
                labels = d2.argmin(axis=1).astype(np.int16)
            else:
                # majority home
                counts = np.bincount(home, minlength=n)
                labels = np.full(len(pts), int(counts.argmax()), dtype=np.int16)
        assign[py, px] = labels

    frames = []
    for i in range(n):
        mask = assign == i
        owned = rgba.copy()
        owned[~mask, 3] = 0
        # Drop tiny disconnected specks (neighbor overflow) but keep
        # larger props like fireballs, blocks, and muzzle flashes.
        owned = _drop_specks(owned, min_area=40)
        fr = autocrop(owned)
        area = int((fr[:, :, 3] > 0).sum())
        print(f"  frame {i}: {fr.shape[1]}x{fr.shape[0]} area={area} cx={centers[i][0]:.1f}")
        frames.append(fr)
    return frames


def process_spinball(target: int = 88) -> np.ndarray:
    """Scale the approved spin-ball to about a standing-cat height."""
    im = Image.open(ROOT / "sonic_spinball.jpg")
    rgba = chroma_rgba(im)
    Image.fromarray(rgba, "RGBA").save(PREVIEW_DIR / "spinball_keyed.png")
    fr = autocrop(rgba)
    print(f"  spinball cropped {fr.shape[1]}x{fr.shape[0]}")
    h, w = fr.shape[:2]
    scale = target / max(w, h)
    nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    # Integer-ish nearest neighbor: resize the cropped RGBA directly.
    imf = Image.fromarray(fr, "RGBA").resize((nw, nh), Image.Resampling.NEAREST)
    scaled = np.array(imf)
    print(f"  spinball scaled {scaled.shape[1]}x{scaled.shape[0]}")
    return scaled


def save_preview(sheet: Image.Image, name: str) -> None:
    prev = Image.new("RGBA", (sheet.size[0] * 4, sheet.size[1] * 4), (20, 22, 28, 255))
    big = sheet.resize((sheet.size[0] * 4, sheet.size[1] * 4), Image.Resampling.NEAREST)
    prev.alpha_composite(big)
    prev.convert("RGB").save(PREVIEW_DIR / f"{name}_sheet_4x.png", quality=95)


def process_sheet(
    path: Path,
    name: str,
    *,
    div: int,
    colors: int,
    reorder: list[int] | None = None,
    replace: dict[int, np.ndarray] | None = None,
    qmethod: int | None = None,
) -> dict:
    im = Image.open(path)
    rgba = chroma_rgba(im)
    Image.fromarray(rgba, "RGBA").save(PREVIEW_DIR / f"{name}_keyed.png")
    frames = equal_frames(rgba, 5)
    if reorder:
        frames = [frames[i] for i in reorder]
        print(f"  reordered -> {reorder}")
    scaled = [nn_downscale(f, div) for f in frames]
    if replace:
        for idx, fr in replace.items():
            print(f"  replace frame {idx} with {fr.shape[1]}x{fr.shape[0]}")
            scaled[idx] = fr
    quantized = quantize_sheet(scaled, colors, method=qmethod)
    sheet, cw, ch, nf, ax, ay = pack_sheet(quantized)
    dest = OUT / f"{name}.png"
    sheet.save(dest, "PNG", optimize=True)
    save_preview(sheet, name)
    cols = sheet.getcolors(maxcolors=500000)
    ncolors = len(cols) if cols else -1
    meta = {
        "file": f"fighters/{dest.name}",
        "sprite_w": cw,
        "sprite_h": ch,
        "frames": nf,
        "anchor_x": ax,
        "anchor_y": ay,
        "colors": ncolors,
        "bytes": dest.stat().st_size,
    }
    print(f"  packed {dest.name} {cw}x{ch} x{nf} colors={ncolors} {meta['bytes']} bytes")
    return meta


def copy_existing(src: Path, name: str, meta_src: dict) -> dict:
    im = Image.open(src)
    dest = OUT / f"{name}.png"
    im.save(dest, "PNG", optimize=True)
    save_preview(im, name)
    meta = dict(meta_src)
    meta["file"] = f"fighters/{dest.name}"
    meta["bytes"] = dest.stat().st_size
    print(f"  copied existing {src.name} -> {dest.name} {im.size} {meta['bytes']} bytes")
    return meta


def main() -> None:
    existing = json.loads((Path("/workspace/litterapp/assets") / "sprites.json").read_text())
    metas: dict = {}

    metas["roman_marth"] = copy_existing(
        Path("/workspace/litterapp/assets/roman_fight.png"),
        "roman_marth",
        existing["roman_fight"],
    )
    metas["morty_pikachu"] = copy_existing(
        Path("/workspace/litterapp/assets/morty_fight.png"),
        "morty_pikachu",
        existing["morty_fight"],
    )

    cats = [
        ("luigi", "roman_luigi.jpg", "morty_luigi.jpg", None, None),
        # MAXCOVERAGE keeps the grass-green on the block; median-cut was
        # eating it in favor of more black/brown/blue slots.
        ("steve", "roman_steve.jpg", "morty_steve.jpg", None, Image.Quantize.MAXCOVERAGE),
        ("snake", "roman_snake.jpg", "morty_snake.jpg", None, None),
    ]
    for fid, roman, morty, reorder, qmethod in cats:
        print(f"\n=== {fid} roman ===")
        metas[f"roman_{fid}"] = process_sheet(
            ROOT / roman, f"roman_{fid}", div=CAT_DIV, colors=CAT_COLORS, reorder=reorder, qmethod=qmethod
        )
        print(f"\n=== {fid} morty ===")
        metas[f"morty_{fid}"] = process_sheet(
            ROOT / morty, f"morty_{fid}", div=CAT_DIV, colors=CAT_COLORS, reorder=reorder, qmethod=qmethod
        )

    # Sonic: source order is ready, kick, ball, jump, victory.
    # Target: ready, kick, jump, approved spinball, victory.
    sonic_reorder = [0, 1, 3, 2, 4]
    print("\n=== sonic spinball ===")
    ball = process_spinball(88)
    # If the ball is huge vs a cat, shrink it to ~ the kick-frame height later if needed.
    print("\n=== sonic roman ===")
    metas["roman_sonic"] = process_sheet(
        ROOT / "roman_sonic.jpg",
        "roman_sonic",
        div=CAT_DIV,
        colors=CAT_COLORS,
        reorder=sonic_reorder,
        replace={3: ball},
    )
    print("\n=== sonic morty ===")
    metas["morty_sonic"] = process_sheet(
        ROOT / "morty_sonic.jpg",
        "morty_sonic",
        div=CAT_DIV,
        colors=CAT_COLORS,
        reorder=sonic_reorder,
        replace={3: ball},
    )

    for fid, roman, morty in [
        ("pyra", "roman_pyra2.jpg", "morty_pyra2.jpg"),
        ("mythra", "roman_mythra2.jpg", "morty_mythra2.jpg"),
    ]:
        print(f"\n=== {fid} roman ===")
        metas[f"roman_{fid}"] = process_sheet(ROOT / roman, f"roman_{fid}", div=AEGIS_DIV, colors=AEGIS_COLORS)
        print(f"\n=== {fid} morty ===")
        metas[f"morty_{fid}"] = process_sheet(ROOT / morty, f"morty_{fid}", div=AEGIS_DIV, colors=AEGIS_COLORS)

    dest = Path("/workspace/litterapp/assets/fighters.json")
    dest.write_text(json.dumps(metas, indent=2))
    print("\nwrote", dest)


if __name__ == "__main__":
    main()
