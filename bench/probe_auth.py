"""Live probe: which status does each route give with/without auth on a real server?"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, "sidecar/src")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def call(base, method, path, token=None, body=None):
    req = urllib.request.Request(base + path, method=method)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    if data:
        req.data = data
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def main():
    port = free_port()
    env_cmd = [
        ".\sidecar\.venv\Scripts\python.exe", "-u", "-m", "atme.server",
        "--port", str(port), "--token", "T"]
    proc = subprocess.Popen(env_cmd, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            cwd=".")
    base = "http://127.0.0.1:%d" % port
    # wait healthz
    for _ in range(100):
        try:
            if call(base, "GET", "/healthz") == 200:
                break
        except Exception:
            pass
        time.sleep(0.3)

    checks = [
        ("GET", "/healthz", None),
        ("GET", "/jobs/1", None),
        ("POST", "/jobs", {"topic": ""}),
        ("GET", "/jobs", None),
        ("GET", "/999999/script", None),
    ]
    for method, path, body in checks:
        noauth = call(base, method, path, body=body)
        auth = call(base, method, path, token="T", body=body)
        print("%-6s %-22s noauth=%s auth=%s" % (method, path, noauth, auth))
    proc.terminate()
    proc.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
