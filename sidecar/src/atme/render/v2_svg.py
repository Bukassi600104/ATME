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
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from itertools import pairwise
from pathlib import Path
from tempfile import TemporaryDirectory

import regex
from PIL import Image, ImageFont

from atme.project_assets import VerifiedEvidenceBytes
from atme.render.code_font_bundle import load_code_font_bundle, verify_code_font_bundle
from atme.render.style_bundle import (
    _asset_inner,
    _font_css,
    registry_endpoint_inputs_for_objects,
    resolve_contract_bundle,
    verified_asset_svg,
)
from atme.render.v2_callout import callout_body_svg
from atme.render.v2_code import code_svg
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
from atme.render.v2_external_aperture import (
    UnsupportedExternalAperture,
    external_aperture_projections,
)
from atme.render.v2_image import (
    image_placement_svg,
    validate_image_placement,
    validate_placement_permissions,
)
from atme.render.v2_list import UnsupportedOrderedList, validate_ordered_list
from atme.render.v2_mask import UnsupportedMask, mask_source_region
from atme.render.v2_media_view import media_visual_view, validate_media_ranges
from atme.render.v2_morph import geometry_object
from atme.render.v2_path import (
    MAX_COORDINATE,
    MAX_STROKE_LENGTH,
    InvalidFreehandPath,
    parse_freehand_path,
)
from atme.render.v2_raster import UnsupportedProjectPNG, canonical_png
from atme.render.v2_registry import (
    SUPPORTED_REGISTRY_VISUALS,
    UnsupportedRegistryPlacement,
    checked_registry_art,
    registry_placement,
    validate_registry_binding,
    validate_registry_world_binding,
)
from atme.render.v2_state import FrameObject, FrameSnapshot, evaluate_frame
from atme.render.v2_world import transform_svg
from atme.store.contracts_v2 import (
    MEDIA_OBJECT_TYPES,
    ConnectionAction,
    ConnectorObject,
    ContainerObject,
    EvidenceAction,
    ExecutableLayoutV2,
    MarkObject,
    MaskContainer,
    ResolvedVisualTimelineV2,
    SplitAction,
    TargetAction,
    TextObject,
    TransformAction,
    VisualObject,
    _annotation_policy_phase_windows,
    _callout_leader_owners,
    validate_character_assembly_map,
    validate_illustration_assembly_map,
)


class UnsupportedVisualObject(ValueError):
    """A scene object has no faithful v2 drawing implementation."""


SUPPORTED_MARKS = SUPPORTED_HIGHLIGHT_MARKS
SUPPORTED_TEXT = SUPPORTED_HIGHLIGHT_TEXT | frozenset({"code", "callout"})


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
def _font(path: str | bytes, size: int):
    return ImageFont.truetype(io.BytesIO(path) if isinstance(path, bytes) else path, size)


def _font_source(root, font, resources):
    return root / font.file if resources is None else resources[2][font.file]


def _chart_font_inputs(style, root, resources):
    ids = {style.typography.title.font_id, style.typography.label.font_id}
    result = {}
    for font in style.fonts:
        if font.id in ids:
            source = _font_source(root, font, resources)
            result[font.file] = source if isinstance(source, bytes) else source.read_bytes()
    return result


def _code_font_inputs(root, resources):
    return (load_code_font_bundle(root) if resources is None else
            verify_code_font_bundle(resources[2].__getitem__))


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
    if obj.object_type not in {"freehand", "line", "polygon", "bracket"} and obj.geometry.points:
        raise UnsupportedVisualObject(f"{obj.object_type} {obj.object_id} has ignored geometry points")
    if obj.object_type != "rounded_rectangle" and obj.geometry.corner_radius is not None:
        raise UnsupportedVisualObject(f"{obj.object_type} {obj.object_id} has ignored corner radius")
    if obj.object_type == "rounded_rectangle" and not obj.geometry.corner_radius:
        raise UnsupportedVisualObject(f"rounded rectangle {obj.object_id} requires a positive corner radius")
    if (obj.object_type == "rounded_rectangle"
            and obj.geometry.corner_radius > min(bounds.width, bounds.height) / 2):
        raise UnsupportedVisualObject(f"rounded rectangle {obj.object_id} radius exceeds its bounds")
    if obj.object_type in {"freehand", "line", "underline", "highlight", "bracket"} and fill != "none":
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
    bracket_points = None
    if obj.object_type == "bracket":
        if obj.path_data is not None or len(obj.geometry.points) != 4:
            raise UnsupportedVisualObject(f"bracket {obj.object_id} requires four authored points and no path data")
        bracket_points = [(float(_n(point.x)), float(_n(point.y))) for point in obj.geometry.points]
        a, b, c, d = bracket_points
        # Arm vectors point outward from the spine. Traversal goes inward along
        # the first arm and outward along the last; preserve that draw order.
        vertical = (b[0] == c[0] and b[1] != c[1] and a[1] == b[1] and d[1] == c[1]
                    and (a[0] - b[0]) * (d[0] - c[0]) > 0)
        horizontal = (b[1] == c[1] and b[0] != c[0] and a[0] == b[0] and d[0] == c[0]
                      and (a[1] - b[1]) * (d[1] - c[1]) > 0)
        qx, qy, qw, qh = (float(_n(value)) for value in (x, y, w, h))
        if (not (vertical or horizontal) or qw <= 0 or qh <= 0
                or any(not(qx <= px <= qx + qw and qy <= py <= qy + qh) for px, py in bracket_points)):
            raise UnsupportedVisualObject(f"bracket {obj.object_id} requires a nonzero orthogonal spine and same-side arms")
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
        elif obj.object_type == "bracket":
            length = sum(math.dist(a, b) for a, b in pairwise(bracket_points))
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
    if bracket_points is not None:
        points = " ".join(f"{_n(px)},{_n(py)}" for px, py in bracket_points)
        return f'<polyline points="{points}" {attributes}/>'
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
          line_height: float, max_characters: int, font_path: Path | bytes,
          write_fraction: float | None = None,
          progressive_fraction: float | None = None) -> str:
    bounds = obj.geometry.bounds
    lines = obj.text.splitlines()
    if obj.object_type == "list" and obj.structured_list is None:
        try:
            validate_ordered_list(obj)
        except UnsupportedOrderedList as exc:
            raise UnsupportedVisualObject(str(exc)) from exc
        lines = [obj.text, *(f"• {item}" for item in obj.items)]
    if any(len(line) > max_characters for line in lines):
        raise UnsupportedVisualObject(f"text {obj.object_id} requires authored line breaks")
    if len(lines) * font_size * line_height > bounds.height:
        raise UnsupportedVisualObject(f"text {obj.object_id} exceeds authored bounds")
    measuring_font = _font(font_path if isinstance(font_path, bytes) else str(font_path),
                           max(1, math.ceil(font_size)))
    if any(measuring_font.getlength(line) > bounds.width for line in lines):
        raise UnsupportedVisualObject(f"text {obj.object_id} exceeds authored width")
    if progressive_fraction is not None:
        if obj.object_type != "list" or obj.structured_list is not None or write_fraction is not None:
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


