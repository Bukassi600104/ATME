"""Real stdio clients receive the new compiler schema from this source checkout."""

import asyncio
import sys
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters

ROOT = Path(__file__).resolve().parents[2]


def test_real_source_mcp_exposes_return_receipt_and_preserves_renderer_capability(tmp_path):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "atme.mcp_server", "--database", str(tmp_path / "return-receipt.db")],
        cwd=ROOT / "sidecar", env={"PYTHONPATH": str(ROOT / "sidecar/src")},
    )

    async def exercise():
        async with Client(params, read_timeout_seconds=30) as client:
            result = await client.call_tool("atme.get_schema", {"kind": "resolved_timeline", "version": "2.0.0"})
            assert not result.is_error
            schema = result.structured_content["result"]
            assert "ReturnHierarchyReceipt" in schema["$defs"]
            assert "return_hierarchy_receipt" in schema["$defs"]["ResolvedAction"]["properties"]
            for kind in ("storyboard", "layout"):
                result = await client.call_tool("atme.get_schema", {"kind": kind, "version": "2.0.0"})
                assert not result.is_error
                assert "ReturnHierarchyReceipt" not in result.structured_content["result"]["$defs"]
            caps = await client.call_tool("atme.get_capabilities", {})
            assert caps.structured_content["result"]["visual_contracts"]["renderer_versions"] == ["1"]

    asyncio.run(exercise())
