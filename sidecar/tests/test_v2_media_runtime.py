"""P3-40 media uses the same native studio canvas, not a thumbnail renderer."""

import hashlib
import io
import subprocess
from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest
from PIL import Image
from test_v2_frame_state import supported_documents
from test_v2_image_placement_runtime import placement_documents, source_pixels
from test_v2_media_decode import (
    encoded_vfr as encoded_vfr,  # noqa: PLC0414 -- pytest fixture re-export
)
from v2_fixtures import digest

from atme.render import v2_media
from atme.render.animator import find_ffmpeg
from atme.render.v2_state import V2FrameError, evaluate_frame
from atme.render.v2_svg import compose_png_frame, compose_svg_frame
from atme.store.contracts_v2 import ExecutableLayoutV2


@pytest.fixture(scope="module")
def patterned_media():
    return patterned_media_bytes()


def patterned_media_bytes():
    """Lossless original video retains independently known source color regions."""
    with Image.open(io.BytesIO(source_pixels())) as image:
        first = image.convert("RGB")
        r, g, b = first.split()
        second, third = Image.merge("RGB", (g, b, r)), Image.merge("RGB", (b, r, g))
        raw = b"".join(frame.tobytes() for frame in (first, second, third))
    command = [find_ffmpeg(), "-hide_banner", "-v", "error", "-f", "rawvideo", "-pixel_format", "rgb24",
               "-video_size", "80x40", "-framerate", "1", "-i", "pipe:0",
               "-vf", "setpts=if(eq(N\\,0)\\,0\\,if(eq(N\\,1)\\,2\\,5))",
               "-fps_mode", "passthrough", "-c:v", "libx264rgb", "-crf", "0",
               "-movflags", "frag_keyframe+empty_moov", "-f", "mp4", "pipe:1"]
    result = subprocess.run(command, input=raw, capture_output=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    return result.stdout


def test_patterned_media_encoder_matches_existing_lossless_fixture(patterned_media):
    encoded = patterned_media_bytes()
    assert encoded == patterned_media
    assert v2_media.inspect_media(encoded, 0).pin.duration_ms == 6000


def install_media(layout, timeline, key, source, *, start=1000, out=6000):
    """Replace one real fixture endpoint, retaining its exact authored geometry."""
    base, clock, supplied = runtime_documents(source)
    media = deepcopy(base["objects"][2])
    old = next(obj for obj in layout["objects"] if obj["object_id"] == key)
    for field in ("object_id", "board_id", "parent_id", "clip_id", "geometry", "transform",
                  "anchors", "z_index", "semantic_role", "description", "coverage_ids",
                  "initial_state", "visible", "opacity"):
        if field in old:
            media[field] = deepcopy(old[field])
    media["style"] = {"stroke": None, "fill": None, "text": None, "effect": None}
    media["media_playback"].update(timeline_start_ms=start, source_out_ms=out)
    layout["objects"][layout["objects"].index(old)] = media
    timeline["resolved_assets"] = deepcopy(clock["resolved_assets"])
    timeline["layout_sha256"] = digest(layout)
    return media, supplied


def runtime_documents(source, *, portrait=False, kind="video"):
    layout, timeline, _ = placement_documents(portrait=portrait)
    pin = v2_media.inspect_media(source, 0).pin.model_dump(mode="json")
    obj = layout["objects"][2]
    placement = obj.pop("image_placement")
    placement["source_sha256"] = hashlib.sha256(source).hexdigest()
    obj.update(object_type=kind, visible=True, initial_state="visible", media_playback={
        "version": "1.0.0", "placement": placement, "source_duration_ms": 6000,
        "source_stream": pin, "source_in_ms": 0, "source_out_ms": 6000,
        "timeline_start_ms": 1000, "frame_selection": "last_pts_at_or_before",
    })
    # Preserve a real authored no-op fade and visible intrinsic state, so natural
    # media expiry cannot be mistaken for a committed hide/exit transition.
    _, fade_clock = supported_documents("fade")
    timeline["actions"][2] = deepcopy(fade_clock["actions"][2])
    timeline["actions"][2]["action"]["opacity"] = 1
    timeline["initial_object_states"][2] = deepcopy(fade_clock["initial_object_states"][2])
    for other in layout["objects"][:2]:
        other["opacity"] = 1
    asset = timeline["resolved_assets"][0]
    asset.update(kind=kind, media_type="video/mp4", byte_length=len(source),
                 checksum_sha256=hashlib.sha256(source).hexdigest(), duration_ms=6000,
                 media_stream=deepcopy(pin))
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline, {obj["asset_id"]: source}


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["video", "presenter", "screen_recording"])
def test_native_media_frames_and_existing_overlay_share_canvas(encoded_vfr, portrait, kind, tmp_path):
    layout, timeline, supplied = runtime_documents(encoded_vfr, portrait=portrait, kind=kind)
    first = compose_png_frame(layout, timeline, 5000, supplied)
    second = compose_png_frame(layout, timeline, 6000, supplied)
    assert "THE SYSTEM" in compose_svg_frame(layout, timeline, 5000, supplied).svg
    for frame, color in ((first, (0, 255, 0)), (second, (0, 0, 255))):
        with Image.open(io.BytesIO(frame.png)) as image:
            assert image.size == ((720, 1280) if portrait else (1280, 720))
            assert image.convert("RGB").getpixel((300, 300)) == color
    (tmp_path / f"native-{kind}-{portrait}.png").write_bytes(second.png)
    assert compose_png_frame(layout, timeline, 5000, supplied).png == first.png


