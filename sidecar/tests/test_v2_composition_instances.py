"""One immutable definition expands twice without aliases or shared action state."""
import xml.etree.ElementTree as ET
from copy import deepcopy
from io import BytesIO

import pytest
from atme.render.v2_state import evaluate_frame
from atme.render.v2_svg import compose_png_frame, compose_svg_frame
from atme.store import contracts_v2 as contracts
from PIL import Image
from test_v2_composition_attachment import composition_project_documents
from test_v2_composition_contract import composition_definition
from test_v2_composition_materializer import (
    instance_spec,
    layout_for_expansion,
    materializer,
)
from test_v2_timeline_replay import resolved
from v2_fixtures import digest, resolved_timeline_v2


def two_instance_documents(*, portrait=False):
    definition = composition_definition()
    definition["objects"][0]["geometry"]["corner_radius"] = None
    for obj in definition["objects"][1:]:
        obj.update(visible=False, initial_state="hidden")
    before = deepcopy(definition)
    specs, objects = [], []
    for index, root in enumerate(("intro:one", "second")):
        spec = instance_spec(definition, root=root)
        values = {row["parameter_id"]: row["value"] for row in spec["parameter_values"]}
        values["caption"]["value"] = "Beta system" if index else "Alpha system"
        values["width"]["value"] = (620.0 - 100.0 * index) if portrait else (400.0 - 40.0 * index)
        values["shown"]["value"] = False
        spec["overrides"].extend([
            {"target": {"object_id": "root", "field": "transform.position.x"},
             "value": {"value_type": "number", "value": -20.0 if portrait else 650.0 * index}},
            {"target": {"object_id": "root", "field": "transform.position.y"},
             "value": {"value_type": "number", "value": 150.0 + 500.0 * index if portrait else 0.0}},
        ])
        specs.append(spec)
        objects.extend(materializer().materialize_composition(spec))
    assert definition == before
    plan, _unused = composition_project_documents(attach=False, definition=definition)
    layout = layout_for_expansion(objects)
    for index, spec in enumerate(specs):
        layout["objects"][3 * index]["composition_binding"] = materializer().build_composition_binding(spec, layout)
    fields = set(contracts.SemanticStandardObjectSpec.model_fields)
    plan["objects"] = [{key: deepcopy(value) for key, value in obj.items() if key in fields} for obj in layout["objects"]]
    for index in (0, 3):
        plan["objects"][index]["object_type"] = "instance"
    plan["boards"] = deepcopy(layout["boards"])
    beat = plan["beats"][0]
    beat["object_ids"] = [obj["object_id"] for obj in layout["objects"]]
    for index in range(2):
        action = deepcopy(plan["actions"][index])
        action["action_id"] += "-second"
        action["target_ids"] = [layout["objects"][4 + index]["object_id"]]
        plan["actions"].append(action)
        beat["action_ids"].append(action["action_id"])
        plan["coverage"][index]["action_ids"].append(action["action_id"])
    profile = ({"profile_id": "SHORT_FORM_9_16", "width": 720, "height": 1280, "fps": 30}
               if portrait else {"profile_id": "LONG_FORM_16_9", "width": 1280, "height": 720, "fps": 30})
    plan["output_profile"] = deepcopy(profile)
    layout.update(output_profile=deepcopy(profile), plan_sha256=digest(plan))
    layout["canvas"].update(width=profile["width"], height=profile["height"])
    timeline = resolved_timeline_v2(plan, layout)
    timeline.update(output_profile=deepcopy(profile), resolved_assets=[], beat_anchors=timeline["beat_anchors"][:1])
    timeline["initial_object_states"] = [{"object_id": obj["object_id"], "state": obj["initial_state"],
        "visible": obj["visible"], "state_version": 1} for obj in layout["objects"]]
    contracts.validate_plan_layout(plan, layout)
    contracts.validate_resolved_structure(contracts.VisualPlanV2.model_validate(plan),
        contracts.ExecutableLayoutV2.model_validate(layout), contracts.ResolvedVisualTimelineV2.model_validate(timeline),
        timeline["duration_ms"])
    return plan, layout, timeline


