from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_studio_has_production_viewer_timeline_and_navigation_contracts():
    html = (ROOT / "app" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "app" / "src" / "studio.ts").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "src" / "studio.css").read_text(encoding="utf-8")

    assert 'id="viewer-stage"' in html
    assert 'id="project-launcher"' in html
    assert 'id="cancel-new-project" type="button"' in html
    assert 'data-workspace="projects"' not in html
    assert 'id="workspace-splitter"' in html
    assert 'id="blade-tool"' in html and 'id="snap-toggle"' in html
    assert 'id="timeline-context-menu"' in html
    assert 'id="viewer-canvas"' in html
    assert 'id="source-removal-dialog"' in html
    assert 'id="confirm-source-removal"' in html
    assert "window.confirm(warning)" not in script
    assert "showSourceRemovalDialog" in script
    assert "beginPlayheadDrag" in script
    assert "beginTrackResize" in script and "beginWorkspaceResize" in script
    assert 'applySourceEdit("detach_audio"' in script
    assert 'applySourceEdit("remove_clip"' in script
    assert "application/x-atme-media" in script
    assert "onDragDropEvent" in script and "import_dropped_source" in script
    assert 'await loadProjects(); toast("Project created.' in script
    assert "set_studio_open" in script and "atme://return-to-projects" in script
    assert "media?.name" in script
    assert "finishPlayheadDrag" in script
    assert "showProjectBrowser" in script
    assert "if (!show) return" in script
    assert "previewMediaSource" in script and "previewTimelineClip" in script
    assert "timeline-export" in script
    assert "showMediaPanel" in script
    assert "source-video-active" in script
    assert ".source-video-active .source-video" in styles
    assert ".viewer-canvas" in styles
    assert ".playhead-handle" in styles
    assert "Preview playback becomes available when validation passes." not in script
    assert "Playback is an editor operation" in script
    assert '<option value="chatgpt">ChatGPT Desktop</option>' in html
    assert '<option value="codex">Codex</option>' in html
    assert '<option value="claude">Claude Desktop</option>' in html
    assert 'value="gemini"' not in html and 'value="cursor"' not in html
    assert "watchMcpConnection" in script
    assert "MCP connected live" in script
    assert 'id="enable-jev"' in html and 'id="jev-key"' in html
    assert 'id="copy-ai-status"' in html and "✓ Copied" in script
    assert "ATME CONNECTION RULE" not in script
    assert "Installation preserves other client settings" in html
    assert 'class="app-menu"' in html and 'data-menu-action="render"' in html
    assert "runMenuAction" in script
    assert 'id="install-ai-setup"' in html and 'id="remove-ai-setup"' in html
    assert '"install_mcp_client"' in script and '"remove_mcp_client"' in script


def test_user_mcp_surface_cannot_edit_or_diagnose_the_application_source():
    mcp = (ROOT / "sidecar" / "src" / "atme" / "mcp_server.py").read_text(encoding="utf-8")
    assert "subprocess" not in mcp
    assert "import subprocess" not in mcp and "import shlex" not in mcp
    assert "arbitrary paths" in mcp
    for forbidden in ("edit_file", "write_file", "apply_patch", "run_command", "diagnose_app"):
        assert f'name="atme.{forbidden}"' not in mcp
