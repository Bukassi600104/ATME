"""Normal writes verify return history; old stored reads retain compatibility."""

from copy import deepcopy

import pytest
from test_v2_resolved_project import stored_v2_basis
from test_v2_return_board import return_documents
from test_v2_return_hierarchy import rehash_receipt
from v2_fixtures import digest

from atme.project_service import ProjectError, _resolved_compilation_fingerprint
from atme.render.v2_hierarchy_replay import completed_hierarchy_basis
from atme.render.v2_state import evaluate_frame


def stored_return_basis(tmp_path, *, stale_history=None):
    service, project, plan, layout, timeline = stored_v2_basis(tmp_path, real_evidence=True)
    _, example = return_documents()
    returned = deepcopy(example["actions"][2])
    returned.update(start_ms=8000, end_ms=8001)
    returned["resolved_trigger"].update(source={"kind": "absolute", "at_ms": 8000},
                                        alignment_anchor_ms=8000, resolved_at_ms=8000)
    returned["action"].update(trigger={"kind": "absolute", "at_ms": 8000},
                               post_state="evidence_visible", destination_state="evidence_visible",
                               expected_object_states={"object-system": "visible", "object-label": "visible",
                                                       "object-evidence": "evidence_visible"},
                               expected_object_state_versions={"object-system": 2, "object-label": 2,
                                                               "object-evidence": 2})
    if stale_history == "state":
        returned["action"]["expected_object_states"]["object-system"] = "hidden"
    elif stale_history == "version":
        returned["action"]["expected_object_state_versions"]["object-system"] += 1
    plan["project_revision"] = project["revision"]
    plan["boards"][0]["expected_prior_state"] = "system_established"
    plan["actions"].append(deepcopy(returned["action"]))
    plan["beats"][1]["action_ids"].append("return-1")
    plan["beats"][1]["continuity"]["expected_state_versions"].update(
        returned["action"]["expected_object_state_versions"])
    plan["coverage"][2]["action_ids"].append("return-1")
    try:
        project = service.write(project["project_id"], "storyboard", plan, project["revision"])
    except ProjectError as exc:
        raise AssertionError(exc.errors) from exc
    layout.update(project_revision=project["revision"], plan_revision=project["artifacts"]["storyboard"],
                  plan_sha256=digest(plan), boards=deepcopy(plan["boards"]))
    layout["activations"] = [
        {**layout["activations"][0], "end_ms": 7500},
        {**layout["activations"][0], "activation_id": "activation-return", "start_ms": 8000,
         "reason": "Return to developed work"},
    ]
    project = service.write(project["project_id"], "layout", layout, project["revision"])
    timeline.update(project_revision=project["revision"], plan_revision=project["artifacts"]["storyboard"],
                    layout_revision=project["artifacts"]["layout"], plan_sha256=digest(plan),
                    layout_sha256=digest(layout), coverage=deepcopy(plan["coverage"]))
    timeline["actions"].append(returned)
    prefix = deepcopy(timeline)
    prefix["actions"].pop()
    prefix["coverage"][2]["action_ids"].remove("return-1")
    before = evaluate_frame(layout, prefix, 7499)
    basis = completed_hierarchy_basis(before.hierarchy, {obj.object_id: obj for obj in before.objects})
    returned["return_hierarchy_receipt"] = {
        "action_id": "return-1", "destination_board_id": "board-main",
        "destination_activation_id": "activation-return", "hierarchy_basis": basis.model_dump(mode="json"),
        "hierarchy_basis_sha256": basis.checksum(),
    }
    timeline["compilation_fingerprint"] = _resolved_compilation_fingerprint(timeline)
    return service, project, timeline


def test_normal_return_write_stores_exact_receipt_and_duplicate_preserves_it(tmp_path):
    service, project, timeline = stored_return_basis(tmp_path)
    try:
        source_id = project["project_id"]
        project = service.write(source_id, "resolved_timeline", timeline, project["revision"])
        assert service.artifact(source_id, "resolved_timeline")["document"] == timeline
        preview = service.runner.preview_v2_source(source_id, project["revision"], 8000)
        copy = service.duplicate(source_id)
        copied = service.artifact(copy["project_id"], "resolved_timeline")["document"]
        assert copied["actions"][-1]["return_hierarchy_receipt"] == timeline["actions"][-1]["return_hierarchy_receipt"]
        assert copied["compilation_fingerprint"] == _resolved_compilation_fingerprint(copied)
        assert copied["project_id"] != source_id
        assert service.runner.preview_v2_source(copy["project_id"], copy["revision"], 8000)["png"] == preview["png"]
        assert service.artifact(source_id, "resolved_timeline")["document"] == timeline
    finally:
        service.store.close()


