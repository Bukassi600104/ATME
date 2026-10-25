"""P3-34 binds semantic anchor names without rewriting legacy visual records."""

import json
from copy import deepcopy
from hashlib import sha256

import pytest
from atme.render.v2_registry import UnsupportedRegistryPlacement
from atme.render.v2_split_identity import split_content_receipts
from atme.render.v2_svg import compose_svg_frame
from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    RegistryAnchorMapping,
    RegistryBinding,
    SemanticStandardObjectSpec,
    VisualObject,
    validate_plan_layout,
)
from pydantic import ValidationError
from test_v2_registry_illustrations import illustration_documents
from test_v2_split_identity import sample_for_layout
from v2_fixtures import digest
from v2_split_fixtures import split_documents


def registry_object():
    layout, _ = illustration_documents("person-collaborators", "character")
    obj = deepcopy(layout["objects"][2])
    obj["geometry"]["bounds"] = {"x": 100., "y": 200., "width": 300., "height": 300.}
    # A 300x220 original is centered vertically in this 300x300 viewport.
    # Registry left_person is (.3, .48), but placed y is not raw-box .48.
    obj["anchors"] = [{"anchor_id": "actor-left", "point": {"x": .3, "y": 145.6 / 300}}]
    obj["registry_binding"] = {"version": "1.0.0", "asset_id": "person-collaborators",
        "anchor_mappings": [{"placed_anchor_id": "actor-left", "registry_anchor_name": "left_person"}]}
    return obj


def semantic_object(obj):
    keys = ("object_id", "object_type", "board_id", "beat_id", "semantic_role", "description",
        "asset_id", "initial_state", "coverage_ids", "registry_binding")
    return {key: deepcopy(obj[key]) for key in keys if key in obj}


@pytest.mark.parametrize("semantic", [False, True])
def test_registry_binding_is_exact_authored_semantic_and_layout_data(semantic):
    raw = registry_object()
    model = SemanticStandardObjectSpec.model_validate(semantic_object(raw)) if semantic else VisualObject.model_validate(raw)
    assert model.model_dump(mode="json")["registry_binding"] == raw["registry_binding"]


@pytest.mark.parametrize("semantic", [False, True])
def test_bare_legacy_registry_object_still_omits_binding(semantic):
    raw = registry_object()
    raw.pop("registry_binding")
    model = SemanticStandardObjectSpec.model_validate(semantic_object(raw)) if semantic else VisualObject.model_validate(raw)
    assert "registry_binding" not in model.model_dump(mode="json")


@pytest.mark.parametrize("mutation,field", [
    ("version", "version"), ("asset", "asset_id"), ("placed", "anchor_mappings"),
    ("name", "anchor_mappings"), ("duplicate", "registry_binding"), ("parts", "parts"),
])
def test_registry_binding_rejects_invalid_authored_contract_at_its_own_boundary(mutation, field):
    raw = registry_object()
    binding = raw["registry_binding"]
    if mutation == "version":
        binding["version"] = "2.0.0"
    elif mutation == "asset":
        binding["asset_id"] = " "
    elif mutation == "placed":
        binding["anchor_mappings"][0]["placed_anchor_id"] = " "
    elif mutation == "name":
        binding["anchor_mappings"][0]["registry_anchor_name"] = " "
    elif mutation == "duplicate":
        binding["anchor_mappings"].append(deepcopy(binding["anchor_mappings"][0]))
    else:
        binding["parts"] = ["invented-hand"]
    with pytest.raises(ValidationError) as error:
        VisualObject.model_validate(raw)
    # A missing whole-field implementation is not valid negative evidence.
    locations = [row["loc"] for row in error.value.errors()]
    assert all(path[0] == "registry_binding" for path in locations)
    if field == "registry_binding":
        assert any("unique placed anchor" in row["msg"] for row in error.value.errors())
    else:
        assert any(field in path[1:] for path in locations)


def test_binding_cannot_claim_parity_without_any_semantic_anchor():
    raw = registry_object()
    raw["anchors"] = []
    raw["registry_binding"]["anchor_mappings"] = []
    with pytest.raises(ValidationError, match="at least 1 item"):
        VisualObject.model_validate(raw)


def test_one_registry_semantic_anchor_cannot_have_two_placed_identities():
    raw = registry_object()
    raw["anchors"].append({"anchor_id": "alias", "point": {"x": .3, "y": 145.6 / 300}})
    raw["registry_binding"]["anchor_mappings"].append(
        {"placed_anchor_id": "alias", "registry_anchor_name": "left_person"})
    with pytest.raises(ValidationError, match="unique registry anchor names"):
        VisualObject.model_validate(raw)


