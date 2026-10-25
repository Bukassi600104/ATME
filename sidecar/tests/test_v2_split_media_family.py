"""S3-F06: authored image/video content, never generated source fragments."""

import base64
import builtins
import io
import json
import os
import socket
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest
import resvg_py
from PIL import Image
from test_v2_image_placement_runtime import placement_documents, source_pixels
from test_v2_media_runtime import (
    patterned_media as patterned_media,  # noqa: PLC0414 -- fixture re-export
)
from test_v2_split_families import geometry_split_family
from test_v2_split_identity import sample_for_layout
from v2_fixtures import digest

from atme.project_assets import VerifiedImageBytes, VerifiedMediaBytes
from atme.render.v2_media import inspect_media
from atme.render.v2_split import _observed_split_placements
from atme.render.v2_split_identity import SplitContentReceipt, split_content_receipts
from atme.render.v2_split_paint import (
    _freeze_verified_split_asset,
    _VerifiedSplitAssetBytes,
    prove_split_coverage,
    split_family_admission,
    verify_split_paint_inputs,
)
from atme.render.v2_state import _sample_validated_frame, camera_segments
from atme.render.v2_svg import _compose_validated_svg_frame, _rasterize_svg_frame
from atme.render.v2_timeline_replay import _replay_split_chronology
from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    ResolvedAction,
    ResolvedAsset,
    ResolvedVisualTimelineV2,
    SplitAssetPin,
    SplitPolicy,
    _split_expected_completion,
    _split_packet_digest,
)


def media_family(portrait=False, mode="reveal", *, raw=None, kind="image"):
    """Independently authored placement/ranges; asset pin from actual encoded bytes."""
    base, _, action, clock, *_ = geometry_split_family(portrait, "rectangle", mode)
    layout = base.model_dump(mode="json")
    template, asset_clock, _ = placement_documents(portrait=portrait)
    original = source_pixels() if raw is None else raw
    asset = deepcopy(asset_clock["resolved_assets"][0])
    asset.update(checksum_sha256=sha256(original).hexdigest(), byte_length=len(original))
    stream = None if kind == "image" else inspect_media(original, 0).pin
    if stream is not None:
        asset.update(kind=kind, media_type="video/mp4", duration_ms=stream.duration_ms,
                     media_stream=stream.model_dump(mode="json"))
    payloads, hashes = {}, {}
    for slot, old in enumerate(layout["objects"]):
        index = {"source": 0, "part-1": 1, "part-2": 2}[old["object_id"]]
        obj = deepcopy(template["objects"][2])
        for field in ("object_id", "board_id", "parent_id", "clip_id", "geometry", "transform",
                      "anchors", "z_index", "initial_state", "visible", "opacity"):
            obj[field] = deepcopy(old[field])
        # Different authored crops/focal/fit; not derived from source_region.
        placement = obj["image_placement"]
        placement.update(source_sha256=asset["checksum_sha256"], fit="cover" if index == 2 else "contain")
        placement["focal_point"] = {"x": float(index == 2), "y": .5}
        obj["object_type"] = kind
        if stream is not None:
            obj.pop("image_placement")
            obj["media_playback"] = {"version": "1.0.0", "placement": placement,
                "source_stream": stream.model_dump(mode="json"), "source_duration_ms": stream.duration_ms,
                "source_in_ms": 3000 if index == 2 else 0, "source_out_ms": stream.duration_ms,
                "timeline_start_ms": 0, "frame_selection": "last_pts_at_or_before"}
        # Explicit independent identity projection; no runtime identity producer.
        payload = {field: obj[field] for field in ("object_type", "geometry", "style", "anchors", "asset_id", "variant")}
        payload["image_placement" if stream is None else "media_playback"] = deepcopy(
            obj["image_placement" if stream is None else "media_playback"])
        payload["asset_bytes_sha256"] = sha256(original).hexdigest()
        payloads[obj["object_id"]] = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        hashes[obj["object_id"]] = sha256(payloads[obj["object_id"]].encode()).hexdigest()
        layout["objects"][slot] = obj
    typed = ExecutableLayoutV2.model_validate(layout)
    asset = ResolvedAsset.model_validate(asset)
    pin = SplitAssetPin(asset_id=asset.asset_id, revision=asset.revision, resource_uri=asset.managed_ref,
                        checksum_sha256=asset.checksum_sha256)
    verified = (VerifiedImageBytes(asset.asset_id, asset.revision, original, asset.checksum_sha256, 80, 40)
        if stream is None else VerifiedMediaBytes(asset.asset_id, asset.revision, original,
            asset.checksum_sha256, 80, 40, stream.model_dump_json()))
    carrier = _VerifiedSplitAssetBytes((_freeze_verified_split_asset(asset, pin, verified, layout=typed),))
    initial = sample_for_layout(typed)
    start = 0 if stream is None else 1995
    observed = replace(initial, at_ms=start)
    raw_action = action.model_dump(mode="json")
    raw_action.update(start_ms=start, end_ms=start + 10)
    policy = raw_action["action"]["split_policy"]
    basis = policy["source_basis"]
    receipts = {key: SplitContentReceipt(key, payloads[key], hashes[key]) for key in hashes}
    basis["placements"] = [row.model_dump(mode="json") for row in _observed_split_placements(
        observed, {obj.object_id: obj for obj in typed.objects}, set(hashes), receipts)]
    basis["asset_pins"] = [pin.model_dump(mode="json")]
    for row in policy["correspondences"]:
        row.update(source_content_sha256=hashes["source"], result_content_sha256=hashes[row["result_object_id"]])
    policy["source_basis_sha256"] = digest(basis)
    completion = _split_expected_completion(SplitPolicy.model_validate(policy))
    completion["completion_sha256"] = digest(completion)
    raw_action["split_completion_receipt"] = completion
    clock = clock.model_dump(mode="json")
    clock.update(actions=[raw_action], layout_sha256=digest(layout), resolved_assets=[asset.model_dump(mode="json")])
    return typed, initial, ResolvedAction.model_validate(raw_action), ResolvedVisualTimelineV2.model_validate(clock), carrier, hashes


