import json
import asyncio
import os
import socket
import threading
import time
import urllib.request
from pathlib import Path
from unittest.mock import patch

from atme.orchestrator import Orchestrator
from atme.mcp_runtime import DesktopMcpBridge, configured_database
from atme.server.app import create_app
from mcp import Client
from mcp.client.stdio import StdioServerParameters
import uvicorn


def test_installed_mcp_resolves_database_from_current_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("ATME_DATA_DIR", str(tmp_path / "projects"))
    assert configured_database() == (tmp_path / "projects" / "jobs" / "jobs.db").resolve()


def test_desktop_bridge_uses_runtime_endpoint_not_project_database(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "desktop.json").write_text(json.dumps({
        "pid": 42, "port": 43210, "token": "secret"}), encoding="utf-8")
    response = type("Response", (), {"status": 200, "__enter__": lambda self: self,
                                     "__exit__": lambda *args: None})()
    with patch("urllib.request.urlopen", return_value=response) as opened:
        assert DesktopMcpBridge(tmp_path, "a" * 32).send("heartbeat") is True
    request = opened.call_args.args[0]
    assert request.full_url == "http://127.0.0.1:43210/mcp/live"
    assert request.headers["Authorization"] == "Bearer secret"


def test_real_stdio_handshake_is_reported_to_running_desktop_immediately(tmp_path):
    token = "live-test-token"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    database = tmp_path / "jobs" / "jobs.db"
    orch = Orchestrator(database, data_root=tmp_path)
    app = create_app(token, orch)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "desktop.json").write_text(json.dumps({
        "pid": os.getpid(), "port": port, "token": token}), encoding="utf-8")
    frozen_mcp = os.environ.get("ATME_FROZEN_MCP")
    params = StdioServerParameters(
        command=frozen_mcp or str(Path(os.sys.executable)),
        args=(["mcp", "--database", str(database)] if frozen_mcp else
              ["-m", "atme.mcp_server", "--database", str(database)]),
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "ATME_DATA_DIR": str(tmp_path)},
    )

    async def connect():
        async with Client(params, read_timeout_seconds=15) as client:
            await client.call_tool("atme.get_capabilities", {})
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/studio/sync",
                headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(request, timeout=3) as response:
                status = json.load(response)["mcp"]
            assert status["active"] is True
            assert status["connection_evidence"] == "live_desktop_bridge"
            assert status["identity_available"] is True

    try:
        asyncio.run(connect())
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        orch.store.close()
