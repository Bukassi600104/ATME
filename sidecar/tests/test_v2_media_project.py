"""Real original media ownership, project authority and frozen moving pixels."""

import builtins
import hashlib
import io
import json
import os
import shutil
import socket
import subprocess
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image
from test_external_inputs import external_payload
from test_v2_media_decode import (
    encoded_vfr as encoded_vfr,  # noqa: PLC0414 -- pytest fixture re-export
)
from test_v2_media_runtime import runtime_documents
from test_v2_registry_project import history
from v2_fixtures import digest, visual_plan_v2

from atme import project_assets
from atme.project_assets import read_verified_split_asset_bytes
from atme.project_service import (
    ProjectError,
    ProjectService,
    _resolved_compilation_fingerprint,
)
from atme.render import v2_media, v2_state
from atme.render.animator import find_ffmpeg
from atme.render.style_bundle import registry_endpoint_inputs_for_objects
from atme.render.v2_split_paint import (
    _freeze_verified_split_asset,
    verify_split_paint_inputs,
)
from atme.render.v2_svg import (
    _compose_validated_svg_frame,
    _rasterize_svg_frame,
    compose_png_frame,
)
from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    ResolvedAsset,
    ResolvedVisualTimelineV2,
    SplitAssetPin,
)
from atme.store.db import JobStore


