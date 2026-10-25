"""S3-F07: exact attested originals through the single Split family registry."""

import io
import json
import socket
from dataclasses import replace
from hashlib import sha256
from math import ceil
from pathlib import Path

import pytest
from PIL import Image
from test_v2_split_lifecycle import (
    readable_evidence_split_documents,
    source_evidence_handoff_documents,
)
from v2_fixtures import digest

from atme.render.v2_camera import camera_segments
from atme.render.v2_split_paint import (
    _split_primitive_paint,
    prove_split_coverage,
    split_family_admission,
    verify_split_paint_inputs,
)
from atme.render.v2_state import _sample_validated_frame
from atme.render.v2_svg import (
    UnsupportedVisualObject,
    _authored_annotation_bindings,
    _compose_validated_svg_frame,
    _rasterize_svg_frame,
)
from atme.render.v2_timeline_replay import _replay_split_chronology
from atme.store.contracts_v2 import ResolvedVisualTimelineV2


def short_evidence_documents(tmp_path, portrait, mode="reveal", *, variant="plain"):
    if variant == "source":
        service, layout, initial, timeline, carrier = source_evidence_handoff_documents(
            tmp_path, portrait, 4000, distinct_source=True)
    else:
        service, layout, initial, timeline, carrier = readable_evidence_split_documents(
            tmp_path, portrait, annotated=variant == "annotated")
    clock = timeline.model_dump(mode="json")
    action = next(row for row in clock["actions"] if row["action"]["verb"] == "split")
    start = action["start_ms"]
    action["end_ms"] = start + 40
    policy = action["action"]["split_policy"]
    if mode == "enter":
        for result in policy["results"]:
            result["construction"]["mode"] = "enter"
            result["construction"]["enter_destination"] = {
                **result["movement"]["from_transform"],
                "position": {"x": 10.0, "y": 0.0},
            }
            result["movement"]["from_transform"] = result["construction"]["enter_destination"]
            result["movement"]["phase"].update(start_tick=result["construction"]["phase"]["end_tick"], end_tick=10000)
    for index, window in enumerate(action["split_evidence_windows"]):
        construction = start + (24, 20)[index]
        movement = start + (40 if mode == "enter" else (16, 36)[index])
        hold = max(construction, movement)
        window.update(construction_complete_ms=construction, movement_complete_ms=movement,
                      readable_hold_start_ms=hold, readable_hold_end_ms=hold + 2500)
    receipt = action["split_completion_receipt"]
    receipt.update(policy_sha256=digest(policy), evidence_windows=action["split_evidence_windows"])
    receipt["completion_sha256"] = digest({key: value for key, value in receipt.items() if key != "completion_sha256"})
    timeline = ResolvedVisualTimelineV2.model_validate(clock)
    return service, layout, initial, timeline, carrier


def short_evidence_family(tmp_path, portrait, mode="reveal", *, variant="plain"):
    service, layout, initial, timeline, carrier = short_evidence_documents(tmp_path, portrait, mode, variant=variant)
    replay = _replay_split_chronology(layout, initial, tuple(timeline.actions), timeline.duration_ms,
                                      carrier, timeline=timeline)
    capture = next(row.split_capture for checkpoint in replay.checkpoints for row in checkpoint.active
                   if row.resolved.action.verb == "split")
    return service, layout, initial, timeline, carrier, replay, capture, verify_split_paint_inputs(layout, carrier)


@pytest.fixture(scope="module", params=[(portrait, mode, variant)
    for portrait in (False, True) for mode in ("reveal", "enter")
    for variant in ("plain", "annotated", "source")], ids=lambda row: "-".join(map(str, row)))
def evidence_family_boundary(request, tmp_path_factory):
    portrait, mode, variant = request.param
    directory = tmp_path_factory.mktemp("attested-family-" + request.node.name)
    return (directory, portrait, mode, variant, *short_evidence_family(directory, portrait, mode, variant=variant))


