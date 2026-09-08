"""SQLite job store (plan S2): jobs, stages, artifacts, events, llm_usage.

Resume semantics: a stage is DONE only when its artifact row exists AND status='done'.
The orchestrator resumes at the first non-done stage; render checkpoints subdivide further.

Threading: constructed on the host thread, driven from API + worker threads -> connection uses
check_same_thread=False and EVERY access serializes through one re-entrant lock. WAL stays OFF:
on this HDD our small-write pattern loses more to -wal churn than it gains.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    topic TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'running',
    settings_json TEXT NOT NULL DEFAULT '{}');

CREATE TABLE IF NOT EXISTS stages (
    job_id INTEGER NOT NULL REFERENCES jobs(id),
    name TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    started_at REAL,
    ended_at REAL,
    PRIMARY KEY (job_id, name, attempt));

CREATE TABLE IF NOT EXISTS artifacts (
    job_id INTEGER NOT NULL REFERENCES jobs(id),
    stage TEXT NOT NULL,
    kind TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    bytes INTEGER NOT NULL,
    created_at REAL NOT NULL,
    id INTEGER PRIMARY KEY AUTOINCREMENT);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id),
    ts REAL NOT NULL,
    level TEXT NOT NULL DEFAULT 'info',
    message TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS llm_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id),
    role TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL,
    attempt INTEGER NOT NULL DEFAULT 1,
    ok INTEGER NOT NULL DEFAULT 1,
    error TEXT,
    wall_ms INTEGER NOT NULL DEFAULT 0,
    ts REAL NOT NULL);
"""

STAGE_ORDER = [
    "created", "researched", "verified", "scripted", "reviewed",
    "laid_out", "voiced", "polished", "aligned",
    "rendered", "assembled",
]


class JobStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        with self._tx() as conn:
            conn.executescript(SCHEMA_V1)
            conn.execute("INSERT OR IGNORE INTO meta(key,value) VALUES('schema_version','1')")

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            yield self.conn
            self.conn.commit()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    # -- jobs -----------------------------------------------------------------
    def create_job(self, topic: str = "", title: str = "",
                   settings: dict | None = None) -> int:
        with self._tx() as conn:
            cur = conn.execute(
                "INSERT INTO jobs(created_at, topic, title, settings_json) VALUES(?,?,?,?)",
                (time.time(), topic, title, json.dumps(settings or {})))
            job_id = int(cur.lastrowid)
        self.log(job_id, "job created")
        return job_id

    def get_job(self, job_id: int) -> dict | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["settings"] = json.loads(d.pop("settings_json", "{}"))
        return d

    def set_job_status(self, job_id: int, status: str) -> None:
        with self._tx() as conn:
            conn.execute("UPDATE jobs SET status=? WHERE id=?", (status, job_id))

    def set_job_title(self, job_id: int, title: str) -> None:
        with self._tx() as conn:
            conn.execute("UPDATE jobs SET title=? WHERE id=?", (title, job_id))

    def update_job_settings(self, job_id: int, updates: dict) -> None:
        job = self.get_job(job_id)
        if not job:
            raise KeyError("job %s not found" % job_id)
        settings = {**job["settings"], **updates}
        with self._tx() as conn:
            conn.execute("UPDATE jobs SET settings_json=? WHERE id=?",
                         (json.dumps(settings), job_id))

    def reset_from_stage(self, job_id: int, stage: str) -> None:
        if stage not in STAGE_ORDER:
            raise ValueError("unknown stage %s" % stage)
        names = STAGE_ORDER[STAGE_ORDER.index(stage):]
        with self._tx() as conn:
            marks = ",".join("?" for _ in names)
            for name in names:
                row = conn.execute(
                    "SELECT COALESCE(MAX(attempt),0) AS attempt FROM stages "
                    "WHERE job_id=? AND name=?", (job_id, name)).fetchone()
                conn.execute(
                    "INSERT INTO stages(job_id,name,attempt,status) VALUES(?,?,?,'pending')",
                    (job_id, name, int(row["attempt"]) + 1))
            conn.execute(
                "DELETE FROM artifacts WHERE job_id=? AND stage IN (%s)" % marks,
                (job_id, *names))

    # -- stages ---------------------------------------------------------------
    def ensure_stage(self, job_id: int, name: str) -> None:
        with self._tx() as conn:
            conn.execute("INSERT OR IGNORE INTO stages(job_id,name,status) VALUES(?,?,'pending')",
                         (job_id, name))

    def start_stage(self, job_id: int, name: str, attempt: int = 1) -> None:
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO stages(job_id,name,attempt,status,started_at) "
                "VALUES(?,?,?,'running',?) "
                "ON CONFLICT(job_id,name,attempt) DO UPDATE SET "
                "status='running', started_at=excluded.started_at",
                (job_id, name, attempt, time.time()))
        self.log(job_id, "stage %s started (attempt %d)" % (name, attempt))

    def finish_stage(self, job_id: int, name: str, ok: bool = True,
                     error: str | None = None, attempt: int = 1) -> None:
        status = "done" if ok else "failed"
        msg = ("stage %s done" % name if ok
               else "stage %s FAILED: %s" % (name, error or ""))
        with self._tx() as conn:
            conn.execute(
                "UPDATE stages SET status=?, ended_at=?, error=? "
                "WHERE job_id=? AND name=? AND attempt=?",
                (status, time.time(), error, job_id, name, attempt))
            level = "info" if ok else "error"
            conn.execute("INSERT INTO events(job_id,ts,level,message) VALUES(?,?,?,?)",
                         (job_id, time.time(), level, msg))
        if not ok:
            self.set_job_status(job_id, "failed")

    def resume_point(self, job_id: int) -> tuple[str, list[str]]:
        """Return (first_incomplete_stage, done_stages)."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT name, status, attempt FROM stages WHERE job_id=? "
                "ORDER BY name, attempt",
                (job_id,)).fetchall()
        latest: dict[str, str] = {}
        for r in rows:
            latest[r["name"]] = r["status"]
        done = [n for n in STAGE_ORDER if latest.get(n) == "done"]
        for name in STAGE_ORDER:
            if name in done:
                continue
            if latest.get(name) == "failed":
                return name, sorted(done)
            return name, sorted(done)
        return "assembled", sorted(done)

    # -- artifacts ------------------------------------------------------------
    def attach_artifact(self, job_id: int, stage: str, kind: str, path: str,
                        sha256: str, bytes_: int) -> None:
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO artifacts(job_id,stage,kind,path,sha256,bytes,created_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (job_id, stage, kind, path, sha256, bytes_, time.time()))

    def artifacts_for(self, job_id: int, stage: str | None = None) -> list[dict]:
        with self._lock:
            if stage:
                rows = self.conn.execute(
                    "SELECT * FROM artifacts WHERE job_id=? AND stage=?",
                    (job_id, stage)).fetchall()
            else:
                rows = self.conn.execute(
                    "SELECT * FROM artifacts WHERE job_id=?", (job_id,)).fetchall()
        return [dict(r) for r in rows]

    # -- events / usage -------------------------------------------------------
    def log(self, job_id: int, message: str, level: str = "info") -> None:
        with self._tx() as conn:
            conn.execute("INSERT INTO events(job_id,ts,level,message) VALUES(?,?,?,?)",
                         (job_id, time.time(), level, message))

    def record_usage(self, job_id: int, entry: Any) -> None:
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO llm_usage(job_id,role,model,prompt_tokens,completion_tokens,"
                "cost_usd,attempt,ok,error,wall_ms,ts) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (job_id, entry.role, entry.model, entry.prompt_tokens,
                 entry.completion_tokens, entry.cost_usd, entry.attempt,
                 1 if entry.ok else 0, entry.error, entry.wall_ms, time.time()))
