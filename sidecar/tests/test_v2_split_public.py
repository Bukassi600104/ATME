"""Task11 internal public Split uses the accepted capture and native painter."""

import io
import json
import socket
from copy import deepcopy
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path

import pytest
from atme.render import v2_state, v2_svg
from atme.render.v2_split_paint import verify_split_paint_inputs
from atme.render.v2_timeline_replay import replay_chronology, supports_operator
from PIL import Image
from test_v2_split_acceptance import split_benchmark
from test_v2_split_return import geometry_history
from v2_fixtures import digest


@pytest.fixture
def public_geometry():
    layout, initial, split, timeline = geometry_history(False)
    inputs = verify_split_paint_inputs(layout, {})
    context = v2_state._validate_pair_static(layout, timeline, timeline.layout_sha256, initial.hierarchy,
                                             split_inputs=inputs)
    replay, camera = v2_state._validate_consumer_history(context, split_inputs=inputs)
    return layout, initial, split, timeline, inputs, replay, camera


def test_public_policy_split_is_supported_without_admitting_bare_legacy(public_geometry):
    from atme.store.contracts_v2 import SplitAction
    from v2_split_fixtures import split_action

    assert supports_operator(public_geometry[2].action)
    assert not supports_operator(SplitAction.model_validate(split_action(policy=False)))


def test_public_assetless_frame_is_the_exact_private_split_sample(public_geometry):
    layout, _, _, timeline, _, replay, camera = public_geometry
    expected = v2_state._sample_validated_frame(layout, timeline, replay, camera, 20)
    assert v2_state.evaluate_frame(layout.model_dump(mode="json"), timeline.model_dump(mode="json"), 20) == expected


def test_public_chronology_requires_and_reuses_the_exact_paired_authority(public_geometry):
    layout, initial, _, timeline, inputs, expected, _ = public_geometry
    replay = replay_chronology({obj.object_id: obj for obj in layout.objects}, initial.hierarchy,
        {row.object_id: row for row in initial.objects}, dict(initial.state_versions), tuple(timeline.actions),
        tuple((row.board_id, row.start_ms, row.end_ms) for row in layout.activations), timeline.duration_ms,
        layout_document=layout.model_dump(mode="json"), timeline_document=timeline.model_dump(mode="json"),
        split_inputs=inputs)
    assert all(replay.at(at) == expected.at(at) for at in (40, 0, 12, 39, 24, 32, 12, 0, 40))


def test_public_svg_png_use_the_same_frozen_split_painter(public_geometry):
    layout, _, _, timeline, inputs, replay, camera = public_geometry
    frame = v2_state._sample_validated_frame(layout, timeline, replay, camera, 20)
    expected = v2_svg._compose_validated_svg_frame(layout, timeline, frame, {}, split_inputs=inputs)
    assert v2_svg.compose_svg_frame(layout.model_dump(mode="json"), timeline.model_dump(mode="json"), 20) == expected
    assert v2_svg.compose_png_frame(layout.model_dump(mode="json"), timeline.model_dump(mode="json"), 20).png == (
        v2_svg._rasterize_svg_frame(layout, expected, split_inputs=inputs).png)


def public_clock(layout, initial, timeline, inputs, **changes):
    ordinary = {row.action.action_id for row in timeline.actions if row.action.verb == "insert_evidence"}
    values = {"objects": {obj.object_id: obj for obj in layout.objects}, "hierarchy": initial.hierarchy,
        "frames": {row.object_id: row for row in initial.objects}, "state_versions": dict(initial.state_versions),
        "actions": tuple(timeline.actions), "activations": tuple((row.board_id, row.start_ms, row.end_ms)
                                                              for row in layout.activations),
        "duration_ms": timeline.duration_ms, "layout_document": layout.model_dump(mode="json"),
        "timeline_document": timeline.model_dump(mode="json"), "split_inputs": inputs,
        "evidence_treatments": tuple(row for row in layout.evidence_treatments if row.action_id in ordinary)}
    values.update(changes)
    return replay_chronology(**values)


