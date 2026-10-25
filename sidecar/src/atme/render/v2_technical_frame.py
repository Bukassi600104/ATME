"""Original technical chrome, canonical local regions and physical anchors.

Pure native primitive only: content remains real authored scene objects. This
module neither admits a compositor family nor invents content/labels/IDs. World
fitting, readiness and lifecycle are separate consumers of this same geometry.
"""

from dataclasses import dataclass, fields
from math import isfinite
from re import fullmatch
from types import MappingProxyType

from atme.render.v2_hierarchy import HierarchySnapshot
from atme.render.v2_world import _n, _q, world_anchor, world_matrix
from atme.store.contracts_v2 import (
    Anchor,
    Bounds,
    ClipContainer,
    ConnectorObject,
    Geometry,
    GroupContainer,
    MarkObject,
    MaskContainer,
    Point,
    StyleRefs,
    TechnicalAnchorMapping,
    TechnicalFrameBinding,
    TechnicalRoleBinding,
    TextObject,
    Transform,
    VisualObject,
    _validate_technical_frames,
)

# Native v1 coordinates. Each tuple is original structural chrome, not a
# template for authored narrative content. Full precision meet-fit is shared
# by paint, role regions and explicitly named boundary anchors.
_REGIONS = MappingProxyType({
    "browser": (("title", 170, 20, 790, 60), ("address", 80, 125, 880, 50), ("content", 40, 220, 920, 340)),
    "application": (("title", 130, 25, 830, 45), ("navigation", 35, 120, 180, 440), ("content", 275, 120, 690, 440)),
    "server": (("title", 120, 25, 760, 70), ("content", 120, 145, 650, 400)),
    "database": (("title", 220, 55, 560, 80), ("content", 140, 190, 620, 285)),
    "folder": (("title", 80, 65, 260, 40), ("content", 130, 260, 730, 275)),
    "comparison": (("left_title", 60, 20, 360, 70), ("left_content", 60, 130, 360, 390),
                   ("right_title", 580, 20, 360, 70), ("right_content", 580, 130, 360, 390)),
})
_ANCHORS = MappingProxyType({
    "browser": (("top", 500, 10), ("right", 990, 300), ("bottom", 500, 590), ("left", 10, 300)),
    "application": (("top", 500, 10), ("right", 990, 300), ("bottom", 500, 590), ("left", 10, 300)),
    "server": (("top", 500, 10), ("right", 920, 300), ("bottom", 500, 590), ("left", 80, 300)),
    "database": (("top", 500, 25), ("right", 930, 300), ("bottom", 500, 575), ("left", 70, 300)),
    "folder": (("top", 500, 120), ("right", 960, 300), ("bottom", 500, 580), ("left", 40, 300)),
    "comparison": (("top", 500, 100), ("right", 960, 320), ("bottom", 500, 560), ("left", 40, 320)),
})


@dataclass(frozen=True)
class TechnicalFrameGeometry:
    viewport: tuple[float, float, float, float]
    fitted: tuple[float, float, float, float]
    regions: tuple[tuple[str, float, float, float, float], ...]
    anchors: tuple[tuple[str, float, float], ...]


def _known(model, cls):
    if type(model) is not cls or set(model.__dict__) != set(cls.model_fields) or model.model_extra:
        raise ValueError("technical_frame has an unknown or missing native contract payload")


def _checked_chrome(obj):
    _known(obj, VisualObject)
    _known(obj.geometry, Geometry)
    _known(obj.geometry.bounds, Bounds)
    _known(obj.style, StyleRefs)
    _known(obj.transform, Transform)
    _known(obj.transform.position, Point)
    _known(obj.transform.origin, Point)
    _known(obj.technical_frame, TechnicalFrameBinding)
    for row in obj.technical_frame.roles:
        _known(row, TechnicalRoleBinding)
    for row in obj.technical_frame.anchor_mappings:
        _known(row, TechnicalAnchorMapping)
    for anchor in obj.anchors:
        _known(anchor, Anchor)
        _known(anchor.point, Point)
    VisualObject.model_validate(obj.model_dump(mode="json"))
    if (obj.geometry.points or obj.geometry.corner_radius is not None or obj.asset_id is not None
            or obj.style.text is not None or obj.style.effect is not None):
        raise ValueError("technical_frame native chrome cannot discard points/radius/asset/text/effect")


def technical_frame_geometry(obj: VisualObject) -> TechnicalFrameGeometry:
    """Project the exact native v1 geometry into a q4 serialized SVG viewport."""
    _checked_chrome(obj)
    bounds = obj.geometry.bounds
    x, y, width, height = map(_q, (bounds.x, bounds.y, bounds.width, bounds.height))
    if width <= 0 or height <= 0:
        raise ValueError("technical_frame serialized native viewport collapses")
    scale = min(width / 1000, height / 600)
    fit_width, fit_height = 1000 * scale, 600 * scale
    fit_x, fit_y = x + (width - fit_width) / 2, y + (height - fit_height) / 2
    regions = tuple((role, fit_x + rx * scale, fit_y + ry * scale, rw * scale, rh * scale)
        for role, rx, ry, rw, rh in _REGIONS[obj.object_type])
    anchors = tuple((name, fit_x + ax * scale, fit_y + ay * scale)
        for name, ax, ay in _ANCHORS[obj.object_type])
    for row in regions + anchors:
        for value in row[1:]:
            _q(value)
    return TechnicalFrameGeometry((x, y, width, height), (fit_x, fit_y, fit_width, fit_height), regions, anchors)


