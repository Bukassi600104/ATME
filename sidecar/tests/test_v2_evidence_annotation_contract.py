"""P3-36 cross-object binding foundation, not runtime or Split admission."""

from copy import deepcopy

import pytest
from atme.render.v2_split_identity import _stored_value
from atme.store.contracts_v2 import (
    AnnotationPhase,
    AnnotationPolicy,
    EvidenceIntent,
    EvidenceTreatment,
)
from jsonschema import Draft202012Validator
from v2_fixtures import digest, executable_layout_v2, visual_plan_v2


def authored_evidence_annotation():
    return {"annotation_object_ids": ["evidence-note"], "leader_connector_id": "evidence-leader",
            "phases": [{"object_id": "evidence-note", "mode": "write", "weight": 2},
                       {"object_id": "evidence-leader", "mode": "draw", "weight": 1}],
            "readable_hold_ms": 2500, "retention": "retain"}


def cross_intent():
    raw = deepcopy(visual_plan_v2()["beats"][1]["evidence"])
    raw.update(annotation_target_id="object-system", annotation_policy=authored_evidence_annotation())
    return raw


def test_evidence_preserves_explicit_authored_annotation_policy_in_model_schema_and_identity():
    raw = cross_intent()
    parsed = EvidenceIntent.model_validate(raw)
    assert type(parsed.annotation_policy) is AnnotationPolicy
    assert parsed.model_dump(mode="json") == raw
    assert _stored_value(parsed) == raw
    Draft202012Validator(EvidenceIntent.model_json_schema()).validate(raw)
    changed = deepcopy(raw)
    changed["annotation_policy"]["phases"][0]["weight"] += 1
    assert digest(_stored_value(EvidenceIntent.model_validate(changed))) != digest(_stored_value(parsed))


def test_exact_typed_annotation_policy_is_revalidated_without_losing_authored_fields():
    raw = cross_intent()
    raw["annotation_policy"] = AnnotationPolicy.model_validate(raw["annotation_policy"])
    parsed = EvidenceIntent.model_validate(raw)
    assert parsed.model_dump(mode="json") == cross_intent()


@pytest.mark.parametrize("target,legacy_sha", [
    ("object-evidence", "3de7676a93cda343b5b8049c00a0cbe511ecc4d7a3df4d4f132864dd58bb3bfc"),
    ("object-system", "147acda5f2ec6bf873c4bf74f24e84723342671f536d3a74daaee89825e46c67"),
])
def test_legacy_evidence_intent_and_identity_keep_exact_omitted_shape(target, legacy_sha):
    raw = deepcopy(visual_plan_v2()["beats"][1]["evidence"])
    raw["annotation_target_id"] = target
    parsed = EvidenceIntent.model_validate(raw)
    assert parsed.model_dump(mode="json") == raw
    assert _stored_value(parsed) == raw
    assert digest(_stored_value(parsed)) == legacy_sha
    Draft202012Validator(EvidenceIntent.model_json_schema()).validate(raw)


@pytest.mark.parametrize("fault", ["null", "empty", "no-leader", "no-annotation", "hold",
                                     "extra", "bool-weight", "string-weight", "float-weight"])
def test_supplied_evidence_annotation_policy_has_one_explicit_strict_authority(fault):
    raw = cross_intent()
    policy = raw["annotation_policy"]
    if fault == "null":
        raw["annotation_policy"] = None
    elif fault == "empty":
        raw["annotation_policy"] = {}
    elif fault == "no-leader":
        policy["leader_connector_id"] = None
        policy["phases"].pop()
    elif fault == "no-annotation":
        raw.update(annotation=None, annotation_target_id=None, annotation_omission_reason="No annotation")
    elif fault == "hold":
        policy["readable_hold_ms"] += 1
    elif fault == "extra":
        policy["generated_text"] = "Not authored"
    else:
        policy["phases"][0]["weight"] = {"bool-weight": True, "string-weight": "2", "float-weight": 2.0}[fault]
    with pytest.raises(ValueError):
        EvidenceIntent.model_validate(raw)


def test_self_target_treatment_forbids_competing_authored_policy():
    raw = deepcopy(executable_layout_v2()["evidence_treatments"][0])
    raw["intent"]["annotation_policy"] = authored_evidence_annotation()
    with pytest.raises(ValueError):
        EvidenceTreatment.model_validate(raw)


@pytest.mark.parametrize("model,raw", [(EvidenceIntent, visual_plan_v2()["beats"][1]["evidence"]),
                                      (AnnotationPolicy, authored_evidence_annotation()),
                                      (AnnotationPhase, authored_evidence_annotation()["phases"][0])])
def test_identity_rejects_unknown_nested_evidence_authority_subclasses(model, raw):
    class UntrustedAuthority(model):
        pass

    unsafe = UntrustedAuthority.model_validate(raw)
    with pytest.raises(ValueError, match="unknown nested"):
        _stored_value(unsafe)


