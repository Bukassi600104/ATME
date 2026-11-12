"""Immutable finite editorial sound score; no audio decoding or mixing."""
from __future__ import annotations

import json
from dataclasses import dataclass, replace

from atme.store.contracts_v2 import ResolvedVisualTimelineV2, SoundAction, VisualPlanV2


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _sequence(action):
    playback = action.sound_policy.playback
    return (action.asset_id, playback.source_in_ms, playback.source_out_ms, playback.repeat_count)


def _end_offset(item):
    playback = item.action.sound_policy.playback
    return playback.offset_ms + (item.end_ms - item.start_ms if item.action.state == "playing" else 0)


def validate_sound_intervals(actions):
    """Validate the complete score, including both sides of adjacent boundaries."""
    buses = {}
    roles = {}
    for item in actions:
        action = item.action
        if not isinstance(action, SoundAction):
            continue
        policy = action.sound_policy
        if policy is None:
            raise ValueError("sound execution requires a complete sound policy")
        if policy.bus_id.strip() != policy.bus_id or not policy.bus_id.strip() or policy.bus_id.lower() in {
            "*", "master", "narration"
        }:
            raise ValueError("sound requires a named editorial bus, never narration or wildcard")
        if roles.setdefault(policy.bus_id, policy.bus_role) != policy.bus_role:
            raise ValueError("sound bus role drift")
        if policy.fade_in.duration_ms + policy.fade_out.duration_ms > item.end_ms - item.start_ms:
            raise ValueError("sound fades exceed the resolved interval")
        playback = policy.playback
        if playback and action.state == "playing" and _end_offset(item) > (
            playback.source_out_ms - playback.source_in_ms
        ) * playback.repeat_count:
            raise ValueError("sound playing interval exceeds finite playback exhaustion")
        key = (policy.bus_role, policy.bus_id, action.verb == "purposeful_silence")
        buses.setdefault(key, []).append(item)
    for (_, _, silence), rows in buses.items():
        for index, item in enumerate(rows):
            previous = rows[index - 1] if index else None
            following = rows[index + 1] if index + 1 < len(rows) else None
            action = item.action
            if previous and previous.end_ms > item.start_ms:
                raise ValueError("overlapping sound controls on the same bus")
            if silence:
                continue
            expected = previous.action.post_state if previous and previous.end_ms == item.start_ms else "stopped"
            if action.expected_state != expected:
                raise ValueError("sound expected state differs from preceding boundary")
            if (action.state == "paused" or expected in {"playing", "paused"}) and (
                        previous is None or previous.end_ms != item.start_ms
                        or previous.action.sound_policy.playback is None
                        or action.sound_policy.playback is None
                        or _sequence(previous.action) != _sequence(action)
                        or _end_offset(previous) != action.sound_policy.playback.offset_ms):
                raise ValueError("sound continuation requires an exact adjacent sequence and cursor")
            post = "stopped"
            playback = action.sound_policy.playback
            if (action.verb == "music_state" and playback is not None and following is not None
                    and following.start_ms == item.end_ms
                    and following.action.state in {"playing", "paused"}
                    and following.action.sound_policy.playback is not None
                    and _sequence(action) == _sequence(following.action)
                    and _end_offset(item) == following.action.sound_policy.playback.offset_ms
                    and _end_offset(item) < (playback.source_out_ms - playback.source_in_ms) * playback.repeat_count):
                post = action.state
            if action.post_state != post:
                raise ValueError("sound post state requires exact adjacent cursor consumer or stopped completion")


@dataclass(frozen=True)
class SoundSample:
    action_id: str
    bus_role: str
    bus_id: str
    state: str
    offset_ms: int | None
    source_position_ms: int | None
    completed_repetitions: int | None
    amplitude: float
    attenuation: float


@dataclass(frozen=True)
class SoundEvent:
    action_id: str
    source_instruction_id: str
    board_id: str
    coverage_id: str
    start_ms: int
    end_ms: int
    bus_role: str
    bus_id: str
    state: str
    expected_state: str
    post_state: str
    gain_db: float
    narration_priority_control: str
    action_json: str
    resolved_trigger_json: str
    asset_json: str | None
    authority_json: str

    def sample(self, at_ms):
        from atme.render.v2_state import _ease

        if not self.start_ms <= at_ms < self.end_ms:
            return None
        action = json.loads(self.action_json)
        policy = action["sound_policy"]
        elapsed = at_ms - self.start_ms
        duration = self.end_ms - self.start_ms
        fade_in, fade_out = policy["fade_in"], policy["fade_out"]
        attack = _ease(elapsed / fade_in["duration_ms"], fade_in["easing"]) if fade_in["duration_ms"] else 1.0
        release = _ease((duration - elapsed) / fade_out["duration_ms"], fade_out["easing"]) if fade_out["duration_ms"] else 1.0
        envelope = attack * release
        playback = policy.get("playback")
        offset = position = repetitions = None
        if playback:
            offset = playback["offset_ms"] + (elapsed if self.state == "playing" else 0)
            region = playback["source_out_ms"] - playback["source_in_ms"]
            position = playback["source_in_ms"] + offset % region
            repetitions = offset // region
        return SoundSample(self.action_id, self.bus_role, self.bus_id, self.state, offset, position,
            repetitions, 10 ** (self.gain_db / 20) * envelope if self.state == "playing" else 0.0,
            1 - envelope if self.state == "silent" else 1.0)


