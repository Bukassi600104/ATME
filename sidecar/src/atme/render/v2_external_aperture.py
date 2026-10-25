"""Named aperture reads over the existing immutable hierarchy and replay.

This module does not paint, infer ownership, or build another clock. A read
borrows only its named Clip bounds or dedicated Mask source, never the aperture
shapes of that owner's ancestors. Those ancestors still supply the actual pose.
"""
import json
from dataclasses import asdict, dataclass, fields
from hashlib import sha256
from itertools import pairwise
from math import isfinite

from atme.render.v2_media_view import (
    media_lifetime_cuts,
    media_visual_view,
    require_media_readiness,
)
from atme.render.v2_morph import geometry_object
from atme.render.v2_split_clock import resolve_split_phase
from atme.render.v2_world import Affine, world_matrix
from atme.store.contracts_v2 import (
    ContainerObject,
    GroupAction,
    MaskContainer,
    SplitAction,
    TargetAction,
    TextObject,
    _annotation_phase_windows,
    _reject_parent_cycles,
    _structured_list_phase_windows,
    _validate_external_aperture_references,
    _validate_mask_layout,
)


class UnsupportedExternalAperture(ValueError):
    """An external read cannot preserve its authored sampled geometry/lifetime."""


def _map_signature(objects, states=None):
    payload = {key: obj.model_dump(mode="json") for key, obj in objects.items()}
    if states is not None:
        payload = [payload, {key: asdict(state) for key, state in states.items()}]
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True, init=False)
class ApertureCapturedSubset:
    """Private selected-paint transport, issued after live Split authentication.

    This is not a partial-map option. Its exact map/sample signatures and finite
    missing edges cannot be reused for another map, clock sample or board.
    """
    present_ids: frozenset[str]
    read_only_ids: frozenset[str]
    missing_edges: frozenset[tuple[str, str]]
    active_board_id: str
    objects_sha256: str
    sample_sha256: str

    def __init__(self, *args, **kwargs):
        raise TypeError("ApertureCapturedSubset is issued only after live Split coverage authentication")

    def validate(self, objects, states=None):
        if (type(self) is not ApertureCapturedSubset or frozenset(objects) != self.present_ids
                or _map_signature(objects) != self.objects_sha256
                or states is not None and _map_signature(objects, states) != self.sample_sha256):
            raise UnsupportedExternalAperture("external aperture captured subset does not match authenticated map/sample")
        missing = frozenset((key, child) for key, obj in objects.items()
            for child in getattr(obj, "child_ids", ()) if child not in objects)
        if (missing != self.missing_edges or any(key not in self.read_only_ids for key, _ in missing)
                or any(obj.board_id != self.active_board_id for obj in objects.values())):
            raise UnsupportedExternalAperture("external aperture captured subset has unauthenticated omissions/board")

    def present_children(self, key, objects):
        children = getattr(objects[key], "child_ids", ())
        if any(child not in objects and (key, child) not in self.missing_edges for child in children):
            raise UnsupportedExternalAperture("external aperture missing an owned child")
        return tuple(child for child in children if child in self.present_ids)


def _captured_subset_after_authentication(objects, states, owned_ids, read_ids, board_id):
    """Called only by the closure returned after _split_coverage_context checks.

    That closure verifies the exact states against the existing capture sampler
    first. Ordinary callers never receive or manufacture this authority.
    """
    owned, reads = frozenset(owned_ids), frozenset(read_ids)
    if owned & reads or owned | reads != frozenset(objects):
        raise UnsupportedExternalAperture("external aperture capture needs exact disjoint owned/read inventory")
    values = (frozenset(objects), reads,
        frozenset((key, child) for key, obj in objects.items()
            for child in getattr(obj, "child_ids", ()) if child not in objects),
        board_id, _map_signature(objects), _map_signature(objects, states))
    context = object.__new__(ApertureCapturedSubset)
    for field, value in zip(fields(ApertureCapturedSubset), values, strict=True):
        object.__setattr__(context, field.name, value)
    context.validate(objects, states)
    return context


@dataclass(frozen=True)
class ApertureProjection:
    consumer_id: str
    aperture_id: str
    source_id: str | None
    relative: Affine
    corners: tuple[tuple[float, float], ...]
    read_ids: frozenset[str]
    structural_ids: frozenset[str]
    live: bool


def _ancestors(key, objects):
    result = []
    parent = objects[key].parent_id
    while parent is not None:
        result.append(parent)
        parent = objects[parent].parent_id
    return tuple(result)


