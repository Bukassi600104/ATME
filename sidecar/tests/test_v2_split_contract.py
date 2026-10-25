"""Split owns its discriminator and clock without enabling unproved rendering."""

import importlib
from copy import deepcopy

import pytest
from atme.store import contracts_v2 as contracts
from conftest import load_schema
from jsonschema import Draft202012Validator
from pydantic import TypeAdapter, ValidationError
from v2_fixtures import digest
from v2_split_fixtures import split_action, split_documents


def split_type():
    assert hasattr(contracts, "SplitAction"), "dedicated SplitAction contract is missing"
    return contracts.SplitAction


def phase_type():
    assert hasattr(contracts, "SplitPhase"), "strict Split phase clock contract is missing"
    return contracts.SplitPhase


@pytest.mark.parametrize("closure", ["results", "owned_descendant", "read_dependency"])
def test_split_references_include_results_and_dependencies(closure):
    raw = split_action()
    basis = raw["split_policy"]["source_basis"]
    expected = {"source", "part-1", "part-2"}
    if closure != "results":
        row = deepcopy(basis["placements"][-1])
        row["object_id"] = "child" if closure == "owned_descendant" else "earlier"
        row["parent_id"] = "source" if closure == "owned_descendant" else None
        row["sibling_ordinal"] = 0 if closure == "owned_descendant" else 3
        basis["placements"].append(row)
        basis["placements"].sort(key=lambda item: item["object_id"])
        expected.add(row["object_id"])
        if closure == "owned_descendant":
            basis["source_closure"]["owned_ids"].append("child")
        else:
            basis["read_dependencies"] = [{"kind": "ancestor", "object_ids": ["earlier"]}]
        raw["split_policy"]["source_basis_sha256"] = digest(basis)
    action = contracts.SplitAction.model_validate(raw)
    assert action.target_ids == ["source"]
    assert expected <= set(contracts._action_object_references(action))


@pytest.mark.parametrize("stage", ["semantic", "paired_layout"])
def test_split_orphan_result_cannot_disappear_from_a_closed_inventory(stage):
    plan, layout, _timeline = split_documents()
    for document in (plan, layout):
        document["objects"] = [obj for obj in document["objects"] if obj["object_id"] != "part-1"]
        document["boards"][0]["object_ids"] = [key for key in document["boards"][0]["object_ids"]
                                                if key != "part-1"]
    plan["beats"][0]["object_ids"] = [key for key in plan["beats"][0]["object_ids"] if key != "part-1"]
    with pytest.raises(ValueError):
        if stage == "semantic":
            contracts.VisualPlanV2.model_validate(plan)
        else:
            contracts.validate_plan_layout(plan, layout)


@pytest.mark.parametrize("mutation", [None, "root_board", "root_beat", "root_coverage", "missing_dependency"])
def test_split_static_reference_binding_owns_roots_but_observes_dependencies(mutation):
    plan, _layout, _timeline = split_documents()
    objects = {obj.object_id: obj for obj in contracts.VisualPlanV2.model_validate(plan).objects}
    boards = {board.board_id: board for board in contracts.VisualPlanV2.model_validate(plan).boards}
    action = contracts.SplitAction.model_validate(plan["actions"][0])
    if mutation == "root_board":
        objects["part-1"] = objects["part-1"].model_copy(update={"board_id": "foreign"})
    elif mutation == "root_beat":
        objects["part-1"] = objects["part-1"].model_copy(update={"beat_id": "earlier"})
    elif mutation == "root_coverage":
        objects["part-1"] = objects["part-1"].model_copy(update={"coverage_ids": ["other"]})
    elif mutation == "missing_dependency":
        raw = action.model_dump(mode="json")
        basis = raw["split_policy"]["source_basis"]
        row = deepcopy(basis["placements"][0])
        row["object_id"] = "missing"
        basis["placements"].append(row)
        basis["placements"].sort(key=lambda item: item["object_id"])
        basis["read_dependencies"] = [{"kind": "ancestor", "object_ids": ["missing"]}]
        raw["split_policy"]["source_basis_sha256"] = digest(basis)
        action = contracts.SplitAction.model_validate(raw)
    assert hasattr(contracts, "_validate_split_references"), "Split static reference boundary is missing"
    if mutation is None:
        contracts._validate_split_references(action, objects, boards)
    else:
        with pytest.raises(ValueError):
            contracts._validate_split_references(action, objects, boards)


