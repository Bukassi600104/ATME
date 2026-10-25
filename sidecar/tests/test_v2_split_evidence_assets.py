"""Task8 immutable shared originals with distinct per-object evidence authority.

These actual project-ingested carrier/identity proofs do not admit F07 paint.
"""

import io
import json
import socket
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest
from atme.project_assets import read_verified_split_asset_bytes
from atme.project_service import ProjectError
from atme.render.v2_split import (
    _observed_split_placements,
    _validate_split_completion,
    capture_split,
    sample_split,
)
from atme.render.v2_split_identity import split_content_receipts
from atme.render.v2_split_paint import (
    _freeze_verified_split_asset,
    _verified_split_asset_pins,
    _VerifiedSplitAssetBytes,
    verify_split_paint_inputs,
)
from atme.render.v2_timeline_replay import (
    _capture_split_observed,
    _replay_split_chronology,
    version_targets,
)
from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    ResolvedAction,
    ResolvedAsset,
    ResolvedVisualTimelineV2,
    SplitAssetPin,
    SplitPolicy,
    VisualPlanV2,
)
from PIL import Image
from test_v2_evidence_compositor import evidence_documents
from test_v2_split_evidence_capture import live_evidence_boundary
from test_v2_split_identity import sample_for_layout
from v2_fixtures import (
    digest,
    executable_layout_v2,
    resolved_timeline_v2,
    visual_plan_v2,
)


def shared_evidence_inputs(tmp_path):
    layout, _, action, original_carrier, service = live_evidence_boundary(tmp_path)
    raw = layout.model_dump(mode="json")
    first = next(obj for obj in raw["objects"] if obj["object_id"] == "part-1")
    slot = next(index for index, obj in enumerate(raw["objects"]) if obj["object_id"] == "part-2")
    previous = raw["objects"][slot]
    second = deepcopy(first)
    for key in ("object_id", "geometry", "transform", "anchors", "z_index"):
        second[key] = deepcopy(previous[key])
    raw["objects"][slot] = second
    # Registered evidence now needs faithful native paint, not the old tiny kernel bounds.
    first["geometry"]["bounds"] = {"x": 700, "y": 130, "width": 500, "height": 420}
    second["geometry"]["bounds"] = {"x": 100, "y": 130, "width": 500, "height": 420}
    treatment = deepcopy(raw["evidence_treatments"][0])
    treatment["object_id"] = "part-2"
    intent = treatment["intent"]
    intent.pop("annotation_policy")
    intent.update(claim_id="shared-second-claim", claim="A distinct authored result from the same original",
                  annotation="Second mechanism", annotation_target_id="part-2", source_label="Second view",
                  crop={"x": 450, "y": 0, "width": 450, "height": 250},
                  focus_region={"x": 450, "y": 0, "width": 450, "height": 250})
    raw["evidence_treatments"].append(treatment)
    typed = ExecutableLayoutV2.model_validate(raw)
    original = original_carrier.rows[0]
    asset = ResolvedAsset.model_validate_json(original.resolved_json)
    pin = SplitAssetPin.model_validate_json(original.pin_json)
    verified = tuple(service.render_evidence_bytes(typed.project_id, asset.model_dump(mode="json"),
        row.model_dump(mode="json")) for row in typed.evidence_treatments)
    return typed, asset, pin, verified, service, action


@pytest.fixture(scope="module")
def shared_inputs(tmp_path_factory):
    root = tmp_path_factory.mktemp("shared-evidence-original")
    return root, *shared_evidence_inputs(root)


