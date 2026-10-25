"""Task10 offline source proof. Partial diagnostics never grant final acceptance."""

from __future__ import annotations

import argparse
import json
import socket
import sys
from contextlib import ExitStack
from dataclasses import asdict
from functools import partial
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
for source in (ROOT / "sidecar/tests", ROOT / "sidecar/src"):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

from test_v2_media_runtime import patterned_media_bytes
from test_v2_split_callout_family import callout_split_fixture
from test_v2_split_chart_family import chart_split_family
from test_v2_split_code_family import code_split_family
from test_v2_split_connector_family import connector_split_family
from test_v2_split_container_family import mask_split_family
from test_v2_split_evidence_family import short_evidence_documents
from test_v2_split_families import GEOMETRY_KINDS, geometry_split_family
from test_v2_split_list_family import (
    structured_list_split_family,
    text_list_split_family,
)
from test_v2_split_media_family import media_family
from test_v2_split_reusable_family import reusable_split_family
from test_v2_split_visual_family import illustration_boundary, split_timeline
from test_v2_split_visual_family_boundaries import aperture_boundary, registry_boundary
from test_v2_split_visual_family_matrix import STATE_CASES, visual_state_layout

from atme.render.v2_split_clock import resolve_split_phase
from atme.render.v2_split_paint import verify_split_paint_inputs
from atme.render.v2_state import _sample_validated_frame, camera_segments
from atme.render.v2_svg import (
    _authored_annotation_bindings,
    _compose_validated_svg_frame,
    _rasterize_svg_frame,
)
from atme.render.v2_timeline_replay import _replay_split_chronology

TEXT_KINDS = ("text", "flat", "structured", "nested")
CODE_KINDS = ("plain", "tokens")
CALLOUT_KINDS = ("unboxed", "boxed")
CHART_KINDS = ("bars", "line")
MEDIA_KINDS = ("image", "video", "presenter", "screen_recording")
VISUAL_KINDS = ("illustration", "character", "technical")
CONTAINER_KINDS = ("group", "clip", "mask-source", "mask-result", "composition", "instance")
EVIDENCE_KINDS = ("plain", "annotated", "source")
CONNECTOR_KINDS = ("arrow", "network", "pointer")
CONNECTOR_ROUTES = ("straight", "elbow", "curve")
APERTURE_KINDS = ("group", "clip", "mask")
REGISTRY_ROLES = (("source", "reveal"), ("part-1", "reveal"), ("part-1", "enter"),
                  ("part-2", "reveal"), ("part-2", "enter"))


def no_network(*args, **kwargs):
    raise AssertionError("Offline Split proof attempted network access")


def verify_import_origins() -> int:
    source = (ROOT / "sidecar/src").resolve()
    checked = 0
    for name, module in tuple(sys.modules.items()):
        if name == "atme" or name.startswith("atme."):
            origin = getattr(module, "__file__", None)
            if origin is None or not Path(origin).resolve().is_relative_to(source):
                raise ValueError(f"Split isolated import origin mismatch: {name}: {origin}")
            checked += 1
        elif name.startswith("test_v2_") or name in {"v2_fixtures", "v2_split_fixtures"}:
            origin = getattr(module, "__file__", None)
            expected = (ROOT / "sidecar/tests" / f"{name}.py").resolve()
            if origin is None or Path(origin).resolve() != expected:
                raise ValueError(f"Split isolated fixture origin mismatch: {name}: {origin}")
            checked += 1
    return checked


