import asyncio
import os
import sys
from pathlib import Path

from atme.mcp_activity import McpActivity
from atme.project_service import ProjectService
from atme.store.db import JobStore
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from test_external_inputs import external_payload
from test_server_controls import _wav_bytes


def test_real_stdio_mcp_project_correction_and_persistence(tmp_path):
    database = tmp_path / "mcp-projects.db"
    frozen = os.environ.get("ATME_FROZEN_MCP")
    params = StdioServerParameters(
        command=frozen or sys.executable,
        args=(["mcp", "--database", str(database)] if frozen else
              ["-m", "atme.mcp_server", "--database", str(database)]),
        cwd=Path(__file__).resolve().parents[1])

    async def exercise():
        async with Client(params, read_timeout_seconds=30) as client:
            listed = await client.list_tools()
            names = {tool.name for tool in listed.tools}
            assert "atme.write_artifact" in names
            assert {"atme.render_project", "atme.preview_project", "atme.validate_project",
                    "atme.get_narrative_source", "atme.read_authoritative_audio",
                    "atme.get_source_timeline",
                    "atme.prepare_timing", "atme.get_timing_status",
                    "atme.get_render_status", "atme.set_output_profile",
                    "atme.list_revision_requests", "atme.apply_revision_request",
                    "atme.submit_revision_proposal", "atme.duplicate_project"} <= names
            assert "atme.list_project_assets" in names
            assert not names & {"atme.shell", "atme.read_file"}

            async def call(name, arguments=None, failed=False):
                result = await client.call_tool("atme." + name, arguments or {})
                assert result.is_error is failed, result.content
                return result.structured_content

            caps = (await call("get_capabilities"))["result"]
            assert caps["mcp_available"] and not caps["api_keys_required"]
            assert caps["render_available"] is True
            assert (await call("get_schema", {"kind": "script"}))["result"]["type"] == "object"
            project = (await call("create_project", {"title": "Actual MCP round trip",
                "profile": "LONG_FORM_16_9", "input_kind": "script-first"}))["result"]
            pid = project["project_id"]
            invalid = await call("write_artifact", {"project_id": pid, "kind": "script",
                "document": {}, "expected_revision": 0}, failed=True)
            assert invalid["error"]["code"] == "invalid_artifact" and invalid["error"]["errors"]
            assert (await call("get_project_state", {"project_id": pid}))["result"]["revision"] == 0
            payload = external_payload()
            await call("write_artifact", {"project_id": pid, "kind": "script",
                "document": payload["script"], "expected_revision": 0})
            await call("approve_script", {"project_id": pid, "script_revision": 1,
                "expected_revision": 1, "approved": True})
            written = (await call("write_artifact", {"project_id": pid, "kind": "layout",
                "document": payload["layout"], "expected_revision": 2}))["result"]
            assert written["approved_script_revision"] == 1
            layout = (await call("get_project_artifact", {"project_id": pid, "kind": "layout"}))["result"]
            assert layout["basis_script_revision"] == 1 and layout["stale"] is False
            conflict = await call("write_artifact", {"project_id": pid, "kind": "script",
                "document": payload["script"], "expected_revision": 0}, failed=True)
            assert conflict["error"]["code"] == "revision_conflict"
            assert len((await call("list_projects", {"limit": 1}))["result"]) == 1
            assert (await call("list_projects", {"before_id": pid}))["result"] == []
            invalid_type = await client.call_tool("atme.get_project_state", {"project_id": "../credentials"})
            assert invalid_type.is_error
            # A direct local upload becomes visible to the connected MCP process;
            # the recording is not sent through the AI client.
            from atme.orchestrator import Orchestrator
            from atme.server.app import create_app
            from fastapi.testclient import TestClient
            orch = Orchestrator(database, data_root=tmp_path)
            http = TestClient(create_app("local-test", orch))
            upload = http.post(f"/projects/{pid}/media/wav?expected_revision=3",
                headers={"Authorization": "Bearer local-test"}, content=_wav_bytes())
            assert upload.status_code == 200
            metadata = (await call("list_source_media", {"project_id": pid}))["result"]
            assert metadata[0]["duration_ms"] == 1200
            assert "relative_path" not in metadata[0]
            source_timeline = (await call("get_source_timeline", {"project_id": pid}))["result"]
            assert source_timeline["timeline_revision"] == 0 and source_timeline["document"]["clips"] == []
            placed = http.post(f"/projects/{pid}/source-timeline/commands",
                headers={"Authorization": "Bearer local-test"}, json={"operation":"insert",
                "arguments":{"media_id":metadata[0]["media_id"],"at_ms":0},"expected_revision":4,
                "expected_timeline_revision":0})
            assert placed.status_code == 200
            source = (await call("get_narrative_source", {"project_id": pid}))["result"]
            assert source["mode"] == "script_authority" and source["ready_for_timing"]
            audio = await client.call_tool("atme.read_authoritative_audio", {"project_id": pid})
            assert not audio.is_error
            assert any(getattr(item, "type", None) == "audio" for item in audio.content)
            resource = await client.read_resource(f"atme://projects/{pid}/authoritative-narrative")
            assert resource.contents and getattr(resource.contents[0], "blob", None)
            timeline_layout = (await call("get_project_artifact", {
                "project_id": pid, "kind": "layout"}))["result"]
            assert timeline_layout["stale"] is False
            assert timeline_layout["basis_timeline_revision"] == 0

            # Replace the short test recording and author both plans after that media
            # revision so the real MCP preview path can prove binary image transport.
            upload = http.post(f"/projects/{pid}/media/wav?expected_revision=5",
                headers={"Authorization": "Bearer local-test"}, content=_wav_bytes(7))
            assert upload.status_code == 200
            second = upload.json()["media"]
            timeline = http.get(f"/projects/{pid}/source-timeline", headers={"Authorization":"Bearer local-test"}).json()
            placed = http.post(f"/projects/{pid}/source-timeline/commands", headers={"Authorization":"Bearer local-test"},
                json={"operation":"insert","arguments":{"media_id":second["media_id"],"at_ms":0},
                      "expected_revision":6,"expected_timeline_revision":timeline["timeline_revision"]})
            assert placed.status_code == 200
            from atme.visual_plan import build_visual_plan
            await call("write_artifact", {"project_id": pid, "kind": "storyboard",
                "document": build_visual_plan(payload["script"]), "expected_revision": 7})
            layout_doc = payload["layout"]
            layout_doc["canvas"] = {"width": 1280, "height": 720}
            await call("write_artifact", {"project_id": pid, "kind": "layout",
                "document": layout_doc, "expected_revision": 8})
            validation = (await call("validate_project", {"project_id": pid}))["result"]
            assert validation["ready"] is True and validation["project_revision"] == 9
            preview = await client.call_tool("atme.preview_project", {
                "project_id": pid, "expected_revision": 9, "at_ms": 2500})
            assert not preview.is_error
            assert any(getattr(item, "type", None) == "image" for item in preview.content)
            http.close()
            orch.store.close()
            return pid

    pid = asyncio.run(exercise())
    store = JobStore(database)
    core = ProjectService(store)
    assert core.open(pid)["revision"] == 9
    assert core.open(pid)["approved_script_revision"] == 1
    assert not store.conn.execute("SELECT * FROM llm_usage").fetchall()
    activity = McpActivity(store).snapshot()
    assert activity["last_activity_at"] is not None
    assert activity["last_tool"] in {"atme.preview_project", "atme.validate_project",
                                     "atme.get_project_artifact"}
    assert pid in activity["recent_project_ids"]
    store.close()


def test_plan_dependency_changes_are_reported_without_rewriting_history(tmp_path):
    store = JobStore(tmp_path / "project.db")
    core = ProjectService(store)
    pid = core.create("Plan version", "LONG_FORM_16_9", "script-first")["project_id"]
    payload = external_payload()
    core.write(pid, "script", payload["script"], 0)
    core.write(pid, "layout", payload["layout"], 1)
    core.write(pid, "script", payload["script"], 2)
    assert core.artifact(pid, "layout")["stale"] is True
    assert core.artifact(pid, "layout")["document"] == payload["layout"]
    store.close()