def test_one_project_original_keeps_two_split_result_treatments_without_asset_id_collapse(shared_inputs):
    tmp_path, layout, asset, pin, verified, service, _ = shared_inputs
    original = (tmp_path / "external-original.png").read_bytes()
    original_project = dict(service._row(layout.project_id))
    assert verified[0].payload == verified[1].payload == original
    row = _freeze_verified_split_asset(asset, pin, verified, layout=layout)
    carrier = _VerifiedSplitAssetBytes((row,))
    assert len(carrier.rows) == 1 and row.payload == original
    assert _verified_split_asset_pins(layout, carrier, {asset.asset_id}) == [pin]
    # An asset alone cannot select one of two different treatment authorities.
    with pytest.raises(ValueError, match="object|ambiguous|treatment"):
        carrier[asset.asset_id]
    for identity in (("unknown-asset", "split-1", "part-1"),
                     (asset.asset_id, "unknown-action", "part-1"),
                     (asset.asset_id, "split-1", "unknown-object")):
        with pytest.raises(ValueError, match="Split evidence"):
            carrier.evidence_for(*identity)
    sample = replace(sample_for_layout(layout), at_ms=1000)
    receipts = {item.object_id: item for item in split_content_receipts(layout, sample, carrier)}
    first, second = (json.loads(receipts[key].canonical_json) for key in ("part-1", "part-2"))
    assert first["evidence"]["intent"] == layout.evidence_treatments[0].intent.model_dump(mode="json")
    assert second["evidence"]["intent"] == layout.evidence_treatments[1].intent.model_dump(mode="json")
    assert first["evidence"]["intent"]["claim_id"] != second["evidence"]["intent"]["claim_id"]
    assert first["asset_bytes_sha256"] == second["asset_bytes_sha256"] == sha256(original).hexdigest()
    assert receipts["part-1"].content_sha256 != receipts["part-2"].content_sha256
    inputs = verify_split_paint_inputs(layout, carrier)
    assert json.loads(inputs.manifest_json)["project_assets"][0]["treatments"] == [
        item.model_dump(mode="json") for item in layout.evidence_treatments]
    assert (tmp_path / "external-original.png").read_bytes() == original
    assert dict(service._row(layout.project_id)) == original_project


def test_actual_project_resolver_preserves_every_shared_result_authority(shared_inputs):
    tmp_path, layout, asset, pin, _, service, _ = shared_inputs
    original = (tmp_path / "external-original.png").read_bytes()
    project = dict(service._row(layout.project_id))
    carrier = read_verified_split_asset_bytes(service, layout, [asset.model_dump(mode="json")],
                                             [pin.model_dump(mode="json")])
    assert len(carrier.rows) == 1 and carrier.rows[0].payload == original
    assert _verified_split_asset_pins(layout, carrier, {asset.asset_id}) == [pin]
    for treatment in layout.evidence_treatments:
        value = carrier.evidence_for(asset.asset_id, "split-1", treatment.object_id)
        assert value.payload == original and value.treatment == treatment
    assert (tmp_path / "external-original.png").read_bytes() == original
    assert dict(service._row(layout.project_id)) == project


@pytest.mark.parametrize("fault", ["provenance", "permissions", "dimensions", "origin"])
def test_actual_project_resolver_checks_nonfirst_treatment_against_stored_source(shared_inputs, fault):
    tmp_path, layout, asset, pin, _, service, _ = shared_inputs
    original = (tmp_path / "external-original.png").read_bytes()
    project = dict(service._row(layout.project_id))
    raw = layout.model_dump(mode="json")
    treatment = raw["evidence_treatments"][1]
    if fault == "provenance":
        treatment["asset_provenance"]["source_uri"] = "https://example.com/forged-source"
    elif fault == "permissions":
        treatment["allowed_transformations"].reverse()
    elif fault == "dimensions":
        treatment["asset_width"] += 1
    else:
        treatment["asset_managed_ref"] = f"atme://projects/999/assets/{asset.asset_id}"
    changed = ExecutableLayoutV2.model_validate(raw)
    with pytest.raises(ProjectError):
        read_verified_split_asset_bytes(service, changed, [asset.model_dump(mode="json")],
                                         [pin.model_dump(mode="json")])
    assert (tmp_path / "external-original.png").read_bytes() == original
    assert dict(service._row(layout.project_id)) == project


