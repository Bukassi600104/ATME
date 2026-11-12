"""Exact current whole-part closures and read authority; paint stays with ordinary owners."""

from atme.store.contracts_v2 import (
    ConnectorObject,
    ContainerObject,
    GroupContainer,
    MaskContainer,
    _validate_progressive_parts_references,
)


def progressive_parts_inventory(action, objects, hierarchy):
    """Return ordered indivisible closures and their complete external read set."""
    _validate_progressive_parts_references(action, objects)
    policy = action.progressive_parts_policy
    hierarchy.validate(objects)
    owner = policy.container_group_id
    roots = policy.part_root_ids

    def subtree(key):
        return (key, *(child for direct in hierarchy.children(action.board_id, key)
                       for child in subtree(direct)))

    order = subtree(owner)
    if [key for key in order if key in roots] != roots:
        raise ValueError("progressive parts current root order or owner ancestry differs from policy")
    if any(isinstance(objects[root], ContainerObject) and type(objects[root]) is not GroupContainer for root in roots):
        raise ValueError("progressive parts container roots must be real Groups")
    closures = {root: subtree(root) for root in roots}
    writes = [key for closure in closures.values() for key in closure]
    if len(set(writes)) != len(writes):
        raise ValueError("progressive parts cannot overlap or nest written closures")
    if set(writes) != set(policy.expected_closure_state_versions):
        raise ValueError("progressive parts versions must cover the exact complete current closure")
    writes = set(writes)
    part_for = {key: root for root, closure in closures.items() for key in closure}
    reads = {owner}
    pending = writes | reads
    visited = set()
    while pending:
        key = pending.pop()
        if key in visited:
            continue
        visited.add(key)
        obj = objects.get(key)
        if obj is None or obj.board_id != action.board_id:
            raise ValueError("progressive parts dependency is unknown or crosses boards")
        dependencies = set(hierarchy.ancestors(key))
        if obj.clip_id is not None:
            dependencies.add(obj.clip_id)
        if isinstance(obj, MaskContainer):
            if obj.mask_source_object_id is None:
                raise ValueError("progressive parts aperture requires its explicit mask source")
            dependencies.add(obj.mask_source_object_id)
        if isinstance(obj, ConnectorObject):
            dependencies.update(value for value in (obj.source_object_id, obj.destination_object_id) if value is not None)
        owned_refs = set()
        binding = getattr(obj, "callout_binding", None)
        if binding is not None:
            owned_refs.add(binding.leader_connector_id)
            dependencies.add(binding.target_object_id)
        for field in ("character_assembly", "illustration_assembly", "technical_frame"):
            binding = getattr(obj, field, None)
            if binding is not None:
                owned_refs.update(row.object_id for row in binding.roles)
                if field == "technical_frame":
                    owned_refs.add(binding.container_group_id)
                else:
                    owned_refs.update(row.object_id for row in binding.semantic_anchors)
        binding = getattr(obj, "structured_list", None)
        if binding is not None:
            owned_refs.update((binding.container_group_id, *binding.item_object_ids))
        binding = getattr(obj, "composition_binding", None)
        if binding is not None:
            owned_refs.update(row.object_id for row in binding.instance.object_map)
        if key in part_for:
            if obj.object_type == "evidence":
                raise ValueError("progressive parts cannot replace evidence-treatment write ownership")
            if any(part_for.get(ref) != part_for[key] for ref in owned_refs):
                raise ValueError("progressive parts bound family ownership must stay within one complete part")
            # An edge into a different hidden part is an external read, never an implicit write.
            if any(ref in part_for and part_for[ref] != part_for[key] for ref in dependencies | owned_refs):
                raise ValueError("progressive parts cannot depend on a different undisclosed part")
        dependencies.update(owned_refs)
        reads.update(dependencies - writes)
        pending.update(dependencies - visited)
    if reads != set(policy.expected_read_state_versions):
        raise ValueError("progressive parts read versions must authenticate every and only current dependency")
    return closures, tuple(sorted(reads))


def validate_progressive_parts_capture(resolved, objects, hierarchy, frames, versions):
    action = resolved.action
    policy = action.progressive_parts_policy
    closures, reads = progressive_parts_inventory(action, objects, hierarchy)
    for expected in (policy.expected_closure_state_versions, policy.expected_read_state_versions):
        if any(versions[key] != version for key, version in expected.items()):
            raise ValueError("progressive parts have stale captured write/read state versions")
    for closure in closures.values():
        for key in closure:
            frame = frames[key]
            if (frame.state != "hidden" or frame.visible or frame.reveal_fraction != 0
                    or not 0 < frame.opacity <= 1):
                raise ValueError("progressive parts require untouched hidden positive-alpha complete closures")
    if any(not frames[key].visible or frames[key].reveal_fraction != 1
           or not 0 < frames[key].opacity <= 1 or frames[key].state == "removed" for key in reads):
        raise ValueError("progressive parts require complete visible authenticated read dependencies")
    return reads
