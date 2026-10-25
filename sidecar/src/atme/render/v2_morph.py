"""Authored geometry correspondence for deterministic Paper & Ink morphs."""

from __future__ import annotations

import math
from dataclasses import dataclass

from atme.render.v2_path import MAX_COORDINATE, InvalidFreehandPath, parse_freehand_path
from atme.store.contracts_v2 import Bounds, MarkObject, MorphPolicy


class UnsupportedMorph(ValueError):
    """The declared geometry correspondence cannot be executed faithfully."""


@dataclass(frozen=True)
class MorphGeometry:
    bounds: tuple[float, float, float, float]
    svg_d: str


def _n(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".") if value else "0"


def _mix(a: float, b: float, p: float) -> float:
    return a + (b - a) * p


def geometry_object(obj: MarkObject, geometry: MorphGeometry | None):
    """Use identical interpolated bounds for SVG pivots and world geometry."""
    if geometry is None:
        return obj
    x, y, width, height = geometry.bounds
    return obj.model_copy(update={"geometry": obj.geometry.model_copy(update={
        "bounds": Bounds(x=x, y=y, width=width, height=height),
    })})


def _bounds(obj):
    bounds = obj.geometry.bounds
    values = (bounds.x, bounds.y, bounds.width, bounds.height)
    if any(abs(value) > MAX_COORDINATE for value in values):
        raise UnsupportedMorph("morph bounds exceed the supported coordinate range")
    return values


def _outline(obj):
    x, y, w, h = _bounds(obj)
    if obj.object_type == "ellipse":
        rx, ry = w / 2, h / 2
    else:
        rx = ry = obj.geometry.corner_radius or 0.0
    # Four exact elliptical arcs alternate with four straight sides. A box
    # uses zero-radius arcs; an ellipse uses zero-length sides. No sampling,
    # approximate cubic ellipse, or automatic vertex matching is involved.
    return (
        ("M", (x + rx, y)), ("L", (x + w - rx, y)),
        ("A", (rx, ry, 0, 0, 1, x + w, y + ry)),
        ("L", (x + w, y + h - ry)),
        ("A", (rx, ry, 0, 0, 1, x + w - rx, y + h)),
        ("L", (x + rx, y + h)),
        ("A", (rx, ry, 0, 0, 1, x, y + h - ry)),
        ("L", (x, y + ry)), ("A", (rx, ry, 0, 0, 1, x + rx, y)),
        ("Z", ()),
    )


def _commands(obj, policy):
    if policy.mapping == "canonical_outline":
        if obj.object_type not in {"rectangle", "rounded_rectangle", "ellipse"}:
            raise UnsupportedMorph("canonical outline morph needs a box or ellipse")
        if obj.geometry.points or obj.path_data:
            raise UnsupportedMorph("canonical outline morph has ignored authored path data")
        radius = obj.geometry.corner_radius
        if obj.object_type == "rounded_rectangle":
            if radius is None or not 0 < radius <= min(_bounds(obj)[2:]) / 2:
                raise UnsupportedMorph("rounded morph outline has an invalid corner radius")
        elif radius is not None:
            raise UnsupportedMorph("morph outline has an ignored corner radius")
        return _outline(obj)
    if policy.mapping == "ordered_vertices":
        if (obj.object_type not in {"polygon", "line", "freehand"} or obj.path_data
                or obj.geometry.corner_radius is not None):
            raise UnsupportedMorph("ordered morph needs authored polygon, line, or freehand points")
        points = obj.geometry.points
        if (len(points) != policy.point_count or obj.object_type == "polygon" and len(points) < 3
                or obj.object_type == "line" and len(points) != 2):
            raise UnsupportedMorph("ordered morph point count does not match authored geometry")
        x, y, w, h = _bounds(obj)
        if any(not (x <= p.x <= x + w and y <= p.y <= y + h) for p in points):
            raise UnsupportedMorph("ordered morph points exceed authored bounds")
        result = tuple(("M" if i == 0 else "L", (p.x, p.y)) for i, p in enumerate(points))
        if obj.object_type == "polygon":
            result += (("Z", ()),)
        return result
    if (obj.object_type != "freehand" or obj.geometry.points
            or obj.geometry.corner_radius is not None or not obj.path_data):
        raise UnsupportedMorph("path morph needs authored freehand command data")
    try:
        result = parse_freehand_path(obj.path_data, obj.geometry.bounds).commands
    except InvalidFreehandPath as exc:
        raise UnsupportedMorph(str(exc)) from exc
    if [command for command, _ in result] != policy.path_commands:
        raise UnsupportedMorph("morph command sequence differs from authored correspondence")
    return result


def _reject_collapsed_stroke(a, b):
    # All control/endpoints vary linearly. If they can coincide at one common
    # time, the stroke disappears; reject the action before any seek executes.
    ap = [values[i:i + 2] for _, values in a for i in range(0, len(values), 2)]
    bp = [values[i:i + 2] for _, values in b for i in range(0, len(values), 2)]
    equations = []
    for first, second in zip(ap[1:], bp[1:], strict=True):
        for axis in (0, 1):
            start = first[axis] - ap[0][axis]
            end = second[axis] - bp[0][axis]
            equations.append((start, end - start))
    changing = next(((start, delta) for start, delta in equations if abs(delta) > 1e-9), None)
    if changing is None:
        collapsed = all(abs(start) < 1e-9 for start, _ in equations)
    else:
        moment = -changing[0] / changing[1]
        collapsed = 0 <= moment <= 1 and all(
            abs(start + delta * moment) < 1e-9 for start, delta in equations
        )
    if collapsed:
        raise UnsupportedMorph("morph correspondence collapses the complete stroke")


def validate_morph_geometry(source, destination, policy: MorphPolicy):
    if not isinstance(source, MarkObject) or not isinstance(destination, MarkObject):
        raise UnsupportedMorph("morph requires authored mark geometry")
    if source.style != destination.style or source.asset_id or destination.asset_id:
        raise UnsupportedMorph("morph requires shared style tokens and no asset substitution")
    _bounds(source)
    _bounds(destination)
    if (policy.mapping != "canonical_outline"
            and source.object_type != destination.object_type):
        raise UnsupportedMorph("morph correspondence cannot change open/closed path topology")
    a, b = _commands(source, policy), _commands(destination, policy)
    if tuple((cmd, len(values)) for cmd, values in a) != tuple(
        (cmd, len(values)) for cmd, values in b
    ):
        raise UnsupportedMorph("morph command/control-point topology is incompatible")
    if policy.mapping != "canonical_outline":
        _reject_collapsed_stroke(a, b)
    return a, b


def interpolate_geometry(source, destination, policy: MorphPolicy, progress: float) -> MorphGeometry:
    if not math.isfinite(progress) or not 0 <= progress <= 1:
        raise UnsupportedMorph("morph progress must be finite and within its action")
    a, b = validate_morph_geometry(source, destination, policy)
    commands = []
    for (command, start), (_, end) in zip(a, b, strict=True):
        values = [_mix(first, second, progress) for first, second in zip(start, end, strict=True)]
        commands.append(command + (" " + " ".join(_n(value) for value in values) if values else ""))
    bounds = tuple(_mix(first, second, progress)
                   for first, second in zip(_bounds(source), _bounds(destination), strict=True))
    # Quantize geometry exactly as SVG does, including the pivot used by the
    # affine resolver. Endpoints are painted by their original authored object.
    return MorphGeometry(tuple(float(_n(value)) for value in bounds), " ".join(commands))
