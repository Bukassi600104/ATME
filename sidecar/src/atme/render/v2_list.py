"""Shared fail-closed support rules for authored one-line list disclosure."""

from __future__ import annotations

from atme.store.contracts_v2 import (
    ContainerObject,
    MaskContainer,
    TextObject,
    _validate_structured_progression_objects,
)

_LINE_BREAKS = frozenset("\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029")


class UnsupportedOrderedList(ValueError):
    """An authored list cannot be disclosed as complete ordered items."""


def validate_ordered_list(obj: TextObject) -> None:
    if obj.object_type != "list" or not obj.items:
        raise UnsupportedOrderedList(f"v2 object {obj.object_id} needs an authored ordered-child list")
    if any(not value.strip() or any(char in _LINE_BREAKS for char in value)
           for value in (obj.text, *obj.items)):
        raise UnsupportedOrderedList(
            f"v2 list {obj.object_id} requires nonblank, one-line heading and items"
        )


def structured_list_reads(action, objects, hierarchy) -> tuple[str, ...]:
    """Exact current ancestry/order reads, never inferred item identities."""
    _validate_structured_progression_objects(action, objects)
    policy = action.structured_list_policy
    selected = (policy.list_object_id, *policy.item_object_ids)
    reads = {policy.list_object_id, policy.container_group_id}
    for key in selected:
        ancestors = hierarchy.ancestors(key)
        if policy.container_group_id not in ancestors:
            raise UnsupportedOrderedList("structured list needs its declared current Group ancestry")
        for parent in ancestors[:ancestors.index(policy.container_group_id) + 1]:
            if objects[parent].object_type != "group":
                raise UnsupportedOrderedList("structured list nesting requires authored Groups")
        reads.update(ancestors)

    def leaves(key):
        obj = objects[key]
        if isinstance(obj, ContainerObject):
            return [leaf for child in hierarchy.children(action.board_id, key) for leaf in leaves(child)]
        return [key]

    if [key for key in leaves(policy.container_group_id) if key in selected] != list(selected):
        raise UnsupportedOrderedList("structured list current heading/item order differs from its authored policy")
    pending = set(selected) | reads
    visited = set()
    while pending:
        key = pending.pop()
        if key in visited:
            continue
        visited.add(key)
        obj = objects.get(key)
        if obj is None or obj.board_id != action.board_id:
            raise UnsupportedOrderedList("structured list aperture dependency is unknown or crosses boards")
        dependencies = set(hierarchy.ancestors(key))
        if obj.clip_id is not None:
            dependencies.add(obj.clip_id)
        if isinstance(obj, MaskContainer):
            if obj.mask_source_object_id is None:
                raise UnsupportedOrderedList("structured list aperture needs an explicit mask source")
            dependencies.add(obj.mask_source_object_id)
        reads.update(dependencies)
        pending.update(dependencies - visited)
    return tuple(sorted(reads))


def validate_structured_list_capture(resolved, objects, hierarchy, frames, versions) -> tuple[str, ...]:
    """Authenticate real item state/versions and readable dependencies at start."""
    action = resolved.action
    policy = action.structured_list_policy
    reads = structured_list_reads(action, objects, hierarchy)
    if frames[policy.list_object_id].state != "visible":
        raise UnsupportedOrderedList("structured list needs a semantically visible readable heading")
    if {key: versions[key] for key in policy.item_object_ids} != policy.expected_item_state_versions:
        raise UnsupportedOrderedList("structured list has stale captured item state versions")
    for key in policy.item_object_ids:
        frame = frames[key]
        if (frame.state != "hidden" or frame.visible or frame.reveal_fraction != 0
                or not 0 < frame.opacity <= 1):
            raise UnsupportedOrderedList("structured list requires untouched hidden positive-alpha items at start")
    if any(not frames[key].visible or frames[key].reveal_fraction != 1
           or not 0 < frames[key].opacity <= 1 or frames[key].state == "removed" for key in reads):
        raise UnsupportedOrderedList("structured list needs a complete readable heading and visible ancestor dependencies")
    return reads
