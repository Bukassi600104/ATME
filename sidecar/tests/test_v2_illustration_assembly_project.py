"""Real immutable project/duplicate authority for authored illustration layers."""

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from socket import socket

import pytest
from test_v2_illustration_assembly_compositor import original_illustration_documents
from test_v2_registry_project import history
from test_v2_resolved_project import stored_v2_basis
from v2_fixtures import digest

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


def stored_illustration_basis(tmp_path, family="device", *, portrait=False, active=True):
    profile = "SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9"
    service, project, plan, old_layout, old_timeline = stored_v2_basis(tmp_path, profile=profile)
    pid = project["project_id"]
    layout, timeline = original_illustration_documents(family, portrait=portrait, active=active)
    layout["objects"] = [*deepcopy(old_layout["objects"][:2]), *layout["objects"]]
    layout["boards"][0]["object_ids"] = [obj["object_id"] for obj in layout["objects"]]
    row = timeline["actions"][0]
    row.update(start_ms=4000, end_ms=5000)
    row["action"]["trigger"] = {"kind": "absolute", "at_ms": 4000}
    row["resolved_trigger"].update(source=row["action"]["trigger"], alignment_anchor_ms=4000, resolved_at_ms=4000)
    timeline["actions"] = [*deepcopy(old_timeline["actions"][:2]), row]
    timeline["coverage"] = deepcopy(old_timeline["coverage"])
    timeline["fallbacks"] = deepcopy(old_timeline["fallbacks"])
    timeline["initial_object_states"] = [{"object_id": obj["object_id"], "state": obj["initial_state"],
        "visible": obj["visible"], "state_version": 1} for obj in layout["objects"]]
    fields = set(plan["objects"][0]) | {"child_ids", "illustration_assembly", "code_payload"}
    plan["objects"] = [{key: deepcopy(value) for key, value in obj.items() if key in fields} for obj in layout["objects"]]
    plan["assets"] = []
    plan["boards"] = deepcopy(layout["boards"])
    plan["actions"] = [deepcopy(item["action"]) for item in timeline["actions"]]
    # Explicit fixture substitution: retain the original introductory speech
    # and real timing authority, then author its conclusion as this illustration.
    def authored_target(value):
        if isinstance(value, dict):
            return {key: authored_target(item) for key, item in value.items()}
        if isinstance(value, list):
            return [authored_target(item) for item in value]
        return "illustration-group" if value == "object-evidence" else value
    plan["beats"] = authored_target(plan["beats"])
    for beat in plan["beats"]:
        beat["object_ids"] = [obj["object_id"] for obj in plan["objects"] if obj["beat_id"] == beat["beat_id"]]
        beat["action_ids"] = [item["action_id"] for item in plan["actions"] if item["coverage_id"] in beat["coverage_ids"]]
        beat["evidence"] = None
    plan["project_revision"] = project["revision"]
    project = service.write(pid, "storyboard", plan, project["revision"])
    layout.update(project_id=pid, project_revision=project["revision"],
        plan_revision=project["artifacts"]["storyboard"], plan_sha256=digest(plan))
    project = service.write(pid, "layout", layout, project["revision"])
    source = service.source_timeline.get(pid)
    timeline.update(project_id=pid, project_revision=project["revision"],
        plan_revision=project["artifacts"]["storyboard"], plan_sha256=digest(plan),
        layout_revision=project["artifacts"]["layout"], layout_sha256=digest(layout),
        cleaned_timeline_revision=source["timeline_revision"], cleaned_timeline_fingerprint=digest(source["document"]))
    timeline["compilation_fingerprint"] = _resolved_compilation_fingerprint(timeline)
    return service, project, plan, layout, timeline


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("family", ["icon", "pictogram", "device", "document", "terminal"])
@pytest.mark.parametrize("active", [False, True])
def test_real_illustration_project_and_duplicate_keep_roles_authority_and_offline_pixels(tmp_path, portrait, family, active, monkeypatch):
    service, project, plan, layout, timeline = stored_illustration_basis(tmp_path, family, portrait=portrait, active=active)
    try:
        pid = project["project_id"]
        media = {str(path): sha256(path.read_bytes()).hexdigest() for path in tmp_path.rglob("*.wav")}
        project = service.write(pid, "resolved_timeline", timeline, project["revision"])
        original_history = history(service, pid)
        duplicate = service.duplicate(pid)
        copy_id = duplicate["project_id"]
        copied = {}
        for kind, authored in (("storyboard", plan), ("layout", layout), ("resolved_timeline", timeline)):
            assert service.artifact(pid, kind)["document"] == authored
            record = service.artifact(copy_id, kind)
            copied[kind] = record["document"]
            assert record["duplicate_derivation"]["source_sha256"] == digest(authored)
            assert record["duplicate_derivation"]["copied_sha256"] == digest(copied[kind])
            assert copied[kind]["project_id"] == copy_id != pid
        assert copied["layout"]["objects"] == layout["objects"]
        assert copied["storyboard"]["objects"] == plan["objects"]
        assert copied["storyboard"]["narrative_authority"] == plan["narrative_authority"]
        assert copied["resolved_timeline"]["cleaned_timeline_fingerprint"] == timeline["cleaned_timeline_fingerprint"]
        assert copied["resolved_timeline"]["layout_sha256"] == digest(copied["layout"])
        assert copied["resolved_timeline"]["plan_sha256"] == digest(copied["storyboard"])
        assert copied["resolved_timeline"]["compilation_fingerprint"] == _resolved_compilation_fingerprint(copied["resolved_timeline"])
        expected = {at: compose_png_frame(layout, timeline, at).png for at in (4000, 4500, 5000)}
        assert len(set(expected.values())) == 3
        typed = ExecutableLayoutV2.model_validate(copied["layout"])
        clock = ResolvedVisualTimelineV2.model_validate(copied["resolved_timeline"])
        inputs = verify_split_paint_inputs(typed, {})
        registry = registry_endpoint_inputs_for_objects({obj.object_id: obj for obj in typed.objects},
            frozen_files={name: raw for name, _, raw in inputs.bundle_bytes})
        assert history(service, pid) == original_history
        assert media == {str(path): sha256(path.read_bytes()).hexdigest() for path in tmp_path.rglob("*.wav")}
        monkeypatch.setattr(Path, "read_bytes", lambda *_: pytest.fail("frozen project reopened live resources"))
        monkeypatch.setattr(socket, "connect", lambda *_: pytest.fail("offline project used network"))
        for at in (5000, 4000, 4500, 4000):
            sample = v2_state._evaluate_frame_with_registry_inputs(copied["layout"], copied["resolved_timeline"], at, registry)
            frame = _compose_validated_svg_frame(typed, clock, sample, {}, split_inputs=inputs)
            assert _rasterize_svg_frame(typed, frame, split_inputs=inputs).png == expected[at]
    finally:
        service.store.close()


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("fault", ["semantic_role", "missing_anchor", "plan_binding", "role_order"])
def test_invalid_authored_illustration_write_is_atomic(tmp_path, portrait, fault):
    service, project, plan, layout, _ = stored_illustration_basis(tmp_path, portrait=portrait)
    try:
        pid = project["project_id"]
        before = deepcopy((service.open(pid), history(service, pid), service.source_timeline.get(pid)))
        kind = "storyboard" if fault == "semantic_role" else "layout"
        candidate = deepcopy(plan if kind == "storyboard" else layout)
        candidate["project_revision"] = project["revision"]
        objects = {obj["object_id"]: obj for obj in candidate["objects"]}
        group = objects["illustration-group"]
        if fault == "semantic_role":
            group["illustration_assembly"]["semantic_anchors"][0]["object_id"] = "device-label"
        elif fault == "missing_anchor":
            objects["original-ink-0"]["anchors"] = []
        elif fault == "plan_binding":
            group["illustration_assembly"]["content_state_id"] = "different-authored-state"
            ExecutableLayoutV2.model_validate(candidate)  # valid by itself, not this semantic revision
        else:
            group["child_ids"].reverse()
        with pytest.raises(ProjectError) as failure:
            service.write(pid, kind, candidate, project["revision"])
        assert failure.value.code == "invalid_artifact"
        assert "illustration_assembly" in str(failure.value.errors)
        assert (service.open(pid), history(service, pid), service.source_timeline.get(pid)) == before
    finally:
        service.store.close()


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("fault", ["plan_hash", "layout_hash", "cleaned_hash", "cleaned_revision", "timing_changed", "script_changed"])
def test_rehashed_illustration_timeline_cannot_claim_stale_authority(tmp_path, portrait, fault):
    service, project, _, _, timeline = stored_illustration_basis(tmp_path, portrait=portrait)
    try:
        pid = project["project_id"]
        media = {str(path): sha256(path.read_bytes()).hexdigest() for path in tmp_path.rglob("*.wav")}
        if fault == "timing_changed":
            source = service.source_timeline.get(pid)
            edited = service.source_timeline.command(pid, "split",
                {"clip_id": source["document"]["clips"][0]["clip_id"], "at_ms": 5000},
                project["revision"], source["timeline_revision"])
            project = edited["project"]
        elif fault == "script_changed":
            script = service.artifact(pid, "script")["document"]
            project = service.write(pid, "script", script, project["revision"])
        candidate = deepcopy(timeline)
        candidate["project_revision"] = project["revision"]
        if fault in {"plan_hash", "layout_hash", "cleaned_hash"}:
            field = {"plan_hash": "plan_sha256", "layout_hash": "layout_sha256", "cleaned_hash": "cleaned_timeline_fingerprint"}[fault]
            candidate[field] = "0" * 64
        elif fault == "cleaned_revision":
            candidate["cleaned_timeline_revision"] += 1
        candidate["compilation_fingerprint"] = _resolved_compilation_fingerprint(candidate)
        ResolvedVisualTimelineV2.model_validate(candidate)
        before = deepcopy((service.open(pid), history(service, pid), service.source_timeline.get(pid)))
        with pytest.raises(ProjectError) as failure:
            service.write(pid, "resolved_timeline", candidate, project["revision"])
        assert failure.value.code == "stale_contract_basis"
        assert (service.open(pid), history(service, pid), service.source_timeline.get(pid)) == before
        assert media == {str(path): sha256(path.read_bytes()).hexdigest() for path in tmp_path.rglob("*.wav")}
    finally:
        service.store.close()
