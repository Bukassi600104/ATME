"""Bound immutable initial content is distinct from live Count/Morph channels."""
import json
import xml.etree.ElementTree as ET
from copy import deepcopy

import pytest
from atme.render.v2_split_identity import split_content_receipts
from atme.render.v2_svg import compose_png_frame, compose_svg_frame
from atme.store import contracts_v2 as contracts
from test_v2_composition_attachment import composition_project_documents
from test_v2_composition_contract import composition_definition
from test_v2_count_contract import count_action
from test_v2_group_annotation import consumer_clock
from test_v2_morph_action import morph_documents
from test_v2_timeline_replay import resolved
from v2_fixtures import digest, resolved_timeline_v2


def member_action_documents(family, *, portrait=False):
    definition = composition_definition()
    definition["parameters"] = []
    root, mark, label = definition["objects"]
    root["geometry"]["corner_radius"] = None
    root["transform"]["position"] = {"x": -20.0 if portrait else 100.0, "y": 150.0 if portrait else 0.0}
    if family == "count":
        label["text"] = "0 widgets"
    else:
        mark["style"]["fill"] = "surface.accent"
        result = deepcopy(mark)
        result.update(object_id="result", object_type="ellipse",
                      geometry={"bounds": {"x": 340.0, "y": 190.0, "width": 240.0, "height": 220.0},
                                "points": [], "corner_radius": None})
        root["child_ids"].append("result")
        definition["objects"].append(result)
    plan, layout = composition_project_documents(definition=definition)
    if family == "count":
        action = count_action()
        action.update(action_id="count-member", target_ids=[layout["objects"][2]["object_id"]],
                      source_instruction_id="instruction-2", coverage_id="coverage-2",
                      fallback={"fallback_id": "fallback-2", "on_failure": "block"})
        action["count_policy"]["text_object_id"] = layout["objects"][2]["object_id"]
        coverage = 1
    else:
        action = deepcopy(morph_documents()[1]["actions"][-1]["action"])
        action.update(action_id="morph-member", from_object_id=layout["objects"][1]["object_id"],
                      to_object_id=layout["objects"][3]["object_id"], source_instruction_id="instruction-1",
                      coverage_id="coverage-1", fallback={"fallback_id": "fallback-1", "on_failure": "block"})
        coverage = 0
    row = resolved(action, 4000, 5000).model_dump(mode="json")
    plan["actions"].append(deepcopy(row["action"]))
    plan["beats"][0]["action_ids"].append(row["action"]["action_id"])
    plan["coverage"][coverage]["action_ids"].append(row["action"]["action_id"])
    profile = ({"profile_id": "SHORT_FORM_9_16", "width": 720, "height": 1280, "fps": 30}
               if portrait else {"profile_id": "LONG_FORM_16_9", "width": 1280, "height": 720, "fps": 30})
    plan["output_profile"] = deepcopy(profile)
    layout.update(output_profile=deepcopy(profile), plan_sha256=digest(plan))
    layout["canvas"].update(width=profile["width"], height=profile["height"])
    timeline = resolved_timeline_v2(plan, layout)
    timeline["actions"] = timeline["actions"][:2] + [row]
    timeline.update(output_profile=deepcopy(profile), resolved_assets=[], beat_anchors=timeline["beat_anchors"][:1])
    timeline["initial_object_states"] = [{"object_id": obj["object_id"], "state": obj["initial_state"],
        "visible": obj["visible"], "state_version": 1} for obj in layout["objects"]]
    contracts.validate_plan_layout(plan, layout)
    contracts.validate_resolved_structure(contracts.VisualPlanV2.model_validate(plan),
        contracts.ExecutableLayoutV2.model_validate(layout), contracts.ResolvedVisualTimelineV2.model_validate(timeline),
        timeline["duration_ms"])
    return plan, layout, timeline


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("family", ["count", "morph"])
def test_expanded_member_changes_current_content_versions_and_native_pixels_not_initial_binding(family, portrait):
    plan, layout, timeline = member_action_documents(family, portrait=portrait)
    original = deepcopy((plan, layout, timeline))
    context, replay, _camera = consumer_clock(layout, timeline)
    owner = layout["objects"][0]
    target = layout["objects"][2 if family == "count" else 1]["object_id"]
    samples = {at: replay.at(at) for at in (3999, 4500, 5000)}
    receipts = {at: {row.object_id: row for row in split_content_receipts(context.layout, sample, {})}
                for at, sample in samples.items()}
    for at in samples:
        payload = json.loads(receipts[at][owner["object_id"]].canonical_json)
        assert payload["composition_binding"] == owner["composition_binding"]
        assert payload["children"] == [{"object_id": key, "content_sha256": receipts[at][key].content_sha256}
                                       for key in sorted(owner["child_ids"])]
    assert receipts[3999][owner["object_id"]] != receipts[4500][owner["object_id"]]
    assert dict(samples[3999].state_versions)[target] == dict(samples[4500].state_versions)[target] == 2
    assert dict(samples[5000].state_versions)[target] == 3
    if family == "count":
        assert samples[4500].object(target).display_text == "5 widgets"
        assert samples[5000].object(target).display_text == "10 widgets"
        assert json.loads(receipts[4500][target].canonical_json)["count"]["display_text"] == "5 widgets"
        assert json.loads(receipts[5000][target].canonical_json)["count"]["display_text"] == "10 widgets"
        assert "5 widgets" in compose_svg_frame(layout, timeline, 4500).svg
    else:
        assert samples[4500].object(target).morph_geometry is not None
        assert "morph_geometry" in json.loads(receipts[4500][target].canonical_json)
        assert not samples[5000].object(target).visible
        assert samples[5000].object(layout["objects"][3]["object_id"]).visible
        root = ET.fromstring(compose_svg_frame(layout, timeline, 4500).svg)
        assert sum(node.attrib.get("data-geometry-action") == "morph" for node in root.iter()) == 1
    frames = {at: compose_png_frame(layout, timeline, at).png for at in samples}
    assert len(set(frames.values())) == 3
    for at in (5000, 3999, 4500, 5000, 4500):
        assert compose_png_frame(layout, timeline, at).png == frames[at]
    assert (plan, layout, timeline) == original
