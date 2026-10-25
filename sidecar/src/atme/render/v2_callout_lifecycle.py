"""Read-only Callout readiness and retained-pointer proof on the shared replay.

No annotation policy or reading duration is inferred. A pointer persists until
an explicit exit completes; endpoint edits may start at that exact boundary.
"""

from atme.render.style_bundle import resolve_contract_bundle
from atme.render.v2_callout_pointer import callout_pointer_route
from atme.render.v2_lifecycle import geometry_dependencies, validate_group_lifetime
from atme.render.v2_media_view import media_lifetime_cuts, media_visual_view
from atme.render.v2_timeline_replay import version_targets
from atme.store.contracts_v2 import (
    GroupAction,
    TargetAction,
    _callout_leader_owners,
)


class UnsupportedCalloutLifecycle(ValueError):
    """Authored Callout endpoints cannot remain readable and stable."""


def validate_callout_history(layout, timeline, objects, replay, *, registry_inputs=None) -> None:
    owners = _callout_leader_owners(objects)
    if not owners:
        return
    # Full ownership inventory is proved by the paired static context. This
    # observer may receive a causal receipt prefix: future owners are not orphan
    # pointers, and their actions must not be pulled into this replay.
    style, _, _ = resolve_contract_bundle(layout.style_system_version, layout.asset_registry_version)
    aspect = "landscape-16:9" if layout.output_profile.profile_id == "LONG_FORM_16_9" else "portrait-9:16"
    design = style.aspects[aspect]
    scale = layout.output_profile.width / design.width
    if abs(scale - layout.output_profile.height / design.height) > 1e-6:
        raise UnsupportedCalloutLifecycle("callout needs uniform profile scaling")

    def ready(sample, callout, leader_id):
        current = sample.hierarchy.object_map(objects)
        states = {row.object_id: row for row in sample.objects}
        endpoints = {callout.object_id, callout.callout_binding.target_object_id}
        chain = geometry_dependencies(sample.hierarchy, endpoints | {leader_id})
        if any(not states[key].visible or states[key].opacity != 1 or states[key].reveal_fraction != 1
               or states[key].state == "removed" for key in chain - {leader_id}):
            raise UnsupportedCalloutLifecycle(f"callout {callout.object_id} needs fully ready endpoints and parents")
        for key in endpoints:
            if current[key].clip_id or any(current[parent].object_type != "group"
                                          for parent in sample.hierarchy.ancestors(key)):
                raise UnsupportedCalloutLifecycle("callout pointer endpoints require unclipped group ancestry")
        order = sample.hierarchy.paint_order(current, callout.board_id)
        target = callout.callout_binding.target_object_id
        if target not in order or any(key not in order or order.index(key) <= order.index(target)
                                     for key in (callout.object_id, leader_id)):
            raise UnsupportedCalloutLifecycle("callout and pointer must paint above their target")
        try:
            callout_pointer_route(current[leader_id], current, states, style.strokes.regular_px * scale,
                            registry_inputs=registry_inputs, media_view=media_visual_view(current, sample.at_ms))
        except ValueError as exc:
            raise UnsupportedCalloutLifecycle(f"callout {callout.object_id}: {exc}") from exc
        return chain

    for leader_id, callout in owners.items():
        starts = []
        if objects[leader_id].visible:
            starts.append((0, None))
        for item in timeline.actions:
            # Structural receipts may version an unchanged pointer's sibling
            # ordinal. Geometric Group effects are proved separately below.
            if isinstance(item.action, GroupAction):
                continue
            if leader_id not in version_targets(item.action):
                continue
            action = item.action
            if (not isinstance(action, TargetAction) or action.annotation_policy is not None
                    or action.target_ids != [leader_id] or action.verb not in {"draw", "reveal", "enter", "exit"}):
                raise UnsupportedCalloutLifecycle("callout pointer requires separate explicit construction or exit")
            if action.verb != "exit":
                starts.append((item.start_ms, item))
        for start, construction in starts:
            sample = replay.at(0) if construction is None else replay.before_action(construction.action.action_id)
            ready(sample, callout, leader_id)
            removal = next((row for row in timeline.actions if row.start_ms >= start
                and isinstance(row.action, TargetAction) and row.action.verb == "exit"
                and row.action.target_ids == [leader_id]), None)
            end = removal.end_ms if removal is not None else timeline.duration_ms
            participants = {callout.object_id, callout.callout_binding.target_object_id, leader_id}
            try:
                validate_group_lifetime(objects, timeline.actions, participants, start, end,
                    description=f"callout {callout.object_id} retained pointer")
            except ValueError as exc:
                raise UnsupportedCalloutLifecycle(str(exc)) from exc
            for other in timeline.actions:
                if other is construction or other is removal or other.start_ms >= end or other.end_ms <= start:
                    continue
                observed = replay.before_action(other.action.action_id)
                dependencies = geometry_dependencies(observed.hierarchy, participants)
                board_isolate = (isinstance(other.action, TargetAction) and other.action.verb == "isolate"
                    and other.action.board_id == callout.board_id)
                if not isinstance(other.action, GroupAction) and (
                    board_isolate or dependencies.intersection(version_targets(other.action))
                ):
                    raise UnsupportedCalloutLifecycle(
                        f"callout {callout.object_id} requires completed explicit pointer exit before endpoint edits")
            moments = {start, end - 1}
            moments.update(at for at in media_lifetime_cuts(objects, timeline.duration_ms) if start <= at < end)
            for checkpoint in replay.checkpoints:
                if start < checkpoint.at_ms < end:
                    moments.update((checkpoint.at_ms - 1, checkpoint.at_ms))
            for time in sorted(moments):
                retained = replay.at(time)
                state = retained.object(leader_id)
                if state.visible and state.opacity > 0 and state.reveal_fraction > 0:
                    ready(retained, callout, leader_id)
