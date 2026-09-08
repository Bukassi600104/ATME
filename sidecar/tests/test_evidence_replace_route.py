import json

from test_server_controls import _client, _upload_job
from test_evidence_image import evidence_doc
from atme.store.db import STAGE_ORDER


def setup_job(tmp_path):
    client, orch, headers = _client(tmp_path)
    job = _upload_job(orch)
    directory = orch._job_dir(job)
    directory.mkdir(parents=True, exist_ok=True)
    doc = evidence_doc()
    (directory / "layout.json").write_text(json.dumps(doc))
    for stage in STAGE_ORDER:
        orch.store.start_stage(job, stage)
        orch.store.finish_stage(job, stage, ok=True)
    orch.store.set_job_status(job, "done")
    image = doc["elements"][-1]
    payload = {key: image[key] for key in ("png_base64", "sha256", "provenance")}
    payload["provenance"] = {"kind": "original_illustration", "description": "Replacement"}
    return client, orch, headers, job, directory, payload


def test_replacement_preserves_backup_and_invalidates_downstream(tmp_path):
    client, orch, headers, job, directory, payload = setup_job(tmp_path)
    before = (directory / "layout.json").read_bytes()
    response = client.put(f"/jobs/{job}/evidence/el-evidence", json=payload, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["requires_realign"] is True
    assert next(directory.glob("layout.before-evidence-*.json")).read_bytes() == before
    assert json.loads((directory / "layout.json").read_text())["elements"][-1]["provenance"] == payload["provenance"]
    _, done = orch.store.resume_point(job)
    assert "laid_out" in done and "polished" in done
    assert not set(done) & {"aligned", "rendered", "assembled"}
    assert orch.store.get_job(job)["status"] == "paused"


def test_replacement_rejects_active_invalid_and_non_evidence_targets(tmp_path):
    client, orch, headers, job, directory, payload = setup_job(tmp_path)
    url = f"/jobs/{job}/evidence/el-evidence"
    before = (directory / "layout.json").read_bytes()
    assert client.put(url, json=payload).status_code == 401
    orch.store.set_job_status(job, "running")
    assert client.put(url, json=payload, headers=headers).status_code == 409
    orch.store.set_job_status(job, "paused")
    assert client.put(f"/jobs/{job}/evidence/el-queue", json=payload, headers=headers).status_code == 404
    payload["sha256"] = "0" * 64
    assert client.put(url, json=payload, headers=headers).status_code == 400
    assert (directory / "layout.json").read_bytes() == before


def test_inventory_omits_image_payload_and_unfinished_layout_cannot_be_edited(tmp_path):
    client, orch, headers, job, directory, payload = setup_job(tmp_path)
    response = client.get(f"/jobs/{job}/evidence", headers=headers)
    assert response.status_code == 200
    assert response.json()["slots"][0]["id"] == "el-evidence"
    assert "png_base64" not in response.text
    assert client.get(f"/jobs/{job}/evidence").status_code == 401
    orch.store.reset_from_stage(job, "laid_out")
    assert client.put(f"/jobs/{job}/evidence/el-evidence", json=payload, headers=headers).status_code == 409
