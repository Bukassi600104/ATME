"""Immutable chronological local-state replay for the v2 hierarchy integration.

This is the shared clock/state kernel, not a replacement production gate. Callers
must retain plan/layout/asset/geometry validation. Public frames still reject
GroupActions until camera, annotation lifetime and retained-board consumers use
this same clock. Group/annotation combinations reject until their dependencies
are integrated. Group/return requires an exact retained-board hierarchy receipt.

At a timestamp: ordinary completions, structural completions in resolved order,
then starts. An active operator always samples its captured start pose. A Group
reads the full sampled boundary, but commits ONLY its member local transforms,
shell state, hierarchy and structural versions -- never unrelated partial poses.
"""

from __future__ import annotations

import json
from bisect import bisect_right
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from pydantic import TypeAdapter

from atme.render.v2_hierarchy import (
    HierarchySnapshot,
    UnsupportedHierarchy,
    validate_authored_hierarchy,
)
from atme.render.v2_hierarchy_replay import (
    apply_hierarchy_step,
    completed_hierarchy_basis,
)
from atme.render.v2_morph import interpolate_geometry
from atme.render.v2_return import UnsupportedReturn, validate_return_sample
from atme.store.contracts_v2 import (
    CameraAction,
    ConnectionAction,
    EvidenceAction,
    ExecutableObject,
    GroupAction,
    ReplaceAction,
    ResolvedAction,
    SoundAction,
    TargetAction,
    TransformAction,
    _action_object_references,
    _annotation_object_ids,
    _annotation_phase_windows,
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

    @property
    def resolved(self) -> ResolvedAction:
        # Contracts are mutable models; never expose a stored mutable instance.
        return ResolvedAction.model_validate_json(self.resolved_json)


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
class ChronologicalReplay:
    duration_ms: int
    authored_objects_json: tuple[tuple[str, str], ...]
    checkpoints: tuple[ReplayCheckpoint, ...]

    def before_action(self, action_id: str) -> ReplaySample:
        """Exact captured precondition, before this operator paints at progress zero."""
        for checkpoint in self.checkpoints:
            for capture in checkpoint.active:
                resolved = capture.resolved
                if (resolved.action.action_id == action_id
                        and resolved.start_ms == checkpoint.at_ms):
                    return ReplaySample(checkpoint.at_ms, capture.baseline,
                                        checkpoint.state_versions, checkpoint.hierarchy)
        raise ReplayError(f"unknown action {action_id}")

    def at(self, at_ms: int) -> ReplaySample:
        if type(at_ms) is not int or not 0 <= at_ms < self.duration_ms:
            raise ReplayError("frame time must be an integer within the resolved duration")
        index = bisect_right(tuple(item.at_ms for item in self.checkpoints), at_ms) - 1
        checkpoint = self.checkpoints[index]
        objects = {key: _OBJECT_ADAPTER.validate_json(value) for key, value in self.authored_objects_json}
        sampled = _sample_active({item.object_id: item for item in checkpoint.objects},
                                 checkpoint.active, at_ms, objects)
        return ReplaySample(at_ms, _ordered(sampled), checkpoint.state_versions, checkpoint.hierarchy)


def _ordered(frames: dict) -> tuple:
    return tuple(frames[key] for key in sorted(frames))


def version_targets(action) -> tuple[str, ...]:
    """Exactly preserve legacy mutation history, including transient dim/isolate."""
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
    return tuple(_action_object_references(action))


def _sample_operator(capture: CapturedAction, at_ms: int, objects: dict) -> dict:
    """Only the operator's owned objects; unrelated sampled poses never commit."""
    from atme.render.v2_state import (
        FramePoint,
        FrameTransform,
        _dim_ratio,
        _ease,
        _interpolate_transform,
        _mix,
    )

    resolved = capture.resolved
    action = resolved.action
    baseline = {item.object_id: item for item in capture.baseline}
    completed = at_ms >= resolved.end_ms
    progress = _ease((at_ms - resolved.start_ms) / (resolved.end_ms - resolved.start_ms), action.easing)
    result = {}
    if isinstance(action, (GroupAction, CameraAction)) or (
        isinstance(action, EvidenceAction) and action.verb == "return_board"
    ):
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
        if not completed:
            for key, before in baseline.items():
                if (before.board_id == action.board_id and key not in action.target_ids and before.visible
                        and before.opacity > 0 and before.reveal_fraction == 1):
                    result[key] = replace(before, opacity=before.opacity * _dim_ratio(progress))
        else:
            # Restore only context actually dimmed from this captured baseline.
            result.update({key: before for key, before in baseline.items()
                           if before.board_id == action.board_id and key not in action.target_ids
                           and before.visible and before.opacity > 0 and before.reveal_fraction == 1})
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


def _sample_active(committed: dict, active: tuple[CapturedAction, ...], at_ms: int, objects: dict) -> dict:
    result = dict(committed)
    for capture in active:
        result.update(_sample_operator(capture, at_ms, objects))
    return result


def supports_operator(action) -> bool:
    return (isinstance(action, (TransformAction, ConnectionAction, CameraAction, ReplaceAction))
                     or isinstance(action, EvidenceAction) and action.verb in {"insert_evidence", "return_board"}
                     or isinstance(action, GroupAction) and action.hierarchy_policy is not None
                     and action.verb in {"group", "ungroup"}
                     or isinstance(action, TargetAction) and (action.annotation_policy is not None or action.verb in {
                         "reveal", "write", "draw", "enter", "exit", "progressive_reveal",
                         "highlight", "cross_out", "dim", "isolate"}))


def _validate_operators(actions: tuple) -> None:
    for item in actions:
        action = item.action
        if not supports_operator(action):
            raise ReplayError(f"action {action.action_id} has no chronological operator for {action.verb}")
    if any(isinstance(item.action, GroupAction) for item in actions) and any(
        isinstance(item.action, TargetAction) and item.action.annotation_policy is not None
        for item in actions
    ):
        raise ReplayError("hierarchy annotation lifetimes and retained-board receipts require consumer integration")
    if any(isinstance(item.action, GroupAction) for item in actions) and any(
        isinstance(item.action, EvidenceAction) and item.action.verb == "return_board"
        and item.return_hierarchy_receipt is None for item in actions
    ):
        raise ReplayError("hierarchy returns require an exact retained-board receipt")


def _owned_write_ids(action, frames: dict) -> set[str]:
    if isinstance(action, (CameraAction, GroupAction)) or (
        isinstance(action, EvidenceAction) and action.verb == "return_board"
    ):
        return set()
    if isinstance(action, TargetAction) and action.verb == "isolate":
        return {key for key, frame in frames.items() if frame.board_id == action.board_id}
    return set(version_targets(action))


def _validate_owned_overlaps(actions: tuple, frames: dict) -> None:
    # Captured full local frames may only commit when their write sets are
    # disjoint. Read references (annotation targets / connector endpoints) are
    # not writes; the caller's geometry/lifetime validation still reserves them.
    for index, item in enumerate(actions):
        owned = _owned_write_ids(item.action, frames)
        for other in actions[index + 1:]:
            if other.start_ms >= item.end_ms:
                break
            overlap = owned.intersection(_owned_write_ids(other.action, frames))
            if overlap:
                raise ReplayError(f"overlapping actions on {min(overlap)} need an explicit composition rule")


def _assert_start_state(resolved, sample: dict, versions: dict, hierarchy) -> None:
    action = resolved.action
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
                      activations: tuple[tuple[str, int, int], ...], duration_ms: int) -> ChronologicalReplay:
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
    except UnsupportedHierarchy as exc:
        raise ReplayError(str(exc)) from exc
    if objects.keys() != frames.keys():
        raise ReplayError("replay requires the exact local frame inventory")
    action_json = tuple(json.dumps(item.model_dump(mode="json"), sort_keys=True,
                                  separators=(",", ":"), allow_nan=False) for item in actions)
    # Detach all mutable caller-owned contract data before creating any checkpoints.
    actions = tuple(ResolvedAction.model_validate_json(value) for value in action_json)
    objects_json = tuple((key, objects[key].model_dump_json()) for key in sorted(objects))
    objects = {key: _OBJECT_ADAPTER.validate_json(value) for key, value in objects_json}
    if (any(item.end_ms > duration_ms for item in actions)
            or list(actions) != sorted(actions, key=lambda item: item.start_ms)
            or len({item.action.action_id for item in actions}) != len(actions)):
        raise ReplayError("actions require unique IDs, monotonic starts and bounded ends")
    _validate_operators(actions)
    _validate_owned_overlaps(actions, frames)
    try:
        _hierarchy_conflicts(objects, actions)
    except UnsupportedHierarchy as exc:
        raise ReplayError(str(exc)) from exc
    for item in actions:
        if not set(_action_object_references(item.action)) <= frames.keys():
            raise ReplayError("an action references a missing local frame")
        if isinstance(item.action, GroupAction) and not any(
            board == item.action.board_id and start <= item.start_ms and item.end_ms < end
            and item.end_ms < duration_ms for board, start, end in activations
        ):
            raise ReplayError("hierarchy completion requires an active visible destination sample")
    # ordinary end=0, structural end=1, starts=2; stable resolved index within phase.
    events = sorted((time, phase, index) for index, item in enumerate(actions)
                    for time, phase in ((item.start_ms, 2),
                                        (item.end_ms, 1 if isinstance(item.action, GroupAction) else 0)))
    committed, versions, active = dict(frames), dict(state_versions), {}
    checkpoints = [ReplayCheckpoint(0, _ordered(committed), tuple(sorted(versions.items())), hierarchy, ())]
    for time, phase, index in events:
        resolved = actions[index]
        action = resolved.action
        if phase == 2:
            sample = _sample_active(committed, tuple(active.values()), time, objects)
            _assert_start_state(resolved, sample, versions, hierarchy)
            active[index] = CapturedAction(index, action_json[index], _ordered(sample))
        elif phase == 0:
            capture = active.pop(index)
            committed.update(_sample_operator(capture, time, objects))
            for key in version_targets(action):
                versions[key] += 1
        else:
            sample = _sample_active(committed, tuple(active.values()), time, objects)
            try:
                outcome = apply_hierarchy_step(action, objects, hierarchy, sample, versions, action.board_id)
            except UnsupportedHierarchy as exc:
                raise ReplayError(str(exc)) from exc
            updated = {item.object_id: item for item in outcome.objects}
            for key in action.target_ids:
                committed[key] = replace(committed[key], transform=updated[key].transform)
            committed[action.container_id] = replace(committed[action.container_id], state=action.post_state)
            hierarchy, versions = outcome.hierarchy, dict(outcome.state_versions)
            active.pop(index)
        checkpoint = ReplayCheckpoint(time, _ordered(committed), tuple(sorted(versions.items())),
                                      hierarchy, tuple(active[key] for key in sorted(active)))
        if checkpoints[-1].at_ms == time:
            checkpoints[-1] = checkpoint
        else:
            checkpoints.append(checkpoint)
    return ChronologicalReplay(duration_ms, objects_json, tuple(checkpoints))
