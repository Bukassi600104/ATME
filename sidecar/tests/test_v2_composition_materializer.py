"""Explicit instance inputs and initial ordinary-graph expansion, not admission."""
import importlib
from copy import deepcopy

import pytest
from atme.store import contracts_v2 as contracts
from test_v2_composition_contract import bound_native_definition, composition_definition
from v2_fixtures import executable_layout_v2


def instance_spec(definition=None, root="intro:one"):
    definition = definition or composition_definition()
    return {
        "version": "1.0.0", "kind": "instance", "definition": definition,
        "definition_sha256": contracts.composition_definition_digest(definition),
        "root_object_id": root, "board_id": "board-main", "beat_id": "beat-001",
        "root_parent_id": None, "root_z_index": 3,
        "coverage_map": [{"local_coverage_id": key, "coverage_id": key}
                         for key in definition["template_coverage_ids"]],
        "object_map": [{"local_object_id": obj["object_id"], "object_id": root if obj["object_id"] == definition["root_local_id"]
                        else f"composition-{len(root)}:{root}:{obj['object_id']}"} for obj in definition["objects"]],
        "parameter_values": [
            {"parameter_id": "caption", "value": {"value_type": "string", "value": "A new system"}},
            {"parameter_id": "color", "value": {"value_type": "string", "value": "surface.accent"}},
            {"parameter_id": "width", "value": {"value_type": "number", "value": 620.0}},
            {"parameter_id": "shown", "value": {"value_type": "boolean", "value": True}},
        ] if definition["parameters"] else [],
        "overrides": [{"target": {"object_id": "node", "field": "transform.position.x"},
                       "value": {"value_type": "number", "value": 25.0}}] if definition["parameters"] else [],
    }


def spec_type():
    assert hasattr(contracts, "CompositionInstanceSpec"), "explicit composition instance input is missing"
    return contracts.CompositionInstanceSpec


def materializer():
    assert importlib.util.find_spec("atme.render.v2_composition") is not None, "pure initial composition materializer is missing"
    return importlib.import_module("atme.render.v2_composition")


def layout_for_expansion(objects, *, parent=None):
    layout = executable_layout_v2()
    layout["objects"] = [obj.model_dump(mode="json") for obj in objects]
    if parent is not None:
        outer = deepcopy(layout["objects"][0])
        outer.update(object_id="outer", parent_id=None, object_type=parent,
                     child_ids=[layout["objects"][0]["object_id"]])
        layout["objects"].insert(0, outer)
    layout["evidence_treatments"] = []
    layout["boards"][0].update(object_ids=[obj["object_id"] for obj in layout["objects"]], density_limit=12)
    return layout


def test_instance_spec_has_explicit_context_and_canonical_disjoint_ids():
    raw = instance_spec()
    assert spec_type().model_validate(raw).model_dump(mode="json") == {
        **raw, "definition": contracts.CompositionDefinition.model_validate(raw["definition"]).model_dump(mode="json")}
    assert raw["object_map"] == [
        {"local_object_id": "root", "object_id": "intro:one"},
        {"local_object_id": "node", "object_id": "composition-9:intro:one:node"},
        {"local_object_id": "label", "object_id": "composition-9:intro:one:label"},
    ]
    assert contracts.composition_expanded_object_id("a", "b::c") == "composition-1:a:b::c"
    assert contracts.composition_expanded_object_id("a::b", "c") == "composition-4:a::b:c"
    assert contracts.composition_expanded_object_id("a", "b::c") != contracts.composition_expanded_object_id("a::b", "c")
    assert sorted(contracts.composition_expanded_object_id("root", local) for local in ("b", "a", "a::b")) == [
        "composition-4:root:a", "composition-4:root:a::b", "composition-4:root:b"]


@pytest.mark.parametrize("value_type,value", [("number", True), ("number", "1"), ("number", float("nan")),
    ("number", float("inf")), ("string", 1), ("boolean", 1), ("boolean", "true")])