@pytest.mark.parametrize("kind", ["missing", "transform", "order", "parent"])
def test_normal_return_write_rejects_missing_or_self_consistent_stale_receipt_atomically(tmp_path, kind):
    service, project, timeline = stored_return_basis(tmp_path)
    try:
        returned = timeline["actions"][-1]
        if kind == "missing":
            returned.pop("return_hierarchy_receipt")
            expected = "exact retained hierarchy receipt"
        else:
            receipt = returned["return_hierarchy_receipt"]
            placements = receipt["hierarchy_basis"]["placements"]
            item = next(p for p in placements if p["object_id"] == "object-system")
            if kind == "transform":
                item["local_transform"]["position"]["x"] += 1
            elif kind == "order":
                other = next(p for p in placements if p["object_id"] == "object-label")
                item["sibling_ordinal"], other["sibling_ordinal"] = other["sibling_ordinal"], item["sibling_ordinal"]
            else:
                item.update(parent_id="object-label", sibling_ordinal=0)
                for ordinal, root in enumerate(sorted((p for p in placements if p["parent_id"] is None),
                                                     key=lambda p: p["sibling_ordinal"])):
                    root["sibling_ordinal"] = ordinal
            rehash_receipt(receipt)
            expected = "retained board hierarchy"
        timeline["compilation_fingerprint"] = _resolved_compilation_fingerprint(timeline)
        with pytest.raises(ProjectError, match=expected) as failure:
            service.write(project["project_id"], "resolved_timeline", timeline, project["revision"])
        assert failure.value.code == "invalid_artifact"
        assert service.open(project["project_id"])["revision"] == project["revision"]
        with pytest.raises(ProjectError):
            service.artifact(project["project_id"], "resolved_timeline")
    finally:
        service.store.close()


def test_old_stored_return_without_receipt_validates_and_previews_with_explicit_read_mode(tmp_path, monkeypatch):
    service, project, timeline = stored_return_basis(tmp_path)
    try:
        timeline["actions"][-1].pop("return_hierarchy_receipt")
        timeline["compilation_fingerprint"] = _resolved_compilation_fingerprint(timeline)
        service._validate_resolved_timeline(project["project_id"], timeline,
                                             service._row(project["project_id"]), require_return_receipts=False)
        # Simulate a pre-receipt immutable artifact, not a normal current write.
        original = service._validate_resolved_timeline

        def legacy_ingestion(project_id, document, row, **kwargs):
            return original(project_id, document, row, require_return_receipts=False)

        with monkeypatch.context() as context:
            context.setattr(service, "_validate_resolved_timeline", legacy_ingestion)
            project = service.write(project["project_id"], "resolved_timeline", timeline, project["revision"])
        seen = []

        def observed_read(*args, **kwargs):
            seen.append(kwargs["require_return_receipts"])
            return original(*args, **kwargs)

        monkeypatch.setattr(service, "_validate_resolved_timeline", observed_read)
        preview = service.runner.preview_v2_source(project["project_id"], project["revision"], 8000)
        assert preview["png"].startswith(b"\x89PNG")
        assert seen == [False]
    finally:
        service.store.close()


@pytest.mark.parametrize("kind", ["state", "version"])
def test_new_write_rejects_false_history_even_when_authored_plan_agrees(tmp_path, kind):
    service, project, timeline = stored_return_basis(tmp_path, stale_history=kind)
    try:
        with pytest.raises(ProjectError, match="retained board state") as failure:
            service.write(project["project_id"], "resolved_timeline", timeline, project["revision"])
        assert failure.value.code == "invalid_artifact"
        assert service.open(project["project_id"])["revision"] == project["revision"]
        with pytest.raises(ProjectError):
            service.artifact(project["project_id"], "resolved_timeline")
    finally:
        service.store.close()
