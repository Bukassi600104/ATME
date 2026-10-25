"""Task8 live evidence capture, not family paint/public admission."""

import json
from copy import deepcopy
from dataclasses import replace

import pytest
from atme.render.v2_split import _validate_split_completion, capture_split, sample_split
from atme.render.v2_split_identity import split_content_receipts
from atme.render.v2_split_paint import (
    _freeze_verified_split_asset,
    _VerifiedSplitAssetBytes,
)
from atme.render.v2_timeline_replay import _capture_split_observed, version_targets
from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    ResolvedAction,
    ResolvedAsset,
    SplitAssetPin,
)
from test_v2_evidence_annotation_contract import authored_evidence_annotation
from test_v2_evidence_annotation_objects import cross_annotation_documents
from test_v2_evidence_compositor import evidence_documents
from test_v2_split_capture import geometry_boundary
from test_v2_split_evidence_contract import window_payload
from test_v2_split_identity import sample_for_layout
from v2_fixtures import digest


def live_evidence_boundary(tmp_path):
    """Actual project-ingested immutable PNG, authored Split and external notes.

    Source basis uses actual input receipts. Endpoint/window expectations below
    are independently authored; this is not a native Split coverage proof.
    """
    service, original_layout, original_clock, _ = evidence_documents(tmp_path)
    base, _, original = geometry_boundary()
    layout = base.model_dump(mode="json")
    layout["project_id"] = original_layout["project_id"]
    slot = next(index for index, obj in enumerate(layout["objects"]) if obj["object_id"] == "part-1")
    old = layout["objects"][slot]
    evidence = deepcopy(next(obj for obj in original_layout["objects"] if obj["object_type"] == "evidence"))
    for key in ("object_id", "board_id", "beat_id", "coverage_ids", "geometry", "transform", "anchors",
                "z_index", "initial_state", "visible", "opacity", "parent_id", "clip_id"):
        evidence[key] = deepcopy(old[key])
    layout["objects"][slot] = evidence
    target = deepcopy(next(obj for obj in layout["objects"] if obj["object_id"] == "source"))
    target.update(object_id="annotation-target", z_index=3)
    target["transform"]["position"]["x"] = 100.0
    notes = deepcopy(cross_annotation_documents()[1]["objects"][-2:])
    for index, obj in enumerate(notes, 4):
        obj.update(board_id=evidence["board_id"], beat_id=evidence["beat_id"],
                   coverage_ids=deepcopy(evidence["coverage_ids"]), z_index=index)
    notes[1].update(source_object_id="part-1", destination_object_id="annotation-target")
    notes[1]["geometry"]["bounds"] = {"x": 0, "y": 0, "width": 1280, "height": 720}
    layout["objects"].extend([target, *notes])
    layout["boards"][0]["object_ids"].extend(["annotation-target", "evidence-note", "evidence-leader"])
    treatment = deepcopy(original_layout["evidence_treatments"][0])
    treatment.update(object_id="part-1", action_id="split-1", beat_id=evidence["beat_id"])
    intent = treatment["intent"]
    intent.update(annotation_target_id="annotation-target", annotation_policy=authored_evidence_annotation(),
                  destination_board_id=evidence["board_id"])
    layout["evidence_treatments"] = [treatment]
    typed = ExecutableLayoutV2.model_validate(layout)
    asset = ResolvedAsset.model_validate(original_clock["resolved_assets"][0])
    pin = SplitAssetPin(asset_id=asset.asset_id, revision=asset.revision, resource_uri=asset.managed_ref,
                        checksum_sha256=asset.checksum_sha256)
    verified = service.render_evidence_bytes(typed.project_id, asset.model_dump(mode="json"), treatment)
    carrier = _VerifiedSplitAssetBytes((_freeze_verified_split_asset(asset, pin, verified, layout=typed),))
    before = replace(sample_for_layout(typed), at_ms=1000)
    objects = {obj.object_id: obj for obj in typed.objects}
    contents = {row.object_id: row for row in split_content_receipts(typed, before, carrier)}
    from atme.render.v2_split import _observed_split_placements

    raw = original.model_dump(mode="json")
    raw.update(start_ms=1000, end_ms=2000)
    policy = raw["action"]["split_policy"]
    result = policy["results"][0]
    result.update(post_state="evidence_visible", evidence_activation={
        "result_object_id": "part-1", "beat_id": evidence["beat_id"], "causal_action_id": "split-1",
        "intent": deepcopy(intent), "asset_pin": pin.model_dump(mode="json"),
        "permission_sha256": digest(asset.allowed_transformations),
        "allowed_transformations": asset.allowed_transformations.copy()})
    result["movement"] = {"phase": {"start_tick": 0, "end_tick": 4000, "easing": "linear"},
        "from_transform": deepcopy(result["destination"]), "destination": deepcopy(result["destination"])}
    basis = policy["source_basis"]
    basis.update(asset_pins=[pin.model_dump(mode="json")],
        placements=[row.model_dump(mode="json") for row in _observed_split_placements(
            before, objects, set(objects), contents)],
        read_dependencies=[{"kind": "connector_anchor", "object_ids": ["annotation-target", "evidence-leader", "part-1"]},
                           {"kind": "annotation_anchor", "object_ids": ["annotation-target", "evidence-leader", "evidence-note"]}])
    for correspondence in policy["correspondences"]:
        correspondence.update(source_content_sha256=contents["source"].content_sha256,
                              result_content_sha256=contents[correspondence["result_object_id"]].content_sha256)
    policy["source_basis_sha256"] = digest(basis)
    # Typed syntax only, never call the endpoint/window derivation being tested.
    from atme.store.contracts_v2 import SplitPolicy

    policy = SplitPolicy.model_validate(policy).model_dump(mode="json")
    raw["action"]["split_policy"] = policy
    basis = policy["source_basis"]
    placements = deepcopy(basis["placements"])
    for row in placements:
        key = row["object_id"]
        if key == "annotation-target":
            continue
        row.update(state_version=2, state="evidence_visible" if key == "part-1" else
                   "removed" if key == "source" else "visible", local_visibility=key != "source",
                   effective_visibility=key != "source", reveal=0.0 if key == "source" else 1.0,
                   local_opacity=0.0 if key == "source" else row["local_opacity"])
    window = window_payload()
    window["treatment_sha256"] = digest(typed.evidence_treatments[0].model_dump(mode="json"))
    receipt = {"source_basis_sha256": digest(basis), "policy_sha256": digest(policy), "placements": placements,
        "read_dependencies": deepcopy(basis["read_dependencies"]), "asset_pins": deepcopy(basis["asset_pins"]),
        "style_sha256": basis["style_sha256"], "registry_sha256": basis["registry_sha256"],
        "evidence_windows": [deepcopy(window)]}
    receipt["completion_sha256"] = digest(receipt)
    raw.update(split_completion_receipt=receipt, split_evidence_windows=[window])
    return typed, before, ResolvedAction.model_validate(raw), carrier, service