@pytest.fixture(scope="module")
def shared_boundary(shared_inputs):
    _, layout, asset, pin, _, service, original = shared_inputs
    carrier = read_verified_split_asset_bytes(service, layout, [asset.model_dump(mode="json")],
                                             [pin.model_dump(mode="json")])
    before = replace(sample_for_layout(layout), at_ms=1000)
    objects = {obj.object_id: obj for obj in layout.objects}
    contents = {row.object_id: row for row in split_content_receipts(layout, before, carrier)}
    raw = original.model_dump(mode="json")
    policy = raw["action"]["split_policy"]
    second = policy["results"][1]
    second.update(post_state="evidence_visible", evidence_activation={
        "result_object_id": "part-2", "beat_id": objects["part-2"].beat_id,
        "causal_action_id": "split-1", "intent": layout.evidence_treatments[1].intent.model_dump(mode="json"),
        "asset_pin": pin.model_dump(mode="json"), "permission_sha256": digest(asset.allowed_transformations),
        "allowed_transformations": asset.allowed_transformations.copy()})
    second["construction"]["phase"]["end_tick"] = 5000
    second["movement"] = {"phase": {"start_tick": 0, "end_tick": 9000, "easing": "linear"},
        "from_transform": deepcopy(second["destination"]), "destination": deepcopy(second["destination"])}
    basis = policy["source_basis"]
    basis["placements"] = [row.model_dump(mode="json") for row in _observed_split_placements(
        before, objects, set(objects), contents)]
    for row in policy["correspondences"]:
        row.update(source_content_sha256=contents["source"].content_sha256,
                   result_content_sha256=contents[row["result_object_id"]].content_sha256)
    policy["source_basis_sha256"] = digest(basis)
    policy = SplitPolicy.model_validate(policy).model_dump(mode="json")
    raw["action"]["split_policy"] = policy
    basis = policy["source_basis"]
    placements = deepcopy(basis["placements"])
    for row in placements:
        key = row["object_id"]
        if key == "annotation-target":
            continue
        row.update(state_version=2, state="evidence_visible" if key in {"part-1", "part-2"} else
                   "removed" if key == "source" else "visible", local_visibility=key != "source",
                   effective_visibility=key != "source", reveal=0.0 if key == "source" else 1.0,
                   local_opacity=0.0 if key == "source" else row["local_opacity"])
    # Literal windows: two different authored clocks, not the runtime's builder.
    windows = [{"result_object_id": key, "treatment_sha256": digest(treatment.model_dump(mode="json")),
        "construction_complete_ms": construction, "movement_complete_ms": movement,
        "readable_hold_start_ms": hold, "readable_hold_end_ms": end}
        for treatment, (key, construction, movement, hold, end) in zip(layout.evidence_treatments,
            [("part-1", 1600, 1400, 1600, 4100), ("part-2", 1500, 1900, 1900, 4400)], strict=True)]
    receipt = {"source_basis_sha256": digest(basis), "policy_sha256": digest(policy),
        "placements": placements, "read_dependencies": deepcopy(basis["read_dependencies"]),
        "asset_pins": deepcopy(basis["asset_pins"]), "style_sha256": basis["style_sha256"],
        "registry_sha256": basis["registry_sha256"], "evidence_windows": deepcopy(windows)}
    receipt["completion_sha256"] = digest(receipt)
    raw.update(split_completion_receipt=receipt, split_evidence_windows=windows)
    return layout, before, ResolvedAction.model_validate(raw), carrier


def test_actual_shared_capture_keeps_both_treatments_and_distinct_windows(shared_boundary):
    layout, before, action, carrier = shared_boundary
    capture = capture_split(action, layout, before, carrier)
    assert [json.loads(value) for _, value in capture.evidence_treatments_json] == [
        treatment.model_dump(mode="json") for treatment in layout.evidence_treatments]
    windows = json.loads(capture.completion_json)["evidence_windows"]
    assert [(row["result_object_id"], row["construction_complete_ms"], row["movement_complete_ms"],
             row["readable_hold_start_ms"], row["readable_hold_end_ms"]) for row in windows] == [
        ("part-1", 1600, 1400, 1600, 4100), ("part-2", 1500, 1900, 1900, 4400)]
    wrapped = _capture_split_observed(layout, before, (action,), 0, {}, carrier)
    assert wrapped.split_capture.evidence_treatments_json == capture.evidence_treatments_json
    frames = {row.object_id: row for row in before.objects}
    frames.update({row.object_id: row for row in sample_split(wrapped.split_capture, 2000).objects})
    versions = dict(before.state_versions)
    for key in version_targets(action.action):
        versions[key] += 1
    endpoint = replace(before, at_ms=2000, objects=tuple(frames[key] for key in sorted(frames)),
                       state_versions=tuple(sorted(versions.items())))
    _validate_split_completion(wrapped.split_capture, layout, endpoint, carrier)
    assert endpoint.object("annotation-target") == before.object("annotation-target")
    assert versions["annotation-target"] == 1