def test_private_media_visual_view_preserves_intrinsic_snapshots(encoded_vfr):
    from atme.render.v2_media_view import media_visual_view

    layout, timeline, supplied = runtime_documents(encoded_vfr)
    key = layout["objects"][2]["object_id"]
    for at_ms, active in ((999, False), (1000, True), (6999, True), (7000, False)):
        snapshot = evaluate_frame(layout, timeline, at_ms)
        before = deepcopy(snapshot)
        assert snapshot.object(key).visible is True
        view = media_visual_view(ExecutableLayoutV2.model_validate(layout).objects, at_ms)
        assert (key in view.active_ids) is active
        assert (key in view.inactive_ids) is not active
        with pytest.raises(FrozenInstanceError):
            view.at_ms = 99
        assert snapshot == before
    with Image.open(io.BytesIO(compose_png_frame(layout, timeline, 7000, supplied).png)) as image:
        assert image.convert("RGB").getpixel((300, 300)) not in {(255, 0, 0), (0, 255, 0), (0, 0, 255)}


def test_media_pair_validation_is_technical_and_has_no_decoder_io(encoded_vfr, monkeypatch):
    layout, timeline, _ = runtime_documents(encoded_vfr)

    def forbidden(*_args, **_kwargs):
        pytest.fail("intrinsic state/history validation entered media decoder")

    monkeypatch.setattr(v2_media, "inspect_media", forbidden)
    monkeypatch.setattr(v2_media, "media_frame", forbidden)
    assert evaluate_frame(layout, timeline, 5000).object("object-evidence").visible


@pytest.mark.parametrize("mutation", ["range_overrun", "stream_inventory", "rotation_grant"])
def test_media_pair_rejects_invalid_bound_range_pins_or_permissions_before_paint(encoded_vfr, mutation):
    layout, timeline, _ = runtime_documents(encoded_vfr)
    if mutation == "range_overrun":
        layout["objects"][2]["media_playback"]["timeline_start_ms"] = 7000
    elif mutation == "stream_inventory":
        timeline["resolved_assets"][0]["media_stream"]["timestamps_sha256"] = "e" * 64
    else:
        layout["objects"][2]["transform"]["rotation_degrees"] = 15
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="media|range|permission|rotate"):
        evaluate_frame(layout, timeline, 0)