def test_split_resolved_ledger_does_not_remove_read_dependencies():
    from test_v2_timeline_replay import resolved

    _plan, _layout, timeline = split_documents()
    split = timeline["actions"][0]
    basis = split["action"]["split_policy"]["source_basis"]
    dependency = deepcopy(basis["placements"][-1])
    dependency.update(object_id="earlier", sibling_ordinal=3)
    basis["placements"].insert(0, dependency)
    basis["read_dependencies"] = [{"kind": "ancestor", "object_ids": ["earlier"]}]
    split["action"]["split_policy"]["source_basis_sha256"] = digest(basis)
    timeline["initial_object_states"].append({"object_id": "earlier", "state": "visible",
        "state_version": 1, "visible": True})
    for index, target in enumerate(("part-1", "part-2", "earlier")):
        observer = split_action(policy=False)
        observer.pop("container_id")
        observer.update(verb="highlight", action_id=f"observe-{target}", target_ids=[target],
                        expected_state="visible", post_state="visible")
        timeline["actions"].append(resolved(observer, split["end_ms"] + index * 100,
            split["end_ms"] + (index + 1) * 100).model_dump(mode="json"))
        timeline["coverage"][0]["action_ids"].append(observer["action_id"])
    parsed = contracts.ResolvedVisualTimelineV2.model_validate(timeline)
    assert parsed.actions[-1].action.target_ids == ["earlier"]


def split_with_earlier_ancestor():
    from test_v2_timeline_replay import resolved

    plan, layout, timeline = split_documents()
    root_ids = [obj["object_id"] for obj in plan["objects"]]
    earlier = deepcopy(plan["objects"][0])
    earlier.update(object_id="earlier", object_type="group", beat_id="beat-earlier",
                   coverage_ids=["coverage-earlier"], initial_state="hidden")
    ancestor = deepcopy(layout["objects"][0])
    ancestor.pop("path_data")
    ancestor.update(earlier, child_ids=root_ids, visible=False)
    plan["objects"].append(earlier)
    layout["objects"].append(ancestor)
    for document in (plan, layout):
        document["boards"][0]["object_ids"] = [*root_ids, "earlier"]
    for obj in layout["objects"]:
        if obj["object_id"] in root_ids:
            obj["parent_id"] = "earlier"
    action = plan["actions"][0]
    basis = action["split_policy"]["source_basis"]
    for placement in basis["placements"]:
        placement["parent_id"] = "earlier"
    ancestor_placement = deepcopy(basis["placements"][-1])
    ancestor_placement.update(object_id="earlier", parent_id=None, sibling_ordinal=0, state_version=2)
    basis["placements"].insert(0, ancestor_placement)
    basis["read_dependencies"] = [{"kind": "ancestor", "object_ids": ["earlier"]}]
    action["split_policy"]["source_basis_sha256"] = digest(basis)
    prior = split_action(policy=False)
    prior.pop("container_id")
    prior.update(action_id="earlier-reveal", source_instruction_id="instruction-earlier", verb="reveal",
                 target_ids=["earlier"], expected_state="hidden", post_state="visible",
                 coverage_id="coverage-earlier", trigger={"kind": "absolute", "at_ms": 0})
    plan["actions"].insert(0, prior)
    coverage = {"coverage_id": "coverage-earlier", "instruction_id": "instruction-earlier",
                "status": "executed", "action_ids": ["earlier-reveal"], "fallback_id": None}
    plan["coverage"].append(coverage)
    plan["fallbacks"][0]["affected_ids"].append("instruction-earlier")
    beat = deepcopy(plan["beats"][0])
    beat.update(beat_id="beat-earlier", object_ids=["earlier"], action_ids=["earlier-reveal"],
                coverage_ids=["coverage-earlier"], rhetorical_role="example")
    beat["attention"]["primary_targets"] = ["earlier"]
    beat["camera_intent"]["target_ids"] = ["earlier"]
    plan["beats"].append(beat)
    layout["boards"] = deepcopy(plan["boards"])
    timeline["coverage"] = deepcopy(plan["coverage"])
    timeline["fallbacks"] = deepcopy(plan["fallbacks"])
    timeline["actions"] = [resolved(prior, 0, 100).model_dump(mode="json"),
                           resolved(action, 500, 1500).model_dump(mode="json")]
    timeline["initial_object_states"].append({"object_id": "earlier", "state": "hidden",
                                             "state_version": 1, "visible": False})
    timeline["beat_anchors"].append({"beat_id": "beat-earlier", "start_ms": 0})
    return plan, layout, timeline


