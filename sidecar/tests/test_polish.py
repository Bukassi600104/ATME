"""Offline unit tests for the polish chain (no model downloads required)."""

from __future__ import annotations

import numpy as np

from atme.audio.edl import EditDecisionList
from atme.audio.polish import SliceConfig, slice_silences


SR = 24000


def tone(seconds: float, sr: int = SR, freq: float = 220.0, amp: float = 0.3) -> np.ndarray:
    t = np.arange(int(sr * seconds), dtype=np.float32) / sr
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_long_interior_silence_is_cut_with_edl() -> None:
    lead, gap, tail = tone(1.0), np.zeros(int(SR * 0.8), dtype=np.float32), tone(1.0)
    x = np.concatenate([lead, gap, tail])
    out, edl = slice_silences(x, SR, SliceConfig(min_silence_ms=100, keep_silence_ms=120))
    assert len(out) < len(x), "silence must shrink the track"
    assert 0 < len(out) <= len(x) - int(SR * 0.5)
    assert len(edl.removals) == 1
    r = edl.removals[0]
    assert abs(r.orig_start_ms - 1000) <= SliceConfig().frame_ms * 3
    assert r.length_ms >= 800 - 120 - SliceConfig().frame_ms * 4
    # EDL maps a tail timestamp onto the shorter final timeline
    assert edl.to_final_ms(2800) < 2800
    edl.validate_monotonic()


def test_short_pauses_are_kept() -> None:
    lead, tiny, tail = tone(0.8), np.zeros(int(SR * 0.06), dtype=np.float32), tone(0.8)
    x = np.concatenate([lead, tiny, tail])
    out, edl = slice_silences(x, SR, SliceConfig(min_silence_ms=100))
    assert len(edl.removals) == 0
    assert len(out) == len(x)


def test_all_quiet_audio_is_not_mangled_into_empty() -> None:
    x = np.zeros(SR, dtype=np.float32)
    out, _edl = slice_silences(x, SR, SliceConfig(min_silence_ms=100))
    # interior cut leaves head padding only; must never return an empty track
    assert len(out) > 0


def test_edl_mapping_piecewise() -> None:
    edl = EditDecisionList(sample_rate=SR)
    from atme.audio.edl import RemovedSpan

    edl.removals = [RemovedSpan(orig_start_ms=1000, orig_end_ms=1800, final_start_ms=1000)]
    assert edl.to_final_ms(500) == 500
    assert edl.to_final_ms(1200) == 1000          # inside removed region clamps
    assert edl.to_final_ms(2300) == 1500          # after removal shifts back by 800ms
