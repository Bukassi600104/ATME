"""Exactly owned Callout leaders in authored ordinary Group coordinates.

Generic semantic/annotation connector admission is deliberately unchanged.
The owner is proved before relaxing the one parentless-payload restriction.
"""
from atme.render.v2_connector import (
    UnsupportedConnector,
    _connector_endpoints,
    _validate_arrow_payload,
    connector_geometry,
)
from atme.render.v2_world import UnsupportedWorldGeometry, world_matrix
from atme.store.contracts_v2 import (
    ConnectorObject,
    GroupContainer,
    TextObject,
    _callout_leader_owners,
)


def validate_callout_pointer(obj, objects):
    owner = _callout_leader_owners(objects).get(obj.object_id)
    if (type(obj) is not ConnectorObject or objects.get(obj.object_id) != obj
            or type(owner) is not TextObject or owner.object_type != "callout"):
        raise UnsupportedConnector("Callout pointer needs its exact authored owner and leader")
    binding = owner.callout_binding
    if (obj.role != "pointer" or obj.source_object_id != owner.object_id
            or obj.source_anchor_id != binding.callout_anchor_id
            or obj.destination_object_id != binding.target_object_id
            or obj.destination_anchor_id != binding.target_anchor_id):
        raise UnsupportedConnector("Callout pointer must preserve exact owner, endpoints and anchors")
    _validate_arrow_payload(obj, objects, allow_pointer=True)
    for root in (obj.object_id, owner.object_id, binding.target_object_id):
        seen, key = set(), root
        while key is not None:
            if key in seen or key not in objects or len(seen) > 8:
                raise UnsupportedConnector("Callout pointer needs complete acyclic ordinary Group ancestry")
            seen.add(key)
            part = objects[key]
            if part.board_id != owner.board_id or part.clip_id is not None:
                raise UnsupportedConnector("callout pointer requires same-board unclipped Group ancestry")
            if key != root and type(part) is not GroupContainer:
                raise UnsupportedConnector("Callout pointer requires ordinary Group ancestry")
            parent = part.parent_id
            if parent in objects and (objects[parent].object_type in {"clip", "mask"} or objects[parent].clip_id is not None):
                raise UnsupportedConnector("callout pointer endpoints require unclipped group ancestry")
            if parent is not None and (parent not in objects or type(objects[parent]) is not GroupContainer
                    or key not in objects[parent].child_ids):
                raise UnsupportedConnector("Callout pointer needs reciprocal ordinary Group ancestry")
            key = parent
    return owner


def callout_pointer_geometry(obj, objects, transforms, start, end, weight):
    """Initial or sampled geometry, with authored parent-local bounds/heads."""
    validate_callout_pointer(obj, objects)
    if obj.parent_id is not None:
        try:
            inverse = world_matrix(objects[obj.parent_id], objects, transforms).inverse()
            start, end = inverse.point(*start), inverse.point(*end)
        except UnsupportedWorldGeometry as exc:
            raise UnsupportedConnector(f"Callout pointer parent projection: {exc}") from exc
    return connector_geometry(obj, start, end, weight)


def callout_pointer_route(obj, objects, states, weight, *, registry_inputs=None, media_view=None):
    validate_callout_pointer(obj, objects)
    key = obj.parent_id
    while key is not None:
        state = states[key]
        if (not state.visible or state.state in {"hidden", "removed"}
                or state.opacity != 1 or state.reveal_fraction != 1):
            raise UnsupportedConnector("Callout pointer needs fully ready opaque leader ancestors")
        key = objects[key].parent_id
    start, end = _connector_endpoints(obj, objects, states, registry_inputs=registry_inputs, media_view=media_view)
    return callout_pointer_geometry(obj, objects, {key: state.transform for key, state in states.items()},
                                    start, end, weight)
