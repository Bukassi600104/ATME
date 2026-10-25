"""Shared static support gate for the bounded v2 semantic-arrow runtime."""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise

from atme.render.v2_media_view import require_media_readiness
from atme.render.v2_registry import (
    UnsupportedRegistryPlacement,
    registry_relationship_anchor,
)
from atme.render.v2_world import UnsupportedWorldGeometry, world_matrix
from atme.store.contracts_v2 import ConnectorObject, GroupContainer


class UnsupportedConnector(ValueError):
    """An authored connector cannot be executed by the bounded arrow runtime."""


@dataclass(frozen=True)
class ConnectorRoute:
    points: tuple[tuple[float, float], ...]
    length: float
    head: tuple[tuple[float, float], tuple[float, float]]


def connector_route(obj: ConnectorObject, objects: dict, states: dict, weight: float,
                    *, registry_inputs=None, media_view=None) -> ConnectorRoute:
    """Exact sampled world anchors and four-decimal route/head, without painting."""
    start, end = _connector_endpoints(obj, objects, states, registry_inputs=registry_inputs, media_view=media_view)
    return connector_geometry(obj, start, end, weight)


def _connector_endpoints(obj, objects, states, *, registry_inputs=None, media_view=None):
    """Named world anchors, or the explicitly authored parent-local free point."""
    free_point = obj.source_point is not None
    destination = objects[obj.destination_object_id]
    endpoints = (destination,) if free_point else (objects[obj.source_object_id], destination)
    if free_point:
        validate_free_pointer(obj, objects)
    try:
        require_media_readiness(objects, tuple(part.object_id for part in endpoints), media_view)
    except ValueError as exc:
        raise UnsupportedConnector(str(exc)) from exc
    for endpoint in endpoints:
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
        end = registry_relationship_anchor(destination, obj.destination_anchor_id, objects, transforms, registry_inputs)
        if free_point:
            start = (obj.source_point.x, obj.source_point.y)
            parent_id = obj.parent_id
            while parent_id is not None:
                parent = states[parent_id]
                if not parent.visible or parent.opacity <= 0 or parent.reveal_fraction <= 0:
                    raise UnsupportedConnector(f"v2 pointer {obj.object_id} has a hidden source parent")
                parent_id = objects[parent_id].parent_id
            if obj.parent_id is not None:
                inverse = world_matrix(objects[obj.parent_id], objects, transforms).inverse()
                end = inverse.point(*end)
        else:
            start = registry_relationship_anchor(endpoints[0], obj.source_anchor_id,
                                                 objects, transforms, registry_inputs)
    except (UnsupportedWorldGeometry, UnsupportedRegistryPlacement) as exc:
        raise UnsupportedConnector(str(exc)) from exc
    return start, end


def connector_geometry(obj: ConnectorObject, start: tuple, end: tuple, weight: float) -> ConnectorRoute:
    """The same exact route/head math for already-resolved world endpoints.

    This is geometry validation, not a fabricated replay or visibility proof.
    """
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
    """Explicit native relationship admission; owned leaders keep their old gate."""
    if obj.source_point is not None:
        if annotation_pointer:
            raise UnsupportedConnector("owned annotation pointer cannot carry a free source_point")
        validate_free_pointer(obj, objects)
    else:
        _validate_arrow_geometry(obj, objects, allow_pointer=annotation_pointer,
                                 allow_network=not annotation_pointer)


def validate_free_pointer(obj: ConnectorObject, objects: dict) -> None:
    """Dedicated point path, not an ownership alias or generic parented arrow."""
    if type(obj) is not ConnectorObject or obj.source_point is None or obj.role != "pointer":
        raise UnsupportedConnector("free pointer requires its exact authored source_point")
    _validate_arrow_payload(obj, objects, allow_pointer=True, allow_free_source=True)
    for root in (obj.object_id, obj.destination_object_id):
        seen, key = set(), root
        while key is not None:
            if key in seen or key not in objects or len(seen) > 8:
                raise UnsupportedConnector("free pointer needs complete acyclic ordinary Group ancestry")
            seen.add(key)
            part = objects[key]
            if part.board_id != obj.board_id or part.clip_id is not None:
                raise UnsupportedConnector("free pointer requires same-board unclipped Group ancestry")
            parent = part.parent_id
            if parent is not None and (parent not in objects or type(objects[parent]) is not GroupContainer
                                       or key not in objects[parent].child_ids):
                raise UnsupportedConnector("free pointer needs reciprocal ordinary Group ancestry")
            key = parent


