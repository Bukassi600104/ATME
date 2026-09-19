import json
import io
from PIL import Image

import pytest

from test_board_planner import inputs
from test_evidence_replace_route import setup_job


def setup(tmp_path, monkeypatch):
    client, orch, headers, job, directory, _ = setup_job(tmp_path)
    _, context, proposal = inputs()
    script = {"scenes": [{"scene_id": s["scene_id"], "spoken_text": s["narration"]}
                         for s in context["scenes"]]}
    (directory / "script.json").write_text(json.dumps(script))
    (directory / "planning_context.json").write_text(json.dumps(context))
    (directory / "audio_state.json").write_text(json.dumps({"sha256": "a" * 64, "duration_ms": 6000}))
    calls = []
    def complete(system, user):
        calls.append(user)
        return json.dumps(proposal)
    monkeypatch.setattr(orch, "_completes_for", lambda settings: {"layouter": complete})
    revision = client.get(f"/jobs/{job}/boards", headers=headers).json()["revision"]
    url = f"/jobs/{job}/board-proposal"
    client.external_proposal = {"source_hashes": client.get(url + "/context", headers=headers).json()["source_hashes"],
                                "proposal": inputs()[2]}
    return client, orch, headers, job, directory, revision, url, calls


def test_generate_review_accept_with_backup_and_usage(tmp_path, monkeypatch):
    client, orch, headers, job, directory, revision, url, calls = setup(tmp_path, monkeypatch)
    before = (directory / "layout.json").read_bytes()
    result = client.post(url, json=client.external_proposal, params={"revision": revision}, headers=headers)
    assert result.status_code == 200, result.text
    assert len(calls) == 0
    exported = client.get(url + "/context", headers=headers)
    assert exported.status_code == 200
    assert "png_base64" not in exported.text
    assert exported.json()["revision"] == revision
    assert "png_base64" not in result.text
    assert (directory / "layout.json").read_bytes() == before
    assert orch.store.get_job(job)["status"] == "done"
    loaded = client.get(url, headers=headers)
    assert loaded.json() == result.json()
    assert len(client.get(f"/jobs/{job}/history", headers=headers).json()["usage"]) == 0
    accepted = client.post(url + "/accept", params={"proposal_id": result.json()["proposal_id"]}, headers=headers)
    assert accepted.status_code == 200, accepted.text
    assert next(directory.glob("layout.before-proposal-*.json")).read_bytes() == before
    assert orch.store.get_job(job)["status"] == "paused"
    assert "aligned" not in orch.store.resume_point(job)[1]
    assert client.get(url, headers=headers).status_code == 409  # Consumed/stale.


@pytest.mark.parametrize("changed", ["layout.json", "script.json", "audio_state.json", "planning_context.json"])
def test_acceptance_rejects_any_changed_source(tmp_path, monkeypatch, changed):
    client, _, headers, _, directory, revision, url, _ = setup(tmp_path, monkeypatch)
    result = client.post(url, json=client.external_proposal, params={"revision": revision}, headers=headers)
    assert result.status_code == 200
    path = directory / changed
    path.write_bytes(path.read_bytes() + b"\n")
    before = (directory / "layout.json").read_bytes()
    accepted = client.post(url + "/accept", params={"proposal_id": result.json()["proposal_id"]}, headers=headers)
    assert accepted.status_code == 409
    assert (directory / "layout.json").read_bytes() == before
    assert not list(directory.glob("layout.before-proposal-*.json"))


def test_reject_before_spending_and_authentication(tmp_path, monkeypatch):
    client, orch, headers, job, directory, revision, url, calls = setup(tmp_path, monkeypatch)
    assert client.post(url, json=client.external_proposal, params={"revision": revision}).status_code == 401
    assert client.get(url).status_code == 401
    assert client.post(url + "/accept", params={"proposal_id": "x"}).status_code == 401
    assert client.post(url, json=client.external_proposal, params={"revision": "stale"}, headers=headers).status_code == 409
    context = json.loads((directory / "planning_context.json").read_text())
    context["status"] = "needs_review"
    (directory / "planning_context.json").write_text(json.dumps(context))
    assert client.post(url, json=client.external_proposal, params={"revision": revision}, headers=headers).status_code == 409
    assert calls == []


