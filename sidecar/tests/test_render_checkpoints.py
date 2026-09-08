"""Render checkpoints must not hide visual revisions or incomplete segment writes."""
import json
from types import SimpleNamespace

import pytest

from atme import pipeline
from test_board_continuity import board_doc


@pytest.fixture
def render_job(tmp_path, monkeypatch):
    layout = tmp_path / "layout.json"
    layout.write_text(json.dumps(board_doc()), encoding="utf-8")
    calls = []

    def render(doc, path, **kwargs):
        calls.append(kwargs)
        path.write_bytes(b"rendered" * 300)
        return {"frames": 30, "layer_builds": 1, "overlay_frames": 2,
                "start_ms": kwargs["start_ms"], "duration_ms": kwargs["duration_ms"]}

    monkeypatch.setattr(pipeline, "render_video", render)
    monkeypatch.setattr(pipeline, "find_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(pipeline.subprocess, "run", lambda *a, **k:
                        SimpleNamespace(returncode=0))
    state = {"layout_file": str(layout), "duration_ms": 6000}

    def run(**kwargs):
        return pipeline.render_stage(tmp_path, state, **{
            "width": 600, "height": 400, "fps": 30, **kwargs})

    return run, calls, layout, tmp_path, state


def test_unchanged_checkpoint_reuses_and_retains_frame_count(render_job):
    run, calls, _, _, _ = render_job
    first = run()
    second = run()
    assert len(calls) == 1
    assert second["segments"][0]["resumed"] is True
    assert second["render"]["frames"] == first["render"]["frames"]


@pytest.mark.parametrize("change", ["layout", "width", "fps", "duration"])
def test_render_input_revision_invalidates_checkpoint(render_job, change):
    run, calls, layout, _, state = render_job
    run()
    options = {}
    if change == "layout":
        doc = json.loads(layout.read_text())
        doc["elements"][0]["enter_action"] = "reveal"
        layout.write_text(json.dumps(doc))
    elif change == "duration":
        state["duration_ms"] += 100
    else:
        options[change] = 800 if change == "width" else 24
    run(**options)
    assert len(calls) == 2


def test_unverified_or_corrupted_video_is_not_reused(render_job):
    run, calls, _, root, _ = render_job
    directory = root / "out" / "segments"
    directory.mkdir(parents=True)
    segment = directory / "seg_0000.mp4"
    segment.write_bytes(b"incomplete" * 300)
    run()
    assert len(calls) == 1
    segment.write_bytes(b"changed!!" * 300)
    run()
    assert len(calls) == 2


def test_interrupted_revision_keeps_old_completed_segment(render_job, monkeypatch):
    run, calls, _, root, _ = render_job
    run()
    segment = root / "out" / "segments" / "seg_0000.mp4"
    original = segment.read_bytes()

    def fail(doc, path, **kwargs):
        path.write_bytes(b"partial" * 300)
        raise RuntimeError("interrupted")

    monkeypatch.setattr(pipeline, "render_video", fail)
    with pytest.raises(RuntimeError, match="interrupted"):
        run(width=800)
    assert segment.read_bytes() == original
    assert run()["segments"][0]["resumed"] is True


def test_malformed_checkpoint_rerenders(render_job):
    run, calls, _, root, _ = render_job
    run()
    (root / "out" / "segments" / "seg_0000.json").write_text("{broken")
    run()
    assert len(calls) == 2
