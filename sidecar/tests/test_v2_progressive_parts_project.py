"""Real ProjectService persistence keeps progressive policy authority immutable."""

from copy import deepcopy

import pytest
from atme.project_service import (
    ProjectError,
    ProjectService,
    _resolved_compilation_fingerprint,
)
from atme.render.v2_state import evaluate_frame
from test_v2_progressive_parts import documents, no_native
from test_v2_resolved_project import stored_v2_basis
from v2_fixtures import digest

pytestmark = pytest.mark.usefixtures(no_native.__name__)


def artifact_rows(service, project_id):
    with service.store._lock:
        return tuple(tuple(row) for row in service.store.conn.execute(
            "SELECT kind,revision,document FROM project_artifact_versions WHERE job_id=? "
            "ORDER BY kind,revision", (project_id,)))


def stored_parts_basis(tmp_path, portrait=False):
    profile = "SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9"
    service, project, previous, _, _ = stored_v2_basis(tmp_path, profile=profile)
    plan, layout, timeline = documents(portrait, grouped=True)
    if portrait:
        # Keep the authored 24px radius inside the shortened portrait specimen.
        layout["objects"][0]["geometry"]["bounds"]["height"] = 60
    pid = project["project_id"]
    plan.update(project_id=pid, project_revision=project["revision"],
                narrative_authority=deepcopy(previous["narrative_authority"]))
    project = service.write(pid, "storyboard", plan, project["revision"])
    layout.update(project_id=pid, project_revision=project["revision"],
                  plan_revision=project["artifacts"]["storyboard"], plan_sha256=digest(plan))
    project = service.write(pid, "layout", layout, project["revision"])
    source = service.source_timeline.get(pid)
    timeline.update(project_id=pid, project_revision=project["revision"],
        plan_revision=project["artifacts"]["storyboard"], layout_revision=project["artifacts"]["layout"],
        plan_sha256=digest(plan), layout_sha256=digest(layout), cleaned_timeline_revision=source["timeline_revision"],
        cleaned_timeline_fingerprint=digest(source["document"]))
    timeline["compilation_fingerprint"] = _resolved_compilation_fingerprint(timeline)
    return service, project, layout, timeline


@pytest.mark.parametrize("portrait", [False, True])
def test_stored_reopened_and_duplicate_parts_preserve_authority_and_state(tmp_path, portrait):
    service, project, layout, timeline = stored_parts_basis(tmp_path, portrait)
    pid = project["project_id"]
    try:
        original_source = deepcopy(service.source_timeline.get(pid))
        project = service.write(pid, "resolved_timeline", timeline, project["revision"])
        assert service.artifact(pid, "resolved_timeline")["document"] == timeline
        snapshots = {at_ms: evaluate_frame(layout, timeline, at_ms) for at_ms in (4000, 4225, 4675, 4900)}
        rows = artifact_rows(service, pid)
        reopened = ProjectService(service.store)
        assert reopened.artifact(pid, "resolved_timeline")["document"] == timeline
        copied = reopened.duplicate(pid)
        duplicate = reopened.artifact(copied["project_id"], "resolved_timeline")["document"]
        duplicate_layout = reopened.artifact(copied["project_id"], "layout")["document"]
        assert duplicate["actions"] == timeline["actions"]
        assert duplicate["compilation_fingerprint"] == _resolved_compilation_fingerprint(duplicate)
        for at_ms in (4900, 4000, 4675, 4225, 4900):
            assert evaluate_frame(duplicate_layout, duplicate, at_ms) == snapshots[at_ms]
        assert artifact_rows(service, pid) == rows
        assert service.source_timeline.get(pid) == original_source
    finally:
        service.store.close()


@pytest.mark.parametrize("fault", ["stale_closure", "missing_descendant", "policy_divergence"])
def test_invalid_resolved_parts_are_rejected_atomically(tmp_path, fault):
    service, project, _, timeline = stored_parts_basis(tmp_path)
    pid = project["project_id"]
    before = deepcopy((service.open(pid), artifact_rows(service, pid), service.source_timeline.get(pid)))
    policy = timeline["actions"][-1]["action"]["progressive_parts_policy"]
    if fault == "stale_closure":
        policy["expected_closure_state_versions"]["part-text"] = 2
    elif fault == "missing_descendant":
        policy["expected_closure_state_versions"].pop("part-text")
    else:
        policy["phases"][0]["weight"] = 2
    timeline["compilation_fingerprint"] = _resolved_compilation_fingerprint(timeline)
    try:
        with pytest.raises(ProjectError) as failure:
            service.write(pid, "resolved_timeline", timeline, project["revision"])
        assert failure.value.code == "invalid_artifact"
        assert (service.open(pid), artifact_rows(service, pid), service.source_timeline.get(pid)) == before
    finally:
        service.store.close()


def test_stored_portrait_fixture_marks_pass_ordinary_shape_preflight(tmp_path):
    from atme.render.style_bundle import load_bundle
    from atme.render.v2_svg import _preflight_object
    from atme.store.contracts_v2 import ExecutableLayoutV2, MarkObject

    service, _, raw, _ = stored_parts_basis(tmp_path, portrait=True)
    try:
        layout = ExecutableLayoutV2.model_validate(raw)
        objects = {obj.object_id: obj for obj in layout.objects}
        assert objects["object-system"].geometry.corner_radius == 24
        style, _, root = load_bundle()
        for obj in objects.values():
            if isinstance(obj, MarkObject):
                _preflight_object(obj, style, root, 2/3, objects)
    finally:
        service.store.close()
