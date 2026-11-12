"""Render a stored v2 timeline using the same offline compositor as Studio."""
from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import time

from atme.project_service import ProjectError, _resolved_compilation_fingerprint, _visual_digest


def resolved_record(service, row, layout, storyboard, timing):
    try:
        record = service.artifact(row["job_id"], "resolved_timeline")
    except ProjectError as exc:
        raise ProjectError("resolved_timeline_missing", "Compile and store the v2 resolved timeline first") from exc
    doc = record["document"]
    if (record.get("stale") or layout.get("stale") or storyboard is None or storyboard.get("stale")
            or doc["layout_revision"] != layout["revision"] or doc["plan_revision"] != storyboard["revision"]
            or doc["cleaned_timeline_revision"] != timing["timeline_revision"]
            or doc["output_profile"]["profile_id"] != row["profile"]):
        raise ProjectError("stale_contract_basis", "Recompile the timeline against the current script, layout and sources")
    if doc["output_profile"]["fps"] != 30:
        raise ProjectError("renderer_contract_unsupported", "The project output profiles support 30 fps")
    return record


def check_export_inputs(storyboard, resolved):
    from atme.render.v2_sound_mix import validate_plan

    if not resolved["document"]["validation"]["production_ready"]:
        raise ProjectError("visual_validation_failed", "The resolved timeline contains unresolved production issues",
                           resolved["document"]["validation"]["issues"])
    try:
        validate_plan(storyboard["document"])
    except ValueError as exc:
        raise ProjectError("sound_mix_unsupported", str(exc)) from exc


def verified_assets(service, row, record, layout_document):
    from atme.project_assets import read_verified_split_asset_bytes
    from atme.store.contracts_v2 import MEDIA_OBJECT_TYPES, ExecutableLayoutV2

    doc = record["document"]
    try:
        service._validate_resolved_timeline(row["job_id"], doc, row, basis_revision=record["revision"] - 1,
                                            require_return_receipts=False)
        layout = ExecutableLayoutV2.model_validate(layout_document)
        required = {obj.asset_id for obj in layout.objects if obj.asset_id is not None}
        assets = [asset for asset in doc["resolved_assets"] if asset["asset_id"] in required]
        owned = {asset["asset_id"]: asset for asset in service.list_assets(row["job_id"])}
        pins = [{"asset_id": asset["asset_id"], "revision": asset["revision"],
                 "resource_uri": (asset["managed_ref"] if asset["kind"] in MEDIA_OBJECT_TYPES else
                                  owned.get(asset["asset_id"], {}).get("resource_uri", "")),
                 "checksum_sha256": asset["checksum_sha256"]} for asset in assets]
        return read_verified_split_asset_bytes(service, layout, assets, pins)
    except ProjectError:
        raise
    except ValueError as exc:
        raise ProjectError("invalid_artifact", str(exc)) from exc


def asset_index(carrier):
    return [{"asset_id": row.asset_id, "resolved_json": row.resolved_json, "pin_json": row.pin_json,
             "treatment_json": row.treatment_json, "treatments_json": list(row.treatments_json)}
            for row in carrier.rows]


def save_inputs(inputs, record, carrier, index):
    (inputs / "resolved_timeline.json").write_text(json.dumps(record["document"]), encoding="utf-8")
    (inputs / "visual_assets.json").write_text(json.dumps(index), encoding="utf-8")
    for i, row in enumerate(carrier.rows):
        (inputs / f"visual-{i}.bin").write_bytes(row.payload)


def _video_inputs(fps, camera, frame_number=0):
    args = ["-f", "image2pipe", "-framerate", str(fps), "-vcodec", "png", "-i", "pipe:0"]
    if camera is None:
        return args
    # Camera is already trimmed, letterboxed and converted to the project frame rate.
    return [*args, "-ss", f"{frame_number / fps:.9f}", "-i", str(camera),
            "-filter_complex", "[1:v:0][0:v:0]overlay=shortest=1:format=yuv420[v]", "-map", "[v]"]


