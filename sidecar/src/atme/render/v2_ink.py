"""Closed authored primary-ink weights shared by ordinary and retained paint."""

from atme.store.contracts_v2 import ConnectorObject, MarkObject

INK_EFFECTS = {"ink_fine": "fine_px", "ink_emphasis": "emphasis_px"}
INK_MARKS = frozenset({"freehand", "line", "rectangle", "rounded_rectangle", "ellipse", "polygon", "bracket"})


def ink_effect_eligible(obj):
    return (type(obj) is MarkObject and obj.object_type in INK_MARKS
            or type(obj) is ConnectorObject and obj.object_type in {"arrow", "network"}
            and obj.role == "semantic_connector" and obj.source_point is None)


def primary_stroke_width(obj, style, scale):
    effect = obj.style.effect
    if effect is not None:
        if effect not in INK_EFFECTS or not ink_effect_eligible(obj):
            raise ValueError(f"unsupported ink effect for {obj.object_id}: {effect!r}")
        return getattr(style.strokes, INK_EFFECTS[effect]) * scale
    return (style.strokes.emphasis_px if obj.object_type == "highlight"
            else style.strokes.regular_px) * scale
