"""Local CPU TTS via kokoro-onnx (Kokoro-82M int8 ONNX) with a phrase cache.

Model files are fetched once into data/models/ by bench/bench_ml.py or the app's first-run
fetcher (M4). The engine instance is process-global and lazy: loading from this HDD costs
seconds, so it happens at most once per sidecar lifetime.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from pathlib import Path

import numpy as np
import soundfile as sf

log = logging.getLogger(__name__)

DEFAULT_MODELS_DIR = Path(os.environ.get("ATME_MODELS_DIR", str(Path("data") / "models")))
MODEL_FILENAME = os.environ.get("ATME_KOKORO_MODEL", "kokoro-v1.0.int8.onnx")
VOICES_FILENAME = os.environ.get("ATME_KOKORO_VOICES", "voices.bin")
SAMPLE_RATE = 24000

_engine_lock = threading.Lock()
_engine = None


def cache_path(text: str, voice: str, speed: float, lang: str, cache_dir=None):
    key = hashlib.sha256((lang + "|" + voice + "|" + str(speed) + "|" + text).encode("utf-8")).hexdigest()
    base = cache_dir or Path(os.environ.get("ATME_TTS_CACHE", str(Path("data") / "cache" / "tts")))
    return Path(base) / (key + "-" + voice + ".wav")


def get_engine(model_path=None, voices_path=None):
    """Lazy, thread-safe singleton engine."""
    global _engine
    if _engine is not None:
        return _engine
    with _engine_lock:
        if _engine is None:
            from kokoro_onnx import Kokoro  # heavy import: only when actually synthesizing

            mp = Path(model_path) if model_path else DEFAULT_MODELS_DIR / MODEL_FILENAME
            vp = Path(voices_path) if voices_path else DEFAULT_MODELS_DIR / VOICES_FILENAME
            if not mp.exists() or not vp.exists():
                raise FileNotFoundError(
                    "Kokoro model files missing: %s / %s. Run bench/bench_ml.py --download "
                    "or the first-run fetcher." % (mp, vp)
                )
            log.info("loading Kokoro engine: %s", mp.name)
            _engine = Kokoro(str(mp), str(vp))
    return _engine


def synthesize(text: str, voice: str = "af_heart", speed: float = 1.0, lang: str = "en-us",
               use_cache: bool = True, cache_dir=None):
    """Synthesize one phrase; returns (float32 mono samples, sample_rate). Cached by SHA-256."""
    wav = cache_path(text, voice, speed, lang, cache_dir)
    if use_cache and wav.exists():
        samples, sr = sf.read(str(wav), dtype="float32", always_2d=False)
        if sr == SAMPLE_RATE:
            return np.asarray(samples, dtype=np.float32), sr

    engine = get_engine()
    samples, sr = engine.create(text, voice=voice, speed=speed, lang=lang)
    samples = np.asarray(samples, dtype=np.float32).reshape(-1)
    if use_cache:
        wav.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(wav), samples, sr, subtype="PCM_16")
    return samples, int(sr)


def synthesize_many(texts, voice: str = "af_heart", speed: float = 1.0, lang: str = "en-us",
                    progress_cb=None):
    """Strictly serial synthesis queue (this CPU runs one media worker at a time)."""
    out = []
    for i, text in enumerate(texts):
        out.append(synthesize(text, voice=voice, speed=speed, lang=lang))
        if progress_cb:
            progress_cb(i + 1, len(texts))
    return out