def family_replay(layout, initial, action, clock, carrier):
    replay = _replay_split_chronology(layout, initial, (action,), clock.duration_ms, carrier)
    capture = next(row.split_capture for checkpoint in replay.checkpoints for row in checkpoint.active
                   if row.resolved.action.action_id == action.action.action_id)
    return replay, capture


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("mode", ["reveal", "enter"])
@pytest.mark.parametrize("kind", ["image", "video", "presenter", "screen_recording"])
def test_split_checked_asset_family_identity_native_pixels_and_coverage(portrait, mode, kind, patterned_media, tmp_path):
    layout, initial, action, clock, carrier, hashes = media_family(
        portrait, mode, raw=None if kind == "image" else patterned_media, kind=kind)
    # Independent expected content is checked before admission, never self-hashed.
    assert {row.object_id: row.content_sha256 for row in split_content_receipts(layout, initial, carrier)} == hashes
    replay, capture = family_replay(layout, initial, action, clock, carrier)
    inputs = verify_split_paint_inputs(layout, carrier)
    for key in hashes:
        admitted = split_family_admission(key, capture, layout, inputs)
        assert admitted.family == ("supporting image" if kind == "image" else "moving media")
        assert admitted.content_sha256 == hashes[key]
        assert admitted.mode == ("source_fade" if key == "source" else mode)
    proof = prove_split_coverage(capture, layout, inputs)
    assert proof.intervals[-1].painted_root_ids == ("part-1", "part-2")
    cameras = camera_segments(layout, clock, replay)
    outputs = {}
    for offset in (10, 0, 3, 5, 10, 3, 0):
        at = action.start_ms + offset
        snapshot = _sample_validated_frame(layout, clock, replay, cameras, at)
        svg = _compose_validated_svg_frame(layout, clock, snapshot, {}, carrier, split_inputs=inputs)
        png = _rasterize_svg_frame(layout, svg, split_inputs=inputs).png
        if offset in outputs:
            assert outputs[offset] == (svg.svg, png)
        outputs[offset] = svg.svg, png
        assert snapshot.hierarchy == initial.hierarchy
        assert dict(replay.at(at).state_versions) == {key: 1 + int(offset == 10) for key in hashes}
    # Actual native pixels must change as real VFR source frames change at 2000ms.
    with Image.open(io.BytesIO(outputs[10][1])) as image:
        assert image.size == ((720, 1280) if portrait else (1280, 720))
    assert outputs[0][1] != outputs[10][1]
    if kind != "image":
        # Before 2000ms part-1 samples the first RGB frame; at 2000ms it
        # samples the second, even though construction has not completed.
        x, y = (110, 445) if portrait else (410, 145)
        with (Image.open(io.BytesIO(outputs[3][1])) as before_boundary,
              Image.open(io.BytesIO(outputs[5][1])) as on_boundary):
            # Enter also translates the image; literal full-frame parity below
            # remains the oracle for its moving pixel location.
            if mode == "reveal":
                assert before_boundary.convert("RGB").getpixel((x, y)) == (220, 30, 30)
                assert on_boundary.convert("RGB").getpixel((x, y)) == (30, 30, 220)
    for offset in (0, 3, 5, 10):
        with (Image.open(io.BytesIO(outputs[offset][1])) as actual,
              Image.open(io.BytesIO(literal_pixels(portrait, mode, kind, action.start_ms, offset))) as expected):
            assert sha256(actual.convert("RGBA").tobytes()).hexdigest() == sha256(expected.convert("RGBA").tobytes()).hexdigest()
        (tmp_path / f"split-{kind}-{mode}-{portrait}-{offset}.png").write_bytes(outputs[offset][1])


def test_private_media_split_rejects_playback_beyond_resolved_duration(patterned_media):
    layout, initial, action, _clock, carrier, _ = media_family(raw=patterned_media, kind="video")
    with pytest.raises(ValueError, match="resolved.*duration"):
        _replay_split_chronology(layout, initial, (action,), action.end_ms + 1, carrier)