def test_tagged_scalar_values_never_coerce_or_infer(value_type, value):
    raw = instance_spec()
    raw["parameter_values"][2]["value"] = {"value_type": value_type, "value": value}
    with pytest.raises(ValueError):
        spec_type().model_validate(raw)


@pytest.mark.parametrize("defect", ["hash", "missing_parameter", "extra_parameter", "duplicate_parameter",
    "parameter_type", "missing_id", "duplicate_id", "arbitrary_id", "old_ambiguous_id", "missing_coverage",
    "aliased_coverage", "duplicate_coverage", "foreign_override", "wrong_override_type", "parameter_conflict",
    "duplicate_override", "identity_override", "ignored_override", "local_parent", "bool_z"])
def test_instance_spec_rejects_ambiguous_bindings_maps_and_overrides(defect):
    raw = instance_spec()
    if defect == "hash":
        raw["definition_sha256"] = "0" * 64
    elif defect == "missing_parameter":
        raw["parameter_values"].pop()
    elif defect == "extra_parameter":
        raw["parameter_values"].append({"parameter_id": "unknown", "value": {"value_type": "boolean", "value": True}})
    elif defect == "duplicate_parameter":
        raw["parameter_values"].append(deepcopy(raw["parameter_values"][0]))
    elif defect == "parameter_type":
        raw["parameter_values"][0]["value"] = {"value_type": "number", "value": 1.0}
    elif defect == "missing_id":
        raw["object_map"].pop()
    elif defect == "duplicate_id":
        raw["object_map"].append(deepcopy(raw["object_map"][0]))
    elif defect == "arbitrary_id":
        raw["object_map"][1]["object_id"] = "selected-by-author"
    elif defect == "old_ambiguous_id":
        raw["object_map"][1]["object_id"] = "intro:one::node"
    elif defect == "missing_coverage":
        raw["coverage_map"].pop()
    elif defect == "aliased_coverage":
        raw["coverage_map"][1]["coverage_id"] = raw["coverage_map"][0]["coverage_id"]
    elif defect == "duplicate_coverage":
        raw["coverage_map"].append(deepcopy(raw["coverage_map"][0]))
    elif defect == "foreign_override":
        raw["overrides"][0]["target"]["object_id"] = "outer-object"
    elif defect == "wrong_override_type":
        raw["overrides"][0]["value"] = {"value_type": "boolean", "value": True}
    elif defect == "parameter_conflict":
        raw["overrides"][0]["target"]["field"] = "geometry.bounds.width"
    elif defect == "duplicate_override":
        raw["overrides"].append(deepcopy(raw["overrides"][0]))
    elif defect == "identity_override":
        raw["overrides"][0]["target"]["field"] = "object_id"
    elif defect == "ignored_override":
        raw["overrides"][0].update(target={"object_id": "label", "field": "style.fill"},
                                    value={"value_type": "string", "value": "surface.accent"})
    elif defect == "local_parent":
        raw["root_parent_id"] = raw["object_map"][1]["object_id"]
    else:
        raw["root_z_index"] = True
    with pytest.raises(ValueError):
        spec_type().model_validate(raw)


def test_materialization_is_explicit_nonmutating_and_preserves_native_content():
    raw = instance_spec()
    original = deepcopy(raw)
    objects = materializer().materialize_composition(raw)
    root, node, label = objects
    assert type(root) is contracts.GroupContainer and type(node) is contracts.MarkObject
    assert type(label) is contracts.TextObject
    assert root.object_id == "intro:one" and root.z_index == 3 and root.parent_id is None
    assert root.child_ids == ["composition-9:intro:one:node", "composition-9:intro:one:label"]
    assert node.geometry.bounds.width == 620.0 and node.transform.position.x == 25.0
    assert node.style.fill == "surface.accent" and label.text == "A new system" and label.visible
    assert node.board_id == label.board_id == "board-main"
    assert node.beat_id == label.beat_id == "beat-001"
    assert node.coverage_ids == ["coverage-1"] and label.coverage_ids == ["coverage-2"]
    assert raw == original
    node.geometry.bounds.width = 10.0
    fresh = materializer().materialize_composition(raw)
    assert fresh[1].geometry.bounds.width == 620.0
    assert raw == original