@pytest.mark.parametrize("at,active", [(999, False), (1000, True), (6999, True), (7000, False)])
def test_anchor_read_uses_exact_media_ink_window_without_changing_state(encoded_vfr, at, active):
    from test_v2_connector_svg import connector_documents

    from atme.render.v2_connector import connector_route
    from atme.render.v2_media_view import media_visual_view

    layout, clock = connector_documents()
    install_media(layout, clock, "object-system", encoded_vfr)
    # Obtain authentic intrinsic frames from a plain document: this direct
    # endpoint probe is separate from the retained-arrow history test below.
    plain, timing = connector_documents()
    sample = evaluate_frame(plain, timing, max(at, 5000))
    objects = {obj.object_id: obj for obj in ExecutableLayoutV2.model_validate(layout).objects}
    states = {row.object_id: row for row in sample.objects}
    before = deepcopy(states)
    if active:
        assert connector_route(objects["object-arrow"], objects, states, 2.6667,
                               media_view=media_visual_view(objects, at)).length > 0
    else:
        with pytest.raises(ValueError, match="media.*active visual anchor"):
            connector_route(objects["object-arrow"], objects, states, 2.6667,
                            media_view=media_visual_view(objects, at))
    assert states == before


@pytest.mark.parametrize("managed", [False, True])
def test_retained_arrow_rejects_natural_endpoint_expiry_even_on_earlier_seek(encoded_vfr, managed):
    from test_v2_connection_actions import relationship_documents
    from test_v2_connector_svg import connector_documents

    layout, clock = relationship_documents() if managed else connector_documents()
    install_media(layout, clock, "object-system", encoded_vfr, out=5000)
    # The connected/generic arrow still paints after the media's natural end
    # at 6000, although no authored endpoint hide or structural edit occurs.
    with pytest.raises(V2FrameError, match="media.*active visual anchor"):
        evaluate_frame(layout, clock, 5000)


def test_managed_arrow_finishing_before_media_expiry_remains_valid(encoded_vfr):
    from test_v2_connection_actions import relationship_documents

    layout, clock = relationship_documents()
    install_media(layout, clock, "object-system", encoded_vfr)
    assert evaluate_frame(layout, clock, 6999).object("object-system").visible
    assert not evaluate_frame(layout, clock, 7000).object("object-arrow").visible


@pytest.mark.parametrize("out,valid", [(6000, True), (5999, False)])
def test_callout_requires_media_through_exact_completed_pointer_exit(encoded_vfr, out, valid):
    from test_v2_callout_compositor import (
        LEADER,
        TARGET,
        add_action,
        compositor_documents,
        rebind,
    )

    layout, clock = compositor_documents()
    install_media(layout, clock, TARGET, encoded_vfr, out=out)
    add_action(clock, "exit", LEADER, 6000, 7000, post="removed")
    rebind(layout, clock)
    if valid:
        assert evaluate_frame(layout, clock, 7000).object(TARGET).visible
    else:
        with pytest.raises(ValueError, match="media.*active visual anchor"):
            evaluate_frame(layout, clock, 5000)


