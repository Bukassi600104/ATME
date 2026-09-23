"""PyInstaller entrypoint for ATME HTTP service or local stdio MCP."""

import hashlib
import json
import sys

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--verify-style-bundle":
        from atme.render.style_bundle import (
            export_asset_matrix,
            load_bundle,
            preview_asset_matrix,
        )

        style, registry, _ = load_bundle()
        previews = {}
        for profile in style.aspects:
            preview = preview_asset_matrix(profile)
            if preview != export_asset_matrix(profile):
                raise RuntimeError("style preview/export proof differs")
            previews[profile] = hashlib.sha256(preview).hexdigest()
        print(json.dumps({"style_system_id": style.system_id,
                          "asset_registry_id": registry.registry_id,
                          "asset_count": len(registry.assets), "proof_sha256": previews},
                         sort_keys=True))
    elif len(sys.argv) > 1 and sys.argv[1] == "mcp":
        from atme.mcp_server import main

        main(sys.argv[2:])
    else:
        from atme.parent_watch import start_parent_watchdog

        start_parent_watchdog()
        from atme.server.__main__ import main

        sys.exit(main())
