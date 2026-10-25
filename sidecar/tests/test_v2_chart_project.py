"""Stored authored charts bind actual cleaned media and narrative authority."""

import socket
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
from test_external_inputs import external_payload
from test_project_runner import wav_bytes
from test_v2_chart_contract import authored_payload, chart_documents
from test_v2_registry_project import history
from v2_fixtures import (
    digest,
    executable_layout_v2,
    resolved_timeline_v2,
    visual_plan_v2,
)

from atme.narrative_source import describe
from atme.project_service import ProjectService, _resolved_compilation_fingerprint
from atme.render import v2_state
from atme.render.style_bundle import registry_endpoint_inputs_for_objects
from atme.render.v2_split_paint import verify_split_paint_inputs
from atme.render.v2_svg import (
    _compose_validated_svg_frame,
    _rasterize_svg_frame,
    compose_png_frame,
)
from atme.store.contracts_v2 import ExecutableLayoutV2, ResolvedVisualTimelineV2
from atme.store.db import JobStore


def stored_chart_basis(tmp_path, *, kind="bars", portrait=False, recording_only=False):
    service = ProjectService(JobStore(tmp_path / "chart-project.db"))
    profile = "SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9"
    project = service.create("Authored measured output", profile, "audio-only" if recording_only else "script+audio")
    pid = project["project_id"]
    project = service.write(pid, "script", external_payload()["script"], project["revision"])
    if not recording_only:
        script = service.artifact(pid, "script")
        project = service.approve_script(pid, script["revision"], project["revision"], True)
    original = tmp_path / "original-narration.wav"
    original.write_bytes(wav_bytes(seconds=7))
    attached = service.attach_wav(pid, original.read_bytes(), project["revision"])
    project, media = attached["project"], attached["media"]
    source = service.source_timeline.get(pid)
    result = service.edit_source_timeline(pid, "insert", {"media_id": media["media_id"], "at_ms": 0},
        project["revision"], source["timeline_revision"])
    project, source = result["project"], result["timeline"]
    result = service.edit_source_timeline(pid, "ripple_delete", {"start_ms": 1000, "end_ms": 2000},
        project["revision"], source["timeline_revision"])
    project, source = result["project"], result["timeline"]
    assert source["document"]["duration_ms"] == 6000
    assert media["duration_ms"] == 7000
    plan = visual_plan_v2(project["revision"])
    plan["project_id"] = pid
    if portrait:
        plan["output_profile"] = {"profile_id": profile, "width": 720, "height": 1280, "fps": 30}
    authority = describe(service, pid)
    script = service.artifact(pid, "script")
    plan["narrative_authority"].update(
        mode="recording_only" if recording_only else "approved_script_plus_recording",
        authority_id=media["media_id"] if recording_only else f"script-revision-{script['revision']}",
        timing_media_id=media["media_id"], timing_media_sha256=media["sha256"],
        cleaned_timeline_revision=source["timeline_revision"],
        cleaned_timeline_fingerprint=digest(source["document"]))
    assert authority["narrative_authority"]["type"] == ("recording" if recording_only else "approved_external_script")
    plan["assets"] = []
    spec = plan["objects"][2]
    spec.update(object_type="chart", asset_id=None, description="Authored measured output",
        chart_payload=authored_payload(kind))
    old = plan["actions"][2]
    action = deepcopy(plan["actions"][0])
    for key in ("action_id", "source_instruction_id", "board_id", "trigger", "fallback", "coverage_id"):
        action[key] = deepcopy(old[key])
    action.update(target_ids=[spec["object_id"]], easing="linear")
    plan["actions"][2] = action
    for beat in plan["beats"]:
        beat["evidence"] = None
    project = service.write(pid, "storyboard", plan, project["revision"])
    layout = executable_layout_v2(plan)
    chart = deepcopy(chart_documents(kind)[1]["objects"][0])
    for key in ("object_id", "board_id", "beat_id", "semantic_role", "description", "coverage_ids"):
        chart[key] = deepcopy(spec[key])
    chart.update(z_index=3, style={"stroke": "ink", "fill": None, "text": None, "effect": None})
    chart["geometry"]["bounds"] = ({"x": 80., "y": 700., "width": 560., "height": 420.} if portrait
                                     else {"x": 680., "y": 130., "width": 500., "height": 420.})
    layout["objects"][2] = chart
    layout.update(project_id=pid, project_revision=project["revision"],
        output_profile=deepcopy(plan["output_profile"]),
        plan_revision=project["artifacts"]["storyboard"], plan_sha256=digest(plan))
    layout["canvas"].update(width=plan["output_profile"]["width"], height=plan["output_profile"]["height"])
    project = service.write(pid, "layout", layout, project["revision"])
    timeline = resolved_timeline_v2(plan, layout)
    timeline.update(project_id=pid, project_revision=project["revision"], duration_ms=6000,
        output_profile=deepcopy(plan["output_profile"]), resolved_assets=[],
        plan_revision=project["artifacts"]["storyboard"], plan_sha256=digest(plan),
        layout_revision=project["artifacts"]["layout"], layout_sha256=digest(layout),
        cleaned_timeline_revision=source["timeline_revision"],
        cleaned_timeline_fingerprint=digest(source["document"]))
    timeline["compilation_fingerprint"] = _resolved_compilation_fingerprint(timeline)
    return service, project, plan, layout, timeline


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["bars", "line"])
@pytest.mark.parametrize("recording_only", [False, True])
def test_real_chart_project_duplicate_rebinds_authority_and_frozen_offline_pixels(
        tmp_path, portrait, kind, recording_only, monkeypatch):
    service, project, plan, layout, timeline = stored_chart_basis(tmp_path,
        kind=kind, portrait=portrait, recording_only=recording_only)
    try:
        pid = project["project_id"]
        if recording_only:
            assert service._row(pid)["approved_script_revision"] is None
        sources = {path: sha256(path.read_bytes()).hexdigest() for path in tmp_path.rglob("*.wav")}
        project = service.write(pid, "resolved_timeline", timeline, project["revision"])
        original_history = history(service, pid)
        duplicate = service.duplicate(pid)
        copy_id = duplicate["project_id"]
        copied = {}
        for artifact, authored in (("storyboard", plan), ("layout", layout), ("resolved_timeline", timeline)):
            assert service.artifact(pid, artifact)["document"] == authored
            record = service.artifact(copy_id, artifact)
            copied[artifact] = record["document"]
            assert record["duplicate_derivation"]["source_sha256"] == digest(authored)
            assert record["duplicate_derivation"]["copied_sha256"] == digest(copied[artifact])
            assert copied[artifact]["project_id"] == copy_id != pid
        assert copied["layout"]["objects"] == layout["objects"]
        assert copied["storyboard"]["narrative_authority"] == plan["narrative_authority"]
        assert copied["resolved_timeline"]["layout_sha256"] == digest(copied["layout"])
        assert copied["resolved_timeline"]["plan_sha256"] == digest(copied["storyboard"])
        assert copied["resolved_timeline"]["cleaned_timeline_fingerprint"] == digest(service.source_timeline.get(copy_id)["document"])
        assert copied["resolved_timeline"]["duration_ms"] == 6000
        expected = {at: compose_png_frame(layout, timeline, at).png for at in (4000, 4450, 4900)}
        assert len(set(expected.values())) == 3
        (tmp_path / f"{kind}-stored-production.png").write_bytes(expected[4900])
        typed = ExecutableLayoutV2.model_validate(copied["layout"])
        clock = ResolvedVisualTimelineV2.model_validate(copied["resolved_timeline"])
        inputs = verify_split_paint_inputs(typed, {})
        registry = registry_endpoint_inputs_for_objects({obj.object_id: obj for obj in typed.objects},
            frozen_files={name: raw for name, _, raw in inputs.bundle_bytes})
        assert history(service, pid) == original_history
        assert all(sha256(path.read_bytes()).hexdigest() == value for path, value in sources.items())

        def forbidden(*args, **kwargs):
            raise AssertionError("frozen stored chart reopened a source or used the network")

        monkeypatch.setattr(Path, "read_bytes", forbidden)
        monkeypatch.setattr(socket.socket, "connect", forbidden)
        for at in (4900, 4000, 4450, 4900):
            snapshot = v2_state._evaluate_frame_with_registry_inputs(copied["layout"], copied["resolved_timeline"], at, registry)
            svg = _compose_validated_svg_frame(typed, clock, snapshot, {}, split_inputs=inputs)
            assert _rasterize_svg_frame(typed, svg, split_inputs=inputs).png == expected[at]
    finally:
        service.store.close()
