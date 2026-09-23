"""Shared static support gate for the bounded v2 semantic-arrow runtime."""

from __future__ import annotations

from atme.store.contracts_v2 import ConnectorObject


class UnsupportedConnector(ValueError):
    """An authored connector cannot be executed by the bounded arrow runtime."""


def validate_static_arrow(obj: ConnectorObject, objects: dict) -> None:
    if obj.object_type != "arrow" or obj.role != "semantic_connector":
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
