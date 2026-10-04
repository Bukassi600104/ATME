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
from atme.render.v2_evidence_reading import validate_evidence_reading
from atme.render.v2_hierarchy import HierarchySnapshot, UnsupportedHierarchy
from atme.render.v2_lifecycle import (
    UnsupportedLifecycle,
    geometry_dependencies,
    lifecycle_samples,
    validate_annotation_paint_order,
    validate_group_lifetime,
    validate_replacement_paint_order,
)
from atme.render.v2_list import UnsupportedOrderedList, validate_ordered_list
from atme.render.v2_mask import UnsupportedMask, mask_source_region
from atme.render.v2_morph import (
    MorphGeometry,
    geometry_object,
    validate_morph_geometry,
)
from atme.render.v2_return import UnsupportedReturn, validate_return_sample
from atme.render.v2_timeline_replay import (
    ChronologicalReplay,
    ReplayError,
    replay_chronology,
    supports_operator,
)
from atme.render.v2_world import UnsupportedWorldGeometry, world_bounds
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
    _require_annotation_contract,
    _require_morph_contract,
    _require_return_board_policy,
    _require_return_contract,
    validate_resolved_hierarchy,
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


@dataclass(frozen=True)
class _PairContext:
    """Caller-local validated inventory; sampled history belongs only to replay."""
    layout: ExecutableLayoutV2
    timeline: ResolvedVisualTimelineV2
    hierarchy: HierarchySnapshot
    objects: dict
    initial: dict
    frames: tuple[FrameObject, ...]
    mask_sources: frozenset[str]
    managed_connectors: frozenset[str]
    connector_endpoints: frozenset[str]
    treatments_by_action: dict


