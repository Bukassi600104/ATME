"""Uploaded voiceover ingestion, quality checks, and script reconciliation."""

from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

from atme.render.animator import find_ffmpeg

ALLOWED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".aac", ".flac"}
MAX_UPLOAD_BYTES = 1_000_000_000
MIN_DURATION_SECONDS = 1.0
MAX_DURATION_SECONDS = 60 * 60


class VoiceUploadError(ValueError):
    pass


class VoiceScriptMismatch(RuntimeError):
    def __init__(self, report: dict):
        self.report = report
        super().__init__(
            "voiceover does not match the approved script closely enough "
            "(similarity %.0f%%); review voice_report.json and upload a corrected recording"
            % (float(report.get("similarity", 0)) * 100)
        )


def normalize_filename(name: str) -> str:
    clean = Path(name or "voice.wav").name
    ext = Path(clean).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise VoiceUploadError("voiceover must be WAV, MP3, M4A, AAC, or FLAC")
    return "source" + ext


def prepare_voice_upload(source: Path, job_dir: Path) -> dict:
    """Decode an uploaded recording to a stable mono PCM WAV and report quality."""
    source = Path(source)
    if not source.exists() or source.stat().st_size < 1024:
        raise VoiceUploadError("voiceover file is empty or too small")
    if source.stat().st_size > MAX_UPLOAD_BYTES:
        raise VoiceUploadError("voiceover exceeds the 1 GB limit")
    if source.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise VoiceUploadError("unsupported voiceover format")

    audio_dir = Path(job_dir) / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    decoded = audio_dir / "upload.wav"
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise VoiceUploadError("FFmpeg is unavailable; repair the ATME installation")
    cmd = [ffmpeg, "-y", "-hide_banner", "-v", "error", "-i", str(source),
           "-t", str(MAX_DURATION_SECONDS + 1), "-vn", "-ac", "1", "-ar", "24000",
           "-c:a", "pcm_s16le", str(decoded)]
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0 or not decoded.exists():
        raise VoiceUploadError("could not decode voiceover: %s" % proc.stderr[-300:])

    info = sf.info(str(decoded))
    sample_rate = int(info.samplerate)
    duration_s = float(info.frames) / float(sample_rate)
    if duration_s < MIN_DURATION_SECONDS:
        decoded.unlink(missing_ok=True)
        raise VoiceUploadError("voiceover must be at least one second long")
    if duration_s > MAX_DURATION_SECONDS:
        decoded.unlink(missing_ok=True)
        raise VoiceUploadError("voiceover exceeds the one-hour limit")

    peak = 0.0
    clipped = 0
    sample_count = 0
    sum_squares = 0.0
    with sf.SoundFile(str(decoded)) as handle:
        while True:
            block = handle.read(262_144, dtype="float32", always_2d=False)
            if len(block) == 0:
                break
            values = np.asarray(block, dtype=np.float32).reshape(-1)
            peak = max(peak, float(np.max(np.abs(values))))
            clipped += int(np.count_nonzero(np.abs(values) >= 0.999))
            sample_count += int(values.size)
            sum_squares += float(np.sum(values.astype(np.float64) ** 2))
    clipping_ratio = clipped / max(1, sample_count)
    rms = float(np.sqrt(sum_squares / max(1, sample_count)))
    report = {
        "source_path": str(source),
        "decoded_path": str(decoded),
        "duration_ms": int(round(duration_s * 1000)),
        "sample_rate": sample_rate,
        "peak_dbfs": round(20 * np.log10(max(peak, 1e-9)), 2),
        "rms_dbfs": round(20 * np.log10(max(rms, 1e-9)), 2),
        "clipping_ratio": round(clipping_ratio, 6),
        "warnings": [],
    }
    if report["peak_dbfs"] < -18:
        report["warnings"].append("recording level is very low")
    if clipping_ratio > 0.0005:
        report["warnings"].append("recording contains clipped samples")
    (audio_dir / "upload_quality.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")
    return report


def load_uploaded_voice(job_dir: Path) -> tuple[np.ndarray, int]:
    path = Path(job_dir) / "audio" / "upload.wav"
    if not path.exists():
        raise FileNotFoundError("uploaded voiceover is not ready")
    samples, sr = sf.read(str(path), dtype="float32", always_2d=False)
    return np.asarray(samples, dtype=np.float32).reshape(-1), int(sr)


