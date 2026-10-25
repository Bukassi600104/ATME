"""External apertures are explicit read edges, never inferred ownership or runtime admission."""
from copy import deepcopy

import pytest
from atme.render.v2_split_identity import split_content_receipts
from atme.render.v2_state import evaluate_frame
from atme.store import contracts_v2 as contracts
from jsonschema import Draft202012Validator
from test_v2_character_assembly_contract import documents as character_documents
from test_v2_illustration_assembly_contract import documents as illustration_documents
from test_v2_mask_contract import MASK_FIELDS
from test_v2_semantic_aperture_membership import aperture_plan_documents
from test_v2_split_identity import sample_for_layout
from test_v2_structured_list_contract import documents as structured_list_documents
from test_v2_technical_frame_contract import documents as technical_documents
from v2_fixtures import digest


def external_aperture_documents(kind, *, portrait=False, group=False):
    plan, layout, timeline, ids = aperture_plan_documents(kind, portrait=portrait, bound=False)
    receiver = deepcopy(layout["objects"][1])
    receiver.pop("registry_binding")
    receiver.pop("variant")
    receiver.update(object_id="external-receiver", object_type="rectangle", parent_id=ids["root"],
                    initial_state="visible", visible=True, clip_id=ids["aperture"], anchors=[], z_index=20)
    receiver["style"] = {"stroke": "ink-primary", "fill": "accent-blue", "text": None, "effect": None}
    added = [receiver]
    if group:
        subtree = deepcopy(layout["objects"][0])
        subtree.update(object_id="external-subtree", child_ids=[receiver["object_id"]],
                       clip_id=ids["aperture"], parent_id=ids["root"], z_index=20)
        receiver.update(clip_id=None, parent_id=subtree["object_id"], z_index=0)
        added.insert(0, subtree)
    ids["receiver"] = added[0]["object_id"]
    layout["objects"][0]["child_ids"].append(ids["receiver"])
    plan["objects"][0]["child_ids"].append(ids["receiver"])
    fields = set(contracts.SemanticStandardObjectSpec.model_fields) | {"clip_id"}
    for obj in added:
        layout["objects"].append(obj)
        plan["objects"].append({key: deepcopy(value) for key, value in obj.items()
                               if key in fields and (key != "clip_id" or value is not None)})
        for inventory in (plan["boards"][0]["object_ids"], layout["boards"][0]["object_ids"],
                          plan["beats"][0]["object_ids"]):
            inventory.append(obj["object_id"])
        timeline["initial_object_states"].append({"object_id": obj["object_id"], "state": "visible",
                                                  "visible": True, "state_version": 1})
    layout["plan_sha256"] = digest(plan)
    timeline.update(plan_sha256=digest(plan), layout_sha256=digest(layout))
    return plan, layout, timeline, ids


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["clip", "mask"])
@pytest.mark.parametrize("group", [False, True])
def test_explicit_external_aperture_preserves_disjoint_leaf_or_group_ownership(kind, portrait, group):
    plan, layout, timeline, ids = external_aperture_documents(kind, portrait=portrait, group=group)
    original = deepcopy((plan, layout, timeline))
    parsed = contracts.VisualPlanV2.model_validate(plan)
    contracts.validate_plan_layout(plan, layout)
    Draft202012Validator(contracts.VisualPlanV2.model_json_schema()).validate(plan)
    semantic = {obj.object_id: obj for obj in parsed.objects}
    assert semantic[ids["receiver"]].clip_id == ids["aperture"]
    assert semantic[ids["aperture"]].child_ids == [ids["art"]]
    assert ids["receiver"] in semantic[ids["root"]].child_ids
    # Runtime admission now has its own native/pixel/lifecycle suite; preserve
    # the original disjoint ownership here rather than a superseded refusal.
    sample = evaluate_frame(layout, timeline, 1000)
    assert sample.object(ids["receiver"]).visible
    assert next(node for node in sample.hierarchy.nodes if node.object_id == ids["receiver"]).parent_id == ids["root"]
    assert (plan, layout, timeline) == original


@pytest.mark.parametrize("kind", ["clip", "mask"])
@pytest.mark.parametrize("fault", ["unknown", "self", "blank", "not_aperture", "no_members",
                                  "cross_board", "ancestor", "descendant", "nested_read"])