def validate_technical_frame_local(obj: VisualObject) -> TechnicalFrameGeometry:
    """Local endpoint proof only; do not substitute this for sampled world fit."""
    geometry = technical_frame_geometry(obj)
    expected = {name: (x, y) for name, x, y in geometry.anchors}
    declared = {anchor.anchor_id: anchor.point for anchor in obj.anchors}
    x, y, width, height = geometry.viewport
    for mapping in obj.technical_frame.anchor_mappings:
        point = declared[mapping.placed_anchor_id]
        actual = (x + width * point.x, y + height * point.y)
        if tuple(map(_q, actual)) != tuple(map(_q, expected[mapping.native_anchor_name])):
            raise ValueError("technical_frame placed anchor does not match physical native anchor")
    return geometry


def _sampled_inputs(objects, transforms):
    # Deferred import: the owning state evaluator may consume this pure seam.
    from atme.render.v2_state import FramePoint, FrameTransform

    if (type(objects) is not dict or type(transforms) is not dict or not objects
            or objects.keys() != transforms.keys()
            or any(key != obj.object_id for key, obj in objects.items())):
        raise ValueError("technical_frame needs every exact actual object and sampled transform")
    for key, obj in objects.items():
        if type(obj) not in {MarkObject, TextObject, VisualObject, ConnectorObject,
                             GroupContainer, ClipContainer, MaskContainer}:
            raise ValueError("technical_frame sampled hierarchy has an unknown node type")
        _known(obj, type(obj))
        type(obj).model_validate(obj.model_dump(mode="json"))
        _known(obj.geometry, Geometry)
        _known(obj.geometry.bounds, Bounds)
        pose = transforms[key]
        if type(pose) is Transform:
            _known(pose, Transform)
            _known(pose.position, Point)
            _known(pose.origin, Point)
            Transform.model_validate(pose.model_dump(mode="json"))
        elif (type(pose) is not FrameTransform or set(pose.__dict__) != {field.name for field in fields(FrameTransform)}
                or any(type(point) is not FramePoint or set(point.__dict__) != {"x", "y"}
                       for point in (pose.position, pose.origin))):
            raise ValueError("technical_frame needs exact known current transform payloads")
        values = (pose.position.x, pose.position.y, pose.origin.x, pose.origin.y,
                  pose.rotation_degrees, pose.scale_x, pose.scale_y)
        if (any(type(value) not in {int, float} or not isfinite(value) for value in values)
                or pose.scale_x <= 0 or pose.scale_y <= 0):
            raise ValueError("technical_frame current transform requires finite non-boolean numbers and positive scales")
    HierarchySnapshot.from_objects(objects)
    _validate_technical_frames(objects, semantic=False)


def _world_quad(bounds, matrix, *, serialized):
    x, y, width, height = tuple(map(_q, bounds)) if serialized else bounds
    if width <= 0 or height <= 0:
        raise ValueError("technical_frame role geometry collapses")
    return tuple(tuple(map(_q, matrix.point(px, py)))
        for px, py in ((x, y), (x + width, y), (x + width, y + height), (x, y + height)))


def _inside_native_quad(points, quad):
    # Exact integer q4 grid, not a floating epsilon or axis-aligned box. An
    # authored part on a rotated boundary must fit the serialized world region.
    grid = lambda point: tuple(round(value * 10000) for value in point)
    edges = tuple(map(grid, quad))
    def cross(a, b, point):
        return (b[0] - a[0]) * (point[1] - a[1]) - (b[1] - a[1]) * (point[0] - a[0])
    if cross(edges[0], edges[1], edges[2]) <= 0 or cross(edges[0], edges[2], edges[3]) <= 0:
        raise ValueError("technical_frame sampled native region collapses")
    return all(cross(edges[index], edges[(index + 1) % 4], grid(point)) >= 0
               for point in points for index in range(4))


