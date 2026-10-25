"""S3-F08: authored relationships, never inferred or transferred endpoints."""

import io
import json
import socket
import xml.etree.ElementTree as ET
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest
from atme.render.v2_split import _observed_split_placements, capture_split
from atme.render.v2_split_identity import SplitContentReceipt, split_content_receipts
from atme.render.v2_split_paint import (
    _split_primitive_paint,
    prove_split_coverage,
    split_family_admission,
    verify_split_paint_inputs,
)
from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    ResolvedAction,
    ResolvedVisualTimelineV2,
    SplitPolicy,
    _split_expected_completion,
    _split_packet_digest,
)
from PIL import Image
from test_v2_media_runtime import (
    patterned_media as patterned_media,  # noqa: PLC0414 -- fixture re-export
)
from test_v2_split_families import geometry_split_family
from test_v2_split_identity import sample_for_layout
from v2_fixtures import digest


def connector_split_family(portrait=False, kind="arrow", mode="reveal", routing="straight"):
    original, _, resolved, clock, *_ = geometry_split_family(portrait, "rectangle", mode)
    raw, action = original.model_dump(mode="json"), resolved.model_dump(mode="json")
    template = deepcopy(raw["objects"][0])
    positions = ((80., 80.), (520., 80.), (300., 700.)) if portrait else (
        (60., 70.), (600., 70.), (320., 450.))
    for index, (x, y) in enumerate(positions):
        if kind == "pointer" and index == 0:
            continue
        endpoint = deepcopy(template)
        endpoint.update(object_id=f"endpoint-{index}", z_index=-3 + index, visible=True, initial_state="visible")
        endpoint["geometry"]["bounds"] = {"x": x, "y": y, "width": 40., "height": 40.}
        raw["objects"].append(endpoint)
    hashes, authored = {}, {}
    for obj in raw["objects"][:3]:
        index = ("source", "part-1", "part-2").index(obj["object_id"])
        obj.pop("path_data")
        source, target = ((0, 1), (0, 2), (2, 1))[index]
        obj.update(object_type="arrow" if kind == "pointer" else kind, anchors=[],
                   source_object_id=None if kind == "pointer" else f"endpoint-{source}",
                   source_anchor_id=None if kind == "pointer" else "center",
                   destination_object_id=f"endpoint-{target}", destination_anchor_id="center",
                   role="pointer" if kind == "pointer" else "semantic_connector",
                   routing=routing, allow_self_loop=False)
        obj["style"].update(fill=None, text=None)
        obj["geometry"] = {"bounds": deepcopy(raw["canvas"]), "points": [], "corner_radius": None}
        if kind == "pointer":
            x, y = positions[source]
            obj["source_point"] = {"x": x + 20., "y": y + 20. + index * 10.}
        fields = ("object_type", "geometry", "style", "anchors", "asset_id", "source_object_id",
                  "source_anchor_id", "destination_object_id", "destination_anchor_id", "role", "routing",
                  "allow_self_loop")
        payload = {key: obj[key] for key in fields}
        if kind == "pointer":
            payload["source_point"] = obj["source_point"]
        key = obj["object_id"]
        hashes[key] = digest(payload)
        authored[key] = SplitContentReceipt(key, json.dumps(payload, sort_keys=True, separators=(",", ":")), hashes[key])
    raw["boards"][0]["object_ids"] = [row["object_id"] for row in raw["objects"]]
    layout = ExecutableLayoutV2.model_validate(raw)
    before = sample_for_layout(layout)
    actual = {row.object_id: row for row in split_content_receipts(layout, before, {})}
    assert all(actual[key] == value for key, value in authored.items())
    policy = action["action"]["split_policy"]
    policy["source_basis"]["read_dependencies"] = [{
        "kind": "connector_anchor", "object_ids": sorted(actual),
    }]
    policy["source_basis"]["placements"] = [row.model_dump(mode="json") for row in _observed_split_placements(
        before, {obj.object_id: obj for obj in layout.objects}, set(actual), actual)]
    for row in policy["correspondences"]:
        row.update(source_content_sha256=hashes["source"], result_content_sha256=hashes[row["result_object_id"]])
    identity = template["transform"]
    for result in policy["results"]:
        result["destination"] = deepcopy(identity)
        if result["movement"] is not None:
            result["movement"]["from_transform"] = deepcopy(identity)
    policy["source_basis_sha256"] = digest(policy["source_basis"])
    completion = _split_expected_completion(SplitPolicy.model_validate(policy))
    completion["completion_sha256"] = digest(completion)
    action["split_completion_receipt"] = completion
    resolved = ResolvedAction.model_validate(action)
    timeline = clock.model_dump(mode="json")
    timeline["layout_sha256"] = digest(raw)
    timeline["actions"] = [action]
    timeline["initial_object_states"] = [{"object_id": row.object_id, "state": row.state,
        "visible": row.visible, "state_version": 1} for row in before.objects]
    return layout, before, resolved, ResolvedVisualTimelineV2.model_validate(timeline), hashes


@pytest.fixture(scope="module", params=[(portrait, kind, mode, routing)
    for portrait in (False, True) for kind in ("arrow", "network", "pointer")
    for mode in ("reveal", "draw") for routing in ("straight", "elbow", "curve")], ids=lambda row: "-".join(map(str, row)))