def literal_pixels(portrait, mode, kind, start, offset, *, move=False):
    """Literal native oracle: known crops/fit arithmetic, phase math and VFR RGB.

    Does not call the runtime placement, media decoder, Split clock or painter.
    """
    boxes = ([(160, 80), (100, 400), (160, 400)] if portrait else [(80, 100), (400, 100), (460, 100)])
    width, height = (720, 1280) if portrait else (1280, 720)
    fraction = min(1., offset / 6)
    fade = 1 - min(1., max(0., (offset - 2) / 6))
    body = [f'<rect width="{width}" height="{height}" fill="#FAF8F1"/>']
    for index, (x, y) in enumerate(boxes):
        alpha = fade if index == 0 else 1
        if alpha == 0 or index > 0 and fraction == 0:
            continue
        with Image.open(io.BytesIO(source_pixels())) as source:
            image = source.convert("RGBA" if kind == "image" else "RGB")
        if kind != "image":
            clock = start + offset + (3000 if index == 2 else 0)
            r, g, b = image.split()
            image = (Image.merge("RGB", (b, r, g)) if clock >= 5000 else
                     Image.merge("RGB", (g, b, r)) if clock >= 2000 else image)
        stream = io.BytesIO()
        image.crop((20, 10, 60, 30)).save(stream, format="PNG")
        encoded = base64.b64encode(stream.getvalue()).decode()
        dx, dy, w, h = (-160, 0, 240, 120) if index == 2 else (0, 40, 80, 40)
        inner = (f'<svg x="{x}" y="{y}" width="80" height="120" viewBox="0 0 80 120" overflow="hidden">'
                 f'<image x="{dx}" y="{dy}" width="{w}" height="{h}" preserveAspectRatio="none" '
                 f'href="data:image/png;base64,{encoded}"/></svg>')
        if index and fraction < 1:
            inner = (f'<defs><clipPath id="oracle-{index}"><rect x="{x}" y="{y}" width="{80*fraction}" '
                     f'height="120"/></clipPath></defs><g clip-path="url(#oracle-{index})">{inner}</g>')
        shift = -80 * (1 - fraction) if index and mode == "enter" else 0
        if index == 1 and move:
            shift += min(40., max(0., (offset - 6) * 10))
        body.append(f'<g opacity="{alpha:.4f}" transform="translate({shift:.4f} 0)">{inner}</g>')
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">{"".join(body)}</svg>'
    return resvg_py.svg_to_bytes(svg_string=svg, skip_system_fonts=True)


def reseal(layout, initial, action, clock, carrier, *, observed=None):
    """Coherent mutated fixture, so failures cannot hide behind stale hashes."""
    raw = deepcopy(action) if type(action) is dict else action.model_dump(mode="json")
    observed = replace(initial, at_ms=raw["start_ms"]) if observed is None else observed
    policy = raw["action"]["split_policy"]
    basis = policy["source_basis"]
    bound = {key for closure in (basis["source_closure"], *basis["result_closures"]) for key in closure["owned_ids"]}
    bound.update(key for row in basis["read_dependencies"] for key in row["object_ids"])
    receipts = {row.object_id: row for row in split_content_receipts(layout, observed, carrier)}
    objects = {obj.object_id: obj for obj in layout.objects}
    basis["placements"] = [row.model_dump(mode="json") for row in _observed_split_placements(observed, objects, bound, receipts)]
    referenced = {objects[key].asset_id for key in bound if objects[key].asset_id is not None}
    basis["asset_pins"] = [json.loads(row.pin_json) for row in carrier.rows if row.asset_id in referenced]
    for row in policy["correspondences"]:
        row.update(source_content_sha256=receipts["source"].content_sha256,
                   result_content_sha256=receipts[row["result_object_id"]].content_sha256)
    clock = clock.model_copy(update={"resolved_assets": [ResolvedAsset.model_validate_json(row.resolved_json)
                                                        for row in carrier.rows]}, deep=True)
    return reseal_policy(layout, initial, raw, clock), receipts


def reseal_policy(layout, initial, raw_action, clock):
    policy = raw_action["action"]["split_policy"]
    policy["source_basis_sha256"] = _split_packet_digest(policy["source_basis"])
    completion = _split_expected_completion(SplitPolicy.model_validate(policy))
    completion["completion_sha256"] = _split_packet_digest(completion)
    raw_action["split_completion_receipt"] = completion
    document = clock.model_dump(mode="json")
    document.update(layout_sha256=digest(layout.model_dump(mode="json")), actions=[raw_action], initial_object_states=[
        {"object_id": row.object_id, "state": row.state, "state_version": dict(initial.state_versions)[row.object_id],
         "visible": row.visible} for row in initial.objects])
    return ResolvedAction.model_validate(raw_action), ResolvedVisualTimelineV2.model_validate(document)


@pytest.mark.parametrize("bad_carrier", ["raw", "missing"])
def test_asset_chronology_rejects_unverified_or_missing_carrier(bad_carrier):
    layout, initial, action, clock, carrier, _ = media_family()
    supplied = dict(carrier) if bad_carrier == "raw" else _VerifiedSplitAssetBytes(())
    with pytest.raises(ValueError, match="trusted project asset inventory"):
        family_replay(layout, initial, action, clock, supplied)


