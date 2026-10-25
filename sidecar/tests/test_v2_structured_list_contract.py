"""P3-33 lists reference real authored objects, never generated virtual items."""

import json
from copy import deepcopy
from hashlib import sha256

import pytest
from atme.render.v2_split_identity import split_content_receipts
from atme.store import contracts_v2 as contracts
from conftest import load_schema
from jsonschema import Draft202012Validator
from test_v2_group_hierarchy import grouped_documents
from test_v2_progressive_list import list_documents
from test_v2_split_identity import sample_for_layout
from v2_fixtures import digest, visual_plan_v2


def payload():
    return {"version": "1.0.0", "container_group_id": "list-group",
        "item_object_ids": ["list-item-a", "list-item-b", "list-item-c"]}


def documents():
    layout, timeline = list_documents()
    heading = layout["objects"][2]
    heading.update(items=[], parent_id="list-group", structured_list=payload(), z_index=0)
    items = []
    for index, (key, text) in enumerate(zip(payload()["item_object_ids"], [
        "Gather evidence", "Explain the change", "Return to the model"], strict=True)):
        obj = deepcopy(heading)
        obj.pop("structured_list")
        obj.update(object_id=key, object_type="text", text=text, z_index=index+1,
            anchors=[{"anchor_id": "item-center", "point": {"x": .5, "y": .5}}])
        obj["geometry"]["bounds"]["y"] += (index+1)*40
        obj["geometry"]["bounds"]["height"] = 40
        items.append(obj)
    group = deepcopy(grouped_documents()[0]["objects"][3])
    group.update(object_id="list-group", beat_id=heading["beat_id"], coverage_ids=heading["coverage_ids"],
        child_ids=[heading["object_id"], *payload()["item_object_ids"]])
    layout["objects"].extend([*items, group])
    layout["boards"][0].update(object_ids=[obj["object_id"] for obj in layout["objects"]], density_limit=7)
    plan = visual_plan_v2()
    fields = list(plan["objects"][0])
    plan["objects"] = [{name: obj[name] for name in fields} for obj in layout["objects"]]
    next(obj for obj in plan["objects"] if obj["object_id"] == heading["object_id"])["structured_list"] = payload()
    plan["objects"][-1]["child_ids"] = deepcopy(group["child_ids"])
    plan["assets"] = []
    plan["boards"] = deepcopy(layout["boards"])
    # Ordinary heading visibility is not the as-yet-unimplemented structured progression.
    timeline["actions"][2]["action"]["verb"] = "reveal"
    plan["actions"] = [deepcopy(row["action"]) for row in timeline["actions"]]
    for beat in plan["beats"]:
        beat["object_ids"] = [obj["object_id"] for obj in plan["objects"] if obj["beat_id"] == beat["beat_id"]]
        beat["evidence"] = None
    layout["plan_sha256"] = digest(plan)
    return plan, layout


def model():
    assert hasattr(contracts, "StructuredListPayload"), "strict real-item list payload is missing"
    return contracts.StructuredListPayload


def test_structured_list_payload_has_exact_authored_refs_and_no_generated_defaults():
    assert model().model_validate(payload()).model_dump(mode="json") == payload()
    for name in payload():
        raw = payload()
        raw.pop(name)
        with pytest.raises(ValueError):
            model().model_validate(raw)


@pytest.mark.parametrize("field,value", [("version", "2.0.0"), ("container_group_id", ""),
    ("container_group_id", " "), ("item_object_ids", []), ("item_object_ids", ["x", "x"]),
    ("item_object_ids", ["list-group"]), ("item_object_ids", [" "]), ("item_object_ids", [1]),
    ("generated_strings", ["invented"])])
def test_structured_list_strict_payload_rejects_ambiguous_refs(field, value):
    raw = payload()
    raw[field] = value
    with pytest.raises(ValueError):
        model().model_validate(raw)


def test_structured_list_semantic_layout_equality_exact_group_order_and_real_item_anchors():
    model()
    plan, layout = documents()
    contracts.validate_plan_evidence_completeness(plan)
    contracts.validate_plan_layout(plan, layout)
    parsed = contracts.ExecutableLayoutV2.model_validate(layout)
    assert next(obj for obj in parsed.objects if obj.object_type == "list").items == []
    for key in payload()["item_object_ids"]:
        obj = next(obj for obj in parsed.objects if obj.object_id == key)
        assert obj.object_type == "text" and obj.anchors[0].anchor_id == "item-center"


