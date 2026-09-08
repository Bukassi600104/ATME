"""Smoke variant that reports netstat for the child pid while healthz is failing."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

EXE = Path("sidecar-dist/atme-sidecar/atme-sidecar.exe")
OUT_LOG = Path("packaged-exe-out.txt")


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = int(s.getsockname()[1])
    s.close()
    return p


def main() -> int:
    port = free_port()
    env = dict(os.environ)
    env["ATME_PORT"] = str(port)
    env["ATME_TOKEN"] = "smoke-token"

    out_fh = open(OUT_LOG, "w", encoding="utf-8")
    proc = subprocess.Popen([str(EXE)], cwd=".", env=env,
                            stdout=out_fh, stderr=subprocess.STDOUT)
    print("pid", proc.pid, "expected port", port)

    for attempt in range(8):
        time.sleep(3)
        alive = proc.poll() is None
        ns = subprocess.run(["netstat", "-ano", "-p", "TCP"],
                            capture_output=True, text=True).stdout
        lines = [l for l in ns.splitlines()
                 if l.strip().endswith(str(proc.pid)) or f":{port} " in l]
        print("t=%2ds alive=%s listening-lines=%s" % ((attempt + 1) * 3, alive, lines))
        if not alive:
            break
        try:
            with urllib.request.urlopen(
                    "http://127.0.0.1:%d/healthz" % port, timeout=2) as r:
                print("healthz!", r.read())
                break
        except Exception as e:
            print("  still refusing:", type(e).__name__)
    try:
        proc.kill()
    except Exception:
        pass
    out_fh.close()
    print("--- exe output ---")
    print(OUT_LOG.read_text(encoding="utf-8")[:1200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