@pytest.mark.parametrize("mutation", ["missing", "extra", "wrong_revision", "wrong_uri"])
def test_capture_recomputes_asset_pins_instead_of_accepting_self_hashed_claim(mutation):
    layout, initial, action, clock, carrier, _ = media_family()
    raw = action.model_dump(mode="json")
    pins = raw["action"]["split_policy"]["source_basis"]["asset_pins"]
    if mutation == "missing":
        pins.clear()
    elif mutation == "extra":
        pins.append({**pins[0], "asset_id": "b" * 32, "resource_uri": f"atme://projects/{layout.project_id}/assets/{'b'*32}"})
    else:
        pins[0].update({"revision": 2} if mutation == "wrong_revision" else {"resource_uri": "atme://wrong"})
    action, clock = reseal_policy(layout, initial, raw, clock)
    with pytest.raises(ValueError, match="submitted basis differs"):
        family_replay(layout, initial, action, clock, carrier)


def test_fresh_valid_carrier_does_not_authorize_old_capture():
    layout, initial, action, clock, carrier, _ = media_family()
    _, capture = family_replay(layout, initial, action, clock, carrier)
    raw = layout.model_dump(mode="json")
    for obj in raw["objects"]:
        obj["image_placement"]["source_revision"] = 2
    fresh_layout = ExecutableLayoutV2.model_validate(raw)
    row = carrier.rows[0]
    asset = ResolvedAsset.model_validate_json(row.resolved_json).model_copy(update={"revision": 2})
    pin = SplitAssetPin.model_validate_json(row.pin_json).model_copy(update={"revision": 2})
    verified = VerifiedImageBytes(asset.asset_id, 2, row.payload, asset.checksum_sha256, 80, 40)
    fresh = _VerifiedSplitAssetBytes((_freeze_verified_split_asset(asset, pin, verified, layout=fresh_layout),))
    inputs = verify_split_paint_inputs(fresh_layout, fresh)
    with pytest.raises(ValueError, match="captured asset pins differ"):
        split_family_admission("part-1", capture, fresh_layout, inputs)


@pytest.mark.parametrize("kind", ["image", "video", "presenter", "screen_recording"])
@pytest.mark.parametrize("mode", ["draw", "write"])
def test_asset_split_does_not_substitute_unsupported_construction(kind, mode, patterned_media):
    from atme.render.v2_split_paint import _split_primitive_paint

    layout, *_ = media_family(raw=None if kind == "image" else patterned_media, kind=kind)
    with pytest.raises(ValueError, match=f"Split {mode} is incompatible with"):
        _split_primitive_paint(layout.objects[0], mode)


@pytest.mark.parametrize("mutation", ["source_late_start", "source_early_end", "result_early_end"])
def test_media_lifetime_cannot_hide_behind_another_roots_positive_alpha(patterned_media, mutation):
    layout, _initial, action, clock, carrier, _ = media_family(raw=patterned_media, kind="video")
    raw = layout.model_dump(mode="json")
    key = "part-1" if mutation == "result_early_end" else "source"
    playback = next(obj for obj in raw["objects"] if obj["object_id"] == key)["media_playback"]
    if mutation == "source_late_start":
        playback["timeline_start_ms"] = action.start_ms + 1
    else:
        playback["source_out_ms"] = action.start_ms + 3
    layout = ExecutableLayoutV2.model_validate(raw)
    initial = sample_for_layout(layout)
    (action, clock), _ = reseal(layout, initial, action, clock, carrier)
    _, capture = family_replay(layout, initial, action, clock, carrier)
    inputs = verify_split_paint_inputs(layout, carrier)
    with pytest.raises(ValueError, match="active visual anchor"):
        prove_split_coverage(capture, layout, inputs)


def test_private_context_keeps_existing_asset_free_forged_initial_negative():
    from atme.render.v2_timeline_replay import _SplitReplayContext, replay_chronology

    layout, initial, *_ = geometry_split_family(False)
    altered = replace(initial, objects=tuple(replace(row, opacity=.2) if row.object_id == "source" else row
                                              for row in initial.objects))
    context = _SplitReplayContext(layout.model_dump_json(), (), altered)
    with pytest.raises(ValueError, match="authored initial"):
        replay_chronology({obj.object_id: obj for obj in layout.objects}, altered.hierarchy,
            {row.object_id: row for row in altered.objects}, dict(altered.state_versions), (),
            tuple((row.board_id, row.start_ms, row.end_ms) for row in layout.activations), 2000, _split_context=context)


def test_frozen_supporting_image_rejects_pin_uri_that_disagrees_with_resolved_owner():
    layout, _initial, _action, _clock, carrier, _ = media_family()
    row = carrier.rows[0]
    pin = json.loads(row.pin_json)
    pin["resource_uri"] = "atme://projects/999/assets/" + row.asset_id
    fake = _VerifiedSplitAssetBytes((replace(row, pin_json=json.dumps(pin, sort_keys=True, separators=(",", ":"))),))
    with pytest.raises(ValueError, match="pin|metadata|identity"):
        verify_split_paint_inputs(layout, fake)