@dataclass(frozen=True)
class SoundLedger:
    duration_ms: int
    events: tuple[SoundEvent, ...]

    def sample(self, at_ms: int) -> tuple[SoundSample, ...]:
        if type(at_ms) is not int:
            raise ValueError("sound sample requires integer project milliseconds")
        rows = tuple(row for event in self.events if (row := event.sample(at_ms)) is not None)
        attenuation = {(row.bus_role, row.bus_id): row.attenuation for row in rows if row.state == "silent"}
        return tuple(replace(row, amplitude=row.amplitude * attenuation.get((row.bus_role, row.bus_id), 1.0),
                             attenuation=attenuation.get((row.bus_role, row.bus_id), 1.0))
                     if row.state != "silent" else row for row in rows)


def derive_sound_ledger(resolved, plan=None) -> SoundLedger:
    """ProjectService additionally authenticates owned bytes before storing authority."""
    timeline = (resolved if isinstance(resolved, ResolvedVisualTimelineV2)
                else ResolvedVisualTimelineV2.model_validate(resolved))
    if plan is not None and not isinstance(plan, VisualPlanV2):
        plan = VisualPlanV2.model_validate(plan)
    validate_sound_intervals(timeline.actions)
    assets = {asset.asset_id: asset for asset in timeline.resolved_assets}
    plan_assets = {asset.asset_id: asset for asset in plan.assets} if plan is not None else {}
    if plan is not None:
        authored = {action.action_id: action for action in plan.actions}
        authored_sound = {key for key, action in authored.items() if isinstance(action, SoundAction)}
        resolved_sound = {item.action.action_id for item in timeline.actions if isinstance(item.action, SoundAction)}
        if authored_sound != resolved_sound:
            raise ValueError("resolved sound inventory differs from authored score")
        for item in timeline.actions:
            if isinstance(item.action, SoundAction) and authored.get(item.action.action_id) != item.action:
                raise ValueError("resolved sound differs from authored action")
    authority = {key: getattr(timeline, key) for key in (
        "timeline_id", "project_id", "project_revision", "plan_id", "plan_revision", "plan_sha256",
        "layout_id", "layout_revision", "layout_sha256", "cleaned_timeline_revision",
        "cleaned_timeline_fingerprint", "compilation_fingerprint")}
    events = []
    for item in timeline.actions:
        action = item.action
        if not isinstance(action, SoundAction):
            continue
        policy = action.sound_policy
        asset_json = None
        if action.asset_id is not None:
            asset = assets.get(action.asset_id)
            if (asset is None or asset.kind not in {"audio", "sound_effect" if policy.bus_role == "effect" else "music"}
                    or not asset.provenance_verified or not asset.media_type or not asset.media_type.startswith("audio/")
                    or asset.byte_length is None or asset.duration_ms is None
                    or asset.managed_ref != f"atme://projects/{timeline.project_id}/assets/{asset.asset_id}"):
                raise ValueError("sound requires exact owned audio asset metadata")
            if policy.playback and policy.playback.source_out_ms > asset.duration_ms:
                raise ValueError("sound source range exceeds declared asset duration")
            if plan is not None:
                original = plan_assets.get(asset.asset_id)
                if original is None or any(getattr(original, key) != getattr(asset, key) for key in (
                    "revision", "managed_ref", "checksum_sha256", "kind", "duration_ms"
                )):
                    raise ValueError("sound plan/resolved asset pins differ")
            asset_json = _json({key: getattr(asset, key) for key in (
                "asset_id", "revision", "managed_ref", "checksum_sha256", "kind", "media_type",
                "byte_length", "duration_ms", "provenance_verified")})
        events.append(SoundEvent(action.action_id, action.source_instruction_id, action.board_id,
            action.coverage_id, item.start_ms, item.end_ms, policy.bus_role, policy.bus_id, action.state,
            action.expected_state, action.post_state, action.gain_db, policy.narration_priority,
            _json(action.model_dump(mode="json")), _json(item.resolved_trigger.model_dump(mode="json")),
            asset_json, _json(authority)))
    return SoundLedger(timeline.duration_ms, tuple(events))
