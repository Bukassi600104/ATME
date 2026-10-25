"""Authored character assemblies are actual layered Groups, never inferred rigs."""

import json
from copy import deepcopy
from hashlib import sha256

import pytest
from conftest import load_schema
from jsonschema import Draft202012Validator
from test_v2_group_hierarchy import grouped_documents
from test_v2_split_identity import sample_for_layout
from v2_fixtures import digest, visual_plan_v2

from atme.render.v2_split_identity import split_content_receipts
from atme.store import contracts_v2 as contracts


def binding():
    return {"version": "1.0.0", "pose_id": "neutral", "roles": [
        {"role": role, "object_id": "actor-" + role}
        for role in ("head", "torso", "left_arm", "right_arm")],
        "semantic_anchors": [
            {"semantic_name": "head", "object_id": "actor-head", "anchor_id": "head-top"},
            {"semantic_name": "left_hand", "object_id": "actor-left_arm", "anchor_id": "hand"},
            {"semantic_name": "right_hand", "object_id": "actor-right_arm", "anchor_id": "hand"}]}


def binding_model():
    assert hasattr(contracts, "CharacterAssemblyBinding"), "strict authored CharacterAssemblyBinding is missing"
    return contracts.CharacterAssemblyBinding


def documents(pose="neutral"):
    layout, timeline = grouped_documents()
    actor = deepcopy(layout["objects"][-1])
    actor.update(object_id="actor-group", beat_id="beat-002", coverage_ids=["coverage-3"], z_index=10,
        child_ids=[row["object_id"] for row in binding()["roles"]], character_assembly=binding(),
        description="Original authored layered presenter", semantic_role="Presenter gesture")
    actor["character_assembly"]["pose_id"] = pose
    actor["geometry"]["bounds"] = {"x": 240., "y": 230., "width": 310., "height": 280.}
    paths = {
        "neutral": ("M 330 350 Q 300 380 295 435 L 310 440", "M 410 350 Q 440 385 450 430 L 435 440"),
        "point_right": ("M 330 350 Q 300 380 295 435 L 310 440", "M 410 350 Q 455 335 480 350 L 540 345 M 520 345 L 540 333"),
        "open_hands": ("M 330 350 Q 300 375 270 350 L 250 330 M 270 350 L 250 345", "M 410 350 Q 440 375 475 350 L 495 330 M 475 350 L 495 345"),
    }
    hands = {"neutral": ((310., 440.), (435., 440.)),
        "point_right": ((310., 440.), (540., 345.)), "open_hands": ((250., 330.), (495., 330.))}
    parts = []
    for index, role in enumerate(("head", "torso", "left_arm", "right_arm")):
        part = deepcopy(layout["objects"][0])
        part.update(object_id="actor-" + role, object_type="ellipse" if role == "head" else "freehand",
            board_id=actor["board_id"], beat_id=actor["beat_id"], coverage_ids=["coverage-3"],
            parent_id=actor["object_id"], z_index=index, initial_state="visible", visible=True,
            asset_id=None, description="Original authored " + role, semantic_role=role,
            anchors=[{"anchor_id": "head-top" if role == "head" else "hand",
                "point": {"x": .5, "y": 0.}}],
            path_data=(None if role == "head" else "M 330 500 C 330 410 330 330 370 320 C 410 330 410 410 410 500"
                if role == "torso" else paths[pose][0 if role == "left_arm" else 1]),
            style={"stroke": "ink", "fill": None, "text": None, "effect": None})
        part["geometry"] = {"bounds": {"x": 335., "y": 230., "width": 70., "height": 80.},
            "points": [], "corner_radius": None} if role == "head" else {
            "bounds": {"x": 240., "y": 315., "width": 310., "height": 195.}, "points": [], "corner_radius": None}
        if role in {"left_arm", "right_arm"}:
            x, y = hands[pose][0 if role == "left_arm" else 1]
            part["anchors"][0]["point"] = {"x": (x - 240.) / 310., "y": (y - 315.) / 195.}
        parts.append(part)
    layout["objects"].extend([actor, *parts])
    layout["boards"][0].update(object_ids=[obj["object_id"] for obj in layout["objects"]], density_limit=12)
    fields = {"object_id", "object_type", "board_id", "beat_id", "semantic_role", "description",
        "asset_id", "initial_state", "coverage_ids", "child_ids", "character_assembly"}
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


