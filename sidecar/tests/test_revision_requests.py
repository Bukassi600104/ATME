import pytest
from copy import deepcopy

from atme.project_service import ProjectError, ProjectService
from atme.store.db import JobStore
from test_external_inputs import external_payload
from test_project_runner import wav_bytes


def service(tmp_path):
    store = JobStore(tmp_path / "projects.db")
    return store, ProjectService(store)


def test_scoped_script_proposal_preserves_other_scenes_and_cannot_overwrite_a_new_edit(tmp_path):
    store, projects = service(tmp_path)
    try:
        script = external_payload()["script"]
        pid = projects.create("Script revisions", "LONG_FORM_16_9", "script-first")["project_id"]
        projects.write(pid, "script", script, 0)
        request = projects.create_revision_request(pid, 1, {"kind":"scene", "id":"scene-1", "start_ms":0, "end_ms":1000},
                                                   "Shorten the first scene")
        changed = deepcopy(script)
        changed["scenes"][1]["spoken_text"] = "Changed outside the selected scene."
        with pytest.raises(ProjectError, match="outside"):
            projects.submit_revision_proposal(pid, request["request_id"], 1, "script", changed, "Updated the scene")
        changed = deepcopy(script)
        changed["scenes"][0]["spoken_text"] = "A queue."
        projects.submit_revision_proposal(pid, request["request_id"], 1, "script", changed, "Shortened the first scene")
        projects.set_profile(pid, "SHORT_FORM_9_16", 1)
        with pytest.raises(ProjectError, match="revision"):
            projects.decide_revision_proposal(pid, request["request_id"], 2, True)
        assert projects.artifact(pid, "script")["document"] == script
        assert projects.revisions.get(pid, request["request_id"])["status"] == "proposed"
    finally:
        store.close()


def test_bounded_external_ai_proposal_requires_user_acceptance(tmp_path):
    store, projects = service(tmp_path)
    payload = external_payload()
    project = projects.create("Bounded revision", "LONG_FORM_16_9", "script-first")
    project = projects.write(project["project_id"], "script", payload["script"], project["revision"])
    project = projects.approve_script(project["project_id"], project["artifacts"]["script"],
                                      project["revision"], True)
    project = projects.attach_wav(project["project_id"], wav_bytes(7), project["revision"])["project"]
    selection = {"kind": "illustration", "id": "board-1", "start_ms": 0, "end_ms": 1000}
    request = projects.create_revision_request(project["project_id"], project["revision"],
                                               selection, "Make this explanation clearer")
    assert request["status"] == "pending"
    proposal = projects.submit_revision_proposal(
        project["project_id"], request["request_id"], project["revision"], "layout",
        payload["layout"], "Clarified the selected visual while preserving timing")
    assert proposal["status"] == "proposed"
    preview = projects.preview_revision_proposal(project["project_id"], request["request_id"],
                                                 project["revision"], 250)
    assert preview["png"].startswith(b"\x89PNG")
    assert projects.open(project["project_id"])["revision"] == project["revision"]
    result = projects.decide_revision_proposal(project["project_id"], request["request_id"],
                                               project["revision"], True)
    assert result["request"]["status"] == "applied"
    assert result["project"]["revision"] == project["revision"] + 1
    store.close()


def test_stale_or_rejected_revision_never_mutates_project(tmp_path):
    store, projects = service(tmp_path)
    payload = external_payload()
    project = projects.create("Rejected revision", "LONG_FORM_16_9", "script-first")
    request = projects.create_revision_request(project["project_id"], 0,
        {"kind": "script", "id": "scene-1", "start_ms": 0, "end_ms": 1000}, "Shorten this")
    projects.submit_revision_proposal(project["project_id"], request["request_id"], 0,
                                      "script", payload["script"], "Shorter narration")
    rejected = projects.decide_revision_proposal(project["project_id"], request["request_id"], 0, False)
    assert rejected["status"] == "rejected" and projects.open(project["project_id"])["revision"] == 0
    try:
        projects.decide_revision_proposal(project["project_id"], request["request_id"], 0, True)
    except ProjectError as error:
        assert error.code == "revision_conflict"
    else:
        raise AssertionError("Rejected proposal was applied")
    store.close()


def test_profile_switch_is_revision_checked(tmp_path):
    store, projects = service(tmp_path)
    project = projects.create("Profile", "LONG_FORM_16_9", "idea-first")
    changed = projects.set_profile(project["project_id"], "SHORT_FORM_9_16", 0)
    assert changed["profile"] == "SHORT_FORM_9_16" and changed["revision"] == 1
    try:
        projects.set_profile(project["project_id"], "LONG_FORM_16_9", 0)
    except ProjectError as error:
        assert error.code == "revision_conflict"
    else:
        raise AssertionError("Stale profile update was accepted")
    store.close()


def test_revision_selection_uses_edited_duration_after_import_and_trim(tmp_path):
    store, projects = service(tmp_path)
    try:
        pid = projects.create("Edited duration", "LONG_FORM_16_9", "audio-only")["project_id"]
        original = projects.attach_wav(pid, wav_bytes(7), 0)
        placed = projects.edit_source_timeline(pid, "insert", {"media_id": original["media"]["media_id"], "at_ms": 0}, 1, 0)
        rev = projects.attach_wav(pid, wav_bytes(2), placed["project"]["revision"])["project"]["revision"]
        selection = {"kind": "audio", "id": "tail", "start_ms": 5000, "end_ms": 7000}
        assert projects.create_revision_request(pid, rev, selection, "Change the ending")["status"] == "pending"
        clip = placed["timeline"]["document"]["clips"][0]
        edit = projects.edit_source_timeline(pid, "trim", {"clip_id": clip["clip_id"], "start_ms": 0, "end_ms": 4000},
                                             rev, placed["timeline"]["timeline_revision"])
        with pytest.raises(ProjectError, match="exceeds"):
            projects.create_revision_request(pid, edit["project"]["revision"], selection, "Edit beyond the trim")
    finally:
        store.close()
