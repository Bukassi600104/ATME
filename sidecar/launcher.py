"""PyInstaller entrypoint for the ATME sidecar server."""

import sys

from atme.parent_watch import start_parent_watchdog

start_parent_watchdog()

from atme.server.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
