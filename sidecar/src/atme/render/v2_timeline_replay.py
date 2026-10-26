"""Immutable chronological local-state replay for the v2 hierarchy integration.

This is the shared clock/state kernel, not a replacement production gate. Callers
must retain plan/layout/asset/geometry validation. The kernel can replay paired
Group/annotation actions; temporal consumer, stored-project and public admission
are separate proofs. Public frames admit only policy-bearing Group/ungroup
through those same proofs. Group/return requires an exact retained-board receipt.

At a timestamp: ordinary completions, structural completions in resolved order,
then starts. An active operator always samples its captured start pose. A Group
reads the full sampled boundary, but commits ONLY its member local transforms,
shell state, hierarchy and structural versions -- never unrelated partial poses.
"""

from __future__ import annotations

import json
from bisect import bisect_right
from dataclasses import asdict, dataclass, fields, replace
from fractions import Fraction
from typing import TYPE_CHECKING

from pydantic import TypeAdapter

from atme.render.v2_character_assembly import (
    validate_character_hierarchy,
    validate_character_transition,
)
from atme.render.v2_count import count_at_ms, count_decimal, count_value_at_ms
from atme.render.v2_hierarchy import (
    HierarchySnapshot,
    UnsupportedHierarchy,
    group_visibility_closure,
    group_visibility_roots,
    validate_authored_hierarchy,
)
from atme.render.v2_hierarchy_replay import (
    apply_hierarchy_step,
    completed_hierarchy_basis,
)
from atme.render.v2_illustration_assembly import (
    validate_illustration_hierarchy,
    validate_illustration_transition,
)
from atme.render.v2_isolation import UnsupportedIsolation, isolation_context_roots
from atme.render.v2_list import validate_structured_list_capture
from atme.render.v2_morph import interpolate_geometry
from atme.render.v2_return import UnsupportedReturn, validate_return_sample
from atme.store.contracts_v2 import (
    CameraAction,
    ConnectionAction,
    ConnectorObject,
    EvidenceAction,
    EvidenceTreatment,
    ExecutableObject,
    GroupAction,
    ReplaceAction,
    ResolvedAction,
    SoundAction,
    SplitAction,
    TargetAction,
    TextObject,
    TransformAction,
    _action_object_references,
    _annotation_object_ids,
    _annotation_phase_windows,
    _annotation_policy_object_ids,
    _annotation_policy_phase_windows,
    _split_logical_write_owners,
    _structured_list_phase_windows,
    _validate_evidence_annotation_objects,
)

if TYPE_CHECKING:
    from atme.render.v2_state import FrameObject

_OBJECT_ADAPTER = TypeAdapter(ExecutableObject)


class ReplayError(ValueError):
    """An authored boundary cannot be replayed without changing its meaning."""


@dataclass(frozen=True)
class CapturedAction:
    resolved_index: int
    resolved_json: str
    baseline: tuple[FrameObject, ...]
    context_root_ids: tuple[str, ...] = ()

    @property
    def resolved(self) -> ResolvedAction:
        # Contracts are mutable models; never expose a stored mutable instance.
        return ResolvedAction.model_validate_json(self.resolved_json)


@dataclass(frozen=True)
class EvidenceTargetRead:
    object_json: str
    frame: FrameObject
    state_version: int
    hierarchy: HierarchySnapshot


@dataclass(frozen=True)
class CapturedEvidenceAction(CapturedAction):
    treatment_json: str = ""
    target_read: EvidenceTargetRead | None = None


def _evidence_read_json(read):
    if type(read) is not EvidenceTargetRead:
        raise ReplayError("evidence capture requires its exact target read receipt")
    return json.dumps(asdict(read), sort_keys=True, separators=(",", ":"), allow_nan=False)


def _require_evidence_capture_authority(capture, evidence_treatments, evidence_reads):
    action_id = capture.resolved.action.action_id
    raw = dict(evidence_treatments).get(action_id)
    treatment = EvidenceTreatment.model_validate_json(raw) if raw is not None else None
    bound = treatment is not None and treatment.intent.annotation_policy is not None
    read = dict(evidence_reads).get(action_id)
    if bound or read is not None or isinstance(capture, CapturedEvidenceAction):
        if not bound or read is None or type(capture) is not CapturedEvidenceAction:
            raise ReplayError("bound evidence read authority requires its exact evidence capture type")
        if capture.treatment_json != raw or _evidence_read_json(capture.target_read) != read:
            raise ReplayError("evidence capture differs from paired treatment or target read authority")
    return treatment if bound else None


@dataclass(frozen=True)
class ReplayCheckpoint:
    at_ms: int
    objects: tuple[FrameObject, ...]
    state_versions: tuple[tuple[str, int], ...]
    hierarchy: HierarchySnapshot
    active: tuple[CapturedAction, ...]


@dataclass(frozen=True)
class ReplaySample:
    at_ms: int
    objects: tuple[FrameObject, ...]
    state_versions: tuple[tuple[str, int], ...]
    hierarchy: HierarchySnapshot

    def object(self, object_id: str) -> FrameObject:
        return next(item for item in self.objects if item.object_id == object_id)


@dataclass(frozen=True)
class SplitReplaySample(ReplaySample):
    envelopes: tuple


@dataclass(frozen=True)
class _SplitReplayContext:
    layout_json: str
    action_json: tuple[str, ...]
    initial: ReplaySample
    asset_bytes: object = None
    timeline_json: str | None = None
    split_inputs: object = None
    layout_sha256: str | None = None
    structural_timeline_json: str | None = None
    registry_inputs: object = None


def _split_causal_timeline(timeline, actions, structural_timeline=None):
    """Validate the full stored document before projecting its exact resolved prefix."""
    from atme.render.v2_split_identity import _stored_value
    from atme.store.contracts_v2 import ResolvedVisualTimelineV2

    if structural_timeline is None:
        return ResolvedVisualTimelineV2.model_validate(_stored_value(timeline))
    full = ResolvedVisualTimelineV2.model_validate(_stored_value(structural_timeline))
    prefix = full.model_copy(update={"actions": list(actions)})
    supplied = _stored_value(timeline)
    if type(timeline) is ResolvedVisualTimelineV2:
        supplied = timeline.model_dump(mode="json")
    if tuple(full.actions[:len(actions)]) != tuple(actions) or supplied != prefix.model_dump(mode="json"):
        raise ReplayError("Split causal timeline differs from the exact validated structural prefix")
    return prefix