@pytest.mark.parametrize("fault", ["unknown", "duplicate", "non_text", "orphan", "wrong_order", "cross_board",
    "flat_strings", "multiline", "wrong_container", "self_item"])
def test_structured_list_graph_and_layout_cannot_substitute_or_infer_items(fault):
    model()
    plan, layout = documents()
    objects = {obj["object_id"]: obj for obj in layout["objects"]}
    heading = objects["object-evidence"]
    if fault == "unknown":
        heading["structured_list"]["item_object_ids"][0] = "unknown"
    elif fault == "duplicate":
        heading["structured_list"]["item_object_ids"][1] = "list-item-a"
    elif fault == "non_text":
        obj = objects["list-item-a"]
        obj.update(object_type="rectangle", path_data=None)
        obj.pop("text")
        obj.pop("items")
    elif fault == "orphan":
        objects["list-item-a"]["parent_id"] = None
        objects["list-group"]["child_ids"].remove("list-item-a")
    elif fault == "wrong_order":
        objects["list-item-a"]["z_index"], objects["list-item-c"]["z_index"] = 3, 1
    elif fault == "cross_board":
        objects["list-item-a"]["board_id"] = "other-board"
    elif fault == "flat_strings":
        heading["items"] = ["Duplicated invisible item"]
    elif fault == "multiline":
        objects["list-item-a"]["text"] = "One\nTwo"
    elif fault == "wrong_container":
        heading["structured_list"]["container_group_id"] = "object-system"
    else:
        heading["structured_list"]["item_object_ids"][0] = "object-evidence"
    with pytest.raises(ValueError):
        contracts.validate_plan_layout(plan, layout)


def test_structured_list_binding_is_exact_in_semantic_plan_and_layout():
    model()
    plan, layout = documents()
    next(obj for obj in plan["objects"] if obj["object_type"] == "list")["structured_list"]["item_object_ids"].reverse()
    layout["plan_sha256"] = digest(plan)
    with pytest.raises(ValueError, match="structured_list|order"):
        contracts.validate_plan_layout(plan, layout)


def test_flat_legacy_list_dump_and_content_identity_remain_exactly_unchanged():
    model()
    raw, _ = list_documents()
    layout = contracts.ExecutableLayoutV2.model_validate(raw)
    listing = layout.objects[2]
    assert "structured_list" not in listing.model_dump(mode="json")
    authored = {name: listing.model_dump(mode="json")[name] for name in
        ("object_type", "geometry", "style", "anchors", "asset_id", "text", "items")}
    encoded = json.dumps(authored, sort_keys=True, separators=(",", ":"))
    receipt = next(row for row in split_content_receipts(layout, sample_for_layout(layout), {})
        if row.object_id == listing.object_id)
    assert receipt.canonical_json == encoded and receipt.content_sha256 == sha256(encoded.encode()).hexdigest()


def test_structured_list_identity_and_distributable_schemas_preserve_exact_refs():
    model()
    plan, raw = documents()
    for document, filename in ((plan, "visual-plan-v2"), (raw, "executable-layout-v2")):
        Draft202012Validator(load_schema(filename)).validate(document)
    layout = contracts.ExecutableLayoutV2.model_validate(raw)
    listing = next(obj for obj in layout.objects if obj.object_type == "list")
    data = listing.model_dump(mode="json")
    projection = {name: data[name] for name in
        ("object_type", "geometry", "style", "anchors", "asset_id", "text", "items", "structured_list")}
    encoded = json.dumps(projection, sort_keys=True, separators=(",", ":"))
    receipt = next(row for row in split_content_receipts(layout, sample_for_layout(layout), {})
        if row.object_id == listing.object_id)
    assert receipt.canonical_json == encoded and receipt.content_sha256 == sha256(encoded.encode()).hexdigest()


def test_structured_items_require_authored_anchors_before_any_layout_admission():
    plan, layout = documents()
    next(obj for obj in layout["objects"] if obj["object_id"] == "list-item-a")["anchors"] = []
    with pytest.raises(ValueError, match="structured_list.*anchor"):
        contracts.validate_plan_layout(plan, layout)