def connector_family_boundary(request, tmp_path_factory):
    portrait, kind, mode, routing = request.param
    layout, before, resolved, clock, hashes = connector_split_family(portrait, kind, mode, routing)
    capture = capture_split(resolved, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    return (*request.param, layout, before, resolved, clock, hashes, capture, inputs,
            tmp_path_factory.mktemp("connector-family"))


def test_split_connector_family_admits_exact_authored_relationships(connector_family_boundary):
    _, kind, mode, _, layout, _, _, _, hashes, capture, inputs, _ = connector_family_boundary
    for key in ("source", "part-1", "part-2"):
        admission = split_family_admission(key, capture, layout, inputs)
        assert admission.family == ("free-source pointer" if kind == "pointer" else "semantic connector")
        assert admission.content_sha256 == hashes[key]
        assert admission.mode == ("source_fade" if key == "source" else mode)
        assert admission.proof_kind == "native_connector_capture_alpha_v1"
    recipes = [json.loads(row) for row in inputs.paint_evidence if "connector_authored_recipe_v1" in row]
    assert {row["object_id"] for row in recipes} == {"source", "part-1", "part-2"}
    assert all("recipe" in row and "paint" not in row for row in recipes)


def test_split_connector_family_has_actual_every_ms_coverage(connector_family_boundary):
    _, _, _, _, layout, _, _, _, _, capture, inputs, _ = connector_family_boundary
    proof = prove_split_coverage(capture, layout, inputs)
    assert proof.proof_kind == "native_alpha_all_integer_ms_v1"
    assert proof.intervals[0].start_ms == 0 and proof.intervals[-1].end_ms == 40
    assert all(row.painted_root_ids for row in proof.intervals)


def test_split_connector_family_native_routes_pixels_and_frozen_seek(connector_family_boundary, monkeypatch):
    from atme.render.v2_camera import camera_segments
    from atme.render.v2_state import _sample_validated_frame
    from atme.render.v2_svg import _compose_validated_svg_frame, _rasterize_svg_frame
    from test_v2_split_action import replay_split

    portrait, kind, mode, routing, layout, before, resolved, clock, _, _, inputs, directory = connector_family_boundary
    replay = replay_split(layout, before, (resolved,), clock.duration_ms)
    camera = camera_segments(layout, clock, replay, split_inputs=inputs)

    def render(at):
        snapshot = _sample_validated_frame(layout, clock, replay, camera, at)
        svg = _compose_validated_svg_frame(layout, clock, snapshot, {}, None, split_inputs=inputs)
        return svg.svg, _rasterize_svg_frame(layout, svg, split_inputs=inputs).png

    expected = {at: render(at) for at in (0, 1, 12, 24, 36, 40, 41)}
    positions = ((100., 100.), (540., 100.), (320., 720.)) if portrait else (
        (80., 90.), (620., 90.), (340., 470.))
    colors = json.loads(inputs.style_json)["colors"]
    complete = ET.fromstring(expected[40][0])
    with Image.open(io.BytesIO(expected[40][1])) as image:
        rgb = image.convert("RGB")
        for index, key in enumerate(("part-1", "part-2"), 1):
            start_id, target_id = ((0, 2), (2, 1))[index - 1]
            sx, sy = positions[start_id]
            ex, ey = positions[target_id]
            if kind == "pointer":
                sy += index * 10.
            node = next(row for row in complete.iter() if row.attrib.get("data-object-id") == key)
            path = next(row for row in node.iter() if row.tag.endswith("path"))
            assert path.attrib["d"].startswith(f"M {sx:g} {sy:g} ")
            assert path.attrib["d"].endswith(f"{ex:g} {ey:g}")
            assert any(row.tag.endswith("polygon") for row in node.iter())
            if routing == "elbow":
                assert f"L {ex:g} {sy:g} L " in path.attrib["d"]
                sample = ((sx + ex) / 2, sy)
            elif routing == "curve":
                assert f"Q {(sx + ex) / 2:g} {sy:g} " in path.attrib["d"]
                sample = ((sx + ex) / 2, .75 * sy + .25 * ey)
            else:
                sample = ((sx + ex) / 2, (sy + ey) / 2)
            hex_color = colors["accent" if index == 1 else "attention"].lstrip("#")
            color = tuple(int(hex_color[at:at + 2], 16) for at in (0, 2, 4))
            assert rgb.getpixel(tuple(round(value) for value in sample)) == color
    if mode == "draw":
        partial = ET.fromstring(expected[1][0])
        node = next(row for row in partial.iter() if row.attrib.get("data-object-id") == "part-1")
        assert not any(row.tag.endswith("polygon") for row in node.iter())
        assert any("stroke-dashoffset" in row.attrib for row in node.iter())
    original = layout.model_dump_json(), clock.model_dump_json(), repr(replay)
    original_open = Path.open

    def denied(*_args, **_kwargs):
        pytest.fail("frozen connector preview reopened an original or used the network")

    def temporary_fonts_only(path, *args, **kwargs):
        assert any(part.startswith("atme-split-fonts-") for part in path.parts)
        return original_open(path, *args, **kwargs)

    with monkeypatch.context() as sealed:
        sealed.setattr(Path, "read_bytes", denied)
        sealed.setattr(Path, "read_text", denied)
        sealed.setattr(Path, "open", temporary_fonts_only)
        sealed.setattr(socket, "create_connection", denied)
        sealed.setattr(socket.socket, "connect", denied)
        for at in (40, 1, 24, 41, 0, 36, 12, 40):
            assert render(at) == expected[at]
    assert original == (layout.model_dump_json(), clock.model_dump_json(), repr(replay))
    (directory / "connector-complete.png").write_bytes(expected[40][1])
    (directory / "connector-construction.png").write_bytes(expected[1][1])


def current_connector_family(portrait, kind, fault=None):
    from test_v2_split_action import replay_split
    from test_v2_split_capture import peer_action
    from test_v2_timeline_replay import resolved as timed

    layout, _, split, clock, _ = connector_split_family(portrait, kind)
    raw = layout.model_dump(mode="json")
    source = next(row for row in raw["objects"] if row["object_id"] == "source")
    source.update(initial_state="hidden", visible=False)
    endpoint = next(row for row in raw["objects"] if row["object_id"] == "endpoint-1")
    dx = 440. if portrait else 540.
    if fault != "coincident":
        endpoint["geometry"]["bounds"]["x"] -= dx
    if fault == "hidden":
        endpoint.update(initial_state="hidden", visible=False)
    layout = ExecutableLayoutV2.model_validate(raw)
    initial = sample_for_layout(layout)
    destination = deepcopy(source["transform"])
    destination["position"]["x"] = -dx if fault == "coincident" else dx
    move = peer_action("move", target_ids=["endpoint-1"], destination=destination).action.model_copy(
        update={"action_id": "position-endpoint", "expected_state": "hidden" if fault == "hidden" else "visible"})
    reveal = peer_action("reveal", target_ids=["source"]).action.model_copy(
        update={"action_id": "reveal-source", "expected_state": "hidden"})
    prefix = (timed(move, 0, 1), timed(reveal, 1, 2))
    before = replay_split(layout, initial, prefix, clock.duration_ms).at(3)
    return seal_current_connector(layout, initial, before, split, clock, prefix)


def seal_current_connector(layout, initial, before, split, clock, prefix):
    action = deepcopy(split) if isinstance(split, dict) else split.model_dump(mode="json")
    trigger = {"kind": "absolute", "at_ms": 3}
    action["action"]["trigger"] = trigger
    action.update(start_ms=3, end_ms=43)
    action["resolved_trigger"].update(source=trigger, alignment_anchor_ms=3, resolved_at_ms=3,
                                      matched_text=None, matched_occurrence=None, confidence=1., exact=True)
    receipts = {row.object_id: row for row in split_content_receipts(layout, before, {})}
    policy = action["action"]["split_policy"]
    basis = policy["source_basis"]
    bound = {key for closure in (basis["source_closure"], *basis["result_closures"]) for key in closure["owned_ids"]}
    bound.update(key for row in basis["read_dependencies"] for key in row["object_ids"])
    policy["source_basis"]["placements"] = [row.model_dump(mode="json") for row in _observed_split_placements(
        before, {obj.object_id: obj for obj in layout.objects}, bound, receipts)]
    for row in policy["correspondences"]:
        row.update(source_content_sha256=receipts["source"].content_sha256,
                   result_content_sha256=receipts[row["result_object_id"]].content_sha256)
    policy["source_basis_sha256"] = _split_packet_digest(policy["source_basis"])
    completion = _split_expected_completion(SplitPolicy.model_validate(policy))
    completion["completion_sha256"] = _split_packet_digest(completion)
    action["split_completion_receipt"] = completion
    split = ResolvedAction.model_validate(action)
    document = clock.model_dump(mode="json")
    document["layout_sha256"] = digest(layout.model_dump(mode="json"))
    document["output_profile"] = layout.output_profile.model_dump(mode="json")
    document["plan_sha256"] = layout.plan_sha256
    document["initial_object_states"] = [{"object_id": row.object_id, "state": row.state,
        "visible": row.visible, "state_version": dict(initial.state_versions)[row.object_id]} for row in initial.objects]
    document["actions"] = [row.model_dump(mode="json") for row in (*prefix, split)]
    document["coverage"][0]["action_ids"] = [row["action"]["action_id"] for row in document["actions"]]
    clock = ResolvedVisualTimelineV2.model_validate(document)
    assert clock.plan_sha256 == layout.plan_sha256
    return layout, before, split, clock


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["arrow", "network", "pointer"])
def test_split_connector_native_proof_uses_actual_completed_pose_not_initial_route(portrait, kind):
    layout, before, split, _ = current_connector_family(portrait, kind)
    inputs = verify_split_paint_inputs(layout, {})
    capture = capture_split(split, layout, before, {})
    assert before.object("endpoint-1").transform.position.x == (440. if portrait else 540.)
    assert split_family_admission("source", capture, layout, inputs).proof_kind == "native_connector_capture_alpha_v1"


