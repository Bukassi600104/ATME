"""Immutable observed Split boundaries; sampling and paint admission are separate.

Capture binds live hierarchy/frame data, never a self-hashed submitted history.
Project asset origins and retained annotation relationships need caller proofs;
this foundation rejects those inputs until the verified context is supplied.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, fields, replace
from hashlib import sha256

from atme.project_assets import VerifiedEvidenceBytes
from atme.render.style_bundle import (
    EXPECTED_REGISTRY_SHA256,
    EXPECTED_STYLE_SHA256,
    resolve_contract_bundle,
)
from atme.render.v2_hierarchy_replay import completed_hierarchy_basis
from atme.render.v2_morph import geometry_object
from atme.render.v2_split_clock import resolve_split_phase, split_phase_progress
from atme.render.v2_split_identity import (
    SplitContentReceipt,
    _stored_value,
    split_basis_digest,
    split_content_receipts,
)
from atme.render.v2_state import (
    CountFrameObject,
    FrameObject,
    FramePoint,
    FrameTransform,
)
from atme.render.v2_timeline_replay import CapturedAction, ReplaySample, version_targets
from atme.render.v2_world import _q, world_matrix
from atme.store.contracts_v2 import (
    Bounds,
    CameraAction,
    ConnectionAction,
    ConnectorObject,
    EvidenceAction,
    EvidenceTreatment,
    ExecutableLayoutV2,
    GroupAction,
    MaskContainer,
    Point,
    ReplaceAction,
    ResolvedAction,
    ResolvedAsset,
    SoundAction,
    SplitAction,
    SplitBasis,
    SplitClosure,
    SplitCompletionReceipt,
    SplitPlacement,
    SplitPolicy,
    SplitReadDependency,
    TargetAction,
    Transform,
    TransformAction,
    _annotation_object_ids,
    _annotation_policy_phase_windows,
    _expected_split_evidence_window,
    _split_expected_completion,
    _split_logical_write_owners,
    _split_packet_digest,
    _validate_evidence_annotation_objects,
)


@dataclass(frozen=True)
class SplitCapture:
    start_ms: int
    end_ms: int
    policy_json: str
    basis_json: str
    completion_json: str
    owned_root_ids: tuple[str, ...]
    owned_object_ids: tuple[str, ...]
    read_dependency_ids: tuple[str, ...]
    baseline: tuple[FrameObject, ...]


@dataclass(frozen=True)
class _PaintBoundSplitCapture(SplitCapture):
    """Private live-history payloads for owned and read paint authentication."""
    content_receipts: tuple[SplitContentReceipt, ...]
    evidence_treatments_json: tuple[tuple[str, str], ...] = field(default=(), kw_only=True)


@dataclass(frozen=True)
class _AttributedSplitCapture(_PaintBoundSplitCapture):
    """Private verified-owner carrier; never a serialized project contract."""
    action_id: str

    def __post_init__(self):
        if type(self.action_id) is not str or not self.action_id.strip():
            raise ValueError("Split attributed capture requires a nonblank action ID")


@dataclass(frozen=True)
class SplitPaintEnvelope:
    root_id: str
    action_id: str
    mode: str
    construction_fraction: float


@dataclass(frozen=True)
class SplitSample:
    objects: tuple[FrameObject, ...]
    envelopes: tuple[SplitPaintEnvelope, ...]


@dataclass(frozen=True)
class _SplitConstruction:
    root_id: str
    mode: str
    construction_fraction: float


@dataclass(frozen=True)
class _SplitPaintSample:
    objects: tuple[FrameObject, ...]
    constructions: tuple[_SplitConstruction, ...]


def sample_split(capture: SplitCapture, at_ms: int) -> SplitSample:
    """Pure owned paint delta; only the outer endpoint changes semantic state."""
    if type(capture) is not _AttributedSplitCapture:
        raise ValueError("Split sampling requires an exact attributed history capture")
    paint = _sample_split_paint(capture, at_ms)
    return SplitSample(paint.objects, tuple(SplitPaintEnvelope(row.root_id, capture.action_id,
        row.mode, row.construction_fraction) for row in paint.constructions))


def _sample_split_paint(capture: SplitCapture, at_ms: int) -> _SplitPaintSample:
    """The single state/pose kernel for replay and captured coverage proofs.

    This private result makes no chronological action-attribution claim.
    """
    if type(at_ms) is not int or at_ms < 0:
        raise ValueError("Split sample time must be nonnegative integer milliseconds")
    _validate_capture_inventory(capture)
    policy = SplitPolicy.model_validate_json(capture.policy_json)
    frames = {row.object_id: row for row in capture.baseline if row.object_id in capture.owned_object_ids}
    if at_ms < capture.start_ms:
        return _SplitPaintSample(tuple(frames[key] for key in sorted(frames)), ())
    complete = at_ms >= capture.end_ms
    source = frames[policy.source_object_id]
    fade = split_phase_progress(capture.start_ms, capture.end_ms, at_ms, policy.source_exit)
    frames[source.object_id] = replace(source, opacity=source.opacity * (1 - fade),
        visible=source.visible and fade < 1, state="removed" if complete else source.state,
        reveal_fraction=0.0 if complete else source.reveal_fraction)
    envelopes = []
    for result in policy.results:
        initial = frames[result.object_id]
        fraction = split_phase_progress(capture.start_ms, capture.end_ms, at_ms, result.construction.phase)
        transform = initial.transform
        if result.construction.enter_destination is not None:
            transform = _split_transform(initial.transform, result.construction.enter_destination, fraction)
        if result.movement is not None:
            move_start, _ = resolve_split_phase(capture.start_ms, capture.end_ms, result.movement.phase)
            if at_ms >= move_start:
                transform = _split_transform(FrameTransform.from_contract(result.movement.from_transform),
                    result.movement.destination,
                    split_phase_progress(capture.start_ms, capture.end_ms, at_ms, result.movement.phase))
        frames[result.object_id] = replace(initial, state=result.post_state if complete else initial.state,
            visible=fraction > 0, reveal_fraction=fraction, transform=transform)
        envelopes.append(_SplitConstruction(result.object_id, result.construction.mode, fraction))
        activation = result.evidence_activation
        annotation = activation.intent.annotation_policy if activation is not None else None
        if annotation is not None:
            from atme.render.v2_state import _ease

            start, end = resolve_split_phase(capture.start_ms, capture.end_ms, result.construction.phase)
            for phase, phase_start, phase_end in _annotation_policy_phase_windows(annotation, start, end):
                initial_note = frames[phase.object_id]
                progress = _ease((at_ms - phase_start) / (phase_end - phase_start),
                                 result.construction.phase.easing)
                frames[phase.object_id] = replace(initial_note, state="visible" if complete else initial_note.state,
                    visible=progress > 0, reveal_fraction=progress)
    return _SplitPaintSample(tuple(frames[key] for key in sorted(frames)), tuple(envelopes))


def _split_transform(start, end, progress):
    from atme.render.v2_state import _mix

    if progress <= 0:
        return start
    if progress >= 1:
        return FrameTransform.from_contract(end)
    return FrameTransform(
        FramePoint(_mix(start.position.x, end.position.x, progress),
                   _mix(start.position.y, end.position.y, progress)),
        _mix(start.scale_x, end.scale_x, progress), _mix(start.scale_y, end.scale_y, progress),
        _mix(start.rotation_degrees, end.rotation_degrees, progress),
        FramePoint(_mix(start.origin.x, end.origin.x, progress),
                   _mix(start.origin.y, end.origin.y, progress)))


@dataclass(frozen=True, kw_only=True)
class CapturedSplitAction(CapturedAction):
    split_capture: SplitCapture


@dataclass(frozen=True)
class _SplitCountOrigin:
    object_id: str
    resolved_index: int
    resolved_json: str
    display_text: str
    count_value: tuple[int, int]
    content_sha256: str
    commit_version: int
    current_version: int
    preserving_writers: tuple[tuple[int, str, int], ...] = ()


def _preserves_count_content(action) -> bool:
    return isinstance(action, (GroupAction, TransformAction)) or (
        isinstance(action, TargetAction) and action.verb in {
            "reveal", "write", "draw", "enter", "exit", "highlight", "cross_out",
            "dim", "isolate", "progressive_reveal", "annotate"})


def _require_proven_history_relationships(capture, owner, actions, objects, hierarchy, *, lifecycle_timeline=None):
    """Do not confuse completed action windows with retained relationship lifetimes.

    An exact typed route defers general relationships to the post-replay observer.
    Evidence holds remain closed until their full reading/camera/native boundary.
    Static unmanaged connectors still use ordinary captured anchor proof.
    """
    bound = set(capture.owned_object_ids) | set(capture.read_dependency_ids)
    if lifecycle_timeline is not None:
        from atme.store.contracts_v2 import ResolvedVisualTimelineV2

        if (type(lifecycle_timeline) is not ResolvedVisualTimelineV2
                or tuple(lifecycle_timeline.actions) != tuple(actions)):
            raise ValueError("Split lifecycle requires its complete exact typed timeline")

    def relationship_context(ids):
        context = set(ids)
        for key in tuple(context):
            obj = objects.get(key)
            if isinstance(obj, ConnectorObject):
                context.add(obj.destination_object_id)
                if obj.source_object_id is not None:
                    context.add(obj.source_object_id)
        for key in tuple(context):
            if key in objects:
                context.update(hierarchy.ancestors(key))
        return context

    for resolved in actions:
        action = resolved.action
        if isinstance(action, ConnectionAction):
            # Any authored lifecycle makes this managed, including an initially
            # connected arrow whose first disconnect occurs after this Split.
            ids = {action.connector_id, action.destination_object_id}
            if action.source_object_id is not None:
                ids.add(action.source_object_id)
            if relationship_context(ids) & bound and lifecycle_timeline is None:
                raise ValueError("Split managed connector requires verified lifecycle context")
        if resolved.start_ms >= capture.end_ms:
            continue
        if isinstance(action, TargetAction) and action.annotation_policy is not None:
            ids = {*action.target_ids, *_annotation_object_ids(action)}
            if relationship_context(ids) & bound and lifecycle_timeline is None:
                raise ValueError("Split retained annotation requires verified lifecycle context")
        if (isinstance(action, EvidenceAction) and action.verb == "insert_evidence"
                and owner.action.board_id in {action.board_id, action.destination_board_id}
                and lifecycle_timeline is None):
            raise ValueError("Split evidence reading hold requires verified treatment context")


def _json(packet) -> str:
    return json.dumps(packet, sort_keys=True, separators=(",", ":"), allow_nan=False)


def capture_split(resolved: ResolvedAction, layout: ExecutableLayoutV2, before: ReplaySample,
                  asset_bytes: Mapping[str, bytes | VerifiedEvidenceBytes]) -> SplitCapture:
    return _capture_split(resolved, layout, before, asset_bytes, ())


def _capture_split(resolved, layout, before, asset_bytes, count_origins: tuple[_SplitCountOrigin, ...],
                   *, split_inputs=None):
    """Trusted history is produced only by the private chronology capture hook."""
    # Reparse mutable contract inputs; callers cannot bypass checks with model_copy.
    resolved = ResolvedAction.model_validate(_stored_value(resolved))
    if type(layout) is not ExecutableLayoutV2:
        raise ValueError("Split requires a known executable layout")
    layout = ExecutableLayoutV2.model_validate(_stored_value(layout))
    action = resolved.action
    if not isinstance(action, SplitAction) or action.split_policy is None or resolved.split_completion_receipt is None:
        raise ValueError("Split capture requires an authored action and completion assertion")
    policy = action.split_policy
    if type(before.at_ms) is not int or before.at_ms != resolved.start_ms:
        raise ValueError("Split capture needs its exact observed start boundary")
    from atme.render.v2_split_paint import _verified_split_asset_pins

    # The private carrier is independently checked; ordinary byte maps and
    # submitted self-hashed pins never establish project origin/revision.
    logical_owners = _split_logical_write_owners(policy)
    if not logical_owners and any(row.kind == "annotation_anchor" for row in policy.source_basis.read_dependencies):
        raise ValueError("Split annotation dependencies require retained chronology context")
    if split_inputs is None:
        resolve_contract_bundle(layout.style_system_version, layout.asset_registry_version)
    else:
        from atme.render.v2_split_paint import _checked_split_resources

        _checked_split_resources(layout, split_inputs)
    if not any(window.board_id == action.board_id and window.start_ms <= resolved.start_ms
               and resolved.end_ms <= window.end_ms for window in layout.activations):
        raise ValueError("Split must fit one actual active-board window")
    for phase in [policy.source_exit, *[row.construction.phase for row in policy.results],
                  *[row.movement.phase for row in policy.results if row.movement is not None]]:
        resolve_split_phase(resolved.start_ms, resolved.end_ms, phase)

    authored = {obj.object_id: obj for obj in layout.objects}
    if len(authored) != len(layout.objects):
        raise ValueError("Split layout inventory repeats an object")
    objects = before.hierarchy.object_map(authored)
    frames = {frame.object_id: frame for frame in before.objects}
    if len(frames) != len(before.objects) or frames.keys() != objects.keys():
        raise ValueError("Split needs the exact unique observed frame inventory")
    completed_hierarchy_basis(before.hierarchy, frames)
    for frame in frames.values():
        for value, cls in ((frame.transform, FrameTransform), (frame.transform.position, FramePoint),
                           (frame.transform.origin, FramePoint)):
            if type(value) is not cls or set(value.__dict__) != {field.name for field in fields(cls)}:
                raise ValueError("Split cannot discard unknown transform payloads")
    versions = dict(before.state_versions)
    if (len(versions) != len(before.state_versions) or versions.keys() != frames.keys()
            or any(type(version) is not int or version < 1 for version in versions.values())):
        raise ValueError("Split needs every exact current state version once")

    def closure(root):
        if root not in objects or objects[root].board_id != action.board_id:
            raise ValueError("Split root is missing or belongs to another board")
        ids = []

        def visit(key):
            ids.append(key)
            for child in before.hierarchy.children(action.board_id, key):
                visit(child)
        visit(root)
        return tuple(sorted(ids))

    roots = (policy.source_object_id, *[row.object_id for row in policy.results])
    closures = [closure(root) for root in roots]
    all_owned = [key for keys in closures for key in keys]
    if len(all_owned) != len(set(all_owned)):
        raise ValueError("Split actual owned closures overlap or nest")
    owned = set(all_owned)
    if owned.intersection(logical_owners):
        raise ValueError("Split logical annotation overlaps an actual physical closure")
    owned.update(logical_owners)
    dependency_sets = {kind: set() for kind in (
        "ancestor", "aperture", "mask_source", "connector_anchor", "annotation_anchor")}
    for result in policy.results:
        activation = result.evidence_activation
        if activation is None or activation.intent.annotation_policy is None:
            continue
        _validate_evidence_annotation_objects(result.object_id, activation.intent, objects)
        note_ids = [key for key, owner in logical_owners.items() if owner == result.object_id]
        target = activation.intent.annotation_target_id
        if target in owned:
            raise ValueError("Split evidence annotation must retain a separate read-only target")
        if any(frames[key].state != "hidden" or frames[key].visible or frames[key].reveal_fraction != 0
               or frames[key].opacity != 1 for key in note_ids):
            raise ValueError("Split evidence annotation requires untouched hidden opaque notes")
        if any(not frames[key].visible or frames[key].opacity != 1 or frames[key].reveal_fraction != 1
               for key in (target, *before.hierarchy.ancestors(target))):
            raise ValueError("Split evidence annotation requires a fully readable current target")
        dependency_sets["annotation_anchor"].update([target, *note_ids])

    def aperture(key):
        if key not in objects:
            raise ValueError("Split aperture references an unknown object")
        dependency_sets["aperture"].add(key)
        if isinstance(objects[key], MaskContainer):
            mask_source = objects[key].mask_source_object_id
            if mask_source is None:
                raise ValueError("Split needs an explicit mask-source definition")
            dependency_sets["mask_source"].update(closure(mask_source))

    for key in sorted(owned):
        for ancestor in before.hierarchy.ancestors(key):
            dependency_sets["ancestor"].add(ancestor)
            if objects[ancestor].object_type in {"clip", "mask"}:
                aperture(ancestor)
        obj = objects[key]
        if obj.clip_id is not None:
            aperture(obj.clip_id)
        if isinstance(obj, MaskContainer):
            aperture(key)
    for obj in objects.values():
        if isinstance(obj, ConnectorObject):
            endpoints = {obj.destination_object_id}
            if obj.source_object_id is not None:
                endpoints.add(obj.source_object_id)
            if obj.object_id in owned or endpoints.intersection(owned):
                dependency_sets["connector_anchor"].update({obj.object_id, *endpoints})
    # Every read object's parent transform and aperture is itself observable.
    changed = True
    while changed:
        old = {key for ids in dependency_sets.values() for key in ids}
        for key in sorted(old):
            if key not in objects or objects[key].board_id != action.board_id:
                raise ValueError("Split read dependency is unknown or crosses boards")
            for ancestor in before.hierarchy.ancestors(key):
                dependency_sets["ancestor"].add(ancestor)
                if objects[ancestor].object_type in {"clip", "mask"}:
                    aperture(ancestor)
            if objects[key].clip_id is not None:
                aperture(objects[key].clip_id)
        changed = old != {key for ids in dependency_sets.values() for key in ids}
    dependencies = [SplitReadDependency(kind=kind, object_ids=sorted(ids))
                    for kind, ids in dependency_sets.items() if ids]
    bound = owned | {key for ids in dependency_sets.values() for key in ids}
    if len(bound) > 4096:
        raise ValueError("Split exceeds the approved distinct-object inventory limit")
    asset_pins = _verified_split_asset_pins(layout, asset_bytes,
        {objects[key].asset_id for key in bound if objects[key].asset_id is not None})
    evidence_context = _capture_split_evidence_context(resolved, layout, objects, asset_bytes)
    receipts = {row.object_id: row for row in split_content_receipts(layout, before, asset_bytes)}
    origins = {row.object_id: row for row in count_origins}
    if len(origins) != len(count_origins):
        raise ValueError("Split Count origin inventory repeats an object")
    for key in sorted(bound):
        frame = frames[key]
        if type(frame) is not CountFrameObject:
            continue
        origin = origins.get(key)
        if type(origin) is not _SplitCountOrigin:
            raise ValueError("Split Count payload requires its actual completed origin")
        previous = ResolvedAction.model_validate_json(origin.resolved_json)
        if (not isinstance(previous.action, TargetAction) or previous.action.verb != "count"
                or previous.action.target_ids != [key] or previous.end_ms > resolved.start_ms
                or (frame.display_text, frame.count_value, receipts[key].content_sha256) != (
                    origin.display_text, origin.count_value, origin.content_sha256)
                or origin.current_version != versions[key]
                or origin.current_version != origin.commit_version + len(origin.preserving_writers)):
            raise ValueError("Split Count origin differs from current content or version history")
        for _, writer_json, writer_version in origin.preserving_writers:
            writer = ResolvedAction.model_validate_json(writer_json)
            if (not _preserves_count_content(writer.action) or key not in version_targets(writer.action)
                    or writer.end_ms > resolved.start_ms or writer.end_ms < previous.end_ms
                    or not origin.commit_version < writer_version <= origin.current_version):
                raise ValueError("Split Count origin has an unproved intervening writer")
    effective_objects = {key: geometry_object(obj, frames[key].morph_geometry)
                         if frames[key].morph_geometry is not None else obj for key, obj in objects.items()}
    def visible(key):
        return frames[key].visible and all(frames[parent].visible and frames[parent].opacity > 0
            for parent in before.hierarchy.ancestors(key))

    source = frames[roots[0]]
    if (source.state != action.expected_state or not visible(roots[0])
            or source.reveal_fraction != 1 or source.opacity <= 0
            or any(frames[key].reveal_fraction != 1 for key in before.hierarchy.ancestors(roots[0]))):
        raise ValueError("Split source is not actually visible, fully revealed and positive-alpha")
    for key in roots[1:]:
        frame = frames[key]
        if frame.state != "hidden" or frame.visible or frame.reveal_fraction != 0 or frame.opacity <= 0:
            raise ValueError("Split result must actually be hidden, zero-reveal and positive-alpha")

    placements = _observed_split_placements(before, effective_objects, bound, receipts)
    basis = SplitBasis(source_closure=SplitClosure(root_id=roots[0], owned_ids=list(closures[0])),
        result_closures=[SplitClosure(root_id=root, owned_ids=list(ids))
                         for root, ids in zip(roots[1:], closures[1:], strict=True)],
        placements=placements, read_dependencies=dependencies, asset_pins=asset_pins,
        style_sha256=EXPECTED_STYLE_SHA256, registry_sha256=EXPECTED_REGISTRY_SHA256)
    if split_basis_digest(basis) != policy.source_basis_sha256:
        raise ValueError("Split submitted basis differs from actual observed history")
    actual_policy = policy.model_copy(update={"source_basis": basis, "source_basis_sha256": split_basis_digest(basis)},
                                      deep=True)
    completion = _split_expected_completion(actual_policy)
    if evidence_context:
        treatments = {key: EvidenceTreatment.model_validate_json(encoded) for key, encoded in evidence_context}
        completion["evidence_windows"] = [_expected_split_evidence_window(resolved, result, treatments[result.object_id])
            for result in actual_policy.results if result.evidence_activation is not None]
    supplied = resolved.split_completion_receipt.model_dump(mode="json", exclude={"completion_sha256"})
    if _split_packet_digest(completion) != _split_packet_digest(supplied):
        raise ValueError("Split completion differs from actual capture and authored phases")
    completion["completion_sha256"] = _split_packet_digest(completion)
    capture = _PaintBoundSplitCapture(resolved.start_ms, resolved.end_ms, _json(actual_policy.model_dump(mode="json")),
        _json(basis.model_dump(mode="json")), _json(completion), roots, tuple(sorted(owned)),
        tuple(sorted(bound - owned)), tuple(frames[key] for key in sorted(bound)),
        tuple(receipts[key] for key in sorted(bound)), evidence_treatments_json=evidence_context)
    _validate_capture_inventory(capture)
    return capture


def _capture_split_evidence_context(resolved, layout, objects, carrier):
    """Rebuild actual result treatment authority from checked original metadata."""
    from atme.render.v2_split_paint import _split_evidence_asset_value

    contexts = []
    assets = {row.asset_id: ResolvedAsset.model_validate_json(row.resolved_json)
              for row in carrier.rows} if carrier else {}
    for result in resolved.action.split_policy.results:
        obj = objects[result.object_id]
        activation = result.evidence_activation
        if activation is None:
            if obj.object_type == "evidence":
                raise ValueError("Split evidence result requires its explicit activation")
            continue
        asset = assets.get(obj.asset_id)
        pin = activation.asset_pin
        if (obj.object_type != "evidence" or asset is None or asset.kind != "evidence"
                or obj.asset_id != pin.asset_id or obj.beat_id != activation.beat_id
                or obj.board_id != activation.intent.destination_board_id
                or (asset.revision, f"atme://projects/{layout.project_id}/assets/{asset.asset_id}", asset.checksum_sha256)
                != (pin.revision, pin.resource_uri, pin.checksum_sha256)
                or asset.allowed_transformations != activation.allowed_transformations):
            raise ValueError("Split evidence activation differs from actual object and verified source")
        verified = _split_evidence_asset_value(carrier, obj.asset_id, resolved.action.action_id, obj.object_id)
        if type(verified) is not VerifiedEvidenceBytes:
            raise ValueError("Split evidence context requires its exact project-verified source treatment")
        expected = EvidenceTreatment(object_id=obj.object_id, action_id=resolved.action.action_id,
            beat_id=obj.beat_id, asset_revision=asset.revision, asset_checksum_sha256=asset.checksum_sha256,
            asset_managed_ref=asset.managed_ref, asset_width=asset.width, asset_height=asset.height,
            asset_provenance=verified.treatment.asset_provenance,
            allowed_transformations=asset.allowed_transformations,
            intent=activation.intent)
        rows = [row for row in layout.evidence_treatments if row.object_id == result.object_id]
        if len(rows) != 1 or rows[0].model_dump(mode="json") != expected.model_dump(mode="json"):
            raise ValueError("Split evidence layout treatment differs from its independently bound source and intent")
        contexts.append((result.object_id, _json(expected.model_dump(mode="json"))))
    return tuple(contexts)


def _observed_split_placements(before, effective_objects, bound, receipts):
    frames = {frame.object_id: frame for frame in before.objects}
    versions = dict(before.state_versions)
    transforms = {key: frame.transform for key, frame in frames.items()}
    nodes = {node.object_id: node for node in before.hierarchy.nodes}

    def visible(key):
        return frames[key].visible and all(frames[parent].visible and frames[parent].opacity > 0
            for parent in before.hierarchy.ancestors(key))

    placements = []
    for key in sorted(bound):
        obj, frame, node = effective_objects[key], frames[key], nodes[key]
        matrix = world_matrix(obj, effective_objects, transforms)
        box = obj.geometry.bounds
        x, y, width, height = map(_q, (box.x, box.y, box.width, box.height))
        corners = [matrix.point(px, py) for px, py in ((x, y), (x + width, y),
                                                     (x + width, y + height), (x, y + height))]
        left, top = min(px for px, _ in corners), min(py for _, py in corners)
        placements.append(SplitPlacement(object_id=key, parent_id=node.parent_id,
            sibling_ordinal=node.sibling_ordinal, local_content_bounds=box.model_copy(deep=True),
            local_transform=Transform.model_validate(asdict(frame.transform)),
            world_matrix=(matrix.a, matrix.b, matrix.c, matrix.d, matrix.e, matrix.f),
            world_corners=tuple(Point(x=px, y=py) for px, py in corners),
            world_bounds=Bounds(x=left, y=top, width=max(px for px, _ in corners) - left,
                                height=max(py for _, py in corners) - top),
            state=frame.state, local_visibility=frame.visible, effective_visibility=visible(key),
            reveal=frame.reveal_fraction, local_opacity=frame.opacity, state_version=versions[key],
            content_sha256=receipts[key].content_sha256))
    return placements


def _validate_split_completion(capture, layout, endpoint, asset_bytes=None):
    """Compare independently sampled world/state/content/version before commit."""
    _validate_capture_inventory(capture)
    if endpoint.at_ms != capture.end_ms:
        raise ValueError("Split completion needs its exact endpoint")
    objects = endpoint.hierarchy.object_map({obj.object_id: obj for obj in layout.objects})
    objects = {key: geometry_object(obj, endpoint.object(key).morph_geometry) for key, obj in objects.items()}
    bound = set(capture.owned_object_ids) | set(capture.read_dependency_ids)
    from atme.render.v2_split_paint import _verified_split_asset_pins

    carrier = {} if asset_bytes is None else asset_bytes
    if SplitBasis.model_validate_json(capture.basis_json).asset_pins != _verified_split_asset_pins(
            layout, carrier, {objects[key].asset_id for key in bound if objects[key].asset_id is not None}):
        raise ValueError("Split completion asset pins differ from captured originals")
    receipts = {row.object_id: row for row in split_content_receipts(layout, endpoint, carrier)}
    actual = _observed_split_placements(endpoint, objects, bound, receipts)
    expected = SplitCompletionReceipt.model_validate_json(capture.completion_json)
    if _split_packet_digest([row.model_dump(mode="json") for row in actual]) != _split_packet_digest(
            [row.model_dump(mode="json") for row in expected.placements]):
        raise ValueError("Split sampled completion differs from its bound receipt")


def _reservation_footprint(action) -> tuple[set[str], set[str]]:
    """Local/structural writes and non-camera geometry reads of one peer."""
    if isinstance(action, (CameraAction, SoundAction)):
        return set(), set()
    if isinstance(action, GroupAction):
        policy = action.hierarchy_policy
        if policy is None:
            raise ValueError("Split reservation cannot interpret a bare hierarchy action")
        writes = set(policy.changed_object_ids) | set(action.target_ids) | {action.container_id}
        reads = set()
        # A structural root affects its entire old/new world closure, even
        # where a descendant's local record and version do not change.
        for basis in (policy.source_basis, policy.destination_basis):
            placements = {row.object_id: row for row in basis.placements}
            roots = set(action.target_ids) | {action.container_id}
            for key, row in placements.items():
                chain = set()
                parent = row.parent_id
                while parent is not None:
                    chain.add(parent)
                    parent = placements[parent].parent_id
                if chain & roots:
                    writes.add(key)
                if key in roots:
                    reads.update(chain)
        return writes, reads
    if isinstance(action, SplitAction):
        if action.split_policy is None:
            raise ValueError("Split reservation cannot interpret a bare Split action")
        basis = action.split_policy.source_basis
        writes = set(basis.source_closure.owned_ids)
        writes.update(key for row in basis.result_closures for key in row.owned_ids)
        writes.update(_split_logical_write_owners(action.split_policy))
        reads = {key for row in basis.read_dependencies for key in row.object_ids} - writes
        return writes, reads
    if isinstance(action, ConnectionAction):
        reads = {action.destination_object_id}
        if action.source_object_id is not None:
            reads.add(action.source_object_id)
        return {action.connector_id}, reads
    if isinstance(action, TargetAction):
        if action.annotation_policy is not None:
            return set(_annotation_object_ids(action)), set(action.target_ids)
        if action.structured_list_policy is not None:
            return set(action.target_ids), {action.structured_list_policy.list_object_id,
                                           action.structured_list_policy.container_group_id}
        return set(action.target_ids), set()
    if isinstance(action, TransformAction):
        return set(action.target_ids), set()
    if isinstance(action, ReplaceAction):
        return {action.from_object_id, action.to_object_id}, set()
    if isinstance(action, EvidenceAction):
        if action.verb == "return_board":
            return set(), set(action.expected_object_states or ())
        return {action.target_object_id}, set()
    raise ValueError("Split reservation encountered an unknown action")


def validate_split_reservations(capture: SplitCapture, actions: tuple[ResolvedAction, ...]) -> None:
    """Internal coherence/overlap check on an immediately observed capture.

    The chronology caller binds the interval to the verified owner and excludes
    that owner by index/ID. A reconstructed carrier alone is not a time receipt.
    Half-open construction intervals may touch. Retained relationship lifetime
    validation is also required by the chronology/lifecycle caller; a completed
    annotation or connection is not assumed removed when its action ends.
    """
    _validate_capture_inventory(capture)
    owned = set(capture.owned_object_ids)
    bound = owned | set(capture.read_dependency_ids)
    boards = {frame.board_id for frame in capture.baseline}
    for item in actions:
        item = ResolvedAction.model_validate_json(item.model_dump_json())
        if item.start_ms >= capture.end_ms or item.end_ms <= capture.start_ms:
            continue
        action = item.action
        writes, reads = _reservation_footprint(action)
        if isinstance(action, TargetAction) and action.verb == "isolate" and action.board_id in boards:
            writes.update(bound)
        conflict = (writes & bound) | (reads & owned)
        if conflict:
            raise ValueError(f"Split reservation conflicts with action {action.action_id} on {min(conflict)}")


def _validate_split_evidence_context(capture, policy, completion):
    """Full captured treatment identity and clocks, separate from base receipts."""
    results = [result for result in policy.results if result.evidence_activation is not None]
    rows = getattr(capture, "evidence_treatments_json", ())
    if (type(rows) is not tuple or any(type(row) is not tuple or len(row) != 2
            or any(type(value) is not str for value in row) for row in rows)
            or [row[0] for row in rows] != [result.object_id for result in results]):
        raise ValueError("Split evidence context needs exact authored-order result treatment rows")
    if results and type(capture) not in (_PaintBoundSplitCapture, _AttributedSplitCapture):
        raise ValueError("Split evidence requires its private captured treatment context")
    expected = []
    for result, (_, encoded) in zip(results, rows, strict=True):
        if _json(json.loads(encoded)) != encoded:
            raise ValueError("Split evidence treatment context must be canonical")
        treatment = EvidenceTreatment.model_validate_json(encoded)
        activation = result.evidence_activation
        pin = activation.asset_pin
        if (_json(treatment.model_dump(mode="json")) != encoded
                or treatment.object_id != result.object_id
                or treatment.action_id != activation.causal_action_id or treatment.beat_id != activation.beat_id
                or treatment.intent.model_dump(mode="json") != activation.intent.model_dump(mode="json")
                or (treatment.intent.evidence_asset_id, treatment.asset_revision, treatment.asset_checksum_sha256)
                != (pin.asset_id, pin.revision, pin.checksum_sha256)
                or treatment.allowed_transformations != activation.allowed_transformations
                or type(capture) is _AttributedSplitCapture and treatment.action_id != capture.action_id):
            raise ValueError("Split evidence treatment context differs from its authenticated activation")
        start, end = resolve_split_phase(capture.start_ms, capture.end_ms, result.construction.phase)
        if activation.intent.annotation_policy is not None:
            _annotation_policy_phase_windows(activation.intent.annotation_policy, start, end)
        expected.append(_expected_split_evidence_window(capture, result, treatment))
    actual = completion.evidence_windows
    if ((not results and actual is not None) or (results and actual is None)
            or results and [row.model_dump(mode="json") for row in actual] != expected):
        raise ValueError("Split evidence receipt windows differ from actual captured treatment and phase clock")


def _validate_capture_inventory(capture: SplitCapture) -> None:
    """Recheck carrier coherence; live-history authentication stays at capture."""
    if (type(capture) not in (SplitCapture, _PaintBoundSplitCapture, _AttributedSplitCapture) or type(capture.start_ms) is not int
            or type(capture.end_ms) is not int or not 0 <= capture.start_ms < capture.end_ms):
        raise ValueError("Split capture has an invalid type or interval")
    basis = SplitBasis.model_validate_json(capture.basis_json)
    policy = SplitPolicy.model_validate_json(capture.policy_json)
    completion = SplitCompletionReceipt.model_validate_json(capture.completion_json)
    _validate_split_evidence_context(capture, policy, completion)
    roots = (policy.source_object_id, *[row.object_id for row in policy.results])
    owned = (set(basis.source_closure.owned_ids) | {key for row in basis.result_closures for key in row.owned_ids}
             | _split_logical_write_owners(policy).keys())
    bound = owned | {key for row in basis.read_dependencies for key in row.object_ids}
    if (basis != policy.source_basis or capture.owned_root_ids != roots
            or capture.owned_object_ids != tuple(sorted(owned))
            or capture.read_dependency_ids != tuple(sorted(bound - owned))
            or type(capture.baseline) is not tuple
            or tuple(frame.object_id for frame in capture.baseline) != tuple(sorted(bound))
            or _split_packet_digest(_split_expected_completion(policy)) != _split_packet_digest(
                completion.model_dump(mode="json", exclude={"completion_sha256", "evidence_windows"}))):
        raise ValueError("Split capture reservation inventory differs from its bound packets")
    if type(capture) in (_PaintBoundSplitCapture, _AttributedSplitCapture):
        receipts = capture.content_receipts
        hashes = {row.object_id: row.content_sha256 for row in basis.placements}
        if (type(receipts) is not tuple or any(type(row) is not SplitContentReceipt for row in receipts)
                or tuple(row.object_id for row in receipts) != tuple(sorted(bound))):
            raise ValueError("Split captured paint receipts differ from bound inventory")
        for row in receipts:
            if (row.canonical_json != _json(json.loads(row.canonical_json))
                    or sha256(row.canonical_json.encode()).hexdigest() != row.content_sha256
                    or row.content_sha256 != hashes[row.object_id]):
                raise ValueError("Split captured paint receipt differs from its identity")
