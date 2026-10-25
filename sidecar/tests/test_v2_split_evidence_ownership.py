"""Logical note ownership is not physical hierarchy or native admission.

Packet/kernel fixtures below deliberately carry placeholder asset attestations.
Expected endpoint states, versions and phase values are independently authored.
"""

import json
from copy import deepcopy
from dataclasses import replace

import pytest
from atme.render.v2_split import (
    _PaintBoundSplitCapture,
    _reservation_footprint,
    _sample_split_paint,
    validate_split_reservations,
)
from atme.render.v2_split_identity import SplitContentReceipt
from atme.render.v2_timeline_replay import version_targets
from atme.store import contracts_v2 as contracts
from test_v2_evidence_annotation_contract import authored_evidence_annotation
from test_v2_split_capture import geometry_boundary, peer_action
from test_v2_split_evidence_contract import evidence_completion_document
from test_v2_timeline_replay import resolved as timed
from v2_fixtures import digest, executable_layout_v2


def logical_completion_document():
    raw = evidence_completion_document(two_results=True)
    policy = raw["action"]["split_policy"]
    intent = policy["results"][0]["evidence_activation"]["intent"]
    intent.update(annotation_target_id="annotation-target", annotation_policy=authored_evidence_annotation())
    basis = policy["source_basis"]
    template = deepcopy(next(row for row in basis["placements"] if row["object_id"] == "part-1"))
    for index, key in enumerate(("evidence-note", "evidence-leader", "annotation-target"), 3):
        row = deepcopy(template)
        row.update(object_id=key, sibling_ordinal=index, content_sha256=digest({"authored": key}))
        if key == "annotation-target":
            row.update(state="visible", local_visibility=True, effective_visibility=True, reveal=1.0)
        basis["placements"].append(row)
    basis["placements"].sort(key=lambda row: row["object_id"])
    basis["read_dependencies"] = [{"kind": "annotation_anchor",
        "object_ids": ["annotation-target", "evidence-leader", "evidence-note"]}]
    policy["source_basis_sha256"] = digest(basis)
    receipt = raw["split_completion_receipt"]
    receipt.update(source_basis_sha256=digest(basis), policy_sha256=digest(policy),
                   read_dependencies=deepcopy(basis["read_dependencies"]))
    for row in basis["placements"]:
        if row["object_id"] not in {"evidence-note", "evidence-leader", "annotation-target"}:
            continue
        endpoint = deepcopy(row)
        if row["object_id"] != "annotation-target":
            endpoint.update(state="visible", state_version=2, local_visibility=True,
                            effective_visibility=True, reveal=1.0)
        receipt["placements"].append(endpoint)
    receipt["placements"].sort(key=lambda row: row["object_id"])
    receipt["completion_sha256"] = digest({key: value for key, value in receipt.items()
                                           if key != "completion_sha256"})
    return raw


def test_policy_derives_exclusive_logical_notes_without_fabricating_physical_descendants():
    raw = logical_completion_document()
    policy = contracts.SplitPolicy.model_validate(raw["action"]["split_policy"])
    original = policy.model_dump(mode="json")
    assert hasattr(contracts, "_split_logical_write_owners"), "Split logical ownership derivation is missing"
    assert contracts._split_logical_write_owners(policy) == {
        "evidence-note": "part-1", "evidence-leader": "part-1"}
    assert [row.owned_ids for row in policy.source_basis.result_closures] == [["part-1"], ["part-2"]]
    assert policy.model_dump(mode="json") == original


@pytest.mark.parametrize("fault", ["missing_note", "missing_note_dependency", "missing_target_dependency",
                                  "physical_overlap", "duplicate_owner"])
def test_policy_cannot_claim_unbound_or_multiply_owned_logical_participants(fault):
    raw = logical_completion_document()["action"]["split_policy"]
    basis = raw["source_basis"]
    if fault == "missing_note":
        basis["placements"] = [row for row in basis["placements"] if row["object_id"] != "evidence-note"]
        basis["read_dependencies"][0]["object_ids"].remove("evidence-note")
    elif fault == "missing_note_dependency":
        # Keep the same bound placement through another dependency kind.
        basis["read_dependencies"][0]["object_ids"].remove("evidence-note")
        basis["read_dependencies"].append({"kind": "connector_anchor", "object_ids": ["evidence-note"]})
    elif fault == "missing_target_dependency":
        # A bound target under the wrong dependency kind must not authorize
        # policy scheduling; the exact annotation read must be declared.
        basis["read_dependencies"][0]["object_ids"].remove("annotation-target")
        basis["read_dependencies"].append({"kind": "connector_anchor", "object_ids": ["annotation-target"]})
    elif fault == "physical_overlap":
        basis["result_closures"][1]["owned_ids"].append("evidence-note")
    else:
        raw["results"][1]["evidence_activation"]["intent"].update(
            annotation_target_id="annotation-target", annotation_policy=authored_evidence_annotation())
    raw["source_basis_sha256"] = digest(basis)
    with pytest.raises(ValueError, match="logical|annotation.*(bound|owner|physical)"):
        contracts.SplitPolicy.model_validate(raw)