@pytest.mark.parametrize("entry", ["frame", "chronology", "svg", "png"])
def test_public_bare_split_rejects_before_authority_or_static_paint(public_geometry, monkeypatch, entry):
    from atme.render import v2_split_paint
    from atme.render.v2_timeline_replay import ReplayError
    from atme.store.contracts_v2 import ResolvedVisualTimelineV2

    layout, initial, _, timeline, inputs, _, _ = public_geometry
    raw = timeline.model_dump(mode="json")
    for row in raw["actions"]:
        if row["action"]["verb"] == "split":
            row["action"].pop("split_policy")
            row.pop("split_completion_receipt", None)
    bare = ResolvedVisualTimelineV2.model_validate(raw)

    def forbidden(*args, **kwargs):
        raise AssertionError("bare Split reached authority or static paint bootstrap")

    monkeypatch.setattr(v2_split_paint, "_public_split_paint_inputs", forbidden)
    monkeypatch.setattr(v2_state, "_validate_pair_static", forbidden)
    error = ReplayError if entry == "chronology" else v2_state.UnsupportedVisualAction
    with pytest.raises(error, match="[Ss]plit"):
        if entry == "chronology":
            public_clock(layout, initial, bare, inputs)
        elif entry == "frame":
            v2_state.evaluate_frame(layout.model_dump(mode="json"), raw, 20, split_inputs=inputs)
        else:
            compose = v2_svg.compose_svg_frame if entry == "svg" else v2_svg.compose_png_frame
            compose(layout.model_dump(mode="json"), raw, 20, split_inputs=inputs)


def test_private_split_paint_still_requires_authored_policy(public_geometry):
    from atme.render.v2_split_paint import _validate_split_paint_modes
    from atme.store.contracts_v2 import ResolvedVisualTimelineV2

    layout, _, _, timeline, _, _, _ = public_geometry
    raw = timeline.model_dump(mode="json")
    for row in raw["actions"]:
        if row["action"]["verb"] == "split":
            row["action"].pop("split_policy")
            row.pop("split_completion_receipt", None)
    with pytest.raises(ValueError, match="authored policy"):
        _validate_split_paint_modes(ResolvedVisualTimelineV2.model_validate(raw),
                                    {obj.object_id: obj for obj in layout.objects})


PUBLIC_CASES = (
    ("geometry", "rectangle", "draw"), ("text", "nested", "write"), ("code", "tokens", "write"),
    ("callout", "boxed", "write"), ("chart", "bars", "draw"),
    ("visual", "illustration", "reveal"), ("visual", "character", "draw"), ("visual", "technical", "reveal"),
    ("registry", "part-1", "reveal"), ("container", "group", "reveal"), ("container", "clip", "reveal"),
    ("container", "mask-result", "reveal"), ("container", "instance", "reveal"),
    ("connector", "arrow", "reveal"), ("media", "image", "reveal"), ("media", "video", "enter"),
    ("media", "presenter", "reveal"), ("media", "screen_recording", "reveal"),
    ("evidence", "annotated", "enter"), ("evidence", "source", "reveal"),
)


