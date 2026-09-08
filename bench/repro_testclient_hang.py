"""TestClient-flavored repro with automatic all-thread traceback dump at 150s."""

from __future__ import annotations

import faulthandler
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, "sidecar/src")

dump_file = Path(tempfile.mkdtemp()) / "stacks.txt"
armed = {"on": False}


def worker_watch():
    time.sleep(150)
    if armed["on"]:
        with open(dump_file, "w") as f:
            f.write("=== stacks at 150s ===\n")
            faulthandler.dump_traceback(file=f)


def main():
    from fastapi.testclient import TestClient

    from atme.orchestrator import Orchestrator
    from atme.server.app import create_app

    orch = Orchestrator(Path(tempfile.mkdtemp()) / "jobs.db")
    app = create_app(token="t", orchestrator=orch)
    client = TestClient(app)
    H = {"Authorization": "Bearer t"}

    job_id = client.post("/jobs", json={"topic": "Why inference is hard",
                                        "provider": "fake", "review_gate": False},
                         headers=H).json()["job_id"]
    print("submitted", job_id, flush=True)

    real_run = client.post

    def posting(path, **kw):
        res = real_run(path, **kw)
        if path.endswith("/run") and not armed["on"]:
            armed["on"] = True
            faulthandler.enable()
            threading.Thread(target=worker_watch, daemon=True).start()
        return res

    client.post = posting  # type: ignore[method-assign]

    client.post("/jobs/%d/run" % job_id, headers=H)

    deadline = time.time() + 300
    state = {}
    while time.time() < deadline:
        state = client.get("/jobs/%d" % job_id, headers=H).json()
        if state["job"]["status"] in ("done", "failed"):
            break
        time.sleep(2)
    print("final status:", state["job"]["status"], flush=True)
    if dump_file.exists():
        print("---- STACKS ----")
        print(dump_file.read_text(encoding="utf-8")[-4000:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
