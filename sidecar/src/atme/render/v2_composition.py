"""Pure explicit initial expansion into ordinary authored v2 objects.

No frame-loop expansion, resource/paint admission, semantic authoring, or hidden
members. A standalone spec is not a completed executable binding. Destination
graph comparison is separate from materialization and precedes that future gate.
"""
from __future__ import annotations

from copy import deepcopy

from pydantic import TypeAdapter

from atme.render.v2_hierarchy import HierarchySnapshot
from atme.store.contracts_v2 import (
    CompositionBinding,
    CompositionDefinition,
    CompositionInstanceSpec,
    ExecutableLayoutV2,
    ExecutableObject,
    GroupContainer,
    _composition_packet_digest,
)

_TARGET_PATHS = {
    "text": ("text",), "style.stroke": ("style", "stroke"), "style.fill": ("style", "fill"),
    "style.text": ("style", "text"),
    "geometry.bounds.x": ("geometry", "bounds", "x"),
    "geometry.bounds.y": ("geometry", "bounds", "y"),
    "geometry.bounds.width": ("geometry", "bounds", "width"),
    "geometry.bounds.height": ("geometry", "bounds", "height"),
    "transform.position.x": ("transform", "position", "x"),
    "transform.position.y": ("transform", "position", "y"),
    "transform.scale_x": ("transform", "scale_x"), "transform.scale_y": ("transform", "scale_y"),
    "transform.rotation_degrees": ("transform", "rotation_degrees"),
    "opacity": ("opacity",), "visible": ("visible",),
}


def _assign(objects, target, value):
    destination = objects[target.object_id]
    path = _TARGET_PATHS[target.field]
    for field in path[:-1]:
        destination = destination[field]
    destination[path[-1]] = value.value


def _rewrite_references(obj, ids):
    """Only actual object-reference fields, never strings/assets/anchor names."""
    if "child_ids" in obj:
        obj["child_ids"] = [ids[key] for key in obj["child_ids"]]
    for field in ("source_object_id", "destination_object_id", "mask_source_object_id"):
        if obj.get(field) is not None:
            obj[field] = ids[obj[field]]
    for field in ("character_assembly", "illustration_assembly", "technical_frame"):
        binding = obj.get(field)
        if binding is None:
            continue
        if field == "technical_frame":
            binding["container_group_id"] = ids[binding["container_group_id"]]
        for row in binding["roles"]:
            row["object_id"] = ids[row["object_id"]]
        if field != "technical_frame":
            for row in binding["semantic_anchors"]:
                row["object_id"] = ids[row["object_id"]]
    if obj.get("structured_list") is not None:
        binding = obj["structured_list"]
        binding["container_group_id"] = ids[binding["container_group_id"]]
        binding["item_object_ids"] = [ids[key] for key in binding["item_object_ids"]]
    if obj.get("callout_binding") is not None:
        binding = obj["callout_binding"]
        for field in ("leader_connector_id", "target_object_id"):
            binding[field] = ids[binding[field]]


def materialize_composition(instance_document: dict) -> tuple:
    """Build fresh initial objects; no original or shared template is mutated.

    Non-null parent IDs remain untrusted external claims until the complete
    destination graph passes validate_composition_expansion. This authoring
    function alone never accepts a project, runtime binding, clip or renderer.
    """
    spec = CompositionInstanceSpec.model_validate(instance_document)
    definition = spec.definition.model_dump(mode="json")
    local_objects = {obj["object_id"]: obj for obj in definition["objects"]}
    values = {row.parameter_id: row.value for row in spec.parameter_values}
    for parameter in spec.definition.parameters:
        for target in parameter.targets:
            _assign(local_objects, target, values[parameter.parameter_id])
    for override in spec.overrides:
        _assign(local_objects, override.target, override.value)
    # Reparse the complete substituted native graph, not only scalar types.
    definition = CompositionDefinition.model_validate(definition).model_dump(mode="json")
    ids = {row.local_object_id: row.object_id for row in spec.object_map}
    coverage = {row.local_coverage_id: row.coverage_id for row in spec.coverage_map}
    for obj in definition["objects"]:
        local_id = obj["object_id"]
        obj["object_id"] = ids[local_id]
        obj["board_id"], obj["beat_id"] = spec.board_id, spec.beat_id
        obj["coverage_ids"] = [coverage[key] for key in obj["coverage_ids"]]
        obj["parent_id"] = spec.root_parent_id if local_id == spec.definition.root_local_id else ids[obj["parent_id"]]
        if local_id == spec.definition.root_local_id:
            obj["z_index"] = spec.root_z_index
        _rewrite_references(obj, ids)
    # Validate mapped local closure independently of the external parent claim.
    # The shadow root is detached only for this check; returned ownership is exact.
    shadow = deepcopy(definition)
    shadow.update(root_local_id=spec.root_object_id, template_board_id=spec.board_id,
                  template_beat_id=spec.beat_id, parameters=[],
                  template_coverage_ids=[coverage[key] for key in spec.definition.template_coverage_ids])
    next(obj for obj in shadow["objects"] if obj["object_id"] == spec.root_object_id)["parent_id"] = None
    CompositionDefinition.model_validate(shadow)
    adapter = TypeAdapter(ExecutableObject)
    return tuple(adapter.validate_python(obj, strict=True) for obj in definition["objects"])


