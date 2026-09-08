import json

from test_server_controls import _client, _upload_job


def test_report_requires_authentication_and_existing_job(tmp_path):
    client, orch, headers = _client(tmp_path)
    job = _upload_job(orch)
    assert client.get(f"/jobs/{job}/narration-events").status_code == 401
    assert client.get("/jobs/99999/narration-events", headers=headers).status_code == 404
    assert client.get(f"/jobs/{job}/narration-events", headers=headers).json() == {
        "status": "not_available", "events": []}


def test_report_distinguishes_empty_success_and_review(tmp_path):
    client, orch, headers = _client(tmp_path)
    job = _upload_job(orch)
    directory = orch._job_dir(job)
    directory.mkdir(parents=True, exist_ok=True)
    report = directory / "narration_events.json"
    for events, status in [([], "no_triggers"),
                           ([{"target_id": "el-a", "status": "resolved"}], "resolved"),
                           ([{"target_id": "el-a", "status": "ambiguous"}], "needs_review")]:
        report.write_text(json.dumps(events))
        result = client.get(f"/jobs/{job}/narration-events", headers=headers)
        assert result.status_code == 200
        assert result.json() == {"status": status, "events": events}
    report.write_text("{incomplete")
    assert client.get(f"/jobs/{job}/narration-events", headers=headers).status_code == 409
