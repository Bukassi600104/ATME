"""Owning truthful chart geometry and native ink, independent of Split admission.

All data, domains, ticks, labels, scales and construction windows are authored.
The fixed native layout uses pinned Paper & Ink typography/spacing; it refuses
unreadable placements instead of truncating, rescaling fonts or inventing data.
"""

import math
from fractions import Fraction
from hashlib import sha256
from re import fullmatch

from pydantic import BaseModel

from atme.render.style_contracts import PaperInkStyle
from atme.store.contracts_v2 import (
    Anchor,
    Bounds,
    ChartAxis,
    ChartBar,
    ChartConstruction,
    ChartHighlight,
    ChartPayload,
    ChartPoint,
    ChartSeries,
    ChartTick,
    Geometry,
    Point,
    StyleRefs,
    Transform,
    VisualObject,
)

_KNOWN = frozenset({VisualObject, Bounds, Geometry, StyleRefs, Transform, Point, Anchor,
    ChartPayload, ChartAxis, ChartTick, ChartSeries, ChartPoint, ChartBar, ChartHighlight, ChartConstruction})


def _known_tree(value):
    if isinstance(value, BaseModel):
        cls = type(value)
        if cls not in _KNOWN or value.model_extra or set(value.__dict__) != set(cls.model_fields):
            raise ValueError("chart has an unknown, extra or missing native payload")
        # Do not serialize before strict numeric validation: Pydantic's float
        # serializer can turn a bypass-mutated True into 1.0.
        return {key: _known_tree(child) for key, child in value.__dict__.items()}
    elif isinstance(value, list):
        return [_known_tree(child) for child in value]
    return value


def _number(value, *, low=None, high=None):
    if (type(value) not in {int, float} or not math.isfinite(value)
            or low is not None and value < low or high is not None and value > high):
        raise ValueError("chart requires a finite non-boolean number within its declared range")
    return value


def _payload(payload):
    if type(payload) is not ChartPayload:
        raise ValueError("chart needs the exact authored data payload")
    return ChartPayload.model_validate(_known_tree(payload))


def _fraction(axis, value):
    low, high = axis.domain
    if axis.scale == "linear":
        result = float((Fraction(value)-Fraction(low))/(Fraction(high)-Fraction(low)))
    else:
        delta = (high-low)/low
        log_ratio = lambda end: math.log1p((end-low)/low) if math.isfinite((end-low)/low) else math.log(end)-math.log(low)
        result = log_ratio(value) / (math.log1p(delta) if math.isfinite(delta) else math.log(high)-math.log(low))
    return _number(result, low=0., high=1.)


def chart_data_geometry(payload: ChartPayload, bounds: Bounds) -> tuple:
    """Exact mapped centers/bar edges/baseline in authored series/point order.

    Bar edges use actual x-axis units, including when that axis is logarithmic.
    The y baseline is explicit; line geometry has no inferred baseline.
    """
    payload = _payload(payload)
    if type(bounds) is not Bounds:
        raise ValueError("chart plot requires exact bounds")
    bounds = Bounds.model_validate(_known_tree(bounds), strict=True)
    from atme.render.v2_svg import _n

    x, y, width, height = bounds.x, bounds.y, bounds.width, bounds.height
    if float(_n(width)) <= 0 or float(_n(height)) <= 0:
        raise ValueError("chart serialized plot collapses")
    mx = lambda value: x + width * _fraction(payload.x_axis, value)
    my = lambda value: y + height * (1 - _fraction(payload.y_axis, value))
    rows = []
    for series in payload.series:
        for point in series.points:
            left = right = baseline = None
            if payload.bar is not None:
                left, right = mx(point.x - payload.bar.width/2), mx(point.x + payload.bar.width/2)
                baseline = my(payload.bar.baseline)
                if float(_n(right)) <= float(_n(left)):
                    raise ValueError("chart serialized bar width collapses")
                if point.y != payload.bar.baseline and _n(my(point.y)) == _n(baseline):
                    raise ValueError("chart serialized bar value collapses onto its baseline")
            row = (series.series_id, point.point_id, mx(point.x), my(point.y), left, right, baseline)
            for value in row[2:]:
                if value is not None:
                    _number(value)
            rows.append(row)
    return tuple(rows)


def _clock(payload, fraction):
    fraction = 1. if fraction is None else _number(fraction, low=0., high=1.)
    return {(item.series_id, item.point_id): min(1., max(0.,
        (fraction-item.start_fraction)/(item.end_fraction-item.start_fraction))) for item in payload.construction}


