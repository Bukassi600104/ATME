"""Read-only technical-composite readiness on the existing canonical replay."""

from dataclasses import fields
from math import isfinite

from atme.render.v2_morph import geometry_object
from atme.render.v2_technical_frame import validate_technical_frame_world
from atme.store.contracts_v2 import (
    GroupContainer,
    TargetAction,
    TransformAction,
    VisualObject,
)


class UnsupportedTechnicalFrameLifecycle(ValueError):
    """Real authored content would outlive or detach from its technical chrome."""


def validate_technical_frame_sample(obj, objects, states, *, active=True):
    """Current actual paint chains; shared ancestor attenuation is not local fade.

    Potential positive paint is conservative under apertures. This does not
    pretend a bounds box establishes actual image alpha or semantic readability.
    """
    from atme.render.v2_state import CountFrameObject, FrameObject

    if objects.keys() != states.keys():
        raise UnsupportedTechnicalFrameLifecycle("technical_frame needs every exact sampled frame")
    for key, frame in states.items():
        if (type(frame) not in {FrameObject, CountFrameObject}
                or set(frame.__dict__) != {field.name for field in fields(type(frame))}
                or frame.object_id != key or frame.board_id != objects[key].board_id
                or type(frame.visible) is not bool
                or any(type(value) not in {int, float} or not isfinite(value) or not 0 <= value <= 1
                       for value in (frame.opacity, frame.reveal_fraction))):
            raise UnsupportedTechnicalFrameLifecycle("technical_frame has an invalid current frame payload")
    current = {key: geometry_object(item, states[key].morph_geometry) for key, item in objects.items()}
    validate_technical_frame_world(current[obj.object_id], current, {key: frame.transform for key, frame in states.items()})
    def positive(key):
        while key is not None:
            frame = states[key]
            if not frame.visible or frame.state == "removed" or frame.opacity <= 0 or frame.reveal_fraction <= 0:
                return False
            key = objects[key].parent_id
        return active
    pending = [role.object_id for role in obj.technical_frame.roles]
    painted_parts = []
    while pending:
        key = pending.pop()
        part = objects[key]
        if type(part) is GroupContainer:
            pending.extend(part.child_ids)
        elif positive(key):
            painted_parts.append(key)
    chrome = states[obj.object_id]
    if painted_parts and (chrome.state != "visible" or not chrome.visible
                          or chrome.opacity != 1 or chrome.reveal_fraction != 1):
        raise UnsupportedTechnicalFrameLifecycle(f"technical_frame {obj.object_id} needs locally ready chrome for positive parts")
    return tuple(sorted(painted_parts))


def validate_technical_frame_history(layout, timeline, objects, replay):
    """Prove readiness at canonical state/paint boundaries and cue extrema.

    Requested-frame geometry is additionally checked by the common compositor,
    exactly as for sampled registry art. No interpolated pose is replaced with
    its authored initial pose, and no second timeline/clock is constructed.
    """
    ids = [obj.object_id for obj in objects.values() if isinstance(obj, VisualObject) and obj.technical_frame is not None]
    if not ids:
        return
    moments = {0, timeline.duration_ms - 1}
    for checkpoint in replay.checkpoints:
        moments.update((checkpoint.at_ms - 1, checkpoint.at_ms, checkpoint.at_ms + 1))
    for item in timeline.actions:
        length = item.end_ms - item.start_ms
        moments.update(item.start_ms + int(length * fraction) for fraction in (.2, .5, .8))
    for activation in layout.activations:
        moments.update((activation.start_ms - 1, activation.start_ms, activation.end_ms - 1, activation.end_ms))
    for at_ms in sorted(moment for moment in moments if 0 <= moment < timeline.duration_ms):
        sample = replay.at(at_ms)
        current = sample.hierarchy.object_map(objects)
        states = {frame.object_id: frame for frame in sample.objects}
        active_board = next((item.board_id for item in layout.activations if item.start_ms <= at_ms < item.end_ms), None)
        for key in ids:
            obj = current[key]
            parts = validate_technical_frame_sample(obj, current, states, active=obj.board_id == active_board)
            for item in timeline.actions:
                action = item.action
                geometric = isinstance(action, TransformAction) and action.verb in {"move", "scale", "rotate"}
                teardown = (isinstance(action, TransformAction) and action.verb == "fade" and action.opacity != 1
                            or isinstance(action, TargetAction) and action.verb in {"exit", "dim"})
                if (parts and (geometric or teardown) and key in action.target_ids
                        and item.start_ms <= at_ms < item.end_ms):
                    raise UnsupportedTechnicalFrameLifecycle(
                        f"technical_frame {key} chrome-local teardown/geometry motion overlaps positive parts")
