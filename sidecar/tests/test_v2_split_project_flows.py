"""Video-only stored retained histories: private diagnostic proof, never final acceptance."""

import json
import socket
import sys
from contextlib import ExitStack
from dataclasses import asdict
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest
import resvg_py
from PIL import Image, ImageDraw
from test_v2_media_decode import encoded_vfr
from test_v2_media_project import original_video
from test_v2_split_project import artifact_rows, stored_split_basis
from v2_fixtures import digest

__all__ = ["encoded_vfr", "original_video"]

PROJECT_FLOW_KINDS = ("geometry", "count-group", "group-count", "morph", "descendants")
PROJECT_FLOW_CASE_IDS = tuple(f"project-flow-{kind}-video-only-{profile}"
    for kind in PROJECT_FLOW_KINDS for profile in ("landscape", "portrait"))


def _visible_a_reference(kind, portrait, font):
    """Independent authored completed results; the Count source has already left A."""
    from test_v2_split_list_family import literal_structured_frame

    width, height = (720, 1280) if portrait else (1280, 720)
    if kind == "descendants":
        boxes = ({"source": (160., 80., 200., 120.), "part-1": (100., 400., 200., 120.),
                  "part-2": (160., 400., 200., 120.)} if portrait else
                 {"source": (80., 100., 200., 120.), "part-1": (400., 100., 200., 120.),
                  "part-2": (460., 100., 200., 120.)})
        return literal_structured_frame(portrait, True, "write", 40, boxes, font, nonidentity=True)
    body = f'<rect width="{width}" height="{height}" fill="#FAF8F1"/>'
    if kind in {"count-group", "group-count"}:
        boxes = [(10, 10, 20, 20, "#FAF8F1", "#172033")] * 2
    else:
        boxes = ([(100, 400, 80, 120, "none", "#2457D6"), (160, 400, 80, 120, "none", "#B93838")]
                 if portrait else [(400, 100, 80, 120, "none", "#2457D6"), (460, 100, 80, 120, "none", "#B93838")])
    for x, y, w, h, fill, stroke in boxes:
        shape = (f'<polyline points="{x+w},{y} {x},{y} {x},{y+h} {x+w},{y+h}"' if kind == "geometry" else
                 f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="0"')
        body += (f'{shape} fill="{fill}" stroke="{stroke}" stroke-width="2.6667" '
                 'stroke-linecap="round" stroke-linejoin="round"/>')
    literal = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">{body}</svg>'
    return bytes(resvg_py.svg_to_bytes(svg_string=literal, skip_system_fonts=True))


def _assert_native_oracles(directory, portrait, kind, inputs, frames, start_ms):
    font, font_pin = None, None
    if kind in {"count-group", "group-count", "descendants"}:
        _, font_pin, font_bytes = next(row for row in inputs.bundle_bytes
                                      if row[0].endswith("AtkinsonHyperlegible-Regular.otf"))
        font = directory / "literal-font.otf"
        font.write_bytes(font_bytes)
        assert sha256(font.read_bytes()).hexdigest() == font_pin
    expected = _visible_a_reference(kind, portrait, font)
    reference_path = directory / "literal-visible-a.png"
    reference_path.write_bytes(expected)
    with Image.open(BytesIO(expected)) as reference:
        rgb = reference.convert("RGB")
        assert rgb.getextrema() != ((250, 250), (248, 248), (241, 241))
        for at in ("1999", "3000"):
            with Image.open(frames[at]["png_path"]) as actual:
                assert actual.convert("RGB").tobytes() == rgb.tobytes(), "Visible A differs from its literal native oracle"
                if kind == "morph":
                    assert actual.convert("RGB").getpixel((100, 450) if portrait else (400, 150)) == (36, 87, 214)
    record = {"visible_a_png_path": str(reference_path.resolve()), "visible_a_png_sha256": sha256(expected).hexdigest(),
              "font_sha256": font_pin}
    if kind in {"count-group", "group-count"}:
        width, height = (720, 1280) if portrait else (1280, 720)
        literal = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
            f'<rect width="{width}" height="{height}" fill="#FAF8F1"/>'
            '<g transform="matrix(2 0 0 3 90 30)"><text x="10" y="31.3333" fill="#172033" '
            'font-family="Atkinson Hyperlegible" font-weight="400" font-size="21.3333" '
            'xml:space="preserve"><tspan x="10" dy="0">10 widgets</tspan></text></g></svg>')
        glyph = bytes(resvg_py.svg_to_bytes(svg_string=literal, font_files=[str(font)], skip_system_fonts=True))
        glyph_path = directory / "literal-count-source.png"
        glyph_path.write_bytes(glyph)
        with Image.open(BytesIO(glyph)) as reference, Image.open(frames[str(start_ms)]["png_path"]) as actual:
            region = (100, 60, 500, 190)
            assert actual.convert("RGB").crop(region).tobytes() == reference.convert("RGB").crop(region).tobytes()
        record.update(count_glyph_png_path=str(glyph_path.resolve()), count_glyph_png_sha256=sha256(glyph).hexdigest())
    return record


