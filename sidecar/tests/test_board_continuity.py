"""Research R01-R03: board returns and transient attention must survive seeking.

Original diagnostic geometry and authored timings, not copied video artwork/timing.
"""
from __future__ import annotations

from copy import deepcopy

import numpy as np
import pytest

from atme.render.animator import _FrameRenderer, build_draw_windows
from atme.render.svg_builder import element_stroke_info, frame_svg


def board_doc():
    return {
        "contract_version": "1", "seed": 7, "grid": 50,
        "canvas": {"width": 600, "height": 400},
        "board_timeline": {
            "version": "1",
            "boards": [{"board_id": "queue"}, {"board_id": "evidence"}],
            "activations": [
                {"activation_id": "queue-first", "board_id": "queue",
                 "start_ms": 0, "end_ms": 2000},
                {"activation_id": "evidence-first", "board_id": "evidence",
                 "start_ms": 2000, "end_ms": 4000},
                {"activation_id": "queue-return", "board_id": "queue",
                 "start_ms": 4000, "end_ms": 6000},
            ],
        },
        "elements": [
            {"id": "el-queue", "scene_id": 1, "board_id": "queue",
             "appear_at_ms": 0, "type": "rectangle", "x": 50, "y": 50,
             "width": 200, "height": 100, "label": "Queue", "fillStyle": "none"},
            {"id": "el-pointer", "scene_id": 1, "board_id": "queue",
             "appear_at_ms": 500, "type": "arrow",
             "start": {"x": 350, "y": 200}, "end": {"x": 450, "y": 200},
             "visibility_intervals": [{"start_ms": 500, "end_ms": 1500}]},
            {"id": "el-evidence", "scene_id": 2, "board_id": "evidence",
             "appear_at_ms": 2000, "type": "rectangle", "x": 350, "y": 50,
             "width": 200, "height": 100, "label": "Evidence", "fillStyle": "none"},
        ],
    }


def renderer(doc=None):
    doc = doc if doc is not None else board_doc()
    windows = build_draw_windows(doc["elements"])
    infos = {e["id"]: element_stroke_info(e, doc["seed"]) for e in doc["elements"]}
    return _FrameRenderer(doc, infos, windows, 600, 400)


def ink(frame, region):
    return int((np.asarray(frame.crop(region)).mean(axis=2) < 180).sum())


def test_evidence_excursion_restores_original_board_without_ghosts():
    r = renderer()
    original = np.asarray(r.frame(1750)).copy()
    evidence = r.frame(3000)
    assert ink(evidence, (40, 40, 270, 170)) == 0
    assert ink(evidence, (340, 40, 570, 170)) > 100
    assert np.array_equal(original, np.asarray(r.frame(4500)))


def test_expired_attention_mark_does_not_live_in_cached_layer():
    r = renderer()
    assert ink(r.frame(1400), (330, 180, 480, 230)) > 0
    assert ink(r.frame(1600), (330, 180, 480, 230)) == 0
    assert ink(r.frame(4500), (330, 180, 480, 230)) == 0


def test_half_open_activation_boundaries_and_end():
    r = renderer()
    assert ink(r.frame(1999), (40, 40, 270, 170)) > 100
    assert ink(r.frame(2000), (40, 40, 270, 170)) == 0
    assert ink(r.frame(4000), (40, 40, 270, 170)) > 100
    assert ink(r.frame(6000), (0, 0, 600, 400)) == 0


def test_arbitrary_seek_matches_fresh_frame_evaluation():
    r = renderer()
    for at in [4500, 1400, 3000, 1600, 0, 5999, 2000, 1750]:
        assert np.array_equal(np.asarray(r.frame(at)), np.asarray(renderer().frame(at)))


def test_svg_preview_uses_same_visibility_as_raster_renderer():
    doc = board_doc()
    infos = {e["id"]: element_stroke_info(e, doc["seed"]) for e in doc["elements"]}
    view = {"x": 0, "y": 0, "w": 600, "h": 400, "out_w": 600, "out_h": 400}
    svg = frame_svg(doc, infos, 3000, build_draw_windows(doc["elements"]), view)
    assert "Evidence" in svg
    assert "Queue" not in svg


def test_typed_layout_round_trip_preserves_visibility_contract():
    from atme.store.contracts import LayoutDoc
    from atme.render.visibility import validate_visibility

    doc = LayoutDoc.model_validate(board_doc()).model_dump()
    validate_visibility(doc)
    assert doc["board_timeline"] == board_doc()["board_timeline"]


def test_legacy_typed_layout_still_serializes_to_legacy_schema():
    from atme.store.contracts import LayoutDoc
    from conftest import load_example, load_schema
    from jsonschema import Draft202012Validator

    doc = LayoutDoc.model_validate(load_example("excalidraw-layout")).model_dump()
    assert "board_timeline" not in doc
    Draft202012Validator(load_schema("excalidraw-layout")).validate(doc)


def test_pipeline_preserves_authored_board_timing():
    from atme.pipeline import _retime_layout

    doc = board_doc()
    before = deepcopy(doc)
    assert _retime_layout(doc, [], [], [], 6000) == before
    with pytest.raises(ValueError, match="exceeds the final narration"):
        _retime_layout(doc, [], [], [], 5000)


@pytest.mark.parametrize("fault", ["unknown_board", "overlap", "empty_interval",
                                   "duplicate_id", "missing_board"])
def test_invalid_board_state_is_rejected_before_render(fault):
    doc = deepcopy(board_doc())
    if fault == "unknown_board":
        doc["elements"][0]["board_id"] = "missing"
    elif fault == "overlap":
        doc["board_timeline"]["activations"][1]["start_ms"] = 1999
    elif fault == "empty_interval":
        doc["elements"][1]["visibility_intervals"][0]["end_ms"] = 500
    elif fault == "duplicate_id":
        doc["board_timeline"]["activations"][1]["activation_id"] = "queue-first"
    else:
        del doc["elements"][0]["board_id"]
    with pytest.raises(ValueError):
        renderer(doc)
