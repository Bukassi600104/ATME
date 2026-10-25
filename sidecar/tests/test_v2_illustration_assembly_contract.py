"""Authored illustration content is real layers, not invented registry parts."""

import json
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest
from conftest import load_schema
from jsonschema import Draft202012Validator
from jsonschema import ValidationError as SchemaValidationError
from test_v2_code_contract import code_object
from test_v2_group_hierarchy import grouped_documents
from test_v2_registry_binding import registry_object
from test_v2_registry_project import history
from test_v2_resolved_project import stored_v2_basis
from test_v2_split_identity import sample_for_layout
from v2_fixtures import digest, visual_plan_v2

from atme.project_service import ProjectError
from atme.render.v2_split_identity import split_content_receipts
from atme.store import contracts_v2 as contracts


def binding():
    return {"version": "1.0.0", "family": "device", "content_state_id": "display-on",
        "roles": [{"role_id": "display-shell", "kind": "artwork", "object_id": "device-shell"},
                  {"role_id": "caption", "kind": "label", "object_id": "device-label"}],
        "semantic_anchors": [{"semantic_name": "screen", "role_id": "display-shell",
                              "object_id": "device-shell", "anchor_id": "screen-center"}]}


def binding_model():
    assert hasattr(contracts, "IllustrationAssemblyBinding"), "strict authored IllustrationAssemblyBinding is missing"
    return contracts.IllustrationAssemblyBinding


@pytest.mark.parametrize("family", ["icon", "pictogram", "device", "document", "terminal"])
def test_only_existing_illustration_families_have_explicit_authored_content_state(family):
    raw = binding()
    raw["family"] = family
    assert binding_model().model_validate(raw).model_dump(mode="json") == raw


@pytest.mark.parametrize("kind", ["artwork", "content"])
def test_plan_may_author_a_single_content_role_without_universal_labels_states_or_anchors(kind):
    raw = binding()
    raw["roles"] = [raw["roles"][0]]
    raw["roles"][0]["kind"] = kind
    raw["semantic_anchors"] = []
    assert binding_model().model_validate(raw).model_dump(mode="json") == raw


@pytest.mark.parametrize("field", ["version", "family", "content_state_id", "roles", "semantic_anchors"])
def test_assembly_has_no_implicit_content_state_role_or_anchor_inventory(field):
    raw = binding()
    raw.pop(field)
    with pytest.raises(ValueError):
        binding_model().model_validate(raw)


@pytest.mark.parametrize("fault", ["version", "new_family", "blank_state", "no_roles", "duplicate_role_id",
    "duplicate_root", "blank_role_id", "blank_root", "unknown_kind", "label_only", "blank_anchor",
    "duplicate_anchor", "foreign_role", "blank_anchor_leaf", "blank_anchor_id", "inferred_parts"])
def test_contract_rejects_ambiguous_or_inferred_illustration_content(fault):
    raw = binding()
    if fault == "version":
        raw["version"] = "9.0.0"
    elif fault == "new_family":
        raw["family"] = "automatic-infographic"
    elif fault == "blank_state":
        raw["content_state_id"] = " "
    elif fault == "no_roles":
        raw["roles"] = []
    elif fault == "duplicate_role_id":
        raw["roles"][1]["role_id"] = raw["roles"][0]["role_id"]
    elif fault == "duplicate_root":
        raw["roles"][1]["object_id"] = raw["roles"][0]["object_id"]
    elif fault in {"blank_role_id", "blank_root", "unknown_kind"}:
        field = {"blank_role_id": "role_id", "blank_root": "object_id", "unknown_kind": "kind"}[fault]
        raw["roles"][0][field] = "infer-slot" if fault == "unknown_kind" else " "
    elif fault == "label_only":
        raw["roles"][0]["kind"] = "label"
    elif fault == "blank_anchor":
        raw["semantic_anchors"][0]["semantic_name"] = " "
    elif fault == "duplicate_anchor":
        raw["semantic_anchors"].append(deepcopy(raw["semantic_anchors"][0]))
    elif fault == "foreign_role":
        raw["semantic_anchors"][0]["role_id"] = "inferred-screen"
    elif fault in {"blank_anchor_leaf", "blank_anchor_id"}:
        raw["semantic_anchors"][0]["object_id" if fault == "blank_anchor_leaf" else "anchor_id"] = " "
    else:
        raw["generated_registry_parts"] = ["screen", "keyboard"]
    model = binding_model()
    with pytest.raises(ValueError):
        model.model_validate(raw)


