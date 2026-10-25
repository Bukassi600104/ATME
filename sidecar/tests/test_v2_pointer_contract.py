"""P3-28: explicit free-source authority, never an inferred/self-loop source."""

from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from test_v2_connector_svg import connector_documents

from atme.store.contracts_v2 import (
    ConnectorObject,
    SemanticStandardObjectSpec,
    validate_plan_layout,
)


def pointer_payload():
    layout, _ = connector_documents()
    raw = deepcopy(layout["objects"][3])
    raw.update(role="pointer", source_object_id=None, source_anchor_id=None,
               source_point={"x": 80.5, "y": 60.25})
    raw["geometry"]["bounds"] = {"x": 0, "y": 0, "width": 1280, "height": 720}
    return raw


def test_authored_source_point_loads_without_fabricating_a_source_object():
    raw = pointer_payload()
    pointer = ConnectorObject.model_validate(raw)
    assert pointer.source_point.model_dump() == {"x": 80.5, "y": 60.25}
    assert pointer.source_object_id is pointer.source_anchor_id is None
    assert pointer.destination_object_id == "object-label"
    assert pointer.model_dump(mode="json") == raw


def test_pointer_json_schema_accepts_the_same_exact_source_authority():
    assert not list(Draft202012Validator(ConnectorObject.model_json_schema()).iter_errors(pointer_payload()))


def test_legacy_connector_shape_and_named_endpoints_remain_unchanged():
    layout, _ = connector_documents()
    raw = layout["objects"][3]
    dumped = ConnectorObject.model_validate(raw).model_dump(mode="json")
    assert dumped == raw
    assert "source_point" not in dumped
    assert dumped["source_object_id"] == "object-system"
    assert dumped["source_anchor_id"] == "center"


@pytest.mark.parametrize("point", [None, {}, {"x": 2}, {"x": "2", "y": 3},
    {"x": True, "y": 3}, {"x": 2, "y": False}, {"x": 2, "y": 3, "extra": 1},
    {"x": 1_000_001, "y": 3}, {"x": 2, "y": -1_000_001}])
def test_pointer_model_and_schema_reject_ignored_or_coerced_point_payload(point):
    raw = pointer_payload()
    raw["source_point"] = point
    with pytest.raises(ValidationError):
        ConnectorObject.model_validate(raw)
    assert list(Draft202012Validator(ConnectorObject.model_json_schema()).iter_errors(raw))


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_pointer_source_point_rejects_nonfinite_json_in_memory(value):
    raw = pointer_payload()
    raw["source_point"]["x"] = value
    with pytest.raises(ValidationError):
        ConnectorObject.model_validate(raw)


@pytest.mark.parametrize("mutation", [{"source_object_id": "object-system"},
    {"source_anchor_id": "center"}, {"role": "semantic_connector"}, {"object_type": "network"}])
def test_source_point_cannot_mix_or_relabel_endpoint_authority(mutation):
    raw = pointer_payload()
    raw.update(mutation)
    with pytest.raises(ValidationError):
        ConnectorObject.model_validate(raw)
    assert list(Draft202012Validator(ConnectorObject.model_json_schema()).iter_errors(raw))


def semantic_pointer(raw=None):
    raw = pointer_payload() if raw is None else raw
    semantic = {key: raw[key] for key in ("object_id", "object_type", "board_id", "beat_id",
        "semantic_role", "description", "asset_id", "initial_state", "coverage_ids")}
    semantic["connector_binding"] = {key: deepcopy(raw[key]) for key in (
        "source_point", "source_object_id", "source_anchor_id", "destination_object_id",
        "destination_anchor_id", "role", "routing", "allow_self_loop")}
    return semantic


def test_semantic_pointer_retains_the_exact_source_target_and_route_authority():
    raw = semantic_pointer()
    parsed = SemanticStandardObjectSpec.model_validate(raw)
    assert parsed.model_dump(mode="json")["connector_binding"] == raw["connector_binding"]
    assert not list(Draft202012Validator(SemanticStandardObjectSpec.model_json_schema()).iter_errors(raw))


@pytest.mark.parametrize("owner", ["line", "callout", "image", "network"])
def test_free_point_binding_cannot_be_relabelled_as_another_semantic_owner(owner):
    raw = semantic_pointer()
    raw["object_type"] = owner
    with pytest.raises(ValidationError):
        SemanticStandardObjectSpec.model_validate(raw)
    assert list(Draft202012Validator(SemanticStandardObjectSpec.model_json_schema()).iter_errors(raw))