def _validate_static_action(item, layout, timeline, objects, mask_sources, managed_connectors,
                            connector_endpoints) -> None:
    """Operator form/binding checks must precede construction of its replay."""
    action = item.action
    if isinstance(action, GroupAction) and action.container_id is not None:
        shell = objects[action.container_id]
        if (not isinstance(shell, ContainerObject) or shell.object_type != "group"
                or shell.board_id != action.board_id
                or any(objects[key].board_id != action.board_id for key in action.target_ids)):
            raise V2FrameError(f"action {action.action_id} needs a same-board group container")
    if isinstance(action, ConnectionAction):
        connector = objects[action.connector_id]
        if not isinstance(connector, ConnectorObject):
            raise V2FrameError(f"connection {action.action_id} needs a rendered arrow connector")
        try:
            validate_static_arrow(connector, objects)
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
            ("disconnected", "connected") if action.verb == "connect" else ("connected", "disconnected")
        ):
            raise V2FrameError(f"connection {action.action_id} needs canonical relationship states")
    if isinstance(action, ReplaceAction):
        source, destination = objects[action.from_object_id], objects[action.to_object_id]
        if (source.object_id == destination.object_id
                or {source.object_id, destination.object_id}.intersection(mask_sources | connector_endpoints)):
            raise V2FrameError(f"{action.verb} {action.action_id} needs distinct paintable objects")
        if not all(
            isinstance(obj, MarkObject) and obj.object_type in SUPPORTED_HIGHLIGHT_MARKS
            or isinstance(obj, TextObject) and obj.object_type in SUPPORTED_HIGHLIGHT_TEXT
            or isinstance(obj, VisualObject) and obj.object_type in _REPLACE_VISUAL_TYPES
            for obj in (source, destination)
        ):
            raise V2FrameError(f"{action.verb} {action.action_id} needs supported paintable leaves")
        if (source.board_id != action.board_id or destination.board_id != action.board_id
                or source.z_index != destination.z_index
                or action.verb == "replace" and source.geometry.bounds != destination.geometry.bounds):
            raise V2FrameError(f"replace {action.action_id} needs co-located objects" if action.verb == "replace"
                               else f"morph {action.action_id} changes board, parent, or layer ownership")
        # Exact co-parentage/transforms are temporal, not initial-layout guesses.
        for other in timeline.actions:
            if (other is item or isinstance(other.action, (CameraAction, SoundAction))
                    or other.start_ms >= item.end_ms or item.start_ms >= other.end_ms):
                continue
            overlap = {source.object_id, destination.object_id}.intersection(_action_object_references(other.action))
            if overlap:
                if other.start_ms <= item.start_ms:
                    raise V2FrameError(f"{action.verb} {action.action_id} overlaps a participant action")
                raise V2FrameError(f"overlapping actions on {min(overlap)} need an explicit composition rule")
    if isinstance(action, TransformAction) and action.verb == "fade" and action.destination is not None:
        raise V2FrameError("fade cannot carry an ignored transform destination")
    if isinstance(action, (TargetAction, TransformAction)) and set(action.target_ids) & managed_connectors:
        raise V2FrameError(f"action {action.action_id} mutates a connection-managed connector")
    if not isinstance(action, TargetAction):
        return
    if action.annotation is not None and action.verb != "annotate":
        raise V2FrameError(f"action {action.action_id} carries an annotation it cannot display")
    if action.annotation_policy is not None:
        return
    for target in action.target_ids:
        obj = objects[target]
        if isinstance(obj, ContainerObject):
            raise V2FrameError(f"action {action.action_id} needs defined descendant semantics for a container")
        if action.verb in {"highlight", "cross_out", "dim", "isolate"}:
            supported = (isinstance(obj, MarkObject) and obj.object_type in SUPPORTED_HIGHLIGHT_MARKS
                         or isinstance(obj, TextObject) and obj.object_type in SUPPORTED_HIGHLIGHT_TEXT
                         or action.verb == "isolate" and isinstance(obj, VisualObject)
                         and obj.object_type in _REPLACE_VISUAL_TYPES)
            if not supported:
                if action.verb == "isolate":
                    raise V2FrameError(f"isolate {action.action_id} needs a supported focus object")
                raise V2FrameError(f"{action.verb} {action.action_id} needs a supported mark or text target")
            if action.verb in {"highlight", "cross_out"} and (
                not obj.visible or obj.initial_state != "visible" or obj.opacity <= 0
            ):
                raise V2FrameError(f"{action.verb} {action.action_id} needs an untouched visible target")
            if action.verb == "dim" and (
                not obj.visible or obj.initial_state != "visible" or obj.opacity <= 0
            ):
                raise V2FrameError(f"dim {action.action_id} needs visible context without prior edits")
            post = {"highlight": "highlighted", "cross_out": "crossed_out"}.get(action.verb, "visible")
            if (action.expected_state, action.post_state) != ("visible", post):
                raise V2FrameError(f"{action.verb} {action.action_id} needs canonical visible-to-{post} states")
            if action.verb in {"dim", "isolate"}:
                if action.easing == "step":
                    raise V2FrameError(f"{action.verb} {action.action_id} cannot use step easing")
                if len(set(action.target_ids)) != len(action.target_ids):
                    if action.verb == "isolate":
                        raise V2FrameError(f"isolate {action.action_id} has duplicate focus targets")
                    raise V2FrameError(f"{action.verb} {action.action_id} has duplicate targets")
            if not any(a.board_id == action.board_id and a.start_ms <= item.start_ms
                       and item.end_ms <= a.end_ms for a in layout.activations):
                raise V2FrameError(f"{action.verb} {action.action_id} needs an active board")
            try:
                if action.verb == "highlight":
                    emphasis_path(obj.geometry.bounds, "highlight")
                elif action.verb == "cross_out":
                    cross_out_paths(obj.geometry.bounds)
            except UnsupportedEmphasis as exc:
                raise V2FrameError(str(exc)) from exc
        if action.verb == "progressive_reveal":
            if not isinstance(obj, TextObject):
                raise V2FrameError(f"action {action.action_id} requires an authored ordered-child list")
            try:
                validate_ordered_list(obj)
            except UnsupportedOrderedList as exc:
                raise V2FrameError(str(exc)) from exc
            if obj.visible or obj.initial_state != "hidden":
                raise V2FrameError(f"action {action.action_id} requires a previously untouched hidden list")
            if (action.expected_state, action.post_state) != ("hidden", "visible"):
                raise V2FrameError(f"action {action.action_id} requires canonical hidden-to-visible list states")


