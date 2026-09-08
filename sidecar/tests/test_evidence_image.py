"""Original test pixels verify R04/R05, not source research claims."""
import base64
import hashlib
import io
import subprocess

import pytest
import numpy as np
from PIL import Image

from atme.render.svg_builder import element_stroke_info, frame_svg
from atme.render.animator import build_draw_windows, resvg_bytes, find_ffmpeg, render_video
from atme.store.contracts import LayoutDoc
from test_board_continuity import board_doc, renderer


def evidence_doc():
    doc = board_doc()
    buffer = io.BytesIO()
    Image.new("RGB", (200, 100), (20, 80, 180)).save(buffer, format="PNG")
    raw = buffer.getvalue()
    doc["elements"][-1] = {
        "id": "el-evidence", "type": "evidence_image", "scene_id": 2,
        "board_id": "evidence", "appear_at_ms": 2000, "enter_action": "reveal",
        "x": 100, "y": 100, "width": 400, "height": 200,
        "png_base64": base64.b64encode(raw).decode("ascii"),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "provenance": {"kind": "original_illustration", "description": "Original test pixels"},
    }
    return doc


def test_evidence_reveals_holds_and_returns_without_ghosts():
    doc = evidence_doc()
    LayoutDoc.model_validate(doc)
    r = renderer(doc)
    original = r.frame(1750).tobytes()
    shown = r.frame(2000)
    assert shown.getpixel((300, 200)) == (20, 80, 180)
    assert shown.tobytes() == r.frame(3999).tobytes()
    assert original == r.frame(4500).tobytes()
    assert shown.tobytes() == r.frame(2000).tobytes()


def test_evidence_preview_contains_same_self_contained_image():
    doc = evidence_doc()
    infos = {e["id"]: element_stroke_info(e, doc["seed"]) for e in doc["elements"]}
    svg = frame_svg(doc, infos, 2500, build_draw_windows(doc["elements"]),
                    {"x": 0, "y": 0, "w": 600, "h": 400, "out_w": 600, "out_h": 400})
    assert "data:image/png;base64," + doc["elements"][-1]["png_base64"] in svg
    assert 'preserveAspectRatio="xMidYMid meet"' in svg
    assert "Queue" not in svg


@pytest.mark.parametrize("change", ["checksum", "base64", "svg", "external_source", "draw"])
def test_invalid_evidence_rejected(change):
    doc = evidence_doc()
    el = doc["elements"][-1]
    if change == "checksum":
        el["sha256"] = "0" * 64
    elif change == "base64":
        el["png_base64"] = "%%%not-base64"
    elif change == "svg":
        raw = b'<svg xmlns="http://www.w3.org/2000/svg"/>'
        el["png_base64"] = base64.b64encode(raw).decode()
        el["sha256"] = hashlib.sha256(raw).hexdigest()
    elif change == "external_source":
        el["provenance"]["kind"] = "external_evidence"
    else:
        el["enter_action"] = "draw"
    with pytest.raises(ValueError):
        LayoutDoc.model_validate(doc)


def test_external_evidence_source_is_metadata_not_fetched():
    doc = evidence_doc()
    doc["elements"][-1]["provenance"].update(
        kind="external_evidence", source_url="https://example.invalid/research")
    LayoutDoc.model_validate(doc)
    assert renderer(doc).frame(2500).getpixel((300, 200)) == (20, 80, 180)


def test_image_fits_without_stretching_or_cropping():
    doc = evidence_doc()
    doc["elements"][-1]["height"] = 300
    shown = renderer(doc).frame(2500)
    assert shown.getpixel((300, 120)) == (250, 249, 245)  # letterbox paper
    assert shown.getpixel((300, 200)) == (20, 80, 180)


def test_image_pixel_limit_rejected(monkeypatch):
    from atme.render import evidence
    evidence.validate_png.cache_clear()
    monkeypatch.setattr(evidence, "MAX_PIXELS", 100)
    with pytest.raises(ValueError, match="pixel limit"):
        LayoutDoc.model_validate(evidence_doc())


@pytest.mark.parametrize("at_ms", [2300, 3200, 2500, 3999, 2300])
@pytest.mark.parametrize("annotation_on_top", [False, True])
def test_export_preserves_preview_paint_order(at_ms, annotation_on_top):
    doc = evidence_doc()
    annotation = {
        "id": "el-annotation", "scene_id": 2, "board_id": "evidence",
        "appear_at_ms": 2100, "type": "rectangle", "x": 150, "y": 150,
        "width": 200, "height": 100, "label": "Overlay", "fillStyle": "none",
    }
    doc["elements"].insert(len(doc["elements"]) if annotation_on_top else -1, annotation)
    r = renderer(doc)
    # Exercise both backwards seeking and returning from a different board.
    r.frame(4500)
    r.frame(3200)
    svg = frame_svg(doc, r.infos, at_ms, r.windows,
                    {"x": 0, "y": 0, "w": 600, "h": 400, "out_w": 600, "out_h": 400})
    preview = Image.open(io.BytesIO(resvg_bytes(svg, 600, 400))).convert("RGB")
    actual = r.frame(at_ms)
    if annotation_on_top:
        # Separate alpha compositing rounds antialiasing by at most two levels.
        assert np.abs(np.asarray(actual).astype(int) - np.asarray(preview).astype(int)).max() <= 2
    else:
        assert actual.tobytes() == preview.tobytes()


def test_encoded_video_keeps_drawing_behind_evidence(tmp_path):
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("FFmpeg is required for encoded video verification")
    doc = evidence_doc()
    doc["elements"].insert(-1, {
        "id": "el-hidden", "scene_id": 2, "board_id": "evidence",
        "appear_at_ms": 2100, "type": "rectangle", "x": 150, "y": 150,
        "width": 200, "height": 100, "label": "Hidden", "fillStyle": "none",
    })
    output = tmp_path / "paint-order.mp4"
    stats = render_video(doc, output, fps=10, width=600, height=400,
                         start_ms=2000, duration_ms=2000)
    assert stats["frames"] == 20
    decoded = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(output), "-f", "rawvideo",
         "-pix_fmt", "rgb24", "-"], capture_output=True, check=True, timeout=30)
    frames = np.frombuffer(decoded.stdout, dtype=np.uint8).reshape(20, 400, 600, 3)
    # Avoid image edges where lossy H.264 chroma subsampling blends with paper.
    interior = frames[:, 120:280, 120:480].astype(int)
    assert np.abs(interior - np.array([20, 80, 180])).max() <= 5