@pytest.mark.parametrize("fault", ["subclass", "missing", "extra", "invalid-phase",
                                     "phase-subclass", "phase-extra", "fields-set"])
def test_typed_annotation_policy_cannot_bypass_new_evidence_ingress(fault):
    raw = cross_intent()
    policy = AnnotationPolicy.model_validate(raw["annotation_policy"])
    if fault == "subclass":
        class UntrustedPolicy(AnnotationPolicy):
            pass
        policy = UntrustedPolicy.model_validate(raw["annotation_policy"])
    elif fault == "missing":
        del policy.__dict__["phases"]
    elif fault == "extra":
        policy.__dict__["generated"] = True
    elif fault == "invalid-phase":
        policy.phases[0].weight = True
    elif fault == "phase-subclass":
        class UntrustedPhase(AnnotationPhase):
            pass
        policy.phases[0] = UntrustedPhase.model_validate(policy.phases[0].model_dump())
    elif fault == "phase-extra":
        policy.phases[0].__dict__["generated"] = True
    else:
        policy.__pydantic_fields_set__.add("unrecognized")
    raw["annotation_policy"] = policy
    with pytest.raises(ValueError):
        EvidenceIntent.model_validate(raw)


def test_identity_cannot_erase_explicit_null_from_bypassed_evidence_intent():
    raw = deepcopy(visual_plan_v2()["beats"][1]["evidence"])
    unsafe = EvidenceIntent.model_construct(**raw)
    unsafe.__dict__["annotation_policy"] = None
    unsafe.__pydantic_fields_set__.add("annotation_policy")
    with pytest.raises(ValueError):
        _stored_value(unsafe)


@pytest.mark.parametrize("fault", ["raw-policy", "intent-subclass", "explicit-null"])
def test_already_typed_evidence_intent_cannot_bypass_new_annotation_authority(fault):
    parsed = EvidenceIntent.model_validate(cross_intent())
    if fault == "raw-policy":
        unsafe = parsed.model_copy(update={"annotation_policy": authored_evidence_annotation()})
    elif fault == "intent-subclass":
        class UntrustedIntent(EvidenceIntent):
            pass
        unsafe = UntrustedIntent.model_construct(**parsed.__dict__)
    else:
        unsafe = parsed.model_copy(update={"annotation_policy": None})
    with pytest.raises(ValueError):
        EvidenceIntent.model_validate(unsafe)


@pytest.mark.parametrize("fault", ["phase-bool", "phase-string", "phase-zero",
                                  "policy-inventory", "policy-hold", "intent-authority",
                                  "treatment-intent", "treatment-permissions"])
def test_direct_identity_revalidates_complete_but_invalid_evidence_authority(fault):
    if fault.startswith("phase-"):
        unsafe = AnnotationPhase.model_validate(authored_evidence_annotation()["phases"][0])
        unsafe.weight = {"phase-bool": True, "phase-string": "2", "phase-zero": 0}[fault]
    elif fault.startswith("policy-"):
        unsafe = AnnotationPolicy.model_validate(authored_evidence_annotation())
        if fault == "policy-inventory":
            unsafe.annotation_object_ids = ["undeclared-note"]
        else:
            unsafe.readable_hold_ms = 0
    elif fault == "intent-authority":
        unsafe = EvidenceIntent.model_validate(cross_intent())
        unsafe.readable_hold_intent_ms += 1
    else:
        unsafe = EvidenceTreatment.model_validate(executable_layout_v2()["evidence_treatments"][0])
        if fault == "treatment-intent":
            unsafe.intent = EvidenceIntent.model_validate(cross_intent())
            unsafe.intent.annotation_target_id = unsafe.object_id
        else:
            unsafe.allowed_transformations = []
    with pytest.raises(ValueError):
        _stored_value(unsafe)


@pytest.mark.parametrize("model,raw", [
    (AnnotationPhase, authored_evidence_annotation()["phases"][0]),
    (AnnotationPolicy, authored_evidence_annotation()),
    (EvidenceIntent, cross_intent()),
    (EvidenceTreatment, executable_layout_v2()["evidence_treatments"][0]),
])
@pytest.mark.parametrize("fault", ["unknown", "missing-required"])
def test_direct_identity_rejects_bypassed_evidence_field_set(model, raw, fault):
    unsafe = model.model_validate(raw)
    if fault == "unknown":
        unsafe.__pydantic_fields_set__.add("unrecognized")
    else:
        required = next(key for key, field in model.model_fields.items() if field.is_required())
        unsafe.__pydantic_fields_set__.discard(required)
    with pytest.raises(ValueError):
        _stored_value(unsafe)


def test_published_evidence_schema_rejects_explicit_null_annotation_policy():
    raw = cross_intent()
    raw["annotation_policy"] = None
    assert not Draft202012Validator(EvidenceIntent.model_json_schema()).is_valid(raw)
