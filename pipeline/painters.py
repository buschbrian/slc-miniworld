"""Image-to-image painter backends. Each takes (prompt, [render_with_context, style_ref]) and
returns (PIL image | None, info dict). `stop` is set on quota/auth failures so a run halts.

  codex  - `codex exec` + built-in image generation (ChatGPT plan quota)
  grok   - `grok -p` (Grok Build) + its image_edit tool (SuperGrok subscription)
  gemini - Gemini API Interactions endpoint, Nano Banana models (GEMINI_API_KEY, billed per image)
"""
import base64
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image

from geo import ROOT

STOP_WORDS = re.compile(r"usage limit|rate limit|quota|insufficient|purchase more credits|401|403|"
                        r"unauthorized|permission denied|billing", re.I)


def env_value(name):
    if os.environ.get(name):
        return os.environ[name]
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip("'\"")
    return None


class Painter:
    wrap = "{prompt}"
    defaults = {}

    def __init__(self, model=None, effort=None, timeout=420):
        self.model = model or self.defaults.get("model")
        self.effort = effort or self.defaults.get("effort")
        self.timeout = timeout
        self.stop = threading.Event()

    def prompt(self, core):
        return self.wrap.format(prompt=core)

    def check_stop(self, text):
        if text and STOP_WORDS.search(text):
            self.stop.set()


class Codex(Painter):
    wrap = "Use your image generation tool. {prompt} Do not write files or run commands."
    defaults = {"model": "gpt-6-luna", "effort": "low"}
    GEN_DIR = Path.home() / ".codex" / "generated_images"

    def paint(self, prompt, images):
        with tempfile.TemporaryDirectory() as td:
            # Prompt goes on stdin: Windows runs codex through an npm .cmd shim, where cmd.exe mangles quotes.
            cmd = [shutil.which("codex") or "codex", "exec", "-m", self.model, "-c",
                   f'model_reasoning_effort="{self.effort}"', "--skip-git-repo-check", "-s", "read-only", "--json"]
            for i, im in enumerate(images):
                p = Path(td) / f"in{i}.png"
                im.save(p)
                cmd += ["-i", str(p)]
            t0 = time.time()
            try:
                pr = subprocess.run(cmd, cwd=td, capture_output=True, text=True, timeout=self.timeout,
                                    input=self.prompt(prompt), encoding="utf-8", errors="replace")
            except subprocess.TimeoutExpired:
                return None, {"error": "timeout"}
            tid =re.search(r'"thread_id":"([^"]+)"', pr.stdout)
            info = {"secs": round(time.time() - t0, 1), "thread": tid.group(1) if tid else None}
            failures = []
            for line in pr.stdout.splitlines():
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("type") in ("error", "turn.failed"):
                    failures.append(ev.get("message") or (ev.get("error") or {}).get("message", ""))
            for m in failures:
                self.check_stop(m)
            if not tid:
                self.check_stop(pr.stderr[-2000:])
            gen = sorted((self.GEN_DIR / info["thread"]).glob("*.png"), key=os.path.getmtime) if tid else []
            if not gen:
                info["error"] = (failures[-1] if failures else (pr.stderr or pr.stdout))[-400:]
                return None, info
            return Image.open(gen[-1]).convert("RGB"), info


class GrokCLI(Painter):
    defaults = {"model": None, "effort": "low"}
    SESSIONS = Path.home() / ".grok" / "sessions"

    def paint(self, prompt, images):
        with tempfile.TemporaryDirectory() as td:
            names = []
            for i, im in enumerate(images):
                p = Path(td) / f"image{i + 1}.png"
                im.save(p)
                names.append(p.name)
            order = ", ".join(f"image {i + 1} = {n}" for i, n in enumerate(names))
            instr = (f"Call the image_edit tool exactly once. Pass these files as the input images in this order "
                     f"({order}), use aspect ratio 1:1, and use this edit prompt verbatim:\n\n{prompt}\n\n"
                     "Do not call any other tool. After the edit, reply only with the output image path.")
            cmd = ["grok", "-p", instr, "--tools", "image_edit", "--output-format", "json", "--always-approve",
                   "--max-turns", "4", "--disable-web-search"]
            if self.model:
                cmd += ["-m", self.model]
            if self.effort:
                cmd += ["--effort", self.effort]
            t0 = time.time()
            try:
                pr = subprocess.run(cmd, cwd=td, capture_output=True, text=True, timeout=self.timeout,
                                    stdin=subprocess.DEVNULL)
            except subprocess.TimeoutExpired:
                return None, {"error": "timeout"}
            info = {"secs": round(time.time() - t0, 1)}
            d = {}
            for line in reversed(pr.stdout.strip().splitlines()):
                try:
                    d = json.loads(line)
                    break
                except ValueError:
                    continue
            if not d:
                try:
                    d = json.loads(pr.stdout)
                except ValueError:
                    d = {}
            sid = d.get("sessionId")
            info["session"] = sid
            self.check_stop(pr.stderr[-2000:] + str(d.get("text", ""))[-500:] if pr.returncode or not sid else "")
            outs = sorted(self.SESSIONS.glob(f"*/{sid}/images/*"), key=os.path.getmtime) if sid else []
            if not outs:
                info["error"] = (str(d.get("text", "")) or pr.stderr or pr.stdout)[-400:]
                return None, info
            return Image.open(outs[-1]).convert("RGB"), info


class Gemini(Painter):
    defaults = {"model": "gemini-nano-banana-2.1"}
    URL = "https://generativelanguage.googleapis.com/v1beta/interactions"

    @staticmethod
    def _b64(im):
        buf = io.BytesIO()
        im.save(buf, "PNG")
        return base64.b64encode(buf.getvalue()).decode()

    @staticmethod
    def _find_image(obj):
        """Last image payload anywhere in the response (the exact REST path is not documented)."""
        found = []

        def walk(o):
            if isinstance(o, dict):
                data = o.get("data")
                mime = str(o.get("mime_type") or o.get("mimeType") or o.get("type") or "")
                if isinstance(data, str) and len(data) > 1000 and "image" in mime:
                    found.append(data)
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(obj)
        return found[-1] if found else None

    def paint(self, prompt, images):
        key = env_value("GEMINI_API_KEY")
        if not key:
            self.stop.set()
            return None, {"error": "GEMINI_API_KEY missing"}
        body = {"model": self.model,
                "input": [{"type": "text", "text": prompt}] +
                         [{"type": "image", "mime_type": "image/png", "data": self._b64(im)} for im in images],
                "response_format": {"type": "image", "mime_type": "image/jpeg", "aspect_ratio": "1:1",
                                    "image_size": "1K"}}
        req = urllib.request.Request(self.URL, data=json.dumps(body).encode(), method="POST", headers={
            "x-goog-api-key": key, "Content-Type": "application/json", "Api-Revision": "2026-05-20"})
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                resp = json.load(r)
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")[-600:]
            if e.code in (401, 403, 429):
                self.stop.set()
            return None, {"error": f"HTTP {e.code}: {msg}"}
        except (urllib.error.URLError, TimeoutError) as e:
            return None, {"error": str(e)}
        info = {"secs": round(time.time() - t0, 1), "id": resp.get("id")}
        data = self._find_image(resp)
        if not data:
            info["error"] = "no image in response; keys: " + ",".join(resp)[:300]
            return None, info
        return Image.open(io.BytesIO(base64.b64decode(data))).convert("RGB"), info


PAINTERS = {"codex": Codex, "grok": GrokCLI, "gemini": Gemini}
