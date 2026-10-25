"""Exact code objects use the existing sampled object-tree and font paths."""

import io
from copy import deepcopy
from pathlib import Path

import pytest
import resvg_py
from atme.render.style_bundle import load_bundle
from atme.render.v2_split_paint import _split_primitive_paint as split_primitive
from atme.render.v2_split_paint import verify_split_paint_inputs
from atme.render.v2_state import evaluate_frame
from atme.render.v2_svg import (
    _compose_validated_svg_frame,
    _rasterize_svg_frame,
    compose_png_frame,
    compose_svg_frame,
)
from atme.store.contracts_v2 import ExecutableLayoutV2, ResolvedVisualTimelineV2
from PIL import Image
from test_v2_code_contract import authored_payload
from test_v2_svg import primitive_documents
from v2_fixtures import digest


def code_documents(portrait=False):
    layout, timeline = primitive_documents()
    obj = layout["objects"][1]
    payload = authored_payload()
    payload["lines"] = [{"line_id": "line-0", "spans": [
        {"span_id": "source-span", "role": "plain", "text": "e\u0301x"}]}]
    obj.update(object_type="code", text="e\u0301x", items=[], code_payload=payload,
               style={"stroke": None, "fill": None, "text": "text.code", "effect": None},
               geometry={"bounds": {"x": 90 if portrait else 80, "y": 280 if portrait else 200,
                                     "width": 500, "height": 160}, "points": [], "corner_radius": None})
    layout["objects"] = [obj]
    layout["boards"][0]["object_ids"] = [obj["object_id"]]
    action = timeline["actions"][1]
    action["action"].update(verb="write", easing="linear")
    timeline["actions"] = [action]
    timeline["initial_object_states"] = [timeline["initial_object_states"][1]]
    timeline["coverage"] = [timeline["coverage"][1]]
    timeline["fallbacks"] = [timeline["fallbacks"][1]]
    timeline["resolved_assets"] = []
    if portrait:
        profile = {"profile_id": "SHORT_FORM_9_16", "width": 720, "height": 1280, "fps": 30}
        layout["output_profile"] = timeline["output_profile"] = profile
        layout["canvas"].update(width=720, height=1280)
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline


def rgba(payload):
    with Image.open(io.BytesIO(payload)) as image:
        return image.convert("RGBA").tobytes()


@pytest.mark.parametrize("portrait", [False, True])
def test_shared_code_compositor_has_literal_start_mid_end_pixels_and_random_seek(portrait):
    layout, timeline = code_documents(portrait)
    style, _, root = load_bundle()
    width, height = (720, 1280) if portrait else (1280, 720)
    x, y = ("90", "298.6667") if portrait else ("80", "218.6667")
    frames = {}
    for time, text in [(2000, ""), (2450, "e\u0301"), (2900, "e\u0301x")]:
        actual = compose_png_frame(layout, timeline, time)
        literal = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
            f'<rect width="{width}" height="{height}" fill="{style.colors["paper"]}"/>'
            f'<text x="{x}" y="{y}" fill="{style.colors["ink"]}" font-family="JetBrains Mono" '
            f'font-size="18.6667" font-weight="400" xml:space="preserve">{text}</text></svg>')
        expected = bytes(resvg_py.svg_to_bytes(svg_string=literal,
            font_files=[str(root / "code-font-v1/fonts/JetBrainsMono-Regular.ttf")], skip_system_fonts=True))
        assert rgba(actual.png) == rgba(expected)
        frames[time] = (compose_svg_frame(layout, timeline, time).svg, actual.png)
    for time in [2900, 2000, 2450, 2900, 2450, 2000]:
        assert (compose_svg_frame(layout, timeline, time).svg,
                compose_png_frame(layout, timeline, time).png) == frames[time]
    assert "JetBrains Mono" in frames[2900][0]


@pytest.mark.parametrize("portrait", [False, True])
def test_shared_code_frozen_and_source_paths_have_identical_svg_and_png(portrait):
    raw_layout, raw_timeline = code_documents(portrait)
    layout = ExecutableLayoutV2.model_validate(raw_layout)
    timeline = ResolvedVisualTimelineV2.model_validate(raw_timeline)
    inputs = verify_split_paint_inputs(layout, {})
    for time in [2000, 2450, 2900]:
        snapshot = evaluate_frame(raw_layout, raw_timeline, time)
        frozen = _compose_validated_svg_frame(layout, timeline, snapshot, {}, split_inputs=inputs)
        source = compose_svg_frame(raw_layout, raw_timeline, time)
        assert frozen == source
        assert _rasterize_svg_frame(layout, frozen, split_inputs=inputs) == compose_png_frame(raw_layout, raw_timeline, time)


