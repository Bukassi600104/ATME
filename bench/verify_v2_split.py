"""Task10 offline source proof. Partial diagnostics never grant final acceptance."""

from __future__ import annotations

import argparse
import json
import socket
import sys
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import asdict
from functools import partial
from hashlib import sha256
from io import BytesIO
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
from test_v2_split_return import retained_history
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
    compose_png_frame,
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
HISTORY_KINDS = ("common-group", "distinct-group", "common-clip", "distinct-clip", "nested-clips",
                 "count-group", "group-count", "morph", "descendants")


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
                 *, extra_offsets: tuple[int, ...] = (), extra_times: tuple[int, ...] = ()) -> dict:
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
        seek_order += extra_times
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


def _history_fixture(portrait, kind, _mode, *, reverse_objects):
    from test_v2_split_capture import ancestor_boundary
    from test_v2_split_contract import split_with_earlier_ancestor
    from test_v2_split_identity import sample_for_layout
    from v2_fixtures import digest
    from v2_split_fixtures import split_documents

    from atme.render.v2_hierarchy_replay import completed_hierarchy_basis
    from atme.render.v2_split import _observed_split_placements
    from atme.render.v2_split_identity import split_content_receipts
    from atme.store.contracts_v2 import (
        ExecutableLayoutV2,
        ResolvedAction,
        ResolvedVisualTimelineV2,
        SplitPolicy,
        _split_expected_completion,
    )

    if kind in HISTORY_KINDS[:5]:
        layout, _, split = ancestor_boundary(aperture="clip" in kind, distinct=kind.startswith("distinct"))
        drawing = layout.model_dump(mode="json")
        _, profile, _ = split_documents("SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9")
        drawing.update(output_profile=profile["output_profile"], canvas=profile["canvas"])
        if kind == "nested-clips":
            earlier = next(row for row in drawing["objects"] if row["object_id"] == "earlier")
            outer = deepcopy(earlier)
            outer.update(object_id="outer-stage", parent_id=None, child_ids=["earlier"],
                initial_state="visible", visible=True, anchors=[],
                style={"stroke": None, "fill": None, "text": None, "effect": None})
            outer["geometry"]["bounds"].update(x=100., y=50., width=30., height=50.)
            outer["transform"].update(position={"x": 0., "y": 0.}, scale_x=1., scale_y=1.,
                                      rotation_degrees=0., origin={"x": 0., "y": 0.})
            earlier["parent_id"] = "outer-stage"
            drawing["objects"].append(outer)
            drawing["boards"][0]["object_ids"].append("outer-stage")
        layout = ExecutableLayoutV2.model_validate(drawing)
        initial = sample_for_layout(layout)
        _, _, clock = split_with_earlier_ancestor()
        prior = ResolvedAction.model_validate(clock["actions"][0])
        before = _replay_split_chronology(layout, initial, (prior,), clock["duration_ms"], {}).at(split.start_ms)
        packet = split.model_dump(mode="json")
        packet["end_ms"] = packet["start_ms"] + 40
        policy = packet["action"]["split_policy"]
        if kind == "nested-clips":
            for dependency in policy["source_basis"]["read_dependencies"]:
                dependency["object_ids"] = ["earlier", "outer-stage"]
        objects = before.hierarchy.object_map({obj.object_id: obj for obj in layout.objects})
        contents = {row.object_id: row for row in split_content_receipts(layout, before, {})}
        policy["source_basis"]["placements"] = [row.model_dump(mode="json") for row in
            _observed_split_placements(before, objects, set(objects), contents)]
        for row in policy["correspondences"]:
            row.update(source_content_sha256=contents["source"].content_sha256,
                       result_content_sha256=contents[row["result_object_id"]].content_sha256)
        policy["source_basis_sha256"] = digest(policy["source_basis"])
        receipt = _split_expected_completion(SplitPolicy.model_validate(policy))
        receipt["completion_sha256"] = digest(receipt)
        packet["split_completion_receipt"] = receipt
        clock["actions"] = [prior.model_dump(mode="json"), packet]
    else:
        layout, timeline = retained_history(kind, portrait)
        drawing, clock = layout.model_dump(mode="json"), timeline.model_dump(mode="json")
        split = next(row for row in clock["actions"] if row["action"]["verb"] == "split")
        split["end_ms"] = split["start_ms"] + 40
    if reverse_objects:
        drawing["objects"].reverse()
    layout = ExecutableLayoutV2.model_validate(drawing)
    initial = sample_for_layout(layout)
    clock.update(layout_sha256=digest(drawing), output_profile=drawing["output_profile"],
        initial_object_states=[{"object_id": row.object_id, "state": row.state, "visible": row.visible,
            "state_version": dict(initial.state_versions)[row.object_id]} for row in initial.objects])
    if clock.get("initial_hierarchy_basis") is not None:
        basis = completed_hierarchy_basis(initial.hierarchy, {row.object_id: row for row in initial.objects})
        clock.update(initial_hierarchy_basis=basis.model_dump(mode="json"), initial_hierarchy_basis_sha256=basis.checksum())
    timeline = ResolvedVisualTimelineV2.model_validate(clock)
    action = next(row for row in timeline.actions if row.action.verb == "split")
    return layout, initial, action, timeline, {}


