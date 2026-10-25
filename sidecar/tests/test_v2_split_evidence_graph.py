"""Inline Split intents join the existing forensic graph, not a bypass."""

from copy import deepcopy

import pytest
from test_v2_evidence_annotation_contract import authored_evidence_annotation
from test_v2_evidence_annotation_objects import cross_annotation_documents
from test_v2_split_evidence_contract import evidence_completion_document
from v2_fixtures import digest, visual_plan_v2
from v2_split_fixtures import split_documents

from atme.store.contracts_v2 import VisualPlanV2


def split_evidence_plan(*, cross=False, ordinary=False, same_beat=False):
    plan, _layout, _timeline = split_documents()
    # Existing geometry fixture aliases these equal inventories. This fixture
    # adds separately owned ordinary/annotation objects; keep the lists distinct.
    plan["boards"][0]["object_ids"] = list(plan["boards"][0]["object_ids"])
    plan["beats"][0]["object_ids"] = list(plan["beats"][0]["object_ids"])
    original = visual_plan_v2()
    asset = deepcopy(original["assets"][0])
    asset["fallback_id"] = "fallback-1"
    plan["assets"] = [asset]
    plan["actions"] = [evidence_completion_document(two_results=True)["action"]]
    for obj in plan["objects"]:
        if obj["object_id"].startswith("part-"):
            obj.update(object_type="evidence", asset_id=asset["asset_id"])
    if cross:
        notes = deepcopy(cross_annotation_documents()[0]["objects"][-2:])
        for obj in notes:
            obj.update(beat_id="beat-001", coverage_ids=["coverage-1"])
        plan["objects"].extend(notes)
        ids = [obj["object_id"] for obj in notes]
        plan["boards"][0]["object_ids"].extend(ids)
        plan["beats"][0]["object_ids"].extend(ids)
        intent = plan["actions"][0]["split_policy"]["results"][0]["evidence_activation"]["intent"]
        intent.update(annotation_target_id="source", annotation_policy=authored_evidence_annotation())
        # Semantic fixture pins remain placeholders, but every logical note must
        # now be explicitly basis-bound without claiming physical descendants.
        policy = plan["actions"][0]["split_policy"]
        basis = policy["source_basis"]
        template = deepcopy(next(row for row in basis["placements"] if row["object_id"] == "part-1"))
        for ordinal, key in enumerate(ids, 3):
            placement = deepcopy(template)
            placement.update(object_id=key, sibling_ordinal=ordinal,
                             content_sha256=digest({"semantic_note": key}))
            basis["placements"].append(placement)
        basis["placements"].sort(key=lambda row: row["object_id"])
        basis["read_dependencies"].append({"kind": "annotation_anchor", "object_ids": sorted(["source", *ids])})
        policy["source_basis_sha256"] = digest(basis)
    if ordinary:
        obj = deepcopy(original["objects"][2])
        plan["objects"].append(obj)
        plan["boards"][0]["object_ids"].append(obj["object_id"])
        beat = deepcopy(original["beats"][1])
        beat["attention"].update(secondary_context=[], dimmed_targets=[])
        beat["continuity"].update(keep=[], expected_state_versions={}, return_from_board_id=None)
        plan["beats"].append(beat)
        plan["actions"].append(deepcopy(original["actions"][2]))
        plan["coverage"].append(deepcopy(original["coverage"][2]))
        plan["fallbacks"].append(deepcopy(original["fallbacks"][2]))
        plan["conclusion_beat_id"] = beat["beat_id"]
        if same_beat:
            plan["beats"].pop()
            owner = plan["beats"][0]
            obj["beat_id"] = owner["beat_id"]
            owner["object_ids"].append(obj["object_id"])
            for key in ("action_ids", "coverage_ids", "fallback_ids"):
                owner[key].extend(beat[key])
            owner["evidence"] = deepcopy(beat["evidence"])
            trigger = plan["actions"][-1]["trigger"]
            if trigger["kind"] == "beat_start":
                trigger["beat_id"] = owner["beat_id"]
            plan["conclusion_beat_id"] = owner["beat_id"]
    return plan


def first_activation(plan):
    return plan["actions"][0]["split_policy"]["results"][0]["evidence_activation"]