def _registry_art(obj: VisualObject, resources=None):
    """Return same-byte art and metadata; no sampled endpoint admission."""
    if not obj.variant:
        raise UnsupportedVisualObject(f"v2 visual {obj.object_id} must select an original registry variant")
    if resources is None:
        asset, inner = verified_asset_svg(obj.variant)
    else:
        style, _, files, _ = resources
        try:
            asset, payload = checked_registry_art(obj.variant, files["asset-registry.json"],
                                                   files[f"assets/{obj.variant}.svg"])
        except (KeyError, UnsupportedRegistryPlacement) as exc:
            raise UnsupportedVisualObject(f"registry byte evidence is missing or invalid: {exc}") from exc
        inner = _asset_inner(Path(asset.file), style.colors, asset.view_box, payload=payload)
    allowed = SUPPORTED_REGISTRY_VISUALS[obj.object_type]
    if asset.family not in allowed:
        raise UnsupportedVisualObject(
            f"v2 {obj.object_type} {obj.object_id} cannot use {asset.family} asset {asset.id}"
        )
    return asset, inner


def _registry_visual(obj: VisualObject, resources=None) -> str:
    """Local primitive paint; the shared tree authenticates sampled geometry."""
    asset, inner = _registry_art(obj, resources)
    try:
        placement = registry_placement(asset, obj.geometry.bounds)
        if obj.registry_binding is not None:
            validate_registry_binding(obj, asset)
    except UnsupportedRegistryPlacement as exc:
        raise UnsupportedVisualObject(str(exc)) from exc
    x, y, width, height = placement.viewport
    view_width, view_height = placement.view_box[2:4]
    return (f'<svg x="{_n(x)}" y="{_n(y)}" '
            f'width="{_n(width)}" height="{_n(height)}" '
            f'viewBox="0 0 {view_width} {view_height}" preserveAspectRatio="xMidYMid meet">'
            f'{inner}</svg>')


def _connector_shape(obj: ConnectorObject, objects: dict, states: dict,
                     stroke: str, weight: float, draw_fraction: float | None,
                     *, registry_inputs=None, media_view=None) -> str:
    try:
        if obj.object_id in _callout_leader_owners(objects):
            from atme.render.v2_callout_pointer import callout_pointer_route

            geometry = callout_pointer_route(obj, objects, states, weight, registry_inputs=registry_inputs,
                                             media_view=media_view)
        else:
            geometry = connector_route(obj, objects, states, weight, registry_inputs=registry_inputs,
                                        media_view=media_view)
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


def _evidence_text(value: str, font_file: Path | bytes, font_size: float, max_width: float) -> str:
    if len(value) > 120:
        raise UnsupportedVisualObject("evidence attribution or annotation is too long")
    _xml_escape(value)
    font = _font(font_file if isinstance(font_file, bytes) else str(font_file), max(1, round(font_size)))
    if font.getlength(value) > max_width:
        raise UnsupportedVisualObject("evidence attribution or annotation does not fit its frame")
    return _xml_escape(value)


