"""Layered SVG Animator (ADR-0001): LayoutDoc + timeline -> H.264 via FFmpeg stdio.

Performance model (measured on i3-7100U: full-frame re-rasterization was 2.2 fps bake, resvg
being 83% of cost):
  - Elements are grouped into EPOCHS by when they finish drawing.
  - Each epoch's FINISHED set is rasterized once into a cached canvas-space RGBA layer.
  - Per frame: crop/resize the cached layer to the camera viewBox (PIL, milliseconds) and,
    only while strokes are mid-draw, rasterize those elements as a transparent overlay.
  - If a drawing sits below a finished element in document paint order, rasterize that
    transient frame together to preserve occlusion. Static holds still reuse layers.
No intermediate frames touch the disk; RGBA bytes stream straight into libx264.
"""

from __future__ import annotations

import io
import logging
import os
import shutil
import subprocess
import sys
import time
from collections import OrderedDict
from pathlib import Path

from PIL import Image

from atme.render.camera import validate_camera_intent, viewbox_at
from atme.render.svg_builder import element_group, element_stroke_info, frame_svg
from atme.render.visibility import validate_visibility, visible_elements

log = logging.getLogger(__name__)

MIN_DRAW_MS = 250
MAX_DRAW_MS = 800
PAPER = "#FAF9F5"


def find_ffmpeg() -> str | None:
    exe = os.environ.get("ATME_FFMPEG") or shutil.which("ffmpeg")
    if exe:
        return exe
    if getattr(sys, "frozen", False):  # PyInstaller: check beside exe, then Tauri resource dir
        exe_dir = Path(sys.executable).parent
        for candidate in (exe_dir / "ffmpeg.exe",
                          exe_dir / "ffmpeg" / "ffmpeg.exe",
                          exe_dir / "_internal" / "ffmpeg" / "ffmpeg.exe"):
            if candidate.exists():
                return str(candidate)
    root = os.environ.get("LOCALAPPDATA", "")
    if root:
        for cand in sorted(Path(root).glob("Microsoft/WinGet/Packages/Gyan.FFmpeg*")):
            hits = list(cand.rglob("bin/ffmpeg.exe")) or list(cand.rglob("ffmpeg.exe"))
            if hits:
                return str(hits[0])
    return None


def build_draw_windows(elements: list[dict]) -> dict[str, int]:
    """Draw duration per element: bounded by gap to the next appearance."""
    times = sorted({e["appear_at_ms"] for e in elements})
    windows: dict[str, int] = {}
    for e in elements:
        action = e.get("enter_action", "draw")
        if action not in ("draw", "reveal"):
            raise ValueError("unsupported enter_action: %s" % action)
        if action == "reveal":
            windows[e["id"]] = 0
            continue
        a = e["appear_at_ms"]
        later = [t for t in times if t > a]
        gap = (later[0] - a) if later else MAX_DRAW_MS * 3
        windows[e["id"]] = max(MIN_DRAW_MS, min(MAX_DRAW_MS, int(gap * 0.7)))
    return windows


def resvg_bytes(svg: str, width: int, height: int, background=None):
    import resvg_py

    return bytes(
        resvg_py.svg_to_bytes(svg_string=svg, width=width, height=height, background=background)
    )


