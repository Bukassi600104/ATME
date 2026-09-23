"""Smoke the PACKAGED sidecar exe: env contract -> healthz -> auth -> shutdown -> no orphan."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

EXE = Path("sidecar-dist/atme-sidecar/atme-sidecar.exe")
OUT_LOG = Path("packaged-exe-out.txt")
DATA_DIR = Path(".packaged-smoke-data").resolve()


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return int(port)


def main() -> int:
    if not EXE.exists():
        print("exe missing - run app/sync-sidecar.ps1 first")
        return 2

    port = free_port()
    env = dict(os.environ)
    env["ATME_PORT"] = str(port)
    env["ATME_TOKEN"] = "smoke-token"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    env["ATME_DATA_DIR"] = str(DATA_DIR)
    env["ATME_MODEL_DIR"] = str(DATA_DIR / "models")

    # The handle intentionally stays open for the child process lifetime and
    # is closed in the unconditional cleanup below.
    out_fh = OUT_LOG.open("w", encoding="utf-8")
    proc = subprocess.Popen([str(EXE), "--port", str(port), "--token", "smoke-token"],
                            stdout=out_fh, stderr=subprocess.STDOUT, env=env)
    print("spawned pid", proc.pid)

    base = f"http://127.0.0.1:{port}"
    ok = True
    try:
        hbody = None
        deadline = time.time() + 150
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(base + "/healthz", timeout=3) as r:
                    hbody = json.loads(r.read())
                    break
            except Exception:  # noqa: BLE001 - bounded readiness polling
                time.sleep(0.4)
        if not hbody:
            raise RuntimeError("healthz never came up")
        ok = ok and hbody.get("status") == "ok"
        print("healthz:", hbody)

        auth = {"Authorization": "Bearer smoke-token"}
        req = urllib.request.Request(base + "/settings/providers", headers=auth)
        with urllib.request.urlopen(req, timeout=5) as r:
            providers = json.loads(r.read())
        zero_key = providers == {
            "configured": False, "roles": {}, "mode": "external", "api_keys_required": False,
        }
        print("external-AI mode:", providers)
        ok = ok and zero_key

        # Provider writes and internal topic generation must remain retired in
        # the packaged binary. These checks catch accidental reachability of
        # migration-era provider code without making a network/model call.
        req = urllib.request.Request(
            base + "/settings/providers", method="PUT", data=b"{}",
            headers={**auth, "Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(req, timeout=5)
            provider_write_code = 200
        except urllib.error.HTTPError as e:
            provider_write_code = e.code
        print("provider configuration write:", provider_write_code)
        ok = ok and provider_write_code == 410

        req = urllib.request.Request(
            base + "/jobs", method="POST", data=b"{}",
            headers={**auth, "Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(req, timeout=5)
            internal_job_code = 200
        except urllib.error.HTTPError as e:
            internal_job_code = e.code
        print("internal topic-generation job:", internal_job_code)
        ok = ok and internal_job_code == 410

        # auth: unauthenticated POST must be 401
        req = urllib.request.Request(base + "/jobs", method="POST",
                                     data=b"{}", headers={"Content-Type": "application/json"})
        code = None
        try:
            urllib.request.urlopen(req, timeout=5)
            code = 200
        except urllib.error.HTTPError as e:
            code = e.code
        print("unauthenticated POST /jobs:", code)
        ok = ok and code == 401

        # graceful shutdown
        req = urllib.request.Request(base + "/shutdown", method="POST",
                                     headers=auth)
        with urllib.request.urlopen(req, timeout=5) as r:
            print("shutdown accepted:", r.status)
    finally:
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
            print("process had to be force-killed")
        out_fh.close()
        print("--- exe output ---")
        print(OUT_LOG.read_text(encoding="utf-8")[:1500])

    alive_after = proc.poll() is None
    print("orphan after shutdown:", alive_after)
    return 0 if (ok and not alive_after) else 1


if __name__ == "__main__":
    raise SystemExit(main())