@pytest.mark.parametrize("family", ["character", "illustration", "technical", "list", "callout"])
def test_only_enumerated_real_references_are_rewritten(family):
    definition = bound_native_definition(family)
    # Text/description/asset IDs are not object-reference substitution channels.
    definition["objects"][0]["description"] = "root remains root; node remains node"
    raw = instance_spec(definition)
    objects = materializer().materialize_composition(raw)
    remapped = {row["local_object_id"]: row["object_id"] for row in raw["object_map"]}
    by_id = {obj.object_id: obj for obj in objects}
    for original in contracts.CompositionDefinition.model_validate(definition).objects:
        actual = by_id[remapped[original.object_id]]
        assert actual.description == original.description
        assert actual.asset_id == original.asset_id
        if isinstance(original, contracts.TextObject):
            assert actual.text == original.text and actual.code_payload == original.code_payload
        for field in ("character_assembly", "illustration_assembly", "technical_frame"):
            binding = getattr(original, field, None)
            if binding is not None:
                updated = getattr(actual, field)
                assert [row.object_id for row in updated.roles] == [remapped[row.object_id] for row in binding.roles]
        if getattr(original, "structured_list", None) is not None:
            assert actual.structured_list.item_object_ids == [remapped[key] for key in original.structured_list.item_object_ids]
        if getattr(original, "callout_binding", None) is not None:
            assert actual.callout_binding.target_object_id == remapped[original.callout_binding.target_object_id]
    # Exact Callout-owned pointers now share the ordinary Group-local path;
    # the full real destination must validate, not just reference rewriting.
    materializer().validate_composition_expansion(raw, layout_for_expansion(objects))


@pytest.mark.parametrize("defect", ["negative_width", "zero_scale", "opacity", "conflicting_text_override"])
def test_full_substitution_is_reparsed_not_trusted_as_typed_values(defect):
    raw = instance_spec()
    if defect == "negative_width":
        raw["parameter_values"][2]["value"]["value"] = -1.0
    elif defect == "zero_scale":
        raw["overrides"][0]["target"]["field"] = "transform.scale_x"
        raw["overrides"][0]["value"]["value"] = 0.0
    elif defect == "opacity":
        raw["overrides"][0]["target"]["field"] = "opacity"
        raw["overrides"][0]["value"]["value"] = 2.0
    else:
        raw["overrides"][0].update(target={"object_id": "label", "field": "text"},
                                    value={"value_type": "string", "value": "not-an-expression"})
    with pytest.raises(ValueError):
        materializer().materialize_composition(raw)


@pytest.mark.parametrize("parent", [None, "group", "clip", "mask"])
def test_destination_parent_is_only_real_ordinary_group_until_p3_37(parent):
    raw = instance_spec()
    if parent is not None:
        raw["root_parent_id"] = "outer"
    objects = materializer().materialize_composition(raw)
    layout = layout_for_expansion(objects, parent=parent)
    if parent in {"clip", "mask"}:
        with pytest.raises(ValueError):
            materializer().validate_composition_expansion(raw, layout)
    else:
        materializer().validate_composition_expansion(raw, layout)


