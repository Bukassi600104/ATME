"""M1 offline media pipeline: script JSON -> polished audio -> cues -> rendered MP4.

Stage order follows the plan (ADR-0003): voice source -> polish/slice -> align FINAL track ->
render against layout -> mux. Every stage writes its artifact into the job dir and records
wall time; the manifest is the seed of the SQLite job store (M3).
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import time
from pathlib import Path

import numpy as np
import soundfile as sf

from atme.audio.align import align_words
from atme.audio.polish import SliceConfig, polish
from atme.audio.segments import concat_with_gaps, load_segments
from atme.render.animator import find_ffmpeg, render_video

log = logging.getLogger(__name__)

# Bump whenever rasterization/encoding semantics change. Layout and output options
# are hashed independently; older size-only checkpoints are intentionally untrusted.
RENDER_CHECKPOINT_VERSION = "4-document-paint-order"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _mux(video: Path, wav: Path, out: Path) -> None:
    ffmpeg = find_ffmpeg()
    cmd = [ffmpeg, "-y", "-hide_banner", "-v", "error",
           "-i", str(video), "-i", str(wav),
           "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
           "-shortest", "-movflags", "+faststart", str(out)]
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                          check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"mux failed: {proc.stderr[-400:]}")


def load_voice(job_dir: Path, mode: str = "segments") -> tuple[np.ndarray, int, list[int]]:
    """Load synthesized scene segments or one uploaded voiceover."""
    if mode == "upload":
        from atme.audio.voice_upload import load_uploaded_voice

        samples, sr = load_uploaded_voice(job_dir)
        return samples, sr, [0]
    if mode != "segments":
        raise ValueError(f"unknown voice mode {mode!r}")
    seg_dir = job_dir / "segments"
    paths = sorted(seg_dir.glob("scene*.wav"))
    if not paths:
        raise FileNotFoundError(f"no scene segments under {seg_dir}")
    segments = load_segments(paths)
    return concat_with_gaps(segments)


def run_pipeline(script_path: str | Path | None, job_dir: str | Path,
                 width: int = 1280, height: int = 720, fps: int = 30,
                 layout_path: str | Path | None = None,
                 slice_cfg: SliceConfig | None = None,
                 target_lufs: float = -16.0,
                 do_denoise: bool = True,
                 script_dict: dict | None = None,
                 layout_dict: dict | None = None,
                 voice_mode: str = "segments") -> dict:
    started = time.perf_counter()
    job_dir = Path(job_dir)
    script = _load_script(script_path, script_dict)
    audio_state = polish_stage(job_dir, voice_mode=voice_mode, slice_cfg=slice_cfg,
                               target_lufs=target_lufs, do_denoise=do_denoise)
    align_state = align_stage(job_dir, script, audio_state, voice_mode=voice_mode,
                              layout_path=layout_path, layout_dict=layout_dict,
                              target_lufs=target_lufs)
    render_state = render_stage(job_dir, align_state, width=width, height=height, fps=fps)
    manifest = assemble_stage(job_dir, script, audio_state, align_state, render_state)
    manifest["total_wall_s"] = round(time.perf_counter() - started, 2)
    (job_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def _load_script(script_path: str | Path | None, script_dict: dict | None) -> dict:
    if script_dict is not None:
        return script_dict
    if script_path is not None:
        return json.loads(Path(script_path).read_text(encoding="utf-8"))
    raise ValueError("provide script_path or script_dict")


def polish_stage(job_dir: Path, voice_mode: str, slice_cfg: SliceConfig | None = None,
                 target_lufs: float = -16.0, do_denoise: bool = True,
                 remove_silence: bool = True) -> dict:
    started = time.perf_counter()
    job_dir = Path(job_dir)
    (job_dir / "audio").mkdir(parents=True, exist_ok=True)
    full, sr, orig_starts = load_voice(job_dir, mode=voice_mode)
    final_samples, edl = polish(full, sr, do_denoise=do_denoise,
                                slice_cfg=slice_cfg, target_lufs=target_lufs,
                                remove_silence=remove_silence)
    final_wav = job_dir / "audio" / "final.wav"
    sf.write(str(final_wav), final_samples, sr, subtype="PCM_16")
    state = {
        "final_wav": str(final_wav), "sample_rate": sr,
        "duration_ms": int(len(final_samples) / sr * 1000),
        "scene_starts_ms": [edl.to_final_ms(s) for s in orig_starts],
        "edl": [r.model_dump() for r in edl.removals],
        "sha256": _sha256(final_wav),
        "wall_s": round(time.perf_counter() - started, 2),
    }
    (job_dir / "audio_state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state


def align_stage(job_dir: Path, script: dict, audio_state: dict, voice_mode: str,
                layout_path: str | Path | None = None, layout_dict: dict | None = None,
                target_lufs: float = -16.0,
                semantic_authority: str = "approved_external_script") -> dict:
    started = time.perf_counter()
    job_dir = Path(job_dir)
    samples, sr = sf.read(audio_state["final_wav"], dtype="float32", always_2d=False)
    words = align_words(np.asarray(samples).reshape(-1), sr,
                        scene_starts_ms=audio_state["scene_starts_ms"])
    starts = list(audio_state["scene_starts_ms"])
    voice_report = None
    if voice_mode == "upload":
        from atme.audio.voice_upload import VoiceScriptMismatch, reconcile_words

        try:
            words, starts, voice_report = reconcile_words(
                words, script["scenes"], int(audio_state["duration_ms"]),
                semantic_source=semantic_authority)
        except VoiceScriptMismatch as exc:
            (job_dir / "audio" / "voice_report.json").write_text(
                json.dumps(exc.report, indent=2), encoding="utf-8")
            raise
        (job_dir / "audio" / "voice_report.json").write_text(
            json.dumps(voice_report, indent=2), encoding="utf-8")

    # Preserve alignment evidence even if an authored visual trigger later blocks.
    # The future post-audio planner must not rely on estimated pre-voice durations.
    from atme.planning_context import build_planning_context
    planning_context_file = job_dir / "planning_context.json"
    planning_context = build_planning_context(
        script, words, int(audio_state["duration_ms"]), audio_state["sha256"],
        semantic_authority=semantic_authority)
    planning_context_file.write_text(json.dumps(planning_context, indent=2), encoding="utf-8")

    if layout_dict is not None:
        doc = json.loads(json.dumps(layout_dict))
    elif layout_path:
        doc = json.loads(Path(layout_path).read_text(encoding="utf-8"))
    elif (job_dir / "layout.json").exists():
        doc = json.loads((job_dir / "layout.json").read_text(encoding="utf-8"))
    else:
        from atme.render.autolayout import build_layout
        doc = build_layout(script["scenes"], starts, title=script.get("title"))
    from atme.visual_plan import build_visual_plan, trigger_times

    visual_plan_file = job_dir / "visual_plan.json"
    if visual_plan_file.exists():
        visual_plan = json.loads(visual_plan_file.read_text(encoding="utf-8"))
    else:
        visual_plan = build_visual_plan(script)
        visual_plan_file.write_text(json.dumps(visual_plan, indent=2), encoding="utf-8")
    from atme.narration_events import TriggerResolutionError, resolve_narration_events
    trigger_report_file = job_dir / "narration_events.json"
    try:
        doc, trigger_report = resolve_narration_events(doc, words, int(audio_state["duration_ms"]))
    except TriggerResolutionError as exc:
        trigger_report_file.write_text(json.dumps(exc.report, indent=2), encoding="utf-8")
        raise
    trigger_report_file.write_text(json.dumps(trigger_report, indent=2), encoding="utf-8")
    doc = _retime_layout(doc, script["scenes"], starts, words,
                         int(audio_state["duration_ms"]),
                         trigger_by_scene=trigger_times(visual_plan, words))
    layout_file = job_dir / "layout.json"
    layout_file.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    directives = [{"at_ms": int(el["appear_at_ms"]),
                   "scene_id": int(el["scene_id"]), "action": el.get("enter_action", "draw"),
                   "target_id": el["id"]} for el in doc["elements"]]
    cue_timeline = {
        "contract_version": "1", "duration_ms": int(audio_state["duration_ms"]),
        "audio": {"path": audio_state["final_wav"], "sha256": audio_state["sha256"],
                  "sample_rate": int(sr), "lufs": target_lufs},
        "words": words, "directives": sorted(directives, key=lambda d: d["at_ms"]),
        "edl_original_to_final_ms": audio_state["edl"],
    }
    cues_file = job_dir / "cue_timeline.json"
    cues_file.write_text(json.dumps(cue_timeline, indent=2), encoding="utf-8")
    state = {"cues_file": str(cues_file), "layout_file": str(layout_file),
             "planning_context_file": str(planning_context_file),
             "narration_events_file": str(trigger_report_file),
             "visual_plan_file": str(visual_plan_file),
             "duration_ms": int(audio_state["duration_ms"]), "words": len(words),
             "voice_similarity": voice_report.get("similarity") if voice_report else None,
             "wall_s": round(time.perf_counter() - started, 2)}
    (job_dir / "align_state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state


def render_stage(job_dir: Path, align_state: dict, width: int, height: int, fps: int,
                 segment_ms: int = 60_000, control_cb=None) -> dict:
    started = time.perf_counter()
    job_dir = Path(job_dir)
    doc = json.loads(Path(align_state["layout_file"]).read_text(encoding="utf-8"))
    out_dir = job_dir / "out"
    segments_dir = out_dir / "segments"
    segments_dir.mkdir(parents=True, exist_ok=True)
    total_ms = int(align_state["duration_ms"]) + 400
    if min(width, height, fps, segment_ms, total_ms) <= 0:
        raise ValueError("render dimensions, rate and durations must be positive")
    render_digest = hashlib.sha256(json.dumps({
        "version": RENDER_CHECKPOINT_VERSION, "layout": doc,
        "width": width, "height": height, "fps": fps,
    }, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    segments = []
    aggregate = {"frames": 0, "layer_builds": 0, "overlay_frames": 0}
    for index, start in enumerate(range(0, total_ms, segment_ms)):
        if control_cb:
            control_cb()
        duration = min(segment_ms, total_ms - start)
        path = segments_dir / f"seg_{index:04d}.mp4"
        checkpoint = path.with_suffix(".json")
        identity = {"render_digest": render_digest, "start_ms": start, "duration_ms": duration}
        saved = None
        try:
            record = json.loads(checkpoint.read_text(encoding="utf-8"))
            if (isinstance(record, dict) and record.get("identity") == identity
                    and path.stat().st_size > 1_000
                    and record.get("sha256") == _sha256(path)
                    and isinstance(record.get("stats"), dict)
                    and all(isinstance(record["stats"].get(k), int)
                            and record["stats"][k] >= 0 for k in aggregate)):
                saved = record["stats"]
        except (OSError, ValueError, TypeError):
            pass  # missing, old, interrupted or corrupt checkpoint: render afresh
        if saved is not None:
            stats = {**saved, "resumed": True, "start_ms": start, "duration_ms": duration}
        else:
            pending_video = path.with_name(path.stem + ".pending.mp4")
            stats = render_video(doc, pending_video, fps=fps, width=width, height=height,
                                 duration_ms=duration, start_ms=start)
            pending_video.replace(path)
            pending_record = checkpoint.with_suffix(".pending.json")
            pending_record.write_text(json.dumps({
                "identity": identity, "sha256": _sha256(path), "stats": stats,
            }, indent=2), encoding="utf-8")
            pending_record.replace(checkpoint)
        segments.append({"path": str(path), **stats})
        for key in aggregate:
            aggregate[key] += int(stats.get(key, 0))
        if control_cb:
            control_cb()

    concat_file = segments_dir / "concat.txt"
    concat_file.write_text("\n".join(
        f"file '{Path(item['path']).resolve().as_posix().replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'"
        for item in segments) + "\n", encoding="utf-8")
    silent_video = out_dir / "video.mp4"
    ffmpeg = find_ffmpeg()
    cmd = [ffmpeg, "-y", "-hide_banner", "-v", "error", "-f", "concat", "-safe", "0",
           "-i", str(concat_file), "-c", "copy", "-movflags", "+faststart", str(silent_video)]
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                          check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"segment assembly failed: {proc.stderr[-400:]}")
    state = {"silent_video": str(silent_video), "segments": segments,
             "render": aggregate, "wall_s": round(time.perf_counter() - started, 2)}
    (job_dir / "render_state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state


def assemble_stage(job_dir: Path, script: dict, audio_state: dict,
                   align_state: dict, render_state: dict) -> dict:
    started = time.perf_counter()
    job_dir = Path(job_dir)
    final_mp4 = job_dir / "out" / "final.mp4"
    _mux(Path(render_state["silent_video"]), Path(audio_state["final_wav"]), final_mp4)
    manifest = {
        "job": job_dir.name, "title": script.get("title", script.get("topic")),
        "duration_ms": int(audio_state["duration_ms"]),
        "timings_s": {"polish_s": audio_state.get("wall_s", 0),
                      "align_s": align_state.get("wall_s", 0),
                      "render_s": render_state.get("wall_s", 0),
                      "assemble_s": round(time.perf_counter() - started, 2)},
        "render": render_state["render"],
        "artifacts": {
            "audio": {"path": audio_state["final_wav"], "sha256": audio_state["sha256"]},
            "video": {"path": str(final_mp4), "sha256": _sha256(final_mp4),
                      "bytes": final_mp4.stat().st_size},
            "layout": {"path": align_state["layout_file"]},
            "cue_timeline": {"path": align_state["cues_file"]},
            "visual_plan": {"path": align_state["visual_plan_file"]},
            "words_aligned": align_state["words"],
            "silence_removed_spans": len(audio_state["edl"]),
            "render_segments": len(render_state["segments"]),
        },
    }
    if align_state.get("planning_context_file"):
        manifest["artifacts"]["planning_context"] = {"path": align_state["planning_context_file"]}
    if align_state.get("voice_similarity") is not None:
        manifest["artifacts"]["voice_report"] = {
            "path": str(job_dir / "audio" / "voice_report.json"),
            "similarity": align_state["voice_similarity"]}
    (job_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def _retime_layout(doc: dict, scenes: list[dict], starts: list[int],
                   words: list[dict], duration_ms: int,
                   trigger_by_scene: dict[int, int] | None = None) -> dict:
    """Preserve spatial decisions while binding visual timing to the final recording."""
    authored = ("board_timeline" in doc
                or any("narration_trigger" in e for e in doc.get("elements", []))
                or any("visibility_intervals" in e for e in doc.get("elements", []))
                or any("action" in c for c in doc.get("camera_plan", [])))
    if authored:
        from atme.render.camera import validate_camera_intent
        from atme.render.visibility import validate_visibility

        validate_visibility(doc)
        validate_camera_intent(doc.get("camera_plan", []))
        bounds = [e["appear_at_ms"] for e in doc.get("elements", [])]
        bounds += [s["end_ms"] for e in doc.get("elements", [])
                   for s in e.get("visibility_intervals", [])]
        bounds += [a["end_ms"] for a in doc.get("board_timeline", {}).get("activations", [])]
        bounds += [c["cue_ms"] + c.get("transition_ms", 0) for c in doc.get("camera_plan", [])]
        if max(bounds, default=0) > duration_ms:
            raise ValueError("authored visual timing exceeds the final narration; revise the plan")
        # Board/visibility/intent timings are authored on the FINAL audio timebase.
        # Legacy scene-fraction retiming would destroy that explicit event schedule.
        return doc
    scene_ids = [int(s["scene_id"]) for s in scenes]
    timing: dict[int, tuple[int, int]] = {}
    for index, sid in enumerate(scene_ids):
        scene_words = [w for w in words if int(w.get("scene_id", 1)) == sid]
        start = int(scene_words[0]["start_ms"]) if scene_words else int(starts[index])
        fallback_end = int(starts[index + 1]) if index + 1 < len(starts) else duration_ms
        end = int(scene_words[-1]["end_ms"]) if scene_words else fallback_end
        timing[sid] = (max(0, start), max(start + 100, end))

    for sid in scene_ids:
        group = sorted((e for e in doc.get("elements", []) if int(e["scene_id"]) == sid),
                       key=lambda e: (int(e.get("appear_at_ms", 0)), e["id"]))
        start, end = timing[sid]
        trigger = max(start, min(end, (trigger_by_scene or {}).get(sid, start)))
        span = max(100, end - start)
        for index, element in enumerate(group):
            if index == 0:
                element["appear_at_ms"] = int(trigger)
            else:
                fraction = min(0.9, (index + 0.25) / max(1, len(group)))
                element["appear_at_ms"] = int(max(trigger, start + span * fraction))

    camera = doc.get("camera_plan") or []
    for index, cue in enumerate(camera):
        cue["cue_ms"] = int(starts[min(index, len(starts) - 1)])
    camera.sort(key=lambda cue: cue["cue_ms"])
    return doc
