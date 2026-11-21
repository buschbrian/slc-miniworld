"""Write cam/<city>_<level>_shots.json: the frozen frame list plus per-frame camera targets.

  python pipeline/plan_grid.py --level detail                              # first build (frozen after)
  python pipeline/plan_grid.py --level detail --extend "Salt Lake County"  # append an area's frames

--extend adds the frames listed for an area in data/frames_by_area.json (see area_frames.py). Existing
frames keep their names, targets and order, so finished renders and paintings stay valid.
"""
import argparse
import json

from geo import ROOT, frame_name, frame_target_enu, load_cam, parse_name, plan_frames, wavefront


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", default="slc")
    ap.add_argument("--level", default="detail")
    ap.add_argument("--force", action="store_true", help="overwrite a frozen shot list")
    ap.add_argument("--extend", metavar="AREA", help="append the frames of AREA in data/frames_by_area.json")
    a = ap.parse_args()
    cam = load_cam(a.city)
    out = ROOT / "cam" / f"{a.city}_{a.level}_shots.json"
    if a.extend:
        return extend(cam, a, out)
    if out.exists() and not a.force:
        print(f"{out.name} exists (frozen); pass --force to rebuild")
        return
    if not cam["probe"]:
        print("warning: no probe yet; using ground_h_guess for h0")
    frames = wavefront(plan_frames(cam, a.level))
    write(cam, a, out, [shot(cam, a.level, r, c) for r, c in frames], {})


def shot(cam, level, r, c):
    return {"name": frame_name(r, c), "r": r, "c": c,
            "target_enu": [round(v, 4) for v in frame_target_enu(cam, level, r, c)]}


def write(cam, a, out, shots, extra):
    rows = sorted({s["r"] for s in shots})
    cols = sorted({s["c"] for s in shots})
    ppm, step = cam["levels"][a.level]["ppm"], cam["step_px"]
    km2 = len(shots) * (step / ppm) * (step / ppm / (0.5 if cam["elevation_deg"] == 30 else 1)) / 1e6
    meta = {"city": a.city, "level": a.level, "ppm": ppm, "h0": cam["h0"], "count": len(shots),
            "rows": [rows[0], rows[-1]], "cols": [cols[0], cols[-1]], "approx_ground_km2": round(km2, 1), **extra}
    out.write_text(json.dumps({"meta": meta, "shots": shots}, indent=1))
    print(json.dumps(meta))


def extend(cam, a, out):
    data = json.loads(out.read_text())
    shots = data["shots"]
    have = {s["name"] for s in shots}
    area = json.loads((ROOT / "data" / "frames_by_area.json").read_text(encoding="utf-8"))[a.extend]
    new = [(r, c) for r, c in wavefront(sorted({parse_name(n) for n in area if n not in have}))]
    shots += [shot(cam, a.level, r, c) for r, c in new]
    extended = sorted(set(data["meta"].get("extended_with", [])) | {a.extend})
    print(f"{len(new)} frames added for {a.extend}")
    write(cam, a, out, shots, {"extended_with": extended})


if __name__ == "__main__":
    main()
