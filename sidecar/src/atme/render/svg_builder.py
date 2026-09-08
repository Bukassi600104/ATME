"""LayoutDoc -> animated-capable SVG generation with hand-drawn roughness.

Determinism contract: same LayoutDoc (incl. seed) => byte-identical SVG stream. All jitter comes
from a per-element RNG seeded off the document seed + element id, never global random.

Draw-on technique (per ADR-0001): strokes carry their approximate path length; the animator sets
stroke-dasharray=L / stroke-dashoffset=L*(1-progress) so a line appears to be inked left-to-right.
"""

from __future__ import annotations

import hashlib
import math

from typing import Any
from atme.render.visibility import validate_visibility, visible_elements

INK = "#191917"
ACCENT = "#E8590C"
MUTED = "#6B6B66"


def _rng(element_id: str, doc_seed: int):
    import random

    key = "%s|%d" % (element_id, doc_seed)
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _jitter(rng, amount: float = 2.0) -> float:
    return rng.uniform(-amount, amount)


def _rough_line_path(x1, y1, x2, y2, rng, segments: int | None = None) -> tuple[str, float]:
    """Perturbed line split into segments; returns (path_d, total_length)."""
    dist = math.hypot(x2 - x1, y2 - y1)
    n = segments or max(2, int(dist // 60))
    pts = []
    for k in range(n + 1):
        tt = k / n
        px = x1 + (x2 - x1) * tt + (_jitter(rng, 1.6) if 0 < k < n else _jitter(rng, 1.0))
        py = y1 + (y2 - y1) * tt + (_jitter(rng, 1.6) if 0 < k < n else _jitter(rng, 1.0))
        pts.append((px, py))
    d = "M " + " L ".join("%.1f %.1f" % p for p in pts)
    length = sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) for i in range(len(pts) - 1))
    return d, length


