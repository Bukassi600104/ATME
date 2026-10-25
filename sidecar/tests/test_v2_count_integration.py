"""Count binds real glyph bounds, schemas and surrounding visible attention."""

from copy import deepcopy
from math import ceil

import pytest
from conftest import load_schema
from jsonschema import Draft202012Validator
from test_v2_annotation_action import append_target
from test_v2_annotation_contract import annotation_documents, leader_documents
from test_v2_count_action import count_documents
from test_v2_count_contract import count_action, count_policy
from test_v2_hierarchy_isolate import nested_isolate_documents
from v2_fixtures import digest

from atme.render.style_bundle import resolve_contract_bundle
from atme.render.v2_state import V2FrameError, evaluate_frame
from atme.render.v2_svg import _font, compose_svg_frame
from atme.store.contracts_v2 import TargetAction


def retime(row, start, end, action_id=None):
    if action_id:
        row["action"]["action_id"] = action_id
    row["action"]["trigger"] = {"kind": "absolute", "at_ms": start}
    row.update(start_ms=start, end_ms=end)
    row["resolved_trigger"].update(source=row["action"]["trigger"], alignment_anchor_ms=start,
                                     resolved_at_ms=start, matched_text=None, matched_occurrence=None)


def append_count(timeline, target, start, end):
    row = deepcopy(timeline["actions"][0])
    row["action"] = count_action(count_policy(text_object_id=target))
    row["action"]["target_ids"] = [target]
    retime(row, start, end, f"count-{target}")
    timeline["actions"].append(row)
    timeline["actions"].sort(key=lambda row: row["start_ms"])
    # Bind the new action to its actual coverage, not an inferred instruction.
    coverage = next(item for item in timeline["coverage"] if item["coverage_id"] == row["action"]["coverage_id"])
    coverage["action_ids"].append(row["action"]["action_id"])


def test_count_glyph_preflight_rejects_wider_real_intermediate_not_just_endpoints():
    policy = count_policy(start_value="1", end_value="3", start_text="1", end_text="3", step_count=2,
                          unit="", unit_placement="none", separator="")
    layout, timeline = count_documents(policy)
    target = layout["objects"][2]
    target["style"]["text"] = "text.heading"
    style, _, root = resolve_contract_bundle(layout["style_system_version"], layout["asset_registry_version"])
    role = style.typography.title
    pinned = next(item for item in style.fonts if item.id == role.font_id)
    scale = layout["output_profile"]["width"] / style.aspects["landscape-16:9"].width
    face = _font(str(root / pinned.file), max(1, ceil(role.size_px * scale)))
    endpoints = max(face.getlength("1"), face.getlength("3"))
    intermediate = face.getlength("2")
    assert intermediate > endpoints
    target["geometry"]["bounds"]["width"] = (endpoints + intermediate) / 2
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="authored width"):
        evaluate_frame(layout, timeline, 0)


def test_count_schema_and_model_agree_for_policy_and_reject_numeric_forms():
    raw = count_action()
    schema = load_schema("visual-plan-v2")
    action_schema = {"$defs": schema["$defs"], "$ref": "#/$defs/TargetAction"}
    validator = Draft202012Validator(action_schema)
    validator.validate(raw)
    assert TargetAction.model_validate(raw).count_policy.start_value == "0"
    bad = deepcopy(raw)
    bad["count_policy"]["start_value"] = "NaN"
    assert list(validator.iter_errors(bad))
    assert schema["$defs"]["CountPolicy"] == load_schema("resolved-visual-timeline-v2")["$defs"]["CountPolicy"]


@pytest.mark.parametrize("parent", ["object-group", "isolate-outer"])
@pytest.mark.parametrize("hidden", [False, True])
def test_count_rejects_unavailable_sampled_parent_without_dimming_or_inventing_start(parent, hidden):
    layout, timeline = nested_isolate_documents()
    target = next(obj for obj in layout["objects"] if obj["object_id"] == "object-label")
    target["text"] = "0 widgets"
    row = timeline["actions"][2]
    row["action"] = count_action(count_policy(text_object_id="object-label"))
    row["action"]["target_ids"] = ["object-label"]
    obj = next(obj for obj in layout["objects"] if obj["object_id"] == parent)
    if hidden:
        obj.update(visible=False, initial_state="hidden")
        next(item for item in timeline["initial_object_states"] if item["object_id"] == parent).update(
            visible=False, state="hidden")
    else:
        obj["opacity"] = 0
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="visible complete count"):
        evaluate_frame(layout, timeline, 0)


@pytest.mark.parametrize("start", [4900, 4800])
def test_count_then_isolate_keeps_exact_numeric_provenance_and_overlap_rejects(start):
    layout, timeline = count_documents()
    append_target(timeline, "object-evidence", "isolate", start, start + 500)
    if start < 4900:
        with pytest.raises(V2FrameError, match="overlaps"):
            evaluate_frame(layout, timeline, 0)
    else:
        before = evaluate_frame(layout, timeline, 4900).object("object-evidence")
        middle = evaluate_frame(layout, timeline, 5150).object("object-evidence")
        after = evaluate_frame(layout, timeline, 5400).object("object-evidence")
        assert before == middle == after
        assert after.display_text == "10 widgets" and after.count_value == (10, 1)
        assert evaluate_frame(layout, timeline, 5150).object("object-label").opacity < 1


@pytest.mark.parametrize("verb", ["highlight", "cross_out"])
def test_count_does_not_weaken_untouched_target_attention_rule(verb):
    layout, timeline = count_documents()
    append_target(timeline, "object-evidence", verb, 6000, 6500)
    if verb == "highlight":
        timeline["actions"][-1]["action"]["post_state"] = "highlighted"
    else:
        timeline["actions"][-1]["action"]["post_state"] = "crossed_out"
    with pytest.raises(V2FrameError, match="untouched visible target"):
        evaluate_frame(layout, timeline, 0)


@pytest.mark.parametrize("leader", [False, True])
def test_count_before_annotation_is_readable_but_retained_pointer_rejects_later_count(leader):
    _, layout, timeline = leader_documents() if leader else annotation_documents()
    target = next(obj for obj in layout["objects"] if obj["object_id"] == "object-system")
    target.pop("path_data", None)
    target.update(object_type="text", text="0 widgets", items=[],
                   style={"stroke": None, "fill": None, "text": "text.body", "effect": None})
    target["geometry"].update(points=[], corner_radius=None)
    append_count(timeline, "object-system", 3000, 4000)
    timeline["layout_sha256"] = digest(layout)
    assert evaluate_frame(layout, timeline, 7999).object("object-system").display_text == "10 widgets"
    assert "A stable boundary" in compose_svg_frame(layout, timeline, 7999).svg
    if leader:
        second = deepcopy(next(row for row in timeline["actions"] if row["action"]["verb"] == "count"))
        second["action"]["count_policy"] = count_policy(text_object_id="object-system", start_value="10",
            end_value="20", start_text="10 widgets", end_text="20 widgets")
        retime(second, 8000, 8500, "count-after-pointer")
        timeline["actions"].append(second)
        timeline["coverage"][2]["action_ids"].append("count-after-pointer")
        with pytest.raises(V2FrameError, match="completed explicit removal"):
            evaluate_frame(layout, timeline, 0)
