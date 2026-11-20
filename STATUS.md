# Status — 2026-11-20

## Google 3D coverage for Salt Lake City

The probe (`cam/slc_probe.json`) found photorealistic 3D at all 26 sample points: the anchor,
16 landmarks, and the corners of both areas. Imagery is credited to Google and Vexcel Imaging US.

- **Downtown and landmarks: good.** Real modelled buildings everywhere, with 16–86 m of relief
  inside each 300 m sample. Towers, the Tabernacle dome, the Capitol and Rice-Eccles Stadium
  are all modelled.
- **Current construction is in the mesh.** The Salt Lake Temple renovation (scaffolding and
  cranes) and the site north of the Capitol render as construction. The painter copies them.
- **Flat areas read as "partial" for low relief, not missing data:** Saltair shore (5.6 m),
  the detail SW corner (3.7 m) and the overview NW corner (1.2 m) are open flats.
- **Terrain is large.** Ensign Peak sits about +311 m above the anchor ground, the detail NE
  corner +675 m, and the overview mountain corners exceed +1,100 m. The height render now spans
  −300 to +2,321 m in 4 cm steps. The probe's mountain-corner heights were measured with the
  older encoding and are clipped at +1,110 m. Frame selection allows terrain up to +420 m, so
  the high Wasatch slopes in the detail area's NE corner sit partly outside the detail squares.
- Anchor ground height h0 = 1,297.4 m ellipsoidal (about 1,314 m NAVD88), frozen.

## Grid

| Level | ppm | Squares | Ground |
|---|---|---|---|
| detail | 3.4 | 881 | ~90 km² (downtown, Capitol, Ensign Peak, U of U, Liberty Park, east bench) |
| overview | 0.425 | 147 | ~960 km², out to the Great Salt Lake shore at Saltair |

I recommend keeping this grid. The full lake edge at 3.4 px/m would add several thousand
squares; the overview covers it at 1/8 detail, as Mini World does.

## Measured so far

- Camera self-test: browser vs Python projection error under 0.4 px.
- Raw render overlaps agree to 0.2–0.5 / 255 mean absolute difference, i.e. seamless.
- Render speed: detail 3.7 s per square (20 squares in 73 s); overview about 30 s per square.
- Codex painting: 64–164 s per square (gpt-6-luna, low effort, driving the image tool).
  Registration corrections were 0–9 px shift and 0.99–1.00 scale.
- Fidelity: buildings, roads, construction and landmarks stay put. The painter adds extra
  trees on open lawns. The first prompt revision should tighten that, or the reference should be
  swapped for a frame with fewer trees.

## Blocker

The ChatGPT plan behind Codex hit its usage limit after a few image generations in this
session; Codex reports a reset at 1:38 PM MST. The pipeline is resumable: re-running `paint.py`
skips finished squares. At this rate, plan quota, not rendering, decides how fast 1,028 squares
can be painted. Options: paint in quota windows, buy credits, or move painting to the open
pixel-art LoRA route (FLUX.2 klein 4B). That route is untested here. Marcelo measured 163 s per
frame on an M5 Max with 128 GB; this M4 has 16 GB.

## First batch

- Rendered: detail rows −2…2 × columns −2…1 (20 squares), plus all 147 overview squares.
- Overview QA: 8 squares came back with tile-shaped holes after a long render session. A
  fresh-session re-render fixed 7, and rendering alone fixed the last. The new tile-error
  logging recorded zero download errors, so cache pressure in long sessions is the likely
  cause (unconfirmed). The QA flag catches every case. The remaining "possibly blurred"
  flags are low-texture lake and salt-flat squares, not Google blurring.
- Water: Google's lake surface sits on the curved Earth, ~17 m lower across a square 25 km
  out than the anchor's tangent plane. Masks now correct for curvature before the
  water-level test (3 m tolerance). Five overview squares are now at least 60% Great Salt
  Lake; `r5_c-11` is at least 92% and gets procedural water.
- Painted: 1 of 20 (r-2_c-2, the Capitol). The style reference is the bootstrap painting of
  the anchor square (`style/ref.png`).
