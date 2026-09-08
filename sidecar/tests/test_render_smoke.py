"""Render smoke tests: structural pixel-level sanity of the layered animator.

These guard the compositor contract (paper background, ink actually drawn, animation progress,
seeded determinism) without requiring human eyes on every change.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from conftest import REPO_ROOT

LAYOUT = REPO_ROOT / "schemas" / "examples" / "excalidraw-layout.example.json"
PAPER = np.array([250, 249, 245], dtype=np.int16)


@pytest.fixture(scope="module")
def renderer():
    from atme.render.animator import _FrameRenderer, build_draw_windows
    from atme.render.svg_builder import element_stroke_info

    doc = json.loads(LAYOUT.read_text(encoding="utf-8"))
    windows = build_draw_windows(doc["elements"])
    infos = {el["id"]: element_stroke_info(el, doc["seed"]) for el in doc["elements"]}
    return _FrameRenderer(doc, infos, windows, 1280, 720), doc


def test_frame_geometry(renderer):
    r, _doc = renderer
    img = r.frame(6000)
    assert img.size == (1280, 720)


def test_background_is_paper_and_ink_exists(renderer):
    r, _doc = renderer
    arr = np.asarray(r.frame(6000).convert("RGB"), dtype=np.int16)
    # corners stay paper
    for y, x in [(5, 5), (714, 5), (5, 1274)]:
        assert np.abs(arr[y, x] - PAPER).max() <= 6, f"corner ({y},{x}) not paper: {arr[y, x]}"
    # some ink was actually drawn (title text lives near top center)
    lum = arr.mean(axis=2)
    ink = (lum < 90).sum()
    assert ink > 50, f"expected visible ink strokes, found {ink} dark px"


def test_animation_progresses_between_frames(renderer):
    r, _doc = renderer
    # text elements fade in (opacity ramp), so 'ink' means clearly-below-paper luminance
    def ink_px(t):
        arr = np.asarray(r.frame(t).convert("RGB"))
        return int((arr.mean(axis=2) < 210).sum())

    before, mid, done = ink_px(400), ink_px(700), ink_px(6000)
    assert before == 0, "nothing visible before appear_at_ms"
    assert mid > before and done > mid, (
        f"draw-on must progress monotonically: {before} -> {mid} -> {done}"
    )


def test_seed_determinism(renderer):
    r, doc = renderer
    a = np.asarray(r.frame(3000).convert("RGB")).copy()
    # fresh renderer, same seed -> byte-identical output
    from atme.render.animator import _FrameRenderer, build_draw_windows
    from atme.render.svg_builder import element_stroke_info

    w2 = build_draw_windows(doc["elements"])
    i2 = {el["id"]: element_stroke_info(el, doc["seed"]) for el in doc["elements"]}
    r2 = _FrameRenderer(doc, i2, w2, 1280, 720)
    b = np.asarray(r2.frame(3000).convert("RGB"))
    assert np.array_equal(a, b), "same seed must reproduce identical frames"
