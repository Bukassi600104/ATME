"""Bounded parent-local geometry checks for static v2 alpha masks."""

from __future__ import annotations

import math

from atme.render.v2_world import (
    MAX_WORLD_COMPONENT,
    UnsupportedWorldGeometry,
    local_matrix,
)
from atme.store.contracts_v2 import MASK_SOURCE_TYPES, MarkObject


class UnsupportedMask(ValueError):
    """A mask cannot be rendered without inventing alpha semantics."""


def _q(value: float) -> float:
    if not math.isfinite(value) or abs(value) > MAX_WORLD_COMPONENT:
        raise UnsupportedMask("mask geometry exceeds the supported coordinate range")
    return float(f"{value:.4f}")


def mask_source_region(source: MarkObject, transform) -> tuple[float, float, float, float]:
    """Return a padded mask region in the mask parent's local coordinates."""
    if source.object_type not in MASK_SOURCE_TYPES:
        raise UnsupportedMask(f"mask source {source.object_id} needs supported filled geometry")
    if (source.path_data is not None or source.anchors or source.style.stroke
            or source.style.fill or source.style.text or source.style.effect):
        raise UnsupportedMask(f"mask source {source.object_id} cannot carry painted style or path data")
    bounds = source.geometry.bounds
    x, y, width, height = map(_q, (bounds.x, bounds.y, bounds.width, bounds.height))
    if width <= 0 or height <= 0:
        raise UnsupportedMask(f"mask source {source.object_id} has collapsed geometry")
    radius = source.geometry.corner_radius
    if source.object_type == "rounded_rectangle":
        if radius is None or not 0 < _q(radius) <= min(width, height) / 2:
            raise UnsupportedMask(f"mask source {source.object_id} has invalid corner radius")
    elif radius is not None:
        raise UnsupportedMask(f"mask source {source.object_id} has ignored corner radius")
    points = source.geometry.points
    if source.object_type == "polygon":
        if not 3 <= len(points) <= 257:
            raise UnsupportedMask(f"mask source {source.object_id} needs 3–257 polygon points")
        xy = [(_q(point.x), _q(point.y)) for point in points]
        if any(not (x <= px <= x + width and y <= py <= y + height) for px, py in xy):
            raise UnsupportedMask(f"mask source {source.object_id} polygon exceeds bounds")
        doubled_area = sum(a[0] * b[1] - b[0] * a[1]
                           for a, b in zip(xy, [*xy[1:], xy[0]]))
        if not math.isfinite(doubled_area) or abs(doubled_area) <= 0.0001:
            raise UnsupportedMask(f"mask source {source.object_id} polygon has no area")
    elif points:
        raise UnsupportedMask(f"mask source {source.object_id} has ignored points")
    try:
        matrix = local_matrix(source, transform)
        corners = [matrix.point(px, py) for px in (x, x + width)
                   for py in (y, y + height)]
    except UnsupportedWorldGeometry as exc:
        raise UnsupportedMask(str(exc)) from exc
    left = min(px for px, _ in corners)
    top = min(py for _, py in corners)
    right = max(px for px, _ in corners)
    bottom = max(py for _, py in corners)
    # Include raster antialiasing while avoiding SVG's 120%-sized default mask region.
    region = (_q(math.floor((left - 1) * 10_000) / 10_000),
              _q(math.floor((top - 1) * 10_000) / 10_000),
              _q(math.ceil((right + 1) * 10_000) / 10_000),
              _q(math.ceil((bottom + 1) * 10_000) / 10_000))
    if _q(region[2] - region[0]) <= 0 or _q(region[3] - region[1]) <= 0:
        raise UnsupportedMask(f"mask source {source.object_id} has collapsed transformed region")
    return (region[0], region[1], _q(region[2] - region[0]),
            _q(region[3] - region[1]))
