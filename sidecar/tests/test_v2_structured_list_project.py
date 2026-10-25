"""Stored real-item progression binds source authority/revisions and one renderer."""

import socket
from copy import deepcopy

import pytest
from atme.project_service import ProjectError, _resolved_compilation_fingerprint
from atme.render.v2_svg import compose_png_frame
from test_v2_progressive_list import list_documents
from test_v2_resolved_project import stored_v2_basis
from test_v2_split_project import artifact_rows
from test_v2_structured_list_policy import progression_documents
from test_v2_structured_list_replay import add_move
from v2_fixtures import digest


def stored_list_basis(tmp_path, portrait=False, fault="none"):
    profile = "SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9"
    service, project, previous, _, _ = stored_v2_basis(tmp_path, profile=profile)
    plan, layout = progression_documents()
    pid = project["project_id"]
    plan.update(project_id=pid, project_revision=project["revision"],
        narrative_authority=deepcopy(previous["narrative_authority"]), output_profile=deepcopy(previous["output_profile"]))
    next(obj for obj in plan["objects"] if obj["object_type"] == "list")["initial_state"] = "visible"
    next(obj for obj in layout["objects"] if obj["object_type"] == "list").update(visible=True, initial_state="visible")
    layout["output_profile"] = deepcopy(plan["output_profile"])
    layout["canvas"].update(width=plan["output_profile"]["width"], height=plan["output_profile"]["height"])
    x, y = (90, 420) if portrait else (80, 300)
    for index, key in enumerate(("object-evidence", "list-item-a", "list-item-b", "list-item-c")):
        obj = next(obj for obj in layout["objects"] if obj["object_id"] == key)
        obj["geometry"]["bounds"] = {"x": x, "y": y+40*index, "width": 500, "height": 40}
    # Independently place the introductory marks inside each output profile.
    layout["objects"][0]["geometry"]["bounds"].update(x=80, y=100, width=480, height=180)
    layout["objects"][1]["geometry"]["bounds"].update(x=90, y=130, width=420, height=80)
    _, timeline = list_documents()
    timeline["actions"][-1]["action"] = deepcopy(plan["actions"][-1])
    timeline["initial_object_states"] = [{"object_id": obj["object_id"], "state": obj["initial_state"],
        "state_version": 1, "visible": obj["visible"]} for obj in layout["objects"]]
    timeline["output_profile"] = deepcopy(plan["output_profile"])
    timeline["resolved_assets"] = []
    if fault == "stale_versions":
        plan["actions"][-1]["structured_list_policy"]["expected_item_state_versions"]["list-item-a"] = 2
        timeline["actions"][-1]["action"] = deepcopy(plan["actions"][-1])
    elif fault == "read_overlap":
        add_move(timeline, layout, "object-evidence", 4100, 4200, expected_state="visible")
        added = deepcopy(timeline["actions"][-1]["action"])
        plan["actions"].append(added)
        plan["coverage"][2]["action_ids"].append(added["action_id"])
        plan["beats"][1]["action_ids"].append(added["action_id"])
    project = service.write(pid, "storyboard", plan, project["revision"])
    layout.update(project_id=pid, project_revision=project["revision"],
        plan_revision=project["artifacts"]["storyboard"], plan_sha256=digest(plan))
    project = service.write(pid, "layout", layout, project["revision"])
    source = service.source_timeline.get(pid)
    timeline.update(project_id=pid, project_revision=project["revision"],
        plan_revision=project["artifacts"]["storyboard"], layout_revision=project["artifacts"]["layout"],
        plan_sha256=digest(plan), layout_sha256=digest(layout),
        cleaned_timeline_revision=source["timeline_revision"], cleaned_timeline_fingerprint=digest(source["document"]))
    timeline["compilation_fingerprint"] = _resolved_compilation_fingerprint(timeline)
    return service, project, layout, timeline


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("fault", ["none", "stale_versions", "read_overlap"])
def test_real_project_list_policy_is_stored_and_rendered_or_rejected_atomically(tmp_path, monkeypatch, portrait, fault):
    service, project, layout, timeline = stored_list_basis(tmp_path, portrait, fault)
    pid = project["project_id"]
    original = deepcopy((service.open(pid), artifact_rows(service, pid), service.source_timeline.get(pid)))
    try:
        if fault != "none":
            with pytest.raises(ProjectError) as failure:
                service.write(pid, "resolved_timeline", timeline, project["revision"])
            assert failure.value.code == "invalid_artifact"
            assert (service.open(pid), artifact_rows(service, pid), service.source_timeline.get(pid)) == original
            return
        project = service.write(pid, "resolved_timeline", timeline, project["revision"])
        assert service.artifact(pid, "resolved_timeline")["document"] == timeline
        monkeypatch.setattr(socket, "socket", lambda *a, **kw: pytest.fail("structured list attempted network access"))
        monkeypatch.setattr(socket, "create_connection", lambda *a, **kw: pytest.fail("structured list attempted network access"))
        monkeypatch.setattr("atme.render.animator._FrameRenderer",
            lambda *a, **kw: pytest.fail("structured list fell back to v1"))
        pixels = {}
        for at_ms in (4225, 4675, 4900):
            preview = service.runner.preview_v2_source(pid, project["revision"], at_ms)
            assert preview["png"] == compose_png_frame(layout, timeline, at_ms).png
            assert (preview["width"], preview["height"]) == ((720, 1280) if portrait else (1280, 720))
            pixels[at_ms] = preview["png"]
        unchanged = artifact_rows(service, pid)
        copied = service.duplicate(pid)
        duplicate = service.artifact(copied["project_id"], "resolved_timeline")["document"]
        assert duplicate["compilation_fingerprint"] == _resolved_compilation_fingerprint(duplicate)
        assert duplicate["actions"][-1]["action"]["structured_list_policy"] == timeline["actions"][-1]["action"][
            "structured_list_policy"]
        for at_ms in (4900, 4225, 4675):
            assert service.runner.preview_v2_source(copied["project_id"], copied["revision"], at_ms)["png"] == pixels[at_ms]
        assert artifact_rows(service, pid) == unchanged
        assert service.source_timeline.get(pid) == original[2]
    finally:
        service.store.close()
