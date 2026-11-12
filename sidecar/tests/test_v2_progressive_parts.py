"""Explicit whole-object and recursive-Group progression uses the shared clock."""

from copy import deepcopy

import pytest
import resvg_py
from atme.store import contracts_v2 as contracts
from PIL import ImageFont
from test_v2_group_annotation import consumer_clock
from test_v2_structured_list_policy import progression_documents, resolved_documents
from v2_fixtures import digest


def documents(portrait=False, grouped=False):
    plan, layout, timeline = resolved_documents()
    heading = next(obj for obj in layout["objects"] if obj["object_type"] == "list")
    heading.pop("structured_list")
    heading.update(object_type="text", visible=True, initial_state="visible")
    owner = next(obj for obj in layout["objects"] if obj["object_id"] == "list-group")
    roots = ["list-item-a", "list-item-b", "list-item-c"]
    mark = next(obj for obj in layout["objects"] if obj["object_id"] == "list-item-a")
    mark.pop("text")
    mark.pop("items")
    mark.update(object_type="rectangle", path_data=None)
    mark["style"] = {"stroke": "ink.accent", "fill": "surface.accent", "text": None, "effect": None}
    if grouped:
        leaf = next(obj for obj in layout["objects"] if obj["object_id"] == "list-item-c")
        leaf.update(object_id="part-text", parent_id="part-nested", z_index=0)
        nested = deepcopy(owner)
        nested.update(object_id="part-nested", parent_id="list-item-c", child_ids=["part-text"],
                      beat_id=leaf["beat_id"], coverage_ids=leaf["coverage_ids"],
                      initial_state="hidden", visible=False, z_index=1)
        part = deepcopy(nested)
        part.update(object_id="list-item-c", parent_id="list-group", child_ids=["part-mark", "part-nested"],
                    z_index=3)
        inner_mark = deepcopy(mark)
        inner_mark.update(object_id="part-mark", parent_id="list-item-c", z_index=0)
        inner_mark["geometry"]["bounds"]["x"] += 150
        layout["objects"].extend([part, nested, inner_mark])
    writes = [obj["object_id"] for obj in layout["objects"]
              if obj["object_id"] in roots or obj["object_id"].startswith("part-")]
    policy = {"version": "1.0.0", "container_group_id": "list-group", "part_root_ids": roots,
              "phases": [{"object_id": key, "weight": weight} for key, weight in zip(roots, (1, 2, 1), strict=True)],
              "expected_closure_state_versions": {key: 1 for key in writes},
              "expected_read_state_versions": {"list-group": 1}}
    action = plan["actions"][-1]
    action.pop("structured_list_policy")
    action["progressive_parts_policy"] = policy
    timeline["actions"][-1]["action"] = deepcopy(action)
    plan["assets"] = timeline["resolved_assets"] = []
    board = layout["boards"][0]
    board.update(object_ids=[obj["object_id"] for obj in layout["objects"]], density_limit=12)
    plan["boards"] = deepcopy(layout["boards"])
    fields = set(progression_documents()[0]["objects"][0]) - {"structured_list"}
    plan["objects"] = [{key: deepcopy(value) for key, value in obj.items() if key in fields}
                       for obj in layout["objects"]]
    for semantic, obj in zip(plan["objects"], layout["objects"], strict=True):
        semantic["initial_state"] = obj["initial_state"]
        if "child_ids" in obj:
            semantic["child_ids"] = deepcopy(obj["child_ids"])
    for beat in plan["beats"]:
        beat["object_ids"] = [obj["object_id"] for obj in layout["objects"] if obj["beat_id"] == beat["beat_id"]]
    if portrait:
        profile = {"profile_id": "SHORT_FORM_9_16", "width": 720, "height": 1280, "fps": 30}
        for doc in (plan, layout, timeline):
            doc["output_profile"] = deepcopy(profile)
        layout["canvas"].update(width=720, height=1280)
        for index, obj in enumerate(layout["objects"]):
            obj["geometry"]["bounds"].update(x=80, y=120+50*index, width=350,
                                                height=100 if obj["object_id"] == "object-label" else 40)
    timeline["initial_object_states"] = [{"object_id": obj["object_id"], "state": obj["initial_state"],
        "visible": obj["visible"], "state_version": 1} for obj in layout["objects"]]
    rehash(plan, layout, timeline)
    return plan, layout, timeline