@pytest.mark.parametrize("defect", ["text", "width", "parent", "order", "missing_member", "wrong_board", "density"])
def test_destination_graph_cannot_launder_a_coherently_changed_expansion(defect):
    raw = instance_spec()
    layout = layout_for_expansion(materializer().materialize_composition(raw))
    if defect == "text":
        layout["objects"][2]["text"] = "another authored meaning"
    elif defect == "width":
        layout["objects"][1]["geometry"]["bounds"]["width"] = 621.0
    elif defect == "parent":
        layout["objects"][1]["parent_id"] = None
        layout["objects"][0]["child_ids"].remove(layout["objects"][1]["object_id"])
    elif defect == "order":
        layout["objects"][1]["z_index"] = 8
    elif defect == "missing_member":
        layout["objects"].pop()
        layout["objects"][0]["child_ids"].pop()
        layout["boards"][0]["object_ids"].pop()
    elif defect == "wrong_board":
        raw["board_id"] = "outer-board"
    else:
        layout["boards"][0]["density_limit"] = 2
    with pytest.raises(ValueError):
        materializer().validate_composition_expansion(raw, layout)


@pytest.mark.parametrize("kind", ["clip", "mask"])
def test_internal_aperture_and_mask_source_references_are_explicitly_remapped(kind):
    definition = composition_definition()
    definition["parameters"] = []
    root, _node, label = definition["objects"]
    aperture = deepcopy(root)
    aperture.update(object_id="aperture", object_type=kind, parent_id="root", child_ids=["label"])
    label["parent_id"] = "aperture"
    root["child_ids"] = ["node", "aperture"]
    if kind == "mask":
        aperture.update(mask_mode="alpha", mask_source_object_id="node", mask_coordinate_space="parent_local",
                        invert=False, feather_px=0)
        aperture["geometry"]["corner_radius"] = None
    definition["objects"].append(aperture)
    raw = instance_spec(definition)
    objects = materializer().materialize_composition(raw)
    ids = {row["local_object_id"]: row["object_id"] for row in raw["object_map"]}
    assert objects[-1].child_ids == [ids["label"]]
    if kind == "mask":
        assert objects[-1].mask_source_object_id == ids["node"]
    materializer().validate_composition_expansion(raw, layout_for_expansion(objects))


def test_pure_materializer_is_offline_and_repeated_outputs_do_not_share_mutable_nodes(monkeypatch):
    import socket
    from pathlib import Path

    raw = instance_spec()
    module = materializer()
    expected = [obj.model_dump(mode="json") for obj in module.materialize_composition(raw)]

    def forbidden(*args, **kwargs):
        raise AssertionError("pure initial materialization must not access files or network")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    for _ in range(3):
        actual = module.materialize_composition(deepcopy(raw))
        assert [obj.model_dump(mode="json") for obj in actual] == expected
        actual[0].child_ids.clear()


@pytest.mark.parametrize("target", ["spec", "scalar", "nested_spec"])
def test_typed_input_instances_cannot_skip_raw_wire_validation(target):
    raw = instance_spec()
    if target == "spec":
        typed = spec_type().model_validate(raw)
        with pytest.raises(ValueError):
            spec_type().model_validate(typed)
    elif target == "nested_spec":
        raw["definition"] = contracts.CompositionDefinition.model_validate(raw["definition"])
        with pytest.raises(ValueError):
            spec_type().model_validate(raw)
    else:
        typed = contracts.CompositionNumberValue.model_validate({"value_type": "number", "value": 1.0})
        with pytest.raises(ValueError):
            contracts.CompositionNumberValue.model_validate(typed)


def test_external_group_cannot_borrow_the_expansion_as_a_special_assembly_role():
    definition = composition_definition()
    definition["template_coverage_ids"] = ["coverage-1"]
    for obj in definition["objects"]:
        obj["coverage_ids"] = ["coverage-1"]
    raw = instance_spec(definition)
    raw["root_parent_id"] = "outer"
    layout = layout_for_expansion(materializer().materialize_composition(raw), parent="group")
    layout["objects"][0]["illustration_assembly"] = {
        "version": "1.0.0", "family": "device", "content_state_id": "whole",
        "roles": [{"role_id": "content", "kind": "content", "object_id": raw["root_object_id"]}],
        "semantic_anchors": [],
    }
    contracts.ExecutableLayoutV2.model_validate(layout)
    with pytest.raises(ValueError, match="ordinary"):
        materializer().validate_composition_expansion(raw, layout)