def _replay_split_chronology(layout, initial, actions, duration_ms, asset_bytes, *, timeline=None, split_inputs=None,
                             layout_sha256=None, structural_timeline=None, registry_inputs=None):
    """Private pre-admission route through the same scheduler, never a second clock."""
    from atme.render.v2_split_identity import _stored_value
    from atme.store.contracts_v2 import ExecutableLayoutV2, ResolvedVisualTimelineV2

    layout = ExecutableLayoutV2.model_validate(_stored_value(layout))
    actions = tuple(ResolvedAction.model_validate(_stored_value(item)) for item in actions)
    objects = {obj.object_id: obj for obj in layout.objects}
    _require_split_initial(layout, initial)
    if split_inputs is not None:
        from atme.render.style_bundle import registry_endpoint_inputs_for_objects
        from atme.render.v2_split_paint import _checked_split_resources

        resources = _checked_split_resources(layout, split_inputs)
        if type(asset_bytes) is not type(resources[3]) or asset_bytes != resources[3]:
            raise ReplayError("Split asset carrier differs from frozen paint inputs")
        registry_inputs = registry_endpoint_inputs_for_objects(objects, frozen_files=resources[2])
    if timeline is not None and type(timeline) is not ResolvedVisualTimelineV2:
        raise ReplayError("Split lifecycle requires the exact typed timeline")
    if timeline is not None:
        timeline = _split_causal_timeline(timeline, actions, structural_timeline)
    context = _SplitReplayContext(layout.model_dump_json(), tuple(item.model_dump_json() for item in actions),
                                 initial, asset_bytes, timeline.model_dump_json() if timeline is not None else None,
                                 split_inputs, layout_sha256,
                                 structural_timeline.model_dump_json() if structural_timeline is not None else None,
                                 registry_inputs)
    # This legacy map is one ordinary insert per action. Split retains its
    # complete (action, result) treatment inventory in the attributed capture.
    ordinary_insert_ids = {item.action.action_id for item in actions
                           if isinstance(item.action, EvidenceAction) and item.action.verb == "insert_evidence"}
    return replay_chronology(objects, initial.hierarchy, {row.object_id: row for row in initial.objects},
        dict(initial.state_versions), actions,
        tuple((row.board_id, row.start_ms, row.end_ms) for row in layout.activations), duration_ms,
        _split_context=context, evidence_treatments=tuple(row for row in layout.evidence_treatments
            if row.action_id in ordinary_insert_ids))


def _require_split_initial(layout, initial):
    from atme.render.v2_state import FrameObject, FrameTransform

    objects = {obj.object_id: obj for obj in layout.objects}
    expected = tuple(FrameObject(object_id=obj.object_id, board_id=obj.board_id, state=obj.initial_state,
        visible=obj.visible, opacity=obj.opacity, reveal_fraction=float(obj.visible),
        transform=FrameTransform.from_contract(obj.transform)) for obj in sorted(layout.objects, key=lambda obj: obj.object_id))
    if (type(initial) is not ReplaySample or initial.at_ms != 0 or initial.objects != expected
            or initial.hierarchy != HierarchySnapshot.from_objects(objects)
            or len(dict(initial.state_versions)) != len(initial.state_versions)):
        raise ReplayError("Split replay requires exact authored initial state")


@dataclass(frozen=True)
class ChronologicalReplay:
    duration_ms: int
    authored_objects_json: tuple[tuple[str, str], ...]
    checkpoints: tuple[ReplayCheckpoint, ...]
    evidence_treatments_json: tuple[tuple[str, str], ...] = ()
    evidence_reads_json: tuple[tuple[str, str], ...] = ()

    def before_action(self, action_id: str) -> ReplaySample:
        """Exact captured precondition, before this operator paints at progress zero."""
        for checkpoint in self.checkpoints:
            for capture in checkpoint.active:
                resolved = capture.resolved
                if (resolved.action.action_id == action_id
                        and resolved.start_ms == checkpoint.at_ms):
                    objects = {key: _OBJECT_ADAPTER.validate_json(value) for key, value in self.authored_objects_json}
                    try:
                        validate_character_hierarchy(objects, checkpoint.hierarchy)
                        validate_illustration_hierarchy(objects, checkpoint.hierarchy)
                    except (UnsupportedHierarchy, ValueError) as exc:
                        raise ReplayError(str(exc)) from exc
                    _require_evidence_capture_authority(capture, self.evidence_treatments_json, self.evidence_reads_json)
                    if isinstance(capture, CapturedEvidenceAction) and (
                            capture.treatment_json != dict(self.evidence_treatments_json).get(action_id)
                                or _evidence_read_json(capture.target_read) != dict(self.evidence_reads_json).get(action_id)
                                or capture.target_read.hierarchy != checkpoint.hierarchy
                                or capture.target_read.state_version != dict(checkpoint.state_versions).get(
                                    capture.target_read.frame.object_id)):
                        raise ReplayError("evidence pre-start differs from its paired target read authority")
                    return ReplaySample(checkpoint.at_ms, capture.baseline,
                                        checkpoint.state_versions, checkpoint.hierarchy)
        raise ReplayError(f"unknown action {action_id}")

    def at(self, at_ms: int) -> ReplaySample:
        if type(at_ms) is not int or not 0 <= at_ms < self.duration_ms:
            raise ReplayError("frame time must be an integer within the resolved duration")
        index = bisect_right(tuple(item.at_ms for item in self.checkpoints), at_ms) - 1
        checkpoint = self.checkpoints[index]
        objects = {key: _OBJECT_ADAPTER.validate_json(value) for key, value in self.authored_objects_json}
        try:
            validate_character_hierarchy(objects, checkpoint.hierarchy)
            validate_illustration_hierarchy(objects, checkpoint.hierarchy)
        except (UnsupportedHierarchy, ValueError) as exc:
            raise ReplayError(str(exc)) from exc
        sampled, envelopes = _sample_active_with_envelopes({item.object_id: item for item in checkpoint.objects},
            checkpoint.active, at_ms, objects, evidence_treatments=dict(self.evidence_treatments_json),
            evidence_reads=dict(self.evidence_reads_json))
        args = (at_ms, _ordered(sampled), checkpoint.state_versions, checkpoint.hierarchy)
        return SplitReplaySample(*args, envelopes) if envelopes else ReplaySample(*args)


