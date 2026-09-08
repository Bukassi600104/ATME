"""Drive review-gate flow over REAL uvicorn with in-process store visibility."""

import faulthandler
import json
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, "sidecar/src")

faulthandler.dump_traceback_later(300, exit=True)

import uvicorn  # noqa: E402

from atme.orchestrator import Orchestrator  # noqa: E402
from atme.server.app import create_app  # noqa: E402


def call(base, method, path, token="T", body=None):
    req = urllib.request.Request(base + path, method=method)
    req.add_header("Authorization", "Bearer " + token)
    if body is not None:
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(body).encode()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, {}


def main():
    tmp = Path(tempfile.mkdtemp())
    orch = Orchestrator(tmp / "jobs.db")
    app = create_app(token="T", orchestrator=orch)
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    base = "http://127.0.0.1:%d" % port

    st, body = call(base, "POST", "/jobs",
                    body={"topic": "Gate live", "provider": "fake"})
    job = body["job_id"]
    call(base, "POST", "/jobs/%d/run" % job)

    approved = False
    t0 = time.time()
    while time.time() - t0 < 220:
        st, state = call(base, "GET", "/jobs/%d" % job)
        rows = orch.store.conn.execute(
            "SELECT name,status FROM stages WHERE job_id=? ORDER BY rowid",
            (job,)).fetchall()
        compact = " ".join("%s=%s" % (r["name"], r["status"]) for r in rows)
        print("[%3ds] job=%s | %s" % (time.time() - t0, state["job"]["status"], compact),
              flush=True)
        if state["job"]["status"] == "paused" and not approved:
            call(base, "POST", "/jobs/%d/review" % job, body={"approved": True})
            approved = True
            print(">>> approved (server auto-resumes)", flush=True)
        if state["job"]["status"] in ("done", "failed"):
            break
        time.sleep(12)
    print("final:", state["job"]["status"], "approved:", approved)


if __name__ == "__main__":
    main()