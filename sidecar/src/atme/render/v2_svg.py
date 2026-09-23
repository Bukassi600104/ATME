"""Fail-closed Paper & Ink SVG compositor for the first v2 drawing primitives.

The output is a frame artifact, not a project preview/export entry point. A
layout containing any unimplemented visual type is rejected in full, even if
that object is hidden at the requested timestamp.
"""

from __future__ import annotations

import hashlib
import html
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import regex
from PIL import ImageFont

from atme.render.style_bundle import (
    _font_css,
    resolve_contract_bundle,
    verified_asset_svg,
)
from atme.render.v2_state import FrameObject, evaluate_frame
from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    MarkObject,
    ResolvedVisualTimelineV2,
    TargetAction,
    TextObject,
    VisualObject,
)


class UnsupportedVisualObject(ValueError):
    """A scene object has no faithful v2 drawing implementation."""


SUPPORTED_MARKS = frozenset({"line", "rectangle", "rounded_rectangle", "ellipse", "polygon"})
SUPPORTED_TEXT = frozenset({"text", "list"})
SUPPORTED_REGISTRY_VISUALS = {
    "icon": frozenset({"people", "gestures", "devices", "documents", "networks",
                       "charts", "technical-frames", "abstract-metaphors"}),
    "pictogram": frozenset({"people", "gestures", "devices", "documents", "networks",
                            "charts", "technical-frames", "abstract-metaphors"}),
    "character": frozenset({"people"}),
    "device": frozenset({"devices"}),
    "document": frozenset({"documents"}),
    "chart": frozenset({"charts"}),
    "terminal": frozenset({"technical-frames"}),
}


@dataclass(frozen=True)
class SVGFrame:
    at_ms: int
    width: int
    height: int
    svg: str


@dataclass(frozen=True)
class PNGFrame:
    at_ms: int
    width: int
    height: int
    png: bytes


def _n(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".") if value else "0"


def _xml_escape(value: str) -> str:
    if any(not (ord(char) in (9, 10, 13) or 32 <= ord(char) <= 0xD7FF
                or 0xE000 <= ord(char) <= 0xFFFD or 0x10000 <= ord(char) <= 0x10FFFF)
           for char in value):
        raise UnsupportedVisualObject("visual text or ID contains an invalid XML character")
    return html.escape(value, quote=True)


def _clip_id(object_id: str) -> str:
    return "clip-" + hashlib.sha256(object_id.encode("utf-8")).hexdigest()


@lru_cache(maxsize=32)
def _font(path: str, size: int):
    return ImageFont.truetype(path, size)


def _color(token: str | None, colors: dict[str, str], *, default: str) -> str:
    if token is None:
        return default
    semantic = {
        "ink.primary": "ink", "ink.muted": "muted", "ink.accent": "accent",
        "surface.paper": "paper", "surface.raised": "paper",
        "surface.accent": "accent-soft", "attention": "attention",
        "text.heading": "ink", "text.body": "ink", "text.muted": "muted",
        "text.accent": "accent", "text.label": "ink",
    }
    key = semantic.get(token, token)
    if key not in colors:
        raise UnsupportedVisualObject(f"unknown Paper & Ink style token: {token}")
    return colors[key]


