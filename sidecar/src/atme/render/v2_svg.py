"""Fail-closed Paper & Ink SVG compositor for the first v2 drawing primitives.

The output is a frame artifact, not a project preview/export entry point. A
layout containing any unimplemented visual type is rejected in full, even if
that object is hidden at the requested timestamp.
"""

from __future__ import annotations

import base64
import hashlib
import html
import io
import math
from dataclasses import dataclass
from functools import lru_cache
from itertools import pairwise
from pathlib import Path

import regex
from PIL import Image, ImageFont

from atme.project_assets import VerifiedEvidenceBytes
from atme.render.style_bundle import (
    _font_css,
    resolve_contract_bundle,
    verified_asset_svg,
)
from atme.render.v2_connector import (
    UnsupportedConnector,
    connector_route,
    validate_static_arrow,
)
from atme.render.v2_emphasis import (
    SUPPORTED_HIGHLIGHT_MARKS,
    SUPPORTED_HIGHLIGHT_TEXT,
    UnsupportedEmphasis,
    cross_out_paths,
    emphasis_path,
)
from atme.render.v2_list import UnsupportedOrderedList, validate_ordered_list
from atme.render.v2_mask import UnsupportedMask, mask_source_region
from atme.render.v2_morph import geometry_object
from atme.render.v2_path import (
    MAX_COORDINATE,
    MAX_STROKE_LENGTH,
    InvalidFreehandPath,
    parse_freehand_path,
)
from atme.render.v2_raster import UnsupportedProjectPNG, canonical_png
from atme.render.v2_state import FrameObject, FrameSnapshot, evaluate_frame
from atme.render.v2_world import transform_svg
from atme.store.contracts_v2 import (
    ConnectionAction,
    ConnectorObject,
    ContainerObject,
    ExecutableLayoutV2,
    MarkObject,
    MaskContainer,
    ResolvedVisualTimelineV2,
    TargetAction,
    TextObject,
    TransformAction,
    VisualObject,
    _annotation_phase_windows,
)


class UnsupportedVisualObject(ValueError):
    """A scene object has no faithful v2 drawing implementation."""


SUPPORTED_MARKS = SUPPORTED_HIGHLIGHT_MARKS
SUPPORTED_TEXT = SUPPORTED_HIGHLIGHT_TEXT
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


def _container_clip_id(object_id: str) -> str:
    return "clip-container-" + hashlib.sha256(object_id.encode("utf-8")).hexdigest()


def _container_mask_id(object_id: str) -> str:
    return "mask-container-" + hashlib.sha256(object_id.encode("utf-8")).hexdigest()


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


def _emphasis_path(obj: MarkObject):
    try:
        return emphasis_path(obj.geometry.bounds, obj.object_type)
    except UnsupportedEmphasis as exc:
        raise UnsupportedVisualObject(
            f"{obj.object_type} {obj.object_id} exceeds supported authored bounds"
        ) from exc


