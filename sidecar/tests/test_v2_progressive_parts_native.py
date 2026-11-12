"""Real finite P3-24 pixel proof; run only after the coordinator releases the native gate."""

import io
import socket
from copy import deepcopy
from pathlib import Path

import pytest
import resvg_py
from atme.render.style_bundle import load_bundle
from atme.render.v2_split_paint import verify_split_paint_inputs
from atme.render.v2_state import evaluate_frame
from atme.render.v2_svg import (
    _compose_validated_svg_frame,
    _rasterize_svg_frame,
    compose_png_frame,
    compose_svg_frame,
)
from PIL import Image
from test_v2_group_annotation import consumer_clock
from test_v2_progressive_parts import documents
from test_v2_progressive_parts_project import stored_parts_basis
from v2_fixtures import digest


def native_documents(portrait=False, grouped=False):
    _, layout, timeline = documents(portrait, grouped)
    objects = {obj["object_id"]: obj for obj in layout["objects"]}
    objects["object-system"].update(object_type="rectangle", style={"stroke": "ink.primary",
        "fill": "surface.paper", "text": None, "effect": None})
    objects["object-system"]["geometry"].update(bounds={"x": 20, "y": 20, "width": 100, "height": 60}, corner_radius=None)
    objects["object-label"].update(text="Intro", style={"stroke": None, "fill": None, "text": "text.body", "effect": None})
    objects["object-label"]["geometry"]["bounds"].update(x=160, y=20, width=150, height=60)
    heading = objects["object-evidence"]
    heading.update(visible=False, initial_state="hidden")
    for key in ("object-evidence",):
        objects[key]["text"] = "Hidden"
        objects[key]["style"]["text"] = "text.body"
        objects[key]["geometry"]["bounds"].update(x=80, y=60, width=500, height=60)
    for key, x, y in (("list-item-a", 80, 200), ("list-item-b", 240, 200),
                      ("list-item-c", 400, 200), ("part-mark", 400, 300), ("part-text", 400, 400)):
        if key not in objects:
            continue
        obj = objects[key]
        obj["geometry"]["bounds"].update(x=x, y=y, width=100, height=60)
        if obj["object_type"] == "text":
            obj["text"] = "B" if key == "list-item-b" else "C"
            obj["style"] = {"stroke": None, "fill": None, "text": "text.body", "effect": None}
    timeline["initial_object_states"] = [{"object_id": obj["object_id"], "state": obj["initial_state"],
        "visible": obj["visible"], "state_version": 1} for obj in layout["objects"]]
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline


def rgba(raw):
    with Image.open(io.BytesIO(raw)) as frame:
        return frame.convert("RGBA").tobytes()


def ordinary_completed_parts(layout, timeline, at_ms):
    from atme.render.v2_hierarchy import HierarchySnapshot
    from atme.store.contracts_v2 import ExecutableLayoutV2

    raw, resolved = deepcopy(layout), deepcopy(timeline)
    progressive = resolved["actions"].pop()
    policy = progressive["action"]["progressive_parts_policy"]
    parsed = ExecutableLayoutV2.model_validate(raw)
    objects = {obj.object_id: obj for obj in parsed.objects}
    hierarchy = HierarchySnapshot.from_objects(objects)
    selected = [key for key in policy["expected_closure_state_versions"]
                if at_ms >= (4225 if key == "list-item-a" else 4675 if key == "list-item-b" else 4900)]
    assert selected, "ordinary comparison requires at least one completed part"
    selected.sort(key=lambda key: (len(hierarchy.ancestors(key)), key))
    added = []
    for index, key in enumerate(selected):
        row = deepcopy(progressive)
        action = row["action"]
        action.pop("progressive_parts_policy")
        start = 3000 + 2*index
        action.update(action_id=f"ordinary-{key}", verb="enter" if objects[key].object_type == "group" else "reveal",
                      target_ids=[key], trigger={"kind": "absolute", "at_ms": start})
        row.update(start_ms=start, end_ms=start+1, resolved_trigger={"source": action["trigger"], "resolved_at_ms": start,
            "alignment_anchor_ms": start, "matched_text": None, "matched_occurrence": None, "confidence": 1, "exact": True})
        resolved["actions"].append(row)
        added.append(action["action_id"])
    next(row for row in resolved["coverage"] if row["coverage_id"] == "coverage-3")["action_ids"] = added
    return raw, resolved