def carrier_for(layout, old, *, permissions=None):
    """Re-resolve a coherent fixture using exact original bytes, never thumbnails."""
    row = old.rows[0]
    asset = ResolvedAsset.model_validate_json(row.resolved_json)
    if permissions is not None:
        asset = asset.model_copy(update={"allowed_transformations": permissions})
    pin = SplitAssetPin.model_validate_json(row.pin_json)
    verified = (VerifiedImageBytes(asset.asset_id, asset.revision, row.payload, asset.checksum_sha256, 80, 40)
        if asset.media_stream is None else VerifiedMediaBytes(asset.asset_id, asset.revision, row.payload,
            asset.checksum_sha256, 80, 40, asset.media_stream.model_dump_json()))
    return _VerifiedSplitAssetBytes((_freeze_verified_split_asset(asset, pin, verified, layout=layout),))


def compound_family(portrait, kind, root_id, container, original=None):
    layout, _, action, clock, carrier, _ = media_family(portrait, raw=original, kind=kind)
    raw = layout.model_dump(mode="json")
    permissions = ["scale", "crop", "mask"]
    for obj in raw["objects"]:
        placement = obj.get("image_placement") or obj["media_playback"]["placement"]
        placement["allowed_transformations"] = permissions[:]
    root = next(obj for obj in raw["objects"] if obj["object_id"] == root_id)
    leaf = deepcopy(root)
    leaf_id = root_id + "-pixels"
    leaf.update(object_id=leaf_id, parent_id=root_id, z_index=0, visible=True, initial_state="visible")
    leaf["transform"]["position"] = {"x": 0., "y": 0.}
    for name in ("variant", "image_placement", "media_playback"):
        root.pop(name, None)
    root.update(object_type=container, child_ids=[leaf_id], asset_id=None, anchors=[],
                style={"stroke": None, "fill": None, "text": None, "effect": None})
    raw["objects"].append(leaf)
    raw["boards"][0]["object_ids"].append(leaf_id)
    control_id = None
    if container == "clip":
        root["geometry"]["bounds"]["width"] /= 2
    elif container == "mask":
        geometry, *_ = geometry_split_family(portrait, "rectangle", "reveal")
        control = next(obj.model_dump(mode="json") for obj in geometry.objects if obj.object_id == root_id)
        control_id = root_id + "-stencil"
        control.update(object_id=control_id, z_index=99, visible=True, initial_state="visible", anchors=[],
                       beat_id=root["beat_id"], parent_id=root["parent_id"], clip_id=None,
                       style={"stroke": None, "fill": None, "text": None, "effect": None})
        control["geometry"]["bounds"]["width"] /= 2
        root.update(mask_mode="alpha", mask_source_object_id=control_id, mask_coordinate_space="parent_local",
                    invert=False, feather_px=0)
        raw["objects"].append(control)
        raw["boards"][0]["object_ids"].append(control_id)
    layout = ExecutableLayoutV2.model_validate(raw)
    carrier = carrier_for(layout, carrier, permissions=permissions)
    initial = sample_for_layout(layout)
    raw_action = action.model_dump(mode="json")
    basis = raw_action["action"]["split_policy"]["source_basis"]
    closure = basis["source_closure"] if root_id == "source" else next(
        row for row in basis["result_closures"] if row["root_id"] == root_id)
    closure["owned_ids"] = sorted((root_id, leaf_id))
    basis["read_dependencies"] = [{"kind": "ancestor", "object_ids": [root_id]}]
    if container in {"clip", "mask"}:
        basis["read_dependencies"].append({"kind": "aperture", "object_ids": [root_id]})
    if control_id is not None:
        basis["read_dependencies"].append({"kind": "mask_source", "object_ids": [control_id]})
    (action, clock), _ = reseal(layout, initial, raw_action, clock, carrier)
    return layout, initial, action, clock, carrier, leaf_id


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("container", ["group", "clip", "mask"])
@pytest.mark.parametrize("root_id", ["source", "part-2"])
@pytest.mark.parametrize("kind", ["image", "video"])
def test_compound_pixel_leaves_use_same_adapters_apertures_and_native_coverage(
    portrait, container, root_id, kind, patterned_media,
):
    layout, initial, action, clock, carrier, leaf_id = compound_family(
        portrait, kind, root_id, container, None if kind == "image" else patterned_media)
    replay, capture = family_replay(layout, initial, action, clock, carrier)
    inputs = verify_split_paint_inputs(layout, carrier)
    assert split_family_admission(root_id, capture, layout, inputs).family == "compound"
    assert split_family_admission(leaf_id, capture, layout, inputs).family == (
        "supporting image" if kind == "image" else "moving media")
    proof = prove_split_coverage(capture, layout, inputs)
    assert proof.intervals[-1].painted_root_ids == ("part-1", "part-2")
    original = initial.object(leaf_id)
    cameras = camera_segments(layout, clock, replay)
    outputs = {}
    for at in (action.end_ms, action.start_ms, action.start_ms + 3, action.end_ms):
        assert replay.at(at).object(leaf_id) == original
        assert dict(replay.at(at).state_versions)[leaf_id] == 1
        snapshot = _sample_validated_frame(layout, clock, replay, cameras, at)
        assert snapshot.hierarchy == initial.hierarchy
        frame = _compose_validated_svg_frame(layout, clock, snapshot, {}, carrier, split_inputs=inputs)
        png = _rasterize_svg_frame(layout, frame, split_inputs=inputs).png
        if at in outputs:
            assert sha256(png).digest() == outputs[at]
        outputs[at] = sha256(png).digest()
        if at == (action.start_ms if root_id == "source" else action.end_ms):
            obj = next(obj for obj in layout.objects if obj.object_id == leaf_id)
            x, y = int(obj.geometry.bounds.x), int(obj.geometry.bounds.y)
            with Image.open(io.BytesIO(png)) as image:
                assert image.convert("RGB").getpixel((x + 10, y + 45)) != (250, 248, 241)
                if container != "group":
                    assert image.convert("RGB").getpixel((x + 60, y + 45)) == (250, 248, 241)


