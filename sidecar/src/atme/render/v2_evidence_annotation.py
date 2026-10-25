"""Read-only authored note proof for ordinary inserts and actual Split windows."""

from atme.render.v2_annotation import validate_annotation_geometry_binding
from atme.render.v2_lifecycle import (
    _evidence_window_samples,
    geometry_dependencies,
    lifecycle_samples,
    validate_annotation_paint_order_binding,
    validate_group_lifetime,
)
from atme.render.v2_media_view import require_media_window
from atme.render.v2_timeline_replay import version_targets
from atme.store.contracts_v2 import (
    CameraAction,
    EvidenceAction,
    GroupAction,
    SoundAction,
    SplitAction,
    TargetAction,
    _annotation_policy_object_ids,
)


def validate_evidence_annotation_history(item, layout, timeline, objects, treatment, replay, viewport_at,
                                          *, registry_inputs=None, split_window=None, camera_plan=()):
    intent = treatment.intent
    policy = intent.annotation_policy
    if policy is None:
        return
    source, target = treatment.object_id, intent.annotation_target_id
    notes = set(_annotation_policy_object_ids(policy))
    participants = {source, target, *notes}
    start_ms, construction_end = item.start_ms, item.end_ms
    hold_end = construction_end + intent.readable_hold_intent_ms

    def samples(end):
        return lifecycle_samples(replay, item, end)

    if isinstance(item.action, SplitAction):
        from atme.render.v2_split_clock import resolve_split_phase
        from atme.store.contracts_v2 import ResolvedSplitEvidenceWindow

        policy_source = item.action.split_policy
        result = next((row for row in policy_source.results if row.object_id == source), None) if policy_source else None
        if (type(split_window) is not ResolvedSplitEvidenceWindow or result is None or result.evidence_activation is None
                or split_window.result_object_id != source or split_window not in item.split_evidence_windows
                or treatment.action_id != item.action.action_id or result.evidence_activation.intent != intent):
            raise ValueError("Split annotation needs its actual result treatment and resolved read window")
        start_ms, construction_end = resolve_split_phase(item.start_ms, item.end_ms, result.construction.phase)
        hold_end = split_window.readable_hold_end_ms

        def samples(end):
            before = replay.before_action(item.action.action_id)
            return (before, *(sample for sample in _evidence_window_samples(replay, start_ms, end, camera_plan,
                boundaries=(construction_end, split_window.readable_hold_start_ms)) if sample.at_ms != before.at_ms))
    elif split_window is not None:
        raise ValueError("ordinary evidence cannot borrow a Split read window")
    before = replay.before_action(item.action.action_id)
    if any(before.object(key).visible or before.object(key).reveal_fraction != 0
           or before.object(key).state != "hidden" for key in notes):
        raise ValueError("evidence annotation requires untouched hidden notes")
    treatments = {row.action_id: row for row in timeline.evidence_treatments
                  if any(isinstance(owner.action, EvidenceAction) and owner.action.verb == "insert_evidence"
                         and owner.action.action_id == row.action_id for owner in timeline.actions)}
    removal = next((row for row in timeline.actions if isinstance(row.action, TargetAction)
                    and row.action.verb == "exit" and row.action.target_ids == [policy.leader_connector_id]
                    and row.start_ms >= hold_end), None)
    live_end = removal.end_ms if removal is not None else timeline.duration_ms
    endpoints = {source, target, policy.leader_connector_id}
    for start, end, observed, description in (
            (start_ms, hold_end, participants, "evidence annotation construction and hold"),
            (hold_end, live_end, endpoints, "retained evidence pointer")):
        if start >= end:
            continue
        validate_group_lifetime(objects, timeline.actions, observed, start, end, description=description)
        for other in timeline.actions:
            if (other.action.action_id == item.action.action_id or other is removal
                    or other.end_ms <= start or other.start_ms >= end
                    or isinstance(other.action, (CameraAction, SoundAction, GroupAction))):
                continue
            hierarchy = replay.before_action(other.action.action_id).hierarchy
            dependencies = geometry_dependencies(hierarchy, observed)
            writes = version_targets(other.action, treatments.get(other.action.action_id))
            isolate = (isinstance(other.action, TargetAction) and other.action.verb == "isolate"
                       and other.action.board_id == item.action.board_id)
            if isolate or dependencies.intersection(writes):
                raise ValueError(f"{description} requires completed pointer removal before target edits")
    require_media_window(objects, [target], start_ms, hold_end)
    for reading in samples(hold_end):
        current = reading.hierarchy.object_map(objects)
        frames = {frame.object_id: frame for frame in reading.objects}
        target_chain = geometry_dependencies(reading.hierarchy, [target])
        parents = geometry_dependencies(reading.hierarchy, participants).difference(participants)
        required = target_chain | parents | (notes if reading.at_ms >= construction_end else set())
        if any(not frames[key].visible or frames[key].opacity != 1 or frames[key].reveal_fraction != 1
               for key in required):
            raise ValueError("evidence annotation needs fully visible opaque target, parents and completed notes")
        validate_annotation_geometry_binding(target, policy, item.action.board_id, layout, current,
            {key: frame.transform for key, frame in frames.items()}, [viewport_at(reading.at_ms)],
            hierarchy=reading.hierarchy, registry_inputs=registry_inputs, source_id=source)
    for retained in samples(live_end):
        validate_annotation_paint_order_binding(target, policy, item.action.board_id,
            retained.hierarchy.object_map(objects), retained.hierarchy, source_id=source)