def _ordered(frames: dict) -> tuple:
    return tuple(frames[key] for key in sorted(frames))


def version_targets(action, evidence_treatment=None) -> tuple[str, ...]:
    """Exactly preserve legacy mutation history, including transient dim/isolate."""
    if isinstance(action, SplitAction):
        if action.split_policy is None:
            raise ReplayError("Split version targets require an authored policy")
        return (action.split_policy.source_object_id, *[row.object_id for row in action.split_policy.results],
                *_split_logical_write_owners(action.split_policy))
    if isinstance(action, (CameraAction, SoundAction)) or (
        isinstance(action, EvidenceAction) and action.verb == "return_board"
    ):
        return ()
    if isinstance(action, GroupAction):
        if action.hierarchy_policy is None:
            raise ReplayError("hierarchy action requires an explicit authored policy")
        return tuple(action.hierarchy_policy.changed_object_ids)
    if isinstance(action, ReplaceAction):
        return action.from_object_id, action.to_object_id
    if isinstance(action, ConnectionAction):
        return (action.connector_id,)
    if isinstance(action, TargetAction) and action.annotation_policy is not None:
        return tuple(_annotation_object_ids(action))
    if isinstance(action, TargetAction) and action.structured_list_policy is not None:
        return tuple(action.target_ids)
    if (isinstance(action, EvidenceAction) and action.verb == "insert_evidence"
            and evidence_treatment is not None and evidence_treatment.intent.annotation_policy is not None):
        return (action.target_object_id, *_annotation_policy_object_ids(evidence_treatment.intent.annotation_policy))
    return tuple(_action_object_references(action))


def _sample_operator(capture: CapturedAction, at_ms: int, objects: dict, *, evidence_treatments=(), evidence_reads=()) -> dict:
    """Only the operator's owned objects; unrelated sampled poses never commit."""
    from atme.render.v2_state import (
        CountFrameObject,
        FrameObject,
        FramePoint,
        FrameTransform,
        _dim_ratio,
        _ease,
        _interpolate_transform,
        _mix,
    )

    resolved = capture.resolved
    action = resolved.action
    annotation_treatment = _require_evidence_capture_authority(capture, evidence_treatments, evidence_reads)
    if isinstance(action, SplitAction):
        from atme.render.v2_split import CapturedSplitAction, sample_split

        if (type(capture) is not CapturedSplitAction
                or capture.split_capture.action_id != action.action_id
                or (capture.split_capture.start_ms, capture.split_capture.end_ms) != (resolved.start_ms, resolved.end_ms)):
            raise ReplayError("Split operator requires its exact attributed capture")
        return {row.object_id: row for row in sample_split(capture.split_capture, at_ms).objects}
    baseline = {item.object_id: item for item in capture.baseline}
    completed = at_ms >= resolved.end_ms
    progress = _ease((at_ms - resolved.start_ms) / (resolved.end_ms - resolved.start_ms), action.easing)
    result = {}
    if isinstance(action, TargetAction) and action.structured_list_policy is not None:
        for phase, _, end in _structured_list_phase_windows(resolved):
            before = baseline[phase.object_id]
            visible = at_ms >= end
            result[phase.object_id] = replace(before,
                state=action.post_state if completed else before.state,
                visible=visible, reveal_fraction=1.0 if visible else 0.0)
        return result
    if isinstance(action, (GroupAction, CameraAction)) or (
        isinstance(action, EvidenceAction) and action.verb == "return_board"
    ):
        return result
    if isinstance(action, TargetAction) and action.verb == "count":
        before = baseline[action.target_ids[0]]
        values = {field.name: getattr(before, field.name) for field in fields(FrameObject)}
        values["state"] = action.post_state if completed else before.state
        result[before.object_id] = CountFrameObject(**values,
            display_text=count_at_ms(action.count_policy, resolved.start_ms, resolved.end_ms, at_ms, action.easing),
            count_value=count_value_at_ms(action.count_policy, resolved.start_ms, resolved.end_ms, at_ms, action.easing))
        return result
    if isinstance(action, TargetAction) and action.annotation_policy is not None:
        for phase, start, end in _annotation_phase_windows(resolved):
            if at_ms < start:
                continue
            fraction = _ease((at_ms - start) / (end - start), action.easing)
            before = baseline[phase.object_id]
            result[phase.object_id] = replace(before, state="visible" if at_ms >= end else before.state,
                                              visible=fraction > 0, reveal_fraction=fraction)
        return result
    if isinstance(action, EvidenceAction):
        before = baseline[action.target_object_id]
        result[before.object_id] = replace(before, state=action.post_state if completed else before.state,
                                          visible=True, opacity=before.opacity * progress, reveal_fraction=1.0)
        if annotation_treatment is not None:
            from atme.render.v2_split_identity import _stored_value

            treatment = annotation_treatment
            target_id = treatment.intent.annotation_target_id
            read = capture.target_read
            target_json = json.dumps(_stored_value(objects[target_id]), sort_keys=True,
                                     separators=(",", ":"), allow_nan=False)
            if (_evidence_read_json(read) != dict(evidence_reads).get(action.action_id) or read.object_json != target_json
                    or read.frame != baseline[target_id] or read.state_version < 1):
                raise ReplayError("evidence capture changed its read-only target receipt")
            for phase, start, end in _annotation_policy_phase_windows(
                    treatment.intent.annotation_policy, resolved.start_ms, resolved.end_ms):
                if at_ms < start:
                    continue
                fraction = _ease((at_ms - start) / (end - start), action.easing)
                frame = baseline[phase.object_id]
                result[phase.object_id] = replace(frame, state="visible" if at_ms >= end else frame.state,
                                                  visible=fraction > 0, reveal_fraction=fraction)
        return result
    if isinstance(action, ReplaceAction):
        source, destination = baseline[action.from_object_id], baseline[action.to_object_id]
        if action.verb == "morph":
            geometry = (None if completed or progress == 0 else interpolate_geometry(
                objects[source.object_id], objects[destination.object_id], action.morph_policy, progress))
            transform = FrameTransform(
                FramePoint(_mix(source.transform.position.x, destination.transform.position.x, progress),
                           _mix(source.transform.position.y, destination.transform.position.y, progress)),
                _mix(source.transform.scale_x, destination.transform.scale_x, progress),
                _mix(source.transform.scale_y, destination.transform.scale_y, progress),
                _mix(source.transform.rotation_degrees, destination.transform.rotation_degrees, progress),
                FramePoint(_mix(source.transform.origin.x, destination.transform.origin.x, progress),
                           _mix(source.transform.origin.y, destination.transform.origin.y, progress)))
            result[source.object_id] = replace(
                source, state="removed" if completed else source.state, visible=not completed,
                opacity=0 if completed else _mix(source.opacity, destination.opacity, progress),
                reveal_fraction=0 if completed else 1, transform=transform, morph_geometry=geometry)
            result[destination.object_id] = replace(
                destination, state=action.post_state if completed else destination.state,
                visible=completed, reveal_fraction=1 if completed else 0)
        else:
            result[source.object_id] = replace(source, state="removed" if completed else source.state,
                                               visible=not completed, opacity=source.opacity * (1 - progress),
                                               reveal_fraction=0.0 if completed else source.reveal_fraction)
            result[destination.object_id] = replace(
                destination, state=action.post_state if completed else destination.state,
                visible=progress > 0 or completed, opacity=destination.opacity * progress,
                reveal_fraction=1.0 if progress > 0 or completed else 0.0)
        return result
    if isinstance(action, TargetAction) and action.verb == "isolate":
        for key in capture.context_root_ids:
            before = baseline[key]
            result[key] = before if completed else replace(before, opacity=before.opacity * _dim_ratio(progress))
        for key in action.target_ids:
            if completed:
                result[key] = replace(baseline[key], state=action.post_state)
        return result
    targets = (action.connector_id,) if isinstance(action, ConnectionAction) else action.target_ids
    for key in targets:
        before = baseline[key]
        state = action.post_state if completed else before.state
        if isinstance(action, ConnectionAction):
            fraction = progress if action.verb == "connect" else 1 - progress
            after = replace(before, state=state, visible=not completed or action.verb == "connect",
                            reveal_fraction=fraction)
        elif isinstance(action, TargetAction):
            if action.verb == "exit":
                after = replace(before, state=state, visible=not completed,
                                opacity=_mix(before.opacity, 0, progress))
            elif action.verb == "enter":
                after = replace(before, state=state, visible=True,
                                opacity=before.opacity * progress, reveal_fraction=1.0)
            elif action.verb == "highlight":
                after = replace(before, state=state, emphasis_fraction=progress)
            elif action.verb == "cross_out":
                after = replace(before, state=state, cross_out_fraction=progress)
            elif action.verb == "dim":
                after = replace(before, state=state, opacity=before.opacity * _dim_ratio(progress))
            else:
                after = replace(before, state=state, visible=True, reveal_fraction=progress)
        elif action.verb == "fade":
            after = replace(before, state=state, visible=before.visible or action.opacity > 0,
                            opacity=_mix(before.opacity, action.opacity, progress))
        else:
            after = replace(before, state=state, transform=_interpolate_transform(
                before.transform, action.destination, progress, action.verb))
        result[key] = after
    return result


