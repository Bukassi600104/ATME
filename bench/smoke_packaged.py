"""Smoke the PACKAGED sidecar exe: env contract -> healthz -> auth -> shutdown -> no orphan."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
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

    out_fh = open(OUT_LOG, "w", encoding="utf-8")
    proc = subprocess.Popen([str(EXE), "--port", str(port), "--token", "smoke-token"],
                            stdout=out_fh, stderr=subprocess.STDOUT, env=env)
    print("spawned pid", proc.pid)

    base = "http://127.0.0.1:%d" % port
    ok = True
    try:
        hbody = None
        deadline = time.time() + 150
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(base + "/healthz", timeout=3) as r:
                    hbody = json.loads(r.read())
                    break
            except Exception:
                time.sleep(0.4)
        if not hbody:
            raise RuntimeError("healthz never came up")
        ok = ok and hbody.get("status") == "ok"
        print("healthz:", hbody)

        req = urllib.request.Request(
            base + "/settings/providers",
            headers={"Authorization": "Bearer smoke-token"},
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            providers = json.loads(r.read())
        roles = providers.get("roles", {})
        expected_models = {
            "researcher": "openrouter/perplexity/sonar-pro",
            "reasoner": "openrouter/openai/gpt-5.6-terra",
            "writer": "openrouter/openai/gpt-5.6-terra",
            "layouter": "openrouter/openai/gpt-5.6-luna",
        }
        models = {role: roles.get(role, {}).get("model") for role in expected_models}
        defaults_ok = models == expected_models and roles.get("researcher", {}).get("web_grounded") is True
        print("provider defaults:", models)
        print("researcher web grounded:", roles.get("researcher", {}).get("web_grounded"))
        ok = ok and defaults_ok

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
                                     headers={"Authorization": "Bearer smoke-token"})
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