def _evidence_markup(obj: VisualObject, state: FrameObject, style, root: Path,
                     scale: float, raster, treatment, resources=None) -> str:
    """Render a bounded evidence card, never a fabricated substitute image."""
    bounds = obj.geometry.bounds
    intent = treatment.intent
    if (intent.annotation is not None and intent.annotation_target_id != obj.object_id
            and intent.annotation_policy is None):
        raise UnsupportedVisualObject(f"evidence {obj.object_id} lacks authored cross-annotation authority")
    inline_annotation = intent.annotation if intent.annotation_target_id == obj.object_id else None
    if bounds.width < 180 * scale or bounds.height < 160 * scale:
        raise UnsupportedVisualObject(f"evidence {obj.object_id} is too small to remain readable")
    caption_role = style.typography.caption
    caption_font = next(font for font in style.fonts if font.id == caption_role.font_id)
    label_height = 34 * scale
    annotation_height = 34 * scale if inline_annotation is not None else 0
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
    label = _evidence_text(intent.source_label, _font_source(root, caption_font, resources),
                           font_size, bounds.width - 2 * margin)
    annotation = (_evidence_text(inline_annotation, _font_source(root, caption_font, resources),
                                  font_size, bounds.width - 2 * margin)
                  if inline_annotation is not None else None)
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
                   raster_images: dict, evidence_treatments: dict, construction=None, resources=None,
                   registry_inputs=None, media_rasters=None, media_view=None) -> str:
    if not state.visible or state.opacity <= 0 or state.reveal_fraction <= 0:
        return ""
    if media_view is not None and not media_view.allows(obj.object_id):
        return ""
    obj = geometry_object(obj, state.morph_geometry)
    transform = _object_transform(obj, state)
    bounds = obj.geometry.bounds
    construction_fraction = (construction.construction_fraction if construction is not None
                             else state.reveal_fraction)
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
                           construction_fraction if active_verb == "draw" else None)
    elif isinstance(obj, TextObject) and obj.object_type == "code":
        inner = code_svg(obj, style, scale, _code_font_inputs(root, resources),
                         write_fraction=construction_fraction if active_verb == "write" else None)
    elif isinstance(obj, TextObject) and obj.object_type == "callout":
        role = _text_role(obj, style)
        font = next(font for font in style.fonts if font.id == role.font_id)
        inner = callout_body_svg(obj, style, scale, _font_source(root, font, resources),
            write_fraction=construction_fraction if active_verb == "write" else None)
    elif isinstance(obj, TextObject):
        color = _color(obj.style.text, style.colors, default=style.colors["ink"])
        role = _text_role(obj, style)
        font = next(font for font in style.fonts if font.id == role.font_id)
        if getattr(state, "display_text", None) is not None:
            obj = obj.model_copy(update={"text": state.display_text}, deep=True)
        inner = _text(obj, color, font.family, font.weight, role.size_px * scale, role.line_height,
                      role.max_characters_per_line, _font_source(root, font, resources),
                      construction_fraction if active_verb == "write" else None,
                      state.reveal_fraction if active_verb == "progressive_reveal" else None)
    elif isinstance(obj, ConnectorObject):
        stroke = _color(obj.style.stroke, style.colors, default=style.colors["ink"])
        inner = _connector_shape(obj, objects, states, stroke,
                                 style.strokes.regular_px * scale,
                                 state.reveal_fraction if active_verb in {
                                     "draw", "connect", "disconnect"
                                 } else None, registry_inputs=registry_inputs, media_view=media_view)
    elif isinstance(obj, VisualObject) and obj.chart_payload is not None:
        from atme.render.v2_chart import chart_svg

        inner = chart_svg(obj, style, scale, _chart_font_inputs(style, root, resources),
            draw_fraction=construction_fraction if active_verb == "draw" else None)
    elif isinstance(obj, VisualObject) and obj.technical_frame is not None:
        from atme.render.v2_technical_frame import technical_frame_svg

        inner = technical_frame_svg(obj, stroke=_color(obj.style.stroke, style.colors, default=style.colors["ink"]),
            fill=_color(obj.style.fill, style.colors, default="none"), stroke_width=style.strokes.regular_px * scale)
    elif isinstance(obj, VisualObject) and obj.object_type in MEDIA_OBJECT_TYPES:
        raster = media_rasters.get(obj.object_id) if media_rasters is not None else None
        if raster is None:
            raise UnsupportedVisualObject(f"media {obj.object_id} lacks its exact current presentation frame")
        inner = image_placement_svg(obj, raster, placement=obj.media_playback.placement)
    elif isinstance(obj, VisualObject) and obj.object_type == "image":
        raster = raster_images[obj.asset_id]
        if obj.image_placement is not None:
            inner = image_placement_svg(obj, raster)
        else:
            encoded = base64.b64encode(raster.payload).decode("ascii")
            inner = (f'<image x="{_n(bounds.x)}" y="{_n(bounds.y)}" '
                     f'width="{_n(bounds.width)}" height="{_n(bounds.height)}" '
                     f'preserveAspectRatio="xMidYMid meet" '
                     f'href="data:image/png;base64,{encoded}"/>')
    elif isinstance(obj, VisualObject) and obj.object_type == "evidence":
        inner = _evidence_markup(obj, state, style, root, scale,
                                 raster_images[obj.asset_id], evidence_treatments[obj.object_id], resources)
    else:
        inner = _registry_visual(obj, resources)
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
    local_split_clip = construction is not None and construction.root_id != obj.object_id
    if state.reveal_fraction < 1 and (local_split_clip or active_verb not in {
        "draw", "write", "progressive_reveal", "connect", "disconnect"
    }):
        clip = f' clip-path="url(#{_clip_id(obj.object_id)})"'
    return (f'<g data-object-id="{_xml_escape(obj.object_id)}" '
            f'transform="{transform}" opacity="{_n(state.opacity)}"{clip}>{inner}</g>')