def test_bare_legacy_group_never_acquires_illustration_metadata():
    layout, _ = grouped_documents()
    raw = deepcopy(layout["objects"][-1])
    assert contracts.GroupContainer.model_validate(raw).model_dump(mode="json") == raw


def invalid_identifier(raw, field, value):
    if field == "state":
        raw["content_state_id"] = value
    elif field == "role":
        raw["roles"][0]["role_id"] = value
        raw["semantic_anchors"][0]["role_id"] = value
    else:
        raw["semantic_anchors"][0][field] = value


@pytest.mark.parametrize("field", ["state", "role", "role_id", "semantic_name"])
@pytest.mark.parametrize("value", [" display-on", "display on", "display-on ", "display\ton", "display-on\n", "display\x00on"])
def test_authored_identifiers_are_stable_tokens_not_whitespace_or_control_text(field, value):
    raw = binding()
    invalid_identifier(raw, field, value)
    model = contracts.IllustrationAnchorBinding if field == "role_id" else binding_model()
    document = raw["semantic_anchors"][0] if field == "role_id" else raw
    with pytest.raises(ValueError):
        model.model_validate(document)


def documents(family="device"):
    """Graph/identity fixture only, not final artwork for these five families."""
    layout, timeline = grouped_documents()
    group = deepcopy(layout["objects"][-1])
    group.update(object_id="illustration-group", beat_id="beat-002", coverage_ids=["coverage-3"],
        z_index=10, child_ids=[row["object_id"] for row in binding()["roles"]], illustration_assembly=binding())
    group["illustration_assembly"]["family"] = family
    group["geometry"]["bounds"] = {"x": 240., "y": 220., "width": 310., "height": 270.}
    shell = deepcopy(layout["objects"][0])
    shell.update(object_id="device-shell", parent_id=group["object_id"], beat_id="beat-002", coverage_ids=["coverage-3"],
        z_index=0, initial_state="visible", visible=True, asset_id=None,
        anchors=[{"anchor_id": "screen-center", "point": {"x": .5, "y": .5}}])
    shell["geometry"]["bounds"] = {"x": 240., "y": 220., "width": 310., "height": 200.}
    label = deepcopy(layout["objects"][1])
    label.update(object_id="device-label", parent_id=group["object_id"], beat_id="beat-002", coverage_ids=["coverage-3"],
        z_index=1, initial_state="visible", visible=True, asset_id=None, text="Workstation")
    label["geometry"]["bounds"] = {"x": 240., "y": 430., "width": 310., "height": 60.}
    layout["objects"].extend([group, shell, label])
    layout["boards"][0].update(object_ids=[obj["object_id"] for obj in layout["objects"]], density_limit=12)
    fields = {"object_id", "object_type", "board_id", "beat_id", "semantic_role", "description", "asset_id",
              "initial_state", "coverage_ids", "child_ids", "illustration_assembly", "registry_binding"}
    plan = visual_plan_v2()
    plan["objects"] = [{key: deepcopy(value) for key, value in obj.items() if key in fields} for obj in layout["objects"]]
    plan["boards"] = deepcopy(layout["boards"])
    plan["assets"] = []
    plan["actions"] = [deepcopy(row["action"]) for row in timeline["actions"]]
    for beat in plan["beats"]:
        beat["object_ids"] = [obj["object_id"] for obj in plan["objects"] if obj["beat_id"] == beat["beat_id"]]
        beat["evidence"] = None
    layout["plan_sha256"] = digest(plan)
    return plan, layout


