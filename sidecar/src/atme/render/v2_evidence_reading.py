"""Technical evidence readability at one exact immutable replay sample.

This does not research/verify claims or alter attested source pixels/permissions.
"""

import itertools
from math import hypot

from atme.render.v2_mask import mask_source_region
from atme.render.v2_world import world_bounds, world_matrix
from atme.store.contracts_v2 import ContainerObject, MaskContainer

_EPS = 1e-7  # Numerical inverse noise only; authored geometry serializes at 1e-4.


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _subtract(a, b):
    return a[0] - b[0], a[1] - b[1]


def _on_segment(point, a, b):
    delta, offset = _subtract(b, a), _subtract(point, a)
    return (abs(_cross(delta, offset)) <= _EPS * hypot(*delta)
            and min(a[0], b[0]) - _EPS <= point[0] <= max(a[0], b[0]) + _EPS
            and min(a[1], b[1]) - _EPS <= point[1] <= max(a[1], b[1]) + _EPS)


def _intersection_parameters(a, b, c, d):
    """Partition AB at actual crossings, touches and collinear edge endpoints."""
    ab, cd, ac = _subtract(b, a), _subtract(d, c), _subtract(c, a)
    denominator = _cross(ab, cd)
    if abs(denominator) > 1e-12 * hypot(*ab) * hypot(*cd):
        t, u = _cross(ac, cd) / denominator, _cross(ac, ab) / denominator
        return [max(0.0, min(1.0, t))] if -1e-12 <= t <= 1 + 1e-12 and -1e-12 <= u <= 1 + 1e-12 else []
    if abs(_cross(ab, ac)) > _EPS * hypot(*ab):
        return []
    length_squared = ab[0] ** 2 + ab[1] ** 2
    values = [sum(x * y for x, y in zip(_subtract(p, a), ab)) / length_squared for p in (c, d)]
    low, high = max(0.0, min(values)), min(1.0, max(values))
    return [low, high] if low <= high else []


def _in_polygon(point, edges):
    if any(_on_segment(point, a, b) for a, b in edges):
        return True
    x, y = point
    return sum(1 for a, b in edges if (a[1] > y) != (b[1] > y)
               and x < a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])) % 2 == 1


def _polygon_contains(points, corners):
    if points[0] == points[-1]:
        points = points[:-1]
    edges = list(zip(points, [*points[1:], points[0]]))
    if len(points) < 3 or any(a == b for a, b in edges):
        raise ValueError("evidence mask polygon has degenerate edges")
    for index, (a, b) in enumerate(edges):
        for other, (c, d) in enumerate(edges[:index]):
            if other == index - 1 or (other == 0 and index == len(edges) - 1):
                continue
            if _intersection_parameters(a, b, c, d):
                raise ValueError("evidence mask polygon is not simple; containment is unprovable")
    if not all(_in_polygon(p, edges) for p in corners):
        return False
    # Concave notches can cross an edge even when every card corner is inside.
    for a, b in zip(corners, [*corners[1:], corners[0]]):
        partitions = sorted({0.0, 1.0, *(t for c, d in edges for t in _intersection_parameters(a, b, c, d))})
        for low, high in itertools.pairwise(partitions):
            t = (low + high) / 2
            if not _in_polygon((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t), edges):
                return False
    return True


def _contains_card(source, corners):
    bounds = source.geometry.bounds
    x, y, width, height = (float(f"{v:.4f}") for v in (bounds.x, bounds.y, bounds.width, bounds.height))
    if not all(x - _EPS <= px <= x + width + _EPS and y - _EPS <= py <= y + height + _EPS
               for px, py in corners):
        return False
    if source.object_type in {"rectangle", "clip"}:
        return True
    if source.object_type == "ellipse":
        return all(((px - x - width / 2) / (width / 2)) ** 2
                   + ((py - y - height / 2) / (height / 2)) ** 2 <= 1 + 1e-12 for px, py in corners)
    if source.object_type == "rounded_rectangle":
        radius = float(f"{source.geometry.corner_radius:.4f}")
        return all(hypot(max(x + radius - px, 0, px - (x + width - radius)),
                         max(y + radius - py, 0, py - (y + height - radius))) <= radius + _EPS
                   for px, py in corners)
    if source.object_type == "polygon":
        points = [(float(f"{p.x:.4f}"), float(f"{p.y:.4f}")) for p in source.geometry.points]
        return _polygon_contains(points, corners)
    raise ValueError("evidence aperture geometry is unprovable")