class _FrameRenderer:
    def __init__(self, doc: dict, infos: dict, windows: dict[str, int],
                 out_w: int, out_h: int):
        validate_visibility(doc)
        validate_camera_intent(doc.get("camera_plan", []))
        self.doc = doc
        self.infos = infos
        self.windows = windows
        self.out_w = out_w
        self.out_h = out_h
        self.canvas_w = int(doc["canvas"]["width"])
        self.canvas_h = int(doc["canvas"]["height"])
        ends = sorted({e["appear_at_ms"] + windows[e["id"]] for e in doc["elements"]})
        self.epoch_bounds = ends
        self._layers: OrderedDict[tuple, Image.Image] = OrderedDict()
        self._stateful = "board_timeline" in doc or any(
            "visibility_intervals" in e for e in doc["elements"])
        self.layer_builds = 0
        self.overlay_frames = 0
        self._cache_key = None
        self._cached: Image.Image | None = None

    # -- epochs ---------------------------------------------------------------
    def _epoch_index(self, t_ms: int) -> int:
        k = 0
        for b in self.epoch_bounds:
            if b <= t_ms:
                k += 1
            else:
                break
        return k

    def _epoch_cutoff(self, k: int) -> int:
        return self.epoch_bounds[k - 1] if k >= 1 else -1

    def _get_layer(self, k: int, t_ms: int) -> Image.Image:
        cutoff = self._epoch_cutoff(k)
        finished = [e for e in visible_elements(self.doc, t_ms)
                    if e["appear_at_ms"] + self.windows[e["id"]] <= cutoff]
        key = tuple(e["id"] for e in finished)
        if key in self._layers:
            self._layers.move_to_end(key)
            return self._layers[key]
        parts = [
            '<rect x="0" y="0" width="%d" height="%d" fill="%s"/>' % (self.canvas_w, self.canvas_h, PAPER)
        ]
        # Paint order is document order, independent of narration/reveal timing.
        for el in finished:
            frag = element_group(el, self.infos[el["id"]], cutoff + 10_000, self.windows[el["id"]])
            if frag:
                parts.append(frag)
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d">%s</svg>'
               % (self.canvas_w, self.canvas_h, "".join(parts)))
        img = Image.open(io.BytesIO(resvg_bytes(svg, self.canvas_w, self.canvas_h, PAPER))).convert("RGB")
        self._layers[key] = img
        if self._stateful and len(self._layers) > 8:
            _, evicted = self._layers.popitem(last=False)
            evicted.close()
        self.layer_builds += 1
        log.debug("epoch layer %d built (%d elems)", k, len(finished))
        return self._layers[key]

    # -- compositing ----------------------------------------------------------
    def _compose_base(self, vb: dict) -> Image.Image:
        layer_idx = max(0, self._epoch_index(int(vb["t"])))
        layer = self._get_layer(layer_idx, int(vb["t"]))
        scale = self.out_w / vb["w"]
        x0, y0 = vb["x"], vb["y"]
        src = (max(0.0, x0), max(0.0, y0),
               min(float(self.canvas_w), x0 + vb["w"]), min(float(self.canvas_h), y0 + vb["h"]))
        frame = Image.new("RGB", (self.out_w, self.out_h), PAPER)
        if src[2] <= src[0] or src[3] <= src[1]:
            return frame
        region = layer.crop((int(src[0]), int(src[1]), int(src[2]), int(src[3])))
        rw = int(round((src[2] - src[0]) * scale))
        rh = int(round((src[3] - src[1]) * scale))
        if rw < 1 or rh < 1:
            return frame
        region = region.resize((rw, rh), Image.BILINEAR)
        dx = int(round((src[0] - x0) * scale))
        dy = int(round((src[1] - y0) * scale))
        frame.paste(region, (max(0, min(dx, self.out_w - 1)), max(0, min(dy, self.out_h - 1))))
        return frame

    def frame(self, t_ms: int) -> Image.Image:
        vb = viewbox_at(self.doc.get("camera_plan", []), float(self.canvas_w),
                        float(self.canvas_h), t_ms, self.out_w, self.out_h)

        visible = visible_elements(self.doc, t_ms)
        active = [el for el in visible
                  if el["appear_at_ms"] <= t_ms < el["appear_at_ms"] + self.windows[el["id"]]]

        # Static-period fast path: identical epoch + camera => identical frame.
        cam_key = (round(vb["x"], 1), round(vb["y"], 1), round(vb["w"], 1), round(vb["h"], 1))
        cache_key = (self._epoch_index(t_ms), cam_key, len(active),
                     tuple(el["id"] for el in visible))
        if not active and cache_key == self._cache_key and self._cached is not None:
            return self._cached

        active_ids = {el["id"] for el in active}
        seen_active = False
        interleaved = False
        for el in visible:
            if el["id"] in active_ids:
                seen_active = True
            elif seen_active:
                interleaved = True
                break
        if interleaved:
            # The fast overlay path cannot paint a stroke UNDER a finished object.
            # Rasterize these transient frames in SVG order; holds still use layers.
            svg = frame_svg(self.doc, self.infos, t_ms, self.windows, vb)
            frame = Image.open(io.BytesIO(resvg_bytes(svg, self.out_w, self.out_h))).convert("RGB")
            self.overlay_frames += 1
            self._cache_key = None
            self._cached = None
            return frame

        frame = self._compose_base({**vb, "t": t_ms})
        if active:
            self.overlay_frames += 1
            parts = [element_group(el, self.infos[el["id"]], t_ms, self.windows[el["id"]])
                     for el in active]
            svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="%.2f %.2f %.2f %.2f" '
                   'width="%d" height="%d">%s</svg>'
                   % (vb["x"], vb["y"], vb["w"], vb["h"],
                      self.out_w, self.out_h, "".join(parts)))
            ov = Image.open(io.BytesIO(resvg_bytes(svg, self.out_w, self.out_h))).convert("RGBA")
            rgba = frame.convert("RGBA")
            rgba.alpha_composite(ov)
            frame = rgba.convert("RGB")
        self._cache_key = cache_key
        self._cached = frame
        return frame