@pytest.fixture(scope="module")
def original_video(encoded_vfr, tmp_path_factory):
    """Real VFR picture with deliberately longer timing audio."""
    directory = tmp_path_factory.mktemp("source-video")
    source = directory / "picture.mp4"
    source.write_bytes(encoded_vfr)
    command = [find_ffmpeg(), "-hide_banner", "-v", "error", "-i", str(source),
               "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=24000:duration=8",
               "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
               "-movflags", "frag_keyframe+empty_moov", "-f", "mp4", "pipe:1"]
    result = subprocess.run(command, capture_output=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    return result.stdout


def owned_media(tmp_path, raw, *, kind="video", supporting=False,
                profile="LONG_FORM_16_9", input_kind="idea-first"):
    service = ProjectService(JobStore(tmp_path / "media.db"))
    project = service.create("Original source", profile, input_kind)
    external = tmp_path / "Original recording.mp4"
    external.write_bytes(raw)
    staged = tmp_path / "upload.mp4"
    shutil.copyfile(external, staged)
    if supporting:
        imported = service.attach_asset_file(project["project_id"], staged, external.name, project["revision"])
        owned = imported["asset"]
        asset_id = owned["asset_id"]
    else:
        imported = service.attach_video_file(project["project_id"], staged, external.name, project["revision"])
        owned = imported["media"]
        asset_id = owned["media_id"]
    project = imported["project"]
    layout, clock, _ = runtime_documents(raw, kind=kind, portrait=profile == "SHORT_FORM_9_16")
    obj = layout["objects"][2]
    obj["asset_id"] = asset_id
    revision = service.list_assets(project["project_id"])[0]["revision"] if supporting else (
        service.list_media(project["project_id"])[0]["revision"])
    obj["media_playback"]["placement"]["source_revision"] = revision
    asset = clock["resolved_assets"][0]
    stream = asset["media_stream"]
    # Remuxing audio changes the decoded presentation interval. Derive the
    # exact integer duration from these real PTS, never the fixture's old 6s.
    duration = ((stream["end_pts"] - stream["first_pts"]) * stream["time_base_numerator"] * 1000
                // stream["time_base_denominator"])
    asset.update(asset_id=asset_id, revision=revision,
                 duration_ms=duration,
                 managed_ref=f"atme://projects/{project['project_id']}/assets/{asset_id}")
    obj["media_playback"]["source_duration_ms"] = duration
    layout["project_id"] = project["project_id"]
    clock.update(project_id=project["project_id"], layout_sha256=digest(layout))
    return service, project, layout, clock, owned, external


@pytest.mark.parametrize("supporting", [False, True])
@pytest.mark.parametrize("kind", ["video", "presenter", "screen_recording"])
def test_actual_owned_original_resolves_without_rewriting_timing_metadata(
        tmp_path, original_video, supporting, kind):
    service, project, layout, clock, owned, external = owned_media(
        tmp_path, original_video, kind=kind, supporting=supporting)
    try:
        pid = project["project_id"]
        before = service.list_media(pid)
        asset = clock["resolved_assets"][0]
        assert 6000 <= asset["duration_ms"] < 6100
        if not supporting:
            assert owned["duration_ms"] > asset["duration_ms"]
        verified = project_assets.read_verified_media_bytes(service, pid, asset, layout=layout)
        assert verified.payload == original_video
        assert verified.asset_id == asset["asset_id"]
        assert verified.revision == asset["revision"]
        assert verified.sha256 == hashlib.sha256(original_video).hexdigest()
        assert json.loads(verified.stream_json) == asset["media_stream"]
        assert (verified.width, verified.height) == (80, 40)
        assert service.list_media(pid) == before
        assert external.read_bytes() == original_video
    finally:
        service.store.close()


def source_row(service, pid, asset_id):
    return service.store.conn.execute(
        "SELECT * FROM project_source_media WHERE job_id=? AND media_id=?", (pid, asset_id)).fetchone()


def replace_source_metadata(service, pid, asset_id, metadata):
    service.store.conn.execute(
        "UPDATE project_source_media SET metadata=? WHERE job_id=? AND media_id=?",
        (json.dumps(metadata), pid, asset_id))
    service.store.conn.commit()


def rebound(layout, asset, pid):
    layout, asset = deepcopy(layout), deepcopy(asset)
    layout["project_id"] = pid
    asset["managed_ref"] = f"atme://projects/{pid}/assets/{asset['asset_id']}"
    return layout, asset


def test_malformed_format_is_rejected_as_a_project_error(tmp_path, original_video):
    service, project, layout, clock, _, _ = owned_media(tmp_path, original_video)
    try:
        pid, asset = project["project_id"], clock["resolved_assets"][0]
        metadata = json.loads(source_row(service, pid, asset["asset_id"])["metadata"])
        metadata["format"] = []
        replace_source_metadata(service, pid, asset["asset_id"], metadata)
        with pytest.raises(ProjectError):
            project_assets.read_verified_media_bytes(service, pid, asset, layout=layout)
    finally:
        service.store.close()


def test_lineage_requires_canonical_metadata_not_python_loose_equality(tmp_path, original_video):
    service, project, layout, clock, _, _ = owned_media(tmp_path, original_video)
    try:
        pid, asset = project["project_id"], clock["resolved_assets"][0]
        duplicate = service.duplicate(pid)
        copied_layout, copied_asset = rebound(layout, asset, duplicate["project_id"])
        metadata = json.loads(source_row(service, pid, asset["asset_id"])["metadata"])
        assert metadata["timing_audio"]["channels"] == 1
        metadata["timing_audio"]["channels"] = True
        replace_source_metadata(service, pid, asset["asset_id"], metadata)
        with pytest.raises(ProjectError, match="lineage"):
            project_assets.read_verified_media_bytes(
                service, duplicate["project_id"], copied_asset, layout=copied_layout)
    finally:
        service.store.close()


@pytest.mark.parametrize("depth", [1, 2])
@pytest.mark.parametrize("origin_removed", [False, True])
def test_source_only_duplicates_survive_origin_removal_but_not_current_removal(
        tmp_path, original_video, depth, origin_removed):
    service, project, layout, clock, _, external = owned_media(tmp_path, original_video)
    try:
        pid, asset = project["project_id"], clock["resolved_assets"][0]
        duplicate = project
        for _ in range(depth):
            duplicate = service.duplicate(duplicate["project_id"])
        copied_layout, copied_asset = rebound(layout, asset, duplicate["project_id"])
        if origin_removed:
            service.remove_source(pid, asset["asset_id"], service.open(pid)["revision"], True)
            assert service.list_media(pid) == []
        verified = project_assets.read_verified_media_bytes(
            service, duplicate["project_id"], copied_asset, layout=copied_layout)
        assert verified.payload == original_video == external.read_bytes()
        service.remove_source(duplicate["project_id"], asset["asset_id"],
                              service.open(duplicate["project_id"])["revision"], True)
        with pytest.raises(ProjectError, match="removed"):
            project_assets.read_verified_media_bytes(
                service, duplicate["project_id"], copied_asset, layout=copied_layout)
    finally:
        service.store.close()


@pytest.mark.parametrize("fault", ["stream", "timestamp_digest", "frame_count", "dimensions", "duration", "missing_pin",
                                  "mime", "uri", "revision", "size", "provenance"])
def test_media_resolver_rejects_false_or_absent_declaration(tmp_path, original_video, fault):
    service, project, layout, clock, _, _ = owned_media(tmp_path, original_video)
    try:
        pid, asset = project["project_id"], deepcopy(clock["resolved_assets"][0])
        playback = layout["objects"][2]["media_playback"]
        if fault in {"stream", "timestamp_digest", "frame_count"}:
            field = {"stream": "stream_index", "timestamp_digest": "timestamps_sha256",
                     "frame_count": "frame_count"}[fault]
            value = "0" * 64 if fault == "timestamp_digest" else asset["media_stream"][field] + 1
            asset["media_stream"][field] = value
            playback["source_stream"] = deepcopy(asset["media_stream"])
        elif fault == "dimensions":
            asset["width"] += 1
            asset["media_stream"]["width"] += 1
            playback["placement"]["source_width"] += 1
            playback["source_stream"] = deepcopy(asset["media_stream"])
        elif fault == "duration":
            stream = asset["media_stream"]
            stream["end_pts"] += stream["time_base_denominator"]
            duration = ((stream["end_pts"] - stream["first_pts"]) * stream["time_base_numerator"] * 1000
                        // stream["time_base_denominator"])
            asset["duration_ms"] = playback["source_duration_ms"] = duration
            playback["source_stream"] = deepcopy(stream)
        elif fault == "missing_pin":
            asset.pop("media_stream")
        elif fault == "mime":
            asset["media_type"] = "image/png"
        elif fault == "uri":
            asset["managed_ref"] = "atme://projects/999/assets/" + asset["asset_id"]
        elif fault == "revision":
            asset["revision"] += 1
            playback["placement"]["source_revision"] = asset["revision"]
        elif fault == "size":
            asset["byte_length"] += 1
        else:
            asset["provenance_verified"] = True
        with pytest.raises(ProjectError):
            project_assets.read_verified_media_bytes(service, pid, asset, layout=layout)
    finally:
        service.store.close()


@pytest.mark.parametrize("fault", ["both_stores", "forged_origin", "wrong_filename", "metadata_sha",
                                  "bytes", "sha_bytes", "missing_file", "reported_redirect"])
def test_media_resolver_rejects_store_path_and_byte_changes(tmp_path, original_video, fault, monkeypatch):
    service, project, layout, clock, _, external = owned_media(tmp_path, original_video)
    try:
        pid, asset = project["project_id"], clock["resolved_assets"][0]
        row = source_row(service, pid, asset["asset_id"])
        metadata = json.loads(row["metadata"])
        managed = service.store.db_path.resolve().parent / row["relative_path"]
        if fault == "both_stores":
            service.store.conn.execute("INSERT INTO project_assets VALUES(?,?,?,?,?)",
                (pid, asset["asset_id"], row["revision"], row["relative_path"], row["metadata"]))
        elif fault in {"forged_origin", "wrong_filename"}:
            relative = (f"project-media/999/{asset['asset_id']}.mp4" if fault == "forged_origin"
                        else f"project-media/{pid}/{'b' * 32}.mp4")
            service.store.conn.execute(
                "UPDATE project_source_media SET relative_path=? WHERE job_id=? AND media_id=?",
                (relative, pid, asset["asset_id"]))
        elif fault == "metadata_sha":
            metadata["sha256"] = "0" * 64
            replace_source_metadata(service, pid, asset["asset_id"], metadata)
        elif fault == "bytes":
            managed.write_bytes(original_video[:-1])
        elif fault == "sha_bytes":
            managed.write_bytes(original_video[:-1] + bytes([original_video[-1] ^ 1]))
        elif fault == "missing_file":
            managed.unlink()
        else:
            # Guard-logic evidence only, not a claim that the host symlink
            # privilege limitation or P3-46 has been resolved.
            monkeypatch.setattr(project_assets, "_is_redirect", lambda path: path == managed.parent)
        service.store.conn.commit()
        with pytest.raises(ProjectError):
            project_assets.read_verified_media_bytes(service, pid, asset, layout=layout)
        assert external.read_bytes() == original_video
    finally:
        service.store.close()


@pytest.mark.parametrize("depth", [1, 2])
def test_supporting_original_video_duplicates_share_verified_origin(tmp_path, original_video, depth):
    service, project, layout, clock, _, external = owned_media(tmp_path, original_video, supporting=True)
    try:
        duplicate = project
        for _ in range(depth):
            duplicate = service.duplicate(duplicate["project_id"])
        copied_layout, copied_asset = rebound(layout, clock["resolved_assets"][0], duplicate["project_id"])
        verified = project_assets.read_verified_media_bytes(
            service, duplicate["project_id"], copied_asset, layout=copied_layout)
        assert verified.payload == original_video == external.read_bytes()
    finally:
        service.store.close()


@pytest.mark.parametrize("fault", ["revision", "missing_row"])
def test_duplicate_cannot_forge_immutable_origin_row(tmp_path, original_video, fault):
    service, project, layout, clock, _, _ = owned_media(tmp_path, original_video)
    try:
        pid, asset = project["project_id"], clock["resolved_assets"][0]
        duplicate = service.duplicate(pid)
        copied_layout, copied_asset = rebound(layout, asset, duplicate["project_id"])
        if fault == "revision":
            service.store.conn.execute(
                "UPDATE project_source_media SET revision=revision+1 WHERE job_id=? AND media_id=?",
                (pid, asset["asset_id"]))
        else:
            service.store.conn.execute("DELETE FROM project_source_media WHERE job_id=? AND media_id=?",
                                       (pid, asset["asset_id"]))
        service.store.conn.commit()
        with pytest.raises(ProjectError, match="lineage"):
            project_assets.read_verified_media_bytes(
                service, duplicate["project_id"], copied_asset, layout=copied_layout)
    finally:
        service.store.close()


@pytest.mark.parametrize("supporting", [False, True])
def test_resolver_preserves_distinct_existing_ingress_ceilings(tmp_path, original_video, supporting, monkeypatch):
    from atme import project_media

    service, project, layout, clock, _, _ = owned_media(tmp_path, original_video, supporting=supporting)
    try:
        assert project_media.MAX_VIDEO_BYTES == 1024 * 1024 * 1024
        assert project_assets.MAX_ASSET_BYTES == 256 * 1024 * 1024
        pid, asset = project["project_id"], clock["resolved_assets"][0]
        # Exercise each existing branch with small actual files; not a claim
        # of 1GiB throughput, long-project memory or host acceptance.
        monkeypatch.setattr(project_assets, "MAX_ASSET_BYTES", len(original_video) - 1)
        if supporting:
            with pytest.raises(ProjectError):
                project_assets.read_verified_media_bytes(service, pid, asset, layout=layout)
        else:
            assert project_assets.read_verified_media_bytes(service, pid, asset, layout=layout).payload == original_video
            monkeypatch.setattr(project_media, "MAX_VIDEO_BYTES", len(original_video) - 1)
            with pytest.raises(ProjectError):
                project_assets.read_verified_media_bytes(service, pid, asset, layout=layout)
    finally:
        service.store.close()


def stored_media(tmp_path, raw, *, portrait=False, kind="video", persist=True, false_inventory=False):
    """Connected-AI-authored artifacts bind only after real source cleanup."""
    profile = "SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9"
    service, project, layout, clock, owned, _ = owned_media(
        tmp_path, raw, kind=kind, profile=profile, input_kind="video-only")
    pid, asset = project["project_id"], clock["resolved_assets"][0]
    placed = service.edit_source_timeline(pid, "insert", {"media_id": asset["asset_id"], "at_ms": 0},
                                          project["revision"], 0)
    cleaned = service.edit_source_timeline(pid, "ripple_delete", {"start_ms": 0, "end_ms": 1000},
        placed["project"]["revision"], placed["timeline"]["timeline_revision"])
    project, timing = cleaned["project"], cleaned["timeline"]
    assert timing["document"]["clips"][0]["source_start_ms"] == 1000
    assert timing["document"]["duration_ms"] == owned["duration_ms"] - 1000
    # An external semantic index is a derivative, never an approved narrative
    # authority or locally generated transcription. Recording remains authority.
    project = service.write(pid, "script", external_payload()["script"], project["revision"])
    assert project["approved_script_revision"] is None
    playback = layout["objects"][2]["media_playback"]
    playback.update(source_in_ms=1000, source_out_ms=6000, timeline_start_ms=0)
    if false_inventory:
        asset["media_stream"]["frame_count"] += 1
        playback["source_stream"] = deepcopy(asset["media_stream"])
    duration = timing["document"]["duration_ms"]
    layout["activations"][0]["end_ms"] = duration
    clock["duration_ms"] = duration
    plan = visual_plan_v2(project["revision"])
    keys = set(plan["objects"][0]) | {"media_playback"}
    plan["objects"] = [{key: deepcopy(value) for key, value in obj.items() if key in keys}
                       for obj in layout["objects"]]
    declared = deepcopy(plan["assets"][0])
    declared.update(asset_id=asset["asset_id"], revision=asset["revision"], kind=kind,
        managed_ref=asset["managed_ref"], checksum_sha256=asset["checksum_sha256"],
        width=asset["width"], height=asset["height"], duration_ms=asset["duration_ms"],
        media_stream=deepcopy(asset["media_stream"]), allowed_transformations=asset["allowed_transformations"],
        provenance={"category": "user_owned", "source_uri": None,
                    "checksum_sha256": asset["checksum_sha256"], "license_status": "owned",
                    "fabrication_prohibited": False, "originality_status": "original"})
    plan["assets"] = [declared]
    plan["actions"] = [deepcopy(row["action"]) for row in clock["actions"]]
    plan["coverage"], plan["fallbacks"] = deepcopy(clock["coverage"]), deepcopy(clock["fallbacks"])
    for beat in plan["beats"]:
        beat["evidence"] = None
    plan.update(project_id=pid, project_revision=project["revision"],
                output_profile=deepcopy(layout["output_profile"]))
    plan["narrative_authority"].update(mode="recording_only", authority_id=asset["asset_id"],
        timing_media_id=asset["asset_id"], timing_media_sha256=asset["checksum_sha256"],
        cleaned_timeline_revision=timing["timeline_revision"],
        cleaned_timeline_fingerprint=digest(timing["document"]))
    project = service.write(pid, "storyboard", plan, project["revision"])
    layout.update(project_revision=project["revision"], plan_revision=project["artifacts"]["storyboard"],
                  plan_sha256=digest(plan))
    project = service.write(pid, "layout", layout, project["revision"])
    clock.update(project_revision=project["revision"], plan_revision=project["artifacts"]["storyboard"],
        plan_sha256=digest(plan), layout_revision=project["artifacts"]["layout"], layout_sha256=digest(layout),
        cleaned_timeline_revision=timing["timeline_revision"],
        cleaned_timeline_fingerprint=digest(timing["document"]))
    clock["compilation_fingerprint"] = _resolved_compilation_fingerprint(clock)
    if persist:
        project = service.write(pid, "resolved_timeline", clock, project["revision"])
    return service, project, plan, layout, clock


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["video", "presenter", "screen_recording"])
def test_stored_original_media_project_duplicate_and_offline_moving_pixels(
        tmp_path, original_video, portrait, kind, monkeypatch):
    service, project, plan, layout, clock = stored_media(tmp_path, original_video, portrait=portrait, kind=kind)
    try:
        pid, asset = project["project_id"], clock["resolved_assets"][0]
        original_history = history(service, pid)
        recordings = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in tmp_path.rglob("*") if path.suffix in {".mp4", ".wav"}}
        media_rows = service.list_media(pid)
        expected = {at: compose_png_frame(layout, clock, at, {asset["asset_id"]: original_video}).png
                    for at in (500, 2500, 4500)}
        for at, color in ((500, (255, 0, 0)), (2500, (0, 255, 0)), (4500, (0, 0, 255))):
            assert Image.open(io.BytesIO(expected[at])).convert("RGB").getpixel((300, 300)) == color
        assert service.runner.preview_v2_source(pid, project["revision"], 4500)["png"] == expected[4500]
        duplicate = service.duplicate(pid)
        copy_id = duplicate["project_id"]
        copied_plan = service.artifact(copy_id, "storyboard")["document"]
        copied_layout = service.artifact(copy_id, "layout")["document"]
        copied_clock = service.artifact(copy_id, "resolved_timeline")["document"]
        assert copied_plan["narrative_authority"] == plan["narrative_authority"]
        assert copied_layout["objects"] == layout["objects"]
        assert copied_clock["cleaned_timeline_fingerprint"] == clock["cleaned_timeline_fingerprint"]
        assert copied_clock["layout_sha256"] == digest(copied_layout)
        assert copied_clock["plan_sha256"] == digest(copied_plan)
        assert copied_clock["compilation_fingerprint"] == _resolved_compilation_fingerprint(copied_clock)
        assert duplicate["approved_script_revision"] is None
        assert service.runner.preview_v2_source(copy_id, duplicate["revision"], 500)["png"] == expected[500]
        typed, resolved = (ExecutableLayoutV2.model_validate(copied_layout),
                           ResolvedVisualTimelineV2.model_validate(copied_clock))
        copied_asset = copied_clock["resolved_assets"][0]
        pins = [{"asset_id": copied_asset["asset_id"], "revision": copied_asset["revision"],
                 "resource_uri": copied_asset["managed_ref"], "checksum_sha256": copied_asset["checksum_sha256"]}]
        frozen_assets = read_verified_split_asset_bytes(service, typed, resolved.resolved_assets, pins)
        inputs = verify_split_paint_inputs(typed, frozen_assets)
        registry = registry_endpoint_inputs_for_objects({obj.object_id: obj for obj in typed.objects},
            frozen_files={name: raw for name, _, raw in inputs.bundle_bytes})
        assert history(service, pid) == original_history
        assert service.list_media(pid) == media_rows
        assert recordings == {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in tmp_path.rglob("*") if path.suffix in {".mp4", ".wav"}}
        protected = {Path(path).resolve() for path in recordings}
        real_open = Path.open
        real_builtin_open = builtins.open

        def deny_originals(path, *args, **kwargs):
            assert path.resolve() not in protected, "frozen media reopened an original source"
            return real_open(path, *args, **kwargs)

        def deny_builtin_originals(file, *args, **kwargs):
            if isinstance(file, (str, bytes, os.PathLike)):
                assert Path(os.fsdecode(file)).resolve() not in protected, "frozen media reopened an original source"
            return real_builtin_open(file, *args, **kwargs)

        monkeypatch.setattr(Path, "open", deny_originals)
        monkeypatch.setattr(builtins, "open", deny_builtin_originals)
        monkeypatch.setattr(Path, "read_bytes", lambda *_: pytest.fail("frozen media reopened a resource"))
        monkeypatch.setattr(socket, "create_connection", lambda *_a, **_k: pytest.fail("media used network"))
        monkeypatch.setattr(socket.socket, "connect", lambda *_a, **_k: pytest.fail("media used network"))
        # Force real decoder work from frozen bytes, not an earlier frame cache.
        with v2_media._CACHE_LOCK:
            v2_media._INVENTORY_CACHE.clear()
            v2_media._FRAME_CACHE.clear()
        for at in (4500, 500, 2500, 500):
            snapshot = v2_state._evaluate_frame_with_registry_inputs(copied_layout, copied_clock, at, registry)
            frame = _compose_validated_svg_frame(typed, resolved, snapshot, {}, frozen_assets, split_inputs=inputs)
            png = _rasterize_svg_frame(typed, frame, split_inputs=inputs).png
            assert png == expected[at]
            (tmp_path / f"frozen-media-{kind}-{portrait}-{at}.png").write_bytes(png)
        assert service.capabilities()["visual_contracts"]["renderer_versions"] == ["1"]
    finally:
        service.store.close()


def test_later_source_cleanup_invalidates_stored_media_without_rewriting_history_or_sources(tmp_path, original_video):
    service, project, _, _, clock = stored_media(tmp_path, original_video)
    try:
        pid = project["project_id"]
        original_history = history(service, pid)
        recordings = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in tmp_path.rglob("*") if path.suffix in {".mp4", ".wav"}}
        timing = service.source_timeline.get(pid)
        changed = service.edit_source_timeline(pid, "ripple_delete", {"start_ms": 1000, "end_ms": 1100},
            project["revision"], timing["timeline_revision"])
        assert changed["timeline"]["document"]["duration_ms"] == timing["document"]["duration_ms"] - 100
        with pytest.raises(ProjectError) as failure:
            service.runner.preview_v2_source(pid, changed["project"]["revision"], 500)
        assert failure.value.code == "invalid_artifact"
        assert str(failure.value) == "resolved duration must match the cleaned source timeline"
        # Updating outer timing/revision hashes cannot launder the old authored
        # narrative/layout timing into a new cleaned recording basis.
        clock.update(project_revision=changed["project"]["revision"], duration_ms=changed["timeline"]["document"]["duration_ms"],
            cleaned_timeline_revision=changed["timeline"]["timeline_revision"],
            cleaned_timeline_fingerprint=digest(changed["timeline"]["document"]))
        clock["compilation_fingerprint"] = _resolved_compilation_fingerprint(clock)
        with pytest.raises(ProjectError) as failure:
            service.write(pid, "resolved_timeline", clock, changed["project"]["revision"])
        assert failure.value.code == "stale_contract_basis"
        assert service.open(pid)["revision"] == changed["project"]["revision"]
        assert history(service, pid) == original_history
        assert recordings == {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in tmp_path.rglob("*") if path.suffix in {".mp4", ".wav"}}
    finally:
        service.store.close()