def _validate_pair_static(layout: ExecutableLayoutV2, timeline: ResolvedVisualTimelineV2,
                   layout_sha256: str, hierarchy: HierarchySnapshot,
                   *, structural_timeline: ResolvedVisualTimelineV2 | None = None) -> _PairContext:
    if (layout.project_id != timeline.project_id or layout.layout_id != timeline.layout_id
            or layout.plan_id != timeline.plan_id or layout.plan_revision != timeline.plan_revision
            or layout.plan_sha256 != timeline.plan_sha256
            or layout_sha256 != timeline.layout_sha256
            or layout.output_profile != timeline.output_profile
            or layout.style_system_version != timeline.style_system_version
            or layout.asset_registry_version != timeline.asset_registry_version
            or layout.evidence_treatments != timeline.evidence_treatments):
        raise V2FrameError("resolved timeline and executable layout do not describe the same composition")
    try:
        # Initial ownership/receipt inventory binds the complete document even
        # when consumer execution is restricted to a return's causal prefix.
        validate_resolved_hierarchy(layout, structural_timeline if structural_timeline is not None else timeline)
    except ValueError as exc:
        raise V2FrameError(str(exc)) from exc
    resolved_actions = {item.action.action_id: item for item in timeline.actions}
    treatments_by_action = {item.action_id: item for item in layout.evidence_treatments
                            if structural_timeline is None or item.action_id in resolved_actions}
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
    for treatment in treatments_by_action.values():
        resolved = resolved_actions.get(treatment.action_id)
        if resolved is None or not any(
            activation.board_id == treatment.intent.destination_board_id
            and activation.start_ms <= resolved.start_ms
            and resolved.end_ms + treatment.intent.readable_hold_intent_ms <= activation.end_ms
            for activation in layout.activations
        ):
            raise V2FrameError("evidence readable hold outlasts its destination board")
    for treatment in treatments_by_action.values():
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
            if other is resolved or isinstance(other.action, (SoundAction, GroupAction)):
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
    for obj in layout.objects:
        state = initial[obj.object_id]
        if obj.visible != state.visible or obj.initial_state != state.state:
            raise V2FrameError(f"initial layout and timeline state disagree for {obj.object_id}")
    # Models own unique IDs, triggers and interval bounds. Close every observer
    # and operator reference before any replay sampler may dereference it.
    for item in timeline.actions:
        action = item.action
        refs = set(_action_object_references(action))
        if isinstance(action, GroupAction) and action.hierarchy_policy is not None:
            refs.update(action.hierarchy_policy.changed_object_ids)
            for basis in (action.hierarchy_policy.source_basis, action.hierarchy_policy.destination_basis):
                refs.update(row.object_id for row in basis.placements)
        if not refs <= layout_objects.keys():
            raise V2FrameError(f"action {action.action_id} targets an unknown layout object")
        if isinstance(action, (TargetAction, TransformAction, CameraAction)) and any(
            layout_objects[target].board_id != action.board_id for target in action.target_ids
        ):
            raise V2FrameError(f"action {action.action_id} crosses board ownership")
        if isinstance(action, TargetAction) and action.annotation_policy is not None:
            try:
                _require_annotation_contract(action)
                _annotation_phase_windows(item)
                leader_id = action.annotation_policy.leader_connector_id
                if leader_id is not None:
                    leader = layout_objects[leader_id]
                    if not isinstance(leader, ConnectorObject):
                        raise V2FrameError("annotation leader must be an authored connector")
                    for key, anchor_id in ((leader.source_object_id, leader.source_anchor_id),
                                           (leader.destination_object_id, leader.destination_anchor_id)):
                        if (key not in layout_objects or layout_objects[key].board_id != action.board_id
                                or not any(anchor.anchor_id == anchor_id for anchor in layout_objects[key].anchors)):
                            raise V2FrameError("annotation leader needs existing same-board named endpoints")
                    validate_static_arrow(leader, layout_objects, annotation_pointer=True)
            except ValueError as exc:
                raise V2FrameError(str(exc)) from exc
        _validate_static_action(item, layout, timeline, layout_objects, mask_sources,
                                managed_connectors, connector_endpoints)
        if isinstance(action, TargetAction) and action.annotation_policy is not None:
            participants = set(action.target_ids) | set(_annotation_object_ids(action))
            # Parentage is temporal. Only direct participants and whole-board
            # effects are history-independent preflight conflicts.
            dependencies = participants
            hold_end = item.end_ms + action.annotation_policy.readable_hold_ms
            for other in timeline.actions:
                if other is item or isinstance(other.action, SoundAction):
                    continue
                board_effect = (other.action.board_id == action.board_id and (
                    isinstance(other.action, CameraAction)
                    or isinstance(other.action, TargetAction) and other.action.verb == "isolate"))
                if (other.start_ms < hold_end and item.start_ms < other.end_ms
                        and (board_effect or dependencies.intersection(_action_object_references(other.action)))):
                    raise V2FrameError(f"annotation {action.action_id} needs uninterrupted construction and hold")
        if isinstance(action, ReplaceAction) and action.verb == "morph":
            try:
                _require_morph_contract(action)
                validate_morph_geometry(layout_objects[action.from_object_id],
                                        layout_objects[action.to_object_id], action.morph_policy)
            except ValueError as exc:
                raise V2FrameError(str(exc)) from exc
    frames = tuple(FrameObject(
        object_id=obj.object_id, board_id=obj.board_id, state=initial[obj.object_id].state,
        visible=obj.visible, opacity=obj.opacity, reveal_fraction=1.0 if obj.visible else 0.0,
        transform=FrameTransform.from_contract(obj.transform),
    ) for obj in layout.objects)
    return _PairContext(layout, timeline, hierarchy, layout_objects, initial, frames,
                        frozenset(mask_sources), frozenset(managed_connectors),
                        frozenset(connector_endpoints), treatments_by_action)


