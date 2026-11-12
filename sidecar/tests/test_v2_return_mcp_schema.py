"""Real stdio clients receive the new compiler schema from this source checkout."""

import asyncio
import sys
from copy import deepcopy
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters

ROOT = Path(__file__).resolve().parents[2]


def test_real_source_mcp_exposes_return_receipt_and_preserves_renderer_capability(tmp_path):
    from test_v2_resolved_project import stored_v2_basis

    service, project, _, _, timeline = stored_v2_basis(tmp_path, real_evidence=True)
    db_path = service.store.db_path
    service.store.close()
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "atme.mcp_server", "--database", str(db_path)],
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
            assert caps.structured_content["result"]["visual_contracts"]["renderer_versions"] == ["1", "2.0.0"]
            pid = project["project_id"]
            args = {"project_id": pid, "expected_revision": project["revision"]}
            async def read(tool, payload):
                value = await client.call_tool("atme." + tool, payload)
                assert not value.is_error, value.content
                return value.structured_content["result"]

            ctx = await read("get_visual_compilation_context", args)
            plan = (await read("get_project_artifact", {"project_id": pid, "kind": "storyboard"}))["document"]
            layout = (await read("get_project_artifact", {"project_id": pid, "kind": "layout"}))["document"]
            plan.update(ctx["project"], narrative_authority=ctx["narrative_authority"])
            state = await read("write_artifact", {**args, "kind": "storyboard", "document": plan})
            args["expected_revision"] = state["revision"]
            ctx = await read("get_visual_compilation_context", args)
            layout.update(ctx["layout_basis"])
            state = await read("write_artifact", {**args, "kind": "layout", "document": layout})
            args["expected_revision"] = state["revision"]
            ctx = await read("get_visual_compilation_context", args)
            timeline.update(ctx["resolved_basis"])
            del timeline["compilation_fingerprint"]
            mismatched = {**timeline, "plan_sha256": "0" * 64}
            rejected = await client.call_tool("atme.get_visual_compilation_context", {**args, "resolved_draft": mismatched})
            assert rejected.is_error
            sealed = await read("get_visual_compilation_context", {**args, "resolved_draft": timeline})
            timeline["compilation_fingerprint"] = sealed["compilation_fingerprint"]
            args["kind"] = "resolved_timeline"
            invalid = deepcopy(timeline)
            invalid["compilation_fingerprint"] = "0" * 64
            rejected = await client.call_tool("atme.write_artifact", {**args, "document": invalid})
            assert rejected.is_error
            stored = await client.call_tool("atme.write_artifact", {**args, "document": timeline})
            assert not stored.is_error
            preview = await client.call_tool("atme.preview_project", {
                "project_id": pid, "expected_revision": args["expected_revision"] + 1, "at_ms": 4900})
            assert not preview.is_error
            assert any(item.type == "image" for item in preview.content)

    asyncio.run(exercise())
