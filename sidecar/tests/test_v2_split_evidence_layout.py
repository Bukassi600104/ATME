"""Task8 plan/layout authority; placeholder basis pins are not native proof."""

from copy import deepcopy

import pytest
from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    VisualPlanV2,
    validate_plan_evidence_completeness,
    validate_plan_layout,
)
from test_v2_evidence_annotation_objects import cross_annotation_documents
from test_v2_split_evidence_graph import split_evidence_plan
from v2_fixtures import digest, executable_layout_v2


def authored_treatment(plan, *, object_id, action_id, beat_id, intent):
    """Copy the authored authority explicitly, never call a treatment compiler."""
    asset = next(asset for asset in plan["assets"] if asset["asset_id"] == intent["evidence_asset_id"])
    return {"object_id": object_id, "action_id": action_id, "beat_id": beat_id,
            "asset_revision": asset["revision"], "asset_checksum_sha256": asset["checksum_sha256"],
            "asset_managed_ref": asset["managed_ref"], "asset_width": asset["width"],
            "asset_height": asset["height"], "asset_provenance": deepcopy(asset["provenance"]),
            "allowed_transformations": deepcopy(asset["allowed_transformations"]), "intent": deepcopy(intent)}


def evidence_layout_documents(*, ordinary=False, same_beat=False, cross=False, portrait=False):
    plan = split_evidence_plan(ordinary=ordinary, same_beat=same_beat, cross=cross)
    layout = executable_layout_v2()
    templates = {obj["object_type"]: obj for obj in layout["objects"]}
    annotation_templates = {obj["object_id"]: obj for obj in cross_annotation_documents()[1]["objects"][-2:]}
    objects = []
    for spec in plan["objects"]:
        template = (annotation_templates[spec["object_id"]] if spec["object_id"] in annotation_templates else
                    templates["evidence"] if spec["object_type"] == "evidence" else templates["rounded_rectangle"])
        obj = deepcopy(template)
        obj.update(deepcopy(spec), visible=spec["initial_state"] != "hidden")
        if obj["object_id"] == "evidence-leader":
            obj.update(source_object_id="part-1", destination_object_id="source")
        if obj["object_type"] == "rectangle":
            obj["geometry"]["corner_radius"] = None
        if obj["object_id"] == "part-2":
            obj["z_index"] = 4
        objects.append(obj)
    treatments = []
    split = plan["actions"][0]
    for result in split["split_policy"]["results"]:
        activation = result["evidence_activation"]
        treatments.append(authored_treatment(plan, object_id=result["object_id"], action_id=split["action_id"],
            beat_id=activation["beat_id"], intent=activation["intent"]))
    if ordinary:
        beat = plan["beats"][0 if same_beat else 1]
        treatments.append(authored_treatment(plan, object_id="object-evidence", action_id="action-3",
                                             beat_id=beat["beat_id"], intent=beat["evidence"]))
    if portrait:
        plan["output_profile"].update(profile_id="SHORT_FORM_9_16", width=720, height=1280)
    layout.update(objects=objects, evidence_treatments=treatments, boards=deepcopy(plan["boards"]),
                  plan_id=plan["plan_id"], plan_sha256=digest(plan), output_profile=deepcopy(plan["output_profile"]),
                  canvas={"x": 0, "y": 0, "width": plan["output_profile"]["width"],
                          "height": plan["output_profile"]["height"]})
    return plan, layout


@pytest.mark.parametrize("ordinary,same_beat,cross", [(False, False, False), (True, False, False),
                                                     (True, True, False), (False, False, True)])
@pytest.mark.parametrize("portrait", [False, True])
def test_new_plan_accepts_exact_split_evidence_owners_without_fake_insert(ordinary, same_beat, cross, portrait):
    plan, _layout = evidence_layout_documents(ordinary=ordinary, same_beat=same_beat, cross=cross, portrait=portrait)
    before = deepcopy(plan)
    validate_plan_evidence_completeness(plan)
    assert plan == before
    assert [action["action_id"] for action in plan["actions"] if action["verb"] == "insert_evidence"] == (
        ["action-3"] if ordinary else [])


