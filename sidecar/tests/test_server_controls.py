from __future__ import annotations

import io
import math
import struct
import wave

from fastapi.testclient import TestClient

from atme.orchestrator import Orchestrator
from atme.server.app import create_app
from atme.settings import SettingsStore
from atme.store.db import STAGE_ORDER


class StubOrchestrator(Orchestrator):
    def run_job(self, job_id: int, progress_cb=None) -> dict:
        return {"job_id": job_id, "paused": True, "waiting_voice": True}


def _client(tmp_path):
    settings = SettingsStore(tmp_path / "settings.json")
    orch = StubOrchestrator(tmp_path / "jobs" / "jobs.db",
                            data_root=tmp_path, settings_store=settings)
    app = create_app("secret", orch)
    return TestClient(app), orch, {"Authorization": "Bearer secret"}


def _wav_bytes(seconds: float = 1.2, sample_rate: int = 16_000) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        frames = [int(9000 * math.sin(2 * math.pi * 220 * i / sample_rate))
                  for i in range(int(seconds * sample_rate))]
        wav.writeframes(b"".join(struct.pack("<h", value) for value in frames))
    return output.getvalue()


def _upload_job(orch: Orchestrator) -> int:
    job_id = orch.store.create_job("Upload route", settings={
        "provider": "fake", "voice": "upload", "review_gate": False,
        "width": 1280, "height": 720, "fps": 30,
    })
    for stage in STAGE_ORDER:
        orch.store.ensure_stage(job_id, stage)
    orch.store.set_job_status(job_id, "waiting_voice")
    return job_id


def test_streamed_voice_upload_is_decoded_without_exposing_source_name(tmp_path):
    client, orch, headers = _client(tmp_path)
    job_id = _upload_job(orch)
    response = client.post(
        f"/jobs/{job_id}/voice", content=_wav_bytes(),
        headers={**headers, "X-Filename": "..\\my original take.WAV",
                 "Content-Type": "audio/wav"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["quality"]["duration_ms"] >= 1000
    assert (orch._job_dir(job_id) / "audio" / "source.wav").exists()
    assert (orch._job_dir(job_id) / "audio" / "upload.wav").exists()


def test_cancel_idle_job_becomes_terminal_immediately(tmp_path):
    client, orch, headers = _client(tmp_path)
    job_id = _upload_job(orch)
    response = client.post(f"/jobs/{job_id}/control",
                           json={"action": "cancel"}, headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "canceled"
    assert orch.store.get_job(job_id)["status"] == "canceled"


def test_provider_settings_are_redacted_over_http(tmp_path):
    client, _orch, headers = _client(tmp_path)
    roles = {
        role: {"model": "provider/model", "api_key": "top-secret-value",
               "web_grounded": role == "researcher"}
        for role in ("researcher", "reasoner", "writer", "layouter")
    }
    response = client.put("/settings/providers", json={"roles": roles}, headers=headers)
    assert response.status_code == 410, response.text
    text = response.text
    assert "top-secret-value" not in text
    result = client.get("/settings/providers", headers=headers).json()
    assert result["configured"] is False
    assert result["roles"] == {}
    assert result["api_keys_required"] is False


def test_review_preview_uses_the_real_svg_renderer(tmp_path):
    import json

    client, orch, headers = _client(tmp_path)
    job_id = _upload_job(orch)
    job_dir = orch._job_dir(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "script.json").write_text(json.dumps({
        "topic": "Queues",
        "title": "Why Queues Back Up",
        "target_seconds": 20,
        "scenes": [
            {"scene_id": 1, "phase": "hook",
             "spoken_text": "A queue can look healthy until arrivals outrun service capacity.",
             "visual_directive": "draw a box labeled Queue"},
            {"scene_id": 2, "phase": "architecture",
             "spoken_text": "The backlog then compounds because each request waits behind the last.",
             "visual_directive": "connect an arrow labeled arrivals to the Queue"},
        ],
    }), encoding="utf-8")
    response = client.get(f"/jobs/{job_id}/preview/2", headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert "<svg" in response.text and "Queue" in response.text


def test_review_preview_uses_saved_board_layout_instead_of_fallback(tmp_path):
    import json
    from conftest import REPO_ROOT

    client, orch, headers = _client(tmp_path)
    job_id = _upload_job(orch)
    job_dir = orch._job_dir(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "script.json").write_text(json.dumps({"scenes": [
        {"scene_id": i, "spoken_text": "Original diagnostic narration", "est_seconds": 3}
        for i in (1, 2, 3)]}), encoding="utf-8")
    layout = REPO_ROOT / "schemas" / "examples" / "board-continuity.example.json"
    (job_dir / "layout.json").write_text(layout.read_text(encoding="utf-8"), encoding="utf-8")
    response = client.get(f"/jobs/{job_id}/preview/2", headers=headers)
    assert response.status_code == 200
    assert "120 arrived" in response.text
    assert "Why does the queue grow?" not in response.text
    returned = client.get(f"/jobs/{job_id}/preview/3", headers=headers)
    assert "Backlog grows by 4" in returned.text
    assert "120 arrived" not in returned.text
