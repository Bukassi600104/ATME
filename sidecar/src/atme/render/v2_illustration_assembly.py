"""Authored illustration role ownership on the existing hierarchy and clock."""

from atme.store.contracts_v2 import ReplaceAction, validate_illustration_assembly_map


def validate_illustration_hierarchy(objects, hierarchy):
    """Leave legacy scenes untouched; never substitute initial for current roles."""
    if any(getattr(obj, "illustration_assembly", None) is not None for obj in objects.values()):
        validate_illustration_assembly_map(hierarchy.object_map(objects))


def validate_illustration_transition(action, objects, hierarchy):
    """Allow ordinary within-role transitions without moving semantic identity.

    Existing Replace/Morph geometry, lifecycle and state rules remain the
    authority. This guard authenticates only authored role/anchor ownership.
    """
    if not isinstance(action, ReplaceAction) or not any(
            getattr(obj, "illustration_assembly", None) is not None for obj in objects.values()):
        return
    current = hierarchy.object_map(objects)
    validate_illustration_assembly_map(current)
    owners = {}
    anchored = set()
    for assembly in current.values():
        binding = getattr(assembly, "illustration_assembly", None)
        if binding is None:
            continue
        owners[assembly.object_id] = (assembly.object_id, None)
        anchored.update(row.object_id for row in binding.semantic_anchors)
        for role in binding.roles:
            pending = [role.object_id]
            while pending:
                key = pending.pop()
                owners[key] = (assembly.object_id, role.role_id)
                pending.extend(getattr(current[key], "child_ids", ()))
    source, destination = action.from_object_id, action.to_object_id
    if source in anchored:
        raise ValueError("illustration_assembly cannot replace a semantic anchor source")
    if (source in owners or destination in owners) and (
            owners.get(source) != owners.get(destination) or owners.get(source, (None, None))[1] is None):
        raise ValueError("illustration_assembly replacement must remain in the same real role closure")
