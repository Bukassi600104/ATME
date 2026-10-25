"""Task8 authority syntax is not attestation, graph, runtime or family admission."""

from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator
from test_v2_split_identity import completion_document
from v2_fixtures import digest, visual_plan_v2
from v2_split_fixtures import split_documents, split_policy

from atme.render.v2_split_identity import _stored_value
from atme.store import contracts_v2 as contracts


def authority_type(name):
    assert hasattr(contracts, name), f"approved Task8 {name} contract is missing"
    return getattr(contracts, name)


def activation_payload(result_id="part-1"):
    original = visual_plan_v2()
    asset = original["assets"][0]
    intent = deepcopy(original["beats"][1]["evidence"])
    intent.update(claim_id=f"claim-{result_id}", annotation_target_id=result_id)
    permissions = deepcopy(asset["allowed_transformations"])
    return {"result_object_id": result_id, "beat_id": "beat-001", "causal_action_id": "split-1",
        "intent": intent, "asset_pin": {"asset_id": asset["asset_id"], "revision": asset["revision"],
            "resource_uri": f"atme://projects/{original['project_id']}/assets/{asset['asset_id']}",
            "checksum_sha256": asset["checksum_sha256"]},
        "permission_sha256": digest(permissions), "allowed_transformations": permissions}


def window_payload(result_id="part-1", *, construction=1600, movement=1400):
    hold = max(construction, movement)
    return {"result_object_id": result_id, "treatment_sha256": "d" * 64,
        "construction_complete_ms": construction, "movement_complete_ms": movement,
        "readable_hold_start_ms": hold, "readable_hold_end_ms": hold + 2500}


@pytest.mark.parametrize("permissions", [None, ["scale", "crop", "annotate", "color_treatment"],
                                         ["crop", "scale", "annotate", "crop", "color_treatment"]])
def test_semantic_activation_preserves_exact_authored_authority_and_ordered_permission_pin(permissions):
    model = authority_type("SplitEvidenceActivation")
    raw = activation_payload()
    if permissions is not None:
        raw.update(allowed_transformations=permissions, permission_sha256=digest(permissions))
    parsed = model.model_validate(raw)
    assert parsed.model_dump(mode="json") == raw
    assert _stored_value(parsed) == raw
    Draft202012Validator(model.model_json_schema()).validate(raw)
    assert parsed.intent.evidence_asset_id == parsed.asset_pin.asset_id


@pytest.mark.parametrize("fault", ["absolute_time", "wrong_asset", "wrong_permission_hash", "reordered_permission",
    "extra", "empty_permissions", "unknown_permission", "bool_revision", "blank_owner", "blank_result"])
def test_semantic_activation_rejects_unbound_or_invented_authority(fault):
    model = authority_type("SplitEvidenceActivation")
    raw = activation_payload()
    if fault == "absolute_time":
        raw["readable_hold_start_ms"] = 1600
    elif fault == "wrong_asset":
        raw["asset_pin"]["asset_id"] = "unrelated-asset"
    elif fault == "wrong_permission_hash":
        raw["permission_sha256"] = "0" * 64
    elif fault == "reordered_permission":
        raw["allowed_transformations"].reverse()
    elif fault == "extra":
        raw["invented_attestation"] = True
    elif fault == "empty_permissions":
        raw.update(allowed_transformations=[], permission_sha256=digest([]))
    elif fault == "unknown_permission":
        raw["allowed_transformations"].append("rewrite_source")
        raw["permission_sha256"] = digest(raw["allowed_transformations"])
    elif fault == "bool_revision":
        raw["asset_pin"]["revision"] = True
    elif fault == "blank_owner":
        raw["causal_action_id"] = " "
    else:
        raw["result_object_id"] = " "
    with pytest.raises(ValueError):
        model.model_validate(raw)


def test_exact_typed_activation_revalidates_nested_intent_and_pin_without_losing_omission():
    model = authority_type("SplitEvidenceActivation")
    raw = activation_payload()
    raw["intent"] = contracts.EvidenceIntent.model_validate(raw["intent"])
    raw["asset_pin"] = contracts.SplitAssetPin.model_validate(raw["asset_pin"])
    assert model.model_validate(raw).model_dump(mode="json") == activation_payload()