@pytest.mark.parametrize("kind", ["clip", "mask"])
def test_inactive_media_has_no_external_aperture_read_lifetime(encoded_vfr, kind):
    from test_v2_external_aperture_lifecycle import add_action
    from test_v2_external_aperture_runtime import (
        runtime_documents as aperture_documents,
    )

    _plan, layout, clock, ids = aperture_documents(kind)
    media, _ = install_media(layout, clock, "external-receiver", encoded_vfr, start=4000)
    grants = ["scale", "crop", "rotate", "mask"]
    media["media_playback"]["placement"]["allowed_transformations"] = grants[:]
    clock["resolved_assets"][0]["allowed_transformations"] = grants[:]
    owner = next(obj for obj in layout["objects"] if obj["object_id"] == ids["aperture"])
    move = deepcopy(clock["actions"][1]["action"])
    destination = deepcopy(owner["transform"])
    destination["position"]["x"] += 20.
    move.update(action_id="move-before-media-ink", target_ids=[ids["aperture"]], destination=destination)
    add_action(clock, move, 1000, 2000)
    clock["layout_sha256"] = digest(layout)
    # Owner motion before the media's first ink is legal, not a live read.
    assert evaluate_frame(layout, clock, 0).object("external-receiver").visible
    move["action_id"] = "move-during-media-ink"
    add_action(clock, move, 4500, 5000)
    with pytest.raises(V2FrameError, match="external aperture.*read lifetime conflicts"):
        evaluate_frame(layout, clock, 0)


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("fit,focal,points", [
    ("contain", (0.5, 0.5), [(225, 265, (220, 30, 30)), (375, 335, (240, 210, 20))]),
    ("contain", (0., 0.), [(225, 315, (220, 30, 30)), (375, 385, (240, 210, 20))]),
    ("contain", (1., 1.), [(225, 215, (220, 30, 30)), (375, 285, (240, 210, 20))]),
    ("cover", (0.5, 0.5), [(230, 275, (220, 30, 30)), (375, 380, (240, 210, 20))]),
    ("cover", (0., 0.), [(225, 220, (220, 30, 30)), (375, 380, (25, 50, 220))]),
    ("cover", (1., 1.), [(225, 220, (20, 190, 40)), (375, 380, (240, 210, 20))]),
])
def test_real_media_crop_fit_focal_pixels_in_both_profiles(patterned_media, portrait, fit, focal, points, tmp_path):
    layout, clock, supplied = runtime_documents(patterned_media, portrait=portrait)
    placement = layout["objects"][2]["media_playback"]["placement"]
    placement.update(fit=fit, focal_point={"x": focal[0], "y": focal[1]})
    clock["layout_sha256"] = digest(layout)
    first = compose_png_frame(layout, clock, 1000, supplied)
    second = compose_png_frame(layout, clock, 3000, supplied)
    with Image.open(io.BytesIO(first.png)) as image:
        for x, y, expected in points:
            assert image.convert("RGB").getpixel((x, y)) == expected
    with Image.open(io.BytesIO(second.png)) as image:
        for x, y, expected in points:
            assert image.convert("RGB").getpixel((x, y)) == (expected[1], expected[2], expected[0])
    assert second.png != first.png
    assert compose_png_frame(layout, clock, 1000, supplied).png == first.png
    (tmp_path / "media-crop-frame.png").write_bytes(second.png)


def test_two_views_of_same_source_keep_independent_playback_clocks(encoded_vfr):
    layout, clock, supplied = runtime_documents(encoded_vfr)
    second = deepcopy(layout["objects"][2])
    second.update(object_id="second-media-view", z_index=10)
    second["geometry"]["bounds"]["x"] = 500
    second["media_playback"]["source_in_ms"] = 2000
    layout["objects"].append(second)
    layout["boards"][0]["object_ids"].append(second["object_id"])
    clock["initial_object_states"].append({"object_id": second["object_id"], "state": "visible",
                                            "visible": True, "state_version": 1})
    clock["layout_sha256"] = digest(layout)
    with Image.open(io.BytesIO(compose_png_frame(layout, clock, 1000, supplied).png)) as image:
        assert image.convert("RGB").getpixel((300, 300)) == (255, 0, 0)
        assert image.convert("RGB").getpixel((600, 300)) == (0, 255, 0)


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["clip", "mask"])
@pytest.mark.parametrize("group", [False, True])
def test_media_paints_shared_external_aperture_with_literal_native_oracle(encoded_vfr, portrait, kind, group):
    from test_v2_external_aperture_runtime import (
        native_oracle,
        unclipped_documents,
    )
    from test_v2_external_aperture_runtime import (
        runtime_documents as aperture_documents,
    )

    _plan, layout, clock, ids = aperture_documents(kind, portrait=portrait, group=group)
    media, supplied = install_media(layout, clock, "external-receiver", encoded_vfr)
    media["media_playback"]["placement"]["allowed_transformations"] += ["rotate", "mask"]
    clock["resolved_assets"][0]["allowed_transformations"] += ["rotate", "mask"]
    clock["layout_sha256"] = digest(layout)
    # Reuse the independent native SVG factor-chain oracle, supplying actual
    # original source bytes instead of replacing the media with a still image.
    plain, timing = unclipped_documents(layout, clock)
    actual = compose_png_frame(layout, clock, 3000, supplied)
    assert actual.png != compose_png_frame(plain, timing, 3000, supplied).png
    assert actual.png == native_oracle(layout, clock, ids, kind, 3000, asset_bytes=supplied)