def validate_composition_expansion(instance_document: dict, layout_document: dict) -> None:
    """Compare every real initial member against independent materialization.

    Only ordinary Group external ancestry is accepted at this owning seam.
    Any Clip/Mask ancestor or external clip reference remains P3-37-closed.
    The layout's real inventory and density limits are never expanded or waived.
    """
    layout = ExecutableLayoutV2.model_validate(layout_document)
    objects = {obj.object_id: obj for obj in layout.objects}
    _validate_expansion_objects(CompositionInstanceSpec.model_validate(instance_document), objects)


def _initial_document(obj, owner_id=None):
    document = obj.model_dump(mode="json")
    if obj.object_id == owner_id:
        document.pop("composition_binding", None)
    return document


def _validate_expansion_objects(spec, objects, *, bound_owner=None):
    expected = materialize_composition(spec.model_dump(mode="json"))
    for obj in expected:
        actual = objects.get(obj.object_id)
        if actual is None or _initial_document(actual, bound_owner) != obj.model_dump(mode="json"):
            raise ValueError("composition destination changes or omits an exact initial expanded member")
    parent_id = spec.root_parent_id
    while parent_id is not None:
        parent = objects.get(parent_id)
        if (type(parent) is not GroupContainer or parent.clip_id is not None
                or any(getattr(parent, field, None) is not None for field in (
                    "character_assembly", "illustration_assembly", "composition_binding"))):
            raise ValueError("composition external parent requires only ordinary reciprocal Groups; clipping remains closed")
        parent_id = parent.parent_id
    if spec.root_parent_id is not None and spec.root_object_id not in objects[spec.root_parent_id].child_ids:
        raise ValueError("composition external parent must declare reciprocal root membership")


def _initial_member_receipts(objects, object_ids, hierarchy, *, bound_owner=None):
    nodes = {row.object_id: row for row in hierarchy.nodes}
    return [{"object_id": key, "initial_object_sha256": _composition_packet_digest(_initial_document(objects[key], bound_owner)),
             "parent_id": objects[key].parent_id, "sibling_ordinal": nodes[key].sibling_ordinal}
            for key in sorted(object_ids)]


def composition_initial_members(instance_document: dict, *, root_ordinal: int) -> list[dict]:
    """Recompute intrinsic receipt syntax; root ordinal is not self-attested.

    The external root's ordinal cannot be proved from the expansion alone.
    Binding model syntax supplies it, but actual-layout verification independently
    derives EVERY ordinal from the complete destination hierarchy below.
    """
    if type(root_ordinal) is not int or root_ordinal < 0:
        raise ValueError("composition root ordinal must be a nonnegative integer")
    spec = CompositionInstanceSpec.model_validate(instance_document)
    objects = {obj.object_id: obj for obj in materialize_composition(instance_document)}
    shadow = {key: obj.model_copy(deep=True) for key, obj in objects.items()}
    shadow[spec.root_object_id] = shadow[spec.root_object_id].model_copy(update={"parent_id": None})
    result = _initial_member_receipts(objects, objects, HierarchySnapshot.from_objects(shadow))
    next(row for row in result if row["object_id"] == spec.root_object_id)["sibling_ordinal"] = root_ordinal
    return result


def build_composition_binding(instance_document: dict, layout_document: dict) -> dict:
    """Derive a receipt from independently compared real initial target objects."""
    spec = CompositionInstanceSpec.model_validate(instance_document)
    validate_composition_expansion(instance_document, layout_document)
    layout = ExecutableLayoutV2.model_validate(layout_document)
    objects = {obj.object_id: obj for obj in layout.objects}
    members = _initial_member_receipts(objects, {row.object_id for row in spec.object_map},
                                       HierarchySnapshot.from_objects(objects))
    packet = {"version": "1.0.0", "instance": spec.model_dump(mode="json"), "members": members}
    packet["expansion_sha256"] = _composition_packet_digest(packet)
    return CompositionBinding.model_validate(packet).model_dump(mode="json")


def validate_composition_binding(binding_document: dict, layout_document: dict) -> None:
    """A self-consistent packet is insufficient: compare actual complete graph."""
    binding = CompositionBinding.model_validate(binding_document)
    layout = ExecutableLayoutV2.model_validate(layout_document)
    objects = {obj.object_id: obj for obj in layout.objects}
    validate_composition_binding_objects(binding, objects)


def validate_composition_binding_objects(binding, objects) -> None:
    """Initial graph hook: never reparse a layout from its own validator.

    Strip only this intrinsically validated owner's matching receipt, not child
    bindings, native payloads, mutable geometry or any other object field.
    """
    spec = binding.instance
    owner = objects.get(spec.root_object_id)
    attached = getattr(owner, "composition_binding", None)
    if attached is not None and attached != binding:
        raise ValueError("composition owner has a different initial binding")
    bound_owner = spec.root_object_id if attached is not None else None
    _validate_expansion_objects(spec, objects, bound_owner=bound_owner)
    expected = _initial_member_receipts(objects, {row.object_id for row in spec.object_map},
                                        HierarchySnapshot.from_objects(objects), bound_owner=bound_owner)
    if [row.model_dump(mode="json") for row in binding.members] != expected:
        raise ValueError("composition receipts do not match the complete initial hierarchy and actual object hashes")
