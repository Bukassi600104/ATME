from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from atme.audio.voice_upload import (
    VoiceScriptMismatch,
    normalize_filename,
    prepare_voice_upload,
    reconcile_words,
)


SCENES = [
    {"scene_id": 1, "spoken_text": "Serving models creates a fight between latency and cost."},
    {"scene_id": 2, "spoken_text": "Memory movement becomes the real bottleneck."},
]


def _words(text: str) -> list[dict]:
    out = []
    for i, word in enumerate(text.split()):
        out.append({"word": word, "start_ms": i * 300, "end_ms": i * 300 + 250,
                    "scene_id": 1, "confidence": 0.95, "flagged": False})
    return out


def test_filename_is_sanitized_and_type_checked():
    assert normalize_filename(r"..\unsafe\voice.MP3") == "source.mp3"
    with pytest.raises(ValueError):
        normalize_filename("voice.exe")


def test_reconcile_assigns_words_to_scenes():
    text = " ".join(scene["spoken_text"] for scene in SCENES)
    assigned, starts, report = reconcile_words(_words(text), SCENES, 5000)
    assert report["accepted"] is True
    assert report["similarity"] == 1.0
    assert starts[0] == 0 and starts[1] > starts[0]
    assert {word["scene_id"] for word in assigned} == {1, 2}


def test_reconcile_rejects_unrelated_recording():
    with pytest.raises(VoiceScriptMismatch) as exc:
        reconcile_words(_words("completely unrelated recording about another subject"),
                        SCENES, 3000)
    assert exc.value.report["accepted"] is False


def test_prepare_voice_upload_decodes_and_reports_quality(tmp_path: Path):
    source = tmp_path / "voice.wav"
    sr = 24000
    t = np.arange(sr * 2, dtype=np.float32) / sr
    sf.write(source, 0.1 * np.sin(2 * np.pi * 220 * t), sr)
    report = prepare_voice_upload(source, tmp_path / "job")
    assert report["duration_ms"] >= 1900
    assert report["sample_rate"] == 24000
    assert (tmp_path / "job" / "audio" / "upload.wav").exists()
    saved = json.loads((tmp_path / "job" / "audio" / "upload_quality.json").read_text())
    assert saved["duration_ms"] == report["duration_ms"]