def test_shared_result_scheduler_preserves_pair_context_atomic_versions_and_random_seek(shared_boundary):
    layout, before, action, carrier = shared_boundary
    initial = replace(before, at_ms=0)
    replay = _replay_split_chronology(layout, initial, (action,), 5000, carrier)
    assert replay.evidence_treatments_json == ()
    captures = [capture.split_capture for checkpoint in replay.checkpoints for capture in checkpoint.active]
    assert captures and all([key for key, _ in capture.evidence_treatments_json] == ["part-1", "part-2"]
                            for capture in captures)
    expected = {}
    for at, first, second, committed in [(999, 0., 0., False), (1000, 0., 0., False),
        (1300, .5, .6, False), (1500, 5/6, 1., False), (1600, 1., 1., False),
        (1900, 1., 1., False), (2000, 1., 1., True), (4400, 1., 1., True)]:
        sample = replay.at(at)
        expected[at] = sample
        assert sample.object("part-1").reveal_fraction == pytest.approx(first)
        assert sample.object("part-2").reveal_fraction == pytest.approx(second)
        assert [sample.object(key).state for key in ("part-1", "part-2")] == (
            ["evidence_visible"] * 2 if committed else ["hidden"] * 2)
        versions = dict(sample.state_versions)
        assert [versions[key] for key in ("source", "part-1", "part-2", "evidence-note", "evidence-leader")] == (
            [2] * 5 if committed else [1] * 5)
        assert versions["annotation-target"] == 1
        assert sample.object("annotation-target") == initial.object("annotation-target")
    for at in (4400, 1300, 2000, 999, 1900, 1500, 1000, 1600):
        assert replay.at(at) == expected[at]


