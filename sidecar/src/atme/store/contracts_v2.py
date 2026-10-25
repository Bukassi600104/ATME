"""Strict ATME visual-pipeline v2 contracts.

These types mirror the three JSON contracts in ``/schemas``.  V2 is deliberately
separate from the legacy renderer contract: accepting a v2 document never implies
that the v1 renderer can execute it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from math import gcd
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_serializer,
    model_validator,
)

from atme.render.v2_count import validate_count_policy


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
MASK_SOURCE_TYPES = frozenset({"rectangle", "rounded_rectangle", "ellipse", "polygon"})
MASK_FIELDS = ("mask_mode", "mask_source_object_id", "mask_coordinate_space",
               "invert", "feather_px")
MASK_SCHEMA_COMPATIBILITY = {
    "oneOf": [
        {"properties": {field: {"type": "null"} for field in MASK_FIELDS}},
        {"required": list(MASK_FIELDS), "properties": {
            "mask_mode": {"const": "alpha"},
            "mask_source_object_id": {"type": "string", "minLength": 1},
            "mask_coordinate_space": {"const": "parent_local"},
            "invert": {"const": False}, "feather_px": {"const": 0},
        }},
    ]
}


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


REGISTRY_BOUND_OBJECT_TYPES = frozenset({"icon", "pictogram", "character", "device", "document", "chart", "terminal"})


class RegistryAnchorMapping(StrictModel):
    placed_anchor_id: str = Field(min_length=1, pattern=r"\S")
    registry_anchor_name: str = Field(min_length=1, pattern=r"\S")


class RegistryBinding(StrictModel):
    """Exact authored anchor names, not inferred art parts or fitted geometry."""

    version: Literal["1.0.0"]
    asset_id: str = Field(pattern=r"^[a-z0-9-]+$")
    anchor_mappings: list[RegistryAnchorMapping] = Field(min_length=1, max_length=4096)

    @model_validator(mode="after")
    def unique_placed_anchors(self):
        ids = [row.placed_anchor_id for row in self.anchor_mappings]
        if len(set(ids)) != len(ids):
            raise ValueError("registry_binding requires unique placed anchor mappings")
        names = [row.registry_anchor_name for row in self.anchor_mappings]
        if len(set(names)) != len(names):
            raise ValueError("registry_binding requires unique registry anchor names")
        return self


REGISTRY_BINDING_SCHEMA = {
    "if": {"required": ["registry_binding"], "properties": {"registry_binding": {"type": "object"}}},
    "then": {"properties": {"object_type": {"enum": sorted(REGISTRY_BOUND_OBJECT_TYPES)}}},
}


TECHNICAL_FRAME_TABLE = {
    "browser": (("ready", "loading", "error"), ("title", "address", "content")),
    "application": (("ready", "busy", "error"), ("title", "navigation", "content")),
    "server": (("idle", "active", "offline"), ("title", "content")),
    "database": (("idle", "active", "offline"), ("title", "content")),
    "folder": (("closed", "open"), ("title", "content")),
    "comparison": (("balanced", "contrast"), ("left_title", "left_content", "right_title", "right_content")),
}


class TechnicalRoleBinding(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    role: Literal["title", "address", "navigation", "content", "left_title", "left_content", "right_title", "right_content"]
    object_id: str = Field(min_length=1, pattern=r"\S")


class TechnicalAnchorMapping(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    placed_anchor_id: str = Field(min_length=1, pattern=r"\S")
    native_anchor_name: Literal["top", "right", "bottom", "left"]


class TechnicalFrameBinding(StrictModel):
    """Authored content roles and chrome state; never a lifecycle-state channel."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    version: Literal["1.0.0"]
    container_group_id: str = Field(min_length=1, pattern=r"\S")
    display_state: Literal["ready", "loading", "error", "busy", "idle", "active", "offline", "closed", "open", "balanced", "contrast"]
    roles: list[TechnicalRoleBinding] = Field(min_length=2, max_length=4)
    anchor_mappings: list[TechnicalAnchorMapping] = Field(max_length=4)

    @model_validator(mode="after")
    def unique_real_roles_and_anchors(self):
        ids = [row.object_id for row in self.roles]
        roles = [row.role for row in self.roles]
        placed = [row.placed_anchor_id for row in self.anchor_mappings]
        names = [row.native_anchor_name for row in self.anchor_mappings]
        if (len(set(ids)) != len(ids) or len(set(roles)) != len(roles)
                or self.container_group_id in ids):
            raise ValueError("technical_frame requires distinct real role/group identities")
        if len(set(placed)) != len(placed) or len(set(names)) != len(names):
            raise ValueError("technical_frame requires one-to-one native anchor mappings")
        return self


TECHNICAL_FRAME_SCHEMA = [{
    "if": {"required": ["technical_frame"], "properties": {"technical_frame": {"type": "object"}}},
    "then": {"properties": {"object_type": {"enum": sorted(TECHNICAL_FRAME_TABLE)}}},
}, *[{
    "if": {"required": ["technical_frame", "object_type"], "properties": {
        "technical_frame": {"type": "object"}, "object_type": {"const": kind}}},
    "then": {"properties": {"technical_frame": {"properties": {
        "display_state": {"enum": list(states)}, "roles": {
            "minItems": len(roles), "maxItems": len(roles),
            "prefixItems": [{"properties": {"role": {"const": role}}} for role in roles]}}}}},
} for kind, (states, roles) in TECHNICAL_FRAME_TABLE.items()]]


def _validate_technical_frame_owner(obj):
    binding = obj.technical_frame
    if binding is None:
        return
    table = TECHNICAL_FRAME_TABLE.get(obj.object_type)
    if (table is None or binding.display_state not in table[0]
            or tuple(row.role for row in binding.roles) != table[1]
            or obj.object_id == binding.container_group_id
            or obj.object_id in {row.object_id for row in binding.roles}):
        raise ValueError("technical_frame requires the exact native owner/state/role contract")


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


MEDIA_OBJECT_TYPES = frozenset({"video", "presenter", "screen_recording"})


class MediaStreamPin(StrictModel):
    """Identity of a checked presentation inventory, not a container/FPS guess.

    Raw decoded PTS/durations are sorted in strict presentation order. The
    inventory's first PTS is the signed origin and its final PTS+duration is
    the exclusive end. The decoder must attest these pins against actual bytes.
    """

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    version: Literal["1.0.0"]
    stream_index: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    time_base_numerator: int = Field(gt=0)
    time_base_denominator: int = Field(gt=0)
    first_pts: int
    end_pts: int
    frame_count: int = Field(gt=0)
    timestamps_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @property
    def duration_ms(self) -> int:
        return ((self.end_pts - self.first_pts) * self.time_base_numerator * 1000
                // self.time_base_denominator)

    @model_validator(mode="after")
    def canonical_presentation_span(self):
        if (gcd(self.time_base_numerator, self.time_base_denominator) != 1
                or self.end_pts <= self.first_pts or self.duration_ms <= 0):
            raise ValueError("media_stream requires a reduced time base and positive exact presentation span")
        return self


def _validate_media_stream_asset(asset):
    pin = asset.media_stream
    if pin is not None and (asset.kind not in MEDIA_OBJECT_TYPES
                            or (asset.width, asset.height, asset.duration_ms)
                            != (pin.width, pin.height, pin.duration_ms)):
        raise ValueError("media_stream changes its selected video asset dimensions or duration")


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
    media_stream: MediaStreamPin | None = None
    provenance: Provenance
    style_family: str | None = None
    style_version: str | None = None
    allowed_transformations: list[Literal["crop", "scale", "rotate", "mask", "annotate", "color_treatment"]]
    fallback_id: str | None = None

    @model_serializer(mode="wrap")
    def preserve_legacy_media_shape(self, handler):
        result = handler(self)
        if self.media_stream is None:
            result.pop("media_stream", None)
        return result

    @model_validator(mode="after")
    def evidence_is_verifiable(self):
        _validate_media_stream_asset(self)
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


class PointerSourcePoint(StrictModel):
    """An authored parent-local source; never inferred from a target anchor."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False, revalidate_instances="always")
    x: float = Field(ge=-1_000_000, le=1_000_000)
    y: float = Field(ge=-1_000_000, le=1_000_000)

    @field_validator("x", "y", mode="before")
    @classmethod
    def exact_numeric_coordinates(cls, value):
        if type(value) not in (int, float):
            raise ValueError("source_point requires exact numeric coordinates")
        return value


def _explicit_source_point(value):
    if value is None:
        raise ValueError("source_point must be omitted or carry its exact authored coordinates")
    if type(value) not in (dict, PointerSourcePoint):
        raise ValueError("source_point requires an exact coordinate payload")
    return value


FREE_SOURCE_POINT_SCHEMA = {
    "if": {"required": ["source_point"]},
    "then": {"properties": {
        "object_type": {"const": "arrow"}, "role": {"const": "pointer"},
        "source_point": {"type": "object"}, "source_object_id": {"type": "null"},
        "source_anchor_id": {"type": "null"}, "allow_self_loop": {"const": False},
    }},
}


class ConnectorBinding(StrictModel):
    """Semantic authority projected exactly onto one executable relationship."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False,
                             revalidate_instances="always", json_schema_extra={
        "allOf": [
            {"if": {"properties": {"role": {"const": "pointer"}}, "required": ["role"]},
             "then": {"required": ["source_point"], "properties": {
                 "source_point": {"type": "object"}, "source_object_id": {"type": "null"},
                 "source_anchor_id": {"type": "null"}}}},
            {"if": {"properties": {"role": {"const": "semantic_connector"}}, "required": ["role"]},
             "then": {"required": ["source_object_id", "source_anchor_id"],
                 "not": {"required": ["source_point"]}, "properties": {
                     "source_object_id": {"type": "string", "minLength": 1},
                     "source_anchor_id": {"type": "string", "minLength": 1}}}},
        ],
    })
    source_object_id: str | None = None
    source_anchor_id: str | None = None
    destination_object_id: str = Field(min_length=1)
    destination_anchor_id: str = Field(min_length=1)
    role: Literal["pointer", "semantic_connector"]
    routing: Literal["straight", "elbow", "curve"]
    allow_self_loop: bool = Field(default=False, strict=True, json_schema_extra={"const": False})
    source_point: PointerSourcePoint | None = None

    @field_validator("source_point", mode="before")
    @classmethod
    def explicit_point(cls, value):
        return _explicit_source_point(value)

    @model_serializer(mode="wrap")
    def omit_absent_point(self, handler):
        result = handler(self)
        if self.source_point is None:
            result.pop("source_point", None)
        return result

    @model_validator(mode="after")
    def exact_relationship_authority(self):
        if self.allow_self_loop or self.source_object_id == self.destination_object_id:
            raise ValueError("connector_binding requires distinct endpoints and no self-loop")
        if self.role == "pointer":
            if self.source_point is None or self.source_object_id is not None or self.source_anchor_id is not None:
                raise ValueError("connector_binding pointer needs only its exact free source_point")
        elif self.source_point is not None or not self.source_object_id or not self.source_anchor_id:
            raise ValueError("connector_binding semantic relationship requires named source anchors")
        return self


CONNECTOR_BINDING_SCHEMA = {
    "if": {"required": ["connector_binding"]},
    "then": {"properties": {
        "object_type": {"enum": ["arrow", "network"]}, "connector_binding": {"type": "object"}},
        "allOf": [{"if": {"properties": {"object_type": {"const": "network"}}, "required": ["object_type"]},
                   "then": {"properties": {"connector_binding": {"properties": {
                       "role": {"const": "semantic_connector"}}}}}}]},
}


class ConnectorObject(ObjectBase):
    model_config = ConfigDict(json_schema_extra={"allOf": [FREE_SOURCE_POINT_SCHEMA]})
    object_type: Literal["arrow", "network"]
    source_object_id: str | None = None
    source_anchor_id: str | None = None
    destination_object_id: str
    destination_anchor_id: str
    role: Literal["pointer", "semantic_connector"]
    routing: Literal["straight", "elbow", "curve"]
    allow_self_loop: bool = False
    source_point: PointerSourcePoint | None = None

    @field_validator("source_point", mode="before")
    @classmethod
    def explicit_point(cls, value):
        return _explicit_source_point(value)

    @model_serializer(mode="wrap")
    def preserve_legacy_connector_shape(self, handler):
        result = handler(self)
        if self.source_point is None:
            result.pop("source_point", None)
        return result

    @model_validator(mode="after")
    def reject_unapproved_self_loop(self):
        if self.source_point is not None and (
                self.object_type != "arrow" or self.role != "pointer" or self.allow_self_loop
                or self.source_object_id is not None or self.source_anchor_id is not None):
            raise ValueError("source_point belongs only to a free-source arrow pointer")
        if self.source_object_id == self.destination_object_id and not self.allow_self_loop:
            raise ValueError("connector self-loop requires allow_self_loop")
        return self


class _StrictCodePayloadModel(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class CodeSpan(_StrictCodePayloadModel):
    """Authored text and role; ATME never tokenizes or rewrites this content."""

    span_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    role: Literal["plain", "keyword", "identifier", "literal", "comment", "operator", "punctuation"]
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def exact_single_line_scalars(self):
        for char in self.text:
            value = ord(char)
            if (value < 0x20 and value != 0x09 or 0x7F <= value <= 0x9F
                    or value in {0x2028, 0x2029, 0xFFFE, 0xFFFF}
                    or 0xD800 <= value <= 0xDFFF):
                raise ValueError("code spans require exact XML scalars on one LF-delimited line")
        return self


class CodeLine(_StrictCodePayloadModel):
    line_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    # An authored blank line has no spans. Empty spans cannot invent identity.
    spans: list[CodeSpan]


class CodePayload(_StrictCodePayloadModel):
    version: Literal["1.0.0"]
    font_system_id: Literal["atme-code-font-v1"]
    mode: Literal["plain", "tokens"]
    tab_size: Literal[2, 4, 8]
    lines: list[CodeLine] = Field(min_length=1)

    @model_validator(mode="after")
    def exact_authored_inventory(self):
        _unique(self.lines, "line_id")
        spans = [span for line in self.lines for span in line.spans]
        _unique(spans, "span_id")
        if self.mode == "plain" and any(
            len(line.spans) > 1 or any(span.role != "plain" for span in line.spans)
            for line in self.lines
        ):
            raise ValueError("plain code needs one exact plain span per nonempty authored line")
        return self

    def authored_text(self) -> str:
        return "\n".join("".join(span.text for span in line.spans) for line in self.lines)


class CalloutBinding(StrictModel):
    """Exact authored pointer endpoints; no source or destination inference."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    version: Literal["1.0.0"]
    leader_connector_id: str = Field(min_length=1)
    callout_anchor_id: str = Field(min_length=1)
    target_object_id: str = Field(min_length=1)
    target_anchor_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def named_references(self):
        if any(not value.strip() for value in (self.leader_connector_id, self.callout_anchor_id,
                                              self.target_object_id, self.target_anchor_id)):
            raise ValueError("callout_binding references must be nonblank")
        if self.leader_connector_id == self.target_object_id:
            raise ValueError("callout_binding leader and target must be distinct")
        return self


class StructuredListPayload(StrictModel):
    """Authored heading/group/order binding; each item is a real scene object."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    version: Literal["1.0.0"]
    container_group_id: str = Field(min_length=1)
    item_object_ids: list[str] = Field(min_length=1, max_length=256, json_schema_extra={"uniqueItems": True})

    @model_validator(mode="after")
    def exact_item_refs(self):
        if (not self.container_group_id.strip() or any(not key.strip() for key in self.item_object_ids)
                or len(set(self.item_object_ids)) != len(self.item_object_ids)
                or self.container_group_id in self.item_object_ids):
            raise ValueError("structured_list requires distinct nonblank authored item/group IDs")
        return self


class TextObject(ObjectBase):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, json_schema_extra={
        "allOf": [{"if": {"required": ["structured_list"],
                           "properties": {"structured_list": {"type": "object"}}},
                   "then": {"properties": {"object_type": {"const": "list"},
                                            "items": {"maxItems": 0}}}}],
    })
    object_type: Literal["text", "list", "callout", "code"]
    text: str = Field(min_length=1)
    items: list[str] = Field(default_factory=list)
    code_payload: CodePayload | None = None
    callout_binding: CalloutBinding | None = None
    structured_list: StructuredListPayload | None = None

    @model_serializer(mode="wrap")
    def preserve_legacy_text_shape(self, handler):
        result = handler(self)
        if self.code_payload is None:
            result.pop("code_payload", None)
        if self.callout_binding is None:
            result.pop("callout_binding", None)
        if self.structured_list is None:
            result.pop("structured_list", None)
        return result

    @model_validator(mode="after")
    def exact_authored_code(self):
        if self.structured_list is not None and (
            self.object_type != "list" or self.items or not self.text.strip()
            or self.object_id == self.structured_list.container_group_id
            or self.object_id in self.structured_list.item_object_ids
        ):
            raise ValueError("structured_list belongs to an exact heading with separate real items and group")
        if self.code_payload is not None and (
            self.object_type != "code" or self.items
            or self.text != self.code_payload.authored_text()
        ):
            raise ValueError("code_payload must preserve the exact code text and ordered LF lines")
        if self.callout_binding is not None and (
            self.object_type != "callout" or self.items or not self.text.strip()
            or self.object_id in {self.callout_binding.leader_connector_id, self.callout_binding.target_object_id}
        ):
            raise ValueError("callout_binding requires a nonblank callout with distinct leader and target")
        return self


