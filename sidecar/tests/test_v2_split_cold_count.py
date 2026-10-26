"""Count's stored Split history must preflight from its frozen font bytes."""

import json
import socket
import sys
from contextlib import ExitStack
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest
import resvg_py
from PIL import Image, ImageDraw
from test_v2_split_return import retained_history

from atme.render import style_bundle, v2_count, v2_svg
from atme.render.v2_split_paint import verify_split_paint_inputs
from atme.render.v2_state import validate_resolved_return_history


@pytest.mark.parametrize("portrait", [False, True])
def test_cold_count_storage_uses_only_authenticated_frozen_font_bytes(monkeypatch, portrait):
    layout, timeline = retained_history("count-group", portrait)
    inputs = verify_split_paint_inputs(layout, {})
    original = layout.model_dump_json(), timeline.model_dump_json(), inputs
    v2_count._validate_glyph_inventory.cache_clear()
    v2_svg._font.cache_clear()
    font = v2_svg._font
    observed = []

    def forbidden(*args, **kwargs):
        raise AssertionError("Cold Count reopened original bundle/files or network")

    def frozen_font(source, size):
        assert type(source) is bytes, "Cold Count must measure authenticated frozen font bytes"
        observed.append(sha256(source).hexdigest())
        return font(source, size)

    monkeypatch.setattr(style_bundle, "resolve_contract_bundle", forbidden)
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(v2_svg, "_font", frozen_font)
    validate_resolved_return_history(layout, timeline, layout_sha256=timeline.layout_sha256, split_inputs=inputs)
    assert observed and set(observed) <= {pin for _, pin, _ in inputs.bundle_bytes}
    assert (layout.model_dump_json(), timeline.model_dump_json(), inputs) == original
    font_index = next(i for i, (key, _, _) in enumerate(inputs.bundle_bytes) if key.endswith((".otf", ".ttf")))
    for fault in ("changed", "missing"):
        rows = list(inputs.bundle_bytes)
        key, pin, data = rows[font_index]
        if fault == "changed":
            rows[font_index] = key, pin, data + b"changed"
        else:
            del rows[font_index]
        with pytest.raises(ValueError, match="frozen bundle|resource is missing"):
            validate_resolved_return_history(layout, timeline, layout_sha256=timeline.layout_sha256,
                                             split_inputs=replace(inputs, bundle_bytes=tuple(rows)))


def test_filesystem_warmed_count_cache_cannot_authenticate_changed_frozen_inputs(monkeypatch):
    layout, timeline = retained_history("count-group")
    inputs = verify_split_paint_inputs(layout, {})
    count = next(row.action for row in timeline.actions if row.action.verb == "count")
    obj = next(row for row in layout.objects if row.object_id == count.target_ids[0])
    v2_count.validate_count_glyphs(obj, count.count_policy, layout)
    assert v2_count._validate_glyph_inventory.cache_info().currsize > 0
    monkeypatch.setattr(Path, "read_bytes", lambda *a, **k: pytest.fail("Count cache reopened a source file"))
    index = next(i for i, (key, _, _) in enumerate(inputs.bundle_bytes) if key.endswith((".otf", ".ttf")))
    rows = list(inputs.bundle_bytes)
    key, _, data = rows[index]
    rows[index] = key, sha256(data + b"changed").hexdigest(), data + b"changed"
    style = json.loads(inputs.style_json)
    style["colors"]["ink"] = "#123456"
    changed_style = json.dumps(style, sort_keys=True, separators=(",", ":"))
    missing_font = tuple(row for i, row in enumerate(inputs.bundle_bytes) if i != index)
    for forged in (replace(inputs, bundle_bytes=tuple(rows)), replace(inputs, bundle_bytes=missing_font),
                   replace(inputs, style_json=changed_style)):
        with pytest.raises(ValueError):
            v2_count.validate_count_glyphs(obj, count.count_policy, layout, split_inputs=forged)


