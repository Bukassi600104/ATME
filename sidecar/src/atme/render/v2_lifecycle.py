"""Read-only lifecycle and effective stacking proofs over the shared replay.

These observers never author objects, reset state, or change structural versions.
Public Group rendering and private annotation integration are separate gates.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from atme.render.v2_hierarchy import validate_authored_hierarchy
from atme.render.v2_media_view import require_media_window
from atme.store.contracts_v2 import (
    CameraAction,
    ConnectionAction,
    ConnectorObject,
    EvidenceAction,
    GroupAction,
    SoundAction,
    TargetAction,
    _action_object_references,
    _annotation_object_ids,
    _annotation_policy_object_ids,
)

if TYPE_CHECKING:
    from atme.render.v2_split import SplitCapture
    from atme.render.v2_timeline_replay import ChronologicalReplay, ReplaySample
    from atme.store.contracts_v2 import (
        ExecutableLayoutV2,
        ResolvedAction,
        ResolvedVisualTimelineV2,
    )


class UnsupportedLifecycle(ValueError):
    """A consumer's authored reading/stacking promise cannot be preserved."""


def _split_requires_evidence_lifecycle(capture, objects, timeline):
    board = next(row.action.board_id for row in timeline.actions if row.action.action_id == capture.action_id)
    return (any(objects[key].object_type == "evidence" for key in capture.owned_object_ids)
            or any(isinstance(row.action, EvidenceAction) and row.action.verb == "insert_evidence"
                   and board in {row.action.board_id, row.action.destination_board_id} for row in timeline.actions))