def ordinary_shared_evidence(tmp_path, portrait):
    """Two valid ordinary insertion owners; never substitute for Split proof."""
    service, origin, clock, _ = evidence_documents(tmp_path,
        crop={"x": 0, "y": 0, "width": 450, "height": 250},
        focus={"x": 0, "y": 0, "width": 450, "height": 250}, annotation=None, source_label="First view")
    asset = ResolvedAsset.model_validate(clock["resolved_assets"][0])
    plan = visual_plan_v2()
    plan["project_id"] = origin["project_id"]
    declared = plan["assets"][0]
    declared.update(asset_id=asset.asset_id, revision=asset.revision, managed_ref=asset.managed_ref,
        checksum_sha256=asset.checksum_sha256, width=asset.width, height=asset.height,
        provenance=deepcopy(origin["evidence_treatments"][0]["asset_provenance"]))
    plan["objects"][2]["asset_id"] = asset.asset_id
    plan["actions"][2]["evidence_asset_id"] = asset.asset_id
    plan["beats"][1]["evidence"] = deepcopy(origin["evidence_treatments"][0]["intent"])
    obj = deepcopy(plan["objects"][2])
    obj.update(object_id="evidence-second", beat_id="beat-003", coverage_ids=["coverage-4"])
    plan["objects"].append(obj)
    plan["boards"][0]["object_ids"].append(obj["object_id"])
    action = deepcopy(plan["actions"][2])
    action.update(action_id="action-4", source_instruction_id="instruction-4", coverage_id="coverage-4",
                  fallback={"fallback_id": "fallback-4", "on_failure": "block"}, target_object_id="evidence-second")
    plan["actions"].append(action)
    beat = deepcopy(plan["beats"][1])
    beat.update(beat_id="beat-003", object_ids=["evidence-second"], action_ids=["action-4"],
                coverage_ids=["coverage-4"], fallback_ids=["fallback-4"])
    beat["attention"]["primary_targets"] = ["evidence-second"]
    beat["camera_intent"]["target_ids"] = ["evidence-second"]
    beat["evidence"].update(claim_id="shared-ordinary-second", source_label="Second view",
        crop={"x": 450, "y": 0, "width": 450, "height": 250},
        focus_region={"x": 450, "y": 0, "width": 450, "height": 250})
    plan["beats"].append(beat)
    fallback = deepcopy(plan["fallbacks"][2])
    fallback.update(fallback_id="fallback-4", affected_ids=["instruction-4"])
    plan["fallbacks"].append(fallback)
    plan["coverage"].append({"coverage_id": "coverage-4", "instruction_id": "instruction-4",
                             "status": "executed", "action_ids": ["action-4"], "fallback_id": None})
    if portrait:
        plan["output_profile"] = {"profile_id": "SHORT_FORM_9_16", "width": 720, "height": 1280, "fps": 30}
    VisualPlanV2.model_validate(plan)
    layout = executable_layout_v2(plan)
    layout.update(project_id=plan["project_id"], output_profile=deepcopy(plan["output_profile"]))
    layout["activations"][0]["end_ms"] = 12000
    layout["objects"][2]["asset_id"] = asset.asset_id
    second = deepcopy(layout["objects"][2])
    second.update(object_id="evidence-second", beat_id="beat-003", coverage_ids=["coverage-4"], z_index=4)
    second["geometry"]["bounds"] = {"x": 100, "y": 680 if portrait else 130, "width": 500, "height": 420}
    layout["objects"].append(second)
    if portrait:
        layout["canvas"] = {"x": 0, "y": 0, "width": 720, "height": 1280}
        layout["objects"][2]["geometry"]["bounds"] = {"x": 100, "y": 80, "width": 500, "height": 420}
    resolved = resolved_timeline_v2(plan, layout)
    resolved.update(project_id=plan["project_id"], output_profile=deepcopy(plan["output_profile"]),
                    resolved_assets=[asset.model_dump(mode="json")], duration_ms=12000)
    resolved["actions"][3].update(start_ms=8000, end_ms=8900)
    resolved["actions"][3]["resolved_trigger"].update(alignment_anchor_ms=8000, resolved_at_ms=8000)
    resolved["beat_anchors"].append({"beat_id": "beat-003", "start_ms": 8000})
    typed = ExecutableLayoutV2.model_validate(layout)
    resolved["layout_sha256"] = digest(typed.model_dump(mode="json"))
    timeline = ResolvedVisualTimelineV2.model_validate(resolved)
    pin = SplitAssetPin(asset_id=asset.asset_id, revision=asset.revision, resource_uri=asset.managed_ref,
                        checksum_sha256=asset.checksum_sha256)
    carrier = read_verified_split_asset_bytes(service, typed, timeline.resolved_assets, [pin.model_dump(mode="json")])
    return service, typed, timeline, carrier