def _rect_paths(el: dict, rng) -> list[tuple[str, float]]:
    x, y, w, h = el["x"], el["y"], el["width"], el["height"]
    corners = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    paths = []
    for i in range(4):
        x1, y1 = corners[i]
        x2, y2 = corners[(i + 1) % 4]
        # overshoot slightly like a real hand-drawn corner
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy) or 1.0
        ox, oy = x2 + dx / L * rng.uniform(2, 7), y2 + dy / L * rng.uniform(2, 7)
        d, ln = _rough_line_path(x1, y1, ox, oy, rng, segments=max(2, int(L // 55)))
        paths.append((d, ln))
    return paths


def _hachure(el: dict, rng) -> str:
    """Cheap hachure fill: diagonal strokes inside the box, drawn instantly under the outline."""
    x, y, w, h = el["x"], el["y"], el["width"], el["height"]
    step = 14
    parts = []
    n = int((w + h) // step)
    for i in range(1, max(1, n)):
        s = i * step
        x1 = x + max(0.0, s - h)
        y1 = y + min(s, h)
        x2 = x + min(s, w)
        y2 = y + max(0.0, s - w)
        if x2 - x1 < 4 or y2 - y1 < 4:
            continue
        parts.append(
            '<path d="M %.1f %.1f L %.1f %.1f" stroke="%s" stroke-width="1" opacity="0.5" fill="none"/>'
            % (x1, y1, x2, y2, MUTED)
        )
    return "".join(parts)


def _arrow(el: dict, rng) -> tuple[str, float]:
    sx, sy, ex, ey = el["start"]["x"], el["start"]["y"], el["end"]["x"], el["end"]["y"]
    mx, my = (sx + ex) / 2 + _jitter(rng, 10), (sy + ey) / 2 + _jitter(rng, 10)
    d = "M %.1f %.1f Q %.1f %.1f %.1f %.1f" % (sx, sy, mx, my, ex, ey)
    base = math.hypot(ex - sx, ey - sy)
    length = base * 1.08 + math.hypot(mx - sx, my - sy) * 0.4
    head_len = 12.0
    ang = math.atan2(ey - my, ex - mx)
    hx1, hy1 = ex - head_len * math.cos(ang - 0.45), ey - head_len * math.sin(ang - 0.45)
    hx2, hy2 = ex - head_len * math.cos(ang + 0.45), ey - head_len * math.sin(ang + 0.45)
    d += " M %.1f %.1f L %.1f %.1f M %.1f %.1f L %.1f %.1f" % (hx1, hy1, ex, ey, hx2, hy2, ex, ey)
    return d, length + head_len * 2


def element_stroke_info(el: dict, doc_seed: int) -> dict:
    """Precompute per-element path data + lengths (stable across frames)."""
    rng = _rng(el["id"], doc_seed)
    etype = el["type"]
    if etype == "rectangle":
        paths = _rect_paths(el, rng)
        return {"paths": [p for p, _l in paths], "length": sum(l for _p, l in paths),
                "under": _hachure(el, rng) if el.get("fillStyle", "hachure") == "hachure" else ""}
    if etype == "arrow":
        d, length = _arrow(el, rng)
        return {"paths": [d], "length": length, "under": ""}
    return {"paths": [], "length": 0.0, "under": ""}  # text handled separately


def element_group(el: dict, info: dict, t_ms: int, draw_ms: int) -> str:
    """SVG fragment for one element at time t_ms given its appear_at_ms/draw window."""
    appear = el["appear_at_ms"]
    if t_ms < appear:
        return ""
    action = el.get("enter_action", "draw")
    if action not in ("draw", "reveal"):
        raise ValueError("unsupported enter_action: %s" % action)
    if action == "reveal":
        draw_ms = 0
    color = {"ink": INK, "accent": ACCENT, "muted": MUTED}.get(el.get("stroke", "ink"), INK)

    if el["type"] == "evidence_image":
        from atme.render.evidence import validate_png
        validate_png(el["png_base64"], el["sha256"])
        return ('<image x="%d" y="%d" width="%d" height="%d" '
                'preserveAspectRatio="xMidYMid meet" href="data:image/png;base64,%s"/>'
                % (el["x"], el["y"], el["width"], el["height"], el["png_base64"]))

    if el["type"] == "text":
        size = {"s": 20, "m": 28, "l": 44}.get(el.get("size", "m"), 28)
        progress = 1.0 if draw_ms <= 0 else min(1.0, (t_ms - appear) / draw_ms)
        opacity = 0.15 + 0.85 * progress
        return (
            '<text x="%d" y="%d" font-family="Segoe Print, Comic Sans MS, cursive" '
            'font-size="%d" fill="%s" opacity="%.2f">%s</text>'
            % (el["x"], el["y"] + size, size, color, opacity, _escape(el["text"]))
        )

    progress = 1.0 if draw_ms <= 0 else min(1.0, (t_ms - appear) / draw_ms)
    parts = []
    if info.get("under"):
        parts.append(info["under"])
    dash = ""
    if progress < 1.0:
        dash = ' stroke-dasharray="%.1f" stroke-dashoffset="%.1f"' % (info["length"], info["length"] * (1 - progress))
    for d in info["paths"]:
        parts.append(
            '<path d="%s" stroke="%s" stroke-width="2.4" fill="none" stroke-linecap="round"%s/>'
            % (d, color, dash)
        )
    label = el.get("label")
    if label and progress > 0.55:
        lx = el.get("x", 0) + el.get("width", 0) / 2
        ly = el.get("y", 0) + el.get("height", 0) / 2 + 6
        parts.append(
            '<text x="%.0f" y="%.0f" text-anchor="middle" font-family="Segoe Print, Comic Sans MS, cursive" '
            'font-size="24" fill="%s">%s</text>' % (lx, ly, color, _escape(label))
        )
    return "".join(parts)


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def frame_svg(doc: dict, infos: dict, t_ms: int, draw_windows: dict, viewbox: dict) -> str:
    """Complete SVG for one frame restricted to the camera viewBox."""
    validate_visibility(doc)
    body = []
    for el in visible_elements(doc, t_ms):
        frag = element_group(el, infos[el["id"]], t_ms, draw_windows.get(el["id"], 700))
        if frag:
            body.append(frag)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="%.1f %.1f %.1f %.1f" '
        'width="%d" height="%d">'
        '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#FAF9F5"/>%s</svg>'
        % (
            viewbox["x"], viewbox["y"], viewbox["w"], viewbox["h"],
            viewbox["out_w"], viewbox["out_h"],
            viewbox["x"], viewbox["y"], viewbox["w"], viewbox["h"],
            "".join(body),
        )
    )