def render_video(
    doc: dict,
    out_path: str | Path,
    fps: int = 30,
    width: int = 1280,
    height: int = 720,
    duration_ms: int | None = None,
    start_ms: int = 0,
    progress_cb=None,
) -> dict:
    """Render one continuous take; returns stats {frames, wall_s, bake_fps, layer_builds}."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise FileNotFoundError("ffmpeg not found (set ATME_FFMPEG)")

    windows = build_draw_windows(doc["elements"])
    infos = {el["id"]: element_stroke_info(el, doc["seed"]) for el in doc["elements"]}
    renderer = _FrameRenderer(doc, infos, windows, width, height)
    last_appear = max(e["appear_at_ms"] for e in doc["elements"])
    activations = doc.get("board_timeline", {}).get("activations", [])
    authored_end = max((a["end_ms"] for a in activations), default=last_appear + 1800)
    duration = duration_ms if duration_ms is not None else authored_end - start_ms
    if duration <= 0:
        raise ValueError("render duration must be positive")
    total_frames = max(1, int(duration / 1000 * fps))

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y", "-hide_banner", "-v", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", "%dx%d" % (width, height), "-r", str(fps), "-i", "-",
        "-c:v", "libx264", "-preset", "superfast", "-crf", "21",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(out_path),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE)
    t_start = time.perf_counter()
    try:
        for f in range(total_frames):
            img = renderer.frame(start_ms + int(f * 1000 / fps))
            proc.stdin.write(img.tobytes())
            if progress_cb and f % fps == 0:
                progress_cb(f + 1, total_frames)
    finally:
        if proc.stdin:
            proc.stdin.close()
        rc = proc.wait()
    wall = time.perf_counter() - t_start
    err = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
    if rc != 0:
        raise RuntimeError("ffmpeg failed (%d): %s" % (rc, err[-400:]))
    stats = {"frames": total_frames, "wall_s": round(wall, 2),
             "bake_fps": round(total_frames / wall, 1),
             "layer_builds": renderer.layer_builds,
             "overlay_frames": renderer.overlay_frames,
             "start_ms": start_ms, "duration_ms": duration}
    log.info("render: %(frames)d frames in %(wall_s).1fs (%(bake_fps).1f fps)", stats)
    return stats
