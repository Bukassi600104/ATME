"""Authored callout identity/binding, never inferred or orphan pointer paint."""

import json
from copy import deepcopy
from hashlib import sha256

import pytest
from atme.render.v2_split_identity import split_content_receipts
from atme.store import contracts_v2 as contracts
from conftest import load_schema
from jsonschema import Draft202012Validator
from pydantic import TypeAdapter, ValidationError
from test_v2_annotation_contract import leader_documents
from test_v2_split_identity import sample_for_layout
from v2_fixtures import digest


def binding():
    return {"version": "1.0.0", "leader_connector_id": "annotation-leader",
            "callout_anchor_id": "center", "target_object_id": "object-system", "target_anchor_id": "center"}


def binding_type():
    assert hasattr(contracts, "CalloutBinding"), "strict authored callout binding is missing"
    return contracts.CalloutBinding


def callout_documents(*, bound=True):
    plan, layout, timeline = leader_documents()
    for document in (plan, layout):
        callout = next(obj for obj in document["objects"] if obj["object_id"] == "annotation-note")
        callout["object_type"] = "callout"
        if bound:
            callout["callout_binding"] = binding()
    # This is an explicit callout, not an annotation owning the same pointer.
    for action in (plan["actions"][-1], timeline["actions"][-1]["action"]):
        action.pop("annotation_policy")
        action.update(verb="write", target_ids=["annotation-note"], expected_state="hidden", post_state="visible")
    layout["plan_sha256"] = digest(plan)
    timeline["plan_sha256"] = digest(plan)
    timeline["layout_sha256"] = digest(layout)
    return plan, layout, timeline


def test_strict_callout_binding_round_trips_exact_authored_fields():
    assert binding_type().model_validate(binding()).model_dump(mode="json") == binding()


def test_callout_binding_distributable_schemas_preserve_exact_plan_and_layout():
    plan, layout, _ = callout_documents()
    for document, schema, model in ((plan, "visual-plan-v2", contracts.VisualPlanV2),
                                   (layout, "executable-layout-v2", contracts.ExecutableLayoutV2)):
        Draft202012Validator(load_schema(schema)).validate(document)
        parsed = model.model_validate(document)
        assert model.model_validate(parsed.model_dump(mode="json")) == parsed
        assert next(obj for obj in parsed.objects if obj.object_id == "annotation-note").callout_binding.model_dump(
            mode="json") == binding()


@pytest.mark.parametrize("field,value", [
    ("version", "2.0.0"), ("leader_connector_id", ""), ("callout_anchor_id", ""),
    ("target_object_id", ""), ("target_anchor_id", ""),
    ("leader_connector_id", "   "), ("target_object_id", "\n"),
    ("target_anchor_id", 2), ("invented_geometry", []),
])
def test_callout_binding_rejects_missing_meaning_wrong_types_and_unknown_fields(field, value):
    model = binding_type()
    raw = binding()
    raw[field] = value
    with pytest.raises(ValidationError):
        model.model_validate(raw)


@pytest.mark.parametrize("field", list(binding()))
def test_callout_binding_has_no_inferred_defaults(field):
    model = binding_type()
    raw = binding()
    raw.pop(field)
    with pytest.raises(ValidationError):
        model.model_validate(raw)


@pytest.mark.parametrize("kind", ["text", "list", "code"])
def test_binding_belongs_only_to_callout_objects_and_semantic_specs(kind):
    binding_type()
    plan, layout, _ = callout_documents()
    for document, model in ((plan, contracts.VisualPlanV2), (layout, contracts.ExecutableLayoutV2)):
        next(obj for obj in document["objects"] if obj["object_id"] == "annotation-note")["object_type"] = kind
        with pytest.raises(ValidationError, match="callout_binding"):
            model.model_validate(document)