@pytest.mark.parametrize("semantic", [False, True])
def test_structured_heading_must_precede_items_in_declared_and_actual_order(semantic):
    plan, layout = documents()
    if semantic:
        group = plan["objects"][-1]
        group["child_ids"] = [*payload()["item_object_ids"], "object-evidence"]
    else:
        next(obj for obj in layout["objects"] if obj["object_type"] == "list")["z_index"] = 4
    layout["plan_sha256"] = digest(plan)
    with pytest.raises(ValueError, match="structured_list.*order"):
        contracts.validate_plan_layout(plan, layout)


def test_structured_container_group_has_one_exact_heading_owner():
    plan, layout = documents()
    heading = deepcopy(next(obj for obj in layout["objects"] if obj["object_type"] == "list"))
    heading.update(object_id="second-heading", z_index=4)
    heading["structured_list"]["item_object_ids"] = ["second-item"]
    item = deepcopy(next(obj for obj in layout["objects"] if obj["object_id"] == "list-item-a"))
    item.update(object_id="second-item", z_index=5)
    layout["objects"].extend((heading, item))
    group = next(obj for obj in layout["objects"] if obj["object_id"] == "list-group")
    group["child_ids"].extend(("second-heading", "second-item"))
    semantic_group = next(obj for obj in plan["objects"] if obj["object_id"] == "list-group")
    semantic_group["child_ids"] = deepcopy(group["child_ids"])
    names = list(plan["objects"][0])
    for obj in (heading, item):
        spec = {name: obj[name] for name in names}
        if obj["object_type"] == "list":
            spec["structured_list"] = deepcopy(obj["structured_list"])
        plan["objects"].append(spec)
    for document in (plan, layout):
        document["boards"][0]["object_ids"].extend(("second-heading", "second-item"))
        document["boards"][0]["density_limit"] = 9
    plan["beats"][1]["object_ids"].extend(("second-heading", "second-item"))
    layout["plan_sha256"] = digest(plan)
    with pytest.raises(ValueError, match="structured_list.*container.*owner"):
        contracts.validate_plan_layout(plan, layout)


def nested_documents():
    plan, layout = documents()
    root = next(obj for obj in layout["objects"] if obj["object_id"] == "list-group")
    nested = deepcopy(root)
    nested.update(object_id="authored-subgroup", parent_id=root["object_id"], z_index=2,
        child_ids=["list-item-b", "list-item-c"])
    root["child_ids"] = ["object-evidence", "list-item-a", nested["object_id"]]
    for obj in layout["objects"]:
        if obj["object_id"] in nested["child_ids"]:
            obj["parent_id"] = nested["object_id"]
    layout["objects"].append(nested)
    plan["objects"][-1]["child_ids"] = deepcopy(root["child_ids"])
    plan["objects"].append({name: deepcopy(nested[name])
        for name in contracts.SemanticStandardObjectSpec.model_fields if name in nested})
    plan["beats"][1]["object_ids"].append(nested["object_id"])
    for document in (plan, layout):
        document["boards"][0]["object_ids"].append(nested["object_id"])
        document["boards"][0]["density_limit"] = 8
    layout["plan_sha256"] = digest(plan)
    return plan, layout


def test_structured_list_nested_membership_is_authored_and_flattens_without_virtual_items():
    plan, raw = nested_documents()
    contracts.validate_plan_layout(plan, raw)
    parsed = contracts.ExecutableLayoutV2.model_validate(raw)
    assert len(parsed.objects) == 8
    assert next(obj for obj in parsed.objects if obj.object_id == "list-item-c").parent_id == "authored-subgroup"
    assert contracts.VisualPlanV2.model_validate(plan).model_dump(mode="json")["objects"][-1][
        "child_ids"] == ["list-item-b", "list-item-c"]


@pytest.mark.parametrize("fault", ["omitted", "reordered", "different_parent"])
def test_structured_nested_graph_cannot_be_inferred_or_differ_from_layout(fault):
    plan, layout = nested_documents()
    nested = plan["objects"][-1]
    if fault == "omitted":
        nested.pop("child_ids")
    elif fault == "reordered":
        nested["child_ids"].reverse()
    else:
        nested["child_ids"].remove("list-item-c")
        plan["objects"][-2]["child_ids"].append("list-item-c")
    layout["plan_sha256"] = digest(plan)
    with pytest.raises(ValueError, match="structured_list|child_ids"):
        contracts.validate_plan_layout(plan, layout)