def _preflight_object(obj: MarkObject | TextObject | VisualObject | ConnectorObject,
                      style, root: Path, scale: float, objects: dict, *, annotation_pointer: bool = False,
                      callout_pointer: bool = False, resources=None) -> None:
    _xml_escape(obj.object_id)
    if (obj.style.effect
            or obj.asset_id and not (isinstance(obj, VisualObject)
                                     and obj.object_type in {"image", "evidence", *MEDIA_OBJECT_TYPES})):
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
            if callout_pointer:
                from atme.render.v2_callout_pointer import validate_callout_pointer

                validate_callout_pointer(obj, objects)
            else:
                validate_static_arrow(obj, objects, annotation_pointer=annotation_pointer)
        except UnsupportedConnector as exc:
            raise UnsupportedVisualObject(str(exc)) from exc
    elif isinstance(obj, TextObject) and obj.object_type == "code":
        code_svg(obj, style, scale, _code_font_inputs(root, resources))
    elif isinstance(obj, TextObject) and obj.object_type == "callout":
        role = _text_role(obj, style)
        font = next(font for font in style.fonts if font.id == role.font_id)
        callout_body_svg(obj, style, scale, _font_source(root, font, resources))
    elif isinstance(obj, TextObject):
        if (obj.style.stroke or obj.style.fill or obj.geometry.points
                or obj.geometry.corner_radius is not None
                or obj.items and obj.object_type != "list"):
            raise UnsupportedVisualObject(f"v2 text {obj.object_id} has unsupported styling or geometry")
        color = _color(obj.style.text, style.colors, default=style.colors["ink"])
        role = _text_role(obj, style)
        font = next(font for font in style.fonts if font.id == role.font_id)
        _text(obj, color, font.family, font.weight, role.size_px * scale, role.line_height,
              role.max_characters_per_line, _font_source(root, font, resources))
    elif isinstance(obj, VisualObject) and obj.chart_payload is not None:
        from atme.render.v2_chart import chart_svg

        chart_svg(obj, style, scale, _chart_font_inputs(style, root, resources))
    elif isinstance(obj, VisualObject) and obj.technical_frame is not None:
        from atme.render.v2_technical_frame import technical_frame_svg

        technical_frame_svg(obj, stroke=_color(obj.style.stroke, style.colors, default=style.colors["ink"]),
            fill=_color(obj.style.fill, style.colors, default="none"), stroke_width=style.strokes.regular_px * scale)
    elif isinstance(obj, VisualObject) and obj.object_type in {"image", *MEDIA_OBJECT_TYPES}:
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
        _registry_visual(obj, resources)


def _authored_annotation_bindings(timeline):
    from atme.render.v2_split_clock import resolve_split_phase

    evidence = {(row.action_id, row.object_id): row for row in timeline.evidence_treatments}
    bindings = []
    for item in timeline.actions:
        action = item.action
        if isinstance(action, TargetAction) and action.annotation_policy is not None:
            bindings.append((action.action_id, action.annotation_policy, item.start_ms, item.end_ms))
        elif isinstance(action, EvidenceAction) and action.verb == "insert_evidence":
            policy = evidence[(action.action_id, action.target_object_id)].intent.annotation_policy
            if policy is not None:
                bindings.append((action.action_id, policy, item.start_ms, item.end_ms))
        elif isinstance(action, SplitAction):
            if action.split_policy is None:
                raise UnsupportedVisualObject("Split annotation binding requires an authored split_policy")
            for result in action.split_policy.results:
                activation = result.evidence_activation
                if activation is None or activation.intent.annotation_policy is None:
                    continue
                key = (action.action_id, result.object_id)
                treatment = evidence.get(key)
                if treatment is None or treatment.intent != activation.intent:
                    raise UnsupportedVisualObject("Split annotation needs its exact result treatment")
                start, end = resolve_split_phase(item.start_ms, item.end_ms, result.construction.phase)
                bindings.append((key, activation.intent.annotation_policy, start, end))
    return tuple(bindings)


def _preflight_annotation_pointers(bindings, held_frames, layout, style, scale, registry_inputs):
    leaders = {key: (policy, end) for key, policy, _, end in bindings if policy.leader_connector_id is not None}
    if held_frames.keys() != leaders.keys() or any(held_frames[key].at_ms != end
            for key, (_, end) in leaders.items()):
        raise UnsupportedVisualObject("annotation pointer preflight requires every exact completed construction frame")
    for key, (policy, _) in leaders.items():
        held = held_frames[key]
        states = {state.object_id: state for state in held.objects}
        objects = held.hierarchy.object_map({obj.object_id: obj for obj in layout.objects})
        leader = objects[policy.leader_connector_id]
        stroke = _color(leader.style.stroke, style.colors, default=style.colors["ink"])
        _connector_shape(leader, objects, states, stroke, style.strokes.regular_px * scale, None,
                         registry_inputs=registry_inputs, media_view=media_visual_view(objects, held.at_ms))


def _annotation_paint_modes(bindings, at_ms):
    return {phase.object_id: phase.mode for _, policy, start, end in bindings
            for phase, phase_start, phase_end in _annotation_policy_phase_windows(policy, start, end)
            if phase_start <= at_ms < phase_end}


def compose_svg_frame(layout_document: dict, timeline_document: dict, at_ms: int,
                      asset_bytes: dict[str, bytes | VerifiedEvidenceBytes] | None = None) -> SVGFrame:
    """Draw supported objects in deterministic z order; never substitute boxes."""
    snapshot = evaluate_frame(layout_document, timeline_document, at_ms)
    layout = ExecutableLayoutV2.model_validate(layout_document)
    timeline = ResolvedVisualTimelineV2.model_validate(timeline_document)
    held_frames = {
        key: evaluate_frame(layout_document, timeline_document, end)
        for key, policy, _, end in _authored_annotation_bindings(timeline)
        if policy.leader_connector_id is not None
    }
    return _compose_validated_svg_frame(layout, timeline, snapshot, held_frames, asset_bytes)