def _validate_apertures(target, obj, objects, treatment, ancestors, transforms, matrix):
    chain = (target, *ancestors)
    if any(objects[key].clip_id is not None for key in chain):
        raise ValueError(f"evidence {target} cannot borrow an external aperture")
    masks = [key for key in ancestors if isinstance(objects[key], MaskContainer)]
    declared = treatment.intent.mask_object_id
    if masks != ([declared] if declared is not None else []):
        raise ValueError(f"evidence {target} needs its actual declared mask ancestor")
    bounds = obj.geometry.bounds
    x, y, width, height = (float(f"{v:.4f}") for v in (bounds.x, bounds.y, bounds.width, bounds.height))
    corners = [matrix.point(px, py) for px, py in (
        (x, y), (x + width, y), (x + width, y + height), (x, y + height))]
    for parent_id in ancestors:
        parent = objects[parent_id]
        if not isinstance(parent, ContainerObject) or parent.object_type not in {"mask", "clip"}:
            continue
        if "mask" not in treatment.allowed_transformations:
            raise ValueError(f"evidence {target} needs actual asset mask permission for its aperture")
        source = objects[parent.mask_source_object_id] if isinstance(parent, MaskContainer) else parent
        if isinstance(parent, MaskContainer):
            if parent.invert or parent.feather_px or source.clip_id is not None:
                raise ValueError(f"evidence {target} has an unprovable mask aperture")
            mask_source_region(source, transforms[source.object_id])
        if "rotate" not in treatment.allowed_transformations and transforms[source.object_id].rotation_degrees != 0:
            raise ValueError(f"evidence {target} has an undeclared rotation")
        inverse = world_matrix(source, objects, transforms).inverse()
        if not _contains_card(source, [inverse.point(*point) for point in corners]):
            label = "declared mask" if isinstance(parent, MaskContainer) else "parent"
            raise ValueError(f"evidence {target} is clipped by its {label}")


def validate_evidence_reading(item, layout, objects, treatment, sample, viewport):
    """Ordinary insert compatibility wrapper; its original completion clock."""
    validate_evidence_reading_binding(item.action.target_object_id, item.end_ms,
                                      layout, objects, treatment, sample, viewport)


def validate_evidence_reading_binding(target, readable_start_ms, layout, objects, treatment, sample, viewport):
    """Observe an explicit evidence owner/window without inventing an action.

    The lifecycle caller proves the treatment and phase-derived window. This
    observer reuses the same current-world geometry and readability invariants.
    """
    if (type(target) is not str or target != treatment.object_id or target not in objects
            or type(readable_start_ms) is not int or readable_start_ms < 0):
        raise ValueError("evidence reading binding needs its exact target and nonnegative integer clock")
    objects = sample.hierarchy.object_map(objects)
    frames = {frame.object_id: frame for frame in sample.objects}
    transforms = {key: frame.transform for key, frame in frames.items()}
    obj = objects[target]
    ancestors = sample.hierarchy.ancestors(target)
    chain = (target, *ancestors)
    if any(not frames[key].visible or frames[key].reveal_fraction != 1
           or frames[key].opacity != 1 for key in ancestors):
        raise ValueError(f"evidence {target} needs fully visible opaque parents throughout its hold")
    if sample.at_ms >= readable_start_ms and (
        not frames[target].visible or frames[target].reveal_fraction != 1 or frames[target].opacity != 1
    ):
        raise ValueError(f"evidence {target} must remain fully visible and opaque for its readable hold")
    if "rotate" not in treatment.allowed_transformations and any(
        transforms[key].rotation_degrees != 0 for key in chain
    ):
        raise ValueError(f"evidence {target} has an undeclared rotation")
    rect = world_bounds(obj, objects, transforms)
    matrix = world_matrix(obj, objects, transforms)
    _validate_apertures(target, obj, objects, treatment, ancestors, transforms, matrix)
    crop, focus, bounds = treatment.intent.crop, treatment.intent.focus_region, obj.geometry.bounds
    source_scale = min(bounds.width / crop.width, bounds.height * 0.5 / crop.height)
    origin = matrix.point(0, 0)
    focus_x = matrix.point(focus.width * source_scale, 0)
    focus_y = matrix.point(0, focus.height * source_scale)
    displayed_focus_x = ((focus_x[0] - origin[0]) ** 2 + (focus_x[1] - origin[1]) ** 2) ** 0.5
    displayed_focus_y = ((focus_y[0] - origin[0]) ** 2 + (focus_y[1] - origin[1]) ** 2) ** 0.5
    if (rect[0] < viewport.x or rect[1] < viewport.y
            or rect[2] > viewport.x + viewport.width or rect[3] > viewport.y + viewport.height
            or (rect[2] - rect[0]) * layout.canvas.width / viewport.width < 180
            or (rect[3] - rect[1]) * layout.canvas.height / viewport.height < 160
            or displayed_focus_x * layout.canvas.width / viewport.width < 8
            or displayed_focus_y * layout.canvas.height / viewport.height < 8):
        raise ValueError(f"evidence {target} is not fully readable in the camera frame during its hold")
