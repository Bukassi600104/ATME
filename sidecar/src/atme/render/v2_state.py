"""Pure, random-access frame evaluation for the visual-production v2 runtime.

This module does not render pixels or make a plan production-ready. Every action
must have an explicit visual implementation before it can enter this evaluator;
unsupported verbs fail rather than silently becoming a static layout.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace

from atme.render.v2_annotation import validate_annotation_geometry
from atme.render.v2_camera import (
    CameraViewport,
    UnsupportedCamera,
    camera_segments,
    evaluate_camera,
)
from atme.render.v2_connector import UnsupportedConnector, validate_static_arrow
from atme.render.v2_emphasis import (
    SUPPORTED_HIGHLIGHT_MARKS,
    SUPPORTED_HIGHLIGHT_TEXT,
    UnsupportedEmphasis,
    cross_out_paths,
    emphasis_path,
)
from atme.render.v2_hierarchy import HierarchySnapshot, UnsupportedHierarchy
from atme.render.v2_list import UnsupportedOrderedList, validate_ordered_list
from atme.render.v2_mask import UnsupportedMask, mask_source_region
from atme.render.v2_morph import (
    MorphGeometry,
    UnsupportedMorph,
    geometry_object,
    interpolate_geometry,
    validate_morph_geometry,
)
from atme.render.v2_world import UnsupportedWorldGeometry, world_bounds, world_matrix
from atme.store.contracts_v2 import (
    CameraAction,
    ConnectionAction,
    ConnectorObject,
    ContainerObject,
    EvidenceAction,
    ExecutableLayoutV2,
    GroupAction,
    MarkObject,
    MaskContainer,
    ReplaceAction,
    ResolvedVisualTimelineV2,
    SoundAction,
    TargetAction,
    TextObject,
    Transform,
    TransformAction,
    VisualObject,
    _action_object_references,
    _annotation_object_ids,
    _annotation_phase_windows,
    _require_morph_contract,
    _require_return_board_policy,
    _require_return_contract,
)


class V2FrameError(ValueError):
    """A v2 frame cannot be evaluated without changing authored meaning."""


class UnsupportedVisualAction(V2FrameError):
    """An authored action has no v2 visual runtime implementation yet."""


# Versioned bounded meaning of a transient dim attention cue. The authored
# opacity is restored after the action; this is not a persistent opacity edit.
_DIM_MIN_RATIO = 0.35
_DIM_RAMP_FRACTION = 0.2
_REPLACE_VISUAL_TYPES = frozenset({
    "icon", "pictogram", "character", "device", "document", "chart", "terminal",
})


def _dim_ratio(progress: float) -> float:
    envelope = min(1.0, progress / _DIM_RAMP_FRACTION,
                   (1.0 - progress) / _DIM_RAMP_FRACTION)
    return 1.0 - (1.0 - _DIM_MIN_RATIO) * max(0.0, envelope)


@dataclass(frozen=True)
class FramePoint:
    x: float
    y: float


@dataclass(frozen=True)
class FrameTransform:
    position: FramePoint
    scale_x: float
    scale_y: float
    rotation_degrees: float
    origin: FramePoint

    @classmethod
    def from_contract(cls, value: Transform) -> FrameTransform:
        return cls(
            position=FramePoint(value.position.x, value.position.y),
            scale_x=value.scale_x,
            scale_y=value.scale_y,
            rotation_degrees=value.rotation_degrees,
            origin=FramePoint(value.origin.x, value.origin.y),
        )


@dataclass(frozen=True)
class FrameObject:
    """Frame state: visible is ancestor/board-effective; opacity and transform are local.

    The compositor applies each ancestor's opacity and transform through nested
    wrappers. Consumers must not mistake these local fields for world values.
    """
    object_id: str
    board_id: str
    state: str
    visible: bool
    opacity: float
    reveal_fraction: float
    transform: FrameTransform
    emphasis_fraction: float = 0.0
    cross_out_fraction: float = 0.0
    morph_geometry: MorphGeometry | None = None


@dataclass(frozen=True)
class FrameSnapshot:
    at_ms: int
    active_board_id: str | None
    objects: tuple[FrameObject, ...]
    camera: CameraViewport
    hierarchy: HierarchySnapshot

    def object(self, object_id: str) -> FrameObject:
        for item in self.objects:
            if item.object_id == object_id:
                return item
        raise KeyError(object_id)


def _ease(value: float, easing: str) -> float:
    progress = max(0.0, min(1.0, value))
    if easing == "linear":
        return progress
    if easing == "step":
        return 1.0 if progress >= 1.0 else 0.0
    if easing == "ease_in":
        return progress * progress
    if easing == "ease_out":
        return 1.0 - (1.0 - progress) ** 2
    if easing == "ease_in_out":
        return progress * progress * (3.0 - 2.0 * progress)
    raise V2FrameError(f"unknown action easing: {easing}")


def _mix(start: float, end: float, progress: float) -> float:
    return start + (end - start) * progress


def _ancestor_ids(obj, object_map: dict) -> tuple[str, ...]:
    ancestors = []
    parent_id = obj.parent_id
    while parent_id is not None:
        ancestors.append(parent_id)
        parent_id = object_map[parent_id].parent_id
    return tuple(ancestors)


def validate_static_hierarchy(layout: ExecutableLayoutV2, objects: dict | None = None) -> None:
    """Fail closed for hierarchy forms not yet supported by frame and paint paths."""
    if objects is None:
        initial = {obj.object_id: obj for obj in layout.objects}
        objects = HierarchySnapshot.from_objects(initial).object_map(initial)
    for obj in objects.values():
        if obj.clip_id is not None:
            raise V2FrameError(f"v2 object {obj.object_id} has unsupported clip_id")
        if isinstance(obj, ContainerObject):
            if isinstance(obj, MaskContainer) and obj.mask_source_object_id is None:
                raise V2FrameError(
                    f"legacy v2 mask {obj.object_id} has no composition semantics"
                )
            if obj.object_type not in {"group", "clip", "mask"}:
                raise V2FrameError(
                    f"v2 {obj.object_type} container {obj.object_id} has no composition semantics"
                )
            if (obj.asset_id is not None or obj.anchors or obj.geometry.points
                    or obj.geometry.corner_radius is not None or obj.style.stroke
                    or obj.style.fill or obj.style.text or obj.style.effect):
                raise V2FrameError(
                    f"v2 {obj.object_type} {obj.object_id} must be a non-painting stacking context"
                )
            if isinstance(obj, MaskContainer):
                try:
                    source = objects[obj.mask_source_object_id]
                    mask_source_region(source, source.transform)
                except UnsupportedMask as exc:
                    raise V2FrameError(str(exc)) from exc
    for obj in objects.values():
        if obj.parent_id is not None and (
            not isinstance(objects[obj.parent_id], ContainerObject)
            or objects[obj.parent_id].object_type not in {"group", "clip", "mask"}
        ):
            raise V2FrameError(f"v2 object {obj.object_id} needs a supported container parent")
        if isinstance(obj, ConnectorObject):
            if obj.parent_id is not None:
                raise V2FrameError(
                    f"v2 connector {obj.object_id} needs inverse parent geometry"
                )
            for endpoint_id in (obj.source_object_id, obj.destination_object_id):
                if endpoint_id is not None and isinstance(objects[endpoint_id], ContainerObject):
                    raise V2FrameError(
                        f"v2 connector {obj.object_id} cannot anchor to a non-painting group"
                    )
                if endpoint_id is not None and any(
                    isinstance(objects[parent_id], ContainerObject)
                    and objects[parent_id].object_type in {"clip", "mask"}
                    for parent_id in _ancestor_ids(objects[endpoint_id], objects)
                ):
                    raise V2FrameError(
                        f"v2 connector {obj.object_id} needs clipped-endpoint geometry, including masks"
                    )


def _interpolate_transform(start: FrameTransform, end: Transform,
                           progress: float, verb: str) -> FrameTransform:
    return FrameTransform(
        position=FramePoint(
            _mix(start.position.x, end.position.x, progress) if verb == "move" else start.position.x,
            _mix(start.position.y, end.position.y, progress) if verb == "move" else start.position.y,
        ),
        scale_x=_mix(start.scale_x, end.scale_x, progress) if verb == "scale" else start.scale_x,
        scale_y=_mix(start.scale_y, end.scale_y, progress) if verb == "scale" else start.scale_y,
        rotation_degrees=(_mix(start.rotation_degrees, end.rotation_degrees, progress)
                          if verb == "rotate" else start.rotation_degrees),
        origin=FramePoint(
            _mix(start.origin.x, end.origin.x, progress)
            if verb in ("scale", "rotate") else start.origin.x,
            _mix(start.origin.y, end.origin.y, progress)
            if verb in ("scale", "rotate") else start.origin.y,
        ),
    )


def _validate_pair(layout: ExecutableLayoutV2, timeline: ResolvedVisualTimelineV2,
                   layout_sha256: str, hierarchy: HierarchySnapshot) -> None:
    if (layout.project_id != timeline.project_id or layout.layout_id != timeline.layout_id
            or layout.plan_id != timeline.plan_id or layout.plan_revision != timeline.plan_revision
            or layout.plan_sha256 != timeline.plan_sha256
            or layout_sha256 != timeline.layout_sha256
            or layout.output_profile != timeline.output_profile
            or layout.style_system_version != timeline.style_system_version
            or layout.asset_registry_version != timeline.asset_registry_version
            or layout.evidence_treatments != timeline.evidence_treatments):
        raise V2FrameError("resolved timeline and executable layout do not describe the same composition")
    resolved_actions = {item.action.action_id: item for item in timeline.actions}
    treatments_by_action = {item.action_id: item for item in layout.evidence_treatments}
    layout_objects = hierarchy.object_map({item.object_id: item for item in layout.objects})
    validate_static_hierarchy(layout, layout_objects)
    state_objects = {item.object_id for item in timeline.initial_object_states}
    if set(layout_objects) != state_objects:
        raise V2FrameError("the resolved timeline must initialize every layout object exactly once")
    initial = {item.object_id: item for item in timeline.initial_object_states}
    for item in timeline.actions:
        action = item.action
        if not isinstance(action, EvidenceAction):
            continue
        if action.verb == "return_board":
            try:
                _require_return_contract(action)
            except ValueError as exc:
                raise UnsupportedVisualAction(str(exc)) from exc
            activations = layout.activations
            destination = next((activation for activation in activations
                                if activation.activation_id == action.destination_activation_id), None)
            prior = next((activation for activation in activations
                          if activation.activation_id == action.prior_destination_activation_id), None)
            source = next((activation for activation in activations
                           if activation.activation_id == action.source_activation_id), None)
            destination_board = next((board for board in layout.boards
                                      if board.board_id == action.destination_board_id), None)
            if destination_board is None:
                raise V2FrameError(f"return_board {action.action_id} has no destination board")
            try:
                _require_return_board_policy(destination_board)
            except ValueError as exc:
                raise V2FrameError(str(exc)) from exc
            if (destination is None or prior is None or source is None
                    or destination.board_id != action.destination_board_id
                    or action.board_id != destination.board_id
                    or prior.board_id != destination.board_id
                    or source.board_id != action.source_board_id
                    or destination.start_ms != item.start_ms
                    or item.end_ms > destination.end_ms
                    or prior is not source and prior.end_ms > source.start_ms
                    or source.end_ms > destination.start_ms
                    or source is not max((a for a in activations if a.end_ms <= destination.start_ms),
                                         key=lambda a: a.end_ms, default=None)
                    or prior is not max((a for a in activations
                                         if a.board_id == destination.board_id
                                         and a.end_ms <= destination.start_ms),
                                        key=lambda a: a.end_ms, default=None)):
                raise V2FrameError(f"return_board {action.action_id} has invalid activation lineage")
            board_objects = {obj.object_id for obj in layout.objects
                             if obj.board_id == destination.board_id}
            if (set(action.expected_object_states) != board_objects
                    or set(action.expected_object_state_versions) != board_objects
                    or destination_board.expected_prior_state != action.expected_state):
                raise V2FrameError(f"return_board {action.action_id} has incomplete board state")
            states = {object_id: initial[object_id].state for object_id in board_objects}
            versions = {object_id: initial[object_id].state_version for object_id in board_objects}
            for earlier in timeline.actions:
                if earlier is item:
                    continue
                previous = earlier.action
                if previous.board_id != destination.board_id:
                    continue
                if (earlier.start_ms < item.start_ms
                        and not any(activation.board_id == destination.board_id
                                    and activation.start_ms <= earlier.start_ms
                                    and earlier.end_ms <= activation.end_ms
                                    for activation in activations)):
                    raise V2FrameError(
                        f"return_board {action.action_id} has an action outside its board activation"
                    )
                if (prior.end_ms <= earlier.start_ms < item.start_ms
                        or earlier.start_ms < prior.end_ms < earlier.end_ms):
                    raise V2FrameError(f"return_board {action.action_id} has off-board mutations")
                if earlier.end_ms > prior.end_ms:
                    continue
                if isinstance(previous, (CameraAction, SoundAction)) or (
                    isinstance(previous, EvidenceAction) and previous.verb == "return_board"
                ):
                    continue
                if isinstance(previous, ReplaceAction):
                    mutations = ((previous.from_object_id, "removed"),
                                 (previous.to_object_id, previous.post_state))
                elif isinstance(previous, ConnectionAction):
                    mutations = ((previous.connector_id, previous.post_state),)
                elif isinstance(previous, TargetAction) and previous.annotation_policy is not None:
                    mutations = ((object_id, "visible") for object_id in _annotation_object_ids(previous))
                else:
                    mutations = ((object_id, previous.post_state)
                                 for object_id in _action_object_references(previous))
                for object_id, state in mutations:
                    if object_id in board_objects:
                        states[object_id] = state
                        versions[object_id] += 1
            if (states != action.expected_object_states
                    or versions != action.expected_object_state_versions):
                raise V2FrameError(f"return_board {action.action_id} changes retained board state")
            continue
        if action.verb != "insert_evidence":
            raise UnsupportedVisualAction(
                f"v2 action {action.action_id} uses {action.verb}, which has no frame implementation"
            )
        treatment = treatments_by_action.get(action.action_id)
        if treatment is None:
            raise UnsupportedVisualAction(
                f"v2 action {action.action_id} uses insert_evidence without executable treatment"
            )
        if (action.target_object_id != treatment.object_id
                or action.evidence_asset_id != treatment.intent.evidence_asset_id
                or action.board_id != treatment.intent.destination_board_id
                or action.destination_board_id != action.board_id
                or action.expected_state != "hidden"
                or action.post_state != action.destination_state
                or action.destination_state != treatment.intent.destination_state):
            raise V2FrameError(f"insert_evidence {action.action_id} changes its authored binding")
    for treatment in layout.evidence_treatments:
        resolved = resolved_actions.get(treatment.action_id)
        if resolved is None or not any(
            activation.board_id == treatment.intent.destination_board_id
            and activation.start_ms <= resolved.start_ms
            and resolved.end_ms + treatment.intent.readable_hold_intent_ms <= activation.end_ms
            for activation in layout.activations
        ):
            raise V2FrameError("evidence readable hold outlasts its destination board")
    for treatment in layout.evidence_treatments:
        obj = layout_objects[treatment.object_id]
        chain = {obj.object_id, *_ancestor_ids(obj, layout_objects)}
        if "rotate" not in treatment.allowed_transformations and any(
            isinstance(other.action, TransformAction)
            and other.action.verb == "rotate"
            and chain.intersection(other.action.target_ids)
            for other in timeline.actions
        ):
            raise V2FrameError(
                f"evidence {treatment.object_id} has an undeclared rotation"
            )
        initial_state = initial[treatment.object_id]
        if (not isinstance(obj, VisualObject) or obj.object_type != "evidence"
                or obj.asset_id != treatment.intent.evidence_asset_id
                or obj.opacity <= 0 or initial_state.state != "hidden"
                or initial_state.visible):
            raise V2FrameError(f"evidence {treatment.object_id} needs an untouched hidden source")
        resolved = resolved_actions[treatment.action_id]
        hold_end = resolved.end_ms + treatment.intent.readable_hold_intent_ms
        for other in timeline.actions:
            if other is resolved or isinstance(other.action, SoundAction):
                continue
            if (other.action.board_id == obj.board_id
                    and other.start_ms < hold_end and other.end_ms > resolved.start_ms):
                raise V2FrameError(
                    f"evidence {treatment.object_id} needs an uninterrupted readable insert and hold"
                )
    mask_sources = {obj.mask_source_object_id for obj in layout.objects
                    if isinstance(obj, MaskContainer)}
    for source_id in mask_sources:
        source_state = initial[source_id]
        if (source_state.state != "visible" or not source_state.visible
                or layout_objects[source_id].opacity != 1):
            raise V2FrameError(f"mask source {source_id} must remain fully visible and static")
    for resolved in timeline.actions:
        if mask_sources.intersection(_action_object_references(resolved.action)):
            raise V2FrameError(
                f"action {resolved.action.action_id} cannot target a mask-only source"
            )
    # Isolation affects every visible object on its board, not only target_ids.
    # Reject overlapping visual actions anywhere on that board before sampling.
    board_windows: dict[str, list] = {}
    for item in timeline.actions:
        if not isinstance(item.action, SoundAction):
            board_windows.setdefault(item.action.board_id, []).append(item)
    for board_id, windows in board_windows.items():
        latest_end = 0
        latest_isolate_end = 0
        for item in windows:
            isolate = isinstance(item.action, TargetAction) and item.action.verb == "isolate"
            if (isolate and latest_end > item.start_ms) or (
                not isolate and latest_isolate_end > item.start_ms
            ):
                raise V2FrameError(f"isolate on {board_id} overlaps another visual action")
            latest_end = max(latest_end, item.end_ms)
            if isolate:
                latest_isolate_end = max(latest_isolate_end, item.end_ms)
    managed_connectors = {item.action.connector_id for item in timeline.actions
                          if isinstance(item.action, ConnectionAction)}
    connector_endpoints = {
        endpoint_id for obj in layout.objects if isinstance(obj, ConnectorObject)
        for endpoint_id in (obj.source_object_id, obj.destination_object_id)
        if endpoint_id is not None
    }
    for connector_id in managed_connectors:
        relationship = initial[connector_id]
        if (relationship.state not in {"connected", "disconnected"}
                or relationship.visible != (relationship.state == "connected")
                or layout_objects[connector_id].visible != relationship.visible):
            raise V2FrameError(
                f"managed connector {connector_id} has inconsistent initial relationship visibility"
            )
    last_target_end: dict[str, int] = {}
    last_target_verb: dict[str, str] = {}
    highlighted_targets: set[str] = set()
    crossed_out_targets: set[str] = set()
    completed_visible = {object_id: state.visible for object_id, state in initial.items()}
    completed_opacity = {object_id: obj.opacity for object_id, obj in layout_objects.items()}
    completed_reveal = {object_id: 1.0 if state.visible else 0.0
                        for object_id, state in initial.items()}
    completed_transform = {
        object_id: FrameTransform.from_contract(obj.transform)
        for object_id, obj in layout_objects.items()
    }
    for item in timeline.actions:
        if isinstance(item.action, TargetAction) and item.action.annotation_policy is not None:
            action = item.action
            target_id = action.target_ids[0]
            note_ids = _annotation_object_ids(action)
            participants = {target_id, *note_ids}
            ancestors = {ancestor for object_id in participants
                         for ancestor in _ancestor_ids(layout_objects[object_id], layout_objects)}
            dependencies = participants | ancestors
            hold_end = item.end_ms + action.annotation_policy.readable_hold_ms
            activation = next((a for a in layout.activations if a.board_id == action.board_id
                               and a.start_ms <= item.start_ms and hold_end <= a.end_ms), None)
            if activation is None:
                raise V2FrameError(f"annotation {action.action_id} reading hold outlasts its board")
            if (not completed_visible[target_id] or completed_reveal[target_id] != 1
                    or completed_opacity[target_id] <= 0
                    or any(not completed_visible[parent] or completed_opacity[parent] <= 0
                           or completed_reveal[parent] != 1 for parent in ancestors)):
                raise V2FrameError(f"annotation {action.action_id} needs fully visible target and parents")
            if any(object_id in last_target_end or completed_visible[object_id]
                   or completed_reveal[object_id] != 0 or completed_opacity[object_id] <= 0
                   for object_id in note_ids):
                raise V2FrameError(f"annotation {action.action_id} needs untouched hidden notes")
            if any(completed_opacity[object_id] != 1 for object_id in dependencies):
                raise V2FrameError(f"annotation {action.action_id} needs opaque participants for reading")
            for other in timeline.actions:
                if other is item or isinstance(other.action, SoundAction):
                    continue
                board_effect = (other.action.board_id == action.board_id and (
                    isinstance(other.action, CameraAction)
                    or isinstance(other.action, TargetAction) and other.action.verb == "isolate"))
                if (other.start_ms < hold_end and item.start_ms < other.end_ms
                        and (board_effect or dependencies.intersection(_action_object_references(other.action)))):
                    raise V2FrameError(f"annotation {action.action_id} needs uninterrupted construction and hold")
            leader_id = action.annotation_policy.leader_connector_id
            if leader_id is not None:
                leader = layout_objects[leader_id]
                endpoint_ids = {leader.source_object_id, leader.destination_object_id}
                live_dependencies = {leader_id, *endpoint_ids, *(ancestor for endpoint in endpoint_ids
                    for ancestor in _ancestor_ids(layout_objects[endpoint], layout_objects))}
                removal = next((other for other in timeline.actions
                                if isinstance(other.action, TargetAction) and other.action.verb == "exit"
                                and other.action.target_ids == [leader_id]
                                and other.start_ms >= hold_end), None)
                live_end = removal.end_ms if removal is not None else timeline.duration_ms
                for other in timeline.actions:
                    if (other is item or other is removal or other.start_ms >= live_end
                            or other.end_ms <= hold_end
                            or isinstance(other.action, (CameraAction, SoundAction))
                            or isinstance(other.action, EvidenceAction) and other.action.verb == "return_board"):
                        continue
                    if isinstance(other.action, TargetAction) and other.action.annotation_policy is not None:
                        mutations = _annotation_object_ids(other.action)
                    elif isinstance(other.action, ConnectionAction):
                        mutations = [other.action.connector_id]
                    else:
                        mutations = _action_object_references(other.action)
                    if live_dependencies.intersection(mutations):
                        raise V2FrameError(
                            f"retained annotation pointer {leader_id} requires completed explicit removal before endpoint edits"
                        )
            try:
                _annotation_phase_windows(item)
                camera_plan = camera_segments(layout, timeline, hierarchy)
                viewports = [evaluate_camera(layout, camera_plan, moment, activation.activation_id, _ease)
                             for moment in (item.start_ms, item.end_ms, hold_end - 1)]
                validate_annotation_geometry(action, layout, layout_objects, completed_transform, viewports)
            except ValueError as exc:
                raise V2FrameError(str(exc)) from exc
            for object_id in participants:
                last_target_end[object_id] = hold_end
            for object_id in note_ids:
                last_target_verb[object_id] = "annotate"
                completed_visible[object_id] = True
                completed_reveal[object_id] = 1.0
            continue
        if isinstance(item.action, EvidenceAction) and item.action.verb == "insert_evidence":
            action = item.action
            target = action.target_object_id
            obj = layout_objects[target]
            ancestors = _ancestor_ids(obj, layout_objects)
            treatment = treatments_by_action[action.action_id]
            if (target in last_target_end or completed_visible[target]
                    or completed_reveal[target] != 0
                    or any(not completed_visible[parent_id]
                           or completed_opacity[parent_id] <= 0
                           or completed_reveal[parent_id] < 1
                           for parent_id in ancestors)):
                raise V2FrameError(
                    f"insert_evidence {action.action_id} needs a visible parent and untouched hidden source"
                )
            chain = (target, *ancestors)
            if any(completed_opacity[object_id] != 1 for object_id in chain):
                raise V2FrameError(
                    f"evidence {target} must remain fully opaque for its readable hold"
                )
            if ("rotate" not in treatment.allowed_transformations
                    and any(completed_transform[object_id].rotation_degrees != 0
                            for object_id in chain)):
                raise V2FrameError(f"evidence {target} has an undeclared rotation")
            try:
                rect = world_bounds(obj, layout_objects, completed_transform)
                matrix = world_matrix(obj, layout_objects, completed_transform)
                camera_plan = camera_segments(layout, timeline, hierarchy)
            except (UnsupportedWorldGeometry, UnsupportedCamera) as exc:
                raise V2FrameError(str(exc)) from exc
            for parent_id in ancestors:
                parent = layout_objects[parent_id]
                if isinstance(parent, MaskContainer):
                    source = layout_objects[parent.mask_source_object_id]
                    if (source.object_type != "rectangle"
                            or any(completed_transform[object_id].rotation_degrees != 0
                                   for object_id in (*chain, source.object_id))):
                        raise V2FrameError(
                            f"evidence {target} needs an axis-aligned rectangular mask aperture"
                        )
                    try:
                        aperture = world_bounds(source, layout_objects, completed_transform)
                    except UnsupportedWorldGeometry as exc:
                        raise V2FrameError(str(exc)) from exc
                    if (rect[0] < aperture[0] or rect[1] < aperture[1]
                            or rect[2] > aperture[2] or rect[3] > aperture[3]):
                        raise V2FrameError(
                            f"evidence {target} is clipped by its declared mask"
                        )
                elif isinstance(parent, ContainerObject) and parent.object_type == "clip":
                    if any(completed_transform[object_id].rotation_degrees != 0
                           for object_id in chain):
                        raise V2FrameError(
                            f"evidence {target} needs an axis-aligned clip aperture"
                        )
                    try:
                        aperture = world_bounds(parent, layout_objects, completed_transform)
                    except UnsupportedWorldGeometry as exc:
                        raise V2FrameError(str(exc)) from exc
                    if (rect[0] < aperture[0] or rect[1] < aperture[1]
                            or rect[2] > aperture[2] or rect[3] > aperture[3]):
                        raise V2FrameError(f"evidence {target} is clipped by its parent")
            activation = next(
                activation for activation in layout.activations
                if activation.board_id == action.board_id
                and activation.start_ms <= item.start_ms
                and item.end_ms + treatment.intent.readable_hold_intent_ms <= activation.end_ms
            )
            for moment in (item.start_ms, item.end_ms,
                           item.end_ms + treatment.intent.readable_hold_intent_ms - 1):
                viewport = evaluate_camera(layout, camera_plan, moment,
                                           activation.activation_id, _ease)
                crop = treatment.intent.crop
                focus = treatment.intent.focus_region
                bounds = obj.geometry.bounds
                source_scale = min(bounds.width / crop.width,
                                   bounds.height * 0.5 / crop.height)
                origin = matrix.point(0, 0)
                focus_x = matrix.point(focus.width * source_scale, 0)
                focus_y = matrix.point(0, focus.height * source_scale)
                displayed_focus_x = ((focus_x[0] - origin[0]) ** 2
                                     + (focus_x[1] - origin[1]) ** 2) ** 0.5
                displayed_focus_y = ((focus_y[0] - origin[0]) ** 2
                                     + (focus_y[1] - origin[1]) ** 2) ** 0.5
                if (rect[0] < viewport.x or rect[1] < viewport.y
                        or rect[2] > viewport.x + viewport.width
                        or rect[3] > viewport.y + viewport.height
                        or (rect[2] - rect[0]) * layout.canvas.width / viewport.width < 180
                        or (rect[3] - rect[1]) * layout.canvas.height / viewport.height < 160
                        or displayed_focus_x * layout.canvas.width / viewport.width < 8
                        or displayed_focus_y * layout.canvas.height / viewport.height < 8):
                    raise V2FrameError(
                        f"evidence {target} is not fully readable in the camera frame during its hold"
                    )
            last_target_end[target] = item.end_ms
            last_target_verb[target] = "insert_evidence"
            completed_visible[target] = True
            completed_reveal[target] = 1.0
            continue
        if isinstance(item.action, ReplaceAction):
            action = item.action
            verb = action.verb
            if verb == "morph":
                try:
                    _require_morph_contract(action)
                    validate_morph_geometry(layout_objects[action.from_object_id],
                                            layout_objects[action.to_object_id], action.morph_policy)
                except ValueError as exc:
                    raise V2FrameError(str(exc)) from exc
            source_id, destination_id = action.from_object_id, action.to_object_id
            source, destination = layout_objects[source_id], layout_objects[destination_id]
            if (source_id == destination_id or source_id in mask_sources
                    or destination_id in mask_sources
                    or source_id in connector_endpoints or destination_id in connector_endpoints):
                raise V2FrameError(f"{verb} {action.action_id} needs distinct paintable objects")
            if not all(
                isinstance(obj, MarkObject) and obj.object_type in SUPPORTED_HIGHLIGHT_MARKS
                or isinstance(obj, TextObject) and obj.object_type in SUPPORTED_HIGHLIGHT_TEXT
                or isinstance(obj, VisualObject) and obj.object_type in _REPLACE_VISUAL_TYPES
                for obj in (source, destination)
            ):
                raise V2FrameError(f"{verb} {action.action_id} needs supported paintable leaves")
            if (source.board_id != action.board_id or destination.board_id != action.board_id
                    or source.parent_id != destination.parent_id
                    or source.z_index != destination.z_index
                    or verb == "replace" and (
                        source.geometry.bounds != destination.geometry.bounds
                        or completed_transform[source_id] != completed_transform[destination_id])):
                raise V2FrameError(f"{verb} {action.action_id} needs co-located objects"
                                   if verb == "replace" else
                                   f"morph {action.action_id} changes board, parent, or layer ownership")
            ancestor_ids = set(_ancestor_ids(source, layout_objects))
            if any(other is not item
                   and isinstance(other.action, (TargetAction, TransformAction))
                   and ancestor_ids.intersection(other.action.target_ids)
                   and other.start_ms < item.end_ms
                   and item.start_ms < other.end_ms
                   for other in timeline.actions):
                raise V2FrameError(f"{verb} {action.action_id} overlaps an ancestor edit")
            if not any(activation.board_id == action.board_id
                       and activation.start_ms <= item.start_ms
                       and item.end_ms <= activation.end_ms
                       for activation in layout.activations):
                raise V2FrameError(f"{verb} {action.action_id} needs one active board")
            if (not completed_visible[source_id] or completed_reveal[source_id] < 1
                    or completed_opacity[source_id] <= 0 or source_id in highlighted_targets
                    or source_id in crossed_out_targets
                    or any(not completed_visible[ancestor_id]
                           or completed_opacity[ancestor_id] <= 0
                           or completed_reveal[ancestor_id] < 1
                           for ancestor_id in ancestor_ids)):
                raise V2FrameError(f"{verb} {action.action_id} needs fully visible source")
            if (initial[destination_id].state != "hidden"
                    or initial[destination_id].visible
                    or completed_visible[destination_id]
                    or completed_reveal[destination_id] != 0
                    or destination.opacity <= 0
                    or destination_id in last_target_end):
                raise V2FrameError(f"{verb} {action.action_id} needs untouched hidden destination")
            if (item.start_ms < last_target_end.get(source_id, 0)
                    or item.start_ms < last_target_end.get(destination_id, 0)):
                raise V2FrameError(f"{verb} {action.action_id} overlaps a participant action")
            last_target_end[source_id] = item.end_ms
            last_target_end[destination_id] = item.end_ms
            last_target_verb[source_id] = verb
            last_target_verb[destination_id] = verb
            completed_visible[source_id] = False
            completed_reveal[source_id] = 0.0
            completed_opacity[source_id] = 0.0
            completed_visible[destination_id] = True
            completed_reveal[destination_id] = 1.0
            continue
        if isinstance(item.action, GroupAction) and item.action.container_id is not None:
            container = layout_objects.get(item.action.container_id)
            if (not isinstance(container, ContainerObject)
                    or container.object_type != "group"
                    or container.board_id != item.action.board_id):
                raise V2FrameError(
                    f"action {item.action.action_id} needs a same-board group container"
                )
        if isinstance(item.action, ConnectionAction):
            action = item.action
            connector = layout_objects.get(action.connector_id)
            if not isinstance(connector, ConnectorObject):
                raise V2FrameError(f"connection {action.action_id} needs a rendered arrow connector")
            try:
                validate_static_arrow(connector, layout_objects)
            except UnsupportedConnector as exc:
                raise V2FrameError(str(exc)) from exc
            if connector.opacity <= 0:
                raise V2FrameError(f"connection {action.action_id} needs a visible semantic connector")
            if (action.board_id != connector.board_id
                    or action.source_object_id != connector.source_object_id
                    or action.source_anchor_id != connector.source_anchor_id
                    or action.destination_object_id != connector.destination_object_id
                    or action.destination_anchor_id != connector.destination_anchor_id):
                raise V2FrameError(f"connection {action.action_id} disagrees with the authored connector")
            if (action.expected_state, action.post_state) != (
                ("disconnected", "connected") if action.verb == "connect"
                else ("connected", "disconnected")
            ):
                raise V2FrameError(f"connection {action.action_id} needs canonical relationship states")
            if item.start_ms < last_target_end.get(action.connector_id, 0):
                raise V2FrameError(f"overlapping actions on {action.connector_id} need composition rules")
            last_target_end[action.connector_id] = item.end_ms
            completed_visible[action.connector_id] = action.verb == "connect"
            completed_reveal[action.connector_id] = 1.0 if action.verb == "connect" else 0.0
        if isinstance(item.action, (TargetAction, TransformAction)):
            if set(item.action.target_ids) & managed_connectors:
                raise V2FrameError(
                    f"action {item.action.action_id} mutates a connection-managed connector"
                )
            if set(item.action.target_ids) - set(layout_objects):
                raise V2FrameError(f"action {item.action.action_id} targets an unknown layout object")
            if any(layout_objects[target].board_id != item.action.board_id
                   for target in item.action.target_ids):
                raise V2FrameError(f"action {item.action.action_id} crosses board ownership")
            if (isinstance(item.action, TargetAction) and item.action.verb == "highlight"
                    and not any(activation.board_id == item.action.board_id
                                and activation.start_ms <= item.start_ms
                                and item.end_ms <= activation.end_ms
                                for activation in layout.activations)):
                raise V2FrameError(f"highlight {item.action.action_id} needs an active board")
            if isinstance(item.action, TargetAction) and item.action.verb == "isolate":
                action = item.action
                if any(isinstance(obj, ContainerObject) and obj.board_id == action.board_id
                       for obj in layout.objects):
                    raise V2FrameError(
                        f"isolate {action.action_id} needs hierarchy-aware focus composition"
                    )
                if (action.expected_state, action.post_state) != ("visible", "visible"):
                    raise V2FrameError(
                        f"isolate {action.action_id} needs canonical visible-to-visible states"
                    )
                if action.easing == "step":
                    raise V2FrameError(f"isolate {action.action_id} cannot use step easing")
                if len(set(action.target_ids)) != len(action.target_ids):
                    raise V2FrameError(f"isolate {action.action_id} has duplicate focus targets")
                if not any(activation.board_id == action.board_id
                           and activation.start_ms <= item.start_ms
                           and item.end_ms <= activation.end_ms
                           for activation in layout.activations):
                    raise V2FrameError(f"isolate {action.action_id} needs an active board")
                focus_ids = set(action.target_ids)
                if not any(
                    obj.board_id == action.board_id and object_id not in focus_ids
                    and completed_visible[object_id] and completed_opacity[object_id] > 0
                    and completed_reveal[object_id] == 1.0
                    for object_id, obj in layout_objects.items()
                ):
                    raise V2FrameError(f"isolate {action.action_id} needs visible secondary context")
            for target in item.action.target_ids:
                if (isinstance(layout_objects[target], ContainerObject)
                        and isinstance(item.action, TargetAction)):
                    raise V2FrameError(
                        f"action {item.action.action_id} needs defined descendant semantics for a container"
                    )
                if target in highlighted_targets:
                    raise V2FrameError(f"highlighted target {target} cannot receive another action")
                if target in crossed_out_targets:
                    raise V2FrameError(f"crossed-out target {target} cannot receive another action")
                if isinstance(item.action, TargetAction) and item.action.verb == "isolate":
                    obj = layout_objects[target]
                    if not (isinstance(obj, MarkObject) and obj.object_type in SUPPORTED_HIGHLIGHT_MARKS
                            or isinstance(obj, TextObject) and obj.object_type in SUPPORTED_HIGHLIGHT_TEXT
                            or isinstance(obj, VisualObject) and obj.object_type in {
                                "icon", "pictogram", "character", "device", "document", "chart", "terminal",
                            }):
                        raise V2FrameError(
                            f"isolate {item.action.action_id} needs a supported focus object"
                        )
                    if (not completed_visible[target] or completed_opacity[target] <= 0
                            or completed_reveal[target] < 1):
                        raise V2FrameError(
                            f"isolate {item.action.action_id} needs visible focus content"
                        )
                if isinstance(item.action, TargetAction) and item.action.verb == "highlight":
                    obj = layout_objects[target]
                    if not (isinstance(obj, MarkObject) and obj.object_type in SUPPORTED_HIGHLIGHT_MARKS
                            or isinstance(obj, TextObject) and obj.object_type in SUPPORTED_HIGHLIGHT_TEXT):
                        raise V2FrameError(
                            f"highlight {item.action.action_id} needs a supported mark or text target"
                        )
                    if (not initial[target].visible or initial[target].state != "visible"
                            or obj.opacity <= 0 or target in last_target_end):
                        raise V2FrameError(
                            f"highlight {item.action.action_id} needs an untouched visible target"
                        )
                    if (item.action.expected_state, item.action.post_state) != ("visible", "highlighted"):
                        raise V2FrameError(
                            f"highlight {item.action.action_id} needs canonical visible-to-highlighted states"
                        )
                    try:
                        emphasis_path(obj.geometry.bounds, "highlight")
                    except UnsupportedEmphasis as exc:
                        raise V2FrameError(str(exc)) from exc
                    highlighted_targets.add(target)
                if isinstance(item.action, TargetAction) and item.action.verb == "cross_out":
                    obj = layout_objects[target]
                    if not (isinstance(obj, MarkObject) and obj.object_type in SUPPORTED_HIGHLIGHT_MARKS
                            or isinstance(obj, TextObject) and obj.object_type in SUPPORTED_HIGHLIGHT_TEXT):
                        raise V2FrameError(
                            f"cross_out {item.action.action_id} needs a supported mark or text target"
                        )
                    if (not initial[target].visible or initial[target].state != "visible"
                            or obj.opacity <= 0 or target in last_target_end):
                        raise V2FrameError(
                            f"cross_out {item.action.action_id} needs an untouched visible target"
                        )
                    if (item.action.expected_state, item.action.post_state) != ("visible", "crossed_out"):
                        raise V2FrameError(
                            f"cross_out {item.action.action_id} needs canonical visible-to-crossed_out states"
                        )
                    if not any(activation.board_id == item.action.board_id
                               and activation.start_ms <= item.start_ms
                               and item.end_ms <= activation.end_ms
                               for activation in layout.activations):
                        raise V2FrameError(f"cross_out {item.action.action_id} needs an active board")
                    try:
                        cross_out_paths(obj.geometry.bounds)
                    except UnsupportedEmphasis as exc:
                        raise V2FrameError(str(exc)) from exc
                    crossed_out_targets.add(target)
                if isinstance(item.action, TargetAction) and item.action.verb == "dim":
                    obj = layout_objects[target]
                    if not (isinstance(obj, MarkObject) and obj.object_type in SUPPORTED_HIGHLIGHT_MARKS
                            or isinstance(obj, TextObject) and obj.object_type in SUPPORTED_HIGHLIGHT_TEXT):
                        raise V2FrameError(
                            f"dim {item.action.action_id} needs a supported mark or text target"
                        )
                    if (not initial[target].visible or initial[target].state != "visible"
                            or obj.opacity <= 0 or last_target_verb.get(target) not in (None, "dim")):
                        raise V2FrameError(
                            f"dim {item.action.action_id} needs visible context without prior edits"
                        )
                    if (item.action.expected_state, item.action.post_state) != ("visible", "visible"):
                        raise V2FrameError(
                            f"dim {item.action.action_id} needs canonical visible-to-visible states"
                        )
                    if item.action.easing == "step":
                        raise V2FrameError(f"dim {item.action.action_id} cannot use step easing")
                    if len(set(item.action.target_ids)) != len(item.action.target_ids):
                        raise V2FrameError(f"dim {item.action.action_id} has duplicate targets")
                    if not any(activation.board_id == item.action.board_id
                               and activation.start_ms <= item.start_ms
                               and item.end_ms <= activation.end_ms
                               for activation in layout.activations):
                        raise V2FrameError(f"dim {item.action.action_id} needs an active board")
                if isinstance(item.action, TargetAction) and item.action.verb == "progressive_reveal":
                    obj = layout_objects[target]
                    if not isinstance(obj, TextObject):
                        raise V2FrameError(
                            f"action {item.action.action_id} requires an authored ordered-child list"
                        )
                    try:
                        validate_ordered_list(obj)
                    except UnsupportedOrderedList as exc:
                        raise V2FrameError(str(exc)) from exc
                    if (initial[target].visible or initial[target].state != "hidden"
                            or target in last_target_end):
                        raise V2FrameError(
                            f"action {item.action.action_id} requires a previously untouched hidden list"
                        )
                    if (item.action.expected_state, item.action.post_state) != ("hidden", "visible"):
                        raise V2FrameError(
                            f"action {item.action.action_id} requires canonical hidden-to-visible list states"
                        )
                if item.start_ms < last_target_end.get(target, 0):
                    raise V2FrameError(f"overlapping actions on {target} need an explicit composition rule")
                last_target_end[target] = item.end_ms
                last_target_verb[target] = item.action.verb
                if isinstance(item.action, TargetAction):
                    if item.action.verb == "exit":
                        completed_visible[target] = False
                        completed_opacity[target] = 0.0
                        completed_reveal[target] = 0.0
                    elif item.action.verb in {
                        "reveal", "write", "draw", "progressive_reveal", "enter"
                    }:
                        completed_visible[target] = True
                        completed_reveal[target] = 1.0
                if isinstance(item.action, TransformAction):
                    action = item.action
                    if action.verb == "fade":
                        if action.destination is not None:
                            raise V2FrameError("fade cannot carry an ignored transform destination")
                        completed_opacity[target] = action.opacity
                        completed_visible[target] = completed_visible[target] or action.opacity > 0
                        continue
                    before = completed_transform[target]
                    after = action.destination
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
                    else:  # rotate
                        unused_changed = (
                            after.position.x != before.position.x or after.position.y != before.position.y
                            or after.scale_x != before.scale_x or after.scale_y != before.scale_y
                        )
                    if unused_changed:
                        raise V2FrameError(
                            f"{action.verb} action {action.action_id} changes an unrelated transform channel"
                        )
                    completed_transform[target] = FrameTransform.from_contract(after)
            if (isinstance(item.action, TargetAction) and item.action.annotation is not None
                    and item.action.verb != "annotate"):
                raise V2FrameError(
                    f"action {item.action.action_id} carries an annotation it cannot display"
                )


def evaluate_frame(
    layout_document: dict,
    timeline_document: dict,
    at_ms: int,
) -> FrameSnapshot:
    """Evaluate from immutable initial state, never from a previous frame."""
    if not isinstance(layout_document, dict) or not isinstance(timeline_document, dict):
        raise V2FrameError("frame evaluation requires the exact stored JSON documents")
    try:
        layout_bytes = json.dumps(
            layout_document, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise V2FrameError("layout is not finite, canonical JSON") from exc
    layout_sha256 = hashlib.sha256(layout_bytes).hexdigest()
    layout = ExecutableLayoutV2.model_validate(layout_document)
    timeline = ResolvedVisualTimelineV2.model_validate(timeline_document)
    try:
        hierarchy = HierarchySnapshot.from_objects({obj.object_id: obj for obj in layout.objects})
    except UnsupportedHierarchy as exc:
        raise V2FrameError(str(exc)) from exc
    _validate_pair(layout, timeline, layout_sha256, hierarchy)
    try:
        camera_plan = camera_segments(layout, timeline, hierarchy)
    except UnsupportedCamera as exc:
        raise V2FrameError(str(exc)) from exc
    if type(at_ms) is not int or not 0 <= at_ms < timeline.duration_ms:
        raise V2FrameError("frame time must be an integer within the resolved timeline")

    initial = {item.object_id: item for item in timeline.initial_object_states}
    for obj in layout.objects:
        if obj.visible != initial[obj.object_id].visible or obj.initial_state != initial[obj.object_id].state:
            raise V2FrameError(f"initial layout and timeline state disagree for {obj.object_id}")
    current = {
        obj.object_id: FrameObject(
            object_id=obj.object_id,
            board_id=obj.board_id,
            state=initial[obj.object_id].state,
            visible=obj.visible,
            opacity=obj.opacity,
            reveal_fraction=1.0 if obj.visible else 0.0,
            transform=FrameTransform.from_contract(obj.transform),
        )
        for obj in layout.objects
    }
    for resolved in timeline.actions:
        action = resolved.action
        supported = (
            isinstance(action, (TransformAction, ConnectionAction, CameraAction))
            or isinstance(action, EvidenceAction)
            and action.verb in {"insert_evidence", "return_board"}
            or isinstance(action, ReplaceAction)
            or isinstance(action, TargetAction) and action.annotation_policy is not None
            or isinstance(action, TargetAction) and action.verb in {
                "reveal", "write", "draw", "enter", "exit", "progressive_reveal", "highlight",
                "cross_out",
                "dim",
                "isolate",
            }
        )
        if not supported:
            raise UnsupportedVisualAction(
                f"v2 action {action.action_id} uses {action.verb}, which has no frame implementation"
            )
        if isinstance(action, CameraAction):
            continue
        if isinstance(action, EvidenceAction) and action.verb == "return_board":
            continue
        if at_ms < resolved.start_ms:
            continue
        progress = _ease(
            (at_ms - resolved.start_ms) / (resolved.end_ms - resolved.start_ms),
            action.easing,
        )
        completed = at_ms >= resolved.end_ms
        if isinstance(action, TargetAction) and action.annotation_policy is not None:
            for phase, start, end in _annotation_phase_windows(resolved):
                if at_ms < start:
                    continue
                fraction = _ease((at_ms - start) / (end - start), action.easing)
                before = current[phase.object_id]
                current[phase.object_id] = replace(
                    before, state="visible" if at_ms >= end else before.state,
                    visible=fraction > 0, reveal_fraction=fraction,
                )
            continue
        if isinstance(action, EvidenceAction):
            before = current[action.target_object_id]
            current[action.target_object_id] = replace(
                before,
                state=action.post_state if completed else before.state,
                visible=True,
                opacity=before.opacity * (1.0 if completed else progress),
                reveal_fraction=1.0,
            )
            continue
        if isinstance(action, ReplaceAction):
            source = current[action.from_object_id]
            destination = current[action.to_object_id]
            if action.verb == "morph":
                source_obj = next(obj for obj in layout.objects if obj.object_id == source.object_id)
                destination_obj = next(obj for obj in layout.objects if obj.object_id == destination.object_id)
                try:
                    geometry = (None if completed or progress == 0 else interpolate_geometry(
                        source_obj, destination_obj, action.morph_policy, progress,
                    ))
                except UnsupportedMorph as exc:
                    raise V2FrameError(str(exc)) from exc
                transform = FrameTransform(
                    position=FramePoint(_mix(source.transform.position.x, destination.transform.position.x, progress),
                                        _mix(source.transform.position.y, destination.transform.position.y, progress)),
                    scale_x=_mix(source.transform.scale_x, destination.transform.scale_x, progress),
                    scale_y=_mix(source.transform.scale_y, destination.transform.scale_y, progress),
                    rotation_degrees=_mix(source.transform.rotation_degrees,
                                          destination.transform.rotation_degrees, progress),
                    origin=FramePoint(_mix(source.transform.origin.x, destination.transform.origin.x, progress),
                                      _mix(source.transform.origin.y, destination.transform.origin.y, progress)),
                )
                current[source.object_id] = replace(
                    source, state="removed" if completed else source.state,
                    visible=not completed, opacity=0 if completed else _mix(source.opacity, destination.opacity, progress),
                    reveal_fraction=0 if completed else 1, transform=transform, morph_geometry=geometry,
                )
                current[destination.object_id] = replace(
                    destination, state=action.post_state if completed else destination.state,
                    visible=completed, reveal_fraction=1 if completed else 0,
                )
                continue
            current[action.from_object_id] = replace(
                source,
                state="removed" if completed else source.state,
                visible=not completed,
                opacity=source.opacity * (1.0 - progress),
                reveal_fraction=0.0 if completed else source.reveal_fraction,
            )
            current[action.to_object_id] = replace(
                destination,
                state=action.post_state if completed else destination.state,
                visible=progress > 0 or completed,
                opacity=destination.opacity * progress,
                reveal_fraction=1.0 if progress > 0 or completed else 0.0,
            )
            continue
        if isinstance(action, TargetAction) and action.verb == "isolate":
            for object_id in action.target_ids:
                focus = current[object_id]
                if not focus.visible or focus.opacity <= 0 or focus.reveal_fraction < 1:
                    raise V2FrameError(f"isolate {action.action_id} has no visible focus")
            if not completed:
                focus_ids = set(action.target_ids)
                ratio = _dim_ratio(progress)
                eligible_context = 0
                for object_id, context in current.items():
                    if (context.board_id == action.board_id and object_id not in focus_ids
                            and context.visible and context.opacity > 0
                            and context.reveal_fraction >= 1):
                        eligible_context += 1
                        current[object_id] = replace(context, opacity=context.opacity * ratio)
                if not eligible_context:
                    raise V2FrameError(f"isolate {action.action_id} has no visible secondary context")
            continue
        targets = (action.connector_id,) if isinstance(action, ConnectionAction) else action.target_ids
        for object_id in targets:
            before = current[object_id]
            state = action.post_state if completed else before.state
            if isinstance(action, ConnectionAction):
                if before.opacity <= 0:
                    raise V2FrameError(f"connection {action.action_id} has an invisible connector")
                fraction = progress if action.verb == "connect" else 1.0 - progress
                after = replace(before, state=state, visible=not completed or action.verb == "connect",
                                reveal_fraction=fraction)
            elif isinstance(action, TargetAction):
                if action.verb == "exit":
                    after = replace(before, state=state, visible=not completed,
                                    opacity=_mix(before.opacity, 0.0, progress))
                elif action.verb == "enter":
                    after = replace(before, state=state, visible=True,
                                    opacity=_mix(0.0, 1.0, progress) * before.opacity,
                                    reveal_fraction=1.0)
                elif action.verb == "highlight":
                    if not before.visible or before.opacity <= 0 or before.reveal_fraction < 1:
                        raise V2FrameError(f"highlight {action.action_id} has no visible target")
                    after = replace(before, state=state, emphasis_fraction=progress)
                elif action.verb == "cross_out":
                    if not before.visible or before.opacity <= 0 or before.reveal_fraction < 1:
                        raise V2FrameError(f"cross_out {action.action_id} has no visible target")
                    after = replace(before, state=state, cross_out_fraction=progress)
                elif action.verb == "dim":
                    if not before.visible or before.opacity <= 0 or before.reveal_fraction < 1:
                        raise V2FrameError(f"dim {action.action_id} has no visible context")
                    after = replace(before, state=state,
                                    opacity=before.opacity * (1.0 if completed else _dim_ratio(progress)))
                else:
                    after = replace(before, state=state, visible=True,
                                    reveal_fraction=progress)
            elif action.verb == "fade":
                after = replace(before, state=state,
                                visible=before.visible or (action.opacity or 0.0) > 0,
                                opacity=_mix(before.opacity, action.opacity, progress))
            else:
                after = replace(
                    before, state=state,
                    transform=_interpolate_transform(before.transform, action.destination,
                                                     progress, action.verb),
                )
            current[object_id] = after

    activation = next((item for item in layout.activations
                       if item.start_ms <= at_ms < item.end_ms), None)
    active_board = activation.board_id if activation else None
    camera = evaluate_camera(layout, camera_plan, at_ms,
                             activation.activation_id if activation else None, _ease)
    object_map = hierarchy.object_map({obj.object_id: obj for obj in layout.objects})
    ordered = tuple(
        replace(current[obj.object_id],
                visible=current[obj.object_id].visible and obj.board_id == active_board
                and all(current[parent_id].visible and current[parent_id].opacity > 0
                        for parent_id in _ancestor_ids(obj, object_map)))
        for obj in sorted(layout.objects, key=lambda item: (item.z_index, item.object_id))
    )
    transforms = {state.object_id: state.transform for state in ordered}
    object_map = {obj.object_id: geometry_object(obj, current[obj.object_id].morph_geometry)
                  for obj in object_map.values()}
    try:
        for obj in object_map.values():
            world_bounds(obj, object_map, transforms)
    except UnsupportedWorldGeometry as exc:
        raise V2FrameError(str(exc)) from exc
    return FrameSnapshot(at_ms=at_ms, active_board_id=active_board,
                         objects=ordered, camera=camera, hierarchy=hierarchy)
