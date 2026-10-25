"""Authored multi-instance actions survive real immutable resolved project writes."""
import socket
from copy import deepcopy
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
from atme.store import contracts_v2 as contracts
from test_v2_composition_instances import two_instance_documents
from test_v2_composition_project import stored_composition_basis
from test_v2_registry_project import history
from test_v2_timeline_replay import resolved
from v2_fixtures import digest


def stored_instances(tmp_path, *, portrait=False):
    service, project, prior, _layout = stored_composition_basis(tmp_path, portrait=portrait)
    plan, layout, timeline = two_instance_documents(portrait=portrait)
    root = layout["objects"][0]
    move = deepcopy(plan["actions"][0])
    move.pop("annotation")
    destination = deepcopy(root["transform"])
    destination["position"]["x"] += 10.0
    destination["position"]["y"] += 10.0
    move.update(action_id="authored-instance-move", verb="move", target_ids=[root["object_id"]],
                expected_state="visible", post_state="visible", easing="linear", destination=destination, opacity=None)
    row = resolved(move, 9000, 9500).model_dump(mode="json")
    plan["actions"].append(deepcopy(row["action"]))
    plan["beats"][0]["action_ids"].append(row["action"]["action_id"])
    plan["coverage"][0]["action_ids"].append(row["action"]["action_id"])
    timeline["actions"].append(row)
    timeline["coverage"] = deepcopy(plan["coverage"])
    pid = project["project_id"]
    plan.update(project_id=pid, project_revision=project["revision"],
                narrative_authority=deepcopy(prior["narrative_authority"]))
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
    return service, project, plan, layout, timeline


@pytest.mark.parametrize("portrait", [False, True])
def test_authored_stored_instances_duplicate_exact_actions_authority_and_frozen_pixels(tmp_path, portrait, monkeypatch):
    service, project, plan, layout, timeline = stored_instances(tmp_path, portrait=portrait)
    try:
        pid = project["project_id"]
        before = history(service, pid)
        before_timing = deepcopy(service.source_timeline.get(pid))
        duplicate = service.duplicate(pid)
        copied = {}
        for kind, document in (("storyboard", plan), ("layout", layout), ("resolved_timeline", timeline)):
            assert service.artifact(pid, kind)["document"] == document
            row = service.artifact(duplicate["project_id"], kind)
            copied[kind] = row["document"]
            assert row["duplicate_derivation"]["source_sha256"] == digest(document)
            assert row["duplicate_derivation"]["copied_sha256"] == digest(copied[kind])
        assert copied["layout"]["objects"] == layout["objects"]
        assert copied["storyboard"]["objects"] == plan["objects"]
        assert copied["storyboard"]["narrative_authority"] == plan["narrative_authority"]
        assert copied["resolved_timeline"]["actions"] == timeline["actions"]
        assert copied["resolved_timeline"]["plan_sha256"] == digest(copied["storyboard"])
        assert copied["resolved_timeline"]["layout_sha256"] == digest(copied["layout"])
        assert copied["resolved_timeline"]["cleaned_timeline_fingerprint"] == digest(
            service.source_timeline.get(duplicate["project_id"])["document"])
        assert copied["resolved_timeline"]["compilation_fingerprint"] == _resolved_compilation_fingerprint(copied["resolved_timeline"])
        assert history(service, pid) == before
        assert service.source_timeline.get(pid) == before_timing
        expected = {at: compose_png_frame(layout, timeline, at).png for at in (3000, 6900, 9250)}
        assert len(set(expected.values())) == 3
        typed = contracts.ExecutableLayoutV2.model_validate(copied["layout"])
        clock = contracts.ResolvedVisualTimelineV2.model_validate(copied["resolved_timeline"])
        inputs = verify_split_paint_inputs(typed, {})
        registry = registry_endpoint_inputs_for_objects({obj.object_id: obj for obj in typed.objects},
            frozen_files={name: raw for name, _, raw in inputs.bundle_bytes})

        def forbidden(*args, **kwargs):
            raise AssertionError("stored frozen composition reopened a file or used the network")

        path_open = Path.open

        def write_only(path, mode="r", *args, **kwargs):
            if "r" in mode or "+" in mode or not any(flag in mode for flag in ("w", "a", "x")):
                forbidden()
            return path_open(path, mode, *args, **kwargs)

        monkeypatch.setattr(Path, "read_bytes", forbidden)
        monkeypatch.setattr(Path, "open", write_only)
        monkeypatch.setattr(socket, "create_connection", forbidden)
        monkeypatch.setattr(socket.socket, "connect", forbidden)
        for at in (9250, 3000, 6900, 9250):
            sample = v2_state._evaluate_frame_with_registry_inputs(copied["layout"], copied["resolved_timeline"], at, registry)
            svg = _compose_validated_svg_frame(typed, clock, sample, {}, split_inputs=inputs)
            assert _rasterize_svg_frame(typed, svg, split_inputs=inputs).png == expected[at]
    finally:
        service.store.close()


@pytest.mark.parametrize("fault", ["unplanned_move", "stale_timing"])
@pytest.mark.parametrize("portrait", [False, True])
def test_coherent_but_unapproved_resolved_instance_write_cannot_change_history(tmp_path, portrait, fault):
    service, project, _plan, _layout, timeline = stored_instances(tmp_path, portrait=portrait)
    try:
        pid = project["project_id"]
        candidate = deepcopy(timeline)
        candidate["project_revision"] = project["revision"]
        if fault == "unplanned_move":
            candidate["actions"][-1]["action"]["destination"]["position"]["x"] += 1.0
        else:
            candidate["cleaned_timeline_revision"] -= 1
        candidate["compilation_fingerprint"] = _resolved_compilation_fingerprint(candidate)
        original = deepcopy(candidate)
        before = deepcopy((service.open(pid), history(service, pid), service.source_timeline.get(pid)))
        with pytest.raises(ProjectError) as failure:
            service.write(pid, "resolved_timeline", candidate, project["revision"])
        assert failure.value.code == ("invalid_artifact" if fault == "unplanned_move" else "stale_contract_basis")
        assert candidate == original
        assert (service.open(pid), history(service, pid), service.source_timeline.get(pid)) == before
    finally:
        service.store.close()