def _validate_pair_temporal(context: _PairContext, replay: ChronologicalReplay, camera_plan) -> None:
    """Read every action boundary from the same immutable chronology."""
    layout, timeline = context.layout, context.timeline
    initial = context.initial
    treatments_by_action = context.treatments_by_action
    last_target_end: dict[str, int] = {}
    last_target_verb: dict[str, str] = {}
    highlighted_targets: set[str] = set()
    crossed_out_targets: set[str] = set()
    for item in timeline.actions:
        sample = replay.before_action(item.action.action_id)
        layout_objects = sample.hierarchy.object_map(context.objects)
        sampled = {frame.object_id: frame for frame in sample.objects}
        completed_visible = {key: frame.visible for key, frame in sampled.items()}
        completed_opacity = {key: frame.opacity for key, frame in sampled.items()}
        completed_reveal = {key: frame.reveal_fraction for key, frame in sampled.items()}
        completed_transform = {key: frame.transform for key, frame in sampled.items()}
        if isinstance(item.action, EvidenceAction) and item.action.verb == "return_board":
            try:
                validate_return_sample(item, sample.hierarchy, sampled, dict(sample.state_versions))
            except UnsupportedReturn as exc:
                raise V2FrameError(str(exc)) from exc
            continue
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
                removal = next((other for other in timeline.actions
                                if isinstance(other.action, TargetAction) and other.action.verb == "exit"
                                and other.action.target_ids == [leader_id]
                                and other.start_ms >= hold_end), None)
                live_end = removal.end_ms if removal is not None else timeline.duration_ms
                try:
                    validate_group_lifetime(context.objects, timeline.actions,
                                            {leader_id, *endpoint_ids}, hold_end, live_end,
                                            description=f"retained annotation pointer {leader_id}")
                    for retained in lifecycle_samples(replay, item, live_end):
                        validate_annotation_paint_order(
                            action, retained.hierarchy.object_map(context.objects), retained.hierarchy)
                except ValueError as exc:
                    raise V2FrameError(str(exc)) from exc
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
                    observed_hierarchy = replay.before_action(other.action.action_id).hierarchy
                    live_dependencies = geometry_dependencies(observed_hierarchy, {leader_id, *endpoint_ids})
                    if live_dependencies.intersection(mutations):
                        raise V2FrameError(
                            f"retained annotation pointer {leader_id} requires completed explicit removal before endpoint edits"
                        )
            try:
                validate_group_lifetime(context.objects, timeline.actions, participants,
                                        item.start_ms, hold_end,
                                        description=f"annotation {action.action_id} needs uninterrupted construction and hold")
                for reading in lifecycle_samples(replay, item, hold_end):
                    reading_objects = reading.hierarchy.object_map(context.objects)
                    reading_frames = {frame.object_id: frame for frame in reading.objects}
                    reading_dependencies = geometry_dependencies(reading.hierarchy, participants)
                    target_chain = geometry_dependencies(reading.hierarchy, [target_id])
                    if any(not reading_frames[key].visible or reading_frames[key].opacity != 1
                           or reading_frames[key].reveal_fraction != 1 for key in target_chain):
                        raise V2FrameError(f"annotation {action.action_id} needs fully visible opaque target and parents")
                    parents = reading_dependencies.difference(participants)
                    if any(not reading_frames[key].visible or reading_frames[key].opacity != 1
                           or reading_frames[key].reveal_fraction != 1 for key in parents):
                        raise V2FrameError(f"annotation {action.action_id} needs fully visible opaque note parents")
                    if reading.at_ms >= item.end_ms and any(
                        not reading_frames[key].visible or reading_frames[key].opacity != 1
                        or reading_frames[key].reveal_fraction != 1 for key in note_ids
                    ):
                        raise V2FrameError(f"annotation {action.action_id} needs completed notes throughout its hold")
                    viewport = evaluate_camera(layout, camera_plan, reading.at_ms, activation.activation_id, _ease)
                    validate_annotation_geometry(
                        action, layout, reading_objects,
                        {key: frame.transform for key, frame in reading_frames.items()},
                        [viewport], hierarchy=reading.hierarchy)
            except ValueError as exc:
                raise V2FrameError(str(exc)) from exc
            for object_id in participants:
                last_target_end[object_id] = hold_end
            for object_id in note_ids:
                last_target_verb[object_id] = "annotate"
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
            activation = next(
                activation for activation in layout.activations
                if activation.board_id == action.board_id
                and activation.start_ms <= item.start_ms
                and item.end_ms + treatment.intent.readable_hold_intent_ms <= activation.end_ms
            )
            try:
                observed = {target, *(layout_objects[parent].mask_source_object_id
                            for parent in ancestors if isinstance(layout_objects[parent], MaskContainer))}
                hold_end = item.end_ms + treatment.intent.readable_hold_intent_ms
                validate_group_lifetime(context.objects, timeline.actions, observed, item.start_ms, hold_end,
                                        description=f"evidence {target} readable insert and hold")
                for reading in lifecycle_samples(replay, item, hold_end):
                    viewport = evaluate_camera(layout, camera_plan, reading.at_ms, activation.activation_id, _ease)
                    validate_evidence_reading(item, layout, context.objects, treatment, reading, viewport)
            except ValueError as exc:
                raise V2FrameError(str(exc)) from exc
            last_target_end[target] = item.end_ms
            last_target_verb[target] = "insert_evidence"
            continue
        if isinstance(item.action, ReplaceAction):
            action = item.action
            verb = action.verb
            source_id, destination_id = action.from_object_id, action.to_object_id
            source, destination = layout_objects[source_id], layout_objects[destination_id]
            try:
                validate_replacement_paint_order(action, sample, layout_objects)
            except UnsupportedLifecycle as exc:
                raise V2FrameError(str(exc)) from exc
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
            continue
        if isinstance(item.action, ConnectionAction):
            action = item.action
            if item.start_ms < last_target_end.get(action.connector_id, 0):
                raise V2FrameError(f"overlapping actions on {action.connector_id} need composition rules")
            last_target_end[action.connector_id] = item.end_ms
        if isinstance(item.action, (TargetAction, TransformAction)):
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
                obj = layout_objects[target]
                if target in highlighted_targets:
                    raise V2FrameError(f"highlighted target {target} cannot receive another action")
                if target in crossed_out_targets:
                    raise V2FrameError(f"crossed-out target {target} cannot receive another action")
                if isinstance(item.action, TargetAction) and item.action.verb == "isolate":
                    obj = layout_objects[target]
                    if (not completed_visible[target] or completed_opacity[target] <= 0
                            or completed_reveal[target] < 1):
                        raise V2FrameError(
                            f"isolate {item.action.action_id} needs visible focus content"
                        )
                if isinstance(item.action, TargetAction) and item.action.verb == "highlight":
                    if (not initial[target].visible or initial[target].state != "visible"
                            or obj.opacity <= 0 or target in last_target_end):
                        raise V2FrameError(
                            f"highlight {item.action.action_id} needs an untouched visible target"
                        )
                    highlighted_targets.add(target)
                if isinstance(item.action, TargetAction) and item.action.verb == "cross_out":
                    if (not initial[target].visible or initial[target].state != "visible"
                            or obj.opacity <= 0 or target in last_target_end):
                        raise V2FrameError(
                            f"cross_out {item.action.action_id} needs an untouched visible target"
                        )
                    crossed_out_targets.add(target)
                if (isinstance(item.action, TargetAction) and item.action.verb == "dim"
                        and (not initial[target].visible or initial[target].state != "visible"
                             or obj.opacity <= 0 or last_target_verb.get(target) not in (None, "dim"))):
                    raise V2FrameError(f"dim {item.action.action_id} needs visible context without prior edits")
                if (isinstance(item.action, TargetAction) and item.action.verb == "progressive_reveal"
                        and (initial[target].visible or initial[target].state != "hidden"
                             or target in last_target_end)):
                    raise V2FrameError(f"action {item.action.action_id} requires a previously untouched hidden list")
                if item.start_ms < last_target_end.get(target, 0):
                    raise V2FrameError(f"overlapping actions on {target} need an explicit composition rule")
                last_target_end[target] = item.end_ms
                last_target_verb[target] = item.action.verb