def test_current_physical_owner_is_independent_of_immutable_origin_project():
    plan = split_evidence_plan()
    asset = plan["assets"][0]
    asset["managed_ref"] = f"atme://projects/1/assets/{asset['asset_id']}"
    plan["project_id"] = 2
    policy = plan["actions"][0]["split_policy"]
    uri = f"atme://projects/2/assets/{asset['asset_id']}"
    policy["source_basis"]["asset_pins"][0]["resource_uri"] = uri
    for result in policy["results"]:
        result["evidence_activation"]["asset_pin"]["resource_uri"] = uri
    policy["source_basis_sha256"] = digest(policy["source_basis"])
    parsed = VisualPlanV2.model_validate(plan)
    assert parsed.assets[0].managed_ref == f"atme://projects/1/assets/{asset['asset_id']}"
    assert parsed.actions[0].split_policy.source_basis.asset_pins[0].resource_uri == uri


def test_coherent_wrong_physical_ids_already_fail_source_authority_binding():
    plan = split_evidence_plan()
    VisualPlanV2.model_validate(plan)
    policy = plan["actions"][0]["split_policy"]
    policy["source_basis"]["asset_pins"][0]["asset_id"] = "wrong-asset"
    for result in policy["results"]:
        result["evidence_activation"]["asset_pin"]["asset_id"] = "wrong-asset"
    policy["source_basis_sha256"] = digest(policy["source_basis"])
    with pytest.raises(ValueError, match="changes its source or exact permission pin"):
        VisualPlanV2.model_validate(plan)


@pytest.mark.parametrize("cross,ordinary", [(False, False), (True, False), (False, True)])
def test_explicit_split_semantic_graph_retains_real_causal_owner_and_ordinary_cardinality(cross, ordinary):
    raw = split_evidence_plan(cross=cross, ordinary=ordinary)
    parsed = VisualPlanV2.model_validate(raw)
    results = parsed.actions[0].split_policy.results
    assert len(results) == 2
    assert all(result.evidence_activation.causal_action_id == "split-1" for result in results)
    assert len([action for action in parsed.actions if action.verb == "insert_evidence"]) == int(ordinary)


@pytest.mark.parametrize("fault", ["duplicate_result_claim", "duplicate_ordinary_claim", "asset_kind",
    "result_asset", "result_kind", "beat", "unknown_annotation", "annotation_other_board",
    "unknown_mask", "not_mask", "permission_order", "invented_grant", "asset_revision",
    "asset_resource", "asset_checksum", "unverified_intent", "unpermitted_crop",
    "invalid_crop", "invalid_focus", "duplicate_owner"])
def test_split_inline_evidence_graph_is_not_a_bypass(fault):
    plan = split_evidence_plan(ordinary=fault == "duplicate_ordinary_claim")
    VisualPlanV2.model_validate(plan)
    activation = first_activation(plan)
    intent = activation["intent"]
    asset = plan["assets"][0]
    if fault == "duplicate_result_claim":
        intent["claim_id"] = plan["actions"][0]["split_policy"]["results"][1]["evidence_activation"]["intent"]["claim_id"]
    elif fault == "duplicate_ordinary_claim":
        intent["claim_id"] = plan["beats"][1]["evidence"]["claim_id"]
    elif fault == "asset_kind":
        asset["kind"] = "image"
    elif fault == "result_asset":
        next(obj for obj in plan["objects"] if obj["object_id"] == "part-1")["asset_id"] = None
    elif fault == "result_kind":
        next(obj for obj in plan["objects"] if obj["object_id"] == "part-1")["object_type"] = "image"
    elif fault == "beat":
        activation["beat_id"] = "not-owning-beat"
    elif fault == "unknown_annotation":
        intent["annotation_target_id"] = "unknown-target"
    elif fault == "annotation_other_board":
        target = deepcopy(plan["objects"][0])
        target.update(object_id="other-target", board_id="other-board", beat_id="other-beat")
        board = deepcopy(plan["boards"][0])
        board.update(board_id="other-board", object_ids=["other-target"])
        beat = deepcopy(plan["beats"][0])
        beat.update(beat_id="other-beat", board_id="other-board", object_ids=["other-target"], action_ids=[])
        beat["attention"].update(primary_targets=["other-target"])
        beat["camera_intent"]["target_ids"] = ["other-target"]
        # A distinct existing instruction coverage keeps the control graph valid.
        beat.update(coverage_ids=["coverage-other"], fallback_ids=["fallback-other"])
        target["coverage_ids"] = ["coverage-other"]
        plan["coverage"].append({"coverage_id": "coverage-other", "instruction_id": "instruction-other",
            "status": "rejected", "action_ids": [], "fallback_id": "fallback-other"})
        fallback = deepcopy(plan["fallbacks"][0])
        fallback.update(fallback_id="fallback-other", affected_ids=["instruction-other"], status="selected")
        plan["fallbacks"].append(fallback)
        plan["objects"].append(target)
        plan["boards"].append(board)
        plan["beats"].append(beat)
        # Establish that only the target reference is invalid, not the fixture.
        VisualPlanV2.model_validate(plan)
        intent["annotation_target_id"] = "other-target"
    elif fault == "unknown_mask":
        intent["mask_object_id"] = "unknown-mask"
    elif fault == "not_mask":
        intent["mask_object_id"] = "source"
    elif fault == "permission_order":
        asset["allowed_transformations"].reverse()
    elif fault == "invented_grant":
        activation["allowed_transformations"].append("rotate")
        activation["permission_sha256"] = digest(activation["allowed_transformations"])
    elif fault == "asset_resource":
        policy = plan["actions"][0]["split_policy"]
        uri = f"atme://projects/999/assets/{asset['asset_id']}"
        policy["source_basis"]["asset_pins"][0]["resource_uri"] = uri
        for result in policy["results"]:
            result["evidence_activation"]["asset_pin"]["resource_uri"] = uri
        policy["source_basis_sha256"] = digest(policy["source_basis"])
    elif fault in {"asset_revision", "asset_checksum"}:
        field, value = {"asset_revision": ("revision", 2),
                        "asset_checksum": ("checksum_sha256", "f" * 64)}[fault]
        asset[field] = value
        if field == "checksum_sha256":
            asset["provenance"]["checksum_sha256"] = value
    elif fault == "unverified_intent":
        intent["checksum_verified"] = False
    elif fault == "unpermitted_crop":
        permissions = [p for p in asset["allowed_transformations"] if p != "crop"]
        asset["allowed_transformations"] = permissions
        for result in plan["actions"][0]["split_policy"]["results"]:
            result["evidence_activation"].update(allowed_transformations=deepcopy(permissions),
                                                 permission_sha256=digest(permissions))
    elif fault == "invalid_crop":
        intent["crop"]["width"] += 1
    elif fault == "invalid_focus":
        intent["focus_region"]["x"] = 899
    else:
        second = deepcopy(plan["actions"][0])
        second["action_id"] = "split-2"
        for result in second["split_policy"]["results"]:
            result["evidence_activation"]["causal_action_id"] = "split-2"
            result["evidence_activation"]["intent"]["claim_id"] += "-second-owner"
        plan["actions"].append(second)
        plan["beats"][0]["action_ids"].append("split-2")
        plan["coverage"][0]["action_ids"].append("split-2")
    with pytest.raises(ValueError):
        VisualPlanV2.model_validate(plan)