def _retained_assertions(kind, layout, paired, replay):
    departed, away, returned = (replay.at(at) for at in (1999, 2500, 3000))
    assert departed.objects == away.objects == returned.objects
    assert departed.hierarchy == away.hierarchy == returned.hierarchy
    assert departed.state_versions == away.state_versions == returned.state_versions
    assert returned.object("source").state == "removed"
    assert returned.object("part-1").state == returned.object("part-2").state == "visible"
    versions = dict(returned.state_versions)
    if kind in {"count-group", "group-count"}:
        assert returned.object("source").display_text == "10 widgets"
        assert returned.object("source").count_value == (10, 1)
        assert returned.object("source").transform.position.x == 100
        assert next(node for node in returned.hierarchy.nodes if node.object_id == "source").parent_id is None
        assert next(obj for obj in layout.objects if obj.object_id == "source").text == "0 widgets"
        assert versions == {"source": 4, "shell": 2, "part-1": 3, "part-2": 3}
    elif kind == "geometry":
        assert versions == {"source": 2, "part-1": 2, "part-2": 2}
    elif kind == "morph":
        assert versions == {"origin": 2, "source": 3, "part-1": 2, "part-2": 2}
        assert returned.object("origin").state == "removed"
        assert returned.object("source").morph_geometry is None
    else:
        for obj in layout.objects:
            assert versions[obj.object_id] == (2 if obj.object_id in {"source", "part-1", "part-2"} else 1)
            if obj.object_id not in {"source", "part-1", "part-2"}:
                assert returned.object(obj.object_id).state == obj.initial_state
                assert returned.object(obj.object_id) == next(frame for frame in paired.frames if frame.object_id == obj.object_id)
    return returned