def test_split_evidence_family_admits_independently_authored_treatments(evidence_family_boundary):
    _, _, mode, variant, _, layout, _, _, carrier, _, capture, inputs = evidence_family_boundary
    identities = []
    for obj in layout.objects:
        if obj.object_type != "evidence":
            continue
        raw = obj.model_dump(mode="json")
        treatment = next(row for row in layout.evidence_treatments if row.object_id == obj.object_id)
        original = next(row.payload for row in carrier.rows if row.asset_id == obj.asset_id)
        payload = {key: raw[key] for key in ("object_type", "geometry", "style", "anchors", "asset_id", "variant")}
        payload.update(asset_bytes_sha256=sha256(original).hexdigest(),
                       evidence={"width": 900, "height": 500, "intent": treatment.intent.model_dump(mode="json")})
        admission = split_family_admission(obj.object_id, capture, layout, inputs)
        assert admission.family == "attested evidence"
        assert admission.mode == ("source_fade" if obj.object_id == "source" else mode)
        assert admission.proof_kind == "native_attested_evidence_alpha_v1"
        assert admission.content_sha256 == digest(payload)
        assert admission.paint_inputs_sha256 == inputs.inputs_sha256
        identities.append(admission.content_sha256)
    assert len(set(identities)) == (3 if variant == "source" else 2)


def test_split_evidence_family_proves_actual_native_continuous_coverage(evidence_family_boundary):
    _, _, _, _, _, layout, _, _, _, _, capture, inputs = evidence_family_boundary
    proof = prove_split_coverage(capture, layout, inputs)
    assert proof.proof_kind == "native_alpha_all_integer_ms_v1"
    assert proof.intervals[0].start_ms == capture.start_ms
    assert proof.intervals[-1].end_ms == capture.end_ms
    assert all(row.painted_root_ids for row in proof.intervals)


def test_split_evidence_family_native_pixels_and_frozen_shuffled_seek(evidence_family_boundary, monkeypatch):
    directory, portrait, _, variant, service, layout, _, timeline, carrier, replay, capture, inputs = evidence_family_boundary
    originals = {path: path.read_bytes() for path in directory.glob("external-*.png")}
    project = dict(service._row(layout.project_id))
    camera = camera_segments(layout, timeline, replay, split_inputs=inputs)
    held = {key: _sample_validated_frame(layout, timeline, replay, camera, end)
            for key, _, _, end in _authored_annotation_bindings(timeline)}
    before = repr(capture), tuple(carrier.rows), layout.model_dump_json(), timeline.model_dump_json()

    def render(at):
        frame = _sample_validated_frame(layout, timeline, replay, camera, at)
        svg = _compose_validated_svg_frame(layout, timeline, frame, held, None, split_inputs=inputs)
        return svg.svg, _rasterize_svg_frame(layout, svg, split_inputs=inputs).png

    start = capture.start_ms
    expected = {at: render(at) for at in (start - 1, start, start + 12, start + 24, start + 36, start + 40, start + 2539)}
    with Image.open(io.BytesIO(expected[start + 40][1])) as image:
        rgb = image.convert("RGB")
        assert rgb.getpixel((370, 240) if portrait else (950, 300)) == (235, 30, 40)
        assert rgb.getpixel((370, 840) if portrait else (370, 300)) == (25, 185, 50)
    assert "First view" in expected[start + 40][0] and "Second view" in expected[start + 40][0]
    if variant == "source":
        assert "Original source" in expected[start - 1][0] and "Original source" not in expected[start + 40][0]
        with Image.open(io.BytesIO(expected[start - 1][1])) as image:
            assert image.convert("RGB").getpixel((350, 240) if portrait else (930, 300)) == (40, 170, 210)
    if variant == "annotated":
        assert all(text in expected[start + 40][0] for text in ("First mechanism", "Second mechanism"))
    assert len({png for _, png in expected.values()}) >= 4

    def denied(*_args, **_kwargs):
        pytest.fail("frozen evidence-family preview reopened a source or used the network")

    original_open = Path.open

    def temporary_fonts_only(path, *args, **kwargs):
        assert any(part.startswith("atme-split-fonts-") for part in path.parts)
        return original_open(path, *args, **kwargs)

    with monkeypatch.context() as sealed:
        sealed.setattr(Path, "read_bytes", denied)
        sealed.setattr(Path, "read_text", denied)
        sealed.setattr(Path, "open", temporary_fonts_only)
        sealed.setattr(socket, "create_connection", denied)
        sealed.setattr(socket.socket, "connect", denied)
        for at in (start + 40, start + 12, start + 2539, start - 1, start + 36, start, start + 24, start + 40):
            assert render(at) == expected[at]
    assert before == (repr(capture), tuple(carrier.rows), layout.model_dump_json(), timeline.model_dump_json())
    assert originals == {path: path.read_bytes() for path in originals}
    assert project == dict(service._row(layout.project_id))
    (directory / "attested-family-before.png").write_bytes(expected[start - 1][1])
    (directory / "attested-family-complete.png").write_bytes(expected[start + 40][1])