def rehash(plan, layout, timeline):
    layout["plan_sha256"] = digest(plan)
    timeline["plan_sha256"] = digest(plan)
    timeline["layout_sha256"] = digest(layout)


@pytest.fixture(autouse=True)
def no_native(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("pure progressive-parts proof must not invoke native render/font work")
    monkeypatch.setattr(resvg_py, "svg_to_bytes", forbidden)
    monkeypatch.setattr(ImageFont, "truetype", forbidden)


def test_policy_is_additive_strict_and_legacy_dump_shape_is_preserved():
    assert hasattr(contracts, "ProgressivePartsPolicy"), "non-list progressive policy is missing"
    plan, layout, timeline = documents(grouped=True)
    parsed = contracts.VisualPlanV2.model_validate(plan)
    contracts.validate_plan_layout(parsed, contracts.ExecutableLayoutV2.model_validate(layout))
    contracts.ResolvedVisualTimelineV2.model_validate(timeline)
    policy = parsed.actions[-1].progressive_parts_policy
    assert policy.model_dump(mode="json") == plan["actions"][-1]["progressive_parts_policy"]
    legacy = progression_documents()[0]["actions"][0]
    assert contracts.TargetAction.model_validate(legacy).model_dump(mode="json") == legacy
    legacy["progressive_parts_policy"] = None
    assert "progressive_parts_policy" not in contracts.TargetAction.model_validate(legacy).model_dump(mode="json")


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("grouped", [False, True])
def test_whole_parts_step_at_weighted_phase_ends_and_commit_once(portrait, grouped):
    _, layout, timeline = documents(portrait, grouped)
    _, replay, _ = consumer_clock(layout, timeline)
    policy = timeline["actions"][-1]["action"]["progressive_parts_policy"]
    retained = {}
    for at_ms in (4000, 4224, 4225, 4226, 4674, 4675, 4676, 4899, 4900, 4901):
        sample = replay.at(at_ms)
        versions = dict(sample.state_versions)
        for key in policy["expected_closure_state_versions"]:
            end = 4225 if key == "list-item-a" else 4675 if key == "list-item-b" else 4900
            frame = sample.object(key)
            assert frame.visible == (at_ms >= end)
            assert frame.reveal_fraction == float(at_ms >= end)
            assert frame.state == ("visible" if at_ms >= 4900 else "hidden")
            assert versions[key] == (2 if at_ms >= 4900 else 1)
        assert versions["list-group"] == 1
        retained[at_ms] = sample
    for at_ms in (4901, 4000, 4676, 4224, 4900, 4899, 4225, 4675, 4226, 4674, 4000):
        assert replay.at(at_ms) == retained[at_ms]

@pytest.mark.parametrize("fault", ["empty", "duplicate", "blank", "owner_root", "missing_version", "extra_read",
    "phase_order", "zero_weight", "bool_weight", "float_weight", "bool_version", "zero_version", "unknown_field"])
def test_policy_rejects_ambiguous_inventory_or_types(fault):
    raw = documents()[0]["actions"][-1]["progressive_parts_policy"]
    if fault == "empty":
        raw["part_root_ids"] = []
    elif fault == "duplicate":
        raw["part_root_ids"][1] = raw["part_root_ids"][0]
    elif fault == "blank":
        raw["part_root_ids"][0] = " "
    elif fault == "owner_root":
        raw["part_root_ids"][0] = raw["container_group_id"]
    elif fault == "missing_version":
        raw["expected_closure_state_versions"].pop("list-item-a")
    elif fault == "extra_read":
        raw["expected_read_state_versions"]["list-item-a"] = 1
    elif fault == "phase_order":
        raw["phases"].reverse()
    elif fault.endswith("weight"):
        raw["phases"][0]["weight"] = {"zero_weight": 0, "bool_weight": True, "float_weight": 1.5}[fault]
    elif fault.endswith("version"):
        raw["expected_closure_state_versions"]["list-item-a"] = True if fault == "bool_version" else 0
    else:
        raw["inferred_parts"] = True
    with pytest.raises(ValueError):
        contracts.ProgressivePartsPolicy.model_validate(raw)


@pytest.mark.parametrize("fault", ["verb", "easing", "expected", "post", "targets", "annotation", "list_policy",
                                   "count_policy", "annotation_policy"])
def test_action_requires_one_exact_progressive_policy(fault):
    raw = documents()[0]["actions"][-1]
    if fault in {"verb", "easing", "expected", "post", "annotation"}:
        name, value = {"verb": ("verb", "reveal"), "easing": ("easing", "ease_out"),
                       "expected": ("expected_state", "visible"), "post": ("post_state", "hidden"),
                       "annotation": ("annotation", "invented")}[fault]
        raw[name] = value
    elif fault == "targets":
        raw["target_ids"].reverse()
    elif fault == "list_policy":
        raw["structured_list_policy"] = progression_documents()[0]["actions"][-1]["structured_list_policy"]
    elif fault == "count_policy":
        from test_v2_count_contract import count_policy
        raw["count_policy"] = count_policy()
    else:
        from test_v2_annotation_action import annotation_documents
        raw["annotation_policy"] = annotation_documents()[2]["actions"][-1]["action"]["annotation_policy"]
    with pytest.raises(ValueError):
        contracts.TargetAction.model_validate(raw)


@pytest.mark.parametrize("fault", ["unknown", "cross_board", "order", "overlap", "omitted_descendant", "stale_write",
    "stale_read", "hidden_read", "zero_read", "visible_part", "removed_part", "zero_part", "extra_closure",
    "missing_read", "extra_read", "unsupported_evidence", "collapsed", "bare"])
def test_current_capture_rejects_invalid_closure_state_and_read_authority(fault):
    plan, layout, timeline = documents(grouped=True)
    objects = {obj["object_id"]: obj for obj in layout["objects"]}
    policy = timeline["actions"][-1]["action"]["progressive_parts_policy"]
    if fault == "unknown":
        policy["expected_closure_state_versions"]["missing"] = 1
    elif fault == "cross_board":
        objects["part-text"]["board_id"] = "other-board"
    elif fault == "order":
        objects["list-item-a"]["z_index"], objects["list-item-b"]["z_index"] = 2, 1
    elif fault == "overlap":
        policy["part_root_ids"].append("part-text")
        policy["phases"].append({"object_id": "part-text", "weight": 1})
        timeline["actions"][-1]["action"]["target_ids"].append("part-text")
    elif fault == "omitted_descendant":
        policy["expected_closure_state_versions"].pop("part-text")
    elif fault == "extra_closure":
        policy["expected_closure_state_versions"]["object-system"] = 1
    elif fault == "stale_write":
        policy["expected_closure_state_versions"]["part-text"] = 2
    elif fault == "stale_read":
        policy["expected_read_state_versions"]["list-group"] = 2
    elif fault in {"hidden_read", "zero_read", "visible_part", "removed_part", "zero_part"}:
        key = "list-group" if fault.endswith("read") else "part-text"
        obj = objects[key]
        if fault.startswith("zero"):
            obj["opacity"] = 0
        else:
            obj.update(initial_state="visible" if fault == "visible_part" else "removed" if fault == "removed_part" else "hidden",
                       visible=fault == "visible_part")
        initial = next(row for row in timeline["initial_object_states"] if row["object_id"] == key)
        initial.update(state=obj["initial_state"], visible=obj["visible"])
    elif fault == "missing_read":
        outer = deepcopy(objects["list-group"])
        outer.update(object_id="outer-group", parent_id=None, child_ids=["list-group"])
        objects["list-group"]["parent_id"] = "outer-group"
        layout["objects"].append(outer)
        layout["boards"][0]["object_ids"].append("outer-group")
        timeline["initial_object_states"].append({"object_id": "outer-group", "state": "visible", "visible": True, "state_version": 1})
    elif fault == "extra_read":
        policy["expected_read_state_versions"]["object-label"] = 2
    elif fault == "unsupported_evidence":
        objects["part-mark"].pop("path_data")
        objects["part-mark"]["object_type"] = "evidence"
    elif fault == "collapsed":
        timeline["actions"][-1]["end_ms"] = 4002
    else:
        timeline["actions"][-1]["action"].pop("progressive_parts_policy")
    rehash(plan, layout, timeline)
    with pytest.raises(ValueError):
        consumer_clock(layout, timeline)


@pytest.mark.parametrize("target", ["list-item-a", "part-text", "part-nested", "list-group"])
def test_outer_interval_reserves_every_descendant_and_read_dependency(target):
    from test_v2_structured_list_replay import add_move
    plan, layout, timeline = documents(grouped=True)
    add_move(timeline, layout, target, 4100, 4200, expected_state=None)
    for coverage in timeline["coverage"]:
        coverage["action_ids"] = [row["action"]["action_id"] for row in timeline["actions"]
                                  if row["action"]["coverage_id"] == coverage["coverage_id"]]
    rehash(plan, layout, timeline)
    with pytest.raises(ValueError, match="overlap|reserved|dependency"):
        consumer_clock(layout, timeline)


def test_resolved_policy_must_equal_the_plan_and_legacy_lists_are_unchanged():
    from test_v2_progressive_list import list_documents
    from test_v2_structured_list_policy import resolved_documents as list_resolved
    plan, layout, timeline = documents()
    timeline["actions"][-1]["action"]["progressive_parts_policy"]["phases"][0]["weight"] = 2
    with pytest.raises(ValueError, match="progressive parts.*authoritative plan"):
        contracts.validate_resolved_structure(contracts.VisualPlanV2.model_validate(plan),
            contracts.ExecutableLayoutV2.model_validate(layout), contracts.ResolvedVisualTimelineV2.model_validate(timeline), 10000)
    raw, legacy = list_documents()
    assert contracts.ResolvedVisualTimelineV2.model_validate(legacy).model_dump(mode="json") == legacy
    _, replay, _ = consumer_clock(raw, legacy)
    assert replay.at(4900).object("object-evidence").visible
    _, raw, structured = list_resolved()
    heading = next(obj for obj in raw["objects"] if obj["object_type"] == "list")
    heading.update(initial_state="visible", visible=True)
    next(obj for obj in structured["initial_object_states"] if obj["object_id"] == heading["object_id"]).update(state="visible", visible=True)
    structured["layout_sha256"] = digest(raw)
    assert consumer_clock(raw, structured)[1].at(4900).object("list-item-c").visible


@pytest.mark.parametrize("fault", ["subclass", "unknown_field"])
def test_private_replay_cannot_discard_unknown_policy_authority(fault):
    from atme.render.v2_timeline_replay import replay_chronology
    _, layout, timeline = documents()
    context, _, _ = consumer_clock(layout, timeline)
    policy = context.timeline.actions[-1].action.progressive_parts_policy
    if fault == "subclass":
        class UnknownPolicy(contracts.ProgressivePartsPolicy):
            pass
        context.timeline.actions[-1].action.progressive_parts_policy = UnknownPolicy.model_validate(policy.model_dump())
    else:
        policy.__dict__["unowned"] = True
    with pytest.raises(ValueError, match="unknown|stored"):
        replay_chronology(context.objects, context.hierarchy, {row.object_id: row for row in context.frames},
            {key: row.state_version for key, row in context.initial.items()}, tuple(context.timeline.actions),
            (("board-main", 0, 10000),), 10000)


def append_object(layout, timeline, obj):
    layout["objects"].append(obj)
    layout["boards"][0]["object_ids"].append(obj["object_id"])
    layout["boards"][0]["density_limit"] = len(layout["objects"])
    timeline["initial_object_states"].append({"object_id": obj["object_id"], "state": obj["initial_state"],
        "visible": obj["visible"], "state_version": 1})
    timeline["layout_sha256"] = digest(layout)


@pytest.mark.parametrize("external", [False, True])
def test_whole_group_authenticates_internal_pointer_or_visible_external_endpoint(external):
    from test_v2_pointer_contract import pointer_payload
    _, layout, timeline = documents(grouped=True)
    pointer = pointer_payload()
    pointer.update(object_id="part-pointer", parent_id="list-item-c", z_index=2,
                   beat_id="beat-002", coverage_ids=["coverage-3"], destination_object_id="object-system" if external else "part-text",
                   destination_anchor_id="center" if external else "item-center")
    next(obj for obj in layout["objects"] if obj["object_id"] == "list-item-c")["child_ids"].append("part-pointer")
    policy = timeline["actions"][-1]["action"]["progressive_parts_policy"]
    policy["expected_closure_state_versions"]["part-pointer"] = 1
    if external:
        policy["expected_read_state_versions"]["object-system"] = 2
    append_object(layout, timeline, pointer)
    _, replay, _ = consumer_clock(layout, timeline)
    assert not replay.at(4899).object("part-pointer").visible
    assert replay.at(4900).object("part-pointer").visible
    assert dict(replay.at(4900).state_versions)["part-pointer"] == 2


def test_reference_into_a_different_hidden_part_cannot_be_borrowed_as_internal_authority():
    from atme.render.v2_hierarchy import HierarchySnapshot
    from atme.render.v2_progressive_parts import progressive_parts_inventory
    from test_v2_pointer_contract import pointer_payload
    _, layout, timeline = documents(grouped=True)
    pointer = pointer_payload()
    pointer.update(object_id="part-pointer", parent_id="list-item-c", z_index=2,
                   destination_object_id="list-item-b", destination_anchor_id="item-center")
    next(obj for obj in layout["objects"] if obj["object_id"] == "list-item-c")["child_ids"].append("part-pointer")
    policy = timeline["actions"][-1]["action"]["progressive_parts_policy"]
    policy["expected_closure_state_versions"]["part-pointer"] = 1
    append_object(layout, timeline, pointer)
    parsed = contracts.ExecutableLayoutV2.model_validate(layout)
    objects = {obj.object_id: obj for obj in parsed.objects}
    action = contracts.TargetAction.model_validate(timeline["actions"][-1]["action"])
    with pytest.raises(ValueError, match="different undisclosed part"):
        progressive_parts_inventory(action, objects, HierarchySnapshot.from_objects(objects))


@pytest.mark.parametrize("fault", [None, "missing_source", "hidden_source", "stale_source"])
def test_external_mask_ancestor_and_source_remain_authenticated_reads(fault):
    from test_v2_mask_contract import MASK_FIELDS
    _, layout, timeline = documents(grouped=True)
    owner = next(obj for obj in layout["objects"] if obj["object_id"] == "list-group")
    mask = deepcopy(owner)
    mask.update(object_id="aperture", object_type="mask", child_ids=["list-group"], **MASK_FIELDS)
    owner["parent_id"] = "aperture"
    source = deepcopy(next(obj for obj in layout["objects"] if obj["object_id"] == "list-item-a"))
    source.update(object_id="mask-source", parent_id=None, anchors=[], visible=True, initial_state="visible")
    source["style"] = {"stroke": None, "fill": None, "text": None, "effect": None}
    append_object(layout, timeline, mask)
    append_object(layout, timeline, source)
    policy = timeline["actions"][-1]["action"]["progressive_parts_policy"]
    policy["expected_read_state_versions"].update(aperture=1, **{"mask-source": 1})
    if fault == "missing_source":
        policy["expected_read_state_versions"].pop("mask-source")
    elif fault == "stale_source":
        policy["expected_read_state_versions"]["mask-source"] = 2
    elif fault == "hidden_source":
        source.update(visible=False, initial_state="hidden")
        next(row for row in timeline["initial_object_states"] if row["object_id"] == "mask-source").update(state="hidden", visible=False)
    timeline["layout_sha256"] = digest(layout)
    if fault:
        with pytest.raises(ValueError):
            consumer_clock(layout, timeline)
    else:
        _, replay, _ = consumer_clock(layout, timeline)
        assert replay.at(4900).object("part-text").visible
        assert dict(replay.at(4900).state_versions)["mask-source"] == 1
        assert dict(replay.at(4900).state_versions)["aperture"] == 1


@pytest.mark.parametrize("stale", [False, True])
def test_prior_group_history_binds_actual_current_closure_and_versions(stale):
    from test_v2_structured_list_replay import prior_group_documents
    layout, timeline = prior_group_documents()
    action = next(row["action"] for row in timeline["actions"] if row["action"]["verb"] == "progressive_reveal")
    old = action.pop("structured_list_policy")
    action["progressive_parts_policy"] = {"version": "1.0.0", "container_group_id": old["container_group_id"],
        "part_root_ids": old["item_object_ids"], "phases": old["phases"],
        "expected_closure_state_versions": old["expected_item_state_versions"],
        "expected_read_state_versions": {old["container_group_id"]: 2}}
    if stale:
        action["progressive_parts_policy"]["expected_closure_state_versions"]["list-item-a"] = 1
        with pytest.raises(ValueError, match="stale.*version"):
            consumer_clock(layout, timeline)
    else:
        _, replay, _ = consumer_clock(layout, timeline)
        assert replay.at(4000).hierarchy.ancestors("list-item-a") == ("list-group",)
        assert dict(replay.at(4000).state_versions)["list-item-a"] == 2
        assert dict(replay.at(4900).state_versions)["list-item-a"] == 3


def test_distributable_schemas_and_generated_outputs_are_exact():
    from conftest import load_schema
    from jsonschema import Draft202012Validator
    for model, name in ((contracts.VisualPlanV2, "visual-plan-v2"),
                        (contracts.ResolvedVisualTimelineV2, "resolved-visual-timeline-v2")):
        generated = model.model_json_schema(mode="validation")
        generated["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        generated["$id"] = f"https://atme.local/schemas/v2/{name}.schema.json"
        assert generated == load_schema(name)
    plan, _, timeline = documents(grouped=True)
    Draft202012Validator(load_schema("visual-plan-v2")).validate(plan)
    Draft202012Validator(load_schema("resolved-visual-timeline-v2")).validate(timeline)

@pytest.mark.parametrize("role", ["write_descendant", "read_reference"])
def test_existing_split_reservation_sees_complete_progressive_footprint(role):
    from atme.render.v2_split import capture_split, validate_split_reservations
    from test_v2_split_capture import geometry_boundary
    layout, before, split = geometry_boundary()
    captured = capture_split(split, layout, before, {})
    raw = documents()[2]["actions"][-1]
    action = raw["action"]
    policy = action["progressive_parts_policy"]
    action["target_ids"] = policy["part_root_ids"] = ["outside-part"]
    policy["phases"] = [{"object_id": "outside-part", "weight": 1}]
    policy["container_group_id"] = "outside-owner"
    policy["expected_closure_state_versions"] = {"outside-part": 1}
    policy["expected_read_state_versions"] = {"outside-owner": 1}
    policy["expected_closure_state_versions" if role == "write_descendant" else "expected_read_state_versions"]["source"] = 1
    raw.update(start_ms=split.start_ms+1, end_ms=split.end_ms-1)
    peer = contracts.ResolvedAction.model_validate(raw)
    with pytest.raises(ValueError, match="Split reservation"):
        validate_split_reservations(captured, (peer,))


def test_existing_group_operation_cannot_edit_progressive_closure_in_outer_interval():
    from test_v2_structured_list_replay import prior_group_documents
    layout, timeline = prior_group_documents()
    group = next(row for row in timeline["actions"] if row["action"]["verb"] == "ungroup")
    group.update(start_ms=4100, end_ms=4200)
    action = next(row["action"] for row in timeline["actions"] if row["action"]["verb"] == "progressive_reveal")
    old = action.pop("structured_list_policy")
    action["progressive_parts_policy"] = {"version": "1.0.0", "container_group_id": "list-group",
        "part_root_ids": old["item_object_ids"], "phases": old["phases"],
        "expected_closure_state_versions": {key: 1 for key in old["item_object_ids"]},
        "expected_read_state_versions": {"list-group": 1, "outer-group": 1}}
    timeline["actions"].sort(key=lambda row: row["start_ms"])
    with pytest.raises(ValueError, match="hierarchy.*overlap|reserved"):
        consumer_clock(layout, timeline)


def test_peer_pointer_cannot_read_an_undisclosed_descendant_during_outer_interval():
    from test_v2_pointer_contract import pointer_payload
    _, layout, timeline = documents(grouped=True)
    pointer = pointer_payload()
    pointer.update(object_id="peer-pointer", parent_id=None, destination_object_id="part-text",
                   destination_anchor_id="item-center", beat_id="beat-002", coverage_ids=["coverage-3"])
    append_object(layout, timeline, pointer)
    row = deepcopy(timeline["actions"][-1])
    row["action"].pop("progressive_parts_policy")
    row["action"].update(action_id="peer-reveal", verb="reveal", target_ids=["peer-pointer"])
    row.update(start_ms=4100, end_ms=4200)
    timeline["actions"].append(row)
    timeline["actions"].sort(key=lambda item: item["start_ms"])
    timeline["coverage"][2]["action_ids"].append("peer-reveal")
    with pytest.raises(ValueError, match="progressive parts.*reserved"):
        consumer_clock(layout, timeline)

@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("grouped", [False, True])
def test_pending_native_fixture_and_ordinary_comparison_are_valid_without_raster(portrait, grouped):
    from test_v2_progressive_parts_native import (
        native_documents,
        ordinary_completed_parts,
    )
    layout, timeline = native_documents(portrait, grouped)
    consumer_clock(layout, timeline)
    for at_ms in (4225, 4675, 4900):
        raw, ordinary = ordinary_completed_parts(layout, timeline, at_ms)
        consumer_clock(raw, ordinary)

@pytest.mark.parametrize("kind", ["clip", "mask"])
def test_nested_clip_is_supported_but_mask_cannot_write_its_dedicated_static_source(kind):
    from test_v2_mask_contract import MASK_FIELDS
    _, layout, timeline = documents(grouped=True)
    nested = next(obj for obj in layout["objects"] if obj["object_id"] == "part-nested")
    nested["object_type"] = kind
    if kind == "mask":
        nested.update(MASK_FIELDS)
        source = deepcopy(next(obj for obj in layout["objects"] if obj["object_id"] == "list-item-a"))
        source.update(object_id="mask-source", parent_id="list-item-c", visible=True, initial_state="visible", anchors=[],
                      style={"stroke": None, "fill": None, "text": None, "effect": None})
        next(obj for obj in layout["objects"] if obj["object_id"] == "list-item-c")["child_ids"].append("mask-source")
        append_object(layout, timeline, source)
        timeline["actions"][-1]["action"]["progressive_parts_policy"]["expected_closure_state_versions"]["mask-source"] = 1
    timeline["layout_sha256"] = digest(layout)
    if kind == "mask":
        contracts.ExecutableLayoutV2.model_validate(layout)
        with pytest.raises(ValueError, match="precondition failed for mask-source"):
            consumer_clock(layout, timeline)
        return
    _, replay, _ = consumer_clock(layout, timeline)
    assert not replay.at(4899).object("part-nested").visible
    assert replay.at(4900).object("part-nested").visible
    assert replay.at(4900).object("part-text").visible
