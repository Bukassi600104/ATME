"""Bounded, data-only freehand paths for the v2 compositor.

Only absolute M/L/Q/C commands are accepted. This is not an SVG/XML passthrough.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from atme.store.contracts_v2 import Bounds

_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_TOKEN = re.compile(rf"\s*,?\s*([MLQC]|{_NUMBER})")
_ARITY = {"M": 2, "L": 2, "Q": 4, "C": 6}
MAX_COORDINATE = 1_000_000
MAX_STROKE_LENGTH = 10_000_000


class InvalidFreehandPath(ValueError):
    """Freehand data cannot be safely and faithfully represented."""


@dataclass(frozen=True)
class FreehandPath:
    svg_d: str
    length: float


def _n(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".") if value else "0"


def _point_on_curve(command: str, points: tuple[tuple[float, float], ...], t: float):
    if command == "Q":
        p0, p1, p2 = points
        return tuple((1 - t) ** 2 * p0[i] + 2 * (1 - t) * t * p1[i] + t ** 2 * p2[i]
                     for i in (0, 1))
    p0, p1, p2, p3 = points
    return tuple((1 - t) ** 3 * p0[i] + 3 * (1 - t) ** 2 * t * p1[i]
                 + 3 * (1 - t) * t ** 2 * p2[i] + t ** 3 * p3[i]
                 for i in (0, 1))


def _curve_length(command: str, points: tuple[tuple[float, float], ...]) -> float:
    # Fixed subdivisions make seek/re-render byte-identical without renderer-specific APIs.
    previous = points[0]
    total = 0.0
    for step in range(1, 65):
        current = _point_on_curve(command, points, step / 64)
        total += math.dist(previous, current)
        previous = current
    return total


def parse_freehand_path(source: str, bounds: Bounds) -> FreehandPath:
    if not source or len(source) > 16384:
        raise InvalidFreehandPath("freehand path must be nonempty and at most 16384 characters")
    tokens = []
    position = 0
    while position < len(source):
        match = _TOKEN.match(source, position)
        if match is None:
            if source[position:].strip() == "":
                break
            raise InvalidFreehandPath("freehand path contains an unsupported command or character")
        tokens.append(match.group(1))
        position = match.end()
        if len(tokens) > 1280:
            raise InvalidFreehandPath("freehand path has too many tokens")
    if not tokens or tokens[0] != "M":
        raise InvalidFreehandPath("freehand path must begin with absolute M")
    cursor = 0
    segment_count = 0
    current = None
    total_length = 0.0
    serialized = []
    while cursor < len(tokens):
        command = tokens[cursor]
        if command not in _ARITY:
            raise InvalidFreehandPath("freehand coordinates need an explicit M, L, Q, or C command")
        if segment_count and command == "M":
            raise InvalidFreehandPath("freehand path must be one continuous stroke")
        arity = _ARITY[command]
        operands = tokens[cursor + 1:cursor + 1 + arity]
        if len(operands) != arity or any(value in _ARITY for value in operands):
            raise InvalidFreehandPath(f"freehand {command} has incomplete coordinates")
        parsed = [float(value) for value in operands]
        if any(not math.isfinite(value) for value in parsed):
            raise InvalidFreehandPath("freehand path coordinates must be finite")
        if any(abs(value) > MAX_COORDINATE for value in parsed):
            raise InvalidFreehandPath("freehand path coordinates exceed the supported range")
        # Length and geometry are measured from exactly the coordinates we emit.
        values = [round(value, 6) for value in parsed]
        points = tuple((values[index], values[index + 1]) for index in range(0, arity, 2))
        if any(not (bounds.x <= x <= bounds.x + bounds.width
                    and bounds.y <= y <= bounds.y + bounds.height) for x, y in points):
            raise InvalidFreehandPath("freehand path exceeds authored bounds")
        if command == "M":
            current = points[0]
        elif command == "L":
            total_length += math.dist(current, points[0])
            current = points[0]
        else:
            total_length += _curve_length(command, (current, *points))
            current = points[-1]
        if not math.isfinite(total_length) or total_length > MAX_STROKE_LENGTH:
            raise InvalidFreehandPath("freehand path length exceeds the supported range")
        serialized.append(f'{command} {" ".join(_n(value) for value in values)}')
        segment_count += 1
        if segment_count > 256:
            raise InvalidFreehandPath("freehand path has too many segments")
        cursor += 1 + arity
    if segment_count < 2 or total_length <= 0:
        raise InvalidFreehandPath("freehand path must draw a nonzero continuous stroke")
    return FreehandPath(svg_d=" ".join(serialized), length=total_length)