def validate_external_aperture_map(objects, *, captured_subset=None):
    """Current reciprocal ownership, not a substitute initial hierarchy."""
    if not any(obj.clip_id is not None for obj in objects.values()):
        return ()
    if captured_subset is not None:
        if type(captured_subset) is not ApertureCapturedSubset:
            raise UnsupportedExternalAperture("external aperture needs an authenticated captured subset")
        captured_subset.validate(objects)
    if any(key != obj.object_id for key, obj in objects.items()):
        raise UnsupportedExternalAperture("external aperture needs exact current object identities")
    try:
        _reject_parent_cycles(objects)
        for key, obj in objects.items():
            if obj.parent_id is not None and (
                    obj.parent_id not in objects or key not in objects[obj.parent_id].child_ids):
                raise ValueError("external aperture needs complete reciprocal current membership")
            children = (captured_subset.present_children(key, objects) if captured_subset is not None else getattr(obj, "child_ids", ()))
            if isinstance(obj, ContainerObject) and set(children) != {
                    child for child, part in objects.items() if part.parent_id == key}:
                raise ValueError("external aperture needs complete reciprocal current children")
        _validate_mask_layout(tuple(objects.values()), objects)
        _validate_external_aperture_references(objects, {key: obj.parent_id for key, obj in objects.items()},
                                             captured_subset=captured_subset)
    except (ValueError, KeyError, AttributeError) as exc:
        raise UnsupportedExternalAperture(f"unsupported clip_id: {exc}") from exc
    references = tuple(sorted(key for key, obj in objects.items() if obj.clip_id is not None))
    for key in references:
        obj, owner = objects[key], objects[objects[key].clip_id]
        if isinstance(obj, TextObject) and obj.object_type == "callout":
            raise UnsupportedExternalAperture("external aperture Callout consumer needs its owned-pointer proof")
        paths = [key, owner.object_id]
        if isinstance(owner, MaskContainer):
            paths.append(owner.mask_source_object_id)
        if any(objects[parent].clip_id is not None for root in paths for parent in _ancestors(root, objects)):
            raise UnsupportedExternalAperture("external aperture cannot execute nested external reference chains")
    return references


def _positive_paint(root, objects, states, active_board, captured_subset, media_view):
    mask_sources = {obj.mask_source_object_id for obj in objects.values() if isinstance(obj, MaskContainer)}
    pending = [root]
    while pending:
        key = pending.pop()
        obj = objects[key]
        if isinstance(obj, ContainerObject):
            pending.extend(captured_subset.present_children(key, objects) if captured_subset is not None else obj.child_ids)
            continue
        if key in mask_sources or obj.board_id != active_board:
            continue
        if getattr(obj, "media_playback", None) is not None:
            if media_view is None:
                raise UnsupportedExternalAperture("external aperture media requires its exact visual view")
            if not media_view.allows(key):
                continue
            require_media_readiness(objects, [key], media_view)
        if all(states[part].visible and states[part].state != "removed"
               and states[part].opacity > 0 and states[part].reveal_fraction > 0
               for part in (key, *_ancestors(key, objects))):
            return True
    return False


def external_aperture_projections(objects, states, *, active_board, state_versions=None, captured_subset=None,
                                  media_view=None):
    """Authenticate actual local frames and project into each consumer's parent.

    A normal frame caller supplies the replay's exact current version inventory.
    Selected frozen paint has already authenticated versions in its captured
    placements; it uses this same geometry/readiness path without inventing any.
    """
    references = validate_external_aperture_map(objects, captured_subset=captured_subset)
    if not references:
        return ()
    if (type(active_board) is not str or active_board not in {obj.board_id for obj in objects.values()}
            or captured_subset is not None and active_board != captured_subset.active_board_id):
        raise UnsupportedExternalAperture("external aperture requires its authoritative active board")
    if captured_subset is not None:
        captured_subset.validate(objects, states)
    from atme.render.v2_state import CountFrameObject, FrameObject

    if (objects.keys() != states.keys() or any(
            type(frame) not in {FrameObject, CountFrameObject}
            or set(frame.__dict__) != {field.name for field in fields(type(frame))}
            or frame.object_id != key or frame.board_id != objects[key].board_id
            or type(frame.visible) is not bool
            or any(type(value) not in {int, float} or not isfinite(value) or not 0 <= value <= 1
                   for value in (frame.opacity, frame.reveal_fraction)) for key, frame in states.items())):
        raise UnsupportedExternalAperture("external aperture requires every exact finite current frame")
    if state_versions is not None and (objects.keys() != state_versions.keys()
            or any(type(value) is not int or value < 1 for value in state_versions.values())):
        raise UnsupportedExternalAperture("external aperture requires the exact current state-version inventory")
    current = {key: geometry_object(obj, states[key].morph_geometry) for key, obj in objects.items()}
    transforms = {key: frame.transform for key, frame in states.items()}
    projections = []
    for key in references:
        consumer = current[key]
        owner = current[consumer.clip_id]
        chain = (key, *_ancestors(key, current))
        roots = [owner.object_id]
        source_id = owner.mask_source_object_id if isinstance(owner, MaskContainer) else None
        if source_id is not None:
            roots.append(source_id)
        reads, structural = set(), set(chain)
        for root in roots:
            structural.update((root, *_ancestors(root, current)))
            cursor = root
            while cursor is not None and cursor not in chain:
                reads.add(cursor)
                cursor = current[cursor].parent_id
        pending = [key]
        while pending:
            child = pending.pop()
            structural.add(child)
            pending.extend(captured_subset.present_children(child, current) if captured_subset is not None
                           else getattr(current[child], "child_ids", ()))
        live = _positive_paint(key, current, states, active_board, captured_subset, media_view)
        if live:
            require_media_readiness(current, reads, media_view)
        if live and any(not states[read].visible or states[read].state in {"hidden", "removed"}
                        or states[read].opacity != 1 or states[read].reveal_fraction != 1 for read in reads):
            raise UnsupportedExternalAperture(f"external aperture {key} requires fully ready opaque exclusive read branches")
        source = current[source_id] if source_id is not None else owner
        parent = current[consumer.parent_id] if consumer.parent_id is not None else None
        parent_world = world_matrix(parent, current, transforms) if parent is not None else Affine()
        relative = parent_world.inverse() @ world_matrix(source, current, transforms)
        bounds = source.geometry.bounds
        # Match native shape serialization, not an AABB substitute for its ink.
        x, y, width, height = (float(f"{value:.4f}") for value in (bounds.x, bounds.y, bounds.width, bounds.height))
        corners = tuple(relative.point(px, py) for px, py in ((x, y), (x+width, y), (x+width, y+height), (x, y+height)))
        projections.append(ApertureProjection(key, owner.object_id, source_id, relative, corners,
                                              frozenset(reads), frozenset(structural), live))
    return tuple(projections)