def project_flow_case(output_dir: Path, portrait: bool, kind: str, video: bytes) -> dict:
    """Consume genuine stored video authority and both service-owned artifact sets."""
    from atme.project_assets import read_verified_split_asset_bytes
    from atme.project_service import _resolved_compilation_fingerprint
    from atme.render import v2_state, v2_svg
    from atme.render.v2_hierarchy import HierarchySnapshot
    from atme.render.v2_media import inspect_media
    from atme.render.v2_split_paint import verify_split_paint_inputs
    from atme.store.contracts_v2 import ExecutableLayoutV2, ResolvedVisualTimelineV2

    if type(portrait) is not bool or kind not in PROJECT_FLOW_KINDS:
        raise ValueError("Project flows require one of the five retained histories and an authored profile")
    destination = Path(output_dir) / f"project-flow-{kind}-video-only-{'portrait' if portrait else 'landscape'}"
    destination.mkdir(parents=True, exist_ok=False)
    external = destination / "original-recording.mp4"
    external.write_bytes(video)

    def forbidden(*args, **kwargs):
        raise AssertionError("Offline project-flow proof attempted network access")

    with ExitStack() as offline:
        for key in ("socket", "create_connection", "getaddrinfo", "gethostbyname", "gethostbyname_ex",
                    "gethostbyaddr", "getnameinfo", "getfqdn"):
            offline.enter_context(patch.object(socket, key, forbidden))
        service, project, _, _, timeline = stored_split_basis(
            destination, portrait=portrait, mode="video-only", history_kind=kind, video=video)
        try:
            pid = project["project_id"]
            project = service.write(pid, "resolved_timeline", timeline, project["revision"])
            originals = artifact_rows(service, pid)
            source_rows = tuple(tuple(row) for row in service.store.conn.execute(
                "SELECT * FROM project_source_media WHERE job_id=? ORDER BY media_id,revision", (pid,)))
            authority = service.narrative_source(pid)
            cleaned = service.source_timeline.get(pid)
            media_bytes, media = service.authoritative_media(pid)
            assert media_bytes == video and media["sha256"] == sha256(video).hexdigest()
            picture_pin = inspect_media(media_bytes, 0).pin
            copy = service.duplicate(pid)
            assert copy["project_id"] != pid
            owners, expected, original_documents = {}, None, None
            for label, owner in (("original", project), ("duplicate", copy)):
                owner_id = owner["project_id"]
                plan = service.artifact(owner_id, "storyboard")["document"]
                drawing = service.artifact(owner_id, "layout")["document"]
                clock = service.artifact(owner_id, "resolved_timeline")["document"]
                source = service.narrative_source(owner_id)
                timing = service.source_timeline.get(owner_id)
                payload, metadata = service.authoritative_media(owner_id)
                assert owner["input_kind"] == "video-only" and "script" not in owner["artifacts"]
                assert not service.store.conn.execute(
                    "SELECT 1 FROM project_artifact_dependencies WHERE job_id=?", (owner_id,)).fetchall()
                assert source["mode"] == "recording_authority" and source["narrative_authority"]["type"] == "recording"
                assert source["semantic_structure"]["revision"] is None and source["script_approval_required"] is False
                assert payload == video
                assert metadata["resource_uri"] == f"atme://projects/{owner_id}/authoritative-narrative"
                assert source["timing_authority"]["media"]["resource_uri"] == metadata["resource_uri"]
                assert inspect_media(payload, 0).pin == picture_pin
                assert {k: v for k, v in metadata.items() if k != "resource_uri"} == {
                    k: v for k, v in media.items() if k != "resource_uri"}
                assert timing["document"] == cleaned["document"]
                assert timing["timeline_revision"] == cleaned["timeline_revision"]
                assert source["timing_authority"]["duration_ms"] == authority["timing_authority"]["duration_ms"]
                assert plan["narrative_authority"]["mode"] == "recording_only"
                assert plan["narrative_authority"]["authority_id"] == metadata["media_id"]
                assert plan["narrative_authority"]["timing_media_id"] == metadata["media_id"]
                assert plan["narrative_authority"]["timing_media_sha256"] == sha256(video).hexdigest()
                assert plan["narrative_authority"]["cleaned_timeline_revision"] == timing["timeline_revision"]
                assert plan["narrative_authority"]["cleaned_timeline_fingerprint"] == digest(timing["document"])
                assert clock["cleaned_timeline_fingerprint"] == digest(timing["document"])
                assert clock["plan_sha256"] == digest(plan) and clock["layout_sha256"] == digest(drawing)
                assert clock["compilation_fingerprint"] == _resolved_compilation_fingerprint(clock)
                documents = (plan, drawing, clock)
                # Only the service's project/revision/hash and recording-authority identities may rebind.
                stable = tuple({k: v for k, v in doc.items() if k not in {
                    "project_id", "project_revision", "plan_sha256", "layout_sha256", "compilation_fingerprint",
                    "narrative_authority"}} for doc in documents)
                if original_documents is None:
                    original_documents = stable
                    original_authority = plan["narrative_authority"]
                else:
                    assert stable == original_documents
                    assert {k: v for k, v in plan["narrative_authority"].items() if k not in {"authority_id", "timing_media_id"}} == {
                        k: v for k, v in original_authority.items() if k not in {"authority_id", "timing_media_id"}}
                layout = ExecutableLayoutV2.model_validate(drawing)
                resolved = ResolvedVisualTimelineV2.model_validate(clock)
                assert not resolved.resolved_assets
                carrier = read_verified_split_asset_bytes(service, layout, clock["resolved_assets"], [])
                inputs = verify_split_paint_inputs(layout, carrier)
                frozen = (layout.model_dump_json(), resolved.model_dump_json(), inputs)
                paired = v2_state._validate_pair_static(layout, resolved, clock["layout_sha256"],
                    HierarchySnapshot.from_objects({obj.object_id: obj for obj in layout.objects}), split_inputs=inputs)
                replay, cameras = v2_state._validate_consumer_history(paired, split_inputs=inputs)
                returned = _retained_assertions(kind, layout, paired, replay)
                if expected is None:
                    expected = returned
                else:
                    assert returned == expected
                split = next(row for row in resolved.actions if row.action.verb == "split")
                order = (split.end_ms, split.start_ms, (split.start_ms + split.end_ms)//2,
                         1999, 2500, 3000, 1999, split.start_ms, split.end_ms)
                frames = {}
                owner_dir = destination / label
                owner_dir.mkdir()
                for at_ms in order:
                    sample = v2_state._sample_validated_frame(layout, resolved, replay, cameras, at_ms)
                    svg = v2_svg._compose_validated_svg_frame(layout, resolved, sample, {}, split_inputs=inputs)
                    png = v2_svg._rasterize_svg_frame(layout, svg, split_inputs=inputs).png
                    observed = replay.at(at_ms)
                    state = digest(asdict(observed))
                    hashes = sha256(svg.svg.encode()).hexdigest(), sha256(png).hexdigest(), state
                    key = str(at_ms)
                    if key in frames:
                        assert hashes == tuple(frames[key][k] for k in ("svg_sha256", "png_sha256", "state_sha256"))
                        continue
                    png_path, svg_path = owner_dir / f"{at_ms}.png", owner_dir / f"{at_ms}.svg"
                    png_path.write_bytes(png)
                    svg_path.write_text(svg.svg, encoding="utf-8")
                    frames[key] = dict(zip(("svg_sha256", "png_sha256", "state_sha256"), hashes))
                    frames[key].update(png_path=str(png_path.resolve()), svg_path=str(svg_path.resolve()),
                                       state_versions=dict(observed.state_versions))
                assert frames["1999"]["png_sha256"] == frames["3000"]["png_sha256"]
                with Image.open(frames["2500"]["png_path"]) as blank:
                    assert blank.convert("RGB").getextrema() == ((250, 250), (248, 248), (241, 241))
                assert frozen == (layout.model_dump_json(), resolved.model_dump_json(), inputs)
                native_oracles = _assert_native_oracles(owner_dir, portrait, kind, inputs, frames, split.start_ms)
                sheet = Image.new("RGB", (len(frames)*240, 270), "#101722")
                labels = ImageDraw.Draw(sheet)
                for index, (at, frame) in enumerate(sorted(frames.items(), key=lambda pair: int(pair[0]))):
                    with Image.open(frame["png_path"]) as image:
                        preview = image.convert("RGB")
                    preview.thumbnail((230, 240), Image.Resampling.LANCZOS)
                    sheet.paste(preview, (index*240, 25))
                    labels.text((index*240 + 6, 6), at + " ms", fill="white")
                sheet_path = owner_dir / "contact.png"
                sheet.save(sheet_path)
                owners[label] = {"project_id": owner_id, "frames": frames, "seek_order_ms": order,
                    "authoritative_media_uri": metadata["resource_uri"], "native_oracles": native_oracles,
                    "frozen_inputs_sha256": inputs.inputs_sha256, "artifact_sha256": [digest(doc) for doc in documents],
                    "contact_sheet_path": str(sheet_path.resolve()), "contact_sheet_sha256": sha256(sheet_path.read_bytes()).hexdigest()}
            assert owners["original"]["authoritative_media_uri"] != owners["duplicate"]["authoritative_media_uri"]
            for at, frame in owners["original"]["frames"].items():
                for key in ("svg_sha256", "png_sha256", "state_sha256", "state_versions"):
                    assert owners["duplicate"]["frames"][at][key] == frame[key]
            assert artifact_rows(service, pid) == originals
            assert source_rows == tuple(tuple(row) for row in service.store.conn.execute(
                "SELECT * FROM project_source_media WHERE job_id=? ORDER BY media_id,revision", (pid,)))
            assert external.read_bytes() == video and service.authoritative_media(pid)[0] == video
        finally:
            service.store.close()
    record = {"case_id": destination.name, "family": "project-flows", "kind": kind, "mode": "video-only",
        "profile": "SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9", "owners": owners,
        "network_forbidden": True, "immutable_input_keys_unchanged": True,
        "original_media_sha256": sha256(video).hexdigest(), "original_artifacts_and_media_rows_unchanged": True,
        "media_stream_pin": picture_pin.model_dump(mode="json"),
        "scope": "private stored video-only retained-history diagnostic; not full Task10/public/installed/creative acceptance",
        "final_acceptance": False}
    (destination / "project-flow.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def project_flow_report(output_dir: Path, cases: list[dict]) -> int:
    ids = [case["case_id"] for case in cases]
    complete = sorted(ids) == sorted(PROJECT_FLOW_CASE_IDS) and all(
        case.get("final_acceptance") is False and case.get("mode") == "video-only" for case in cases)
    report = {"status": "DIAGNOSTIC ONLY" if complete else "INCOMPLETE", "final_acceptance": False,
        "required_case_ids": PROJECT_FLOW_CASE_IDS, "cases": cases}
    (Path(output_dir) / "split-project-flows-diagnostic.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if complete else 1


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", PROJECT_FLOW_KINDS)
def test_video_only_stored_history_native_duplicate(tmp_path, portrait, kind, original_video):
    record = project_flow_case(tmp_path, portrait, kind, original_video)
    assert record["case_id"] in PROJECT_FLOW_CASE_IDS and record["final_acceptance"] is False
    with pytest.raises(FileExistsError):
        project_flow_case(tmp_path, portrait, kind, original_video)


@pytest.mark.parametrize("ids", [[], PROJECT_FLOW_CASE_IDS[:-1], PROJECT_FLOW_CASE_IDS + (PROJECT_FLOW_CASE_IDS[0],)])
def test_project_flow_report_fails_closed(tmp_path, ids):
    assert project_flow_report(tmp_path, [{"case_id": key, "final_acceptance": False, "mode": "video-only"} for key in ids]) == 1


def test_project_flow_report_complete_is_diagnostic_only(tmp_path):
    cases = [{"case_id": key, "final_acceptance": False, "mode": "video-only"} for key in PROJECT_FLOW_CASE_IDS]
    assert project_flow_report(tmp_path, cases) == 0
    assert json.loads((tmp_path / "split-project-flows-diagnostic.json").read_text())["final_acceptance"] is False


def test_project_flow_rejects_unknown_history_before_output(tmp_path):
    with pytest.raises(ValueError):
        project_flow_case(tmp_path, False, "invented", b"")
    assert not list(tmp_path.iterdir())


def test_project_flow_interface_exists():
    assert callable(getattr(sys.modules[__name__], "project_flow_case", None)), "Missing stored video-only project-flow proof"