@pytest.fixture(scope="module")
def public_benchmark():
    return split_benchmark()


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("family,kind,mode", PUBLIC_CASES)
def test_public_split_family_seams_keep_exact_private_state_svg_png_and_frozen_seeks(
        public_benchmark, tmp_path, monkeypatch, portrait, family, kind, mode):
    from atme.store.contracts_v2 import ResolvedVisualTimelineV2

    service = None
    if family == "evidence":
        from test_v2_split_evidence_family import short_evidence_documents

        service, layout, initial, timeline, carrier = short_evidence_documents(tmp_path, portrait, mode, variant=kind)
        split = next(row for row in timeline.actions if row.action.verb == "split")
    else:
        fixture = getattr(public_benchmark, "_" + family + "_fixture")
        extra = {"routing": "curve"} if family == "connector" else {}
        layout, initial, split, timeline, carrier = fixture(portrait, kind, mode, **extra)
    try:
        raw_layout, raw_timeline = layout.model_dump(mode="json"), timeline.model_dump(mode="json")
        # Bind the actual stored layout bytes, leaving all authored action packets/timing intact.
        raw_timeline["layout_sha256"] = digest(raw_layout)
        raw_timeline["plan_sha256"] = layout.plan_sha256
        timeline = ResolvedVisualTimelineV2.model_validate(raw_timeline)
        originals = deepcopy((raw_layout, raw_timeline))
        inputs = verify_split_paint_inputs(layout, carrier)
        public_assets = carrier if inputs.project_assets else None
        context = v2_state._validate_pair_static(layout, timeline, timeline.layout_sha256, initial.hierarchy,
                                                 split_inputs=inputs)
        expected, camera = v2_state._validate_consumer_history(context, split_inputs=inputs)
        ordinary = {row.action.action_id for row in timeline.actions if row.action.verb == "insert_evidence"}
        held = {key: v2_state._sample_validated_frame(layout, timeline, expected, camera, end)
                for key, policy, _, end in v2_svg._authored_annotation_bindings(timeline)
                if policy.leader_connector_id is not None}
        assert supports_operator(split.action)
        start, end = split.start_ms, split.end_ms
        times = (end, start, start + (end - start) // 2, end - 1, start, end)
        reference = {}
        for at in set(times):
            frame = v2_state._sample_validated_frame(layout, timeline, expected, camera, at)
            svg = v2_svg._compose_validated_svg_frame(layout, timeline, frame, held, carrier, split_inputs=inputs)
            reference[at] = frame, svg, v2_svg._rasterize_svg_frame(layout, svg, split_inputs=inputs).png

        def denied(*args, **kwargs):
            raise AssertionError("public frozen Split reopened original resources or network")

        original_open = Path.open
        decoder = None
        if family == "media" and kind != "image":
            from atme.render.v2_media import _decoder_identity

            decoder = _decoder_identity()

        def frozen_fonts_or_output(path, mode="r", *args, **kwargs):
            checked_tool = decoder is not None and mode == "rb" and path.resolve() == Path(decoder[0])
            if checked_tool:
                stat = path.stat()
                assert (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns) == decoder[1:4]
            if "r" in mode and not checked_tool and not any(part.startswith("atme-split-fonts-") for part in path.parts):
                raise AssertionError(f"public frozen Split reopened source: {path}")
            return original_open(path, mode, *args, **kwargs)

        with monkeypatch.context() as sealed:
            sealed.setattr(socket, "create_connection", denied)
            sealed.setattr(socket.socket, "connect", denied)
            sealed.setattr(Path, "read_bytes", denied)
            sealed.setattr(Path, "read_text", denied)
            sealed.setattr(Path, "open", frozen_fonts_or_output)
            if decoder is not None:
                for forbidden in (Path(decoder[0]).with_name("unselected-decoder.exe"), tmp_path / "original-media.mp4"):
                    with pytest.raises(AssertionError, match="reopened source"):
                        forbidden.open("rb")
            actual = public_clock(layout, initial, timeline, inputs)
            for at in times:
                assert actual.at(at) == expected.at(at)
            # Every family/profile crosses each actual public entry, with repeated/backward seeks.
            for at in (end, times[2], start, times[2]):
                frame, svg, png = reference[at]
                assert v2_state.evaluate_frame(raw_layout, raw_timeline, at, split_inputs=inputs) == frame
                assert v2_svg.compose_svg_frame(raw_layout, raw_timeline, at, public_assets, split_inputs=inputs) == svg
                assert v2_svg.compose_png_frame(raw_layout, raw_timeline, at, public_assets, split_inputs=inputs).png == png
            if decoder is not None:
                assert _decoder_identity() == decoder
        assert not ordinary or layout.evidence_treatments
        for at, (frame, svg, png) in reference.items():
            (tmp_path / f"public-{family}-{kind}-{portrait}-{at}.svg").write_bytes(svg.svg.encode("utf-8"))
            (tmp_path / f"public-{family}-{kind}-{portrait}-{at}.png").write_bytes(png)
            assert frame.at_ms == at
        if family == "media":
            from test_v2_split_media_family import literal_pixels

            for at in (start, end):
                with (Image.open(io.BytesIO(reference[at][2])) as actual_image,
                      Image.open(io.BytesIO(literal_pixels(portrait, mode, kind, start, at - start))) as literal):
                    assert actual_image.convert("RGBA").tobytes() == literal.convert("RGBA").tobytes()
        assert (raw_layout, raw_timeline) == originals
        summary = {"profile": layout.output_profile.profile_id, "family": family, "kind": kind, "mode": mode,
                   "frames": {str(at): {"png_sha256": sha256(png).hexdigest(), "svg_sha256": sha256(svg.svg.encode()).hexdigest(),
                                        "frame_sha256": sha256(json.dumps(asdict(frame), sort_keys=True).encode()).hexdigest()}
                              for at, (frame, svg, png) in reference.items()}}
        (tmp_path / "public-seam.json").write_text(json.dumps(summary, indent=2))
    finally:
        if service is not None:
            service.store.close()


@pytest.mark.parametrize("fault", ["missing", "dict", "empty", "wrong_type", "stale_layout", "missing_bundle", "changed_bytes"])
@pytest.mark.parametrize("entry", ["frame", "chronology", "svg", "png"])
def test_public_split_rejects_missing_unverified_or_stale_asset_authority(fault, entry):
    from test_v2_split_media_family import media_family

    layout, initial, _, timeline, carrier, _ = media_family()
    raw_layout, raw_timeline = layout.model_dump(mode="json"), timeline.model_dump(mode="json")
    raw_timeline["layout_sha256"] = digest(raw_layout)
    from atme.store.contracts_v2 import ResolvedVisualTimelineV2

    timeline = ResolvedVisualTimelineV2.model_validate(raw_timeline)
    inputs = verify_split_paint_inputs(layout, carrier)
    if fault == "missing": inputs = None
    elif fault == "dict": inputs = asdict(inputs)
    elif fault == "empty": inputs = {}
    elif fault == "wrong_type": inputs = object()
    elif fault == "stale_layout": inputs = replace(inputs, layout_sha256="0"*64)
    elif fault == "missing_bundle": inputs = replace(inputs, bundle_bytes=())
    else:
        row = inputs.project_assets[0]
        inputs = replace(inputs, project_assets=(replace(row, payload=b"unverified"),))
    with pytest.raises(ValueError):
        if entry == "frame": v2_state.evaluate_frame(raw_layout, raw_timeline, 3, split_inputs=inputs)
        elif entry == "chronology": public_clock(layout, initial, timeline, inputs)
        else:
            # Raw project bytes never become trusted authority when the carrier is missing.
            getattr(v2_svg, "compose_" + entry + "_frame")(
                raw_layout, raw_timeline, 3, dict(carrier), split_inputs=inputs)


@pytest.mark.parametrize("entry", ["svg", "png"])
@pytest.mark.parametrize("raw_map", [False, True])
def test_public_trusted_asset_carrier_freezes_once_and_raw_map_cannot_substitute(monkeypatch, entry, raw_map):
    from atme.render import v2_split_paint
    from atme.store.contracts_v2 import ResolvedVisualTimelineV2
    from test_v2_split_media_family import media_family

    layout, initial, _, timeline, carrier, _ = media_family()
    raw_layout, raw_timeline = layout.model_dump(mode="json"), timeline.model_dump(mode="json")
    raw_timeline.update(layout_sha256=digest(raw_layout), plan_sha256=layout.plan_sha256)
    timeline = ResolvedVisualTimelineV2.model_validate(raw_timeline)
    reference_inputs = verify_split_paint_inputs(layout, carrier)
    context = v2_state._validate_pair_static(layout, timeline, timeline.layout_sha256, initial.hierarchy,
                                             split_inputs=reference_inputs)
    replay, camera = v2_state._validate_consumer_history(context, split_inputs=reference_inputs)
    frame = v2_state._sample_validated_frame(layout, timeline, replay, camera, 3)
    expected_svg = v2_svg._compose_validated_svg_frame(layout, timeline, frame, {}, carrier, split_inputs=reference_inputs)
    expected_png = v2_svg._rasterize_svg_frame(layout, expected_svg, split_inputs=reference_inputs).png
    if raw_map:
        with pytest.raises(ValueError, match="trusted.*asset"):
            getattr(v2_svg, "compose_" + entry + "_frame")(raw_layout, raw_timeline, 3, dict(carrier))
        return
    freeze, checked, original_open = verify_split_paint_inputs, v2_split_paint._checked_split_resources, Path.open
    built, observed = [], []

    def frozen_only(path, mode="r", *args, **kwargs):
        if "r" in mode and not any(part.startswith("atme-split-fonts-") for part in path.parts):
            raise AssertionError("trusted-carrier public entry reopened source after freezing")
        return original_open(path, mode, *args, **kwargs)

    def once(typed_layout, assets):
        assert assets is carrier
        result = freeze(typed_layout, assets)
        built.append(result)
        monkeypatch.setattr(Path, "open", frozen_only)
        monkeypatch.setattr(Path, "read_bytes", lambda *args: pytest.fail("source reopened after freeze"))
        return result

    def observe(typed_layout, inputs):
        observed.append(inputs)
        return checked(typed_layout, inputs)

    monkeypatch.setattr(v2_split_paint, "verify_split_paint_inputs", once)
    monkeypatch.setattr(v2_split_paint, "_checked_split_resources", observe)
    result = getattr(v2_svg, "compose_" + entry + "_frame")(raw_layout, raw_timeline, 3, carrier)
    assert result == expected_svg if entry == "svg" else result.png == expected_png
    assert len(built) == 1 and observed and all(inputs is built[0] for inputs in observed)


@pytest.mark.parametrize("fault", ["objects", "frames", "hierarchy", "versions", "activations", "actions", "duration",
                                  "layout_digest", "timeline", "missing_layout", "missing_timeline", "treatments"])
def test_public_chronology_rejects_contradictory_low_level_and_paired_inputs(public_geometry, fault):
    layout, initial, _, timeline, inputs, _, _ = public_geometry
    changes = {}
    if fault == "objects": changes["objects"] = {}
    elif fault == "frames": changes["frames"] = {row.object_id: replace(row, opacity=.5) for row in initial.objects}
    elif fault == "hierarchy": changes["hierarchy"] = replace(initial.hierarchy, nodes=initial.hierarchy.nodes[:-1])
    elif fault == "versions": changes["state_versions"] = {key: value + 1 for key, value in initial.state_versions}
    elif fault == "activations": changes["activations"] = ()
    elif fault == "actions": changes["actions"] = ()
    elif fault == "duration": changes["duration_ms"] = timeline.duration_ms + 1
    elif fault == "layout_digest":
        raw = timeline.model_dump(mode="json")
        raw["layout_sha256"] = "0"*64
        changes["timeline_document"] = raw
    elif fault == "timeline": changes["timeline_document"] = {}
    elif fault == "missing_layout": changes["layout_document"] = None
    elif fault == "missing_timeline": changes["timeline_document"] = None
    else: changes["evidence_treatments"] = (object(),)
    with pytest.raises(ValueError):
        public_clock(layout, initial, timeline, inputs, **changes)


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["geometry", "count-group", "group-count", "morph", "descendants"])
def test_public_split_retained_returns_keep_a_b_a_state_versions_and_native_pixels(tmp_path, kind, portrait):
    from atme.render.v2_hierarchy import HierarchySnapshot
    from test_v2_split_return import retained_history

    layout, timeline = retained_history(kind, portrait)
    inputs = verify_split_paint_inputs(layout, {})
    raw_layout, raw_timeline = layout.model_dump(mode="json"), timeline.model_dump(mode="json")
    context = v2_state._validate_pair_static(layout, timeline, timeline.layout_sha256,
        HierarchySnapshot.from_objects({row.object_id: row for row in layout.objects}), split_inputs=inputs)
    replay, camera = v2_state._validate_consumer_history(context, split_inputs=inputs)
    frames, outputs = {}, {}
    for at in (3000, 1999, 2500, 3000):
        expected = v2_state._sample_validated_frame(layout, timeline, replay, camera, at)
        assert v2_state.evaluate_frame(raw_layout, raw_timeline, at, split_inputs=inputs) == expected
        svg = v2_svg._compose_validated_svg_frame(layout, timeline, expected, {}, split_inputs=inputs)
        png = v2_svg._rasterize_svg_frame(layout, svg, split_inputs=inputs).png
        assert v2_svg.compose_png_frame(raw_layout, raw_timeline, at, split_inputs=inputs).png == png
        if at in outputs: assert outputs[at] == png
        outputs[at], frames[at] = png, expected
    assert frames[1999].objects == frames[3000].objects and frames[1999].hierarchy == frames[3000].hierarchy
    assert replay.at(1999).state_versions == replay.at(3000).state_versions
    assert not any(row.visible for row in frames[2500].objects)
    assert outputs[1999] == outputs[3000] != outputs[2500]
    (tmp_path / f"public-return-{kind}-{portrait}.png").write_bytes(outputs[3000])