def test_resolved_media_write_rejects_coherent_false_source_inventory_atomically(tmp_path, original_video):
    service, project, _, _, clock = stored_media(tmp_path, original_video, persist=False, false_inventory=True)
    try:
        pid = project["project_id"]
        before, revision = history(service, pid), service.open(pid)["revision"]
        with pytest.raises(ProjectError):
            service.write(pid, "resolved_timeline", clock, project["revision"])
        assert history(service, pid) == before
        assert service.open(pid)["revision"] == revision
    finally:
        service.store.close()


def test_media_read_error_is_a_project_error(tmp_path, original_video, monkeypatch):
    service, project, layout, clock, _, _ = owned_media(tmp_path, original_video)
    try:
        pid, asset = project["project_id"], clock["resolved_assets"][0]
        managed = service.store.db_path.resolve().parent / source_row(service, pid, asset["asset_id"])["relative_path"]
        real_open = Path.open

        def denied(path, *args, **kwargs):
            if path == managed:
                raise PermissionError("fixture read denied")
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", denied)
        with pytest.raises(ProjectError):
            project_assets.read_verified_media_bytes(service, pid, asset, layout=layout)
    finally:
        service.store.close()


@pytest.mark.parametrize("fault", ["id", "revision", "boolean_revision", "sha", "payload", "dimensions",
                                  "stream", "inventory", "pin_uri", "owner_project", "subclass"])
