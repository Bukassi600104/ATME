"""Reproduce the server worker path outside pytest: thread + orchestrator + store.

Prints a heartbeat from both threads so a deadlock is visible within ~240s.
"""

from __future__ import annotations

import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, "sidecar/src")

from atme.orchestrator import Orchestrator  # noqa: E402

stop = threading.Event()


def heartbeat(tag):
    while not stop.is_set():
        print("[hb:" + tag + "] alive " + time.strftime("%H:%M:%S"), flush=True)
        time.sleep(10)


def main():
    tmp = Path(tempfile.mkdtemp())
    orch = Orchestrator(tmp / "jobs.db")
    job = orch.submit_topic("Why inference is hard", provider="fake", review_gate=False)
    print("submitted", job, flush=True)

    threading.Thread(target=heartbeat, args=("main",), daemon=True).start()

    box = {}

    def worker():
        try:
            box["result"] = orch.run_job(job)
            print("[worker] DONE", flush=True)
        except Exception as exc:
            print("[worker] FAILED", type(exc).__name__, str(exc)[:200], flush=True)
            box["error"] = str(exc)
        finally:
            stop.set()

    threading.Thread(target=heartbeat, args=("worker",), daemon=True).start()
    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout=240)
    if t.is_alive():
        print("WORKER STILL ALIVE AFTER 240s -> hang confirmed", flush=True)
        return 2
    print("result:", box.get("result", box.get("error")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