def validate_split_lifecycle(capture: SplitCapture, replay: ChronologicalReplay,
                              layout: ExecutableLayoutV2, timeline: ResolvedVisualTimelineV2,
                              *, split_inputs=None, layout_sha256=None, structural_timeline=None,
                              registry_inputs=None) -> None:
    """Observe terminated relationships and explicitly frozen evidence reads.

    Evidence needs exact frozen inputs; the old four-argument path stays closed
    for it. Typed replay and public admission remain separate gates.
    """
    from atme.render.v2_split import (
        _AttributedSplitCapture,
        _validate_capture_inventory,
    )
    from atme.render.v2_split_identity import _stored_value
    from atme.render.v2_state import _validate_pair_static
    from atme.render.v2_timeline_replay import (
        ChronologicalReplay,
        _split_causal_timeline,
        version_targets,
    )
    from atme.store.contracts_v2 import (
        ExecutableLayoutV2,
        ResolvedVisualTimelineV2,
        _split_packet_digest,
    )

    if (type(capture) is not _AttributedSplitCapture or type(replay) is not ChronologicalReplay
            or type(layout) is not ExecutableLayoutV2 or type(timeline) is not ResolvedVisualTimelineV2):
        raise UnsupportedLifecycle("Split lifecycle needs exact attributed capture and paired replay contracts")
    _validate_capture_inventory(capture)
    layout = ExecutableLayoutV2.model_validate(_stored_value(layout))
    timeline = _split_causal_timeline(timeline, tuple(timeline.actions), structural_timeline)
    initial = replay.checkpoints[0]
    paired = _validate_pair_static(layout, timeline,
        layout_sha256 if layout_sha256 is not None else _split_packet_digest(layout.model_dump(mode="json")),
        initial.hierarchy, structural_timeline=structural_timeline, registry_inputs=registry_inputs,
        split_inputs=split_inputs)
    if {key: row.state_version for key, row in paired.initial.items()} != dict(initial.state_versions):
        raise UnsupportedLifecycle("Split lifecycle timeline differs from actual initial versions")
    recorded = {row.resolved_index: row for checkpoint in replay.checkpoints for row in checkpoint.active}
    owner = next((row for row in recorded.values() if getattr(row, "split_capture", None) is capture), None)
    if (owner is None or replay.duration_ms != timeline.duration_ms
            or tuple(recorded[key].resolved for key in sorted(recorded)) != tuple(timeline.actions)
            or {key: json.loads(value) for key, value in replay.authored_objects_json}
                != {obj.object_id: obj.model_dump(mode="json") for obj in layout.objects}):
        raise UnsupportedLifecycle("Split lifecycle capture, layout and complete timeline differ from actual replay")
    action = owner.resolved.action
    if action.action_id != capture.action_id:
        raise UnsupportedLifecycle("Split lifecycle capture differs from its actual owner")
    objects = {obj.object_id: obj for obj in layout.objects}
    before = replay.before_action(capture.action_id)
    if tuple(before.object(row.object_id) for row in capture.baseline) != capture.baseline:
        raise UnsupportedLifecycle("Split lifecycle baseline differs from the captured precondition")
    if _split_requires_evidence_lifecycle(capture, objects, timeline):
        if split_inputs is None:
            raise UnsupportedLifecycle("Split evidence lifecycle still requires reading, camera and native validation")
        _validate_split_evidence_lifecycle(capture, owner.resolved, replay, layout, timeline, split_inputs,
            layout_sha256=layout_sha256, structural_timeline=structural_timeline)
    bound = set(capture.owned_object_ids) | set(capture.read_dependency_ids)
    treatments = {row.action_id: row for row in timeline.evidence_treatments
                  if any(item.action.action_id == row.action_id and isinstance(item.action, EvidenceAction)
                         and item.action.verb == "insert_evidence" for item in timeline.actions)}

    def terminated(release, participants, expected):
        if release.end_ms >= capture.start_ms:
            raise UnsupportedLifecycle("Split retained relationship needs completed termination before capture")
        post = replay.at(release.end_ms)
        for key, state in expected.items():
            frame = before.object(key)
            if (frame.state != state or frame.visible
                    or state == "disconnected" and frame.reveal_fraction != 0
                    or state == "removed" and frame.opacity != 0):
                raise UnsupportedLifecycle("Split retained relationship has no exact terminated post-state")
        dependencies = geometry_dependencies(before.hierarchy, participants)
        dependencies |= geometry_dependencies(post.hierarchy, participants)
        post_nodes = {node.object_id: node for node in post.hierarchy.nodes}
        before_nodes = {node.object_id: node for node in before.hierarchy.nodes}
        if any(post.object(key) != before.object(key)
               or dict(post.state_versions)[key] != dict(before.state_versions)[key]
               or post_nodes[key] != before_nodes[key] for key in dependencies):
            raise UnsupportedLifecycle("Split retained termination lost its exact frame, version or hierarchy")
        for other in timeline.actions:
            if (other.action.action_id in {release.action.action_id, capture.action_id}
                    or other.end_ms <= release.end_ms or other.start_ms >= capture.end_ms
                    or isinstance(other.action, (CameraAction, SoundAction))):
                continue
            if isinstance(other.action, GroupAction):
                conflict = group_affects_geometry(other.action, objects, participants)
            else:
                conflict = bool(dependencies.intersection(version_targets(other.action,
                                                        treatments.get(other.action.action_id))))
            isolate = (isinstance(other.action, TargetAction) and other.action.verb == "isolate"
                       and other.action.board_id == action.board_id)
            if conflict or isolate:
                raise UnsupportedLifecycle("Split retained relationship has a later writer, re-add or reparent")

    managed = {row.action.connector_id for row in timeline.actions if isinstance(row.action, ConnectionAction)
               and row.start_ms < capture.end_ms}
    for key in sorted(managed):
        connector = objects[key]
        if not isinstance(connector, ConnectorObject):
            raise UnsupportedLifecycle("Split managed connector has no actual connector object")
        participants = {key, connector.destination_object_id}
        if connector.source_object_id is not None:
            participants.add(connector.source_object_id)
        if not geometry_dependencies(before.hierarchy, participants).intersection(bound):
            continue
        events = [row for row in timeline.actions if isinstance(row.action, ConnectionAction)
                  and row.action.connector_id == key]
        releases = [row for row in events if row.action.verb == "disconnect" and row.end_ms < capture.start_ms]
        if not releases:
            raise UnsupportedLifecycle("Split managed connector needs completed disconnect before capture")
        release = max(releases, key=lambda row: row.end_ms)
        if any(row.action.verb == "connect" and release.end_ms <= row.start_ms < capture.end_ms for row in events):
            raise UnsupportedLifecycle("Split managed connector cannot reconnect before Split completion")
        terminated(release, participants, {key: "disconnected"})
    for item in timeline.actions:
        candidate = item.action
        if (not isinstance(candidate, TargetAction) or candidate.annotation_policy is None
                or item.start_ms >= capture.end_ms):
            continue
        notes = set(_annotation_object_ids(candidate))
        participants = notes | set(candidate.target_ids)
        if not geometry_dependencies(before.hierarchy, participants).intersection(bound):
            continue
        hold_end = item.end_ms + candidate.annotation_policy.readable_hold_ms
        removals = []
        for key in sorted(notes):
            removal = next((row for row in timeline.actions if isinstance(row.action, TargetAction)
                and row.action.verb == "exit" and key in row.action.target_ids and row.start_ms >= hold_end
                and row.end_ms < capture.start_ms), None)
            if removal is None:
                raise UnsupportedLifecycle("Split retained annotation needs completed removal after its hold")
            removals.append(removal)
        terminated(max(removals, key=lambda row: row.end_ms), participants, {key: "removed" for key in notes})