@pytest.mark.parametrize("fault", ["coincident", "hidden"])
@pytest.mark.parametrize("kind", ["arrow", "network", "pointer"])
def test_split_connector_recipe_does_not_authorize_invalid_captured_route(kind, fault):
    layout, before, split, _ = current_connector_family(False, kind, fault)
    inputs = verify_split_paint_inputs(layout, {})
    capture = capture_split(split, layout, before, {})
    with pytest.raises(ValueError, match="degenerate|hidden endpoint"):
        split_family_admission("source", capture, layout, inputs)


@pytest.mark.parametrize("kind", ["arrow", "network", "pointer"])
@pytest.mark.parametrize("mode", ["write", "enter"])
def test_split_connector_family_rejects_incompatible_construction(kind, mode):
    layout, *_ = connector_split_family(False, kind)
    with pytest.raises(ValueError, match=f"Split {mode} is incompatible"):
        _split_primitive_paint(layout.objects[1], mode)


@pytest.mark.parametrize("kind", ["arrow", "network", "pointer"])
def test_split_connector_family_rejects_partial_captured_endpoint_inventory(kind):
    layout, before, resolved, _, _ = connector_split_family(False, kind)
    capture = capture_split(resolved, layout, before, {})
    partial = replace(capture, baseline=tuple(row for row in capture.baseline if row.object_id != "endpoint-1"))
    with pytest.raises(ValueError):
        split_family_admission("source", partial, layout, verify_split_paint_inputs(layout, {}))