@pytest.mark.parametrize("family", ["icon", "pictogram", "device", "document", "terminal"])
def test_assembly_is_exact_real_semantic_and_executable_group_content(family):
    plan, layout = documents(family)
    contracts.validate_plan_layout(plan, layout)
    parsed = contracts.ExecutableLayoutV2.model_validate(layout)
    group = next(obj for obj in parsed.objects if obj.object_id == "illustration-group")
    assert group.illustration_assembly.model_dump(mode="json") == next(
        obj for obj in plan["objects"] if obj["object_id"] == group.object_id)["illustration_assembly"]


@pytest.mark.parametrize("fault", ["missing_role", "role_order", "parent", "foreign_beat", "coverage",
    "cross_role_anchor", "group_anchor", "unknown_anchor", "external_anchor", "mark_label", "unowned_child"])
def test_assembly_requires_actual_disjoint_roles_and_declared_leaf_anchor_ownership(fault):
    _, layout = documents()
    objects = {obj["object_id"]: obj for obj in layout["objects"]}
    group = objects["illustration-group"]
    if fault == "missing_role":
        group["illustration_assembly"]["roles"][0]["object_id"] = "missing-shell"
    elif fault == "role_order":
        group["child_ids"].reverse()
    elif fault == "parent":
        objects["device-shell"]["parent_id"] = None
    elif fault == "foreign_beat":
        objects["device-shell"]["beat_id"] = "beat-001"
    elif fault == "coverage":
        objects["device-shell"]["coverage_ids"] = ["coverage-1"]
    elif fault == "cross_role_anchor":
        anchor = group["illustration_assembly"]["semantic_anchors"][0]
        anchor.update(object_id="device-label", anchor_id=objects["device-label"]["anchors"][0]["anchor_id"])
    elif fault == "group_anchor":
        group["illustration_assembly"]["semantic_anchors"][0]["object_id"] = group["object_id"]
    elif fault == "unknown_anchor":
        group["illustration_assembly"]["semantic_anchors"][0]["anchor_id"] = "inferred-slot"
    elif fault == "external_anchor":
        group["illustration_assembly"]["semantic_anchors"][0].update(object_id="object-system", anchor_id="center")
    elif fault == "mark_label":
        label = deepcopy(objects["device-shell"])
        label.update(object_id="device-label", z_index=1)
        layout["objects"][-1] = label
    else:
        objects["object-evidence"]["parent_id"] = group["object_id"]
        group["child_ids"].append("object-evidence")
    with pytest.raises(ValueError, match="parentage" if fault == "parent" else "illustration_assembly"):
        contracts.ExecutableLayoutV2.model_validate(layout)


@pytest.mark.parametrize("field", ["family", "content_state_id", "semantic_anchors", "missing_layout", "missing_plan"])
def test_layout_cannot_change_or_drop_authored_illustration_semantics(field):
    plan, layout = documents()
    group = next(obj for obj in layout["objects"] if obj["object_id"] == "illustration-group")
    if field == "family":
        group["illustration_assembly"][field] = "document"
    elif field == "content_state_id":
        group["illustration_assembly"][field] = "display-off"
    elif field == "semantic_anchors":
        group["illustration_assembly"][field] = []
    elif field == "missing_layout":
        group.pop("illustration_assembly")
    else:
        next(obj for obj in plan["objects"] if obj["object_id"] == group["object_id"]).pop("illustration_assembly")
        layout["plan_sha256"] = digest(plan)
    with pytest.raises(ValueError, match="illustration_assembly"):
        contracts.validate_plan_layout(plan, layout)


def test_actual_bound_registry_leaf_preserves_exact_existing_binding():
    _, layout = registry_documents()
    art = next(obj for obj in layout["objects"] if obj["object_id"] == "device-shell")
    contracts.ExecutableLayoutV2.model_validate(layout)
    art.pop("registry_binding")
    with pytest.raises(ValueError, match="illustration_assembly.*registry"):
        contracts.ExecutableLayoutV2.model_validate(layout)