def _shape(obj: MarkObject, stroke: str, fill: str, weight: float,
           draw_fraction: float | None = None) -> str:
    bounds = obj.geometry.bounds
    if obj.object_type not in {"freehand", "line", "polygon"} and obj.geometry.points:
        raise UnsupportedVisualObject(f"{obj.object_type} {obj.object_id} has ignored geometry points")
    if obj.object_type != "rounded_rectangle" and obj.geometry.corner_radius is not None:
        raise UnsupportedVisualObject(f"{obj.object_type} {obj.object_id} has ignored corner radius")
    if obj.object_type == "rounded_rectangle" and not obj.geometry.corner_radius:
        raise UnsupportedVisualObject(f"rounded rectangle {obj.object_id} requires a positive corner radius")
    if (obj.object_type == "rounded_rectangle"
            and obj.geometry.corner_radius > min(bounds.width, bounds.height) / 2):
        raise UnsupportedVisualObject(f"rounded rectangle {obj.object_id} radius exceeds its bounds")
    if obj.object_type in {"freehand", "line", "underline", "highlight"} and fill != "none":
        raise UnsupportedVisualObject(f"{obj.object_type} {obj.object_id} cannot use a fill")
    x, y, w, h = (bounds.x, bounds.y, bounds.width, bounds.height)
    if any(not (x <= point.x <= x + w and y <= point.y <= y + h)
           for point in obj.geometry.points):
        raise UnsupportedVisualObject(f"mark {obj.object_id} points exceed authored bounds")
    if obj.object_type == "polygon" and len(obj.geometry.points) < 3:
        raise UnsupportedVisualObject(f"polygon {obj.object_id} requires at least three points")
    if obj.object_type == "line" and obj.geometry.points and len(obj.geometry.points) != 2:
        raise UnsupportedVisualObject(f"line {obj.object_id} requires exactly two points")
    freehand = None
    emphasis = _emphasis_path(obj) if obj.object_type in {"underline", "highlight"} else None
    if obj.object_type == "freehand":
        if obj.path_data and obj.geometry.points:
            raise UnsupportedVisualObject(f"freehand {obj.object_id} cannot mix path data and points")
        if obj.path_data:
            try:
                freehand = parse_freehand_path(obj.path_data, bounds)
            except InvalidFreehandPath as exc:
                raise UnsupportedVisualObject(f"freehand {obj.object_id}: {exc}") from exc
            freehand_length = freehand.length
        else:
            if len(obj.geometry.points) < 2:
                raise UnsupportedVisualObject(f"freehand {obj.object_id} requires a path or two points")
            if len(obj.geometry.points) > 257:
                raise UnsupportedVisualObject(f"freehand {obj.object_id} exceeds 256 line segments")
            if any(abs(value) > MAX_COORDINATE for point in obj.geometry.points
                   for value in (point.x, point.y)):
                raise UnsupportedVisualObject(f"freehand {obj.object_id} coordinates exceed the supported range")
            rendered_points = [(float(_n(point.x)), float(_n(point.y)))
                               for point in obj.geometry.points]
            freehand_length = sum(math.dist(a, b) for a, b in pairwise(rendered_points))
            if not math.isfinite(freehand_length) or freehand_length > MAX_STROKE_LENGTH:
                raise UnsupportedVisualObject(f"freehand {obj.object_id} length exceeds the supported range")
        if freehand_length <= 0:
            raise UnsupportedVisualObject(f"freehand {obj.object_id} has zero length")
    if draw_fraction is not None and draw_fraction < 1:
        if emphasis:
            length = emphasis.length
        elif obj.object_type == "freehand":
            length = freehand_length
        elif obj.object_type == "line":
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
    if obj.object_type == "freehand":
        if freehand:
            return f'<path d="{freehand.svg_d}" {attributes}/>'
        points = " ".join(f"{_n(p.x)},{_n(p.y)}" for p in obj.geometry.points)
        return f'<polyline points="{points}" {attributes}/>'
    if emphasis:
        return f'<path d="{emphasis.svg_d}" {attributes}/>'
    if obj.object_type == "line":
        if obj.geometry.points:
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
          write_fraction: float | None = None,
          progressive_fraction: float | None = None) -> str:
    bounds = obj.geometry.bounds
    lines = obj.text.splitlines()
    if obj.object_type == "list":
        try:
            validate_ordered_list(obj)
        except UnsupportedOrderedList as exc:
            raise UnsupportedVisualObject(str(exc)) from exc
        lines = [obj.text, *(f"• {item}" for item in obj.items)]
    if any(len(line) > max_characters for line in lines):
        raise UnsupportedVisualObject(f"text {obj.object_id} requires authored line breaks")
    if len(lines) * font_size * line_height > bounds.height:
        raise UnsupportedVisualObject(f"text {obj.object_id} exceeds authored bounds")
    measuring_font = _font(str(font_path), max(1, math.ceil(font_size)))
    if any(measuring_font.getlength(line) > bounds.width for line in lines):
        raise UnsupportedVisualObject(f"text {obj.object_id} exceeds authored width")
    if progressive_fraction is not None:
        if obj.object_type != "list" or write_fraction is not None:
            raise UnsupportedVisualObject("ordered disclosure needs one authored list")
        visible_items = math.floor(len(obj.items) * progressive_fraction)
        lines = lines[:1 + visible_items]
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


def _connector_shape(obj: ConnectorObject, objects: dict, states: dict,
                     stroke: str, weight: float, draw_fraction: float | None) -> str:
    try:
        geometry = connector_route(obj, objects, states, weight)
    except UnsupportedConnector as exc:
        raise UnsupportedVisualObject(str(exc)) from exc
    start, end = geometry.points[0], geometry.points[-1]
    length = geometry.length
    left, right = geometry.head
    if obj.routing == "straight":
        path = f'M {_n(start[0])} {_n(start[1])} L {_n(end[0])} {_n(end[1])}'
    elif obj.routing == "elbow":
        bend = geometry.points[1]
        path = (f'M {_n(start[0])} {_n(start[1])} L {_n(bend[0])} {_n(bend[1])} '
                f'L {_n(end[0])} {_n(end[1])}')
    else:
        bend = geometry.points[1]
        path = (f'M {_n(start[0])} {_n(start[1])} Q {_n(bend[0])} {_n(bend[1])} '
                f'{_n(end[0])} {_n(end[1])}')
    dash = (f' stroke-dasharray="{_n(length)} {_n(length)}" '
            f'stroke-dashoffset="{_n(length * (1 - draw_fraction))}"'
            if draw_fraction is not None and draw_fraction < 1 else "")
    arrowhead = "" if draw_fraction is not None and draw_fraction < 1 else (
        f'<polygon points="{_n(end[0])},{_n(end[1])} '
        f'{_n(left[0])},{_n(left[1])} {_n(right[0])},{_n(right[1])}" fill="{stroke}"/>')
    return (f'<path d="{path}" fill="none" stroke="{stroke}" stroke-width="{_n(weight)}" '
            f'stroke-linecap="round" stroke-linejoin="round"{dash}/>{arrowhead}')


def _object_transform(obj, state: FrameObject) -> str:
    return transform_svg(obj, state.transform)