def _evidence_window_samples(replay, start_ms, end_ms, camera_plan, *, boundaries=()):
    """Actual half-open read samples, including monotonic camera extrema."""
    if (type(start_ms) is not int or type(end_ms) is not int
            or not 0 <= start_ms < end_ms <= replay.duration_ms
            or any(type(at) is not int for at in boundaries)):
        raise UnsupportedLifecycle("evidence reading needs an exact bounded half-open window")
    # Supported camera easing is monotonic, and the owning observer forbids
    # geometry writers during this hold; viewport extrema are segment endpoints.
    edges = {*boundaries, *(row.at_ms for row in replay.checkpoints),
             *(at for item, _, _, _ in camera_plan for at in (item.start_ms, item.end_ms))}
    moments = {start_ms, end_ms - 1, *(at + offset for at in edges for offset in (-1, 0)
                                    if start_ms <= at + offset < end_ms)}
    return tuple(replay.at(at) for at in sorted(moments))


def _validate_split_evidence_lifecycle(capture, owner, replay, layout, timeline, inputs, *,
                                        layout_sha256=None, structural_timeline=None):
    from atme.render.style_bundle import registry_endpoint_inputs_for_objects
    from atme.render.v2_camera import camera_segments, evaluate_camera
    from atme.render.v2_evidence_annotation import validate_evidence_annotation_history
    from atme.render.v2_evidence_reading import validate_evidence_reading_binding
    from atme.render.v2_split import _expected_split_evidence_window
    from atme.render.v2_split_clock import resolve_split_phase
    from atme.render.v2_split_paint import _canonical, _checked_split_resources
    from atme.render.v2_state import _ease, _sample_validated_frame
    from atme.render.v2_svg import (
        _authored_annotation_bindings,
        _compose_validated_svg_frame,
    )
    from atme.render.v2_timeline_replay import version_targets
    from atme.store.contracts_v2 import EvidenceTreatment

    resources = _checked_split_resources(layout, inputs)
    if layout.evidence_treatments != timeline.evidence_treatments:
        raise UnsupportedLifecycle("Split reading requires the exact paired layout and timeline treatments")
    if ({row.asset_id: row.resolved_json for row in resources[3].rows}
            != {row.asset_id: _canonical(row.model_dump(mode="json")) for row in timeline.resolved_assets}):
        raise UnsupportedLifecycle("Split reading requires the complete actual frozen asset inventory")
    objects = {obj.object_id: obj for obj in layout.objects}
    registry = registry_endpoint_inputs_for_objects(objects, frozen_files=resources[2])
    camera_plan = camera_segments(layout, timeline, replay, split_inputs=inputs,
        layout_sha256=layout_sha256, structural_timeline=structural_timeline)
    held = {key: _sample_validated_frame(layout, timeline, replay, camera_plan, end)
            for key, policy, _, end in _authored_annotation_bindings(timeline)
            if policy.leader_connector_id is not None}
    _compose_validated_svg_frame(layout, timeline,
        _sample_validated_frame(layout, timeline, replay, camera_plan, capture.start_ms), held, None,
        split_inputs=inputs)
    treatments = {(row.action_id, row.object_id): row for row in timeline.evidence_treatments}
    ordinary = {row.action_id: row for row in timeline.evidence_treatments
                if any(isinstance(item.action, EvidenceAction) and item.action.verb == "insert_evidence"
                       and item.action.action_id == row.action_id for item in timeline.actions)}
    for item in timeline.actions:
        action = item.action
        if (not isinstance(action, EvidenceAction) or action.verb != "insert_evidence"
                or owner.action.board_id not in {action.board_id, action.destination_board_id}):
            continue
        treatment = ordinary[action.action_id]
        if treatments[(action.action_id, action.target_object_id)] != treatment:
            raise UnsupportedLifecycle("Split source hold needs its exact ordinary evidence treatment")
        hold_end = item.end_ms + treatment.intent.readable_hold_intent_ms
        if item.start_ms < capture.end_ms and capture.start_ms < hold_end:
            raise UnsupportedLifecycle("Split overlaps an active ordinary evidence readable hold")
        activation = next((row for row in layout.activations if row.board_id == action.destination_board_id
                           and row.start_ms <= item.start_ms and hold_end <= row.end_ms), None)
        if activation is None:
            raise UnsupportedLifecycle("ordinary evidence hold outlasts its actual board window")

        def ordinary_viewport(at, activation_id=activation.activation_id):
            return evaluate_camera(layout, camera_plan, at, activation_id, _ease)

        for reading in _evidence_window_samples(replay, item.end_ms, hold_end, camera_plan):
            validate_evidence_reading_binding(treatment.object_id, item.end_ms, layout, objects,
                                              treatment, reading, ordinary_viewport(reading.at_ms))
        validate_evidence_annotation_history(item, layout, timeline, objects, treatment, replay, ordinary_viewport,
                                              registry_inputs=registry)
    results = [row for row in owner.action.split_policy.results if row.evidence_activation is not None]
    captured = [(key, EvidenceTreatment.model_validate_json(raw)) for key, raw in capture.evidence_treatments_json]
    if captured != [(row.object_id, treatments.get((capture.action_id, row.object_id))) for row in results]:
        raise UnsupportedLifecycle("Split reading requires every exact captured result treatment")
    for result, window in zip(results, owner.split_evidence_windows, strict=True):
        treatment = treatments[(capture.action_id, result.object_id)]
        if window.model_dump(mode="json") != _expected_split_evidence_window(capture, result, treatment):
            raise UnsupportedLifecycle("Split reading differs from the actual captured phase clock")
        start, _ = resolve_split_phase(capture.start_ms, capture.end_ms, result.construction.phase)
        hold_start, hold_end = window.readable_hold_start_ms, window.readable_hold_end_ms
        activation = next((row for row in layout.activations if row.board_id == owner.action.board_id
                           and row.start_ms <= start and hold_end <= row.end_ms), None)
        if activation is None:
            raise UnsupportedLifecycle("Split reading outlasts its actual board window")
        observed = {result.object_id, *(key for row in owner.action.split_policy.source_basis.read_dependencies
                                      if row.kind in {"aperture", "mask_source"} for key in row.object_ids)}
        validate_group_lifetime(objects, timeline.actions, observed, start, hold_end,
                                description="Split evidence construction and readable hold")
        for other in timeline.actions:
            if (other is owner or other.action.action_id == capture.action_id
                    or other.end_ms <= start or other.start_ms >= hold_end
                    or isinstance(other.action, (CameraAction, SoundAction, GroupAction))):
                continue
            dependencies = geometry_dependencies(replay.before_action(other.action.action_id).hierarchy, observed)
            if (dependencies.intersection(version_targets(other.action, ordinary.get(other.action.action_id)))
                    or isinstance(other.action, TargetAction) and other.action.verb == "isolate"
                    and other.action.board_id == owner.action.board_id):
                raise UnsupportedLifecycle("Split evidence needs an uninterrupted construction and readable hold")

        def viewport(at, activation_id=activation.activation_id):
            return evaluate_camera(layout, camera_plan, at, activation_id, _ease)

        for reading in _evidence_window_samples(replay, hold_start, hold_end, camera_plan):
            validate_evidence_reading_binding(result.object_id, hold_start, layout, objects,
                                              treatment, reading, viewport(reading.at_ms))
        validate_evidence_annotation_history(owner, layout, timeline, objects, treatment, replay, viewport,
            registry_inputs=registry, split_window=window, camera_plan=camera_plan)