@pytest.mark.parametrize("fault", ["intent_subclass", "pin_subclass", "intent_unsafe", "pin_unknown", "pin_fieldset"])
def test_nested_typed_activation_cannot_launder_constructed_or_subclass_authority(fault):
    model = authority_type("SplitEvidenceActivation")
    raw = activation_payload()
    if fault == "intent_subclass":
        class UnknownIntent(contracts.EvidenceIntent):
            pass

        raw["intent"] = UnknownIntent.model_validate(raw["intent"])
    elif fault == "pin_subclass":
        class UnknownPin(contracts.SplitAssetPin):
            pass

        raw["asset_pin"] = UnknownPin.model_validate(raw["asset_pin"])
    elif fault == "intent_unsafe":
        raw["intent"] = contracts.EvidenceIntent.model_validate(raw["intent"])
        raw["intent"].crop = raw["intent"].crop.model_copy(update={"width": -1})
    else:
        pin = contracts.SplitAssetPin.model_validate(raw["asset_pin"])
        if fault == "pin_unknown":
            pin.__dict__["unknown_grant"] = True
        else:
            pin.__pydantic_fields_set__.remove("revision")
        raw["asset_pin"] = pin
    with pytest.raises(ValueError):
        model.model_validate(raw)


@pytest.mark.parametrize("construction,movement", [(1600, 1400), (1400, 1800), (1600, 1600)])
def test_resolved_window_preserves_parallel_phase_completion_without_inventing_treatment(construction, movement):
    model = authority_type("ResolvedSplitEvidenceWindow")
    raw = window_payload(construction=construction, movement=movement)
    parsed = model.model_validate(raw)
    assert parsed.model_dump(mode="json") == raw
    assert _stored_value(parsed) == raw
    Draft202012Validator(model.model_json_schema()).validate(raw)


@pytest.mark.parametrize("field,value", [("construction_complete_ms", True), ("movement_complete_ms", "1400"),
    ("readable_hold_start_ms", 1600.0), ("readable_hold_end_ms", False), ("construction_complete_ms", -1),
    ("readable_hold_start_ms", 1599), ("readable_hold_end_ms", 1600), ("treatment_sha256", "unverified")])
def test_resolved_window_rejects_coercion_or_premature_hold_syntax(field, value):
    model = authority_type("ResolvedSplitEvidenceWindow")
    raw = window_payload()
    raw[field] = value
    with pytest.raises(ValueError):
        model.model_validate(raw)


@pytest.mark.parametrize("fault", ["wrong_result", "wrong_destination", "null"])
def test_result_requires_its_exact_semantic_activation_and_destination_state(fault):
    authority_type("SplitEvidenceActivation")
    raw = split_policy()["results"][0]
    raw.update(post_state="evidence_visible", evidence_activation=activation_payload())
    if fault == "wrong_result":
        raw["evidence_activation"]["result_object_id"] = "part-2"
    elif fault == "wrong_destination":
        raw["post_state"] = "visible"
    else:
        raw["evidence_activation"] = None
    with pytest.raises(ValueError):
        contracts.SplitResult.model_validate(raw)


def test_result_keeps_explicit_evidence_state_and_immutable_identity_without_family_admission():
    authority_type("SplitEvidenceActivation")
    raw = split_policy()["results"][0]
    raw.update(post_state="evidence_visible", evidence_activation=activation_payload())
    parsed = contracts.SplitResult.model_validate(raw)
    assert parsed.post_state == "evidence_visible"
    assert parsed.model_dump(mode="json") == raw
    assert _stored_value(parsed) == raw


@pytest.mark.parametrize("name,expected_sha", [
    ("SplitResult", "a92eaf0eb9070f2dfd03813aeaca54a091c648806e9c158e7cee2f655f251f6a"),
    ("SplitCompletionReceipt", "2ba4fffadfef1150956a6396e1d6dcb2595be950d8bc398faa66d516d2cfb2a8"),
    ("ResolvedAction", "c446b588b5a329c878561dcb6b2c4e03ded486a024d6575b803d023b0930a443")])