def validate_owned_pointer(obj: ConnectorObject, objects: dict) -> None:
    """Geometry only; the caller must first prove explicit pointer ownership."""
    if type(obj) is not ConnectorObject or obj.role != "pointer":
        raise UnsupportedConnector("owned pointer validation requires an exact pointer connector")
    _validate_arrow_geometry(obj, objects, allow_pointer=True)


def _validate_arrow_geometry(obj: ConnectorObject, objects: dict, *, allow_pointer: bool,
                             allow_network: bool = False) -> None:
    _validate_arrow_payload(obj, objects, allow_pointer=allow_pointer, allow_network=allow_network)
    if obj.parent_id is not None:
        raise UnsupportedConnector(f"v2 arrow {obj.object_id} has ignored geometry or styling")


def _validate_arrow_payload(obj: ConnectorObject, objects: dict, *, allow_pointer: bool,
                            allow_free_source: bool = False, allow_network: bool = False) -> None:
    """Shared payload guards; ownership-specific callers still own ancestry."""
    if obj.object_type not in ({"arrow", "network"} if allow_network else {"arrow"}) or obj.role not in (
        {"semantic_connector", "pointer"} if allow_pointer else {"semantic_connector"}
    ):
        raise UnsupportedConnector(f"v2 connector {obj.object_id} has unsupported network/pointer semantics")
    free_point = obj.source_point is not None
    if free_point and (not allow_free_source or obj.role != "pointer"
                       or obj.source_object_id is not None or obj.source_anchor_id is not None):
        raise UnsupportedConnector("free source_point cannot replace a named/owned relationship source")
    if not free_point and (not obj.source_object_id or not obj.source_anchor_id):
        raise UnsupportedConnector(f"v2 arrow {obj.object_id} needs a named source anchor")
    if obj.source_object_id == obj.destination_object_id:
        raise UnsupportedConnector(f"v2 arrow {obj.object_id} cannot loop back to itself")
    if obj.source_object_id == obj.object_id or obj.destination_object_id == obj.object_id:
        raise UnsupportedConnector(f"v2 arrow {obj.object_id} cannot anchor to itself")
    destination = objects[obj.destination_object_id]
    endpoints = ((destination, obj.destination_anchor_id),) if free_point else (
        (objects[obj.source_object_id], obj.source_anchor_id), (destination, obj.destination_anchor_id))
    if any(isinstance(endpoint, ConnectorObject) or endpoint.board_id != obj.board_id
           for endpoint, _ in endpoints):
        raise UnsupportedConnector(f"v2 arrow {obj.object_id} endpoints must be non-connectors on its board")
    if (obj.clip_id or obj.asset_id or obj.style.effect
            or obj.geometry.points or obj.geometry.corner_radius is not None or obj.anchors
            or obj.style.fill or obj.style.text or obj.allow_self_loop):
        raise UnsupportedConnector(f"v2 arrow {obj.object_id} has ignored geometry or styling")
    transform = obj.transform
    if (transform.position.x or transform.position.y or transform.scale_x != 1
            or transform.scale_y != 1 or transform.rotation_degrees
            or transform.origin.x != 0.5 or transform.origin.y != 0.5):
        raise UnsupportedConnector(f"v2 arrow {obj.object_id} has unsupported independent transform")
    for endpoint, anchor_id in endpoints:
        anchor = next(anchor for anchor in endpoint.anchors if anchor.anchor_id == anchor_id)
        if not 0 <= anchor.point.x <= 1 or not 0 <= anchor.point.y <= 1:
            raise UnsupportedConnector(f"v2 arrow {obj.object_id} needs normalized endpoint anchors")