@pytest.mark.parametrize("pose", ["neutral", "point_right", "open_hands"])
def test_finite_authored_character_pose_is_content_not_lifecycle_or_rig(pose):
    model = binding_model()
    raw = binding()
    raw["pose_id"] = pose
    assert model.model_validate(raw).model_dump(mode="json") == raw


@pytest.mark.parametrize("fault", ["version", "pose", "roles_missing", "roles_order", "roles_duplicate",
    "blank_part", "unknown_role", "anchor_name", "anchor_part", "anchor_id", "duplicate_name",
    "anchor_alias", "no_anchors", "generated_rig"])
def test_strict_assembly_does_not_infer_parts_anchors_pose_or_geometry(fault):
    model = binding_model()
    raw = binding()
    if fault == "version":
        raw["version"] = "9.0.0"
    elif fault == "pose":
        raw["pose_id"] = "infer-happy-walk"
    elif fault == "roles_missing":
        raw["roles"].pop()
    elif fault == "roles_order":
        raw["roles"][:2] = list(reversed(raw["roles"][:2]))
    elif fault == "roles_duplicate":
        raw["roles"][1]["object_id"] = raw["roles"][0]["object_id"]
    elif fault == "blank_part":
        raw["roles"][0]["object_id"] = " "
    elif fault == "unknown_role":
        raw["roles"][0]["role"] = "automatic-face"
    elif fault in {"anchor_name", "anchor_part", "anchor_id"}:
        field = {"anchor_name": "semantic_name", "anchor_part": "object_id", "anchor_id": "anchor_id"}[fault]
        raw["semantic_anchors"][0][field] = " "
    elif fault == "duplicate_name":
        raw["semantic_anchors"][1]["semantic_name"] = raw["semantic_anchors"][0]["semantic_name"]
    elif fault == "anchor_alias":
        alias = deepcopy(raw["semantic_anchors"][0])
        alias["semantic_name"] = "invented-head-alias"
        raw["semantic_anchors"].append(alias)
    elif fault == "no_anchors":
        raw["semantic_anchors"] = []
    else:
        raw["automatic_body_parts"] = ["head", "hands"]
    with pytest.raises(ValueError):
        model.model_validate(raw)


@pytest.mark.parametrize("field", ["version", "pose_id", "roles", "semantic_anchors"])
def test_every_assembly_field_is_explicit_no_default_inventory(field):
    model = binding_model()
    raw = binding()
    raw.pop(field)
    with pytest.raises(ValueError):
        model.model_validate(raw)


@pytest.mark.parametrize("fault", ["missing", "reordered", "unknown"])
def test_v1_anchor_inventory_is_explicit_stable_and_finite(fault):
    model = binding_model()
    raw = binding()
    if fault == "missing":
        raw["semantic_anchors"].pop()
    elif fault == "reordered":
        raw["semantic_anchors"][:2] = list(reversed(raw["semantic_anchors"][:2]))
    else:
        raw["semantic_anchors"][0]["semantic_name"] = "nose"
    with pytest.raises(ValueError):
        model.model_validate(raw)


@pytest.mark.parametrize("fault", ["head_left", "left_torso", "right_torso"])
def test_semantic_anchor_cannot_claim_a_different_real_role_closure(fault):
    binding_model()
    _, layout = documents()
    actor = next(obj for obj in layout["objects"] if obj["object_id"] == "actor-group")
    anchors = actor["character_assembly"]["semantic_anchors"]
    if fault == "head_left":
        # Keep all names and unique target/anchor pairs. Only role ownership is
        # false, so alias detection cannot accidentally satisfy this rejection.
        first = (anchors[0]["object_id"], anchors[0]["anchor_id"])
        anchors[0].update(object_id=anchors[1]["object_id"], anchor_id=anchors[1]["anchor_id"])
        anchors[1].update(object_id=first[0], anchor_id=first[1])
    else:
        anchors[1 if fault == "left_torso" else 2].update(object_id="actor-torso", anchor_id="hand")
    with pytest.raises(ValueError, match="character_assembly.*role"):
        contracts.ExecutableLayoutV2.model_validate(layout)


@pytest.mark.parametrize("pose", ["neutral", "point_right", "open_hands"])
def test_authored_assembly_binds_actual_group_role_inventory_and_semantic_meaning(pose):
    binding_model()
    plan, layout = documents(pose)
    contracts.validate_plan_layout(plan, layout)
    group = next(obj for obj in contracts.ExecutableLayoutV2.model_validate(layout).objects if obj.object_id == "actor-group")
    assert group.character_assembly.model_dump(mode="json") == next(
        obj for obj in plan["objects"] if obj["object_id"] == group.object_id)["character_assembly"]