def test_split_accepts_earlier_beat_read_dependency_without_mutation_coverage():
    plan, layout, _timeline = split_with_earlier_ancestor()
    contracts.VisualPlanV2.model_validate(plan)
    contracts.validate_plan_layout(plan, layout)
    parsed = contracts.VisualPlanV2.model_validate(plan)
    action = parsed.actions[-1]
    assert "earlier" in contracts._action_object_references(action)
    assert "earlier" not in contracts._action_mutation_references(action)
    assert next(obj for obj in parsed.objects if obj.object_id == "earlier").coverage_ids == ["coverage-earlier"]


@pytest.mark.parametrize("mutation", ["wrong_owner", "duplicated_owner"])
def test_split_requires_exact_unique_owning_beat(mutation):
    plan, _layout, _timeline = split_with_earlier_ancestor()
    if mutation == "duplicated_owner":
        plan["beats"][-1]["action_ids"].append("split-1")
    else:
        plan["beats"][0]["action_ids"].remove("split-1")
        plan["beats"][-1]["action_ids"].append("split-1")
        # Coverage has the same exclusive owner as the action; roots retain theirs.
        plan["beats"][0]["coverage_ids"] = ["coverage-earlier"]
        plan["beats"][-1]["coverage_ids"] = ["coverage-1"]
    with pytest.raises(ValueError):
        contracts.VisualPlanV2.model_validate(plan)


def test_new_resolved_split_requires_completion_receipt_before_history_execution():
    plan, layout, timeline = split_documents()
    with pytest.raises(ValueError, match="completion receipt"):
        contracts.validate_resolved_structure(contracts.VisualPlanV2.model_validate(plan),
            contracts.ExecutableLayoutV2.model_validate(layout),
            contracts.ResolvedVisualTimelineV2.model_validate(timeline), timeline["duration_ms"])


@pytest.mark.parametrize("target", ["source", "part-1"])
def test_split_resolved_source_and_hidden_result_preconditions_are_distinct(target):
    _plan, _layout, timeline = split_documents()
    row = next(item for item in timeline["initial_object_states"] if item["object_id"] == target)
    row["state"] = "hidden" if target == "source" else "visible"
    with pytest.raises(ValueError):
        contracts.ResolvedVisualTimelineV2.model_validate(timeline)


def test_split_foreign_read_dependency_rejects_without_becoming_a_mutation_target():
    plan, _layout, _timeline = split_with_earlier_ancestor()
    parsed = contracts.VisualPlanV2.model_validate(plan)
    objects = {obj.object_id: obj for obj in parsed.objects}
    objects["earlier"] = objects["earlier"].model_copy(update={"board_id": "foreign"})
    action = parsed.actions[-1]
    assert "earlier" not in contracts._action_mutation_references(action)
    with pytest.raises(ValueError):
        contracts._validate_split_references(action, objects, {board.board_id: board for board in parsed.boards})


