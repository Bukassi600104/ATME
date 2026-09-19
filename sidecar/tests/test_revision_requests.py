from atme.project_service import ProjectError, ProjectService
from atme.store.db import JobStore
from test_external_inputs import external_payload
from test_project_runner import wav_bytes


def service(tmp_path):
    store = JobStore(tmp_path / "projects.db")
    return store, ProjectService(store)


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