def test_bare_legacy_code_parses_but_cannot_execute_even_before_its_action():
    layout, timeline = code_documents()
    layout["objects"][0].pop("code_payload")
    ExecutableLayoutV2.model_validate(layout)
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(ValueError, match="code_payload"):
        compose_svg_frame(layout, timeline, 0)


def test_code_adapter_does_not_implicitly_admit_unimplemented_text_subtypes():
    layout, _timeline = code_documents()
    layout["objects"][0].update(object_type="callout")
    layout["objects"][0].pop("code_payload")
    obj = ExecutableLayoutV2.model_validate(layout).objects[0]
    with pytest.raises(ValueError, match="Split callout construction adapter is not implemented"):
        split_primitive(obj, "write")


@pytest.mark.parametrize("verb", ["draw", "progressive_reveal", "count"])
def test_code_cannot_claim_an_incompatible_construction_verb(verb):
    layout, timeline = code_documents()
    timeline["actions"][0]["action"]["verb"] = verb
    with pytest.raises(ValueError):
        compose_svg_frame(layout, timeline, 0)


def replace_code_text(layout, timeline, text, *, spans=None):
    obj = layout["objects"][0]
    obj["text"] = text
    obj["code_payload"]["lines"] = [{"line_id": f"row-{index}", "spans": [
        {"span_id": f"run-{index}", "role": "plain", "text": line}] if line else []}
        for index, line in enumerate(text.split("\n"))]
    if spans is not None:
        obj["code_payload"]["mode"] = "tokens"
        obj["code_payload"]["lines"][0]["spans"] = spans
    timeline["layout_sha256"] = digest(layout)


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("text,want", [
    ("x\t=\t1", ((0, "x"), (44.8, "="), (89.6, "1"))),
    ("\t\tx", ((89.6, "x"),)),
    ("x\t", ((0, "x"),)),
])
def test_code_compositor_multi_consecutive_and_end_tabs_have_literal_positions(portrait, text, want):
    layout, timeline = code_documents(portrait)
    replace_code_text(layout, timeline, text)
    style, _, root = load_bundle()
    width, height = (720, 1280) if portrait else (1280, 720)
    x, y = (90, "298.6667") if portrait else (80, "218.6667")
    body = "".join(f'<text x="{x + delta:g}" y="{y}">{part}</text>' for delta, part in want)
    literal = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
        f'<rect width="{width}" height="{height}" fill="{style.colors["paper"]}"/>'
        f'<g fill="{style.colors["ink"]}" font-family="JetBrains Mono" font-size="18.6667" '
        f'font-weight="400" xml:space="preserve">{body}</g></svg>')
    expected = bytes(resvg_py.svg_to_bytes(svg_string=literal,
        font_files=[str(root / "code-font-v1/fonts/JetBrainsMono-Regular.ttf")], skip_system_fonts=True))
    assert rgba(compose_png_frame(layout, timeline, 2900).png) == rgba(expected)


@pytest.mark.parametrize("portrait", [False, True])
def test_code_compositor_all_authored_roles_preserve_explicit_color_transitions(portrait):
    values = [("plain", "x", "ink"), ("keyword", "y", "accent"), ("identifier", "z", "ink"),
              ("literal", "1", "success"), ("comment", "#", "muted"),
              ("operator", "=", "accent"), ("punctuation", ";", "ink")]
    layout, timeline = code_documents(portrait)
    replace_code_text(layout, timeline, "xyz1#=;", spans=[
        {"span_id": role, "role": role, "text": text} for role, text, _ in values])
    style, _, root = load_bundle()
    width, height = (720, 1280) if portrait else (1280, 720)
    x, y = (90, "298.6667") if portrait else (80, "218.6667")
    body = "".join(f'<text x="{x + delta:g}" y="{y}" fill="{style.colors[color]}">{text}</text>'
                   for delta, (_, text, color) in zip([0, 11.2, 22.4, 33.6, 44.8, 56, 67.2], values, strict=True))
    literal = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
        f'<rect width="{width}" height="{height}" fill="{style.colors["paper"]}"/>'
        f'<g font-family="JetBrains Mono" font-size="18.6667" font-weight="400" '
        f'xml:space="preserve">{body}</g></svg>')
    expected = bytes(resvg_py.svg_to_bytes(svg_string=literal,
        font_files=[str(root / "code-font-v1/fonts/JetBrainsMono-Regular.ttf")], skip_system_fonts=True))
    assert rgba(compose_png_frame(layout, timeline, 2900).png) == rgba(expected)


