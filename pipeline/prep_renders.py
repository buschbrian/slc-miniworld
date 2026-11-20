"""2,048 px raw renders -> 1,024 px JPEG + 16-bit height PNG, then QA flags.

Heights are stored as uint16 v = (h_rel + 300) / 0.04, 0 = no geometry. Raw 2,048 px files are
deleted after conversion (keep only what the pipeline needs from Google content).
"""
import argparse
import json

import numpy as np
from PIL import Image

from geo import ROOT


def decode_raw_height(path):
    a = np.asarray(Image.open(path).convert("RGB")).astype(np.float64)
    v = a[..., 0] * 256 + a[..., 1]
    return np.where(a[..., 2] == 255, v, np.nan)


def downsample_height(v):
    h, w = v.shape
    blocks = v.reshape(h // 2, 2, w // 2, 2).transpose(0, 2, 1, 3).reshape(h // 2, w // 2, 4)
    with np.errstate(all="ignore"):
        out = np.nanmedian(blocks, axis=-1)
    return np.where(np.isfinite(out), np.clip(np.round(out), 1, 65535), 0).astype(np.uint16)


def load_height(level, name):
    """uint16 PNG -> metres relative to h0 (nan where no geometry)."""
    v = np.asarray(Image.open(ROOT / "heights" / level / f"{name}.png")).astype(np.float64)
    return np.where(v > 0, v * 0.04 - 300.0, np.nan)


def laplacian_var(gray):
    g = gray.astype(np.float32)
    lap = -4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]
    return float(lap.var())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", default="detail")
    ap.add_argument("--keep-raw", action="store_true")
    a = ap.parse_args()
    rdir, hdir = ROOT / "renders" / a.level, ROOT / "heights" / a.level
    qa_path = rdir / "qa.json"
    qa = json.loads(qa_path.read_text()) if qa_path.exists() else {}
    for raw in sorted((rdir / "raw").glob("*.png")):
        name = raw.stem
        img = Image.open(raw).convert("RGB")
        small = img.resize((img.width // 2, img.height // 2), Image.LANCZOS)
        small.save(rdir / f"{name}.jpg", quality=92)
        hraw = hdir / "raw" / f"{name}.png"
        hv = downsample_height(decode_raw_height(hraw)) if hraw.exists() else None
        if hv is not None:
            Image.fromarray(hv).save(hdir / f"{name}.png")
        arr = np.asarray(small)
        black = float((arr.max(-1) < 10).mean())
        nodata = float((hv == 0).mean()) if hv is not None else 1.0
        qa[name] = {"black_frac": round(black, 4), "nodata_frac": round(nodata, 4),
                    "lap_var": round(laplacian_var(arr.mean(-1)), 1)}
        if not a.keep_raw:
            raw.unlink()
            if hraw.exists():
                hraw.unlink()
    lv = np.array([q["lap_var"] for q in qa.values()]) if qa else np.array([1.0])
    med = float(np.median(lv))
    for name, q in qa.items():
        flags = []
        if q["black_frac"] > 0.02 or q["nodata_frac"] > 0.02:
            flags.append("black_or_missing")
        if q["lap_var"] < 0.15 * med:
            flags.append("possibly_blurred")
        q["flags"] = flags
    qa_path.write_text(json.dumps(qa, indent=1))
    bad = {k: v["flags"] for k, v in qa.items() if v["flags"]}
    print(f"{len(qa)} frames prepared; flagged: {bad or 'none'}")


if __name__ == "__main__":
    main()