def validate_technical_frame_world(obj: VisualObject, objects: dict, transforms: dict) -> tuple:
    """Actual sampled role quadrilaterals and full-chain physical endpoints.

    No visibility, alpha, ready-state or camera claim is inferred here. Those
    consumers must supply this same actual hierarchy and their own lifecycle.
    """
    geometry = validate_technical_frame_local(obj)
    if objects.get(obj.object_id) != obj:
        raise ValueError("technical_frame sampled map has a different or missing chrome")
    _sampled_inputs(objects, transforms)
    matrix = world_matrix(obj, objects, transforms)
    canonical = {name: (x, y) for name, x, y in geometry.anchors}
    endpoints = []
    for mapping in obj.technical_frame.anchor_mappings:
        expected = tuple(map(_q, matrix.point(*canonical[mapping.native_anchor_name])))
        actual = tuple(map(_q, world_anchor(obj, mapping.placed_anchor_id, objects, transforms)))
        if actual != expected:
            raise ValueError("technical_frame placed anchor differs from physical sampled world anchor")
        endpoints.append((mapping.placed_anchor_id, actual))
    regions = {row[0]: row[1:] for row in geometry.regions}
    for role in obj.technical_frame.roles:
        region = _world_quad(regions[role.role], matrix, serialized=False)
        pending = [role.object_id]
        while pending:
            key = pending.pop()
            part = objects[key]
            bounds = part.geometry.bounds
            corners = _world_quad((bounds.x, bounds.y, bounds.width, bounds.height),
                                  world_matrix(part, objects, transforms), serialized=True)
            if not _inside_native_quad(corners, region):
                raise ValueError(f"technical_frame part {key} is outside its physical native {role.role} region")
            if type(part) is GroupContainer:
                pending.extend(part.child_ids)
    return tuple(endpoints)


def _window_shell():
    return '<rect x="10" y="10" width="980" height="580" rx="20"/>'


def _state_cue(state, x, y):
    if state == "ready":
        return f'<path d="M{x-11} {y}L{x} {y+11}L{x+17} {y-11}"/>'
    if state in {"loading", "busy"}:
        return f'<path d="M{x-14} {y+10}A17 17 0 1 1 {x+16} {y+5}"/>'
    return f'<path d="M{x-13} {y-13}L{x+13} {y+13}M{x+13} {y-13}L{x-13} {y+13}"/>'


def _chrome_paths(kind, state, stroke):
    if kind == "browser":
        return (_window_shell() + '<path d="M10 100H990"/>'
            '<circle cx="45" cy="50" r="9"/><circle cx="80" cy="50" r="9"/><circle cx="115" cy="50" r="9"/>'
            '<rect x="24" y="125" width="952" height="52" rx="12"/>' + _state_cue(state, 40, 150))
    if kind == "application":
        return _window_shell() + '<path d="M10 90H990M240 90V590"/>' + _state_cue(state, 55, 45)
    if kind == "server":
        fill = stroke if state == "active" else "none"
        lights = f'<g fill="{fill}"><circle cx="835" cy="180" r="13"/><circle cx="835" cy="300" r="13"/><circle cx="835" cy="420" r="13"/></g>'
        return ('<rect x="80" y="10" width="840" height="580" rx="20"/>'
            '<path d="M120 120H880M800 120V550"/>' + lights
            + ('<path d="M810 155L860 445M860 155L810 445"/>' if state == "offline" else ""))
    if kind == "database":
        fill = stroke if state == "active" else "none"
        return ('<ellipse cx="500" cy="95" rx="430" ry="70"/>'
            '<path d="M70 95V505C70 598.3333 930 598.3333 930 505V95"/>'
            f'<circle cx="845" cy="105" r="15" fill="{fill}"/>'
            + ('<path d="M822 82L868 128M868 82L822 128"/>' if state == "offline" else ""))
    if kind == "folder":
        back = '<path d="M40 180V65Q40 40 65 40H365L435 120H935Q960 120 960 145V555Q960 580 935 580H65Q40 580 40 555Z"/>'
        front = ('<path d="M40 220H960"/>' if state == "closed" else
            '<path d="M40 580L110 220H985L960 555Q957 580 935 580Z"/>')
        return back + front
    if kind == "comparison":
        cue = ('<path d="M160 105H320M680 105H840"/>' if state == "balanced" else
            '<path d="M100 105H380M740 105H800M480 270L520 310L480 350L520 390"/>')
        return '<path d="M460 80H40V560H460M540 80H960V560H540M500 100V560"/>' + cue
    raise ValueError("technical_frame native chrome kind is not implemented")


def technical_frame_svg(obj: VisualObject, *, stroke: str, fill: str, stroke_width: float) -> str:
    """Paint structural chrome only; shared compositor paints real parts once."""
    geometry = validate_technical_frame_local(obj)
    if (type(stroke) is not str or fullmatch(r"#[a-fA-F0-9]{6}", stroke) is None
            or type(fill) is not str or fill != "none" and fullmatch(r"#[a-fA-F0-9]{6}", fill) is None
            or type(stroke_width) not in {int, float} or not isfinite(stroke_width) or not 0 < stroke_width <= 32):
        raise ValueError("technical_frame paint requires explicit safe colors and finite supported stroke")
    x, y, width, height = geometry.viewport
    scale = geometry.fitted[2] / 1000
    native_weight = _q(stroke_width / scale)
    if native_weight <= 0:
        raise ValueError("technical_frame serialized native stroke collapses")
    inner = _chrome_paths(obj.object_type, obj.technical_frame.display_state, stroke)
    return (f'<svg x="{_n(x)}" y="{_n(y)}" width="{_n(width)}" height="{_n(height)}" '
        'viewBox="0 0 1000 600" preserveAspectRatio="xMidYMid meet" overflow="visible">'
        f'<g fill="{fill}" stroke="{stroke}" stroke-width="{_n(native_weight)}" '
        f'stroke-linecap="round" stroke-linejoin="round">{inner}</g></svg>')