@pytest.mark.parametrize("entry", ["frame", "svg", "png", "chronology"])
def test_public_split_rejects_unsupported_geometry_write_without_a_fallback(entry):
    from atme.store.contracts_v2 import ResolvedVisualTimelineV2
    from test_v2_split_compositor import geometry_paint_frames
    from test_v2_split_identity import sample_for_layout

    layout, timeline, _ = geometry_paint_frames("write")
    raw_layout, raw_timeline = layout.model_dump(mode="json"), timeline.model_dump(mode="json")
    raw_timeline["layout_sha256"] = digest(raw_layout)
    raw_timeline["plan_sha256"] = layout.plan_sha256
    timeline = ResolvedVisualTimelineV2.model_validate(raw_timeline)
    inputs = verify_split_paint_inputs(layout, {})
    with pytest.raises(ValueError, match="[Ss]plit.*write.*geometry"):
        if entry == "frame": v2_state.evaluate_frame(raw_layout, raw_timeline, 270, split_inputs=inputs)
        elif entry == "chronology": public_clock(layout, sample_for_layout(layout), timeline, inputs)
        else: getattr(v2_svg, "compose_" + entry + "_frame")(raw_layout, raw_timeline, 270, split_inputs=inputs)


@pytest.mark.parametrize("fault", ["equal", "wrong_type", "stale_bytes", "changed_artwork", "missing_artwork", "metadata"])
def test_public_split_supplied_registry_authority_must_equal_independent_frozen_inputs(public_benchmark, fault):
    from atme.render.style_bundle import registry_endpoint_inputs_for_objects
    from atme.render.v2_registry import registry_endpoint_inputs
    from atme.render.v2_split_paint import _checked_split_resources

    layout, _, _, timeline, carrier = public_benchmark._registry_fixture(False, "part-1", "reveal")
    inputs = verify_split_paint_inputs(layout, carrier)
    resources = _checked_split_resources(layout, inputs)
    expected = registry_endpoint_inputs_for_objects({obj.object_id: obj for obj in layout.objects}, frozen_files=resources[2])
    supplied = registry_endpoint_inputs(bytes(bytearray(expected.registry_payload)),
        {key: bytes(bytearray(raw)) for key, raw in expected.artworks})
    assert supplied is not expected and supplied == expected
    if fault == "wrong_type": supplied = asdict(supplied)
    elif fault == "stale_bytes": supplied = replace(supplied, registry_payload=supplied.registry_payload + b"\n")
    elif fault == "changed_artwork":
        key, raw = supplied.artworks[0]
        supplied = replace(supplied, artworks=((key, raw + b"\n"), *supplied.artworks[1:]))
    elif fault == "missing_artwork": supplied = replace(supplied, artworks=())
    elif fault == "metadata":
        raw = json.loads(supplied.registry_payload)
        raw["version"] = "contradictory-caller-metadata"
        supplied = replace(supplied, registry_payload=json.dumps(raw).encode())
    raw_layout, raw_timeline = layout.model_dump(mode="json"), timeline.model_dump(mode="json")
    if fault == "equal":
        assert v2_state._evaluate_frame_with_registry_inputs(raw_layout, raw_timeline, 20, supplied, split_inputs=inputs) == (
            v2_state.evaluate_frame(raw_layout, raw_timeline, 20, split_inputs=inputs))
    else:
        with pytest.raises(ValueError, match="[Ss]plit.*registry|registry.*[Ss]plit"):
            v2_state._evaluate_frame_with_registry_inputs(raw_layout, raw_timeline, 20, supplied, split_inputs=inputs)


