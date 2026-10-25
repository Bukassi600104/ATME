"""Authored role ownership on the existing hierarchy/replay, not a character rig."""

from atme.store.contracts_v2 import ReplaceAction, validate_character_assembly_map


def validate_character_hierarchy(objects, hierarchy):
    """No extra tree projection for legacy scenes without authored assemblies."""
    if any(getattr(obj, "character_assembly", None) is not None for obj in objects.values()):
        validate_character_assembly_map(hierarchy.object_map(objects))


def validate_character_transition(action, objects, hierarchy):
    """Ordinary within-role replacements retain stable semantic anchor leaves.

    Both immutable authored payloads already belong to the same role closure;
    all ordinary state, layer, topology and correspondence checks still apply.
    This is ownership authentication, not a new Morph policy or pose inference.
    """
    if not isinstance(action, ReplaceAction) or not any(
            getattr(obj, "character_assembly", None) is not None for obj in objects.values()):
        return
    current = hierarchy.object_map(objects)
    validate_character_assembly_map(current)
    owners = {}
    anchored = set()
    for actor in current.values():
        binding = getattr(actor, "character_assembly", None)
        if binding is None:
            continue
        anchored.update(row.object_id for row in binding.semantic_anchors)
        owners[actor.object_id] = (actor.object_id, None)
        for role in binding.roles:
            pending = [role.object_id]
            while pending:
                key = pending.pop()
                owners[key] = (actor.object_id, role.role)
                pending.extend(getattr(current[key], "child_ids", ()))
    source, destination = action.from_object_id, action.to_object_id
    if source in anchored:
        raise ValueError("character_assembly cannot replace a semantic anchor source")
    if (source in owners or destination in owners) and (
            owners.get(source) != owners.get(destination) or owners.get(source, (None, None))[1] is None):
        raise ValueError("character_assembly replacement must remain in the same real role closure")
