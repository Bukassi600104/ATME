"""Server API tests over a REAL loopback uvicorn server (production-faithful transport)."""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

from conftest import REPO_ROOT

pytestmark = pytest.mark.integration


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    src = REPO_ROOT / "sidecar" / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

    import uvicorn

    from atme.orchestrator import Orchestrator
    from atme.server.app import create_app

    orch = Orchestrator(tmp_path_factory.mktemp("srv") / "jobs.db")
    app = create_app(token="test-token", orchestrator=orch)
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = "http://127.0.0.1:%d" % port

    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            urllib.request.urlopen(base + "/healthz", timeout=2)
            break
        except Exception:
            time.sleep(0.2)

    yield {"base": base, "H": {"Authorization": "Bearer test-token"}}

    server.should_exit = True
    thread.join(timeout=10)


def _req(api, method: str, path: str, body: dict | None = None, auth: bool = True):
    url = api["base"] + path
    data = json.dumps(body).encode() if body is not None else None
    headers = {**api["H"], "Content-Type": "application/json"} if auth \
        else {"Content-Type": "application/json"}
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


def test_healthz_open_but_rest_locked(api):
    status, _body = _req(api, "GET", "/healthz")   # no auth header
    assert status == 200
    status, _body = _req(api, "GET", "/jobs/1", auth=False)
    assert status == 401
    status, _body = _req(api, "POST", "/jobs", body={"topic": ""}, auth=False)
    assert status == 401


def test_internal_generation_retired(api):
    status, _body = _req(api, "POST", "/jobs", body={"topic": "Legacy topic"})
    assert status == 410


def test_external_import_review_and_artifacts_over_real_http(api):
    from test_external_inputs import external_payload
    payload = external_payload()
    status, body = _req(api, "POST", "/jobs/external", body=payload)
    assert status == 200
    job_id = body["job_id"]
    status, state = _req(api, "GET", f"/jobs/{job_id}")
    assert state["job"]["status"] == "paused"
    status, doc = _req(api, "GET", f"/jobs/{job_id}/script")
    assert status == 200 and doc == payload["script"]
    status, approved = _req(api, "POST", f"/jobs/{job_id}/review",
                           body={"approved": True, "scenes": doc["scenes"]})
    assert status == 200 and approved["status"] == "waiting_voice"
    status, arts = _req(api, "GET", f"/jobs/{job_id}/artifacts")
    assert status == 200
    assert any(a["kind"] == "approved_script" for a in arts["artifacts"])
    status, history = _req(api, "GET", f"/jobs/{job_id}/history")
    assert history["usage"] == []
    status, listing = _req(api, "GET", "/jobs")
    assert any(j["id"] == job_id for j in listing["jobs"])
    status, _body = _req(api, "GET", "/jobs/999999/script")
    assert status == 404