def test_split_owned_descendants_keep_their_declared_beat_and_coverage():
    plan, layout, _timeline = split_with_earlier_ancestor()
    child = deepcopy(next(obj for obj in plan["objects"] if obj["object_id"] == "source"))
    child.update(object_id="child", beat_id="beat-earlier", coverage_ids=["coverage-earlier"])
    source = next(obj for obj in plan["objects"] if obj["object_id"] == "source")
    source["object_type"] = "group"
    plan["objects"].append(child)
    plan["beats"][-1]["object_ids"].append("child")
    plan["boards"][0]["object_ids"].append("child")
    source_layout = next(obj for obj in layout["objects"] if obj["object_id"] == "source")
    child_layout = deepcopy(source_layout)
    child_layout.update(child, parent_id="source")
    source_layout.pop("path_data")
    source_layout.update(object_type="group", child_ids=["child"])
    layout["objects"].append(child_layout)
    layout["boards"] = deepcopy(plan["boards"])
    basis = plan["actions"][-1]["split_policy"]["source_basis"]
    child_placement = deepcopy(next(row for row in basis["placements"] if row["object_id"] == "source"))
    child_placement.update(object_id="child", parent_id="source", sibling_ordinal=0)
    basis["placements"].append(child_placement)
    basis["placements"].sort(key=lambda row: row["object_id"])
    basis["source_closure"]["owned_ids"].append("child")
    plan["actions"][-1]["split_policy"]["source_basis_sha256"] = digest(basis)
    parsed = contracts.VisualPlanV2.model_validate(plan)
    contracts.validate_plan_layout(plan, layout)
    retained = next(obj for obj in parsed.objects if obj.object_id == "child")
    assert retained.beat_id == "beat-earlier" and retained.coverage_ids == ["coverage-earlier"]
    assert "child" in contracts._action_object_references(parsed.actions[-1])
    assert "child" not in contracts._action_mutation_references(parsed.actions[-1])


def split_with_completion_receipt():
    plan, layout, timeline = split_documents()
    policy = timeline["actions"][0]["action"]["split_policy"]
    basis = policy["source_basis"]
    placements = deepcopy(basis["placements"])
    for row in placements:
        source = row["object_id"] == "source"
        row.update(state="removed" if source else "visible", state_version=2,
                   local_visibility=not source, effective_visibility=not source,
                   reveal=0.0 if source else 1.0, local_opacity=0.0 if source else 1.0)
    receipt = {"source_basis_sha256": digest(basis), "policy_sha256": digest(policy),
               "placements": placements, "read_dependencies": [], "asset_pins": [],
               "style_sha256": basis["style_sha256"], "registry_sha256": basis["registry_sha256"]}
    receipt["completion_sha256"] = digest(receipt)
    timeline["actions"][0]["split_completion_receipt"] = receipt
    return plan, layout, timeline


@pytest.mark.parametrize("mutation", [None, "correspondence", "phase", "missing", "extra"])
def test_resolved_split_inventory_and_full_policy_are_bound_to_authoritative_plan(mutation):
    plan, layout, timeline = split_with_completion_receipt()
    item = timeline["actions"][0]
    if mutation in ("correspondence", "phase"):
        if mutation == "correspondence":
            item["action"]["split_policy"]["correspondences"][0]["statement"] = "Resolved-only assertion"
        else:
            item["action"]["split_policy"]["source_exit"]["start_tick"] = 3000
        receipt = item["split_completion_receipt"]
        receipt["policy_sha256"] = digest(item["action"]["split_policy"])
        receipt["completion_sha256"] = digest({key: value for key, value in receipt.items()
                                                if key != "completion_sha256"})
    elif mutation in ("missing", "extra"):
        observer = deepcopy(plan["actions"][0])
        observer.pop("split_policy")
        observer.pop("container_id")
        observer.update(action_id="observe", verb="highlight", expected_state="visible", post_state="visible")
        if mutation == "missing":
            item["action"] = observer
            item.pop("split_completion_receipt")
            timeline["coverage"][0]["action_ids"] = ["observe"]
        else:
            plan["actions"] = [observer]
            plan["beats"][0]["action_ids"] = ["observe"]
            plan["coverage"][0]["action_ids"] = ["observe"]
    args = (contracts.VisualPlanV2.model_validate(plan), contracts.ExecutableLayoutV2.model_validate(layout),
            contracts.ResolvedVisualTimelineV2.model_validate(timeline), timeline["duration_ms"])
    if mutation is None:
        contracts.validate_resolved_structure(*args)
    else:
        with pytest.raises(ValueError, match="authoritative plan"):
            contracts.validate_resolved_structure(*args)


