"""Read-only lifecycle and effective stacking proofs over the shared replay.

These observers never author objects, reset state, or change structural versions.
Public Group rendering and private annotation integration are separate gates.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from atme.render.v2_hierarchy import validate_authored_hierarchy
from atme.store.contracts_v2 import (
    CameraAction,
    ConnectionAction,
    EvidenceAction,
    GroupAction,
    SoundAction,
    TargetAction,
    _action_object_references,
    _annotation_object_ids,
)

if TYPE_CHECKING:
    from atme.render.v2_timeline_replay import ChronologicalReplay, ReplaySample
    from atme.store.contracts_v2 import ResolvedAction


class UnsupportedLifecycle(ValueError):
    """A consumer's authored reading/stacking promise cannot be preserved."""


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
    endpoints = {action.source_object_id, action.destination_object_id}
    dependencies = geometry_dependencies(sample.hierarchy, endpoints)
    description = f"connector {action.connector_id} connected lifetime"
    validate_group_lifetime(objects, actions, endpoints, start, end, description=description)
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
    order = hierarchy.paint_order(objects, action.board_id)
    target = action.target_ids[0]
    if target not in order or any(key not in order or order.index(key) <= order.index(target)
                                  for key in _annotation_object_ids(action)):
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
