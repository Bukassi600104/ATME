"""Task10 owning proof: real offline pixels, not a green partial-matrix label."""

import html
import importlib.util
import io
import json
import socket
import sys
import types
import xml.etree.ElementTree as ET
from copy import deepcopy
from pathlib import Path

import pytest
import resvg_py
from PIL import Image
from test_v2_character_assembly_compositor import original_pose_documents
from test_v2_illustration_assembly_compositor import original_illustration_documents
from test_v2_registry_binding import registry_object
from test_v2_registry_illustrations import illustration_documents
from test_v2_split_callout_family import callout_split_fixture
from test_v2_split_chart_family import chart_split_family, native_chart_oracle
from test_v2_split_code_family import code_split_family
from test_v2_split_container_family import literal_mask_oracle, mask_split_family
from test_v2_split_families import GEOMETRY_KINDS, authored_geometry, n
from test_v2_split_list_family import (
    literal_structured_frame,
    literal_text_list_frame,
    structured_list_split_family,
    text_list_split_family,
)
from test_v2_split_media_family import literal_pixels
from test_v2_split_reusable_family import literal_reusable_oracle, reusable_split_family
from test_v2_split_visual_family import illustration_boundary, native_reference
from test_v2_split_visual_family_matrix import STATE_CASES
from test_v2_technical_frame_compositor import composite_documents
from test_v2_technical_frame_contract import CASES
from v2_fixtures import digest

from atme.render.v2_svg import compose_png_frame

VISUAL_CASES = (
    ("illustration", "reveal"), ("illustration", "enter"),
    ("character", "reveal"), ("character", "enter"), ("character", "draw"),
    ("technical", "reveal"), ("technical", "enter"),
)
CONTAINER_CASES = ("group", "clip", "mask-source", "mask-result", "composition", "instance")
EVIDENCE_CASES = ("plain", "annotated", "source")
CONNECTOR_CASES = ("arrow", "network", "pointer")
CONNECTOR_ROUTES = ("straight", "elbow", "curve")
VISUAL_STATE_CASES = [
    (family, kind, state, owner, mode)
    for family, kind, state in STATE_CASES
    for owner in ("source", "part-1", "part-2")
    for mode in (("reveal",) if owner == "source" else
                 ("reveal", "enter", "draw") if family == "character" else ("reveal", "enter"))
]
APERTURE_KINDS = ("group", "clip", "mask")
REGISTRY_ROLES = (("source", "reveal"), ("part-1", "reveal"), ("part-1", "enter"),
                  ("part-2", "reveal"), ("part-2", "enter"))


def split_benchmark():
    path = Path(__file__).resolve().parents[2] / "bench/verify_v2_split.py"
    assert path.is_file(), "Task10 offline Split benchmark is not implemented"
    spec = importlib.util.spec_from_file_location("split_acceptance_benchmark", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("mode", ["draw", "reveal", "enter"])
@pytest.mark.parametrize("kind", GEOMETRY_KINDS)
def test_split_geometry_offline_pixels_and_shuffled_seek(tmp_path, portrait, mode, kind, monkeypatch):
    benchmark = split_benchmark()
    observed = []
    original = benchmark._replay_split_chronology

    def primitive_replay(*args, **kwargs):
        observed.append(kwargs["timeline"])
        return original(*args, **kwargs)

    monkeypatch.setattr(benchmark, "_replay_split_chronology", primitive_replay)
    record = benchmark.geometry_case(tmp_path, portrait, kind, mode)
    assert observed == [None]
    assert record["profile"] == ("SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9")
    assert record["seek_order_ms"] == [40, 0, 12, 39, 24, 32, 12, 0, 40]
    assert set(record["frames"]) == {"0", "12", "24", "32", "39", "40"}
    assert record["network_forbidden"] is True
    assert record["immutable_input_keys_unchanged"] is True
    assert len(record["paint_inputs_sha256"]) == 64
    assert all(value >= 0 for value in record["sample_compose_raster_ms"])
    assert len(record["sample_compose_raster_ms"]) == 9
    assert record["frames"]["0"]["png_sha256"] != record["frames"]["40"]["png_sha256"]
    # Literal source/midpoint/completion oracles never use the compositor.
    width, height = (720, 1280) if portrait else (1280, 720)
    boxes = ((160, 80), (100, 400), (160, 400)) if portrait else ((80, 100), (400, 100), (460, 100))
    style = json.loads(record["style_json"])
    colors = style["colors"]
    for at, fraction, source_alpha in ((0, 0, 1), (12, .5, .8333), (40, 1, 0)):
        body = f'<rect width="{width}" height="{height}" fill="#FAF8F1"/>'
        for index, ((x, y), color) in enumerate(zip(boxes, (colors["ink"], colors["accent"], colors["attention"]))):
            alpha = source_alpha if index == 0 else 1
            if not alpha or index > 0 and not fraction:
                continue
            *_, markup, length = authored_geometry(kind, (x, y, 80, 120))
            dash = (f' stroke-dasharray="{n(length)} {n(length)}" stroke-dashoffset="{n(length/2)}"'
                    if index and fraction == .5 and mode == "draw" else "")
            weight = style["strokes"]["emphasis_px"] * 2/3 if kind == "highlight" else 4 * 2/3
            inner = (f'{markup} fill="none" stroke="{color}" stroke-width="{n(weight)}" '
                     f'stroke-linecap="round" stroke-linejoin="round"{dash}/>')
            if index and fraction == .5 and mode in {"reveal", "enter"}:
                inner = (f'<defs><clipPath id="oracle-{index}"><rect x="{x}" y="{y}" width="40" '
                         f'height="120"/></clipPath></defs><g clip-path="url(#oracle-{index})">{inner}</g>')
            transform = ' transform="translate(-40 0)"' if index and fraction == .5 and mode == "enter" else ""
            body += f'<g opacity="{alpha}"{transform}>{inner}</g>'
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">{body}</svg>'
        expected = resvg_py.svg_to_bytes(svg_string=svg, skip_system_fonts=True)
        with Image.open(io.BytesIO(expected)) as want, Image.open(record["frames"][str(at)]["png_path"]) as got:
            assert got.size == (width, height)
            assert got.convert("RGBA").tobytes() == want.convert("RGBA").tobytes()


def test_split_offline_cli_requires_explicit_output_directory():
    with pytest.raises(SystemExit) as error:
        split_benchmark().main([])
    assert error.value.code == 2


def test_split_full_acceptance_cannot_succeed_with_unexecuted_matrix(tmp_path):
    result = split_benchmark().write_report(tmp_path, [])
    assert result != 0
    report = json.loads((tmp_path / "split-acceptance.json").read_text(encoding="utf-8"))
    assert report["status"] == "INCOMPLETE"
    assert report["final_acceptance"] is False
    assert report["missing_required_proofs"]
    assert report["cases"] == []


def test_split_offline_case_does_not_overwrite_prior_evidence(tmp_path):
    benchmark = split_benchmark()
    first = benchmark.geometry_case(tmp_path, False, "rectangle", "reveal")
    original = Path(first["frames"]["40"]["png_path"]).read_bytes()
    with pytest.raises(FileExistsError):
        benchmark.geometry_case(tmp_path, False, "rectangle", "reveal")
    assert Path(first["frames"]["40"]["png_path"]).read_bytes() == original


def test_split_benchmark_rejects_preloaded_foreign_imports(monkeypatch):
    benchmark = split_benchmark()
    foreign = types.ModuleType("atme.foreign_acceptance_probe")
    foreign.__file__ = "C:/outside-current-worktree/atme/foreign.py"
    monkeypatch.setitem(sys.modules, foreign.__name__, foreign)
    assert hasattr(benchmark, "verify_import_origins"), "Task10 benchmark lacks isolated-origin enforcement"
    with pytest.raises(ValueError, match="isolated.*origin"):
        benchmark.verify_import_origins()


@pytest.mark.parametrize("helper", ["test_v2_split_action", "test_v2_split_families"])
def test_split_benchmark_rejects_preloaded_foreign_fixture_helpers(monkeypatch, helper):
    foreign = types.ModuleType(helper)
    foreign.__dict__.update(vars(sys.modules[helper]))
    foreign.__file__ = f"C:/outside-current-worktree/tests/{helper}.py"
    monkeypatch.setitem(sys.modules, helper, foreign)
    benchmark = split_benchmark()
    with pytest.raises(ValueError, match="isolated.*origin"):
        benchmark.verify_import_origins()


@pytest.mark.parametrize("resolver", ["getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr", "getnameinfo"])
def test_split_offline_geometry_denies_direct_dns_without_network(tmp_path, monkeypatch, resolver):
    benchmark = split_benchmark()
    original = benchmark.geometry_split_family

    def escaped_dns(*args):
        raise RuntimeError("DNS resolver escaped the offline guard")

    def fixture_with_dns(*args):
        # A backend sentinel prevents real network even in the RED run.
        getattr(socket, resolver)("atme.invalid")
        return original(*args)

    monkeypatch.setattr(socket, resolver, escaped_dns)
    monkeypatch.setattr(benchmark, "geometry_split_family", fixture_with_dns)
    with pytest.raises(AssertionError, match="Offline Split proof attempted network"):
        benchmark.geometry_case(tmp_path, False, "rectangle", "draw")


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("mode", ["write", "reveal", "enter"])
@pytest.mark.parametrize("kind", ["text", "flat", "structured", "nested"])
def test_split_text_list_offline_literal_pixels_and_seek(tmp_path, portrait, mode, kind):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "text_case"), "Task10 authored text/list proof is missing"
    record = benchmark.text_case(tmp_path, portrait, kind, mode)
    assert record["family"] == "text-list"
    assert record["profile"] == ("SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9")
    assert record["network_forbidden"] and record["immutable_input_keys_unchanged"]
    assert record["seek_order_ms"] == [40, 0, 12, 39, 24, 32, 12, 0, 40]
    from atme.render.style_bundle import load_bundle

    font = load_bundle()[2] / "fonts/AtkinsonHyperlegible-Regular.otf"
    if kind in {"text", "flat"}:
        *_, boxes = text_list_split_family(portrait, mode, flat=kind == "flat")
    else:
        *_, boxes = structured_list_split_family(portrait, mode, nested=kind == "nested")
    for at in (0, 12, 40):
        expected = (literal_text_list_frame(portrait, kind == "flat", mode, at, boxes, font)
                    if kind in {"text", "flat"} else
                    literal_structured_frame(portrait, kind == "nested", mode, at, boxes, font))
        with Image.open(io.BytesIO(expected)) as want, Image.open(record["frames"][str(at)]["png_path"]) as got:
            assert got.convert("RGBA").tobytes() == want.convert("RGBA").tobytes()