@pytest.mark.parametrize("hierarchy", ["absent", None])
@pytest.mark.parametrize("policy", ["absent", None])
def test_dedicated_split_legacy_roundtrip(hierarchy, policy):
    raw = split_action(policy=False)
    if hierarchy != "absent":
        raw["hierarchy_policy"] = hierarchy
    if policy != "absent":
        raw["split_policy"] = policy
    expected = split_action(policy=False)
    parsed = TypeAdapter(contracts.CanonicalAction).validate_python(raw)
    assert isinstance(parsed, split_type())
    assert parsed.model_dump(mode="json") == expected
    assert digest(parsed.model_dump(mode="json")) == digest(expected)
    # Independently measured with GroupAction from the frozen fc480037 source.
    assert digest(parsed.model_dump(mode="json")) == (
        "0641f8ebbc70734af19f0d353fef461690c46eb29a6c8e7d16213702ce225bf1")
    from atme.render.v2_timeline_replay import supports_operator
    assert not supports_operator(parsed)


@pytest.mark.parametrize("policy", [False, True])
def test_split_rejects_nonnull_hierarchy_even_without_execution_policy(policy):
    raw = split_action(policy=policy)
    raw["hierarchy_policy"] = {}
    with pytest.raises(ValidationError, match="hierarchy_policy"):
        split_type().model_validate(raw)


@pytest.mark.parametrize("bare", [False, True])
def test_split_public_evaluator_remains_unavailable(bare):
    from atme.render.v2_state import UnsupportedVisualAction, evaluate_frame

    _plan, layout, timeline = split_documents()
    if bare:
        timeline["actions"][0]["action"].pop("split_policy")
    with pytest.raises(UnsupportedVisualAction, match="split.*no frame implementation"):
        evaluate_frame(layout, timeline, 450)


@pytest.mark.parametrize("count", [2, 256])
def test_split_policy_limits_and_phase_clock(count):
    parsed = split_type().model_validate(split_action(count))
    assert len(parsed.split_policy.results) == count
    assert split_type().model_validate(parsed.model_dump(mode="json")) == parsed
    from atme.render.v2_timeline_replay import supports_operator
    assert not supports_operator(parsed)


@pytest.mark.parametrize("count", [1, 257])
def test_split_result_count_limits_reject(count):
    with pytest.raises(ValidationError):
        split_type().model_validate(split_action(count))


@pytest.mark.parametrize("change", [
    {"easing": "ease_in"}, {"easing": "step"}, {"post_state": "visible"},
    {"expected_state": None}, {"target_ids": ["other"]},
    {"target_ids": ["source", "part-1"]}, {"container_id": "container"},
    {"hierarchy_policy": {}}, {"unknown": True},
])
def test_split_rejects_ignored_or_ambiguous_outer_channels(change):
    raw = split_action()
    raw.update(change)
    with pytest.raises(ValidationError):
        split_type().model_validate(raw)


@pytest.mark.parametrize("change", [
    {"start_tick": True}, {"end_tick": False}, {"start_tick": -1},
    {"end_tick": 10001}, {"start_tick": 8000, "end_tick": 8000},
    {"start_tick": 8001, "end_tick": 8000}, {"easing": "step"},
    {"start_tick": 1.2}, {"end_tick": float("inf")}, {"invented": 1},
])
def test_phase_rejects_noninteger_nonfinite_unknown_and_noncontinuous_fields(change):
    raw = {"start_tick": 0, "end_tick": 10000, "easing": "linear", **change}
    with pytest.raises(ValidationError):
        phase_type().model_validate(raw)


def test_clock_uses_specific_phase_and_floor_not_outer_action_fraction():
    cls = phase_type()
    clock = importlib.import_module("atme.render.v2_split_clock")
    phase = cls(start_tick=1000, end_tick=9000, easing="linear")
    assert clock.resolve_split_phase(100, 111, phase) == (101, 109)
    early = cls(start_tick=2000, end_tick=6000, easing="linear")
    late = cls(start_tick=7000, end_tick=9000, easing="linear")
    assert [clock.split_phase_progress(100, 200, t, early)
            for t in (119, 120, 140, 160, 161)] == [0, 0, .5, 1, 1]
    assert [clock.split_phase_progress(100, 200, t, late)
            for t in (169, 170, 180, 190, 191)] == [0, 0, .5, 1, 1]
    with pytest.raises(ValueError, match="collapse"):
        clock.resolve_split_phase(100, 101, cls(start_tick=1, end_tick=2, easing="linear"))