@pytest.mark.parametrize("kind", ["image", "video"])
@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("mode", ["reveal", "enter"])
def test_pixel_family_post_construction_movement_matches_literal_native_oracle(kind, portrait, mode, patterned_media):
    layout, initial, action, clock, carrier, _ = media_family(portrait, mode,
        raw=None if kind == "image" else patterned_media, kind=kind)
    raw = action.model_dump(mode="json")
    result = next(row for row in raw["action"]["split_policy"]["results"] if row["object_id"] == "part-1")
    origin = deepcopy(result["destination"])
    destination = deepcopy(origin)
    destination["position"]["x"] = 40.
    result.update(movement={"phase": {"start_tick": 6000, "end_tick": 10000, "easing": "linear"},
                            "from_transform": origin, "destination": destination}, destination=destination)
    action, clock = reseal_policy(layout, initial, raw, clock)
    replay, capture = family_replay(layout, initial, action, clock, carrier)
    inputs = verify_split_paint_inputs(layout, carrier)
    assert prove_split_coverage(capture, layout, inputs).intervals[-1].painted_root_ids == ("part-1", "part-2")
    cameras = camera_segments(layout, clock, replay)
    for offset in (10, 3, 8, 10):
        snapshot = _sample_validated_frame(layout, clock, replay, cameras, action.start_ms + offset)
        frame = _compose_validated_svg_frame(layout, clock, snapshot, {}, carrier, split_inputs=inputs)
        actual = _rasterize_svg_frame(layout, frame, split_inputs=inputs).png
        expected = literal_pixels(portrait, mode, kind, action.start_ms, offset, move=True)
        with Image.open(io.BytesIO(actual)) as left, Image.open(io.BytesIO(expected)) as right:
            assert sha256(left.convert("RGBA").tobytes()).digest() == sha256(right.convert("RGBA").tobytes()).digest()


@pytest.mark.parametrize("kind", ["image", "video"])
@pytest.mark.parametrize("fault", ["rotate", "mask"])
def test_coherent_pixel_family_cannot_borrow_ungranted_transform_permission(kind, fault, patterned_media):
    if fault == "mask":
        layout, _initial, action, clock, carrier, _ = compound_family(
            False, kind, "source", "mask", None if kind == "image" else patterned_media)
        raw = layout.model_dump(mode="json")
        permissions = ["scale", "crop"]
        for obj in raw["objects"]:
            placement = obj.get("image_placement") or (obj.get("media_playback") or {}).get("placement")
            if placement is not None:
                placement["allowed_transformations"] = permissions
        layout = ExecutableLayoutV2.model_validate(raw)
        carrier = carrier_for(layout, carrier, permissions=permissions)
    else:
        layout, _initial, action, clock, carrier, _ = media_family(
            raw=None if kind == "image" else patterned_media, kind=kind)
        raw = layout.model_dump(mode="json")
        next(obj for obj in raw["objects"] if obj["object_id"] == "source")["transform"]["rotation_degrees"] = 15.
        layout = ExecutableLayoutV2.model_validate(raw)
    initial = sample_for_layout(layout)
    (action, clock), _ = reseal(layout, initial, action, clock, carrier)
    _, capture = family_replay(layout, initial, action, clock, carrier)
    inputs = verify_split_paint_inputs(layout, carrier)
    with pytest.raises(ValueError, match=f"{fault} permission|cannot {fault}|no {fault} permission"):
        prove_split_coverage(capture, layout, inputs)


def test_nonempty_image_does_not_attest_a_fully_transparent_authored_crop():
    layout, _initial, _action, _clock, carrier, _ = media_family()
    raw = layout.model_dump(mode="json")
    next(obj for obj in raw["objects"] if obj["object_id"] == "source")["image_placement"]["crop"] = {
        "x": 30, "y": 12, "width": 4, "height": 4}
    layout = ExecutableLayoutV2.model_validate(raw)
    with pytest.raises(ValueError, match="no placed painted pixels"):
        verify_split_paint_inputs(layout, carrier)