def registry_documents():
    plan, layout = documents()
    original = next(obj for obj in layout["objects"] if obj["object_id"] == "device-shell")
    art = registry_object()
    art.update({field: deepcopy(original[field]) for field in
        ("object_id", "parent_id", "board_id", "beat_id", "coverage_ids", "z_index", "initial_state", "visible")})
    layout["objects"][-2] = art
    anchor = next(obj for obj in layout["objects"] if obj["object_id"] == "illustration-group")[
        "illustration_assembly"]["semantic_anchors"][0]
    anchor["anchor_id"] = art["anchors"][0]["anchor_id"]
    fields = set(plan["objects"][0]) | {"child_ids", "illustration_assembly", "registry_binding"}
    plan["objects"] = [{key: deepcopy(value) for key, value in obj.items() if key in fields} for obj in layout["objects"]]
    layout["plan_sha256"] = digest(plan)
    return plan, layout


@pytest.mark.parametrize("fault", ["missing-binding", "false-name", "false-family", "false-fit", "corrupt-art", "missing-art"])
def test_real_normal_write_keeps_registry_leaf_authentication_independent(tmp_path, monkeypatch, fault):
    service, project, plan, _, _ = stored_v2_basis(tmp_path)
    try:
        authored, layout = registry_documents()
        for field in ("objects", "boards", "beats", "actions", "assets"):
            plan[field] = deepcopy(authored[field])
        pid = project["project_id"]
        plan["project_revision"] = project["revision"]
        project = service.write(pid, "storyboard", plan, project["revision"])
        layout.update(project_id=pid, project_revision=project["revision"],
                      plan_revision=project["artifacts"]["storyboard"], plan_sha256=digest(plan))
        project = service.write(pid, "layout", layout, project["revision"])
        assert service.artifact(pid, "storyboard")["document"] == plan
        assert service.artifact(pid, "layout")["document"] == layout
        before = history(service, pid)
        media = {str(path): sha256(path.read_bytes()).hexdigest() for path in tmp_path.rglob("*.wav")}
        kind = "storyboard" if fault in {"missing-binding", "false-name", "false-family"} else "layout"
        candidate = deepcopy(plan if kind == "storyboard" else layout)
        candidate["project_revision"] = project["revision"]
        art = next(obj for obj in candidate["objects"] if obj["object_id"] == "device-shell")
        if fault == "missing-binding":
            art.pop("registry_binding")
        elif fault == "false-name":
            art["registry_binding"]["anchor_mappings"][0]["registry_anchor_name"] = "imaginary-part"
        elif fault == "false-family":
            art["object_type"] = "device"  # Still a strict valid member; its own registry family must reject.
        elif fault == "false-fit":
            art["anchors"][0]["point"]["x"] = .31
        elif fault == "missing-art":
            is_file = Path.is_file
            monkeypatch.setattr(Path, "is_file", lambda path: False if path.name == "person-collaborators.svg" else is_file(path))
        else:
            read = Path.read_bytes
            def resource_read(path):
                if path.name == "person-collaborators.svg":
                    return read(path) + b"\ncorrupt"
                return read(path)
            monkeypatch.setattr(Path, "read_bytes", resource_read)
        # These coherent per-document claims must fail on this real write path,
        # not become trusted merely because the outer Group supplies roles.
        with pytest.raises(ProjectError) as failure:
            service.write(pid, kind, candidate, project["revision"])
        assert failure.value.code == "invalid_artifact"
        assert service.open(pid)["revision"] == project["revision"]
        assert history(service, pid) == before
        assert media == {str(path): sha256(path.read_bytes()).hexdigest() for path in tmp_path.rglob("*.wav")}
    finally:
        service.store.close()


