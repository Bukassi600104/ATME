"""Env-passing probe against the SOURCE launcher (not packaged)."""

import os
import socket
import subprocess
import sys
import time
import urllib.request

py = "sidecar/.venv/Scripts/python.exe"

s = socket.socket()
s.bind(("127.0.0.1", 0))
port = s.getsockname()[1]
s.close()

env = dict(os.environ)
env["ATME_PORT"] = str(port)
env["ATME_TOKEN"] = "probe"

proc = subprocess.Popen([py, "-u", "sidecar/launcher.py"], cwd=".", env=env,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

deadline = time.time() + 60
ok = False
while time.time() < deadline:
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/healthz" % port, timeout=2):
            ok = True
            break
    except Exception:
        time.sleep(0.5)

print("healthz on expected port:", ok)
try:
    proc.kill()
except Exception:
    pass
sys.exit(0 if ok else 1)