def test_mixed_count_then_media_split_threads_same_assets_through_origin_and_completion(patterned_media):
    from test_v2_split_capture import counted_boundary

    from atme.render.v2_timeline_replay import _capture_split_from_history

    counted, _old_initial, observed, prior, split = counted_boundary()
    media, _initial, _action, clock, carrier, _ = media_family(raw=patterned_media, kind="video")
    raw = counted.model_dump(mode="json")
    for index, old in enumerate(raw["objects"]):
        if old["object_id"] == "source":
            old["geometry"]["bounds"].update(width=320., height=120.)
            continue
        obj = next(row.model_dump(mode="json") for row in media.objects if row.object_id == old["object_id"])
        for field in ("geometry", "transform", "anchors", "z_index"):
            obj[field] = deepcopy(old[field])
        raw["objects"][index] = obj
    layout = ExecutableLayoutV2.model_validate(raw)
    initial = sample_for_layout(layout)
    (split, _clock), _ = reseal(layout, initial, split, clock, carrier, observed=observed)
    replay = _replay_split_chronology(layout, initial, (*prior, split), clock.duration_ms, carrier)
    capture = _capture_split_from_history(layout, initial, (*prior, split), len(prior), clock.duration_ms, carrier).split_capture
    assert capture == next(row.split_capture for cp in replay.checkpoints for row in cp.active
                           if row.resolved.action.action_id == split.action.action_id)
    assert replay.at(split.end_ms).object("source").display_text == "10 widgets"
    assert replay.at(split.end_ms).object("source").state == "removed"
    assert replay.at(split.end_ms).object("part-1").visible
    assert len(json.loads(capture.basis_json)["asset_pins"]) == 1
    assert split_family_admission("part-1", capture, layout, verify_split_paint_inputs(layout, carrier)).family == "moving media"


def test_capture_pins_only_owned_and_read_assets_not_unrelated_layout_inventory():
    layout, _initial, action, clock, carrier, _ = media_family()
    raw = layout.model_dump(mode="json")
    extra = deepcopy(raw["objects"][0])
    extra.update(object_id="unrelated-pixels", asset_id="b" * 32, z_index=99)
    raw["objects"].append(extra)
    raw["boards"][0]["object_ids"].append(extra["object_id"])
    layout = ExecutableLayoutV2.model_validate(raw)
    row = carrier.rows[0]
    asset = ResolvedAsset.model_validate_json(row.resolved_json).model_copy(update={
        "asset_id": extra["asset_id"], "managed_ref": f"atme://projects/{layout.project_id}/assets/{extra['asset_id']}"})
    pin = SplitAssetPin(asset_id=asset.asset_id, revision=asset.revision, resource_uri=asset.managed_ref,
                        checksum_sha256=asset.checksum_sha256)
    verified = VerifiedImageBytes(asset.asset_id, asset.revision, row.payload, asset.checksum_sha256, 80, 40)
    added = _freeze_verified_split_asset(asset, pin, verified, layout=layout)
    carrier = _VerifiedSplitAssetBytes(tuple(sorted((*carrier.rows, added), key=lambda value: value.asset_id)))
    initial = sample_for_layout(layout)
    (action, clock), _ = reseal(layout, initial, action, clock, carrier)
    _, capture = family_replay(layout, initial, action, clock, carrier)
    pins = json.loads(capture.basis_json)["asset_pins"]
    assert [pin["asset_id"] for pin in pins] == ["a" * 32]
    assert extra["object_id"] not in (*capture.owned_object_ids, *capture.read_dependency_ids)
    assert split_family_admission("part-1", capture, layout, verify_split_paint_inputs(layout, carrier)).family == "supporting image"


