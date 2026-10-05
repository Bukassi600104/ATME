"""Shared static support gate for the bounded v2 semantic-arrow runtime."""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise

from atme.render.v2_world import UnsupportedWorldGeometry, world_anchor
from atme.store.contracts_v2 import ConnectorObject


class UnsupportedConnector(ValueError):
    """An authored connector cannot be executed by the bounded arrow runtime."""


@dataclass(frozen=True)
class ConnectorRoute:
    points: tuple[tuple[float, float], ...]
    length: float
    head: tuple[tuple[float, float], tuple[float, float]]


def connector_route(obj: ConnectorObject, objects: dict, states: dict, weight: float) -> ConnectorRoute:
    """Exact sampled world anchors and four-decimal route/head, without painting."""
    source, destination = objects[obj.source_object_id], objects[obj.destination_object_id]
    for endpoint in (source, destination):
        state = states[endpoint.object_id]
        if not state.visible or state.opacity <= 0 or state.reveal_fraction <= 0:
            raise UnsupportedConnector(f"v2 arrow {obj.object_id} has a hidden endpoint")
        parent_id = endpoint.parent_id
        while parent_id is not None:
            parent = states[parent_id]
            if not parent.visible or parent.opacity <= 0:
                raise UnsupportedConnector(f"v2 arrow {obj.object_id} has a hidden endpoint")
            parent_id = objects[parent_id].parent_id
    transforms = {key: state.transform for key, state in states.items()}
    try:
        start = world_anchor(source, obj.source_anchor_id, objects, transforms)
        end = world_anchor(destination, obj.destination_anchor_id, objects, transforms)
    except UnsupportedWorldGeometry as exc:
        raise UnsupportedConnector(str(exc)) from exc
    if not all(math.isfinite(value) and abs(value) <= 1_000_000 for point in (start, end) for value in point):
        raise UnsupportedConnector(f"v2 arrow {obj.object_id} endpoint is outside supported range")
    start, end = tuple(float(f"{value:.4f}") for value in start), tuple(float(f"{value:.4f}") for value in end)
    bounds = obj.geometry.bounds

    def inside(point):
        x, y = point
        return bounds.x <= x <= bounds.x + bounds.width and bounds.y <= y <= bounds.y + bounds.height

    if not all(inside(point) for point in (start, end)):
        raise UnsupportedConnector(f"v2 arrow {obj.object_id} exceeds authored bounds")
    if obj.routing == "straight":
        route = (start, end)
        tangent = (end[0] - start[0], end[1] - start[1])
        length = math.dist(start, end)
    elif obj.routing == "elbow":
        bend = (end[0], start[1])
        route = (start, bend, end)
        tangent = (end[0] - bend[0], end[1] - bend[1])
        if tangent == (0, 0):
            tangent = (bend[0] - start[0], bend[1] - start[1])
        length = math.dist(start, bend) + math.dist(bend, end)
    else:
        bend = (float(f"{(start[0] + end[0]) / 2:.4f}"), start[1])
        route = (start, bend, end)
        tangent = (end[0] - bend[0], end[1] - bend[1])
        length = sum(math.dist(previous, current) for previous, current in pairwise(
            ((1 - t) ** 2 * start[0] + 2 * (1 - t) * t * bend[0] + t ** 2 * end[0],
             (1 - t) ** 2 * start[1] + 2 * (1 - t) * t * bend[1] + t ** 2 * end[1])
            for t in (step / 64 for step in range(65))
        ))
    if not all(inside(point) for point in route):
        raise UnsupportedConnector(f"v2 arrow {obj.object_id} route exceeds authored bounds")
    if not math.isfinite(length) or not 0.0001 <= length <= 10_000_000:
        raise UnsupportedConnector(f"v2 arrow {obj.object_id} has degenerate/oversized route")
    tangent_length = math.hypot(*tangent)
    if tangent_length <= 0:
        raise UnsupportedConnector(f"v2 arrow {obj.object_id} has no endpoint direction")
    unit_x, unit_y = tangent[0] / tangent_length, tangent[1] / tangent_length
    wing, depth = 6 * weight / 2.6667, 14 * weight / 2.6667
    base_x, base_y = end[0] - depth * unit_x, end[1] - depth * unit_y
    left = (float(f"{base_x - wing * unit_y:.4f}"), float(f"{base_y + wing * unit_x:.4f}"))
    right = (float(f"{base_x + wing * unit_y:.4f}"), float(f"{base_y - wing * unit_x:.4f}"))
    if not all(inside(point) for point in (left, right)):
        raise UnsupportedConnector(f"v2 arrow {obj.object_id} head exceeds authored bounds")
    return ConnectorRoute(route, length, (left, right))


def validate_static_arrow(obj: ConnectorObject, objects: dict, *, annotation_pointer: bool = False) -> None:
    if obj.object_type != "arrow" or obj.role not in (
        {"semantic_connector", "pointer"} if annotation_pointer else {"semantic_connector"}
    ):
        raise UnsupportedConnector(f"v2 connector {obj.object_id} has unsupported network/pointer semantics")
    if not obj.source_object_id or not obj.source_anchor_id:
        raise UnsupportedConnector(f"v2 arrow {obj.object_id} needs a named source anchor")
    if obj.source_object_id == obj.destination_object_id:
        raise UnsupportedConnector(f"v2 arrow {obj.object_id} cannot loop back to itself")
    if obj.source_object_id == obj.object_id or obj.destination_object_id == obj.object_id:
        raise UnsupportedConnector(f"v2 arrow {obj.object_id} cannot anchor to itself")
    source = objects[obj.source_object_id]
    destination = objects[obj.destination_object_id]
    if (isinstance(source, ConnectorObject) or isinstance(destination, ConnectorObject)
            or source.board_id != obj.board_id or destination.board_id != obj.board_id):
        raise UnsupportedConnector(f"v2 arrow {obj.object_id} endpoints must be non-connectors on its board")
    if (obj.parent_id or obj.clip_id or obj.asset_id or obj.style.effect
            or obj.geometry.points or obj.geometry.corner_radius is not None or obj.anchors
            or obj.style.fill or obj.style.text or obj.allow_self_loop):
        raise UnsupportedConnector(f"v2 arrow {obj.object_id} has ignored geometry or styling")
    transform = obj.transform
    if (transform.position.x or transform.position.y or transform.scale_x != 1
            or transform.scale_y != 1 or transform.rotation_degrees
            or transform.origin.x != 0.5 or transform.origin.y != 0.5):
        raise UnsupportedConnector(f"v2 arrow {obj.object_id} has unsupported independent transform")
    for endpoint, anchor_id in ((source, obj.source_anchor_id),
                                (destination, obj.destination_anchor_id)):
        anchor = next(anchor for anchor in endpoint.anchors if anchor.anchor_id == anchor_id)
        if not 0 <= anchor.point.x <= 1 or not 0 <= anchor.point.y <= 1:
            raise UnsupportedConnector(f"v2 arrow {obj.object_id} needs normalized endpoint anchors")