@pytest.mark.parametrize("portrait", [False, True])
def test_shared_definition_has_disjoint_native_members_distinct_parameters_and_no_action_alias(portrait):
    _plan, layout, timeline = two_instance_documents(portrait=portrait)
    first, second = [layout["objects"][index]["composition_binding"] for index in (0, 3)]
    assert first["instance"]["definition_sha256"] == second["instance"]["definition_sha256"]
    assert {row["object_id"] for row in first["members"]}.isdisjoint(row["object_id"] for row in second["members"])
    assert first["instance"]["parameter_values"] != second["instance"]["parameter_values"]
    early = evaluate_frame(layout, timeline, 2900)
    assert early.object(layout["objects"][2]["object_id"]).visible
    assert not early.object(layout["objects"][5]["object_id"]).visible
    svg = compose_svg_frame(layout, timeline, 6900).svg
    ids = [node.attrib["data-object-id"] for node in ET.fromstring(svg).iter() if "data-object-id" in node.attrib]
    assert len(ids) == len(set(ids)) == 6
    assert "Alpha system" in svg and "Beta system" in svg
    expected = compose_png_frame(layout, timeline, 6900).png
    image = Image.open(BytesIO(expected)).convert("RGB")
    for index in (0, 1):
        width = (620.0 - 100.0 * index) if portrait else (400.0 - 40.0 * index)
        assert layout["objects"][3 * index + 1]["geometry"]["bounds"]["width"] == width
        # Literal native fill/paper on both sides of each independently sized
        # Mark, including the definition-local node override (+25 x).
        x = 85 if portrait else 105 + 650 * index
        y = 480 + 500 * index if portrait else 330
        assert image.getpixel((round(x + width - 8), y)) == (220, 230, 255)
        assert image.getpixel((round(x + width + 8), y)) == (250, 248, 241)
    reordered, clock = deepcopy(layout), deepcopy(timeline)
    reordered["objects"].reverse()
    clock["layout_sha256"] = digest(reordered)
    assert compose_png_frame(reordered, clock, 6900).png == expected


@pytest.mark.parametrize("portrait", [False, True])
def test_current_root_motion_preserves_immutable_binding_and_does_not_move_another_instance(portrait):
    _plan, layout, timeline = two_instance_documents(portrait=portrait)
    root, second = layout["objects"][0], layout["objects"][3]
    initial_binding = deepcopy(root["composition_binding"])
    action = deepcopy(timeline["actions"][0]["action"])
    action.pop("annotation")  # Construction-only field is not a Move contract field.
    destination = deepcopy(root["transform"])
    destination["position"]["x"] += 10.0
    destination["position"]["y"] += 10.0
    action.update(action_id="move-first-instance", verb="move", target_ids=[root["object_id"]],
                  expected_state="visible", post_state="visible", easing="linear", destination=destination, opacity=None)
    timeline["actions"].append(resolved(action, 9000, 9500).model_dump(mode="json"))
    timeline["coverage"][0]["action_ids"].append(action["action_id"])
    start, middle, end = [evaluate_frame(layout, timeline, at) for at in (8500, 9250, 9500)]
    assert middle.object(root["object_id"]).transform.position.x == pytest.approx(root["transform"]["position"]["x"] + 5)
    assert end.object(root["object_id"]).transform.position.y == pytest.approx(root["transform"]["position"]["y"] + 10)
    assert start.object(second["object_id"]) == middle.object(second["object_id"]) == end.object(second["object_id"])
    frames = {at: compose_png_frame(layout, timeline, at).png for at in (8500, 9250, 9500)}
    images = [Image.open(BytesIO(raw)).convert("RGB") for raw in frames.values()]
    assert len({image.tobytes() for image in images}) == 3
    second_box = (40, 800, 720, 1200) if portrait else (700, 100, 1200, 550)
    assert len({image.crop(second_box).tobytes() for image in images}) == 1
    assert root["composition_binding"] == initial_binding
    for at in (9500, 8500, 9250, 9500, 9250):
        assert compose_png_frame(layout, timeline, at).png == frames[at]