@pytest.mark.parametrize("fault", ["subclass", "unknown_field", "duplicate_refs"])
def test_structured_payload_identity_rejects_unknown_or_bypass_constructed_data(fault):
    _, raw = documents()
    layout = contracts.ExecutableLayoutV2.model_validate(raw)
    heading = next(obj for obj in layout.objects if obj.object_type == "list")
    if fault == "subclass":
        class UnknownPayload(contracts.StructuredListPayload):
            pass
        heading.structured_list = UnknownPayload.model_validate(payload())
    elif fault == "unknown_field":
        heading.structured_list.__dict__["generated_items"] = ["not authored"]
    else:
        heading.structured_list.item_object_ids[1] = "list-item-a"
    with pytest.raises(ValueError):
        split_content_receipts(layout, sample_for_layout(layout), {})


def test_legacy_semantic_list_dump_omits_new_payload_and_keeps_original_hash():
    legacy = visual_plan_v2()["objects"][2]
    legacy["object_type"] = "list"
    parsed = contracts.SemanticStandardObjectSpec.model_validate(legacy)
    assert parsed.model_dump(mode="json") == legacy
    assert digest(parsed.model_dump(mode="json")) == digest(legacy)


@pytest.mark.parametrize("semantic", [False, True])
def test_structured_payload_owner_is_list_only_in_model_and_schema(semantic):
    plan, layout = documents()
    document = plan if semantic else layout
    heading = next(obj for obj in document["objects"] if obj["object_type"] == "list")
    heading["object_type"] = "text"
    contract = contracts.VisualPlanV2 if semantic else contracts.ExecutableLayoutV2
    with pytest.raises(ValueError, match="structured_list"):
        contract.model_validate(document)
    assert list(Draft202012Validator(load_schema(
        "visual-plan-v2" if semantic else "executable-layout-v2")).iter_errors(document))


@pytest.mark.parametrize("fault", ["plan_order", "layout_anchors", "payload_mismatch", "none"])
def test_real_project_structured_list_writes_and_duplicate_are_exact_or_atomic(tmp_path, fault):
    from atme.project_service import ProjectError, _visual_digest
    from test_v2_split_project import artifact_rows
    from test_visual_contracts_v2 import _store_v2_plan

    service, project, existing = _store_v2_plan(tmp_path)
    try:
        plan, layout = nested_documents()
        pid = project["project_id"]
        plan.update(project_id=pid, project_revision=project["revision"],
            narrative_authority=deepcopy(existing["narrative_authority"]))
        if fault == "plan_order":
            plan["objects"][-1]["child_ids"].reverse()
            before = artifact_rows(service, pid)
            with pytest.raises(ProjectError) as failure:
                service.write(pid, "storyboard", plan, project["revision"])
            assert failure.value.code == "invalid_artifact"
            assert service.open(pid)["revision"] == project["revision"]
            assert artifact_rows(service, pid) == before
            return
        project = service.write(pid, "storyboard", plan, project["revision"])
        layout.update(project_id=pid, project_revision=project["revision"],
            plan_revision=project["artifacts"]["storyboard"], plan_sha256=_visual_digest(plan))
        if fault != "none":
            if fault == "layout_anchors":
                next(obj for obj in layout["objects"] if obj["object_id"] == "list-item-a")["anchors"] = []
            else:
                next(obj for obj in layout["objects"] if obj["object_type"] == "list")[
                    "structured_list"]["container_group_id"] = "authored-subgroup"
            before = artifact_rows(service, pid)
            with pytest.raises(ProjectError) as failure:
                service.write(pid, "layout", layout, project["revision"])
            assert failure.value.code == "invalid_artifact"
            assert service.open(pid)["revision"] == project["revision"]
            assert artifact_rows(service, pid) == before
        else:
            service.write(pid, "layout", layout, project["revision"])
            assert service.artifact(pid, "storyboard")["document"] == plan
            assert service.artifact(pid, "layout")["document"] == layout
            original = artifact_rows(service, pid)
            copied = service.duplicate(pid)
            for name in ("storyboard", "layout"):
                duplicate = service.artifact(copied["project_id"], name)["document"]
                assert next(obj for obj in duplicate["objects"] if obj["object_type"] == "list")[
                    "structured_list"] == payload()
                assert next(obj for obj in duplicate["objects"] if obj["object_id"] == "authored-subgroup")[
                    "child_ids"] == ["list-item-b", "list-item-c"]
            assert artifact_rows(service, pid) == original
    finally:
        service.store.close()