@pytest.mark.parametrize("text,width", [("x\t", 20), ("x   ", 12), ("Ω", 1)])
def test_code_compositor_preflight_checks_all_native_bounds_before_the_first_action(text, width):
    layout, timeline = code_documents()
    replace_code_text(layout, timeline, text)
    layout["objects"][0]["geometry"]["bounds"]["width"] = width
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(ValueError, match="code.*(advance|bounds)"):
        compose_svg_frame(layout, timeline, 0)


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["group", "clip", "mask"])
def test_code_uses_real_parent_transform_and_clip_or_mask_aperture(portrait, kind):
    from test_v2_group_hierarchy import grouped_documents

    layout, timeline = code_documents(portrait)
    obj = layout["objects"][0]
    shell = deepcopy(grouped_documents()[0]["objects"][3])
    shell.update(object_type=kind, child_ids=[obj["object_id"]])
    shell["geometry"]["bounds"] = deepcopy(obj["geometry"]["bounds"])
    shell["transform"]["position"] = {"x": 0 if kind == "mask" else 30, "y": 0 if kind == "mask" else 10}
    if kind == "clip":
        shell["geometry"]["bounds"]["width"] = 12
    if kind == "mask":
        shell.update(mask_mode="alpha", mask_source_object_id="code-aperture",
                     mask_coordinate_space="parent_local", invert=False, feather_px=0)
        source = {key: deepcopy(value) for key, value in obj.items()
                  if key not in {"text", "items", "code_payload"}}
        source.update(object_id="code-aperture", object_type="rectangle", path_data=None,
                      visible=True, initial_state="visible", anchors=[],
                      style={"stroke": None, "fill": None, "text": None, "effect": None})
        source["geometry"]["bounds"]["width"] = 12
        layout["objects"].append(source)
        timeline["initial_object_states"].append({"object_id": source["object_id"],
            "visible": True, "state": "visible", "state_version": 1})
    obj["parent_id"] = shell["object_id"]
    layout["objects"].append(shell)
    layout["boards"][0]["object_ids"] = [item["object_id"] for item in layout["objects"]]
    timeline["initial_object_states"].append({"object_id": shell["object_id"],
        "visible": True, "state": "visible", "state_version": 1})
    timeline["layout_sha256"] = digest(layout)
    style, _, root = load_bundle()
    width, height = (720, 1280) if portrait else (1280, 720)
    x, top, baseline = (90, 280, "298.6667") if portrait else (80, 200, "218.6667")
    text = (f'<text x="{x}" y="{baseline}" fill="{style.colors["ink"]}" '
            f'font-family="JetBrains Mono" font-size="18.6667" font-weight="400" '
            f'xml:space="preserve">e\u0301x</text>')
    if kind == "mask":
        body = (f'<defs><mask id="oracle" maskUnits="userSpaceOnUse" maskContentUnits="userSpaceOnUse" '
                f'style="mask-type:alpha"><rect x="{x}" y="{top}" width="12" height="160" fill="white"/>'
                f'</mask></defs><g mask="url(#oracle)">{text}</g>')
    elif kind == "clip":
        body = (f'<defs><clipPath id="oracle" clipPathUnits="userSpaceOnUse">'
                f'<rect x="{x}" y="{top}" width="12" height="160"/></clipPath></defs>'
                f'<g transform="translate(30 10)" clip-path="url(#oracle)">{text}</g>')
    else:
        body = f'<g transform="translate(30 10)">{text}</g>'
    literal = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
               f'<rect width="{width}" height="{height}" fill="{style.colors["paper"]}"/>{body}</svg>')
    expected = bytes(resvg_py.svg_to_bytes(svg_string=literal,
        font_files=[str(root / "code-font-v1/fonts/JetBrainsMono-Regular.ttf")], skip_system_fonts=True))
    assert rgba(compose_png_frame(layout, timeline, 2900).png) == rgba(expected)


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("verb", ["move", "fade"])
def test_completed_code_keeps_existing_motion_and_fade_pixels_and_seek(portrait, verb):
    layout, timeline = code_documents(portrait)
    trigger = {"kind": "absolute", "at_ms": 3000}
    action = deepcopy(timeline["actions"][0]["action"])
    action.pop("annotation", None)
    action.update(action_id="code-after", verb=verb, trigger=trigger, expected_state="visible",
                  destination=(deepcopy(layout["objects"][0]["transform"]) if verb == "move" else None),
                  opacity=.2 if verb == "fade" else None)
    if verb == "move":
        action["destination"]["position"] = {"x": 40, "y": 0}
    timeline["actions"].append({"action": action, "start_ms": 3000, "end_ms": 4000,
        "resolved_trigger": {"source": trigger, "alignment_anchor_ms": 3000,
        "resolved_at_ms": 3000, "confidence": 1, "exact": True,
        "matched_text": None, "matched_occurrence": None}})
    timeline["coverage"][0]["action_ids"].append("code-after")
    style, _, root = load_bundle()
    width, height = (720, 1280) if portrait else (1280, 720)
    x, y = ("90", "298.6667") if portrait else ("80", "218.6667")
    snapshots = {}
    for time, shift, opacity in [(3000, 0, 1), (3500, 20 if verb == "move" else 0, .6 if verb == "fade" else 1),
                                  (4000, 40 if verb == "move" else 0, .2 if verb == "fade" else 1)]:
        literal = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
            f'<rect width="{width}" height="{height}" fill="{style.colors["paper"]}"/>'
            f'<g transform="translate({shift} 0)" opacity="{opacity}"><text x="{x}" y="{y}" '
            f'fill="{style.colors["ink"]}" font-family="JetBrains Mono" font-size="18.6667" '
            f'font-weight="400" xml:space="preserve">e\u0301x</text></g></svg>')
        expected = bytes(resvg_py.svg_to_bytes(svg_string=literal,
            font_files=[str(root / "code-font-v1/fonts/JetBrainsMono-Regular.ttf")], skip_system_fonts=True))
        actual = compose_png_frame(layout, timeline, time).png
        assert rgba(actual) == rgba(expected)
        snapshots[time] = actual
    for time in [4000, 3000, 3500, 3000]:
        assert compose_png_frame(layout, timeline, time).png == snapshots[time]