def _history_boundaries(layout, timeline):
    cuts = {0, timeline.duration_ms, *media_lifetime_cuts(layout.objects, timeline.duration_ms)}
    for row in layout.activations:
        cuts.update((row.start_ms, row.end_ms))
    for row in timeline.actions:
        cuts.update((row.start_ms, row.end_ms))
        action = row.action
        if isinstance(action, TargetAction):
            windows = (_annotation_phase_windows(row) if action.annotation_policy is not None
                       else _structured_list_phase_windows(row) if action.structured_list_policy is not None else ())
            for _phase, start, end in windows:
                cuts.update((start, end))
        if isinstance(action, SplitAction) and action.split_policy is not None:
            policy = action.split_policy
            for phase in (policy.source_exit, *[result.construction.phase for result in policy.results],
                          *[result.movement.phase for result in policy.results if result.movement is not None]):
                cuts.update(resolve_split_phase(row.start_ms, row.end_ms, phase))
    return sorted(cut for cut in cuts if 0 <= cut <= timeline.duration_ms)


def validate_external_aperture_history(layout, timeline, objects, replay):
    """Reserve positive paint intervals from the canonical replay and phase cuts.

    Between these boundaries the existing supported scalar visibility channels
    are monotone. Start/start+1/end-1 witnesses establish the first positive
    integer-ms instant; interval overlap, not sparse samples, reserves the read.
    A requested frame is independently rechecked before either paint path.
    """
    if not validate_external_aperture_map(objects):
        return
    from atme.render.v2_split import _reservation_footprint

    peers = tuple((row, *_reservation_footprint(row.action)) for row in timeline.actions)
    cuts = _history_boundaries(layout, timeline)
    for start, end in pairwise(cuts):
        observed = {}
        for at_ms in sorted({start, min(start+1, end-1), end-1}):
            sample = replay.at(at_ms)
            current = sample.hierarchy.object_map(objects)
            active = next((row.board_id for row in layout.activations if row.start_ms <= at_ms < row.end_ms), None)
            for projection in external_aperture_projections(current, {row.object_id: row for row in sample.objects},
                    active_board=active, state_versions=dict(sample.state_versions),
                    media_view=media_visual_view(current, at_ms)):
                if projection.live:
                    observed.setdefault(projection.consumer_id, (at_ms, projection))
        for live_start, projection in observed.values():
            for peer, writes, _reads in peers:
                if not peer.start_ms < end or not live_start < peer.end_ms:
                    continue
                action = peer.action
                board_isolate = isinstance(action, TargetAction) and action.verb == "isolate" and action.board_id == objects[projection.consumer_id].board_id
                if (projection.read_ids.intersection(writes) or board_isolate
                        or isinstance(action, GroupAction) and projection.structural_ids.intersection(writes)):
                    raise UnsupportedExternalAperture(
                        f"external aperture {projection.consumer_id} read lifetime conflicts with action {action.action_id}")
