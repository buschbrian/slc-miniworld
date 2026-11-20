"""Paint rendered frames with an image-to-image painter (Codex, Grok CLI or Gemini; see painters.py).

  python pipeline/paint.py --level detail --block=0:2,0:2 --bootstrap   # first frame, style candidate
  cp style/candidate.png style/ref.png                                    # human approves the style
  python pipeline/paint.py --level detail --block=0:2,0:2                 # paint with the reference

Order is a wavefront from the top-left. Before a frame is sent, the already-painted pixels of its
top, left and top-left neighbours are pasted over the render's overlap band so the painter continues
existing art. The result is resized to 1,024 px, registered back onto the render (scale + shift)
and rejected/retried if it moved too far.
"""
import argparse
import json
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

from geo import ROOT, frame_name, frame_origin, load_cam, parse_name, wavefront
from painters import PAINTERS

OVERLAP = 256

STYLE_RULES = (
    "Style: crisp hand-made pixel art with hard edges and thin dark outlines; each surface uses one lit "
    "tone and one shadow tone, with no gradients and no photo texture; warm late-afternoon light; warm "
    "sandstone, brick and pale-grey roofs, warm-grey asphalt with simple lane markings, mid-green lawns, "
    "dry tan grass on hillsides, rounded tree canopies, flat calm water.")
FIDELITY = (
    "Keep the exact camera, framing, scale and layout: every building, road, tree, field and water body "
    "stays exactly where it is, with the same shape and size, so neighbouring tiles stitch together. "
    "Do not add, remove or move anything. Paint trees only where the render shows trees: never add "
    "trees or shrubs to open lawns, plazas, parking lots or bare ground. "
    "Prefer empty streets: leave out cars and people. "
    "No text, labels, borders or UI. Output one square image with exactly the framing of the input.")
BOOTSTRAP_PROMPT = (
    "The attached image is a render of a real photogrammetric 3D model "
    "of a city from a fixed orthographic camera looking down at 30 degrees. Repaint this exact view in "
    "a warm isometric pixel-art map style; preserve layout, buildings, roads, and water exactly. "
    + STYLE_RULES + " " + FIDELITY)
PAINT_PROMPT = (
    "Image 1 is a 3D render of one map tile. Repaint this exact view in "
    "the warm miniWorld pixel style shown in image 2; preserve layout, buildings, roads, and water exactly. "
    "Image 2 is only a style reference: copy its palette, outlines, shading and pixel scale, never its "
    "content. " + FIDELITY)
CONTEXT_NOTE = (" The {sides} edge of image 1 already contains finished painted art from neighbouring "
                "tiles; keep that art unchanged and continue it seamlessly into the rest of the tile.")


def gray(a):
    return np.asarray(a, np.float32)[..., :3].mean(-1)


def grad(g):
    gx = np.zeros_like(g)
    gy = np.zeros_like(g)
    gx[:, 1:-1] = g[:, 2:] - g[:, :-2]
    gy[1:-1] = g[2:] - g[:-2]
    return np.hypot(gx, gy)


def phase_corr(a, b):
    """Shift (dx, dy) that moves b onto a, plus peak sharpness."""
    win = np.outer(np.hanning(a.shape[0]), np.hanning(a.shape[1])).astype(np.float32)
    fa, fb = np.fft.rfft2((a - a.mean()) * win), np.fft.rfft2((b - b.mean()) * win)
    r = fa * np.conj(fb)
    r /= np.abs(r) + 1e-6
    c = np.fft.irfft2(r, s=a.shape)
    y, x = np.unravel_index(np.argmax(c), c.shape)
    peak = float(c[y, x] / (c.std() + 1e-9))
    if y > a.shape[0] // 2:
        y -= a.shape[0]
    if x > a.shape[1] // 2:
        x -= a.shape[1]
    return int(x), int(y), peak


def affine(img, scale, dx, dy, size):
    """Scale about the centre then shift; returns a size x size image."""
    c = size / 2
    inv = 1 / scale
    return img.transform((size, size), Image.AFFINE,
                         (inv, 0, c - inv * (c + dx), 0, inv, c - inv * (c + dy)),
                         resample=Image.BICUBIC, fillcolor=None)


