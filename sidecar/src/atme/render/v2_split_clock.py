"""Integer-millisecond, phase-local Split timing; independent of model imports."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from atme.store.contracts_v2 import SplitPhase


def resolve_split_phase(action_start_ms: int, action_end_ms: int,
                        phase: SplitPhase) -> tuple[int, int]:
    if (type(action_start_ms) is not int or type(action_end_ms) is not int
            or action_start_ms < 0 or action_end_ms <= action_start_ms):
        raise ValueError("Split needs an increasing nonnegative integer action interval")
    duration = action_end_ms - action_start_ms
    start = action_start_ms + duration * phase.start_tick // 10000
    end = action_start_ms + duration * phase.end_tick // 10000
    if start >= end:
        raise ValueError("Split phase collapses at integer-millisecond resolution")
    return start, end


def split_phase_progress(action_start_ms: int, action_end_ms: int,
                         at_ms: int, phase: SplitPhase) -> float:
    if type(at_ms) is not int:
        raise ValueError("Split observation time must be integer milliseconds")
    start, end = resolve_split_phase(action_start_ms, action_end_ms, phase)
    p = max(0.0, min(1.0, (at_ms - start) / (end - start)))
    if phase.easing == "linear":
        return p
    if phase.easing == "ease_in":
        return p * p
    if phase.easing == "ease_out":
        return 1 - (1 - p) ** 2
    if phase.easing == "ease_in_out":
        return p * p * (3 - 2 * p)
    raise ValueError("Split requires continuous phase easing")