def test_split_inline_annotation_ownership_joins_the_shared_exclusivity_graph():
    plan = split_evidence_plan(cross=True)
    first = first_activation(plan)
    second = plan["actions"][0]["split_policy"]["results"][1]["evidence_activation"]
    second["intent"].update(annotation_target_id="source",
                           annotation_policy=deepcopy(first["intent"]["annotation_policy"]))
    with pytest.raises(ValueError, match="exclusive|logical annotation needs one owner"):
        VisualPlanV2.model_validate(plan)


def test_one_ordinary_insert_and_two_split_results_can_share_beat_and_asset_without_invented_writers():
    raw = split_evidence_plan(ordinary=True, same_beat=True)
    parsed = VisualPlanV2.model_validate(raw)
    assert len(parsed.beats) == 1
    assert parsed.beats[0].evidence.evidence_asset_id == first_activation(raw)["asset_pin"]["asset_id"]
    assert len(parsed.actions) == 2
    assert parsed.actions[1].target_object_id == "object-evidence"


def test_ordinary_insert_cannot_also_target_split_owned_result():
    raw = split_evidence_plan(ordinary=True)
    raw["actions"][-1]["target_object_id"] = "part-1"
    with pytest.raises(ValueError, match="both own"):
        VisualPlanV2.model_validate(raw)


def test_inline_annotation_cannot_display_dedicated_mask_source():
    raw = split_evidence_plan()
    source = deepcopy(next(obj for obj in raw["objects"] if obj["object_id"] == "source"))
    source.update(object_id="mask-source", initial_state="visible")
    mask = deepcopy(source)
    mask.update(object_id="unused-mask", object_type="mask", mask_mode="alpha",
        mask_source_object_id="mask-source", mask_coordinate_space="parent_local", invert=False, feather_px=0)
    raw["objects"].extend([source, mask])
    for key in ("boards", "beats"):
        raw[key][0]["object_ids"].extend(["mask-source", "unused-mask"])
    VisualPlanV2.model_validate(raw)  # Only the later attempted visible target is forbidden.
    first_activation(raw)["intent"]["annotation_target_id"] = "mask-source"
    with pytest.raises(ValueError, match="non-mask-source"):
        VisualPlanV2.model_validate(raw)