def test_callout_binding_is_exact_in_semantic_plan_layout_and_new_write_completeness():
    binding_type()
    plan, layout, _ = callout_documents()
    contracts.validate_plan_evidence_completeness(plan)
    contracts.validate_plan_layout(plan, layout)
    callout = next(obj for obj in layout["objects"] if obj["object_id"] == "annotation-note")
    assert next(obj for obj in contracts.ExecutableLayoutV2.model_validate(layout).objects
                if obj.object_id == "annotation-note").callout_binding.model_dump(mode="json") == binding()
    callout["callout_binding"]["target_anchor_id"] = "changed-anchor"
    with pytest.raises(ValueError, match="callout|anchor"):
        contracts.validate_plan_layout(plan, layout)


@pytest.mark.parametrize("missing", ["plan", "layout", "both"])
def test_normal_callout_writes_require_binding_without_guessing_legacy_status(missing):
    binding_type()
    plan, layout, _ = callout_documents()
    for document in ([plan] if missing == "plan" else [layout] if missing == "layout" else [plan, layout]):
        next(obj for obj in document["objects"] if obj["object_id"] == "annotation-note").pop("callout_binding")
    with pytest.raises(ValueError, match="callout_binding"):
        contracts.validate_plan_layout(plan, layout)
    if missing != "layout":
        with pytest.raises(ValueError, match="callout_binding"):
            contracts.validate_plan_evidence_completeness(plan)
    if missing == "both":
        contracts.validate_plan_layout(plan, layout, require_code_payloads=False)


def test_bare_legacy_callout_shape_and_content_hash_are_preserved():
    binding_type()
    plan, layout, _ = callout_documents(bound=False)
    parsed = contracts.ExecutableLayoutV2.model_validate(layout)
    obj = next(obj for obj in parsed.objects if obj.object_id == "annotation-note")
    assert "callout_binding" not in obj.model_dump(mode="json")
    spec = next(obj for obj in contracts.VisualPlanV2.model_validate(plan).objects if obj.object_id == "annotation-note")
    assert "callout_binding" not in spec.model_dump(mode="json")
    raw = obj.model_dump(mode="json")
    authored = {name: raw[name] for name in ("object_type", "geometry", "style", "anchors", "asset_id", "text", "items")}
    expected = json.dumps(authored, sort_keys=True, separators=(",", ":"))
    receipt = next(row for row in split_content_receipts(parsed, sample_for_layout(parsed), {})
                   if row.object_id == obj.object_id)
    assert receipt.canonical_json == expected and receipt.content_sha256 == sha256(expected.encode()).hexdigest()


def test_callout_identity_includes_every_exact_binding_field_without_pose_data():
    binding_type()
    _, raw, _ = callout_documents()
    layout = contracts.ExecutableLayoutV2.model_validate(raw)
    obj = next(obj for obj in layout.objects if obj.object_id == "annotation-note")
    payload = obj.model_dump(mode="json")
    authored = {name: payload[name] for name in
                ("object_type", "geometry", "style", "anchors", "asset_id", "text", "items", "callout_binding")}
    expected = json.dumps(authored, sort_keys=True, separators=(",", ":"))
    receipt = next(row for row in split_content_receipts(layout, sample_for_layout(layout), {})
                   if row.object_id == obj.object_id)
    assert receipt.canonical_json == expected and receipt.content_sha256 == sha256(expected.encode()).hexdigest()
    moved = deepcopy(raw)
    next(row for row in moved["objects"] if row["object_id"] == obj.object_id)["transform"]["position"]["x"] += 10
    candidate = contracts.ExecutableLayoutV2.model_validate(moved)
    assert next(row for row in split_content_receipts(candidate, sample_for_layout(candidate), {})
                if row.object_id == obj.object_id).content_sha256 == receipt.content_sha256


