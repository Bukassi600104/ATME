"""Pure authored hierarchy step replay; chronological frame routing is separate.

Every step binds to the supplied completed frame hierarchy and local transforms.
It never fabricates a shell, parent, child, transform or changed-version receipt.
Existing frame execution does not import this module until resolved chronology,
empty-shell ownership and all consumer/conflict gates are implemented.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from math import isfinite
from typing import TYPE_CHECKING

from pydantic import ValidationError

from atme.render.v2_hierarchy import (
    HierarchySnapshot,
    UnsupportedHierarchy,
    validate_authored_hierarchy,
)
from atme.store.contracts_v2 import GroupAction, HierarchyBasis

if TYPE_CHECKING:
    from atme.render.v2_state import FrameObject


@dataclass(frozen=True)
class HierarchyStep:
    hierarchy: HierarchySnapshot
    objects: tuple[FrameObject, ...]
    state_versions: tuple[tuple[str, int], ...]
    changed_object_ids: tuple[str, ...]


def completed_hierarchy_basis(hierarchy: HierarchySnapshot, frames: dict) -> HierarchyBasis:
    """Canonical authored-basis shape from immutable, completed frame values."""
    from atme.render.v2_state import CountFrameObject, FrameObject, FrameTransform

    nodes = {node.object_id: node for node in hierarchy.nodes}
    if {node.object_id for node in hierarchy.nodes} != frames.keys() or any(
        type(frame) not in (FrameObject, CountFrameObject) or frame.object_id != object_id
        or frame.board_id != nodes[object_id].board_id or type(frame.transform) is not FrameTransform
        or type(frame.visible) is not bool or type(frame.state) is not str or not frame.state
        or any(type(value) not in (float, int) or not isfinite(value) or not 0 <= value <= 1
               for value in (frame.opacity, frame.reveal_fraction, frame.emphasis_fraction, frame.cross_out_fraction))
        for object_id, frame in frames.items()
    ):
        raise UnsupportedHierarchy("completed hierarchy basis requires the exact immutable frame inventory")
    try:
        return HierarchyBasis(placements=[{
            "object_id": node.object_id, "board_id": node.board_id, "parent_id": node.parent_id,
            "sibling_ordinal": node.sibling_ordinal, "local_transform": asdict(frames[node.object_id].transform),
        } for node in hierarchy.nodes])
    except ValidationError as exc:
        raise UnsupportedHierarchy("hierarchy basis contains an invalid completed transform") from exc


def apply_hierarchy_step(action: GroupAction, objects: dict, hierarchy: HierarchySnapshot,
                         frames: dict, state_versions: dict[str, int], active_board_id: str) -> HierarchyStep:
    """Apply one validated complete structural step, never partial interpolation.

    The caller must invoke this only at a resolved action end after chronological
    conflicts and active-board containment have been validated. All stored input
    dictionaries and layout objects remain unchanged.
    """
    from atme.render.v2_state import FrameTransform

    before, after = validate_authored_hierarchy(action, objects)
    current = completed_hierarchy_basis(hierarchy, frames)
    policy = action.hierarchy_policy
    if active_board_id != action.board_id:
        raise UnsupportedHierarchy("hierarchy step requires its authored active board")
    if (hierarchy != before or current != policy.source_basis
            or current.checksum() != policy.source_basis_sha256):
        raise UnsupportedHierarchy("hierarchy step source basis differs from the completed frame")
    if frames.keys() != objects.keys() or state_versions.keys() != objects.keys() or any(
        type(version) is not int or version < 1 for version in state_versions.values()
    ):
        raise UnsupportedHierarchy("hierarchy step requires the exact positive state-version inventory")
    if any(frame.board_id != objects[object_id].board_id for object_id, frame in frames.items()):
        raise UnsupportedHierarchy("hierarchy step cannot change frame board ownership")
    shell = frames[action.container_id]
    if shell.state != action.expected_state or shell.opacity != 1:
        raise UnsupportedHierarchy("hierarchy step requires the canonical opaque shell source state")
    dependencies = {action.container_id, *action.target_ids}
    for snapshot in (before, after):
        for root_id in action.target_ids:
            dependencies.update(snapshot.ancestors(root_id))
        dependencies.update(snapshot.ancestors(action.container_id))
    if any(not frames[key].visible or frames[key].opacity <= 0 or frames[key].reveal_fraction != 1
           for key in dependencies):
        raise UnsupportedHierarchy("hierarchy step requires fully revealed visible participant chains")
    destination = {item.object_id: item.local_transform for item in policy.destination_basis.placements}
    updated = dict(frames)
    for object_id in action.target_ids:
        updated[object_id] = replace(updated[object_id], transform=FrameTransform.from_contract(destination[object_id]))
    updated[action.container_id] = replace(shell, state=action.post_state)
    changed = tuple(policy.changed_object_ids)
    versions = dict(state_versions)
    for object_id in changed:
        versions[object_id] += 1
    if completed_hierarchy_basis(after, updated) != policy.destination_basis:
        raise UnsupportedHierarchy("hierarchy step does not exactly realize its destination receipt")
    return HierarchyStep(hierarchy=after,
                         objects=tuple(updated[key] for key in sorted(updated)),
                         state_versions=tuple(sorted(versions.items())), changed_object_ids=changed)