def test_split_text_proof_refuses_unauthored_variant(tmp_path):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "text_case"), "Task10 authored text/list proof is missing"
    with pytest.raises(ValueError, match="Unsupported.*text/list"):
        benchmark.text_case(tmp_path, False, "not-authored", "write")


def test_split_text_list_diagnostic_report_cannot_grant_final_acceptance(tmp_path):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "text_case"), "Task10 authored text/list proof is missing"
    record = benchmark.text_case(tmp_path, False, "text", "write")
    assert benchmark.write_report(tmp_path, [record], diagnostic="text-list") == 0
    report = json.loads((tmp_path / "split-text-list-diagnostic.json").read_text(encoding="utf-8"))
    assert report["status"] == "DIAGNOSTIC ONLY"
    assert report["final_acceptance"] is False
    assert report["cases"][0]["case_id"] == record["case_id"]
    assert report["missing_required_proofs"]


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("mode", ["write", "reveal", "enter"])
@pytest.mark.parametrize("tokens", [False, True])
def test_split_code_offline_literal_glyph_pixels_and_seek(tmp_path, portrait, mode, tokens):
    from atme.render.style_bundle import load_bundle

    benchmark = split_benchmark()
    assert hasattr(benchmark, "code_case"), "Task10 authored Code proof is missing"
    record = benchmark.code_case(tmp_path, portrait, "tokens" if tokens else "plain", mode)
    assert record["family"] == "code"
    assert record["profile"] == ("SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9")
    assert record["seek_order_ms"] == [40, 0, 12, 39, 24, 32, 12, 0, 40]
    assert record["network_forbidden"] and record["immutable_input_keys_unchanged"]
    layout, *_, boxes = code_split_family(portrait, mode, tokens)
    style, _, root = load_bundle()
    width, height = layout.output_profile.width, layout.output_profile.height
    for at, source_alpha in ((0, 1), (12, .8333), (40, 0)):
        body = [f'<rect width="{width}" height="{height}" fill="{style.colors["paper"]}"/>']
        for key in ("source", "part-1", "part-2"):
            if key == "source" and not source_alpha or key != "source" and at == 0:
                continue
            x, y, w, h = boxes[key]
            short = key != "source" and at == 12 and mode == "write"
            if key == "source":
                glyphs = [(0, "src", "ink")]
            elif key == "part-1":
                glyphs = [(0, "e\u0301", "accent" if tokens else "ink")]
                if not short:
                    glyphs.append((11.2, "x", "ink"))
            else:
                glyphs = [(0, "x", "ink")]
                if not short:
                    glyphs.extend(((11.2, "=", "accent" if tokens else "ink"),
                                   (22.4, "y", "success" if tokens else "ink")))
            inner = "".join(f'<text x="{x+dx:g}" y="{y+56/3:.4f}" fill="{style.colors[color]}" '
                'font-family="JetBrains Mono" font-size="18.6667" font-weight="400" '
                f'xml:space="preserve">{html.escape(text)}</text>' for dx, text, color in glyphs)
            if key != "source" and at == 12 and mode in {"reveal", "enter"}:
                inner = (f'<defs><clipPath id="oracle-{key}"><rect x="{x:g}" y="{y:g}" '
                    f'width="{w/2:g}" height="{h:g}"/></clipPath></defs>'
                    f'<g clip-path="url(#oracle-{key})">{inner}</g>')
            shift = ' transform="translate(-40 0)"' if key != "source" and at == 12 and mode == "enter" else ""
            body.append(f'<g opacity="{source_alpha if key == "source" else 1}"{shift}>{inner}</g>')
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">{"".join(body)}</svg>'
        expected = bytes(resvg_py.svg_to_bytes(svg_string=svg,
            font_files=[str(root / "code-font-v1/fonts/JetBrainsMono-Regular.ttf")], skip_system_fonts=True))
        with Image.open(io.BytesIO(expected)) as want, Image.open(record["frames"][str(at)]["png_path"]) as got:
            assert got.convert("RGBA").tobytes() == want.convert("RGBA").tobytes()


def literal_callout_frame(layout, mode, boxed, at):
    """Authored SVG oracle: no renderer geometry, clipping or state helpers."""
    from atme.render.style_bundle import load_bundle

    style, _, root = load_bundle()
    color, paper = style.colors["ink"], style.colors["paper"]
    width, height = layout.output_profile.width, layout.output_profile.height
    objects = {obj.object_id: obj for obj in layout.objects}
    target = objects["callout-target"].geometry.bounds
    body = [f'<rect width="{width}" height="{height}" fill="{paper}"/>',
        (f'<rect x="{target.x:g}" y="{target.y:g}" width="80" height="80" fill="{paper}" '
         f'stroke="{color}" stroke-width="2.6667" stroke-linecap="round" stroke-linejoin="round"/>')]
    source_alpha = {1: 1, 13: .8333, 41: 0}[at]
    for key in ("source", "part-1", "part-2"):
        if key == "source" and not source_alpha or key != "source" and at == 1:
            continue
        bounds = objects[key].geometry.bounds
        x, y, w, h = bounds.x, bounds.y, bounds.width, bounds.height
        text = {"source": "src", "part-1": "A\u0301B", "part-2": "x=y"}[key]
        if key != "source" and at == 13 and mode == "write":
            text = "A\u0301" if key == "part-1" else "x"
        inset = 32/3 if boxed else 0
        glyph = (f'<text x="{x+inset:.4f}" y="{y+inset+64/3:.4f}" fill="{color}" '
            'font-family="Atkinson Hyperlegible" font-size="21.3333" font-weight="400" '
            f'xml:space="preserve">{html.escape(text)}</text>')
        box = (f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="8" '
            f'fill="{paper}" stroke="{color}" stroke-width="2.6667" '
            'stroke-linecap="round" stroke-linejoin="round"/>') if boxed else ""
        inner = box + glyph
        if key != "source" and at == 13 and mode in {"reveal", "enter"}:
            inner = (f'<defs><clipPath id="oracle-{key}"><rect x="{x:g}" y="{y:g}" '
                f'width="{w/2:g}" height="{h:g}"/></clipPath></defs>'
                f'<g clip-path="url(#oracle-{key})">{inner}</g>')
        shift = ' transform="translate(-40 0)"' if key != "source" and at == 13 and mode == "enter" else ""
        body.append(f'<g opacity="{source_alpha if key == "source" else 1}"{shift}>{inner}</g>')
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">{"".join(body)}</svg>'
    return resvg_py.svg_to_bytes(svg_string=svg,
        font_files=[str(root / "fonts/AtkinsonHyperlegible-Regular.otf")], skip_system_fonts=True)


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("mode", ["write", "reveal", "enter"])
@pytest.mark.parametrize("boxed", [False, True])
def test_split_callout_offline_prefix_clock_pixels_and_readonly_leaders(tmp_path, portrait, mode, boxed):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "callout_case"), "Task10 authored Callout proof is missing"
    record = benchmark.callout_case(tmp_path, portrait, "boxed" if boxed else "unboxed", mode)
    assert record["family"] == "callout"
    assert record["profile"] == ("SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9")
    assert record["seek_order_ms"] == [41, 1, 13, 40, 25, 33, 13, 1, 41]
    assert (record["action_start_ms"], record["action_end_ms"]) == (1, 41)
    assert record["chronology_action_ids"] == ["source-pointer-exit", "split-1"]
    assert record["network_forbidden"] and record["immutable_input_keys_unchanged"]
    layout, *_ = callout_split_fixture(portrait, mode, boxed)
    for at in (1, 13, 41):
        expected = literal_callout_frame(layout, mode, boxed, at)
        frame = record["frames"][str(at)]
        with Image.open(io.BytesIO(expected)) as want, Image.open(frame["png_path"]) as got:
            assert got.convert("RGBA").tobytes() == want.convert("RGBA").tobytes()
        svg = Path(frame["svg_path"]).read_text(encoding="utf-8")
        assert 'data-object-id="leader-' not in svg
    for frame in record["frames"].values():
        assert frame["state_versions"]["leader-source"] == 2
        assert frame["state_versions"]["leader-part-1"] == frame["state_versions"]["leader-part-2"] == 1
        for key in ("leader-source", "leader-part-1", "leader-part-2", "callout-target"):
            assert frame["state_sha256"][key] == record["frames"]["1"]["state_sha256"][key]
    assert record["frames"]["1"]["state_versions"]["source"] == 1
    assert record["frames"]["41"]["state_versions"]["source"] == 2


