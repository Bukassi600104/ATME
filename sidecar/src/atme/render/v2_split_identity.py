"""Immutable Split content identities, independent of placement and paint admission.

Recognizing a stored family here does not enable that family's Split renderer.
Capture and completion verification are separate boundaries.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, fields

from pydantic import BaseModel

from atme.project_assets import VerifiedEvidenceBytes
from atme.render.v2_raster import canonical_png
from atme.render.v2_state import CountFrameObject, FrameObject
from atme.render.v2_timeline_replay import ReplaySample
from atme.store.contracts_v2 import (
    Anchor,
    AnnotationPhase,
    AnnotationPolicy,
    Bounds,
    CalloutBinding,
    CharacterAnchorBinding,
    CharacterAssemblyBinding,
    CharacterRoleBinding,
    ChartAxis,
    ChartBar,
    ChartConstruction,
    ChartHighlight,
    ChartPayload,
    ChartPoint,
    ChartSeries,
    ChartTick,
    ClipContainer,
    CodeLine,
    CodePayload,
    CodeSpan,
    CompositionBinding,
    CompositionBooleanValue,
    CompositionCoverageMapping,
    CompositionDefinition,
    CompositionExpansionMember,
    CompositionInstanceSpec,
    CompositionNumberValue,
    CompositionObjectMapping,
    CompositionOverride,
    CompositionParameterSpec,
    CompositionParameterTarget,
    CompositionParameterValue,
    CompositionStringValue,
    ConnectorObject,
    EvidenceIntent,
    EvidenceTreatment,
    ExecutableLayoutV2,
    Geometry,
    GroupContainer,
    IllustrationAnchorBinding,
    IllustrationAssemblyBinding,
    IllustrationRoleBinding,
    ImageFocalPoint,
    ImagePixelCrop,
    ImagePlacement,
    MarkObject,
    MaskContainer,
    MediaPlayback,
    MediaStreamPin,
    Point,
    PointerSourcePoint,
    RegistryAnchorMapping,
    RegistryBinding,
    ResolvedAction,
    ResolvedSplitEvidenceWindow,
    SplitAssetPin,
    SplitBasis,
    SplitCompletionReceipt,
    SplitEvidenceActivation,
    SplitPolicy,
    SplitResult,
    StructuredListPayload,
    StructuredListPhase,
    StructuredListPolicy,
    StyleRefs,
    TechnicalAnchorMapping,
    TechnicalFrameBinding,
    TechnicalRoleBinding,
    TextObject,
    Transform,
    VisualObject,
    _split_packet_digest,
)


@dataclass(frozen=True)
class SplitContentReceipt:
    object_id: str
    canonical_json: str
    content_sha256: str


def split_basis_digest(basis: SplitBasis) -> str:
    return _split_packet_digest(_stored_value(basis))


def split_policy_digest(policy: SplitPolicy) -> str:
    return _split_packet_digest(_stored_value(policy))


def split_completion_digest(receipt: SplitCompletionReceipt) -> str:
    packet = _stored_value(receipt)
    del packet["completion_sha256"]
    return _split_packet_digest(packet)


_FAMILY_FIELDS = {
    MarkObject: ("path_data",),
    TextObject: ("text", "items"),
    VisualObject: ("variant",),
    ConnectorObject: ("source_object_id", "source_anchor_id", "destination_object_id",
                      "destination_anchor_id", "role", "routing", "allow_self_loop"),
    GroupContainer: (),
    ClipContainer: (),
    MaskContainer: ("mask_mode", "mask_source_object_id", "mask_coordinate_space",
                    "invert", "feather_px"),
}
_CONTAINERS = (GroupContainer, ClipContainer, MaskContainer)


def _stored_value(value):
    """Reject unrecognized stored fields even on bypass-constructed models."""
    if isinstance(value, BaseModel):
        known_nested = (Geometry, Bounds, Point, PointerSourcePoint, Anchor, StyleRefs, Transform,
                        EvidenceIntent, EvidenceTreatment, AnnotationPolicy, AnnotationPhase,
                        SplitEvidenceActivation, ResolvedSplitEvidenceWindow, SplitAssetPin, SplitResult,
                        SplitCompletionReceipt, ResolvedAction,
                        CodePayload, CodeLine, CodeSpan, CalloutBinding, StructuredListPayload,
                        StructuredListPhase, StructuredListPolicy, RegistryBinding, RegistryAnchorMapping,
                        TechnicalFrameBinding, TechnicalRoleBinding, TechnicalAnchorMapping,
                        CharacterAssemblyBinding, CharacterRoleBinding, CharacterAnchorBinding,
                        IllustrationAssemblyBinding, IllustrationRoleBinding, IllustrationAnchorBinding,
                        ChartPayload, ChartAxis, ChartTick, ChartSeries, ChartPoint, ChartBar,
                        ChartHighlight, ChartConstruction,
                        ImagePlacement, ImagePixelCrop, ImageFocalPoint, MediaPlayback, MediaStreamPin,
                        CompositionBinding, CompositionDefinition, CompositionInstanceSpec,
                        CompositionExpansionMember, CompositionParameterSpec, CompositionParameterTarget,
                        CompositionParameterValue, CompositionStringValue, CompositionNumberValue,
                        CompositionBooleanValue, CompositionOverride, CompositionCoverageMapping,
                        CompositionObjectMapping, MarkObject, TextObject, VisualObject, ConnectorObject,
                        GroupContainer, ClipContainer, MaskContainer)
        if any(isinstance(value, model) and type(value) is not model for model in known_nested):
            raise ValueError("Split identity has an unknown nested payload subclass")
        if set(value.__dict__) != set(type(value).model_fields) or value.model_extra:
            raise ValueError("Split identity cannot discard unknown or missing stored fields")
        evidence_models = (EvidenceIntent, EvidenceTreatment, AnnotationPolicy, AnnotationPhase)
        authority_models = (*evidence_models, ConnectorObject, SplitEvidenceActivation, ResolvedSplitEvidenceWindow,
                            SplitResult, SplitAssetPin)
        # A completion digest projects every field except its own checksum.
        # Keep inventory/nested-window checks here, not whole-receipt checksum
        # validation (which belongs to receipt ingress and would be circular).
        inventory_models = (*authority_models, SplitCompletionReceipt, ResolvedAction)
        if type(value) in inventory_models:
            required = {key for key, field in type(value).model_fields.items() if field.is_required()}
            if (not value.model_fields_set.issubset(type(value).model_fields)
                    or not required.issubset(value.model_fields_set)):
                raise ValueError("Split stored identity requires exact explicitly declared authority fields")
        if type(value) is CompositionDefinition and any(
            "composition_binding" in obj.model_fields_set for obj in value.objects
        ):
            raise ValueError("Split identity cannot normalize a nested template binding, including null")
        stored = {name: _stored_value(value.__dict__[name]) for name in type(value).model_fields}
        if type(value) is EvidenceIntent and stored["annotation_policy"] is None:
            if "annotation_policy" in value.model_fields_set:
                raise ValueError("Split evidence identity cannot discard explicit null annotation authority")
            stored.pop("annotation_policy")
        if type(value) is ConnectorObject and stored["source_point"] is None:
            if "source_point" in value.model_fields_set:
                raise ValueError("Split connector identity cannot discard explicit null source authority")
            stored.pop("source_point")
        if type(value) is SplitResult and stored["evidence_activation"] is None:
            if "evidence_activation" in value.model_fields_set:
                raise ValueError("Split result identity cannot discard explicit null evidence activation")
            stored.pop("evidence_activation")
        if type(value) is SplitCompletionReceipt and stored["evidence_windows"] is None:
            if "evidence_windows" in value.model_fields_set:
                raise ValueError("Split completion identity cannot discard explicit null evidence windows")
            stored.pop("evidence_windows")
        if type(value) is ResolvedAction and stored["split_evidence_windows"] is None:
            if "split_evidence_windows" in value.model_fields_set:
                raise ValueError("Split action identity cannot discard explicit null evidence windows")
            stored.pop("split_evidence_windows")
        if type(value) in authority_models:
            # Validate canonical values, not just their inventory. Bypass-built
            # or mutated exact instances must never acquire identity authority.
            type(value).model_validate(stored, strict=True)
        if type(value) is CompositionBinding:
            # Only after recursively rejecting bypass/unknown fields may the
            # canonical wire serializer omit absent legacy prototype fields.
            stored = value.model_dump(mode="json")
            CompositionBinding.model_validate(stored)
        return stored
    if type(value) in (list, tuple):
        return [_stored_value(item) for item in value]
    if type(value) is dict:
        return {key: _stored_value(item) for key, item in value.items()}
    return value


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def split_content_receipts(
    layout: ExecutableLayoutV2,
    sample: ReplaySample,
    asset_bytes: Mapping[str, bytes | VerifiedEvidenceBytes],
) -> tuple[SplitContentReceipt, ...]:
    objects = {obj.object_id: obj for obj in layout.objects}
    frames = {obj.object_id: obj for obj in sample.objects}
    if (len(objects) != len(layout.objects) or len(frames) != len(sample.objects)
            or objects.keys() != frames.keys()):
        raise ValueError("Split content requires the exact unique layout/frame inventory")
    sample.hierarchy.validate(objects)
    return _content_receipts(layout, objects, frames,
        lambda key: sample.hierarchy.children(objects[key].board_id, key), asset_bytes)


def _content_receipts(layout, objects, frames, children, asset_bytes):
    """Shared content projection for a validated full sample or captured closure.

    The caller owns hierarchy/closure authentication. No absent frame is filled
    from layout defaults, and parent/paint ordering is not a content channel.
    """
    if objects.keys() != frames.keys():
        raise ValueError("Split content requires exact object/frame membership")
    payloads = {}
    for object_id, obj in objects.items():
        if type(obj) not in _FAMILY_FIELDS:
            raise ValueError("Split content has no projection for this object family")
        raw = _stored_value(obj)
        frame = frames[object_id]
        if (type(frame) not in (FrameObject, CountFrameObject)
                or set(frame.__dict__) != {field.name for field in fields(type(frame))}
                or frame.board_id != obj.board_id):
            raise ValueError("Split content has an unknown or mismatched frame payload")
        payload = {name: raw[name] for name in (
            "object_type", "geometry", "style", "anchors", "asset_id",
            *_FAMILY_FIELDS[type(obj)],
        )}
        if type(obj) is TextObject and obj.code_payload is not None:
            # Preserve bare legacy content hashes. New authored line/token/tab
            # semantics are content, not a pose or a guessed rendering default.
            TextObject.model_validate(raw)
            payload["code_payload"] = raw["code_payload"]
        if type(obj) is TextObject and obj.callout_binding is not None:
            TextObject.model_validate(raw)
            payload["callout_binding"] = raw["callout_binding"]
        if type(obj) is TextObject and obj.structured_list is not None:
            TextObject.model_validate(raw)
            payload["structured_list"] = raw["structured_list"]
        if type(obj) is ConnectorObject and obj.source_point is not None:
            # Exact authored source authority is content; this does not admit
            # the separate Split connector family or infer any endpoint.
            ConnectorObject.model_validate(raw)
            payload["source_point"] = raw["source_point"]
        if type(obj) is VisualObject and obj.registry_binding is not None:
            # Semantic binding is content. Actual fitted/resource authentication
            # remains the owning P3-34 runtime boundary, never inferred here.
            VisualObject.model_validate(raw)
            payload["registry_binding"] = raw["registry_binding"]
        if type(obj) is VisualObject and obj.technical_frame is not None:
            # Content identity does not admit native painting or Split coverage.
            VisualObject.model_validate(raw)
            payload["technical_frame"] = raw["technical_frame"]
        if type(obj) is VisualObject and obj.chart_payload is not None:
            # Data, display and construction decisions are semantic content.
            # Recognizing them here does not admit a data-chart paint adapter.
            VisualObject.model_validate(raw)
            payload["chart_payload"] = raw["chart_payload"]
        if type(obj) is VisualObject and obj.image_placement is not None:
            # Authored source-pixel placement is content, not inferred geometry.
            # This does not admit a Split image paint adapter.
            VisualObject.model_validate(raw)
            payload["image_placement"] = raw["image_placement"]
        if type(obj) is VisualObject and obj.media_playback is not None:
            # Source/range/stream/placement is authored content. This neither
            # decodes media nor admits the separate Split media family.
            VisualObject.model_validate(raw)
            payload["media_playback"] = raw["media_playback"]
        if type(obj) is GroupContainer and obj.character_assembly is not None:
            GroupContainer.model_validate(raw)
            payload["character_assembly"] = raw["character_assembly"]
        if type(obj) is GroupContainer and obj.illustration_assembly is not None:
            GroupContainer.model_validate(raw)
            payload["illustration_assembly"] = raw["illustration_assembly"]
        if type(obj) is GroupContainer and obj.composition_binding is not None:
            GroupContainer.model_validate(raw)
            payload["composition_binding"] = raw["composition_binding"]
        if frame.morph_geometry is not None:
            from atme.render.v2_morph import MorphGeometry

            geometry = frame.morph_geometry
            if (type(geometry) is not MorphGeometry
                    or set(geometry.__dict__) != {"bounds", "svg_d"}
                    or type(geometry.bounds) is not tuple or len(geometry.bounds) != 4
                    or type(geometry.svg_d) is not str or not geometry.svg_d.strip()):
                raise ValueError("Split content requires known Morph geometry")
            Bounds.model_validate(dict(zip(("x", "y", "width", "height"), geometry.bounds, strict=True)))
            payload["morph_geometry"] = {
                "bounds": frame.morph_geometry.bounds, "svg_d": frame.morph_geometry.svg_d,
            }
        if type(frame) is CountFrameObject:
            if type(obj) is not TextObject or obj.object_type != "text":
                raise ValueError("Split Count content requires an authored text object")
            frame.__post_init__()
            payload["count"] = {"display_text": frame.display_text, "value": frame.count_value}
        if type(obj) is VisualObject and obj.object_type == "evidence" and obj.asset_id is None:
            raise ValueError("Split evidence requires an immutable asset identity")
        if obj.asset_id is not None:
            if type(obj) is VisualObject and obj.object_type == "evidence":
                from atme.render.v2_split_paint import _split_evidence_asset_value

                treatments = [item for item in layout.evidence_treatments if item.object_id == object_id]
                if len(treatments) != 1 or type(treatments[0]) is not EvidenceTreatment:
                    raise ValueError("Split evidence requires exact attested bytes and treatment")
                value = _split_evidence_asset_value(asset_bytes, obj.asset_id, treatments[0].action_id, object_id)
            else:
                value = asset_bytes.get(obj.asset_id)
            if type(value) is VerifiedEvidenceBytes:
                if set(value.__dict__) != {field.name for field in fields(VerifiedEvidenceBytes)}:
                    raise ValueError("Split evidence has an unknown attestation payload field")
                if (type(value.asset_id) is not str or not value.asset_id.strip()
                        or type(value.sha256) is not str or not value.sha256.strip()
                        or any(type(number) is not int or number <= 0 for number in (
                            value.revision, value.width, value.height))
                        or type(value.payload) is not bytes or not value.payload
                        or type(value.treatment) is not EvidenceTreatment):
                    raise ValueError("Split evidence requires exact primitive and treatment types")
            if type(obj) is VisualObject and obj.object_type == "evidence":
                treatments = [item for item in layout.evidence_treatments if item.object_id == object_id]
                if len(treatments) != 1 or type(value) is not VerifiedEvidenceBytes:
                    raise ValueError("Split evidence requires exact attested bytes and treatment")
                treatment = treatments[0]
                if (type(treatment) is not EvidenceTreatment or value.treatment != treatment
                        or value.revision != treatment.asset_revision
                        or value.sha256 != treatment.asset_checksum_sha256
                        or value.width != treatment.asset_width or value.height != treatment.asset_height):
                    raise ValueError("Split evidence attestation differs from the layout treatment")
                EvidenceTreatment.model_validate(_stored_value(treatment))
                raster = canonical_png(value.payload)
                if (raster.width, raster.height, raster.source_sha256) != (
                        value.width, value.height, value.sha256):
                    raise ValueError("Split evidence attestation differs from actual source pixels")
            if type(value) is VerifiedEvidenceBytes:
                if (value.asset_id != obj.asset_id or type(value.revision) is not int
                        or value.revision < 1 or type(value.payload) is not bytes
                        or hashlib.sha256(value.payload).hexdigest() != value.sha256):
                    raise ValueError("Split evidence bytes do not match their verified identity")
                payload["evidence"] = {
                    "width": value.width, "height": value.height,
                    "intent": _stored_value(value.treatment.intent),
                }
                value = value.payload
            if type(value) is not bytes or not value:
                raise ValueError("Split content requires actual nonempty asset bytes")
            payload["asset_bytes_sha256"] = hashlib.sha256(value).hexdigest()
        payloads[object_id] = payload

    receipts = {}
    visiting = set()

    def capture(object_id):
        if object_id in receipts:
            return receipts[object_id]
        if object_id in visiting or object_id not in objects:
            raise ValueError("Split content has an incomplete or cyclic closure")
        visiting.add(object_id)
        payload = dict(payloads[object_id])
        obj = objects[object_id]
        if type(obj) in _CONTAINERS:
            payload["children"] = [
                {"object_id": child, "content_sha256": capture(child).content_sha256}
                for child in sorted(children(object_id))
            ]
        encoded = _json(payload)
        receipt = SplitContentReceipt(object_id, encoded, hashlib.sha256(encoded.encode()).hexdigest())
        receipts[object_id] = receipt
        visiting.remove(object_id)
        return receipt

    return tuple(capture(object_id) for object_id in sorted(objects))
