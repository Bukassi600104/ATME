"""PyInstaller entrypoint for ATME HTTP service or local stdio MCP."""

import sys

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "mcp":
        from atme.mcp_server import main

        main(sys.argv[2:])
    else:
        from atme.parent_watch import start_parent_watchdog

        start_parent_watchdog()
        from atme.server.__main__ import main

        sys.exit(main())
