"""A desktop restart and a disconnected MCP client must leave an actionable job."""
import subprocess
import sys
import threading

import pytest

from atme.project_service import ProjectError, ProjectService
from atme.project_workers import submit
from atme.store.db import JobStore


@pytest.mark.parametrize("kind", ["render", "timing"])
def test_interrupted_job_can_be_resumed_once(tmp_path, kind):
    database = tmp_path / "atme.db"
    first = ProjectService(JobStore(database))
    second = ProjectService(JobStore(database))
    project = first.create("Worker recovery", "LONG_FORM_16_9", "audio-only")["project_id"]
    owner = first.runner if kind == "render" else first.timing
    observer = second.runner if kind == "render" else second.timing
    fingerprint = "a" * 64
    run_id = fingerprint[:24]
    snapshot = {"fingerprint" if kind == "render" else "source_fingerprint": fingerprint}
    # A separate real process acquires the OS lock, records running, and exits.
    code = """
import os, sys
import sqlite3, threading
from types import SimpleNamespace
from pathlib import Path
from atme.project_workers import submit
database, kind, pid, fingerprint = sys.argv[1:]
store = SimpleNamespace(conn=sqlite3.connect(database), db_path=Path(database), _lock=threading.RLock())
owner = SimpleNamespace(service=SimpleNamespace(store=store))
submit(owner, kind, int(pid), 0,
       {'fingerprint' if kind == 'render' else 'source_fingerprint': fingerprint},
       lambda: os._exit(17), False)
"""
    assert subprocess.run([sys.executable, "-c", code, str(database), kind, str(project),
                           fingerprint], timeout=60).returncode == 17
    stopped = observer.status(project, run_id)
    assert stopped["status"] == "failed" and "stopped" in stopped["error"]
    entered, finish = threading.Event(), threading.Event()

    def resume():
        entered.set()
        assert finish.wait(15)
        owner._finish(project, run_id, "done", {"recovered": True}, None)

    try:
        submit(owner, kind, project, 0, snapshot, resume, True)
        assert entered.wait(15)
        duplicate = submit(observer, kind, project, 0, snapshot,
                           lambda: pytest.fail("duplicate worker"), False)
        assert duplicate["status"] in ("queued", "running")
    finally:
        finish.set()
        owner._workers[run_id].join(15)
    assert observer.status(project, run_id)["status"] == "done"
    first.store.close()
    second.store.close()


def test_thread_start_and_preflight_failures_are_terminal(tmp_path, monkeypatch):
    core = ProjectService(JobStore(tmp_path / "jobs.db"))
    pid = core.create("Worker failure", "LONG_FORM_16_9", "audio-only")["project_id"]
    snapshot = {"source_fingerprint": "d" * 64}
    run_id = snapshot["source_fingerprint"][:24]

    def fail(*args):
        raise OSError("Out of resources")

    with monkeypatch.context() as patch:
        patch.setattr(threading.Thread, "start", fail)
        with pytest.raises(ProjectError, match="Could not start"):
            submit(core.timing, "timing", pid, 0, snapshot, fail, True)
    assert core.timing.status(pid, run_id)["status"] == "failed"
    with pytest.raises(ProjectError, match="Out of resources"):
        submit(core.timing, "timing", pid, 0, snapshot, fail, False)
    assert core.timing.status(pid, run_id)["error"] == "Out of resources"
    core.store.close()
