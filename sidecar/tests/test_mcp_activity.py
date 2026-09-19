import time

from test_server_controls import _client

from atme.mcp_activity import ACTIVE_TTL_SECONDS, McpActivity
from atme.project_service import ProjectService
from atme.store.db import JobStore


def test_activity_tracks_multiple_logical_sessions_and_real_identity(tmp_path):
    database = tmp_path / "activity.db"
    store = JobStore(database)
    other_store = JobStore(database)
    anonymous = McpActivity(store, session_id="anonymous")
    identified = McpActivity(other_store, session_id="identified",
                             client_name="Test Client", client_version="1.2")
    anonymous.start()
    identified.start()
    anonymous.record("atme.list_projects")
    identified.record("atme.write_artifact", 42)

    status = anonymous.snapshot()
    assert status["active"] is True
    assert status["active_session_count"] == 2
    assert status["client_identities"] == ["Test Client 1.2"]
    assert status["identity_available"] is True
    assert status["last_tool"] == "atme.write_artifact"
    assert status["last_project_id"] == 42
    assert status["recent_project_ids"] == [42]

    identified.stop()
    status = anonymous.snapshot()
    assert status["active_session_count"] == 1
    assert status["client_identities"] == []
    anonymous.stop()
    other_store.close()
    store.close()


def test_stale_crashed_session_degrades_to_inactive(tmp_path):
    store = JobStore(tmp_path / "stale.db")
    activity = McpActivity(store, session_id="crashed")
    activity.start()
    with store._tx() as conn:
        conn.execute("UPDATE mcp_client_sessions SET last_seen_at=? WHERE session_id=?",
                     (time.time() - ACTIVE_TTL_SECONDS - 1, "crashed"))
    status = activity.snapshot()
    assert status["active"] is False
    assert status["active_session_count"] == 0
    store.close()


def test_studio_sync_reports_project_version_and_live_desktop_mcp_activity(tmp_path):
    client, orch, headers = _client(tmp_path)
    initial = client.get("/studio/sync", headers=headers)
    assert initial.status_code == 200
    assert initial.json()["project_version"] == ""
    session_id = "a" * 32
    connected = client.post("/mcp/live", headers=headers, json={
        "session_id": session_id, "event": "connected", "client_name": "Codex",
        "client_version": "1.0"})
    assert connected.status_code == 200
    activity_event = client.post("/mcp/live", headers=headers, json={
        "session_id": session_id, "event": "activity", "client_name": "Codex",
        "client_version": "1.0", "tool": "atme.create_project", "project_id": 1})
    assert activity_event.status_code == 200
    project = ProjectService(orch.store).create("Synced", "SHORT_FORM_9_16", "idea-first")

    changed = client.get("/studio/sync", headers=headers).json()
    assert changed["project_version"] == f"{project['project_id']}:0"
    assert changed["mcp"]["active"] is True
    assert changed["mcp"]["last_tool"] == "atme.create_project"
    assert changed["mcp"]["last_project_id"] == 1
    assert changed["mcp"]["client_identities"] == ["Codex 1.0"]
    assert changed["mcp"]["connection_evidence"] == "live_desktop_bridge"
    disconnected = client.post("/mcp/live", headers=headers, json={
        "session_id": session_id, "event": "disconnected"})
    assert disconnected.status_code == 200
    assert client.get("/studio/sync", headers=headers).json()["mcp"]["active"] is False
    client.close()
    orch.store.close()


def test_database_activity_alone_does_not_claim_live_desktop_connection(tmp_path):
    client, orch, headers = _client(tmp_path)
    activity = McpActivity(orch.store, session_id="database-only")
    activity.start()
    activity.record("atme.list_projects")
    status = client.get("/studio/sync", headers=headers).json()["mcp"]
    assert status["active"] is False
    assert status["connection_evidence"] == "live_desktop_bridge"
    activity.stop()
    client.close()
    orch.store.close()
