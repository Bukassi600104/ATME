"""Strict ATME visual-pipeline v2 contracts.

These types mirror the three JSON contracts in ``/schemas``.  V2 is deliberately
separate from the legacy renderer contract: accepting a v2 document never implies
that the v1 renderer can execute it.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


ObjectType = Literal[
    "freehand", "line", "arrow", "rectangle", "rounded_rectangle", "ellipse",
    "polygon", "bracket", "underline", "highlight", "callout", "text", "list",
    "icon", "pictogram", "character", "image", "evidence", "chart", "comparison",
    "browser", "application", "terminal", "code", "document", "device", "server",
    "database", "folder", "network", "group", "mask", "clip", "composition", "instance",
]
ActionVerb = Literal[
    "reveal", "write", "draw", "enter", "exit", "move", "scale", "rotate", "fade",
    "highlight", "dim", "isolate", "connect", "disconnect", "replace", "morph",
    "cross_out", "annotate", "group", "ungroup", "split", "count", "progressive_reveal",
    "insert_evidence", "return_board", "camera_hold", "camera_cut", "camera_pan",
    "camera_zoom", "camera_reframe", "sound_cue", "music_state", "purposeful_silence",
]


class Point(StrictModel):
    x: float
    y: float


class Bounds(StrictModel):
    x: float
    y: float
    width: float = Field(gt=0)
    height: float = Field(gt=0)


class Transform(StrictModel):
    position: Point
    scale_x: float = Field(default=1, gt=0)
    scale_y: float = Field(default=1, gt=0)
    rotation_degrees: float = 0
    origin: Point = Field(default_factory=lambda: Point(x=0.5, y=0.5))


class Anchor(StrictModel):
    anchor_id: str = Field(min_length=1)
    point: Point


class StyleRefs(StrictModel):
    stroke: str | None = None
    fill: str | None = None
    text: str | None = None
    effect: str | None = None


class Provenance(StrictModel):
    category: Literal["original", "user_owned", "licensed", "external_evidence", "generated"]
    source_uri: str | None = None
    checksum_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    license_status: Literal["owned", "licensed", "fair_use_review", "not_applicable", "unresolved"]
    fabrication_prohibited: bool
    originality_status: Literal["original", "transformed", "reference_only", "unresolved"]


class AssetV2(StrictModel):
    asset_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    kind: Literal[
        "audio", "video", "image", "source_image", "evidence", "icon", "pictogram",
        "character", "illustration", "chart_data", "font", "sound_effect", "music",
        "screen_recording", "presenter", "logo",
    ]
    semantic_role: str = Field(min_length=1)
    managed_ref: str | None = None
    checksum_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    duration_ms: int | None = Field(default=None, gt=0)
    provenance: Provenance
    style_family: str | None = None
    style_version: str | None = None
    allowed_transformations: list[Literal["crop", "scale", "rotate", "mask", "annotate", "color_treatment"]]
    fallback_id: str | None = None

    @model_validator(mode="after")
    def evidence_is_verifiable(self):
        if self.kind == "evidence" and (
            self.provenance.license_status == "unresolved"
            or not self.checksum_sha256
            or not self.provenance.source_uri
        ):
            raise ValueError("evidence assets require resolved provenance, source URI, and checksum")
        return self


class Geometry(StrictModel):
    bounds: Bounds
    points: list[Point] = Field(default_factory=list)
    corner_radius: float | None = Field(default=None, ge=0)


class ObjectBase(StrictModel):
    object_id: str = Field(min_length=1)
    board_id: str = Field(min_length=1)
    beat_id: str = Field(min_length=1)
    semantic_role: str = Field(min_length=1)
    z_index: int
    geometry: Geometry
    transform: Transform
    opacity: float = Field(default=1, ge=0, le=1)
    visible: bool = True
    style: StyleRefs
    anchors: list[Anchor] = Field(default_factory=list)
    parent_id: str | None = None
    clip_id: str | None = None
    initial_state: str = Field(min_length=1)
    asset_id: str | None = None
    description: str = Field(min_length=1)
    coverage_ids: list[str] = Field(min_length=1)


class MarkObject(ObjectBase):
    object_type: Literal[
        "freehand", "line", "rectangle", "rounded_rectangle", "ellipse", "polygon",
        "bracket", "underline", "highlight",
    ]
    path_data: str | None = None


class ConnectorObject(ObjectBase):
    object_type: Literal["arrow", "network"]
    source_object_id: str | None = None
    source_anchor_id: str | None = None
    destination_object_id: str
    destination_anchor_id: str
    role: Literal["pointer", "semantic_connector"]
    routing: Literal["straight", "elbow", "curve"]
    allow_self_loop: bool = False

    @model_validator(mode="after")
    def reject_unapproved_self_loop(self):
        if self.source_object_id == self.destination_object_id and not self.allow_self_loop:
            raise ValueError("connector self-loop requires allow_self_loop")
        return self


class TextObject(ObjectBase):
    object_type: Literal["text", "list", "callout", "code"]
    text: str = Field(min_length=1)
    items: list[str] = Field(default_factory=list)


class VisualObject(ObjectBase):
    object_type: Literal[
        "icon", "pictogram", "character", "image", "evidence", "chart", "comparison",
        "browser", "application", "terminal", "document", "device", "server", "database",
        "folder", "composition", "instance",
    ]
    variant: str | None = None


class ContainerObject(ObjectBase):
    object_type: Literal["group", "mask", "clip"]
    child_ids: list[str] = Field(min_length=1)


ExecutableObject = Annotated[
    MarkObject | ConnectorObject | TextObject | VisualObject | ContainerObject,
    Field(discriminator="object_type"),
]


class BeatStartTrigger(StrictModel):
    kind: Literal["beat_start"]
    beat_id: str = Field(min_length=1)
    offset_ms: int = 0


class WordTrigger(StrictModel):
    kind: Literal["word"]
    word: str = Field(min_length=1)
    occurrence: int = Field(default=1, ge=1)
    offset_ms: int = 0
    minimum_confidence: float = Field(default=0.75, ge=0, le=1)


class PhraseTrigger(StrictModel):
    kind: Literal["phrase"]
    phrase: str = Field(min_length=1)
    occurrence: int = Field(default=1, ge=1)
    offset_ms: int = 0
    minimum_confidence: float = Field(default=0.75, ge=0, le=1)


class AbsoluteTrigger(StrictModel):
    kind: Literal["absolute"]
    at_ms: int = Field(ge=0)


class PriorActionTrigger(StrictModel):
    kind: Literal["prior_action"]
    action_id: str = Field(min_length=1)
    offset_ms: int = 0


Trigger = Annotated[
    BeatStartTrigger | WordTrigger | PhraseTrigger | AbsoluteTrigger | PriorActionTrigger,
    Field(discriminator="kind"),
]


class FallbackPolicy(StrictModel):
    fallback_id: str
    on_failure: Literal["block", "degrade", "skip_with_exception"]


class ActionBase(StrictModel):
    action_id: str = Field(min_length=1)
    source_instruction_id: str = Field(min_length=1)
    board_id: str = Field(min_length=1)
    semantic_reason: str = Field(min_length=1)
    trigger: Trigger
    easing: Literal["linear", "ease_in", "ease_out", "ease_in_out", "step"] = "ease_out"
    expected_state: str | None = None
    post_state: str = Field(min_length=1)
    fallback: FallbackPolicy
    coverage_id: str = Field(min_length=1)


class TargetAction(ActionBase):
    verb: Literal[
        "reveal", "write", "draw", "enter", "exit", "highlight", "dim", "isolate",
        "cross_out", "annotate", "count", "progressive_reveal",
    ]
    target_ids: list[str] = Field(min_length=1)
    annotation: str | None = None

    @model_validator(mode="after")
    def exit_is_permanent_removal(self):
        if self.verb == "exit" and self.post_state != "removed":
            raise ValueError("exit must declare the canonical removed post-state")
        return self


class TransformAction(ActionBase):
    verb: Literal["move", "scale", "rotate", "fade"]
    target_ids: list[str] = Field(min_length=1)
    destination: Transform | None = None
    opacity: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def parameters_match_verb(self):
        if self.verb == "fade" and self.opacity is None:
            raise ValueError("fade requires opacity")
        if self.verb != "fade" and self.destination is None:
            raise ValueError(f"{self.verb} requires destination transform")
        return self


class ConnectionAction(ActionBase):
    verb: Literal["connect", "disconnect"]
    connector_id: str
    source_object_id: str | None = None
    source_anchor_id: str | None = None
    destination_object_id: str
    destination_anchor_id: str


class ReplaceAction(ActionBase):
    verb: Literal["replace", "morph"]
    from_object_id: str
    to_object_id: str


class GroupAction(ActionBase):
    verb: Literal["group", "ungroup", "split"]
    target_ids: list[str] = Field(min_length=1)
    container_id: str | None = None


class EvidenceAction(ActionBase):
    verb: Literal["insert_evidence", "return_board"]
    evidence_asset_id: str | None = None
    destination_board_id: str
    destination_state: str


class CameraAction(ActionBase):
    verb: Literal["camera_hold", "camera_cut", "camera_pan", "camera_zoom", "camera_reframe"]
    target_ids: list[str] = Field(min_length=1)
    framing: Literal["wide", "medium", "close", "detail", "safe_area"]
    movement_purpose: Literal["orient", "reveal", "compare", "follow", "emphasize", "return"]


class SoundAction(ActionBase):
    verb: Literal["sound_cue", "music_state", "purposeful_silence"]
    asset_id: str | None = None
    gain_db: float = Field(default=0, ge=-60, le=12)
    state: str

    @model_validator(mode="after")
    def asset_matches_verb(self):
        if self.verb in ("sound_cue", "music_state") and not self.asset_id:
            raise ValueError(f"{self.verb} requires an asset")
        if self.verb == "purposeful_silence" and self.asset_id is not None:
            raise ValueError("purposeful silence cannot name an asset")
        return self


CanonicalAction = Annotated[
    TargetAction | TransformAction | ConnectionAction | ReplaceAction | GroupAction
    | EvidenceAction | CameraAction | SoundAction,
    Field(discriminator="verb"),
]


class NarrativeAuthority(StrictModel):
    mode: Literal["approved_script_plus_recording", "recording_only"]
    authority_id: str
    timing_media_id: str
    timing_media_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    cleaned_timeline_revision: int = Field(ge=0)
    cleaned_timeline_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


class OutputProfile(StrictModel):
    profile_id: Literal["LONG_FORM_16_9", "SHORT_FORM_9_16"]
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: float = Field(gt=0)

    @model_validator(mode="after")
    def profile_matches_dimensions(self):
        actual = self.width / self.height
        expected = 16 / 9 if self.profile_id == "LONG_FORM_16_9" else 9 / 16
        if abs(actual - expected) > 0.01:
            raise ValueError("output profile and dimensions disagree")
        return self


class BoardSpec(StrictModel):
    board_id: str
    template: Literal[
        "timeline", "layer_stack", "comparison", "hub_spokes", "flow", "nested_boundary",
        "quantity_ladder", "evidence_annotation", "recap", "custom",
    ]
    object_ids: list[str]
    persistence_policy: Literal["within_board", "returnable", "single_beat"]
    density_limit: int = Field(ge=1, le=12)
    creation_reason: str
    departure_reason: str | None = None
    return_reason: str | None = None
    expected_prior_state: str | None = None
    activation_policy: Literal["once", "returnable", "persistent"]
    aspect_composition: dict[Literal["LONG_FORM_16_9", "SHORT_FORM_9_16"], str]


class SemanticObjectSpec(StrictModel):
    """Director-level object declaration; geometry is resolved in ExecutableLayoutV2."""

    object_id: str
    object_type: ObjectType
    board_id: str
    beat_id: str
    semantic_role: str
    description: str
    asset_id: str | None = None
    initial_state: str
    coverage_ids: list[str] = Field(min_length=1)


class AttentionPlan(StrictModel):
    primary_targets: list[str] = Field(min_length=1)
    secondary_context: list[str]
    dimmed_targets: list[str]
    priority: Literal["listen", "read", "inspect", "compare"]
    progressive_state: str

    @model_validator(mode="after")
    def no_attention_conflicts(self):
        sets = [set(self.primary_targets), set(self.secondary_context), set(self.dimmed_targets)]
        if any(sets[i] & sets[j] for i in range(3) for j in range(i + 1, 3)):
            raise ValueError("attention targets cannot occupy conflicting roles")
        return self


class ContinuityPlan(StrictModel):
    keep: list[str]
    change: list[str]
    remove: list[str]
    return_from_board_id: str | None = None
    expected_state_versions: dict[str, int]
    replacements: dict[str, str]
    developed_return_state: str | None = None
    hook_resolution_role: Literal["none", "opens_hook", "resolves_hook"]


class EvidenceIntent(StrictModel):
    claim_id: str
    claim: str
    evidence_asset_id: str
    crop: Bounds
    focus_region: Bounds
    mask_object_id: str | None = None
    darkening: float = Field(ge=0, le=1)
    source_label: str
    annotation: str | None = None
    annotation_target_id: str | None = None
    annotation_omission_reason: str | None = None
    readable_hold_intent_ms: int = Field(gt=0)
    destination_board_id: str
    destination_state: str
    provenance_verified: bool
    checksum_verified: bool

    @model_validator(mode="after")
    def annotation_is_explained(self):
        if self.annotation is None and not self.annotation_omission_reason:
            raise ValueError("evidence without annotation requires an omission reason")
        if self.annotation is not None and not self.annotation_target_id:
            raise ValueError("evidence annotation requires a target")
        return self


class CameraIntent(StrictModel):
    mode: Literal["hold", "cut", "pan", "zoom", "reframe"]
    target_ids: list[str] = Field(min_length=1)
    reason: str = Field(min_length=1)
    framing: Literal["wide", "medium", "close", "detail", "safe_area"]
    movement_purpose: Literal["orient", "reveal", "compare", "follow", "emphasize", "return"]
    duration_ms: int = Field(ge=0)
    easing: Literal["linear", "ease_in", "ease_out", "ease_in_out", "step"]


class SoundIntent(StrictModel):
    role: Literal["none", "effect", "music", "purposeful_silence"]
    asset_id: str | None = None
    reason: str
    gain_db: float = Field(default=0, ge=-60, le=12)

    @model_validator(mode="after")
    def asset_matches_role(self):
        if self.role in ("effect", "music") and not self.asset_id:
            raise ValueError(f"{self.role} sound intent requires an asset")
        if self.role in ("none", "purposeful_silence") and self.asset_id is not None:
            raise ValueError(f"{self.role} sound intent cannot name an asset")
        return self


class BeatV2(StrictModel):
    beat_id: str
    narration_summary: str
    rhetorical_role: Literal[
        "hook", "definition", "history", "comparison", "mechanism", "limitation",
        "evidence", "example", "consequence", "sponsor", "conclusion",
    ]
    visual_purpose: Literal[
        "identity", "quantity", "change", "causality", "comparison", "sequence",
        "containment", "conflict", "location", "emphasis", "proof",
    ]
    board_id: str
    object_ids: list[str]
    action_ids: list[str]
    attention: AttentionPlan
    continuity: ContinuityPlan
    camera_intent: CameraIntent
    sound_intent: SoundIntent
    evidence: EvidenceIntent | None = None
    fallback_ids: list[str]
    coverage_ids: list[str] = Field(min_length=1)


class FallbackRecord(StrictModel):
    fallback_id: str
    affected_ids: list[str] = Field(min_length=1)
    reason_code: str
    degradation_class: Literal["none", "visual_simplification", "asset_substitution", "timing_relaxation", "omission"]
    substitute: str
    recoverable: bool
    production_blocking: bool
    user_exception_required: bool
    status: Literal["unused", "selected", "resolved", "rejected"]


class CoverageRecord(StrictModel):
    coverage_id: str
    instruction_id: str
    status: Literal["executed", "degraded", "rejected"]
    action_ids: list[str]
    fallback_id: str | None = None

    @model_validator(mode="after")
    def degradation_is_explicit(self):
        if self.status == "executed" and (not self.action_ids or self.fallback_id is not None):
            raise ValueError("executed coverage requires actions and no fallback")
        if self.status == "degraded" and (not self.fallback_id or not self.action_ids):
            raise ValueError("degraded coverage requires retained actions and fallback")
        if self.status == "rejected" and (self.action_ids or not self.fallback_id):
            raise ValueError("rejected coverage requires no actions and an explicit fallback")
        return self


class VisualPlanV2(StrictModel):
    contract_version: Literal["2.0.0"]
    plan_id: str
    project_id: int = Field(ge=1)
    project_revision: int = Field(ge=0)
    narrative_authority: NarrativeAuthority
    output_profile: OutputProfile
    style_system_version: str
    asset_registry_version: str
    declared_capability_version: str
    assets: list[AssetV2]
    objects: list[SemanticObjectSpec] = Field(min_length=1)
    boards: list[BoardSpec] = Field(min_length=1)
    actions: list[CanonicalAction]
    beats: list[BeatV2] = Field(min_length=1)
    fallbacks: list[FallbackRecord]
    coverage: list[CoverageRecord] = Field(min_length=1)
    opening_beat_id: str
    conclusion_beat_id: str

    @model_validator(mode="after")
    def validate_graph(self):
        if self.style_system_version != "atme-style-v2":
            raise ValueError("unknown style-system version")
        if self.asset_registry_version != "atme-assets-v2":
            raise ValueError("unknown asset-registry version")
        _unique(self.assets, "asset_id")
        _unique(self.objects, "object_id")
        _unique(self.boards, "board_id")
        _unique(self.actions, "action_id")
        _unique(self.beats, "beat_id")
        _unique(self.fallbacks, "fallback_id")
        _unique(self.coverage, "coverage_id")
        boards = {x.board_id for x in self.boards}
        objects = {x.object_id for x in self.objects}
        actions = {x.action_id for x in self.actions}
        beats = {x.beat_id for x in self.beats}
        assets = {x.asset_id for x in self.assets}
        coverage = {x.coverage_id for x in self.coverage}
        fallbacks = {x.fallback_id for x in self.fallbacks}
        action_map = {x.action_id: x for x in self.actions}
        object_map = {x.object_id: x for x in self.objects}
        asset_map = {x.asset_id: x for x in self.assets}
        if self.opening_beat_id not in beats or self.conclusion_beat_id not in beats:
            raise ValueError("opening and conclusion beats must exist")
        for board in self.boards:
            _subset(board.object_ids, objects, f"board {board.board_id} objects")
            owned = {x.object_id for x in self.objects if x.board_id == board.board_id}
            if set(board.object_ids) != owned:
                raise ValueError(f"board {board.board_id} inventory must match object ownership")
            if len(board.object_ids) > board.density_limit:
                raise ValueError(f"board {board.board_id} exceeds density limit")
        for obj in self.objects:
            if obj.board_id not in boards or obj.beat_id not in beats:
                raise ValueError(f"object {obj.object_id} references unknown board or beat")
            if obj.asset_id and obj.asset_id not in assets:
                raise ValueError(f"object {obj.object_id} references unknown asset")
            _subset(obj.coverage_ids, coverage, f"object {obj.object_id} coverage")
        for beat in self.beats:
            if beat.board_id not in boards:
                raise ValueError(f"beat {beat.beat_id} references unknown board")
            _subset(beat.object_ids, objects, f"beat {beat.beat_id} objects")
            _subset(beat.action_ids, actions, f"beat {beat.beat_id} actions")
            _subset(beat.coverage_ids, coverage, f"beat {beat.beat_id} coverage")
            _subset(beat.fallback_ids, fallbacks, f"beat {beat.beat_id} fallbacks")
            _subset(beat.attention.primary_targets + beat.attention.secondary_context
                    + beat.attention.dimmed_targets, objects, f"beat {beat.beat_id} attention")
            _subset(beat.continuity.keep + beat.continuity.change + beat.continuity.remove,
                    objects, f"beat {beat.beat_id} continuity")
            _subset(list(beat.continuity.replacements) + list(beat.continuity.replacements.values()),
                    objects, f"beat {beat.beat_id} replacements")
            _subset(beat.camera_intent.target_ids, objects, f"beat {beat.beat_id} camera")
            owned_objects = {item.object_id for item in self.objects if item.beat_id == beat.beat_id}
            if set(beat.object_ids) != owned_objects:
                raise ValueError(f"beat {beat.beat_id} must own all and only its declared objects")
            if any(object_map[item].board_id != beat.board_id for item in beat.object_ids):
                raise ValueError(f"beat {beat.beat_id} object ownership crosses boards")
            if any(action_map[item].board_id != beat.board_id for item in beat.action_ids):
                raise ValueError(f"beat {beat.beat_id} action ownership crosses boards")
            linked_coverage = ({coverage_id for object_id in beat.object_ids
                                for coverage_id in object_map[object_id].coverage_ids}
                               | {action_map[action_id].coverage_id for action_id in beat.action_ids})
            if not linked_coverage.issubset(set(beat.coverage_ids)):
                raise ValueError(f"beat {beat.beat_id} omits coverage owned by its objects or actions")
            if beat.continuity.return_from_board_id and beat.continuity.return_from_board_id not in boards:
                raise ValueError(f"beat {beat.beat_id} returns from an unknown board")
            _subset(beat.continuity.expected_state_versions, objects,
                    f"beat {beat.beat_id} expected state versions")
            if any(version < 1 for version in beat.continuity.expected_state_versions.values()):
                raise ValueError(f"beat {beat.beat_id} expected state versions must be positive")
            if beat.evidence and beat.evidence.evidence_asset_id not in assets:
                raise ValueError(f"beat {beat.beat_id} references unknown evidence asset")
            if beat.evidence:
                if beat.evidence.destination_board_id not in boards:
                    raise ValueError(f"beat {beat.beat_id} evidence references unknown destination board")
                if beat.evidence.annotation_target_id and beat.evidence.annotation_target_id not in objects:
                    raise ValueError(f"beat {beat.beat_id} evidence annotation target is unknown")
                if beat.evidence.mask_object_id and beat.evidence.mask_object_id not in objects:
                    raise ValueError(f"beat {beat.beat_id} evidence mask target is unknown")
            if beat.sound_intent.asset_id:
                asset = asset_map.get(beat.sound_intent.asset_id)
                if asset is None:
                    raise ValueError(f"beat {beat.beat_id} references unknown sound asset")
                expected_kinds = ({"audio", "sound_effect"} if beat.sound_intent.role == "effect"
                                  else {"audio", "music"})
                if asset.kind not in expected_kinds:
                    raise ValueError(f"beat {beat.beat_id} sound asset kind disagrees with its role")
        beat_action_ids = [action_id for beat in self.beats for action_id in beat.action_ids]
        if len(beat_action_ids) != len(set(beat_action_ids)) or set(beat_action_ids) != actions:
            raise ValueError("actions must be owned by exactly one beat")
        beat_coverage_ids = [coverage_id for beat in self.beats for coverage_id in beat.coverage_ids]
        if len(beat_coverage_ids) != len(set(beat_coverage_ids)) or set(beat_coverage_ids) != coverage:
            raise ValueError("coverage records must be owned by exactly one beat")
        for action in self.actions:
            if action.board_id not in boards or action.coverage_id not in coverage:
                raise ValueError(f"action {action.action_id} references unknown board or coverage")
            if action.fallback.fallback_id not in fallbacks:
                raise ValueError(f"action {action.action_id} references unknown fallback")
            action_fallback = next(x for x in self.fallbacks
                                   if x.fallback_id == action.fallback.fallback_id)
            if not ({action.action_id, action.source_instruction_id}
                    & set(action_fallback.affected_ids)):
                raise ValueError(f"action {action.action_id} fallback does not identify its affected instruction")
            _validate_action_references(action, objects, assets, boards)
        action_order = {item.action_id: index for index, item in enumerate(self.actions)}
        for action in self.actions:
            if isinstance(action.trigger, BeatStartTrigger) and action.trigger.beat_id not in beats:
                raise ValueError(f"action {action.action_id} references unknown trigger beat")
            if isinstance(action.trigger, PriorActionTrigger):
                prior = action.trigger.action_id
                if prior not in action_order or action_order[prior] >= action_order[action.action_id]:
                    raise ValueError(f"action {action.action_id} prior-action trigger is unresolved or not prior")
        instruction_ids = ({x.source_instruction_id for x in self.actions}
                           | {x.instruction_id for x in self.coverage})
        allowed_affected = objects | assets | actions | beats | instruction_ids
        for asset in self.assets:
            if asset.fallback_id and asset.fallback_id not in fallbacks:
                raise ValueError(f"asset {asset.asset_id} references unknown fallback")
        for fallback in self.fallbacks:
            _subset(fallback.affected_ids, allowed_affected, f"fallback {fallback.fallback_id} affected IDs")
        for item in self.coverage:
            _subset(item.action_ids, actions, f"coverage {item.coverage_id} actions")
            if item.fallback_id and item.fallback_id not in fallbacks:
                raise ValueError(f"coverage {item.coverage_id} references unknown fallback")
            if item.fallback_id:
                fallback = next(x for x in self.fallbacks if x.fallback_id == item.fallback_id)
                if fallback.status not in ("selected", "resolved"):
                    raise ValueError(f"coverage {item.coverage_id} requires its fallback to be selected")
                if item.instruction_id not in fallback.affected_ids:
                    raise ValueError(f"coverage {item.coverage_id} fallback does not affect its instruction")
            for action_id in item.action_ids:
                if action_map[action_id].coverage_id != item.coverage_id:
                    raise ValueError(f"coverage {item.coverage_id} and action {action_id} disagree")
                if action_map[action_id].source_instruction_id != item.instruction_id:
                    raise ValueError(f"coverage {item.coverage_id} instruction disagrees with action {action_id}")
            matching = {a.action_id for a in self.actions if a.coverage_id == item.coverage_id}
            if matching != set(item.action_ids):
                raise ValueError(f"coverage {item.coverage_id} must name all and only linked actions")
        if not {x.source_instruction_id for x in self.actions}.issubset(
            {x.instruction_id for x in self.coverage}
        ):
            raise ValueError("every executable action must have an instruction coverage record")
        selected_fallbacks = {x.fallback_id for x in self.fallbacks if x.status == "selected"}
        used_fallbacks = {x.fallback_id for x in self.coverage if x.fallback_id}
        if not selected_fallbacks.issubset(used_fallbacks):
            raise ValueError("selected fallbacks must be justified by instruction coverage")
        return self


class BoardActivation(StrictModel):
    activation_id: str
    board_id: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    reason: str

    @model_validator(mode="after")
    def nonempty(self):
        if self.end_ms <= self.start_ms:
            raise ValueError("board activation must be a non-empty half-open interval")
        return self


class ExecutableLayoutV2(StrictModel):
    contract_version: Literal["2.0.0"]
    layout_id: str
    project_id: int = Field(ge=1)
    project_revision: int = Field(ge=0)
    plan_id: str
    plan_revision: int = Field(ge=1)
    plan_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    output_profile: OutputProfile
    style_system_version: str
    asset_registry_version: str
    canvas: Bounds
    boards: list[BoardSpec] = Field(min_length=1)
    objects: list[ExecutableObject] = Field(min_length=1)
    activations: list[BoardActivation] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_scene_graph(self):
        if self.style_system_version != "atme-style-v2" or self.asset_registry_version != "atme-assets-v2":
            raise ValueError("unknown style-system or asset-registry version")
        if (self.canvas.width, self.canvas.height) != (self.output_profile.width, self.output_profile.height):
            raise ValueError("canvas must match the independently authored output profile")
        _unique(self.boards, "board_id"); _unique(self.objects, "object_id"); _unique(self.activations, "activation_id")
        board_ids = {x.board_id for x in self.boards}; object_ids = {x.object_id for x in self.objects}
        object_map = {x.object_id: x for x in self.objects}
        for board in self.boards:
            _subset(board.object_ids, object_ids, f"board {board.board_id} objects")
            owned = {x.object_id for x in self.objects if x.board_id == board.board_id}
            if set(board.object_ids) != owned:
                raise ValueError(f"board {board.board_id} inventory must match object ownership")
            if len(board.object_ids) > board.density_limit:
                raise ValueError(f"board {board.board_id} exceeds density limit")
        for obj in self.objects:
            if obj.board_id not in board_ids:
                raise ValueError(f"object {obj.object_id} references unknown board")
            if obj.parent_id:
                parent = object_map.get(obj.parent_id)
                if not isinstance(parent, ContainerObject):
                    raise ValueError(f"object {obj.object_id} parent must be a group/mask/clip container")
                if obj.object_id not in parent.child_ids:
                    raise ValueError(f"object {obj.object_id} and parent {obj.parent_id} disagree on membership")
            if obj.clip_id:
                clip = object_map.get(obj.clip_id)
                if not isinstance(clip, ContainerObject) or clip.object_type not in ("mask", "clip"):
                    raise ValueError(f"object {obj.object_id} clip must be a mask or clip object")
            _unique(obj.anchors, "anchor_id")
            if isinstance(obj, ConnectorObject):
                if obj.role == "semantic_connector" and obj.source_object_id is None:
                    raise ValueError("semantic connectors require an authoritative source endpoint")
                if obj.source_object_id and obj.source_object_id not in object_ids:
                    raise ValueError(f"connector {obj.object_id} has unknown source")
                if obj.destination_object_id not in object_ids:
                    raise ValueError(f"connector {obj.object_id} has unknown destination")
                _check_anchor(obj.source_object_id, obj.source_anchor_id, object_map)
                _check_anchor(obj.destination_object_id, obj.destination_anchor_id, object_map)
            if isinstance(obj, ContainerObject):
                _subset(obj.child_ids, object_ids, f"container {obj.object_id} children")
        _reject_parent_cycles(object_map)
        _reject_container_cycles(object_map)
        last_end = 0
        for activation in self.activations:
            if activation.board_id not in board_ids or activation.start_ms < last_end:
                raise ValueError("board activations must be sorted, non-overlapping, and reference known boards")
            last_end = activation.end_ms
        return self


class ResolvedTrigger(StrictModel):
    source: Trigger
    alignment_anchor_ms: int = Field(ge=0)
    resolved_at_ms: int = Field(ge=0)
    matched_text: str | None = None
    matched_occurrence: int | None = Field(default=None, ge=1)
    confidence: float = Field(ge=0, le=1)
    exact: bool

    @model_validator(mode="after")
    def confidence_supports_exactness(self):
        if isinstance(self.source, (WordTrigger, PhraseTrigger)):
            if not self.matched_text or self.matched_occurrence != self.source.occurrence:
                raise ValueError("word and phrase triggers require matching text and occurrence evidence")
            requested = self.source.word if isinstance(self.source, WordTrigger) else self.source.phrase
            normalized_requested = " ".join(requested.casefold().split())
            normalized_match = " ".join(self.matched_text.casefold().split())
            if normalized_requested not in normalized_match:
                raise ValueError("alignment evidence does not contain the requested word or phrase")
        elif self.matched_text is not None or self.matched_occurrence is not None:
            raise ValueError("non-speech triggers cannot carry matched-text evidence")
        minimum = getattr(self.source, "minimum_confidence", 0)
        if self.exact and self.confidence < minimum:
            raise ValueError("low-confidence alignment cannot be presented as exact")
        return self


class ResolvedAction(StrictModel):
    action: CanonicalAction
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    resolved_trigger: ResolvedTrigger

    @model_validator(mode="after")
    def interval(self):
        if self.end_ms <= self.start_ms:
            raise ValueError("actions use non-empty half-open intervals")
        return self


class ResolvedAsset(StrictModel):
    asset_id: str
    revision: int = Field(ge=1)
    managed_ref: str
    checksum_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    provenance_verified: bool


class ObjectState(StrictModel):
    object_id: str
    state: str
    state_version: int = Field(ge=1)
    visible: bool


class ResolvedBeatAnchor(StrictModel):
    beat_id: str = Field(min_length=1)
    start_ms: int = Field(ge=0)


class ValidationIssue(StrictModel):
    severity: Literal["warning", "error"]
    code: str
    message: str
    affected_ids: list[str]


class ValidationState(StrictModel):
    status: Literal["pass", "warn", "fail"]
    production_ready: bool
    issues: list[ValidationIssue]

    @model_validator(mode="after")
    def status_matches_issues(self):
        has_error = any(x.severity == "error" for x in self.issues)
        has_warning = any(x.severity == "warning" for x in self.issues)
        if self.status == "pass" and self.issues:
            raise ValueError("pass validation cannot contain issues")
        if self.status == "warn" and (has_error or not has_warning):
            raise ValueError("warn validation requires warnings and no errors")
        if self.status == "fail" and not has_error:
            raise ValueError("fail validation requires an error")
        if self.production_ready and (self.status != "pass" or has_error):
            raise ValueError("production-ready state cannot contain errors or non-pass status")
        if not self.production_ready and self.status == "pass":
            raise ValueError("a passing validation state must be production-ready")
        return self


class ResolvedVisualTimelineV2(StrictModel):
    contract_version: Literal["2.0.0"]
    timeline_id: str
    project_id: int = Field(ge=1)
    project_revision: int = Field(ge=0)
    plan_id: str
    plan_revision: int = Field(ge=1)
    plan_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    layout_id: str
    layout_revision: int = Field(ge=1)
    layout_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    cleaned_timeline_revision: int = Field(ge=0)
    cleaned_timeline_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    output_profile: OutputProfile
    style_system_version: str
    asset_registry_version: str
    duration_ms: int = Field(gt=0)
    compilation_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    resolved_assets: list[ResolvedAsset]
    initial_object_states: list[ObjectState]
    beat_anchors: list[ResolvedBeatAnchor] = Field(min_length=1)
    actions: list[ResolvedAction] = Field(min_length=1)
    coverage: list[CoverageRecord] = Field(min_length=1)
    fallbacks: list[FallbackRecord]
    validation: ValidationState

    @model_validator(mode="after")
    def validate_timeline(self):
        if self.style_system_version != "atme-style-v2" or self.asset_registry_version != "atme-assets-v2":
            raise ValueError("unknown style-system or asset-registry version")
        _unique(self.resolved_assets, "asset_id"); _unique(self.initial_object_states, "object_id")
        _unique(self.beat_anchors, "beat_id"); _unique(self.coverage, "coverage_id")
        _unique(self.fallbacks, "fallback_id")
        beat_anchors = {item.beat_id: item.start_ms for item in self.beat_anchors}
        if any(start >= self.duration_ms for start in beat_anchors.values()):
            raise ValueError("beat anchors must be within the resolved duration")
        action_ids = []
        previous = 0
        states = {item.object_id: item.state for item in self.initial_object_states}
        resolved_actions: dict[str, ResolvedAction] = {}
        for resolved in self.actions:
            action_ids.append(resolved.action.action_id)
            if resolved.start_ms < previous or resolved.end_ms > self.duration_ms:
                raise ValueError("actions must be monotonic and within duration")
            previous = resolved.start_ms
            action = resolved.action
            if resolved.resolved_trigger.source != action.trigger:
                raise ValueError(f"action {action.action_id} resolved a different trigger")
            if resolved.resolved_trigger.resolved_at_ms > resolved.start_ms:
                raise ValueError(f"action {action.action_id} begins before its resolved trigger")
            trigger = action.trigger
            anchor = resolved.resolved_trigger.alignment_anchor_ms
            if (isinstance(trigger, (WordTrigger, PhraseTrigger))
                    and resolved.resolved_trigger.resolved_at_ms != anchor + trigger.offset_ms):
                raise ValueError(f"action {action.action_id} speech trigger offset is incorrectly resolved")
            if isinstance(trigger, BeatStartTrigger):
                beat_start = beat_anchors.get(trigger.beat_id)
                if (beat_start is None or anchor != beat_start
                        or resolved.resolved_trigger.resolved_at_ms != beat_start + trigger.offset_ms):
                    raise ValueError(f"action {action.action_id} beat-start trigger is unresolved")
            if (isinstance(action.trigger, AbsoluteTrigger)
                    and (action.trigger.at_ms >= self.duration_ms
                         or anchor != action.trigger.at_ms
                         or resolved.resolved_trigger.resolved_at_ms != action.trigger.at_ms)):
                raise ValueError(f"action {action.action_id} absolute trigger is outside or incorrectly resolved")
            if isinstance(action.trigger, PriorActionTrigger):
                prior = resolved_actions.get(action.trigger.action_id)
                expected_anchor = prior.end_ms if prior else None
                expected = expected_anchor + action.trigger.offset_ms if prior else None
                if (prior is None or anchor != expected_anchor
                        or resolved.resolved_trigger.resolved_at_ms != expected):
                    raise ValueError(f"action {action.action_id} prior-action trigger is unresolved or out of order")
            targets = _action_object_references(action)
            for target in targets:
                if target not in states:
                    raise ValueError(f"action {action.action_id} targets an object without initial state")
                if states[target] == "removed" and action.verb not in ("return_board",):
                    raise ValueError(f"action {action.action_id} resurrects removed object {target}")
                if action.expected_state is not None and states[target] != action.expected_state:
                    raise ValueError(f"action {action.action_id} precondition failed for {target}")
            for target in targets:
                states[target] = "removed" if action.verb == "exit" else action.post_state
            resolved_actions[action.action_id] = resolved
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("action_id values must be unique")
        coverage_ids = {item.coverage_id for item in self.coverage}
        fallbacks = {item.fallback_id: item for item in self.fallbacks}
        action_map = {item.action.action_id: item.action for item in self.actions}
        allowed_affected = (set(action_map) | set(states) | {item.asset_id for item in self.resolved_assets}
                            | {item.source_instruction_id for item in action_map.values()}
                            | set(beat_anchors))
        for fallback in self.fallbacks:
            _subset(fallback.affected_ids, allowed_affected,
                    f"fallback {fallback.fallback_id} affected IDs")
        selected_fallbacks = {item.fallback_id for item in self.fallbacks
                              if item.status in ("selected", "resolved")}
        used_fallbacks = {item.fallback_id for item in self.coverage if item.fallback_id}
        if selected_fallbacks != used_fallbacks:
            raise ValueError("selected/resolved fallbacks must match coverage fallback use")
        for item in self.coverage:
            _subset(item.action_ids, set(action_map), f"coverage {item.coverage_id} actions")
            if item.fallback_id:
                fallback = fallbacks.get(item.fallback_id)
                if fallback is None or fallback.status not in ("selected", "resolved"):
                    raise ValueError(f"coverage {item.coverage_id} fallback is unavailable")
                if item.instruction_id not in fallback.affected_ids:
                    raise ValueError(f"coverage {item.coverage_id} fallback does not affect its instruction")
            linked = {action_id for action_id, action in action_map.items()
                      if action.coverage_id == item.coverage_id}
            if linked != set(item.action_ids):
                raise ValueError(f"coverage {item.coverage_id} must name all and only linked actions")
            for action_id in item.action_ids:
                action = action_map[action_id]
                if action.source_instruction_id != item.instruction_id:
                    raise ValueError(f"coverage {item.coverage_id} instruction disagrees with action {action_id}")
        if any(action.coverage_id not in coverage_ids for action in action_map.values()):
            raise ValueError("every resolved action must reference known coverage")
        if any(action.fallback.fallback_id not in fallbacks for action in action_map.values()):
            raise ValueError("every resolved action fallback must exist")
        for action in action_map.values():
            fallback = fallbacks[action.fallback.fallback_id]
            if not ({action.action_id, action.source_instruction_id} & set(fallback.affected_ids)):
                raise ValueError(f"action {action.action_id} fallback does not identify its affected instruction")
        if self.validation.production_ready:
            if any(x.status != "executed" for x in self.coverage):
                raise ValueError("production-ready timeline requires executed coverage")
            if any(x.production_blocking and x.status in ("selected", "rejected")
                   for x in self.fallbacks):
                raise ValueError("unresolved production-blocking fallback")
        return self


VISUAL_PLAN_ADAPTER = TypeAdapter(VisualPlanV2)
EXECUTABLE_LAYOUT_ADAPTER = TypeAdapter(ExecutableLayoutV2)
RESOLVED_TIMELINE_ADAPTER = TypeAdapter(ResolvedVisualTimelineV2)


class MigrationChange(StrictModel):
    path: str
    value: str
    reason: str


class MigrationReportV2(StrictModel):
    contract_version: Literal["2.0.0"]
    migration_id: str
    adapter_version: Literal["v1-to-v2.1"]
    source_contracts: dict[str, str]
    source_revisions: dict[str, int]
    source_sha256: dict[str, str]
    output_sha256: dict[str, str]
    inserted_defaults: list[MigrationChange]
    inferred_values: list[MigrationChange]
    unsupported_semantics: list[MigrationChange]
    degraded_fields: list[MigrationChange]
    warnings: list[str]
    lossless: bool


MIGRATION_REPORT_ADAPTER = TypeAdapter(MigrationReportV2)


def validate_plan_layout(plan_document: dict, layout_document: dict) -> None:
    """Reject any executable layout that silently changes semantic-plan meaning."""
    plan = VisualPlanV2.model_validate(plan_document)
    layout = ExecutableLayoutV2.model_validate(layout_document)
    if layout.plan_id != plan.plan_id:
        raise ValueError("layout references a different visual plan")
    semantic = {item.object_id: item for item in plan.objects}
    executable = {item.object_id: item for item in layout.objects}
    if set(semantic) != set(executable):
        raise ValueError("layout must realize every and only declared semantic object")
    for object_id, spec in semantic.items():
        obj = executable[object_id]
        object_document = obj.model_dump(mode="json")
        for field, value in spec.model_dump(mode="json").items():
            if object_document.get(field) != value:
                raise ValueError(f"layout object {object_id} changes semantic field {field}")
    plan_boards = {item.board_id: item for item in plan.boards}
    layout_boards = {item.board_id: item for item in layout.boards}
    if set(plan_boards) != set(layout_boards):
        raise ValueError("layout board inventory differs from the visual plan")
    for board_id, board in plan_boards.items():
        candidate = layout_boards[board_id]
        if candidate.model_dump(mode="json") != board.model_dump(mode="json"):
            raise ValueError(f"layout board {board_id} changes its directing declaration")


def _unique(items, field):
    values = [getattr(x, field) for x in items]
    if len(values) != len(set(values)):
        raise ValueError(f"{field} values must be unique")


def _subset(values, allowed, label):
    missing = set(values) - set(allowed)
    if missing:
        raise ValueError(f"{label} reference unknown IDs: {sorted(missing)}")


def _check_anchor(object_id, anchor_id, object_map):
    if object_id is None:
        if anchor_id is not None:
            raise ValueError("free-source connector cannot name an object anchor")
        return
    anchors = {x.anchor_id for x in object_map[object_id].anchors}
    if anchor_id not in anchors:
        raise ValueError(f"unknown anchor {anchor_id!r} on {object_id}")


def _reject_parent_cycles(object_map):
    for object_id in object_map:
        seen = set()
        current = object_id
        while current is not None:
            if current in seen:
                raise ValueError("group/mask/clip parentage must be acyclic")
            seen.add(current)
            current = object_map[current].parent_id if current in object_map else None


def _reject_container_cycles(object_map):
    graph = {object_id: (obj.child_ids if isinstance(obj, ContainerObject) else [])
             for object_id, obj in object_map.items()}

    def visit(object_id, visiting, visited):
        if object_id in visiting:
            raise ValueError("group/mask/clip child membership must be acyclic")
        if object_id in visited:
            return
        visiting.add(object_id)
        for child_id in graph[object_id]:
            child = object_map[child_id]
            if child.parent_id != object_id:
                raise ValueError(f"container {object_id} and child {child_id} disagree on parentage")
            visit(child_id, visiting, visited)
        visiting.remove(object_id)
        visited.add(object_id)

    visited = set()
    for object_id in object_map:
        visit(object_id, set(), visited)


def _validate_action_references(action, objects, assets, boards):
    refs = _action_object_references(action)
    _subset(refs, objects, f"action {action.action_id} objects")
    if isinstance(action, EvidenceAction):
        if action.destination_board_id not in boards:
            raise ValueError(f"action {action.action_id} references unknown destination board")
        if action.evidence_asset_id and action.evidence_asset_id not in assets:
            raise ValueError(f"action {action.action_id} references unknown evidence asset")
    if isinstance(action, SoundAction) and action.asset_id and action.asset_id not in assets:
        raise ValueError(f"action {action.action_id} references unknown sound asset")


def _action_object_references(action):
    refs: list[str] = []
    if isinstance(action, (TargetAction, TransformAction, GroupAction, CameraAction)):
        refs.extend(action.target_ids)
    elif isinstance(action, ConnectionAction):
        refs.extend([action.connector_id, action.destination_object_id])
        if action.source_object_id:
            refs.append(action.source_object_id)
    elif isinstance(action, ReplaceAction):
        refs.extend([action.from_object_id, action.to_object_id])
    return refs