def test_unknown_callout_binding_subclass_cannot_be_discarded_by_identity():
    model = binding_type()
    _, raw, _ = callout_documents()
    layout = contracts.ExecutableLayoutV2.model_validate(raw)
    obj = next(obj for obj in layout.objects if obj.object_id == "annotation-note")

    class UnknownBinding(model):
        pass

    obj.callout_binding = UnknownBinding.model_validate(binding())
    with pytest.raises(ValueError, match="unknown nested payload subclass"):
        split_content_receipts(layout, sample_for_layout(layout), {})


@pytest.mark.parametrize("change", [
    lambda c, p, t: p.update(role="semantic_connector"),
    lambda c, p, t: p.update(source_object_id="object-label"),
    lambda c, p, t: p.update(destination_object_id="object-label"),
    lambda c, p, t: p.update(source_object_id=None, source_anchor_id=None),
    lambda c, p, t: c["callout_binding"].update(callout_anchor_id="missing"),
    lambda c, p, t: c["callout_binding"].update(target_anchor_id="missing"),
    lambda c, p, t: c["callout_binding"].update(target_object_id="object-label"),
    lambda c, p, t: c["callout_binding"].update(leader_connector_id="object-label"),
    lambda c, p, t: c["callout_binding"].update(leader_connector_id="unknown"),
    lambda c, p, t: p.update(beat_id="another-beat"),
    lambda c, p, t: p.update(coverage_ids=["other-coverage"]),
    lambda c, p, t: p.update(asset_id="invented-asset"),
    lambda c, p, t: p["style"].update(fill="ink.primary"),
    lambda c, p, t: p["transform"]["position"].update(x=1),
    lambda c, p, t: c["anchors"][0]["point"].update(x=1.5),
    lambda c, p, t: t["anchors"][0]["point"].update(y=-.1),
    lambda c, p, t: c.update(items=["Not a callout list"]),
    lambda c, p, t: c.update(text="   "),
])
def test_callout_layout_rejects_unfaithful_pointer_endpoints_ownership_and_ignored_styling(change):
    _, layout, _ = callout_documents()
    objects = {obj["object_id"]: obj for obj in layout["objects"]}
    change(objects["annotation-note"], objects["annotation-leader"], objects["object-system"])
    with pytest.raises(ValueError):
        contracts.ExecutableLayoutV2.model_validate(layout)


@pytest.mark.parametrize("change", [
    lambda c, p, t: p.update(object_type="rectangle"),
    lambda c, p, t: p.update(beat_id="beat-002"),
    lambda c, p, t: p.update(coverage_ids=["coverage-2"]),
    lambda c, p, t: c["callout_binding"].update(leader_connector_id="unknown"),
    lambda c, p, t: c["callout_binding"].update(target_object_id="unknown"),
    lambda c, p, t: t.update(object_type="evidence"),
])
def test_new_callout_plan_has_exact_declared_leader_target_beat_and_coverage(change):
    plan, _, _ = callout_documents()
    objects = {obj["object_id"]: obj for obj in plan["objects"]}
    change(objects["annotation-note"], objects["annotation-leader"], objects["object-system"])
    with pytest.raises(ValueError):
        contracts.validate_plan_evidence_completeness(plan)


def test_callout_and_annotation_cannot_both_own_the_same_pointer():
    plan, layout, _ = callout_documents()
    annotation = leader_documents()[0]["actions"][-1]
    annotation["action_id"] = "competing-annotation"
    plan["actions"].append(annotation)
    plan["beats"][0]["action_ids"].append(annotation["action_id"])
    plan["coverage"][0]["action_ids"].append(annotation["action_id"])
    with pytest.raises(ValueError, match="(callout.*annotation|pointer.*owner)"):
        contracts.validate_plan_evidence_completeness(plan)
    with pytest.raises(ValueError, match="(callout.*annotation|pointer.*owner)"):
        contracts.validate_plan_layout(plan, layout)