@pytest.mark.parametrize("fault", ["self_role", "missing_role", "child_order", "parent", "foreign_beat",
    "coverage", "text_role", "external_anchor", "unknown_anchor", "unowned_child"])
def test_assembly_never_fabricates_or_borrows_foreign_parts_and_anchors(fault):
    binding_model()
    _, layout = documents()
    objects = {obj["object_id"]: obj for obj in layout["objects"]}
    actor = objects["actor-group"]
    if fault == "self_role":
        actor["character_assembly"]["roles"][0]["object_id"] = actor["object_id"]
    elif fault == "missing_role":
        actor["character_assembly"]["roles"][0]["object_id"] = "missing-head"
    elif fault == "child_order":
        actor["child_ids"][:2] = list(reversed(actor["child_ids"][:2]))
    elif fault == "parent":
        objects["actor-head"]["parent_id"] = None
    elif fault == "foreign_beat":
        objects["actor-head"]["beat_id"] = "beat-001"
    elif fault == "coverage":
        objects["actor-head"]["coverage_ids"] = ["coverage-1"]
    elif fault == "text_role":
        part = objects["actor-head"]
        part.pop("path_data")
        part.update(object_type="text", text="not an authored head", items=[])
    elif fault == "external_anchor":
        actor["character_assembly"]["semantic_anchors"][0].update(object_id="object-system", anchor_id="center")
    elif fault == "unknown_anchor":
        actor["character_assembly"]["semantic_anchors"][0]["anchor_id"] = "missing-anchor"
    else:
        actor["child_ids"].append("object-evidence")
        objects["object-evidence"]["parent_id"] = actor["object_id"]
    with pytest.raises(ValueError):
        contracts.ExecutableLayoutV2.model_validate(layout)


@pytest.mark.parametrize("fault", ["removed", "added", "pose"])
def test_layout_cannot_add_or_change_character_assembly_semantics(fault):
    binding_model()
    plan, layout = documents()
    actor = next(obj for obj in plan["objects"] if obj["object_id"] == "actor-group")
    if fault == "added":
        actor.pop("character_assembly")
    elif fault == "removed":
        next(obj for obj in layout["objects"] if obj["object_id"] == "actor-group").pop("character_assembly")
    else:
        actor["character_assembly"]["pose_id"] = "open_hands"
    with pytest.raises(ValueError, match="changes semantic field character_assembly"):
        contracts.validate_plan_layout(plan, layout)


def test_assembly_content_identity_pins_authored_binding_and_preserves_bare_group_hash():
    binding_model()
    _, raw = documents()
    for bound in (True, False):
        actor = next(obj for obj in raw["objects"] if obj["object_id"] == "actor-group")
        if not bound:
            actor.pop("character_assembly")
        layout = contracts.ExecutableLayoutV2.model_validate(raw)
        rows = {row.object_id: row for row in split_content_receipts(layout, sample_for_layout(layout), {})}
        payload = {key: actor[key] for key in ("object_type", "geometry", "style", "anchors", "asset_id")}
        if bound:
            payload["character_assembly"] = actor["character_assembly"]
        payload["children"] = [{"object_id": key, "content_sha256": rows[key].content_sha256}
            for key in sorted(actor["child_ids"])]
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        assert rows[actor["object_id"]].canonical_json == encoded
        assert rows[actor["object_id"]].content_sha256 == sha256(encoded.encode()).hexdigest()
        if not bound:
            assert "character_assembly" not in next(obj for obj in layout.objects
                if obj.object_id == actor["object_id"]).model_dump(mode="json")


@pytest.mark.parametrize("document_kind", ["plan", "layout"])
def test_schema_publishes_real_assembly_and_refuses_non_group_owner(document_kind):
    binding_model()
    plan, layout = documents()
    document = plan if document_kind == "plan" else layout
    name = "visual-plan-v2" if document_kind == "plan" else "executable-layout-v2"
    validator = Draft202012Validator(load_schema(name))
    validator.validate(document)
    actor = next(obj for obj in document["objects"] if obj["object_id"] == "actor-group")
    children = actor.pop("child_ids")
    assert list(validator.iter_errors(document))
    actor["child_ids"] = children
    actor["character_assembly"]["roles"][:2] = list(reversed(actor["character_assembly"]["roles"][:2]))
    assert list(validator.iter_errors(document))
    actor["character_assembly"]["roles"][:2] = list(reversed(actor["character_assembly"]["roles"][:2]))
    actor["character_assembly"]["semantic_anchors"][:2] = list(reversed(actor["character_assembly"]["semantic_anchors"][:2]))
    assert list(validator.iter_errors(document))
    actor["character_assembly"]["semantic_anchors"][:2] = list(reversed(actor["character_assembly"]["semantic_anchors"][:2]))
    actor["object_type"] = "clip"
    assert list(validator.iter_errors(document))


