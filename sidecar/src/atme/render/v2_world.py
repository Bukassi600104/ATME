"""Shared affine geometry for v2 authored groups, camera, and connector anchors.

An object's bounds and anchors are authored in board coordinates. Its local
transform and each ancestor group's transform are composed in SVG nesting
order. Components are serialized to four decimals before composition, matching
the SVG emitted by the compositor.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, isfinite, radians, sin


class UnsupportedWorldGeometry(ValueError):
    """An authored transform cannot be projected faithfully into the frame."""


MAX_WORLD_COMPONENT = 1_000_000


def _n(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".") if value else "0"


def _q(value: float) -> float:
    if not isfinite(value) or abs(value) > MAX_WORLD_COMPONENT:
        raise UnsupportedWorldGeometry("world component is outside the supported range")
    return float(_n(value))


@dataclass(frozen=True)
class Affine:
    a: float = 1.0
    b: float = 0.0
    c: float = 0.0
    d: float = 1.0
    e: float = 0.0
    f: float = 0.0

    def __matmul__(self, other: Affine) -> Affine:
        result = Affine(
            self.a * other.a + self.c * other.b,
            self.b * other.a + self.d * other.b,
            self.a * other.c + self.c * other.d,
            self.b * other.c + self.d * other.d,
            self.a * other.e + self.c * other.f + self.e,
            self.b * other.e + self.d * other.f + self.f,
        )
        result.validate()
        return result

    def validate(self) -> None:
        if not all(isfinite(value) and abs(value) <= MAX_WORLD_COMPONENT for value in (
            self.a, self.b, self.c, self.d, self.e, self.f
        )):
            raise UnsupportedWorldGeometry("world affine is outside the supported range")

    def point(self, x: float, y: float) -> tuple[float, float]:
        result = (self.a * x + self.c * y + self.e,
                  self.b * x + self.d * y + self.f)
        if not all(isfinite(value) and abs(value) <= MAX_WORLD_COMPONENT for value in result):
            raise UnsupportedWorldGeometry("world point is outside the supported range")
        return result


def _translation(x: float, y: float) -> Affine:
    return Affine(e=x, f=y)


def local_matrix(obj, transform) -> Affine:
    bounds = obj.geometry.bounds
    if (_q(transform.scale_x) <= 0 or _q(transform.scale_y) <= 0
            or abs(transform.rotation_degrees) > MAX_WORLD_COMPONENT):
        raise UnsupportedWorldGeometry("world transform is collapsed or outside the supported range")
    origin_x = _q(bounds.x + bounds.width * transform.origin.x)
    origin_y = _q(bounds.y + bounds.height * transform.origin.y)
    angle = radians(_q(transform.rotation_degrees))
    rotation = Affine(cos(angle), sin(angle), -sin(angle), cos(angle))
    scaling = Affine(a=_q(transform.scale_x), d=_q(transform.scale_y))
    return (_translation(_q(transform.position.x), _q(transform.position.y))
            @ _translation(origin_x, origin_y) @ rotation @ scaling
            @ _translation(-origin_x, -origin_y))


def transform_svg(obj, transform) -> str:
    """Serialize the same transform factors used by ``local_matrix``."""
    local_matrix(obj, transform)
    bounds = obj.geometry.bounds
    origin_x = bounds.x + bounds.width * transform.origin.x
    origin_y = bounds.y + bounds.height * transform.origin.y
    return (f'translate({_n(transform.position.x)} {_n(transform.position.y)}) '
            f'translate({_n(origin_x)} {_n(origin_y)}) '
            f'rotate({_n(transform.rotation_degrees)}) '
            f'scale({_n(transform.scale_x)} {_n(transform.scale_y)}) '
            f'translate({_n(-origin_x)} {_n(-origin_y)})')


def world_matrix(obj, objects: dict, transforms: dict) -> Affine:
    chain = []
    current = obj
    while current is not None:
        chain.append(current)
        current = objects[current.parent_id] if current.parent_id is not None else None
    matrix = Affine()
    for ancestor in reversed(chain):
        matrix = matrix @ local_matrix(ancestor, transforms[ancestor.object_id])
    return matrix


def world_bounds(obj, objects: dict, transforms: dict) -> tuple[float, float, float, float]:
    bounds = obj.geometry.bounds
    matrix = world_matrix(obj, objects, transforms)
    x, y, width, height = (_q(bounds.x), _q(bounds.y),
                           _q(bounds.width), _q(bounds.height))
    if width <= 0 or height <= 0:
        raise UnsupportedWorldGeometry("serialized world bounds collapse to zero area")
    points = [matrix.point(px, py) for px in (x, x + width)
              for py in (y, y + height)]
    return (min(x for x, _ in points), min(y for _, y in points),
            max(x for x, _ in points), max(y for _, y in points))


def world_anchor(obj, anchor_id: str, objects: dict, transforms: dict) -> tuple[float, float]:
    anchor = next(anchor for anchor in obj.anchors if anchor.anchor_id == anchor_id)
    bounds = obj.geometry.bounds
    x = _q(bounds.x) + _q(bounds.width) * anchor.point.x
    y = _q(bounds.y) + _q(bounds.height) * anchor.point.y
    return world_matrix(obj, objects, transforms).point(x, y)
