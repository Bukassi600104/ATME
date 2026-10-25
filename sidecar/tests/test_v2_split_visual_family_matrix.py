"""Approved F03 state/family and coherent-receipt boundary matrix."""

import io
import json
from dataclasses import replace
from hashlib import sha256

import pytest
from PIL import Image
from test_v2_character_assembly_compositor import original_pose_documents
from test_v2_illustration_assembly_compositor import original_illustration_documents
from test_v2_split_code_family import code_split_frames
from test_v2_split_identity import sample_for_layout
from test_v2_split_visual_family import (
    authored_receipts,
    illustration_boundary,
    split_timeline,
)
from test_v2_technical_frame_compositor import composite_documents
from test_v2_technical_frame_contract import CASES
from v2_fixtures import digest

from atme.render.v2_split import _observed_split_placements, capture_split
from atme.render.v2_split_paint import split_family_admission, verify_split_paint_inputs
from atme.render.v2_svg import compose_png_frame
from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    ResolvedAction,
    SplitPolicy,
    _split_expected_completion,
)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def repin(raw, action):
    """Rebind geometry/state changes with independently authored content pins."""
    layout = ExecutableLayoutV2.model_validate(raw)
    before = sample_for_layout(layout)
    receipts = authored_receipts(raw["objects"])
    action = action.model_dump(mode="json")
    policy = action["action"]["split_policy"]
    basis = policy["source_basis"]
    objects = {obj.object_id: obj for obj in layout.objects}
    basis["placements"] = [row.model_dump(mode="json") for row in
        _observed_split_placements(before, objects, set(objects), receipts)]
    for row in policy["correspondences"]:
        row.update(source_content_sha256=receipts["source"].content_sha256,
            result_content_sha256=receipts[row["result_object_id"]].content_sha256)
    policy["source_basis_sha256"] = digest(basis)
    completion = _split_expected_completion(SplitPolicy.model_validate(policy))
    completion["completion_sha256"] = digest(completion)
    action["split_completion_receipt"] = completion
    return layout, before, ResolvedAction.model_validate(action), receipts


STATE_CASES = ([('character', pose, True) for pose in ('neutral', 'point_right', 'open_hands')]
    + [('illustration', kind, active) for kind in ('icon', 'pictogram', 'device', 'document', 'terminal')
       for active in (False, True)]
    + [('technical', kind, state) for kind, states, _ in CASES for state in states])


def visual_state_layout(family, kind, state, portrait, *, owner="part-1", mode="reveal"):
    layout, before, action, receipts = illustration_boundary(family=family, kind=kind,
        active=state if family == "illustration" else True, portrait=portrait, owner=owner, mode=mode)
    if family == "technical":
        raw = layout.model_dump(mode="json")
        chrome = next(obj for obj in raw["objects"] if obj.get("technical_frame"))
        chrome["variant"] = chrome["technical_frame"]["display_state"] = state
        layout, before, action, receipts = repin(raw, action)
    return layout, before, action, receipts


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("family,kind,state", STATE_CASES)
def test_existing_real_family_states_retain_pinned_native_payload_through_split(family, kind, state, portrait):
    layout, before, action, receipts = visual_state_layout(family, kind, state, portrait)
    if family == "technical":
        _, _, roles = next(row for row in CASES if row[0] == kind)
        native, native_timeline = composite_documents(kind, state, roles, portrait=portrait)
    elif family == "character":
        native, native_timeline = original_pose_documents(kind, portrait=portrait)
    else:
        native, native_timeline = original_illustration_documents(kind, active=state, portrait=portrait)
    capture = capture_split(action, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    admission = split_family_admission("part-1", capture, layout, inputs)
    assert admission.content_sha256 == receipts["part-1"].content_sha256
    assert receipts["source"].content_sha256 != receipts["part-1"].content_sha256
    assert admission.family == {"character": "authored character", "illustration": "authored illustration",
        "technical": "technical illustration"}[family]
    outputs = code_split_frames(layout, before, action, split_timeline(layout, before, action), inputs, (40, 0, 40))
    actual = Image.open(io.BytesIO(outputs[40][1])).convert("RGBA")
    expected = Image.open(io.BytesIO(compose_png_frame(native, native_timeline, 0).png)).convert("RGBA")
    assert actual.crop((100, 180, 620, 610)).tobytes() == expected.crop((100, 180, 620, 610)).tobytes()


@pytest.mark.parametrize("family,field", [("character", "pose_id"), ("illustration", "content_state_id")])
def test_fresh_valid_owner_binding_cannot_replace_captured_identity(family, field):
    layout, before, action, _ = illustration_boundary(family=family)
    capture = capture_split(action, layout, before, {})
    raw = layout.model_dump(mode="json")
    owner = next(obj for obj in raw["objects"] if obj["object_id"] == "part-1")
    owner[family + "_assembly"][field] = "point_right" if family == "character" else "another-authored-state"
    changed = ExecutableLayoutV2.model_validate(raw)
    with pytest.raises(ValueError, match="Split captured content differs"):
        split_family_admission("part-1", capture, changed, verify_split_paint_inputs(changed, {}))


@pytest.mark.parametrize("family", ["character", "illustration", "technical"])
def test_coherently_rehashed_sibling_order_cannot_rearrange_assembly_roles(family):
    layout, before, action, _ = illustration_boundary(family=family)
    capture = capture_split(action, layout, before, {})
    policy = json.loads(capture.policy_json)
    basis = policy["source_basis"]
    children = [row for row in basis["placements"] if row["parent_id"] == "part-1"]
    children[0]["sibling_ordinal"], children[1]["sibling_ordinal"] = children[1]["sibling_ordinal"], children[0]["sibling_ordinal"]
    policy["source_basis_sha256"] = digest(basis)
    completion = _split_expected_completion(SplitPolicy.model_validate(policy))
    completion["completion_sha256"] = digest(completion)
    changed = replace(capture, policy_json=canonical(policy), basis_json=canonical(basis), completion_json=canonical(completion))
    with pytest.raises(ValueError, match="character_assembly|illustration_assembly|technical_frame"):
        split_family_admission("part-1", changed, layout, verify_split_paint_inputs(layout, {}))


@pytest.mark.parametrize("fault", ["missing", "registry_proof", "alpha", "state"])
def test_rehashed_native_chrome_evidence_cannot_be_replaced_by_author_claims(fault):
    layout, before, action, _ = illustration_boundary(family="technical")
    capture = capture_split(action, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    rows = [json.loads(row) for row in inputs.paint_evidence]
    chrome = next(row for row in rows if row.get("family") == "technical chrome")
    assert chrome["proof_kind"] == "native_technical_chrome_alpha_v1"
    assert "asset_sha256" not in chrome["paint"]
    if fault == "missing":
        rows.remove(chrome)
    elif fault == "registry_proof":
        chrome.update(family="registry illustration", proof_kind="pinned_registry_alpha_v1")
    elif fault == "alpha":
        chrome["paint"]["alpha_sha256"] = "0" * 64
    else:
        chrome["paint"]["display_state"] = "error"
    manifest = json.loads(inputs.manifest_json)
    manifest["paint_evidence"] = rows
    encoded = canonical(manifest)
    forged = replace(inputs, paint_evidence=tuple(canonical(row) for row in rows),
        manifest_json=encoded, inputs_sha256=sha256(encoded.encode()).hexdigest())
    with pytest.raises(ValueError, match="Split frozen paint binding differs"):
        split_family_admission("part-1", capture, layout, forged)