def chart_series_svg(payload: ChartPayload, bounds: Bounds, colors: dict, stroke_width: float,
                     *, draw_fraction: float | None = None) -> str:
    """Actual bar growth/ordered line segments, never a rectangular chart wipe.

    A point follows its own authored window. Its incoming line segment uses the
    minimum construction fraction of both endpoints; an unconstructed endpoint
    cannot leak a line. Overlapping/out-of-order windows are not rewritten.
    """
    from atme.render.v2_svg import _color, _n, _xml_escape

    payload = _payload(payload)
    _number(stroke_width, low=0.0001, high=1000.)
    if (type(colors) is not dict or any(type(value) is not str or fullmatch(r"#[0-9A-Fa-f]{6}", value) is None
                                       for value in colors.values())):
        raise ValueError("chart palette requires pinned #RRGGBB colors")
    clocks = _clock(payload, draw_fraction)
    highlights = {(item.series_id, item.point_id): _color(item.color, colors, default="none")
                  for item in payload.highlights}
    series_colors = {item.series_id: _color(item.color, colors, default="none") for item in payload.series}
    markup, previous = [], {}
    for series, point, x, y, left, right, baseline in chart_data_geometry(payload, bounds):
        progress = clocks[series, point]
        start = previous.get(series)
        previous[series] = (x, y, progress)
        if progress <= 0:
            continue
        color = series_colors[series]
        attention = (f' stroke="{highlights[series, point]}" stroke-width="{_n(stroke_width)}"'
                     if (series, point) in highlights else "")
        if payload.kind == "bars":
            tip = baseline + (y-baseline)*progress
            if y == baseline:
                inner = (f'<path d="M{_n(left)} {_n(y)}L{_n(right)} {_n(y)}" fill="none" '
                         f'stroke="{highlights.get((series, point), color)}" stroke-width="{_n(stroke_width)}"/>')
            else:
                inner = (f'<rect x="{_n(left)}" y="{_n(min(tip, baseline))}" width="{_n(right-left)}" '
                         f'height="{_n(abs(tip-baseline))}" fill="{color}"{attention}/>')
        else:
            inner = ""
            if start is not None and start[2] > 0:
                sx, sy, source_fraction = start
                line_fraction = min(source_fraction, progress)
                inner = (f'<path d="M{_n(sx)} {_n(sy)}L{_n(sx+(x-sx)*line_fraction)} {_n(sy+(y-sy)*line_fraction)}" '
                         f'fill="none" stroke="{color}" stroke-width="{_n(stroke_width)}" '
                         'stroke-linecap="round" stroke-linejoin="round"/>')
            inner += (f'<circle cx="{_n(x)}" cy="{_n(y)}" r="{_n(stroke_width*1.5*progress)}" '
                      f'fill="{color}"{attention}/>')
        markup.append(f'<g data-chart-series="{_xml_escape(series)}" data-chart-point="{_xml_escape(point)}">{inner}</g>')
    return "".join(markup)