def test_empty_request_does_not_generate_or_call_provider(tmp_path, monkeypatch):
    client, _, headers, _, directory, revision, url, calls = setup(tmp_path, monkeypatch)
    result = client.post(url, params={"revision": revision}, headers=headers)
    assert result.status_code == 400
    assert calls == []
    assert not (directory / "board_proposal.json").exists()


def test_import_rejects_old_context_even_when_layout_is_unchanged(tmp_path, monkeypatch):
    client, _, headers, _, directory, revision, url, calls = setup(tmp_path, monkeypatch)
    context = json.loads((directory / "planning_context.json").read_text())
    context["audio_sha256"] = "b" * 64
    (directory / "planning_context.json").write_text(json.dumps(context))
    (directory / "audio_state.json").write_text(json.dumps({"sha256": "b" * 64, "duration_ms": 6000}))
    result = client.post(url, json=client.external_proposal, params={"revision": revision}, headers=headers)
    assert result.status_code == 409
    assert calls == []
    assert not (directory / "board_proposal.json").exists()


def test_duplicate_generation_is_rejected_and_wrong_acceptance_id_is_safe(tmp_path, monkeypatch):
    client, orch, headers, _, directory, revision, url, _ = setup(tmp_path, monkeypatch)
    def complete(system, user):
        assert client.post(url, json=client.external_proposal, params={"revision": revision}, headers=headers).status_code == 409
        return json.dumps(inputs()[2])
    monkeypatch.setattr(orch, "_completes_for", lambda settings: {"layouter": complete})
    before = (directory / "layout.json").read_bytes()
    assert client.post(url, json=client.external_proposal, params={"revision": revision}, headers=headers).status_code == 200
    assert client.post(url + "/accept", params={"proposal_id": "wrong"}, headers=headers).status_code == 409
    assert (directory / "layout.json").read_bytes() == before


def test_invalid_import_preserves_layout_and_has_no_usage(tmp_path, monkeypatch):
    client, _, headers, job, directory, revision, url, calls = setup(tmp_path, monkeypatch)
    before = (directory / "layout.json").read_bytes()
    result = client.post(url, json={}, params={"revision": revision}, headers=headers)
    assert result.status_code == 400
    assert calls == []
    assert client.get(f"/jobs/{job}/history", headers=headers).json()["usage"] == []
    assert (directory / "layout.json").read_bytes() == before


def test_preview_renders_candidate_without_applying_and_checks_identity(tmp_path, monkeypatch):
    client, _, headers, _, directory, revision, url, calls = setup(tmp_path, monkeypatch)
    before = (directory / "layout.json").read_bytes()
    result = client.post(url, json=client.external_proposal, params={"revision": revision}, headers=headers).json()
    params = {"proposal_id": result["proposal_id"], "at_ms": 2050}
    current = client.get(url + "/preview", params={**params, "version": "current"}, headers=headers)
    proposed = client.get(url + "/preview", params=params, headers=headers)
    assert current.status_code == proposed.status_code == 200
    assert current.headers["content-type"] == "image/png"
    assert proposed.headers["cache-control"] == "no-store"
    image = Image.open(io.BytesIO(proposed.content))
    assert image.size == (960, 540)
    assert current.content != proposed.content  # Evidence cut moves from 2000 to 2100.
    assert len(calls) == 0  # Import and rendering never call an LLM.
    assert (directory / "layout.json").read_bytes() == before
    assert client.get(url + "/preview", params=params).status_code == 401
    assert client.get(url + "/preview", params={**params, "at_ms": 6000}, headers=headers).status_code == 400
    assert client.get(url + "/preview", params={**params, "proposal_id": "wrong"}, headers=headers).status_code == 409
    assert client.get(url + "/preview", params={**params, "version": "invalid"}, headers=headers).status_code == 422
    (directory / "layout.json").write_bytes(before + b"\n")
    assert client.get(url + "/preview", params=params, headers=headers).status_code == 409