def register(painted, render):
    """Find scale/shift aligning painted to render using gradient phase correlation (quarter res)."""
    q = 256
    rg = grad(gray(render.resize((q, q), Image.BILINEAR)))
    best = None
    for s in np.round(np.arange(0.94, 1.0601, 0.01), 2):
        cand = affine(painted, s, 0, 0, painted.width).resize((q, q), Image.BILINEAR)
        dx, dy, peak = phase_corr(rg, grad(gray(cand)))
        if best is None or peak > best[3]:
            best = (s, dx * painted.width / q, dy * painted.width / q, peak)
    s, _, _, peak = best
    dx, dy, _ = phase_corr(grad(gray(render)), grad(gray(affine(painted, s, 0, 0, painted.width))))
    return s, float(dx), float(dy), peak


def context_image(cam, level, r, c, render):
    """Paste painted neighbour overlap bands into the render. Returns image and the pasted mask."""
    ctx = render.copy()
    mask = np.zeros((render.height, render.width), bool)
    size, step = cam["frame_px"], cam["step_px"]
    sides = []
    for dr, dc, side in ((-1, 0, "top"), (0, -1, "left"), (-1, -1, None)):
        p = painted_path(level, r + dr, c + dc)
        if not p.exists():
            continue
        nb = Image.open(p).convert("RGB")
        ox, oy = -dc * step, -dr * step  # neighbour origin relative to this frame
        x0, y0 = max(0, -ox), max(0, -oy)
        x1, y1 = min(size, size - ox), min(size, size - oy)
        crop = nb.crop((x0 + ox, y0 + oy, x1 + ox, y1 + oy))
        # neighbour pixel (x+ox) == this frame pixel x, since frames step by `step`
        ctx.paste(crop, (x0, y0))
        mask[y0:y1, x0:x1] = True
        if side:
            sides.append(side)
    return ctx, mask, sides


PAINT_ROOT = ROOT / "painted"


def painted_path(level, r, c):
    return PAINT_ROOT / level / f"{frame_name(r, c)}.png"


def procedural_water(cam, r, c, rgb):
    size = cam["frame_px"]
    ox, oy = frame_origin(cam, r, c)
    yy, xx = np.mgrid[0:size, 0:size]
    gx, gy = (xx + ox) // 4, (yy + oy) // 4
    h = (gx * 73856093 ^ gy * 19349663) & 1023
    base = np.array(rgb, np.float32)
    img = np.broadcast_to(base, (size, size, 3)).copy()
    img[h < 24] = base * 1.12
    img[(h >= 24) & (h < 40)] = base * 0.92
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))


def paint_one(cam, level, name, painter, style_ref, bootstrap, water, retries=2):
    r, c = parse_name(name)
    out = painted_path(level, r, c)
    log = {"name": name, "level": level}
    if water.get(name, 0) >= 0.92:
        procedural_water(cam, r, c, cam.get("water_rgb", [74, 128, 150])).save(out)
        return {**log, "mode": "procedural_water"}
    render = Image.open(ROOT / "renders" / level / f"{name}.jpg").convert("RGB")
    ctx, mask, sides = context_image(cam, level, r, c, render)
    if bootstrap:
        prompt, images = BOOTSTRAP_PROMPT, [ctx]
    else:
        prompt, images = PAINT_PROMPT + (CONTEXT_NOTE.format(sides=" and ".join(sides)) if sides else ""), [ctx, style_ref]
    for attempt in range(retries + 1):
        if painter.stop.is_set():
            return {**log, "error": "stopped (quota/auth): " + str(log.get("error", ""))[:300]}
        img, info = painter.paint(prompt, images)
        log.update(info, attempt=attempt)
        if img is None:
            continue
        img = img.resize((cam["frame_px"], cam["frame_px"]), Image.LANCZOS)
        s, dx, dy, peak = register(img, render)
        log.update(scale=s, dx=round(dx, 1), dy=round(dy, 1), peak=round(peak, 1))
        if abs(dx) > 48 or abs(dy) > 48 or peak < 6:
            log["error"] = "misregistered"
            continue
        if abs(s - 1) > 1e-6 or abs(dx) > 1.5 or abs(dy) > 1.5:
            img = affine(img, s, dx, dy, cam["frame_px"])
            fill = np.asarray(img).max(-1) == 0
            if fill.any():  # areas uncovered by the shift fall back to the context/render pixels
                a = np.asarray(img).copy()
                a[fill] = np.asarray(ctx)[fill]
                img = Image.fromarray(a)
        if mask.any():
            diff = np.abs(np.asarray(img, np.float32) - np.asarray(ctx, np.float32)).mean(-1)[mask].mean()
            log["context_mad"] = round(float(diff), 1)
        log.pop("error", None)
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(out)
        return log
    return log