def _sample_active(committed: dict, active: tuple[CapturedAction, ...], at_ms: int, objects: dict,
                   *, evidence_treatments=(), evidence_reads=()) -> dict:
    return _sample_active_with_envelopes(committed, active, at_ms, objects,
                                         evidence_treatments=evidence_treatments, evidence_reads=evidence_reads)[0]


def _sample_active_with_envelopes(committed, active, at_ms, objects, *, evidence_treatments=(), evidence_reads=()):
    from atme.render.v2_split import sample_split

    result = dict(committed)
    envelopes = []
    for capture in sorted(active, key=lambda row: row.resolved_index):
        result.update(_sample_operator(capture, at_ms, objects,
            evidence_treatments=evidence_treatments, evidence_reads=evidence_reads))
        if isinstance(capture.resolved.action, SplitAction) and capture.resolved.start_ms <= at_ms < capture.resolved.end_ms:
            envelopes.extend(sample_split(capture.split_capture, at_ms).envelopes)
    return result, tuple(envelopes)


def supports_operator(action) -> bool:
    return (isinstance(action, (TransformAction, ConnectionAction, CameraAction, ReplaceAction))
                     or isinstance(action, EvidenceAction) and action.verb in {"insert_evidence", "return_board"}
                     or isinstance(action, GroupAction) and action.hierarchy_policy is not None
                     and action.verb in {"group", "ungroup"}
                     or isinstance(action, TargetAction) and (action.annotation_policy is not None
                         or action.verb == "count" and action.count_policy is not None or action.verb in {
                         "reveal", "write", "draw", "enter", "exit", "progressive_reveal",
                         "highlight", "cross_out", "dim", "isolate"}))


def _validate_operators(actions: tuple, split_context=None) -> None:
    for item in actions:
        action = item.action
        if not supports_operator(action) and not (type(split_context) is _SplitReplayContext and isinstance(action, SplitAction)):
            raise ReplayError(f"action {action.action_id} has no chronological operator for {action.verb}")
    if any(isinstance(item.action, GroupAction) for item in actions) and any(
        isinstance(item.action, EvidenceAction) and item.action.verb == "return_board"
        and item.return_hierarchy_receipt is None for item in actions
    ):
        raise ReplayError("hierarchy returns require an exact retained-board receipt")


def _owned_write_ids(action, frames: dict, evidence_treatment=None) -> set[str]:
    if isinstance(action, (CameraAction, GroupAction)) or (
        isinstance(action, EvidenceAction) and action.verb == "return_board"
    ):
        return set()
    if isinstance(action, TargetAction) and action.verb == "isolate":
        return {key for key, frame in frames.items() if frame.board_id == action.board_id}
    return set(version_targets(action, evidence_treatment))


def _validate_owned_overlaps(actions: tuple, frames: dict, evidence_treatments=None) -> None:
    # Captured full local frames may only commit when their write sets are
    # disjoint. Read references (annotation targets / connector endpoints) are
    # not writes; the caller's geometry/lifetime validation still reserves them.
    treatments = evidence_treatments or {}
    for index, item in enumerate(actions):
        owned = _owned_write_ids(item.action, frames, treatments.get(item.action.action_id))
        for other in actions[index + 1:]:
            if other.start_ms >= item.end_ms:
                break
            overlap = owned.intersection(_owned_write_ids(other.action, frames, treatments.get(other.action.action_id)))
            if overlap:
                raise ReplayError(f"overlapping actions on {min(overlap)} need an explicit composition rule")