class _StrictChartModel(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    @model_validator(mode="after")
    def exact_chart_labels(self):
        for name, text in self.__dict__.items():
            if not isinstance(text, str):
                continue
            if (not text.strip() and not (name == "unit" and text == "")
                    or any(ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F
                           or ord(char) in {0x2028, 0x2029, 0xFFFE, 0xFFFF}
                           or 0xD800 <= ord(char) <= 0xDFFF for char in text)):
                raise ValueError("chart_payload requires exact nonblank one-line XML labels; unit may be explicitly empty")
        return self


class ChartTick(_StrictChartModel):
    value: float
    label: str


class ChartAxis(_StrictChartModel):
    label: str
    unit: str
    domain: list[float] = Field(min_length=2, max_length=2)
    scale: Literal["linear", "log"]
    ticks: list[ChartTick] = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def exact_authored_domain_and_ticks(self):
        low, high = self.domain
        if low >= high or self.scale == "log" and low <= 0:
            raise ValueError("chart_payload axis domain must increase and log domains must be positive")
        values = [tick.value for tick in self.ticks]
        if len(set(values)) != len(values) or any(not low <= value <= high for value in values):
            raise ValueError("chart_payload requires unique authored in-domain ticks")
        return self


class ChartPoint(_StrictChartModel):
    point_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    x: float
    y: float
    label: str


class ChartSeries(_StrictChartModel):
    series_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    label: str
    color: str
    points: list[ChartPoint] = Field(min_length=1, max_length=4096)

    @model_validator(mode="after")
    def exact_authored_points(self):
        _unique(self.points, "point_id")
        return self


class ChartBar(_StrictChartModel):
    width: float = Field(gt=0)
    width_units: Literal["x_axis"]
    baseline: float


class ChartHighlight(_StrictChartModel):
    series_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    point_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    color: str


class ChartConstruction(_StrictChartModel):
    series_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    point_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    start_fraction: float = Field(ge=0, le=1)
    end_fraction: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def positive_authored_interval(self):
        if self.start_fraction >= self.end_fraction:
            raise ValueError("chart_payload construction requires start < end")
        return self


class ChartPayload(_StrictChartModel):
    """Exact external data and display decisions, not an inferred chart recipe."""

    version: Literal["1.0.0"]
    kind: Literal["bars", "line"]
    title: str
    x_axis: ChartAxis
    y_axis: ChartAxis
    series: list[ChartSeries] = Field(min_length=1, max_length=32)
    bar: ChartBar | None
    highlights: list[ChartHighlight] = Field(max_length=4096)
    construction: list[ChartConstruction] = Field(min_length=1, max_length=131072)

    @model_validator(mode="after")
    def truthful_data_and_references(self):
        _unique(self.series, "series_id")
        if (self.kind == "bars") != (self.bar is not None):
            raise ValueError("chart_payload bars require explicit width/baseline; line must not carry bar semantics")
        x_low, x_high = self.x_axis.domain
        y_low, y_high = self.y_axis.domain
        if self.bar is not None and not y_low <= self.bar.baseline <= y_high:
            raise ValueError("chart_payload bar baseline is outside its y-domain")
        data = set()
        for series in self.series:
            if self.kind == "line" and (len(series.points) < 2 or any(
                    left.x >= right.x for left, right in zip(series.points, series.points[1:]))):
                raise ValueError("chart_payload line points require strictly increasing authored x coordinates")
            for point in series.points:
                data.add((series.series_id, point.point_id))
                if not (x_low <= point.x <= x_high and y_low <= point.y <= y_high):
                    raise ValueError("chart_payload datum is outside its explicit domain")
                if self.bar is not None and not (x_low <= point.x - self.bar.width / 2
                                                < point.x + self.bar.width / 2 <= x_high):
                    raise ValueError("chart_payload full bar width must fit its x-domain")
        phases = [(row.series_id, row.point_id) for row in self.construction]
        highlights = [(row.series_id, row.point_id) for row in self.highlights]
        if len(set(phases)) != len(phases) or set(phases) != data:
            raise ValueError("chart_payload construction must reference every and only datum exactly once")
        if len(set(highlights)) != len(highlights) or not set(highlights) <= data:
            raise ValueError("chart_payload highlights must uniquely reference real authored data")
        return self


CHART_PAYLOAD_SCHEMA = {
    "if": {"required": ["chart_payload"], "properties": {"chart_payload": {"type": "object"}}},
    "then": {"properties": {"object_type": {"const": "chart"}, "asset_id": {"type": "null"},
                            "variant": {"type": "null"}, "registry_binding": {"type": "null"},
                            "technical_frame": {"type": "null"}}},
}


def _validate_chart_owner(obj):
    if obj.chart_payload is not None and (
            obj.object_type != "chart" or obj.asset_id is not None
            or getattr(obj, "variant", None) is not None or obj.registry_binding is not None
            or obj.technical_frame is not None):
        raise ValueError("chart_payload belongs only to its inline data-bound chart, never registry art or another owner")


class ImagePixelCrop(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class ImageFocalPoint(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


IMAGE_TRANSFORMATION_ORDER = ("scale", "crop", "rotate", "mask")


class ImagePlacement(StrictModel):
    """Authored placement of checked supporting pixels, never evidence authority."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    version: Literal["1.0.0"]
    source_revision: int = Field(ge=1)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_width: int = Field(gt=0)
    source_height: int = Field(gt=0)
    crop: ImagePixelCrop
    fit: Literal["contain", "cover"]
    focal_point: ImageFocalPoint
    allowed_transformations: list[Literal["scale", "crop", "rotate", "mask"]] = Field(
        min_length=1, max_length=4, json_schema_extra={"uniqueItems": True})

    @model_validator(mode="after")
    def exact_source_crop_and_permissions(self):
        if (self.crop.x + self.crop.width > self.source_width
                or self.crop.y + self.crop.height > self.source_height):
            raise ValueError("image_placement crop exceeds the pinned source pixels")
        allowed = self.allowed_transformations
        if allowed != [value for value in IMAGE_TRANSFORMATION_ORDER if value in allowed] or "scale" not in allowed:
            raise ValueError("image_placement permissions require unique canonical scale,crop,rotate,mask order")
        if ((self.crop.x, self.crop.y, self.crop.width, self.crop.height)
                != (0, 0, self.source_width, self.source_height) and "crop" not in allowed):
            raise ValueError("image_placement source crop requires crop permission")
        return self


class MediaPlayback(StrictModel):
    """One-to-one absolute playback of a checked half-open source interval."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    version: Literal["1.0.0"]
    placement: ImagePlacement
    source_stream: MediaStreamPin
    source_duration_ms: int = Field(gt=0)
    source_in_ms: int = Field(ge=0)
    source_out_ms: int = Field(gt=0)
    timeline_start_ms: int = Field(ge=0)
    frame_selection: Literal["last_pts_at_or_before"]

    @model_validator(mode="after")
    def exact_range_and_stream(self):
        if (not self.source_in_ms < self.source_out_ms <= self.source_duration_ms
                or self.source_duration_ms != self.source_stream.duration_ms
                or (self.placement.source_width, self.placement.source_height)
                != (self.source_stream.width, self.source_stream.height)):
            raise ValueError("media_playback requires the exact selected stream and a bounded half-open source range")
        return self


MEDIA_PLAYBACK_SCHEMA = [
    {"if": {"required": ["media_playback"],
            "properties": {"media_playback": {"type": "object"}}},
     "then": {"required": ["asset_id"], "properties": {
         "object_type": {"enum": sorted(MEDIA_OBJECT_TYPES)},
         "asset_id": {"type": "string", "minLength": 1}}}},
    {"if": {"required": ["object_type"],
            "properties": {"object_type": {"enum": sorted(MEDIA_OBJECT_TYPES)}}},
     "then": {"required": ["asset_id", "media_playback"], "properties": {
         "asset_id": {"type": "string", "minLength": 1},
         "media_playback": {"type": "object"},
         **{key: {"type": "null"} for key in (
             "variant", "registry_binding", "technical_frame", "chart_payload", "image_placement",
             "composition_binding", "character_assembly", "illustration_assembly", "structured_list",
             "code_payload", "callout_binding", "child_ids")}}}},
]


def _validate_media_playback_owner(obj):
    media = obj.media_playback
    is_media = obj.object_type in MEDIA_OBJECT_TYPES
    if ((media is not None) != is_media or is_media and (
            not obj.asset_id or any(getattr(obj, key, None) is not None for key in (
                "variant", "registry_binding", "technical_frame", "chart_payload", "image_placement",
                "composition_binding", "character_assembly", "illustration_assembly", "structured_list",
                "code_payload", "callout_binding", "child_ids")))):
        raise ValueError("media_playback requires its sole video/presenter/screen_recording owner and asset")


def validate_media_asset_binding(obj, asset):
    """Authored playback cannot change its exact selected-stream/source inventory."""
    media = obj.media_playback
    placement = media.placement
    if (asset is None or asset.asset_id != obj.asset_id or asset.kind != obj.object_type
            or (asset.revision, asset.checksum_sha256, asset.width, asset.height,
                asset.allowed_transformations, asset.duration_ms, asset.media_stream)
            != (placement.source_revision, placement.source_sha256, placement.source_width,
                placement.source_height, placement.allowed_transformations,
                media.source_duration_ms, media.source_stream)):
        raise ValueError("media_playback changes its exact asset pins, stream or permissions")


IMAGE_PLACEMENT_SCHEMA = {
    "if": {"required": ["image_placement"], "properties": {"image_placement": {"type": "object"}}},
    "then": {"required": ["asset_id"], "properties": {
        "object_type": {"const": "image"}, "asset_id": {"type": "string", "minLength": 1}}},
}


def _validate_image_placement_owner(obj):
    if obj.image_placement is not None and (obj.object_type != "image" or not obj.asset_id):
        raise ValueError("image_placement belongs only to an image with an explicit supporting asset_id")


def validate_image_asset_binding(obj, asset):
    """Bind one authored placement to its semantic or resolved asset inventory."""
    placement = obj.image_placement
    if (asset is None or obj.asset_id != asset.asset_id
            or asset.kind not in {"image", "source_image"}):
        raise ValueError("image_placement requires its exact supporting asset")
    if placement is None:
        if asset.allowed_transformations != ["scale"]:
            raise ValueError("image_placement sibling cannot grant a bare image expanded asset permissions")
        return
    if ((placement.source_revision, placement.source_sha256,
         placement.source_width, placement.source_height, placement.allowed_transformations)
            != (asset.revision, asset.checksum_sha256, asset.width,
                asset.height, asset.allowed_transformations)):
        raise ValueError("image_placement changes its asset pins or permissions")


class VisualObject(ObjectBase):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False,
                              json_schema_extra={"allOf": [REGISTRY_BINDING_SCHEMA, *TECHNICAL_FRAME_SCHEMA,
                                                          CHART_PAYLOAD_SCHEMA, IMAGE_PLACEMENT_SCHEMA,
                                                          *MEDIA_PLAYBACK_SCHEMA]})
    object_type: Literal[
        "icon", "pictogram", "character", "image", "evidence", "chart", "comparison",
        "browser", "application", "terminal", "document", "device", "server", "database",
        "folder", "composition", "instance", "video", "presenter", "screen_recording",
    ]
    variant: str | None = None
    registry_binding: RegistryBinding | None = None
    technical_frame: TechnicalFrameBinding | None = None
    chart_payload: ChartPayload | None = None
    image_placement: ImagePlacement | None = None
    media_playback: MediaPlayback | None = None

    @model_serializer(mode="wrap")
    def preserve_legacy_registry_shape(self, handler):
        result = handler(self)
        if self.media_playback is None:
            result.pop("media_playback", None)
        if self.registry_binding is None:
            result.pop("registry_binding", None)
        if self.technical_frame is None:
            result.pop("technical_frame", None)
        if self.chart_payload is None:
            result.pop("chart_payload", None)
        if self.image_placement is None:
            result.pop("image_placement", None)
        return result

    @model_validator(mode="after")
    def binding_owner_and_declared_anchors(self):
        _validate_media_playback_owner(self)
        _validate_image_placement_owner(self)
        _validate_chart_owner(self)
        _validate_technical_frame_owner(self)
        if self.technical_frame is not None:
            binding = self.technical_frame
            anchor_ids = [anchor.anchor_id for anchor in self.anchors]
            if (self.variant != binding.display_state or len(set(anchor_ids)) != len(anchor_ids)
                    or set(anchor_ids) != {row.placed_anchor_id for row in binding.anchor_mappings}):
                raise ValueError("technical_frame requires exact variant and every/only placed chrome anchor")
        binding = self.registry_binding
        if binding is None:
            return self
        if self.object_type not in REGISTRY_BOUND_OBJECT_TYPES:
            raise ValueError("registry_binding requires a supported registry-backed object")
        if self.variant != binding.asset_id:
            raise ValueError("registry_binding asset_id must equal the exact authored variant")
        anchor_ids = [anchor.anchor_id for anchor in self.anchors]
        if (len(set(anchor_ids)) != len(anchor_ids)
                or set(anchor_ids) != {row.placed_anchor_id for row in binding.anchor_mappings}):
            raise ValueError("registry_binding must map every and only unique placed anchor")
        return self


class ContainerObject(ObjectBase):
    # Initial empty groups need an explicit owner receipt on the layout.
    # Clip/mask/composition emptiness remains invalid at the scene-graph gate.
    child_ids: list[str]


class CharacterRoleBinding(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    role: Literal["head", "torso", "left_arm", "right_arm"]
    object_id: str = Field(min_length=1, pattern=r"\S")


CHARACTER_SEMANTIC_ROLES = (("head", "head"), ("left_hand", "left_arm"), ("right_hand", "right_arm"))


class CharacterAnchorBinding(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    semantic_name: Literal["head", "left_hand", "right_hand"]
    object_id: str = Field(min_length=1, pattern=r"\S")
    anchor_id: str = Field(min_length=1, pattern=r"\S")


class CharacterAssemblyBinding(StrictModel):
    """An author's explicit layered character claim, not a generated body/rig."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    version: Literal["1.0.0"]
    pose_id: Literal["neutral", "point_right", "open_hands"]
    roles: list[CharacterRoleBinding] = Field(min_length=4, max_length=4, json_schema_extra={
        "prefixItems": [{"properties": {"role": {"const": role}}}
                        for role in ("head", "torso", "left_arm", "right_arm")],
    })
    semantic_anchors: list[CharacterAnchorBinding] = Field(min_length=3, max_length=3, json_schema_extra={
        "prefixItems": [{"properties": {"semantic_name": {"const": name}}}
                        for name, _ in CHARACTER_SEMANTIC_ROLES],
    })

    @model_validator(mode="after")
    def exact_authored_inventory(self):
        if ([row.role for row in self.roles] != ["head", "torso", "left_arm", "right_arm"]
                or len({row.object_id for row in self.roles}) != 4):
            raise ValueError("character_assembly needs exact ordered distinct real roles")
        if ([row.semantic_name for row in self.semantic_anchors] != [name for name, _ in CHARACTER_SEMANTIC_ROLES]
                or len({(row.object_id, row.anchor_id) for row in self.semantic_anchors}) != len(self.semantic_anchors)):
            raise ValueError("character_assembly needs exact ordered semantic names and non-aliased anchors")
        return self


CHARACTER_ASSEMBLY_SCHEMA = {
    "if": {"required": ["character_assembly"], "properties": {"character_assembly": {"type": "object"}}},
    "then": {"required": ["child_ids"], "properties": {"object_type": {"const": "group"}}},
}


ILLUSTRATION_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
# JSON Schema's regex end anchor may match before a final newline. The model's
# stable-token pattern and the exported schema must reject the same exact text.
ILLUSTRATION_ID_SCHEMA = {"not": {"pattern": r"\s"}}


class IllustrationRoleBinding(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    role_id: str = Field(min_length=1, pattern=ILLUSTRATION_ID_PATTERN, json_schema_extra=ILLUSTRATION_ID_SCHEMA)
    kind: Literal["artwork", "content", "label", "state"]
    object_id: str = Field(min_length=1, pattern=r"\S")


class IllustrationAnchorBinding(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    semantic_name: str = Field(min_length=1, pattern=ILLUSTRATION_ID_PATTERN, json_schema_extra=ILLUSTRATION_ID_SCHEMA)
    role_id: str = Field(min_length=1, pattern=ILLUSTRATION_ID_PATTERN, json_schema_extra=ILLUSTRATION_ID_SCHEMA)
    object_id: str = Field(min_length=1, pattern=r"\S")
    anchor_id: str = Field(min_length=1, pattern=r"\S")


class IllustrationAssemblyBinding(StrictModel):
    """Per-plan authored content identity, not a registry asset or state machine."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    version: Literal["1.0.0"]
    family: Literal["icon", "pictogram", "device", "document", "terminal"]
    content_state_id: str = Field(min_length=1, pattern=ILLUSTRATION_ID_PATTERN,
                                  json_schema_extra=ILLUSTRATION_ID_SCHEMA)
    roles: list[IllustrationRoleBinding] = Field(min_length=1, max_length=4096,
        json_schema_extra={"contains": {"type": "object", "required": ["kind"],
                                       "properties": {"kind": {"enum": ["artwork", "content"]}}}})
    semantic_anchors: list[IllustrationAnchorBinding] = Field(max_length=4096)

    @model_validator(mode="after")
    def explicit_authored_inventory(self):
        role_ids = {row.role_id for row in self.roles}
        if (len(role_ids) != len(self.roles)
                or len({row.object_id for row in self.roles}) != len(self.roles)
                or not any(row.kind in {"artwork", "content"} for row in self.roles)):
            raise ValueError("illustration_assembly needs distinct real roles and authored artwork/content")
        if (len({row.semantic_name for row in self.semantic_anchors}) != len(self.semantic_anchors)
                or any(row.role_id not in role_ids for row in self.semantic_anchors)):
            raise ValueError("illustration_assembly needs unique authored semantic names and exact declared roles")
        return self


ILLUSTRATION_ASSEMBLY_SCHEMA = {
    "if": {"required": ["illustration_assembly"], "properties": {"illustration_assembly": {"type": "object"}}},
    "then": {"required": ["child_ids"], "properties": {"object_type": {"const": "group"},
        "child_ids": {"type": "array", "minItems": 1, "maxItems": 4096,
                      "uniqueItems": True, "items": {"type": "string"}}}},
}

EXCLUSIVE_ASSEMBLY_OWNER_SCHEMA = {"not": {
    "required": ["character_assembly", "illustration_assembly"],
    "properties": {"character_assembly": {"type": "object"}, "illustration_assembly": {"type": "object"}},
}}


class GroupContainer(ContainerObject):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, json_schema_extra=EXCLUSIVE_ASSEMBLY_OWNER_SCHEMA)
    object_type: Literal["group"]
    character_assembly: CharacterAssemblyBinding | None = None
    illustration_assembly: IllustrationAssemblyBinding | None = None
    composition_binding: CompositionBinding | None = None

    @model_validator(mode="after")
    def one_assembly_owner(self):
        if self.character_assembly is not None and self.illustration_assembly is not None:
            raise ValueError("illustration_assembly cannot share a character assembly owner")
        if self.composition_binding is not None and self.object_id != self.composition_binding.instance.root_object_id:
            raise ValueError("composition binding belongs only to its named real Group root")
        return self

    @model_serializer(mode="wrap")
    def preserve_legacy_character_shape(self, handler):
        result = handler(self)
        if self.character_assembly is None:
            result.pop("character_assembly", None)
        if self.illustration_assembly is None:
            result.pop("illustration_assembly", None)
        if self.composition_binding is None:
            result.pop("composition_binding", None)
        return result


class ClipContainer(ContainerObject):
    object_type: Literal["clip"]


class MaskContainer(ContainerObject):
    """Static alpha mask; source is a dedicated sibling, not painted content."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False,
                              json_schema_extra=MASK_SCHEMA_COMPATIBILITY)
    object_type: Literal["mask"]
    mask_mode: Literal["alpha"] | None = None
    mask_source_object_id: str | None = Field(default=None, min_length=1)
    mask_coordinate_space: Literal["parent_local"] | None = None
    invert: Literal[False] | None = None
    feather_px: Literal[0] | None = None

    @model_validator(mode="after")
    def no_partial_mask_policy(self):
        _validate_mask_fields(self)
        return self


ExecutableObject = Annotated[
    MarkObject | ConnectorObject | TextObject | VisualObject
    | GroupContainer | ClipContainer | MaskContainer,
    Field(discriminator="object_type"),
]


CompositionID = Annotated[str, Field(min_length=1, pattern=ILLUSTRATION_ID_PATTERN,
                                    json_schema_extra=ILLUSTRATION_ID_SCHEMA)]
CompositionParameterField = Literal[
    "text", "style.stroke", "style.fill", "style.text",
    "geometry.bounds.x", "geometry.bounds.y", "geometry.bounds.width", "geometry.bounds.height",
    "transform.position.x", "transform.position.y", "transform.scale_x", "transform.scale_y",
    "transform.rotation_degrees", "opacity", "visible",
]


def _composition_wire_value(value):
    """Only JSON wire shapes: never trust an already-constructed nested model."""
    if type(value) is dict and all(type(key) is str for key in value):
        for item in value.values():
            _composition_wire_value(item)
    elif type(value) is list:
        for item in value:
            _composition_wire_value(item)
    elif value is not None and type(value) not in (str, int, float, bool):
        raise ValueError("composition definitions require exact JSON wire values")


class CompositionParameterTarget(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    object_id: CompositionID
    field: CompositionParameterField


class CompositionParameterSpec(StrictModel):
    """All parameters are required at binding; no implicit defaults or expressions."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    parameter_id: CompositionID
    value_type: Literal["string", "number", "boolean"]
    targets: list[CompositionParameterTarget] = Field(min_length=1, max_length=4096)


def _composition_parameter_fields(obj):
    """Only fields consumed by the existing exact native/state owner.

    This table does not admit the object or waive token/resource/world checks.
    Substitution must revalidate the complete graph and owning native contract.
    In particular, pivot-only container bounds and endpoint-managed connector
    geometry are not advertised as editable drawing dimensions.
    """
    pose = {"transform.position.x", "transform.position.y", "transform.scale_x", "transform.scale_y",
            "transform.rotation_degrees", "opacity", "visible"}
    bounds = {"geometry.bounds.x", "geometry.bounds.y", "geometry.bounds.width", "geometry.bounds.height"}
    if isinstance(obj, ConnectorObject):
        return {"style.stroke", "opacity", "visible"}
    if isinstance(obj, ContainerObject):
        return pose | (bounds if type(obj) is ClipContainer else set())
    if isinstance(obj, MarkObject):
        fields = pose | {"style.stroke"}
        if obj.object_type in {"rectangle", "rounded_rectangle", "ellipse", "polygon"}:
            fields.add("style.fill")
        if obj.object_type not in {"freehand", "polygon"} and not obj.geometry.points:
            fields |= bounds
        return fields
    if isinstance(obj, TextObject):
        fields = pose | bounds
        if obj.object_type != "code":
            fields.add("style.text")
        if (obj.object_type in {"text", "callout"} and not obj.items
                and obj.code_payload is None and obj.structured_list is None):
            fields.add("text")
        if obj.object_type == "callout":
            fields |= {"style.stroke", "style.fill"}
        return fields
    fields = pose | bounds
    if obj.chart_payload is not None:
        fields |= {"style.stroke", "style.fill", "style.text"}
    elif obj.technical_frame is not None or obj.object_type == "evidence":
        fields |= {"style.stroke", "style.fill"}
    elif obj.object_type == "image" and (
            obj.image_placement is None or "rotate" not in obj.image_placement.allowed_transformations):
        fields.remove("transform.rotation_degrees")
    return fields


class CompositionDefinition(StrictModel):
    """Closed authored template, not an executable scene object or runtime rig.

    Board/beat/coverage IDs are definition-local context. Later explicit binding
    must map that context and every local object ID before ordinary graph paint.
    Arrays remain authored content; sibling paint order is still z/ID, not array
    order. Definitions contain no nested template references or external clips.
    """

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False, revalidate_instances="always")
    version: Literal["1.0.0"]
    definition_id: CompositionID
    revision: int = Field(ge=1)
    root_local_id: CompositionID
    template_board_id: CompositionID
    template_beat_id: CompositionID
    template_coverage_ids: list[CompositionID] = Field(min_length=1, max_length=4096)
    # Eager, real members all count against the existing one-board density cap.
    # Binding additionally checks the destination board's remaining capacity.
    objects: list[ExecutableObject] = Field(min_length=1, max_length=12, json_schema_extra={
        "allOf": [{"items": {"not": {"required": ["composition_binding"]}}}],
    })
    parameters: list[CompositionParameterSpec] = Field(max_length=4096)

    @model_validator(mode="wrap")
    @classmethod
    def exact_wire_document(cls, value, handler):
        if type(value) is not dict:
            raise ValueError("composition definition requires a JSON object")
        _composition_wire_value(value)
        rows = value.get("objects")
        if type(rows) is list and any(type(obj) is dict and "composition_binding" in obj for obj in rows):
            raise ValueError("composition definitions cannot contain a binding, including explicit null")
        return handler(value)

    @field_validator("objects", mode="before")
    @classmethod
    def exact_native_objects(cls, value):
        # Strictness on the new owner must also reach legacy nested numeric
        # models; otherwise bool is silently coerced to a valid float first.
        return TypeAdapter(list[ExecutableObject]).validate_python(value, strict=True)

    @model_validator(mode="after")
    def closed_graph_and_typed_parameters(self):
        objects = {obj.object_id: obj for obj in self.objects}
        if len(objects) != len(self.objects):
            raise ValueError("composition definition requires unique local object IDs")
        root = objects.get(self.root_local_id)
        if type(root) is not GroupContainer or root.parent_id is not None:
            raise ValueError("composition definition requires exactly one real root Group")
        coverage = set(self.template_coverage_ids)
        if len(coverage) != len(self.template_coverage_ids):
            raise ValueError("composition template coverage IDs must be unique")
        used_coverage = set()
        local_id = TypeAdapter(CompositionID)
        mask_sources = {obj.mask_source_object_id for obj in self.objects if isinstance(obj, MaskContainer)}
        for obj in self.objects:
            local_id.validate_python(obj.object_id, strict=True)
            used_coverage.update(obj.coverage_ids)
            if (obj.board_id != self.template_board_id or obj.beat_id != self.template_beat_id
                    or len(set(obj.coverage_ids)) != len(obj.coverage_ids)
                    or not set(obj.coverage_ids) <= coverage):
                raise ValueError("composition requires the exact declared local board/beat/coverage context")
            if obj.clip_id is not None or obj.object_type in {"composition", "instance"}:
                raise ValueError("composition external clip and nested template references remain closed")
            if obj.object_id != self.root_local_id:
                parent = objects.get(obj.parent_id)
                if not isinstance(parent, ContainerObject) or obj.object_id not in parent.child_ids:
                    raise ValueError("composition requires reciprocal complete local parent membership")
            if isinstance(obj, ContainerObject) and (
                    not obj.child_ids or len(set(obj.child_ids)) != len(obj.child_ids)
                    or any(key not in objects for key in obj.child_ids)):
                raise ValueError("composition requires nonempty unique known local children")
            if isinstance(obj, MaskContainer) and obj.mask_source_object_id is None:
                raise ValueError("composition requires a complete authored mask policy")
            _unique(obj.anchors, "anchor_id")
            if isinstance(obj, ConnectorObject):
                endpoints = (obj.source_object_id, obj.destination_object_id)
                if (any(key is not None and key not in objects for key in endpoints)
                        or any(key in mask_sources for key in endpoints if key is not None)
                        or obj.role == "semantic_connector" and obj.source_object_id is None):
                    raise ValueError("composition connector endpoints require real local non-mask sources")
                _check_anchor(obj.source_object_id, obj.source_anchor_id, objects)
                _check_anchor(obj.destination_object_id, obj.destination_anchor_id, objects)
        if used_coverage != coverage:
            raise ValueError("composition template coverage must be exactly used")
        _reject_parent_cycles(objects)
        _reject_container_cycles(objects)
        _validate_mask_layout(self.objects, objects)
        _validate_structured_lists(objects, semantic=False)
        _validate_technical_frames(objects, semantic=False)
        _validate_character_assemblies(objects, semantic=False)
        _validate_illustration_assemblies(objects, semantic=False)
        _callout_leader_owners(objects)
        _require_code_payloads(self.objects)
        _require_chart_payloads(self.objects)
        _unique(self.parameters, "parameter_id")
        targets = set()
        for parameter in self.parameters:
            for target in parameter.targets:
                pair = (target.object_id, target.field)
                obj = objects.get(target.object_id)
                expected_type = ("boolean" if target.field == "visible" else
                                 "string" if target.field == "text" or target.field.startswith("style.") else "number")
                if obj is None or pair in targets or parameter.value_type != expected_type:
                    raise ValueError("composition parameter targets must be unique local fields of the declared type")
                if (target.field not in _composition_parameter_fields(obj)
                        or target.object_id in mask_sources and target.field in {
                            "opacity", "visible", "style.stroke", "style.fill", "style.text"}):
                    raise ValueError("composition parameter field is not consumed by this exact native object")
                if target.field == "text" and (
                        type(obj) is not TextObject or obj.object_type not in {"text", "callout"}
                        or obj.code_payload is not None or obj.structured_list is not None or obj.items):
                    raise ValueError("composition text parameter requires ordinary authored text/callout content")
                targets.add(pair)
        return self


def composition_definition_digest(document: dict) -> str:
    """Revalidate exact wire content before canonical hashing; no trusted hash field."""
    if type(document) is not dict:
        raise ValueError("composition definition digest requires an exact JSON object")
    payload = CompositionDefinition.model_validate(document).model_dump(mode="json")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class _CompositionWireModel(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False, revalidate_instances="always")

    @model_validator(mode="wrap")
    @classmethod
    def exact_wire_document(cls, value, handler):
        if type(value) is not dict:
            raise ValueError("composition inputs require exact JSON objects")
        _composition_wire_value(value)
        return handler(value)


class CompositionStringValue(_CompositionWireModel):
    value_type: Literal["string"]
    value: str


class CompositionNumberValue(_CompositionWireModel):
    value_type: Literal["number"]
    value: float


class CompositionBooleanValue(_CompositionWireModel):
    value_type: Literal["boolean"]
    value: bool


CompositionScalarValue = Annotated[
    CompositionStringValue | CompositionNumberValue | CompositionBooleanValue,
    Field(discriminator="value_type"),
]


class CompositionParameterValue(_CompositionWireModel):
    parameter_id: CompositionID
    value: CompositionScalarValue


class CompositionOverride(_CompositionWireModel):
    target: CompositionParameterTarget
    value: CompositionScalarValue


class CompositionCoverageMapping(_CompositionWireModel):
    local_coverage_id: CompositionID
    coverage_id: CompositionID


class CompositionObjectMapping(_CompositionWireModel):
    local_object_id: CompositionID
    object_id: CompositionID


def composition_expanded_object_id(root_id: str, local_id: str) -> str:
    """Injective tuple encoding, preserving local lexical order within a root."""
    adapter = TypeAdapter(CompositionID)
    adapter.validate_python(root_id, strict=True)
    adapter.validate_python(local_id, strict=True)
    return f"composition-{len(root_id)}:{root_id}:{local_id}"


class CompositionInstanceSpec(_CompositionWireModel):
    """Explicit authoring input, NOT an executable binding or admission receipt."""

    version: Literal["1.0.0"]
    kind: Literal["composition", "instance"]
    definition: CompositionDefinition
    definition_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    root_object_id: CompositionID
    board_id: CompositionID
    beat_id: CompositionID
    root_parent_id: CompositionID | None
    root_z_index: int
    coverage_map: list[CompositionCoverageMapping] = Field(min_length=1, max_length=4096)
    object_map: list[CompositionObjectMapping] = Field(min_length=1, max_length=12)
    parameter_values: list[CompositionParameterValue] = Field(max_length=4096)
    overrides: list[CompositionOverride] = Field(max_length=4096)

    @model_validator(mode="after")
    def exact_definition_maps_values_and_overrides(self):
        definition = self.definition
        if self.definition_sha256 != composition_definition_digest(definition.model_dump(mode="json")):
            raise ValueError("composition instance requires the exact canonical definition hash")
        _unique(self.object_map, "local_object_id")
        _unique(self.object_map, "object_id")
        expected = {obj.object_id: self.root_object_id if obj.object_id == definition.root_local_id else
                    composition_expanded_object_id(self.root_object_id, obj.object_id) for obj in definition.objects}
        if {row.local_object_id: row.object_id for row in self.object_map} != expected:
            raise ValueError("composition instance requires the complete canonical expanded ID map")
        if self.root_parent_id in expected.values():
            raise ValueError("composition root parent must be outside its expansion")
        _unique(self.coverage_map, "local_coverage_id")
        _unique(self.coverage_map, "coverage_id")
        if {row.local_coverage_id for row in self.coverage_map} != set(definition.template_coverage_ids):
            raise ValueError("composition instance requires an exact one-to-one complete coverage map")
        _unique(self.parameter_values, "parameter_id")
        declarations = {row.parameter_id: row for row in definition.parameters}
        if {row.parameter_id for row in self.parameter_values} != declarations.keys():
            raise ValueError("composition instance must explicitly supply every and only declared parameter")
        for row in self.parameter_values:
            if row.value.value_type != declarations[row.parameter_id].value_type:
                raise ValueError("composition instance parameter value has the wrong declared scalar type")
        targets = {(row.object_id, row.field) for param in definition.parameters for row in param.targets}
        objects = {obj.object_id: obj for obj in definition.objects}
        mask_sources = {obj.mask_source_object_id for obj in definition.objects if isinstance(obj, MaskContainer)}
        for override in self.overrides:
            target = override.target
            pair = (target.object_id, target.field)
            obj = objects.get(target.object_id)
            expected_type = ("boolean" if target.field == "visible" else
                             "string" if target.field == "text" or target.field.startswith("style.") else "number")
            if (obj is None or pair in targets or override.value.value_type != expected_type
                    or target.field not in _composition_parameter_fields(obj)
                    or target.object_id in mask_sources and target.field in {
                        "opacity", "visible", "style.stroke", "style.fill", "style.text"}):
                raise ValueError("composition overrides require distinct applicable typed fields, never parameter conflicts")
            targets.add(pair)
        return self


def _composition_packet_digest(packet: dict) -> str:
    canonical = json.dumps(packet, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class CompositionExpansionMember(_CompositionWireModel):
    object_id: CompositionID
    initial_object_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    parent_id: CompositionID | None
    sibling_ordinal: int = Field(ge=0)


class CompositionBinding(_CompositionWireModel):
    """Initial receipt; actual complete-layout verification remains mandatory."""

    version: Literal["1.0.0"]
    instance: CompositionInstanceSpec
    members: list[CompositionExpansionMember] = Field(min_length=1, max_length=12)
    expansion_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def faithful_initial_member_receipts(self):
        from atme.render.v2_composition import composition_initial_members

        _unique(self.members, "object_id")
        root = next((row for row in self.members if row.object_id == self.instance.root_object_id), None)
        if root is None:
            raise ValueError("composition receipt omits its root")
        expected = composition_initial_members(self.instance.model_dump(mode="json"), root_ordinal=root.sibling_ordinal)
        if [row.model_dump(mode="json") for row in self.members] != expected:
            raise ValueError("composition member receipts change initial content, parent, order or membership")
        packet = self.model_dump(mode="json")
        del packet["expansion_sha256"]
        if self.expansion_sha256 != _composition_packet_digest(packet):
            raise ValueError("composition expansion receipt hash changes canonical spec or members")
        return self


GroupContainer.model_rebuild()
CompositionDefinition.model_rebuild()
CompositionInstanceSpec.model_rebuild()
CompositionBinding.model_rebuild()


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


class AnnotationPhase(StrictModel):
    object_id: str = Field(min_length=1)
    mode: Literal["draw", "write"]
    weight: int = Field(ge=1, le=10000)


class AnnotationPolicy(StrictModel):
    """Ordered construction of authored objects; never renderer-generated copy."""

    annotation_object_ids: list[str] = Field(min_length=1, max_length=32)
    leader_connector_id: str | None = Field(default=None, min_length=1)
    phases: list[AnnotationPhase] = Field(min_length=1, max_length=33)
    readable_hold_ms: int = Field(ge=1, le=60000)
    retention: Literal["retain"] = "retain"

    @model_validator(mode="after")
    def exact_phase_inventory(self):
        ids = self.annotation_object_ids + ([self.leader_connector_id] if self.leader_connector_id else [])
        phase_ids = [phase.object_id for phase in self.phases]
        if len(ids) != len(set(ids)) or len(phase_ids) != len(set(phase_ids)) or set(ids) != set(phase_ids):
            raise ValueError("annotation phases must construct every authored object exactly once")
        if self.leader_connector_id and next(
            phase.mode for phase in self.phases if phase.object_id == self.leader_connector_id
        ) != "draw":
            raise ValueError("annotation leader requires a draw phase")
        return self


class CountPolicy(StrictModel):
    text_object_id: str = Field(min_length=1)
    start_value: str = Field(min_length=1, max_length=64, pattern=r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?$")
    end_value: str = Field(min_length=1, max_length=64, pattern=r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?$")
    decimal_places: int = Field(ge=0, le=6, strict=True)
    rounding: Literal["half_even", "half_up", "half_down", "floor", "ceiling", "truncate"]
    step_count: int = Field(ge=1, le=4096, strict=True)
    grouping: Literal["none", "thousands"]
    unit: str = Field(max_length=32)
    unit_placement: Literal["none", "before", "after"]
    separator: str = Field(max_length=3)
    start_text: str = Field(min_length=1, max_length=128)
    end_text: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def exact_formatted_endpoints(self):
        validate_count_policy(self)
        return self


class StructuredListPhase(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    object_id: str = Field(min_length=1)
    weight: int = Field(ge=1, le=10000)


class StructuredListPolicy(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    version: Literal["1.0.0"]
    list_object_id: str = Field(min_length=1)
    container_group_id: str = Field(min_length=1)
    item_object_ids: list[str] = Field(min_length=1, max_length=256,
                                      json_schema_extra={"uniqueItems": True})
    phases: list[StructuredListPhase] = Field(min_length=1, max_length=256)
    expected_item_state_versions: dict[str, Annotated[int, Field(strict=True, ge=1)]]

    @model_validator(mode="after")
    def exact_item_phase_inventory(self):
        ids = self.item_object_ids
        if (len(set(ids)) != len(ids) or any(not key.strip() for key in ids)
                or not self.list_object_id.strip() or not self.container_group_id.strip()
                or self.list_object_id == self.container_group_id
                or {self.list_object_id, self.container_group_id}.intersection(ids)
                or [phase.object_id for phase in self.phases] != ids
                or set(self.expected_item_state_versions) != set(ids)):
            raise ValueError("structured list policy requires exact distinct item/phase/version inventory")
        return self


class TargetAction(ActionBase):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, json_schema_extra={
        "allOf": [{"if": {"required": ["structured_list_policy"],
                           "properties": {"structured_list_policy": {"type": "object"}}},
                   "then": {"required": ["easing", "expected_state"],
                       "properties": {"verb": {"const": "progressive_reveal"},
                       "easing": {"const": "linear"}, "expected_state": {"const": "hidden"},
                       "post_state": {"const": "visible"}, "annotation": {"type": "null"},
                       "annotation_policy": {"type": "null"}, "count_policy": {"type": "null"}}}}],
    })
    verb: Literal[
        "reveal", "write", "draw", "enter", "exit", "highlight", "dim", "isolate",
        "cross_out", "annotate", "count", "progressive_reveal",
    ]
    target_ids: list[str] = Field(min_length=1)
    annotation: str | None = None
    # Optional parsing preserves old bare annotate documents. New writes and
    # execution require explicit authored objects and ordered construction.
    annotation_policy: AnnotationPolicy | None = None
    count_policy: CountPolicy | None = None
    structured_list_policy: StructuredListPolicy | None = None

    @model_serializer(mode="wrap")
    def preserve_legacy_shape(self, handler):
        result = handler(self)
        if self.annotation_policy is None:
            result.pop("annotation_policy", None)
        if self.count_policy is None:
            result.pop("count_policy", None)
        if self.structured_list_policy is None:
            result.pop("structured_list_policy", None)
        return result

    @model_validator(mode="after")
    def exit_is_permanent_removal(self):
        if self.structured_list_policy is not None:
            _require_structured_list_contract(self)
        if self.annotation_policy is not None:
            _require_annotation_contract(self)
        if self.count_policy is not None:
            _require_count_contract(self)
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


class MorphPolicy(StrictModel):
    """Authored correspondence; the renderer never guesses how shapes match."""

    mapping: Literal["canonical_outline", "ordered_vertices", "matching_path_commands"]
    point_count: int | None = Field(default=None, ge=2, le=257)
    path_commands: list[Literal["M", "L", "Q", "C"]] | None = Field(
        default=None, min_length=2, max_length=256,
    )
    paint: Literal["shared_style"] = "shared_style"
    transforms: Literal["interpolate_all"] = "interpolate_all"

    @model_validator(mode="after")
    def mapping_parameters(self):
        if self.mapping == "ordered_vertices":
            if self.point_count is None or self.path_commands is not None:
                raise ValueError("ordered morph needs only an explicit point count")
        elif self.mapping == "matching_path_commands":
            if (self.point_count is not None or self.path_commands is None
                    or self.path_commands[0] != "M" or "M" in self.path_commands[1:]):
                raise ValueError("path morph needs one explicit continuous command sequence")
        elif self.point_count is not None or self.path_commands is not None:
            raise ValueError("canonical outline morph cannot carry ignored mapping parameters")
        return self


class ReplaceAction(ActionBase):
    verb: Literal["replace", "morph"]
    from_object_id: str
    to_object_id: str
    # Older 2.0.0 morph declarations remain loadable, but cannot execute or
    # pass a new storyboard write without a correspondence policy.
    morph_policy: MorphPolicy | None = None

    @model_validator(mode="after")
    def bounded_replace_semantics(self):
        if self.verb == "morph" and self.morph_policy is not None:
            _require_morph_contract(self)
        if self.verb == "replace":
            if self.morph_policy is not None:
                raise ValueError("replace cannot carry a morph policy")
            if self.from_object_id == self.to_object_id:
                raise ValueError("replace needs distinct source and destination objects")
            if self.expected_state is None:
                raise ValueError("replace needs a source expected_state")
            if self.post_state != "visible":
                raise ValueError("replace destination post_state must be visible")
        return self


class HierarchyPlacement(StrictModel):
    """An exact authored hierarchy node and local transform, not a destination hint."""

    object_id: str = Field(min_length=1)
    board_id: str = Field(min_length=1)
    parent_id: str | None
    sibling_ordinal: int = Field(ge=0, strict=True)
    local_transform: Transform


class HierarchyBasis(StrictModel):
    """Complete canonical layout inventory, including root and empty-parent order."""

    placements: list[HierarchyPlacement] = Field(min_length=1, max_length=4096)

    @model_validator(mode="after")
    def complete_canonical_topology(self):
        ids = [item.object_id for item in self.placements]
        if ids != sorted(set(ids)):
            raise ValueError("hierarchy basis needs unique canonical object-ID order")
        objects = {item.object_id: item for item in self.placements}
        siblings = {}
        for item in self.placements:
            siblings.setdefault((item.board_id, item.parent_id), []).append(item.sibling_ordinal)
            chain = {item.object_id}
            parent_id = item.parent_id
            while parent_id is not None:
                parent = objects.get(parent_id)
                if parent is None or parent.board_id != item.board_id or parent_id in chain:
                    raise ValueError("hierarchy basis needs acyclic same-board known parents")
                chain.add(parent_id)
                if len(chain) > 9:
                    raise ValueError("hierarchy basis exceeds eight ancestor levels")
                parent_id = parent.parent_id
        if any(sorted(ordinals) != list(range(len(ordinals))) for ordinals in siblings.values()):
            raise ValueError("hierarchy basis must encode complete parent-order permutations")
        return self

    def checksum(self) -> str:
        return hashlib.sha256(json.dumps(self.model_dump(mode="json"), sort_keys=True,
                                         separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


class ReturnHierarchyReceipt(StrictModel):
    """Compiler proof of one retained board; not semantic plan intent."""

    action_id: str = Field(min_length=1)
    destination_board_id: str = Field(min_length=1)
    destination_activation_id: str = Field(min_length=1)
    hierarchy_basis: HierarchyBasis
    hierarchy_basis_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def exact_board_basis(self):
        if (any(item.board_id != self.destination_board_id
                for item in self.hierarchy_basis.placements)
                or self.hierarchy_basis.checksum() != self.hierarchy_basis_sha256):
            raise ValueError("return hierarchy receipt needs one complete board and canonical hash")
        return self


class HierarchyTransitionPolicy(StrictModel):
    """Complete authored before/after receipt; no inferred membership or inverse."""

    member_root_ids: list[str] = Field(min_length=1, max_length=256)
    source_basis: HierarchyBasis
    destination_basis: HierarchyBasis
    source_basis_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    destination_basis_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    changed_object_ids: list[str] = Field(min_length=1, max_length=4096)
    preserve_world_transform: Literal[True]

    @model_validator(mode="after")
    def exact_basis_receipt(self):
        source = {item.object_id: item for item in self.source_basis.placements}
        destination = {item.object_id: item for item in self.destination_basis.placements}
        if (len(self.member_root_ids) != len(set(self.member_root_ids))
                or set(self.member_root_ids) - source.keys()
                or source.keys() != destination.keys()
                or self.changed_object_ids != sorted(set(self.changed_object_ids))
                or set(self.changed_object_ids) - source.keys()
                or self.source_basis_sha256 != self.source_basis.checksum()
                or self.destination_basis_sha256 != self.destination_basis.checksum()):
            raise ValueError("hierarchy policy needs exact inventories and canonical basis checksums")
        if any(source[key].board_id != destination[key].board_id for key in source):
            raise ValueError("hierarchy policy cannot change board ownership")
        return self


class GroupAction(ActionBase):
    verb: Literal["group", "ungroup"]
    target_ids: list[str] = Field(min_length=1)
    container_id: str | None = None
    # Bare legacy actions remain readable/hash-compatible, never executable.
    hierarchy_policy: HierarchyTransitionPolicy | None = None

    @model_serializer(mode="wrap")
    def preserve_legacy_shape(self, handler):
        result = handler(self)
        if self.hierarchy_policy is None:
            result.pop("hierarchy_policy", None)
        return result

    @model_validator(mode="after")
    def explicit_transition_semantics(self):
        if self.hierarchy_policy is not None:
            _require_hierarchy_contract(self)
        return self


SplitID = Annotated[str, Field(min_length=1, pattern=r"\S")]
SplitSHA256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class SplitPhase(StrictModel):
    start_tick: int = Field(ge=0, le=10000, strict=True)
    end_tick: int = Field(ge=0, le=10000, strict=True)
    easing: Literal["linear", "ease_in", "ease_out", "ease_in_out"]

    @model_validator(mode="after")
    def increasing_phase(self):
        if self.start_tick >= self.end_tick:
            raise ValueError("Split phase must have increasing ticks")
        return self


class SplitConstruction(StrictModel):
    mode: Literal["reveal", "draw", "write", "enter"]
    phase: SplitPhase
    enter_destination: Transform | None = None

    @model_validator(mode="after")
    def exact_transform_channel(self):
        if (self.mode == "enter") != (self.enter_destination is not None):
            raise ValueError("Split enter alone requires a construction destination")
        return self


class SplitMovement(StrictModel):
    phase: SplitPhase
    from_transform: Transform
    destination: Transform


class SplitCorrespondence(StrictModel):
    correspondence_id: SplitID
    source_object_id: SplitID
    source_content_sha256: SplitSHA256
    result_object_id: SplitID
    result_content_sha256: SplitSHA256
    relationship: Literal["authored_assertion"]
    statement: str = Field(min_length=1, max_length=512, pattern=r"\S")
    source_region: Bounds | None = None


class SplitAssetPin(StrictModel):
    asset_id: SplitID
    revision: int = Field(ge=1, strict=True)
    resource_uri: SplitID
    checksum_sha256: SplitSHA256


def _split_permission_digest(permissions: list[str]) -> str:
    # Ordered authority from the source snapshot, never a normalized set.
    packet = json.dumps(permissions, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(packet.encode("utf-8")).hexdigest()


class SplitEvidenceActivation(StrictModel):
    """Authored causal authority only; attestation needs the actual source context."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False,
                             revalidate_instances="always")
    result_object_id: SplitID
    beat_id: SplitID
    causal_action_id: SplitID
    intent: EvidenceIntent
    asset_pin: SplitAssetPin
    permission_sha256: SplitSHA256
    allowed_transformations: list[Literal[
        "crop", "scale", "rotate", "mask", "annotate", "color_treatment"
    ]] = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def exact_authority_payload(cls, value):
        return _evidence_annotation_payload(value, cls)

    @field_validator("intent", mode="before")
    @classmethod
    def exact_intent(cls, value):
        return _validated_split_evidence_intent(value)

    @field_validator("asset_pin", mode="before")
    @classmethod
    def exact_asset_pin(cls, value):
        return SplitAssetPin.model_validate(_evidence_annotation_payload(value, SplitAssetPin), strict=True)

    @model_validator(mode="after")
    def binds_source_authority(self):
        if (self.asset_pin.asset_id != self.intent.evidence_asset_id
                or self.permission_sha256 != _split_permission_digest(self.allowed_transformations)):
            raise ValueError("Split evidence activation changes its source or exact permission pin")
        return self


class SplitResult(StrictModel):
    object_id: SplitID
    correspondence_id: SplitID
    construction: SplitConstruction
    movement: SplitMovement | None = None
    destination: Transform
    post_state: SplitID
    evidence_activation: SplitEvidenceActivation | None = Field(default=None, json_schema_extra={"type": "object"})

    @field_validator("evidence_activation", mode="before")
    @classmethod
    def exact_activation(cls, value):
        if value is None:
            raise ValueError("Split evidence activation must be omitted or carry exact authored authority")
        return SplitEvidenceActivation.model_validate(
            _evidence_annotation_payload(value, SplitEvidenceActivation), strict=True)

    @model_serializer(mode="wrap")
    def preserve_legacy_result_shape(self, handler):
        result = handler(self)
        if self.evidence_activation is None:
            result.pop("evidence_activation", None)
        return result

    @model_validator(mode="after")
    def exact_destination_state(self):
        activation = self.evidence_activation
        if (activation is None and self.post_state != "visible"
                or activation is not None and (activation.result_object_id != self.object_id
                    or activation.intent.destination_state != self.post_state)):
            raise ValueError("Split result needs its exact authored evidence destination or ordinary visible state")
        return self


class SplitPlacement(StrictModel):
    object_id: SplitID
    parent_id: SplitID | None
    sibling_ordinal: int = Field(ge=0, strict=True)
    local_content_bounds: Bounds
    local_transform: Transform
    world_matrix: tuple[float, float, float, float, float, float]
    world_corners: tuple[Point, Point, Point, Point]
    world_bounds: Bounds
    state: SplitID
    local_visibility: bool = Field(strict=True)
    effective_visibility: bool = Field(strict=True)
    reveal: float = Field(ge=0, le=1)
    local_opacity: float = Field(ge=0, le=1)
    state_version: int = Field(ge=1, strict=True)
    content_sha256: SplitSHA256


class SplitClosure(StrictModel):
    root_id: SplitID
    owned_ids: list[SplitID] = Field(min_length=1, max_length=4096)

    @model_validator(mode="after")
    def owns_root_once(self):
        if self.root_id not in self.owned_ids or len(set(self.owned_ids)) != len(self.owned_ids):
            raise ValueError("Split closure must own its root and each object exactly once")
        return self


class SplitReadDependency(StrictModel):
    kind: Literal["ancestor", "aperture", "mask_source", "connector_anchor", "annotation_anchor"]
    object_ids: list[SplitID] = Field(min_length=1, max_length=4096)

    @model_validator(mode="after")
    def unique_ids(self):
        if len(self.object_ids) != len(set(self.object_ids)):
            raise ValueError("Split read dependency IDs must be unique")
        return self


class SplitBasis(StrictModel):
    source_closure: SplitClosure
    result_closures: list[SplitClosure] = Field(min_length=2, max_length=256)
    placements: list[SplitPlacement] = Field(min_length=3, max_length=4096)
    read_dependencies: list[SplitReadDependency] = Field(max_length=4096)
    asset_pins: list[SplitAssetPin] = Field(max_length=4096)
    style_sha256: SplitSHA256
    registry_sha256: SplitSHA256

    @model_validator(mode="after")
    def exact_inventory(self):
        ids = [item.object_id for item in self.placements]
        if ids != sorted(set(ids)):
            raise ValueError("Split placements need unique canonical ID order")
        owned = [key for closure in [self.source_closure, *self.result_closures]
                 for key in closure.owned_ids]
        if len(owned) != len(set(owned)):
            raise ValueError("Split owned closures must be disjoint")
        bound = set(owned)
        dependencies = set()
        for dependency in self.read_dependencies:
            key = (dependency.kind, tuple(dependency.object_ids))
            if key in dependencies:
                raise ValueError("Split read dependency rows must be unique")
            dependencies.add(key)
            bound.update(dependency.object_ids)
        if len(bound) > 4096 or bound != set(ids):
            raise ValueError("Split basis must bind exactly all owned and read objects, at most 4096")
        pins = [pin.asset_id for pin in self.asset_pins]
        if pins != sorted(set(pins)):
            raise ValueError("Split asset pins need unique canonical ID order")
        return self


def _split_pose_key(transform: Transform) -> tuple[float, ...]:
    # Numeric equality at v2_world/v2_svg's existing four-decimal precision.
    # World range and collapsed-scale validity still require actual capture;
    # this contract check does not admit a transform to the renderer.
    return tuple(round(value, 4) for value in (
        transform.position.x, transform.position.y, transform.scale_x, transform.scale_y,
        transform.rotation_degrees, transform.origin.x, transform.origin.y))


def _split_packet_digest(packet: dict) -> str:
    """Canonical Split packet identity; only placement channels are quantized.

    Keep this contract-only helper independent of runtime imports so parsed
    policies and runtime receipts cannot disagree on pose equivalence.
    """
    pose_fields = {"local_transform", "from_transform", "destination", "enter_destination",
                   "world_matrix", "world_corners", "world_bounds"}

    def canonical(value, pose=False):
        if isinstance(value, dict):
            return {key: canonical(item, pose or key in pose_fields) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [canonical(item, pose) for item in value]
        if pose and type(value) in (int, float):
            number = float(f"{value:.4f}")
            return number if number else 0.0
        return value

    encoded = json.dumps(canonical(packet), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class SplitPolicy(StrictModel):
    source_object_id: SplitID
    parent_policy: Literal["common_parent", "authored_distinct_parents"]
    source_exit: SplitPhase
    results: list[SplitResult] = Field(min_length=2, max_length=256)
    correspondences: list[SplitCorrespondence] = Field(min_length=2, max_length=256)
    source_basis: SplitBasis
    source_basis_sha256: SplitSHA256

    @model_validator(mode="after")
    def exact_authored_participants(self):
        result_ids = [result.object_id for result in self.results]
        correspondence_ids = [item.correspondence_id for item in self.correspondences]
        if (len(result_ids) != len(set(result_ids)) or self.source_object_id in result_ids
                or len(correspondence_ids) != len(set(correspondence_ids))
                or [item.result_object_id for item in self.correspondences] != result_ids
                or [item.correspondence_id for item in self.results] != correspondence_ids
                or any(item.source_object_id != self.source_object_id for item in self.correspondences)
                or self.source_basis.source_closure.root_id != self.source_object_id
                or [item.root_id for item in self.source_basis.result_closures] != result_ids):
            raise ValueError("Split needs exact ordered source/result/correspondence inventories")
        if _split_packet_digest(self.source_basis.model_dump(mode="json")) != self.source_basis_sha256:
            raise ValueError("Split needs the canonical source basis checksum")
        placements = {item.object_id: item for item in self.source_basis.placements}
        source = placements[self.source_object_id]
        starts = [result.construction.phase.start_tick for result in self.results]
        if starts != sorted(starts):
            raise ValueError("Split construction starts must follow authored result order")
        for result, correspondence in zip(self.results, self.correspondences, strict=True):
            placement = placements[result.object_id]
            activation = result.evidence_activation
            if activation is not None:
                pins = {pin.asset_id: pin for pin in self.source_basis.asset_pins}
                if (activation.asset_pin.asset_id not in pins
                        or activation.asset_pin.model_dump(mode="json")
                        != pins[activation.asset_pin.asset_id].model_dump(mode="json")):
                    raise ValueError("Split evidence activation must bind its exact captured asset pin")
            if (correspondence.source_content_sha256 != source.content_sha256
                    or correspondence.result_content_sha256 != placement.content_sha256):
                raise ValueError("Split correspondence must bind captured content digests")
            if self.parent_policy == "common_parent" and placement.parent_id != source.parent_id:
                raise ValueError("Split common-parent roots must share their captured parent")
            region = correspondence.source_region
            bounds = source.local_content_bounds
            if region is not None and (region.x < bounds.x or region.y < bounds.y
                    or region.x + region.width > bounds.x + bounds.width
                    or region.y + region.height > bounds.y + bounds.height):
                raise ValueError("Split correspondence region must fit source local content bounds")
            construction = result.construction
            origin = construction.enter_destination or placement.local_transform
            movement = result.movement
            if movement is not None:
                earliest = (construction.phase.end_tick if construction.mode == "enter"
                            else construction.phase.start_tick)
                if (movement.phase.start_tick < earliest
                        or _split_pose_key(movement.from_transform) != _split_pose_key(origin)):
                    raise ValueError("Split movement must continue construction without channel overlap or jump")
            final = movement.destination if movement is not None else origin
            if _split_pose_key(final) != _split_pose_key(result.destination):
                raise ValueError("Split final destination must match authored phase endpoints")
        _split_logical_write_owners(self)
        return self


def _split_logical_write_owners(policy: SplitPolicy) -> dict[str, str]:
    """Authored logical writes, never fabricated physical descendants.

    Dependency placements authenticate these participants; ownership comes only
    from the result's annotation policy. Targets and ancestry stay read-only.
    """
    physical = {key for closure in [policy.source_basis.source_closure, *policy.source_basis.result_closures]
                for key in closure.owned_ids}
    anchors = {key for row in policy.source_basis.read_dependencies if row.kind == "annotation_anchor"
               for key in row.object_ids}
    owners = {}
    for result in policy.results:
        activation = result.evidence_activation
        annotation = activation.intent.annotation_policy if activation is not None else None
        if annotation is None:
            continue
        if activation.intent.annotation_target_id not in anchors:
            raise ValueError("Split logical annotation must bind its annotation target as annotation_anchor")
        for key in _annotation_policy_object_ids(annotation):
            if key in physical or key in owners:
                raise ValueError("Split logical annotation needs one owner disjoint from physical closures")
            if key not in anchors:
                raise ValueError("Split logical annotation must bind its annotation_anchor placement")
            owners[key] = result.object_id
    return owners


class ResolvedSplitEvidenceWindow(StrictModel):
    """Resolved syntax; the timeline rederives phase times and real treatment SHA."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False,
                             revalidate_instances="always")
    result_object_id: SplitID
    treatment_sha256: SplitSHA256
    construction_complete_ms: int = Field(ge=0, strict=True)
    movement_complete_ms: int = Field(ge=0, strict=True)
    readable_hold_start_ms: int = Field(ge=0, strict=True)
    readable_hold_end_ms: int = Field(gt=0, strict=True)

    @model_validator(mode="before")
    @classmethod
    def exact_window_payload(cls, value):
        return _evidence_annotation_payload(value, cls)

    @model_validator(mode="after")
    def readable_window(self):
        if (self.readable_hold_start_ms < max(self.construction_complete_ms, self.movement_complete_ms)
                or self.readable_hold_end_ms <= self.readable_hold_start_ms):
            raise ValueError("Split evidence hold must follow both completed phases and have positive duration")
        return self


class SplitCompletionReceipt(StrictModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, revalidate_instances="always")

    source_basis_sha256: SplitSHA256
    policy_sha256: SplitSHA256
    placements: list[SplitPlacement] = Field(min_length=3, max_length=4096)
    read_dependencies: list[SplitReadDependency] = Field(max_length=4096)
    asset_pins: list[SplitAssetPin] = Field(max_length=4096)
    style_sha256: SplitSHA256
    registry_sha256: SplitSHA256
    completion_sha256: SplitSHA256
    evidence_windows: list[ResolvedSplitEvidenceWindow] | None = Field(
        default=None, min_length=1, max_length=256, json_schema_extra={"type": "array"})

    @model_validator(mode="before")
    @classmethod
    def exact_completion_payload(cls, value):
        payload = _evidence_annotation_payload(value, cls)
        if (type(value) is cls and payload.get("evidence_windows") is None
                and "evidence_windows" not in value.model_fields_set):
            payload.pop("evidence_windows")
        return payload

    @field_validator("evidence_windows", mode="before")
    @classmethod
    def exact_evidence_windows(cls, value):
        return _validated_split_evidence_windows(value)

    @model_serializer(mode="wrap")
    def preserve_legacy_completion_shape(self, handler):
        result = handler(self)
        if self.evidence_windows is None:
            result.pop("evidence_windows", None)
        return result

    @model_validator(mode="after")
    def checksum_and_order(self):
        ids = [item.object_id for item in self.placements]
        if ids != sorted(set(ids)):
            raise ValueError("Split completion needs unique canonical placement order")
        packet = self.model_dump(mode="json", exclude={"completion_sha256"})
        if _split_packet_digest(packet) != self.completion_sha256:
            raise ValueError("Split completion checksum does not match its packet")
        return self


def _validated_split_evidence_windows(value):
    if type(value) is not list or not 1 <= len(value) <= 256:
        raise ValueError("Split evidence windows must be omitted or an exact nonempty list")
    return [ResolvedSplitEvidenceWindow.model_validate(
        _evidence_annotation_payload(item, ResolvedSplitEvidenceWindow), strict=True) for item in value]


def _split_expected_completion(policy: SplitPolicy) -> dict:
    """Derive packet consistency, not proof of the live capture's authenticity.

    Chronological capture must independently bind the source basis before any
    runtime admission. Use the existing affine implementation, never caller
    supplied final world matrices.
    """
    from types import SimpleNamespace

    from atme.render.v2_world import Affine, _q, local_matrix

    basis = policy.source_basis
    rows = {row.object_id: row.model_copy(deep=True) for row in basis.placements}
    source = rows[policy.source_object_id]
    source.state = "removed"
    source.local_visibility = False
    source.local_opacity = 0.0
    source.reveal = 0.0
    source.state_version += 1
    for result in policy.results:
        row = rows[result.object_id]
        row.state = result.post_state
        row.local_visibility = True
        row.reveal = 1.0
        row.local_transform = result.destination.model_copy(deep=True)
        row.state_version += 1
    logical = _split_logical_write_owners(policy)
    for key in logical:
        row = rows[key]
        row.state = "visible"
        row.local_visibility = True
        row.reveal = 1.0
        row.state_version += 1
    owned = {key for closure in [basis.source_closure, *basis.result_closures]
             for key in closure.owned_ids} | logical.keys()
    matrices = {}
    visibility = {}

    def derive(object_id, ancestors=()):
        if object_id in matrices:
            return matrices[object_id]
        if object_id in ancestors or len(ancestors) > 8 or object_id not in rows:
            raise ValueError("Split completion requires closed acyclic parent placement inventory")
        row = rows[object_id]
        parent = row.parent_id
        parent_matrix = derive(parent, (*ancestors, object_id)) if parent is not None else Affine()
        shape = SimpleNamespace(geometry=SimpleNamespace(bounds=row.local_content_bounds))
        matrix = parent_matrix @ local_matrix(shape, row.local_transform)
        matrices[object_id] = matrix
        visibility[object_id] = row.local_visibility and (
            parent is None or visibility[parent] and rows[parent].local_opacity > 0)
        if object_id in owned:
            row.effective_visibility = visibility[object_id]
        row.world_matrix = (matrix.a, matrix.b, matrix.c, matrix.d, matrix.e, matrix.f)
        bounds = row.local_content_bounds
        x, y, width, height = map(_q, (bounds.x, bounds.y, bounds.width, bounds.height))
        corners = [matrix.point(px, py) for px, py in (
            (x, y), (x + width, y), (x + width, y + height), (x, y + height))]
        row.world_corners = tuple(Point(x=px, y=py) for px, py in corners)
        left, top = min(px for px, _ in corners), min(py for _, py in corners)
        row.world_bounds = Bounds(x=left, y=top,
            width=max(px for px, _ in corners) - left,
            height=max(py for _, py in corners) - top)
        return matrix

    for object_id in sorted(rows):
        derive(object_id)
    return {
        "source_basis_sha256": _split_packet_digest(basis.model_dump(mode="json")),
        "policy_sha256": _split_packet_digest(policy.model_dump(mode="json")),
        "placements": [rows[key].model_dump(mode="json") for key in sorted(rows)],
        "read_dependencies": [item.model_dump(mode="json") for item in basis.read_dependencies],
        "asset_pins": [item.model_dump(mode="json") for item in basis.asset_pins],
        "style_sha256": basis.style_sha256, "registry_sha256": basis.registry_sha256,
    }


class SplitAction(ActionBase):
    verb: Literal["split"]
    target_ids: list[str] = Field(min_length=1)
    container_id: str | None = None
    hierarchy_policy: None = None
    split_policy: SplitPolicy | None = None

    @model_serializer(mode="wrap")
    def preserve_legacy_shape(self, handler):
        result = handler(self)
        result.pop("hierarchy_policy", None)
        if self.split_policy is None:
            result.pop("split_policy", None)
        return result

    @model_validator(mode="after")
    def explicit_split_semantics(self):
        if self.split_policy is not None:
            source = next(item for item in self.split_policy.source_basis.placements
                          if item.object_id == self.split_policy.source_object_id)
            if (self.target_ids != [source.object_id] or self.container_id is not None
                    or not self.expected_state or self.expected_state != source.state
                    or self.post_state != "removed" or self.easing != "linear"):
                raise ValueError("Split needs one captured source, removed post-state and linear outer easing")
            for result in self.split_policy.results:
                activation = result.evidence_activation
                if activation is not None and (
                        activation.causal_action_id != self.action_id
                        or activation.intent.destination_board_id != self.board_id):
                    raise ValueError("Split evidence activation must name its actual causal action and board")
        return self


class EvidenceAction(ActionBase):
    verb: Literal["insert_evidence", "return_board"]
    evidence_asset_id: str | None = None
    # Optional only so older 2.0.0 documents remain loadable. New writes and
    # frame execution require an exact object binding for insert_evidence.
    target_object_id: str | None = None
    destination_board_id: str
    destination_state: str
    # A return is an authored cut to a previously activated board, not a
    # request to invent or reset its retained object state. Optional parsing
    # preserves older 2.0.0 documents; new writes and execution require all.
    source_board_id: str | None = None
    source_activation_id: str | None = None
    prior_destination_activation_id: str | None = None
    destination_activation_id: str | None = None
    expected_object_states: dict[str, str] | None = None
    expected_object_state_versions: dict[str, int] | None = None


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
    TargetAction | TransformAction | ConnectionAction | ReplaceAction | GroupAction | SplitAction
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
    board_id: str
    beat_id: str
    semantic_role: str
    description: str
    asset_id: str | None = None
    initial_state: str
    coverage_ids: list[str] = Field(min_length=1)


class SemanticStandardObjectSpec(SemanticObjectSpec):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, json_schema_extra={
        "allOf": [{"if": {"required": ["child_ids"], "properties": {"child_ids": {"type": "array"}}},
                   "then": {"anyOf": [
                       {"properties": {"object_type": {"enum": ["group", "clip"]}}},
                       {"required": ["composition_binding"], "properties": {
                           "object_type": {"enum": ["composition", "instance"]},
                           "composition_binding": {"type": "object"}}}]}},
                  {"if": {"required": ["composition_binding"],
                          "properties": {"composition_binding": {"type": "object"}}},
                   "then": {"required": ["child_ids"], "properties": {
                       "object_type": {"enum": ["composition", "instance"]}, "child_ids": {"type": "array"}}}},
                  {"if": {"required": ["structured_list"],
                          "properties": {"structured_list": {"type": "object"}}},
                   "then": {"properties": {"object_type": {"const": "list"}}}},
                  REGISTRY_BINDING_SCHEMA, *TECHNICAL_FRAME_SCHEMA, CHARACTER_ASSEMBLY_SCHEMA,
                  ILLUSTRATION_ASSEMBLY_SCHEMA, EXCLUSIVE_ASSEMBLY_OWNER_SCHEMA, CHART_PAYLOAD_SCHEMA,
                  IMAGE_PLACEMENT_SCHEMA, *MEDIA_PLAYBACK_SCHEMA, CONNECTOR_BINDING_SCHEMA],
    })
    object_type: Literal[
        "freehand", "line", "arrow", "rectangle", "rounded_rectangle", "ellipse",
        "polygon", "bracket", "underline", "highlight", "callout", "text", "list",
        "icon", "pictogram", "character", "image", "evidence", "chart", "comparison",
        "browser", "application", "terminal", "code", "document", "device", "server",
        "database", "folder", "network", "group", "clip", "composition", "instance",
        "video", "presenter", "screen_recording",
    ]
    code_payload: CodePayload | None = None
    callout_binding: CalloutBinding | None = None
    structured_list: StructuredListPayload | None = None
    registry_binding: RegistryBinding | None = None
    technical_frame: TechnicalFrameBinding | None = None
    character_assembly: CharacterAssemblyBinding | None = None
    illustration_assembly: IllustrationAssemblyBinding | None = None
    chart_payload: ChartPayload | None = None
    composition_binding: CompositionBinding | None = None
    image_placement: ImagePlacement | None = None
    media_playback: MediaPlayback | None = None
    connector_binding: ConnectorBinding | None = None
    # An authored external aperture read, never an ownership/parent edge.
    clip_id: str | None = Field(default=None, min_length=1, pattern=r"\S")
    # Explicit initial membership only. Absence preserves every legacy plan.
    child_ids: list[str] | None = Field(default=None, min_length=1, max_length=4096,
                                       json_schema_extra={"uniqueItems": True})

    @field_validator("connector_binding", mode="before")
    @classmethod
    def explicit_connector_authority(cls, value):
        if value is None:
            raise ValueError("connector_binding must be omitted or carry exact semantic authority")
        if type(value) not in (dict, ConnectorBinding):
            raise ValueError("connector_binding requires an exact binding payload")
        if type(value) is ConnectorBinding:
            present = value.model_fields_set
            fields = ConnectorBinding.model_fields
            required = {key for key, field in fields.items() if field.is_required()}
            if type(present) is not set or not present <= fields.keys() or not required <= present:
                raise ValueError("connector_binding needs its exact explicit required-field inventory")
            try:
                # Preserve presence, not serializer output: explicit null must
                # reject, while a genuinely omitted optional point stays absent.
                return {key: getattr(value, key) for key in present}
            except AttributeError as exc:
                raise ValueError("connector_binding is missing an explicitly declared field") from exc
        return value

    @model_serializer(mode="wrap")
    def preserve_legacy_code_shape(self, handler):
        result = handler(self)
        if self.connector_binding is None:
            result.pop("connector_binding", None)
        if self.media_playback is None:
            result.pop("media_playback", None)
        if self.image_placement is None:
            result.pop("image_placement", None)
        if self.code_payload is None:
            result.pop("code_payload", None)
        if self.callout_binding is None:
            result.pop("callout_binding", None)
        if self.structured_list is None:
            result.pop("structured_list", None)
        if self.registry_binding is None:
            result.pop("registry_binding", None)
        if self.technical_frame is None:
            result.pop("technical_frame", None)
        if self.character_assembly is None:
            result.pop("character_assembly", None)
        if self.illustration_assembly is None:
            result.pop("illustration_assembly", None)
        if self.chart_payload is None:
            result.pop("chart_payload", None)
        if self.child_ids is None:
            result.pop("child_ids", None)
        if self.composition_binding is None:
            result.pop("composition_binding", None)
        if self.clip_id is None:
            result.pop("clip_id", None)
        return result

    @model_validator(mode="after")
    def code_payload_owner(self):
        if self.connector_binding is not None and (
                self.object_type not in {"arrow", "network"}
                or self.object_type == "network" and self.connector_binding.role != "semantic_connector"):
            raise ValueError("connector_binding belongs only to its exact arrow/network relationship")
        _validate_media_playback_owner(self)
        _validate_image_placement_owner(self)
        _validate_chart_owner(self)
        _validate_technical_frame_owner(self)
        if self.composition_binding is not None:
            from atme.render.v2_composition import materialize_composition

            instance = self.composition_binding.instance
            root = next(obj for obj in materialize_composition(instance.model_dump(mode="json"))
                        if obj.object_id == instance.root_object_id)
            if (self.object_type != instance.kind or self.object_id != instance.root_object_id
                    or self.child_ids != root.child_ids):
                raise ValueError("semantic composition requires its exact kind, root and direct expanded children")
        if self.character_assembly is not None and self.object_type != "group":
            raise ValueError("character_assembly belongs only to its real authored Group")
        if self.illustration_assembly is not None and (
                self.object_type != "group" or self.character_assembly is not None):
            raise ValueError("illustration_assembly belongs only to its distinct real authored Group")
        if self.registry_binding is not None and self.object_type not in REGISTRY_BOUND_OBJECT_TYPES:
            raise ValueError("registry_binding requires a supported registry-backed object")
        if self.structured_list is not None and (
            self.object_type != "list" or self.object_id == self.structured_list.container_group_id
            or self.object_id in self.structured_list.item_object_ids
        ):
            raise ValueError("structured_list belongs only to its distinct authored list heading")
        if self.child_ids is not None and (
            (self.object_type not in {"group", "clip"} and self.composition_binding is None)
            or len(set(self.child_ids)) != len(self.child_ids)
            or self.object_id in self.child_ids or any(not key.strip() for key in self.child_ids)
        ):
            raise ValueError("semantic child_ids require unique non-self authored group membership")
        if self.code_payload is not None and self.object_type != "code":
            raise ValueError("code_payload belongs only to its authored code object")
        if self.callout_binding is not None and (
            self.object_type != "callout"
            or self.object_id in {self.callout_binding.leader_connector_id, self.callout_binding.target_object_id}
        ):
            raise ValueError("callout_binding belongs only to its distinct authored callout object")
        return self


class SemanticMaskObjectSpec(SemanticObjectSpec):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False,
                              json_schema_extra=MASK_SCHEMA_COMPATIBILITY)
    object_type: Literal["mask"]
    mask_mode: Literal["alpha"] | None = None
    mask_source_object_id: str | None = Field(default=None, min_length=1)
    mask_coordinate_space: Literal["parent_local"] | None = None
    invert: Literal[False] | None = None
    feather_px: Literal[0] | None = None
    child_ids: list[str] | None = Field(default=None, min_length=1, max_length=4096,
                                       json_schema_extra={"uniqueItems": True})

    @model_serializer(mode="wrap")
    def preserve_legacy_membership_shape(self, handler):
        result = handler(self)
        if self.child_ids is None:
            result.pop("child_ids", None)
        return result

    @model_validator(mode="after")
    def no_partial_mask_policy(self):
        _validate_mask_fields(self)
        if self.child_ids is not None and (
                len(set(self.child_ids)) != len(self.child_ids) or self.object_id in self.child_ids
                or any(not key.strip() for key in self.child_ids)
                or self.mask_source_object_id in self.child_ids):
            raise ValueError("semantic mask source must remain outside unique non-self authored children")
        return self


SemanticObject = Annotated[
    SemanticStandardObjectSpec | SemanticMaskObjectSpec,
    Field(discriminator="object_type"),
]


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


def _evidence_annotation_payload(value, model):
    """Strict raw revalidation at the evidence boundary, not a general alias."""
    if type(value) is model:
        fields = set(model.model_fields)
        required = {key for key, field in model.model_fields.items() if field.is_required()}
        if (set(value.__dict__) != fields or value.model_extra
                or not value.model_fields_set.issubset(fields)
                or not required.issubset(value.model_fields_set)):
            raise ValueError("evidence annotation needs exact explicitly declared authority fields")
        return dict(value.__dict__)
    if type(value) is not dict:
        raise ValueError("evidence annotation requires exact policy/phase payload types")
    return dict(value)


def _validated_evidence_annotation_policy(value):
    payload = _evidence_annotation_payload(value, AnnotationPolicy)
    if type(payload.get("phases")) is list:
        payload["phases"] = [_evidence_annotation_payload(phase, AnnotationPhase) for phase in payload["phases"]]
    return AnnotationPolicy.model_validate(payload, strict=True)


class EvidenceIntent(StrictModel):
    claim_id: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    evidence_asset_id: str = Field(min_length=1)
    crop: Bounds
    focus_region: Bounds
    mask_object_id: str | None = None
    darkening: float = Field(ge=0, le=1)
    source_label: str = Field(min_length=1)
    annotation: str | None = None
    annotation_target_id: str | None = None
    annotation_omission_reason: str | None = None
    annotation_policy: AnnotationPolicy | None = Field(default=None, json_schema_extra={"type": "object"})
    readable_hold_intent_ms: int = Field(gt=0)
    destination_board_id: str = Field(min_length=1)
    destination_state: str = Field(min_length=1)
    provenance_verified: bool
    checksum_verified: bool

    @field_validator("annotation_policy", mode="before")
    @classmethod
    def exact_authored_annotation_policy(cls, value):
        if value is None:
            raise ValueError("evidence annotation_policy must be omitted or carry authored authority")
        return _validated_evidence_annotation_policy(value)

    @model_serializer(mode="wrap")
    def preserve_legacy_annotation_shape(self, handler):
        result = handler(self)
        if self.annotation_policy is None:
            result.pop("annotation_policy", None)
        return result

    @model_validator(mode="after")
    def annotation_is_explained(self):
        if (not self.claim_id.strip() or not self.claim.strip()
                or not self.source_label.strip()
                or not self.destination_board_id.strip()
                or not self.destination_state.strip()):
            raise ValueError("evidence claim, source label, and destination must be readable")
        if self.annotation is not None and not self.annotation.strip():
            raise ValueError("evidence annotation cannot be blank")
        if (self.annotation_omission_reason is not None
                and not self.annotation_omission_reason.strip()):
            raise ValueError("evidence annotation omission reason cannot be blank")
        if self.annotation is None:
            if self.annotation_target_id is not None or not self.annotation_omission_reason:
                raise ValueError("evidence without annotation needs only an omission reason")
        elif not self.annotation_target_id or self.annotation_omission_reason is not None:
            raise ValueError("evidence annotation requires a target and no omission reason")
        if self.annotation_policy is None:
            if "annotation_policy" in self.model_fields_set:
                raise ValueError("evidence annotation_policy cannot explicitly be null")
        else:
            # Model instances can arrive through a parent or model_construct;
            # never let that skip strict revalidation of the new authority.
            if type(self) is not EvidenceIntent or type(self.annotation_policy) is not AnnotationPolicy:
                raise ValueError("evidence annotation needs exact typed intent and policy authority")
            policy = _validated_evidence_annotation_policy(self.annotation_policy)
            if (self.annotation is None or not policy.leader_connector_id
                    or policy.readable_hold_ms != self.readable_hold_intent_ms):
                raise ValueError("evidence annotation needs text, an authored leader and one matching hold duration")
        return self


def _validated_split_evidence_intent(value):
    payload = _evidence_annotation_payload(value, EvidenceIntent)
    # Authenticate typed nested source geometry before strict reconstruction.
    for key in ("crop", "focus_region"):
        if key in payload:
            payload[key] = _evidence_annotation_payload(payload[key], Bounds)
    if (type(value) is EvidenceIntent and payload.get("annotation_policy") is None
            and "annotation_policy" not in value.model_fields_set):
        payload.pop("annotation_policy")
    return EvidenceIntent.model_validate(payload, strict=True)


class EvidenceTreatment(StrictModel):
    """Exact forensic intent preserved across plan, layout and timing stages."""

    beat_id: str = Field(min_length=1)
    object_id: str = Field(min_length=1)
    action_id: str = Field(min_length=1)
    asset_revision: int = Field(ge=1)
    asset_checksum_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    asset_managed_ref: str = Field(min_length=1)
    asset_width: int = Field(gt=0)
    asset_height: int = Field(gt=0)
    asset_provenance: Provenance
    allowed_transformations: list[Literal[
        "crop", "scale", "rotate", "mask", "annotate", "color_treatment"
    ]]
    intent: EvidenceIntent

    @model_validator(mode="after")
    def bounded_source_geometry(self):
        if (self.intent.annotation_policy is not None
                and self.intent.annotation_target_id == self.object_id):
            raise ValueError("self-target evidence must preserve its inline annotation without an authored policy")
        crop = self.intent.crop
        focus = self.intent.focus_region
        if any(not float(value).is_integer() for bounds in (crop, focus)
               for value in (bounds.x, bounds.y, bounds.width, bounds.height)):
            raise ValueError("evidence crop and focus require whole source pixels")
        if (crop.x < 0 or crop.y < 0
                or crop.x + crop.width > self.asset_width
                or crop.y + crop.height > self.asset_height):
            raise ValueError("evidence crop must fit the immutable source pixels")
        if (focus.x < crop.x or focus.y < crop.y
                or focus.x + focus.width > crop.x + crop.width
                or focus.y + focus.height > crop.y + crop.height):
            raise ValueError("evidence focus must fit inside the declared crop")
        if self.asset_provenance.category != "external_evidence":
            raise ValueError("evidence needs external-evidence provenance")
        if (not self.asset_provenance.fabrication_prohibited
                or self.asset_provenance.originality_status != "reference_only"):
            raise ValueError("evidence source must prohibit fabrication and remain reference-only")
        if (not self.asset_provenance.source_uri
                or not self.asset_provenance.source_uri.strip()
                or self.asset_provenance.license_status == "unresolved"):
            raise ValueError("evidence needs a source URI and resolved license")
        if self.asset_provenance.checksum_sha256 != self.asset_checksum_sha256:
            raise ValueError("evidence provenance checksum must match the asset")
        if not self.intent.provenance_verified or not self.intent.checksum_verified:
            raise ValueError("evidence provenance and source checksum must be verified")
        permitted = set(self.allowed_transformations)
        required = {"crop", "scale"}
        if self.intent.annotation is not None:
            required.add("annotate")
        if self.intent.darkening > 0:
            required.add("color_treatment")
        if self.intent.mask_object_id is not None:
            required.add("mask")
        if not required.issubset(permitted):
            raise ValueError("evidence treatment exceeds declared asset permissions")
        return self


def _evidence_treatment_for(beat, asset, obj, action, *, intent: EvidenceIntent | None = None) -> EvidenceTreatment:
    if (asset.managed_ref is None or asset.checksum_sha256 is None
            or asset.width is None or asset.height is None):
        raise ValueError(f"beat {beat.beat_id} evidence has no immutable source snapshot")
    return EvidenceTreatment(
        beat_id=beat.beat_id, object_id=obj.object_id, action_id=action.action_id,
        asset_revision=asset.revision, asset_checksum_sha256=asset.checksum_sha256,
        asset_managed_ref=asset.managed_ref, asset_width=asset.width,
        asset_height=asset.height, asset_provenance=asset.provenance,
        allowed_transformations=asset.allowed_transformations, intent=beat.evidence if intent is None else intent,
    )


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
    objects: list[SemanticObject] = Field(min_length=1)
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
        object_map = _semantic_composition_view({x.object_id: x for x in self.objects})
        placed_images = {obj.asset_id for obj in object_map.values()
                         if getattr(obj, "image_placement", None) is not None}
        image_assets = {asset.asset_id: asset for asset in self.assets}
        for obj in object_map.values():
            if getattr(obj, "media_playback", None) is not None:
                validate_media_asset_binding(obj, image_assets.get(obj.asset_id))
            if obj.object_type == "image" and obj.asset_id in placed_images:
                validate_image_asset_binding(obj, image_assets.get(obj.asset_id))
        semantic_parents = _semantic_group_parents(object_map)
        _validate_structured_lists(object_map, semantic=True)
        _validate_technical_frames(object_map, semantic=True)
        _validate_character_assemblies(object_map, semantic=True)
        _validate_illustration_assemblies(object_map, semantic=True)
        for action in self.actions:
            _validate_structured_progression_objects(action, object_map)
        asset_map = {x.asset_id: x for x in self.assets}
        inline_evidence_ids = {result.object_id for action in self.actions
                               if isinstance(action, SplitAction) and action.split_policy is not None
                               for result in action.split_policy.results if result.evidence_activation is not None}
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
            if obj.object_type == "mask" and obj.mask_source_object_id is not None:
                source = object_map.get(obj.mask_source_object_id)
                if (source is None or source.object_type not in MASK_SOURCE_TYPES
                        or source.board_id != obj.board_id
                        or source.beat_id != obj.beat_id
                        or source.initial_state != "visible"):
                    raise ValueError(f"mask {obj.object_id} requires a same-board, same-beat geometry source")
                if obj.child_ids is not None and (
                        semantic_parents[source.object_id] != semantic_parents[obj.object_id]
                        or source.asset_id is not None):
                    raise ValueError(f"mask {obj.object_id} source must be a dedicated same-parent geometry sibling")
        _unique_mask_sources(self.objects)
        _validate_external_aperture_references({x.object_id: x for x in self.objects}, semantic_parents)
        mask_sources = {obj.mask_source_object_id for obj in self.objects
                        if obj.object_type == "mask" and obj.mask_source_object_id is not None}
        evidence_claim_ids = []
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
            visible_refs = (beat.attention.primary_targets + beat.attention.secondary_context
                            + beat.attention.dimmed_targets + beat.camera_intent.target_ids
                            + beat.continuity.keep + beat.continuity.change
                            + beat.continuity.remove + list(beat.continuity.replacements)
                            + list(beat.continuity.replacements.values())
                            + list(beat.continuity.expected_state_versions))
            if mask_sources.intersection(visible_refs):
                raise ValueError(f"beat {beat.beat_id} cannot display or direct a mask source")
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
                evidence = beat.evidence
                evidence_claim_ids.append(evidence.claim_id)
                asset = asset_map[evidence.evidence_asset_id]
                if asset.kind != "evidence":
                    raise ValueError(f"beat {beat.beat_id} cannot use a supporting image as evidence")
                matching_objects = [obj for obj in self.objects
                                    if obj.beat_id == beat.beat_id
                                    and obj.board_id == beat.board_id
                                    and obj.object_type == "evidence"
                                    and obj.object_id not in inline_evidence_ids
                                    and obj.asset_id == evidence.evidence_asset_id]
                matching_actions = [action_map[action_id] for action_id in beat.action_ids
                                    if isinstance(action_map[action_id], EvidenceAction)
                                    and action_map[action_id].verb == "insert_evidence"
                                    and action_map[action_id].evidence_asset_id == evidence.evidence_asset_id]
                if (len(matching_objects) != 1 or len(matching_actions) != 1
                        or evidence.destination_board_id != beat.board_id
                        or matching_actions[0].destination_board_id != beat.board_id
                        or matching_actions[0].destination_state != evidence.destination_state):
                    raise ValueError(f"beat {beat.beat_id} needs one matched evidence object and insert action")
                if beat.evidence.destination_board_id not in boards:
                    raise ValueError(f"beat {beat.beat_id} evidence references unknown destination board")
                if beat.evidence.annotation_target_id and beat.evidence.annotation_target_id not in objects:
                    raise ValueError(f"beat {beat.beat_id} evidence annotation target is unknown")
                if (beat.evidence.annotation_target_id
                        and object_map[beat.evidence.annotation_target_id].board_id != beat.board_id):
                    raise ValueError(f"beat {beat.beat_id} evidence annotation crosses boards")
                if beat.evidence.annotation_target_id in mask_sources:
                    raise ValueError(f"beat {beat.beat_id} cannot annotate a mask source")
                if beat.evidence.mask_object_id:
                    mask = object_map.get(beat.evidence.mask_object_id)
                    if (mask is None or mask.object_type != "mask"
                            or mask.board_id != beat.board_id):
                        raise ValueError(f"beat {beat.beat_id} evidence mask must be a same-board mask")
                # Old 2.0.0 plans may load without a materialized source snapshot.
                # New writes and all executable layouts require completeness below.
                if all(value is not None for value in (
                    asset.managed_ref, asset.checksum_sha256, asset.width, asset.height
                )):
                    _evidence_treatment_for(beat, asset, matching_objects[0], matching_actions[0])
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
        split_evidence_owners = set()
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
            if isinstance(action, SplitAction) and action.split_policy is not None:
                _validate_split_references(action, object_map, {board.board_id: board for board in self.boards})
                owner = next(beat for beat in self.beats if action.action_id in beat.action_ids)
                if any(object_map[key].beat_id != owner.beat_id for key in _action_mutation_references(action)):
                    raise ValueError("Split source and result roots must retain their action's owning beat")
                for result in action.split_policy.results:
                    activation = result.evidence_activation
                    if activation is None:
                        continue
                    if result.object_id in split_evidence_owners:
                        raise ValueError("each evidence object requires exactly one activation owner")
                    split_evidence_owners.add(result.object_id)
                    _validate_split_evidence_graph(action, result, owner, object_map, asset_map, mask_sources,
                                                   project_id=self.project_id)
                    evidence_claim_ids.append(activation.intent.claim_id)
            if mask_sources.intersection(_action_mutation_references(action)):
                raise ValueError(f"action {action.action_id} cannot animate a mask source")
            if isinstance(action, (GroupAction, SplitAction)) and action.container_id is not None:
                container = object_map[action.container_id]
                if (container.object_type != "group"
                        or container.board_id != action.board_id):
                    raise ValueError(
                        f"action {action.action_id} needs a same-board group container"
                    )
        if len(evidence_claim_ids) != len(set(evidence_claim_ids)):
            raise ValueError("evidence claim IDs must be unique")
        if split_evidence_owners:
            ordinary_targets = {action.target_object_id for action in self.actions
                                if isinstance(action, EvidenceAction) and action.verb == "insert_evidence"}
            if split_evidence_owners.intersection(ordinary_targets):
                raise ValueError("ordinary insert and Split cannot both own an evidence object")
            _validate_evidence_annotation_ownership(object_map, _plan_evidence_annotations(self), self.actions)
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


class InitialEmptyGroupOwnership(StrictModel):
    shell_object_id: str = Field(min_length=1)
    owner_group_action_id: str = Field(min_length=1)
    owner_source_basis_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


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
    evidence_treatments: list[EvidenceTreatment] = Field(default_factory=list)
    initial_empty_group_ownership: list[InitialEmptyGroupOwnership] = Field(default_factory=list)

    @model_serializer(mode="wrap")
    def preserve_legacy_hierarchy_shape(self, handler):
        result = handler(self)
        if not self.initial_empty_group_ownership:
            result.pop("initial_empty_group_ownership", None)
        return result

    @model_validator(mode="after")
    def validate_scene_graph(self):
        if self.style_system_version != "atme-style-v2" or self.asset_registry_version != "atme-assets-v2":
            raise ValueError("unknown style-system or asset-registry version")
        if (self.canvas.width, self.canvas.height) != (self.output_profile.width, self.output_profile.height):
            raise ValueError("canvas must match the independently authored output profile")
        _unique(self.boards, "board_id"); _unique(self.objects, "object_id"); _unique(self.activations, "activation_id")
        board_ids = {x.board_id for x in self.boards}; object_ids = {x.object_id for x in self.objects}
        object_map = {x.object_id: x for x in self.objects}
        _unique(self.initial_empty_group_ownership, "shell_object_id")
        _unique(self.initial_empty_group_ownership, "owner_group_action_id")
        empty_containers = {obj.object_id: obj for obj in self.objects
                            if isinstance(obj, ContainerObject) and not obj.child_ids}
        if set(empty_containers) != {row.shell_object_id for row in self.initial_empty_group_ownership}:
            raise ValueError("every initial empty group needs exactly one ownership receipt; nonempty objects cannot have one")
        for shell in empty_containers.values():
            if (shell.object_type != "group" or not shell.visible or shell.opacity != 1
                    or shell.initial_state != "ungrouped" or shell.asset_id is not None
                    or shell.anchors or shell.geometry.points or shell.geometry.corner_radius is not None
                    or shell.clip_id is not None
                    or any((shell.style.stroke, shell.style.fill, shell.style.text, shell.style.effect))):
                raise ValueError("initial empty shell must be a visible opaque nonpainting ungrouped group")
        mask_sources = {obj.mask_source_object_id for obj in self.objects
                        if isinstance(obj, MaskContainer) and obj.mask_source_object_id is not None}
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
                if parent.board_id != obj.board_id:
                    raise ValueError(f"object {obj.object_id} and parent {obj.parent_id} cross boards")
                if obj.object_id not in parent.child_ids:
                    raise ValueError(f"object {obj.object_id} and parent {obj.parent_id} disagree on membership")
            if obj.clip_id:
                clip = object_map.get(obj.clip_id)
                if not isinstance(clip, ContainerObject) or clip.object_type not in ("mask", "clip"):
                    raise ValueError(f"object {obj.object_id} clip must be a mask or clip object")
            _unique(obj.anchors, "anchor_id")
            if isinstance(obj, ConnectorObject):
                if obj.source_object_id in mask_sources or obj.destination_object_id in mask_sources:
                    raise ValueError(f"connector {obj.object_id} cannot bind to a mask source")
                if obj.role == "semantic_connector" and obj.source_object_id is None:
                    raise ValueError("semantic connectors require an authoritative source endpoint")
                if obj.source_object_id and obj.source_object_id not in object_ids:
                    raise ValueError(f"connector {obj.object_id} has unknown source")
                if obj.destination_object_id not in object_ids:
                    raise ValueError(f"connector {obj.object_id} has unknown destination")
                _check_anchor(obj.source_object_id, obj.source_anchor_id, object_map)
                _check_anchor(obj.destination_object_id, obj.destination_anchor_id, object_map)
            if isinstance(obj, ContainerObject):
                if len(obj.child_ids) != len(set(obj.child_ids)):
                    raise ValueError(f"container {obj.object_id} repeats a child")
                _subset(obj.child_ids, object_ids, f"container {obj.object_id} children")
        _validate_mask_layout(self.objects, object_map)
        _unique_evidence_treatment_owners(self.evidence_treatments)
        if self.evidence_treatments:
            evidence_ids = {obj.object_id for obj in self.objects
                            if isinstance(obj, VisualObject) and obj.object_type == "evidence"}
            if {item.object_id for item in self.evidence_treatments} != evidence_ids:
                raise ValueError("evidence treatment inventory must cover every evidence object")
            for treatment in self.evidence_treatments:
                obj = object_map[treatment.object_id]
                if (obj.beat_id != treatment.beat_id
                        or obj.board_id != treatment.intent.destination_board_id
                        or obj.asset_id != treatment.intent.evidence_asset_id):
                    raise ValueError("evidence treatment changes object, beat, board, or asset")
                _validate_evidence_annotation_objects(treatment.object_id, treatment.intent, object_map)
                mask_ancestors = []
                parent_id = obj.parent_id
                while parent_id is not None:
                    parent = object_map[parent_id]
                    if isinstance(parent, MaskContainer):
                        mask_ancestors.append(parent_id)
                    parent_id = parent.parent_id
                declared_mask = treatment.intent.mask_object_id
                if (mask_ancestors and mask_ancestors != [declared_mask]
                        or declared_mask is not None and mask_ancestors != [declared_mask]):
                    raise ValueError("evidence mask must actually contain its evidence object")
            _validate_evidence_annotation_ownership(object_map,
                [(item.object_id, item.intent) for item in self.evidence_treatments])
        _reject_parent_cycles(object_map)
        _reject_container_cycles(object_map)
        _validate_callout_layout_references(object_map, self.output_profile,
                                            self.style_system_version, self.asset_registry_version)
        _validate_structured_lists(object_map, semantic=False)
        _validate_technical_frames(object_map, semantic=False)
        _validate_character_assemblies(object_map, semantic=False)
        _validate_illustration_assemblies(object_map, semantic=False)
        _validate_composition_objects(object_map)
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
    return_hierarchy_receipt: ReturnHierarchyReceipt | None = None
    split_completion_receipt: SplitCompletionReceipt | None = None
    split_evidence_windows: list[ResolvedSplitEvidenceWindow] | None = Field(
        default=None, min_length=1, max_length=256, json_schema_extra={"type": "array"})

    @field_validator("split_evidence_windows", mode="before")
    @classmethod
    def exact_evidence_windows(cls, value):
        return _validated_split_evidence_windows(value)

    @model_serializer(mode="wrap")
    def preserve_legacy_return_shape(self, handler):
        result = handler(self)
        if self.return_hierarchy_receipt is None:
            result.pop("return_hierarchy_receipt", None)
        if self.split_completion_receipt is None:
            result.pop("split_completion_receipt", None)
        if self.split_evidence_windows is None:
            result.pop("split_evidence_windows", None)
        return result

    @model_validator(mode="after")
    def interval(self):
        if self.end_ms <= self.start_ms:
            raise ValueError("actions use non-empty half-open intervals")
        if isinstance(self.action, TargetAction) and self.action.structured_list_policy is not None:
            _structured_list_phase_windows(self)
        results = (self.action.split_policy.results
                   if isinstance(self.action, SplitAction) and self.action.split_policy is not None else [])
        evidence_ids = [result.object_id for result in results if result.evidence_activation is not None]
        windows = self.split_evidence_windows
        if windows is not None:
            windows = _validated_split_evidence_windows(windows)
        if (bool(evidence_ids) != (windows is not None)
                or windows is not None and [window.result_object_id for window in windows] != evidence_ids):
            raise ValueError("Split evidence windows require exact authored result order and coverage")
        if evidence_ids and self.split_completion_receipt is None:
            raise ValueError("Split evidence windows require their checksummed completion receipt")
        if self.split_completion_receipt is not None:
            if not isinstance(self.action, SplitAction) or self.action.split_policy is None:
                raise ValueError("only an authored Split may carry its completion receipt")
            expected = _split_expected_completion(self.action.split_policy)
            supplied = self.split_completion_receipt.model_dump(
                mode="json", exclude={"completion_sha256", "evidence_windows"})
            if _split_packet_digest(expected) != _split_packet_digest(supplied):
                raise ValueError("Split completion differs from the captured basis and authored final state")
            receipt_windows = self.split_completion_receipt.evidence_windows
            if ((receipt_windows is None) != (windows is None)
                    or windows is not None and [window.model_dump(mode="json") for window in windows]
                    != [window.model_dump(mode="json") for window in receipt_windows]):
                raise ValueError("Split completion must checksum the exact resolved evidence windows")
        receipt = self.return_hierarchy_receipt
        if receipt is not None:
            action = self.action
            if not isinstance(action, EvidenceAction) or action.verb != "return_board":
                raise ValueError("only return_board may carry a return hierarchy receipt")
            if (receipt.action_id != action.action_id
                    or receipt.destination_board_id != action.destination_board_id
                    or receipt.destination_activation_id != action.destination_activation_id
                    or {item.object_id for item in receipt.hierarchy_basis.placements}
                    != set(action.expected_object_states or {})
                    or set(action.expected_object_states or {})
                    != set(action.expected_object_state_versions or {})):
                raise ValueError("return hierarchy receipt changes action, activation or exact retained inventory")
        return self


def _expected_split_evidence_window(item, result, treatment):
    """Derive from actual treatment and the existing integer phase clock only."""
    from atme.render.v2_split_clock import resolve_split_phase

    construction_end = resolve_split_phase(item.start_ms, item.end_ms, result.construction.phase)[1]
    movement_end = (resolve_split_phase(item.start_ms, item.end_ms, result.movement.phase)[1]
                    if result.movement is not None else construction_end)
    hold_start = max(construction_end, movement_end)
    return {
        "result_object_id": result.object_id,
        "treatment_sha256": _split_packet_digest(treatment.model_dump(mode="json")),
        "construction_complete_ms": construction_end,
        "movement_complete_ms": movement_end,
        "readable_hold_start_ms": hold_start,
        "readable_hold_end_ms": hold_start + result.evidence_activation.intent.readable_hold_intent_ms,
    }


class ResolvedAsset(StrictModel):
    asset_id: str
    revision: int = Field(ge=1)
    managed_ref: str
    checksum_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    provenance_verified: bool
    # Optional for old stored 2.0.0 timelines. Raster execution requires every
    # field and rejects ambiguous legacy records rather than guessing.
    kind: str | None = None
    media_type: str | None = None
    byte_length: int | None = Field(default=None, gt=0)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    duration_ms: int | None = Field(default=None, gt=0, strict=True)
    media_stream: MediaStreamPin | None = None
    orientation: Literal["upright"] | None = None
    allowed_transformations: list[Literal[
        "crop", "scale", "rotate", "mask", "annotate", "color_treatment"
    ]] | None = None

    @model_serializer(mode="wrap")
    def preserve_legacy_media_shape(self, handler):
        result = handler(self)
        for key in ("duration_ms", "media_stream"):
            if getattr(self, key) is None:
                result.pop(key, None)
        return result

    @model_validator(mode="after")
    def exact_media_stream(self):
        _validate_media_stream_asset(self)
        return self


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
    evidence_treatments: list[EvidenceTreatment] = Field(default_factory=list)
    initial_object_states: list[ObjectState]
    beat_anchors: list[ResolvedBeatAnchor] = Field(min_length=1)
    actions: list[ResolvedAction] = Field(min_length=1)
    coverage: list[CoverageRecord] = Field(min_length=1)
    fallbacks: list[FallbackRecord]
    validation: ValidationState
    initial_hierarchy_basis: HierarchyBasis | None = None
    initial_hierarchy_basis_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_serializer(mode="wrap")
    def preserve_legacy_hierarchy_shape(self, handler):
        result = handler(self)
        for field in ("initial_hierarchy_basis", "initial_hierarchy_basis_sha256"):
            if getattr(self, field) is None:
                result.pop(field, None)
        return result

    @model_validator(mode="after")
    def validate_timeline(self):
        if self.style_system_version != "atme-style-v2" or self.asset_registry_version != "atme-assets-v2":
            raise ValueError("unknown style-system or asset-registry version")
        _unique(self.resolved_assets, "asset_id"); _unique(self.initial_object_states, "object_id")
        _unique_evidence_treatment_owners(self.evidence_treatments)
        _unique(self.beat_anchors, "beat_id"); _unique(self.coverage, "coverage_id")
        _unique(self.fallbacks, "fallback_id")
        beat_anchors = {item.beat_id: item.start_ms for item in self.beat_anchors}
        if any(start >= self.duration_ms for start in beat_anchors.values()):
            raise ValueError("beat anchors must be within the resolved duration")
        action_ids = []
        previous = 0
        states = {item.object_id: item.state for item in self.initial_object_states}
        hierarchy_actions = [item.action for item in self.actions
                             if isinstance(item.action, GroupAction) and item.action.hierarchy_policy is not None]
        if (self.initial_hierarchy_basis is None) != (self.initial_hierarchy_basis_sha256 is None):
            raise ValueError("initial hierarchy basis and hash must be supplied together")
        if hierarchy_actions and self.initial_hierarchy_basis is None:
            raise ValueError("authored hierarchy actions require an explicit initial hierarchy basis")
        if self.initial_hierarchy_basis is not None:
            initial_placements = {item.object_id: item for item in self.initial_hierarchy_basis.placements}
            if (initial_placements.keys() != states.keys()
                    or self.initial_hierarchy_basis.checksum() != self.initial_hierarchy_basis_sha256):
                raise ValueError("initial hierarchy receipt must cover the exact object inventory and canonical hash")
            for action in hierarchy_actions:
                for basis in (action.hierarchy_policy.source_basis, action.hierarchy_policy.destination_basis):
                    if (len(basis.placements) != len(initial_placements)
                            or any(item.object_id not in initial_placements
                                   or item.board_id != initial_placements[item.object_id].board_id
                                   for item in basis.placements)):
                        raise ValueError("hierarchy actions must preserve initial object and board inventory")
        resolved_actions: dict[str, ResolvedAction] = {}
        ordinary_evidence_actions = {item.action.action_id for item in self.actions
                                     if isinstance(item.action, EvidenceAction) and item.action.verb == "insert_evidence"}
        evidence_by_action = {row.action_id: row for row in self.evidence_treatments
                              if row.action_id in ordinary_evidence_actions}
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
            for target in _action_mutation_references(action):
                if states[target] == "removed" and action.verb not in ("return_board",):
                    raise ValueError(f"action {action.action_id} resurrects removed object {target}")
            if isinstance(action, SplitAction) and action.split_policy is not None:
                policy = action.split_policy
                if states[policy.source_object_id] != action.expected_state:
                    raise ValueError("Split source precondition failed")
                if any(states[result.object_id] != "hidden" for result in policy.results):
                    raise ValueError("Split requires hidden result roots")
                states[policy.source_object_id] = "removed"
                for result in policy.results:
                    states[result.object_id] = result.post_state
                resolved_actions[action.action_id] = resolved
                continue
            if isinstance(action, ReplaceAction):
                if action.from_object_id == action.to_object_id:
                    raise ValueError(f"{action.verb} {action.action_id} needs distinct objects")
                if action.expected_state is None or states[action.from_object_id] != action.expected_state:
                    raise ValueError(f"{action.verb} {action.action_id} source precondition failed")
                if states[action.to_object_id] != "hidden" or action.post_state != "visible":
                    raise ValueError(f"{action.verb} {action.action_id} needs hidden-to-visible destination")
                states[action.from_object_id] = "removed"
                states[action.to_object_id] = "visible"
                resolved_actions[action.action_id] = resolved
                continue
            if isinstance(action, TargetAction) and action.annotation_policy is not None:
                if states[action.target_ids[0]] != "visible":
                    raise ValueError("annotation requires an unchanged visible target")
                for object_id in _annotation_object_ids(action):
                    if states[object_id] != "hidden":
                        raise ValueError("annotation requires hidden authored objects")
                    states[object_id] = "visible"
                _annotation_phase_windows(resolved)
                if resolved.end_ms + action.annotation_policy.readable_hold_ms > self.duration_ms:
                    raise ValueError("annotation phases or reading hold exceed resolved timing")
                resolved_actions[action.action_id] = resolved
                continue
            treatment = evidence_by_action.get(action.action_id)
            if isinstance(action, EvidenceAction) and treatment is not None and treatment.intent.annotation_policy is not None:
                policy = treatment.intent.annotation_policy
                ids = _annotation_policy_object_ids(policy)
                if any(key not in states or states[key] != "hidden" for key in ids):
                    raise ValueError("evidence annotation requires untouched hidden annotation objects")
                _annotation_policy_phase_windows(policy, resolved.start_ms, resolved.end_ms)
                for key in ids:
                    states[key] = "visible"
            # A camera observes objects; it does not mutate their semantic state.
            state_targets = ([] if isinstance(action, CameraAction)
                             else action.target_ids if isinstance(action, TargetAction)
                             and action.structured_list_policy is not None
                             else [action.connector_id] if isinstance(action, ConnectionAction)
                             else [action.container_id] if isinstance(action, GroupAction)
                             and action.hierarchy_policy is not None
                             else targets)
            for target in state_targets:
                if action.expected_state is not None and states[target] != action.expected_state:
                    raise ValueError(f"action {action.action_id} precondition failed for {target}")
            for target in state_targets:
                states[target] = "removed" if action.verb == "exit" else action.post_state
            resolved_actions[action.action_id] = resolved
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("action_id values must be unique")
        coverage_ids = {item.coverage_id for item in self.coverage}
        fallbacks = {item.fallback_id: item for item in self.fallbacks}
        action_map = {item.action.action_id: item.action for item in self.actions}
        expected_split_pairs = {(item.action.action_id, result.object_id)
                                for item in self.actions if isinstance(item.action, SplitAction)
                                and item.action.split_policy is not None
                                for result in item.action.split_policy.results if result.evidence_activation is not None}
        actual_split_pairs = set()
        ordinary_treatments = []
        if self.evidence_treatments:
            assets_by_id = {asset.asset_id: asset for asset in self.resolved_assets}
            resolved_by_id = {item.action.action_id: item for item in self.actions}
            for treatment in self.evidence_treatments:
                asset = assets_by_id.get(treatment.intent.evidence_asset_id)
                _require_evidence_annotation_policy(treatment.object_id, treatment.intent)
                resolved = resolved_by_id.get(treatment.action_id)
                if (asset is None or resolved is None
                        or asset.revision != treatment.asset_revision
                        or asset.checksum_sha256 != treatment.asset_checksum_sha256
                        or asset.managed_ref != treatment.asset_managed_ref
                        or asset.kind != "evidence"
                         or asset.media_type != "image/png"
                         or asset.byte_length is None
                         or asset.width != treatment.asset_width
                         or asset.height != treatment.asset_height
                         or asset.orientation != "upright"
                         or asset.allowed_transformations != treatment.allowed_transformations
                        or not asset.provenance_verified):
                    raise ValueError("resolved evidence changes treatment, asset, action, or hold")
                action = resolved.action
                if isinstance(action, SplitAction) and action.split_policy is not None:
                    result = next((row for row in action.split_policy.results
                                   if row.object_id == treatment.object_id), None)
                    activation = result.evidence_activation if result is not None else None
                    if (activation is None or treatment.intent != activation.intent
                            or treatment.beat_id != activation.beat_id
                            or action.board_id != treatment.intent.destination_board_id
                            or activation.asset_pin.asset_id != asset.asset_id
                            or activation.asset_pin.revision != asset.revision
                            or activation.asset_pin.resource_uri != f"atme://projects/{self.project_id}/assets/{asset.asset_id}"
                            or activation.asset_pin.checksum_sha256 != asset.checksum_sha256
                            or activation.allowed_transformations != asset.allowed_transformations):
                        raise ValueError("resolved Split evidence changes its exact activation or source authority")
                    expected_window = _expected_split_evidence_window(resolved, result, treatment)
                    supplied = next(row for row in resolved.split_evidence_windows
                                    if row.result_object_id == result.object_id)
                    if (supplied.model_dump(mode="json") != expected_window
                            or expected_window["readable_hold_end_ms"] > self.duration_ms):
                        raise ValueError("resolved Split evidence window differs from actual treatment and phase timing")
                    actual_split_pairs.add((action.action_id, result.object_id))
                elif isinstance(action, EvidenceAction) and action.verb == "insert_evidence":
                    if (action.evidence_asset_id != asset.asset_id
                            or action.board_id != treatment.intent.destination_board_id
                            or action.destination_state != treatment.intent.destination_state
                            or resolved.end_ms + treatment.intent.readable_hold_intent_ms > self.duration_ms):
                        raise ValueError("resolved evidence changes treatment, asset, action, or hold")
                    ordinary_treatments.append(treatment)
                else:
                    raise ValueError("resolved evidence has no actual insert or Split activation owner")
        if actual_split_pairs != expected_split_pairs:
            raise ValueError("every resolved Split evidence result needs its exact treatment")
        # Preserve ordinary one-object/one-insert/one-beat cardinality; Split's
        # multiple result rows are a separate ownership branch, not extra inserts.
        _unique(ordinary_treatments, "beat_id")
        _unique(ordinary_treatments, "action_id")
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


def validate_plan_layout(plan_document: dict, layout_document: dict, *, require_code_payloads: bool = True) -> None:
    """Reject any executable layout that silently changes semantic-plan meaning."""
    plan = VisualPlanV2.model_validate(plan_document)
    layout = ExecutableLayoutV2.model_validate(layout_document)
    if require_code_payloads:
        _require_composition_bindings(plan.objects)
        _require_composition_bindings(layout.objects)
        _require_code_payloads(plan.objects)
        _require_code_payloads(layout.objects)
        _require_chart_payloads(layout.objects)
        annotations = _plan_evidence_annotations(plan)
        _validate_callout_ownership({obj.object_id: obj for obj in plan.objects}, plan.actions, annotations)
        _validate_callout_ownership({obj.object_id: obj for obj in layout.objects}, plan.actions, annotations)
    if layout.project_id != plan.project_id or layout.plan_id != plan.plan_id:
        raise ValueError("layout references a different visual plan")
    semantic_original = {item.object_id: item for item in plan.objects}
    semantic = _semantic_composition_view(semantic_original)
    executable = {item.object_id: item for item in layout.objects}
    if set(semantic) != set(executable):
        raise ValueError("layout must realize every and only declared semantic object")
    semantic_parents = _semantic_group_parents(semantic)
    reference_members = _validate_external_aperture_references(semantic_original, semantic_parents)
    if any(executable[key].parent_id != semantic_parents[key] for key in reference_members):
        raise ValueError("layout external aperture must preserve explicit semantic ownership")
    for object_id, spec in semantic.items():
        obj = executable[object_id]
        binding = getattr(spec, "connector_binding", None)
        if isinstance(obj, ConnectorObject):
            if binding is None and (obj.source_point is not None
                                    or require_code_payloads and obj.object_type == "network"):
                raise ValueError(f"layout object {object_id} requires exact semantic connector_binding")
            if binding is not None:
                actual = {key: getattr(obj, key) for key in (
                    "source_object_id", "source_anchor_id", "destination_object_id",
                    "destination_anchor_id", "role", "routing", "allow_self_loop")}
                if obj.source_point is not None:
                    actual["source_point"] = obj.source_point.model_dump(mode="json")
                if binding.model_dump(mode="json") != actual:
                    raise ValueError(f"layout object {object_id} changes semantic connector_binding")
        elif binding is not None:
            raise ValueError(f"layout object {object_id} changes semantic connector_binding owner")
        reference = getattr(spec, "clip_id", None)
        if (require_code_payloads or reference is not None) and obj.clip_id != reference:
            raise ValueError(f"layout object {object_id} changes semantic field clip_id")
        original_binding = getattr(semantic_original[object_id], "composition_binding", None)
        if getattr(obj, "composition_binding", None) != original_binding:
            raise ValueError(f"layout object {object_id} changes semantic field composition_binding")
        if (isinstance(obj, GroupContainer)
                and (not isinstance(spec, SemanticStandardObjectSpec)
                     or spec.character_assembly != obj.character_assembly)):
            raise ValueError(f"layout object {object_id} changes semantic field character_assembly")
        if (isinstance(obj, GroupContainer)
                and (not isinstance(spec, SemanticStandardObjectSpec)
                     or spec.illustration_assembly != obj.illustration_assembly)):
            raise ValueError(f"layout object {object_id} changes semantic field illustration_assembly")
        if (isinstance(obj, VisualObject)
                and (not isinstance(spec, SemanticStandardObjectSpec)
                     or spec.registry_binding != obj.registry_binding)):
            raise ValueError(f"layout object {object_id} changes semantic field registry_binding")
        if (isinstance(obj, VisualObject)
                and (not isinstance(spec, SemanticStandardObjectSpec)
                     or spec.technical_frame != obj.technical_frame)):
            raise ValueError(f"layout object {object_id} changes semantic field technical_frame")
        if (isinstance(obj, VisualObject)
                and (not isinstance(spec, SemanticStandardObjectSpec)
                     or spec.chart_payload != obj.chart_payload)):
            raise ValueError(f"layout object {object_id} changes semantic field chart_payload")
        if (isinstance(obj, VisualObject)
                and (not isinstance(spec, SemanticStandardObjectSpec)
                     or spec.image_placement != obj.image_placement)):
            raise ValueError(f"layout object {object_id} changes semantic field image_placement")
        if (isinstance(obj, TextObject) and obj.object_type == "code"
                and (not isinstance(spec, SemanticStandardObjectSpec)
                     or spec.code_payload != obj.code_payload)):
            raise ValueError(f"layout object {object_id} changes semantic field code_payload")
        if (isinstance(obj, TextObject) and obj.object_type == "callout"
                and (not isinstance(spec, SemanticStandardObjectSpec)
                     or spec.callout_binding != obj.callout_binding)):
            raise ValueError(f"layout object {object_id} changes semantic field callout_binding")
        object_document = obj.model_dump(mode="json")
        for field, value in spec.model_dump(mode="json").items():
            if field == "connector_binding":
                continue  # Semantic-only wrapper checked against exact executable fields above.
            if object_document.get(field) != value:
                raise ValueError(f"layout object {object_id} changes semantic field {field}")
    if any(getattr(obj, "image_placement", None) is not None for obj in executable.values()):
        from atme.render.v2_image import validate_image_permissions

        images = [obj for obj in executable.values() if obj.object_type == "image"]
        assets = {asset.asset_id: asset for asset in plan.assets}
        # Bind every use first: an extended inventory cannot grant a bare sibling
        # permissions, and executable geometry must not bypass the semantic pins.
        for obj in images:
            validate_image_asset_binding(obj, assets.get(obj.asset_id))
        transforms = {key: obj.transform for key, obj in executable.items()}
        for obj in images:
            validate_image_permissions(obj, executable, transforms, plan.actions)
    media_objects = [obj for obj in executable.values() if getattr(obj, "media_playback", None) is not None]
    if media_objects:
        from atme.render.v2_image import validate_placement_permissions

        transforms = {key: obj.transform for key, obj in executable.items()}
        for obj in media_objects:
            validate_placement_permissions(obj, obj.media_playback.placement, executable, transforms,
                                           plan.actions, label="media_playback.placement")
    plan_boards = {item.board_id: item for item in plan.boards}
    layout_boards = {item.board_id: item for item in layout.boards}
    if set(plan_boards) != set(layout_boards):
        raise ValueError("layout board inventory differs from the visual plan")
    for board_id, board in plan_boards.items():
        candidate = layout_boards[board_id]
        if candidate.model_dump(mode="json") != board.model_dump(mode="json"):
            raise ValueError(f"layout board {board_id} changes its directing declaration")
    activations = {item.activation_id: item for item in layout.activations}
    plan_actions = {item.action_id: item for item in plan.actions}
    for owner in layout.initial_empty_group_ownership:
        action = plan_actions.get(owner.owner_group_action_id)
        if (not isinstance(action, GroupAction) or action.verb != "group"
                or action.container_id != owner.shell_object_id or action.hierarchy_policy is None
                or action.hierarchy_policy.source_basis_sha256 != owner.owner_source_basis_sha256
                or any(item.parent_id == owner.shell_object_id
                       for item in action.hierarchy_policy.source_basis.placements)):
            raise ValueError("empty group ownership must bind its actual group action and empty source-basis hash")
    for action in plan.actions:
        _validate_structured_progression_objects(action, executable, normal_write=True)
        if isinstance(action, SplitAction) and action.split_policy is not None:
            _validate_split_references(action, executable, layout_boards)
        if isinstance(action, GroupAction) and action.verb in {"group", "ungroup"}:
            from atme.render.v2_hierarchy import validate_authored_hierarchy

            validate_authored_hierarchy(action, executable)
        if isinstance(action, TargetAction) and action.verb == "count" and action.count_policy is not None:
            _require_count_contract(action)
            obj = executable[action.target_ids[0]]
            if (not isinstance(obj, TextObject) or obj.object_type != "text" or obj.items
                    or not obj.text.strip() or len(obj.text.splitlines()) != 1):
                raise ValueError("count layout requires one supported single-line text object")
            starts = {candidate.count_policy.start_text for candidate in plan.actions
                      if isinstance(candidate, TargetAction) and candidate.verb == "count"
                      and candidate.count_policy is not None and candidate.target_ids == action.target_ids}
            if obj.text not in starts:
                raise ValueError("count layout initial text must be an explicitly authored starting value")
            # Plan array order is not necessarily resolved trigger order. The
            # shared chronology proves which declared start is actually first.
        if isinstance(action, TargetAction) and action.verb == "annotate":
            _validate_annotation_plan_objects(action, {obj.object_id: obj for obj in plan.objects},
                                              next(beat for beat in plan.beats if action.action_id in beat.action_ids))
            _validate_annotation_plan_objects(action, executable)
            _validate_annotation_layout(action, executable)
        if isinstance(action, ReplaceAction) and action.verb == "morph":
            from atme.render.v2_morph import validate_morph_geometry

            _require_morph_contract(action)
            source, destination = executable[action.from_object_id], executable[action.to_object_id]
            if (source.board_id != action.board_id or destination.board_id != action.board_id
                    or source.parent_id != destination.parent_id
                    or source.z_index != destination.z_index):
                raise ValueError("morph must preserve board, parent, and layer ownership")
            validate_morph_geometry(source, destination, action.morph_policy)
        if not isinstance(action, EvidenceAction) or action.verb != "return_board":
            continue
        _require_return_contract(action)
        _require_return_board_policy(plan_boards[action.destination_board_id])
        source = activations.get(action.source_activation_id)
        prior = activations.get(action.prior_destination_activation_id)
        destination = activations.get(action.destination_activation_id)
        if (source is None or prior is None or destination is None
                or action.board_id != action.destination_board_id
                or source.board_id != action.source_board_id
                or prior.board_id != action.destination_board_id
                or destination.board_id != action.destination_board_id
                or prior.end_ms > destination.start_ms
                or source.end_ms > destination.start_ms):
            raise ValueError(f"return_board {action.action_id} changes its activation lineage")
    plan_assets = {item.asset_id: item for item in plan.assets}
    plan_actions = {item.action_id: item for item in plan.actions}
    split_ids = {result.object_id for action in plan.actions
                 if isinstance(action, SplitAction) and action.split_policy is not None
                 for result in action.split_policy.results if result.evidence_activation is not None}
    expected_treatments = []
    for beat in plan.beats:
        if beat.evidence is None:
            continue
        evidence = beat.evidence
        asset = plan_assets[evidence.evidence_asset_id]
        obj = next(item for item in plan.objects
                   if item.beat_id == beat.beat_id and item.object_type == "evidence"
                   and item.object_id not in split_ids
                   and item.asset_id == asset.asset_id)
        action = next(plan_actions[action_id] for action_id in beat.action_ids
                      if isinstance(plan_actions[action_id], EvidenceAction)
                      and plan_actions[action_id].verb == "insert_evidence")
        if (action.target_object_id != obj.object_id
                or action.expected_state != "hidden"
                or action.post_state != evidence.destination_state):
            raise ValueError("evidence insert must bind its hidden object and declared destination state")
        expected_treatments.append(_evidence_treatment_for(beat, asset, obj, action))
        _validate_evidence_annotation_objects(obj.object_id, evidence, semantic_original,
                                              beat=beat, coverage_id=action.coverage_id)
        _validate_evidence_annotation_objects(obj.object_id, evidence, executable,
                                              beat=beat, coverage_id=action.coverage_id)
    for beat, obj, action, intent in _plan_split_evidence_rows(plan):
        asset = plan_assets[intent.evidence_asset_id]
        expected_treatments.append(_evidence_treatment_for(beat, asset, obj, action, intent=intent))
        _validate_evidence_annotation_objects(obj.object_id, intent, semantic_original,
                                              beat=beat, coverage_id=action.coverage_id)
        _validate_evidence_annotation_objects(obj.object_id, intent, executable,
                                              beat=beat, coverage_id=action.coverage_id)
    if _plan_evidence_annotations(plan):
        _validate_evidence_annotation_ownership(executable, _plan_evidence_annotations(plan), plan.actions)
    actual = {(item.action_id, item.object_id): item for item in layout.evidence_treatments}
    expected = {(item.action_id, item.object_id): item for item in expected_treatments}
    if actual != expected:
        raise ValueError("layout must preserve every evidence treatment exactly")


def _require_registry_write_bindings(document, *, placed: bool) -> None:
    from atme.render.style_bundle import (
        registry_endpoint_inputs_for_objects,
        resolve_contract_bundle,
    )
    from atme.render.v2_registry import (
        SUPPORTED_REGISTRY_VISUALS,
        validate_registry_new_write_objects,
    )

    if any(getattr(obj, "registry_binding", None) is not None for obj in document.objects):
        resolve_contract_bundle(document.style_system_version, document.asset_registry_version)
    require_metadata = placed and any(isinstance(obj, VisualObject) and obj.anchors
        and obj.variant is not None and obj.object_type in SUPPORTED_REGISTRY_VISUALS for obj in document.objects)
    inputs = registry_endpoint_inputs_for_objects({obj.object_id: obj for obj in document.objects},
                                                 require_metadata=require_metadata)
    validate_registry_new_write_objects(document.objects, inputs, placed=placed)


def validate_layout_registry_completeness(layout: ExecutableLayoutV2) -> None:
    """New writes only: authenticate placed artwork/native physical coherence."""
    _require_registry_write_bindings(layout, placed=True)
    _require_composition_bindings(layout.objects)
    _require_chart_payloads(layout.objects)
    chromes = [obj for obj in layout.objects
               if isinstance(obj, VisualObject) and obj.technical_frame is not None]
    if chromes:
        from atme.render.v2_technical_frame import validate_technical_frame_world

        objects = {obj.object_id: obj for obj in layout.objects}
        transforms = {key: obj.transform for key, obj in objects.items()}
        for chrome in chromes:
            validate_technical_frame_world(chrome, objects, transforms)


def validate_plan_evidence_completeness(plan_document: dict) -> None:
    """Require executable evidence and return declarations for new plan writes."""
    plan = VisualPlanV2.model_validate(plan_document)
    _require_composition_bindings(plan.objects)
    _require_registry_write_bindings(plan, placed=False)
    _require_code_payloads(plan.objects)
    if any(obj.object_type == "network" and getattr(obj, "connector_binding", None) is None
           for obj in plan.objects):
        raise ValueError("new network writes require exact semantic connector_binding")
    _validate_callout_ownership({obj.object_id: obj for obj in plan.objects}, plan.actions,
                              _plan_evidence_annotations(plan))
    for action in plan.actions:
        _validate_structured_progression_objects(action, {obj.object_id: obj for obj in plan.objects},
                                                 normal_write=True)
        if isinstance(action, SplitAction):
            _require_split_contract(action)
        if isinstance(action, GroupAction) and action.verb in {"group", "ungroup"}:
            _require_hierarchy_contract(action)
            policy_objects = {item.object_id: item for item in action.hierarchy_policy.source_basis.placements}
            if (policy_objects.keys() != {obj.object_id for obj in plan.objects}
                    or any(obj.board_id != policy_objects[obj.object_id].board_id for obj in plan.objects)):
                raise ValueError("hierarchy policy must cover the exact semantic-plan inventory and boards")
        if isinstance(action, TargetAction) and action.verb == "annotate":
            _validate_annotation_plan_objects(action, {obj.object_id: obj for obj in plan.objects},
                                              next(beat for beat in plan.beats if action.action_id in beat.action_ids))
        if isinstance(action, TargetAction) and action.verb == "count":
            _require_count_contract(action)
            obj = next(obj for obj in plan.objects if obj.object_id == action.target_ids[0])
            if obj.object_type != "text" or obj.board_id != action.board_id:
                raise ValueError("count requires one semantic text object on its declared board")
        if isinstance(action, ReplaceAction) and action.verb == "morph":
            _require_morph_contract(action)
            objects = {obj.object_id: obj for obj in plan.objects}
            source, destination = objects[action.from_object_id], objects[action.to_object_id]
            family = ({"rectangle", "rounded_rectangle", "ellipse"}
                      if action.morph_policy.mapping == "canonical_outline"
                      else {"polygon", "line", "freehand"}
                      if action.morph_policy.mapping == "ordered_vertices" else {"freehand"})
            if (source.object_type not in family or destination.object_type not in family
                    or action.morph_policy.mapping != "canonical_outline"
                    and source.object_type != destination.object_type
                    or source.board_id != action.board_id or destination.board_id != action.board_id):
                raise ValueError("morph semantic objects do not match their correspondence policy")
    assets = {item.asset_id: item for item in plan.assets}
    actions = {item.action_id: item for item in plan.actions}
    evidence_objects = {item.object_id for item in plan.objects
                        if item.object_type == "evidence"}
    insert_actions = {item.action_id for item in plan.actions
                      if isinstance(item, EvidenceAction) and item.verb == "insert_evidence"}
    covered_objects = set()
    covered_actions = set()
    split_ids = {result.object_id for action in plan.actions
                 if isinstance(action, SplitAction) and action.split_policy is not None
                 for result in action.split_policy.results if result.evidence_activation is not None}
    for beat in plan.beats:
        if beat.evidence is None:
            continue
        asset = assets[beat.evidence.evidence_asset_id]
        obj = next(item for item in plan.objects if item.beat_id == beat.beat_id
                   and item.object_type == "evidence" and item.asset_id == asset.asset_id
                   and item.object_id not in split_ids)
        action = next(actions[action_id] for action_id in beat.action_ids
                      if isinstance(actions[action_id], EvidenceAction)
                      and actions[action_id].verb == "insert_evidence")
        if (action.target_object_id != obj.object_id
                or action.expected_state != "hidden"
                or action.post_state != beat.evidence.destination_state):
            raise ValueError("evidence insert must bind its hidden object and declared destination state")
        _evidence_treatment_for(beat, asset, obj, action)
        _validate_evidence_annotation_objects(obj.object_id, beat.evidence,
            {item.object_id: item for item in plan.objects}, beat=beat, coverage_id=action.coverage_id)
        covered_objects.add(obj.object_id)
        covered_actions.add(action.action_id)
    for beat, obj, action, intent in _plan_split_evidence_rows(plan):
        if obj.object_id in covered_objects:
            raise ValueError("every evidence object needs exactly one activation owner")
        _evidence_treatment_for(beat, assets[intent.evidence_asset_id], obj, action, intent=intent)
        _validate_evidence_annotation_objects(obj.object_id, intent,
            {item.object_id: item for item in plan.objects}, beat=beat, coverage_id=action.coverage_id)
        covered_objects.add(obj.object_id)
    if covered_objects != evidence_objects or covered_actions != insert_actions:
        raise ValueError("every evidence object and insert action needs an EvidenceIntent")
    boards = {item.board_id: item for item in plan.boards}
    for beat in plan.beats:
        for action_id in beat.action_ids:
            action = actions[action_id]
            if not isinstance(action, EvidenceAction) or action.verb != "return_board":
                continue
            _require_return_contract(action)
            board = boards[action.destination_board_id]
            _require_return_board_policy(board)
            expected_versions = beat.continuity.expected_state_versions
            if (action.board_id != beat.board_id
                    or action.destination_board_id != beat.board_id
                    or action.source_board_id != beat.continuity.return_from_board_id
                    or action.destination_state != beat.continuity.developed_return_state
                    or action.expected_state != board.expected_prior_state
                    or set(action.expected_object_states) != set(board.object_ids)
                    or not expected_versions
                    or not set(expected_versions).issubset(set(board.object_ids))
                    or any(action.expected_object_state_versions[object_id] != version
                           for object_id, version in expected_versions.items())):
                raise ValueError("return_board must match its board, continuity, and full object inventory")


def _require_split_contract(action: SplitAction) -> None:
    # Bare legacy records remain parseable; new authored writes require policy.
    if action.split_policy is None:
        raise ValueError("split requires an explicit authored policy for new writes")


def _validate_split_references(action: SplitAction,
                               objects: Mapping[str, ObjectBase | SemanticObjectSpec],
                               boards: Mapping[str, BoardSpec]) -> None:
    _require_split_contract(action)
    references = _action_object_references(action)
    _subset(references, set(objects), f"Split {action.action_id} objects")
    if action.board_id not in boards or any(objects[key].board_id != action.board_id for key in references):
        raise ValueError("Split participants and read dependencies must stay on their declared board")
    source = objects[action.split_policy.source_object_id]
    for key in _action_mutation_references(action):
        obj = objects[key]
        if obj.beat_id != source.beat_id or action.coverage_id not in obj.coverage_ids:
            raise ValueError("Split roots must share their declared beat and action coverage")
    for result in action.split_policy.results:
        activation = result.evidence_activation
        if activation is None:
            continue
        obj = objects[result.object_id]
        if (obj.object_type != "evidence" or obj.asset_id != activation.intent.evidence_asset_id
                or obj.beat_id != activation.beat_id):
            raise ValueError("Split evidence activation must bind its actual evidence object, asset and beat")


def _validate_split_evidence_graph(action, result, beat, objects, assets, mask_sources, *, project_id):
    """Join inline authority to the same forensic graph as ordinary evidence."""
    activation = result.evidence_activation
    intent = activation.intent
    obj = objects[result.object_id]
    asset = assets.get(intent.evidence_asset_id)
    pin = activation.asset_pin
    if (activation.beat_id != beat.beat_id or result.object_id not in beat.object_ids
            or asset is None or asset.kind != "evidence"
            or pin.revision != asset.revision
            or pin.resource_uri != f"atme://projects/{project_id}/assets/{asset.asset_id}"
            or pin.checksum_sha256 != asset.checksum_sha256
            or activation.allowed_transformations != asset.allowed_transformations):
        raise ValueError("Split evidence changes its owning beat, evidence source snapshot or exact permissions")
    if intent.annotation_target_id is not None:
        target = objects.get(intent.annotation_target_id)
        if (target is None or target.board_id != beat.board_id
                or intent.annotation_target_id in mask_sources):
            raise ValueError("Split evidence annotation must name a same-board non-mask-source target")
    if intent.mask_object_id is not None:
        mask = objects.get(intent.mask_object_id)
        if mask is None or mask.object_type != "mask" or mask.board_id != beat.board_id:
            raise ValueError("Split evidence mask must name a same-board mask")
    _evidence_treatment_for(beat, asset, obj, action, intent=intent)
    _validate_evidence_annotation_objects(obj.object_id, intent, objects,
                                          beat=beat, coverage_id=action.coverage_id)


def _action_mutation_references(action):
    if isinstance(action, TargetAction) and action.structured_list_policy is not None:
        return list(action.target_ids)
    if isinstance(action, SplitAction) and action.split_policy is not None:
        return [action.split_policy.source_object_id, *[row.object_id for row in action.split_policy.results]]
    return _action_object_references(action)


def _require_count_contract(action: TargetAction) -> None:
    if (action.verb != "count" or action.count_policy is None
            or action.target_ids != [action.count_policy.text_object_id]
            or (action.expected_state, action.post_state) != ("visible", "visible")
            or action.annotation is not None or action.annotation_policy is not None):
        raise ValueError("count requires one exact text target, explicit policy and visible-to-visible states")
    if action.easing == "step":
        raise ValueError("count cannot discard its declared quantization levels with step easing")


def _require_structured_list_contract(action):
    policy = action.structured_list_policy
    if (action.verb != "progressive_reveal" or action.target_ids != policy.item_object_ids
            or (action.expected_state, action.post_state) != ("hidden", "visible")
            or action.easing != "linear" or action.annotation is not None
            or action.annotation_policy is not None or action.count_policy is not None):
        raise ValueError("structured list progression requires exact items, linear hidden-to-visible timing and one policy")


def _validate_structured_progression_objects(action, objects, *, normal_write=False):
    if not isinstance(action, TargetAction) or action.verb != "progressive_reveal":
        return
    policy = action.structured_list_policy
    if policy is None:
        if normal_write:
            for key in action.target_ids:
                obj = objects.get(key)
                if (not isinstance(obj, (SemanticStandardObjectSpec, TextObject))
                        or obj.object_type != "list" or obj.structured_list is not None):
                    raise ValueError("policy-less progression requires authored flat lists, not structured or non-list targets")
                if isinstance(obj, TextObject):
                    from atme.render.v2_list import validate_ordered_list

                    validate_ordered_list(obj)
        return
    heading = objects.get(policy.list_object_id)
    binding = getattr(heading, "structured_list", None)
    if (heading is None or heading.object_type != "list" or heading.board_id != action.board_id
            or binding is None or binding.container_group_id != policy.container_group_id
            or binding.item_object_ids != policy.item_object_ids):
        raise ValueError("structured list policy differs from the authoritative heading/group/item binding")


def _require_morph_contract(action: ReplaceAction) -> None:
    if (action.morph_policy is None or action.from_object_id == action.to_object_id
            or action.expected_state is None or action.post_state != "visible"
            or action.easing == "step"):
        raise ValueError("morph needs distinct objects, correspondence, source state, and continuous easing")


def validate_resolved_structure(plan: VisualPlanV2, layout: ExecutableLayoutV2,
                                resolved: ResolvedVisualTimelineV2,
                                cleaned_duration_ms: int) -> None:
    """Compiler output must initialize the complete layout and authoritative timing."""
    authored_lists = {action.action_id: action for action in plan.actions
        if isinstance(action, TargetAction) and action.structured_list_policy is not None}
    resolved_lists = {item.action.action_id: item.action for item in resolved.actions
        if isinstance(item.action, TargetAction) and item.action.structured_list_policy is not None}
    if (authored_lists.keys() != resolved_lists.keys()
            or any(action != resolved_lists[key] for key, action in authored_lists.items())):
        raise ValueError("resolved structured list inventory or policy differs from the authoritative plan")
    authored_splits = {action.action_id: action for action in plan.actions if isinstance(action, SplitAction)}
    resolved_splits = {item.action.action_id: item.action for item in resolved.actions
                       if isinstance(item.action, SplitAction)}
    if (authored_splits.keys() != resolved_splits.keys()
            or any(action != resolved_splits[key] for key, action in authored_splits.items())):
        raise ValueError("resolved Split inventory or policy differs from the authoritative plan")
    objects = {obj.object_id: obj for obj in layout.objects}
    states = {item.object_id: item for item in resolved.initial_object_states}
    if objects.keys() != states.keys() or any(
        obj.initial_state != states[object_id].state
        or obj.visible != states[object_id].visible
        for object_id, obj in objects.items()
    ):
        raise ValueError("resolved timeline must preserve every initial layout state and visibility")
    if {beat.beat_id for beat in plan.beats} != {beat.beat_id for beat in resolved.beat_anchors}:
        raise ValueError("resolved beat anchors must match the complete visual plan")
    if cleaned_duration_ms <= 0 or resolved.duration_ms != cleaned_duration_ms:
        raise ValueError("resolved duration must match the cleaned source timeline")
    assets = {asset.asset_id: asset for asset in plan.assets}
    expected_split_treatments = {
        (action.action_id, obj.object_id): _evidence_treatment_for(
            beat, assets[intent.evidence_asset_id], obj, action, intent=intent)
        for beat, obj, action, intent in _plan_split_evidence_rows(plan)}
    if expected_split_treatments:
        layout_treatments = {(row.action_id, row.object_id): row for row in layout.evidence_treatments}
        if (layout.evidence_treatments != resolved.evidence_treatments
                or any(layout_treatments.get(key) != treatment
                       for key, treatment in expected_split_treatments.items())):
            raise ValueError("resolved Split evidence must preserve exact plan and layout treatments")
    for item in resolved.actions:
        _validate_structured_progression_objects(item.action, objects)
        if isinstance(item.action, SplitAction):
            _require_split_contract(item.action)
            _validate_split_references(item.action, objects, {board.board_id: board for board in layout.boards})
            if item.split_completion_receipt is None:
                raise ValueError("new resolved Split requires an exact completion receipt")
            results = [result for result in item.action.split_policy.results if result.evidence_activation is not None]
            if results:
                windows = _validated_split_evidence_windows(item.split_evidence_windows)
                if [window.result_object_id for window in windows] != [result.object_id for result in results]:
                    raise ValueError("resolved Split evidence windows change exact result coverage")
                for result, window in zip(results, windows, strict=True):
                    treatment = expected_split_treatments[(item.action.action_id, result.object_id)]
                    expected = _expected_split_evidence_window(item, result, treatment)
                    if (window.model_dump(mode="json") != expected
                            or not any(activation.board_id == item.action.board_id
                                       and activation.start_ms <= item.start_ms
                                       and max(item.end_ms, expected["readable_hold_end_ms"]) <= activation.end_ms
                                       for activation in layout.activations)):
                        raise ValueError("Split evidence construction and readable hold require one actual active-board window")
    validate_resolved_hierarchy(layout, resolved)


def validate_resolved_hierarchy(layout: ExecutableLayoutV2, resolved: ResolvedVisualTimelineV2) -> None:
    """Bind the initial structural receipt and empty-shell owner at both entry paths.

    This verifies initial identity, not later action-boundary source equality.
    Earlier actions on unrelated shells may change the owner's complete basis;
    chronological replay must prove those changes instead of assuming initial.
    """
    objects = {obj.object_id: obj for obj in layout.objects}
    for item in resolved.actions:
        receipt = item.return_hierarchy_receipt
        if receipt is not None:
            owned = {key for key, obj in objects.items() if obj.board_id == receipt.destination_board_id}
            if ({placement.object_id for placement in receipt.hierarchy_basis.placements} != owned
                    or set(item.action.expected_object_states or {}) != owned
                    or set(item.action.expected_object_state_versions or {}) != owned):
                raise ValueError("return hierarchy receipt must cover the exact layout board inventory")
    if layout.initial_empty_group_ownership and resolved.initial_hierarchy_basis is None:
        raise ValueError("owned empty groups require an explicit resolved initial hierarchy")
    if resolved.initial_hierarchy_basis is not None:
        from atme.render.v2_hierarchy import HierarchySnapshot

        hierarchy = HierarchySnapshot.from_objects(objects)
        expected = HierarchyBasis(placements=[{
            "object_id": node.object_id, "board_id": node.board_id, "parent_id": node.parent_id,
            "sibling_ordinal": node.sibling_ordinal, "local_transform": objects[node.object_id].transform,
        } for node in hierarchy.nodes])
        if resolved.initial_hierarchy_basis != expected:
            raise ValueError("resolved initial hierarchy must match exact layout parents, sibling order and local transforms")
    for owner in layout.initial_empty_group_ownership:
        candidates = [(item.end_ms, index, item.action) for index, item in enumerate(resolved.actions)
                      if isinstance(item.action, GroupAction) and item.action.container_id == owner.shell_object_id]
        action = min(candidates, key=lambda item: item[:2])[2] if candidates else None
        if (action is None or action.action_id != owner.owner_group_action_id
                or action.verb != "group" or action.hierarchy_policy is None
                or action.hierarchy_policy.source_basis_sha256 != owner.owner_source_basis_sha256):
            raise ValueError("empty group owner must be its earliest resolved hierarchy action with the exact source hash")


def _require_hierarchy_contract(action: GroupAction) -> None:
    policy = action.hierarchy_policy
    states = (("ungrouped", "grouped") if action.verb == "group" else ("grouped", "ungrouped"))
    if (action.verb not in {"group", "ungroup"} or policy is None
            or action.container_id is None or action.container_id in action.target_ids
            or action.target_ids != policy.member_root_ids or action.easing != "step"
            or (action.expected_state, action.post_state) != states):
        raise ValueError("group/ungroup needs an exact authored step hierarchy policy and canonical group states")
    source = {item.object_id: item for item in policy.source_basis.placements}
    destination = {item.object_id: item for item in policy.destination_basis.placements}
    container = source.get(action.container_id)
    other = destination.get(action.container_id)
    if (container is None or container.board_id != action.board_id or other is None
            or container.parent_id != other.parent_id
            or container.local_transform != other.local_transform):
        raise ValueError("group shell placement and local transform must remain unchanged")
    for object_id in action.target_ids:
        before, after = source[object_id], destination[object_id]
        expected_parents = ((container.parent_id, action.container_id) if action.verb == "group"
                            else (action.container_id, container.parent_id))
        if (before.board_id != action.board_id
                or (before.parent_id, after.parent_id) != expected_parents):
            raise ValueError("hierarchy members must transfer exactly between the shell and its sibling parent")
    for basis, grouped in ((policy.source_basis, action.verb == "ungroup"),
                           (policy.destination_basis, action.verb == "group")):
        children = [item.object_id for item in sorted(basis.placements, key=lambda item: item.sibling_ordinal)
                    if item.parent_id == action.container_id]
        if children != (action.target_ids if grouped else []):
            raise ValueError("hierarchy group shell needs the exact ordered member inventory")


def _require_return_contract(action: EvidenceAction) -> None:
    if (action.source_board_id is None or action.source_activation_id is None
            or action.prior_destination_activation_id is None
            or action.destination_activation_id is None
            or action.expected_object_states is None
            or action.expected_object_state_versions is None
            or not action.expected_object_states
            or set(action.expected_object_states) != set(action.expected_object_state_versions)
            or any(not state for state in action.expected_object_states.values())
            or any(version < 1 for version in action.expected_object_state_versions.values())
            or action.easing != "step" or action.expected_state is None
            or action.post_state != action.destination_state
            or action.evidence_asset_id is not None or action.target_object_id is not None):
        raise ValueError("return_board needs complete activation and retained-state provenance")


def _require_return_board_policy(board: BoardSpec) -> None:
    if (board.persistence_policy != "returnable"
            or board.activation_policy not in {"returnable", "persistent"}
            or not board.return_reason or not board.return_reason.strip()
            or not board.expected_prior_state):
        raise ValueError(f"board {board.board_id} has no declared returnable policy")


def _require_composition_bindings(objects):
    for obj in objects:
        if obj.object_type in {"composition", "instance"} and getattr(obj, "composition_binding", None) is None:
            raise ValueError("new composition/instance writes require an exact explicit expansion binding")


def _composition_owners(objects):
    members, definitions = set(), {}
    for obj in objects.values():
        binding = getattr(obj, "composition_binding", None)
        if binding is None:
            continue
        spec = binding.instance
        ids = {row.object_id for row in spec.object_map}
        key = (spec.definition.definition_id, spec.definition.revision)
        if (members & ids or not ids <= objects.keys()
                or definitions.get(key, spec.definition_sha256) != spec.definition_sha256):
            raise ValueError("composition requires disjoint complete members and immutable definition revisions")
        members.update(ids)
        definitions[key] = spec.definition_sha256
        yield obj, binding


def _validate_composition_objects(objects):
    from atme.render.v2_composition import validate_composition_binding_objects

    for _owner, binding in _composition_owners(objects):
        validate_composition_binding_objects(binding, objects)


def _semantic_composition_view(objects):
    """Validation-only Group view, never a persisted rewrite or broad alias.

    Every initial member stays individually authored and counted. Native root
    metadata is pinned by materialization, not guessed from an opaque name.
    """
    from atme.render.v2_composition import materialize_composition

    view, expansions = dict(objects), []
    for owner, binding in _composition_owners(objects):
        spec = binding.instance
        expected = materialize_composition(spec.model_dump(mode="json"))
        root = next(obj for obj in expected if obj.object_id == spec.root_object_id)
        raw = owner.model_dump(mode="json")
        raw.pop("composition_binding")
        raw["object_type"] = "group"
        for field in ("character_assembly", "illustration_assembly"):
            if getattr(root, field) is not None:
                raw[field] = getattr(root, field).model_dump(mode="json")
        view[owner.object_id] = SemanticStandardObjectSpec.model_validate(raw)
        expansions.append((spec, expected))
    if not expansions:
        return view
    parents = _semantic_group_parents(view)
    fields = set(SemanticStandardObjectSpec.model_fields)
    for spec, expected in expansions:
        for obj in expected:
            actual = view[obj.object_id]
            expected_document = obj.model_dump(mode="json")
            semantic_document = {key: value for key, value in expected_document.items() if key in fields}
            if isinstance(obj, ConnectorObject) and (
                    obj.source_point is not None or getattr(actual, "connector_binding", None) is not None):
                # The independent definition, not the submitted semantic member
                # or executable layout, owns the comparison authority. Named
                # legacy connectors keep their omitted wrapper on history loads;
                # normal new network writes separately require explicit binding.
                semantic_document["connector_binding"] = {
                    key: expected_document[key] for key in (
                        "source_object_id", "source_anchor_id", "destination_object_id",
                        "destination_anchor_id", "role", "routing", "allow_self_loop")}
                if obj.source_point is not None:
                    semantic_document["connector_binding"]["source_point"] = expected_document["source_point"]
            projection = SemanticStandardObjectSpec.model_validate(semantic_document) if obj.object_type != "mask" else SemanticMaskObjectSpec.model_validate({
                key: value for key, value in obj.model_dump(mode="json").items()
                if key in SemanticMaskObjectSpec.model_fields
            })
            if actual.model_dump(mode="json") != projection.model_dump(mode="json") or parents[obj.object_id] != obj.parent_id:
                raise ValueError("semantic composition changes an exact expanded member or parent")
    return view


def _semantic_group_parents(objects):
    """Explicit membership only; never infer initial parents from later receipts."""
    if any(getattr(obj, "composition_binding", None) is not None for obj in objects.values()):
        objects = _semantic_composition_view(objects)
    parents = {key: None for key in objects}
    for obj in objects.values():
        members = getattr(obj, "child_ids", None)
        if members is None:
            continue
        if obj.object_type not in {"group", "clip", "mask"}:
            raise ValueError("semantic group membership belongs only to groups")
        for key in members:
            if key not in objects or objects[key].board_id != obj.board_id:
                raise ValueError("semantic group membership requires existing same-board child_ids")
            if parents[key] is not None:
                raise ValueError("semantic group membership permits only one parent per child")
            parents[key] = obj.object_id
    for key in objects:
        seen = {key}
        parent = parents[key]
        while parent is not None:
            if parent in seen or len(seen) > 8:
                raise ValueError("semantic group ancestry is cyclic or exceeds eight parents")
            seen.add(parent)
            parent = parents[parent]
    return parents


def _validate_external_aperture_references(objects, parents, *, captured_subset=None):
    """Validate new semantic read edges without admitting their runtime paint.

    Legacy layout-only references stay at the trusted history seam. New reads
    name real nonempty owners; they neither inherit membership nor borrow a
    protected component/role. Parent pose and dedicated Mask source reads form
    one dependency DAG, separate from the ordinary ownership tree.
    """
    references = {key: obj.clip_id for key, obj in objects.items() if getattr(obj, "clip_id", None) is not None}
    if not references:
        return set()

    def ancestors(key):
        result = []
        parent = parents[key]
        while parent is not None:
            result.append(parent)
            parent = parents[parent]
        return result

    def closure(key):
        selected, pending = set(), [key]
        while pending:
            current = pending.pop()
            if current not in selected:
                selected.add(current)
                pending.extend(captured_subset.present_children(current, objects) if captured_subset is not None
                               else (getattr(objects[current], "child_ids", None) or []))
        return selected

    protected = set()
    for key, obj in objects.items():
        if any(getattr(obj, field, None) is not None for field in (
                "composition_binding", "character_assembly", "illustration_assembly")):
            protected.update(closure(key))
        for field in ("technical_frame", "structured_list"):
            binding = getattr(obj, field, None)
            if binding is not None:
                protected.update(closure(binding.container_group_id))
    mask_sources = {obj.mask_source_object_id for obj in objects.values()
                    if obj.object_type == "mask" and obj.mask_source_object_id is not None}
    participants = set()
    for consumer_id, owner_id in references.items():
        consumer, owner = objects[consumer_id], objects.get(owner_id)
        if (consumer.object_type in {"clip", "mask", "arrow", "composition", "instance"}
                or consumer.object_type == "group" and not consumer.child_ids):
            raise ValueError("external aperture consumer requires an ordinary leaf or explicit nonempty Group subtree")
        if consumer_id in mask_sources:
            raise ValueError("external aperture cannot use a dedicated mask source as consumer")
        if (owner is None or owner.object_type not in {"clip", "mask"}
                or not getattr(owner, "child_ids", None) or owner.board_id != consumer.board_id):
            raise ValueError("external aperture requires an explicit nonempty same-board Clip/Mask owner")
        if owner.object_type == "mask" and owner.mask_source_object_id is None:
            raise ValueError("external aperture requires a Mask's explicit dedicated geometry source")
        if (consumer_id == owner_id or owner_id in ancestors(consumer_id)
                or consumer_id in ancestors(owner_id)):
            raise ValueError("external aperture must cross disjoint ownership closures, not ancestors or descendants")
        if getattr(owner, "clip_id", None) is not None:
            raise ValueError("external aperture cannot borrow a nested external reference chain")
        if (consumer_id in protected or owner_id in protected
                or owner.object_type == "mask" and owner.mask_source_object_id in protected):
            raise ValueError("external aperture cannot borrow protected component or role ownership")
        roots = [consumer_id, owner_id]
        if owner.object_type == "mask":
            roots.append(owner.mask_source_object_id)
        for key in roots:
            participants.update(closure(key))
            participants.update(ancestors(key))

    dependencies = {key: [parents[key]] if parents[key] is not None else [] for key in objects}
    for key, owner in references.items():
        dependencies[key].append(owner)
    for key, obj in objects.items():
        if obj.object_type == "mask" and obj.mask_source_object_id is not None:
            dependencies[key].append(obj.mask_source_object_id)
    # Iterative tri-colour DFS: a long read chain must not exhaust Python's stack.
    active, finished = set(), set()
    for key in objects:
        pending = [(key, False)]
        while pending:
            current, leaving = pending.pop()
            if leaving:
                active.remove(current)
                finished.add(current)
            elif current not in finished:
                if current in active:
                    raise ValueError("external aperture read dependency graph must be acyclic")
                active.add(current)
                pending.append((current, True))
                pending.extend((dependency, False) for dependency in dependencies[current])
    return participants


def validate_character_assembly_map(objects):
    """Authenticate the actual hierarchy map without inferring pose or readiness.

    Callers supply the current hierarchy's reciprocal child order, not an initial
    layout substituted for a sampled map. Ordinary leaf state/geometry is free
    to animate; authored identities and role/anchor ownership are not.
    """
    _validate_character_assemblies(objects, semantic=False)


def _validate_character_assemblies(objects, *, semantic):
    """Real authored marks/groups and exact descendant anchor correspondence."""
    actors = [obj for obj in objects.values() if getattr(obj, "character_assembly", None) is not None]
    if not actors:
        return
    if any(key != obj.object_id for key, obj in objects.items()):
        raise ValueError("character_assembly requires exact current object-map identities")
    parents = _semantic_group_parents(objects) if semantic else {key: obj.parent_id for key, obj in objects.items()}
    mark_types = {"freehand", "line", "rectangle", "rounded_rectangle", "ellipse", "polygon",
                  "bracket", "underline", "highlight"}
    for actor in actors:
        binding = actor.character_assembly
        expected = [row.object_id for row in binding.roles]
        if (actor.object_type != "group" or not semantic and type(actor) is not GroupContainer
                or actor.child_ids != expected
                or actor.object_id in expected or any(key not in objects for key in expected)):
            raise ValueError("character_assembly requires one exact real Group with ordered role roots")
        selected = {actor.object_id}

        def visit(key, parent, depth, *, selected=selected, actor=actor):
            if key not in objects or key in selected or depth > 8:
                raise ValueError("character_assembly needs complete disjoint finite role closures")
            selected.add(key)
            part = objects[key]
            if (part.object_id != key or not semantic and type(part) not in {GroupContainer, MarkObject}
                    or parents.get(key) != parent or part.board_id != actor.board_id
                    or part.beat_id != actor.beat_id or part.coverage_ids != actor.coverage_ids):
                raise ValueError("character_assembly roles must preserve reciprocal ownership and board/beat/coverage")
            if getattr(part, "character_assembly", None) is not None:
                raise ValueError("character_assembly cannot borrow a nested character assembly")
            if part.object_type == "group":
                children = part.child_ids
                if not children or any(child not in objects for child in children):
                    raise ValueError("character_assembly role Group needs explicit real children")
                ordered(children)
                reciprocal(key, children)
                for child in children:
                    visit(child, key, depth + 1)
            elif part.object_type not in mark_types:
                raise ValueError("character_assembly roles require actual authored Mark/Group content")

        def ordered(children):
            if not semantic and children != sorted(children, key=lambda child_id: (objects[child_id].z_index, child_id)):
                raise ValueError("character_assembly must preserve explicit real paint order")

        def reciprocal(key, children):
            if not semantic and set(children) != {child for child, obj in objects.items() if obj.parent_id == key}:
                raise ValueError("character_assembly requires complete reciprocal child inventory")

        ordered(expected)
        reciprocal(actor.object_id, expected)
        role_members = {}
        for role in binding.roles:
            prior = set(selected)
            visit(role.object_id, actor.object_id, 1)
            role_members[role.role] = selected - prior
        for anchor in binding.semantic_anchors:
            if anchor.object_id not in selected or anchor.object_id == actor.object_id:
                raise ValueError("character_assembly semantic anchor needs its exact real role descendant")
            if anchor.object_id not in role_members[dict(CHARACTER_SEMANTIC_ROLES)[anchor.semantic_name]]:
                raise ValueError("character_assembly semantic anchor must belong to its declared role closure")
            part = objects[anchor.object_id]
            if part.object_type == "group":
                raise ValueError("character_assembly does not infer Group anchors")
            if not semantic:
                ids = [row.anchor_id for row in part.anchors]
                if len(ids) != len(set(ids)) or anchor.anchor_id not in ids:
                    raise ValueError("character_assembly semantic anchor needs an exact authored anchor ID")


def validate_illustration_assembly_map(objects):
    """Authenticate real sampled role ownership, without deriving content/state."""
    for obj in objects.values():
        binding = getattr(obj, "illustration_assembly", None)
        if binding is None:
            continue
        if (type(binding) is not IllustrationAssemblyBinding
                or type(binding.roles) is not list or type(binding.semantic_anchors) is not list
                or any(type(role) is not IllustrationRoleBinding for role in binding.roles)
                or any(type(anchor) is not IllustrationAnchorBinding for anchor in binding.semantic_anchors)):
            raise ValueError("illustration_assembly requires exact known authored binding types")
        try:
            IllustrationAssemblyBinding.model_validate(binding.model_dump(mode="json"))
        except ValueError as exc:
            raise ValueError(f"illustration_assembly invalid current binding: {exc}") from exc
    _validate_illustration_assemblies(objects, semantic=False)


def _validate_illustration_assemblies(objects, *, semantic):
    """Authenticate real authored layers; registry bytes remain P3-34's gate."""
    assemblies = [obj for obj in objects.values() if getattr(obj, "illustration_assembly", None) is not None]
    if not assemblies:
        return
    if any(key != obj.object_id for key, obj in objects.items()):
        raise ValueError("illustration_assembly requires exact current object identities")
    parents = _semantic_group_parents(objects) if semantic else {key: obj.parent_id for key, obj in objects.items()}
    mark_types = {"freehand", "line", "rectangle", "rounded_rectangle", "ellipse", "polygon",
                  "bracket", "underline", "highlight"}
    for assembly in assemblies:
        binding = assembly.illustration_assembly
        expected = [row.object_id for row in binding.roles]
        if (assembly.object_type != "group" or not semantic and type(assembly) is not GroupContainer
                or getattr(assembly, "character_assembly", None) is not None
                or assembly.child_ids != expected or assembly.object_id in expected
                or any(key not in objects for key in expected)):
            raise ValueError("illustration_assembly requires one distinct real Group and exact ordered role roots")
        selected = {assembly.object_id}

        def ordered(key, children):
            if not children or len(set(children)) != len(children) or any(child not in objects for child in children):
                raise ValueError("illustration_assembly requires complete distinct real children")
            if not semantic and (children != sorted(children, key=lambda child: (objects[child].z_index, child))
                    or set(children) != {child for child, obj in objects.items() if obj.parent_id == key}):
                raise ValueError("illustration_assembly requires reciprocal explicit paint order")

        def visit(key, parent, depth, *, selected=selected, assembly=assembly):
            if key not in objects or key in selected or depth > 8:
                raise ValueError("illustration_assembly needs complete disjoint finite role closures")
            selected.add(key)
            part = objects[key]
            if (part.object_id != key or parents.get(key) != parent or part.board_id != assembly.board_id
                    or part.beat_id != assembly.beat_id or part.coverage_ids != assembly.coverage_ids):
                raise ValueError("illustration_assembly must preserve exact reciprocal board/beat/coverage ownership")
            if any(getattr(part, field, None) is not None for field in (
                    "illustration_assembly", "character_assembly", "technical_frame")):
                raise ValueError("illustration_assembly cannot borrow a separately bound assembly or technical subtree")
            if part.object_type == "group":
                if not semantic and type(part) is not GroupContainer:
                    raise ValueError("illustration_assembly needs real Group subtrees")
                ordered(key, part.child_ids)
                for child in part.child_ids:
                    visit(child, key, depth + 1)
            elif part.object_type in mark_types | {"text", "code"}:
                if not semantic and type(part) not in {MarkObject, TextObject}:
                    raise ValueError("illustration_assembly needs actual Mark/Text/Code content")
            elif part.object_type in REGISTRY_BOUND_OBJECT_TYPES:
                # Presence is structural, not proof of bytes/physical anchors.
                # Normal-write and renderer resource validation stay mandatory.
                if (getattr(part, "registry_binding", None) is None
                        or not semantic and type(part) is not VisualObject):
                    raise ValueError("illustration_assembly registry leaves need their own exact registry_binding")
            else:
                raise ValueError("illustration_assembly needs real authored content, not inferred parts")

        ordered(assembly.object_id, expected)
        members = {}
        for role in binding.roles:
            prior = set(selected)
            visit(role.object_id, assembly.object_id, 1)
            members[role.role_id] = selected - prior
            if role.kind == "label" and not any(objects[key].object_type in {"text", "code"}
                                                 for key in members[role.role_id]):
                raise ValueError("illustration_assembly label role requires real Text/Code content")
        for anchor in binding.semantic_anchors:
            if anchor.object_id not in members[anchor.role_id]:
                raise ValueError("illustration_assembly semantic anchor must belong to its exact declared role closure")
            part = objects[anchor.object_id]
            if part.object_type == "group":
                raise ValueError("illustration_assembly never infers Group anchors")
            if not semantic:
                ids = [row.anchor_id for row in part.anchors]
                if len(ids) != len(set(ids)) or anchor.anchor_id not in ids:
                    raise ValueError("illustration_assembly needs exact unique authored leaf anchor IDs")


def _validate_technical_frames(objects, *, semantic):
    """Explicit real Group closure only; geometry is a separate runtime gate."""
    chromes = [obj for obj in objects.values() if getattr(obj, "technical_frame", None) is not None]
    if not chromes:
        return
    parents = _semantic_group_parents(objects) if semantic else {key: obj.parent_id for key, obj in objects.items()}
    owners = set()
    for chrome in chromes:
        binding = chrome.technical_frame
        group = objects.get(binding.container_group_id)
        expected = [chrome.object_id, *[row.object_id for row in binding.roles]]
        if (group is None or group.object_type != "group"
                or group.object_id in owners or group.child_ids != expected):
            raise ValueError("technical_frame requires one exact real Group with ordered chrome/role roots")
        owners.add(group.object_id)
        selected = {group.object_id}

        def visit(key, path, *, selected=selected, chrome=chrome):
            obj = objects.get(key)
            if obj is None or key in selected or key in path or len(path) > 8:
                raise ValueError("technical_frame requires complete disjoint authored role closures")
            selected.add(key)
            if (obj.board_id != chrome.board_id or obj.beat_id != chrome.beat_id
                    or obj.coverage_ids != chrome.coverage_ids):
                raise ValueError("technical_frame closure must preserve exact board/beat/coverage")
            children = getattr(obj, "child_ids", None)
            if obj.object_type in {"group", "clip", "mask", "composition", "instance"}:
                if obj.object_type != "group" or not children:
                    raise ValueError("technical_frame role subtrees require explicitly authored Groups")
                if not semantic and children != sorted(children, key=lambda child: objects[child].z_index):
                    raise ValueError("technical_frame subtree must preserve explicit paint order")
                for child in children:
                    if parents.get(child) != key:
                        raise ValueError("technical_frame role subtree requires reciprocal actual ownership")
                    visit(child, {*path, key})

        if (group.board_id != chrome.board_id or group.beat_id != chrome.beat_id
                or group.coverage_ids != chrome.coverage_ids):
            raise ValueError("technical_frame containing Group must preserve exact board/beat/coverage")
        if not semantic and expected != sorted(expected, key=lambda key: objects[key].z_index):
            raise ValueError("technical_frame chrome/roles must preserve explicit paint order")
        for key in expected:
            if parents.get(key) != group.object_id:
                raise ValueError("technical_frame requires reciprocal chrome/role ownership")
            visit(key, set())
        for row in binding.roles:
            obj = objects[row.object_id]
            kinds = {"text"} if row.role in {"title", "address", "left_title", "right_title"} else {"text", "group"}
            if obj.object_type not in kinds:
                raise ValueError("technical_frame role requires real plain Text or authored Group content")
            if not semantic and isinstance(obj, TextObject) and (not obj.text.strip() or obj.items):
                raise ValueError("technical_frame text role must contain real nonblank authored text")


def _validate_structured_lists(objects, *, semantic):
    """One authoritative real-item binding and authored Group graph.

    Semantic order is declared membership order; executable order is actual
    flattened paint order. Layout comparison separately binds the same payload.
    """
    headings = [obj for obj in objects.values() if getattr(obj, "structured_list", None) is not None]
    if not headings:
        return
    parents = _semantic_group_parents(objects) if semantic else {key: obj.parent_id for key, obj in objects.items()}
    item_owners = {}
    container_owners = {}
    line_breaks = frozenset("\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029")
    for heading in headings:
        payload = heading.structured_list
        root = objects.get(payload.container_group_id)
        if root is None or root.object_type != "group" or root.board_id != heading.board_id:
            raise ValueError("structured_list requires its exact existing same-board Group")
        if root.object_id in container_owners:
            raise ValueError("structured_list container requires one exact heading owner")
        container_owners[root.object_id] = heading.object_id
        selected = {heading.object_id, *payload.item_object_ids}
        for key in selected:
            obj = objects.get(key)
            if obj is None or obj.board_id != heading.board_id:
                raise ValueError("structured_list requires every real item on the heading's board")
            if key != heading.object_id:
                if obj.object_type != "text":
                    raise ValueError("structured_list item IDs require plain authored text objects")
                if key in item_owners:
                    raise ValueError("structured_list item has more than one owner")
                item_owners[key] = heading.object_id
                if not semantic and not obj.anchors:
                    raise ValueError("structured_list items require at least one authored anchor")
            if not semantic and (
                not isinstance(obj, TextObject) or obj.items or not obj.text.strip()
                or any(char in line_breaks for char in obj.text)
            ):
                raise ValueError("structured_list requires one-line nonblank heading and real item text")
            seen = {key}
            parent = parents[key]
            while parent != root.object_id:
                if parent is None or parent not in objects or parent in seen or len(seen) > 8:
                    raise ValueError("structured_list needs complete explicit heading/item Group ancestry")
                if objects[parent].object_type != "group":
                    raise ValueError("structured_list nesting requires explicitly authored Groups")
                seen.add(parent)
                parent = parents[parent]
        if semantic:
            def visit(key):
                obj = objects[key]
                if obj.object_type == "group":
                    members = obj.child_ids
                    if members is None:
                        raise ValueError("structured_list needs explicit semantic Group child_ids")
                    return [leaf for child in members for leaf in visit(child)]
                return [key]

            order = visit(root.object_id)
        else:
            order = _layout_leaf_paint_order(objects, heading.board_id)
        if [key for key in order if key in selected] != [heading.object_id, *payload.item_object_ids]:
            raise ValueError("structured_list must preserve exact authored flattened heading/item order")


def _callout_hidden_compound_pair(callout, leader, objects):
    """A locally ready child behind an explicitly authored hidden Group root.

    Local child state stays immutable; the separate pointer is not constructed
    until the shared chronology proves effective endpoint readiness.
    """
    if callout.initial_state != "visible" or leader.initial_state != "hidden":
        return False
    if isinstance(callout, TextObject):
        if not callout.visible or leader.visible:
            return False
        parents = {key: obj.parent_id for key, obj in objects.items()}
    else:
        parents = _semantic_group_parents(objects)
    if parents[leader.object_id] is not None:
        return False
    seen, hidden = {callout.object_id}, False
    child = callout.object_id
    parent = parents[child]
    while parent is not None:
        if parent in seen or parent not in objects or len(seen) > 8:
            raise ValueError("callout compound ancestry is missing or cyclic")
        obj = objects[parent]
        if obj.object_type != "group" or obj.board_id != callout.board_id:
            return False
        if child not in obj.child_ids:
            raise ValueError("callout compound ancestry requires exact declared group membership")
        if isinstance(callout, TextObject):
            if obj.opacity <= 0 or not obj.visible and obj.initial_state != "hidden":
                return False
            hidden |= not obj.visible and obj.initial_state == "hidden"
        else:
            hidden |= obj.initial_state == "hidden"
        seen.add(parent)
        child, parent = parent, parents[parent]
    return hidden


def _callout_leader_owners(objects):
    owners = {}
    for callout in objects.values():
        binding = getattr(callout, "callout_binding", None)
        if binding is None:
            continue
        if binding.leader_connector_id in owners:
            raise ValueError("callout pointer must have exactly one owner")
        leader = objects.get(binding.leader_connector_id)
        target = objects.get(binding.target_object_id)
        if (leader is None or leader.object_type != "arrow" or target is None
                or target.object_type in {"arrow", "network", "evidence", "group", "clip", "mask", "composition", "instance"}
                or leader.board_id != callout.board_id or target.board_id != callout.board_id
                or leader.beat_id != callout.beat_id
                or leader.coverage_ids != callout.coverage_ids
                or len(set(callout.coverage_ids)) != len(callout.coverage_ids)):
            raise ValueError("callout_binding needs exact declared arrow, target, board, beat and coverage ownership")
        shadowed = _callout_hidden_compound_pair(callout, leader, objects)
        if leader.initial_state != callout.initial_state and not shadowed:
            raise ValueError("callout and leader must have paired initial state")
        if isinstance(callout, TextObject) and (
            callout.visible != leader.visible and not shadowed or callout.opacity <= 0 or leader.opacity <= 0
        ):
            raise ValueError("callout and leader need paired initial visibility and positive opacity")
        owners[leader.object_id] = callout
    return owners


def _plan_evidence_annotations(plan):
    actions = {action.action_id: action for action in plan.actions}
    ordinary = [(actions[action_id].target_object_id, beat.evidence)
            for beat in plan.beats if beat.evidence is not None and beat.evidence.annotation_policy is not None
            for action_id in beat.action_ids
            if isinstance(actions[action_id], EvidenceAction) and actions[action_id].verb == "insert_evidence"]
    split = [(result.object_id, result.evidence_activation.intent)
             for action in plan.actions if isinstance(action, SplitAction) and action.split_policy is not None
             for result in action.split_policy.results if result.evidence_activation is not None
             and result.evidence_activation.intent.annotation_policy is not None]
    return [*ordinary, *split]


def _plan_split_evidence_rows(plan):
    """New-write/layout authority only; no fake insert and no runtime attestation."""
    objects = {obj.object_id: obj for obj in plan.objects}
    owners = {action_id: beat for beat in plan.beats for action_id in beat.action_ids}
    for action in plan.actions:
        if not isinstance(action, SplitAction) or action.split_policy is None:
            continue
        for result in action.split_policy.results:
            obj = objects[result.object_id]
            if obj.object_type != "evidence":
                continue
            if result.evidence_activation is None:
                raise ValueError("new Split evidence results require an explicit evidence_activation")
            yield owners[action.action_id], obj, action, result.evidence_activation.intent


def _annotation_compound_members(objects):
    roots = set()
    for obj in objects.values():
        if any(getattr(obj, name, None) is not None for name in (
                "composition_binding", "character_assembly", "illustration_assembly")):
            roots.add(obj.object_id)
        for name in ("technical_frame", "structured_list"):
            binding = getattr(obj, name, None)
            if binding is not None:
                roots.add(binding.container_group_id)
    protected, pending = set(), list(roots)
    while pending:
        key = pending.pop()
        if key not in protected:
            protected.add(key)
            pending.extend(getattr(objects[key], "child_ids", None) or [])
    return protected


def _validate_evidence_annotation_ownership(objects, evidence_annotations, actions=()):
    claimed = set()
    leaders = set()
    competing = set(_callout_leader_owners(objects)) | _annotation_compound_members(objects)
    for action in actions:
        if isinstance(action, TargetAction) and action.annotation_policy is not None:
            competing.update(_annotation_object_ids(action))
    for source_id, intent in evidence_annotations:
        policy = intent.annotation_policy
        if policy is None:
            continue
        ids = set(_annotation_policy_object_ids(policy))
        _subset(ids, set(objects), "evidence annotation objects")
        if ids & (claimed | competing):
            raise ValueError("evidence annotation objects require exclusive authored ownership")
        claimed.update(ids)
        leaders.add(policy.leader_connector_id)
        leader = objects[policy.leader_connector_id]
        if getattr(leader, "connector_binding", None) is not None or getattr(leader, "source_point", None) is not None:
            raise ValueError("owned evidence pointer cannot carry competing connector authority")
    if any(isinstance(action, ConnectionAction) and action.connector_id in leaders for action in actions):
        raise ValueError("owned evidence pointer cannot be managed as a semantic connection")
    return leaders


def _validate_callout_ownership(objects, actions, evidence_annotations=()):
    """Normal-write ownership, preserving repeated legacy annotation policies."""
    callouts = _callout_leader_owners(objects)
    annotations = {action.annotation_policy.leader_connector_id for action in actions
                   if isinstance(action, TargetAction) and action.verb == "annotate"
                   and action.annotation_policy is not None
                   and action.annotation_policy.leader_connector_id is not None}
    if set(callouts).intersection(annotations):
        raise ValueError("callout and annotation cannot both own a pointer")
    evidence_leaders = _validate_evidence_annotation_ownership(objects, evidence_annotations, actions)
    owners = set(callouts) | annotations | evidence_leaders
    for key in owners:
        obj = objects[key]
        if (getattr(obj, "connector_binding", None) is not None
                or getattr(obj, "source_point", None) is not None):
            raise ValueError("owned pointer cannot carry competing connector_binding or source_point")
    for obj in objects.values():
        if (isinstance(obj, ConnectorObject) and obj.role == "pointer"
                and obj.object_id not in owners and obj.source_point is None):
            raise ValueError("pointer has no explicit annotation or callout owner")
    if any(isinstance(action, ConnectionAction) and action.connector_id in owners for action in actions):
        raise ValueError("owned pointer cannot be managed as a semantic connection")


def _validate_callout_layout_references(objects, profile, style_version, registry_version):
    from atme.render.style_bundle import resolve_contract_bundle
    from atme.render.v2_callout_pointer import (
        callout_pointer_geometry,
        validate_callout_pointer,
    )
    from atme.render.v2_world import world_anchor

    owners = _callout_leader_owners(objects)
    if not owners:
        return
    style, _, _ = resolve_contract_bundle(style_version, registry_version)
    aspect = "landscape-16:9" if profile.profile_id == "LONG_FORM_16_9" else "portrait-9:16"
    design = style.aspects[aspect]
    scale = profile.width / design.width
    if abs(scale - profile.height / design.height) > 1e-6:
        raise ValueError("callout pointer needs uniform authored profile scaling")
    transforms = {key: obj.transform for key, obj in objects.items()}
    for leader_id, callout in owners.items():
        binding = callout.callout_binding
        leader = objects[leader_id]
        if (not isinstance(leader, ConnectorObject) or leader.role != "pointer"
                or leader.source_object_id != callout.object_id
                or leader.source_anchor_id != binding.callout_anchor_id
                or leader.destination_object_id != binding.target_object_id
                or leader.destination_anchor_id != binding.target_anchor_id):
            raise ValueError("callout_binding must match the exact pointer source and destination anchors")
        validate_callout_pointer(leader, objects)
        for endpoint in (callout, objects[binding.target_object_id]):
            if endpoint.clip_id is not None:
                raise ValueError("callout pointer endpoints require unclipped group ancestry")
            parent = endpoint.parent_id
            while parent is not None:
                if objects[parent].object_type != "group":
                    raise ValueError("callout pointer endpoints require unclipped group ancestry")
                parent = objects[parent].parent_id
        order = _layout_leaf_paint_order(objects, callout.board_id)
        target_id = binding.target_object_id
        if target_id not in order or any(key not in order or order.index(key) <= order.index(target_id)
                                         for key in (callout.object_id, leader_id)):
            raise ValueError("callout and leader must paint above their target")
        start = world_anchor(callout, binding.callout_anchor_id, objects, transforms)
        end = world_anchor(objects[target_id], binding.target_anchor_id, objects, transforms)
        callout_pointer_geometry(leader, objects, transforms, start, end, style.strokes.regular_px * scale)


def _require_chart_payloads(objects):
    """Require data for inline charts, never reinterpret declared static art.

    Only placed objects can distinguish the existing custom-variant artwork
    path: semantic specs deliberately have no variant. Legacy parsing and the
    trusted immutable-history pair-validation switch remain unchanged.
    """
    for obj in objects:
        if (isinstance(obj, VisualObject) and obj.object_type == "chart"
                and obj.chart_payload is None and obj.asset_id is None
                and obj.registry_binding is None and obj.variant is None):
            raise ValueError(f"new inline chart object {obj.object_id} requires a complete chart_payload")


def _require_code_payloads(objects):
    """Normal writes need authored payloads; omission is not legacy provenance.

    The internal compatibility switch remains limited to trusted migration and
    immutable-history validation, never a public new-write escape hatch.
    """
    for obj in objects:
        if obj.object_type == "code" and obj.code_payload is None:
            raise ValueError(f"new code object {obj.object_id} requires a complete code_payload")
        if obj.object_type == "callout" and obj.callout_binding is None:
            raise ValueError(f"new callout object {obj.object_id} requires a complete callout_binding")


def _unique(items, field):
    values = [getattr(x, field) for x in items]
    if len(values) != len(set(values)):
        raise ValueError(f"{field} values must be unique")


def _unique_evidence_claims(treatments):
    claim_ids = [item.intent.claim_id for item in treatments]
    if len(claim_ids) != len(set(claim_ids)):
        raise ValueError("evidence claim IDs must be unique")


def _unique_evidence_treatment_owners(treatments):
    pairs = [(item.action_id, item.object_id) for item in treatments]
    if len(pairs) != len(set(pairs)):
        raise ValueError("evidence treatment action/object pairs must be unique")
    # Multiple results may share one real Split, never multiple owners per object.
    _unique(treatments, "object_id")
    _unique_evidence_claims(treatments)


def _validate_mask_fields(mask):
    values = [getattr(mask, field) for field in MASK_FIELDS]
    if any(value is None for value in values) and not all(value is None for value in values):
        raise ValueError("mask policy must be fully specified or omitted as legacy non-executable")


def _unique_mask_sources(objects):
    sources = [obj.mask_source_object_id for obj in objects
               if obj.object_type == "mask" and obj.mask_source_object_id is not None]
    if len(sources) != len(set(sources)):
        raise ValueError("each mask source must be owned by exactly one mask")


def _validate_mask_layout(objects, object_map):
    _unique_mask_sources(objects)
    for mask in objects:
        if not isinstance(mask, MaskContainer):
            continue
        if mask.mask_source_object_id is None:
            # Existing 2.0.0 masks remain loadable but non-executable.
            continue
        source = object_map.get(mask.mask_source_object_id)
        if (not isinstance(source, MarkObject)
                or source.object_type not in MASK_SOURCE_TYPES
                or source.board_id != mask.board_id
                or source.beat_id != mask.beat_id
                or source.parent_id != mask.parent_id
                or source.clip_id is not None):
            raise ValueError(f"mask {mask.object_id} source must be a dedicated same-parent geometry sibling")
        if (source.object_id in mask.child_ids or not source.visible
                or source.opacity != 1 or source.initial_state != "visible"
                or source.asset_id is not None):
            raise ValueError(f"mask {mask.object_id} source must be static, visible, and outside content")
        if (mask.asset_id is not None or mask.anchors or mask.geometry.points
                or mask.geometry.corner_radius is not None or mask.style.stroke
                or mask.style.fill or mask.style.text or mask.style.effect):
            raise ValueError(f"mask {mask.object_id} must be a non-painting stacking context")


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
            if len(seen) > 9:
                raise ValueError("group/mask/clip nesting exceeds eight ancestor levels")
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
        if action.source_board_id is not None and action.source_board_id not in boards:
            raise ValueError(f"action {action.action_id} references unknown source board")
        if action.evidence_asset_id and action.evidence_asset_id not in assets:
            raise ValueError(f"action {action.action_id} references unknown evidence asset")
    if isinstance(action, SoundAction) and action.asset_id and action.asset_id not in assets:
        raise ValueError(f"action {action.action_id} references unknown sound asset")


def _annotation_phase_windows(resolved):
    return _annotation_policy_phase_windows(resolved.action.annotation_policy, resolved.start_ms, resolved.end_ms)


def _annotation_policy_phase_windows(policy, start_ms, end_ms):
    return _weighted_phase_windows(policy.phases, start_ms, end_ms, "annotation")


def _structured_list_phase_windows(resolved):
    return _weighted_phase_windows(resolved.action.structured_list_policy.phases,
        resolved.start_ms, resolved.end_ms, "structured list")


def _weighted_phase_windows(phases, start_ms, end_ms, label):
    total = sum(phase.weight for phase in phases)
    elapsed = 0
    result = []
    for phase in phases:
        start = start_ms + (end_ms - start_ms) * elapsed // total
        elapsed += phase.weight
        end = start_ms + (end_ms - start_ms) * elapsed // total
        if end <= start:
            raise ValueError(f"{label} weights collapse a construction phase")
        result.append((phase, start, end))
    return tuple(result)


def _validate_annotation_plan_objects(action, objects, beat=None):
    _require_annotation_contract(action)
    _validate_annotation_objects(action.target_ids[0], action.annotation_policy, action.board_id,
                                 objects, beat=beat, coverage_id=action.coverage_id)


def _require_evidence_annotation_policy(source_id, intent):
    if (intent.annotation is not None and intent.annotation_target_id != source_id
            and intent.annotation_policy is None):
        raise ValueError("cross-object evidence annotation requires an authored annotation_policy")


def _validate_evidence_annotation_objects(source_id, intent, objects, *, beat=None, coverage_id=None):
    _require_evidence_annotation_policy(source_id, intent)
    policy = intent.annotation_policy
    if policy is None:
        return
    source = objects.get(source_id)
    if (source is None or source.object_type != "evidence"
            or source.board_id != intent.destination_board_id):
        raise ValueError("evidence annotation requires its exact source object and board")
    _validate_annotation_objects(intent.annotation_target_id, policy, source.board_id, objects,
        beat=beat, coverage_id=coverage_id, source_id=source_id, annotation_text=intent.annotation)
    if hasattr(source, "geometry"):
        _validate_annotation_layout_binding(intent.annotation_target_id, policy, source.board_id, objects,
                                            source_id=source_id)


def _validate_annotation_objects(target_id, policy, board_id, objects, *, beat=None, coverage_id=None,
                                 source_id=None, annotation_text=None):
    _subset([target_id, *_annotation_policy_object_ids(policy)], set(objects), "annotation participants")
    if target_id in _annotation_policy_object_ids(policy) or source_id in _annotation_policy_object_ids(policy):
        raise ValueError("annotation cannot construct its target or evidence source")
    target = objects[target_id]
    if target.board_id != board_id or target.object_type in {
        "evidence", "group", "mask", "clip", "composition", "instance", "network",
    }:
        raise ValueError("general annotation cannot cross boards or bypass evidence treatment")
    notes = [objects[key] for key in policy.annotation_object_ids if objects[key].object_type == "text"]
    if source_id is not None and (len(notes) != 1 or any(
            isinstance(note, TextObject) and note.text != annotation_text for note in notes)):
        raise ValueError("evidence annotation requires one exact authored annotation text")
    for phase in policy.phases:
        obj = objects[phase.object_id]
        allowed = {"text"} if phase.mode == "write" else {
            "freehand", "line", "rectangle", "rounded_rectangle", "ellipse", "polygon", "underline",
        }
        if phase.object_id == policy.leader_connector_id:
            allowed = {"arrow"}
        if (obj.board_id != board_id or obj.initial_state != "hidden"
                or obj.object_type not in allowed or obj.asset_id is not None
                or getattr(obj, "visible", False) or getattr(obj, "opacity", 1) <= 0):
            raise ValueError("annotation phase needs a hidden authored compatible leaf on its board")
        if beat is not None and (obj.beat_id != beat.beat_id
                                 or coverage_id not in obj.coverage_ids
                                 or not set(obj.coverage_ids).issubset(beat.coverage_ids)):
            raise ValueError("annotation objects must preserve action beat and coverage ownership")
        if source_id is not None and (obj.beat_id != objects[source_id].beat_id
                                      or obj.coverage_ids != objects[source_id].coverage_ids):
            raise ValueError("evidence annotation must preserve exact source beat and coverage ownership")
        if isinstance(obj, TextObject) and (not obj.text or not obj.text.strip() or obj.items):
            raise ValueError("annotation needs exact nonblank authored text")
        if isinstance(obj, ConnectorObject):
            sources = policy.annotation_object_ids if source_id is None else [source_id]
            if (obj.role != "pointer" or obj.source_object_id not in sources
                    or obj.destination_object_id != target.object_id or not obj.source_anchor_id
                    or obj.source_object_id == obj.destination_object_id
                    or obj.source_anchor_id not in {anchor.anchor_id for anchor in objects[obj.source_object_id].anchors}
                    or obj.destination_anchor_id not in {anchor.anchor_id for anchor in target.anchors}):
                raise ValueError("annotation leader needs exact annotation-to-target pointer anchors")
            ordered_ids = [phase.object_id for phase in policy.phases]
            if source_id is None and ordered_ids.index(obj.source_object_id) >= ordered_ids.index(obj.object_id):
                raise ValueError("annotation leader must follow construction of its source note")
            from atme.render.v2_connector import validate_static_arrow

            validate_static_arrow(obj, objects, annotation_pointer=True)


def _validate_annotation_layout(action, objects):
    _validate_annotation_layout_binding(action.target_ids[0], action.annotation_policy, action.board_id, objects)


def _validate_annotation_layout_binding(target_id, policy, board_id, objects, *, source_id=None):
    order = _layout_leaf_paint_order(objects, board_id)
    references = [target_id] if source_id is None else [target_id, source_id]
    if any(key not in order for key in references) or any(
        object_id not in order or any(order.index(object_id) <= order.index(key) for key in references)
        for object_id in _annotation_policy_object_ids(policy)
    ):
        raise ValueError("annotation must paint above its target in the effective stacking hierarchy")
    if policy.leader_connector_id:
        from atme.render.v2_world import world_anchor

        leader = objects[policy.leader_connector_id]
        endpoints = (objects[leader.source_object_id], objects[leader.destination_object_id])
        participants = endpoints if source_id is None else (*endpoints,
            *(objects[key] for key in _annotation_policy_object_ids(policy)))
        for obj in participants:
            if source_id is not None and obj.clip_id is not None:
                raise ValueError("evidence annotation requires unclipped group ancestry")
            parent = obj.parent_id
            while parent:
                if objects[parent].object_type != "group":
                    raise ValueError("annotation pointer endpoints require unclipped group ancestry")
                parent = objects[parent].parent_id
        transforms = {object_id: obj.transform for object_id, obj in objects.items()}
        start = world_anchor(endpoints[0], leader.source_anchor_id, objects, transforms)
        end = world_anchor(endpoints[1], leader.destination_anchor_id, objects, transforms)
        bounds = leader.geometry.bounds
        if start == end or any(not (bounds.x <= x <= bounds.x + bounds.width
                                   and bounds.y <= y <= bounds.y + bounds.height) for x, y in (start, end)):
            raise ValueError("annotation pointer world endpoints must fit its authored route bounds")


def _layout_leaf_paint_order(objects, board_id):
    """Authored static tree order; actual replay order remains a runtime proof."""
    children = {}
    for obj in sorted(objects.values(), key=lambda obj: (obj.z_index, obj.object_id)):
        if obj.board_id == board_id:
            children.setdefault(obj.parent_id, []).append(obj)
    mask_sources = {obj.mask_source_object_id for obj in objects.values() if isinstance(obj, MaskContainer)}
    order = []

    def walk(parent_id):
        for obj in children.get(parent_id, ()):
            if isinstance(obj, ContainerObject):
                walk(obj.object_id)
            elif obj.object_id not in mask_sources:
                order.append(obj.object_id)

    walk(None)
    return order


def _annotation_object_ids(action):
    return _annotation_policy_object_ids(action.annotation_policy)


def _annotation_policy_object_ids(policy):
    return policy.annotation_object_ids + ([policy.leader_connector_id] if policy.leader_connector_id else [])


def _require_annotation_contract(action):
    if (action.verb != "annotate" or action.annotation_policy is None
            or len(action.target_ids) != 1 or action.annotation is not None
            or action.expected_state != "visible" or action.post_state != "visible"
            or action.easing == "step"):
        raise ValueError("annotation needs authored objects, one visible target, and continuous construction")
    if action.target_ids[0] in _annotation_object_ids(action):
        raise ValueError("annotation cannot construct its own target")


def _action_object_references(action):
    refs: list[str] = []
    if isinstance(action, (TargetAction, TransformAction, GroupAction, SplitAction, CameraAction)):
        refs.extend(action.target_ids)
        if isinstance(action, TargetAction) and action.structured_list_policy is not None:
            refs.extend((action.structured_list_policy.list_object_id,
                         action.structured_list_policy.container_group_id))
        if isinstance(action, TargetAction) and action.annotation_policy is not None:
            refs.extend(_annotation_object_ids(action))
        if isinstance(action, (GroupAction, SplitAction)) and action.container_id is not None:
            refs.append(action.container_id)
        if isinstance(action, SplitAction) and action.split_policy is not None:
            basis = action.split_policy.source_basis
            for closure in [basis.source_closure, *basis.result_closures]:
                refs.extend(closure.owned_ids)
            for dependency in basis.read_dependencies:
                refs.extend(dependency.object_ids)
    elif isinstance(action, ConnectionAction):
        refs.extend([action.connector_id, action.destination_object_id])
        if action.source_object_id:
            refs.append(action.source_object_id)
    elif isinstance(action, ReplaceAction):
        refs.extend([action.from_object_id, action.to_object_id])
    elif isinstance(action, EvidenceAction) and action.verb == "insert_evidence":
        if action.target_object_id is not None:
            refs.append(action.target_object_id)
    return refs