def test_non_evidence_split_keeps_pre_task8_serialized_shape_and_identity(name, expected_sha):
    raw = (split_policy()["results"][0] if name == "SplitResult" else
           completion_document()["split_completion_receipt"] if name == "SplitCompletionReceipt" else
           completion_document())
    parsed = getattr(contracts, name).model_validate(raw)
    assert parsed.model_dump(mode="json") == raw
    assert digest(parsed.model_dump(mode="json")) == expected_sha
    if name != "ResolvedAction":
        assert _stored_value(parsed) == raw


def evidence_completion_document(*, two_results=False):
    """Independent identity-pose fixture, not a capture or treatment attestation."""
    _plan, _layout, timeline = split_documents()
    document = deepcopy(timeline["actions"][0])
    policy = document["action"]["split_policy"]
    for result in policy["results"][:2 if two_results else 1]:
        result.update(post_state="evidence_visible", evidence_activation=activation_payload(result["object_id"]))
        result["movement"] = {"phase": {"start_tick": 0, "end_tick": 4000, "easing": "linear"},
                              "from_transform": deepcopy(result["destination"]),
                              "destination": deepcopy(result["destination"])}
    basis = policy["source_basis"]
    basis["asset_pins"] = [deepcopy(activation_payload()["asset_pin"])]
    policy["source_basis_sha256"] = digest(basis)
    # Canonicalize existing primitive syntax, never call completion derivation.
    policy = contracts.SplitPolicy.model_validate(policy).model_dump(mode="json")
    document["action"]["split_policy"] = policy
    document.update(start_ms=1000, end_ms=2000)
    basis = policy["source_basis"]
    placements = deepcopy(basis["placements"])
    for row in placements:
        if row["object_id"] == "source":
            row.update(state="removed", local_visibility=False, effective_visibility=False,
                       local_opacity=0.0, reveal=0.0, state_version=2)
        else:
            row.update(state=next(result["post_state"] for result in policy["results"]
                                  if result["object_id"] == row["object_id"]),
                       local_visibility=True, effective_visibility=True, reveal=1.0, state_version=2)
    windows = [window_payload(result["object_id"]) for result in policy["results"]
               if "evidence_activation" in result]
    receipt = {"source_basis_sha256": digest(basis), "policy_sha256": digest(policy),
               "placements": placements, "read_dependencies": [], "asset_pins": basis["asset_pins"],
               "style_sha256": basis["style_sha256"], "registry_sha256": basis["registry_sha256"],
               "evidence_windows": deepcopy(windows)}
    receipt["completion_sha256"] = digest(receipt)
    document.update(split_completion_receipt=receipt, split_evidence_windows=windows)
    return document


@pytest.mark.parametrize("two_results", [False, True])
def test_resolved_split_carries_ordered_windows_in_action_and_checksummed_receipt(two_results):
    raw = evidence_completion_document(two_results=two_results)
    parsed = contracts.ResolvedAction.model_validate(raw)
    assert parsed.model_dump(mode="json") == raw
    assert _stored_value(parsed.split_completion_receipt) == raw["split_completion_receipt"]
    assert [row.result_object_id for row in parsed.split_evidence_windows] == (
        ["part-1", "part-2"] if two_results else ["part-1"])
    # Opaque syntax is deliberately not proof of treatment or actual phase times.
    assert parsed.split_evidence_windows[0].treatment_sha256 == "d" * 64


@pytest.mark.parametrize("fault", ["missing_action_windows", "missing_receipt_windows", "reordered", "missing_result",
    "duplicate", "extra_result", "window_mismatch", "rehashed_false_state", "rehashed_false_version",
    "rehashed_false_content", "rehashed_false_basis", "rehashed_false_permission_pin", "bad_window_checksum"])
