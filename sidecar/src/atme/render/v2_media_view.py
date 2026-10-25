"""Pure absolute-clock media ink/readiness; never changes intrinsic replay state."""

from collections.abc import Mapping
from dataclasses import dataclass


def media_active_at(playback, at_ms: int) -> bool:
    if type(at_ms) is not int or at_ms < 0:
        raise ValueError("media visual view requires an exact nonnegative project clock")
    end = playback.timeline_start_ms + playback.source_out_ms - playback.source_in_ms
    return playback.timeline_start_ms <= at_ms < end


def _objects(objects):
    return objects.values() if isinstance(objects, Mapping) else objects


@dataclass(frozen=True)
class _MediaVisualView:
    at_ms: int
    active_ids: frozenset[str]
    inactive_ids: frozenset[str]

    def allows(self, object_id: str) -> bool:
        return object_id not in self.inactive_ids


def media_visual_view(objects, at_ms: int) -> _MediaVisualView:
    if type(at_ms) is not int or at_ms < 0:
        raise ValueError("media visual view requires an exact nonnegative project clock")
    active, inactive = set(), set()
    for obj in _objects(objects):
        playback = getattr(obj, "media_playback", None)
        if playback is not None:
            (active if media_active_at(playback, at_ms) else inactive).add(obj.object_id)
    return _MediaVisualView(at_ms, frozenset(active), frozenset(inactive))


def media_lifetime_cuts(objects, duration_ms: int) -> tuple[int, ...]:
    cuts = set()
    for obj in _objects(objects):
        playback = getattr(obj, "media_playback", None)
        if playback is None:
            continue
        start = playback.timeline_start_ms
        end = start + playback.source_out_ms - playback.source_in_ms
        cuts.update((start - 1, start, end - 1, end))
    return tuple(sorted(at for at in cuts if 0 <= at < duration_ms))


def require_media_readiness(objects, object_ids, view):
    """Intrinsic readiness stays with each consumer; add only media ink gating."""
    for key in object_ids:
        obj = objects[key]
        if getattr(obj, "media_playback", None) is None:
            continue
        if (type(view) is not _MediaVisualView or key not in view.active_ids
                or key in view.inactive_ids or not media_active_at(obj.media_playback, view.at_ms)):
            raise ValueError(f"media {key} has no active visual anchor at this project clock")


def require_media_window(objects, object_ids, start_ms, end_ms):
    """Read-only interval proof, including exact natural media lifetime cuts."""
    ids = tuple(object_ids)
    selected = {key: objects[key] for key in ids}
    moments = {start_ms, end_ms - 1, *media_lifetime_cuts(selected, end_ms)}
    for at in sorted(time for time in moments if start_ms <= time < end_ms):
        require_media_readiness(objects, ids, media_visual_view(objects, at))


def validate_media_relationship_history(layout, timeline, objects, replay):
    """A visible retained arrow cannot read a naturally expired media endpoint.

    Only media ink readiness is observed. Ordinary moving-route, hierarchy and
    intrinsic lifecycle proofs retain their existing owners. No decoder I/O.
    """
    from atme.store.contracts_v2 import (
        ConnectorObject,
        TargetAction,
        _annotation_phase_windows,
    )

    arrows = [obj for obj in objects.values() if isinstance(obj, ConnectorObject)
              and any(getattr(objects.get(key), "media_playback", None) is not None
                      for key in (obj.source_object_id, obj.destination_object_id))]
    if not arrows:
        return
    cuts = {0, timeline.duration_ms, *media_lifetime_cuts(objects, timeline.duration_ms)}
    for activation in layout.activations:
        cuts.update((activation.start_ms, activation.end_ms))
    for checkpoint in replay.checkpoints:
        cuts.add(checkpoint.at_ms)
    for row in timeline.actions:
        cuts.update((row.start_ms, row.end_ms))
        if isinstance(row.action, TargetAction) and row.action.annotation_policy is not None:
            for _phase, start, end in _annotation_phase_windows(row):
                cuts.update((start, end))
    moments = {time + delta for time in cuts for delta in (-1, 0, 1)}
    for at in sorted(time for time in moments if 0 <= time < timeline.duration_ms):
        sample = replay.at(at)
        current = sample.hierarchy.object_map(objects)
        states = {row.object_id: row for row in sample.objects}
        active = next((row.board_id for row in layout.activations if row.start_ms <= at < row.end_ms), None)
        view = media_visual_view(current, at)
        for arrow in arrows:
            if arrow.board_id != active:
                continue
            chain = (arrow.object_id, *sample.hierarchy.ancestors(arrow.object_id))
            if all(states[key].visible and states[key].opacity > 0 and states[key].reveal_fraction > 0
                   and states[key].state != "removed" for key in chain):
                require_media_readiness(current, (arrow.source_object_id, arrow.destination_object_id), view)


def validate_media_ranges(objects, assets, duration_ms):
    from atme.store.contracts_v2 import validate_media_asset_binding

    for obj in _objects(objects):
        playback = getattr(obj, "media_playback", None)
        if playback is None:
            continue
        validate_media_asset_binding(obj, assets.get(obj.asset_id))
        if playback.timeline_start_ms + playback.source_out_ms - playback.source_in_ms > duration_ms:
            raise ValueError(f"media {obj.object_id} source range exceeds the resolved timeline duration")