def select(cam, level, a):
    shots = json.loads((ROOT / "cam" / f"{cam['city']}_{level}_shots.json").read_text())["shots"]
    names = [s["name"] for s in shots]
    if a.only:
        want = set(a.only.split(","))
        names = [n for n in names if n in want]
    if a.block:
        (r0, r1), (c0, c1) = [tuple(map(int, p.split(":"))) for p in a.block.split(",")]
        names = [n for n in names if r0 <= parse_name(n)[0] <= r1 and c0 <= parse_name(n)[1] <= c1]
    names = [n for n in names if (ROOT / "renders" / level / f"{n}.jpg").exists()]
    if not a.redo:
        names = [n for n in names if not painted_path(level, *parse_name(n)).exists()]
    order = [frame_name(r, c) for r, c in wavefront([parse_name(n) for n in names])]
    return order[: a.limit] if a.limit else order


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", default="slc")
    ap.add_argument("--level", default="detail")
    ap.add_argument("--only")
    ap.add_argument("--block", help="r0:r1,c0:c1 inclusive")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--bootstrap", action="store_true", help="paint one frame without a style reference")
    ap.add_argument("--redo", action="store_true")
    ap.add_argument("--painter", default="codex", choices=sorted(PAINTERS))
    ap.add_argument("--tag", help="write to painted/bakeoff/<tag>/ instead of painted/")
    ap.add_argument("--model", help="painter model override")
    ap.add_argument("--effort", help="painter reasoning effort override")
    ap.add_argument("--timeout", type=int, default=420)
    a = ap.parse_args()
    global PAINT_ROOT
    if a.tag:
        PAINT_ROOT = ROOT / "painted" / "bakeoff" / a.tag
    cam = load_cam(a.city)
    if not cam["probe"]:
        sys.exit("run the probe first; h0 must be frozen before painting")
    ref_path = ROOT / "style" / "ref.png"
    if a.bootstrap:
        a.limit, a.workers = 1, 1
    elif not ref_path.exists():
        sys.exit("style/ref.png missing: run with --bootstrap, review style/candidate.png, then copy it to style/ref.png")
    style_ref = None if a.bootstrap else Image.open(ref_path).convert("RGB")
    wpath = ROOT / "masks" / a.level / "water.json"
    water = json.loads(wpath.read_text()) if wpath.exists() else {}
    names = select(cam, a.level, a)
    painter = PAINTERS[a.painter](a.model, a.effort, a.timeout)
    print(f"painting {len(names)} frames ({a.level}) with {a.painter} {painter.model or ''}/{painter.effort or ''}, "
          f"{a.workers} workers -> {PAINT_ROOT.relative_to(ROOT)}")
    logf = PAINT_ROOT / a.level / "log.jsonl"
    logf.parent.mkdir(parents=True, exist_ok=True)
    done = failed = 0
    by_diag = {}
    for n in names:
        by_diag.setdefault(sum(parse_name(n)), []).append(n)
    with ThreadPoolExecutor(a.workers) as pool:
        for d in sorted(by_diag):
            for res in pool.map(lambda n: paint_one(cam, a.level, n, painter, style_ref, a.bootstrap, water),
                                by_diag[d]):
                with logf.open("a") as f:
                    f.write(json.dumps(res) + "\n")
                ok = "error" not in res
                done += ok
                failed += not ok
                print(("ok   " if ok else "FAIL ") + json.dumps(res))
            if painter.stop.is_set():
                sys.exit(f"stopped: {a.painter} reported a quota/auth problem")
            if done + failed >= 5 and failed / (done + failed) > 0.2:
                sys.exit(f"stopped: {failed}/{done + failed} frames failed (>20%)")
    if a.bootstrap and done:
        (ROOT / "style").mkdir(exist_ok=True)
        shutil.copy(painted_path(a.level, *parse_name(names[0])), ROOT / "style" / "candidate.png")
        print("style candidate written to style/candidate.png; review it, then copy to style/ref.png")
    print(f"done: {done} painted, {failed} failed")


if __name__ == "__main__":
    main()