def _prepare_project_rasters(layout, objects, states, actions, resolved_assets, asset_bytes, at_ms,
                             *, duration_ms=None):
    """One native preparation path for full and authenticated subset painting.

    Uses original bytes and absolute project time, never a thumbnail/local clock.
    Evidence stays on its separate attested treatment path.
    """
    if duration_ms is not None:
        try:
            validate_media_ranges(objects, resolved_assets, duration_ms)
        except ValueError as exc:
            raise UnsupportedVisualObject(str(exc)) from exc
    media_view = media_visual_view(objects, at_ms)
    media_rasters = {}
    for obj in objects.values():
        if not isinstance(obj, VisualObject) or obj.object_type not in MEDIA_OBJECT_TYPES:
            continue
        asset = resolved_assets.get(obj.asset_id)
        if (asset is None or asset.managed_ref != f"atme://projects/{layout.project_id}/assets/{obj.asset_id}"
                or asset.media_type is None or not asset.media_type.startswith("video/")
                or asset.byte_length is None or asset.orientation != "upright" or asset.provenance_verified
                or asset_bytes is None or type(asset_bytes.get(obj.asset_id)) is not bytes):
            raise UnsupportedVisualObject(f"media {obj.object_id} lacks verified original project video bytes")
        raw = asset_bytes[obj.asset_id]
        if len(raw) != asset.byte_length or hashlib.sha256(raw).hexdigest() != asset.checksum_sha256:
            raise UnsupportedVisualObject(f"media {obj.object_id} failed source asset integrity")
        try:
            from atme.render.v2_media import media_frame

            validate_placement_permissions(obj, obj.media_playback.placement, objects,
                {key: state.transform for key, state in states.items()},
                tuple(row.action for row in actions), label="media_playback.placement")
            media_rasters[obj.object_id] = media_frame(raw, obj.media_playback, at_ms)
        except ValueError as exc:
            raise UnsupportedVisualObject(str(exc)) from exc
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
                or obj.image_placement is None and asset.allowed_transformations != ["scale"]
                or asset_bytes is None or obj.asset_id not in asset_bytes):
            raise UnsupportedVisualObject(
                f"v2 image {obj.object_id} lacks verified project PNG bytes and metadata"
            )
        if obj.image_placement is not None:
            try:
                validate_image_placement(obj, asset, objects,
                                         states, actions)
            except ValueError as exc:
                raise UnsupportedVisualObject(str(exc)) from exc
        elif (obj.transform.rotation_degrees != 0
                or any(isinstance(item.action, TransformAction)
                       and item.action.verb == "rotate"
                       and obj.object_id in item.action.target_ids
                       for item in actions)):
            raise UnsupportedVisualObject(
                f"v2 image {obj.object_id} cannot rotate without plan-bound permission"
            )
        parent_id = obj.parent_id
        while parent_id is not None:
            parent = objects[parent_id]
            if obj.image_placement is None and isinstance(parent, MaskContainer):
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
    return raster_images, media_rasters, media_view


def _prepare_evidence_rasters(objects, resolved_assets, asset_bytes, evidence_treatments):
    """Use the same attested originals for full frames and private observations."""
    from atme.render.v2_split_paint import _split_evidence_asset_value

    rasters = {}
    for obj in objects.values():
        if not isinstance(obj, VisualObject) or obj.object_type != "evidence":
            continue
        treatment = evidence_treatments.get(obj.object_id)
        asset = resolved_assets.get(obj.asset_id)
        verified = (_split_evidence_asset_value(asset_bytes, obj.asset_id, treatment.action_id, obj.object_id)
                    if treatment is not None else None)
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
        rasters[obj.asset_id] = raster
    return rasters