def _native_case(output_dir: Path, portrait: bool, kind: str, mode: str, family: str, fixture,
                 *, extra_offsets: tuple[int, ...] = ()) -> dict:
    """Each fixture supplies layout, initial state, action, timeline and checked assets."""
    origins_before = verify_import_origins()
    case_id = f"{family}-{kind}-{mode}-{'portrait' if portrait else 'landscape'}"
    destination = output_dir / case_id
    destination.mkdir(parents=True, exist_ok=False)
    with ExitStack() as offline:
        for entry in ("socket", "create_connection", "getaddrinfo", "gethostbyname", "gethostbyname_ex",
                      "gethostbyaddr", "getnameinfo", "getfqdn"):
            offline.enter_context(patch.object(socket, entry, no_network))
        layout, before, action, timeline, assets = fixture(portrait, kind, mode)
        policy = action.action.split_policy
        first_start, first_end = resolve_split_phase(action.start_ms, action.end_ms,
                                                     policy.results[0].construction.phase)
        _, source_end = resolve_split_phase(action.start_ms, action.end_ms, policy.source_exit)
        midpoint = (first_start + first_end) // 2
        seek_order = (action.end_ms, action.start_ms, midpoint, action.end_ms - 1,
                      first_end, source_end, midpoint, action.start_ms, action.end_ms)
        seek_order += tuple(action.start_ms + offset for offset in extra_offsets)
        inputs = verify_split_paint_inputs(layout, assets)
        keys_before = (layout.model_dump_json(), timeline.model_dump_json(), inputs.inputs_sha256,
                       inputs.manifest_json, inputs.bundle_bytes, inputs.asset_pins_json, inputs.project_assets)
        started = perf_counter()
        timeline_context = timeline if layout.evidence_treatments else None
        replay = _replay_split_chronology(layout, before, tuple(timeline.actions), timeline.duration_ms, assets,
                                          timeline=timeline_context)
        cameras = camera_segments(layout, timeline, replay, split_inputs=inputs)
        held = {key: _sample_validated_frame(layout, timeline, replay, cameras, end)
                for key, _, _, end in _authored_annotation_bindings(timeline)}
        construction_ms = (perf_counter() - started) * 1000
        frames, durations = {}, []
        for at in seek_order:
            started = perf_counter()
            snapshot = _sample_validated_frame(layout, timeline, replay, cameras, at)
            svg = _compose_validated_svg_frame(layout, timeline, snapshot, held, assets, split_inputs=inputs)
            png = _rasterize_svg_frame(layout, svg, split_inputs=inputs).png
            durations.append((perf_counter() - started) * 1000)
            hashes = (sha256(svg.svg.encode()).hexdigest(), sha256(png).hexdigest())
            observed = replay.at(at)
            state_versions = dict(observed.state_versions)
            state_hashes = {obj.object_id: sha256(json.dumps(asdict(obj), sort_keys=True,
                separators=(",", ":"), allow_nan=False).encode()).hexdigest() for obj in observed.objects}
            if str(at) in frames:
                prior = frames[str(at)]
                if (hashes != (prior["svg_sha256"], prior["png_sha256"])
                        or state_versions != prior["state_versions"] or state_hashes != prior["state_sha256"]):
                    raise AssertionError(f"Non-deterministic Split seek: {case_id}/{at}")
                continue
            png_path, svg_path = destination / f"{at}.png", destination / f"{at}.svg"
            png_path.write_bytes(png)
            svg_path.write_bytes(svg.svg.encode("utf-8"))
            frames[str(at)] = {"png_sha256": hashes[1], "svg_sha256": hashes[0],
                "png_path": str(png_path.resolve()), "svg_path": str(svg_path.resolve()),
                "state_versions": state_versions, "state_sha256": state_hashes}
        keys_after = (layout.model_dump_json(), timeline.model_dump_json(), inputs.inputs_sha256,
                      inputs.manifest_json, inputs.bundle_bytes, inputs.asset_pins_json, inputs.project_assets)
        if keys_before != keys_after:
            raise AssertionError(f"Split proof mutated its inputs: {case_id}")
    sheet = Image.new("RGB", (len(frames) * 240, 275 if portrait else 160), "#101722")
    label = ImageDraw.Draw(sheet)
    for column, at in enumerate(sorted(map(int, frames))):
        with Image.open(frames[str(at)]["png_path"]) as image:
            image = image.convert("RGB")
            image.thumbnail((235, sheet.height - 25), Image.Resampling.LANCZOS)
            sheet.paste(image, (column * 240, 25))
        label.text((column * 240 + 4, 4), f"{at} ms", fill="white")
    sheet_path = destination / "contact.png"
    sheet.save(sheet_path)
    return {"case_id": case_id, "family": family, "kind": kind, "mode": mode,
        "profile": layout.output_profile.profile_id, "frames": frames,
        "seek_order_ms": list(seek_order), "network_forbidden": True,
        "action_start_ms": action.start_ms, "action_end_ms": action.end_ms,
        "chronology_action_ids": [row.action.action_id for row in timeline.actions],
        "immutable_input_keys_unchanged": True, "paint_inputs_sha256": inputs.inputs_sha256,
        "asset_pins_json": inputs.asset_pins_json, "verified_project_asset_count": len(inputs.project_assets),
        "style_json": inputs.style_json, "chronology_construction_ms": construction_ms,
        "verified_import_origins_before": origins_before, "verified_import_origins_after": verify_import_origins(),
        "sample_compose_raster_ms": durations, "contact_sheet_path": str(sheet_path.resolve()),
        "contact_sheet_sha256": sha256(sheet_path.read_bytes()).hexdigest()}