@pytest.mark.parametrize("entry", ["svg", "png"])
@pytest.mark.parametrize("asset_backed", [False, True])
@pytest.mark.parametrize("raw_map", [False, True])
def test_public_simultaneous_asset_authority_requires_exact_typed_rows_but_private_compatibility_remains(
        entry, asset_backed, raw_map):
    from atme.render.v2_split_paint import _checked_split_resources
    from atme.store.contracts_v2 import ResolvedVisualTimelineV2
    from test_v2_split_media_family import media_family

    if asset_backed:
        layout, initial, _, timeline, carrier, _ = media_family()
    else:
        layout, initial, _, timeline = geometry_history()
        carrier = {}
    raw_layout, raw_timeline = layout.model_dump(mode="json"), timeline.model_dump(mode="json")
    raw_timeline.update(layout_sha256=digest(raw_layout), plan_sha256=layout.plan_sha256)
    timeline = ResolvedVisualTimelineV2.model_validate(raw_timeline)
    inputs = verify_split_paint_inputs(layout, carrier)
    typed = _checked_split_resources(layout, inputs)[3]
    independently_typed = type(typed)(tuple(typed.rows))
    assert independently_typed is not typed and independently_typed.rows == inputs.project_assets
    context = v2_state._validate_pair_static(layout, timeline, timeline.layout_sha256, initial.hierarchy,
                                             split_inputs=inputs)
    replay, camera = v2_state._validate_consumer_history(context, split_inputs=inputs)
    frame = v2_state._sample_validated_frame(layout, timeline, replay, camera, 3)
    expected_svg = v2_svg._compose_validated_svg_frame(layout, timeline, frame, {}, typed, split_inputs=inputs)
    expected_png = v2_svg._rasterize_svg_frame(layout, expected_svg, split_inputs=inputs).png
    # This existing private legacy seam is deliberately unchanged by public admission.
    assert v2_svg._compose_validated_svg_frame(layout, timeline, frame, {}, dict(typed), split_inputs=inputs) == expected_svg
    compose = getattr(v2_svg, "compose_" + entry + "_frame")
    if raw_map:
        with pytest.raises(ValueError, match="[Ss]plit.*trusted|[Ss]plit.*typed"):
            compose(raw_layout, raw_timeline, 3, dict(typed), split_inputs=inputs)
    else:
        actual = compose(raw_layout, raw_timeline, 3, independently_typed, split_inputs=inputs)
        assert actual == expected_svg if entry == "svg" else actual.png == expected_png