def test_external_reference_rejects_invalid_owner_and_read_edges_at_semantic_boundary(kind, fault):
    plan, _layout, _timeline, ids = external_aperture_documents(kind, group=True)
    contracts.VisualPlanV2.model_validate(plan)
    objects = {obj["object_id"]: obj for obj in plan["objects"]}
    receiver, owner, root = objects[ids["receiver"]], objects[ids["aperture"]], objects[ids["root"]]
    if fault == "unknown":
        receiver["clip_id"] = "missing-owner"
    elif fault == "self":
        receiver["clip_id"] = receiver["object_id"]
    elif fault == "blank":
        receiver["clip_id"] = " "
    elif fault == "not_aperture":
        receiver["clip_id"] = ids["art"]
    elif fault == "no_members":
        owner.pop("child_ids")
    elif fault == "cross_board":
        owner["board_id"] = "another-board"
    elif fault == "ancestor":
        root["child_ids"].remove(receiver["object_id"])
        owner["child_ids"].append(receiver["object_id"])
    elif fault == "descendant":
        root["child_ids"].remove(owner["object_id"])
        receiver["child_ids"].append(owner["object_id"])
        if kind == "mask":
            root["child_ids"].remove(ids["source"])
            receiver["child_ids"].append(ids["source"])
    else:
        # A real second aperture, with its own real content, not an empty dummy.
        other, content = deepcopy(owner), deepcopy(objects[ids["art"]])
        content.update(object_id="second-art")
        other.update(object_id="second-aperture", object_type="clip", child_ids=["second-art"])
        for field in ("mask_mode", "mask_source_object_id", "mask_coordinate_space", "invert", "feather_px"):
            other.pop(field, None)
        plan["objects"].extend([other, content])
        root["child_ids"].append("second-aperture")
        for inventory in (plan["boards"][0]["object_ids"], plan["beats"][0]["object_ids"]):
            inventory.extend(["second-aperture", "second-art"])
        if kind == "mask":
            # Mask consumers have no semantic clip_id field in the first seam.
            receiver["clip_id"] = "second-aperture"
            other["clip_id"] = ids["aperture"]
        else:
            owner["clip_id"] = "second-aperture"
    with pytest.raises(ValueError, match="external aperture|pattern|same-board"):
        contracts.VisualPlanV2.model_validate(plan)


def test_mask_source_is_never_a_consumer_even_if_the_external_edge_is_not_a_cycle():
    plan, _layout, _timeline, ids = external_aperture_documents("mask")
    contracts.VisualPlanV2.model_validate(plan)
    # Borrow an independent Clip rather than its owning Mask to isolate the guard.
    aperture = deepcopy(plan["objects"][2])
    aperture.update(object_id="other-aperture", object_type="clip", child_ids=[ids["receiver"]])
    for field in ("mask_mode", "mask_source_object_id", "mask_coordinate_space", "invert", "feather_px"):
        aperture.pop(field, None)
    plan["objects"][-1].pop("clip_id")
    plan["objects"][0]["child_ids"].remove(ids["receiver"])
    plan["objects"][0]["child_ids"].append(aperture["object_id"])
    plan["objects"].append(aperture)
    for inventory in (plan["boards"][0]["object_ids"], plan["beats"][0]["object_ids"]):
        inventory.append(aperture["object_id"])
    contracts.VisualPlanV2.model_validate(plan)
    plan["objects"][3]["clip_id"] = aperture["object_id"]
    with pytest.raises(ValueError, match="external aperture.*mask source"):
        contracts.VisualPlanV2.model_validate(plan)


@pytest.mark.parametrize("kind", ["clip", "mask"])
@pytest.mark.parametrize("fault", ["omitted", "null", "undeclared"])
def test_normal_write_requires_exact_semantic_reference_and_legacy_seam_cannot_drop_it(kind, fault):
    plan, layout, _timeline, ids = external_aperture_documents(kind)
    contracts.validate_plan_layout(plan, layout)
    candidate = layout["objects"][-1]
    if fault == "omitted":
        candidate.pop("clip_id")
    elif fault == "null":
        candidate["clip_id"] = None
    else:
        plan["objects"][-1].pop("clip_id")
    with pytest.raises(ValueError, match="semantic field clip_id"):
        contracts.validate_plan_layout(plan, layout)
    if fault == "undeclared":
        # Only trusted immutable history can preserve a prior layout-only edge.
        contracts.validate_plan_layout(plan, layout, require_code_payloads=False)
    else:
        with pytest.raises(ValueError, match="semantic field clip_id"):
            contracts.validate_plan_layout(plan, layout, require_code_payloads=False)
    assert candidate.get("clip_id") == (ids["aperture"] if fault == "undeclared" else None)


