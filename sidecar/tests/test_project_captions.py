import pytest
from io import BytesIO

from PIL import Image, ImageChops

from atme.project_service import ProjectError
from test_storyboard_speech import measured_plan


@pytest.mark.parametrize("size", [(1280, 720), (720, 1280)])
def test_burned_captions_use_exclusive_ends_and_fit_the_profile(size):
    from atme.project_captions import CaptionPainter

    stream = BytesIO()
    base = Image.new("RGBA", size, "white")
    base.save(stream, format="PNG")
    plain = stream.getvalue()
    painter = CaptionPainter([{"start_ms":100, "end_ms":320, "text":"Here is the queue."}], *size)
    assert painter.index(99) is None and painter.index(319) == 0 and painter.index(320) is None
    assert painter.paint(plain, None) == plain
    painted = Image.open(BytesIO(painter.paint(plain, 0))).convert("RGB")
    x, y, right, bottom = ImageChops.difference(painted, base.convert("RGB")).getbbox()
    assert x > size[0] * .03 and right < size[0] * .97
    assert y > size[1] / 2 and bottom < size[1] * .94


def test_captions_reuse_current_measurement_and_keep_edits_separate(tmp_path, monkeypatch):
    service, pid, revision, _, run_id = measured_plan(tmp_path, monkeypatch)
    try:
        track = service.caption_track(pid, revision)
        assert track["timing_run_id"] == run_id and track["status"] == "ready"
        first, second = track["cues"]
        assert first["start_ms"] == 100 and second["start_ms"] == 1100
        assert second["text"] == "Queue pointer."
        edited = [first, {**second, "text": "Queue pointer!", "start_ms": 1125}]
        saved = service.save_captions(pid, revision, run_id, edited)
        assert saved["project_revision"] == revision + 1
        assert service.caption_track(pid, revision + 1)["cues"] == edited
        assert "00:00:01.125 --> " in service.subtitle_file(pid, revision + 1, "vtt")
        assert "00:00:01,125 --> " in service.subtitle_file(pid, revision + 1, "srt")
        assert service.open(pid)["approved_script_revision"] == 1
        assert service.save_captions(pid, revision + 1, run_id, edited)["project_revision"] == revision + 1
        with pytest.raises(ProjectError, match="overlap"):
            service.save_captions(pid, revision + 1, run_id, [first, {**second, "start_ms": 101}])
        current = service.source_timeline.get(pid)
        result = service.edit_source_timeline(pid, "trim", {"clip_id": current["document"]["clips"][0]["clip_id"],
            "start_ms": 50, "end_ms": 7000}, revision + 1, current["timeline_revision"])
        assert service.caption_track(pid, result["project"]["revision"])["status"] == "needs_timing"
    finally:
        service.store.close()