def _shape(obj: MarkObject, stroke: str, fill: str, weight: float,
           draw_fraction: float | None = None) -> str:
    bounds = obj.geometry.bounds
    if obj.object_type != "line" and obj.object_type != "polygon" and obj.geometry.points:
        raise UnsupportedVisualObject(f"{obj.object_type} {obj.object_id} has ignored geometry points")
    if obj.object_type != "rounded_rectangle" and obj.geometry.corner_radius is not None:
        raise UnsupportedVisualObject(f"{obj.object_type} {obj.object_id} has ignored corner radius")
    if obj.object_type == "rounded_rectangle" and not obj.geometry.corner_radius:
        raise UnsupportedVisualObject(f"rounded rectangle {obj.object_id} requires a positive corner radius")
    if (obj.object_type == "rounded_rectangle"
            and obj.geometry.corner_radius > min(bounds.width, bounds.height) / 2):
        raise UnsupportedVisualObject(f"rounded rectangle {obj.object_id} radius exceeds its bounds")
    if obj.object_type == "line" and fill != "none":
        raise UnsupportedVisualObject(f"line {obj.object_id} cannot use a fill")
    x, y, w, h = (bounds.x, bounds.y, bounds.width, bounds.height)
    if any(not (x <= point.x <= x + w and y <= point.y <= y + h)
           for point in obj.geometry.points):
        raise UnsupportedVisualObject(f"mark {obj.object_id} points exceed authored bounds")
    if obj.object_type == "polygon" and len(obj.geometry.points) < 3:
        raise UnsupportedVisualObject(f"polygon {obj.object_id} requires at least three points")
    if draw_fraction is not None and draw_fraction < 1:
        if obj.object_type == "line":
            if obj.geometry.points:
                a, b = obj.geometry.points
                length = math.hypot(b.x - a.x, b.y - a.y)
            else:
                length = math.hypot(w, h)
        elif obj.object_type == "rectangle":
            length = 2 * (w + h)
        elif obj.object_type == "rounded_rectangle":
            radius = obj.geometry.corner_radius
            length = 2 * (w + h - 4 * radius) + 2 * math.pi * radius
        elif obj.object_type == "ellipse":
            a, b = w / 2, h / 2
            length = math.pi * (3 * (a + b) - math.sqrt((3 * a + b) * (a + 3 * b)))
        else:
            points = obj.geometry.points
            length = sum(math.hypot(b.x - a.x, b.y - a.y)
                         for a, b in zip(points, [*points[1:], points[0]]))
        if length <= 0:
            raise UnsupportedVisualObject(f"draw path {obj.object_id} has zero length")
        fill = "none"
        draw_attributes = (f' stroke-dasharray="{_n(length)} {_n(length)}" '
                           f'stroke-dashoffset="{_n(length * (1 - draw_fraction))}"')
    else:
        draw_attributes = ""
    attributes = (f'fill="{fill}" stroke="{stroke}" stroke-width="{_n(weight)}" '
                  f'stroke-linecap="round" stroke-linejoin="round"{draw_attributes}')
    if obj.object_type == "line":
        if obj.geometry.points:
            if len(obj.geometry.points) != 2:
                raise UnsupportedVisualObject(f"line {obj.object_id} requires exactly two points")
            a, b = obj.geometry.points
            x1, y1, x2, y2 = a.x, a.y, b.x, b.y
        else:
            x1, y1, x2, y2 = x, y, x + w, y + h
        return (f'<line x1="{_n(x1)}" y1="{_n(y1)}" x2="{_n(x2)}" '
                f'y2="{_n(y2)}" {attributes}/>')
    if obj.object_type in {"rectangle", "rounded_rectangle"}:
        radius = (obj.geometry.corner_radius or 0) if obj.object_type == "rounded_rectangle" else 0
        return (f'<rect x="{_n(x)}" y="{_n(y)}" width="{_n(w)}" height="{_n(h)}" '
                f'rx="{_n(radius)}" {attributes}/>')
    if obj.object_type == "ellipse":
        return (f'<ellipse cx="{_n(x + w / 2)}" cy="{_n(y + h / 2)}" '
                f'rx="{_n(w / 2)}" ry="{_n(h / 2)}" {attributes}/>')
    if obj.object_type == "polygon":
        points = " ".join(f"{_n(p.x)},{_n(p.y)}" for p in obj.geometry.points)
        return f'<polygon points="{points}" {attributes}/>'
    raise UnsupportedVisualObject(f"unimplemented mark type: {obj.object_type}")


