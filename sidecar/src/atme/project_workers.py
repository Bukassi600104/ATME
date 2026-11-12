"""Claim one timing or export snapshot across desktop and MCP processes."""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from contextlib import closing

from atme.project_service import ProjectError
from atme.store.db import database_busy


# Only internal constants select table and column names.
_RUNS = {"render": ("project_render_runs", "manifest", "fingerprint"),
         "timing": ("project_timing_runs", "document", "source_fingerprint")}


def _worker_path(database, kind, project_id, run_id):
    return database.parent / (database.name + ".workers") / kind / str(project_id) / run_id


def _lease(database, kind, project_id, run_id):
    path = _worker_path(database, kind, project_id, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    # SQLite's OS lock also releases when Windows terminates the worker process.
    lease = sqlite3.connect(path.with_suffix(".lock"), timeout=0, check_same_thread=False)
    try:
        lease.execute("BEGIN IMMEDIATE")
    except sqlite3.Error as exc:
        lease.close()
        if getattr(exc, "sqlite_errorcode", None) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            return None
        raise
    return lease


def _restore_result(connection, table, document, receipt, keys):
    if not receipt.is_file():
        return False
    payload = receipt.read_text(encoding="utf-8")
    connection.execute(f"UPDATE {table} SET status='done',{document}=?,error=NULL,updated_at=? "
                       "WHERE job_id=? AND run_id=? AND status IN ('queued','running')",
                       (payload, time.time(), *keys))
    return True


def mark_interrupted(store, kind, project_id, run_id):
    """Called only when a saved row says queued/running. Recheck under ownership."""
    table, document, _ = _RUNS[kind]
    receipt = _worker_path(store.db_path, kind, project_id, run_id).with_suffix(".result")
    lease = None
    try:
        # A poll takes the DB lock before the lease, just as a submission does.
        # It can return the observed active status immediately while another client writes.
        with closing(sqlite3.connect(store.db_path, timeout=0)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            lease = _lease(store.db_path, kind, project_id, run_id)
            if lease is None:
                return False
            restored = _restore_result(connection, table, document, receipt, (project_id, run_id))
            if not restored:
                connection.execute(
                    f"UPDATE {table} SET status='failed',error=?,updated_at=? "
                    "WHERE job_id=? AND run_id=? AND status IN ('queued','running')",
                    ("The worker stopped before completion. Request the operation again to resume.",
                     time.time(), project_id, run_id))
        if restored:
            receipt.unlink(missing_ok=True)
    except sqlite3.OperationalError as exc:
        if database_busy(exc):
            return False
        raise
    finally:
        if lease is not None:
            lease.close()
    return True


def submit(owner, kind, project_id, revision, snapshot, callback, background):
    store = owner.service.store
    table, document, fingerprint_key = _RUNS[kind]
    fingerprint = snapshot[fingerprint_key]
    run_id = fingerprint[:24]
    keys = (project_id, run_id)
    receipt = _worker_path(store.db_path, kind, *keys).with_suffix(".result")
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
            if row and row["status"] in ("queued", "running") and _restore_result(
                    store.conn, table, document, receipt, keys) and intact():
                lease.close()
                return owner.status(*keys)
            receipt.unlink(missing_ok=True)
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

    def persist(status, payload=None, error=None):
        # Workers only update their admitted row. Schema migrations belong to startup.
        with closing(sqlite3.connect(store.db_path, timeout=30)) as connection, connection:
            connection.execute(f"UPDATE {table} SET status=?,{document}=?,error=?,updated_at=? "
                               "WHERE job_id=? AND run_id=? AND status IN ('queued','running')",
                               (status, payload, error, time.time(), project_id, run_id))

    def execute():
        try:
            if background:
                persist("running")
            payload = json.dumps(callback(), allow_nan=False)
            pending = receipt.with_suffix(".pending")
            pending.write_text(payload, encoding="utf-8")
            os.replace(pending, receipt)
        except Exception as exc:
            logging.getLogger(__name__).exception("%s worker failed on project %s", kind, project_id)
            cause = exc.__cause__ if exc.__cause__ is not None else exc
            persist("failed", error=str(cause)[:2000])
            if not background:
                if isinstance(exc, ProjectError):
                    raise
                raise ProjectError(kind + "_failed", str(exc)[:500]) from exc
        else:
            try:
                persist("done", payload)
            except sqlite3.OperationalError:
                # A new status request can recover the finished result after the writer exits.
                logging.getLogger(__name__).exception("Saved %s result for project %s pending DB commit", kind, project_id)
            else:
                receipt.unlink(missing_ok=True)
        finally:
            lease.close()

    if not background:
        execute()
        return owner.status(*keys)
    try:
        worker = threading.Thread(target=execute, name=f"atme-{kind}-{project_id}-{run_id}", daemon=False)
        with store._lock:
            owner._workers = {key: thread for key, thread in owner._workers.items() if thread.is_alive()}
            owner._workers[run_id] = worker
            worker.start()
    except Exception as exc:
        try:
            persist("failed", error=str(exc)[:2000])
        finally:
            lease.close()
        raise ProjectError(kind + "_failed", "Could not start the local worker") from exc
    return owner.status(project_id, run_id)