@pytest.mark.parametrize("kind", ["arrow", "network", "pointer"])
@pytest.mark.parametrize("fault", ["payload", "pretend_native", "missing", "duplicate"])
def test_split_connector_coherently_rehashed_recipe_cannot_be_native_authority(kind, fault):
    layout, before, resolved, _, _ = connector_split_family(False, kind)
    capture = capture_split(resolved, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    rows = [json.loads(value) for value in inputs.paint_evidence]
    source = next(row for row in rows if row.get("object_id") == "source")
    if fault == "payload":
        source["recipe"]["object_sha256"] = "0" * 64
    elif fault == "pretend_native":
        source["proof_kind"] = "native_connector_capture_alpha_v1"
        source["paint"] = {"alpha_sha256": "0" * 64}
        del source["recipe"]
    elif fault == "missing":
        rows.remove(source)
    else:
        rows.append(deepcopy(source))
    manifest = json.loads(inputs.manifest_json)
    manifest["paint_evidence"] = rows
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    forged = replace(inputs, paint_evidence=tuple(json.dumps(row, sort_keys=True, separators=(",", ":")) for row in rows),
                     manifest_json=encoded, inputs_sha256=sha256(encoded.encode()).hexdigest())
    with pytest.raises(ValueError, match="frozen paint binding"):
        split_family_admission("source", capture, layout, forged)


@pytest.mark.parametrize("kind", ["arrow", "network", "pointer"])
@pytest.mark.parametrize("fault", ["destination", "source", "anchor", "routing"])
def test_split_connector_fresh_recipe_cannot_replace_captured_relationship(kind, fault):
    layout, before, resolved, _, _ = connector_split_family(False, kind)
    capture = capture_split(resolved, layout, before, {})
    raw = layout.model_dump(mode="json")
    part = next(row for row in raw["objects"] if row["object_id"] == "part-1")
    if fault == "destination":
        part["destination_object_id"] = "endpoint-1"
    elif fault == "source":
        part = next(row for row in raw["objects"] if row["object_id"] == "part-2")
        if kind == "pointer":
            part["source_point"]["x"] += 5.
        else:
            part["source_object_id"] = "endpoint-0"
    elif fault == "anchor":
        target = next(row for row in raw["objects"] if row["object_id"] == "endpoint-2")
        target["anchors"].append({"anchor_id": "alternate", "point": {"x": .25, "y": .25}})
        part["destination_anchor_id"] = "alternate"
    else:
        part["routing"] = "curve"
    fresh = ExecutableLayoutV2.model_validate(raw)
    inputs = verify_split_paint_inputs(fresh, {})
    with pytest.raises(ValueError, match="captured content|captured read"):
        split_family_admission("part-1", capture, fresh, inputs)


@pytest.fixture(scope="module")
def connector_media_carrier(patterned_media):
    from test_v2_split_media_family import media_family

    return media_family(raw=patterned_media, kind="video")[4]


def media_connector_family(portrait, kind, raw_media, carrier, fault):
    from test_v2_media_runtime import install_media
    from test_v2_split_media_family import carrier_for, reseal

    base, _, action, clock, _ = connector_split_family(portrait, kind)
    raw, document = base.model_dump(mode="json"), clock.model_dump(mode="json")
    media, _ = install_media(raw, document, "endpoint-1", raw_media,
        start=100 if fault == "inactive" else 0, out=20 if fault == "ends_early" else 6000)
    if fault == "translated":
        media["transform"]["position"]["x"] = 10.
    elif fault == "hidden":
        media.update(visible=False, initial_state="hidden")
    elif fault == "rotation_denied":
        media["transform"]["rotation_degrees"] = 15.
    layout = ExecutableLayoutV2.model_validate(raw)
    verified = carrier_for(layout, carrier)
    before = sample_for_layout(layout)
    (split, clock), _ = reseal(layout, before, action, clock, verified)
    return layout, before, split, clock, verified


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["arrow", "network", "pointer"])
@pytest.mark.parametrize("fault", ["active", "translated", "hidden", "inactive", "ends_early", "rotation_denied"])
def test_split_connector_media_endpoint_uses_actual_readiness_and_current_grants(
    portrait, kind, fault, patterned_media, connector_media_carrier,
):
    layout, before, split, _, carrier = media_connector_family(
        portrait, kind, patterned_media, connector_media_carrier, fault)
    original = layout.model_dump_json(), carrier
    capture = capture_split(split, layout, before, carrier)
    inputs = verify_split_paint_inputs(layout, carrier)
    if fault in {"active", "translated", "ends_early"}:
        assert split_family_admission("source", capture, layout, inputs).proof_kind == "native_connector_capture_alpha_v1"
        if fault == "ends_early":
            with pytest.raises(ValueError, match="media|inactive|endpoint"):
                prove_split_coverage(capture, layout, inputs)
        else:
            assert prove_split_coverage(capture, layout, inputs).intervals[-1].end_ms == 40
    else:
        with pytest.raises(ValueError, match="hidden endpoint|has no active visual anchor|rotate permission|cannot rotate|no rotate permission"):
            split_family_admission("source", capture, layout, inputs)
    assert (layout.model_dump_json(), carrier) == original


def parented_connector_family(portrait, kind, distinct=False):
    from test_v2_group_hierarchy import grouped_documents
    from test_v2_split_action import replay_split
    from test_v2_split_capture import peer_action
    from test_v2_timeline_replay import resolved as timed

    base, _, split, clock, _ = connector_split_family(portrait, kind)
    raw = base.model_dump(mode="json")
    source = next(row for row in raw["objects"] if row["object_id"] == "source")
    source.update(initial_state="hidden", visible=False)
    groups, prefix = [], []
    specs = [
        ("endpoint-parent", [row["object_id"] for row in raw["objects"] if row["object_id"].startswith("endpoint-")],
         (.9, 1.1), -7., (40., 30.)),
    ]
    if kind == "pointer":
        specs.append(("pointer-parent", ["source", "part-1", "part-2"], (1.1, .9), -13., (20., 10.)))
    if distinct:
        specs[0][1].remove("endpoint-1")
        specs.extend([
            ("destination-inner", ["endpoint-1"], (.95, 1.05), -3., (10., 5.)),
            ("destination-outer", ["destination-inner"], (1.05, .95), 3., (5., 15.)),
        ])
    for name, children, scale, rotation, position in specs:
        group = deepcopy(grouped_documents()[0]["objects"][3])
        group.update(object_id=name, child_ids=children, parent_id=None,
                     **{key: deepcopy(source[key]) for key in ("board_id", "beat_id", "coverage_ids")})
        group["geometry"]["bounds"] = deepcopy(raw["canvas"])
        group["transform"].update(position={"x": 0., "y": 0.}, scale_x=scale[0], scale_y=scale[1],
                                   rotation_degrees=rotation, origin={"x": 0., "y": 0.})
        for obj in (*raw["objects"], *groups):
            if obj["object_id"] in children:
                obj["parent_id"] = name
        destination = deepcopy(group["transform"])
        destination["position"] = dict(zip(("x", "y"), position, strict=True))
        move = peer_action("move", target_ids=[name], destination=destination).action.model_copy(
            update={"action_id": f"pose-{name}", "expected_state": "visible"})
        prefix.append(timed(move, 0, 1))
        groups.append(group)
    raw["objects"].extend(groups)
    raw["boards"][0]["object_ids"].extend(row["object_id"] for row in groups)
    layout = ExecutableLayoutV2.model_validate(raw)
    initial = sample_for_layout(layout)
    reveal = peer_action("reveal", target_ids=["source"]).action.model_copy(
        update={"action_id": "reveal-parented-source", "expected_state": "hidden"})
    prefix.append(timed(reveal, 1, 2))
    before = replay_split(layout, initial, tuple(prefix), clock.duration_ms).at(3)
    action = split.model_dump(mode="json")
    action["action"]["split_policy"]["source_basis"]["read_dependencies"].insert(0, {
        "kind": "ancestor", "object_ids": sorted(row["object_id"] for row in groups),
    })
    return seal_current_connector(layout, initial, before, action, clock, prefix)


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind,distinct", [("arrow", False), ("network", False), ("pointer", False),
                                          ("arrow", True), ("network", True)])
