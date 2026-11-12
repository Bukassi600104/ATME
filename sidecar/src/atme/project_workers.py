"""Claim one timing or export snapshot across desktop and MCP processes."""
from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import closing

from atme.project_service import ProjectError


# Only internal constants select table and column names.
_RUNS = {"render": ("project_render_runs", "manifest", "fingerprint"),
         "timing": ("project_timing_runs", "document", "source_fingerprint")}


def _lease(database, kind, project_id, run_id):
    directory = database.parent / (database.name + ".workers") / kind / str(project_id)
    directory.mkdir(parents=True, exist_ok=True)
    # SQLite's OS lock also releases when Windows terminates the worker process.
    lease = sqlite3.connect(directory / (run_id + ".lock"), timeout=0, check_same_thread=False)
    try:
        lease.execute("BEGIN IMMEDIATE")
    except sqlite3.Error as exc:
        lease.close()
        if getattr(exc, "sqlite_errorcode", None) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            return None
        raise
    return lease


def mark_interrupted(store, kind, project_id, run_id):
    """Called only when a saved row says queued/running. Recheck under ownership."""
    lease = _lease(store.db_path, kind, project_id, run_id)
    if lease is None:
        return False
    table = _RUNS[kind][0]
    with closing(lease), store._lock, store.conn:
        store.conn.execute(
            f"UPDATE {table} SET status='failed',error=?,updated_at=? "
            "WHERE job_id=? AND run_id=? AND status IN ('queued','running')",
            ("The worker stopped before completion. Request the operation again to resume.",
             time.time(), project_id, run_id))
    return True


def submit(owner, kind, project_id, revision, snapshot, callback, background):
    store = owner.service.store
    table, document, fingerprint_key = _RUNS[kind]
    fingerprint = snapshot[fingerprint_key]
    run_id = fingerprint[:24]
    keys = (project_id, run_id)
    def intact():
        if kind == "render":
            try:
                owner.output_path(*keys)
            except ProjectError as exc:
                if exc.code in ("render_not_ready", "render_changed"):
                    return False
                raise
        return True

    query = f"SELECT status,updated_at FROM {table} WHERE job_id=? AND run_id=?"
    with store._lock:
        previous = store.conn.execute(query, keys).fetchone()
    # A large completed export is normally verified outside the write transaction.
    if previous and previous["status"] == "done" and intact():
        return owner.status(*keys)
    lease = None
    try:
        with store._lock, store.conn:
            store.conn.execute("BEGIN IMMEDIATE")
            row = store.conn.execute(query, keys).fetchone()
            if row and row["status"] == "done" and row != previous and intact():
                return owner.status(*keys)
            lease = _lease(store.db_path, kind, project_id, run_id)
            if lease is None:
                return owner.status(project_id, run_id)
            status = "queued" if background else "running"
            now = time.time()
            store.conn.execute(
                f"INSERT INTO {table} VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(job_id,run_id) "
                f"DO UPDATE SET status=excluded.status,{document}=NULL,error=NULL,updated_at=excluded.updated_at",
                (project_id, run_id, revision, fingerprint, status, None, None, now, now))
    except BaseException:
        if lease is not None:
            lease.close()
        raise

    def fail(exc):
        # The originating HTTP/MCP connection may already have closed.
        with closing(sqlite3.connect(store.db_path)) as connection, connection:
            connection.execute(
                f"UPDATE {table} SET status='failed',error=?,updated_at=? "
                "WHERE job_id=? AND run_id=? AND status IN ('queued','running')",
                (str(exc)[:2000], time.time(), project_id, run_id))

    def execute():
        try:
            return callback()
        except Exception as exc:
            fail(exc)
            if not background:
                if isinstance(exc, ProjectError):
                    raise
                raise ProjectError(kind + "_failed", str(exc)[:500]) from exc
        finally:
            lease.close()

    if not background:
        return execute()
    worker = threading.Thread(target=execute, name=f"atme-{kind}-{project_id}-{run_id}", daemon=False)
    try:
        with store._lock:
            owner._workers = {key: thread for key, thread in owner._workers.items() if thread.is_alive()}
            owner._workers[run_id] = worker
            worker.start()
    except Exception as exc:
        try:
            fail(exc)
        finally:
            lease.close()
        raise ProjectError(kind + "_failed", "Could not start the local worker") from exc
    return owner.status(project_id, run_id)