def history_case(output_dir: Path, portrait: bool, kind: str, *, reverse_objects: bool = False) -> dict:
    if kind not in HISTORY_KINDS or type(reverse_objects) is not bool:
        raise ValueError("Unsupported authored history selector")
    record = _native_case(output_dir, portrait, kind, "authored", f"history-{'reversed' if reverse_objects else 'authored'}",
        partial(_history_fixture, reverse_objects=reverse_objects), extra_offsets=(1, 36, 41, 1, 41),
        extra_times=(0, 100, 499) if kind in HISTORY_KINDS[:5] else (1999, 2500, 3000, 3001))
    record.update(family="history", reverse_objects=reverse_objects)
    return record


def retained_frames_case(output_dir: Path) -> dict:
    """Regenerate the original paired pixels without rewriting their historical reports."""
    from test_v2_annotation_action import append_target
    from test_v2_annotation_contract import leader_documents
    from test_v2_group_annotation import (
        annotation_group_documents,
        consumer_clock,
        private_svg,
        regroup_first_documents,
    )
    from v2_fixtures import digest

    baseline_dir = ROOT / "docs/visual-acceptance"
    if output_dir.resolve().is_relative_to(baseline_dir.resolve()):
        raise ValueError("Accepted baseline directory is read-only")
    pins = {
        "phase-3z-annotation.json": "86d4e25c6c969281891862f8de2f589b5efc66404a7f6b7d3a4560f7127b0b70",
        "phase-3z-annotation.png": "112a6c9f980f05d62f6d0fbbaf83a317f7d9f5d859122c2f7507c3a2c4ef6a4f",
        "phase-3aa-group-annotation.json": "7489307543d1d562a10b22eb782c79392cc0ec0144e3aba9bc2223adb5aed08a",
        "phase-3aa-group-annotation.png": "4b04705e56c18687c7bb289c375c5f16e14b83c5dfa92cba4ca00033cf43549c",
    }
    assert all(sha256((baseline_dir / name).read_bytes()).hexdigest() == value for name, value in pins.items())
    origins_before = verify_import_origins()
    destination = output_dir / "retained-baselines"
    destination.mkdir(parents=True, exist_ok=False)
    corpora = []
    with ExitStack() as offline:
        for entry in ("socket", "create_connection", "getaddrinfo", "gethostbyname", "gethostbyname_ex",
                      "gethostbyaddr", "getnameinfo", "getfqdn"):
            offline.enter_context(patch.object(socket, entry, no_network))
        for kind, stem, size in (("annotation", "phase-3z-annotation", (1920, 720)),
                                 ("group", "phase-3aa-group-annotation", (2000, 2880))):
            expected = json.loads((baseline_dir / (stem + ".json")).read_text(encoding="utf-8"))
            corpus = {"corpus": kind, "frames": [], "frame_paths": []}
            sheet = Image.new("RGB", size, "#101722")
            labels = ImageDraw.Draw(sheet)
            selections = ((None, False), (None, True)) if kind == "annotation" else tuple(
                (mode, portrait) for mode in ("ungroup", "group", "note-after-exit", "target-after-exit")
                for portrait in (False, True))
            for row_index, (mode, portrait) in enumerate(selections):
                if kind == "annotation":
                    _, layout, timeline = leader_documents()
                    if portrait:
                        for doc in (layout, timeline):
                            doc["output_profile"] = {"profile_id": "SHORT_FORM_9_16", "width": 720, "height": 1280, "fps": 30}
                        layout["canvas"].update(width=720, height=1280)
                        layout["objects"][-1]["geometry"]["bounds"]["width"] = 600
                        timeline["layout_sha256"] = digest(layout)
                    moments = (6000, 6250, 6500, 6750, 7000)
                    origin_y = 280 if portrait else 0
                    original = deepcopy((layout, timeline))
                else:
                    if mode in {"group", "ungroup"}:
                        builder = regroup_first_documents if mode == "group" else annotation_group_documents
                        layout, timeline = builder(nested=True, portrait=portrait)
                        moments = (5999, 6000, 6500, 6750, 7999)
                    else:
                        shell = "annotation-group" if mode == "note-after-exit" else "target-group"
                        layout, timeline = annotation_group_documents(shell, 8250, 8700, portrait=portrait)
                        append_target(timeline, "annotation-leader", "exit", 8000, 8250)
                        moments = (7999, 8125, 8250, 8699, 8700)
                    timeline["layout_sha256"] = digest(layout)
                    original = deepcopy((layout, timeline))
                    context, replay, camera = consumer_clock(layout, timeline)
                    origin_y = row_index * 360
                profile = layout["output_profile"]["profile_id"]
                label = profile + " / authored note then pointer" if kind == "annotation" else f"{mode} / {profile}"
                labels.text((10, origin_y + 4), label, fill="white")
                for column, moment in enumerate(moments):
                    if kind == "annotation":
                        raw = compose_png_frame(layout, timeline, moment).png
                        compose_png_frame(layout, timeline, 7999)
                        repeated = compose_png_frame(layout, timeline, moment).png
                        frame_row = {"profile": profile, "at_ms": moment, "sha256": sha256(raw).hexdigest()}
                    else:
                        svg = private_svg(context, replay, camera, moment)
                        raw = _rasterize_svg_frame(context.layout, svg).png
                        private_svg(context, replay, camera, 9000)
                        repeated = _rasterize_svg_frame(context.layout, private_svg(context, replay, camera, moment)).png
                        frame_row = {"mode": mode, "profile": profile, "at_ms": moment,
                            "layout_sha256": digest(layout), "timeline_sha256": digest(timeline),
                            "svg_sha256": sha256(svg.svg.encode("utf-8")).hexdigest(), "png_sha256": sha256(raw).hexdigest()}
                    pixels_match = raw == repeated
                    assert pixels_match, f"Retained {kind} random seek differs at {moment}"
                    index = len(corpus["frames"])
                    assert frame_row == expected["frames"][index], f"Retained {kind} frame {index} differs"
                    frame_path = destination / f"{stem}-{index:02d}.png"
                    frame_path.write_bytes(raw)
                    corpus["frames"].append(frame_row)
                    corpus["frame_paths"].append(str(frame_path))
                    with Image.open(BytesIO(raw)) as image:
                        frame = image.convert("RGB")
                    if kind == "annotation":
                        frame = frame.resize((224, 398) if portrait else (384, 216))
                        x = column * 384
                    else:
                        frame.thumbnail((384, 320), Image.Resampling.LANCZOS)
                        x = column * 400
                    sheet.paste(frame, (x, origin_y + 35))
                    labels.text((x + 10, origin_y + 20), f"{moment} ms", fill="white")
                assert (layout, timeline) == original, f"Retained {kind} inputs changed"
            assert corpus["frames"] == expected["frames"]
            sheet_path = destination / (stem + ".png")
            sheet.save(sheet_path)
            sheet_sha = sha256(sheet_path.read_bytes()).hexdigest()
            assert sheet_sha == expected["contact_sheet_sha256"], f"Retained {kind} contact sheet differs"
            corpus.update(contact_sheet_path=str(sheet_path), contact_sheet_sha256=sheet_sha)
            corpora.append(corpus)
    assert all(sha256((baseline_dir / name).read_bytes()).hexdigest() == value for name, value in pins.items())
    assert sum(len(corpus["frames"]) for corpus in corpora) == 50
    return {"case_id": "retained-50-annotation-group", "family": "retained-baselines", "frame_count": 50,
        "final_acceptance": False, "network_forbidden": True, "random_seek_parity": True,
        "immutable_input_keys_unchanged": True, "original_baselines_unchanged": True,
        "baseline_file_sha256": pins, "corpora": corpora,
        "origins_before": origins_before, "origins_after": verify_import_origins(),
        "historical_scope_qualification": "The original public Group closed scope and rejection assertion are obsolete; "
            "current proof preserves the original private consumer, ordered rows and exact pixels, not that assertion."}


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
        "visual-state", "aperture", "registry", "history", "retained-baselines", "cold-count", "project-flows"))
    parser.add_argument("--source-video", type=Path, help="Local recording for project-flows diagnostics")
    args = parser.parse_args(argv)
    verify_import_origins()
    cases = []
    if args.diagnostic_family == "project-flows":
        if args.source_video is None:
            parser.error("--source-video is required for project-flows")
        from test_v2_split_project_flows import (
            PROJECT_FLOW_KINDS,
            project_flow_case,
            project_flow_report,
        )

        video = args.source_video.read_bytes()
        cases = [project_flow_case(args.output_dir, portrait, kind, video)
                 for kind in PROJECT_FLOW_KINDS for portrait in (False, True)]
        return project_flow_report(args.output_dir, cases)
    if args.diagnostic_family == "retained-baselines":
        cases.append(retained_frames_case(args.output_dir))
    elif args.diagnostic_family == "cold-count":
        from test_v2_split_cold_count import cold_count_case

        cases.extend(cold_count_case(args.output_dir, portrait) for portrait in (False, True))
    elif args.diagnostic_family == "geometry":
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
    elif args.diagnostic_family == "history":
        for portrait in (False, True):
            for kind in HISTORY_KINDS:
                for reverse_objects in (False, True):
                    cases.append(history_case(args.output_dir, portrait, kind, reverse_objects=reverse_objects))
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
