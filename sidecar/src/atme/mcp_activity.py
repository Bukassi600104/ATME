"""Shared MCP session and activity state for the desktop studio.

Each stdio server owns a logical session ID and periodically updates its heartbeat.
The data lives beside project state so the independently running HTTP sidecar can
report it without coupling either transport to a process ID.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
from uuid import uuid4

log = logging.getLogger(__name__)

ACTIVE_TTL_SECONDS = 30.0
RECENT_SESSION_LIMIT = 12


class LiveMcpSessions:
    """In-memory proof that an MCP process is talking to this desktop instance."""

    def __init__(self):
        self._sessions: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._changed = threading.Condition(self._lock)
        self._version = 0

    def update(self, payload: dict) -> dict:
        session_id = payload.get("session_id")
        event = payload.get("event")
        if not isinstance(session_id, str) or len(session_id) != 32:
            raise ValueError("invalid MCP session")
        if event not in {"connected", "heartbeat", "identified", "activity", "disconnected"}:
            raise ValueError("invalid MCP event")
        now = time.time()
        with self._lock:
            item = self._sessions.setdefault(session_id, {
                "session_id": session_id, "transport": "stdio", "started_at": now,
                "client_name": None, "client_version": None, "last_activity_at": None,
                "last_tool": None, "last_project_id": None, "call_count": 0,
                "ended_at": None,
            })
            item["last_seen_at"] = now
            if payload.get("client_name"):
                item["client_name"] = str(payload["client_name"])[:120]
                item["client_version"] = str(payload.get("client_version") or "")[:60] or None
            if event == "activity":
                item["last_activity_at"] = now
                item["last_tool"] = str(payload.get("tool") or "")[:160] or None
                project_id = payload.get("project_id")
                item["last_project_id"] = project_id if type(project_id) is int else None
                item["call_count"] += 1
            item["ended_at"] = now if event == "disconnected" else None
            self._version += 1
            self._changed.notify_all()
        return {"accepted": True, "session_id": session_id}

    def wait(self, after: int, timeout_seconds: float = 25.0) -> dict:
        with self._changed:
            if self._version <= after:
                self._changed.wait(timeout_seconds)
        return self.snapshot()

    def snapshot(self, now: float | None = None) -> dict:
        observed_at = time.time() if now is None else now
        cutoff = observed_at - ACTIVE_TTL_SECONDS
        with self._lock:
            sessions = [dict(item) for item in self._sessions.values()]
        sessions.sort(key=lambda item: item.get("last_activity_at") or item["last_seen_at"], reverse=True)
        sessions = sessions[:RECENT_SESSION_LIMIT]
        for item in sessions:
            item["active"] = item["ended_at"] is None and item["last_seen_at"] >= cutoff
            item["client_identity"] = McpActivity._identity(item["client_name"], item["client_version"])
        active = [item for item in sessions if item["active"]]
        identities = sorted({item["client_identity"] for item in active if item["client_identity"]})
        latest = next((item for item in sessions if item["last_activity_at"] is not None), None)
        projects = []
        for item in sessions:
            project_id = item["last_project_id"]
            if project_id is not None and project_id not in projects:
                projects.append(project_id)
        return {"active": bool(active), "active_session_count": len(active),
                "client_identities": identities, "identity_available": bool(identities),
                "last_activity_at": latest["last_activity_at"] if latest else None,
                "last_tool": latest["last_tool"] if latest else None,
                "last_project_id": latest["last_project_id"] if latest else None,
                "recent_project_ids": projects, "sessions": sessions,
                "connection_evidence": "live_desktop_bridge", "version": self._version}


class McpActivity:
    def __init__(self, store, session_id: str | None = None,
                 client_name: str | None = None, client_version: str | None = None,
                 bridge=None):
        self.store = store
        self.session_id = session_id or uuid4().hex
        self.client_name = client_name.strip() if client_name else None
        self.client_version = client_version.strip() if client_version else None
        self.bridge = bridge
        with store._tx() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS mcp_client_sessions (
                    session_id TEXT PRIMARY KEY,
                    transport TEXT NOT NULL,
                    client_name TEXT,
                    client_version TEXT,
                    started_at REAL NOT NULL,
                    last_seen_at REAL NOT NULL,
                    last_activity_at REAL,
                    last_tool TEXT,
                    last_project_id INTEGER,
                    call_count INTEGER NOT NULL DEFAULT 0,
                    ended_at REAL);
                CREATE INDEX IF NOT EXISTS idx_mcp_sessions_last_seen
                    ON mcp_client_sessions(last_seen_at DESC);
            """)

    def start(self) -> None:
        now = time.time()
        self._write("""
            INSERT INTO mcp_client_sessions(
                session_id,transport,client_name,client_version,started_at,last_seen_at,ended_at)
            VALUES(?,?,?,?,?,?,NULL)
            ON CONFLICT(session_id) DO UPDATE SET
                transport=excluded.transport,
                client_name=excluded.client_name,
                client_version=excluded.client_version,
                started_at=excluded.started_at,
                last_seen_at=excluded.last_seen_at,
                last_activity_at=NULL,
                last_tool=NULL,
                last_project_id=NULL,
                call_count=0,
                ended_at=NULL
        """, (self.session_id, "stdio", self.client_name, self.client_version, now, now))
        self._bridge("connected")

    def heartbeat(self) -> None:
        self._write(
            "UPDATE mcp_client_sessions SET last_seen_at=? WHERE session_id=? AND ended_at IS NULL",
            (time.time(), self.session_id))
        self._bridge("heartbeat")

    def record(self, tool: str, project_id: int | None = None) -> None:
        now = time.time()
        self._write("""
            UPDATE mcp_client_sessions
            SET last_seen_at=?, last_activity_at=?, last_tool=?, last_project_id=?,
                call_count=call_count+1
            WHERE session_id=? AND ended_at IS NULL
        """, (now, now, tool, project_id, self.session_id))
        self._bridge("activity", tool=tool, project_id=project_id)

    def identify(self, name: str | None, version: str | None = None) -> None:
        """Persist only identity declared by the MCP initialize handshake."""
        if not name:
            return
        self.client_name = name.strip()
        self.client_version = version.strip() if version else None
        self._write("UPDATE mcp_client_sessions SET client_name=?,client_version=?,last_seen_at=? "
                    "WHERE session_id=? AND ended_at IS NULL",
                    (self.client_name, self.client_version, time.time(), self.session_id))
        self._bridge("identified", client_name=self.client_name,
                     client_version=self.client_version)

    def stop(self) -> None:
        now = time.time()
        self._write(
            "UPDATE mcp_client_sessions SET last_seen_at=?, ended_at=? WHERE session_id=?",
            (now, now, self.session_id))
        self._bridge("disconnected")

    def _bridge(self, event: str, **values) -> None:
        if self.bridge is not None:
            values.setdefault("client_name", self.client_name)
            values.setdefault("client_version", self.client_version)
            self.bridge.send(event, **values)

    def snapshot(self, now: float | None = None) -> dict:
        observed_at = time.time() if now is None else now
        cutoff = observed_at - ACTIVE_TTL_SECONDS
        with self.store._lock:
            rows = self.store.conn.execute("""
                SELECT session_id,transport,client_name,client_version,started_at,last_seen_at,
                       last_activity_at,last_tool,last_project_id,call_count,ended_at
                FROM mcp_client_sessions
                ORDER BY COALESCE(last_activity_at,last_seen_at) DESC
                LIMIT ?
            """, (RECENT_SESSION_LIMIT,)).fetchall()
        sessions = []
        for row in rows:
            item = dict(row)
            item["active"] = item["ended_at"] is None and item["last_seen_at"] >= cutoff
            item["client_identity"] = self._identity(item["client_name"], item["client_version"])
            sessions.append(item)
        active = [item for item in sessions if item["active"]]
        latest_activity = max(
            (item for item in sessions if item["last_activity_at"] is not None),
            key=lambda item: item["last_activity_at"], default=None)
        recent_project_ids = []
        for item in sessions:
            project_id = item["last_project_id"]
            if project_id is not None and project_id not in recent_project_ids:
                recent_project_ids.append(project_id)
        identities = sorted({item["client_identity"] for item in active if item["client_identity"]})
        return {
            "active": bool(active),
            "active_session_count": len(active),
            "client_identities": identities,
            "identity_available": bool(identities),
            "last_activity_at": latest_activity["last_activity_at"] if latest_activity else None,
            "last_tool": latest_activity["last_tool"] if latest_activity else None,
            "last_project_id": latest_activity["last_project_id"] if latest_activity else None,
            "recent_project_ids": recent_project_ids,
            "sessions": sessions,
        }

    @staticmethod
    def _identity(name: str | None, version: str | None) -> str | None:
        if not name:
            return None
        return f"{name} {version}" if version else name

    def _write(self, sql: str, params: tuple) -> None:
        try:
            with self.store._tx() as conn:
                conn.execute(sql, params)
        except sqlite3.Error as exc:
            # Activity telemetry must never break a valid project operation.
            log.warning("Could not persist MCP activity: %s", exc)


class McpHeartbeat:
    def __init__(self, activity: McpActivity, interval_seconds: float = 10.0):
        self.activity = activity
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="atme-mcp-heartbeat", daemon=True)

    def start(self) -> None:
        self.activity.start()
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=max(1.0, self.interval_seconds + 1.0))
        self.activity.stop()

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            self.activity.heartbeat()