@pytest.mark.parametrize("easing,want", [
    ("linear", .25), ("ease_in", .0625), ("ease_out", .4375), ("ease_in_out", .15625),
])
def test_clock_phase_easing(easing, want):
    phase = phase_type()(start_tick=2000, end_tick=6000, easing=easing)
    clock = importlib.import_module("atme.render.v2_split_clock")
    assert clock.split_phase_progress(100, 200, 130, phase) == want


def test_policy_rejects_wrong_correspondence_order_and_overlapping_owned_closures():
    cls = split_type()
    raw = split_action()
    raw["split_policy"]["correspondences"].reverse()
    with pytest.raises(ValidationError):
        cls.model_validate(raw)
    raw = split_action()
    basis = raw["split_policy"]["source_basis"]
    basis["result_closures"][0]["owned_ids"].append("source")
    raw["split_policy"]["source_basis_sha256"] = digest(basis)
    with pytest.raises(ValidationError):
        cls.model_validate(raw)
    raw = split_action()
    raw["split_policy"]["source_basis"]["placements"][0]["world_matrix"][0] = float("nan")
    with pytest.raises(ValidationError):
        cls.model_validate(raw)


def test_basis_rejects_over_4096_bound_objects_and_nonfinite_pose():
    cls = split_type()
    raw = split_action()
    basis = raw["split_policy"]["source_basis"]
    for i in range(4094):
        row = deepcopy(basis["placements"][0])
        row["object_id"] = f"extra-{i}"
        basis["placements"].append(row)
    basis["placements"].sort(key=lambda row: row["object_id"])
    raw["split_policy"]["source_basis_sha256"] = digest(basis)
    with pytest.raises(ValidationError):
        cls.model_validate(raw)


@pytest.mark.parametrize("profile", ["LONG_FORM_16_9", "SHORT_FORM_9_16"])
@pytest.mark.parametrize("bare", [False, True])
def test_plan_and_resolved_generated_schema_roundtrip(profile, bare):
    plan, _layout, timeline = split_documents(profile)
    if bare:
        plan["actions"][0].pop("split_policy")
        timeline["actions"][0]["action"].pop("split_policy", None)
    for name, model, raw in [("visual-plan-v2", contracts.VisualPlanV2, plan),
                             ("resolved-visual-timeline-v2", contracts.ResolvedVisualTimelineV2, timeline)]:
        schema = load_schema(name)
        branch = schema["$defs"].get("SplitAction")
        assert branch is not None, "distributable schema must carry dedicated SplitAction"
        assert branch["properties"]["verb"]["const"] == "split"
        assert "split" not in schema["$defs"]["GroupAction"]["properties"]["verb"]["enum"]
        Draft202012Validator(schema).validate(raw)
        parsed = model.model_validate(raw)
        dumped = parsed.model_dump(mode="json")
        assert model.model_validate(dumped).model_dump(mode="json") == dumped


@pytest.mark.parametrize("invalid", ["enter_missing", "reveal_destination", "move_overlap",
                                     "move_jump", "wrong_final", "reverse_order", "blank_id",
                                     "region_outside", "wrong_content"])
def test_phase_channels_and_correspondence_are_authored(invalid):
    raw = split_action()
    policy = raw["split_policy"]
    result = policy["results"][0]
    construction = result["construction"]
    if invalid == "enter_missing":
        construction["mode"] = "enter"
    elif invalid == "reveal_destination":
        construction["enter_destination"] = deepcopy(result["destination"])
    elif invalid in {"move_overlap", "move_jump"}:
        construction.update(mode="enter", enter_destination=deepcopy(result["destination"]))
        result["movement"] = {"phase": {"start_tick": 6000, "end_tick": 10000, "easing": "linear"},
                              "from_transform": deepcopy(result["destination"]),
                              "destination": deepcopy(result["destination"])}
        if invalid == "move_overlap":
            result["movement"]["phase"]["start_tick"] = 5999
        else:
            result["movement"]["from_transform"]["position"]["x"] = 10.0
    elif invalid == "wrong_final":
        result["destination"] = deepcopy(result["destination"])
        result["destination"]["position"]["x"] = 10.0
    elif invalid == "reverse_order":
        construction["phase"]["start_tick"] = 1000
    elif invalid == "blank_id":
        policy["correspondences"][0]["correspondence_id"] = "  "
    elif invalid == "region_outside":
        policy["correspondences"][0]["source_region"] = {"x": 0, "y": 0, "width": 10, "height": 10}
    else:
        policy["correspondences"][0]["result_content_sha256"] = "d" * 64
    with pytest.raises(ValidationError):
        split_type().model_validate(raw)