def test_code_camera_observes_without_changing_completed_code_state():
    from test_v2_camera_action import append_camera

    layout, timeline = code_documents()
    append_camera(timeline, "code-camera", "camera_cut", 6000, 6500, target="object-label", framing="close")
    timeline["actions"][-1]["action"].update(coverage_id="coverage-2", source_instruction_id="instruction-2",
        fallback={"fallback_id": "fallback-2", "on_failure": "block"})
    before = evaluate_frame(layout, timeline, 5999)
    after = evaluate_frame(layout, timeline, 8000)
    assert before.object("object-label") == after.object("object-label")
    assert before.camera != after.camera
    assert compose_png_frame(layout, timeline, 5999).png != compose_png_frame(layout, timeline, 8000).png


def test_frozen_code_compositor_does_not_reopen_fonts_or_source_resources(monkeypatch):
    raw_layout, raw_timeline = code_documents()
    layout = ExecutableLayoutV2.model_validate(raw_layout)
    timeline = ResolvedVisualTimelineV2.model_validate(raw_timeline)
    inputs = verify_split_paint_inputs(layout, {})
    snapshot = evaluate_frame(raw_layout, raw_timeline, 2900)
    expected = compose_png_frame(raw_layout, raw_timeline, 2900)

    def no_original(path):
        raise AssertionError(f"frozen code reopened {path}")

    monkeypatch.setattr(Path, "read_bytes", no_original)
    frame = _compose_validated_svg_frame(layout, timeline, snapshot, {}, split_inputs=inputs)
    assert _rasterize_svg_frame(layout, frame, split_inputs=inputs) == expected


@pytest.mark.parametrize("bad", ["code-font-v1/code-font.json", "code-font-v1/fonts/JetBrainsMono-Regular.ttf",
                                  "code-font-v1/fonts/OFL-JetBrainsMono.txt"])
def test_source_code_compositor_rechecks_manifest_font_and_license_after_prior_success(monkeypatch, bad):
    layout, timeline = code_documents()
    compose_png_frame(layout, timeline, 2900)
    _, _, root = load_bundle()
    original = Path.read_bytes

    def changed(path):
        payload = original(path)
        return payload + b"changed" if path.resolve() == (root / bad).resolve() else payload

    monkeypatch.setattr(Path, "read_bytes", changed)
    with pytest.raises(ValueError, match="code.font.*checksum"):
        compose_png_frame(layout, timeline, 2900)


@pytest.mark.parametrize("portrait", [False, True])
def test_code_write_prefix_before_after_tab_lf_and_combined_grapheme_is_exact(portrait):
    import xml.etree.ElementTree as ET

    layout, timeline = code_documents(portrait)
    replace_code_text(layout, timeline, "x\t=\ne\u0301")
    for time, visible in [(2000, ""), (2180, "x"), (2360, "x"),
                          (2540, "x="), (2720, "x="), (2900, "x=e\u0301")]:
        root = ET.fromstring(compose_svg_frame(layout, timeline, time).svg)
        code = next((node for node in root.iter() if node.attrib.get("data-object-id") == "object-label"), None)
        assert ("".join(code.itertext()) if code is not None else "") == visible