def test_semantic_assembly_belongs_only_to_an_explicit_group():
    binding_model()
    plan, _ = documents()
    actor = deepcopy(next(obj for obj in plan["objects"] if obj["object_id"] == "actor-group"))
    actor.pop("child_ids")
    actor["object_type"] = "rectangle"
    with pytest.raises(ValueError, match="character_assembly.*Group"):
        contracts.SemanticStandardObjectSpec.model_validate(actor)


def test_real_nested_mark_role_and_descendant_anchor_are_explicit_not_virtual():
    binding_model()
    plan, layout = documents()
    head = next(obj for obj in layout["objects"] if obj["object_id"] == "actor-head")
    ink = deepcopy(head)
    ink.update(object_id="actor-head-ink", parent_id=head["object_id"], z_index=0)
    head.pop("path_data")
    head.update(object_type="group", child_ids=[ink["object_id"]], anchors=[],
        style={"stroke": None, "fill": None, "text": None, "effect": None})
    layout["objects"].append(ink)
    actor = next(obj for obj in layout["objects"] if obj["object_id"] == "actor-group")
    actor["character_assembly"]["semantic_anchors"][0]["object_id"] = ink["object_id"]
    layout["boards"][0]["object_ids"].append(ink["object_id"])
    fields = set(plan["objects"][0]) | {"child_ids", "character_assembly"}
    plan["objects"] = [{key: deepcopy(value) for key, value in obj.items() if key in fields} for obj in layout["objects"]]
    plan["boards"] = deepcopy(layout["boards"])
    for beat in plan["beats"]:
        beat["object_ids"] = [obj["object_id"] for obj in plan["objects"] if obj["beat_id"] == beat["beat_id"]]
    contracts.validate_plan_layout(plan, layout)
    actor["character_assembly"]["semantic_anchors"][0]["object_id"] = head["object_id"]
    with pytest.raises(ValueError, match="character_assembly.*Group anchors"):
        contracts.ExecutableLayoutV2.model_validate(layout)


def test_authored_pose_and_anchor_identity_change_content_but_transform_does_not():
    binding_model()
    _, raw = documents()
    def receipts():
        layout = contracts.ExecutableLayoutV2.model_validate(raw)
        return {row.object_id: row.content_sha256 for row in split_content_receipts(layout, sample_for_layout(layout), {})}
    original = receipts()
    actor = next(obj for obj in raw["objects"] if obj["object_id"] == "actor-group")
    actor["transform"]["position"]["x"] += 10.
    assert receipts() == original
    actor["character_assembly"]["pose_id"] = "point_right"
    changed = receipts()
    assert changed["actor-group"] != original["actor-group"]
    assert changed["actor-right_arm"] == original["actor-right_arm"]
    arm = next(obj for obj in raw["objects"] if obj["object_id"] == "actor-right_arm")
    arm["anchors"][0]["point"]["x"] += .1
    assert receipts()["actor-group"] != changed["actor-group"]


@pytest.mark.parametrize("nested", ["binding", "role", "anchor"])
def test_identity_rejects_bypassed_unknown_character_payload_subclasses(nested):
    model = binding_model()
    _, raw = documents()
    layout = contracts.ExecutableLayoutV2.model_validate(raw)
    actor = next(obj for obj in layout.objects if obj.object_id == "actor-group")
    if nested == "binding":
        class Forged(model):
            phantom_rig: bool = True
        actor.character_assembly = Forged.model_validate(binding())
    elif nested == "role":
        class Forged(contracts.CharacterRoleBinding):
            phantom_rig: bool = True
        actor.character_assembly.roles[0] = Forged.model_validate(binding()["roles"][0])
    else:
        class Forged(contracts.CharacterAnchorBinding):
            phantom_rig: bool = True
        actor.character_assembly.semantic_anchors[0] = Forged.model_validate(binding()["semantic_anchors"][0])
    with pytest.raises(ValueError, match="unknown nested payload subclass"):
        split_content_receipts(layout, sample_for_layout(layout), {})
