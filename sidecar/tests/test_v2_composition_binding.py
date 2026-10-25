"""Initial expansion receipts are not a substitute for actual graph verification."""
import hashlib
import json
from copy import deepcopy

import pytest
from atme.store import contracts_v2 as contracts
from jsonschema import Draft202012Validator, ValidationError
from test_v2_composition_contract import composition_definition
from test_v2_composition_materializer import (
    instance_spec,
    layout_for_expansion,
    materializer,
)


def packet_hash(packet):
    return hashlib.sha256(json.dumps(packet, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def rehash_binding(raw):
    raw["expansion_sha256"] = packet_hash({key: value for key, value in raw.items() if key != "expansion_sha256"})


def binding_documents(*, other_root=False):
    module = materializer()
    assert hasattr(module, "build_composition_binding"), "independent initial expansion receipt builder is missing"
    raw = instance_spec()
    objects = module.materialize_composition(raw)
    layout = layout_for_expansion(objects)
    if other_root:
        other = deepcopy(layout["objects"][1])
        other.update(object_id="unrelated", parent_id=None, z_index=0)
        layout["objects"].append(other)
        layout["boards"][0]["object_ids"].append("unrelated")
    return raw, layout, module.build_composition_binding(raw, layout)


def test_receipt_pins_real_initial_content_and_complete_destination_root_order():
    spec, layout, binding = binding_documents(other_root=True)
    assert hasattr(contracts, "CompositionBinding"), "typed composition binding receipt is missing"
    assert contracts.CompositionBinding.model_validate(binding).model_dump(mode="json") == binding
    assert binding["instance"] == contracts.CompositionInstanceSpec.model_validate(spec).model_dump(mode="json")
    assert [row["object_id"] for row in binding["members"]] == sorted(row["object_id"] for row in binding["members"])
    root = next(row for row in binding["members"] if row["object_id"] == spec["root_object_id"])
    assert root["parent_id"] is None and root["sibling_ordinal"] == 1
    native = next(obj for obj in layout["objects"] if obj["object_id"] == spec["root_object_id"])
    normalized = contracts.GroupContainer.model_validate(native).model_dump(mode="json")
    assert root["initial_object_sha256"] == packet_hash(normalized)
    assert binding["expansion_sha256"] == packet_hash({key: value for key, value in binding.items() if key != "expansion_sha256"})
    materializer().validate_composition_binding(binding, layout)


@pytest.mark.parametrize("defect", ["content", "parent", "internal_order", "missing", "duplicate", "reorder"])
def test_false_but_coherently_rehashed_member_receipts_are_recomputed(defect):
    _spec, layout, binding = binding_documents()
    row = binding["members"][0]
    if defect == "content":
        row["initial_object_sha256"] = "0" * 64
    elif defect == "parent":
        row["parent_id"] = None
    elif defect == "internal_order":
        row["sibling_ordinal"] += 1
    elif defect == "missing":
        binding["members"].pop()
    elif defect == "duplicate":
        binding["members"].append(deepcopy(row))
    else:
        binding["members"].reverse()
    rehash_binding(binding)
    with pytest.raises(ValueError):
        materializer().validate_composition_binding(binding, layout)


def test_root_order_is_an_actual_complete_hierarchy_claim_not_self_attestation():
    spec, layout, binding = binding_documents(other_root=True)
    root = next(row for row in binding["members"] if row["object_id"] == spec["root_object_id"])
    root["sibling_ordinal"] = 0
    rehash_binding(binding)
    # A nonnegative root ordinal is syntax-valid; only the complete target graph
    # can establish whether it is the real ordinal among external siblings.
    contracts.CompositionBinding.model_validate(binding)
    with pytest.raises(ValueError, match="hierarchy|ordinal|receipt"):
        materializer().validate_composition_binding(binding, layout)


@pytest.mark.parametrize("binding", [None, {}])
def test_definition_schema_and_model_explicitly_forbid_even_null_nested_binding(binding):
    raw = composition_definition()
    schema = contracts.CompositionDefinition.model_json_schema()
    root = schema["$defs"][schema["$ref"].split("/")[-1]] if "$ref" in schema else schema
    assert root["properties"]["objects"]["allOf"] == [{"items": {"not": {"required": ["composition_binding"]}}}]
    raw["objects"][0]["composition_binding"] = binding
    with pytest.raises(ValueError):
        contracts.CompositionDefinition.model_validate(raw)
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(raw)