def test_binding_is_exact_immutable_content_while_sampled_motion_is_basis_only():
    _, raw = documents()
    layout = contracts.ExecutableLayoutV2.model_validate(raw)
    sample = sample_for_layout(layout)
    def receipt(typed, frame):
        return next(row for row in split_content_receipts(typed, frame, {}) if row.object_id == "illustration-group")
    original = receipt(layout, sample)
    group = next(obj for obj in layout.objects if obj.object_id == "illustration-group")
    group.illustration_assembly.content_state_id = "display-off"
    assert receipt(layout, sample).content_sha256 != original.content_sha256
    group.illustration_assembly.content_state_id = "display-on"
    moved = replace(sample, objects=tuple(replace(row, transform=replace(row.transform,
        position=replace(row.transform.position, x=10.))) if row.object_id == group.object_id else row for row in sample.objects))
    assert receipt(layout, moved).content_sha256 == original.content_sha256


@pytest.mark.parametrize("schema", ["visual-plan-v2", "executable-layout-v2"])
def test_exported_schema_publishes_bound_group_without_allowing_owner_retagging(schema):
    plan, layout = documents()
    document = plan if schema == "visual-plan-v2" else layout
    validator = Draft202012Validator(load_schema(schema))
    validator.validate(document)
    group = next(obj for obj in document["objects"] if obj["object_id"] == "illustration-group")
    group["object_type"] = "rectangle"
    with pytest.raises(SchemaValidationError):
        validator.validate(document)


@pytest.mark.parametrize("schema", ["visual-plan-v2", "executable-layout-v2"])
@pytest.mark.parametrize("fault", ["no_children", "null_children", "label_only", "dual_owner"])
def test_exported_schema_preserves_local_assembly_ownership_and_content_requirements(schema, fault):
    from test_v2_character_assembly_contract import binding as character_binding

    plan, layout = documents()
    document = plan if schema == "visual-plan-v2" else layout
    group = next(obj for obj in document["objects"] if obj["object_id"] == "illustration-group")
    if fault == "no_children":
        group.pop("child_ids")
    elif fault == "null_children":
        group["child_ids"] = None
    elif fault == "label_only":
        group["illustration_assembly"]["roles"][0]["kind"] = "label"
    else:
        group["character_assembly"] = character_binding()
    assert list(Draft202012Validator(load_schema(schema)).iter_errors(document))


@pytest.mark.parametrize("schema", ["visual-plan-v2", "executable-layout-v2"])
@pytest.mark.parametrize("field", ["state", "role", "role_id", "semantic_name"])
@pytest.mark.parametrize("value", [" display-on", "display on", "display-on ", "display\ton", "display-on\n", "display\x00on"])
def test_exported_schema_rejects_unstable_illustration_identifiers(schema, field, value):
    plan, layout = documents()
    document = plan if schema == "visual-plan-v2" else layout
    group = next(obj for obj in document["objects"] if obj["object_id"] == "illustration-group")
    invalid_identifier(group["illustration_assembly"], field, value)
    assert list(Draft202012Validator(load_schema(schema)).iter_errors(document))


@pytest.mark.parametrize("real_text", [False, True])
def test_label_role_group_can_have_real_supporting_marks_but_cannot_infer_text(real_text):
    _, layout = documents()
    objects = {obj["object_id"]: obj for obj in layout["objects"]}
    label = objects["device-label"]
    group = deepcopy(objects["illustration-group"])
    group.pop("illustration_assembly")
    group.update(object_id="label-role", parent_id="illustration-group", z_index=1, child_ids=[])
    mark = deepcopy(objects["device-shell"])
    mark.update(object_id="label-support", parent_id=group["object_id"], z_index=1)
    label.update(parent_id=group["object_id"], z_index=0)
    group["child_ids"] = [label["object_id"], mark["object_id"]] if real_text else [mark["object_id"]]
    if not real_text:
        label["parent_id"] = None
    owner = objects["illustration-group"]
    owner["child_ids"][1] = group["object_id"]
    owner["illustration_assembly"]["roles"][1]["object_id"] = group["object_id"]
    layout["objects"].extend([group, mark])
    layout["boards"][0]["object_ids"] = [obj["object_id"] for obj in layout["objects"]]
    if real_text:
        contracts.ExecutableLayoutV2.model_validate(layout)
    else:
        with pytest.raises(ValueError, match="illustration_assembly.*label"):
            contracts.ExecutableLayoutV2.model_validate(layout)