@lru_cache(maxsize=8)
def _evidence_crop_png(payload: bytes, crop: tuple[int, int, int, int]) -> bytes:
    """Make an exact source-pixel crop from the already canonical RGBA source."""
    with Image.open(io.BytesIO(payload)) as image:
        result = image.crop(crop)
        output = io.BytesIO()
        result.save(output, format="PNG", optimize=False, compress_level=9)
    encoded = output.getvalue()
    if len(encoded) > 16 * 1024 * 1024:
        raise UnsupportedVisualObject("evidence crop exceeds bounded PNG output")
    return encoded


def _evidence_text(value: str, font_file: Path, font_size: float, max_width: float) -> str:
    if len(value) > 120:
        raise UnsupportedVisualObject("evidence attribution or annotation is too long")
    _xml_escape(value)
    font = ImageFont.truetype(str(font_file), max(1, round(font_size)))
    if font.getlength(value) > max_width:
        raise UnsupportedVisualObject("evidence attribution or annotation does not fit its frame")
    return _xml_escape(value)


def _evidence_markup(obj: VisualObject, state: FrameObject, style, root: Path,
                     scale: float, raster, treatment) -> str:
    """Render a bounded evidence card, never a fabricated substitute image."""
    bounds = obj.geometry.bounds
    intent = treatment.intent
    if intent.annotation is not None and intent.annotation_target_id != obj.object_id:
        raise UnsupportedVisualObject(
            f"evidence {obj.object_id} needs a supported self-anchored annotation"
        )
    if bounds.width < 180 * scale or bounds.height < 160 * scale:
        raise UnsupportedVisualObject(f"evidence {obj.object_id} is too small to remain readable")
    caption_role = style.typography.caption
    caption_font = next(font for font in style.fonts if font.id == caption_role.font_id)
    label_height = 34 * scale
    annotation_height = 34 * scale if intent.annotation is not None else 0
    gap = 4 * scale
    image_height = bounds.height - label_height - annotation_height - gap
    if image_height < 90 * scale:
        raise UnsupportedVisualObject(f"evidence {obj.object_id} has no readable source image area")
    crop = intent.crop
    crop_box = (int(crop.x), int(crop.y), int(crop.x + crop.width), int(crop.y + crop.height))
    encoded = base64.b64encode(_evidence_crop_png(raster.payload, crop_box)).decode("ascii")
    image_scale = min(bounds.width / crop.width, image_height / crop.height)
    image_width = crop.width * image_scale
    shown_height = crop.height * image_scale
    image_x = bounds.x + (bounds.width - image_width) / 2
    image_y = bounds.y + (image_height - shown_height) / 2
    focus = intent.focus_region
    focus_x = image_x + (focus.x - crop.x) * image_scale
    focus_y = image_y + (focus.y - crop.y) * image_scale
    focus_width = focus.width * image_scale
    focus_height = focus.height * image_scale
    margin = 10 * scale
    font_size = min(caption_role.size_px * scale, 20 * scale)
    label = _evidence_text(intent.source_label, root / caption_font.file,
                           font_size, bounds.width - 2 * margin)
    annotation = (_evidence_text(intent.annotation, root / caption_font.file,
                                  font_size, bounds.width - 2 * margin)
                  if intent.annotation is not None else None)
    ink = style.colors["ink"]
    paper = style.colors["paper"]
    accent = style.colors["attention"]
    border = _color(obj.style.stroke, style.colors, default=ink)
    backing = _color(obj.style.fill, style.colors, default=paper)
    family = _xml_escape(caption_font.family)
    radius = obj.geometry.corner_radius or 0
    clip_id = f"evidence-card-{_clip_id(obj.object_id)}"
    markup = [
        (f'<defs><clipPath id="{clip_id}" clipPathUnits="userSpaceOnUse">'
         f'<rect x="{_n(bounds.x)}" y="{_n(bounds.y)}" width="{_n(bounds.width)}" '
         f'height="{_n(bounds.height)}" rx="{_n(radius)}"/></clipPath></defs>'),
        f'<g clip-path="url(#{clip_id})">',
        (f'<rect x="{_n(bounds.x)}" y="{_n(bounds.y)}" width="{_n(bounds.width)}" '
         f'height="{_n(bounds.height)}" fill="{backing}"/>'),
        (f'<image data-evidence-crop="{_xml_escape(intent.claim_id)}" '
         f'x="{_n(image_x)}" y="{_n(image_y)}" width="{_n(image_width)}" '
         f'height="{_n(shown_height)}" preserveAspectRatio="xMidYMid meet" '
         f'href="data:image/png;base64,{encoded}"/>'),
    ]
    if intent.darkening:
        strips = (
            (image_x, image_y, image_width, focus_y - image_y),
            (image_x, focus_y + focus_height, image_width,
             image_y + shown_height - focus_y - focus_height),
            (image_x, focus_y, focus_x - image_x, focus_height),
            (focus_x + focus_width, focus_y,
             image_x + image_width - focus_x - focus_width, focus_height),
        )
        for x, y, width, height in strips:
            if width > 0 and height > 0:
                markup.append(
                    f'<rect data-evidence-darkening="outside-focus" x="{_n(x)}" y="{_n(y)}" '
                    f'width="{_n(width)}" height="{_n(height)}" fill="{ink}" '
                    f'opacity="{_n(intent.darkening)}"/>'
                )
    markup.append(
        f'<rect data-evidence-focus="{_xml_escape(intent.claim_id)}" '
        f'x="{_n(focus_x)}" y="{_n(focus_y)}" width="{_n(focus_width)}" '
        f'height="{_n(focus_height)}" fill="none" stroke="{accent}" '
        f'stroke-width="{_n(2 * scale)}"/>'
    )
    if annotation is not None:
        annotation_y = bounds.y + image_height + gap
        markup.extend((
            (f'<path data-evidence-annotation="pointer" d="M {_n(focus_x + focus_width / 2)} '
             f'{_n(focus_y + focus_height)} L {_n(bounds.x + margin)} {_n(annotation_y + annotation_height / 2)}" '
             f'fill="none" stroke="{accent}" stroke-width="{_n(2 * scale)}"/>'),
            (f'<text data-evidence-annotation="text" x="{_n(bounds.x + margin)}" '
             f'y="{_n(annotation_y + annotation_height * 0.72)}" fill="{ink}" '
             f'font-family="{family}" font-weight="{caption_font.weight}" '
             f'font-size="{_n(font_size)}">{annotation}</text>'),
        ))
    label_y = bounds.y + bounds.height - label_height
    markup.extend((
        (f'<rect x="{_n(bounds.x)}" y="{_n(label_y)}" width="{_n(bounds.width)}" '
         f'height="{_n(label_height)}" fill="{paper}"/>'),
        (f'<text data-evidence-source-label="{_xml_escape(intent.claim_id)}" '
         f'x="{_n(bounds.x + margin)}" y="{_n(label_y + label_height * 0.72)}" '
         f'fill="{ink}" font-family="{family}" font-weight="{caption_font.weight}" '
         f'font-size="{_n(font_size)}">{label}</text>'),
        '</g>',
        (f'<rect x="{_n(bounds.x)}" y="{_n(bounds.y)}" width="{_n(bounds.width)}" '
         f'height="{_n(bounds.height)}" rx="{_n(radius)}" fill="none" stroke="{border}" '
         f'stroke-width="{_n(2 * scale)}"/>'),
    ))
    return "".join(markup)


