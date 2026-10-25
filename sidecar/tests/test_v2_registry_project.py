"""Real revision/authority storage and offline duplicate frames for bound artwork."""

import socket
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
from atme.project_service import ProjectError, _resolved_compilation_fingerprint
from atme.render import v2_state
from atme.render.style_bundle import registry_endpoint_inputs_for_objects
from atme.render.v2_split_paint import verify_split_paint_inputs
from atme.render.v2_svg import (
    _compose_validated_svg_frame,
    _rasterize_svg_frame,
    compose_png_frame,
)
from atme.store.contracts_v2 import ExecutableLayoutV2, ResolvedVisualTimelineV2
from test_v2_registry_runtime import bound_art_documents
from test_v2_resolved_project import stored_v2_basis
from v2_fixtures import digest


def stored_registry_basis(tmp_path, portrait=False):
    profile = "SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9"
    service, project, plan, _, _ = stored_v2_basis(tmp_path, profile=profile)
    layout, timeline = bound_art_documents(portrait)
    keys = set(plan["objects"][0])
    plan["objects"] = [{key: deepcopy(value) for key, value in obj.items()
        if key in keys or key == "registry_binding"} for obj in layout["objects"]]
    plan["assets"] = []
    plan["actions"] = [deepcopy(row["action"]) for row in timeline["actions"]]
    plan["coverage"] = deepcopy(timeline["coverage"])
    plan["fallbacks"] = deepcopy(timeline["fallbacks"])
    for beat in plan["beats"]:
        beat["evidence"] = None
    plan["project_revision"] = project["revision"]
    project = service.write(project["project_id"], "storyboard", plan, project["revision"])
    layout.update(project_id=project["project_id"], project_revision=project["revision"],
        plan_revision=project["artifacts"]["storyboard"], plan_sha256=digest(plan))
    project = service.write(project["project_id"], "layout", layout, project["revision"])
    timing = service.source_timeline.get(project["project_id"])
    timeline.update(project_id=project["project_id"], project_revision=project["revision"],
        plan_revision=project["artifacts"]["storyboard"], plan_sha256=digest(plan),
        layout_revision=project["artifacts"]["layout"], layout_sha256=digest(layout),
        cleaned_timeline_revision=timing["timeline_revision"],
        cleaned_timeline_fingerprint=digest(timing["document"]))
    timeline["compilation_fingerprint"] = _resolved_compilation_fingerprint(timeline)
    return service, project, plan, layout, timeline


def history(service, pid):
    return tuple(tuple(row) for row in service.store.conn.execute(
        "SELECT kind,revision,document FROM project_artifact_versions WHERE job_id=? ORDER BY kind,revision", (pid,)))


@pytest.mark.parametrize("portrait", [False, True])
def test_real_bound_project_and_duplicate_preserve_authority_and_offline_pixels(tmp_path, portrait, monkeypatch):
    service, project, plan, layout, timeline = stored_registry_basis(tmp_path, portrait)
    try:
        pid = project["project_id"]
        media = {str(path): sha256(path.read_bytes()).hexdigest() for path in tmp_path.rglob("*.wav")}
        project = service.write(pid, "resolved_timeline", timeline, project["revision"])
        original_history = history(service, pid)
        duplicate = service.duplicate(pid)
        assert service.artifact(pid, "storyboard")["document"] == plan
        assert service.artifact(pid, "layout")["document"] == layout
        assert service.artifact(pid, "resolved_timeline")["document"] == timeline
        copy_id = duplicate["project_id"]
        copied_plan = service.artifact(copy_id, "storyboard")["document"]
        copied_layout = service.artifact(copy_id, "layout")["document"]
        copied_timeline = service.artifact(copy_id, "resolved_timeline")["document"]
        assert copied_layout["objects"] == layout["objects"]
        assert copied_plan["objects"] == plan["objects"]
        assert copied_plan["narrative_authority"] == plan["narrative_authority"]
        assert copied_timeline["cleaned_timeline_fingerprint"] == timeline["cleaned_timeline_fingerprint"]
        assert copied_timeline["layout_sha256"] == digest(copied_layout)
        assert copied_timeline["plan_sha256"] == digest(copied_plan)
        assert copied_timeline["compilation_fingerprint"] == _resolved_compilation_fingerprint(copied_timeline)
        expected = {t: compose_png_frame(layout, timeline, t).png for t in (4100, 4900, 5000)}
        typed, resolved = ExecutableLayoutV2.model_validate(copied_layout), ResolvedVisualTimelineV2.model_validate(copied_timeline)
        inputs = verify_split_paint_inputs(typed, {})
        registry_inputs = registry_endpoint_inputs_for_objects({obj.object_id: obj for obj in typed.objects},
            frozen_files={name: raw for name, _, raw in inputs.bundle_bytes})
        assert media == {str(path): sha256(path.read_bytes()).hexdigest() for path in tmp_path.rglob("*.wav")}
        assert history(service, pid) == original_history
        monkeypatch.setattr(Path, "read_bytes", lambda *_: pytest.fail("frozen stored frame reopened a file"))
        monkeypatch.setattr(socket, "create_connection", lambda *_args, **_kwargs: pytest.fail("offline frame used network"))
        monkeypatch.setattr(socket.socket, "connect", lambda *_args, **_kwargs: pytest.fail("offline frame used network"))
        for t in (5000, 4100, 4900, 4100):
            sample = v2_state._evaluate_frame_with_registry_inputs(copied_layout, copied_timeline, t, registry_inputs)
            frame = _compose_validated_svg_frame(typed, resolved, sample, {}, split_inputs=inputs)
            assert _rasterize_svg_frame(typed, frame, split_inputs=inputs).png == expected[t]
        assert service.capabilities()["visual_contracts"]["renderer_versions"] == ["1"]
    finally:
        service.store.close()


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("fault", ["unbound", "fit", "semantic-name", "semantic-mismatch"])
def test_invalid_registry_write_is_atomic_and_preserves_existing_artifacts(tmp_path, portrait, fault):
    service, project, plan, layout, _ = stored_registry_basis(tmp_path, portrait)
    try:
        pid = project["project_id"]
        before = history(service, pid)
        media = {str(path): sha256(path.read_bytes()).hexdigest() for path in tmp_path.rglob("*.wav")}
        document = deepcopy(plan if fault == "semantic-name" else layout)
        document["project_revision"] = project["revision"]
        actor = next(row for row in document["objects"] if row["object_id"] == "object-evidence")
        if fault == "unbound":
            actor.pop("registry_binding")
        elif fault == "fit":
            actor["anchors"][0]["point"]["x"] = .31
        elif fault == "semantic-mismatch":
            actor["variant"] = actor["registry_binding"]["asset_id"] = "person-presenter"
            actor["registry_binding"]["anchor_mappings"][0]["registry_anchor_name"] = "center"
            actor["anchors"][0]["point"] = {"x": .5, "y": .5}
            # Internally valid layout; only the exact existing semantic binding differs.
            service._serialized_artifact("layout", document)
        else:
            actor["registry_binding"]["anchor_mappings"][0]["registry_anchor_name"] = "invented-part"
        kind = "storyboard" if fault == "semantic-name" else "layout"
        with pytest.raises(ProjectError) as failure:
            service.write(pid, kind, document, project["revision"])
        assert failure.value.code == "invalid_artifact"
        assert "registry" in str(failure.value.errors)
        assert service.open(pid)["revision"] == project["revision"]
        assert history(service, pid) == before
        assert media == {str(path): sha256(path.read_bytes()).hexdigest() for path in tmp_path.rglob("*.wav")}
    finally:
        service.store.close()