def test_split_basis_preserves_positive_stored_state_version_contract():
    raw = split_action()
    basis = raw["split_policy"]["source_basis"]
    basis["placements"][0]["state_version"] = 0
    raw["split_policy"]["source_basis_sha256"] = digest(basis)
    with pytest.raises(ValidationError, match="state_version"):
        split_type().model_validate(raw)


@pytest.mark.parametrize("value", [0.0, -0.0, 0.000049, -0.000049, 0.00005,
                                  -0.00005, 1.23445, -1.23445, 12345.67895])
def test_split_pose_comparison_matches_existing_world_quantization(value):
    from atme.render.v2_world import _q

    pose = contracts.Transform.model_validate({"position": {"x": value, "y": value}})
    assert contracts._split_pose_key(pose)[:2] == (_q(value), _q(value))


@pytest.mark.parametrize("field", ["origin", "destination"])
@pytest.mark.parametrize("offset,accepted", [(0.000049, True), (0.00005, False),
                                             (-0.000049, True), (-0.00005, False)])
def test_split_endpoint_validation_uses_canonical_not_raw_pose_equality(field, offset, accepted):
    raw = split_action()
    result = raw["split_policy"]["results"][0]
    result["movement"] = {
        "phase": {"start_tick": 6000, "end_tick": 10000, "easing": "linear"},
        "from_transform": deepcopy(result["destination"]),
        "destination": deepcopy(result["destination"]),
    }
    pose = result["movement"]["from_transform"] if field == "origin" else result["destination"]
    pose["position"]["x"] = offset
    if accepted:
        split_type().model_validate(raw)
    else:
        with pytest.raises(ValidationError):
            split_type().model_validate(raw)


@pytest.mark.parametrize("document", ["plan", "resolved"])
@pytest.mark.parametrize("field", ["target_ids", "container_id"])
def test_legacy_split_preserves_unknown_reference_rejection(document, field):
    plan, _layout, timeline = split_documents()
    action = (plan["actions"][0] if document == "plan"
              else timeline["actions"][0]["action"])
    action.pop("split_policy")
    action[field] = ["does-not-exist"] if field == "target_ids" else "does-not-exist"
    model, raw = ((contracts.VisualPlanV2, plan) if document == "plan"
                  else (contracts.ResolvedVisualTimelineV2, timeline))
    message = "unknown" if document == "plan" else "without initial state"
    with pytest.raises(ValidationError, match=message):
        model.model_validate(raw)


def test_legacy_split_preserves_group_container_type_check():
    plan, _layout, _timeline = split_documents()
    action = plan["actions"][0]
    action.pop("split_policy")
    action["container_id"] = "part-1"
    with pytest.raises(ValidationError, match="same-board group container"):
        contracts.VisualPlanV2.model_validate(plan)


def test_legacy_split_preserves_resolved_state_precondition():
    _plan, _layout, timeline = split_documents()
    action = timeline["actions"][0]["action"]
    action.pop("split_policy")
    action["expected_state"] = "hidden"
    with pytest.raises(ValidationError, match="precondition failed"):
        contracts.ResolvedVisualTimelineV2.model_validate(timeline)


def test_split_document_fixtures_are_mutation_independent():
    plan, layout, timeline = split_documents()
    original_timeline = deepcopy(timeline)
    original_layout = deepcopy(layout)
    plan["actions"][0]["split_policy"]["results"][0]["destination"]["position"]["x"] = 12.0
    assert timeline == original_timeline
    assert layout == original_layout
    assert plan["actions"][0] is not timeline["actions"][0]["action"]
