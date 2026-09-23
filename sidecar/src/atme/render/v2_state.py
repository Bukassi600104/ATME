"""Pure, random-access frame evaluation for the visual-production v2 runtime.

This module does not render pixels or make a plan production-ready. Every action
must have an explicit visual implementation before it can enter this evaluator;
unsupported verbs fail rather than silently becoming a static layout.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace

from atme.render.v2_connector import UnsupportedConnector, validate_static_arrow
from atme.render.v2_emphasis import (
    SUPPORTED_HIGHLIGHT_MARKS,
    SUPPORTED_HIGHLIGHT_TEXT,
    UnsupportedEmphasis,
    cross_out_paths,
    emphasis_path,
)
from atme.render.v2_list import UnsupportedOrderedList, validate_ordered_list
from atme.store.contracts_v2 import (
    ConnectionAction,
    ConnectorObject,
    ExecutableLayoutV2,
    MarkObject,
    ResolvedVisualTimelineV2,
    TargetAction,
    TextObject,
    Transform,
    TransformAction,
)


class V2FrameError(ValueError):
    """A v2 frame cannot be evaluated without changing authored meaning."""


class UnsupportedVisualAction(V2FrameError):
    """An authored action has no v2 visual runtime implementation yet."""


# Versioned bounded meaning of a transient dim attention cue. The authored
# opacity is restored after the action; this is not a persistent opacity edit.
_DIM_MIN_RATIO = 0.35
_DIM_RAMP_FRACTION = 0.2


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
    object_id: str
    board_id: str
    state: str
    visible: bool
    opacity: float
    reveal_fraction: float
    transform: FrameTransform
    emphasis_fraction: float = 0.0
    cross_out_fraction: float = 0.0


@dataclass(frozen=True)
class FrameSnapshot:
    at_ms: int
    active_board_id: str | None
    objects: tuple[FrameObject, ...]

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
                   layout_sha256: str) -> None:
    if (layout.project_id != timeline.project_id or layout.layout_id != timeline.layout_id
            or layout.plan_id != timeline.plan_id or layout.plan_revision != timeline.plan_revision
            or layout.plan_sha256 != timeline.plan_sha256
            or layout_sha256 != timeline.layout_sha256
            or layout.output_profile != timeline.output_profile
            or layout.style_system_version != timeline.style_system_version
            or layout.asset_registry_version != timeline.asset_registry_version):
        raise V2FrameError("resolved timeline and executable layout do not describe the same composition")
    layout_objects = {item.object_id: item for item in layout.objects}
    state_objects = {item.object_id for item in timeline.initial_object_states}
    if set(layout_objects) != state_objects:
        raise V2FrameError("the resolved timeline must initialize every layout object exactly once")
    initial = {item.object_id: item for item in timeline.initial_object_states}
    managed_connectors = {item.action.connector_id for item in timeline.actions
                          if isinstance(item.action, ConnectionAction)}
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
    completed_transform = {
        object_id: FrameTransform.from_contract(obj.transform)
        for object_id, obj in layout_objects.items()
    }
    for item in timeline.actions:
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
            for target in item.action.target_ids:
                if target in highlighted_targets:
                    raise V2FrameError(f"highlighted target {target} cannot receive another action")
                if target in crossed_out_targets:
                    raise V2FrameError(f"crossed-out target {target} cannot receive another action")
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
                if isinstance(item.action, TransformAction):
                    action = item.action
                    if action.verb == "fade":
                        if action.destination is not None:
                            raise V2FrameError("fade cannot carry an ignored transform destination")
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
    _validate_pair(layout, timeline, layout_sha256)
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
            isinstance(action, (TransformAction, ConnectionAction))
            or isinstance(action, TargetAction) and action.verb in {
                "reveal", "write", "draw", "enter", "exit", "progressive_reveal", "highlight",
                "cross_out",
                "dim",
            }
        )
        if not supported:
            raise UnsupportedVisualAction(
                f"v2 action {action.action_id} uses {action.verb}, which has no frame implementation"
            )
        if at_ms < resolved.start_ms:
            continue
        progress = _ease(
            (at_ms - resolved.start_ms) / (resolved.end_ms - resolved.start_ms),
            action.easing,
        )
        completed = at_ms >= resolved.end_ms
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

    active_board = next((item.board_id for item in layout.activations
                         if item.start_ms <= at_ms < item.end_ms), None)
    ordered = tuple(
        replace(current[obj.object_id],
                visible=current[obj.object_id].visible and obj.board_id == active_board)
        for obj in sorted(layout.objects, key=lambda item: (item.z_index, item.object_id))
    )
    return FrameSnapshot(at_ms=at_ms, active_board_id=active_board, objects=ordered)