def _geometry_fixture(portrait, kind, mode):
    return (*geometry_split_family(portrait, kind, mode)[:4], {})


def geometry_case(output_dir: Path, portrait: bool, kind: str, mode: str) -> dict:
    return _native_case(output_dir, portrait, kind, mode, "geometry", _geometry_fixture)


def _text_fixture(portrait, kind, mode):
    if kind in {"text", "flat"}:
        case = text_list_split_family(portrait, mode, flat=kind == "flat")
    elif kind in {"structured", "nested"}:
        case = structured_list_split_family(portrait, mode, nested=kind == "nested")
    else:
        raise ValueError(f"Unsupported authored text/list variant: {kind}")
    return (*case[:4], {})


def text_case(output_dir: Path, portrait: bool, kind: str, mode: str) -> dict:
    return _native_case(output_dir, portrait, kind, mode, "text-list", _text_fixture)


def _code_fixture(portrait, kind, mode):
    if kind not in CODE_KINDS:
        raise ValueError(f"Unsupported authored code variant: {kind}")
    return (*code_split_family(portrait, mode, tokens=kind == "tokens")[:4], {})


def code_case(output_dir: Path, portrait: bool, kind: str, mode: str) -> dict:
    return _native_case(output_dir, portrait, kind, mode, "code", _code_fixture)


def _callout_fixture(portrait, kind, mode):
    if kind not in CALLOUT_KINDS:
        raise ValueError(f"Unsupported authored Callout variant: {kind}")
    layout, initial, _, _, split, timeline, _ = callout_split_fixture(portrait, mode, boxed=kind == "boxed")
    return layout, initial, split, timeline, {}


def callout_case(output_dir: Path, portrait: bool, kind: str, mode: str) -> dict:
    return _native_case(output_dir, portrait, kind, mode, "callout", _callout_fixture)


def _chart_fixture(portrait, kind, mode):
    if kind not in CHART_KINDS:
        raise ValueError(f"Unsupported authored Chart variant: {kind}")
    return (*chart_split_family(portrait, kind, mode)[:4], {})


def chart_case(output_dir: Path, portrait: bool, kind: str, mode: str) -> dict:
    return _native_case(output_dir, portrait, kind, mode, "chart", _chart_fixture)


def _media_fixture(portrait, kind, mode):
    if kind not in MEDIA_KINDS:
        raise ValueError(f"Unsupported authored media variant: {kind}")
    raw = None if kind == "image" else patterned_media_bytes()
    layout, initial, action, timeline, carrier, _ = media_family(portrait, mode, raw=raw, kind=kind)
    return layout, initial, action, timeline, carrier


def media_case(output_dir: Path, portrait: bool, kind: str, mode: str) -> dict:
    return _native_case(output_dir, portrait, kind, mode, "media", _media_fixture, extra_offsets=(5, 3, 5))


def _visual_fixture(portrait, kind, mode):
    if kind not in VISUAL_KINDS:
        raise ValueError(f"Unsupported authored visual variant: {kind}")
    layout, initial, action, _ = illustration_boundary(portrait=portrait, family=kind, mode=mode)
    return layout, initial, action, split_timeline(layout, initial, action), {}


def visual_case(output_dir: Path, portrait: bool, kind: str, mode: str) -> dict:
    return _native_case(output_dir, portrait, kind, mode, "visual", _visual_fixture)


def _visual_state_fixture(portrait, kind, mode, *, family, state, owner):
    layout, before, action, _ = visual_state_layout(family, kind, state, portrait, owner=owner, mode=mode)
    return layout, before, action, split_timeline(layout, before, action), {}


def visual_state_case(output_dir: Path, portrait: bool, family: str, kind: str, state, owner: str, mode: str) -> dict:
    modes = ("reveal",) if owner == "source" else (
        ("reveal", "enter", "draw") if family == "character" else ("reveal", "enter"))
    if (not any(family == f and kind == k and type(state) is type(s) and state == s for f, k, s in STATE_CASES)
            or owner not in ("source", "part-1", "part-2") or mode not in modes):
        raise ValueError("Unsupported authored visual state/role/mode selector")
    record = _native_case(output_dir, portrait, kind, mode,
        f"visual-state-{family}-{str(state).lower()}-{owner}",
        partial(_visual_state_fixture, family=family, state=state, owner=owner), extra_offsets=(1, 36, 41, 1, 41))
    record.update(family="visual-state", visual_family=family, state=state, owner=owner)
    return record