@pytest.mark.parametrize("entry", ["svg", "png"])
@pytest.mark.parametrize("fault", ["missing_rows", "stale_row"])
def test_public_typed_asset_rows_must_match_before_frame_sampling(monkeypatch, entry, fault):
    from test_v2_split_media_family import media_family

    layout, _, _, timeline, carrier, _ = media_family()
    inputs = verify_split_paint_inputs(layout, carrier)
    raw_layout, raw_timeline = layout.model_dump(mode="json"), timeline.model_dump(mode="json")
    raw_timeline.update(layout_sha256=digest(raw_layout), plan_sha256=layout.plan_sha256)
    if fault == "missing_rows":
        supplied = type(carrier)(())
    else:
        row = carrier.rows[0]
        metadata = json.loads(row.resolved_json)
        metadata["revision"] += 1
        supplied = type(carrier)((replace(row, resolved_json=json.dumps(metadata, sort_keys=True, separators=(",", ":"))),))
    original, observed = v2_svg.evaluate_frame, []

    def observe(*args, **kwargs):
        observed.append(args[2])
        return original(*args, **kwargs)

    monkeypatch.setattr(v2_svg, "evaluate_frame", observe)
    with pytest.raises(ValueError):
        getattr(v2_svg, "compose_" + entry + "_frame")(raw_layout, raw_timeline, 3, supplied, split_inputs=inputs)
    assert observed == [], "contradictory public asset authority reached frame sampling"