def pointer_documents():
    from test_v2_image_placement_contract import image_documents
    from v2_fixtures import digest

    plan, layout = image_documents()
    old = layout["objects"][0]
    pointer = pointer_payload()
    for key in ("object_id", "board_id", "beat_id", "semantic_role", "description",
                "initial_state", "coverage_ids", "z_index"):
        pointer[key] = deepcopy(old[key])
    pointer["asset_id"] = None
    layout["objects"][0] = pointer
    layout["objects"][1]["anchors"].append({"anchor_id": "other", "point": {"x": 0, "y": 0.5}})
    plan["objects"][0] = semantic_pointer(pointer)
    plan["actions"][0]["verb"] = "draw"
    layout["plan_sha256"] = digest(plan)
    return plan, layout


def test_pointer_plan_and_layout_share_the_same_authored_authority():
    plan, layout = pointer_documents()
    validate_plan_layout(plan, layout)


@pytest.mark.parametrize("fault", ["point", "target_anchor", "routing", "missing_binding"])
def test_coherent_layout_rehash_cannot_reauthor_the_semantic_pointer(fault):
    from v2_fixtures import digest

    plan, layout = pointer_documents()
    if fault == "point":
        layout["objects"][0]["source_point"]["x"] += 1
    elif fault == "target_anchor":
        layout["objects"][0]["destination_anchor_id"] = "other"
    elif fault == "routing":
        layout["objects"][0]["routing"] = "curve"
    else:
        plan["objects"][0].pop("connector_binding")
    layout["plan_sha256"] = digest(plan)
    with pytest.raises(ValueError, match="connector_binding"):
        validate_plan_layout(plan, layout)


def test_source_point_is_content_not_an_unpinned_geometry_hint():
    from test_v2_split_identity import sample_for_layout

    from atme.render.v2_split_identity import split_content_receipts
    from atme.store.contracts_v2 import ExecutableLayoutV2

    _plan, raw = pointer_documents()

    def receipt(document):
        layout = ExecutableLayoutV2.model_validate(document)
        return next(row for row in split_content_receipts(layout, sample_for_layout(layout), {})
                    if row.object_id == "object-system")

    original = receipt(raw)
    changed = deepcopy(raw)
    changed["objects"][0]["source_point"]["x"] += 1
    assert receipt(changed).content_sha256 != original.content_sha256


def test_source_point_identity_rejects_an_unknown_nested_model_subclass():
    from test_v2_split_identity import sample_for_layout

    from atme.render.v2_split_identity import split_content_receipts
    from atme.store.contracts_v2 import ExecutableLayoutV2

    _plan, raw = pointer_documents()
    layout = ExecutableLayoutV2.model_validate(raw)
    point = layout.objects[0].source_point

    class UnknownPoint(type(point)):
        pass

    altered = layout.objects[0].model_copy(update={"source_point": UnknownPoint.model_validate(point.model_dump())})
    layout = layout.model_copy(update={"objects": [altered, *layout.objects[1:]]})
    with pytest.raises(ValueError, match="unknown nested payload subclass"):
        split_content_receipts(layout, sample_for_layout(layout), {})


def network_semantic():
    semantic = semantic_pointer()
    semantic["object_type"] = "network"
    binding = semantic["connector_binding"]
    binding.pop("source_point")
    binding.update(role="semantic_connector", source_object_id="network-source", source_anchor_id="center")
    return semantic


def test_network_semantic_binding_has_only_explicit_named_endpoint_authority():
    raw = network_semantic()
    parsed = SemanticStandardObjectSpec.model_validate(raw)
    assert parsed.model_dump(mode="json")["connector_binding"] == raw["connector_binding"]
    assert "source_point" not in parsed.connector_binding.model_dump(mode="json")
    assert not list(Draft202012Validator(SemanticStandardObjectSpec.model_json_schema()).iter_errors(raw))


@pytest.mark.parametrize("mutation", [{"source_object_id": None}, {"source_anchor_id": None},
    {"source_point": None}, {"allow_self_loop": True}, {"role": "pointer"}])
def test_network_binding_cannot_use_free_or_unowned_relationship_authority(mutation):
    raw = network_semantic()
    raw["connector_binding"].update(mutation)
    with pytest.raises(ValidationError):
        SemanticStandardObjectSpec.model_validate(raw)
    assert list(Draft202012Validator(SemanticStandardObjectSpec.model_json_schema()).iter_errors(raw))