@pytest.mark.parametrize("entry", ["code_case", "callout_case"])
def test_split_code_callout_proof_refuses_unauthored_variant(tmp_path, entry):
    benchmark = split_benchmark()
    assert hasattr(benchmark, entry), f"Task10 {entry} proof is missing"
    with pytest.raises(ValueError, match="Unsupported.*variant"):
        getattr(benchmark, entry)(tmp_path, False, "not-authored", "write")


def test_split_callout_proof_cannot_omit_actual_prefix_exit(tmp_path, monkeypatch):
    from atme.store.contracts_v2 import ResolvedVisualTimelineV2

    benchmark = split_benchmark()
    assert hasattr(benchmark, "callout_case"), "Task10 authored Callout proof is missing"
    original = benchmark.callout_split_fixture

    def without_exit(*args, **kwargs):
        layout, initial, before, prefix, split, timeline, hashes = original(*args, **kwargs)
        removed = {row.action.action_id for row in prefix}
        raw = timeline.model_dump(mode="json")
        raw["actions"] = [row for row in raw["actions"] if row["action"]["action_id"] not in removed]
        for row in raw["coverage"]:
            row["action_ids"] = [key for key in row["action_ids"] if key not in removed]
        coherent = ResolvedVisualTimelineV2.model_validate(raw)
        assert [row.action.action_id for row in coherent.actions] == [split.action.action_id]
        assert all(row.action_ids == [split.action.action_id] for row in coherent.coverage)
        return layout, initial, before, prefix, split, coherent, hashes

    monkeypatch.setattr(benchmark, "callout_split_fixture", without_exit)
    with pytest.raises(ValueError, match="^Split submitted basis differs from actual observed history$"):
        benchmark.callout_case(tmp_path, False, "unboxed", "write")


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("mode", ["draw", "reveal", "enter"])
@pytest.mark.parametrize("kind", ["bars", "line"])
def test_split_chart_offline_authored_primitive_pixels_and_seek(tmp_path, portrait, mode, kind):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "chart_case"), "Task10 authored Chart proof is missing"
    record = benchmark.chart_case(tmp_path, portrait, kind, mode)
    assert record["family"] == "chart"
    assert record["profile"] == ("SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9")
    assert record["seek_order_ms"] == [40, 0, 12, 39, 24, 32, 12, 0, 40]
    assert record["network_forbidden"] and record["immutable_input_keys_unchanged"]
    layout, _, split, _, _ = chart_split_family(portrait, kind, mode)
    assert [row.object_id for row in split.action.split_policy.results] == ["part-2", "part-1"]
    inputs = benchmark.verify_split_paint_inputs(layout, {})
    for at in (0, 12, 40):
        expected = native_chart_oracle(layout, inputs, at, mode)
        frame = record["frames"][str(at)]
        with Image.open(io.BytesIO(expected)) as want, Image.open(frame["png_path"]) as got:
            assert got.convert("RGBA").tobytes() == want.convert("RGBA").tobytes()
        tree = ET.fromstring(Path(frame["svg_path"]).read_text(encoding="utf-8"))
        order = [node.attrib["data-object-id"] for node in tree.iter() if "data-object-id" in node.attrib]
        assert order == {0: ["source"], 12: ["source", "part-1", "part-2"], 40: ["part-1", "part-2"]}[at]
        if at == 12:
            first = next(node for node in tree.iter() if node.attrib.get("data-object-id") == "part-1")
            point_ids = [node.attrib["data-chart-point"] for node in first.iter() if "data-chart-point" in node.attrib]
            assert point_ids == (["first"] if mode == "draw" else ["first", "second"])
            assert ("clip-path" in first.attrib) == (mode != "draw")


def test_split_chart_proof_refuses_unauthored_variant(tmp_path):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "chart_case"), "Task10 authored Chart proof is missing"
    with pytest.raises(ValueError, match="Unsupported.*Chart variant"):
        benchmark.chart_case(tmp_path, False, "not-authored", "draw")


def test_split_chart_diagnostic_report_cannot_grant_final_acceptance(tmp_path):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "chart_case"), "Task10 authored Chart proof is missing"
    record = benchmark.chart_case(tmp_path, False, "bars", "draw")
    assert benchmark.write_report(tmp_path, [record], diagnostic="chart") == 0
    report = json.loads((tmp_path / "split-chart-diagnostic.json").read_text(encoding="utf-8"))
    assert report["status"] == "DIAGNOSTIC ONLY"
    assert report["final_acceptance"] is False
    assert report["cases"][0]["case_id"] == record["case_id"]
    assert report["missing_required_proofs"]


def test_split_chart_cli_routes_only_the_authored_diagnostic_matrix(tmp_path, monkeypatch):
    benchmark = split_benchmark()
    expected = [(portrait, kind, mode) for portrait in (False, True) for kind in ("bars", "line")
                for mode in ("draw", "reveal", "enter")]
    calls = []

    def route(directory, portrait, kind, mode):
        assert directory == tmp_path
        calls.append((portrait, kind, mode))
        return {"route": (portrait, kind, mode)}

    def report(directory, cases, *, diagnostic):
        assert directory == tmp_path and diagnostic == "chart"
        assert cases == [{"route": row} for row in expected]
        return 0

    def wrong_family(*args, **kwargs):
        pytest.fail("Chart CLI dispatched a different family")

    monkeypatch.setattr(benchmark, "chart_case", route)
    monkeypatch.setattr(benchmark, "write_report", report)
    for entry in ("geometry_case", "text_case", "code_case", "callout_case"):
        monkeypatch.setattr(benchmark, entry, wrong_family)
    assert benchmark.main(["--output-dir", str(tmp_path), "--diagnostic-family", "chart"]) == 0
    assert calls == expected


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("mode", ["reveal", "enter"])
@pytest.mark.parametrize("kind", ["image", "video", "presenter", "screen_recording"])
def test_split_media_offline_verified_assets_literal_vfr_pixels_and_seek(tmp_path, portrait, mode, kind):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "media_case"), "Task10 verified media proof is missing"
    record = benchmark.media_case(tmp_path, portrait, kind, mode)
    start = 0 if kind == "image" else 1995
    assert record["family"] == "media"
    assert record["profile"] == ("SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9")
    assert (record["action_start_ms"], record["action_end_ms"]) == (start, start + 10)
    assert record["seek_order_ms"] == [start + offset for offset in (10, 0, 3, 9, 6, 8, 3, 0, 10, 5, 3, 5)]
    assert set(record["frames"]) == {str(start + offset) for offset in (0, 3, 5, 6, 8, 9, 10)}
    assert record["network_forbidden"] and record["immutable_input_keys_unchanged"]
    assert record["verified_project_asset_count"] == 1
    assert len(json.loads(record["asset_pins_json"])) == 1
    assert len(record["sample_compose_raster_ms"]) == 12
    for offset in (0, 3, 5, 10):
        frame = record["frames"][str(start + offset)]
        expected = literal_pixels(portrait, mode, kind, start, offset)
        with Image.open(io.BytesIO(expected)) as want, Image.open(frame["png_path"]) as got:
            assert got.convert("RGBA").tobytes() == want.convert("RGBA").tobytes()
    with Image.open(record["contact_sheet_path"]) as sheet:
        assert sheet.width == len(record["frames"]) * 240
    assert all(version == 1 for version in record["frames"][str(start)]["state_versions"].values())
    assert all(version == 2 for version in record["frames"][str(start + 10)]["state_versions"].values())