def _assert_start_state(resolved, sample: dict, versions: dict, hierarchy, objects: dict):
    action = resolved.action
    try:
        validate_character_transition(action, objects, hierarchy)
        validate_illustration_transition(action, objects, hierarchy)
        visibility_closure = group_visibility_closure(action, objects, hierarchy)
    except (UnsupportedHierarchy, ValueError) as exc:
        raise ReplayError(str(exc)) from exc
    if isinstance(action, TargetAction) and action.structured_list_policy is not None:
        try:
            return validate_structured_list_capture(resolved, objects, hierarchy, sample, versions)
        except ValueError as exc:
            raise ReplayError(str(exc)) from exc
    if isinstance(action, TargetAction) and action.verb == "count":
        key = action.target_ids[0]
        obj = objects[key]
        if not isinstance(obj, TextObject) or obj.object_type != "text":
            raise ReplayError("count needs one supported single-line text object")
        captured_text = getattr(sample[key], "display_text", obj.text)
        if captured_text != action.count_policy.start_text:
            raise ReplayError(f"count {action.action_id} has stale captured starting text")
        captured_value = getattr(sample[key], "count_value", None)
        if (captured_value is not None
                and Fraction(*captured_value) != Fraction(count_decimal(action.count_policy.start_value))):
            raise ReplayError(f"count {action.action_id} has stale captured numeric value")
    if isinstance(action, TransformAction) and action.verb != "fade":
        # Channel purity depends on the captured chronological source, not the
        # initial layout (a prior Group can change its local coordinate system).
        for key in action.target_ids:
            before, after = sample[key].transform, action.destination
            if action.verb == "move":
                unused_changed = (
                    after.scale_x != before.scale_x or after.scale_y != before.scale_y
                    or after.rotation_degrees != before.rotation_degrees
                    or after.origin.x != before.origin.x or after.origin.y != before.origin.y
                )
            elif action.verb == "scale":
                unused_changed = (
                    after.position.x != before.position.x or after.position.y != before.position.y
                    or after.rotation_degrees != before.rotation_degrees
                )
            else:
                unused_changed = (
                    after.position.x != before.position.x or after.position.y != before.position.y
                    or after.scale_x != before.scale_x or after.scale_y != before.scale_y
                )
            if unused_changed:
                raise ReplayError(f"{action.verb} action {action.action_id} changes an unrelated transform channel")
    if isinstance(action, (GroupAction, CameraAction)):
        return
    if isinstance(action, EvidenceAction) and action.verb == "return_board":
        try:
            validate_return_sample(resolved, hierarchy, sample, versions)
        except UnsupportedReturn as exc:
            raise ReplayError(str(exc)) from exc
        return
    targets = ((action.from_object_id,) if isinstance(action, ReplaceAction) else
               (action.connector_id,) if isinstance(action, ConnectionAction) else
               (action.target_ids[0],) if isinstance(action, TargetAction) and action.annotation_policy is not None else
               tuple(_action_object_references(action)))
    if action.expected_state is not None and any(sample[key].state != action.expected_state for key in targets):
        raise ReplayError(f"action {action.action_id} has a stale chronological start state")
    return visibility_closure


def _reserve_group_visibility(resolved, reserved, objects, hierarchy, actions) -> None:
    """Reserve captured descendants for the whole half-open action interval.

    The operator still writes/version-increments only its exact roots. Reuse
    existing read/write footprints, expanding actual hierarchy and connector
    reads instead of treating their local record IDs as the whole dependency.
    """
    from atme.render.v2_split import _reservation_footprint

    for other in actions:
        if (other is resolved or other.start_ms >= resolved.end_ms or resolved.start_ms >= other.end_ms):
            continue
        writes, reads = _reservation_footprint(other.action)
        try:
            writes.update(group_visibility_closure(other.action, objects, hierarchy))
        except UnsupportedHierarchy as exc:
            raise ReplayError(str(exc)) from exc
        if isinstance(other.action, TargetAction):
            if other.action.verb == "isolate" and other.action.board_id == resolved.action.board_id:
                writes.update(reserved)
            if other.action.structured_list_policy is not None:
                from atme.render.v2_list import structured_list_reads

                reads.update(structured_list_reads(other.action, objects, hierarchy))
        for key in tuple(writes):
            obj = objects[key]
            if isinstance(obj, ConnectorObject):
                reads.update(value for value in (obj.source_object_id, obj.destination_object_id) if value is not None)
        reads.update(parent for key in tuple(reads) for parent in hierarchy.ancestors(key))
        if reserved.intersection(writes | reads):
            raise ReplayError("Group enter/exit overlaps reserved descendant writes or relationship reads")


def _hierarchy_conflicts(objects: dict, actions: tuple) -> None:
    """Separate structural-version IDs from true geometry/read dependencies."""
    for item in actions:
        action = item.action
        if not isinstance(action, GroupAction):
            continue
        before, after = validate_authored_hierarchy(action, objects)
        mutation_ids = {action.container_id, *action.target_ids}
        dependencies = set(mutation_ids)
        for snapshot in (before, after):
            for root in action.target_ids:
                dependencies.update(snapshot.ancestors(root))
                # Descendants move in world space even if their local pose is retained.
                mutation_ids.update(node.object_id for node in snapshot.nodes if root in snapshot.ancestors(node.object_id))
            dependencies.update(snapshot.ancestors(action.container_id))
        dependencies.update(mutation_ids)
        for other in actions:
            if other is item or not other.start_ms < item.end_ms or not item.start_ms < other.end_ms:
                continue
            other_action = other.action
            referenced = set(_action_object_references(other_action))
            if isinstance(other_action, GroupAction):
                referenced = {other_action.container_id, *other_action.target_ids}
            if isinstance(other_action, (CameraAction, ConnectionAction)):
                # Camera/connector are observers of world-space endpoint chains.
                for snapshot in (before, after):
                    for key in tuple(referenced):
                        referenced.update(snapshot.ancestors(key))
            if (dependencies.intersection(referenced)
                    or isinstance(other_action, TargetAction) and other_action.verb == "isolate"
                    and other_action.board_id == action.board_id):
                raise ReplayError(f"hierarchy {action.action_id} overlaps a geometric participant action")