def _compose_validated_svg_frame(layout: ExecutableLayoutV2, timeline: ResolvedVisualTimelineV2,
                                 snapshot: FrameSnapshot, held_frames: dict[str | tuple[str, str], FrameSnapshot],
                                 asset_bytes: dict[str, bytes | VerifiedEvidenceBytes] | None = None,
                                 *, split_inputs=None) -> SVGFrame:
    """Pure paint from requested and held snapshots of the same proven history.

    This internal consumer does not admit an action or advertise a capability.
    Public callers obtain every snapshot through the public frame evaluator.
    """
    at_ms = snapshot.at_ms
    if layout.evidence_treatments != timeline.evidence_treatments:
        raise UnsupportedVisualObject("evidence paint needs the exact paired layout and timeline treatments")
    annotation_bindings = _authored_annotation_bindings(timeline)
    objects = snapshot.hierarchy.object_map({obj.object_id: obj for obj in layout.objects})
    callout_leaders = _callout_leader_owners(objects)
    annotation_leaders = {policy.leader_connector_id for _, policy, _, _ in annotation_bindings}
    for _, policy, start, end in annotation_bindings:
        for phase, _, _ in _annotation_policy_phase_windows(policy, start, end):
            mark = objects[phase.object_id]
            if phase.mode == "draw" and isinstance(mark, MarkObject):
                _shape(mark, "#000000", "none", 1, draw_fraction=0.5)
    for resolved in timeline.actions:
        action = resolved.action
        if (isinstance(action, TargetAction) and action.verb == "progressive_reveal"
                and action.structured_list_policy is None
                and any(not isinstance(objects[target], TextObject)
                        or objects[target].object_type != "list" for target in action.target_ids)):
            raise UnsupportedVisualObject(
                f"v2 action {action.action_id} requires an authored ordered-child list"
            )
        if isinstance(action, TargetAction) and action.verb in {"draw", "write"}:
            compatible = (MarkObject, ConnectorObject) if action.verb == "draw" else TextObject
            if any(not (isinstance(objects[target], compatible)
                        or action.verb == "draw" and isinstance(objects[target], VisualObject)
                        and objects[target].chart_payload is not None) for target in action.target_ids):
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
                           or isinstance(obj, ConnectorObject) and obj.object_type in {"arrow", "network"}
                           or isinstance(obj, ContainerObject) and obj.object_type in {"group", "clip", "mask"}
                           or isinstance(obj, VisualObject)
                           and obj.object_type in SUPPORTED_REGISTRY_VISUALS
                           or isinstance(obj, VisualObject) and obj.technical_frame is not None
                           or isinstance(obj, VisualObject)
                           and obj.object_type in {"image", "evidence", *MEDIA_OBJECT_TYPES})]
    if unsupported:
        first = unsupported[0]
        raise UnsupportedVisualObject(
            f"v2 object {first.object_id} uses {first.object_type}, which has no SVG implementation"
        )
    resources = None
    if split_inputs is not None:
        from atme.render.v2_split_paint import (
            _canonical,
            _checked_split_resources,
            _VerifiedSplitAssetBytes,
        )

        resources = _checked_split_resources(layout, split_inputs)
        style, _, _, frozen_assets = resources
        root = None
        if asset_bytes is not None:
            if type(asset_bytes) is _VerifiedSplitAssetBytes:
                same_assets = asset_bytes.rows == frozen_assets.rows
            else:
                same_assets = dict(asset_bytes) == dict(frozen_assets)
            if not same_assets:
                raise ValueError("Split asset bytes differ from frozen inputs")
        frozen_resolved = {row.asset_id: row.resolved_json for row in frozen_assets.rows}
        if (len(frozen_resolved) != len(timeline.resolved_assets)
                or frozen_resolved != {item.asset_id: _canonical(item.model_dump(mode="json"))
                                        for item in timeline.resolved_assets}):
            raise ValueError("Split resolved assets differ from frozen inputs")
        asset_bytes = frozen_assets
    else:
        if any(isinstance(item.action, SplitAction) for item in timeline.actions):
            raise ValueError("Split composition requires frozen paint inputs")
        style, _, root = resolve_contract_bundle(layout.style_system_version,
                                                layout.asset_registry_version)
    registry_inputs = registry_endpoint_inputs_for_objects(objects,
        frozen_files=resources[2] if resources is not None else None)
    profile_key = "landscape-16:9" if layout.output_profile.profile_id == "LONG_FORM_16_9" else "portrait-9:16"
    design = style.aspects[profile_key]
    scale_x = layout.output_profile.width / design.width
    scale_y = layout.output_profile.height / design.height
    if abs(scale_x - scale_y) > 1e-6:
        raise UnsupportedVisualObject("output profile cannot uniformly scale Paper & Ink design tokens")
    for obj in objects.values():
        if not isinstance(obj, ContainerObject):
            _preflight_object(obj, style, root, scale_x, objects,
                              annotation_pointer=obj.object_id in annotation_leaders,
                              callout_pointer=obj.object_id in callout_leaders, resources=resources)
    # Preflight complete pointer paint even when the requested frame precedes
    # annotation construction. Invalid routes/heads must not become late failures.
    _preflight_annotation_pointers(annotation_bindings, held_frames, layout, style, scale_x, registry_inputs)
    resolved_assets = {asset.asset_id: asset for asset in timeline.resolved_assets}
    raster_images, media_rasters, media_view = _prepare_project_rasters(layout, objects,
        {row.object_id: row for row in snapshot.objects}, timeline.actions, resolved_assets, asset_bytes, at_ms,
        duration_ms=timeline.duration_ms)
    evidence_treatments = {item.object_id: item for item in layout.evidence_treatments}
    from atme.render.v2_split_paint import _split_active_paint_modes

    raster_images.update(_prepare_evidence_rasters(objects, resolved_assets, asset_bytes, evidence_treatments))
    active_verbs = {
        target: ("reveal" if isinstance(resolved.action, TargetAction)
                 and resolved.action.structured_list_policy is not None else resolved.action.verb)
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
    active_verbs.update(_annotation_paint_modes(annotation_bindings, at_ms))
    # Consume exact private replay envelopes. This does not open public Split
    # admission; the evaluator's family/coverage gates remain separate.
    split_envelopes = _split_active_paint_modes(snapshot, timeline, objects)
    active_verbs.update({key: envelope.mode for key, envelope in split_envelopes.items()})
    definitions, tree = _compose_object_tree(objects,
        {state.object_id: state for state in snapshot.objects},
        {node.object_id: node.sibling_ordinal for node in snapshot.hierarchy.nodes},
        style, root, scale_x, active_verbs, raster_images, evidence_treatments,
        split_envelopes, resources, registry_inputs=registry_inputs, active_board_id=snapshot.active_board_id,
        media_rasters=media_rasters, media_view=media_view)
    paper = (f'<rect x="{_n(layout.canvas.x)}" y="{_n(layout.canvas.y)}" '
             f'width="{_n(layout.canvas.width)}" height="{_n(layout.canvas.height)}" '
             f'fill="{style.colors["paper"]}"/>')
    width, height = layout.output_profile.width, layout.output_profile.height
    viewport = snapshot.camera
    code_bundle = (_code_font_inputs(root, resources)
                   if any(isinstance(obj, TextObject) and obj.object_type == "code"
                          for obj in objects.values()) else None)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
           f'viewBox="{_n(viewport.x)} {_n(viewport.y)} '
           f'{_n(viewport.width)} {_n(viewport.height)}">'
           f'<defs><style>{_font_css(style, root, frozen_files=resources[2] if resources else None, code_bundle=code_bundle)}</style>'
           f'{definitions}</defs>{paper}{tree}</svg>')
    return SVGFrame(at_ms=at_ms, width=width, height=height, svg=svg)