def test_split_media_proof_refuses_unauthored_variant(tmp_path):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "media_case"), "Task10 verified media proof is missing"
    with pytest.raises(ValueError, match="Unsupported.*media variant"):
        benchmark.media_case(tmp_path, False, "not-authored", "reveal")


@pytest.mark.parametrize("fault", ["raw", "missing"])
def test_split_media_proof_requires_original_verified_carrier(tmp_path, monkeypatch, fault):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "media_case"), "Task10 verified media proof is missing"
    original = benchmark.media_family

    def untrusted(*args, **kwargs):
        layout, initial, action, timeline, carrier, hashes = original(*args, **kwargs)
        carrier = dict(carrier) if fault == "raw" else type(carrier)(())
        return layout, initial, action, timeline, carrier, hashes

    monkeypatch.setattr(benchmark, "media_family", untrusted)
    message = ("Split paint requires trusted project asset metadata" if fault == "raw" else
               "Split paint requires the exact asset inventory")
    with pytest.raises(ValueError, match=f"^{message}$"):
        benchmark.media_case(tmp_path, False, "image", "reveal")


def test_split_media_diagnostic_report_cannot_grant_final_acceptance(tmp_path):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "media_case"), "Task10 verified media proof is missing"
    record = benchmark.media_case(tmp_path, False, "image", "reveal")
    assert benchmark.write_report(tmp_path, [record], diagnostic="media") == 0
    report = json.loads((tmp_path / "split-media-diagnostic.json").read_text(encoding="utf-8"))
    assert report["status"] == "DIAGNOSTIC ONLY" and report["final_acceptance"] is False
    assert report["cases"][0]["case_id"] == record["case_id"]
    assert report["missing_required_proofs"]


def test_split_media_cli_routes_only_the_authored_diagnostic_matrix(tmp_path, monkeypatch):
    benchmark = split_benchmark()
    expected = [(portrait, kind, mode) for portrait in (False, True)
                for kind in ("image", "video", "presenter", "screen_recording") for mode in ("reveal", "enter")]
    calls = []

    def route(directory, portrait, kind, mode):
        assert directory == tmp_path
        calls.append((portrait, kind, mode))
        return {"route": (portrait, kind, mode)}

    def report(directory, cases, *, diagnostic):
        assert directory == tmp_path and diagnostic == "media"
        assert cases == [{"route": row} for row in expected]
        return 0

    def wrong_family(*args, **kwargs):
        pytest.fail("Media CLI dispatched a different family")

    monkeypatch.setattr(benchmark, "media_case", route)
    monkeypatch.setattr(benchmark, "write_report", report)
    for entry in ("geometry_case", "text_case", "code_case", "callout_case", "chart_case"):
        monkeypatch.setattr(benchmark, entry, wrong_family)
    assert benchmark.main(["--output-dir", str(tmp_path), "--diagnostic-family", "media"]) == 0
    assert calls == expected


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind,mode", VISUAL_CASES)
def test_split_visual_offline_real_owner_pixels_and_seek(tmp_path, portrait, kind, mode):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "visual_case"), "Task10 authored visual-family proof is missing"
    record = benchmark.visual_case(tmp_path, portrait, kind, mode)
    assert record["family"] == "visual"
    assert record["profile"] == ("SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9")
    assert record["seek_order_ms"] == [40, 0, 12, 39, 24, 32, 12, 0, 40]
    assert record["network_forbidden"] and record["immutable_input_keys_unchanged"]
    assert record["verified_project_asset_count"] == 0
    layout, _, _, _ = illustration_boundary(family=kind, mode=mode, portrait=portrait)
    owner_ids = {obj.object_id for obj in layout.objects if obj.object_id.startswith("part-1")}
    for at, expected_ids in ((0, {"source"}), (12, {"source", "part-2"} | owner_ids),
                             (40, {"part-2"} | owner_ids)):
        frame = record["frames"][str(at)]
        tree = ET.fromstring(Path(frame["svg_path"]).read_text(encoding="utf-8"))
        ids = [node.attrib["data-object-id"] for node in tree.iter() if "data-object-id" in node.attrib]
        assert set(ids) == expected_ids and len(ids) == len(set(ids))
        for key, version in frame["state_versions"].items():
            assert version == (2 if at == 40 and key in {"source", "part-1", "part-2"} else 1)
        if at == 12:
            source = next(node for node in tree.iter() if node.attrib.get("data-object-id") == "source")
            assert float(source.attrib["opacity"]) == .8333
            if mode == "draw":
                strokes = [node for node in tree.iter() if "stroke-dasharray" in node.attrib]
                assert strokes
                for stroke in strokes:
                    length = float(stroke.attrib["stroke-dasharray"].split()[0])
                    assert abs(float(stroke.attrib["stroke-dashoffset"]) - length / 2) <= .0001
            # Literal authored ink remains inside the half-built owner aperture.
            offset = 40 if mode == "enter" else 0
            point = {"illustration": (215, 325), "character": (335, 270), "technical": (105, 350)}[kind]
            with Image.open(frame["png_path"]) as image:
                assert image.convert("RGBA").getpixel((point[0] + offset, point[1])) == (23, 32, 51, 255)
    # Compare the entire native artwork crop to the accepted owning primitive,
    # outside Split's capture/phase path; its own tests pin authored ink pixels.
    native_layout, native_timeline = native_reference(kind, portrait)
    expected = compose_png_frame(native_layout, native_timeline, 0).png
    offset = 80 if mode == "enter" else 0
    with Image.open(io.BytesIO(expected)) as want, Image.open(record["frames"]["40"]["png_path"]) as got:
        assert got.convert("RGBA").crop((100 + offset, 180, 620 + offset, 610)).tobytes() == (
            want.convert("RGBA").crop((100, 180, 620, 610)).tobytes())
    with Image.open(record["contact_sheet_path"]) as sheet:
        assert sheet.width == 6 * 240


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("family,kind,state,owner,mode", VISUAL_STATE_CASES)
def test_split_visual_state_offline_native_roles_pixels_and_seek(tmp_path, portrait, family, kind, state, owner, mode):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "visual_state_case"), "Task10 authored visual state/source-role proof is missing"
    record = benchmark.visual_state_case(tmp_path, portrait, family, kind, state, owner, mode)
    assert (record["family"], record["visual_family"], record["kind"], record["state"], record["owner"]) == (
        "visual-state", family, kind, state, owner)
    assert record["case_id"] == (
        f"visual-state-{family}-{str(state).lower()}-{owner}-{kind}-{mode}-{'portrait' if portrait else 'landscape'}")
    assert record["profile"] == ("SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9")
    assert record["seek_order_ms"] == [40, 0, 12, 39, 24, 32, 12, 0, 40, 1, 36, 41, 1, 41]
    assert record["network_forbidden"] and record["immutable_input_keys_unchanged"]
    assert record["verified_project_asset_count"] == 0 and json.loads(record["asset_pins_json"]) == []
    assert len(record["sample_compose_raster_ms"]) == 14
    if family == "character":
        native, clock = original_pose_documents(kind, portrait=portrait)
        native_root = "actor-group"
    elif family == "technical":
        roles = next(roles for name, _, roles in CASES if name == kind)
        native, clock = composite_documents(kind, state, roles, portrait=portrait)
        native_root = "list-group"
    else:
        native, clock = original_illustration_documents(kind, active=state, portrait=portrait)
        native_root = "illustration-group"
    objects = {row["object_id"]: row for row in native["objects"]}
    closure, pending = set(), [native_root]
    while pending:
        key = pending.pop()
        closure.add(key)
        pending.extend(objects[key].get("child_ids", []))
    owner_ids = {owner if key == native_root else f"{owner}.{key}" for key in closure}
    for at in (0, 12, 39, 40, 41):
        frame = record["frames"][str(at)]
        tree = ET.fromstring(Path(frame["svg_path"]).read_text(encoding="utf-8"))
        ids = [node.attrib["data-object-id"] for node in tree.iter() if "data-object-id" in node.attrib]
        if at == 0:
            expected_ids = owner_ids if owner == "source" else {"source"}
        else:
            roots = {"part-1", "part-2"} | ({"source"} if at < 32 else set())
            expected_ids = (roots - {owner}) | (owner_ids if owner != "source" or at < 32 else set())
        assert set(ids) == expected_ids and len(ids) == len(set(ids))
        for key, version in frame["state_versions"].items():
            assert version == (2 if at >= 40 and key in {"source", "part-1", "part-2"} else 1)
        if at == 12:
            source = next(node for node in tree.iter() if node.attrib.get("data-object-id") == "source")
            assert float(source.attrib["opacity"]) == .8333
            if owner != "source" and mode == "draw":
                node = next(node for node in tree.iter() if node.attrib.get("data-object-id") == owner)
                assert any(float(row.attrib.get("stroke-dashoffset", 0)) > 0 for row in node.iter())
    expected = compose_png_frame(native, clock, 0).png
    box = (100, 180, 620, 610)
    offset = 80 if mode == "enter" else 0
    at = "0" if owner == "source" else "40"
    with Image.open(io.BytesIO(expected)) as want, Image.open(record["frames"][at]["png_path"]) as got:
        assert got.convert("RGBA").crop((100 + offset, 180, 620 + offset, 610)).tobytes() == (
            want.convert("RGBA").crop(box).tobytes())
    if owner == "source":
        with Image.open(record["frames"]["0"]["png_path"]) as start, Image.open(
                record["frames"]["12"]["png_path"]) as middle, Image.open(
                record["frames"]["40"]["png_path"]) as final:
            assert start.convert("RGBA").crop(box).tobytes() != middle.convert("RGBA").crop(box).tobytes()
            assert final.convert("RGBA").crop(box).getextrema() == (
                (250, 250), (248, 248), (241, 241), (255, 255))
    with Image.open(record["contact_sheet_path"]) as sheet:
        assert sheet.width == len(record["frames"]) * 240