@pytest.mark.parametrize("entry", ["frame", "chronology"])
def test_public_split_mask_read_does_not_authorize_mutating_its_definition(entry):
    from atme.store.contracts_v2 import ResolvedVisualTimelineV2
    from test_v2_split_container_family import mask_split_family
    from v2_fixtures import common_action

    layout, initial, _, timeline = mask_split_family()
    raw_layout, raw_timeline = layout.model_dump(mode="json"), timeline.model_dump(mode="json")
    raw_timeline.update(layout_sha256=digest(raw_layout), plan_sha256=layout.plan_sha256)
    owner = raw_timeline["actions"][0]
    mutation = {**common_action("mask-mutation", "instruction-mask"), "verb": "dim",
                "target_ids": ["part-1-mask-definition"], "expected_state": "visible", "post_state": "visible"}
    for key in ("source_instruction_id", "coverage_id", "fallback"):
        mutation[key] = owner["action"][key]
    next(row for row in raw_timeline["coverage"] if row["coverage_id"] == mutation["coverage_id"])["action_ids"].append(
        mutation["action_id"])
    raw_timeline["actions"].append({"action": mutation, "start_ms": 0, "end_ms": 1,
        "resolved_trigger": {**owner["resolved_trigger"], "source": mutation["trigger"]}})
    timeline = ResolvedVisualTimelineV2.model_validate(raw_timeline)
    inputs = verify_split_paint_inputs(layout, {})
    with pytest.raises(ValueError, match="mask-only source"):
        if entry == "frame":
            v2_state.evaluate_frame(raw_layout, raw_timeline, 0, split_inputs=inputs)
        else:
            public_clock(layout, initial, timeline, inputs)
