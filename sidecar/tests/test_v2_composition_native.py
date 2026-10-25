"""One expanded pinned native leaf: current world, internal aperture, frozen paint."""
import io
import json
import socket
import xml.etree.ElementTree as ET
from copy import deepcopy
from pathlib import Path

import pytest
from atme.render import v2_state
from atme.render.style_bundle import registry_endpoint_inputs_for_objects
from atme.render.v2_registry import (
    UnsupportedRegistryPlacement,
    checked_registry_art,
    registry_relationship_anchor,
    validate_registry_world_binding,
)
from atme.render.v2_split_paint import verify_split_paint_inputs
from atme.render.v2_svg import (
    _compose_validated_svg_frame,
    _rasterize_svg_frame,
    compose_png_frame,
    compose_svg_frame,
)
from atme.store import contracts_v2 as contracts
from PIL import Image
from test_v2_composition_contract import composition_definition
from test_v2_composition_materializer import (
    instance_spec,
    layout_for_expansion,
    materializer,
)
from test_v2_registry_binding import registry_object
from test_v2_timeline_replay import resolved
from v2_fixtures import common_action, digest, resolved_timeline_v2


def native_documents(kind, *, portrait=False):
    definition = composition_definition()
    definition["parameters"] = []
    definition["template_coverage_ids"] = ["coverage-1"]
    root = definition["objects"][0]
    root.update(child_ids=["aperture"], coverage_ids=["coverage-1"])
    root["geometry"] = {"bounds": {"x": 0., "y": 0., "width": 600., "height": 600.},
                        "points": [], "corner_radius": None}
    root["transform"].update(position={"x": 70. if portrait else 100., "y": 300. if portrait else 100.},
                             origin={"x": 0., "y": 0.}, scale_x=1.2, scale_y=.8)
    art = registry_object()
    art.update(object_id="art", parent_id="aperture", board_id="template-board", beat_id="template-beat",
               asset_id=None, initial_state="hidden", visible=False, coverage_ids=["coverage-1"])
    aperture = deepcopy(root)
    aperture.update(object_id="aperture", object_type=kind, parent_id="root", child_ids=["art"])
    # Crop vertically so a partial left-to-right reveal still changes visible
    # ink; a narrow horizontal aperture would already be full at half reveal.
    aperture["geometry"]["bounds"].update(width=600., height=300.)
    aperture["transform"].update(position={"x": 17., "y": 9.}, scale_x=1.1, scale_y=.8)
    definition["objects"] = [root, art, aperture]
    if kind == "mask":
        aperture.update(mask_mode="alpha", mask_source_object_id="source", mask_coordinate_space="parent_local",
                         invert=False, feather_px=0)
        source = deepcopy(art)
        source.pop("registry_binding")
        source.pop("variant")
        source.update(object_id="source", object_type="rectangle", parent_id="root",
                      initial_state="visible", visible=True, anchors=[])
        source["style"] = {"stroke": None, "fill": None, "text": None, "effect": None}
        source["geometry"] = deepcopy(aperture["geometry"])
        root["child_ids"].append("source")
        definition["objects"].append(source)
    spec = instance_spec(definition)
    layout = layout_for_expansion(materializer().materialize_composition(spec))
    binding = materializer().build_composition_binding(spec, layout)
    ids = {row["local_object_id"]: row["object_id"] for row in spec["object_map"]}
    draw = {**common_action("action-1", "instruction-1"), "verb": "reveal",
            "target_ids": [ids["art"]], "annotation": None, "easing": "linear"}
    move = deepcopy(draw)
    move.pop("annotation")
    destination = deepcopy(layout["objects"][0]["transform"])
    destination["position"]["x"] += 20.
    destination["position"]["y"] += 10.
    move.update(action_id="native-root-move", verb="move", target_ids=[ids["root"]],
                expected_state="visible", post_state="visible", destination=destination, opacity=None,
                easing="linear")
    rows = [resolved(draw, 0, 900).model_dump(mode="json"),
            resolved(move, 4000, 5000).model_dump(mode="json")]
    layout["objects"][0]["composition_binding"] = deepcopy(binding)
    profile = ({"profile_id": "SHORT_FORM_9_16", "width": 720, "height": 1280, "fps": 30}
               if portrait else {"profile_id": "LONG_FORM_16_9", "width": 1280, "height": 720, "fps": 30})
    layout["output_profile"] = deepcopy(profile)
    layout["canvas"].update(width=profile["width"], height=profile["height"])
    # Existing P3-37 semantic Clip/Mask membership remains closed. This is
    # the real bound executable/native-consumer proof, not a fabricated plan
    # or a claim of normal project writes/public production admission.
    timeline = resolved_timeline_v2(layout=layout)
    timeline.update(output_profile=deepcopy(profile), resolved_assets=[], actions=rows,
                    beat_anchors=timeline["beat_anchors"][:1], coverage=timeline["coverage"][:1],
                    fallbacks=timeline["fallbacks"][:1])
    timeline["coverage"][0]["action_ids"] = [row["action"]["action_id"] for row in rows]
    timeline["initial_object_states"] = [{"object_id": obj["object_id"], "state": obj["initial_state"],
        "visible": obj["visible"], "state_version": 1} for obj in layout["objects"]]
    contracts.ExecutableLayoutV2.model_validate(layout)
    contracts.ResolvedVisualTimelineV2.model_validate(timeline)
    return layout, timeline, ids


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["clip", "mask"])
def test_expanded_native_current_world_internal_aperture_and_frozen_offline_pixels(kind, portrait, monkeypatch, tmp_path):
    layout, timeline, ids = native_documents(kind, portrait=portrait)
    original = deepcopy((layout, timeline))
    plain, plain_clock = deepcopy(layout), deepcopy(timeline)
    plain["objects"][0].pop("composition_binding")
    plain_clock["layout_sha256"] = digest(plain)
    wide, wide_clock = deepcopy(plain), deepcopy(plain_clock)
    wide["objects"][2]["geometry"]["bounds"].update(width=600., height=600.)
    if kind == "mask":
        wide["objects"][3]["geometry"]["bounds"].update(width=600., height=600.)
    wide_clock["layout_sha256"] = digest(wide)
    times = (450, 900, 4500, 5000)
    expected = {at: compose_png_frame(layout, timeline, at).png for at in times}
    assert len(set(expected.values())) == len(times)
    assert all(compose_png_frame(plain, plain_clock, at).png == expected[at] for at in times)
    partial = Image.open(io.BytesIO(expected[450])).convert("RGB")
    unclipped = Image.open(io.BytesIO(compose_png_frame(wide, wide_clock, 450).png)).convert("RGB")
    paper = (250, 248, 241)
    assert 0 < sum(pixel != paper for pixel in partial.get_flattened_data()) < sum(
        pixel != paper for pixel in unclipped.get_flattened_data())
    for actual, full in zip(partial.get_flattened_data(), unclipped.get_flattened_data(), strict=True):
        # Antialiased aperture edges may blend existing ink toward paper only.
        assert all(min(fg, bg)-1 <= value <= max(fg, bg)+1
                   for value, fg, bg in zip(actual, full, paper, strict=True))
    tree = ET.fromstring(compose_svg_frame(layout, timeline, 450).svg)
    assert sum(node.attrib.get("data-object-id") == ids["art"] for node in tree.iter()) == 1
    assert any(node.tag.endswith("clipPath" if kind == "clip" else "mask") for node in tree.iter())
    if kind == "mask":
        assert all(node.attrib.get("data-object-id") != ids["source"] for node in tree.iter())
        assert layout["objects"][2]["mask_source_object_id"] == ids["source"]
    assert layout["objects"][2]["child_ids"] == [ids["art"]]
    (tmp_path / "expanded-native-aperture.png").write_bytes(expected[450])
    typed = contracts.ExecutableLayoutV2.model_validate(layout)
    clock = contracts.ResolvedVisualTimelineV2.model_validate(timeline)
    inputs = verify_split_paint_inputs(typed, {})
    registry = registry_endpoint_inputs_for_objects({obj.object_id: obj for obj in typed.objects},
        frozen_files={name: raw for name, _, raw in inputs.bundle_bytes})
    assert registry is not None and len(registry.artworks) == 1
    asset, _ = checked_registry_art("person-collaborators", registry.registry_payload, registry.artworks[0][1])
    assert any(json.loads(row).get("object_id") == ids["art"] for row in inputs.paint_evidence)

    def forbidden(*args, **kwargs):
        raise AssertionError("frozen native composition reopened a file or used the network")

    path_open = Path.open

    def write_only(path, mode="r", *args, **kwargs):
        if "r" in mode or "+" in mode or not any(flag in mode for flag in ("w", "a", "x")):
            forbidden()
        return path_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(Path, "open", write_only)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    for at in (5000, 450, 4500, 900, 5000):
        sample = v2_state._evaluate_frame_with_registry_inputs(layout, timeline, at, registry)
        objects = {obj.object_id: obj for obj in typed.objects}
        transforms = {obj.object_id: obj.transform for obj in sample.objects}
        delta = 1. if at >= 5000 else .5 if at == 4500 else 0.
        # Literal fitted local anchor(190,345.6), then aperture(17,9;1.1,.8),
        # then the sampled nonuniform root(1.2,.8) and its actual Move offset.
        endpoint = (341.2 if portrait else 371.2) + 20*delta, (528.384 if portrait else 328.384) + 10*delta
        assert validate_registry_world_binding(objects[ids["art"]], asset, objects, transforms) == (
            ("actor-left", endpoint),)
        with pytest.raises(UnsupportedRegistryPlacement, match="aperture ancestry"):
            registry_relationship_anchor(objects[ids["art"]], "actor-left", objects, transforms, registry)
        svg = _compose_validated_svg_frame(typed, clock, sample, {}, split_inputs=inputs)
        assert _rasterize_svg_frame(typed, svg, split_inputs=inputs).png == expected[at]
    assert (layout, timeline) == original