@pytest.mark.parametrize("portrait", [False, True])
def test_media_keeps_existing_global_camera_and_absolute_clock(encoded_vfr, portrait):
    from test_v2_camera_action import append_camera

    layout, clock, supplied = runtime_documents(encoded_vfr, portrait=portrait)
    layout["objects"][0]["geometry"]["bounds"] = {"x": 200, "y": 200, "width": 200, "height": 200}
    clock["layout_sha256"] = digest(layout)
    append_camera(clock, "media-camera", "camera_cut", 4000, 4500, target="object-system")
    before, after = evaluate_frame(layout, clock, 3999), evaluate_frame(layout, clock, 4500)
    assert after.object("object-evidence").transform == before.object("object-evidence").transform
    assert after.camera.width < before.camera.width
    first = compose_png_frame(layout, clock, 4500, supplied)
    assert (0, 255, 0) in set(Image.open(io.BytesIO(first.png)).convert("RGB").get_flattened_data())
    compose_png_frame(layout, clock, 6000, supplied)
    assert compose_png_frame(layout, clock, 4500, supplied).png == first.png


@pytest.mark.parametrize("fault", ["cover", "local_rotate", "ancestor_rotate", "clip", "rotate_action"])
@pytest.mark.parametrize("permitted", [False, True])
def test_media_initial_and_zero_progress_permissions_use_shared_rule(encoded_vfr, fault, permitted):
    from test_v2_image_placement_runtime import image_parent

    layout, clock, supplied = runtime_documents(encoded_vfr)
    media = layout["objects"][2]
    placement = media["media_playback"]["placement"]
    needed = "crop" if fault == "cover" else "mask" if fault == "clip" else "rotate"
    grants = ["scale"] if fault == "cover" else ["scale", "crop"]
    if permitted:
        grants.append(needed)
    placement["allowed_transformations"] = grants[:]
    clock["resolved_assets"][0]["allowed_transformations"] = grants[:]
    if fault == "cover":
        placement.update(crop={"x": 0, "y": 0, "width": 80, "height": 40}, fit="cover")
    elif fault == "local_rotate":
        media["transform"]["rotation_degrees"] = 15
    elif fault in {"ancestor_rotate", "clip"}:
        image_parent(layout, clock, kind="clip" if fault == "clip" else "group",
                     rotation=0 if fault == "clip" else 15)
    else:
        clock["actions"][2] = deepcopy(supported_documents("rotate")[1]["actions"][2])
        clock["actions"][2]["action"]["expected_state"] = "visible"
    clock["layout_sha256"] = digest(layout)
    if permitted:
        assert evaluate_frame(layout, clock, 0).object(media["object_id"]).visible
        assert compose_svg_frame(layout, clock, 5000, supplied).svg
    else:
        with pytest.raises(V2FrameError, match=f"media_playback.*{needed}"):
            evaluate_frame(layout, clock, 0)


@pytest.mark.parametrize("fault", ["resolved_pin", "range", "current_rotation", "checksum", "uri", "mutable_bytes"])
def test_private_native_media_boundary_rechecks_its_exact_resources(encoded_vfr, fault):
    from dataclasses import replace

    from atme.render.v2_svg import UnsupportedVisualObject, _compose_validated_svg_frame
    from atme.store.contracts_v2 import ResolvedVisualTimelineV2

    layout, clock, supplied = runtime_documents(encoded_vfr)
    snapshot = evaluate_frame(layout, clock, 5000)
    if fault == "resolved_pin":
        clock["resolved_assets"][0]["media_stream"]["timestamps_sha256"] = "e" * 64
    elif fault == "range":
        layout["objects"][2]["media_playback"]["timeline_start_ms"] = 7000
    elif fault == "current_rotation":
        original = snapshot.object("object-evidence")
        changed = replace(original, transform=replace(original.transform, rotation_degrees=15))
        snapshot = replace(snapshot, objects=tuple(changed if row.object_id == changed.object_id else row
                                                   for row in snapshot.objects))
    elif fault == "checksum":
        supplied["a" * 32] += b"unexpected appended bytes"
    elif fault == "uri":
        clock["resolved_assets"][0]["managed_ref"] = "https://example.invalid/video.mp4"
    else:
        supplied["a" * 32] = bytearray(encoded_vfr)
    with pytest.raises(UnsupportedVisualObject, match="media|source"):
        _compose_validated_svg_frame(ExecutableLayoutV2.model_validate(layout),
            ResolvedVisualTimelineV2.model_validate(clock), snapshot, {}, supplied)


