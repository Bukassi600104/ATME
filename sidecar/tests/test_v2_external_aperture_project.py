"""Authored aperture references persist atomically; legacy clones never invent semantics."""
from copy import deepcopy

import pytest
from atme.project_service import ProjectError
from test_v2_external_aperture_contract import external_aperture_documents
from test_v2_registry_project import history
from test_v2_resolved_project import stored_v2_basis
from v2_fixtures import digest


def stored_external_basis(tmp_path, kind, *, portrait=False, group=False):
    profile = "SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9"
    service, project, original, _old_layout, _old_clock = stored_v2_basis(tmp_path, profile=profile)
    plan, layout, _clock, ids = external_aperture_documents(kind, portrait=portrait, group=group)
    pid = project["project_id"]
    plan.update(project_id=pid, project_revision=project["revision"],
                narrative_authority=deepcopy(original["narrative_authority"]))
    project = service.write(pid, "storyboard", plan, project["revision"])
    layout.update(project_id=pid, project_revision=project["revision"],
                  plan_revision=project["artifacts"]["storyboard"], plan_sha256=digest(plan))
    project = service.write(pid, "layout", layout, project["revision"])
    return service, project, plan, layout, ids


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["clip", "mask"])
@pytest.mark.parametrize("group", [False, True])
def test_real_store_duplicate_preserves_external_reference_ownership_and_source_lineage(tmp_path, kind, portrait, group):
    service, project, plan, layout, ids = stored_external_basis(tmp_path, kind, portrait=portrait, group=group)
    try:
        pid = project["project_id"]
        before = deepcopy((history(service, pid), service.source_timeline.get(pid)))
        duplicate = service.duplicate(pid)
        copied = {}
        for artifact, original in (("storyboard", plan), ("layout", layout)):
            assert service.artifact(pid, artifact)["document"] == original
            record = service.artifact(duplicate["project_id"], artifact)
            copied[artifact] = record["document"]
            assert copied[artifact]["objects"] == original["objects"]
            assert record["duplicate_derivation"]["source_sha256"] == digest(original)
            assert record["duplicate_derivation"]["copied_sha256"] == digest(copied[artifact])
            receiver = next(obj for obj in copied[artifact]["objects"] if obj["object_id"] == ids["receiver"])
            assert receiver["clip_id"] == ids["aperture"]
            assert copied[artifact]["objects"][2]["child_ids"] == [ids["art"]]
        assert copied["storyboard"]["narrative_authority"] == plan["narrative_authority"]
        assert copied["layout"]["plan_sha256"] == digest(copied["storyboard"])
        assert (history(service, pid), service.source_timeline.get(pid)) == before
    finally:
        service.store.close()


@pytest.mark.parametrize("kind", ["clip", "mask"])
@pytest.mark.parametrize("fault", ["undeclared", "omitted", "null", "reparented"])
def test_public_reference_mismatch_write_is_atomic_with_no_legacy_bypass(tmp_path, kind, fault):
    service, project, plan, layout, ids = stored_external_basis(tmp_path, kind)
    try:
        pid = project["project_id"]
        if fault == "undeclared":
            # A legitimate new plan may remove a reference; a layout may not put it back.
            plan["objects"][-1].pop("clip_id")
            plan["project_revision"] = project["revision"]
            project = service.write(pid, "storyboard", plan, project["revision"])
            layout.update(plan_revision=project["artifacts"]["storyboard"], plan_sha256=digest(plan))
        elif fault == "omitted":
            layout["objects"][-1].pop("clip_id")
        elif fault == "null":
            layout["objects"][-1]["clip_id"] = None
        else:
            layout["objects"][-1]["parent_id"] = None
            layout["objects"][0]["child_ids"].remove(ids["receiver"])
        layout["project_revision"] = project["revision"]
        original = deepcopy(layout)
        before = deepcopy((service.open(pid), history(service, pid), service.source_timeline.get(pid)))
        with pytest.raises(ProjectError) as failure:
            service.write(pid, "layout", layout, project["revision"])
        assert failure.value.code == "invalid_artifact"
        assert layout == original
        assert (service.open(pid), history(service, pid), service.source_timeline.get(pid)) == before
        with pytest.raises(TypeError):
            service.write(pid, "layout", layout, project["revision"], require_code_payloads=False)
        assert (service.open(pid), history(service, pid), service.source_timeline.get(pid)) == before
    finally:
        service.store.close()


@pytest.mark.parametrize("kind", ["clip", "mask"])
def test_actual_old_layout_only_history_duplicates_without_inventing_a_semantic_reference(tmp_path, kind):
    service, project, plan, layout, ids = stored_external_basis(tmp_path, kind)
    try:
        pid = project["project_id"]
        # Test-only historical fixture, using the established trusted migration
        # serializer/DB seam; no public write gains a compatibility flag.
        plan["objects"][-1].pop("clip_id")
        layout["plan_sha256"] = digest(plan)
        for artifact, document in (("storyboard", plan), ("layout", layout)):
            serialized = service._serialized_artifact(artifact, document, legacy_migration=True)
            service.store.conn.execute(
                "UPDATE project_artifact_versions SET document=? WHERE job_id=? AND kind=? AND revision=?",
                (serialized, pid, artifact, project["artifacts"][artifact]))
        service.store.conn.commit()
        before = deepcopy((history(service, pid), service.source_timeline.get(pid)))
        duplicate = service.duplicate(pid)
        copied = {}
        for artifact, original in (("storyboard", plan), ("layout", layout)):
            assert service.artifact(pid, artifact)["document"] == original
            record = service.artifact(duplicate["project_id"], artifact)
            copied[artifact] = record["document"]
            assert copied[artifact]["objects"] == original["objects"]
            assert record["duplicate_derivation"]["source_sha256"] == digest(original)
            assert record["duplicate_derivation"]["copied_sha256"] == digest(copied[artifact])
        assert "clip_id" not in copied["storyboard"]["objects"][-1]
        assert copied["layout"]["objects"][-1]["clip_id"] == ids["aperture"]
        assert copied["layout"]["plan_sha256"] == digest(copied["storyboard"])
        assert (history(service, pid), service.source_timeline.get(pid)) == before
    finally:
        service.store.close()
