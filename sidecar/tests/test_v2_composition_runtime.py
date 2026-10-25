"""Real expanded members use the existing native clock and paint path."""
import socket
import xml.etree.ElementTree as ET
from copy import deepcopy
from io import BytesIO
from pathlib import Path

import pytest
from atme.render import v2_state
from atme.render.style_bundle import registry_endpoint_inputs_for_objects
from atme.render.v2_split_paint import verify_split_paint_inputs
from atme.render.v2_svg import (
    _compose_validated_svg_frame,
    _rasterize_svg_frame,
    compose_png_frame,
    compose_svg_frame,
)
from atme.store import contracts_v2 as contracts
from PIL import Image
from test_v2_composition_attachment import composition_project_documents
from test_v2_composition_contract import composition_definition
from v2_fixtures import digest, resolved_timeline_v2


def runtime_documents(*, portrait=False):
    definition = composition_definition()
    # The contract fixture inherited a rounded Mark's corner radius; a real
    # non-painting Group intentionally has no shape of its own.
    definition["objects"][0]["geometry"]["corner_radius"] = None
    # Explicit local placement for each authored profile, not an auto-layout.
    definition["objects"][0]["transform"]["position"] = {
        "x": -20.0 if portrait else 100.0, "y": 150.0 if portrait else 0.0}
    plan, layout = composition_project_documents(definition=definition)
    profile = ({"profile_id": "SHORT_FORM_9_16", "width": 720, "height": 1280, "fps": 30}
               if portrait else {"profile_id": "LONG_FORM_16_9", "width": 1280, "height": 720, "fps": 30})
    plan["output_profile"] = deepcopy(profile)
    layout.update(output_profile=deepcopy(profile), plan_sha256=digest(plan))
    layout["canvas"].update(width=profile["width"], height=profile["height"])
    timeline = resolved_timeline_v2(plan, layout)
    timeline.update(output_profile=deepcopy(profile), resolved_assets=[], beat_anchors=timeline["beat_anchors"][:1])
    timeline["initial_object_states"] = [{"object_id": obj["object_id"], "state": obj["initial_state"],
        "state_version": 1, "visible": obj["visible"]} for obj in layout["objects"]]
    contracts.validate_plan_layout(plan, layout)
    contracts.validate_resolved_structure(contracts.VisualPlanV2.model_validate(plan),
        contracts.ExecutableLayoutV2.model_validate(layout), contracts.ResolvedVisualTimelineV2.model_validate(timeline),
        timeline["duration_ms"])
    return layout, timeline


@pytest.mark.parametrize("portrait", [False, True])
def test_bound_expansion_paints_real_members_once_with_construction_and_random_seek(portrait, tmp_path):
    layout, timeline = runtime_documents(portrait=portrait)
    original = deepcopy((layout, timeline))
    times = (0, 450, 900, 2450, 2900)
    frames = {at: compose_png_frame(layout, timeline, at).png for at in times}
    assert len(set(frames.values())) == len(times)
    _owner, mark, label = layout["objects"]
    first = v2_state.evaluate_frame(layout, timeline, 450)
    second = v2_state.evaluate_frame(layout, timeline, 2450)
    assert 0 < first.object(mark["object_id"]).reveal_fraction < 1
    assert not first.object(label["object_id"]).visible
    assert second.object(mark["object_id"]).reveal_fraction == 1
    assert 0 < second.object(label["object_id"]).reveal_fraction < 1
    for at in (2900, 450, 2450, 0, 900, 2900):
        assert compose_png_frame(layout, timeline, at).png == frames[at]
    svg = compose_svg_frame(layout, timeline, 2900).svg
    root = ET.fromstring(svg)
    ids = [node.attrib["data-object-id"] for node in root.iter() if "data-object-id" in node.attrib]
    assert ids == [obj["object_id"] for obj in layout["objects"]]
    assert "A new system" in svg
    image = Image.open(BytesIO(frames[2900])).convert("RGB")
    assert image.size == ((720, 1280) if portrait else (1280, 720))
    # Independent literal pixel locations: native rectangle translated only by
    # the explicitly authored root; paper remains outside the compact model.
    assert image.getpixel((280, 450) if portrait else (400, 300)) == (220, 230, 255)
    assert image.getpixel((20, 20)) == (250, 248, 241)
    (tmp_path / "expanded-native.png").write_bytes(frames[2900])
    assert (layout, timeline) == original


@pytest.mark.parametrize("portrait", [False, True])
def test_binding_metadata_never_substitutes_for_native_pixels_or_frozen_offline_paint(portrait, monkeypatch):
    layout, timeline = runtime_documents(portrait=portrait)
    plain, plain_clock = deepcopy(layout), deepcopy(timeline)
    plain["objects"][0].pop("composition_binding")
    plain_clock["layout_sha256"] = digest(plain)
    expected = {at: compose_png_frame(layout, timeline, at).png for at in (450, 2450, 2900)}
    assert all(compose_png_frame(plain, plain_clock, at).png == raw for at, raw in expected.items())
    typed = contracts.ExecutableLayoutV2.model_validate(layout)
    clock = contracts.ResolvedVisualTimelineV2.model_validate(timeline)
    inputs = verify_split_paint_inputs(typed, {})
    registry = registry_endpoint_inputs_for_objects({obj.object_id: obj for obj in typed.objects},
        frozen_files={name: raw for name, _, raw in inputs.bundle_bytes})

    def forbidden(*args, **kwargs):
        raise AssertionError("frozen composition paint reopened a file or used the network")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    path_open = Path.open

    def write_only(path, mode="r", *args, **kwargs):
        if "r" in mode or "+" in mode or not any(flag in mode for flag in ("w", "a", "x")):
            forbidden()
        return path_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", write_only)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    for at in (2900, 450, 2450, 2900):
        sample = v2_state._evaluate_frame_with_registry_inputs(layout, timeline, at, registry)
        svg = _compose_validated_svg_frame(typed, clock, sample, {}, split_inputs=inputs)
        assert _rasterize_svg_frame(typed, svg, split_inputs=inputs).png == expected[at]