def _compose_object_tree(objects, states, paint_ordinals, style, root, scale_x,
                         active_verbs, raster_images, evidence_treatments,
                         split_envelopes, resources, *, included_ids=None, registry_inputs=None,
                         active_board_id=None, captured_aperture_subset=None, media_rasters=None, media_view=None):
    """Shared native tree paint; callers own authentication and viewport framing.

    No backing paper is added here. An isolated proof can select one captured
    closure plus its ancestors without painting unrelated siblings; aperture
    definitions still use the exact supplied captured dependency state.
    """
    definitions = []
    validate_character_assembly_map(objects)
    validate_illustration_assembly_map(objects)
    if registry_inputs is None:
        registry_inputs = registry_endpoint_inputs_for_objects(objects,
            frozen_files=resources[2] if resources is not None else None)
    tree_objects = objects
    definition_states = states.values()
    if included_ids is not None:
        if not set(included_ids).issubset(objects):
            raise ValueError("Selected paint tree is missing captured objects")
        tree_objects = {key: obj for key, obj in objects.items() if key in included_ids}
        if any(key not in states or key not in paint_ordinals for key in tree_objects):
            raise ValueError("Selected paint tree requires captured state and paint ordinals")
        if any(obj.parent_id is not None and obj.parent_id not in tree_objects for obj in tree_objects.values()):
            raise ValueError("Selected paint tree requires its complete captured ancestor chain")
        definition_states = (states[key] for key in tree_objects)
    # Local primitive alpha is not a sampled-world proof. Both the normal tree
    # and frozen selected-closure path authenticate the actual full hierarchy
    # before any bound artwork paints, including hidden records in that tree.
    transforms = {key: state.transform for key, state in states.items()}
    try:
        projections = external_aperture_projections(objects, states,
            active_board=active_board_id, captured_subset=captured_aperture_subset, media_view=media_view)
    except (UnsupportedExternalAperture, ValueError) as exc:
        raise UnsupportedVisualObject(str(exc)) from exc
    external_definitions = {}
    for projection in projections:
        name = "external-aperture-" + hashlib.sha256(projection.consumer_id.encode("utf-8")).hexdigest()
        full = lambda value: format(value, ".17g") if value else "0"
        if projection.source_id is None:
            points = " ".join(f"{full(x)},{full(y)}" for x, y in projection.corners)
            definitions.append(f'<clipPath id="{name}" clipPathUnits="userSpaceOnUse">'
                               f'<polygon points="{points}"/></clipPath>')
            attribute = "clip-path"
        else:
            source = geometry_object(objects[projection.source_id], states[projection.source_id].morph_geometry)
            matrix = projection.relative
            coefficients = " ".join(full(value) for value in (matrix.a, matrix.b, matrix.c, matrix.d, matrix.e, matrix.f))
            xs, ys = zip(*projection.corners)
            x, y, width, height = min(xs)-2, min(ys)-2, max(xs)-min(xs)+4, max(ys)-min(ys)+4
            definitions.append(f'<mask id="{name}" maskUnits="userSpaceOnUse" maskContentUnits="userSpaceOnUse" '
                               f'x="{full(x)}" y="{full(y)}" width="{full(width)}" height="{full(height)}" '
                               f'style="mask-type:alpha"><g transform="matrix({coefficients})">'
                               f'{_shape(source, "none", "#ffffff", 0)}</g></mask>')
            attribute = "mask"
        external_definitions[projection.consumer_id] = (attribute, name)

    def externally_clipped(obj, markup):
        if obj.object_id not in external_definitions or not markup:
            return markup
        attribute, name = external_definitions[obj.object_id]
        return f'<g {attribute}="url(#{name})">{markup}</g>'

    for obj in tree_objects.values():
        if isinstance(obj, VisualObject) and obj.technical_frame is not None:
            from atme.render.v2_technical_frame_lifecycle import (
                validate_technical_frame_sample,
            )

            validate_technical_frame_sample(obj, objects, states)
        if isinstance(obj, VisualObject) and obj.registry_binding is not None:
            asset, _ = _registry_art(obj, resources)
            try:
                validate_registry_world_binding(obj, asset, objects, transforms)
            except ValueError as exc:
                raise UnsupportedVisualObject(str(exc)) from exc
    mask_sources = {obj.mask_source_object_id for obj in tree_objects.values()
                    if isinstance(obj, MaskContainer)}
    children: dict[str | None, list] = {}
    for obj in tree_objects.values():
        children.setdefault(obj.parent_id, []).append(obj)
    for siblings in children.values():
        siblings.sort(key=lambda item: paint_ordinals[item.object_id])
    for state in definition_states:
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
        construction = split_envelopes.get(state.object_id)
        local_split_clip = construction is not None and construction.root_id != state.object_id
        if 0 < state.reveal_fraction < 1 and (local_split_clip or active_verbs.get(state.object_id) not in {
            "draw", "write", "progressive_reveal", "connect", "disconnect"
        }):
            bounds = obj.geometry.bounds
            definitions.append(
                f'<clipPath id="{_clip_id(obj.object_id)}">'
                f'<rect x="{_n(bounds.x)}" y="{_n(bounds.y)}" '
                f'width="{_n(bounds.width * state.reveal_fraction)}" '
                f'height="{_n(bounds.height)}"/></clipPath>'
            )
    def render_object(obj) -> str:
        if included_ids is not None and obj.object_id not in included_ids:
            return ""
        if obj.object_id in mask_sources:
            return ""
        state = states[obj.object_id]
        construction = split_envelopes.get(obj.object_id)
        if isinstance(obj, ContainerObject):
            if not state.visible or state.opacity <= 0 or state.reveal_fraction <= 0:
                return ""
            inner = "".join(render_object(child) for child in children.get(obj.object_id, ()))
            if (construction is not None and state.reveal_fraction < 1
                    and (construction.root_id != obj.object_id or construction.mode in {"reveal", "enter"})):
                inner = f'<g clip-path="url(#{_clip_id(obj.object_id)})">{inner}</g>'
            if isinstance(obj, MaskContainer):
                # Aperture stays in parent-local coordinates; content moves beneath it.
                return (f'<g data-object-id="{_xml_escape(obj.object_id)}" '
                        f'mask="url(#{_container_mask_id(obj.object_id)})" '
                        f'opacity="{_n(state.opacity)}">'
                        f'<g transform="{_object_transform(obj, state)}">{inner}</g></g>')
            clip = (f' clip-path="url(#{_container_clip_id(obj.object_id)})"'
                    if obj.object_type == "clip" else "")
            return externally_clipped(obj, (f'<g data-object-id="{_xml_escape(obj.object_id)}" '
                    f'transform="{_object_transform(obj, state)}" '
                    f'opacity="{_n(state.opacity)}"{clip}>{inner}</g>'))
        return externally_clipped(obj, _object_markup(obj, state, style, root, scale_x,
                              active_verbs.get(obj.object_id), objects, states,
                              raster_images, evidence_treatments, construction, resources, registry_inputs,
                              media_rasters, media_view))

    return "".join(definitions), "".join(render_object(obj) for obj in children.get(None, ()))


