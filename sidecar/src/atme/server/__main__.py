"""python -m atme.server --port 0 --token XXX

Binds 127.0.0.1 only. Port/token arrive from the Tauri host; port 0 picks an ephemeral one and
prints the chosen port on stdout so hosts that need to learn it can parse the line "PORT=<n>".
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import socket
from pathlib import Path

import uvicorn

from atme.server.app import create_app


def main() -> int:
    parser = argparse.ArgumentParser(prog="atme-server")
    parser.add_argument("--host", default=os.environ.get("ATME_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("ATME_PORT", "0")))
    parser.add_argument("--token", default=os.environ.get("ATME_TOKEN", "dev-token"))
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    from atme.parent_watch import start_parent_watchdog

    start_parent_watchdog()

    from atme import warmup

    warmup.warm_heavy_imports()

    from atme.orchestrator import Orchestrator

    data_root = Path(os.environ.get("ATME_DATA_DIR", "data")).resolve()
    data_root.mkdir(parents=True, exist_ok=True)
    # Legacy credentials remain on disk, but production no longer opens a key store.
    orchestrator = Orchestrator(data_root / "jobs" / "jobs.db", data_root=data_root)
    app = create_app(token=args.token, orchestrator=orchestrator)
    if args.port == 0:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((args.host, 0))
            args.port = s.getsockname()[1]
    print(json.dumps({"event": "ready", "PORT": args.port}), flush=True)

    config = uvicorn.Config(app, host=args.host, port=args.port, log_level="warning")
    server = uvicorn.Server(config)
    app.state.uvicorn_server = server   # /shutdown flips should_exit on this
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