@pytest.mark.parametrize("family,kind,state,owner,mode", [
    ("missing", "device", True, "part-1", "reveal"),
    ("illustration", "missing", True, "part-1", "reveal"),
    ("character", "neutral", False, "part-1", "reveal"),
    ("illustration", "device", 1, "part-1", "reveal"),
    ("technical", "browser", "missing", "part-1", "reveal"),
    ("technical", "browser", "ready", "missing", "reveal"),
    ("illustration", "device", True, "source", "enter"),
    ("character", "neutral", True, "source", "draw"),
    ("character", "neutral", True, "part-2", "write"),
    ("illustration", "device", True, "part-1", "draw"),
    ("technical", "browser", "ready", "part-2", "draw"),
    ("illustration", "../device", True, "part-1", "reveal"),
])
def test_split_visual_state_proof_refuses_unauthored_selectors(tmp_path, family, kind, state, owner, mode):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "visual_state_case"), "Task10 authored visual state/source-role proof is missing"
    with pytest.raises(ValueError, match="^Unsupported authored visual state"):
        benchmark.visual_state_case(tmp_path, False, family, kind, state, owner, mode)
    assert not list(tmp_path.iterdir())


def test_split_visual_state_diagnostic_cannot_grant_final_acceptance(tmp_path):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "visual_state_case"), "Task10 authored visual state/source-role proof is missing"
    record = benchmark.visual_state_case(tmp_path, False, "character", "open_hands", True, "part-2", "draw")
    assert benchmark.write_report(tmp_path, [record], diagnostic="visual-state") == 0
    report = json.loads((tmp_path / "split-visual-state-diagnostic.json").read_text(encoding="utf-8"))
    assert report["status"] == "DIAGNOSTIC ONLY" and report["final_acceptance"] is False
    assert report["cases"][0]["case_id"] == record["case_id"] and report["missing_required_proofs"]


def test_split_visual_state_cli_routes_only_existing_states_and_roles(tmp_path, monkeypatch):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "visual_state_case"), "Task10 authored visual state/source-role proof is missing"
    expected = [(portrait, *row) for portrait in (False, True) for row in VISUAL_STATE_CASES]
    assert len(expected) == 302 and len(set(expected)) == 302
    calls = []

    def route(directory, *row):
        assert directory == tmp_path
        calls.append(row)
        return {"route": row}

    def report(directory, cases, *, diagnostic):
        assert directory == tmp_path and diagnostic == "visual-state"
        assert cases == [{"route": row} for row in expected]
        return 0

    def wrong_family(*args, **kwargs):
        pytest.fail("Visual state CLI dispatched a different family")

    monkeypatch.setattr(benchmark, "visual_state_case", route)
    monkeypatch.setattr(benchmark, "write_report", report)
    for entry in ("geometry_case", "text_case", "code_case", "callout_case", "chart_case", "media_case",
                  "visual_case", "container_case", "evidence_case", "connector_case"):
        monkeypatch.setattr(benchmark, entry, wrong_family)
    assert benchmark.main(["--output-dir", str(tmp_path), "--diagnostic-family", "visual-state"]) == 0
    assert calls == expected


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("family", ["character", "illustration", "technical"])
@pytest.mark.parametrize("kind", APERTURE_KINDS)
def test_split_aperture_offline_native_pixels_and_read_ancestry(tmp_path, portrait, family, kind):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "aperture_case"), "Task10 authored read-aperture proof is missing"
    record = benchmark.aperture_case(tmp_path, portrait, family, kind)
    assert (record["family"], record["visual_family"], record["kind"], record["mode"]) == (
        "aperture", family, kind, "reveal")
    assert record["case_id"] == f"aperture-{family}-{kind}-reveal-{'portrait' if portrait else 'landscape'}"
    assert record["profile"] == ("SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9")
    assert record["seek_order_ms"] == [40, 0, 12, 39, 24, 32, 12, 0, 40, 1, 36, 41, 1, 41]
    assert record["network_forbidden"] and record["immutable_input_keys_unchanged"]
    assert record["verified_project_asset_count"] == 0
    final = record["frames"]["40"]
    tree = ET.fromstring(Path(final["svg_path"]).read_text(encoding="utf-8"))
    ids = [row.attrib["data-object-id"] for row in tree.iter() if "data-object-id" in row.attrib]
    assert "source" not in ids and ids.count("read-stage") == 1
    for key in set(final["state_versions"]) - {"source", "read-stage", "mask-source"}:
        assert ids.count(key) == 1
    point = {"character": (335, 270), "illustration": (325, 435), "technical": (105, 350)}[family]
    with Image.open(final["png_path"]) as image:
        rgba = image.convert("RGBA")
        assert rgba.getpixel((point[0] + 37, point[1] + 13)) == (23, 32, 51, 255)
        if kind in {"clip", "mask"}:
            assert rgba.crop((418, 200, 650, 610)).getextrema() == (
                (250, 250), (248, 248), (241, 241), (255, 255))
    for at in (0, 39, 40, 41):
        frame = record["frames"][str(at)]
        for key, version in frame["state_versions"].items():
            assert version == (2 if at >= 40 and key in {"source", "part-1", "part-2"} else 1)
        for key in (("read-stage", "mask-source") if kind == "mask" else ("read-stage",)):
            assert frame["state_sha256"][key] == record["frames"]["0"]["state_sha256"][key]
    with Image.open(record["contact_sheet_path"]) as sheet:
        assert sheet.width == len(record["frames"]) * 240


@pytest.mark.parametrize("family,kind", [("missing", "group"), ("character", "missing")])
def test_split_aperture_proof_refuses_unauthored_selector(tmp_path, family, kind):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "aperture_case"), "Task10 authored read-aperture proof is missing"
    with pytest.raises(ValueError, match="^Unsupported authored read-aperture selector$"):
        benchmark.aperture_case(tmp_path, False, family, kind)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("owner,mode", REGISTRY_ROLES)
def test_split_registry_offline_authenticated_native_roles_and_seek(tmp_path, portrait, owner, mode, monkeypatch):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "registry_case"), "Task10 authenticated registry proof is missing"
    observed = []
    verify = benchmark.verify_split_paint_inputs

    def actual_inputs(*args, **kwargs):
        inputs = verify(*args, **kwargs)
        observed.append(inputs)
        return inputs

    monkeypatch.setattr(benchmark, "verify_split_paint_inputs", actual_inputs)
    record = benchmark.registry_case(tmp_path, portrait, owner, mode)
    assert (record["family"], record["kind"], record["mode"]) == ("registry", owner, mode)
    assert record["case_id"] == f"registry-{owner}-{mode}-{'portrait' if portrait else 'landscape'}"
    assert record["profile"] == ("SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9")
    assert record["seek_order_ms"] == [40, 0, 12, 39, 24, 32, 12, 0, 40, 1, 36, 41, 1, 41]
    assert record["network_forbidden"] and record["immutable_input_keys_unchanged"]
    evidence = next(json.loads(row) for row in observed[0].paint_evidence if json.loads(row).get("object_id") == owner)
    assert len(evidence["paint"]["asset_sha256"]) == 64
    assert evidence["paint"]["alpha_bounds"] and evidence["paint"]["alpha_sha256"]
    reference, clock = illustration_documents("person-collaborators", "character")
    for unrelated in reference["objects"][:2]:
        unrelated["transform"] = deepcopy(unrelated["transform"])
        unrelated["transform"]["position"]["x"] = 2000.
    reference["objects"][2].update(geometry=registry_object()["geometry"],
        anchors=registry_object()["anchors"], registry_binding=registry_object()["registry_binding"])
    width, height = (720, 1280) if portrait else (1280, 720)
    reference["output_profile"] = {**reference["output_profile"], "profile_id": record["profile"],
                                   "width": width, "height": height}
    reference["canvas"].update(width=width, height=height)
    clock.update(output_profile=deepcopy(reference["output_profile"]), layout_sha256=digest(reference))
    expected = compose_png_frame(reference, clock, 5000).png
    offset = 80 if mode == "enter" else 0
    at = "0" if owner == "source" else "40"
    with Image.open(io.BytesIO(expected)) as want, Image.open(record["frames"][at]["png_path"]) as got:
        assert got.convert("RGBA").crop((100 + offset, 200, 400 + offset, 500)).tobytes() == (
            want.convert("RGBA").crop((100, 200, 400, 500)).tobytes())
    for at in (0, 39, 40, 41):
        frame = record["frames"][str(at)]
        for key, version in frame["state_versions"].items():
            assert version == (2 if at >= 40 and key in {"source", "part-1", "part-2"} else 1)
    final = ET.fromstring(Path(record["frames"]["40"]["svg_path"]).read_text(encoding="utf-8"))
    ids = [row.attrib["data-object-id"] for row in final.iter() if "data-object-id" in row.attrib]
    assert "source" not in ids and ids.count("part-1") == ids.count("part-2") == 1
    if owner == "source":
        with Image.open(record["frames"]["40"]["png_path"]) as image:
            assert image.convert("RGBA").crop((100, 200, 400, 500)).getextrema() == (
                (250, 250), (248, 248), (241, 241), (255, 255))