def test_split_window_binding_does_not_weaken_exact_base_completion(fault):
    raw = evidence_completion_document(two_results=True)
    receipt = raw["split_completion_receipt"]
    if fault == "missing_action_windows":
        raw.pop("split_evidence_windows")
    elif fault == "missing_receipt_windows":
        receipt.pop("evidence_windows")
    elif fault == "reordered":
        raw["split_evidence_windows"].reverse()
        receipt["evidence_windows"].reverse()
    elif fault == "missing_result":
        raw["split_evidence_windows"].pop()
        receipt["evidence_windows"].pop()
    elif fault == "duplicate":
        raw["split_evidence_windows"][1] = deepcopy(raw["split_evidence_windows"][0])
        receipt["evidence_windows"] = deepcopy(raw["split_evidence_windows"])
    elif fault == "extra_result":
        raw["split_evidence_windows"].append(window_payload("invented-result"))
        receipt["evidence_windows"] = deepcopy(raw["split_evidence_windows"])
    elif fault == "window_mismatch":
        receipt["evidence_windows"][0]["treatment_sha256"] = "e" * 64
    elif fault == "rehashed_false_basis":
        receipt["source_basis_sha256"] = "f" * 64
    elif fault == "rehashed_false_permission_pin":
        receipt["asset_pins"] = []
    elif fault == "bad_window_checksum":
        receipt["evidence_windows"][0]["readable_hold_end_ms"] += 1
        raw["split_evidence_windows"][0]["readable_hold_end_ms"] += 1
    else:
        result = next(row for row in receipt["placements"] if row["object_id"] == "part-1")
        field, value = {"rehashed_false_state": ("state", "visible"),
                        "rehashed_false_version": ("state_version", 3),
                        "rehashed_false_content": ("content_sha256", "f" * 64)}[fault]
        result[field] = value
    if fault != "bad_window_checksum":
        receipt["completion_sha256"] = digest({key: value for key, value in receipt.items()
                                               if key != "completion_sha256"})
    with pytest.raises(ValueError):
        contracts.ResolvedAction.model_validate(raw)


@pytest.mark.parametrize("owner,field", [("ResolvedAction", "split_evidence_windows"),
                                        ("SplitCompletionReceipt", "evidence_windows")])
@pytest.mark.parametrize("value", [None, [], "invented", [None]])
def test_window_authority_must_be_omitted_or_exact_nonempty_list(owner, field, value):
    raw = evidence_completion_document()
    if owner == "SplitCompletionReceipt":
        raw = raw["split_completion_receipt"]
    raw[field] = value
    with pytest.raises(ValueError):
        getattr(contracts, owner).model_validate(raw)


@pytest.mark.parametrize("fault", ["window_subclass", "unknown_field", "missing_authority", "unsafe_timestamp"])
def test_window_identity_rejects_unsafe_typed_parent_payloads(fault):
    raw = evidence_completion_document()
    model = authority_type("ResolvedSplitEvidenceWindow")
    window = model.model_validate(raw["split_evidence_windows"][0])
    if fault == "window_subclass":
        class UnknownWindow(model):
            pass

        window = UnknownWindow.model_validate(window.model_dump())
    elif fault == "unknown_field":
        window.__dict__["invented"] = True
    elif fault == "missing_authority":
        window.__pydantic_fields_set__.remove("treatment_sha256")
    else:
        window = window.model_copy(update={"construction_complete_ms": True})
    raw["split_evidence_windows"] = [window]
    with pytest.raises(ValueError):
        contracts.ResolvedAction.model_validate(raw)


@pytest.mark.parametrize("fault", ["wrong_action", "wrong_board", "missing_basis_pin", "changed_basis_pin"])
def test_activation_binds_actual_causal_split_and_basis_asset_pin(fault):
    raw = evidence_completion_document()["action"]
    policy = raw["split_policy"]
    activation = policy["results"][0]["evidence_activation"]
    if fault == "wrong_action":
        activation["causal_action_id"] = "not-this-split"
    elif fault == "wrong_board":
        activation["intent"]["destination_board_id"] = "other-board"
    elif fault == "missing_basis_pin":
        policy["source_basis"]["asset_pins"] = []
    else:
        policy["source_basis"]["asset_pins"][0]["revision"] += 1
    policy["source_basis_sha256"] = digest(policy["source_basis"])
    with pytest.raises(ValueError):
        contracts.SplitAction.model_validate(raw)