def _object_markup(obj: MarkObject | TextObject | VisualObject | ConnectorObject,
                   state: FrameObject, style, root: Path, scale: float,
                   active_verb: str | None, objects: dict, states: dict,
                   raster_images: dict, evidence_treatments: dict) -> str:
    if not state.visible or state.opacity <= 0 or state.reveal_fraction <= 0:
        return ""
    obj = geometry_object(obj, state.morph_geometry)
    transform = _object_transform(obj, state)
    bounds = obj.geometry.bounds
    if isinstance(obj, MarkObject):
        stroke = _color(obj.style.stroke, style.colors, default=style.colors[
            "attention" if obj.object_type == "highlight" else
            "accent" if obj.object_type == "underline" else "ink"
        ])
        fill = _color(obj.style.fill, style.colors, default="none")
        weight = (style.strokes.emphasis_px if obj.object_type == "highlight"
                  else style.strokes.regular_px) * scale
        if state.morph_geometry is not None:
            inner = (f'<path data-geometry-action="morph" d="{state.morph_geometry.svg_d}" '
                     f'fill="{fill}" stroke="{stroke}" stroke-width="{_n(weight)}" '
                     f'stroke-linecap="round" stroke-linejoin="round"/>')
        else:
            inner = _shape(obj, stroke, fill, weight,
                           state.reveal_fraction if active_verb == "draw" else None)
    elif isinstance(obj, TextObject):
        color = _color(obj.style.text, style.colors, default=style.colors["ink"])
        role = _text_role(obj, style)
        font = next(font for font in style.fonts if font.id == role.font_id)
        inner = _text(obj, color, font.family, font.weight, role.size_px * scale, role.line_height,
                      role.max_characters_per_line, root / font.file,
                      state.reveal_fraction if active_verb == "write" else None,
                      state.reveal_fraction if active_verb == "progressive_reveal" else None)
    elif isinstance(obj, ConnectorObject):
        stroke = _color(obj.style.stroke, style.colors, default=style.colors["ink"])
        inner = _connector_shape(obj, objects, states, stroke,
                                 style.strokes.regular_px * scale,
                                 state.reveal_fraction if active_verb in {
                                     "draw", "connect", "disconnect"
                                 } else None)
    elif isinstance(obj, VisualObject) and obj.object_type == "image":
        raster = raster_images[obj.asset_id]
        encoded = base64.b64encode(raster.payload).decode("ascii")
        inner = (f'<image x="{_n(bounds.x)}" y="{_n(bounds.y)}" '
                 f'width="{_n(bounds.width)}" height="{_n(bounds.height)}" '
                 f'preserveAspectRatio="xMidYMid meet" '
                 f'href="data:image/png;base64,{encoded}"/>')
    elif isinstance(obj, VisualObject) and obj.object_type == "evidence":
        inner = _evidence_markup(obj, state, style, root, scale,
                                 raster_images[obj.asset_id], evidence_treatments[obj.object_id])
    else:
        inner = _registry_visual(obj)
    if state.emphasis_fraction > 0:
        try:
            emphasis = emphasis_path(bounds, "highlight")
        except UnsupportedEmphasis as exc:
            raise UnsupportedVisualObject(
                f"highlight target {obj.object_id} exceeds supported authored bounds"
            ) from exc
        dash = ""
        if state.emphasis_fraction < 1:
            dash = (f' stroke-dasharray="{_n(emphasis.length)} {_n(emphasis.length)}" '
                    f'stroke-dashoffset="{_n(emphasis.length * (1 - state.emphasis_fraction))}"')
        inner += (f'<path data-attention-action="highlight" d="{emphasis.svg_d}" '
                  f'fill="none" stroke="{style.colors["attention"]}" '
                  f'stroke-width="{_n(style.strokes.emphasis_px * scale)}" '
                  f'stroke-linecap="round" stroke-linejoin="round"{dash}/>')
    if state.cross_out_fraction > 0:
        try:
            strokes = cross_out_paths(bounds)
        except UnsupportedEmphasis as exc:
            raise UnsupportedVisualObject(
                f"cross_out target {obj.object_id} exceeds supported authored bounds"
            ) from exc
        for index, stroke_path in enumerate(strokes):
            fraction = min(1.0, max(0.0, state.cross_out_fraction * 2 - index))
            if fraction <= 0:
                continue
            dash = ""
            if fraction < 1:
                dash = (f' stroke-dasharray="{_n(stroke_path.length)} {_n(stroke_path.length)}" '
                        f'stroke-dashoffset="{_n(stroke_path.length * (1 - fraction))}"')
            inner += (f'<path data-attention-action="cross_out" data-stroke="{index + 1}" '
                      f'd="{stroke_path.svg_d}" fill="none" '
                      f'stroke="{style.colors["attention"]}" '
                      f'stroke-width="{_n(style.strokes.emphasis_px * scale)}" '
                      f'stroke-linecap="round" stroke-linejoin="round"{dash}/>')
    # Reveal is clipped in canvas coordinates inside the transformed local group.
    clip = ""
    if state.reveal_fraction < 1 and active_verb not in {
        "draw", "write", "progressive_reveal", "connect", "disconnect"
    }:
        clip = f' clip-path="url(#{_clip_id(obj.object_id)})"'
    return (f'<g data-object-id="{_xml_escape(obj.object_id)}" '
            f'transform="{transform}" opacity="{_n(state.opacity)}"{clip}>{inner}</g>')


