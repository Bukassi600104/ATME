"""Pydantic mirrors of the versioned JSON Schemas in /schemas.

The JSON Schemas are the source of truth for cross-stage validation; these models give the
Python side typed views plus the few semantic rules JSON Schema cannot express comfortably.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Source(_Strict):
    source_id: str = Field(pattern=r"^src-[a-zA-Z0-9_-]+$")
    url: str
    title: str = Field(min_length=1)
    publisher: str | None = None
    published_at: str | None = None
    retrieved_at: str
    excerpt: str | None = None


class Claim(_Strict):
    claim_id: str = Field(pattern=r"^clm-[a-zA-Z0-9_-]+$")
    text: str = Field(min_length=1)
    kind: Literal["fact", "figure", "quote", "opinion"]
    source_ids: list[str] = Field(min_length=1)
    status: Literal["verified", "dropped", "unresolved"]
    verification_rounds: int = Field(default=0, ge=0)
    notes: str | None = None

    @model_validator(mode="after")
    def _verified_figures_are_dual_sourced(self) -> "Claim":
        # ADR-0002: surviving quantitative claims need >= 2 independent sources.
        # Dropped claims are exempt by definition - insufficient sourcing is WHY they were cut.
        if (
            self.kind == "figure"
            and self.status == "verified"
            and len(set(self.source_ids)) < 2
        ):
            raise ValueError(
                f"{self.claim_id}: verified figure claims require >= 2 independent sources"
            )
        return self


class FactSheet(_Strict):
    topic: str = Field(min_length=1)
    generated_at: str
    research_model: str | None = None
    verification_rounds_used: int = Field(default=0, ge=0, le=5)
    sources: list[Source]
    claims: list[Claim] = Field(min_length=1)


class Scene(_Strict):
    scene_id: int = Field(ge=1)
    phase: Literal["hook", "context", "architecture", "conclusion"]
    spoken_text: str = Field(min_length=1)
    visual_directive: str = Field(min_length=1)
    est_seconds: float | None = Field(default=None, gt=0)
    claim_ids: list[str] = Field(default_factory=list)


class ScriptScenes(_Strict):
    topic: str = Field(min_length=1)
    title: str | None = None
    target_seconds: float | None = Field(default=None, gt=0)
    fact_sheet_digest: str | None = None
    scenes: list[Scene] = Field(min_length=2)


class _Focus(_Strict):
    x: int
    y: int
    width: int
    height: int


class CameraCue(_Strict):
    cue_ms: int = Field(ge=0)
    focus: _Focus
    easing: Literal["linear", "easeInOut"] = "easeInOut"
    action: Literal["hold", "cut", "pan", "zoom", "reframe"] | None = None
    transition_ms: int | None = Field(default=None, ge=0)

    @model_serializer(mode="wrap")
    def _serialize_camera(self, handler):
        return {key: value for key, value in handler(self).items() if value is not None}


class _Canvas(_Strict):
    width: int
    height: int


class LayoutDoc(_Strict):
    contract_version: Literal["1"]
    seed: int = Field(ge=0)
    canvas: _Canvas
    grid: Literal[50]
    roughness: int = Field(default=1, ge=0, le=2)
    elements: list[dict] = Field(min_length=1)  # detailed checks stay in JSON Schema
    camera_plan: list[CameraCue] = Field(default_factory=list)
    board_timeline: dict | None = None  # validated with layout schema and visibility semantics

    @model_serializer(mode="wrap")
    def _serialize_layout(self, handler):
        result = handler(self)
        if result.get("board_timeline") is None:
            result.pop("board_timeline", None)
        return result

    @model_validator(mode="after")
    def _visibility(self) -> "LayoutDoc":
        from atme.render.visibility import validate_visibility
        from atme.render.camera import validate_camera_intent

        doc = self.model_dump(exclude_none=True)
        validate_visibility(doc)
        validate_camera_intent(doc.get("camera_plan", []))
        return self


class AudioRef(_Strict):
    path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    sample_rate: int | None = None
    lufs: float | None = Field(default=None, ge=-30, le=-6)


class Word(_Strict):
    word: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=1)
    scene_id: int = Field(ge=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    flagged: bool = False


class Directive(_Strict):
    at_ms: int = Field(ge=0)
    scene_id: int = Field(ge=1)
    action: Literal["draw", "reveal", "highlight", "camera"]
    target_id: str


class EdlSpan(_Strict):
    orig_start_ms: int = Field(ge=0)
    orig_end_ms: int = Field(ge=0)
    final_start_ms: int = Field(ge=0)


class CueTimeline(_Strict):
    contract_version: Literal["1"]
    duration_ms: int = Field(ge=1)
    audio: AudioRef
    words: list[Word]
    directives: list[Directive]
    edl_original_to_final_ms: list[EdlSpan] = Field(default_factory=list)