@pytest.mark.parametrize("kind", ["clip", "mask"])
def test_external_aperture_is_plan_layout_identity_not_intrinsic_artwork_content(kind):
    plan, layout, _timeline, ids = external_aperture_documents(kind)
    contracts.validate_plan_layout(plan, layout)
    typed = contracts.ExecutableLayoutV2.model_validate(layout)
    sample = sample_for_layout(typed)
    actual = {row.object_id: row for row in split_content_receipts(typed, sample, {})}
    without = deepcopy(layout)
    without["objects"][-1]["clip_id"] = None
    plain = contracts.ExecutableLayoutV2.model_validate(without)
    expected = {row.object_id: row for row in split_content_receipts(plain, sample_for_layout(plain), {})}
    assert actual[ids["receiver"]] == expected[ids["receiver"]]
    assert actual[ids["aperture"]] == expected[ids["aperture"]]
    assert actual[ids["art"]] == expected[ids["art"]]
    plain_plan = deepcopy(plan)
    plain_plan["objects"][-1].pop("clip_id")
    contracts.validate_plan_layout(plain_plan, without)
    assert digest(plan) != digest(plain_plan)
    assert digest(layout) != digest(without)
    assert "clip_id" not in contracts.VisualPlanV2.model_validate(
        aperture_plan_documents(kind, bound=False)[0]).model_dump(mode="json")["objects"][0]


@pytest.mark.parametrize("kind", ["clip", "mask"])
def test_combined_parent_and_external_read_cycle_is_not_mistaken_for_disjoint_ownership(kind):
    plan, _layout, _timeline, ids = external_aperture_documents(kind, group=True)
    contracts.VisualPlanV2.model_validate(plan)
    root, art, owner = plan["objects"][:3]
    group_a = next(obj for obj in plan["objects"] if obj["object_id"] == ids["receiver"])
    group_b = deepcopy(root)
    group_b.update(object_id="group-b", child_ids=[owner["object_id"]])
    root["child_ids"].remove(owner["object_id"])
    if kind == "mask":
        root["child_ids"].remove(ids["source"])
        group_b["child_ids"].append(ids["source"])
    root["child_ids"].append("group-b")
    second, content = deepcopy(owner), deepcopy(art)
    content["object_id"] = "other-content"
    second.update(object_id="other-clip", object_type="clip", child_ids=["other-content"])
    for field in ("mask_mode", "mask_source_object_id", "mask_coordinate_space", "invert", "feather_px"):
        second.pop(field, None)
    group_a["child_ids"].append("other-clip")
    for obj in (group_b, second, content):
        plan["objects"].append(obj)
        for inventory in (plan["boards"][0]["object_ids"], plan["beats"][0]["object_ids"]):
            inventory.append(obj["object_id"])
    contracts.VisualPlanV2.model_validate(plan)  # One-way read is acyclic.
    group_b["clip_id"] = "other-clip"
    with pytest.raises(ValueError, match="external aperture read dependency graph must be acyclic"):
        contracts.VisualPlanV2.model_validate(plan)


@pytest.mark.parametrize("family", ["character", "illustration", "technical", "structured_list"])
def test_external_reference_cannot_borrow_a_protected_real_role(family):
    factory = {"character": character_documents, "illustration": illustration_documents,
               "technical": technical_documents, "structured_list": structured_list_documents}[family]
    plan, _layout = factory()
    contracts.VisualPlanV2.model_validate(plan)
    binding_field = {"character": "character_assembly", "illustration": "illustration_assembly",
                     "technical": "technical_frame", "structured_list": "structured_list"}[family]
    owner = next(obj for obj in plan["objects"] if obj.get(binding_field))
    binding = owner[binding_field]
    if family == "structured_list":
        consumer_id = binding["item_object_ids"][0]
    else:
        consumer_id = binding["roles"][0]["object_id"]
    consumer = next(obj for obj in plan["objects"] if obj["object_id"] == consumer_id)
    base, _unused_layout, _clock, ids = aperture_plan_documents("clip", bound=False)
    aperture, content = deepcopy(base["objects"][2]), deepcopy(base["objects"][1])
    for obj in (aperture, content):
        obj.update(board_id=consumer["board_id"], beat_id=consumer["beat_id"],
                   coverage_ids=deepcopy(consumer["coverage_ids"]))
        plan["objects"].append(obj)
        next(row for row in plan["boards"] if row["board_id"] == obj["board_id"])["object_ids"].append(obj["object_id"])
        next(row for row in plan["beats"] if row["beat_id"] == obj["beat_id"])["object_ids"].append(obj["object_id"])
    for board in plan["boards"]:
        board["density_limit"] = max(board["density_limit"], len(board["object_ids"]))
    contracts.VisualPlanV2.model_validate(plan)
    consumer["clip_id"] = ids["aperture"]
    with pytest.raises(ValueError, match="external aperture cannot borrow protected"):
        contracts.VisualPlanV2.model_validate(plan)


