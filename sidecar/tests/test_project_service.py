import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from atme.project_service import ProjectError, ProjectService
from atme.store.db import JobStore


def test_project_archive_removes_launcher_entry_without_deleting_managed_data(tmp_path):
    core = ProjectService(JobStore(tmp_path / "archive.db"))
    project = core.create("Keep files", "LONG_FORM_16_9", "audio-only")
    from test_server_controls import _wav_bytes
    uploaded = core.attach_wav(project["project_id"], _wav_bytes(), 0)
    managed = next((tmp_path / "project-media").rglob("*.wav"))
    with pytest.raises(ProjectError):
        core.archive(project["project_id"], uploaded["project"]["revision"], False)
    result = core.archive(project["project_id"], uploaded["project"]["revision"], True)
    assert result["archived"] and result["files_retained"] and managed.is_file()
    assert core.list() == []
    core.store.close()
from test_external_inputs import external_payload
from test_server_controls import _client, _wav_bytes


def service(tmp_path):
    return ProjectService(JobStore(tmp_path / "projects.db"))


def create(core, profile="LONG_FORM_16_9"):
    return core.create("Externally authored project", profile, "script-first")


def test_script_without_layout_version_approval_and_invalidation(tmp_path):
    core = service(tmp_path)
    project = create(core)
    pid = project["project_id"]
    script = external_payload()["script"]
    state = core.write(pid, "script", script, 0)
    assert state["revision"] == 1 and state["artifacts"] == {"script": 1}
    approved = core.approve_script(pid, 1, 1, True)
    assert approved["approved_script_revision"] == 1 and approved["revision"] == 2
    script["scenes"][0]["spoken_text"] = "An externally authored revision."
    revised = core.write(pid, "script", script, 2)
    assert revised["approved_script_revision"] is None
    assert core.store.conn.execute("SELECT script_revision FROM project_approval_events").fetchone()[0] == 1
    assert core.artifact(pid, "script", 1)["document"] != script
    assert core.artifact(pid, "script")["document"] == script
    assert revised["render_ready"] is False
    core.store.close()
    reopened = service(tmp_path)
    assert reopened.open(pid) == revised
    assert reopened.list() == [revised]
    reopened.store.close()


def test_invalid_artifact_is_structured_and_does_not_mutate(tmp_path):
    core = service(tmp_path)
    project = create(core)
    with pytest.raises(ProjectError) as error:
        core.write(project["project_id"], "script", {"topic": "Incomplete"}, 0)
    assert error.value.code == "invalid_artifact"
    assert error.value.errors
    assert core.open(project["project_id"]) == project
    # Correction loop on the same unchanged revision.
    assert core.write(project["project_id"], "script", external_payload()["script"], 0)["revision"] == 1
    core.store.close()


def test_concurrent_writers_cannot_overwrite_same_revision(tmp_path):
    core = service(tmp_path)
    other = service(tmp_path)
    pid = create(core)["project_id"]
    def write(number):
        try:
            (core if number == 1 else other).write(pid, "brief", {"description": str(number)}, 0)
            return "written"
        except ProjectError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(write, [1, 2])) == ["revision_conflict", "written"]
    assert core.open(pid)["revision"] == 1
    other.store.close()
    core.store.close()


@pytest.mark.parametrize("profile", ["LONG_FORM_16_9", "SHORT_FORM_9_16"])
def test_supported_profile_metadata(tmp_path, profile):
    core = service(tmp_path)
    assert create(core, profile)["profile"] == profile
    core.store.close()


def test_reject_square_unknown_artifacts_and_implicit_approval(tmp_path):
    core = service(tmp_path)
    with pytest.raises(ProjectError):
        create(core, "SQUARE_1_1")
    pid = create(core)["project_id"]
    with pytest.raises(ProjectError):
        core.write(pid, "../../settings", {}, 0)
    core.write(pid, "script", external_payload()["script"], 0)
    for approved in (False, "true", 1, None):
        with pytest.raises(ProjectError, match="Explicit"):
            core.approve_script(pid, 1, 1, approved)
    with pytest.raises(ProjectError, match="current"):
        core.approve_script(pid, 0, 1, True)
    core.store.close()


