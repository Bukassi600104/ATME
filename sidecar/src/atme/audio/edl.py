"""Edit-decision list for silence removal (ADR-0003 companion).

The slicer removes time from the ORIGINAL recording; every downstream timestamp lives on the
FINAL timeline. The EDL is the single bridge between them.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RemovedSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    orig_start_ms: int = Field(ge=0)
    orig_end_ms: int = Field(ge=0)
    final_start_ms: int = Field(ge=0)  # where the kept material AFTER this cut begins

    @property
    def length_ms(self) -> int:
        return self.orig_end_ms - self.orig_start_ms


class EditDecisionList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_rate: int
    removals: list[RemovedSpan] = Field(default_factory=list)

    def to_final_ms(self, orig_ms: int) -> int:
        """Map a timestamp on the original recording onto the final timeline."""
        t = orig_ms
        for r in self.removals:
            if orig_ms >= r.orig_end_ms:
                t -= r.length_ms
            elif orig_ms > r.orig_start_ms:  # inside a removed region: clamp to its start
                return r.orig_start_ms - sum(
                    q.length_ms for q in self.removals if q.orig_end_ms <= r.orig_start_ms
                )
        return max(0, t)

    def validate_monotonic(self) -> None:
        last_end = -1
        for r in self.removals:
            assert r.orig_start_ms >= last_end, "overlapping removals"
            assert r.orig_end_ms >= r.orig_start_ms, "negative-length removal"
            last_end = r.orig_end_ms
