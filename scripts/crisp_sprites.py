#!/usr/bin/env python3
"""Chroma-key, pixelize, and pack sprite sheets for the litter-tracker dashboard."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path("/workspace")
OUT = Path("/workspace/litterapp/assets")
PREVIEW = Path("/workspace/sprite_preview")
OUT.mkdir(parents=True, exist_ok=True)
PREVIEW.mkdir(parents=True, exist_ok=True)

# Downscale by an integer factor so nearest-neighbor stays on a hard pixel grid.
SCALE_DIV = 3
PALETTE_COLORS = 22
MIN_FRAME_W = 24
MIN_COMPONENT = 40


def chroma_rgba(im: Image.Image) -> np.ndarray:
    rgb = np.array(im.convert("RGB"))
    r = rgb[:, :, 0].astype(np.int16)
    g = rgb[:, :, 1].astype(np.int16)
    b = rgb[:, :, 2].astype(np.int16)
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    sat = np.where(mx == 0, 0, (mx - mn) / np.maximum(mx, 1))
    # Bright magenta / hot-pink key (JPEG-shifted #FF00FF).
    is_bg = (sat > 0.32) & (g < r) & (g < b) & (g < 150) & (r > 155) & (b > 100)
    is_bg |= (g < 90) & (r > 190) & (b > 115) & ((r + b) > (2 * g + 70))
    alpha = np.where(is_bg, 0, 255).astype(np.uint8)

    # Drop isolated specks (JPEG noise).
    fg = alpha > 0
    # 4-connected neighbor count
    nbr = np.zeros(fg.shape, dtype=np.int16)
    nbr[1:, :] += fg[:-1, :]
    nbr[:-1, :] += fg[1:, :]
    nbr[:, 1:] += fg[:, :-1]
    nbr[:, :-1] += fg[:, 1:]
    alpha[(fg) & (nbr == 0)] = 0

    # Despill: pull magenta fringe toward local luminance on edge pixels.
    fg = alpha > 0
    edge = fg & (nbr < 4)
    if edge.any():
        # magenta component ≈ min(excess R above G, excess B above G)
        spill = np.minimum(np.maximum(r - g, 0), np.maximum(b - g, 0))
        # only despill strongly magenta-tinted edge pixels
        strong = edge & (spill > 25) & (g < 160)
        if strong.any():
            r2, g2, b2 = r.copy(), g.copy(), b.copy()
            # mix toward a de-magentaized color
            r2[strong] = np.clip(r[strong] - spill[strong] * 3 // 4, 0, 255)
            b2[strong] = np.clip(b[strong] - spill[strong] * 3 // 4, 0, 255)
            # if almost pure spill leftover, punch to transparent
            still = strong & (g < 100) & (r2 > 180) & (b2 > 120)
            alpha[still] = 0
            rgb = np.dstack([r2.astype(np.uint8), g2.astype(np.uint8), b2.astype(np.uint8)])
        else:
            rgb = np.array(im.convert("RGB"))
    else:
        rgb = np.array(im.convert("RGB"))

    return np.dstack([rgb, alpha])


def column_runs(alpha: np.ndarray, min_w: int = MIN_FRAME_W) -> list[tuple[int, int]]:
    occ = (alpha > 0).sum(axis=0)
    # A column counts as content if it has more than a couple of pixels
    # (ignores 1–3 px JPEG crumbs / whisker slivers in gaps).
    filled = occ >= 5
    runs: list[tuple[int, int]] = []
    in_run = False
    start = 0
    for i, v in enumerate(filled):
        if v and not in_run:
            start = i
            in_run = True
        elif not v and in_run:
            if i - start >= min_w:
                runs.append((start, i - 1))
            in_run = False
    if in_run and (len(filled) - start) >= min_w:
        runs.append((start, len(filled) - 1))

    # Split unusually wide runs at deep occupancy valleys (touching poses).
    split: list[tuple[int, int]] = []
    for a, b in runs:
        width = b - a + 1
        if width < 180:
            split.append((a, b))
            continue
        sl = occ[a : b + 1].astype(np.float64)
        # smooth a little
        k = 5
        kernel = np.ones(k) / k
        sm = np.convolve(sl, kernel, mode="same")
        # find local minima in the interior
        interior = sm[20:-20]
        if len(interior) == 0:
            split.append((a, b))
            continue
        peak = sm.max()
        thresh = max(8, peak * 0.18)
        mins = []
        for i in range(20, width - 20):
            if sm[i] <= thresh and sm[i] <= sm[i - 1] and sm[i] <= sm[i + 1]:
                mins.append(i)
        if not mins:
            split.append((a, b))
            continue
        # cluster nearby minima, take the deepest in each cluster
        cuts = []
        cluster = [mins[0]]
        for m in mins[1:]:
            if m - cluster[-1] <= 8:
                cluster.append(m)
            else:
                cuts.append(a + min(cluster, key=lambda x: sm[x - a] if False else sm[x]))
                cluster = [m]
        cuts.append(a + min(cluster, key=lambda x: sm[x]))
        # keep cuts that actually produce wide enough pieces
        edges = [a] + cuts + [b]
        pieces = []
        ok = True
        prev = a
        for c in cuts + [b]:
            if c - prev < min_w:
                ok = False
                break
            pieces.append((prev, c - (0 if c == b else 1)))
            prev = c
        if ok and len(pieces) > 1:
            split.extend(pieces)
        else:
            split.append((a, b))
    return split


def autocrop(frame: np.ndarray) -> np.ndarray:
    ys, xs = np.where(frame[:, :, 3] > 0)
    if len(xs) == 0:
        return frame[:1, :1]
    return frame[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]


def foot_baseline(frame: np.ndarray) -> int:
    """Lowest row with a solid stance (paws), ignoring thin sword tips or lightning FX."""
    alpha = frame[:, :, 3] > 0
    row_w = alpha.sum(axis=1)
    rows = np.where(row_w > 0)[0]
    if len(rows) == 0:
        return frame.shape[0] - 1
    # Body/paws are much wider than sword tips or lightning bolts.
    peak = int(row_w.max())
    need = max(10, int(peak * 0.35))
    for y in range(rows[-1], rows[0] - 1, -1):
        if int(row_w[y]) >= need:
            return int(y)
    return int(rows[-1])


def nn_downscale(frame: np.ndarray, div: int) -> np.ndarray:
    im = Image.fromarray(frame, "RGBA")
    w, h = im.size
    nw, nh = max(1, w // div), max(1, h // div)
    return np.array(im.resize((nw, nh), Image.Resampling.NEAREST))


def quantize_sheet(frames: list[np.ndarray], colors: int = PALETTE_COLORS) -> list[np.ndarray]:
    # Collect opaque pixels into a single image for a shared palette.
    pixels = [f[f[:, :, 3] >= 128][:, :3] for f in frames]
    pix = np.concatenate(pixels, axis=0) if pixels else np.zeros((1, 3), dtype=np.uint8)
    swatch = Image.fromarray(pix.reshape(1, -1, 3), "RGB")
    pal_img = swatch.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    palette = pal_img.getpalette()[: colors * 3]

    out = []
    for f in frames:
        rgb = Image.fromarray(f[:, :, :3], "RGB")
        q = rgb.quantize(palette=pal_img, dither=Image.Dither.NONE).convert("RGB")
        arr = np.array(q)
        alpha = np.where(f[:, :, 3] >= 128, 255, 0).astype(np.uint8)
        # punch fully transparent
        arr[alpha == 0] = 0
        out.append(np.dstack([arr, alpha]))
    return out


def pack_sheet(frames: list[np.ndarray], pad: int = 2) -> tuple[Image.Image, int, int, int]:
    """Baseline-align frames onto a shared canvas and pack horizontally.

    Cell width is large enough that no pose clips, with a shared foot-anchor.
    """
    bases = [foot_baseline(f) for f in frames]
    above = max(b + 1 for b in bases)
    below = max(f.shape[0] - b - 1 for f, b in zip(frames, bases))
    foot_cxs = []
    lefts = []
    rights = []
    for f, b in zip(frames, bases):
        foot = f[max(0, b - 3): b + 1]
        xs = np.where(foot[:, :, 3] > 0)[1] if foot.size else np.array([])
        foot_cx = int(xs.mean()) if len(xs) else f.shape[1] // 2
        foot_cxs.append(foot_cx)
        lefts.append(foot_cx + pad)
        rights.append(f.shape[1] - foot_cx + pad)
    left_need = max(lefts)
    right_need = max(rights)
    cell_w = left_need + right_need
    target_cx = left_need
    top_pad = pad
    canvas_h = above + below + pad * 2
    canvas_w = cell_w * len(frames)
    sheet = np.zeros((canvas_h, canvas_w, 4), dtype=np.uint8)
    for i, f in enumerate(frames):
        b = foot_baseline(f)
        x0 = i * cell_w + target_cx - foot_cxs[i]
        y0 = top_pad + (above - (b + 1))
        y1 = y0 + f.shape[0]
        x1 = x0 + f.shape[1]
        # clip if needed
        ys, xs = max(0, y0), max(0, x0)
        ye, xe = min(canvas_h, y1), min(canvas_w, x1)
        fy0, fx0 = ys - y0, xs - x0
        sheet[ys:ye, xs:xe] = f[fy0 : fy0 + (ye - ys), fx0 : fx0 + (xe - xs)]
    # Foot line as a fraction of canvas height, for CSS transform-origin.
    anchor_x = round(target_cx / cell_w, 4) if cell_w else 0.5
    anchor_y = (top_pad + above) / canvas_h if canvas_h else 1.0
    return Image.fromarray(sheet, "RGBA"), cell_w, canvas_h, len(frames), anchor_x, round(anchor_y, 4)


def process(path: Path, name: str) -> dict:
    im = Image.open(path)
    rgba = chroma_rgba(im)
    Image.fromarray(rgba, "RGBA").save(PREVIEW / f"{name}_keyed.png")
    runs = column_runs(rgba[:, :, 3])
    print(f"{name}: {len(runs)} frames from {path.name}")
    raw_frames = []
    for a, b in runs:
        fr = autocrop(rgba[:, a : b + 1])
        # drop nearly empty
        if (fr[:, :, 3] > 0).sum() < MIN_COMPONENT:
            print(f"  skip tiny run x={a}-{b}")
            continue
        raw_frames.append(fr)
        print(f"  frame {len(raw_frames)-1}: {fr.shape[1]}x{fr.shape[0]} x={a}-{b}")

    # Drop leftover crumbs (slash sparks, cape slivers) vs real poses.
    if raw_frames:
        areas = [(f[:, :, 3] > 0).sum() for f in raw_frames]
        med = sorted(areas)[len(areas) // 2]
        kept = []
        for i, (f, a) in enumerate(zip(raw_frames, areas)):
            if a < max(MIN_COMPONENT, med * 0.25):
                print(f"  drop crumb frame {i} area={a} (median={med})")
                continue
            kept.append(f)
        raw_frames = kept

    scaled = [nn_downscale(f, SCALE_DIV) for f in raw_frames]
    # Drop frames that collapsed to nothing
    scaled = [f for f in scaled if (f[:, :, 3] >= 128).sum() >= 8]
    quantized = quantize_sheet(scaled, PALETTE_COLORS)
    sheet, cw, ch, nf, ax, ay = pack_sheet(quantized)
    dest = OUT / f"{name}.png"
    sheet.save(dest, "PNG", optimize=True)
    # also a preview on a dark bg, scaled up 4x nearest for inspection
    prev = Image.new("RGBA", (sheet.size[0] * 4, sheet.size[1] * 4), (20, 22, 28, 255))
    big = sheet.resize((sheet.size[0] * 4, sheet.size[1] * 4), Image.Resampling.NEAREST)
    prev.alpha_composite(big)
    prev.convert("RGB").save(PREVIEW / f"{name}_sheet_4x.png", quality=95)
    # unique colors
    cols = sheet.getcolors(maxcolors=500000)
    ncolors = len(cols) if cols else -1
    meta = {
        "file": dest.name,
        "sprite_w": cw,
        "sprite_h": ch,
        "frames": nf,
        "anchor_x": ax,
        "anchor_y": ay,
        "colors": ncolors,
        "bytes": dest.stat().st_size,
    }
    print(f"  packed {dest} {cw}x{ch} x{nf}  colors={ncolors}  {meta['bytes']} bytes")
    return meta


def compress_stage():
    im = Image.open(ROOT / "omega_stage.jpg").convert("RGB")
    im = im.resize((960, 540), Image.Resampling.LANCZOS)
    dest = OUT / "omega_stage.jpg"
    im.save(dest, "JPEG", quality=84, optimize=True)
    print(f"stage {im.size} -> {dest} {dest.stat().st_size} bytes")


def main():
    metas = {}
    metas["roman_idle"] = process(ROOT / "roman_idle8.jpg", "roman_idle")
    metas["morty_idle"] = process(ROOT / "morty_idle8.jpg", "morty_idle")
    metas["roman_fight"] = process(ROOT / "roman_sword.jpg", "roman_fight")
    metas["morty_fight"] = process(ROOT / "morty_fight.jpg", "morty_fight")
    compress_stage()
    (OUT / "sprites.json").write_text(json.dumps(metas, indent=2))
    print("wrote", OUT / "sprites.json")


if __name__ == "__main__":
    main()