def test_http_project_ingress_auth_and_correction(tmp_path):
    client, orch, headers = _client(tmp_path)
    assert client.get("/projects").status_code == 401
    caps = client.get("/projects/capabilities", headers=headers).json()
    assert caps["api_keys_required"] is False and caps["mcp_available"] is True
    assert caps["mcp_connection_status"] == "shared_activity"
    response = client.post("/projects", headers=headers, json={
        "title": "External script", "profile": "LONG_FORM_16_9", "input_kind": "script-first"})
    assert response.status_code == 200, response.text
    pid = response.json()["project_id"]
    url = f"/projects/{pid}/artifacts/script"
    invalid = client.put(url, headers=headers, json={"document": {}, "expected_revision": 0})
    assert invalid.status_code == 400
    assert invalid.json()["detail"]["errors"]
    valid = client.put(url, headers=headers, json={
        "document": external_payload()["script"], "expected_revision": 0})
    assert valid.status_code == 200
    assert client.put(url, headers=headers, json={
        "document": external_payload()["script"], "expected_revision": 0}).status_code == 409
    approved = client.post(f"/projects/{pid}/script-approval", headers=headers,
        json={"approved": True, "expected_revision": 1, "script_revision": 1})
    assert approved.status_code == 200
    assert approved.json()["status"] == "script_approved"
    assert client.get(url, headers=headers).json()["document"] == external_payload()["script"]
    assert not orch._job_dir(pid).exists()  # No renderer or creative stage launched.


def test_project_core_and_board_compiler_do_not_import_creative_runtime():
    command = (
        "import atme.project_service, atme.board_compiler, sys; "
        "assert not any(n == 'litellm' or n.startswith(('litellm.', 'atme.gateway', "
        "'atme.agents', 'atme.cognitive', 'atme.settings')) for n in sys.modules)"
    )
    result = subprocess.run([sys.executable, "-c", command], capture_output=True,
                            text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stderr


def test_recording_authority_does_not_require_script_approval(tmp_path):
    core = service(tmp_path)
    pid = core.create("Recording authority", "LONG_FORM_16_9", "audio-only")["project_id"]
    core.attach_wav(pid, _wav_bytes(7), 0)
    source = core.narrative_source(pid)
    assert source["mode"] == "recording_authority"
    assert source["ready_for_timing"] is True
    assert source["narrative_authority"]["media"]["semantic_transcript"] is None
    script = external_payload()["script"]
    state = core.write(pid, "script", script, 1)
    assert state["approved_script_revision"] is None
    assert state["authoritative_narrative_source"]["semantic_structure"]["role"] == (
        "connected_ai_derivative_of_recording")
    with pytest.raises(ProjectError, match="do not promote"):
        core.approve_script(pid, 2, 2, True)
    core.store.close()


def test_editor_history_persists_cut_undo_and_redo(tmp_path):
    core = service(tmp_path)
    project = create(core, "SHORT_FORM_9_16")
    original = external_payload()["script"]
    project = core.write(project["project_id"], "script", original, 0)
    cut = {**original, "scenes": [
        {**original["scenes"][0], "spoken_text": "Queue"},
        {**original["scenes"][0], "scene_id": 3, "spoken_text": "pointer."},
        original["scenes"][1]]}
    result = core.edit(project["project_id"], "cut", "script", cut, project["revision"])
    assert result["history"] == {"can_undo": True, "can_redo": False,
                                 "undo_label": "cut", "redo_label": None}
    reopened = ProjectService(core.store)
    undone = reopened.undo(project["project_id"], result["project"]["revision"])
    assert reopened.artifact(project["project_id"], "script")["document"] == original
    assert undone["history"]["can_redo"] is True
    redone = reopened.redo(project["project_id"], undone["project"]["revision"])
    assert reopened.artifact(project["project_id"], "script")["document"] == cut
    assert redone["history"]["can_undo"] is True
    core.store.close()