def _aperture_fixture(portrait, kind, _mode, *, family):
    layout, before, action, _ = aperture_boundary(family, portrait, kind)
    return layout, before, action, split_timeline(layout, before, action), {}


def aperture_case(output_dir: Path, portrait: bool, family: str, kind: str) -> dict:
    if family not in VISUAL_KINDS or kind not in APERTURE_KINDS:
        raise ValueError("Unsupported authored read-aperture selector")
    record = _native_case(output_dir, portrait, kind, "reveal", f"aperture-{family}",
        partial(_aperture_fixture, family=family), extra_offsets=(1, 36, 41, 1, 41))
    record.update(family="aperture", visual_family=family)
    return record


def _registry_fixture(portrait, owner, mode):
    layout, before, action, _ = registry_boundary(portrait, owner, mode)
    return layout, before, action, split_timeline(layout, before, action), {}


def registry_case(output_dir: Path, portrait: bool, owner: str, mode: str) -> dict:
    if (owner, mode) not in REGISTRY_ROLES:
        raise ValueError("Unsupported authenticated registry selector")
    return _native_case(output_dir, portrait, owner, mode, "registry", _registry_fixture,
        extra_offsets=(1, 36, 41, 1, 41))


def _container_fixture(portrait, kind, mode):
    if kind not in CONTAINER_KINDS:
        raise ValueError(f"Unsupported authored container variant: {kind}")
    content = "code" if mode == "write" else "rectangle"
    if kind in {"mask-source", "mask-result"}:
        root_id = "source" if kind == "mask-source" else "part-1"
        case = mask_split_family(portrait, root_id, mode, content=content)
    else:
        case = reusable_split_family(portrait, kind, mode, content=content)
    return (*case[:4], {})


def container_case(output_dir: Path, portrait: bool, kind: str, mode: str) -> dict:
    return _native_case(output_dir, portrait, kind, mode, "container", _container_fixture)


def _evidence_fixture(output_dir, portrait, kind, mode):
    directory = output_dir / f"project-{kind}-{mode}-{'portrait' if portrait else 'landscape'}"
    directory.mkdir()
    _, layout, initial, timeline, carrier = short_evidence_documents(directory, portrait, mode, variant=kind)
    action = next(row for row in timeline.actions if row.action.verb == "split")
    return layout, initial, action, timeline, carrier


def evidence_case(output_dir: Path, portrait: bool, kind: str, mode: str) -> dict:
    if kind not in EVIDENCE_KINDS:
        raise ValueError(f"Unsupported authored evidence variant: {kind}")
    if mode not in {"reveal", "enter"}:
        raise ValueError(f"Unsupported authored evidence mode: {mode}")
    return _native_case(output_dir, portrait, kind, mode, "evidence", partial(_evidence_fixture, output_dir),
                        extra_offsets=(-1, 36, 2539, -1, 2539))


def _connector_fixture(portrait, kind, mode, *, routing):
    return (*connector_split_family(portrait, kind, mode, routing)[:4], {})


def connector_case(output_dir: Path, portrait: bool, kind: str, mode: str, routing: str) -> dict:
    if kind not in CONNECTOR_KINDS:
        raise ValueError(f"Unsupported authored connector variant: {kind}")
    if mode not in {"reveal", "draw"}:
        raise ValueError(f"Unsupported authored connector mode: {mode}")
    if routing not in CONNECTOR_ROUTES:
        raise ValueError(f"Unsupported authored connector routing: {routing}")
    record = _native_case(output_dir, portrait, kind, mode, f"connector-{routing}",
                          partial(_connector_fixture, routing=routing), extra_offsets=(1, 36, 41, 1, 41))
    record.update(family="connector", routing=routing)
    return record