@pytest.mark.parametrize("ordinary,same_beat,cross", [(False, False, False), (True, False, False),
                                                     (True, True, False), (False, False, True)])
@pytest.mark.parametrize("portrait", [False, True])
def test_layout_keeps_multiple_exact_split_treatments_on_the_real_causal_action(ordinary, same_beat, cross, portrait):
    plan, layout = evidence_layout_documents(ordinary=ordinary, same_beat=same_beat, cross=cross, portrait=portrait)
    before = deepcopy(layout)
    parsed = ExecutableLayoutV2.model_validate(layout)
    validate_plan_layout(plan, layout)
    assert layout == before
    assert [(row.action_id, row.object_id) for row in parsed.evidence_treatments] == (
        [("split-1", "part-1"), ("split-1", "part-2")] + ([("action-3", "object-evidence")] if ordinary else []))
    assert parsed.evidence_treatments[0].intent.model_dump(mode="json") == (
        plan["actions"][0]["split_policy"]["results"][0]["evidence_activation"]["intent"])


@pytest.mark.parametrize("fault", ["missing_activation", "orphan_object", "ordinary_double_owner"])
def test_new_write_cannot_claim_split_result_without_one_authoritative_owner(fault):
    plan, _layout = evidence_layout_documents(ordinary=fault == "ordinary_double_owner")
    if fault == "missing_activation":
        result = plan["actions"][0]["split_policy"]["results"][0]
        result.pop("evidence_activation")
        result["post_state"] = "visible"
        VisualPlanV2.model_validate(plan)  # Legacy syntax may load, not become a new write.
    elif fault == "orphan_object":
        obj = deepcopy(next(obj for obj in plan["objects"] if obj["object_id"] == "part-1"))
        obj["object_id"] = "unowned-evidence"
        plan["objects"].append(obj)
        plan["boards"][0]["object_ids"].append(obj["object_id"])
        plan["beats"][0]["object_ids"].append(obj["object_id"])
        VisualPlanV2.model_validate(plan)
    else:
        plan["actions"][-1]["target_object_id"] = "part-1"
    with pytest.raises(ValueError):
        validate_plan_evidence_completeness(plan)


@pytest.mark.parametrize("fault", ["missing", "all_missing", "duplicate_pair", "wrong_action", "invented_action", "wrong_beat",
    "source_label", "permission_order", "snapshot", "destination_state", "swapped_intents"])
def test_layout_must_preserve_exact_owner_treatment_and_snapshot(fault):
    plan, layout = evidence_layout_documents(ordinary=True, same_beat=True)
    treatment = layout["evidence_treatments"][0]
    if fault == "missing":
        layout["evidence_treatments"].pop(0)
    elif fault == "all_missing":
        layout["evidence_treatments"] = []
        ExecutableLayoutV2.model_validate(layout)  # Legacy parsing is not new-layout admission.
    elif fault == "duplicate_pair":
        layout["evidence_treatments"].append(deepcopy(treatment))
    elif fault in {"wrong_action", "invented_action", "wrong_beat"}:
        treatment[{"wrong_action": "action_id", "invented_action": "action_id", "wrong_beat": "beat_id"}[fault]] = (
            {"wrong_action": "action-3", "invented_action": "fake-insert", "wrong_beat": "unknown-beat"}[fault])
    elif fault == "source_label":
        treatment["intent"]["source_label"] = "Rewritten source"
    elif fault == "permission_order":
        treatment["allowed_transformations"].reverse()
    elif fault == "snapshot":
        treatment["asset_managed_ref"] = "different-source.png"
    elif fault == "destination_state":
        treatment["intent"]["destination_state"] = "invented-visible"
    else:
        first, second = layout["evidence_treatments"][:2]
        first["intent"], second["intent"] = second["intent"], first["intent"]
    with pytest.raises(ValueError):
        validate_plan_layout(plan, layout)
