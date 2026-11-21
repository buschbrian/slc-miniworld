# Helping paint Tiny Salt Lake City

The goal is all of Salt Lake County: 21,264 squares, from the Oquirrhs to the Wasatch crest and
from the airport to Draper. The map is painted one 1,024 px square at a time, and each square
costs one AI image generation. A ChatGPT plan allows roughly 190 of those a day, which is more
than 100 days for one person, so the map grows faster when more people paint.
You can take a block of up to 25 squares, paint it on your own machine with your own accounts,
and send the result back. It goes onto the [live map](https://slc-miniworld.pages.dev) after a
check, and your GitHub name goes into the credits.

## What you need

- Google Chrome, Node.js 20 or later, Python 3.11 or later and [uv](https://docs.astral.sh/uv/).
- The [Codex CLI](https://github.com/openai/codex), signed in with a ChatGPT plan that includes
  image generation. Every square uses one generation from your plan.
- A Google Maps Platform API key with the **Map Tiles API** enabled. Renders come from Google's
  Photorealistic 3D Tiles through your key. Each Chrome launch is one root-tileset request (one
  per 40 squares); check the quota page for your key before you start.
- About 2 GB of free disk space for a block.

## Rules that keep the map consistent

- Paint with the Codex painter and the prompts in `pipeline/paint.py`, against the shared style
  reference. Do not edit the prompts, `cam/` or the shot lists. The grid is frozen, so skip the
  probe and `plan_grid` steps in the README.
- Paint only the squares `contrib.py` gives you: squares inside Salt Lake County that are not on
  the map yet. It leaves out the squares the maintainer's own run paints (the Liberty Park to
  Sugar House corridor and the East Bench east of 1300 East). Check the open claim issues too:
  a block someone has claimed is theirs.
- Mountain blocks are welcome. Expect more trees and rock than buildings there; the same prompt
  and style reference apply.
- One block per claim. If you stop, say so on the issue so someone else can take it. Claims
  with no activity for 7 days are released.

## Steps

Commands use `python` for the project's virtualenv Python: `.venv\Scripts\python.exe` on
Windows, `.venv/bin/python` on macOS and Linux.

1. **Set up** (once):

   ```bash
   git clone https://github.com/buschbrian/slc-miniworld && cd slc-miniworld
   npm install
   uv venv .venv && uv pip install --python .venv numpy pillow
   cp .env.example .env      # then add GOOGLE_MAPS_API_KEY=... (or: bash scripts/set_key.sh)
   ```

   On Linux, set `CHROME_PATH` to your Chrome or Chromium binary. The renderer needs a GPU-backed
   WebGL context.

2. **Pick a block.** Blocks are 5 × 5 squares, named like `b2_-3`.

   ```bash
   python pipeline/contrib.py open          # open blocks, nearest downtown first
   python pipeline/contrib.py show b2_-3    # what a block holds
   ```

   Then open a **Claim a block** issue with the block id. Wait for the claim to be acknowledged
   so two people do not paint the same squares.

3. **Prepare** the block. This downloads the style reference and the painted squares around your
   block, so your edges continue the existing art. It then renders your squares, checks them and
   builds the water masks.

   ```bash
   python pipeline/contrib.py prepare b2_-3
   ```

   If it reports squares that are still missing, run it again. Renders are resumable.

4. **Paint.**

   ```bash
   python pipeline/contrib.py paint b2_-3
   ```

   This takes about a minute per square with 3 at a time. If your plan's image limit stops the
   run, run the same command after the limit resets; finished squares are skipped. Look through
   `painted/detail/` before you pack. Each square should be the same place as its render, in the
   same style as its neighbours.

5. **Pack and send.**

   ```bash
   python pipeline/contrib.py pack b2_-3 --github your-github-name
   ```

   Attach the zip file(s) from `submissions/` to your claim issue. GitHub limits attachments to
   25 MB, so a full block may come in two parts.

## What happens next

The maintainer runs `pipeline/intake.py` on your zip. It re-checks every square against a fresh
render of the same place, rejects anything shifted or out of place, and builds a side-by-side
review sheet. Accepted squares go through the same water and stitching pass as the rest of the
map and appear on the live site at the next deploy. The issue is closed with a link.

## Other contributions

Bug reports and fixes to the pipeline or the viewer are welcome as ordinary issues and pull
requests. Please keep generated images (renders, paintings, tiles) out of pull requests; they
are gitignored on purpose. If you work with a coding agent, point it at
[AGENTS.md](AGENTS.md); it holds the rules that keep the grid and the look consistent, and
`python scripts/live_config.py` runs the web page locally against the live tiles.