def test_cold_capture_uses_exact_private_carrier_without_changing_public_default(monkeypatch):
    from test_v2_split_families import geometry_split_family

    from atme.render import v2_split

    layout, before, action, *_ = geometry_split_family(False, "rectangle", "reveal")
    inputs = verify_split_paint_inputs(layout, {})
    legacy_calls = []

    def denied_legacy(*args, **kwargs):
        legacy_calls.append(args)
        raise AssertionError("legacy resolver unavailable")

    def forbidden(*args, **kwargs):
        raise AssertionError("private capture attempted original source IO")

    monkeypatch.setattr(v2_split, "resolve_contract_bundle", denied_legacy)
    monkeypatch.setattr(style_bundle, "load_bundle", forbidden)
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    with pytest.raises(AssertionError, match="legacy resolver unavailable"):
        v2_split.capture_split(action, layout, before, {})
    with pytest.raises(AssertionError, match="legacy resolver unavailable"):
        v2_split._capture_split(action, layout, before, {}, (), split_inputs=None)
    captured = v2_split._capture_split(action, layout, before, {}, (), split_inputs=inputs)
    assert set(captured.owned_root_ids) == {"source", "part-1", "part-2"}
    assert (captured.start_ms, captured.end_ms) == (action.start_ms, action.end_ms)
    key, _, data = inputs.bundle_bytes[0]
    changed = (key, sha256(data + b"changed").hexdigest(), data + b"changed")
    for forged in ({}, replace(inputs, bundle_bytes=inputs.bundle_bytes[1:]),
                   replace(inputs, bundle_bytes=(changed, *inputs.bundle_bytes[1:]))):
        with pytest.raises(ValueError):
            v2_split._capture_split(action, layout, before, {}, (), split_inputs=forged)
    assert legacy_calls == [(layout.style_system_version, layout.asset_registry_version)] * 2


def test_cold_capture_chronology_forwards_the_same_verified_value(monkeypatch):
    from test_v2_split_families import geometry_split_family

    from atme.render import v2_split
    from atme.render.v2_split_paint import _checked_split_resources
    from atme.render.v2_timeline_replay import _replay_split_chronology

    layout, before, _, timeline, *_ = geometry_split_family(False, "rectangle", "reveal")
    inputs = verify_split_paint_inputs(layout, {})
    assets = _checked_split_resources(layout, inputs)[3]
    original = v2_split._capture_split
    observed = []

    def capture(*args, **kwargs):
        observed.append(kwargs.get("split_inputs"))
        matches = kwargs.get("split_inputs") == inputs
        assert matches, "Chronology did not forward its exact verified carrier"
        return original(*args, **kwargs)

    monkeypatch.setattr(v2_split, "_capture_split", capture)
    _replay_split_chronology(layout, before, tuple(timeline.actions), timeline.duration_ms, assets, split_inputs=inputs)
    assert observed == [inputs]