@pytest.mark.integration
@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("grouped", [False, True])
def test_real_parts_literal_pixels_boundaries_frozen_and_ordinary_compositors(tmp_path, monkeypatch, portrait, grouped):
    layout, timeline = native_documents(portrait, grouped)
    context, _, _ = consumer_clock(layout, timeline)
    frozen_inputs = verify_split_paint_inputs(context.layout, {})
    _, _, root = load_bundle()
    monkeypatch.setattr(socket, "socket", lambda *a, **kw: pytest.fail("progressive parts attempted network access"))
    monkeypatch.setattr(socket, "create_connection", lambda *a, **kw: pytest.fail("progressive parts attempted network access"))
    monkeypatch.setattr("atme.render.animator._FrameRenderer", lambda *a, **kw: pytest.fail("progressive parts fell back to v1"))
    width, height = (720, 1280) if portrait else (1280, 720)
    profile = "portrait" if portrait else "landscape"
    parts = "group" if grouped else "leaves"
    frames = {}
    for at_ms in (4000, 4224, 4225, 4226, 4674, 4675, 4676, 4899, 4900, 4901):
        ink = ['<rect x="20" y="20" width="100" height="60" rx="0" fill="#FAF8F1" stroke="#172033" stroke-width="2.6667" stroke-linecap="round" stroke-linejoin="round"/>',
               '<text x="160" y="41.3333" fill="#172033" font-family="Atkinson Hyperlegible" font-weight="400" font-size="21.3333" xml:space="preserve">Intro</text>']
        if at_ms >= 4225:
            ink.append('<rect x="80" y="200" width="100" height="60" rx="0" fill="#DCE6FF" stroke="#2457D6" stroke-width="2.6667" stroke-linecap="round" stroke-linejoin="round"/>')
        if at_ms >= 4675:
            ink.append('<text x="240" y="221.3333" fill="#172033" font-family="Atkinson Hyperlegible" font-weight="400" font-size="21.3333" xml:space="preserve">B</text>')
        if at_ms >= 4900:
            if grouped:
                ink.append('<rect x="400" y="300" width="100" height="60" rx="0" fill="#DCE6FF" stroke="#2457D6" stroke-width="2.6667" stroke-linecap="round" stroke-linejoin="round"/>')
            ink.append(f'<text x="400" y="{421.3333 if grouped else 221.3333}" fill="#172033" font-family="Atkinson Hyperlegible" font-weight="400" font-size="21.3333" xml:space="preserve">C</text>')
        literal = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
                   f'<rect width="{width}" height="{height}" fill="#FAF8F1"/>{"".join(ink)}</svg>')
        expected = bytes(resvg_py.svg_to_bytes(svg_string=literal,
            font_files=[str(root / "fonts/AtkinsonHyperlegible-Regular.otf")], skip_system_fonts=True))
        stem = f"{profile}-{parts}-{at_ms:05d}"
        (tmp_path / f"{stem}-expected.png").write_bytes(expected)
        (tmp_path / f"{stem}-expected.svg").write_text(literal, encoding="utf-8")
        png = compose_png_frame(layout, timeline, at_ms).png
        source = compose_svg_frame(layout, timeline, at_ms)
        (tmp_path / f"{stem}-actual.png").write_bytes(png)
        (tmp_path / f"{stem}-source.svg").write_text(source.svg, encoding="utf-8")
        assert rgba(png) == rgba(expected)
        snapshot = evaluate_frame(layout, timeline, at_ms)
        with monkeypatch.context() as frozen_guard:
            frozen_guard.setattr(Path, "read_bytes", lambda *a: pytest.fail("frozen progression attempted path fallback"))
            frozen = _compose_validated_svg_frame(context.layout, context.timeline, snapshot, {}, split_inputs=frozen_inputs)
            frozen_png = _rasterize_svg_frame(context.layout, frozen, split_inputs=frozen_inputs).png
            (tmp_path / f"{stem}-frozen.svg").write_text(frozen.svg, encoding="utf-8")
            (tmp_path / f"{stem}-frozen.png").write_bytes(frozen_png)
            assert frozen_png == png
        assert frozen == source
        if at_ms >= 4225:
            ordinary_layout, ordinary_timeline = ordinary_completed_parts(layout, timeline, at_ms)
            ordinary_png = compose_png_frame(ordinary_layout, ordinary_timeline, at_ms).png
            (tmp_path / f"{stem}-ordinary.png").write_bytes(ordinary_png)
            assert rgba(ordinary_png) == rgba(png)
        frames[at_ms] = png
    for at_ms in (4901, 4000, 4676, 4224, 4900, 4899, 4225, 4675, 4226, 4674):
        assert compose_png_frame(layout, timeline, at_ms).png == frames[at_ms]


@pytest.mark.integration
@pytest.mark.parametrize("portrait", [False, True])
def test_real_stored_reopened_and_duplicate_project_parts_pixels(tmp_path, portrait):
    service, project, layout, timeline = stored_parts_basis(tmp_path, portrait)
    try:
        pid = project["project_id"]
        project = service.write(pid, "resolved_timeline", timeline, project["revision"])
        profile = "portrait" if portrait else "landscape"
        pixels = {}
        for at_ms in (4000, 4225, 4675, 4900):
            pixels[at_ms] = service.runner.preview_v2_source(pid, project["revision"], at_ms)["png"]
            (tmp_path / f"{profile}-stored-{at_ms:05d}.png").write_bytes(pixels[at_ms])
        for at_ms, png in pixels.items():
            direct = compose_png_frame(layout, timeline, at_ms).png
            (tmp_path / f"{profile}-direct-{at_ms:05d}.png").write_bytes(direct)
            assert png == direct
        service.open(pid)
        reopened = service.runner.preview_v2_source(pid, project["revision"], 4900)["png"]
        (tmp_path / f"{profile}-reopened-04900.png").write_bytes(reopened)
        copied = service.duplicate(pid)
        for at_ms in (4900, 4000, 4675, 4225):
            duplicate = service.runner.preview_v2_source(copied["project_id"], copied["revision"], at_ms)["png"]
            (tmp_path / f"{profile}-duplicate-{at_ms:05d}.png").write_bytes(duplicate)
            assert duplicate == pixels[at_ms]
    finally:
        service.store.close()