def test_real_editable_code_can_supply_explicit_label_or_content():
    _, layout = documents("terminal")
    original = layout["objects"][-1]
    code = code_object()
    code.update({key: deepcopy(original[key]) for key in
        ("object_id", "parent_id", "board_id", "beat_id", "coverage_ids", "z_index", "initial_state", "visible")})
    layout["objects"][-1] = code
    parsed = contracts.ExecutableLayoutV2.model_validate(layout)
    assert parsed.objects[-1].code_payload is not None
    assert parsed.objects[-1].text == "\tx = 'Ω'  \n"


@pytest.mark.parametrize("nested", ["binding", "role", "anchor"])
def test_content_identity_refuses_bypass_constructed_unknown_illustration_payloads(nested):
    _, raw = documents()
    layout = contracts.ExecutableLayoutV2.model_validate(raw)
    group = next(obj for obj in layout.objects if obj.object_id == "illustration-group")
    if nested == "binding":
        class Forged(contracts.IllustrationAssemblyBinding):
            invented_parts: bool = True
        group.illustration_assembly = Forged.model_validate(binding())
    elif nested == "role":
        class Forged(contracts.IllustrationRoleBinding):
            invented_parts: bool = True
        group.illustration_assembly.roles[0] = Forged.model_validate(binding()["roles"][0])
    else:
        class Forged(contracts.IllustrationAnchorBinding):
            invented_parts: bool = True
        group.illustration_assembly.semantic_anchors[0] = Forged.model_validate(binding()["semantic_anchors"][0])
    with pytest.raises(ValueError, match="unknown nested payload subclass"):
        split_content_receipts(layout, sample_for_layout(layout), {})


@pytest.mark.parametrize("bound", [False, True])
def test_independent_canonical_group_projection_retains_bare_legacy_identity(bound):
    _, raw = documents()
    group = next(obj for obj in raw["objects"] if obj["object_id"] == "illustration-group")
    if not bound:
        group.pop("illustration_assembly")
    layout = contracts.ExecutableLayoutV2.model_validate(raw)
    receipts = {row.object_id: row for row in split_content_receipts(layout, sample_for_layout(layout), {})}
    payload = {key: group[key] for key in ("object_type", "geometry", "style", "anchors", "asset_id")}
    if bound:
        payload["illustration_assembly"] = group["illustration_assembly"]
    payload["children"] = [{"object_id": key, "content_sha256": receipts[key].content_sha256}
        for key in sorted(group["child_ids"])]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    assert receipts[group["object_id"]].canonical_json == encoded
    assert receipts[group["object_id"]].content_sha256 == sha256(encoded.encode()).hexdigest()


@pytest.mark.parametrize("nested", ["illustration", "character", "technical"])
def test_separately_owned_assembly_or_technical_subtree_cannot_be_borrowed(nested):
    if nested == "illustration":
        _, layout = documents()
        child_id = "illustration-group"
    elif nested == "character":
        from test_v2_character_assembly_contract import documents as character_documents
        _, layout = character_documents()
        child_id = "actor-group"
    else:
        from test_v2_technical_frame_contract import documents as technical_documents
        _, layout = technical_documents()
        child_id = "list-group"
    child = next(obj for obj in layout["objects"] if obj["object_id"] == child_id)
    group = deepcopy(child)
    group.pop("illustration_assembly", None)
    group.pop("character_assembly", None)
    authored = binding()
    authored["roles"] = [{"role_id": "whole-artwork", "kind": "artwork", "object_id": child_id}]
    authored["semantic_anchors"] = []
    group.update(object_id="outer-illustration", child_ids=[child_id], z_index=11,
                 illustration_assembly=authored)
    child["parent_id"] = group["object_id"]
    layout["objects"].append(group)
    layout["boards"][0].update(object_ids=[obj["object_id"] for obj in layout["objects"]], density_limit=12)
    with pytest.raises(ValueError, match="illustration_assembly.*borrow"):
        contracts.ExecutableLayoutV2.model_validate(layout)
