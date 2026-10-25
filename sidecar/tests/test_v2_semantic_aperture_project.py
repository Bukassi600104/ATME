"""Explicit semantic apertures survive real writes/duplicates without new admission."""
from copy import deepcopy

import pytest
from atme.project_service import ProjectError, _resolved_compilation_fingerprint
from test_v2_registry_project import history
from test_v2_resolved_project import stored_v2_basis
from test_v2_semantic_aperture_membership import aperture_plan_documents
from v2_fixtures import digest


def stored_aperture_basis(tmp_path, kind, *, portrait=False, bound=True):
    profile = "SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9"
    service, project, original, _old_layout, _old_clock = stored_v2_basis(tmp_path, profile=profile)
    plan, layout, timeline, ids = aperture_plan_documents(kind, portrait=portrait, bound=bound)
    pid = project["project_id"]
    plan.update(project_id=pid, project_revision=project["revision"],
                narrative_authority=deepcopy(original["narrative_authority"]))
    project = service.write(pid, "storyboard", plan, project["revision"])
    layout.update(project_id=pid, project_revision=project["revision"],
                  plan_revision=project["artifacts"]["storyboard"], plan_sha256=digest(plan))
    project = service.write(pid, "layout", layout, project["revision"])
    timing = service.source_timeline.get(pid)
    timeline.update(project_id=pid, project_revision=project["revision"],
                    plan_revision=project["artifacts"]["storyboard"], plan_sha256=digest(plan),
                    layout_revision=project["artifacts"]["layout"], layout_sha256=digest(layout),
                    cleaned_timeline_revision=timing["timeline_revision"],
                    cleaned_timeline_fingerprint=digest(timing["document"]))
    timeline["compilation_fingerprint"] = _resolved_compilation_fingerprint(timeline)
    project = service.write(pid, "resolved_timeline", timeline, project["revision"])
    return service, project, plan, layout, timeline, ids


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["clip", "mask"])
@pytest.mark.parametrize("bound", [False, True])
def test_semantic_aperture_real_store_duplicate_preserves_members_sources_and_authority(tmp_path, kind, portrait, bound):
    service, project, plan, layout, timeline, ids = stored_aperture_basis(
        tmp_path, kind, portrait=portrait, bound=bound)
    try:
        pid = project["project_id"]
        before = deepcopy((history(service, pid), service.source_timeline.get(pid)))
        duplicate = service.duplicate(pid)
        copied = {}
        for artifact, document in (("storyboard", plan), ("layout", layout), ("resolved_timeline", timeline)):
            assert service.artifact(pid, artifact)["document"] == document
            record = service.artifact(duplicate["project_id"], artifact)
            copied[artifact] = record["document"]
            assert record["duplicate_derivation"]["source_sha256"] == digest(document)
            assert record["duplicate_derivation"]["copied_sha256"] == digest(copied[artifact])
        assert copied["storyboard"]["objects"] == plan["objects"]
        assert copied["layout"]["objects"] == layout["objects"]
        assert copied["storyboard"]["objects"][2]["child_ids"] == [ids["art"]]
        if kind == "mask":
            assert copied["storyboard"]["objects"][2]["mask_source_object_id"] == ids["source"]
        assert copied["storyboard"]["narrative_authority"] == plan["narrative_authority"]
        assert copied["layout"]["plan_sha256"] == digest(copied["storyboard"])
        assert copied["resolved_timeline"]["plan_sha256"] == digest(copied["storyboard"])
        assert copied["resolved_timeline"]["layout_sha256"] == digest(copied["layout"])
        assert copied["resolved_timeline"]["actions"] == timeline["actions"]
        assert copied["resolved_timeline"]["cleaned_timeline_fingerprint"] == digest(
            service.source_timeline.get(duplicate["project_id"])["document"])
        assert copied["resolved_timeline"]["compilation_fingerprint"] == _resolved_compilation_fingerprint(
            copied["resolved_timeline"])
        assert (history(service, pid), service.source_timeline.get(pid)) == before
    finally:
        service.store.close()


@pytest.mark.parametrize("kind", ["clip", "mask"])
@pytest.mark.parametrize("fault", ["semantic_members", "layout_members"])
def test_rejected_aperture_membership_write_is_atomic_and_preserves_existing_history(tmp_path, kind, fault):
    service, project, plan, layout, _timeline, ids = stored_aperture_basis(tmp_path, kind, bound=False)
    try:
        pid = project["project_id"]
        artifact = "storyboard" if fault == "semantic_members" else "layout"
        candidate = deepcopy(plan if artifact == "storyboard" else layout)
        candidate["project_revision"] = project["revision"]
        if artifact == "storyboard":
            candidate["objects"][2]["child_ids"] = [ids["root"]]  # Coherent IDs, forbidden cycle.
        else:
            candidate["objects"][0]["child_ids"] = []
        original = deepcopy(candidate)
        before = deepcopy((service.open(pid), history(service, pid), service.source_timeline.get(pid)))
        with pytest.raises(ProjectError) as failure:
            service.write(pid, artifact, candidate, project["revision"])
        assert failure.value.code == "invalid_artifact"
        assert candidate == original
        assert (service.open(pid), history(service, pid), service.source_timeline.get(pid)) == before
    finally:
        service.store.close()