def _preflight_object(obj: MarkObject | TextObject | VisualObject | ConnectorObject,
                      style, root: Path, scale: float, objects: dict, *, annotation_pointer: bool = False) -> None:
    _xml_escape(obj.object_id)
    if (obj.clip_id or obj.style.effect
            or obj.asset_id and not (isinstance(obj, VisualObject)
                                     and obj.object_type in {"image", "evidence"})):
        raise UnsupportedVisualObject(
            f"v2 object {obj.object_id} requires unimplemented hierarchy, clip, effect, or asset composition"
        )
    if isinstance(obj, MarkObject):
        if (obj.path_data and obj.object_type != "freehand") or obj.style.text:
            raise UnsupportedVisualObject(f"v2 mark {obj.object_id} has unimplemented path or text styling")
        stroke = _color(obj.style.stroke, style.colors, default=style.colors[
            "attention" if obj.object_type == "highlight" else
            "accent" if obj.object_type == "underline" else "ink"
        ])
        fill = _color(obj.style.fill, style.colors, default="none")
        weight = (style.strokes.emphasis_px if obj.object_type == "highlight"
                  else style.strokes.regular_px) * scale
        _shape(obj, stroke, fill, weight)
    elif isinstance(obj, ConnectorObject):
        _color(obj.style.stroke, style.colors, default=style.colors["ink"])
        try:
            validate_static_arrow(obj, objects, annotation_pointer=annotation_pointer)
        except UnsupportedConnector as exc:
            raise UnsupportedVisualObject(str(exc)) from exc
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
    elif isinstance(obj, VisualObject) and obj.object_type == "image":
        if (obj.asset_id is None or obj.variant is not None
                or obj.style.stroke or obj.style.fill or obj.style.text
                or obj.geometry.points or obj.geometry.corner_radius is not None):
            raise UnsupportedVisualObject(
                f"v2 image {obj.object_id} needs unstyled full-frame asset placement"
            )
    elif isinstance(obj, VisualObject) and obj.object_type == "evidence":
        if (obj.asset_id is None or obj.variant not in {None, "annotated_crop"}
                or obj.style.text or obj.geometry.points
                or obj.geometry.corner_radius is not None and obj.geometry.corner_radius > 32 * scale):
            raise UnsupportedVisualObject(
                f"v2 evidence {obj.object_id} has unsupported styling or geometry"
            )
    else:
        if (obj.style.stroke or obj.style.fill or obj.style.text
                or obj.geometry.points or obj.geometry.corner_radius is not None):
            raise UnsupportedVisualObject(
                f"v2 visual {obj.object_id} cannot override pinned illustration style or geometry"
            )
        _registry_visual(obj)


