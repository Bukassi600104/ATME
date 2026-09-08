"""Per-scene VO segment loading + concatenation with exact scene boundaries."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

DEFAULT_GAP_MS = 350


def load_segments(paths: list[Path]) -> list[tuple[np.ndarray, int]]:
    """Load scene segment wavs as (samples, sr) pairs; rates must agree."""
    rates = {sf.info(str(p)).samplerate for p in paths}
    if len(rates) != 1:
        raise ValueError("mixed sample rates in segments: %s" % rates)
    sr = rates.pop()
    out = []
    for p in paths:
        data, s = sf.read(str(p), dtype="float32", always_2d=False)
        if s != sr:
            raise ValueError("unexpected rate %d in %s" % (s, p))
        out.append((np.asarray(data, dtype=np.float32).reshape(-1), s))
    return out


def concat_with_gaps(segments: list[tuple[np.ndarray, int]], gap_ms: int = DEFAULT_GAP_MS,
                     scene_gap_overrides: list[int] | None = None) -> tuple[np.ndarray, int, list[int]]:
    """Concatenate (samples, sr) pairs inserting silence between scenes.

    Returns (full_samples, sr, scene_starts_ms) where starts are on the ORIGINAL timeline
    (pre-polish); the caller maps them through the EDL after slicing.
    """
    if not segments:
        raise ValueError("no segments")
    sr = segments[0][0].__class__ and segments[0][1]
    gap = np.zeros(int(sr * gap_ms / 1000), dtype=np.float32)
    parts: list[np.ndarray] = []
    starts: list[int] = []
    cursor = 0
    for i, (samples, s) in enumerate(segments):
        if s != sr:
            raise ValueError("rate mismatch at segment %d" % i)
        starts.append(cursor)
        parts.append(samples.reshape(-1))
        cursor += int(len(samples) / sr * 1000)
        if i < len(segments) - 1:
            parts.append(gap)
            cursor += gap_ms
    return np.concatenate(parts), sr, starts
