"""Native shape/world oracle, then identical frozen offline shuffled seeks."""
import socket
from copy import deepcopy
from pathlib import Path

import pytest
from atme.render import v2_state
from atme.render.style_bundle import registry_endpoint_inputs_for_objects
from atme.render.v2_split_paint import verify_split_paint_inputs
from atme.render.v2_svg import (
    _compose_validated_svg_frame,
    _rasterize_svg_frame,
    compose_png_frame,
)
from atme.store import contracts_v2 as contracts
from test_v2_external_aperture_runtime import (
    native_oracle,
    runtime_documents,
    unclipped_documents,
)
from v2_fixtures import digest


def nested_documents(kind, ancestor, portrait):
    _plan, layout, clock, ids = runtime_documents(kind, portrait=portrait, group=True)
    objects = {obj["object_id"]: obj for obj in layout["objects"]}
    root, owner, consumer = objects[ids["root"]], objects[ids["aperture"]], objects[ids["receiver"]]
    owner_branch, consumer_branch = deepcopy(root), deepcopy(root)
    owner_branch.update(object_id="owner-branch", object_type=ancestor, parent_id=ids["root"],
                        child_ids=[ids["aperture"]], z_index=0)
    consumer_branch.update(object_id="consumer-branch", parent_id=ids["root"], child_ids=[ids["receiver"]], z_index=1)
    owner_branch["geometry"]["bounds"].update(x=0., y=0., width=5., height=5.)
    owner_branch["transform"].update(position={"x": 12., "y": 5.}, scale_x=1.15, scale_y=.85,
                                    rotation_degrees=11., origin={"x": .13, "y": .7})
    consumer_branch["transform"].update(position={"x": -5., "y": 8.}, scale_x=.9, scale_y=1.1,
                                       rotation_degrees=-7., origin={"x": .2, "y": .3})
    owner["parent_id"] = "owner-branch"
    consumer["parent_id"] = "consumer-branch"
    root["child_ids"].remove(ids["aperture"])
    root["child_ids"].remove(ids["receiver"])
    if kind == "mask":
        objects[ids["source"]]["parent_id"] = "owner-branch"
        owner_branch["child_ids"].append(ids["source"])
        root["child_ids"].remove(ids["source"])
        objects[ids["source"]]["object_type"] = "ellipse"
        # Mask owner's own pose moves its content, never the named aperture.
        owner["transform"].update(position={"x": 44., "y": 18.}, rotation_degrees=23.)
    root["child_ids"].extend(["owner-branch", "consumer-branch"])
    additions = [owner_branch, consumer_branch]
    if ancestor == "mask":
        source = deepcopy(objects[ids["art"]])
        source.update(object_id="ancestor-mask-source", parent_id=ids["root"], initial_state="visible", visible=True,
                      anchors=[], style={"stroke": None, "fill": None, "text": None, "effect": None})
        source["geometry"]["bounds"] = deepcopy(owner_branch["geometry"]["bounds"])
        source["transform"].update(position={"x": 0., "y": 0.}, scale_x=1., scale_y=1., rotation_degrees=0., origin={"x": 0., "y": 0.})
        owner_branch.update(mask_mode="alpha", mask_source_object_id=source["object_id"],
                            mask_coordinate_space="parent_local", invert=False, feather_px=0, anchors=[])
        root["child_ids"].append(source["object_id"])
        additions.append(source)
    layout["objects"].extend(additions)
    layout["boards"][0]["object_ids"].extend(obj["object_id"] for obj in additions)
    clock["initial_object_states"].extend({"object_id": obj["object_id"], "state": obj["initial_state"],
                                          "visible": obj["visible"], "state_version": 1} for obj in additions)
    clock["layout_sha256"] = digest(layout)
    contracts.ExecutableLayoutV2.model_validate(layout)
    return layout, clock, ids


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["clip", "mask"])
@pytest.mark.parametrize("ancestor", ["group", "clip", "mask"])
def test_actual_rotated_nonuniform_branches_use_named_native_aperture_and_frozen_offline_seek_parity(
        kind, ancestor, portrait, monkeypatch, tmp_path):
    layout, timeline, ids = nested_documents(kind, ancestor, portrait)
    original = deepcopy((layout, timeline))
    times = (1000, 4500, 5000)
    expected = {at: compose_png_frame(layout, timeline, at).png for at in times}
    assert all(expected[at] == native_oracle(layout, timeline, ids, kind, at, wrap_id="consumer-branch") for at in times)
    plain, plain_clock = unclipped_documents(layout, timeline)
    assert expected[1000] != compose_png_frame(plain, plain_clock, 1000).png
    (tmp_path / "actual-nested-native.png").write_bytes(expected[4500])
    typed = contracts.ExecutableLayoutV2.model_validate(layout)
    clock = contracts.ResolvedVisualTimelineV2.model_validate(timeline)
    inputs = verify_split_paint_inputs(typed, {})
    registry = registry_endpoint_inputs_for_objects({obj.object_id: obj for obj in typed.objects},
        frozen_files={name: raw for name, _, raw in inputs.bundle_bytes})

    def forbidden(*args, **kwargs):
        raise AssertionError("frozen external aperture reopened source files or network")

    original_open = Path.open

    def write_only(path, mode="r", *args, **kwargs):
        if "r" in mode or "+" in mode or not any(flag in mode for flag in ("w", "a", "x")):
            forbidden()
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(Path, "open", write_only)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    for at in (5000, 1000, 4500, 5000, 1000):
        sample = v2_state._evaluate_frame_with_registry_inputs(layout, timeline, at, registry)
        svg = _compose_validated_svg_frame(typed, clock, sample, {}, split_inputs=inputs)
        assert _rasterize_svg_frame(typed, svg, split_inputs=inputs).png == expected[at]
    assert (layout, timeline) == original