def compose_svg_frame(layout_document: dict, timeline_document: dict, at_ms: int,
                      asset_bytes: dict[str, bytes | VerifiedEvidenceBytes] | None = None) -> SVGFrame:
    """Draw supported objects in deterministic z order; never substitute boxes."""
    snapshot = evaluate_frame(layout_document, timeline_document, at_ms)
    layout = ExecutableLayoutV2.model_validate(layout_document)
    timeline = ResolvedVisualTimelineV2.model_validate(timeline_document)
    held_frames = {
        item.action.action_id: evaluate_frame(layout_document, timeline_document, item.end_ms)
        for item in timeline.actions
        if isinstance(item.action, TargetAction) and item.action.annotation_policy is not None
        and item.action.annotation_policy.leader_connector_id is not None
    }
    return _compose_validated_svg_frame(layout, timeline, snapshot, held_frames, asset_bytes)


def _compose_validated_svg_frame(layout: ExecutableLayoutV2, timeline: ResolvedVisualTimelineV2,
                                 snapshot: FrameSnapshot, held_frames: dict[str, FrameSnapshot],
                                 asset_bytes: dict[str, bytes | VerifiedEvidenceBytes] | None = None) -> SVGFrame:
    """Pure paint from requested and held snapshots of the same proven history.

    This internal consumer does not admit an action or advertise a capability.
    Public callers obtain every snapshot through the public frame evaluator.
    """
    at_ms = snapshot.at_ms
    leader_actions = {item.action.action_id: item for item in timeline.actions
                      if isinstance(item.action, TargetAction) and item.action.annotation_policy is not None
                      and item.action.annotation_policy.leader_connector_id is not None}
    if held_frames.keys() != leader_actions.keys() or any(
        held_frames[key].at_ms != item.end_ms for key, item in leader_actions.items()
    ):
        raise UnsupportedVisualObject("annotation pointer preflight requires every exact completed construction frame")
    objects = snapshot.hierarchy.object_map({obj.object_id: obj for obj in layout.objects})
    annotation_leaders = {item.action.annotation_policy.leader_connector_id for item in timeline.actions
                          if isinstance(item.action, TargetAction) and item.action.annotation_policy is not None}
    for resolved in timeline.actions:
        action = resolved.action
        if isinstance(action, TargetAction) and action.annotation_policy is not None:
            for phase, _, _ in _annotation_phase_windows(resolved):
                mark = objects[phase.object_id]
                if phase.mode == "draw" and isinstance(mark, MarkObject):
                    _shape(mark, "#000000", "none", 1, draw_fraction=0.5)
        if (isinstance(action, TargetAction) and action.verb == "progressive_reveal"
                and any(not isinstance(objects[target], TextObject)
                        or objects[target].object_type != "list" for target in action.target_ids)):
            raise UnsupportedVisualObject(
                f"v2 action {action.action_id} requires an authored ordered-child list"
            )
        if isinstance(action, TargetAction) and action.verb in {"draw", "write"}:
            compatible = (MarkObject, ConnectorObject) if action.verb == "draw" else TextObject
            if any(not isinstance(objects[target], compatible) for target in action.target_ids):
                raise UnsupportedVisualObject(
                    f"v2 {action.verb} action {action.action_id} targets an incompatible object type"
                )
            if action.verb == "draw":
                for target in action.target_ids:
                    mark = objects[target]
                    if isinstance(mark, MarkObject):
                        _shape(mark, "#000000", "none", 1, draw_fraction=0.5)
    unsupported = [obj for obj in objects.values()
                   if not (isinstance(obj, MarkObject) and obj.object_type in SUPPORTED_MARKS
                           or isinstance(obj, TextObject) and obj.object_type in SUPPORTED_TEXT
                           or isinstance(obj, ConnectorObject) and obj.object_type == "arrow"
                           or isinstance(obj, ContainerObject) and obj.object_type in {"group", "clip", "mask"}
                           or isinstance(obj, VisualObject)
                           and obj.object_type in SUPPORTED_REGISTRY_VISUALS
                           or isinstance(obj, VisualObject)
                           and obj.object_type in {"image", "evidence"})]
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
    for obj in objects.values():
        if not isinstance(obj, ContainerObject):
            _preflight_object(obj, style, root, scale_x, objects,
                              annotation_pointer=obj.object_id in annotation_leaders)
    # Preflight complete pointer paint even when the requested frame precedes
    # annotation construction. Invalid routes/heads must not become late failures.
    for item in timeline.actions:
        if (isinstance(item.action, TargetAction) and item.action.annotation_policy is not None
                and item.action.annotation_policy.leader_connector_id is not None):
            held = held_frames[item.action.action_id]
            held_states = {state.object_id: state for state in held.objects}
            held_objects = held.hierarchy.object_map({obj.object_id: obj for obj in layout.objects})
            leader = held_objects[item.action.annotation_policy.leader_connector_id]
            stroke = _color(leader.style.stroke, style.colors, default=style.colors["ink"])
            _connector_shape(leader, held_objects, held_states, stroke, style.strokes.regular_px * scale_x, None)
    resolved_assets = {asset.asset_id: asset for asset in timeline.resolved_assets}
    evidence_treatments = {item.object_id: item for item in layout.evidence_treatments}
    raster_images = {}
    for obj in objects.values():
        if not isinstance(obj, VisualObject) or obj.object_type != "image":
            continue
        asset = resolved_assets.get(obj.asset_id)
        expected_uri = f"atme://projects/{layout.project_id}/assets/{obj.asset_id}"
        if (asset is None or asset.managed_ref != expected_uri
                or asset.kind not in {"image", "source_image"}
                or asset.media_type != "image/png"
                or asset.byte_length is None or asset.width is None or asset.height is None
                or asset.orientation != "upright" or asset.provenance_verified
                or asset.allowed_transformations != ["scale"]
                or asset_bytes is None or obj.asset_id not in asset_bytes):
            raise UnsupportedVisualObject(
                f"v2 image {obj.object_id} lacks verified project PNG bytes and metadata"
            )
        if (obj.transform.rotation_degrees != 0
                or any(isinstance(item.action, TransformAction)
                       and item.action.verb == "rotate"
                       and obj.object_id in item.action.target_ids
                       for item in timeline.actions)):
            raise UnsupportedVisualObject(
                f"v2 image {obj.object_id} cannot rotate without plan-bound permission"
            )
        parent_id = obj.parent_id
        while parent_id is not None:
            parent = objects[parent_id]
            if isinstance(parent, MaskContainer):
                raise UnsupportedVisualObject(f"v2 image {obj.object_id} has no mask permission")
            parent_id = parent.parent_id
        raw = asset_bytes[obj.asset_id]
        try:
            raster = canonical_png(raw)
        except UnsupportedProjectPNG as exc:
            raise UnsupportedVisualObject(str(exc)) from exc
        if (raster.source_sha256 != asset.checksum_sha256
                or len(raw) != asset.byte_length
                or (raster.width, raster.height) != (asset.width, asset.height)):
            raise UnsupportedVisualObject(f"v2 image {obj.object_id} failed asset integrity")
        raster_images[obj.asset_id] = raster
    for obj in objects.values():
        if not isinstance(obj, VisualObject) or obj.object_type != "evidence":
            continue
        treatment = evidence_treatments.get(obj.object_id)
        asset = resolved_assets.get(obj.asset_id)
        verified = asset_bytes.get(obj.asset_id) if asset_bytes is not None else None
        if (treatment is None or asset is None
                or not isinstance(verified, VerifiedEvidenceBytes)
                or verified.asset_id != obj.asset_id
                or verified.revision != asset.revision
                or verified.sha256 != asset.checksum_sha256
                or verified.treatment != treatment
                or verified.width != asset.width or verified.height != asset.height
                or asset.kind != "evidence" or asset.media_type != "image/png"
                or asset.byte_length is None or asset.orientation != "upright"
                or not asset.provenance_verified
                or asset.allowed_transformations != treatment.allowed_transformations
                or asset.managed_ref != treatment.asset_managed_ref):
            raise UnsupportedVisualObject(
                f"v2 evidence {obj.object_id} lacks verified project evidence bytes and treatment"
            )
        try:
            raster = canonical_png(verified.payload)
        except UnsupportedProjectPNG as exc:
            raise UnsupportedVisualObject(str(exc)) from exc
        if (raster.source_sha256 != asset.checksum_sha256
                or len(verified.payload) != asset.byte_length
                or (raster.width, raster.height) != (asset.width, asset.height)):
            raise UnsupportedVisualObject(f"v2 evidence {obj.object_id} failed asset integrity")
        raster_images[obj.asset_id] = raster
    active_verbs = {
        target: resolved.action.verb
        for resolved in timeline.actions
        if resolved.start_ms <= at_ms < resolved.end_ms
        for target in (
            resolved.action.target_ids
            if isinstance(resolved.action, TargetAction)
            and resolved.action.verb in {"draw", "write", "progressive_reveal"}
            else (resolved.action.connector_id,)
            if isinstance(resolved.action, ConnectionAction) else ()
        )
    }
    for item in timeline.actions:
        if isinstance(item.action, TargetAction) and item.action.annotation_policy is not None:
            for phase, start, end in _annotation_phase_windows(item):
                if start <= at_ms < end:
                    active_verbs[phase.object_id] = phase.mode
    definitions = []
    body = [(f'<rect x="{_n(layout.canvas.x)}" y="{_n(layout.canvas.y)}" '
             f'width="{_n(layout.canvas.width)}" height="{_n(layout.canvas.height)}" '
             f'fill="{style.colors["paper"]}"/>')]
    states = {state.object_id: state for state in snapshot.objects}
    mask_sources = {obj.mask_source_object_id for obj in objects.values()
                    if isinstance(obj, MaskContainer)}
    children: dict[str | None, list] = {}
    for obj in objects.values():
        children.setdefault(obj.parent_id, []).append(obj)
    paint_ordinals = {node.object_id: node.sibling_ordinal for node in snapshot.hierarchy.nodes}
    for siblings in children.values():
        siblings.sort(key=lambda item: paint_ordinals[item.object_id])
    for state in snapshot.objects:
        obj = objects[state.object_id]
        if isinstance(obj, ContainerObject) and obj.object_type == "clip":
            bounds = obj.geometry.bounds
            definitions.append(
                f'<clipPath id="{_container_clip_id(obj.object_id)}" '
                f'clipPathUnits="userSpaceOnUse">'
                f'<rect x="{_n(bounds.x)}" y="{_n(bounds.y)}" '
                f'width="{_n(bounds.width)}" height="{_n(bounds.height)}"/>'
                f'</clipPath>'
            )
        if isinstance(obj, MaskContainer):
            source = objects[obj.mask_source_object_id]
            source_state = states[source.object_id]
            try:
                x, y, width, height = mask_source_region(source, source_state.transform)
            except UnsupportedMask as exc:
                raise UnsupportedVisualObject(str(exc)) from exc
            shape = _shape(source, "none", "#ffffff", 0)
            definitions.append(
                f'<mask id="{_container_mask_id(obj.object_id)}" '
                f'maskUnits="userSpaceOnUse" maskContentUnits="userSpaceOnUse" '
                f'x="{_n(x)}" y="{_n(y)}" width="{_n(width)}" '
                f'height="{_n(height)}" style="mask-type:alpha">'
                f'<g transform="{_object_transform(source, source_state)}">'
                f'{shape}</g></mask>'
            )
        if 0 < state.reveal_fraction < 1 and active_verbs.get(state.object_id) not in {
            "draw", "write", "progressive_reveal", "connect", "disconnect"
        }:
            bounds = obj.geometry.bounds
            definitions.append(
                f'<clipPath id="{_clip_id(obj.object_id)}">'
                f'<rect x="{_n(bounds.x)}" y="{_n(bounds.y)}" '
                f'width="{_n(bounds.width * state.reveal_fraction)}" '
                f'height="{_n(bounds.height)}"/></clipPath>'
            )
    def render_object(obj) -> str:
        if obj.object_id in mask_sources:
            return ""
        state = states[obj.object_id]
        if isinstance(obj, ContainerObject):
            if not state.visible or state.opacity <= 0 or state.reveal_fraction <= 0:
                return ""
            inner = "".join(render_object(child) for child in children.get(obj.object_id, ()))
            if isinstance(obj, MaskContainer):
                # Aperture stays in parent-local coordinates; content moves beneath it.
                return (f'<g data-object-id="{_xml_escape(obj.object_id)}" '
                        f'mask="url(#{_container_mask_id(obj.object_id)})" '
                        f'opacity="{_n(state.opacity)}">'
                        f'<g transform="{_object_transform(obj, state)}">{inner}</g></g>')
            clip = (f' clip-path="url(#{_container_clip_id(obj.object_id)})"'
                    if obj.object_type == "clip" else "")
            return (f'<g data-object-id="{_xml_escape(obj.object_id)}" '
                    f'transform="{_object_transform(obj, state)}" '
                    f'opacity="{_n(state.opacity)}"{clip}>{inner}</g>')
        return _object_markup(obj, state, style, root, scale_x,
                              active_verbs.get(obj.object_id), objects, states,
                              raster_images, evidence_treatments)

    body.extend(render_object(obj) for obj in children.get(None, ()))
    width, height = layout.output_profile.width, layout.output_profile.height
    viewport = snapshot.camera
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
           f'viewBox="{_n(viewport.x)} {_n(viewport.y)} '
           f'{_n(viewport.width)} {_n(viewport.height)}">'
           f'<defs><style>{_font_css(style, root)}</style>'
           f'{"".join(definitions)}</defs>'
           f'{"".join(body)}</svg>')
    return SVGFrame(at_ms=at_ms, width=width, height=height, svg=svg)


def compose_png_frame(layout_document: dict, timeline_document: dict, at_ms: int,
                      asset_bytes: dict[str, bytes | VerifiedEvidenceBytes] | None = None) -> PNGFrame:
    """Rasterize a supported frame with verified, pinned fonts and no system-font fallback."""
    frame = compose_svg_frame(layout_document, timeline_document, at_ms, asset_bytes)
    return _rasterize_svg_frame(ExecutableLayoutV2.model_validate(layout_document), frame)


def _rasterize_svg_frame(layout: ExecutableLayoutV2, frame: SVGFrame) -> PNGFrame:
    """The same pinned offline rasterizer for public frames and private proofs."""
    import resvg_py

    style, _, root = resolve_contract_bundle(layout.style_system_version, layout.asset_registry_version)
    font_files = [str(root / font.file) for font in style.fonts]
    png = bytes(resvg_py.svg_to_bytes(
        svg_string=frame.svg, width=frame.width, height=frame.height,
        font_files=font_files, skip_system_fonts=True,
    ))
    return PNGFrame(at_ms=frame.at_ms, width=frame.width, height=frame.height, png=png)