def test_logical_notes_and_roots_share_atomic_endpoint_but_target_remains_read_only():
    raw = logical_completion_document()
    parsed = contracts.ResolvedAction.model_validate(raw)
    assert version_targets(parsed.action) == ("source", "part-1", "part-2", "evidence-note", "evidence-leader")
    rows = {row.object_id: row for row in parsed.split_completion_receipt.placements}
    assert [(rows[key].state, rows[key].state_version, rows[key].reveal)
            for key in ("source", "part-1", "part-2", "evidence-note", "evidence-leader", "annotation-target")] == [
        ("removed", 2, 0.0), ("evidence_visible", 2, 1.0), ("evidence_visible", 2, 1.0),
        ("visible", 2, 1.0), ("visible", 2, 1.0), ("visible", 1, 1.0)]


def test_reservations_treat_notes_as_writes_not_read_only_targets():
    action = contracts.SplitAction.model_validate(logical_completion_document()["action"])
    writes, reads = _reservation_footprint(action)
    assert writes == {"source", "part-1", "part-2", "evidence-note", "evidence-leader"}
    assert reads == {"annotation-target"}


def test_annotation_target_read_conflicts_with_concurrent_write_without_becoming_owned():
    capture = kernel_capture()
    action = contracts.SplitAction.model_validate(logical_completion_document()["action"])
    assert "annotation-target" not in capture.owned_object_ids
    assert "annotation-target" not in version_targets(action)
    writer = timed(peer_action("fade", target_ids=["annotation-target"], opacity=0.5).action, 1100, 1900)
    assert writer.start_ms < capture.end_ms and capture.start_ms < writer.end_ms
    with pytest.raises(ValueError, match="reservation conflicts.*annotation-target"):
        validate_split_reservations(capture, (writer,))


def test_non_evidence_capture_requires_empty_private_treatment_context():
    from atme.render.v2_split import capture_split

    layout, before, action = geometry_boundary()
    capture = capture_split(action, layout, before, {})
    assert capture.evidence_treatments_json == ()
    _sample_split_paint(capture, 500)
    with pytest.raises(ValueError, match="evidence context"):
        _sample_split_paint(replace(capture, evidence_treatments_json=(("part-1", "{}"),)), 500)


def kernel_capture():
    """Coherent private packet input, NOT live/captured attestation evidence."""
    raw = logical_completion_document()
    policy = raw["action"]["split_policy"]
    basis = policy["source_basis"]
    payloads = {row["object_id"]: json.dumps({"authored": row["object_id"]}, sort_keys=True,
        separators=(",", ":")) for row in basis["placements"]}
    for row in basis["placements"]:
        row["content_sha256"] = digest({"authored": row["object_id"]})
    for correspondence in policy["correspondences"]:
        correspondence.update(source_content_sha256=digest({"authored": "source"}),
                              result_content_sha256=digest({"authored": correspondence["result_object_id"]}))
    policy["source_basis_sha256"] = digest(basis)
    # Canonical primitive syntax for full treatment identities, not a window compiler.
    policy = contracts.SplitPolicy.model_validate(policy).model_dump(mode="json")
    basis = policy["source_basis"]
    policy["source_basis_sha256"] = digest(basis)
    template = executable_layout_v2()["evidence_treatments"][0]
    contexts = []
    for result, window in zip(policy["results"], raw["split_evidence_windows"], strict=True):
        treatment = deepcopy(template)
        treatment.update(object_id=result["object_id"], action_id="split-1", beat_id="beat-001",
                         intent=deepcopy(result["evidence_activation"]["intent"]))
        treatment = contracts.EvidenceTreatment.model_validate(treatment).model_dump(mode="json")
        contexts.append((result["object_id"], json.dumps(treatment, sort_keys=True, separators=(",", ":"))))
        window["treatment_sha256"] = digest(treatment)
    receipt = raw["split_completion_receipt"]
    for row in receipt["placements"]:
        row["content_sha256"] = digest({"authored": row["object_id"]})
    receipt.update(source_basis_sha256=digest(basis), policy_sha256=digest(policy),
                   evidence_windows=deepcopy(raw["split_evidence_windows"]))
    receipt["completion_sha256"] = digest({key: value for key, value in receipt.items()
                                           if key != "completion_sha256"})
    _, before, _ = geometry_boundary()
    frames = {row.object_id: row for row in before.objects}
    for key in ("evidence-note", "evidence-leader", "annotation-target"):
        frames[key] = replace(frames["part-1"], object_id=key)
    frames["annotation-target"] = replace(frames["annotation-target"], state="visible", visible=True,
                                           reveal_fraction=1.0)
    return _PaintBoundSplitCapture(1000, 2000, json.dumps(policy), json.dumps(basis),
        json.dumps(receipt), ("source", "part-1", "part-2"),
        ("evidence-leader", "evidence-note", "part-1", "part-2", "source"), ("annotation-target",),
        tuple(frames[key] for key in sorted(frames)),
        tuple(SplitContentReceipt(key, payloads[key], digest({"authored": key})) for key in sorted(frames)),
        evidence_treatments_json=tuple(contexts))