def _text(obj: TextObject, color: str, font_family: str, font_weight: int, font_size: float,
          line_height: float, max_characters: int, font_path: Path,
          write_fraction: float | None = None) -> str:
    bounds = obj.geometry.bounds
    lines = obj.text.splitlines()
    if obj.object_type == "list":
        if not obj.items:
            raise UnsupportedVisualObject(f"list {obj.object_id} has no items")
        lines = [obj.text, *(f"• {item}" for item in obj.items)]
    if any(len(line) > max_characters for line in lines):
        raise UnsupportedVisualObject(f"text {obj.object_id} requires authored line breaks")
    if len(lines) * font_size * line_height > bounds.height:
        raise UnsupportedVisualObject(f"text {obj.object_id} exceeds authored bounds")
    measuring_font = _font(str(font_path), max(1, math.ceil(font_size)))
    if any(measuring_font.getlength(line) > bounds.width for line in lines):
        raise UnsupportedVisualObject(f"text {obj.object_id} exceeds authored width")
    if write_fraction is not None and write_fraction < 1:
        graphemes = regex.findall(r"\X", "\n".join(lines))
        visible = math.floor(len(graphemes) * write_fraction)
        lines = "".join(graphemes[:visible]).split("\n")
    x = _n(bounds.x)
    y = _n(bounds.y + font_size)
    spans = "".join(
        f'<tspan x="{x}" dy="{_n(0 if index == 0 else font_size * line_height)}">'
        f'{_xml_escape(line)}</tspan>'
        for index, line in enumerate(lines)
    )
    return (f'<text x="{x}" y="{y}" fill="{color}" font-family="{_xml_escape(font_family)}" '
            f'font-weight="{font_weight}" font-size="{_n(font_size)}" '
            f'xml:space="preserve">{spans}</text>')


def _text_role(obj: TextObject, style):
    token = obj.style.text
    roles = {
        "text.heading": style.typography.title,
        "text.label": style.typography.label,
        "text.body": style.typography.body,
        "text.muted": style.typography.body,
        "text.accent": style.typography.body,
    }
    if token not in roles:
        raise UnsupportedVisualObject(f"text {obj.object_id} has no explicit typography role: {token}")
    if obj.object_type == "list" and token != "text.body":
        raise UnsupportedVisualObject(f"list {obj.object_id} requires body typography")
    return roles[token]


def _registry_visual(obj: VisualObject) -> str:
    if not obj.variant:
        raise UnsupportedVisualObject(f"v2 visual {obj.object_id} must select an original registry variant")
    asset, inner = verified_asset_svg(obj.variant)
    allowed = SUPPORTED_REGISTRY_VISUALS[obj.object_type]
    if asset.family not in allowed:
        raise UnsupportedVisualObject(
            f"v2 {obj.object_type} {obj.object_id} cannot use {asset.family} asset {asset.id}"
        )
    bounds = obj.geometry.bounds
    view_width, view_height = asset.view_box[2:4]
    return (f'<svg x="{_n(bounds.x)}" y="{_n(bounds.y)}" '
            f'width="{_n(bounds.width)}" height="{_n(bounds.height)}" '
            f'viewBox="0 0 {view_width} {view_height}" preserveAspectRatio="xMidYMid meet">'
            f'{inner}</svg>')