def lifecycle_samples(replay: ChronologicalReplay, item: ResolvedAction,
                      hold_end_ms: int) -> tuple[ReplaySample, ...]:
    """Captured pre-start plus completed end/hold and every intervening boundary.

    Sample immediately before each boundary as well as after its end-before-start
    commit. Keep intervals half-open; hold_end itself belongs to later work.
    """
    if (type(hold_end_ms) is not int
            or not item.start_ms < item.end_ms < hold_end_ms <= replay.duration_ms):
        raise UnsupportedLifecycle("lifecycle needs a bounded positive readable hold")
    moments = {item.end_ms, hold_end_ms - 1}
    for checkpoint in replay.checkpoints:
        if item.start_ms < checkpoint.at_ms < hold_end_ms:
            moments.add(checkpoint.at_ms)
            if checkpoint.at_ms - 1 > item.start_ms:
                moments.add(checkpoint.at_ms - 1)
    return (replay.before_action(item.action.action_id),
            *(replay.at(moment) for moment in sorted(moments)))


def geometry_dependencies(hierarchy, object_ids) -> frozenset[str]:
    """Read chains, distinct from ordinal-only structural version changes."""
    return frozenset(key for object_id in object_ids
                     for key in (object_id, *hierarchy.ancestors(object_id)))