@pytest.mark.parametrize("at,note,leader,committed", [
    (999, 0.0, 0.0, False), (1000, 0.0, 0.0, False), (1200, 0.5, 0.0, False),
    (1400, 1.0, 0.0, False), (1500, 1.0, 0.5, False), (1600, 1.0, 1.0, False),
    (1999, 1.0, 1.0, False), (2000, 1.0, 1.0, True),
])
def test_logical_construction_uses_result_clock_without_early_semantic_commit(at, note, leader, committed):
    capture = kernel_capture()
    frozen = repr(capture)
    sampled = _sample_split_paint(capture, at)
    actual = {row.object_id: row for row in sampled.objects}
    assert "annotation-target" not in actual
    assert actual["evidence-note"].reveal_fraction == note
    assert actual["evidence-leader"].reveal_fraction == leader
    assert actual["evidence-note"].visible == (note > 0)
    assert actual["evidence-leader"].visible == (leader > 0)
    assert actual["evidence-note"].state == ("visible" if committed else "hidden")
    assert actual["evidence-leader"].state == ("visible" if committed else "hidden")
    assert repr(capture) == frozen


@pytest.mark.parametrize("fault", ["missing", "partial", "reordered", "duplicate", "extra", "noncanonical",
    "wrong_intent", "wrong_pin", "wrong_permissions", "wrong_owner", "wrong_beat", "unknown_field",
    "list_rows", "list_row", "false_rehashed_clock"])
def test_capture_context_cannot_be_invented_or_omitted_even_with_rehashed_windows(fault):
    capture = kernel_capture()
    rows = list(capture.evidence_treatments_json)
    if fault == "missing":
        rows = []
    elif fault == "partial":
        rows.pop()
    elif fault == "reordered":
        rows.reverse()
    elif fault == "duplicate":
        rows[1] = rows[0]
    elif fault == "extra":
        rows.append(("unknown-result", rows[0][1]))
    elif fault == "noncanonical":
        rows[0] = rows[0][0], json.dumps(json.loads(rows[0][1]), indent=2)
    elif fault in {"wrong_intent", "wrong_pin", "wrong_permissions", "wrong_owner", "wrong_beat", "unknown_field"}:
        treatment = json.loads(rows[0][1])
        if fault == "wrong_intent":
            treatment["intent"]["annotation"] = "Invented copy"
        elif fault == "wrong_pin":
            treatment["asset_revision"] += 1
        elif fault == "wrong_permissions":
            treatment["allowed_transformations"].reverse()
        elif fault == "wrong_owner":
            treatment["action_id"] = "not-the-split"
        elif fault == "wrong_beat":
            treatment["beat_id"] = "not-the-beat"
        else:
            treatment["invented_grant"] = True
        rows[0] = rows[0][0], json.dumps(treatment, sort_keys=True, separators=(",", ":"))
    elif fault == "list_row":
        rows[0] = list(rows[0])
    if fault == "false_rehashed_clock":
        receipt = json.loads(capture.completion_json)
        for field in ("construction_complete_ms", "readable_hold_start_ms", "readable_hold_end_ms"):
            receipt["evidence_windows"][0][field] += 1
        receipt["completion_sha256"] = digest({key: value for key, value in receipt.items()
                                               if key != "completion_sha256"})
        capture = replace(capture, completion_json=json.dumps(receipt))
    else:
        capture = replace(capture, evidence_treatments_json=rows if fault == "list_rows" else tuple(rows))
    with pytest.raises(ValueError, match="evidence|Evidence"):
        _sample_split_paint(capture, 1500)