@pytest.mark.parametrize("owner,mode", [
    ("missing", "reveal"), ("source", "enter"), ("source", "draw"), ("source", "write"),
    ("part-1", "draw"), ("part-1", "write"), ("part-2", "draw"), ("part-2", "write"),
])
def test_split_registry_proof_refuses_unauthored_selector(tmp_path, owner, mode):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "registry_case"), "Task10 authenticated registry proof is missing"
    with pytest.raises(ValueError, match="^Unsupported authenticated registry selector$"):
        benchmark.registry_case(tmp_path, False, owner, mode)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("diagnostic", ["aperture", "registry"])
def test_split_visual_boundary_diagnostic_cannot_grant_final_acceptance(tmp_path, diagnostic):
    benchmark = split_benchmark()
    assert hasattr(benchmark, diagnostic + "_case"), "Task10 authored visual boundary proof is missing"
    record = (benchmark.aperture_case(tmp_path, False, "illustration", "clip") if diagnostic == "aperture" else
              benchmark.registry_case(tmp_path, False, "part-2", "enter"))
    assert benchmark.write_report(tmp_path, [record], diagnostic=diagnostic) == 0
    report = json.loads((tmp_path / f"split-{diagnostic}-diagnostic.json").read_text(encoding="utf-8"))
    assert report["status"] == "DIAGNOSTIC ONLY" and report["final_acceptance"] is False
    assert report["cases"][0]["case_id"] == record["case_id"] and report["missing_required_proofs"]


@pytest.mark.parametrize("diagnostic", ["aperture", "registry"])
def test_split_visual_boundary_cli_routes_only_authored_matrix(tmp_path, diagnostic, monkeypatch):
    benchmark = split_benchmark()
    expected_diagnostic = diagnostic
    entry = diagnostic + "_case"
    assert hasattr(benchmark, entry), "Task10 authored visual boundary proof is missing"
    expected = ([(portrait, family, kind) for portrait in (False, True)
                 for family in ("character", "illustration", "technical") for kind in APERTURE_KINDS]
                if diagnostic == "aperture" else
                [(portrait, owner, mode) for portrait in (False, True) for owner, mode in REGISTRY_ROLES])
    assert len(expected) == (18 if diagnostic == "aperture" else 10)
    calls = []

    def route(directory, *row):
        assert directory == tmp_path
        calls.append(row)
        return {"route": row}

    def report(directory, cases, *, diagnostic):
        assert directory == tmp_path and diagnostic == expected_diagnostic
        assert cases == [{"route": row} for row in expected]
        return 0

    def wrong_family(*args, **kwargs):
        pytest.fail("Visual boundary CLI dispatched another matrix")

    monkeypatch.setattr(benchmark, entry, route)
    monkeypatch.setattr(benchmark, "write_report", report)
    for name in ("geometry_case", "text_case", "code_case", "callout_case", "chart_case", "media_case",
                 "visual_case", "visual_state_case", "container_case", "evidence_case", "connector_case",
                 "registry_case" if diagnostic == "aperture" else "aperture_case"):
        monkeypatch.setattr(benchmark, name, wrong_family)
    assert benchmark.main(["--output-dir", str(tmp_path), "--diagnostic-family", diagnostic]) == 0
    assert calls == expected


def test_split_visual_proof_refuses_unauthored_variant(tmp_path):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "visual_case"), "Task10 authored visual-family proof is missing"
    with pytest.raises(ValueError, match="^Unsupported authored visual variant: not-authored$"):
        benchmark.visual_case(tmp_path, False, "not-authored", "reveal")


@pytest.mark.parametrize("kind", ["illustration", "technical"])
@pytest.mark.parametrize("mode", ["draw", "write"])
def test_split_visual_proof_preserves_incompatible_whole_owner_modes(tmp_path, kind, mode):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "visual_case"), "Task10 authored visual-family proof is missing"
    with pytest.raises(ValueError, match=f"Split {mode} is incompatible with"):
        benchmark.visual_case(tmp_path, False, kind, mode)


def test_split_visual_diagnostic_report_cannot_grant_final_acceptance(tmp_path):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "visual_case"), "Task10 authored visual-family proof is missing"
    record = benchmark.visual_case(tmp_path, False, "illustration", "reveal")
    assert benchmark.write_report(tmp_path, [record], diagnostic="visual") == 0
    report = json.loads((tmp_path / "split-visual-diagnostic.json").read_text(encoding="utf-8"))
    assert report["status"] == "DIAGNOSTIC ONLY" and report["final_acceptance"] is False
    assert report["cases"][0]["case_id"] == record["case_id"] and report["missing_required_proofs"]


def test_split_visual_cli_routes_only_the_authored_diagnostic_matrix(tmp_path, monkeypatch):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "visual_case"), "Task10 authored visual-family proof is missing"
    expected = [(portrait, kind, mode) for portrait in (False, True) for kind, mode in VISUAL_CASES]
    calls = []

    def route(directory, portrait, kind, mode):
        assert directory == tmp_path
        calls.append((portrait, kind, mode))
        return {"route": (portrait, kind, mode)}

    def report(directory, cases, *, diagnostic):
        assert directory == tmp_path and diagnostic == "visual"
        assert cases == [{"route": row} for row in expected]
        return 0

    def wrong_family(*args, **kwargs):
        pytest.fail("Visual CLI dispatched a different family")

    monkeypatch.setattr(benchmark, "visual_case", route)
    monkeypatch.setattr(benchmark, "write_report", report)
    for entry in ("geometry_case", "text_case", "code_case", "callout_case", "chart_case", "media_case"):
        monkeypatch.setattr(benchmark, entry, wrong_family)
    assert benchmark.main(["--output-dir", str(tmp_path), "--diagnostic-family", "visual"]) == 0
    assert calls == expected


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("mode", ["reveal", "draw", "enter", "write"])
@pytest.mark.parametrize("kind", CONTAINER_CASES)
def test_split_container_offline_literal_pixels_closures_and_seek(tmp_path, portrait, mode, kind):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "container_case"), "Task10 authored container proof is missing"
    record = benchmark.container_case(tmp_path, portrait, kind, mode)
    assert record["family"] == "container"
    assert record["profile"] == ("SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9")
    assert record["seek_order_ms"] == [40, 0, 12, 39, 24, 32, 12, 0, 40]
    assert record["network_forbidden"] and record["immutable_input_keys_unchanged"]
    content = "code" if mode == "write" else "rectangle"
    masked = kind in {"mask-source", "mask-result"}
    if masked:
        root_id = "source" if kind == "mask-source" else "part-1"
        layout, _, action, _ = mask_split_family(portrait, root_id, mode, content=content)
        extra_ids = set()
    else:
        layout, _, action, _, _, _, boxes = reusable_split_family(portrait, kind, mode, content=content)
        extra_ids = {"studio-stage"}
    inputs = benchmark.verify_split_paint_inputs(layout, {})
    basis = action.action.split_policy.source_basis
    source_ids = set(basis.source_closure.owned_ids)
    result_ids = {key for closure in basis.result_closures for key in closure.owned_ids}
    initial = record["frames"]["0"]["state_sha256"]
    roots = {"source", "part-1", "part-2"}
    for at in (0, 12, 40):
        frame = record["frames"][str(at)]
        expected = (literal_mask_oracle(portrait, root_id, mode, at, inputs, content=content) if masked else
                    literal_reusable_oracle(portrait, kind, mode, at, inputs, boxes, content=content))
        with Image.open(io.BytesIO(expected)) as want, Image.open(frame["png_path"]) as got:
            assert got.convert("RGBA").tobytes() == want.convert("RGBA").tobytes()
        tree = ET.fromstring(Path(frame["svg_path"]).read_text(encoding="utf-8"))
        ids = [node.attrib["data-object-id"] for node in tree.iter() if "data-object-id" in node.attrib]
        expected_ids = extra_ids | (source_ids if at < 40 else set()) | (result_ids if at > 0 else set())
        assert set(ids) == expected_ids and len(ids) == len(set(ids))
        for key, version in frame["state_versions"].items():
            assert version == (2 if at == 40 and key in roots else 1)
            if key not in roots:
                assert frame["state_sha256"][key] == initial[key]
    assert record["verified_project_asset_count"] == 0