def test_external_reference_cannot_borrow_a_bound_composition_member():
    plan, layout, _timeline, ids = aperture_plan_documents("clip", bound=True)
    receiver = deepcopy(plan["objects"][1])
    receiver.pop("registry_binding")
    receiver.update(object_id="external-outsider", object_type="rectangle")
    plan["objects"].append(receiver)
    for inventory in (plan["boards"][0]["object_ids"], plan["beats"][0]["object_ids"]):
        inventory.append(receiver["object_id"])
    contracts.VisualPlanV2.model_validate(plan)
    receiver["clip_id"] = ids["aperture"]
    with pytest.raises(ValueError, match="external aperture cannot borrow protected"):
        contracts.VisualPlanV2.model_validate(plan)
    # Definitions do not gain a hidden cross-instance reference capability.
    definition = deepcopy(layout["objects"][0]["composition_binding"]["instance"]["definition"])
    definition["objects"][1]["clip_id"] = "aperture"
    with pytest.raises(ValueError):
        contracts.CompositionDefinition.model_validate(definition)


@pytest.mark.parametrize("kind", ["clip", "mask"])
def test_layout_cannot_silently_reparent_the_new_read_consumer(kind):
    plan, layout, _timeline, ids = external_aperture_documents(kind)
    contracts.validate_plan_layout(plan, layout)
    layout["objects"][-1]["parent_id"] = None
    layout["objects"][0]["child_ids"].remove(ids["receiver"])
    contracts.ExecutableLayoutV2.model_validate(layout)
    with pytest.raises(ValueError, match="external aperture must preserve explicit semantic ownership"):
        contracts.validate_plan_layout(plan, layout)


@pytest.mark.parametrize("value", ["", " ", 1, False])
def test_malformed_external_reference_is_rejected_at_the_semantic_boundary(value):
    plan, _layout, _timeline, _ids = external_aperture_documents("clip")
    contracts.VisualPlanV2.model_validate(plan)
    plan["objects"][-1]["clip_id"] = value
    with pytest.raises(ValueError):
        contracts.VisualPlanV2.model_validate(plan)


def test_legacy_mask_without_dedicated_source_cannot_be_borrowed_as_an_external_aperture():
    plan, _layout, _clock, _ids = external_aperture_documents("mask")
    contracts.VisualPlanV2.model_validate(plan)
    for field in MASK_FIELDS:
        plan["objects"][2].pop(field)
    with pytest.raises(ValueError, match="external aperture requires a Mask's explicit dedicated geometry source"):
        contracts.VisualPlanV2.model_validate(plan)


@pytest.mark.parametrize("kind", ["clip", "mask"])
def test_new_external_read_is_same_board_not_artificially_same_beat(kind):
    plan, _layout, _clock, ids = external_aperture_documents(kind)
    contracts.VisualPlanV2.model_validate(plan)
    later = deepcopy(plan["beats"][0])
    later.update(beat_id="later-beat", object_ids=[ids["receiver"]], action_ids=[],
                 fallback_ids=[], coverage_ids=["later-coverage"])
    later["attention"].update(primary_targets=[ids["receiver"]], secondary_context=[], dimmed_targets=[])
    later["camera_intent"]["target_ids"] = [ids["receiver"]]
    later["continuity"].update(keep=[], change=[], remove=[], expected_state_versions={}, replacements={})
    row = deepcopy(plan["coverage"][0])
    move = plan["actions"][1]
    move.update(target_ids=[ids["receiver"]], coverage_id="later-coverage")
    later.update(action_ids=[move["action_id"]], fallback_ids=[move["fallback"]["fallback_id"]])
    plan["beats"][0]["action_ids"].remove(move["action_id"])
    plan["coverage"][0]["action_ids"].remove(move["action_id"])
    row.update(coverage_id="later-coverage", action_ids=[move["action_id"]])
    plan["coverage"].append(row)
    plan["beats"][0]["object_ids"].remove(ids["receiver"])
    plan["beats"].append(later)
    plan["objects"][-1].update(beat_id="later-beat", coverage_ids=["later-coverage"])
    contracts.VisualPlanV2.model_validate(plan)