def _validate_consumer_history(context: _PairContext):
    """One replay/camera/lifecycle proof for the caller's exact causal actions.

    Storage receipt callers may use a resolved-order prefix. All observers must
    use that same prefix, including their later-edit scans, not the full document.
    Public capability admission remains the responsibility of the frame caller.
    """
    layout, timeline, hierarchy = context.layout, context.timeline, context.hierarchy
    try:
        replay = replay_chronology(
            context.objects, hierarchy, {frame.object_id: frame for frame in context.frames},
            {key: item.state_version for key, item in context.initial.items()}, tuple(timeline.actions),
            tuple((item.board_id, item.start_ms, item.end_ms) for item in layout.activations), timeline.duration_ms,
        )
    except ReplayError as exc:
        raise V2FrameError(str(exc)) from exc
    try:
        camera_plan = camera_segments(layout, timeline, replay)
        _validate_pair_temporal(context, replay, camera_plan)
    except (UnsupportedCamera, ReplayError) as exc:
        raise V2FrameError(str(exc)) from exc
    return replay, camera_plan


def _validate_pair(layout: ExecutableLayoutV2, timeline: ResolvedVisualTimelineV2,
                   layout_sha256: str, hierarchy: HierarchySnapshot):
    context = _validate_pair_static(layout, timeline, layout_sha256, hierarchy)
    # Preserve capability/error boundaries until full structural consumers land.
    for resolved in timeline.actions:
        action = resolved.action
        if isinstance(action, GroupAction) or not supports_operator(action):
            raise UnsupportedVisualAction(
                f"v2 action {action.action_id} uses {action.verb}, which has no frame implementation"
            )
    return _validate_consumer_history(context)