def chart_svg(obj: VisualObject, style: PaperInkStyle, scale: float, font_sources: dict[str, bytes],
              *, draw_fraction: float | None = None) -> str:
    """Pinned native chart shell, exact labels and the same pure data painter.

    Legend entries retain authored series order. Each datum's exact label fades
    with its own construction window; numeric values are never reformatted.
    Outer object hierarchy, opacity, camera and apertures belong to the shared
    compositor rather than a second chart-specific animation pipeline.
    """
    from atme.render.v2_svg import _color, _font, _n, _xml_escape

    if type(obj) is not VisualObject or obj.object_type != "chart" or obj.chart_payload is None:
        raise ValueError("native chart needs an exact chart object and authored payload")
    obj = VisualObject.model_validate(_known_tree(obj), strict=True)
    style = PaperInkStyle.model_validate(style.model_dump(mode="json"))
    _number(scale, low=0.0001, high=100.)
    if obj.geometry.points or obj.geometry.corner_radius is not None or obj.style.effect:
        raise ValueError("chart cannot discard authored points, radius or effect")
    payload, bounds = obj.chart_payload, obj.geometry.bounds
    clocks = _clock(payload, draw_fraction)
    ink = _color(obj.style.stroke, style.colors, default=style.colors["ink"])
    fill = _color(obj.style.fill, style.colors, default="none")
    text_color = _color(obj.style.text, style.colors, default=style.colors["ink"])
    roles, metrics, fonts = {}, {}, {}
    for key in ("title", "label"):
        role = getattr(style.typography, key)
        font = next(font for font in style.fonts if font.id == role.font_id)
        raw = font_sources.get(font.file)
        if type(raw) is not bytes or sha256(raw).hexdigest() != font.sha256:
            raise ValueError("chart pinned font bytes are missing or changed")
        roles[key], fonts[key] = role, font
        metrics[key] = _font(raw, max(1, math.ceil(role.size_px * scale)))
    pad, gap = style.spacing_px["sm"] * scale, style.spacing_px["xs"] * scale
    size = roles["label"].size_px * scale
    pitch = size * roles["label"].line_height
    title_size = roles["title"].size_px * scale
    title_pitch = title_size * roles["title"].line_height
    width = lambda text: metrics["label"].getlength(text)
    x, y, w, h = bounds.x, bounds.y, bounds.width, bounds.height
    top = y + pad + title_pitch + gap + len(payload.series)*pitch + gap + 3*pitch
    bottom = y + h - pad - 3*pitch - gap
    left = x + pad + max(width(tick.label) for tick in payload.y_axis.ticks) + 2*gap
    right = x + w - pad - max(width(tick.label)/2 for tick in payload.x_axis.ticks)
    if right-left <= 2*size or bottom-top <= 2*size:
        raise ValueError("chart has no readable plot within authored bounds")
    plot = Bounds(x=left, y=top, width=right-left, height=bottom-top)
    label_boxes = []

    def label(text, lx, baseline, *, role="label", anchor="start", opacity=1.):
        if text == "":
            return ""
        spec, font = roles[role], fonts[role]
        fs = spec.size_px * scale
        measure = metrics[role]
        actual_width = measure.getlength(text)
        shift = actual_width/2 if anchor == "middle" else actual_width if anchor == "end" else 0
        l, t, r, b = measure.getbbox(text, anchor="ls")
        if (len(text) > spec.max_characters_per_line or lx-shift+l < x or lx-shift+r > x+w
                or baseline+t < y or baseline+b > y+h):
            raise ValueError("chart exact authored label exceeds readable native bounds")
        box = (lx-shift+l, baseline+t, lx-shift+r, baseline+b)
        if any(min(box[2], other[2]) > max(box[0], other[0])
               and min(box[3], other[3]) > max(box[1], other[1]) for other in label_boxes):
            raise ValueError("chart measured label bounds overlap; author a readable placement")
        # Reserve every exact full label even before its construction window.
        # A seek must not admit a layout that fails only when later labels paint.
        label_boxes.append(box)
        return (f'<text x="{_n(lx)}" y="{_n(baseline)}" text-anchor="{anchor}" fill="{text_color}" '
                f'font-family="{_xml_escape(font.family)}" font-weight="{font.weight}" '
                f'font-size="{_n(fs)}" opacity="{_n(opacity)}" xml:space="preserve">{_xml_escape(text)}</text>')

    markup = [f'<rect x="{_n(x)}" y="{_n(y)}" width="{_n(w)}" height="{_n(h)}" fill="{fill}"/>']
    markup.append(label(payload.title, x+pad, y+pad+title_size, role="title"))
    for index, series in enumerate(payload.series):
        row_y = y+pad+title_pitch+gap+(index+1)*pitch
        color = _color(series.color, style.colors, default="none")
        markup.append(f'<path d="M{_n(x+pad)} {_n(row_y-size/3)}h{_n(gap*2)}" '
                      f'stroke="{color}" stroke-width="{_n(style.strokes.regular_px*scale)}"/>')
        markup.append(label(series.label, x+pad+3*gap, row_y))
    markup += [label(payload.y_axis.label, left, top-2*pitch),
               label(payload.y_axis.unit, left, top-pitch)]
    sw = style.strokes.fine_px * scale
    markup.append(f'<path d="M{_n(left)} {_n(top)}V{_n(bottom)}H{_n(right)}" '
                  f'fill="none" stroke="{ink}" stroke-width="{_n(sw)}"/>')
    for tick in payload.y_axis.ticks:
        ty = top + plot.height*(1-_fraction(payload.y_axis, tick.value))
        markup.append(f'<path d="M{_n(left-gap)} {_n(ty)}H{_n(left)}" stroke="{ink}" stroke-width="{_n(sw)}"/>')
        markup.append(label(tick.label, left-2*gap, ty+size/3, anchor="end"))
    for tick in payload.x_axis.ticks:
        tx = left + plot.width*_fraction(payload.x_axis, tick.value)
        markup.append(f'<path d="M{_n(tx)} {_n(bottom)}v{_n(gap)}" stroke="{ink}" stroke-width="{_n(sw)}"/>')
        markup.append(label(tick.label, tx, bottom+gap+size, anchor="middle"))
    markup += [label(payload.x_axis.label, (left+right)/2, bottom+gap+size+pitch, anchor="middle"),
               label(payload.x_axis.unit, (left+right)/2, bottom+gap+size+2*pitch, anchor="middle")]
    markup.append(chart_series_svg(payload, plot, style.colors, style.strokes.regular_px*scale,
                                   draw_fraction=draw_fraction))
    points = {(s.series_id, point.point_id): point for s in payload.series for point in s.points}
    for series, point, px, py, _, _, _ in chart_data_geometry(payload, plot):
        datum = points[series, point]
        # Native labels may shift within the plot, never the data coordinates.
        tx = min(right-width(datum.label)/2, max(left+width(datum.label)/2, px))
        exact = label(datum.label, tx, py-gap, anchor="middle", opacity=clocks[series, point])
        if clocks[series, point] > 0:
            markup.append(exact)
    return "".join(markup)