def test_normal_layout_write_cannot_let_an_unowned_pointer_execute():
    plan, layout, _ = leader_documents()
    for action in plan["actions"]:
        if "annotation_policy" in action:
            action["annotation_policy"]["leader_connector_id"] = None
            action["annotation_policy"]["phases"] = [row for row in action["annotation_policy"]["phases"]
                if row["object_id"] != "annotation-leader"]
    with pytest.raises(ValueError, match="pointer.*owner"):
        contracts.validate_plan_layout(plan, layout)


@pytest.mark.parametrize("kind", ["group", "clip", "mask", "composition", "instance"])
def test_callout_cannot_invent_a_paintable_target_for_a_nonpainting_container(kind):
    plan, _, _ = callout_documents()
    next(obj for obj in plan["objects"] if obj["object_id"] == "object-system")["object_type"] = kind
    if kind in {"composition", "instance"}:
        # Prove the role guard directly: whole-plan normal writes now require
        # an expansion Binding before this independent Callout role check.
        parts = [TypeAdapter(contracts.SemanticObject).validate_python(raw) for raw in plan["objects"]]
        with pytest.raises(ValueError, match="callout_binding"):
            contracts._callout_leader_owners({obj.object_id: obj for obj in parts})
        with pytest.raises(ValueError, match="composition/instance writes require an exact explicit expansion binding"):
            contracts.validate_plan_evidence_completeness(plan)
    else:
        with pytest.raises(ValueError, match="callout_binding"):
            contracts.validate_plan_evidence_completeness(plan)


def test_semantic_callout_and_leader_have_paired_initial_state():
    plan, _, _ = callout_documents()
    next(obj for obj in plan["objects"] if obj["object_id"] == "annotation-leader")["initial_state"] = "visible"
    with pytest.raises(ValueError, match="callout.*state"):
        contracts.validate_plan_evidence_completeness(plan)


@pytest.mark.parametrize("object_id,field,value", [
    ("annotation-leader", "visible", True), ("annotation-note", "visible", True),
    ("annotation-leader", "initial_state", "visible"), ("annotation-note", "initial_state", "visible"),
    ("annotation-leader", "opacity", 0), ("annotation-note", "opacity", 0),
])
def test_callout_layout_has_paired_initial_visibility_state_and_positive_opacity(object_id, field, value):
    _, layout, _ = callout_documents()
    next(obj for obj in layout["objects"] if obj["object_id"] == object_id)[field] = value
    with pytest.raises(ValueError, match="callout.*(state|visibility|opacity)"):
        contracts.ExecutableLayoutV2.model_validate(layout)


@pytest.mark.parametrize("visible", [False, True])
def test_callout_pair_can_be_coherently_hidden_or_already_visible(visible):
    _, layout, _ = callout_documents()
    for obj in layout["objects"]:
        if obj["object_id"] in {"annotation-note", "annotation-leader"}:
            obj.update(visible=visible, initial_state="visible" if visible else "hidden", opacity=.6)
    contracts.ExecutableLayoutV2.model_validate(layout)


@pytest.mark.parametrize("change", [
    lambda c, p: p["geometry"]["bounds"].update(width=5),
    lambda c, p: c["transform"]["position"].update(x=900),
    lambda c, p: c.update(z_index=-1),
    lambda c, p: p.update(z_index=-1),
])
def test_callout_world_route_and_effective_paint_order_are_not_ignored(change):
    _, layout, _ = callout_documents()
    objects = {obj["object_id"]: obj for obj in layout["objects"]}
    change(objects["annotation-note"], objects["annotation-leader"])
    with pytest.raises(ValueError):
        contracts.ExecutableLayoutV2.model_validate(layout)


