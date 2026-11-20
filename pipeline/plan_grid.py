"""Write cam/<city>_<level>_shots.json: the frozen frame list plus per-frame camera targets."""
import argparse
import json

from geo import ROOT, frame_name, frame_target_enu, load_cam, plan_frames, wavefront


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", default="slc")
    ap.add_argument("--level", default="detail")
    ap.add_argument("--force", action="store_true", help="overwrite a frozen shot list")
    a = ap.parse_args()
    cam = load_cam(a.city)
    out = ROOT / "cam" / f"{a.city}_{a.level}_shots.json"
    if out.exists() and not a.force:
        print(f"{out.name} exists (frozen); pass --force to rebuild")
        return
    if not cam["probe"]:
        print("warning: no probe yet; using ground_h_guess for h0")
    lvl = cam["levels"][a.level]
    frames = wavefront(plan_frames(cam, a.level))
    shots = [{"name": frame_name(r, c), "r": r, "c": c,
              "target_enu": [round(v, 4) for v in frame_target_enu(cam, a.level, r, c)]}
             for r, c in frames]
    rows = sorted({r for r, _ in frames})
    cols = sorted({c for _, c in frames})
    ppm, step = lvl["ppm"], cam["step_px"]
    km2 = len(frames) * (step / ppm) * (step / ppm / (0.5 if cam["elevation_deg"] == 30 else 1)) / 1e6
    meta = {"city": a.city, "level": a.level, "ppm": ppm, "h0": cam["h0"], "count": len(frames),
            "rows": [rows[0], rows[-1]], "cols": [cols[0], cols[-1]], "approx_ground_km2": round(km2, 1)}
    out.write_text(json.dumps({"meta": meta, "shots": shots}, indent=1))
    print(json.dumps(meta))


if __name__ == "__main__":
    main()
