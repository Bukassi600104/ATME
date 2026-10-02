"""Bounded authored annotation geometry and reading-hold checks.

Notes are real authored leaves, never renderer-generated copy. The referenced
target is read-only; source evidence uses its separate attested treatment.
"""

from __future__ import annotations

import math

from atme.render.style_bundle import resolve_contract_bundle
from atme.render.v2_world import world_anchor, world_bounds, world_matrix
from atme.store.contracts_v2 import (
    TextObject,
    _annotation_object_ids,
    _validate_annotation_layout,
    _validate_annotation_plan_objects,
)


def validate_annotation_geometry(action, layout, objects, transforms, viewports):
    """Validate final authored paint, transformed anchors, and on-screen size."""
    _validate_annotation_plan_objects(action, objects)
    _validate_annotation_layout(action, objects)
    ids = [action.target_ids[0], *_annotation_object_ids(action)]
    for object_id in ids:
        parent_id = objects[object_id].parent_id
        while parent_id is not None:
            if objects[parent_id].object_type != "group":
                raise ValueError("annotation requires unclipped group ancestry")
            parent_id = objects[parent_id].parent_id
    style, _, _ = resolve_contract_bundle(layout.style_system_version, layout.asset_registry_version)
    design_key = "landscape-16:9" if layout.output_profile.profile_id == "LONG_FORM_16_9" else "portrait-9:16"
    scale = layout.output_profile.width / style.aspects[design_key].width
    roles = {"text.heading": style.typography.title, "text.label": style.typography.label,
             "text.body": style.typography.body, "text.muted": style.typography.body,
             "text.accent": style.typography.body}
    for object_id in ids:
        obj = objects[object_id]
        rect = world_bounds(obj, objects, transforms)
        for viewport in viewports:
            if (rect[0] < viewport.x or rect[1] < viewport.y
                    or rect[2] > viewport.x + viewport.width
                    or rect[3] > viewport.y + viewport.height):
                raise ValueError(f"annotation participant {object_id} is outside its reading viewport")
            if isinstance(obj, TextObject):
                role = roles.get(obj.style.text)
                if role is None:
                    raise ValueError(f"annotation text {object_id} needs pinned typography")
                matrix = world_matrix(obj, objects, transforms)
                origin = matrix.point(0, 0)
                x, y = matrix.point(1, 0), matrix.point(0, 1)
                a, b = x[0] - origin[0], x[1] - origin[1]
                c, d = y[0] - origin[0], y[1] - origin[1]
                # Smallest singular value catches flattening and nested shear.
                norm = a*a + b*b + c*c + d*d
                determinant = a*d - b*c
                largest = (norm + math.sqrt(max(0, norm*norm - 4*determinant*determinant))) / 2
                smallest = abs(determinant) / math.sqrt(largest) if largest > 0 else 0
                size = role.size_px * scale * smallest * layout.canvas.width / viewport.width
                if size < 18 * scale:
                    raise ValueError(f"annotation text {object_id} is too small to read")
    leader_id = action.annotation_policy.leader_connector_id
    if leader_id is not None:
        leader = objects[leader_id]
        start = world_anchor(objects[leader.source_object_id], leader.source_anchor_id, objects, transforms)
        end = world_anchor(objects[leader.destination_object_id], leader.destination_anchor_id, objects, transforms)
        bounds = leader.geometry.bounds
        if start == end or any(not (bounds.x <= x <= bounds.x + bounds.width
                                   and bounds.y <= y <= bounds.y + bounds.height) for x, y in (start, end)):
            raise ValueError("annotation pointer world endpoints exceed its authored route bounds")