def _object_markup(obj: MarkObject | TextObject | VisualObject, state: FrameObject, style,
                   root: Path, scale: float, active_verb: str | None) -> str:
    if not state.visible or state.opacity <= 0 or state.reveal_fraction <= 0:
        return ""
    t = state.transform
    bounds = obj.geometry.bounds
    origin_x = bounds.x + bounds.width * t.origin.x
    origin_y = bounds.y + bounds.height * t.origin.y
    transform = (f'translate({_n(t.position.x)} {_n(t.position.y)}) '
                 f'translate({_n(origin_x)} {_n(origin_y)}) '
                 f'rotate({_n(t.rotation_degrees)}) scale({_n(t.scale_x)} {_n(t.scale_y)}) '
                 f'translate({_n(-origin_x)} {_n(-origin_y)})')
    if isinstance(obj, MarkObject):
        stroke = _color(obj.style.stroke, style.colors, default=style.colors["ink"])
        fill = _color(obj.style.fill, style.colors, default="none")
        inner = _shape(obj, stroke, fill, style.strokes.regular_px * scale,
                       state.reveal_fraction if active_verb == "draw" else None)
    elif isinstance(obj, TextObject):
        color = _color(obj.style.text, style.colors, default=style.colors["ink"])
        role = _text_role(obj, style)
        font = next(font for font in style.fonts if font.id == role.font_id)
        inner = _text(obj, color, font.family, font.weight, role.size_px * scale, role.line_height,
                      role.max_characters_per_line, root / font.file,
                      state.reveal_fraction if active_verb == "write" else None)
    else:
        inner = _registry_visual(obj)
    # Reveal is clipped in canvas coordinates inside the transformed local group.
    clip = ""
    if state.reveal_fraction < 1 and active_verb not in {"draw", "write"}:
        clip = f' clip-path="url(#{_clip_id(obj.object_id)})"'
    return (f'<g data-object-id="{_xml_escape(obj.object_id)}" '
            f'transform="{transform}" opacity="{_n(state.opacity)}"{clip}>{inner}</g>')


def _preflight_object(obj: MarkObject | TextObject | VisualObject,
                      style, root: Path, scale: float) -> None:
    _xml_escape(obj.object_id)
    if obj.parent_id or obj.clip_id or obj.style.effect or obj.asset_id:
        raise UnsupportedVisualObject(
            f"v2 object {obj.object_id} requires unimplemented hierarchy, clip, effect, or asset composition"
        )
    if isinstance(obj, MarkObject):
        if obj.path_data or obj.style.text:
            raise UnsupportedVisualObject(f"v2 mark {obj.object_id} has unimplemented path or text styling")
        stroke = _color(obj.style.stroke, style.colors, default=style.colors["ink"])
        fill = _color(obj.style.fill, style.colors, default="none")
        _shape(obj, stroke, fill, style.strokes.regular_px * scale)
    elif isinstance(obj, TextObject):
        if (obj.style.stroke or obj.style.fill or obj.geometry.points
                or obj.geometry.corner_radius is not None
                or obj.items and obj.object_type != "list"):
            raise UnsupportedVisualObject(f"v2 text {obj.object_id} has unsupported styling or geometry")
        color = _color(obj.style.text, style.colors, default=style.colors["ink"])
        role = _text_role(obj, style)
        font = next(font for font in style.fonts if font.id == role.font_id)
        _text(obj, color, font.family, font.weight, role.size_px * scale, role.line_height,
              role.max_characters_per_line, root / font.file)
    else:
        if (obj.style.stroke or obj.style.fill or obj.style.text
                or obj.geometry.points or obj.geometry.corner_radius is not None):
            raise UnsupportedVisualObject(
                f"v2 visual {obj.object_id} cannot override pinned illustration style or geometry"
            )
        _registry_visual(obj)


