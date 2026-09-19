"""Live bridge between a stdio MCP process and the running ATME desktop sidecar."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path


def configured_data_dir() -> Path:
    """Resolve the same Windows project root used by the installed Tauri host."""
    override = os.environ.get("ATME_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\ATME") as key:
                value, _ = winreg.QueryValueEx(key, "ProjectDataDir")
                if str(value).strip():
                    return Path(value).expanduser().resolve()
        except OSError:
            pass
        return (Path(os.environ["APPDATA"]) / "dev.atme.engine").resolve()
    return (Path.home() / ".local" / "share" / "dev.atme.engine").resolve()


def configured_database() -> Path:
    return configured_data_dir() / "jobs" / "jobs.db"


class DesktopMcpBridge:
    """Authenticated best-effort telemetry to the currently running desktop instance."""

    def __init__(self, data_dir: Path, session_id: str):
        self.runtime_file = data_dir / "runtime" / "desktop.json"
        self.session_id = session_id

    def send(self, event: str, **values) -> bool:
        try:
            runtime = json.loads(self.runtime_file.read_text(encoding="utf-8"))
            if int(runtime.get("pid", 0)) <= 0 or not runtime.get("token"):
                return False
            payload = json.dumps({
                "session_id": self.session_id,
                "event": event,
                "observed_at": time.time(),
                **values,
            }).encode("utf-8")
            request = urllib.request.Request(
                f"http://127.0.0.1:{int(runtime['port'])}/mcp/live",
                data=payload,
                method="POST",
                headers={"Authorization": f"Bearer {runtime['token']}",
                         "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=1.5) as response:
                return response.status == 200
        except (OSError, ValueError, KeyError, urllib.error.URLError):
            return False
