"""python -m atme.server --port 0 --token XXX

Binds 127.0.0.1 only. Port/token arrive from the Tauri host; port 0 picks an ephemeral one and
prints the chosen port on stdout so hosts that need to learn it can parse the line "PORT=<n>".
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import logging
import os
import socket
from pathlib import Path

import uvicorn

from atme.server.app import create_app


def _loopback(host: str) -> str:
    if host.lower() == "localhost":
        return "127.0.0.1"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is None or not address.is_loopback:
        raise argparse.ArgumentTypeError("ATME requires a local loopback address")
    return str(address)


def main() -> int:
    parser = argparse.ArgumentParser(prog="atme-server")
    parser.add_argument("--host", type=_loopback, default=os.environ.get("ATME_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("ATME_PORT", "0")))
    parser.add_argument("--token", default=os.environ.get("ATME_TOKEN", "dev-token"))
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    from atme.parent_watch import start_parent_watchdog

    start_parent_watchdog()

    # The media worker orders its DSP imports when a job begins. Project startup
    # must be able to serve the Studio before the first media operation.
    from atme.orchestrator import Orchestrator

    data_root = Path(os.environ.get("ATME_DATA_DIR", "data")).resolve()
    data_root.mkdir(parents=True, exist_ok=True)
    # Legacy credentials remain on disk, but production no longer opens a key store.
    orchestrator = Orchestrator(data_root / "jobs" / "jobs.db", data_root=data_root)
    app = create_app(token=args.token, orchestrator=orchestrator)
    family = socket.AF_INET6 if ":" in args.host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as listener:
        listener.bind((args.host, args.port))
        port = listener.getsockname()[1]
        config = uvicorn.Config(app, host=args.host, port=port, log_level="warning")
        server = uvicorn.Server(config)
        app.state.uvicorn_server = server   # /shutdown flips should_exit on this
        print(json.dumps({"event": "ready", "PORT": port}), flush=True)
        server.run(sockets=[listener])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
