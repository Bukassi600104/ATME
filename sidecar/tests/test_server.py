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


def test_submit_empty_topic_rejected(api):
    status, _body = _req(api, "POST", "/jobs", body={"topic": ""})
    assert status == 400


def test_submit_run_reaches_done_with_review_gate_off(api):
    status, body = _req(api, "POST", "/jobs",
                        body={"topic": "Why inference is hard", "provider": "fake",
                              "voice": "sapi", "target_seconds": 30,
                              "review_gate": False})
    assert status == 200
    job_id = body["job_id"]

    status, body = _req(api, "POST", "/jobs/%d/run" % job_id)
    assert status == 200 and body["accepted"] is True

    deadline = time.time() + 480
    state = {}
    while time.time() < deadline:
        status, state = _req(api, "GET", "/jobs/%d" % job_id)
        if state["job"]["status"] in ("done", "failed"):
            break
        time.sleep(3)
    assert state["job"]["status"] == "done", state.get("stages")
    assert len(state["stages"]) >= 10


def test_review_gate_pauses_and_approves_over_http(api):
    status, body = _req(api, "POST", "/jobs",
                        body={"topic": "Gate over http", "provider": "fake",
                              "voice": "sapi", "target_seconds": 30,
                              "review_gate": True})
    job_id = body["job_id"]
    _req(api, "POST", "/jobs/%d/run" % job_id)

    deadline = time.time() + 240
    state = {}
    approved = False
    while time.time() < deadline:
        status, state = _req(api, "GET", "/jobs/%d" % job_id)
        if state["job"]["status"] == "paused" and not approved:
            status, _b = _req(api, "POST", "/jobs/%d/review" % job_id,
                              body={"approved": True})
            assert status == 200
            approved = True
        if state["job"]["status"] in ("done", "failed"):
            break
        time.sleep(3)
    assert state["job"]["status"] == "done"
    assert approved


def test_script_and_artifacts_endpoints(api):
    status, body = _req(api, "POST", "/jobs",
                        body={"topic": "Endpoint probe", "provider": "fake",
                              "voice": "sapi", "target_seconds": 30,
                              "review_gate": False})
    job_id = body["job_id"]
    _req(api, "POST", "/jobs/%d/run" % job_id)

    deadline = time.time() + 480
    state = {}
    while time.time() < deadline:
        status, state = _req(api, "GET", "/jobs/%d" % job_id)
        if state["job"]["status"] in ("done", "failed"):
            break
        time.sleep(3)
    assert state["job"]["status"] == "done"

    status, doc = _req(api, "GET", "/jobs/%d/script" % job_id)
    assert status == 200 and len(doc["scenes"]) >= 2

    status, arts = _req(api, "GET", "/jobs/%d/artifacts" % job_id)
    assert status == 200
    assert any(a["kind"] == "video" for a in arts["artifacts"])

    status, listing = _req(api, "GET", "/jobs")
    assert any(j["id"] == job_id for j in listing["jobs"])

    status, _body = _req(api, "GET", "/jobs/999999/script")
    assert status == 404