def write_report(output_dir: Path, cases: list[dict], *, diagnostic: str | None = None) -> int:
    """Retain measured evidence without silently upgrading a partial proof."""
    output_dir.mkdir(parents=True, exist_ok=True)
    report = {"scope": "private source compositor; not public/installed/creative acceptance",
        "status": "DIAGNOSTIC ONLY" if diagnostic else "INCOMPLETE", "final_acceptance": False,
        "cases": cases, "missing_required_proofs": [
            "complete approved eight-family/profile/mode and source/result matrix",
            "cross-matrix parents/apertures/prior-actions/array-order/same-time/negative reservations",
            "normal stored/duplicate/A-B-A flows at the final matrix boundary",
            "256-result and4096-bound-object cold/warm seek time/memory/immutable-key measurements",
            "cold Count font policy without original bundle/cache reads",
            "all50 retained old offline frame/report hashes and v1/Caleb regression",
            "same independent reviewer Task10 acceptance",
        ]}
    path = output_dir / (f"split-{diagnostic}-diagnostic.json" if diagnostic else "split-acceptance.json")
    with path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(f"{report['status']}: {len(cases)} cases; {path}")
    return 0 if diagnostic else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--diagnostic-family", choices=(
        "geometry", "text-list", "code", "callout", "chart", "media", "visual", "container", "evidence", "connector",
        "visual-state", "aperture", "registry"))
    args = parser.parse_args(argv)
    verify_import_origins()
    cases = []
    if args.diagnostic_family == "geometry":
        for portrait in (False, True):
            for kind in GEOMETRY_KINDS:
                for mode in ("draw", "reveal", "enter"):
                    cases.append(geometry_case(args.output_dir, portrait, kind, mode))
    elif args.diagnostic_family == "text-list":
        for portrait in (False, True):
            for kind in TEXT_KINDS:
                for mode in ("write", "reveal", "enter"):
                    cases.append(text_case(args.output_dir, portrait, kind, mode))
    elif args.diagnostic_family == "code":
        for portrait in (False, True):
            for kind in CODE_KINDS:
                for mode in ("write", "reveal", "enter"):
                    cases.append(code_case(args.output_dir, portrait, kind, mode))
    elif args.diagnostic_family == "callout":
        for portrait in (False, True):
            for kind in CALLOUT_KINDS:
                for mode in ("write", "reveal", "enter"):
                    cases.append(callout_case(args.output_dir, portrait, kind, mode))
    elif args.diagnostic_family == "chart":
        for portrait in (False, True):
            for kind in CHART_KINDS:
                for mode in ("draw", "reveal", "enter"):
                    cases.append(chart_case(args.output_dir, portrait, kind, mode))
    elif args.diagnostic_family == "media":
        for portrait in (False, True):
            for kind in MEDIA_KINDS:
                for mode in ("reveal", "enter"):
                    cases.append(media_case(args.output_dir, portrait, kind, mode))
    elif args.diagnostic_family == "visual":
        for portrait in (False, True):
            for kind in VISUAL_KINDS:
                for mode in (("reveal", "enter", "draw") if kind == "character" else ("reveal", "enter")):
                    cases.append(visual_case(args.output_dir, portrait, kind, mode))
    elif args.diagnostic_family == "visual-state":
        for portrait in (False, True):
            for family, kind, state in STATE_CASES:
                for owner in ("source", "part-1", "part-2"):
                    for mode in (("reveal",) if owner == "source" else
                                 ("reveal", "enter", "draw") if family == "character" else ("reveal", "enter")):
                        cases.append(visual_state_case(args.output_dir, portrait, family, kind, state, owner, mode))
    elif args.diagnostic_family == "aperture":
        for portrait in (False, True):
            for family in ("character", "illustration", "technical"):
                for kind in APERTURE_KINDS:
                    cases.append(aperture_case(args.output_dir, portrait, family, kind))
    elif args.diagnostic_family == "registry":
        for portrait in (False, True):
            for owner, mode in REGISTRY_ROLES:
                cases.append(registry_case(args.output_dir, portrait, owner, mode))
    elif args.diagnostic_family == "container":
        for portrait in (False, True):
            for kind in CONTAINER_KINDS:
                for mode in ("reveal", "draw", "enter", "write"):
                    cases.append(container_case(args.output_dir, portrait, kind, mode))
    elif args.diagnostic_family == "evidence":
        for portrait in (False, True):
            for kind in EVIDENCE_KINDS:
                for mode in ("reveal", "enter"):
                    cases.append(evidence_case(args.output_dir, portrait, kind, mode))
    elif args.diagnostic_family == "connector":
        for portrait in (False, True):
            for kind in CONNECTOR_KINDS:
                for mode in ("reveal", "draw"):
                    for routing in CONNECTOR_ROUTES:
                        cases.append(connector_case(args.output_dir, portrait, kind, mode, routing))
    return write_report(args.output_dir, cases, diagnostic=args.diagnostic_family)


if __name__ == "__main__":
    raise SystemExit(main())
