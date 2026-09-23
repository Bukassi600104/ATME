"""Bounded, data-only paths for authored Paper & Ink emphasis."""

from __future__ import annotations

from typing import Literal

from atme.render.v2_path import FreehandPath, InvalidFreehandPath, parse_freehand_path
from atme.store.contracts_v2 import Bounds

SUPPORTED_HIGHLIGHT_MARKS = frozenset({
    "freehand", "line", "rectangle", "rounded_rectangle", "ellipse", "polygon",
    "underline", "highlight",
})
SUPPORTED_HIGHLIGHT_TEXT = frozenset({"text", "list"})


class UnsupportedEmphasis(ValueError):
    """Authored bounds cannot hold a supported emphasis stroke."""


def emphasis_path(bounds: Bounds, kind: Literal["underline", "highlight"]) -> FreehandPath:
    x, y, w, h = bounds.x, bounds.y, bounds.width, bounds.height

    def number(value: float) -> str:
        return f"{value:.4f}".rstrip("0").rstrip(".") if value else "0"

    def point(x_fraction: float, y_fraction: float) -> str:
        return f"{number(x + w * x_fraction)} {number(y + h * y_fraction)}"

    if kind == "underline":
        path = (f"M {point(0.04, 0.35)} Q {point(0.48, 0.82)} "
                f"{point(0.96, 0.42)}")
    elif kind == "highlight":
        path = (
            f"M {point(0.52, 0.04)} "
            f"C {point(0.82, 0.02)} {point(0.96, 0.20)} {point(0.96, 0.51)} "
            f"C {point(0.97, 0.78)} {point(0.73, 0.96)} {point(0.49, 0.95)} "
            f"C {point(0.18, 0.97)} {point(0.04, 0.77)} {point(0.04, 0.48)} "
            f"C {point(0.04, 0.20)} {point(0.25, 0.04)} {point(0.52, 0.04)}"
        )
    else:
        raise UnsupportedEmphasis(f"unsupported emphasis kind: {kind}")
    try:
        return parse_freehand_path(path, bounds)
    except InvalidFreehandPath as exc:
        raise UnsupportedEmphasis(f"{kind} exceeds supported authored bounds") from exc


def cross_out_paths(bounds: Bounds) -> tuple[FreehandPath, FreehandPath]:
    """Two separately drawn diagonals, with no hidden connecting stroke."""
    x, y, w, h = bounds.x, bounds.y, bounds.width, bounds.height

    def number(value: float) -> str:
        return f"{value:.4f}".rstrip("0").rstrip(".") if value else "0"

    def point(x_fraction: float, y_fraction: float) -> str:
        return f"{number(x + w * x_fraction)} {number(y + h * y_fraction)}"

    paths = (
        f"M {point(0.08, 0.12)} L {point(0.92, 0.88)}",
        f"M {point(0.90, 0.10)} L {point(0.10, 0.90)}",
    )
    try:
        return tuple(parse_freehand_path(path, bounds) for path in paths)
    except InvalidFreehandPath as exc:
        raise UnsupportedEmphasis("cross_out exceeds supported authored bounds") from exc