def validate_resolved_return_history(layout: ExecutableLayoutV2, timeline: ResolvedVisualTimelineV2,
                                     *, layout_sha256: str) -> None:
    """Validate compiler return receipts on write without opening public Group rendering.

    Replay and lifecycle consumers are the same immutable proof used by frames.
    A receipt is proved at its captured start, never compared to the initial pose.
    Without returns, this helper proves the full history. This is a storage
    validator, not a renderer capability advertisement.
    """
    hierarchy = HierarchySnapshot.from_objects({obj.object_id: obj for obj in layout.objects})
    return_indices = [index for index, item in enumerate(timeline.actions)
                      if isinstance(item.action, EvidenceAction) and item.action.verb == "return_board"]
    # Same-time starts follow resolved order. An action after the last return is
    # not its causal history, even if their millisecond timestamps are equal.
    causal_actions = timeline.actions[:return_indices[-1] + 1] if return_indices else timeline.actions
    # Kernel-level paired consumer proofs do not yet admit stored Group/annotation
    # productions. Preserve that write boundary until stored receipts/duplication
    # and the remaining hierarchy consumers are proven through their real callers.
    if any(isinstance(item.action, GroupAction) for item in causal_actions) and any(
        isinstance(item.action, TargetAction) and item.action.annotation_policy is not None
        for item in causal_actions
    ):
        raise V2FrameError("stored hierarchy annotation productions require consumer integration")
    causal_timeline = timeline.model_copy(update={"actions": list(causal_actions)})
    # The caller hashes the exact stored document, not a default-expanded dump.
    # All static and temporal consumer scans share this same resolved-order slice.
    context = _validate_pair_static(layout, causal_timeline, layout_sha256, hierarchy,
                                    structural_timeline=timeline if return_indices else None)
    _validate_consumer_history(context)


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
    replay, camera_plan = _validate_pair(layout, timeline, layout_sha256, hierarchy)
    return _sample_validated_frame(layout, timeline, replay, camera_plan, at_ms)


def _sample_validated_frame(layout: ExecutableLayoutV2, timeline: ResolvedVisualTimelineV2,
                            replay: ChronologicalReplay, camera_plan, at_ms: int) -> FrameSnapshot:
    """Sample an already-proven history; not a public capability admission route.

    Private paired-consumer proofs and the public evaluator use this identical
    geometry/view assembly. Production callers still enter through evaluate_frame.
    """
    if type(at_ms) is not int or not 0 <= at_ms < timeline.duration_ms:
        raise V2FrameError("frame time must be an integer within the resolved timeline")
    sample = replay.at(at_ms)
    current = {item.object_id: item for item in sample.objects}
    hierarchy = sample.hierarchy
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