def camera_preview(camera, overlay, at_ms, fps):
    from atme.render.animator import find_ffmpeg

    command = [find_ffmpeg(), "-v", "error", *_video_inputs(fps, camera, at_ms * fps // 1000),
               "-frames:v", "1", "-an", "-f", "image2pipe", "-c:v", "png", "pipe:1"]
    run = subprocess.run(command, input=overlay, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if run.returncode or not run.stdout:
        raise ProjectError("preview_unavailable", "Could not compose the cleaned camera frame",
                           [{"message": run.stderr[-500:].decode(errors="replace")}])
    return run.stdout


def render(work, inputs, compiled, layout, audio):
    from atme.render.animator import find_ffmpeg
    from atme.render.v2_split_paint import _SplitAssetBytes, _VerifiedSplitAssetBytes
    from atme.render.v2_sound_mix import mix_master
    from atme.render.v2_svg import compose_png_frame

    started = time.monotonic()
    timeline_file = inputs / "resolved_timeline.json"
    timeline = json.loads(timeline_file.read_text(encoding="utf-8"))
    index = json.loads((inputs / "visual_assets.json").read_text(encoding="utf-8"))
    if (_resolved_compilation_fingerprint(timeline) != compiled["resolved_timeline_sha256"]
            or _visual_digest(layout) != timeline["layout_sha256"]
            or _visual_digest(index) != compiled["visual_assets_sha256"]):
        raise ValueError("The compiled visual snapshot failed its integrity check")
    plan = json.loads((inputs / "visual_plan.json").read_text(encoding="utf-8"))
    if _visual_digest(plan) != timeline["plan_sha256"]:
        raise ValueError("The compiled visual plan failed its integrity check")
    audio = mix_master(inputs, work, plan, timeline, audio)
    rows = []
    for i, entry in enumerate(index):
        payload = (inputs / f"visual-{i}.bin").read_bytes()
        expected = json.loads(entry["resolved_json"])
        if len(payload) != expected["byte_length"] or hashlib.sha256(payload).hexdigest() != expected["checksum_sha256"]:
            raise ValueError("A frozen project visual failed its integrity check")
        rows.append(_SplitAssetBytes(**{**entry, "treatments_json": tuple(entry["treatments_json"])}, payload=payload))
    assets = _VerifiedSplitAssetBytes(tuple(rows))
    fps = int(timeline["output_profile"]["fps"])
    duration_ms = timeline["duration_ms"]
    if abs(audio["duration_ms"] - duration_ms) > 1:
        raise ValueError("Mastered narration duration differs from the resolved visual timeline")
    frames = (duration_ms * fps + 999) // 1000
    out = work / "out"
    out.mkdir(exist_ok=True)
    target = out / "video.mp4"
    pending = out / "video.pending.mp4"
    camera = inputs / "source-video.mp4" if "source_video_sha256" in compiled else None
    if camera is not None:
        from atme.project_assets import _sha256
        if _sha256(camera) != compiled["source_video_sha256"]:
            raise ValueError("The frozen camera video failed its integrity check")
    command = [find_ffmpeg(), "-y", "-v", "error", *_video_inputs(fps, camera), "-an", "-c:v", "libx264", "-preset", "veryfast",
               "-pix_fmt", "yuv420p", "-crf", "18", str(pending)]
    try:
        with tempfile.TemporaryFile() as errors, subprocess.Popen(command, stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL, stderr=errors) as proc:
            try:
                for n in range(frames):
                    frame = compose_png_frame(layout, timeline, n * 1000 // fps, assets, paper_background=camera is None)
                    proc.stdin.write(frame.png)
                proc.stdin.close()
                if proc.wait() != 0:
                    raise BrokenPipeError
            except BrokenPipeError as exc:
                proc.wait()
                errors.seek(0)
                raise RuntimeError("V2 video encoding failed: " + errors.read()[-500:].decode(errors="replace")) from exc
            except BaseException:
                proc.kill()
                raise
        pending.replace(target)
    finally:
        pending.unlink(missing_ok=True)
    return ({"layout_file": str(work / "layout.json"), "cues_file": str(timeline_file),
             "visual_plan_file": str(work / "visual_plan.json")},
            {"render": {"frames": frames, "contract_version": "2.0.0"}, "segments": [{"path": str(target)}],
             "composition_mode": "camera_with_v2_overlays" if camera else "v2_board",
             "wall_s": round(time.monotonic() - started, 2), "silent_video": str(target)}, audio)