def cold_count_case(output_dir: Path, portrait: bool) -> dict:
    """Actual frozen preview/export frames after denying original files and caches."""
    from atme.render import v2_state
    from atme.render.v2_hierarchy import HierarchySnapshot
    from atme.render.v2_split_paint import _checked_split_resources

    layout, timeline = retained_history("count-group", portrait)
    inputs = verify_split_paint_inputs(layout, {})
    style, _, files, _ = _checked_split_resources(layout, inputs)
    count = next(row.action for row in timeline.actions if row.action.verb == "count")
    target = next(row for row in layout.objects if row.object_id == count.target_ids[0])
    role = v2_svg._text_role(target, style)
    pinned = next(row for row in style.fonts if row.id == role.font_id)
    original = layout.model_dump_json(), timeline.model_dump_json(), inputs
    destination = Path(output_dir) / ("cold-count-portrait" if portrait else "cold-count-landscape")
    destination.mkdir(parents=True, exist_ok=False)
    font_path = destination / ("count-font" + Path(pinned.file).suffix)
    font_path.write_bytes(files[pinned.file])
    v2_count._validate_glyph_inventory.cache_clear()
    v2_svg._font.cache_clear()
    font, read_bytes, read_text = v2_svg._font, Path.read_bytes, Path.read_text
    observed_fonts = []

    def forbidden(*args, **kwargs):
        raise AssertionError("Cold Count preview/export reopened original files or network")

    def output_read(path, *args, **kwargs):
        if not path.resolve().is_relative_to(destination.resolve()):
            forbidden()
        return read_bytes(path, *args, **kwargs)

    def output_text(path, *args, **kwargs):
        if not path.resolve().is_relative_to(destination.resolve()):
            forbidden()
        return read_text(path, *args, **kwargs)

    def frozen_font(source, size):
        assert type(source) is bytes, "Cold Count preview/export requires frozen font bytes"
        observed_fonts.append(sha256(source).hexdigest())
        return font(source, size)

    split = next(row for row in timeline.actions if row.action.verb == "split")
    middle = (split.start_ms + split.end_ms) // 2
    order = (split.end_ms, split.start_ms, middle, 1999, 2500, 3000, middle, split.start_ms, split.end_ms)
    frames = {}
    with ExitStack() as isolated:
        isolated.enter_context(patch.object(style_bundle, "resolve_contract_bundle", forbidden))
        isolated.enter_context(patch.object(style_bundle, "load_bundle", forbidden))
        isolated.enter_context(patch.object(v2_state, "resolve_contract_bundle", forbidden))
        isolated.enter_context(patch.object(Path, "read_bytes", output_read))
        isolated.enter_context(patch.object(Path, "read_text", output_text))
        isolated.enter_context(patch.object(v2_svg, "_font", frozen_font))
        for key in ("socket", "create_connection", "getaddrinfo", "gethostbyname", "gethostbyname_ex",
                    "gethostbyaddr", "getnameinfo", "getfqdn"):
            isolated.enter_context(patch.object(socket, key, forbidden))
        context = v2_state._validate_pair_static(layout, timeline, timeline.layout_sha256,
            HierarchySnapshot.from_objects({obj.object_id: obj for obj in layout.objects}), split_inputs=inputs)
        replay, cameras = v2_state._validate_consumer_history(context, split_inputs=inputs)
        for at_ms in order:
            sample = v2_state._sample_validated_frame(layout, timeline, replay, cameras, at_ms)
            svg = v2_svg._compose_validated_svg_frame(layout, timeline, sample, {}, split_inputs=inputs)
            png = v2_svg._rasterize_svg_frame(layout, svg, split_inputs=inputs).png
            hashes = sha256(svg.svg.encode()).hexdigest(), sha256(png).hexdigest()
            if str(at_ms) in frames:
                assert hashes == (frames[str(at_ms)]["svg_sha256"], frames[str(at_ms)]["png_sha256"])
                continue
            png_path, svg_path = destination / f"{at_ms}.png", destination / f"{at_ms}.svg"
            png_path.write_bytes(png)
            svg_path.write_text(svg.svg, encoding="utf-8")
            frames[str(at_ms)] = {"svg_sha256": hashes[0], "png_sha256": hashes[1],
                "png_path": str(png_path), "svg_path": str(svg_path),
                "state_versions": dict(replay.at(at_ms).state_versions)}
        assert (layout.model_dump_json(), timeline.model_dump_json(), inputs) == original
    assert frames["1999"]["png_sha256"] == frames["3000"]["png_sha256"]
    assert frames["1999"]["state_versions"] == frames["3000"]["state_versions"]
    assert observed_fonts and set(observed_fonts) == {pinned.sha256}
    sheet = Image.new("RGB", (len(frames) * 240, 270), "#101722")
    labels = ImageDraw.Draw(sheet)
    for index, (at_ms, frame) in enumerate(sorted(frames.items(), key=lambda pair: int(pair[0]))):
        with Image.open(frame["png_path"]) as image:
            preview = image.convert("RGB")
        preview.thumbnail((230, 240), Image.Resampling.LANCZOS)
        sheet.paste(preview, (index * 240, 25))
        labels.text((index * 240 + 6, 6), at_ms + " ms", fill="white")
    sheet_path = destination / "contact.png"
    sheet.save(sheet_path)
    record = {"case_id": destination.name, "profile": layout.output_profile.profile_id,
        "network_forbidden": True, "original_bundle_and_paths_forbidden": True, "caches_cleared_before_validation": True,
        "immutable_input_keys_unchanged": True, "frozen_inputs_sha256": inputs.inputs_sha256,
        "count_metric_font_sha256": pinned.sha256, "font_path": str(font_path), "frames": frames,
        "seek_order_ms": order, "action_start_ms": split.start_ms, "action_end_ms": split.end_ms,
        "contact_sheet_path": str(sheet_path), "contact_sheet_sha256": sha256(sheet_path.read_bytes()).hexdigest(),
        "scope": "private frozen Count/Split preview-export mechanics; not creative/installed acceptance",
        "final_acceptance": False}
    (destination / "cold-count.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


@pytest.mark.parametrize("portrait", [False, True])
def test_cold_count_native_preview_export_and_return_pixels(tmp_path, portrait):
    record = cold_count_case(tmp_path, portrait)
    assert record["original_bundle_and_paths_forbidden"] and record["caches_cleared_before_validation"]
    assert record["network_forbidden"] and record["immutable_input_keys_unchanged"] and record["final_acceptance"] is False
    assert sha256(Path(record["font_path"]).read_bytes()).hexdigest() == record["count_metric_font_sha256"]
    width, height = (720, 1280) if portrait else (1280, 720)
    literal = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
        f'<rect width="{width}" height="{height}" fill="#FAF8F1"/>'
        '<g transform="matrix(2 0 0 3 90 30)"><text x="10" y="31.3333" fill="#172033" '
        'font-family="Atkinson Hyperlegible" font-weight="400" font-size="21.3333" '
        'xml:space="preserve"><tspan x="10" dy="0">10 widgets</tspan></text></g></svg>')
    expected = bytes(resvg_py.svg_to_bytes(svg_string=literal, font_files=[record["font_path"]], skip_system_fonts=True))
    first = record["frames"][str(record["action_start_ms"])]
    assert "10 widgets" in Path(first["svg_path"]).read_text(encoding="utf-8")
    with Image.open(BytesIO(expected)) as reference, Image.open(first["png_path"]) as actual:
        assert actual.size == (width, height)
        region = (100, 60, 500, 190)
        pixels_match = actual.convert("RGB").crop(region).tobytes() == reference.convert("RGB").crop(region).tobytes()
        assert pixels_match, "Cold Count glyph differs from the literal native oracle"
    assert record["frames"]["1999"]["png_sha256"] == record["frames"]["3000"]["png_sha256"]
    with Image.open(record["frames"]["2500"]["png_path"]) as blank:
        assert blank.convert("RGB").getextrema() == ((250, 250), (248, 248), (241, 241))
    assert len(record["seek_order_ms"]) > len(record["frames"])
    with Image.open(record["contact_sheet_path"]) as sheet:
        assert sheet.width == len(record["frames"]) * 240
    from test_v2_split_acceptance import split_benchmark

    assert split_benchmark().write_report(tmp_path, [record], diagnostic="cold-count") == 0
    report = json.loads((tmp_path / "split-cold-count-diagnostic.json").read_text(encoding="utf-8"))
    assert report["status"] == "DIAGNOSTIC ONLY" and report["final_acceptance"] is False
    assert report["missing_required_proofs"] and report["cases"][0]["case_id"] == record["case_id"]


def test_cold_count_cli_routes_both_profiles_without_granting_final_acceptance(tmp_path, monkeypatch):
    from test_v2_split_acceptance import split_benchmark

    benchmark = split_benchmark()
    calls = []

    def route(directory, portrait):
        assert directory == tmp_path
        calls.append(portrait)
        return {"portrait": portrait}

    def report(directory, cases, *, diagnostic):
        assert directory == tmp_path and cases == [{"portrait": False}, {"portrait": True}]
        assert diagnostic == "cold-count"
        return 0

    monkeypatch.setattr(sys.modules[__name__], "cold_count_case", route)
    monkeypatch.setattr(benchmark, "write_report", report)
    assert benchmark.main(["--output-dir", str(tmp_path), "--diagnostic-family", "cold-count"]) == 0
    assert calls == [False, True]