def test_absent_binding_keeps_legacy_semantic_arrow_shape():
    raw = semantic_pointer()
    raw.pop("connector_binding")
    assert SemanticStandardObjectSpec.model_validate(raw).model_dump(mode="json") == raw


def network_documents():
    from v2_fixtures import digest

    plan, layout = pointer_documents()
    source = deepcopy(layout["objects"][1])
    source["object_id"] = "network-source"
    semantic = deepcopy(plan["objects"][1])
    semantic["object_id"] = source["object_id"]
    layout["objects"].append(source)
    plan["objects"].append(semantic)
    for document in (plan, layout):
        document["boards"][0]["object_ids"].append(source["object_id"])
    plan["beats"][0]["object_ids"].append(source["object_id"])
    connector = layout["objects"][0]
    connector.pop("source_point")
    connector.update(object_type="network", role="semantic_connector",
                     source_object_id="network-source", source_anchor_id="center")
    plan["objects"][0]["object_type"] = "network"
    plan["objects"][0].pop("connector_binding")
    layout["plan_sha256"] = digest(plan)
    return plan, layout


def test_legacy_network_history_remains_loadable_without_new_write_binding():
    plan, layout = network_documents()
    validate_plan_layout(plan, layout, require_code_payloads=False)
    with pytest.raises(ValueError, match="connector_binding"):
        validate_plan_layout(plan, layout)


def test_new_network_plan_write_cannot_omit_its_explicit_binding():
    from atme.store.contracts_v2 import validate_plan_evidence_completeness

    plan, _layout = network_documents()
    with pytest.raises(ValueError, match="connector_binding"):
        validate_plan_evidence_completeness(plan)


@pytest.mark.parametrize("bypass", ["subclass", "construct"])
def test_connector_binding_rejects_unknown_subclass_or_bypassed_field_validation(bypass):
    from atme.store.contracts_v2 import ConnectorBinding

    raw = semantic_pointer()
    binding = raw["connector_binding"]
    if bypass == "subclass":
        class UnknownBinding(ConnectorBinding):
            pass
        raw["connector_binding"] = UnknownBinding.model_validate(binding)
    else:
        raw["connector_binding"] = ConnectorBinding.model_construct(**{**binding, "routing": "made-up"})
    with pytest.raises(ValueError):
        SemanticStandardObjectSpec.model_validate(raw)


@pytest.mark.parametrize("mode", ["dict", "model", "constructed"])
def test_network_binding_exact_inputs_preserve_omitted_point_and_original_value(mode):
    from atme.store.contracts_v2 import ConnectorBinding

    raw = network_semantic()
    wire = deepcopy(raw["connector_binding"])
    if mode != "dict":
        binding = (ConnectorBinding.model_validate(wire) if mode == "model"
                   else ConnectorBinding.model_construct(**wire))
        fields_before = set(binding.model_fields_set)
        assert "source_point" not in fields_before
        raw["connector_binding"] = binding
    parsed = SemanticStandardObjectSpec.model_validate(raw)
    assert parsed.connector_binding.model_dump(mode="json") == wire
    if mode != "dict":
        assert binding.model_fields_set == fields_before
        assert binding.source_point is None


@pytest.mark.parametrize("mode", ["dict", "model"])
def test_explicit_null_point_cannot_be_laundered_through_typed_binding(mode):
    from atme.store.contracts_v2 import ConnectorBinding

    raw = network_semantic()
    raw["connector_binding"]["source_point"] = None
    if mode == "model":
        raw["connector_binding"] = ConnectorBinding.model_construct(**raw["connector_binding"])
        assert "source_point" in raw["connector_binding"].model_fields_set
    with pytest.raises(ValueError, match="source_point"):
        SemanticStandardObjectSpec.model_validate(raw)


@pytest.mark.parametrize("fault", ["unknown_field_set", "missing_required"])
def test_typed_binding_cannot_forge_its_explicit_field_inventory(fault):
    from atme.store.contracts_v2 import ConnectorBinding

    raw = semantic_pointer()
    if fault == "unknown_field_set":
        binding = ConnectorBinding.model_validate(raw["connector_binding"])
        binding.__pydantic_fields_set__.add("unrecognized_authority")
    else:
        payload = deepcopy(raw["connector_binding"])
        payload.pop("destination_object_id")
        binding = ConnectorBinding.model_construct(**payload)
    raw["connector_binding"] = binding
    with pytest.raises(ValueError):
        SemanticStandardObjectSpec.model_validate(raw)