def test_split_connector_current_parent_ancestry_and_noncommuting_pointer_inverse(portrait, kind, distinct, tmp_path):
    from atme.render.v2_camera import camera_segments
    from atme.render.v2_state import _sample_validated_frame
    from atme.render.v2_svg import _compose_validated_svg_frame, _rasterize_svg_frame
    from test_v2_registry_world import literal_transform
    from test_v2_split_action import replay_split

    layout, before, split, clock = parented_connector_family(portrait, kind, distinct)
    inputs = verify_split_paint_inputs(layout, {})
    capture = capture_split(split, layout, before, {})
    assert split_family_admission("source", capture, layout, inputs).proof_kind == "native_connector_capture_alpha_v1"
    assert prove_split_coverage(capture, layout, inputs).intervals[-1].end_ms == 43
    initial = sample_for_layout(layout)
    replay = replay_split(layout, initial, tuple(clock.actions), clock.duration_ms)
    camera = camera_segments(layout, clock, replay, split_inputs=inputs)
    snapshot = _sample_validated_frame(layout, clock, replay, camera, 43)
    svg = _compose_validated_svg_frame(layout, clock, snapshot, {}, None, split_inputs=inputs)
    root = ET.fromstring(svg.svg)
    objects = {obj.object_id: obj for obj in layout.objects}
    points = ((100., 100.), (540., 100.), (320., 720.)) if portrait else ((80., 90.), (620., 90.), (340., 470.))

    def world_endpoint(index):
        point, parent_id = points[index], objects[f"endpoint-{index}"].parent_id
        while parent_id is not None:
            parent = objects[parent_id]
            point = literal_transform(point, parent, before.object(parent_id).transform)
            parent_id = parent.parent_id
        return point

    for index, key in enumerate(("part-1", "part-2"), 1):
        source_id, target_id = ((0, 2), (2, 1))[index - 1]
        end = world_endpoint(target_id)
        if kind == "pointer":
            pointer_parent = objects["pointer-parent"]
            transform = before.object("pointer-parent").transform
            origin, x_axis, y_axis = [literal_transform(point, pointer_parent, transform) for point in ((0., 0.), (1., 0.), (0., 1.))]
            a, b, c, d = x_axis[0] - origin[0], x_axis[1] - origin[1], y_axis[0] - origin[0], y_axis[1] - origin[1]
            x, y = end[0] - origin[0], end[1] - origin[1]
            end = ((d * x - c * y) / (a * d - b * c), (a * y - b * x) / (a * d - b * c))
            start = (points[source_id][0], points[source_id][1] + index * 10.)
        else:
            start = world_endpoint(source_id)
        node = next(row for row in root.iter() if row.attrib.get("data-object-id") == key)
        path = next(row for row in node.iter() if row.tag.endswith("path"))
        coordinates = [float(value) for value in path.attrib["d"].replace("M", "").replace("L", "").split()]
        assert coordinates[:2] == pytest.approx(start, abs=.00005)
        assert coordinates[-2:] == pytest.approx(end, abs=.00005)
        assert any(row.tag.endswith("polygon") for row in node.iter())
    png = _rasterize_svg_frame(layout, svg, split_inputs=inputs).png
    (tmp_path / f"current-parent-{kind}-{portrait}.png").write_bytes(png)
    assert any(row.object_id == "endpoint-parent" for row in capture.content_receipts)


