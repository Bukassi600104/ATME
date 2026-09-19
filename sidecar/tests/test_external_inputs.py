import json

import pytest

from atme.orchestrator import Orchestrator
from test_server_controls import _client
from test_board_continuity import board_doc


def external_payload():
    return {"script": {"topic": "Queue evidence", "scenes": [
        {"scene_id": 1, "phase": "hook", "spoken_text": "Queue pointer.",
         "visual_directive": "Explain the queue."},
        {"scene_id": 2, "phase": "conclusion", "spoken_text": "Evidence return.",
         "visual_directive": "Show evidence then return."}]}, "layout": board_doc()}


def test_import_review_and_wait_for_original_voice_without_providers(tmp_path, monkeypatch):
    client, orch, headers = _client(tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError("No internal AI or credentials may be used")
    monkeypatch.setattr(orch, "_completes_for", forbidden)
    monkeypatch.setattr(orch.settings_store, "runtime_roles", forbidden)
    monkeypatch.setattr(orch.settings_store, "configured", forbidden)
    payload = external_payload()
    response = client.post("/jobs/external", json=payload, headers=headers)
    assert response.status_code == 200, response.text
    job = response.json()["job_id"]
    assert orch.store.get_job(job)["settings"]["provider"] == "external"
    from atme import warmup, guardrails, cognitive
    monkeypatch.setattr(warmup, "warm_heavy_imports", lambda: None)
    monkeypatch.setattr(guardrails, "preflight", lambda path: {})
    for name in ("research_stage", "script_stage", "layout_stage"):
        monkeypatch.setattr(cognitive, name, forbidden)
    result = Orchestrator.run_job(orch, job)
    assert result["paused"] and "script" in result
    assert "researched" not in orch.store.resume_point(job)[1]
    changed = external_payload()["script"]["scenes"]
    changed[0]["spoken_text"] = "Changed"
    assert client.post(f"/jobs/{job}/review", json={"approved": True, "scenes": changed},
                       headers=headers).status_code == 409
    approved = client.post(f"/jobs/{job}/review",
        json={"approved": True, "scenes": payload["script"]["scenes"]}, headers=headers)
    assert approved.json()["status"] == "waiting_voice"
    assert Orchestrator.run_job(orch, job)["waiting_voice"]
    assert orch.store.get_job(job)["status"] == "waiting_voice"
    assert client.get(f"/jobs/{job}/history", headers=headers).json()["usage"] == []


@pytest.mark.parametrize("problem", ["missing", "scenes", "board", "timing"])
def test_invalid_import_creates_no_job(tmp_path, problem):
    client, orch, headers = _client(tmp_path)
    payload = external_payload()
    if problem == "missing":
        del payload["script"]
    elif problem == "scenes":
        payload["script"]["scenes"][1]["scene_id"] = 9
    elif problem == "board":
        del payload["layout"]["board_timeline"]
    else:
        payload["layout"]["elements"][0]["appear_at_ms"] = 2500
    assert client.post("/jobs/external", json=payload, headers=headers).status_code == 400
    assert client.get("/jobs", headers=headers).json()["jobs"] == []


def test_provider_setup_and_topic_generation_retired_without_touching_credentials(tmp_path, monkeypatch):
    client, orch, headers = _client(tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError("Credentials must stay untouched")
    monkeypatch.setattr(orch.settings_store, "save", forbidden)
    monkeypatch.setattr(orch.settings_store, "public", forbidden)
    assert client.get("/settings/providers", headers=headers).json()["api_keys_required"] is False
    assert client.put("/settings/providers", json={}, headers=headers).status_code == 410
    assert client.post("/jobs", json={"topic": "Test"}, headers=headers).status_code == 410
    assert client.post("/jobs/external", json=external_payload()).status_code == 401
    with pytest.raises(ValueError, match="retired"):
        orch._completes_for({"provider": "litellm"})


def test_external_orchestration_reaches_assembly_with_media_doubles(tmp_path, monkeypatch):
    """Control-flow proof only: media functions are doubles, not video acceptance."""
    client, orch, headers = _client(tmp_path)
    response = client.post("/jobs/external", json=external_payload(), headers=headers)
    job = response.json()["job_id"]
    client.post(f"/jobs/{job}/review", json={"approved": True}, headers=headers)
    directory = orch._job_dir(job)
    (directory / "audio").mkdir()
    (directory / "audio" / "upload.wav").write_bytes(b"test-only media double")
    from atme import warmup, guardrails, cognitive, pipeline
    monkeypatch.setattr(warmup, "warm_heavy_imports", lambda: None)
    monkeypatch.setattr(guardrails, "preflight", lambda path: {})
    def forbidden(*args, **kwargs):
        raise AssertionError("Internal creative work must never run")
    monkeypatch.setattr(orch, "_completes_for", forbidden)
    for name in ("research_stage", "script_stage", "layout_stage"):
        monkeypatch.setattr(cognitive, name, forbidden)
    monkeypatch.setattr(orch, "_attach_file", lambda *args: None)
    calls = []
    results = {
        "polish_stage": {"final_wav": str(directory / "audio" / "final.wav")},
        "align_stage": {key: str(directory / name) for key, name in [
            ("cues_file", "cue_timeline.json"), ("planning_context_file", "planning_context.json"),
            ("layout_file", "layout.json"), ("visual_plan_file", "visual_plan.json")]},
        "render_stage": {"silent_video": str(directory / "out" / "video.mp4")},
        "assemble_stage": {"artifacts": {"video": {"path": str(directory / "out" / "final.mp4")}}},
    }
    for name, output in results.items():
        def stage(*args, _name=name, _output=output, **kwargs):
            calls.append(_name)
            return _output
        monkeypatch.setattr(pipeline, name, stage)
    result = Orchestrator.run_job(orch, job)
    assert calls == list(results)
    assert result["manifest"] == results["assemble_stage"]
    assert orch.store.get_job(job)["status"] == "done"
    assert client.get(f"/jobs/{job}/history", headers=headers).json()["usage"] == []