def test_split_container_proof_refuses_unauthored_variant(tmp_path):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "container_case"), "Task10 authored container proof is missing"
    with pytest.raises(ValueError, match="^Unsupported authored container variant: not-authored$"):
        benchmark.container_case(tmp_path, False, "not-authored", "reveal")


@pytest.mark.parametrize("kind", CONTAINER_CASES)
def test_split_container_proof_cannot_substitute_marks_for_write(tmp_path, monkeypatch, kind):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "container_case"), "Task10 authored container proof is missing"
    name = "mask_split_family" if kind.startswith("mask-") else "reusable_split_family"
    original = getattr(benchmark, name)

    def marks(*args, **kwargs):
        kwargs["content"] = "rectangle"
        return original(*args, **kwargs)

    monkeypatch.setattr(benchmark, name, marks)
    with pytest.raises(ValueError, match="^Split write is incompatible with geometry construction$"):
        benchmark.container_case(tmp_path, False, kind, "write")


def test_split_container_diagnostic_report_cannot_grant_final_acceptance(tmp_path):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "container_case"), "Task10 authored container proof is missing"
    record = benchmark.container_case(tmp_path, False, "mask-result", "reveal")
    assert benchmark.write_report(tmp_path, [record], diagnostic="container") == 0
    report = json.loads((tmp_path / "split-container-diagnostic.json").read_text(encoding="utf-8"))
    assert report["status"] == "DIAGNOSTIC ONLY" and report["final_acceptance"] is False
    assert report["cases"][0]["case_id"] == record["case_id"] and report["missing_required_proofs"]


def test_split_container_cli_routes_only_the_authored_diagnostic_matrix(tmp_path, monkeypatch):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "container_case"), "Task10 authored container proof is missing"
    expected = [(portrait, kind, mode) for portrait in (False, True) for kind in CONTAINER_CASES
                for mode in ("reveal", "draw", "enter", "write")]
    calls = []

    def route(directory, portrait, kind, mode):
        assert directory == tmp_path
        calls.append((portrait, kind, mode))
        return {"route": (portrait, kind, mode)}

    def report(directory, cases, *, diagnostic):
        assert directory == tmp_path and diagnostic == "container"
        assert cases == [{"route": row} for row in expected]
        return 0

    def wrong_family(*args, **kwargs):
        pytest.fail("Container CLI dispatched a different family")

    monkeypatch.setattr(benchmark, "container_case", route)
    monkeypatch.setattr(benchmark, "write_report", report)
    for entry in ("geometry_case", "text_case", "code_case", "callout_case", "chart_case", "media_case", "visual_case"):
        monkeypatch.setattr(benchmark, entry, wrong_family)
    assert benchmark.main(["--output-dir", str(tmp_path), "--diagnostic-family", "container"]) == 0
    assert calls == expected


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("mode", ["reveal", "enter"])
@pytest.mark.parametrize("kind", EVIDENCE_CASES)
def test_split_evidence_offline_attested_pixels_history_and_seek(tmp_path, portrait, mode, kind, monkeypatch):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "evidence_case"), "Task10 attested evidence proof is missing"
    authored, observed = [], []
    prepare, replay = benchmark.short_evidence_documents, benchmark._replay_split_chronology

    def evidence_documents(*args, **kwargs):
        result = prepare(*args, **kwargs)
        authored.append(result[3])
        return result

    def evidence_replay(*args, **kwargs):
        assert len(authored) == 1 and kwargs["timeline"] is authored[0]
        observed.append(kwargs["timeline"])
        return replay(*args, **kwargs)

    monkeypatch.setattr(benchmark, "short_evidence_documents", evidence_documents)
    monkeypatch.setattr(benchmark, "_replay_split_chronology", evidence_replay)
    record = benchmark.evidence_case(tmp_path, portrait, kind, mode)
    assert len(observed) == len(authored) == 1
    start = 4000 if kind == "source" else 1000
    assert record["family"] == "evidence"
    assert record["profile"] == ("SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9")
    assert (record["action_start_ms"], record["action_end_ms"]) == (start, start + 40)
    assert record["seek_order_ms"] == [start + offset for offset in
        (40, 0, 12, 39, 24, 32, 12, 0, 40, -1, 36, 2539, -1, 2539)]
    assert record["chronology_action_ids"] == (["source-insert", "split-1"] if kind == "source" else ["split-1"])
    assert record["network_forbidden"] and record["immutable_input_keys_unchanged"]
    assert record["verified_project_asset_count"] == (2 if kind == "source" else 1)
    assert len(json.loads(record["asset_pins_json"])) == record["verified_project_asset_count"]
    frame = record["frames"][str(start + 40)]
    with Image.open(frame["png_path"]) as image:
        rgb = image.convert("RGB")
        assert rgb.getpixel((370, 240) if portrait else (950, 300)) == (235, 30, 40)
        assert rgb.getpixel((370, 840) if portrait else (370, 300)) == (25, 185, 50)
    final_svg = Path(frame["svg_path"]).read_text(encoding="utf-8")
    assert "First view" in final_svg and "Second view" in final_svg
    if kind == "annotated":
        assert "First mechanism" in final_svg and "Second mechanism" in final_svg
    before = record["frames"][str(start - 1)]
    assert before["state_versions"]["source"] == (2 if kind == "source" else 1)
    assert frame["state_versions"]["source"] == (3 if kind == "source" else 2)
    assert all(frame["state_versions"][key] == 2 for key in ("part-1", "part-2"))
    if kind == "source":
        assert "Original source" in Path(before["svg_path"]).read_text(encoding="utf-8")
        assert "Original source" not in final_svg
        with Image.open(before["png_path"]) as image:
            assert image.convert("RGB").getpixel((350, 240) if portrait else (930, 300)) == (40, 170, 210)
    assert len({value["png_sha256"] for value in record["frames"].values()}) >= 4
    assert len(record["sample_compose_raster_ms"]) == 14
    with Image.open(record["contact_sheet_path"]) as sheet:
        assert sheet.width == len(record["frames"]) * 240


def test_split_evidence_proof_refuses_unauthored_variant(tmp_path):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "evidence_case"), "Task10 attested evidence proof is missing"
    with pytest.raises(ValueError, match="^Unsupported authored evidence variant: not-authored$"):
        benchmark.evidence_case(tmp_path, False, "not-authored", "reveal")


@pytest.mark.parametrize("mode", ["draw", "write"])
def test_split_evidence_proof_refuses_unfaithful_mode_instead_of_aliasing_reveal(tmp_path, mode):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "evidence_case"), "Task10 attested evidence proof is missing"
    with pytest.raises(ValueError, match=f"^Unsupported authored evidence mode: {mode}$"):
        benchmark.evidence_case(tmp_path, False, "plain", mode)


@pytest.mark.parametrize("fault", ["raw", "missing"])
def test_split_evidence_proof_requires_original_verified_carrier(tmp_path, monkeypatch, fault):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "evidence_case"), "Task10 attested evidence proof is missing"
    original = benchmark.short_evidence_documents

    def untrusted(*args, **kwargs):
        service, layout, initial, timeline, carrier = original(*args, **kwargs)
        carrier = {row.asset_id: row.payload for row in carrier.rows} if fault == "raw" else type(carrier)(())
        return service, layout, initial, timeline, carrier

    monkeypatch.setattr(benchmark, "short_evidence_documents", untrusted)
    message = ("Split paint requires trusted project asset metadata" if fault == "raw" else
               "Split paint requires the exact asset inventory")
    with pytest.raises(ValueError, match=f"^{message}$"):
        benchmark.evidence_case(tmp_path, False, "plain", "reveal")