@pytest.mark.parametrize("kind", ["arrow", "network"])
@pytest.mark.parametrize("parent_id", ["destination-inner", "destination-outer"])
@pytest.mark.parametrize("fault", ["missing", "changed"])
def test_split_connector_distinct_current_ancestor_chains_are_independently_bound(kind, parent_id, fault):
    layout, before, split, _ = parented_connector_family(False, kind, distinct=True)
    capture = capture_split(split, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    assert split_family_admission("source", capture, layout, inputs).proof_kind == "native_connector_capture_alpha_v1"
    state = next(row for row in capture.baseline if row.object_id == parent_id)
    if fault == "missing":
        capture = replace(capture, baseline=tuple(row for row in capture.baseline if row.object_id != parent_id))
    else:
        changed = replace(state, transform=replace(state.transform, rotation_degrees=17.))
        capture = replace(capture, baseline=tuple(changed if row.object_id == parent_id else row for row in capture.baseline))
    with pytest.raises(ValueError, match="captured|inventory|receipt|state"):
        split_family_admission("source", capture, layout, inputs)


@pytest.mark.parametrize("kind", ["arrow", "network", "pointer"])
@pytest.mark.parametrize("fault", ["missing_state", "missing_receipt", "changed_pose", "hidden", "missing_version"])
def test_split_connector_cannot_borrow_incomplete_or_changed_current_ancestry(kind, fault):
    layout, before, split, _ = parented_connector_family(False, kind)
    capture = capture_split(split, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    if fault == "missing_version":
        before = replace(before, state_versions=tuple(row for row in before.state_versions if row[0] != "endpoint-parent"))
        with pytest.raises(ValueError, match="version"):
            capture_split(split, layout, before, {})
        return
    if fault == "missing_state":
        capture = replace(capture, baseline=tuple(row for row in capture.baseline if row.object_id != "endpoint-parent"))
    elif fault == "missing_receipt":
        capture = replace(capture, content_receipts=tuple(row for row in capture.content_receipts if row.object_id != "endpoint-parent"))
    else:
        state = next(row for row in capture.baseline if row.object_id == "endpoint-parent")
        changed = (replace(state, visible=False) if fault == "hidden" else replace(state,
            transform=replace(state.transform, position=replace(state.transform.position, x=99.))))
        capture = replace(capture, baseline=tuple(changed if row.object_id == state.object_id else row for row in capture.baseline))
    with pytest.raises(ValueError, match="captured|inventory|receipt|state"):
        split_family_admission("source", capture, layout, inputs)


def registry_connector_family(portrait, kind):
    from test_v2_registry_consumers import replace_with_bound_actor
    from test_v2_split_action import replay_split

    base, _, split, clock = parented_connector_family(portrait, kind, distinct=kind != "pointer")
    raw = base.model_dump(mode="json")
    for key in ("endpoint-0", "endpoint-1", "endpoint-2"):
        if kind == "pointer" and key == "endpoint-0":
            continue
        actor = replace_with_bound_actor(raw, key, retain_geometry=True)
        if key == "endpoint-1":
            actor["anchors"][0].update(anchor_id="actor-right")
            actor["anchors"][0]["point"]["x"] = .7
            actor["registry_binding"]["anchor_mappings"][0].update(
                placed_anchor_id="actor-right", registry_anchor_name="right_person")
        for obj in raw["objects"]:
            for side in ("source", "destination"):
                if obj.get(f"{side}_object_id") == key:
                    obj[f"{side}_anchor_id"] = actor["anchors"][0]["anchor_id"]
    layout = ExecutableLayoutV2.model_validate(raw)
    initial = sample_for_layout(layout)
    prefix = tuple(clock.actions[:-1])
    before = replay_split(layout, initial, prefix, clock.duration_ms).at(3)
    return seal_current_connector(layout, initial, before, split, clock, prefix)


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["arrow", "network", "pointer"])
def test_split_connector_registry_parts_use_pinned_art_and_current_semantic_anchors(portrait, kind, tmp_path):
    from atme.render.v2_camera import camera_segments
    from atme.render.v2_state import _sample_validated_frame
    from atme.render.v2_svg import _compose_validated_svg_frame, _rasterize_svg_frame
    from test_v2_registry_world import literal_transform
    from test_v2_split_action import replay_split

    layout, before, split, clock = registry_connector_family(portrait, kind)
    inputs = verify_split_paint_inputs(layout, {})
    capture = capture_split(split, layout, before, {})
    assert split_family_admission("source", capture, layout, inputs).proof_kind == "native_connector_capture_alpha_v1"
    assert prove_split_coverage(capture, layout, inputs).intervals[-1].end_ms == 43
    assert any(name == "assets/person-collaborators.svg" and checksum ==
               "8821865df2fe372a4c240640d908a28755262b1766ff0a9cfb4c186d8f54d356"
               for name, checksum, _ in inputs.bundle_bytes)
    replay = replay_split(layout, sample_for_layout(layout), tuple(clock.actions), clock.duration_ms)
    cameras = camera_segments(layout, clock, replay, split_inputs=inputs)
    frame = _sample_validated_frame(layout, clock, replay, cameras, 43)
    svg = _compose_validated_svg_frame(layout, clock, frame, {}, None, split_inputs=inputs)
    objects = {obj.object_id: obj for obj in layout.objects}
    root = ET.fromstring(svg.svg)
    for key, endpoint, offset in (("source", "endpoint-1", 28.), ("part-1", "endpoint-2", 12.),
                                   ("part-2", "endpoint-1", 28.)):
        if key == "source":
            assert not any(row.attrib.get("data-object-id") == key for row in root.iter())
            continue
        actor = objects[endpoint]
        # Literal 300x220 artwork fitted to 40x40, left/right persons at .3/.7,.48.
        point = (actor.geometry.bounds.x + offset, actor.geometry.bounds.y + 19.413333333333334)
        parent_id = actor.parent_id
        while parent_id is not None:
            parent = objects[parent_id]
            point = literal_transform(point, parent, before.object(parent_id).transform)
            parent_id = parent.parent_id
        if kind == "pointer":
            parent = objects["pointer-parent"]
            origin, x_axis, y_axis = [literal_transform(p, parent, before.object(parent.object_id).transform)
                                     for p in ((0., 0.), (1., 0.), (0., 1.))]
            a, b, c, d = x_axis[0] - origin[0], x_axis[1] - origin[1], y_axis[0] - origin[0], y_axis[1] - origin[1]
            x, y = point[0] - origin[0], point[1] - origin[1]
            point = ((d * x - c * y) / (a * d - b * c), (a * y - b * x) / (a * d - b * c))
        node = next(row for row in root.iter() if row.attrib.get("data-object-id") == key)
        path = next(row for row in node.iter() if row.tag.endswith("path"))
        coordinates = [float(value) for value in path.attrib["d"].replace("M", "").replace("L", "").split()]
        assert coordinates[-2:] == pytest.approx(point, abs=.0001)
    png = _rasterize_svg_frame(layout, svg, split_inputs=inputs).png
    (tmp_path / f"registry-{kind}-{portrait}.png").write_bytes(png)


@pytest.mark.parametrize("kind", ["arrow", "network", "pointer"])
@pytest.mark.parametrize("fault", ["variant", "placed_anchor", "part", "missing_bytes", "changed_bytes"])
def test_split_connector_registry_authority_cannot_be_replaced(kind, fault):
    layout, before, split, _ = registry_connector_family(False, kind)
    capture = capture_split(split, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    assert split_family_admission("source", capture, layout, inputs).proof_kind == "native_connector_capture_alpha_v1"
    if fault in {"missing_bytes", "changed_bytes"}:
        rows = []
        for name, checksum, payload in inputs.bundle_bytes:
            if name == "assets/person-collaborators.svg":
                if fault == "missing_bytes":
                    continue
                payload += b" "
                checksum = sha256(payload).hexdigest()
            rows.append((name, checksum, payload))
        forged = replace(inputs, bundle_bytes=tuple(rows))
        with pytest.raises(ValueError, match="resource|checksum|hash|binding"):
            split_family_admission("source", capture, layout, forged)
        return
    raw = layout.model_dump(mode="json")
    actor = next(obj for obj in raw["objects"] if obj["object_id"] == "endpoint-1")
    if fault == "variant":
        actor["variant"] = "person-presenter"
    elif fault == "placed_anchor":
        actor["anchors"][0]["point"]["x"] = .5
    else:
        actor["registry_binding"]["anchor_mappings"][0]["registry_anchor_name"] = "not-a-part"
    with pytest.raises(ValueError, match="registry|anchor|binding|variant|captured read content"):
        fresh = ExecutableLayoutV2.model_validate(raw)
        split_family_admission("source", capture, fresh, verify_split_paint_inputs(fresh, {}))


@pytest.mark.parametrize("kind", ["arrow", "network", "pointer"])
@pytest.mark.parametrize("fault", ["destination_id", "source_id_or_point", "direction"])
def test_split_connector_upstream_semantic_binding_cannot_be_rehashed_into_new_relationship(kind, fault):
    from atme.store.contracts_v2 import validate_plan_layout
    from test_v2_pointer_composition import composed_relationship_documents

    plan, layout, _ = composed_relationship_documents("anchored" if kind == "arrow" else kind)
    validate_plan_layout(plan, layout)
    binding = plan["objects"][-1]["connector_binding"]
    if fault == "destination_id":
        binding["destination_object_id"] = layout["objects"][0]["object_id"]
    elif kind == "pointer":
        binding["source_point"]["x"] += 5.
        if fault == "direction":
            binding["destination_object_id"] = layout["objects"][1]["object_id"]
    elif fault == "source_id_or_point":
        binding["source_object_id"] = layout["objects"][0]["object_id"]
    else:
        binding["source_object_id"], binding["destination_object_id"] = (
            binding["destination_object_id"], binding["source_object_id"])
    layout["plan_sha256"] = digest(plan)
    with pytest.raises(ValueError, match="expanded member|connector_binding"):
        validate_plan_layout(plan, layout)


def managed_endpoint_handoff_family(portrait, kind, fault=None):
    from atme.render.v2_timeline_replay import replay_chronology
    from test_v2_group_hierarchy import grouped_documents
    from test_v2_split_capture import peer_action
    from test_v2_timeline_replay import resolved as timed

    base, _, split, clock, _ = connector_split_family(portrait, kind)
    raw = base.model_dump(mode="json")
    source = next(obj for obj in raw["objects"] if obj["object_id"] == "source")
    extra = deepcopy(source)
    extra.pop("source_point", None)
    extra.update(object_id="managed-endpoint-relation", object_type="arrow", source_object_id="endpoint-2",
                 source_anchor_id="center", destination_object_id="endpoint-1", destination_anchor_id="center",
                 role="semantic_connector", initial_state="disconnected", visible=False, z_index=9)
    parent = deepcopy(grouped_documents()[0]["objects"][3])
    parent.update(object_id="handoff-parent", parent_id=None,
                  child_ids=[obj["object_id"] for obj in raw["objects"] if obj["object_id"].startswith("endpoint-")],
                  **{key: deepcopy(source[key]) for key in ("board_id", "beat_id", "coverage_ids", "transform")})
    parent["geometry"]["bounds"] = deepcopy(raw["canvas"])
    for obj in raw["objects"]:
        if obj["object_id"] in parent["child_ids"]:
            obj["parent_id"] = parent["object_id"]
    raw["objects"].extend((extra, parent))
    raw["boards"][0]["object_ids"].extend((extra["object_id"], parent["object_id"]))
    layout = ExecutableLayoutV2.model_validate(raw)
    initial = sample_for_layout(layout)
    fields = {key: extra[key] for key in ("source_object_id", "source_anchor_id",
                                         "destination_object_id", "destination_anchor_id")}
    connect = peer_action("connect", connector_id=extra["object_id"], **fields).action.model_copy(update={
        "action_id": "connect-endpoints", "expected_state": "disconnected", "post_state": "connected"})
    disconnect = peer_action("disconnect", connector_id=extra["object_id"], **fields).action.model_copy(update={
        "action_id": "disconnect-endpoints", "expected_state": "connected", "post_state": "disconnected"})
    prefix = [timed(connect, 0, 1)]
    if fault != "active":
        prefix.append(timed(disconnect, 1, 3 if fault == "at_capture" else 4 if fault == "inflight" else 2))
    if fault in {"endpoint_writer", "ancestor_writer"}:
        target = "handoff-parent" if fault == "ancestor_writer" else "endpoint-1"
        destination = next(obj for obj in raw["objects"] if obj["object_id"] == target)["transform"]
        destination = deepcopy(destination)
        destination["position"]["x"] = 5.
        writer = peer_action("move", target_ids=[target], destination=destination).action
        prefix.append(timed(writer.model_copy(update={"action_id": f"after-disconnect-{fault}"}), 2, 3))
    objects = {obj.object_id: obj for obj in layout.objects}
    prior = replay_chronology(objects, initial.hierarchy, {obj.object_id: obj for obj in initial.objects},
        dict(initial.state_versions), tuple(prefix),
        tuple((row.board_id, row.start_ms, row.end_ms) for row in layout.activations), clock.duration_ms)
    before = prior.at(3)
    action = split.model_dump(mode="json")
    action["action"]["split_policy"]["source_basis"]["read_dependencies"].insert(0, {
        "kind": "ancestor", "object_ids": [parent["object_id"]],
    })
    layout, _, _, clock = seal_current_connector(layout, initial, before, action, clock, tuple(prefix))
    if fault in {"reconnect", "isolate"}:
        document = clock.model_dump(mode="json")
        later = connect if fault == "reconnect" else peer_action("isolate", target_ids=["endpoint-1"]).action
        action_id = f"after-capture-{fault}"
        document["actions"].append(timed(later.model_copy(update={"action_id": action_id}), 4, 5).model_dump(mode="json"))
        document["coverage"][0]["action_ids"].append(action_id)
        clock = ResolvedVisualTimelineV2.model_validate(document)
    return layout, initial, clock


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["arrow", "network", "pointer"])
def test_split_connector_family_keeps_completed_typed_endpoint_handoff(portrait, kind):
    from atme.render.v2_lifecycle import validate_split_lifecycle
    from atme.render.v2_timeline_replay import _replay_split_chronology

    layout, initial, clock = managed_endpoint_handoff_family(portrait, kind)
    original = layout.model_dump_json(), repr(initial), clock.model_dump_json()
    with pytest.raises(ValueError, match="managed connector"):
        _replay_split_chronology(layout, initial, tuple(clock.actions), clock.duration_ms, {})
    replay = _replay_split_chronology(layout, initial, tuple(clock.actions), clock.duration_ms, {}, timeline=clock)
    capture = next(row.split_capture for checkpoint in replay.checkpoints for row in checkpoint.active
                   if getattr(row, "split_capture", None) is not None)
    before = replay.before_action(capture.action_id)
    assert before.object("source").state == "visible"
    assert before.object("managed-endpoint-relation").state == "disconnected"
    assert before.object("managed-endpoint-relation").visible is False
    assert dict(before.state_versions)["managed-endpoint-relation"] == 3
    post = replay.at(2)
    for at in (3, 22, 42, 43):
        sampled = replay.at(at)
        for key in ("managed-endpoint-relation", "endpoint-1", "endpoint-2", "handoff-parent"):
            assert sampled.object(key) == post.object(key)
            assert dict(sampled.state_versions)[key] == dict(post.state_versions)[key]
        assert sampled.hierarchy == post.hierarchy
    inputs = verify_split_paint_inputs(layout, {})
    validate_split_lifecycle(capture, replay, layout, clock, split_inputs=inputs)
    assert split_family_admission("source", capture, layout, inputs).proof_kind == "native_connector_capture_alpha_v1"
    assert prove_split_coverage(capture, layout, inputs).intervals[-1].end_ms == 43
    assert (layout.model_dump_json(), repr(initial), clock.model_dump_json()) == original


@pytest.mark.parametrize("kind", ["arrow", "network", "pointer"])
@pytest.mark.parametrize("fault", ["active", "inflight", "at_capture", "reconnect", "endpoint_writer", "ancestor_writer", "isolate"])
def test_split_connector_family_rejects_unreleased_or_rewritten_endpoint_handoff(kind, fault):
    from atme.render.v2_timeline_replay import _replay_split_chronology

    layout, initial, clock = managed_endpoint_handoff_family(False, kind, fault)
    diagnostic = {
        "active": "Split managed connector needs completed disconnect before capture",
        "inflight": "Split managed connector needs completed disconnect before capture",
        "at_capture": "Split managed connector needs completed disconnect before capture",
        "reconnect": "Split managed connector cannot reconnect before Split completion",
        "endpoint_writer": "Split retained termination lost its exact frame, version or hierarchy",
        "ancestor_writer": "Split retained termination lost its exact frame, version or hierarchy",
        "isolate": "isolate on board-main overlaps another visual action",
    }[fault]
    with pytest.raises(ValueError, match=diagnostic):
        _replay_split_chronology(layout, initial, tuple(clock.actions), clock.duration_ms, {}, timeline=clock)


@pytest.mark.parametrize("kind", ["arrow", "network", "pointer"])
@pytest.mark.parametrize("key", ["endpoint-1", "endpoint-parent"])
@pytest.mark.parametrize("layer", ["pose_with_original_baseline", "payload_with_coherent_baseline"])
def test_split_connector_canonical_packet_rehash_cannot_replace_independent_current_read(kind, key, layer):
    layout, before, split, clock = parented_connector_family(False, kind)
    capture = capture_split(split, layout, before, {})
    initial, prefix = sample_for_layout(layout), tuple(clock.actions[:-1])
    fresh = layout
    if layer == "pose_with_original_baseline":
        state = before.object(key)
        changed = replace(state, transform=replace(state.transform,
            position=replace(state.transform.position, x=state.transform.position.x + 5.)))
        before = replace(before, objects=tuple(changed if row.object_id == key else row for row in before.objects))
    else:
        raw = layout.model_dump(mode="json")
        next(obj for obj in raw["objects"] if obj["object_id"] == key)["geometry"]["bounds"]["x"] += 5.
        fresh = ExecutableLayoutV2.model_validate(raw)
    _, _, resealed, _ = seal_current_connector(fresh, initial, before, split, clock, prefix)
    policy = resealed.action.split_policy.model_dump_json()
    basis = resealed.action.split_policy.source_basis.model_dump_json()
    forged = replace(capture, policy_json=policy, basis_json=basis,
                     completion_json=resealed.split_completion_receipt.model_dump_json())
    if layer == "payload_with_coherent_baseline":
        forged = replace(forged, baseline=tuple(before.object(row.object_id) for row in capture.baseline))
    assert forged.content_receipts == capture.content_receipts
    with pytest.raises(ValueError, match="captured read state|captured paint receipt|captured read content"):
        split_family_admission("source", forged, fresh, verify_split_paint_inputs(fresh, {}))
