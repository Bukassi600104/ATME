"""Render the resolved editorial score over the unchanged mastered narration."""
from __future__ import annotations

import json
import shutil
import tempfile
from contextlib import ExitStack
from pathlib import Path

import numpy as np
import soundfile as sf

from atme.audio.editorial import AUDIO_FORMATS, decode_sound
from atme.project_assets import _sha256
from atme.render.v2_sound_events import derive_sound_ledger


SOUND_VERBS = {"sound_cue", "music_state", "purposeful_silence"}


def validate_plan(plan):
    actions = {action["action_id"]: action for action in plan["actions"]}
    for action in plan["actions"]:
        if action["verb"] in SOUND_VERBS and not action.get("sound_policy"):
            raise ValueError("Audio export requires an explicit playback and bus policy for each sound action")
    for beat in plan["beats"]:
        intent = beat["sound_intent"]
        if intent["role"] in ("effect", "music") and not any(
            actions[key].get("asset_id") == intent["asset_id"]
            and (actions[key].get("sound_policy") or {}).get("bus_role") == intent["role"]
            for key in beat["action_ids"]
        ):
            raise ValueError(f"Beat {beat['beat_id']} needs an executable action for its intended sound")


def freeze_sources(service, project_id, timeline, plan, inputs):
    if not any(action["verb"] in SOUND_VERBS for action in plan["actions"]):
        return
    for index, pin in enumerate(_source_pins(derive_sound_ledger(timeline, plan)).values()):
        source, metadata = service.asset(project_id, pin["asset_id"])
        if (metadata["revision"] != pin["revision"] or metadata["sha256"] != pin["checksum_sha256"]
                or metadata["bytes"] != pin["byte_length"] or source.suffix.lower() not in AUDIO_FORMATS):
            raise ValueError("The original editorial sound differs from its resolved asset")
        target = inputs / f"sound-{index}.bin"
        shutil.copyfile(source, target)
        if _sha256(target) != pin["checksum_sha256"]:
            raise ValueError("An editorial sound changed while compiling")


def _source_pins(ledger):
    pins = {}
    for event in ledger.events:
        if event.asset_json:
            asset = json.loads(event.asset_json)
            pins[asset["asset_id"]] = asset
    return pins


def _fade(elapsed, fade):
    if not fade["duration_ms"]:
        return 1.0
    x = np.clip(elapsed / fade["duration_ms"], 0.0, 1.0)
    easing = fade["easing"]
    if easing == "step":
        return x >= 1
    if easing == "ease_in":
        return x ** 2
    if easing == "ease_out":
        return 1 - (1 - x) ** 2
    if easing == "ease_in_out":
        return x * x * (3 - 2 * x)
    return x


def _envelope(event, policy, times):
    return (_fade(times - event.start_ms, policy["fade_in"])
            * _fade(event.end_ms - times, policy["fade_out"]))


def _read_region(track, region_start, region_end, offset, count):
    size = region_end - region_start
    if size <= 0 or region_end > len(track):
        raise ValueError("Editorial sound playback exceeds the decoded source")
    samples = np.empty((count, track.channels), dtype=np.float32)
    written = 0
    while written < count:
        position = (offset + written) % size
        length = min(count - written, size - position)
        track.seek(region_start + position)
        samples[written:written + length] = track.read(length, dtype="float32", always_2d=True)
        written += length
    return samples


def mix_master(inputs, work, plan, timeline, audio):
    if not any(action["verb"] in SOUND_VERBS for action in plan["actions"]):
        return audio
    ledger = derive_sound_ledger(timeline, plan)
    score = [(event, json.loads(event.action_json)) for event in ledger.events]
    if not any(event.state == "playing" for event, _ in score):
        return audio
    target = work / "audio" / "editorial.wav"
    with tempfile.TemporaryDirectory(dir=target.parent) as temporary, ExitStack() as stack:
        voice = stack.enter_context(sf.SoundFile(audio["final_wav"]))
        rate = voice.samplerate
        tracks = {}
        for index, (key, pin) in enumerate(_source_pins(ledger).items()):
            source = inputs / f"sound-{index}.bin"
            if source.stat().st_size != pin["byte_length"] or _sha256(source) != pin["checksum_sha256"]:
                raise ValueError("The frozen editorial sound failed its integrity check")
            decoded = Path(temporary) / f"{index}.wav"
            duration = decode_sound(source, destination=decoded, sample_rate=rate)
            if duration != pin["duration_ms"]:
                raise ValueError("The actual editorial sound duration differs from the resolved duration")
            tracks[key] = stack.enter_context(sf.SoundFile(decoded))
        channels = max(voice.channels, *(track.channels for track in tracks.values()))
        pending = Path(temporary) / "mix.wav"
        with sf.SoundFile(pending, "w", rate, channels, subtype="PCM_24") as output:
            for start in range(0, len(voice), 16384):
                narration = voice.read(16384, always_2d=True, dtype="float32")
                effects = np.zeros((len(narration), channels), dtype=np.float32)
                for event, action in score:
                    if event.state != "playing":
                        continue
                    start_frame = round(event.start_ms * rate / 1000)
                    left = max(start, start_frame)
                    right = min(start + len(narration), round(event.end_ms * rate / 1000))
                    if left >= right:
                        continue
                    policy = action["sound_policy"]
                    clip = policy["playback"]
                    track = tracks[action["asset_id"]]
                    region_start = round(clip["source_in_ms"] * rate / 1000)
                    region_end = min(round(clip["source_out_ms"] * rate / 1000), len(track))
                    samples = _read_region(track, region_start, region_end,
                        round(clip["offset_ms"] * rate / 1000) + left - start_frame, right - left)
                    times = np.arange(left, right) * (1000 / rate)
                    gain = np.ones(right - left) * (10 ** (event.gain_db / 20)) * _envelope(event, policy, times)
                    for quiet, quiet_action in score:
                        if quiet.state == "silent" and quiet.bus_id == event.bus_id:
                            overlap = (times >= quiet.start_ms) & (times < quiet.end_ms)
                            gain[overlap] *= 1 - _envelope(quiet, quiet_action["sound_policy"], times[overlap])
                    effects[left - start:right - start] += samples * gain[:, None]
                # Preserve the narration level; only the editorial bus uses spare peak headroom.
                output.write(narration + np.clip(effects, -1.0 - narration, 1.0 - narration))
        pending.replace(target)
    return {**audio, "final_wav": str(target), "sha256": _sha256(target)}