def compose_svg_frame(layout_document: dict, timeline_document: dict, at_ms: int) -> SVGFrame:
    """Draw supported objects in deterministic z order; never substitute boxes."""
    snapshot = evaluate_frame(layout_document, timeline_document, at_ms)
    layout = ExecutableLayoutV2.model_validate(layout_document)
    timeline = ResolvedVisualTimelineV2.model_validate(timeline_document)
    objects = {obj.object_id: obj for obj in layout.objects}
    for resolved in timeline.actions:
        action = resolved.action
        if action.verb == "progressive_reveal":
            raise UnsupportedVisualObject(
                f"v2 action {action.action_id} requires an authored ordered-child reveal"
            )
        if isinstance(action, TargetAction) and action.verb in {"draw", "write"}:
            compatible = MarkObject if action.verb == "draw" else TextObject
            if any(not isinstance(objects[target], compatible) for target in action.target_ids):
                raise UnsupportedVisualObject(
                    f"v2 {action.verb} action {action.action_id} targets an incompatible object type"
                )
            if action.verb == "draw":
                for target in action.target_ids:
                    mark = objects[target]
                    _shape(mark, "#000000", "none", 1, draw_fraction=0.5)
    unsupported = [obj for obj in layout.objects
                   if not (isinstance(obj, MarkObject) and obj.object_type in SUPPORTED_MARKS
                           or isinstance(obj, TextObject) and obj.object_type in SUPPORTED_TEXT
                           or isinstance(obj, VisualObject)
                           and obj.object_type in SUPPORTED_REGISTRY_VISUALS)]
    if unsupported:
        first = unsupported[0]
        raise UnsupportedVisualObject(
            f"v2 object {first.object_id} uses {first.object_type}, which has no SVG implementation"
        )
    style, _, root = resolve_contract_bundle(layout.style_system_version,
                                            layout.asset_registry_version)
    profile_key = "landscape-16:9" if layout.output_profile.profile_id == "LONG_FORM_16_9" else "portrait-9:16"
    design = style.aspects[profile_key]
    scale_x = layout.output_profile.width / design.width
    scale_y = layout.output_profile.height / design.height
    if abs(scale_x - scale_y) > 1e-6:
        raise UnsupportedVisualObject("output profile cannot uniformly scale Paper & Ink design tokens")
    for obj in layout.objects:
        _preflight_object(obj, style, root, scale_x)
    active_verbs = {
        target: resolved.action.verb
        for resolved in timeline.actions
        if isinstance(resolved.action, TargetAction)
        and resolved.action.verb in {"draw", "write"}
        and resolved.start_ms <= at_ms < resolved.end_ms
        for target in resolved.action.target_ids
    }
    definitions = []
    body = [(f'<rect x="{_n(layout.canvas.x)}" y="{_n(layout.canvas.y)}" '
             f'width="{_n(layout.canvas.width)}" height="{_n(layout.canvas.height)}" '
             f'fill="{style.colors["paper"]}"/>')]
    for state in snapshot.objects:
        obj = objects[state.object_id]
        if 0 < state.reveal_fraction < 1 and active_verbs.get(state.object_id) not in {"draw", "write"}:
            bounds = obj.geometry.bounds
            definitions.append(
                f'<clipPath id="{_clip_id(obj.object_id)}">'
                f'<rect x="{_n(bounds.x)}" y="{_n(bounds.y)}" '
                f'width="{_n(bounds.width * state.reveal_fraction)}" '
                f'height="{_n(bounds.height)}"/></clipPath>'
            )
        body.append(_object_markup(obj, state, style, root, scale_x,
                                   active_verbs.get(state.object_id)))
    width, height = layout.output_profile.width, layout.output_profile.height
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
           f'viewBox="{_n(layout.canvas.x)} {_n(layout.canvas.y)} {width} {height}">'
           f'<defs><style>{_font_css(style, root)}</style>'
           f'{"".join(definitions)}</defs>'
           f'{"".join(body)}</svg>')
    return SVGFrame(at_ms=at_ms, width=width, height=height, svg=svg)


def compose_png_frame(layout_document: dict, timeline_document: dict, at_ms: int) -> PNGFrame:
    """Rasterize a supported frame with verified, pinned fonts and no system-font fallback."""
    import resvg_py

    frame = compose_svg_frame(layout_document, timeline_document, at_ms)
    style, _, root = resolve_contract_bundle(layout_document["style_system_version"],
                                             layout_document["asset_registry_version"])
    font_files = [str(root / font.file) for font in style.fonts]
    png = bytes(resvg_py.svg_to_bytes(
        svg_string=frame.svg, width=frame.width, height=frame.height,
        font_files=font_files, skip_system_fonts=True,
    ))
    return PNGFrame(at_ms=at_ms, width=frame.width, height=frame.height, png=png)