@pytest.mark.parametrize("state", ["not_started", "expired", "active"])
def test_isolation_cannot_count_inactive_media_as_its_only_secondary_ink(encoded_vfr, state):
    from test_v2_isolate_action import isolate_documents

    layout, clock = isolate_documents()
    start, out = {"not_started": (5000, 5000), "expired": (0, 4000), "active": (1000, 6000)}[state]
    install_media(layout, clock, "object-system", encoded_vfr, start=start, out=out)
    layout["objects"][1]["opacity"] = 0
    clock["layout_sha256"] = digest(layout)
    if state == "active":
        assert evaluate_frame(layout, clock, 4450).object("object-system").opacity == pytest.approx(.35)
    else:
        with pytest.raises(V2FrameError, match="visible secondary context"):
            evaluate_frame(layout, clock, 4450)


@pytest.mark.parametrize("leader", [False, True])
@pytest.mark.parametrize("valid", [False, True])
def test_annotation_media_target_must_outlive_reading_and_retained_pointer(encoded_vfr, leader, valid):
    from test_v2_annotation_action import append_target
    from test_v2_annotation_contract import annotation_documents, leader_documents

    _plan, layout, clock = leader_documents() if leader else annotation_documents()
    install_media(layout, clock, "object-system", encoded_vfr,
                  start=3000 if leader else 2000, out=6000 if valid else 5999)
    if leader:
        append_target(clock, "annotation-leader", "exit", 8000, 9000)
    if valid:
        assert evaluate_frame(layout, clock, 7000).object("object-system").visible
    else:
        with pytest.raises(V2FrameError, match="media.*active visual anchor"):
            evaluate_frame(layout, clock, 5000)


def test_media_clock_continues_while_authored_opacity_hides_it(encoded_vfr):
    from test_v2_callout_compositor import add_action

    layout, clock, supplied = runtime_documents(encoded_vfr)
    hidden = add_action(clock, "fade", "object-evidence", 1000, 1500)
    hidden["action"].update(destination=None, opacity=0.)
    clock["coverage"][0]["action_ids"].append(hidden["action"]["action_id"])
    clock["actions"].sort(key=lambda row: row["start_ms"])
    assert evaluate_frame(layout, clock, 3000).object("object-evidence").opacity == 0
    with Image.open(io.BytesIO(compose_png_frame(layout, clock, 5000, supplied).png)) as image:
        assert image.convert("RGB").getpixel((300, 300)) == (0, 255, 0)


@pytest.mark.parametrize("covered", [False, True])
def test_media_starting_inside_isolation_requires_a_captured_context_ancestor(encoded_vfr, covered):
    from test_v2_group_hierarchy import grouped_documents
    from test_v2_isolate_action import isolate_documents

    layout, clock = isolate_documents()
    install_media(layout, clock, "object-system", encoded_vfr, start=4500, out=5500)
    if covered:
        shell = deepcopy(grouped_documents()[0]["objects"][3])
        shell.update(object_id="media-context-parent", child_ids=["object-system", "object-label"], z_index=10)
        shell["transform"] = deepcopy(layout["objects"][0]["transform"])
        for obj in layout["objects"][:2]:
            obj["parent_id"] = shell["object_id"]
        layout["objects"].append(shell)
        layout["boards"][0]["object_ids"].append(shell["object_id"])
        clock["initial_object_states"].append({"object_id": shell["object_id"], "state": "visible",
                                                "visible": True, "state_version": 1})
    clock["layout_sha256"] = digest(layout)
    if covered:
        sample = evaluate_frame(layout, clock, 4450)
        assert sample.object("media-context-parent").opacity == pytest.approx(.35)
    else:
        with pytest.raises(V2FrameError, match="media.*captured context"):
            evaluate_frame(layout, clock, 4600)
