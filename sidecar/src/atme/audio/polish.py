"""Audio polish chain: denoise -> silence slice -> dynamics -> loudness normalize.

Slicing strategy note (ADR-0004): the deterministic energy-RMS slicer below is the DEFAULT
because tight pacing cuts must be predictable and unit-testable; a Silero-backed strategy can be
plugged behind the same interface once validated against faster-whisper's bundled VAD.
Alignment itself always runs on the FINAL track (ADR-0003).
"""

from __future__ import annotations

import dataclasses
import logging

import numpy as np

from atme.audio.edl import EditDecisionList, RemovedSpan

log = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class SliceConfig:
    threshold_dbfs: float = -30.0
    min_silence_ms: int = 100
    keep_silence_ms: int = 120      # total padding left where a longer silence was cut
    frame_ms: int = 20


def slice_silences(
    samples: np.ndarray,
    sample_rate: int,
    cfg: SliceConfig | None = None,
) -> tuple[np.ndarray, EditDecisionList]:
    """Remove interior silences longer than cfg.min_silence_ms below cfg.threshold_dbfs."""
    cfg = cfg or SliceConfig()
    x = np.asarray(samples, dtype=np.float32)
    frame = max(1, int(sample_rate * cfg.frame_ms / 1000))
    usable = (x.shape[0] // frame) * frame
    if usable == 0:
        return x.copy(), EditDecisionList(sample_rate=sample_rate)

    rms = np.sqrt(np.mean(x[:usable].reshape(-1, frame) ** 2, axis=1))
    dbfs = 20.0 * np.log10(rms + 1e-9)
    quiet = dbfs < cfg.threshold_dbfs

    nframes = quiet.shape[0]
    cut = np.zeros(nframes, dtype=bool)
    i = 0
    while i < nframes:
        if quiet[i]:
            j = i
            while j < nframes and quiet[j]:
                j += 1
            if (j - i) * cfg.frame_ms >= cfg.min_silence_ms:
                cut[i:j] = True
            i = j
        else:
            i += 1

    pad_frames = max(0, int(cfg.keep_silence_ms / 2 / cfg.frame_ms))
    for _ in range(pad_frames):  # erode each removed run by one frame per side per pass
        shrunk = cut.copy()
        shrunk[1:] &= cut[:-1]
        shrunk[:-1] &= cut[1:]
        cut = shrunk
    # edge policy: never strip leading/trailing padding entirely
    if nframes > 2 * pad_frames + 2:
        cut[:pad_frames] = False
        cut[nframes - pad_frames:] = False
    else:
        cut[:] = False

    keep_samples = np.repeat(~cut, frame)  # frame decision -> sample decision
    kept = x[:usable][keep_samples]
    tail = x[usable:]
    out = np.concatenate([kept, tail]) if tail.size else kept

    # build EDL from cut mask
    removals: list[RemovedSpan] = []
    d = np.diff(cut.astype(np.int8), prepend=np.int8(0), append=np.int8(0))
    starts = np.flatnonzero(d == 1)
    ends = np.flatnonzero(d == -1)
    final_cursor_ms = 0
    for s, e in zip(starts.tolist(), ends.tolist()):
        orig_start_ms = s * cfg.frame_ms
        orig_end_ms = e * cfg.frame_ms
        removals.append(
            RemovedSpan(
                orig_start_ms=orig_start_ms,
                orig_end_ms=orig_end_ms,
                final_start_ms=orig_start_ms - final_cursor_ms,
            )
        )
        final_cursor_ms += orig_end_ms - orig_start_ms

    edl = EditDecisionList(sample_rate=sample_rate, removals=removals)
    edl.validate_monotonic()
    log.info("slice: removed %d spans, %d ms", len(removals), sum(r.length_ms for r in removals))
    return out.astype(np.float32, copy=False), edl


def denoise(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    """Spectral-gating background-noise reduction (noisereduce). Falls back to passthrough."""
    try:
        import noisereduce as nr
    except ImportError:
        log.warning("noisereduce not installed; skipping denoise")
        return samples
    reduced = nr.reduce_noise(y=samples, sr=sample_rate, stationary=False, prop_decrease=0.85)
    return np.asarray(reduced, dtype=np.float32)


def dynamics_and_loudness(samples: np.ndarray, sample_rate: int, target_lufs: float = -16.0) -> np.ndarray:
    """Compressor -> gate -> limiter (pedalboard), then normalize to target LUFS (pyloudnorm)."""
    x = np.asarray(samples, dtype=np.float32)
    try:
        from pedalboard import Compressor, Limiter, NoiseGate, Pedalboard

        board = Pedalboard(
            [
                Compressor(threshold_db=-18.0, ratio=3.0, attack_ms=8.0, release_ms=120.0),
                NoiseGate(threshold_db=-50.0, ratio=3.0, attack_ms=5.0, release_ms=80.0),
                Limiter(threshold_db=-1.5, release_ms=120.0),
            ]
        )
        x = board(x, sample_rate)
    except ImportError:
        log.warning("pedalboard not installed; skipping dynamics")
    x = np.asarray(x, dtype=np.float32).reshape(-1)

    try:
        import pyloudnorm as pyln

        meter = pyln.Meter(sample_rate)
        loudness = float(meter.integrated_loudness(x))
        if np.isfinite(loudness):  # very short clips yield -inf; skip rather than blow up gain
            gain_db = target_lufs - loudness
            x = x * (10.0 ** (gain_db / 20.0))
    except ImportError:
        log.warning("pyloudnorm not installed; skipping loudness normalization")
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    if peak > 0.999:  # safety limiter in the numeric domain
        x = x * (0.999 / peak)
    return x.astype(np.float32, copy=False)


def polish(
    samples: np.ndarray,
    sample_rate: int,
    do_denoise: bool = True,
    slice_cfg: SliceConfig | None = None,
    target_lufs: float = -16.0,
    remove_silence: bool = True,
) -> tuple[np.ndarray, EditDecisionList]:
    """Full chain; returns final samples + the EDL bridging original->final timeline."""
    x = denoise(samples, sample_rate) if do_denoise else samples
    if remove_silence:
        x, edl = slice_silences(x, sample_rate, slice_cfg)
    else:
        # Source-cleanup decisions are already represented by the immutable
        # project timeline. Never make a second, hidden duration change here.
        edl = EditDecisionList(sample_rate=sample_rate)
    x = dynamics_and_loudness(x, sample_rate, target_lufs)
    return x, edl