def test_frozen_media_carrier_revalidates_exact_pins_and_private_identity(tmp_path, original_video, fault):
    service, project, layout, clock, _, _ = owned_media(tmp_path, original_video)
    try:
        pid = project["project_id"]
        asset = ResolvedAsset.model_validate(clock["resolved_assets"][0])
        typed = ExecutableLayoutV2.model_validate(layout)
        pin = SplitAssetPin(asset_id=asset.asset_id, revision=asset.revision,
                            resource_uri=asset.managed_ref, checksum_sha256=asset.checksum_sha256)
        verified = project_assets.read_verified_media_bytes(service, pid, asset, layout=typed)
        baseline = _freeze_verified_split_asset(asset, pin, verified, layout=typed)
        assert baseline.payload == original_video
        if fault == "id":
            verified = replace(verified, asset_id="b" * 32)
        elif fault == "revision":
            verified = replace(verified, revision=verified.revision + 1)
        elif fault == "boolean_revision":
            assert verified.revision == 1
            verified = replace(verified, revision=True)
        elif fault == "sha":
            verified = replace(verified, sha256="0" * 64)
        elif fault == "payload":
            verified = replace(verified, payload=original_video[:-1])
        elif fault == "dimensions":
            verified = replace(verified, width=verified.width + 1)
        elif fault in {"stream", "inventory"}:
            changed = json.loads(verified.stream_json)
            changed["frame_count"] += 1
            verified = replace(verified, stream_json=json.dumps(changed, separators=(",", ":")))
            if fault == "inventory":
                asset.media_stream.frame_count += 1
                typed.objects[2].media_playback.source_stream.frame_count += 1
                assert asset.media_stream == typed.objects[2].media_playback.source_stream
                assert verified.stream_json == asset.media_stream.model_dump_json()
        elif fault == "pin_uri":
            pin.resource_uri = "atme://projects/999/assets/" + asset.asset_id
        elif fault == "owner_project":
            typed.project_id += 1
        else:
            class UnknownMediaBytes(project_assets.VerifiedMediaBytes):
                pass

            verified = UnknownMediaBytes(**vars(verified))
        with pytest.raises(ValueError):
            _freeze_verified_split_asset(asset, pin, verified, layout=typed)
    finally:
        service.store.close()
