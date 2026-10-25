"""Owning authored Callout body; pointer and chronological admission are separate."""

import math

from atme.render.style_contracts import PaperInkStyle
from atme.store.contracts_v2 import Bounds, CalloutBinding, TextObject

CALLOUT_INSET_TOKEN = "sm"


def callout_body_svg(obj: TextObject, style: PaperInkStyle, scale: float, font_source,
                     *, write_fraction: float | None = None) -> str:
    """Paint an explicit box and its fixed token inset, or an unchanged label.

    No box, geometry, semantic text, pointer or object ID is synthesized. The
    temporary inner rectangle affects glyph layout only, never stored geometry
    or world anchors. Callers must separately validate the bound pointer.
    """
    from atme.render.v2_svg import (
        UnsupportedVisualObject,
        _color,
        _font,
        _n,
        _text,
        _text_role,
    )

    if (type(obj) is not TextObject or obj.object_type != "callout"
            or type(obj.callout_binding) is not CalloutBinding
            or set(obj.__dict__) != set(TextObject.model_fields) or obj.model_extra
            or set(obj.callout_binding.__dict__) != set(CalloutBinding.model_fields)
            or obj.callout_binding.model_extra):
        raise UnsupportedVisualObject("native Callout needs an exact authored callout_binding")
    obj = TextObject.model_validate(obj.model_dump(mode="json"))
    style = PaperInkStyle.model_validate(style.model_dump(mode="json"))
    if (type(scale) not in {int, float} or not math.isfinite(scale) or not 0 < scale <= 100
            or write_fraction is not None and (type(write_fraction) not in {int, float}
                or not math.isfinite(write_fraction) or not 0 <= write_fraction <= 1)):
        raise UnsupportedVisualObject("Callout scale/write fraction must be finite and within range")
    if obj.asset_id is not None or obj.style.effect or obj.geometry.points or obj.items:
        raise UnsupportedVisualObject("Callout has unsupported asset, effect, points or list content")
    role = _text_role(obj, style)
    font = next(font for font in style.fonts if font.id == role.font_id)
    size, pitch = role.size_px * scale, role.size_px * scale * role.line_height
    color = _color(obj.style.text, style.colors, default=style.colors["ink"])
    boxed = obj.style.stroke is not None or obj.style.fill is not None
    bounds, radius, box = obj.geometry.bounds, obj.geometry.corner_radius, ""
    if not boxed and radius is not None:
        raise UnsupportedVisualObject("unboxed Callout cannot ignore authored corner radius")
    text_obj = obj
    if boxed:
        radius = 0 if radius is None else radius
        if not math.isfinite(radius) or not 0 <= radius <= min(bounds.width, bounds.height)/2:
            raise UnsupportedVisualObject("Callout box corner radius exceeds its authored bounds")
        inset = style.spacing_px[CALLOUT_INSET_TOKEN] * scale
        if bounds.width <= 2 * inset or bounds.height <= 2 * inset:
            raise UnsupportedVisualObject("Callout box has no positive inner text area")
        inner = Bounds(x=bounds.x + inset, y=bounds.y + inset,
                       width=bounds.width - 2 * inset, height=bounds.height - 2 * inset)
        text_obj = obj.model_copy(update={"geometry": obj.geometry.model_copy(update={"bounds": inner})})
        measuring = _font(font_source if isinstance(font_source, bytes) else str(font_source), math.ceil(size))
        for index, line in enumerate(obj.text.splitlines()):
            left, top, right, bottom = measuring.getbbox(line, anchor="ls")
            if (left < 0 or right > inner.width or size + index * pitch + top < 0
                    or size + index * pitch + bottom > inner.height):
                raise UnsupportedVisualObject("Callout actual glyph exceeds the fixed inset bounds")
        fill = _color(obj.style.fill, style.colors, default="none")
        stroke = _color(obj.style.stroke, style.colors, default="none")
        box = (f'<rect x="{_n(bounds.x)}" y="{_n(bounds.y)}" width="{_n(bounds.width)}" '
               f'height="{_n(bounds.height)}" rx="{_n(radius)}" fill="{fill}" stroke="{stroke}" '
               f'stroke-width="{_n(style.strokes.regular_px * scale)}" '
               f'stroke-linecap="round" stroke-linejoin="round"/>')
    return box + _text(text_obj, color, font.family, font.weight, size, role.line_height,
                       role.max_characters_per_line, font_source, write_fraction=write_fraction)