def test_split_evidence_family_native_receipts_pin_each_treatment_and_original(evidence_family_boundary):
    _, _, _, _, _, layout, _, _, carrier, _, _, inputs = evidence_family_boundary
    rows = {row["object_id"]: row["paint"] for value in inputs.paint_evidence
            if "object_id" in (row := json.loads(value)) and row["family"] == "attested evidence"}
    for treatment in layout.evidence_treatments:
        obj = next(obj for obj in layout.objects if obj.object_id == treatment.object_id)
        original = next(row.payload for row in carrier.rows if row.asset_id == obj.asset_id)
        proof = rows[obj.object_id]
        assert proof["treatment_sha256"] == digest(treatment.model_dump(mode="json"))
        assert proof["asset_sha256"] == sha256(original).hexdigest()
        assert proof["alpha_size"] == [ceil(obj.geometry.bounds.width), ceil(obj.geometry.bounds.height)]
        assert proof["alpha_bounds"] is not None
    assert rows["part-1"]["treatment_sha256"] != rows["part-2"]["treatment_sha256"]
    assert rows["part-1"]["svg_sha256"] != rows["part-2"]["svg_sha256"]


@pytest.mark.parametrize("field", ["treatment_sha256", "alpha_sha256", "alpha_bounds", "asset_sha256"])
def test_split_evidence_family_coherently_rehashed_native_proof_is_not_authority(evidence_family_boundary, field):
    _, _, _, _, _, layout, _, _, _, _, capture, inputs = evidence_family_boundary
    rows = [json.loads(row) for row in inputs.paint_evidence]
    row = next(row for row in rows if row.get("object_id") == "part-1")
    row["paint"][field] = [0, 0, 1, 1] if field == "alpha_bounds" else "0" * 64
    manifest = json.loads(inputs.manifest_json)
    manifest["paint_evidence"] = rows

    def canonical(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    encoded = canonical(manifest)
    forged = replace(inputs, paint_evidence=tuple(canonical(row) for row in rows),
                     manifest_json=encoded, inputs_sha256=sha256(encoded.encode()).hexdigest())
    with pytest.raises(ValueError, match="frozen paint binding"):
        split_family_admission("part-1", capture, layout, forged)


@pytest.mark.parametrize("mode", ["draw", "write"])
def test_split_evidence_family_rejects_unfaithful_construction_modes(evidence_family_boundary, mode):
    _, _, _, _, _, layout, *_ = evidence_family_boundary
    obj = next(obj for obj in layout.objects if obj.object_id == "part-1")
    with pytest.raises(ValueError, match=f"Split {mode} is incompatible with attested evidence construction"):
        _split_primitive_paint(obj, mode)


def test_split_evidence_family_too_small_card_cannot_receive_verified_paint_inputs(evidence_family_boundary):
    _, _, _, _, _, layout, _, _, carrier, *_ = evidence_family_boundary
    unreadable = layout.model_copy(deep=True)
    obj = next(obj for obj in unreadable.objects if obj.object_id == "part-1")
    obj.geometry.bounds.width = obj.geometry.bounds.height = 1
    with pytest.raises(UnsupportedVisualObject, match="too small to remain readable"):
        verify_split_paint_inputs(unreadable, carrier)
    assert next(obj for obj in layout.objects if obj.object_id == "part-1").geometry.bounds.width == 500