@pytest.mark.parametrize("portrait", [False, True])
def test_shared_carrier_ordinary_svg_uses_each_exact_crop_in_source_and_frozen_path(tmp_path, monkeypatch, portrait):
    from atme.render.v2_state import evaluate_frame
    from atme.render.v2_svg import (
        _compose_validated_svg_frame,
        _rasterize_svg_frame,
        compose_png_frame,
    )

    service, layout, timeline, carrier = ordinary_shared_evidence(tmp_path, portrait)
    original = (tmp_path / "external-original.png").read_bytes()
    project = dict(service._row(layout.project_id))
    layout_doc, timeline_doc = layout.model_dump(mode="json"), timeline.model_dump(mode="json")
    source = compose_png_frame(layout_doc, timeline_doc, 11000, carrier).png
    with Image.open(io.BytesIO(source)) as image:
        rgb = image.convert("RGB")
        assert rgb.getpixel((350, 240) if portrait else (930, 300)) == (235, 30, 40)
        assert rgb.getpixel((350, 840) if portrait else (350, 300)) == (25, 185, 50)
    (tmp_path / f"shared-ordinary-evidence-{portrait}.png").write_bytes(source)
    inputs = verify_split_paint_inputs(layout, carrier)
    snapshot = evaluate_frame(layout_doc, timeline_doc, 11000)
    first = layout.evidence_treatments[0]
    partial = {carrier.rows[0].asset_id: carrier.evidence_for(carrier.rows[0].asset_id,
                                                            first.action_id, first.object_id)}
    with pytest.raises(ValueError, match="ambiguous"):
        _compose_validated_svg_frame(layout, timeline, snapshot, {}, partial, split_inputs=inputs)
    changed_row = replace(carrier.rows[0], payload=carrier.rows[0].payload + b"\x00")
    with pytest.raises(ValueError, match="differ from frozen"):
        _compose_validated_svg_frame(layout, timeline, snapshot, {},
                                    _VerifiedSplitAssetBytes((changed_row,)), split_inputs=inputs)
    def denied(*_args, **_kwargs):
        pytest.fail("frozen carrier reopened a file or used the network")
    with monkeypatch.context() as sealed:
        sealed.setattr(Path, "read_bytes", denied)
        sealed.setattr(socket, "create_connection", denied)
        sealed.setattr(socket.socket, "connect", denied)
        svg = _compose_validated_svg_frame(layout, timeline, snapshot, {}, carrier, split_inputs=inputs)
        assert _rasterize_svg_frame(layout, svg, split_inputs=inputs).png == source
        assert _compose_validated_svg_frame(layout, timeline, snapshot, {}, split_inputs=inputs).svg == svg.svg
    assert (tmp_path / "external-original.png").read_bytes() == original
    assert dict(service._row(layout.project_id)) == project


@pytest.mark.parametrize("fault", ["missing", "extra", "duplicate", "reordered", "mixed_bytes",
                                  "mixed_dimensions", "mixed_permissions", "list"])
def test_multi_consumer_freeze_requires_every_exact_independently_bound_value(shared_inputs, fault):
    _, layout, asset, pin, verified, _, _ = shared_inputs
    supplied = verified
    if fault == "missing":
        supplied = verified[:1]
    elif fault == "extra":
        supplied = (*verified, verified[1])
    elif fault == "duplicate":
        supplied = (verified[0], verified[0])
    elif fault == "reordered":
        supplied = tuple(reversed(verified))
    elif fault == "mixed_bytes":
        supplied = (verified[0], replace(verified[1], payload=verified[1].payload + b"\x00"))
    elif fault == "mixed_dimensions":
        supplied = (verified[0], replace(verified[1], width=verified[1].width + 1))
    elif fault == "mixed_permissions":
        changed = verified[1].treatment.model_copy(update={
            "allowed_transformations": list(reversed(verified[1].treatment.allowed_transformations))})
        supplied = (verified[0], replace(verified[1], treatment=changed))
    elif fault == "list":
        supplied = list(verified)
    with pytest.raises(ValueError, match="Split|evidence|treatment|tuple"):
        _freeze_verified_split_asset(asset, pin, supplied, layout=layout)


@pytest.mark.parametrize("fault", ["one_row", "duplicate", "reordered", "both_shapes", "erased", "orphan"])
def test_revalidation_cannot_trust_a_forged_multi_consumer_carrier(shared_inputs, fault):
    _, layout, asset, pin, verified, _, _ = shared_inputs
    row = _freeze_verified_split_asset(asset, pin, verified, layout=layout)
    if fault == "one_row":
        row = replace(row, treatments_json=row.treatments_json[:1])
    elif fault == "duplicate":
        row = replace(row, treatments_json=(row.treatments_json[0], row.treatments_json[0]))
    elif fault == "reordered":
        row = replace(row, treatments_json=tuple(reversed(row.treatments_json)))
    elif fault == "both_shapes":
        row = replace(row, treatment_json=row.treatments_json[0])
    elif fault == "erased":
        row = replace(row, treatments_json=())
    else:
        treatment = json.loads(row.treatments_json[1])
        treatment["object_id"] = "zz-orphan"
        row = replace(row, treatments_json=(*row.treatments_json,
            json.dumps(treatment, sort_keys=True, separators=(",", ":"), ensure_ascii=False)))
    with pytest.raises(ValueError, match="Split|evidence|treatment|tuple"):
        _verified_split_asset_pins(layout, _VerifiedSplitAssetBytes((row,)), {asset.asset_id})