@pytest.mark.parametrize("kind", ["image", "video"])
def test_frozen_split_reuses_original_bytes_with_network_and_original_file_reads_denied(kind, patterned_media, monkeypatch, tmp_path):
    from atme.render import v2_media

    layout, initial, action, clock, carrier, _ = media_family(raw=None if kind == "image" else patterned_media, kind=kind)
    replay, capture = family_replay(layout, initial, action, clock, carrier)
    inputs = verify_split_paint_inputs(layout, carrier)
    cameras = camera_segments(layout, clock, replay)
    original_path = tmp_path / ("original.png" if kind == "image" else "original.mp4")
    original_path.write_bytes(carrier.rows[0].payload)
    original_sha = sha256(original_path.read_bytes()).digest()
    expected = {}
    for at in (action.start_ms + 3, action.end_ms):
        snapshot = _sample_validated_frame(layout, clock, replay, cameras, at)
        frame = _compose_validated_svg_frame(layout, clock, snapshot, {}, carrier, split_inputs=inputs)
        expected[at] = _rasterize_svg_frame(layout, frame, split_inputs=inputs).png
    real_open, real_builtin = Path.open, builtins.open

    def deny_original(path, *args, **kwargs):
        assert path.resolve() != original_path.resolve(), "Split reopened original source"
        return real_open(path, *args, **kwargs)

    def deny_builtin(file, *args, **kwargs):
        if isinstance(file, (str, bytes, os.PathLike)):
            assert Path(os.fsdecode(file)).resolve() != original_path.resolve(), "Split reopened original source"
        return real_builtin(file, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", deny_original)
        patch.setattr(builtins, "open", deny_builtin)
        patch.setattr(Path, "read_bytes", lambda *_: pytest.fail("Split reopened live resource"))
        patch.setattr(socket, "create_connection", lambda *_a, **_k: pytest.fail("Split used network"))
        patch.setattr(socket.socket, "connect", lambda *_a, **_k: pytest.fail("Split used network"))
        with v2_media._CACHE_LOCK:
            v2_media._INVENTORY_CACHE.clear()
            v2_media._FRAME_CACHE.clear()
        for at in (action.end_ms, action.start_ms + 3, action.end_ms):
            snapshot = _sample_validated_frame(layout, clock, replay, cameras, at)
            frame = _compose_validated_svg_frame(layout, clock, snapshot, {}, carrier, split_inputs=inputs)
            assert sha256(_rasterize_svg_frame(layout, frame, split_inputs=inputs).png).digest() == sha256(expected[at]).digest()
        assert json.loads(capture.basis_json)["asset_pins"] == json.loads(inputs.asset_pins_json)
    assert sha256(original_path.read_bytes()).digest() == original_sha


def duplicated_evidence_inputs(tmp_path):
    from test_v2_evidence_compositor import evidence_documents

    service, raw_layout, clock, verified = evidence_documents(tmp_path)
    copy_id = service.duplicate(raw_layout["project_id"])["project_id"]
    raw_layout["project_id"] = copy_id
    layout = ExecutableLayoutV2.model_validate(raw_layout)
    asset = ResolvedAsset.model_validate(clock["resolved_assets"][0])
    current_uri = f"atme://projects/{copy_id}/assets/{asset.asset_id}"
    assert asset.managed_ref != current_uri
    assert verified.treatment.asset_managed_ref == asset.managed_ref
    return service, layout, asset, verified, current_uri


@pytest.mark.parametrize("with_layout", [False, True])
@pytest.mark.parametrize("pin_owner", ["current", "origin", "foreign"])
def test_frozen_duplicate_evidence_separates_current_pin_and_immutable_origin(tmp_path, with_layout, pin_owner):
    service, layout, asset, verified, current_uri = duplicated_evidence_inputs(tmp_path)
    try:
        uri = {"current": current_uri, "origin": asset.managed_ref,
               "foreign": f"atme://projects/999/assets/{asset.asset_id}"}[pin_owner]
        pin = SplitAssetPin(asset_id=asset.asset_id, revision=asset.revision, resource_uri=uri,
                            checksum_sha256=asset.checksum_sha256)
        if pin_owner != ("current" if with_layout else "origin"):
            with pytest.raises(ValueError, match="metadata or pin"):
                _freeze_verified_split_asset(asset, pin, verified, layout=layout if with_layout else None)
            return
        row = _freeze_verified_split_asset(asset, pin, verified, layout=layout if with_layout else None)
        assert json.loads(row.pin_json)["resource_uri"] == uri
        assert json.loads(row.resolved_json)["managed_ref"] == asset.managed_ref
        assert json.loads(row.treatment_json)["asset_managed_ref"] == asset.managed_ref
        assert verified.treatment.asset_managed_ref == asset.managed_ref
        if with_layout:
            inputs = verify_split_paint_inputs(layout, _VerifiedSplitAssetBytes((row,)))
            assert json.loads(inputs.asset_pins_json) == [pin.model_dump(mode="json")]
            assert json.loads(inputs.project_assets[0].treatment_json)["asset_managed_ref"] == asset.managed_ref
    finally:
        service.store.close()


@pytest.mark.parametrize("with_layout", [False, True])
def test_frozen_duplicate_evidence_cannot_rewrite_treatment_origin_to_current_pin(tmp_path, with_layout):
    service, layout, asset, verified, current_uri = duplicated_evidence_inputs(tmp_path)
    try:
        pin = SplitAssetPin(asset_id=asset.asset_id, revision=asset.revision,
                            resource_uri=current_uri if with_layout else asset.managed_ref,
                            checksum_sha256=asset.checksum_sha256)
        forged = replace(verified, treatment=verified.treatment.model_copy(update={"asset_managed_ref": current_uri}))
        with pytest.raises(ValueError, match="evidence treatment"):
            _freeze_verified_split_asset(asset, pin, forged, layout=layout if with_layout else None)
        assert verified.treatment.asset_managed_ref == asset.managed_ref
    finally:
        service.store.close()


@pytest.mark.parametrize("kind", ["image", "video"])
@pytest.mark.parametrize("pin_owner", ["current", "foreign"])
def test_frozen_pixel_family_preserves_current_owner_pin_guard(kind, pin_owner, patterned_media):
    layout, _initial, _action, _clock, carrier, _ = media_family(
        raw=None if kind == "image" else patterned_media, kind=kind)
    row = carrier.rows[0]
    asset = ResolvedAsset.model_validate_json(row.resolved_json)
    pin = SplitAssetPin.model_validate_json(row.pin_json)
    current_uri = f"atme://projects/{layout.project_id}/assets/{asset.asset_id}"
    assert asset.managed_ref == pin.resource_uri == current_uri
    verified = (VerifiedImageBytes(asset.asset_id, asset.revision, row.payload, asset.checksum_sha256, 80, 40)
        if kind == "image" else VerifiedMediaBytes(asset.asset_id, asset.revision, row.payload,
            asset.checksum_sha256, 80, 40, asset.media_stream.model_dump_json()))
    if pin_owner == "foreign":
        pin = pin.model_copy(update={"resource_uri": f"atme://projects/999/assets/{asset.asset_id}"})
        with pytest.raises(ValueError, match="metadata or pin"):
            _freeze_verified_split_asset(asset, pin, verified, layout=layout)
    else:
        assert _freeze_verified_split_asset(asset, pin, verified, layout=layout) == row