@pytest.mark.parametrize("semantic", [False, True])
def test_binding_cannot_claim_unimplemented_or_nonregistry_object_kind(semantic):
    raw = registry_object()
    raw.update(object_type="image", variant=None)
    with pytest.raises(ValidationError, match="registry_binding requires a supported registry-backed object"):
        if semantic:
            SemanticStandardObjectSpec.model_validate(semantic_object(raw))
        else:
            VisualObject.model_validate(raw)


def bound_split_documents():
    plan, layout, timeline = split_documents()
    obj = next(obj for obj in layout["objects"] if obj["object_id"] == "source")
    obj.pop("path_data")
    obj.update(object_type="character", variant="person-presenter",
        style={"stroke": None, "fill": None, "text": None, "effect": None},
        anchors=[{"anchor_id": "actor", "point": {"x": .5, "y": .5}}],
        registry_binding={"version": "1.0.0", "asset_id": "person-presenter",
            "anchor_mappings": [{"placed_anchor_id": "actor", "registry_anchor_name": "center"}]})
    spec = next(obj for obj in plan["objects"] if obj["object_id"] == "source")
    spec.update(object_type="character", registry_binding=deepcopy(obj["registry_binding"]))
    timeline["layout_sha256"] = digest(layout)
    return plan, layout, timeline


@pytest.mark.parametrize("mutation", ["missing", "changed"])
def test_layout_cannot_add_or_change_registry_meaning_absent_from_the_semantic_plan(mutation):
    plan, raw, _ = bound_split_documents()
    validate_plan_layout(plan, raw, require_code_payloads=False)
    spec = next(obj for obj in plan["objects"] if obj["object_id"] == "source")
    if mutation == "missing":
        spec.pop("registry_binding")
    else:
        spec["registry_binding"]["anchor_mappings"][0]["registry_anchor_name"] = "head"
    with pytest.raises(ValueError, match="changes semantic field registry_binding"):
        validate_plan_layout(plan, raw, require_code_payloads=False)


def test_split_identity_pins_binding_but_preserves_bare_legacy_content():
    _, raw, _ = bound_split_documents()
    obj = next(obj for obj in raw["objects"] if obj["object_id"] == "source")
    for bound in (True, False):
        if not bound:
            obj.pop("registry_binding")
        layout = ExecutableLayoutV2.model_validate(raw)
        receipt = next(row for row in split_content_receipts(layout, sample_for_layout(layout), {})
            if row.object_id == "source")
        payload = {key: obj[key] for key in ("object_type", "geometry", "style", "anchors", "asset_id", "variant")}
        if bound:
            payload["registry_binding"] = obj["registry_binding"]
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        assert receipt.canonical_json == encoded
        assert receipt.content_sha256 == sha256(encoded.encode()).hexdigest()


@pytest.mark.parametrize("nested", ["binding", "mapping"])
def test_split_identity_refuses_unknown_registry_payload_subclasses(nested):
    _, raw, _ = bound_split_documents()
    layout = ExecutableLayoutV2.model_validate(raw)
    obj = next(obj for obj in layout.objects if obj.object_id == "source")
    if nested == "binding":
        class UnapprovedBinding(RegistryBinding):
            part: str = "invented-part"
        obj.registry_binding = UnapprovedBinding.model_validate(obj.registry_binding.model_dump())
    else:
        class UnapprovedMapping(RegistryAnchorMapping):
            part: str = "invented-part"
        obj.registry_binding.anchor_mappings[0] = UnapprovedMapping.model_validate(
            obj.registry_binding.anchor_mappings[0].model_dump())
    with pytest.raises(ValueError, match="unknown nested payload subclass"):
        split_content_receipts(layout, sample_for_layout(layout), {})


def test_misplaced_binding_execution_fails_closed_without_changing_legacy_art():
    raw, timeline = illustration_documents("person-collaborators", "character")
    raw["objects"][2] = registry_object()
    raw["objects"][2]["anchors"][0]["point"]["y"] = .48
    timeline["layout_sha256"] = digest(raw)
    with pytest.raises(UnsupportedRegistryPlacement, match="does not match fitted registry anchor"):
        compose_svg_frame(raw, timeline, 5000)