def group_affects_geometry(action: GroupAction, objects: dict, object_ids) -> bool:
    before, after = validate_authored_hierarchy(action, objects)
    roots = {action.container_id, *action.target_ids}
    mutations = set(roots)
    observed = set()
    for hierarchy in (before, after):
        mutations.update(node.object_id for node in hierarchy.nodes
                         if roots.intersection(hierarchy.ancestors(node.object_id)))
        observed.update(geometry_dependencies(hierarchy, object_ids))
    return bool(mutations.intersection(observed))


def validate_group_lifetime(objects: dict, actions, object_ids, start_ms: int,
                            end_ms: int, *, description: str) -> None:
    for other in actions:
        if (isinstance(other.action, GroupAction)
                and other.start_ms < end_ms and start_ms < other.end_ms
                and group_affects_geometry(other.action, objects, object_ids)):
            raise UnsupportedLifecycle(f"{description} overlaps a geometric hierarchy edit")


def validate_connection_lifetime(item, sample, objects: dict, actions, duration_ms: int) -> None:
    """Managed relationships require stable endpoint geometry until disconnect ends.

    Live endpoint motion remains available to generic arrows. Managed connect /
    disconnect is bounded, not a promise of continuous moving-route validation.
    """
    action = item.action
    index = next(index for index, row in enumerate(actions) if row is item)
    if action.verb == "disconnect" and any(
        isinstance(row.action, ConnectionAction) and row.action.connector_id == action.connector_id
        and row.action.verb == "connect" for row in actions[:index]
    ):
        return  # The preceding connect already proves this whole retained interval.
    start = item.start_ms if action.verb == "connect" else 0
    end = item.end_ms if action.verb == "disconnect" else next(
        (row.end_ms for row in actions[index + 1:]
         if isinstance(row.action, ConnectionAction) and row.action.connector_id == action.connector_id
         and row.action.verb == "disconnect"), duration_ms,
    )
    endpoints = {key for key in (action.source_object_id, action.destination_object_id) if key is not None}
    connector = objects[action.connector_id]
    dependencies = geometry_dependencies(sample.hierarchy, endpoints)
    if connector.source_point is not None:
        dependencies |= frozenset(sample.hierarchy.ancestors(connector.object_id))
    description = f"connector {action.connector_id} connected lifetime"
    try:
        require_media_window(objects, endpoints, start, end)
    except ValueError as exc:
        raise UnsupportedLifecycle(f"{description}: {exc}") from exc
    hierarchy_reads = endpoints | ({connector.object_id} if connector.source_point is not None else set())
    validate_group_lifetime(objects, actions, hierarchy_reads, start, end, description=description)
    for other in actions:
        if other is item or other.start_ms >= end or other.end_ms <= start:
            continue
        candidate = other.action
        if isinstance(candidate, (CameraAction, SoundAction, GroupAction)):
            continue
        if isinstance(candidate, EvidenceAction) and candidate.verb == "return_board":
            continue
        mutations = ({candidate.connector_id} if isinstance(candidate, ConnectionAction)
                     else set(_action_object_references(candidate)))
        board_isolate = (isinstance(candidate, TargetAction) and candidate.verb == "isolate"
                         and candidate.board_id == action.board_id)
        if board_isolate or dependencies.intersection(mutations):
            raise UnsupportedLifecycle(f"{description} requires completed disconnect before endpoint edits")