def replay_chronology(objects: dict, hierarchy: HierarchySnapshot, frames: dict,
                      state_versions: dict[str, int], actions: tuple[ResolvedAction, ...],
                      activations: tuple[tuple[str, int, int], ...], duration_ms: int, *,
                      _split_context=None, evidence_treatments=()) -> ChronologicalReplay:
    """Build every boundary from exact local initial state, independent of seek order.

    Input actions are already resolved contracts. This kernel deliberately does
    not certify asset provenance, camera framing, annotation holds or evidence
    reading geometry; those remain caller validation responsibilities.
    """
    if type(duration_ms) is not int or duration_ms <= 0:
        raise ReplayError("replay requires a positive integer duration")
    if objects.keys() != state_versions.keys() or any(type(value) is not int or value < 1
                                                     for value in state_versions.values()):
        raise ReplayError("replay requires the exact positive state-version inventory")
    try:
        completed_hierarchy_basis(hierarchy, frames)
        hierarchy.validate(objects)
        validate_character_hierarchy(objects, hierarchy)
        validate_illustration_hierarchy(objects, hierarchy)
    except (UnsupportedHierarchy, ValueError) as exc:
        raise ReplayError(str(exc)) from exc
    if objects.keys() != frames.keys():
        raise ReplayError("replay requires the exact local frame inventory")
    from atme.render.v2_split_identity import _stored_value

    action_json = tuple(json.dumps(
        _stored_value(item) if isinstance(item.action, TargetAction)
        and item.action.structured_list_policy is not None else item.model_dump(mode="json"), sort_keys=True,
                                  separators=(",", ":"), allow_nan=False) for item in actions)
    # Detach all mutable caller-owned contract data before creating any checkpoints.
    actions = tuple(ResolvedAction.model_validate_json(value) for value in action_json)
    objects_json = tuple((key, objects[key].model_dump_json()) for key in sorted(objects))
    objects = {key: _OBJECT_ADAPTER.validate_json(value) for key, value in objects_json}
    treatments, treatment_json = {}, {}
    action_map = {item.action.action_id: item.action for item in actions}
    for row in evidence_treatments:
        if type(row) is not EvidenceTreatment:
            raise ReplayError("evidence replay requires exact paired treatment models")
        raw = _stored_value(row)
        treatment = EvidenceTreatment.model_validate(raw, strict=True)
        action = action_map.get(treatment.action_id)
        if (treatment.action_id in treatments or not isinstance(action, EvidenceAction)
                or action.verb != "insert_evidence" or action.target_object_id != treatment.object_id
                or action.board_id != treatment.intent.destination_board_id
                or action.evidence_asset_id != treatment.intent.evidence_asset_id
                or action.destination_state != treatment.intent.destination_state):
            raise ReplayError("evidence replay treatment differs from its exact paired action")
        _validate_evidence_annotation_objects(treatment.object_id, treatment.intent, objects)
        treatments[treatment.action_id] = treatment
        treatment_json[treatment.action_id] = json.dumps(raw, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if (any(item.end_ms > duration_ms for item in actions)
            or list(actions) != sorted(actions, key=lambda item: item.start_ms)
            or len({item.action.action_id for item in actions}) != len(actions)):
        raise ReplayError("actions require unique IDs, monotonic starts and bounded ends")
    split_layout, split_timeline = None, None
    if _split_context is not None:
        from atme.store.contracts_v2 import ExecutableLayoutV2

        if type(_split_context) is not _SplitReplayContext:
            raise ReplayError("unknown private Split replay context")
        split_layout = ExecutableLayoutV2.model_validate_json(_split_context.layout_json)
        _require_split_initial(split_layout, _split_context.initial)
        if (tuple(ResolvedAction.model_validate_json(row) for row in _split_context.action_json) != actions
                or {obj.object_id: obj for obj in split_layout.objects} != objects
                or _split_context.initial.hierarchy != hierarchy
                or {row.object_id: row for row in _split_context.initial.objects} != frames
                or dict(_split_context.initial.state_versions) != state_versions
                or tuple((row.board_id, row.start_ms, row.end_ms) for row in split_layout.activations) != activations):
            raise ReplayError("Split context differs from actual replay inputs")
        from atme.render.v2_split_paint import _verified_split_asset_pins

        _verified_split_asset_pins(split_layout, _split_context.asset_bytes,
            {obj.asset_id for obj in objects.values() if obj.asset_id is not None})
        from atme.render.v2_media_view import validate_media_ranges
        from atme.store.contracts_v2 import ResolvedAsset

        assets = {row.asset_id: ResolvedAsset.model_validate_json(row.resolved_json)
                  for row in _split_context.asset_bytes.rows} if _split_context.asset_bytes else {}
        validate_media_ranges(objects, assets, duration_ms)
        if _split_context.timeline_json is not None:
            from atme.render.v2_state import _validate_pair_static
            from atme.store.contracts_v2 import (
                ResolvedVisualTimelineV2,
                _split_packet_digest,
            )

            structural_timeline = (ResolvedVisualTimelineV2.model_validate_json(_split_context.structural_timeline_json)
                                   if _split_context.structural_timeline_json is not None else None)
            split_timeline = _split_causal_timeline(json.loads(_split_context.timeline_json), actions, structural_timeline)
            if tuple(split_timeline.actions) != actions or split_timeline.duration_ms != duration_ms:
                raise ReplayError("Split lifecycle timeline differs from the complete replay chronology")
            paired = _validate_pair_static(split_layout, split_timeline,
                (_split_context.layout_sha256 if _split_context.layout_sha256 is not None
                 else _split_packet_digest(split_layout.model_dump(mode="json"))), hierarchy,
                structural_timeline=structural_timeline, registry_inputs=_split_context.registry_inputs,
                split_inputs=_split_context.split_inputs)
            if {key: row.state_version for key, row in paired.initial.items()} != state_versions:
                raise ReplayError("Split lifecycle timeline differs from the actual initial versions")
    _validate_operators(actions, _split_context)
    for item in actions:
        if not set(_action_object_references(item.action)) <= frames.keys():
            raise ReplayError("an action references a missing local frame")
        if (isinstance(item.action, TargetAction) and item.action.structured_list_policy is not None
                and not any(board == item.action.board_id and start <= item.start_ms and item.end_ms <= end
                            for board, start, end in activations)):
            raise ReplayError("structured list progression requires one active board interval")
        try:
            visibility_roots = group_visibility_roots(item.action, objects)
        except UnsupportedHierarchy as exc:
            raise ReplayError(str(exc)) from exc
        if visibility_roots and not any(
            board == item.action.board_id and start <= item.start_ms and item.end_ms <= end
            for board, start, end in activations
        ):
            raise ReplayError("Group enter/exit requires one active board interval")
    _validate_owned_overlaps(actions, frames, treatments)
    try:
        _hierarchy_conflicts(objects, actions)
    except UnsupportedHierarchy as exc:
        raise ReplayError(str(exc)) from exc
    for item in actions:
        if isinstance(item.action, (GroupAction, SplitAction)) and not any(
            board == item.action.board_id and start <= item.start_ms and item.end_ms < end
            and item.end_ms < duration_ms for board, start, end in activations
        ):
            raise ReplayError("structural completion requires an active visible destination sample")
    # ordinary end=0, structural end=1, starts=2; stable resolved index within phase.
    events = sorted((time, phase, index) for index, item in enumerate(actions)
                    for time, phase in ((item.start_ms, 2),
                                        (item.end_ms, 1 if isinstance(item.action, GroupAction) else 0)))
    committed, versions, active = dict(frames), dict(state_versions), {}
    count_origins, split_removed, read_json = {}, set(), {}
    checkpoints = [ReplayCheckpoint(0, _ordered(committed), tuple(sorted(versions.items())), hierarchy, ())]
    for time, phase, index in events:
        resolved = actions[index]
        action = resolved.action
        if phase == 2:
            sample = _sample_active(committed, tuple(active.values()), time, objects,
                evidence_treatments=treatment_json, evidence_reads=read_json)
            treatment = treatments.get(action.action_id)
            if split_removed.intersection(version_targets(action, treatment)):
                raise ReplayError("a removed Split source cannot be edited or resurrected")
            if isinstance(action, SplitAction):
                before = ReplaySample(time, _ordered(sample), tuple(sorted(versions.items())), hierarchy)
                active[index] = _capture_split_observed(split_layout, before, actions, index, count_origins,
                                                       _split_context.asset_bytes, lifecycle_timeline=split_timeline,
                                                       split_inputs=_split_context.split_inputs)
                checkpoint = ReplayCheckpoint(time, _ordered(committed), tuple(sorted(versions.items())),
                                              hierarchy, tuple(active[key] for key in sorted(active)))
                if checkpoints[-1].at_ms == time:
                    checkpoints[-1] = checkpoint
                else:
                    checkpoints.append(checkpoint)
                continue
            reads = _assert_start_state(resolved, sample, versions, hierarchy, objects)
            if reads and isinstance(action, TargetAction) and action.verb in {"enter", "exit"}:
                _reserve_group_visibility(resolved, reads, objects, hierarchy, actions)
            if isinstance(action, TargetAction) and action.structured_list_policy is not None:
                from atme.render.v2_split import _reservation_footprint

                reserved = set(action.target_ids) | set(reads)
                for other in actions:
                    if (other is resolved or other.start_ms >= resolved.end_ms
                            or resolved.start_ms >= other.end_ms):
                        continue
                    writes, peer_reads = _reservation_footprint(other.action)
                    if (isinstance(other.action, TargetAction) and other.action.verb == "isolate"
                            and other.action.board_id == action.board_id):
                        writes.update(reserved)
                    if (isinstance(other.action, TargetAction)
                            and other.action.structured_list_policy is not None):
                        from atme.render.v2_list import structured_list_reads

                        peer_reads.update(structured_list_reads(other.action, objects, hierarchy))
                    if reserved.intersection(writes) or set(action.target_ids).intersection(peer_reads):
                        raise ReplayError("structured list overlaps reserved item or ancestor dependency writes")
            context_roots = ()
            if isinstance(action, TargetAction) and action.verb == "isolate":
                try:
                    from atme.render.v2_media_view import media_visual_view

                    context_roots = isolation_context_roots(objects, hierarchy, sample, action,
                        media_view=media_visual_view(objects, time), end_ms=resolved.end_ms)
                except UnsupportedIsolation as exc:
                    raise ReplayError(str(exc)) from exc
            if treatment is not None and treatment.intent.annotation_policy is not None:
                policy = treatment.intent.annotation_policy
                if any(sample[key].state != "hidden" or sample[key].visible or sample[key].reveal_fraction != 0
                       or versions[key] != state_versions[key] for key in _annotation_policy_object_ids(policy)):
                    raise ReplayError("evidence annotation requires untouched hidden notes")
                target_id = treatment.intent.annotation_target_id
                read = EvidenceTargetRead(json.dumps(_stored_value(objects[target_id]), sort_keys=True,
                    separators=(",", ":"), allow_nan=False), sample[target_id], versions[target_id], hierarchy)
                read_json[action.action_id] = _evidence_read_json(read)
                active[index] = CapturedEvidenceAction(index, action_json[index], _ordered(sample), context_roots,
                                                       treatment_json[action.action_id], read)
            else:
                active[index] = CapturedAction(index, action_json[index], _ordered(sample), context_roots)
        elif phase == 0:
            capture = active[index]
            delta = _sample_operator(capture, time, objects,
                evidence_treatments=treatment_json, evidence_reads=read_json)
            if isinstance(action, SplitAction):
                from atme.render.v2_split import _validate_split_completion

                proposed_versions = dict(versions)
                for key in version_targets(action):
                    proposed_versions[key] += 1
                endpoint = _sample_active(committed, tuple(active.values()), time, objects,
                    evidence_treatments=treatment_json, evidence_reads=read_json)
                _validate_split_completion(capture.split_capture, split_layout,
                    ReplaySample(time, _ordered(endpoint), tuple(sorted(proposed_versions.items())), hierarchy),
                    _split_context.asset_bytes)
                split_removed.add(action.split_policy.source_object_id)
            committed.update(delta)
            for key in version_targets(action, treatments.get(action.action_id)):
                versions[key] += 1
            active.pop(index)
        else:
            sample = _sample_active(committed, tuple(active.values()), time, objects,
                evidence_treatments=treatment_json, evidence_reads=read_json)
            try:
                outcome = apply_hierarchy_step(action, objects, hierarchy, sample, versions, action.board_id)
                validate_character_hierarchy(objects, outcome.hierarchy)
                validate_illustration_hierarchy(objects, outcome.hierarchy)
            except (UnsupportedHierarchy, ValueError) as exc:
                raise ReplayError(str(exc)) from exc
            updated = {item.object_id: item for item in outcome.objects}
            for key in action.target_ids:
                committed[key] = replace(committed[key], transform=updated[key].transform)
            committed[action.container_id] = replace(committed[action.container_id], state=action.post_state)
            hierarchy, versions = outcome.hierarchy, dict(outcome.state_versions)
            active.pop(index)
        if _split_context is not None and phase != 2:
            observed = ReplaySample(time, _ordered(_sample_active(committed, tuple(active.values()), time, objects,
                                        evidence_treatments=treatment_json, evidence_reads=read_json)),
                                    tuple(sorted(versions.items())), hierarchy)
            _advance_split_count_origins(count_origins, split_layout, observed, resolved, index,
                                         _split_context.asset_bytes, treatments.get(action.action_id))
        checkpoint = ReplayCheckpoint(time, _ordered(committed), tuple(sorted(versions.items())),
                                      hierarchy, tuple(active[key] for key in sorted(active)))
        if checkpoints[-1].at_ms == time:
            checkpoints[-1] = checkpoint
        else:
            checkpoints.append(checkpoint)
    replay = ChronologicalReplay(duration_ms, objects_json, tuple(checkpoints),
                                  tuple(sorted(treatment_json.items())), tuple(sorted(read_json.items())))
    if split_timeline is not None:
        from atme.render.v2_lifecycle import (
            _split_requires_evidence_lifecycle,
            validate_split_lifecycle,
        )
        from atme.render.v2_split import CapturedSplitAction

        captures = {row.resolved_index: row for checkpoint in replay.checkpoints for row in checkpoint.active
                    if isinstance(row, CapturedSplitAction)}
        inputs = _split_context.split_inputs
        if inputs is None and any(_split_requires_evidence_lifecycle(row.split_capture, objects, split_timeline)
                                  for row in captures.values()):
            from atme.render.v2_split_paint import verify_split_paint_inputs

            inputs = verify_split_paint_inputs(split_layout, _split_context.asset_bytes)
        for capture in captures.values():
            validate_split_lifecycle(capture.split_capture, replay, split_layout, split_timeline, split_inputs=inputs,
                layout_sha256=_split_context.layout_sha256, structural_timeline=structural_timeline,
                registry_inputs=_split_context.registry_inputs)
    return replay


def _capture_split_observed(layout, before, actions, index, origins, asset_bytes, *, lifecycle_timeline=None,
                             split_inputs=None):
    from atme.render.v2_split import (
        CapturedSplitAction,
        _AttributedSplitCapture,
        _capture_split,
        _require_proven_history_relationships,
        validate_split_reservations,
    )

    owner = actions[index]
    args = (owner, layout, before, asset_bytes, tuple(origins[key] for key in sorted(origins)))
    capture = (_capture_split(*args) if split_inputs is None
               else _capture_split(*args, split_inputs=split_inputs))
    if (capture.start_ms, capture.end_ms) != (owner.start_ms, owner.end_ms):
        raise ReplayError("Split capture interval differs from verified owner")
    _require_proven_history_relationships(capture, owner, actions,
        before.hierarchy.object_map({obj.object_id: obj for obj in layout.objects}), before.hierarchy,
        lifecycle_timeline=lifecycle_timeline)
    validate_split_reservations(capture, tuple(row for i, row in enumerate(actions) if i != index))
    attributed = _AttributedSplitCapture(**{field.name: getattr(capture, field.name) for field in fields(capture)},
                                         action_id=owner.action.action_id)
    return CapturedSplitAction(index, owner.model_dump_json(), before.objects, split_capture=attributed)


def _advance_split_count_origins(origins, layout, observed, resolved, index, asset_bytes, evidence_treatment=None):
    from atme.render.v2_split import _preserves_count_content, _SplitCountOrigin
    from atme.render.v2_split_identity import split_content_receipts
    from atme.render.v2_state import CountFrameObject

    action, versions = resolved.action, dict(observed.state_versions)
    for key in version_targets(action, evidence_treatment):
        if isinstance(action, TargetAction) and action.verb == "count":
            frame = observed.object(key)
            if type(frame) is not CountFrameObject:
                raise ReplayError("Count completion lost its known payload")
            content = next(row for row in split_content_receipts(layout, observed, asset_bytes) if row.object_id == key)
            origins[key] = _SplitCountOrigin(key, index, resolved.model_dump_json(), frame.display_text,
                frame.count_value, content.content_sha256, versions[key], versions[key])
        elif key in origins:
            if _preserves_count_content(action):
                origin = origins[key]
                origins[key] = replace(origin, current_version=versions[key],
                    preserving_writers=(*origin.preserving_writers, (index, resolved.model_dump_json(), versions[key])))
            else:
                del origins[key]


def _capture_split_from_history(layout, initial: ReplaySample, actions: tuple[ResolvedAction, ...],
                                resolved_index: int, duration_ms: int, asset_bytes, *, timeline=None):
    """Return the exact scheduler capture, with no duplicate provenance clock."""
    from atme.render.v2_split_identity import _stored_value

    actions = tuple(ResolvedAction.model_validate(_stored_value(item)) for item in actions)
    if (type(resolved_index) is not int or not 0 <= resolved_index < len(actions)
            or len({item.action.action_id for item in actions}) != len(actions)):
        raise ReplayError("Split history needs one exact owner index and unique action IDs")
    if (list(actions) != sorted(actions, key=lambda item: item.start_ms)
            or any(item.end_ms > duration_ms for item in actions)):
        raise ReplayError("Split history requires the complete bounded resolved chronology")
    owner = actions[resolved_index]
    if not isinstance(owner.action, SplitAction) or owner.end_ms > duration_ms:
        raise ReplayError("Split history owner is not a bounded Split")
    replay = _replay_split_chronology(layout, initial, actions, duration_ms, asset_bytes, timeline=timeline)
    for checkpoint in replay.checkpoints:
        for capture in checkpoint.active:
            if capture.resolved_index == resolved_index and capture.resolved.action.action_id == owner.action.action_id:
                return capture
    raise ReplayError("Split owner capture was not retained by the scheduler")
