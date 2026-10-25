"""Deterministic, bounded camera viewports for authored v2 visual actions.

Camera framing is computed once from the authored action boundary, not from the
time at which a caller happens to seek. The legacy camera renderer is untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from atme.render.v2_morph import geometry_object
from atme.render.v2_technical_frame import validate_technical_frame_world
from atme.render.v2_world import UnsupportedWorldGeometry, world_bounds
from atme.store.contracts_v2 import (
    CameraAction,
    ContainerObject,
    ExecutableLayoutV2,
    ReplaceAction,
    ResolvedVisualTimelineV2,
    VisualObject,
)

if TYPE_CHECKING:
    from atme.render.v2_timeline_replay import ChronologicalReplay


class UnsupportedCamera(ValueError):
    """An authored camera move cannot be framed faithfully and safely."""


@dataclass(frozen=True)
class CameraViewport:
    x: float
    y: float
    width: float
    height: float
    action_id: str | None = None
    movement_purpose: str | None = None


def _full(layout: ExecutableLayoutV2) -> CameraViewport:
    canvas = layout.canvas
    return CameraViewport(canvas.x, canvas.y, canvas.width, canvas.height)


def _contains(outer: CameraViewport, inner: tuple[float, float, float, float]) -> bool:
    x1, y1, x2, y2 = inner
    epsilon = 1e-6
    return (outer.x - epsilon <= x1 and outer.y - epsilon <= y1
            and x2 <= outer.x + outer.width + epsilon
            and y2 <= outer.y + outer.height + epsilon)


def _safe_contains(viewport: CameraViewport,
                   rect: tuple[float, float, float, float]) -> bool:
    inset_x = viewport.width * 0.08
    inset_y = viewport.height * 0.08
    return _contains(CameraViewport(viewport.x + inset_x, viewport.y + inset_y,
                                    viewport.width - 2 * inset_x,
                                    viewport.height - 2 * inset_y), rect)


def _target_viewport(layout: ExecutableLayoutV2, rects, framing: str) -> CameraViewport:
    canvas = layout.canvas
    left = min(rect[0] for rect in rects)
    top = min(rect[1] for rect in rects)
    right = max(rect[2] for rect in rects)
    bottom = max(rect[3] for rect in rects)
    full = _full(layout)
    if not _contains(full, (left, top, right, bottom)):
        raise UnsupportedCamera("camera target extends beyond the output canvas")
    # Fraction of viewport reserved for the target. Larger fraction means a
    # closer shot; safe_area deliberately keeps more breathing room.
    occupancy = {"wide": 0.42, "medium": 0.60, "close": 0.78,
                 "detail": 0.90, "safe_area": 0.52}[framing]
    aspect = canvas.width / canvas.height
    needed_w = max((right - left) / occupancy, (bottom - top) * aspect / occupancy)
    # A tiny icon must not become a full-screen illustration. Bound the camera
    # zoom independently of the target size.
    width = min(canvas.width, max(canvas.width * 0.30, needed_w))
    # Wide targets may force a wider shot than the requested framing. Never
    # crop the focus merely to satisfy a nominal occupancy target.
    center_x = (left + right) / 2
    center_y = (top + bottom) / 2

    def centered(candidate_width: float) -> CameraViewport:
        candidate_height = candidate_width / aspect
        x = min(max(center_x - candidate_width / 2, canvas.x),
                canvas.x + canvas.width - candidate_width)
        y = min(max(center_y - candidate_height / 2, canvas.y),
                canvas.y + canvas.height - candidate_height)
        return CameraViewport(x, y, candidate_width, candidate_height)

    viewport = centered(width)
    if not _contains(viewport, (left, top, right, bottom)):
        raise UnsupportedCamera("camera framing clips the target at a canvas edge")
    if framing == "safe_area":
        rect = (left, top, right, bottom)
        if not _safe_contains(viewport, rect):
            lower = max(canvas.width * 0.30,
                        (right - left) / 0.84, (bottom - top) * aspect / 0.84)
            for step in range(1, 257):
                candidate = centered(width - (width - lower) * step / 256)
                if _safe_contains(candidate, rect):
                    viewport = candidate
                    break
        if not _safe_contains(viewport, rect):
            raise UnsupportedCamera("safe_area camera framing cannot maintain its required inset")
    return viewport


def _same(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-6


def _destination(layout, source: CameraViewport, target: CameraViewport,
                 rect, action: CameraAction) -> CameraViewport:
    if action.verb == "camera_hold":
        if not (_same(source.width, target.width) and _same(source.height, target.height)):
            raise UnsupportedCamera("camera_hold framing disagrees with the current viewport")
        result = source
    elif action.verb == "camera_pan":
        if not (_same(source.width, target.width) and _same(source.height, target.height)):
            raise UnsupportedCamera("camera_pan framing needs the current viewport scale; use reframe")
        canvas = layout.canvas
        x = target.x + (target.width - source.width) / 2
        y = target.y + (target.height - source.height) / 2
        result = CameraViewport(min(max(x, canvas.x), canvas.x + canvas.width - source.width),
                                min(max(y, canvas.y), canvas.y + canvas.height - source.height),
                                source.width, source.height)
    elif action.verb == "camera_zoom":
        center_x = source.x + source.width / 2
        center_y = source.y + source.height / 2
        result = CameraViewport(center_x - target.width / 2, center_y - target.height / 2,
                                target.width, target.height)
    else:
        result = target
    full = _full(layout)
    if not _contains(full, (result.x, result.y, result.x + result.width, result.y + result.height)):
        raise UnsupportedCamera(f"{action.verb} would move the viewport outside the canvas")
    if not _contains(result, rect):
        raise UnsupportedCamera(f"{action.verb} cannot keep the focus target in frame")
    if action.framing == "safe_area" and not _safe_contains(result, rect):
        raise UnsupportedCamera(f"{action.verb} cannot maintain the safe_area inset")
    if action.verb == "camera_pan" and not (_same(source.width, result.width)
                                            and _same(source.height, result.height)):
        raise UnsupportedCamera("camera_pan cannot change zoom")
    if action.verb == "camera_zoom" and not (_same(source.x + source.width / 2,
                                                   result.x + result.width / 2)
                                             and _same(source.y + source.height / 2,
                                                       result.y + result.height / 2)):
        raise UnsupportedCamera("camera_zoom cannot pan")
    return CameraViewport(result.x, result.y, result.width, result.height,
                          action.action_id, action.movement_purpose)


def camera_segments(layout: ExecutableLayoutV2, timeline: ResolvedVisualTimelineV2,
                    replay: ChronologicalReplay, *, split_inputs=None, layout_sha256=None, structural_timeline=None):
    """Frame focus from the shared sampled start boundary, never start-ordered guesses."""
    initial = {obj.object_id: obj for obj in layout.objects}
    segments = []
    previous_end = 0
    active_activation = None
    viewport = _full(layout)
    for resolved in timeline.actions:
        action = resolved.action
        if isinstance(action, CameraAction):
            sample = replay.before_action(action.action_id)
            objects = sample.hierarchy.object_map(initial)
            frames = {frame.object_id: frame for frame in sample.objects}
            visible = {key: frame.visible for key, frame in frames.items()}
            opacity = {key: frame.opacity for key, frame in frames.items()}
            revealed = {key: frame.reveal_fraction == 1 for key, frame in frames.items()}
            transforms = {key: frame.transform for key, frame in frames.items()}
            if len(set(action.target_ids)) != len(action.target_ids):
                raise UnsupportedCamera(f"camera {action.action_id} repeats a focus target")
            activation = next((item for item in layout.activations
                               if item.board_id == action.board_id
                               and item.start_ms <= resolved.start_ms
                               and resolved.end_ms <= item.end_ms), None)
            if activation is None:
                raise UnsupportedCamera(f"camera {action.action_id} needs one active board")
            if active_activation != activation.activation_id:
                viewport = _full(layout)
                previous_end = 0
                active_activation = activation.activation_id
            if resolved.start_ms < previous_end:
                raise UnsupportedCamera("overlapping camera actions need an explicit composition rule")
            previous_end = resolved.end_ms
            if action.verb in {"camera_hold", "camera_cut"} and action.easing != "step":
                raise UnsupportedCamera(f"{action.verb} requires step easing")
            if action.verb not in {"camera_hold", "camera_cut"} and action.easing == "step":
                raise UnsupportedCamera(f"{action.verb} requires continuous easing")
            if action.expected_state not in (None, "framed") or action.post_state != "framed":
                raise UnsupportedCamera(f"camera {action.action_id} needs canonical framed state")
            rects = []
            from atme.render.v2_split import CapturedSplitAction
            from atme.render.v2_split_paint import _split_focus_bounds

            split_captures = {id(row.split_capture): row.split_capture for checkpoint in replay.checkpoints
                              for row in checkpoint.active if isinstance(row, CapturedSplitAction)
                              and row.resolved.start_ms <= resolved.start_ms
                              and set(action.target_ids).intersection(row.split_capture.owned_object_ids)}
            split_targets = set()
            if split_captures:
                if len(split_captures) != 1 or split_inputs is None:
                    raise UnsupportedCamera("Split camera needs one attributed capture and frozen paint inputs")
                capture = next(iter(split_captures.values()))
                from atme.render.v2_lifecycle import (
                    geometry_dependencies,
                    group_affects_geometry,
                )
                from atme.render.v2_timeline_replay import version_targets
                from atme.store.contracts_v2 import (
                    EvidenceAction,
                    GroupAction,
                    TargetAction,
                )

                participants = set(capture.owned_object_ids) | set(capture.read_dependency_ids)
                dependencies = geometry_dependencies(sample.hierarchy, participants)
                for other in timeline.actions:
                    if other.end_ms <= resolved.start_ms or other.start_ms >= resolved.end_ms:
                        continue
                    treatment = next((row for row in timeline.evidence_treatments
                        if isinstance(other.action, EvidenceAction) and other.action.verb == "insert_evidence"
                        and (row.action_id, row.object_id) == (other.action.action_id, other.action.target_object_id)), None)
                    writes = version_targets(other.action, treatment)
                    regroup = (isinstance(other.action, GroupAction)
                               and group_affects_geometry(other.action, objects, participants))
                    isolate = (isinstance(other.action, TargetAction) and other.action.verb == "isolate"
                               and other.action.board_id == action.board_id)
                    if dependencies.intersection(writes) or regroup or isolate:
                        raise UnsupportedCamera(f"camera {action.action_id} overlaps a focus-object edit")
                rects.append(_split_focus_bounds(capture, layout, timeline, replay, split_inputs, action.action_id,
                    layout_sha256=layout_sha256, structural_timeline=structural_timeline))
                split_targets.update(capture.owned_object_ids)
            for target_id in action.target_ids:
                if target_id in split_targets:
                    continue
                obj = objects[target_id]
                if obj.board_id != action.board_id:
                    raise UnsupportedCamera(f"camera {action.action_id} crosses board ownership")
                if obj.clip_id is not None:
                    raise UnsupportedCamera("camera needs external post-clip visible focus geometry")
                dependency_ids = {target_id}
                parent_id = obj.parent_id
                while parent_id is not None:
                    if (objects[parent_id].clip_id is not None
                            or isinstance(objects[parent_id], ContainerObject)
                            and objects[parent_id].object_type in {"clip", "mask"}):
                        raise UnsupportedCamera(
                            f"camera {action.action_id} needs post-clip visible focus geometry, including masks"
                        )
                    dependency_ids.add(parent_id)
                    parent_id = objects[parent_id].parent_id
                if any((other.action.verb in {"move", "scale", "rotate", "fade", "reveal",
                                              "write", "draw", "enter", "exit", "progressive_reveal"}
                        and dependency_ids.intersection(getattr(other.action, "target_ids", ()))
                        and other.start_ms < resolved.end_ms
                        and resolved.start_ms < other.end_ms)
                       or (isinstance(other.action, ReplaceAction)
                           and dependency_ids.intersection({other.action.from_object_id,
                                                            other.action.to_object_id})
                           and other.start_ms < resolved.end_ms
                           and resolved.start_ms < other.end_ms)
                       for other in timeline.actions):
                    raise UnsupportedCamera(f"camera {action.action_id} overlaps a focus-object edit")
                if any(not visible[item] or not revealed[item] or opacity[item] <= 0
                       for item in dependency_ids):
                    raise UnsupportedCamera(f"camera {action.action_id} needs revealed visible focus")
                # The current compositor has faithful geometry for these types.
                focus_obj, focus_objects = obj, objects
                native = (isinstance(obj, VisualObject) and obj.technical_frame is not None
                          and obj.object_type in {"browser", "application", "server", "database", "folder", "comparison"})
                if native:
                    if obj.clip_id is not None:
                        raise UnsupportedCamera("technical_frame camera needs post-clip visible focus geometry")
                    current = {key: geometry_object(value, frames[key].morph_geometry) for key, value in objects.items()}
                    try:
                        validate_technical_frame_world(current[target_id], current, transforms)
                    except ValueError as exc:
                        raise UnsupportedCamera(str(exc)) from exc
                    focus_obj, focus_objects = current[target_id], current
                elif obj.object_type not in {"freehand", "line", "rectangle", "rounded_rectangle",
                                           "ellipse", "polygon", "underline", "highlight", "text", "list", "code", "callout",
                                           "icon", "pictogram", "character", "device", "document",
                                           "chart", "terminal"}:
                    raise UnsupportedCamera(f"camera {action.action_id} targets unsupported visual geometry")
                try:
                    rects.append(world_bounds(focus_obj, focus_objects, transforms))
                except UnsupportedWorldGeometry as exc:
                    raise UnsupportedCamera(str(exc)) from exc
            rect = (min(r[0] for r in rects), min(r[1] for r in rects),
                    max(r[2] for r in rects), max(r[3] for r in rects))
            target_viewport = _target_viewport(layout, rects, action.framing)
            destination = _destination(layout, viewport, target_viewport, rect, action)
            if (action.verb in {"camera_pan", "camera_zoom", "camera_reframe"}
                    and all(_same(getattr(viewport, field), getattr(destination, field))
                            for field in ("x", "y", "width", "height"))):
                raise UnsupportedCamera(f"{action.verb} has no visible camera movement")
            segments.append((resolved, activation.activation_id, viewport, destination))
            viewport = destination
    return tuple(segments)


def evaluate_camera(layout: ExecutableLayoutV2, segments, at_ms: int,
                    activation_id: str | None, ease) -> CameraViewport:
    viewport = _full(layout)
    for resolved, segment_activation, start, end in segments:
        if segment_activation != activation_id or at_ms < resolved.start_ms:
            continue
        if at_ms >= resolved.end_ms or resolved.action.verb in {"camera_cut", "camera_hold"}:
            viewport = end
            continue
        progress = ease((at_ms - resolved.start_ms) / (resolved.end_ms - resolved.start_ms),
                        resolved.action.easing)
        viewport = CameraViewport(
            start.x + (end.x - start.x) * progress,
            start.y + (end.y - start.y) * progress,
            start.width + (end.width - start.width) * progress,
            start.height + (end.height - start.height) * progress,
            resolved.action.action_id, resolved.action.movement_purpose,
        )
    return viewport
