"""Word alignment on the FINAL polished audio (ADR-0003).

Scene attribution: callers pass cumulative scene start offsets in final-timeline milliseconds;
every recognized word is attributed to the last scene whose offset <= word start.
"""

from __future__ import annotations

import logging
import os
import threading

import numpy as np

log = logging.getLogger(__name__)

_model_lock = threading.Lock()
_model = None

CONFIDENCE_FLAG_THRESHOLD = 0.6


def _get_model(model_size=None):
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel

            size = model_size or os.environ.get("ATME_WHISPER_MODEL", "base.en")
            threads = int(os.environ.get("ATME_WHISPER_THREADS", "4"))
            model_dir = os.environ.get("ATME_MODEL_DIR")
            log.info("loading faster-whisper %s (int8, cpu, %d threads)", size, threads)
            _model = WhisperModel(size, device="cpu", compute_type="int8", cpu_threads=threads,
                                  download_root=model_dir or None)
    return _model


def align_words(samples, sample_rate: int, scene_starts_ms, language: str = "en"):
    """Return word dicts matching cue-timeline.schema.json words[] shape."""
    model = _get_model()
    samples16 = samples if sample_rate == 16000 else _resample_to_16k(samples, sample_rate)

    segments, info = model.transcribe(
        samples16,
        language=language,
        vad_filter=True,
        word_timestamps=True,
        beam_size=1,  # greedy: alignment task, not quality task; ~2x faster on 2 cores
    )
    words = []
    for seg in segments:
        for w in getattr(seg, "words", None) or []:
            start_ms = int(round(w.start * 1000))
            end_ms = max(start_ms + 20, int(round(w.end * 1000)))
            confidence = float(w.probability) if w.probability is not None else None
            scene_id = 1
            for sid, off in enumerate(scene_starts_ms, start=1):
                if start_ms >= off:
                    scene_id = sid
            words.append({
                "word": w.word.strip(),
                "start_ms": start_ms,
                "end_ms": end_ms,
                "scene_id": scene_id,
                "confidence": confidence,
                "flagged": bool(confidence is not None and confidence < CONFIDENCE_FLAG_THRESHOLD),
            })
    log.info("align: %d words, language=%s", len(words), info.language)
    return words


def _resample_to_16k(samples, sample_rate: int):
    # deterministic linear resample; whisper is robust to minor interpolation artifacts and this
    # avoids pulling an extra resampling dependency into the critical path.
    duration = samples.shape[0] / float(sample_rate)
    target_len = int(duration * 16000)
    x_old = np.linspace(0.0, duration, num=samples.shape[0], endpoint=False)
    x_new = np.linspace(0.0, duration, num=target_len, endpoint=False)
    return np.interp(x_new, x_old, samples.astype(np.float32)).astype(np.float32)