def test_callout_pointer_head_must_fit_not_only_its_named_endpoints():
    _, layout, _ = callout_documents()
    objects = {obj["object_id"]: obj for obj in layout["objects"]}
    # These authored objects have identity transforms and center anchors.
    points = [(obj["geometry"]["bounds"]["x"] + obj["geometry"]["bounds"]["width"]/2,
               obj["geometry"]["bounds"]["y"] + obj["geometry"]["bounds"]["height"]/2)
              for obj in (objects["annotation-note"], objects["object-system"])]
    x, y = min(p[0] for p in points), min(p[1] for p in points)
    objects["annotation-leader"]["geometry"]["bounds"] = {
        "x": x, "y": y, "width": max(p[0] for p in points)-x, "height": max(p[1] for p in points)-y}
    with pytest.raises(ValueError, match="head.*bounds"):
        contracts.ExecutableLayoutV2.model_validate(layout)


@pytest.mark.parametrize("kind", ["group", "clip"])
@pytest.mark.parametrize("endpoint", ["annotation-note", "object-system"])
def test_callout_pointer_ancestry_uses_only_proven_unclipped_groups(kind, endpoint):
    _, layout, _ = callout_documents()
    child = next(obj for obj in layout["objects"] if obj["object_id"] == endpoint)
    parent = {key: deepcopy(value) for key, value in child.items()
              if key not in {"text", "items", "callout_binding", "path_data"}}
    parent.update(object_id="pointer-parent", object_type=kind, child_ids=[endpoint], anchors=[],
                  visible=True, initial_state="visible", style={"stroke": None, "fill": None, "text": None, "effect": None})
    parent["transform"]["position"]["x"] = 10
    child["parent_id"] = parent["object_id"]
    layout["objects"].append(parent)
    layout["boards"][0]["object_ids"].append(parent["object_id"])
    layout["boards"][0]["density_limit"] = 7
    if kind == "clip":
        with pytest.raises(ValueError, match="callout.*unclipped"):
            contracts.ExecutableLayoutV2.model_validate(layout)
    else:
        contracts.ExecutableLayoutV2.model_validate(layout)


@pytest.mark.parametrize("fault", ["plan_missing", "layout_missing", "endpoint_mismatch", "none"])
def test_real_project_callout_writes_preserve_binding_or_reject_atomically(tmp_path, fault):
    from atme.project_service import ProjectError, _visual_digest
    from test_v2_split_project import artifact_rows
    from test_visual_contracts_v2 import _store_v2_plan

    service, project, existing = _store_v2_plan(tmp_path)
    try:
        plan, layout, _ = callout_documents()
        pid = project["project_id"]
        plan.update(project_id=pid, project_revision=project["revision"],
                    narrative_authority=deepcopy(existing["narrative_authority"]))
        if fault == "plan_missing":
            next(obj for obj in plan["objects"] if obj["object_type"] == "callout").pop("callout_binding")
            before = artifact_rows(service, pid)
            with pytest.raises(ProjectError) as failure:
                service.write(pid, "storyboard", plan, project["revision"])
            assert failure.value.code == "invalid_artifact"
            assert any("callout_binding" in error["message"] for error in failure.value.errors)
            assert service.open(pid)["revision"] == project["revision"]
            assert artifact_rows(service, pid) == before
            return
        project = service.write(pid, "storyboard", plan, project["revision"])
        layout.update(project_id=pid, project_revision=project["revision"],
                      plan_revision=project["artifacts"]["storyboard"], plan_sha256=_visual_digest(plan))
        if fault != "none":
            if fault == "layout_missing":
                next(obj for obj in layout["objects"] if obj["object_type"] == "callout").pop("callout_binding")
            else:
                next(obj for obj in layout["objects"] if obj["object_id"] == "annotation-leader")[
                    "source_object_id"] = "object-label"
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
            original_rows = artifact_rows(service, pid)
            copied = service.duplicate(pid)
            duplicate = service.artifact(copied["project_id"], "layout")["document"]
            assert next(obj for obj in duplicate["objects"] if obj["object_type"] == "callout")[
                "callout_binding"] == binding()
            assert artifact_rows(service, pid) == original_rows
    finally:
        service.store.close()