def test_non_evidence_split_rejects_evidence_windows_even_without_receipt():
    raw = completion_document()
    raw.pop("split_completion_receipt")
    raw["split_evidence_windows"] = [window_payload()]
    with pytest.raises(ValueError):
        contracts.ResolvedAction.model_validate(raw)


def test_evidence_split_windows_cannot_omit_checksummed_completion_receipt():
    raw = evidence_completion_document()
    raw.pop("split_completion_receipt")
    with pytest.raises(ValueError):
        contracts.ResolvedAction.model_validate(raw)


@pytest.mark.parametrize("fault", ["result_state", "result_id", "result_fieldset", "pin_bool_revision",
                                     "pin_blank_id", "pin_fieldset"])
def test_policy_identity_cannot_launder_mutated_result_or_asset_authority(fault):
    raw = evidence_completion_document()["action"]["split_policy"]
    policy = contracts.SplitPolicy.model_validate(raw)
    if fault == "result_state":
        policy.results[0].post_state = "visible"
    elif fault == "result_id":
        policy.results[0].object_id = "invented-result"
    elif fault == "result_fieldset":
        policy.results[0].__pydantic_fields_set__.remove("object_id")
    elif fault == "pin_bool_revision":
        policy.source_basis.asset_pins[0].revision = True
    elif fault == "pin_blank_id":
        policy.source_basis.asset_pins[0].asset_id = " "
    else:
        policy.source_basis.asset_pins[0].__pydantic_fields_set__.remove("revision")
    with pytest.raises(ValueError):
        _stored_value(policy)


def test_completion_digest_projects_window_changes_but_excludes_only_self_hash():
    from atme.render.v2_split_identity import split_completion_digest

    receipt = contracts.SplitCompletionReceipt.model_validate(
        evidence_completion_document()["split_completion_receipt"])
    assert split_completion_digest(receipt) == receipt.completion_sha256
    changed = receipt.model_copy(update={"completion_sha256": "0" * 64}, deep=True)
    assert split_completion_digest(changed) == split_completion_digest(receipt)
    changed.evidence_windows[0].readable_hold_end_ms += 1
    assert split_completion_digest(changed) != split_completion_digest(receipt)
    with pytest.raises(ValueError):
        contracts.SplitCompletionReceipt.model_validate(changed)


@pytest.mark.parametrize("evidence", [False, True])
def test_replay_identity_roundtrip_omits_absent_new_action_authority(evidence):
    raw = evidence_completion_document() if evidence else completion_document()
    parsed = contracts.ResolvedAction.model_validate(raw)
    stored = _stored_value(parsed)
    if not evidence:
        assert "split_evidence_windows" not in stored
        expected = deepcopy(raw)
        expected["return_hierarchy_receipt"] = None
        expected["action"]["hierarchy_policy"] = None
        assert stored == expected  # Exact old packet, including its older null fields.
    restored = contracts.ResolvedAction.model_validate(stored)
    assert restored.model_dump(mode="json") == raw


def test_replay_identity_does_not_silently_drop_explicit_null_new_action_authority():
    parsed = contracts.ResolvedAction.model_validate(completion_document())
    parsed = parsed.model_copy(update={"split_evidence_windows": None})
    with pytest.raises(ValueError):
        _stored_value(parsed)


@pytest.mark.parametrize("fault", ["subclass", "missing_required_fieldset", "unknown_fieldset"])
def test_replay_identity_requires_exact_resolved_action_authority_inventory(fault):
    raw = evidence_completion_document()
    if fault == "subclass":
        class UnknownResolvedAction(contracts.ResolvedAction):
            pass

        parsed = UnknownResolvedAction.model_validate(raw)
    else:
        parsed = contracts.ResolvedAction.model_validate(raw)
        if fault == "missing_required_fieldset":
            parsed.__pydantic_fields_set__.remove("action")
        else:
            parsed.__pydantic_fields_set__.add("invented_authority")
    with pytest.raises(ValueError):
        _stored_value(parsed)