def compose_png_frame(layout_document: dict, timeline_document: dict, at_ms: int,
                      asset_bytes: dict[str, bytes | VerifiedEvidenceBytes] | None = None) -> PNGFrame:
    """Rasterize a supported frame with verified, pinned fonts and no system-font fallback."""
    frame = compose_svg_frame(layout_document, timeline_document, at_ms, asset_bytes)
    return _rasterize_svg_frame(ExecutableLayoutV2.model_validate(layout_document), frame)


def _rasterize_svg_frame(layout: ExecutableLayoutV2, frame: SVGFrame, *, split_inputs=None) -> PNGFrame:
    """The same pinned offline rasterizer for public frames and private proofs."""
    import resvg_py

    def raster(font_files):
        return bytes(resvg_py.svg_to_bytes(
            svg_string=frame.svg, width=frame.width, height=frame.height,
            font_files=font_files, skip_system_fonts=True,
        ))

    if split_inputs is None:
        style, _, root = resolve_contract_bundle(layout.style_system_version, layout.asset_registry_version)
        has_code = any(isinstance(obj, TextObject) and obj.object_type == "code" for obj in layout.objects)
        has_chart = any(isinstance(obj, VisualObject) and obj.chart_payload is not None for obj in layout.objects)
        if has_code or has_chart:
            code_bundle = load_code_font_bundle(root) if has_code else None
            files = {}
            for font in style.fonts:
                payload = (root / font.file).read_bytes()
                if hashlib.sha256(payload).hexdigest() != font.sha256:
                    raise UnsupportedVisualObject("native frame pinned font checksum mismatch")
                files[font.file] = payload
            if code_bundle is not None:
                files.update({name: payload for name, _, payload in code_bundle.files})
            # All actual native font paths are isolated copies of checked bytes,
            # never mutable original files reopened by resvg after verification.
            return _rasterize_frozen_svg(frame, style, files)
        png = raster([str(root / font.file) for font in style.fonts])
    else:
        from atme.render.v2_split_paint import _checked_split_resources

        style, _, files, _ = _checked_split_resources(layout, split_inputs)
        return _rasterize_frozen_svg(frame, style, files)
    return PNGFrame(at_ms=frame.at_ms, width=frame.width, height=frame.height, png=png)


def _rasterize_frozen_svg(frame: SVGFrame, style, files) -> PNGFrame:
    """Shared private raster path after frozen resource verification."""
    with _frozen_svg_rasterizer(style, files) as rasterize:
        return rasterize(frame)


@contextmanager
def _frozen_svg_rasterizer(style, files):
    """One checked font lifetime for a frame or a streaming coverage scan."""
    import resvg_py

    # resvg accepts file paths, not font bytes. Materialize only frozen
    # checked fonts in an isolated lifetime; never reopen the source bundle.
    with TemporaryDirectory(prefix="atme-split-fonts-") as directory:
        paths = []
        fonts = list(style.fonts)
        from atme.render.code_font_bundle import (
            CODE_FONT_MANIFEST,
            CodeFontManifest,
            verify_code_font_bundle,
        )

        if CODE_FONT_MANIFEST in files:
            code_bundle = verify_code_font_bundle(files.__getitem__)
            fonts.append(CodeFontManifest.model_validate_json(code_bundle.manifest_json).font)
        for index, font in enumerate(fonts):
            path = Path(directory) / str(index) / Path(font.file).name
            path.parent.mkdir()
            path.write_bytes(files[font.file])
            paths.append(str(path))
        def rasterize(frame):
            png = bytes(resvg_py.svg_to_bytes(svg_string=frame.svg, width=frame.width, height=frame.height,
                                             font_files=paths, skip_system_fonts=True))
            return PNGFrame(at_ms=frame.at_ms, width=frame.width, height=frame.height, png=png)
        yield rasterize