def _token(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", text.lower())


def reconcile_words(words: list[dict], scenes: list[dict], duration_ms: int,
                    minimum_similarity: float = 0.65) -> tuple[list[dict], list[int], dict]:
    """Assign recognized words to approved scenes and produce a deviation report."""
    expected: list[str] = []
    expected_scene: list[int] = []
    for scene in scenes:
        tokens = _token(scene["spoken_text"])
        expected.extend(tokens)
        expected_scene.extend([int(scene["scene_id"])] * len(tokens))
    observed = [_token(w.get("word", ""))[0] if _token(w.get("word", "")) else ""
                for w in words]

    matcher = difflib.SequenceMatcher(a=expected, b=observed, autojunk=False)
    mapped: dict[int, int] = {}
    matched_expected: set[int] = set()
    matched_observed: set[int] = set()
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            ei, oi = block.a + offset, block.b + offset
            mapped[oi] = expected_scene[ei]
            matched_expected.add(ei)
            matched_observed.add(oi)

    first_mapped = next((mapped[i] for i in range(len(observed)) if i in mapped), 1)
    current_scene = first_mapped
    assigned: list[dict] = []
    for i, word in enumerate(words):
        if i in mapped:
            current_scene = mapped[i]
        assigned.append({**word, "scene_id": current_scene})

    scene_starts: list[int] = []
    for scene in scenes:
        sid = int(scene["scene_id"])
        first = next((w["start_ms"] for w in assigned if w["scene_id"] == sid), None)
        if first is None:
            prior_words = sum(len(_token(s["spoken_text"])) for s in scenes if s["scene_id"] < sid)
            first = int(duration_ms * prior_words / max(1, len(expected)))
        scene_starts.append(max(scene_starts[-1] if scene_starts else 0, int(first)))

    per_scene = []
    for scene in scenes:
        sid = int(scene["scene_id"])
        indexes = [i for i, value in enumerate(expected_scene) if value == sid]
        matched = sum(1 for i in indexes if i in matched_expected)
        per_scene.append({"scene_id": sid, "expected_words": len(indexes),
                          "matched_words": matched,
                          "coverage": round(matched / max(1, len(indexes)), 4)})

    similarity = matcher.ratio()
    report = {
        "contract_version": "1",
        "similarity": round(similarity, 4),
        "accepted": bool(similarity >= minimum_similarity and len(observed) >= 3),
        "minimum_similarity": minimum_similarity,
        "expected_word_count": len(expected),
        "observed_word_count": len(observed),
        "matched_word_count": len(matched_observed),
        "missing_words": [expected[i] for i in range(len(expected)) if i not in matched_expected][:100],
        "unexpected_words": [observed[i] for i in range(len(observed)) if i not in matched_observed and observed[i]][:100],
        "low_confidence_words": sum(1 for w in assigned if w.get("flagged")),
        "scenes": per_scene,
    }
    if not report["accepted"]:
        raise VoiceScriptMismatch(report)
    return assigned, scene_starts, report


def replace_uploaded_source(job_dir: Path, filename: str, body: bytes) -> tuple[Path, dict]:
    """Persist one upload under a safe name, replacing older source formats."""
    safe = normalize_filename(filename)
    audio_dir = Path(job_dir) / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    for old in audio_dir.glob("source.*"):
        if old.is_file():
            old.unlink()
    source = audio_dir / safe
    source.write_bytes(body)
    try:
        report = prepare_voice_upload(source, job_dir)
    except Exception:
        source.unlink(missing_ok=True)
        raise
    return source, report


def replace_uploaded_file(job_dir: Path, filename: str,
                          staged_file: Path) -> tuple[Path, dict]:
    """Atomically adopt a streamed upload and decode it to the canonical WAV."""
    safe = normalize_filename(filename)
    staged_file = Path(staged_file)
    if not staged_file.exists():
        raise VoiceUploadError("voiceover upload was not received")
    size = staged_file.stat().st_size
    if size < 1024:
        raise VoiceUploadError("voiceover file is empty or too small")
    if size > MAX_UPLOAD_BYTES:
        raise VoiceUploadError("voiceover exceeds the 1 GB limit")

    audio_dir = Path(job_dir) / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    source = audio_dir / safe
    for old in audio_dir.glob("source.*"):
        if old.is_file() and old != staged_file:
            old.unlink()
    os.replace(staged_file, source)
    try:
        report = prepare_voice_upload(source, job_dir)
    except Exception:
        source.unlink(missing_ok=True)
        raise
    return source, report