def validate_annotation_paint_order(action, objects: dict, hierarchy) -> None:
    validate_annotation_paint_order_binding(action.target_ids[0], action.annotation_policy,
                                             action.board_id, objects, hierarchy)


def validate_annotation_paint_order_binding(target_id, policy, board_id, objects, hierarchy, *, source_id=None):
    order = hierarchy.paint_order(objects, board_id)
    references = [target_id] if source_id is None else [target_id, source_id]
    if any(key not in order for key in references) or any(
            key not in order or any(order.index(key) <= order.index(target) for target in references)
            for key in _annotation_policy_object_ids(policy)):
        raise UnsupportedLifecycle("annotation must paint above its target in the effective stacking hierarchy")


def nonterminal_paint_order(sample: ReplaySample, objects: dict, board_id: str,
                            *, retain: frozenset[str] = frozenset()) -> tuple[str, ...]:
    order = sample.hierarchy.paint_order(objects, board_id)
    frames = {frame.object_id: frame for frame in sample.objects}
    for key in order:
        if frames[key].state == "removed" and frames[key].visible:
            raise UnsupportedLifecycle(f"removed leaf {key} is still visible")
    return tuple(key for key in order if key in retain
                 or not (frames[key].state == "removed" and frames[key].visible is False))


def validate_replacement_paint_order(action, sample: ReplaySample, objects: dict) -> None:
    participants = frozenset((action.from_object_id, action.to_object_id))
    order = nonterminal_paint_order(sample, objects, action.board_id, retain=participants)
    if (not participants.issubset(order)
            or abs(order.index(action.from_object_id) - order.index(action.to_object_id)) != 1):
        raise UnsupportedLifecycle(f"{action.verb} {action.action_id} needs consecutive nonterminal paint slots")