@pytest.mark.parametrize("kind", ["clip", "mask"])
def test_changing_to_another_valid_aperture_is_not_semantic_reference_parity(kind):
    plan, layout, _clock, ids = external_aperture_documents(kind)
    contracts.validate_plan_layout(plan, layout)
    other, content = deepcopy(layout["objects"][2]), deepcopy(layout["objects"][-1])
    other.update(object_id="another-aperture", object_type="clip", child_ids=["another-content"])
    for field in MASK_FIELDS:
        other.pop(field, None)
    content.update(object_id="another-content", clip_id=None, parent_id="another-aperture", z_index=0)
    for obj in (other, content):
        layout["objects"].append(obj)
        plan["objects"].append({key: deepcopy(value) for key, value in obj.items()
                               if key in contracts.SemanticStandardObjectSpec.model_fields
                               and (key != "clip_id" or value is not None)})
        for inventory in (plan["boards"][0]["object_ids"], layout["boards"][0]["object_ids"],
                          plan["beats"][0]["object_ids"]):
            inventory.append(obj["object_id"])
    for document in (plan, layout):
        document["objects"][0]["child_ids"].append(other["object_id"])
    contracts.validate_plan_layout(plan, layout)
    receiver = next(obj for obj in layout["objects"] if obj["object_id"] == ids["receiver"])
    receiver["clip_id"] = other["object_id"]
    contracts.ExecutableLayoutV2.model_validate(layout)
    for strict in (False, True):
        with pytest.raises(ValueError, match="semantic field clip_id"):
            contracts.validate_plan_layout(plan, layout, require_code_payloads=strict)


@pytest.mark.parametrize("object_type", ["clip", "arrow"])
def test_standalone_aperture_and_connector_consumers_remain_explicitly_closed(object_type):
    plan, _layout, _clock, ids = external_aperture_documents("clip", group=object_type == "clip")
    consumer = next(obj for obj in plan["objects"] if obj["object_id"] == ids["receiver"])
    consumer["object_type"] = object_type
    consumer.pop("clip_id")
    contracts.VisualPlanV2.model_validate(plan)
    consumer["clip_id"] = ids["aperture"]
    with pytest.raises(ValueError, match="external aperture.*consumer"):
        contracts.VisualPlanV2.model_validate(plan)


def test_external_group_consumer_cannot_leave_its_real_subtree_undeclared():
    plan, _layout, _clock, ids = external_aperture_documents("clip", group=True)
    contracts.VisualPlanV2.model_validate(plan)
    consumer = next(obj for obj in plan["objects"] if obj["object_id"] == ids["receiver"])
    consumer.pop("child_ids")
    with pytest.raises(ValueError, match="external aperture.*consumer"):
        contracts.VisualPlanV2.model_validate(plan)


def test_real_protected_mask_source_fails_at_sibling_boundary_and_defensive_read_guard():
    plan, _layout = character_documents()
    contracts.VisualPlanV2.model_validate(plan)
    actor = next(obj for obj in plan["objects"] if obj.get("character_assembly"))
    source_id = actor["character_assembly"]["roles"][0]["object_id"]
    source = next(obj for obj in plan["objects"] if obj["object_id"] == source_id)
    base, _raw, _clock, ids = external_aperture_documents("mask")
    # Three real additions fit the already-approved 12-object board budget.
    # Reuse an ordinary existing consumer; no extra scaffold/dummy owner.
    added = deepcopy(base["objects"][1:4])
    for obj in added:
        obj.update(board_id=source["board_id"], beat_id=source["beat_id"],
                   coverage_ids=deepcopy(source["coverage_ids"]))
        plan["objects"].append(obj)
        next(row for row in plan["boards"] if row["board_id"] == obj["board_id"])["object_ids"].append(obj["object_id"])
        next(row for row in plan["beats"] if row["beat_id"] == obj["beat_id"])["object_ids"].append(obj["object_id"])
    for board in plan["boards"]:
        board["density_limit"] = max(board["density_limit"], len(board["object_ids"]))
    plan["objects"][0]["clip_id"] = ids["aperture"]
    contracts.VisualPlanV2.model_validate(plan)
    source["initial_state"] = "visible"
    next(obj for obj in added if obj["object_id"] == ids["aperture"])["mask_source_object_id"] = source_id
    with pytest.raises(ValueError, match="mask.*dedicated same-parent"):
        contracts.VisualPlanV2.model_validate(plan)
    # Unit-only guard assertion, NOT a model-valid source-only reachability or
    # execution claim: the full contract already rejects the non-sibling role.
    objects = {obj["object_id"]: contracts.SemanticMaskObjectSpec.model_validate(obj)
               if obj["object_type"] == "mask" else contracts.SemanticStandardObjectSpec.model_validate(obj)
               for obj in plan["objects"]}
    with pytest.raises(ValueError, match="external aperture cannot borrow protected"):
        contracts._validate_external_aperture_references(objects, contracts._semantic_group_parents(objects))
