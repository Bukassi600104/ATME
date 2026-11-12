"""A desktop restart and a disconnected MCP client must leave an actionable job."""
import subprocess
import sqlite3
import os
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
        return {"recovered": True}

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


def test_worker_can_finish_after_client_disconnects_and_failed_writes_roll_back(tmp_path):
    path = tmp_path / "connections.db"
    writer = ProjectService(JobStore(path))
    reader = ProjectService(JobStore(path))
    project = writer.create("Disconnect", "LONG_FORM_16_9", "audio-only")["project_id"]
    with pytest.raises(ValueError, match="cancelled"):
        with writer.store._tx() as connection:
            connection.execute("UPDATE jobs SET title='Uncommitted' WHERE id=?", (project,))
            raise ValueError("cancelled")
    assert not writer.store.conn.in_transaction
    assert reader.open(project)["title"] == "Disconnect"
    proceed = threading.Event()
    def calculate():
        assert proceed.wait(15)
        return {"ready": True}
    queued = submit(writer.timing, "timing", project, 0, {"source_fingerprint": "c" * 64},
                    calculate, True)
    thread = writer.timing._workers[queued["run_id"]]
    writer.store.close()
    proceed.set()
    thread.join(15)
    assert reader.timing.status(project, queued["run_id"])["timing"] == {"ready": True}
    reader.store.close()


def test_finished_work_survives_a_busy_terminal_database_write(tmp_path, monkeypatch):
    core = ProjectService(JobStore(tmp_path / "receipt.db"))
    project = core.create("Receipt recovery", "LONG_FORM_16_9", "audio-only")["project_id"]
    snapshot = {"source_fingerprint": "f" * 64}
    connect = sqlite3.connect
    calls = []

    class BusyTerminalWrite(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if parameters and parameters[0] == "done":
                raise sqlite3.OperationalError("database is locked")
            return super().execute(sql, parameters)

    def with_busy_writer(database, *args, **kwargs):
        if kwargs.get("timeout") == 30:
            kwargs["factory"] = BusyTerminalWrite
        return connect(database, *args, **kwargs)

    def calculate():
        calls.append("computed")
        return {"duration_ms": 1700}

    monkeypatch.setattr(sqlite3, "connect", with_busy_writer)
    first = submit(core.timing, "timing", project, 0, snapshot, calculate, False)
    second = submit(core.timing, "timing", project, 0, snapshot, calculate, False)
    assert first["status"] == second["status"] == "done"
    assert second["timing"] == {"duration_ms": 1700} and calls == ["computed"]
    core.store.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows local project storage")
def test_poll_reads_committed_job_while_another_connection_writes(tmp_path):
    path = tmp_path / "live.db"
    writer = ProjectService(JobStore(path))
    reader = ProjectService(JobStore(path))
    project = writer.create("Simultaneous edit", "LONG_FORM_16_9", "audio-only")["project_id"]
    run_id = "1" * 24
    try:
        with writer.store.conn:
            writer.store.conn.execute("INSERT INTO project_timing_runs VALUES(?,?,?,?,?,?,?,?,?)",
                                      (project, run_id, 0, "1" * 64, "running", None, None, 1, 1))
        assert reader.store.conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        writer.store.conn.execute("BEGIN EXCLUSIVE")
        writer.store.conn.execute("UPDATE jobs SET title='Pending edit' WHERE id=?", (project,))
        assert reader.timing.status(project, run_id)["status"] == "running"
        writer.store.conn.rollback()
        assert reader.timing.status(project, run_id)["status"] == "failed"
    finally:
        writer.store.close()
        reader.store.close()