def test_split_evidence_diagnostic_report_cannot_grant_final_acceptance(tmp_path):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "evidence_case"), "Task10 attested evidence proof is missing"
    record = benchmark.evidence_case(tmp_path, False, "plain", "reveal")
    assert benchmark.write_report(tmp_path, [record], diagnostic="evidence") == 0
    report = json.loads((tmp_path / "split-evidence-diagnostic.json").read_text(encoding="utf-8"))
    assert report["status"] == "DIAGNOSTIC ONLY" and report["final_acceptance"] is False
    assert report["cases"][0]["case_id"] == record["case_id"] and report["missing_required_proofs"]


def test_split_evidence_cli_routes_only_the_authored_diagnostic_matrix(tmp_path, monkeypatch):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "evidence_case"), "Task10 attested evidence proof is missing"
    expected = [(portrait, kind, mode) for portrait in (False, True) for kind in EVIDENCE_CASES
                for mode in ("reveal", "enter")]
    calls = []

    def route(directory, portrait, kind, mode):
        assert directory == tmp_path
        calls.append((portrait, kind, mode))
        return {"route": (portrait, kind, mode)}

    def report(directory, cases, *, diagnostic):
        assert directory == tmp_path and diagnostic == "evidence"
        assert cases == [{"route": row} for row in expected]
        return 0

    def wrong_family(*args, **kwargs):
        pytest.fail("Evidence CLI dispatched a different family")

    monkeypatch.setattr(benchmark, "evidence_case", route)
    monkeypatch.setattr(benchmark, "write_report", report)
    for entry in ("geometry_case", "text_case", "code_case", "callout_case", "chart_case", "media_case",
                  "visual_case", "container_case"):
        monkeypatch.setattr(benchmark, entry, wrong_family)
    assert benchmark.main(["--output-dir", str(tmp_path), "--diagnostic-family", "evidence"]) == 0
    assert calls == expected


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("mode", ["reveal", "draw"])
@pytest.mark.parametrize("routing", CONNECTOR_ROUTES)
@pytest.mark.parametrize("kind", CONNECTOR_CASES)
def test_split_connector_offline_literal_routes_heads_pixels_and_seek(tmp_path, portrait, mode, routing, kind):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "connector_case"), "Task10 authored connector proof is missing"
    record = benchmark.connector_case(tmp_path, portrait, kind, mode, routing)
    assert record["family"] == "connector" and record["routing"] == routing
    assert record["case_id"] == f"connector-{routing}-{kind}-{mode}-{'portrait' if portrait else 'landscape'}"
    assert record["profile"] == ("SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9")
    assert record["seek_order_ms"] == [40, 0, 12, 39, 24, 32, 12, 0, 40, 1, 36, 41, 1, 41]
    assert record["network_forbidden"] and record["immutable_input_keys_unchanged"]
    assert record["verified_project_asset_count"] == 0 and json.loads(record["asset_pins_json"]) == []
    assert len(record["sample_compose_raster_ms"]) == 14
    positions = ((100., 100.), (540., 100.), (320., 720.)) if portrait else (
        (80., 90.), (620., 90.), (340., 470.))
    colors = json.loads(record["style_json"])["colors"]
    final = record["frames"]["40"]
    complete = ET.fromstring(Path(final["svg_path"]).read_text(encoding="utf-8"))
    assert not any(row.attrib.get("data-object-id") == "source" for row in complete.iter())
    with Image.open(final["png_path"]) as image:
        rgb = image.convert("RGB")
        assert rgb.size == ((720, 1280) if portrait else (1280, 720))
        for index, key in enumerate(("part-1", "part-2"), 1):
            start, end = ((0, 2), (2, 1))[index - 1]
            sx, sy = positions[start]
            ex, ey = positions[end]
            if kind == "pointer":
                sy += index * 10.
            nodes = [row for row in complete.iter() if row.attrib.get("data-object-id") == key]
            assert len(nodes) == 1
            path = next(row for row in nodes[0].iter() if row.tag.endswith("path"))
            assert path.attrib["d"].startswith(f"M {sx:g} {sy:g} ")
            assert path.attrib["d"].endswith(f"{ex:g} {ey:g}")
            assert any(row.tag.endswith("polygon") for row in nodes[0].iter())
            if routing == "elbow":
                assert f"L {ex:g} {sy:g} L " in path.attrib["d"]
                sample = ((sx + ex) / 2, sy)
            elif routing == "curve":
                assert f"Q {(sx + ex) / 2:g} {sy:g} " in path.attrib["d"]
                sample = ((sx + ex) / 2, .75 * sy + .25 * ey)
            else:
                sample = ((sx + ex) / 2, (sy + ey) / 2)
            color = colors["accent" if index == 1 else "attention"].lstrip("#")
            assert rgb.getpixel(tuple(round(value) for value in sample)) == tuple(
                int(color[at:at + 2], 16) for at in (0, 2, 4))
    if mode == "draw":
        partial = ET.fromstring(Path(record["frames"]["1"]["svg_path"]).read_text(encoding="utf-8"))
        node = next(row for row in partial.iter() if row.attrib.get("data-object-id") == "part-1")
        assert not any(row.tag.endswith("polygon") for row in node.iter())
        assert any(float(row.attrib.get("stroke-dashoffset", 0)) > 0 for row in node.iter())
    for key in ("source", "part-1", "part-2"):
        assert record["frames"]["0"]["state_versions"][key] == 1
        assert record["frames"]["39"]["state_versions"][key] == 1
        assert final["state_versions"][key] == record["frames"]["41"]["state_versions"][key] == 2
    endpoints = ("endpoint-1", "endpoint-2") if kind == "pointer" else (
        "endpoint-0", "endpoint-1", "endpoint-2")
    for key in endpoints:
        assert final["state_versions"][key] == 1
        assert record["frames"]["0"]["state_sha256"][key] == final["state_sha256"][key]
    with Image.open(record["contact_sheet_path"]) as sheet:
        assert sheet.width == len(record["frames"]) * 240


@pytest.mark.parametrize("kind", CONNECTOR_CASES)
@pytest.mark.parametrize("mode", ["write", "enter"])
def test_split_connector_proof_refuses_incompatible_mode(tmp_path, kind, mode):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "connector_case"), "Task10 authored connector proof is missing"
    with pytest.raises(ValueError, match=f"^Unsupported authored connector mode: {mode}$"):
        benchmark.connector_case(tmp_path, False, kind, mode, "straight")


def test_split_connector_proof_refuses_unauthored_kind(tmp_path):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "connector_case"), "Task10 authored connector proof is missing"
    with pytest.raises(ValueError, match="^Unsupported authored connector variant: not-authored$"):
        benchmark.connector_case(tmp_path, False, "not-authored", "reveal", "straight")


def test_split_connector_proof_refuses_unauthored_routing(tmp_path):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "connector_case"), "Task10 authored connector proof is missing"
    with pytest.raises(ValueError, match="^Unsupported authored connector routing: not-authored$"):
        benchmark.connector_case(tmp_path, False, "arrow", "reveal", "not-authored")


def test_split_connector_diagnostic_report_cannot_grant_final_acceptance(tmp_path):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "connector_case"), "Task10 authored connector proof is missing"
    record = benchmark.connector_case(tmp_path, False, "pointer", "draw", "curve")
    assert benchmark.write_report(tmp_path, [record], diagnostic="connector") == 0
    report = json.loads((tmp_path / "split-connector-diagnostic.json").read_text(encoding="utf-8"))
    assert report["status"] == "DIAGNOSTIC ONLY" and report["final_acceptance"] is False
    assert report["cases"][0]["case_id"] == record["case_id"] and report["missing_required_proofs"]


def test_split_connector_cli_routes_only_the_authored_diagnostic_matrix(tmp_path, monkeypatch):
    benchmark = split_benchmark()
    assert hasattr(benchmark, "connector_case"), "Task10 authored connector proof is missing"
    expected = [(portrait, kind, mode, routing) for portrait in (False, True) for kind in CONNECTOR_CASES
                for mode in ("reveal", "draw") for routing in CONNECTOR_ROUTES]
    calls = []

    def route(directory, portrait, kind, mode, routing):
        assert directory == tmp_path
        calls.append((portrait, kind, mode, routing))
        return {"route": (portrait, kind, mode, routing)}

    def report(directory, cases, *, diagnostic):
        assert directory == tmp_path and diagnostic == "connector"
        assert cases == [{"route": row} for row in expected]
        return 0

    def wrong_family(*args, **kwargs):
        pytest.fail("Connector CLI dispatched a different family")

    monkeypatch.setattr(benchmark, "connector_case", route)
    monkeypatch.setattr(benchmark, "write_report", report)
    for entry in ("geometry_case", "text_case", "code_case", "callout_case", "chart_case", "media_case",
                  "visual_case", "container_case", "evidence_case"):
        monkeypatch.setattr(benchmark, entry, wrong_family)
    assert benchmark.main(["--output-dir", str(tmp_path), "--diagnostic-family", "connector"]) == 0
    assert calls == expected