def test_live_capture_keeps_logical_note_writes_separate_from_physical_closures(tmp_path):
    layout, before, action, carrier, service = live_evidence_boundary(tmp_path)
    original = (repr(before), action.model_dump(mode="json"), tuple(carrier.rows),
                (tmp_path / "external-original.png").read_bytes(), dict(service._row(layout.project_id)))
    capture = capture_split(action, layout, before, carrier)
    assert capture.owned_object_ids == ("evidence-leader", "evidence-note", "part-1", "part-2", "source")
    assert capture.read_dependency_ids == ("annotation-target",)
    assert [row[0] for row in capture.evidence_treatments_json] == ["part-1"]
    basis = json.loads(capture.basis_json)
    assert [row["owned_ids"] for row in basis["result_closures"]] == [["part-1"], ["part-2"]]
    assert {row.object_id for row in capture.baseline} == {row.object_id for row in before.objects}
    assert (repr(before), action.model_dump(mode="json"), tuple(carrier.rows),
            (tmp_path / "external-original.png").read_bytes(), dict(service._row(layout.project_id))) == original


def test_scheduler_attribution_preserves_full_context_and_commits_notes_atomically(tmp_path):
    layout, before, action, carrier, _ = live_evidence_boundary(tmp_path)
    wrapped = _capture_split_observed(layout, before, (action,), 0, {}, carrier)
    capture = wrapped.split_capture
    assert capture.action_id == "split-1"
    assert json.loads(capture.evidence_treatments_json[0][1]) == layout.evidence_treatments[0].model_dump(mode="json")
    original = repr(capture)
    for at, note, leader in [(1500, 1.0, 0.5), (1200, 0.5, 0.0), (1600, 1.0, 1.0), (1000, 0.0, 0.0)]:
        rows = {row.object_id: row for row in sample_split(capture, at).objects}
        assert "annotation-target" not in rows
        assert (rows["evidence-note"].reveal_fraction, rows["evidence-leader"].reveal_fraction) == (note, leader)
        assert rows["evidence-note"].state == rows["evidence-leader"].state == "hidden"
    # Exercise the scheduler's real endpoint guard with the sampled delta and
    # one version increment per owned participant; the target remains untouched.
    frames = {row.object_id: row for row in before.objects}
    frames.update({row.object_id: row for row in sample_split(capture, 2000).objects})
    versions = dict(before.state_versions)
    for key in version_targets(action.action):
        versions[key] += 1
    endpoint = replace(before, at_ms=2000, objects=tuple(frames[key] for key in sorted(frames)),
                       state_versions=tuple(sorted(versions.items())))
    assert endpoint.object("annotation-target") == before.object("annotation-target")
    assert versions["annotation-target"] == dict(before.state_versions)["annotation-target"]
    _validate_split_completion(capture, layout, endpoint, carrier)
    assert repr(capture) == original


@pytest.mark.parametrize("fault", ["raw_bytes", "false_treatment_hash", "false_phase_clock", "visible_note", "partial_note"])
def test_live_capture_rejects_unverified_context_or_rehashed_false_windows(tmp_path, fault):
    layout, before, action, carrier, _ = live_evidence_boundary(tmp_path)
    if fault == "raw_bytes":
        carrier = dict(carrier)
    elif fault in {"visible_note", "partial_note"}:
        before = replace(before, objects=tuple(replace(row, visible=True if fault == "visible_note" else row.visible,
            reveal_fraction=0.5 if fault == "partial_note" else row.reveal_fraction)
            if row.object_id == "evidence-note" else row for row in before.objects))
    else:
        raw = action.model_dump(mode="json")
        window = raw["split_evidence_windows"][0]
        if fault == "false_treatment_hash":
            window["treatment_sha256"] = "0" * 64
        else:
            for key in ("construction_complete_ms", "readable_hold_start_ms", "readable_hold_end_ms"):
                window[key] += 1
        receipt = raw["split_completion_receipt"]
        receipt["evidence_windows"] = deepcopy(raw["split_evidence_windows"])
        receipt["completion_sha256"] = digest({key: value for key, value in receipt.items()
                                               if key != "completion_sha256"})
        action = ResolvedAction.model_validate(raw)
    with pytest.raises(ValueError):
        capture_split(action, layout, before, carrier)
