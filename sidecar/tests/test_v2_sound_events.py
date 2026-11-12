"""Finite sound score proof, independent of audio or native paint."""
from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest
from atme.render.v2_sound_events import derive_sound_ledger
from atme.store.contracts_v2 import ResolvedVisualTimelineV2, SoundAction
from v2_fixtures import common_action, resolved_timeline_v2


def sound(action_id, verb, start, end, *, state=None, expected="stopped", post="stopped",
          bus="score", offset=0, repeats=2, fade=0):
    silence = verb == "purposeful_silence"
    cue = verb == "sound_cue"
    action = {**common_action(action_id, "instruction-1"), "verb": verb,
        "trigger": {"kind": "absolute", "at_ms": start}, "easing": "linear",
        "asset_id": None if silence else "audio", "gain_db": 0,
        "coverage_id": "coverage-1", "fallback": {"fallback_id": "fallback-1", "on_failure": "block"},
        "state": state or ("silent" if silence else "playing"),
        "expected_state": "clear" if silence else expected, "post_state": "clear" if silence else post,
        "sound_policy": {"version": "1.0.0", "bus_id": bus,
            "bus_role": "effect" if cue else "music", "narration_priority": "preserve_narration",
            "fade_in": {"duration_ms": fade, "easing": "linear"},
            "fade_out": {"duration_ms": fade, "easing": "linear"}}}
    if not silence and action["state"] != "stopped":
        action["sound_policy"]["playback"] = {"source_in_ms": 100, "source_out_ms": 1100,
            "repeat_count": 1 if cue else repeats, "offset_ms": offset}
    return {"action": action, "start_ms": start, "end_ms": end,
        "resolved_trigger": {"source": action["trigger"], "alignment_anchor_ms": start,
            "resolved_at_ms": start, "confidence": 1, "exact": True}}


def score(rows):
    doc = resolved_timeline_v2()
    doc["actions"] = rows
    doc["evidence_treatments"] = []
    doc["coverage"] = [doc["coverage"][0]]
    doc["coverage"][0]["action_ids"] = [row["action"]["action_id"] for row in rows]
    doc["fallbacks"] = [doc["fallbacks"][0]]
    doc["resolved_assets"] = [{"asset_id": "audio", "revision": 1,
        "managed_ref": "atme://projects/1/assets/audio", "checksum_sha256": "a" * 64,
        "provenance_verified": True, "kind": "audio", "media_type": "audio/wav",
        "byte_length": 100, "duration_ms": 1200}]
    ResolvedVisualTimelineV2.model_validate(doc)
    return doc


def test_literal_score_is_immutable_and_exact():
    doc = score([sound("cue", "sound_cue", 0, 1000, bus="hit"),
        sound("music", "music_state", 0, 2000),
        sound("quiet", "purposeful_silence", 500, 1000)])
    before = deepcopy(doc)
    ledger = derive_sound_ledger(doc)
    assert [(e.action_id, e.start_ms, e.end_ms, e.bus_role, e.bus_id, e.state,
             e.expected_state, e.post_state) for e in ledger.events] == [
        ("cue", 0, 1000, "effect", "hit", "playing", "stopped", "stopped"),
        ("music", 0, 2000, "music", "score", "playing", "stopped", "stopped"),
        ("quiet", 500, 1000, "music", "score", "silent", "clear", "clear")]
    assert ledger.events[0].asset_json == '{"asset_id":"audio","byte_length":100,"checksum_sha256":"' + "a"*64 + '","duration_ms":1200,"kind":"audio","managed_ref":"atme://projects/1/assets/audio","media_type":"audio/wav","provenance_verified":true,"revision":1}'
    assert ledger.events[0].narration_priority_control == "preserve_narration"
    assert ledger == derive_sound_ledger(doc)
    with pytest.raises(FrozenInstanceError):
        ledger.events[0].state = "stopped"
    assert doc == before


def test_wrap_pause_resume_exhaustion_and_random_queries():
    doc = score([sound("play", "music_state", 0, 1200, post="playing"),
        sound("pause", "music_state", 1200, 1500, state="paused", expected="playing",
              post="paused", offset=1200),
        sound("resume", "music_state", 1500, 2300, expected="paused", offset=1200)])
    ledger = derive_sound_ledger(doc)
    expected = {0: ("playing", 0, 100), 999: ("playing", 999, 1099),
        1000: ("playing", 1000, 100), 1200: ("paused", 1200, 300),
        1499: ("paused", 1200, 300), 1500: ("playing", 1200, 300),
        2299: ("playing", 1999, 1099)}
    for at in [1500, 0, 2299, 999, 1200, 1000, 1499, 0]:
        row, = ledger.sample(at)
        assert (row.state, row.offset_ms, row.source_position_ms) == expected[at]
    assert ledger.sample(-1) == ledger.sample(2300) == ledger.sample(10000) == ()


def test_legacy_shape_and_incomplete_execution():
    action = sound("cue", "sound_cue", 0, 500)["action"]
    action.pop("sound_policy")
    assert "sound_policy" not in SoundAction.model_validate(action).model_dump(mode="json")
    action["sound_policy"] = None
    assert "sound_policy" not in SoundAction.model_validate(action).model_dump(mode="json")
    with pytest.raises(ValueError, match="policy"):
        derive_sound_ledger(score([{**sound("cue", "sound_cue", 0, 500), "action": action}]))

@pytest.fixture(autouse=True)
def no_media_execution(monkeypatch):
    import socket
    import subprocess

    import resvg_py
    from PIL import Image, ImageFont

    def forbidden(*args, **kwargs):
        pytest.fail("sound event proof cannot render, allocate images, decode audio or use network/processes")
    for obj, name in ((socket, "create_connection"), (subprocess, "Popen"),
                      (resvg_py, "svg_to_bytes"), (Image, "new"), (ImageFont, "truetype")):
        monkeypatch.setattr(obj, name, forbidden)
    import soundfile
    monkeypatch.setattr(soundfile, "read", forbidden)
    monkeypatch.setattr(soundfile, "SoundFile", forbidden)


@pytest.mark.parametrize("case", [
    "cue_post", "cue_repeat", "cursor", "sequence_range", "sequence_repeat", "asset", "exhaustion",
    "pause_initial", "pause_advance", "stopped_playback", "gap_persistence", "post_without_consumer",
    "same_bus_overlap", "duplicate", "silence_overlap", "role_drift", "narration", "wildcard",
    "unknown_role", "missing_gain", "missing_fade", "fade_duration", "outer_easing", "silence_gain",
    "silence_asset", "silence_playback", "infinite", "unknown_state", "extra", "wrong_kind", "source_duration",
])
def test_refused_controls(case):
    rows = [sound("a", "music_state", 0, 500, post="playing"),
            sound("b", "music_state", 500, 1000, expected="playing", offset=500)]
    doc = score(rows)
    action, next_action = (row["action"] for row in doc["actions"])
    policy = action["sound_policy"]
    if case == "cue_post":
        action.update(verb="sound_cue", post_state="playing")
        policy["bus_role"] = "effect"
        policy["playback"]["repeat_count"] = 1
    elif case == "cue_repeat":
        doc = score([sound("a", "sound_cue", 0, 500)])
        doc["actions"][0]["action"]["sound_policy"]["playback"]["repeat_count"] = 2
    elif case == "cursor":
        next_action["sound_policy"]["playback"]["offset_ms"] = 501
    elif case in {"sequence_range", "sequence_repeat"}:
        key = "source_in_ms" if case == "sequence_range" else "repeat_count"
        next_action["sound_policy"]["playback"][key] += 1
    elif case == "asset":
        next_action["asset_id"] = "different"
    elif case == "exhaustion":
        policy["playback"]["offset_ms"] = 1800
    elif case == "pause_initial":
        action["state"] = "paused"
    elif case == "pause_advance":
        next_action["state"] = "paused"
        next_action["sound_policy"]["playback"]["offset_ms"] = 501
    elif case == "stopped_playback":
        action["state"] = "stopped"
    elif case == "gap_persistence":
        doc["actions"][1]["start_ms"] = 501
    elif case == "post_without_consumer":
        doc["actions"] = doc["actions"][:1]
        doc["coverage"][0]["action_ids"] = ["a"]
    elif case in {"same_bus_overlap", "duplicate"}:
        doc["actions"][1]["start_ms"] = 0
        next_action["trigger"]["at_ms"] = 0
        doc["actions"][1]["resolved_trigger"].update(source=next_action["trigger"], alignment_anchor_ms=0, resolved_at_ms=0)
    elif case == "silence_overlap":
        doc = score([sound("a", "purposeful_silence", 0, 700), sound("b", "purposeful_silence", 500, 1000)])
    elif case == "role_drift":
        doc = score([sound("a", "sound_cue", 0, 500), sound("b", "purposeful_silence", 500, 1000)])
    elif case in {"narration", "wildcard"}:
        policy["bus_id"] = "narration" if case == "narration" else "*"
    elif case == "unknown_role":
        policy["bus_role"] = "narration"
    elif case == "missing_gain":
        action.pop("gain_db")
    elif case == "missing_fade":
        policy.pop("fade_in")
    elif case == "fade_duration":
        policy["fade_in"]["duration_ms"] = 501
    elif case == "outer_easing":
        action["easing"] = "ease_out"
    elif case.startswith("silence_"):
        doc = score([sound("a", "purposeful_silence", 0, 1000)])
        action = doc["actions"][0]["action"]
        if case == "silence_gain":
            action["gain_db"] = -1
        elif case == "silence_asset":
            action["asset_id"] = "audio"
        else:
            action["sound_policy"]["playback"] = policy["playback"]
    elif case == "infinite":
        policy["playback"]["repeat_count"] = -1
    elif case == "unknown_state":
        action["state"] = "resume"
    elif case == "extra":
        policy["audible_priority_passed"] = True
    elif case == "wrong_kind":
        doc["resolved_assets"][0]["kind"] = "image"
    elif case == "source_duration":
        policy["playback"]["source_out_ms"] = 1201
    with pytest.raises(ValueError):
        derive_sound_ledger(doc)


def test_envelopes_silence_transport_and_boundaries():
    music = sound("music", "music_state", 100, 1100, fade=200)
    music["action"]["gain_db"] = -20
    quiet = sound("quiet", "purposeful_silence", 300, 900, fade=100)
    ledger = derive_sound_ledger(score([music, quiet]))
    expected = {99: (), 100: (("music", 0, 0.0, 1.0),),
        200: (("music", 100, 0.05, 1.0),),
        300: (("music", 200, 0.1, 1.0), ("quiet", None, 0.0, 1.0)),
        350: (("music", 250, 0.05, 0.5), ("quiet", None, 0.0, 0.5)),
        500: (("music", 400, 0.0, 0.0), ("quiet", None, 0.0, 0.0)),
        850: (("music", 750, 0.05, 0.5), ("quiet", None, 0.0, 0.5)),
        900: (("music", 800, 0.1, 1.0),), 1000: (("music", 900, 0.05, 1.0),), 1100: ()}
    for at in (1100, 350, 99, 100, 500, 200, 300, 850, 900, 1000, 500):
        actual = ledger.sample(at)
        assert len(actual) == len(expected[at])
        for row, (key, offset, amplitude, attenuation) in zip(actual, expected[at], strict=True):
            assert (row.action_id, row.offset_ms) == (key, offset)
            assert row.amplitude == pytest.approx(amplitude)
            assert row.attenuation == pytest.approx(attenuation)


def test_adjacent_stopped_clears_and_gap_restarts_new_sequence():
    rows = [sound("play", "music_state", 0, 500),
        sound("stop", "music_state", 500, 700, state="stopped"),
        sound("restart", "music_state", 900, 1200, offset=100)]
    ledger = derive_sound_ledger(score(rows))
    assert ledger.sample(499)[0].offset_ms == 499
    assert ledger.sample(500)[0].state == "stopped"
    assert ledger.sample(699)[0].offset_ms is None
    assert ledger.sample(700) == ledger.sample(899) == ()
    assert ledger.sample(900)[0].offset_ms == 100
    assert ledger.sample(1200) == ()
    doc = score(rows)
    doc["actions"][1]["action"]["expected_state"] = "playing"
    with pytest.raises(ValueError, match="preceding boundary"):
        derive_sound_ledger(doc)


@pytest.mark.parametrize("field,value", [("source_in_ms", True), ("repeat_count", 1.5),
    ("offset_ms", -1), ("offset_ms", 2000), ("source_out_ms", 100), ("repeat_count", 0)])
def test_finite_playback_trust_boundary(field, value):
    doc = score([sound("music", "music_state", 0, 500)])
    doc["actions"][0]["action"]["sound_policy"]["playback"][field] = value
    with pytest.raises(ValueError):
        derive_sound_ledger(doc)


def test_full_frame_history_remains_identical_with_editorial_score():
    from atme.render.v2_state import evaluate_frame
    from test_v2_frame_state import supported_documents
    from v2_fixtures import digest

    layout, timeline = supported_documents()
    before = deepcopy((layout, timeline))
    expected = {at: evaluate_frame(layout, timeline, at) for at in (0, 450, 2200, 4900, 9999)}
    cue = sound("sound", "sound_cue", 500, 1000, bus="fx")
    cue["action"]["coverage_id"] = "coverage-1"
    timeline["actions"].append(cue)
    timeline["actions"].sort(key=lambda row: row["start_ms"])
    timeline["coverage"][0]["action_ids"].append("sound")
    timeline["resolved_assets"].append(score([sound("unused", "sound_cue", 0, 1)])["resolved_assets"][0])
    timeline["layout_sha256"] = digest(layout)
    sound_inputs = deepcopy((layout, timeline))
    for at in (9999, 450, 4900, 0, 2200, 450):
        assert evaluate_frame(layout, timeline, at) == expected[at]
    assert (layout, timeline) == sound_inputs
    assert layout == before[0]


def authored_documents():
    from v2_fixtures import executable_layout_v2, visual_plan_v2
    plan = visual_plan_v2()
    layout = executable_layout_v2(plan)
    timeline = resolved_timeline_v2(plan, layout)
    row = sound("music", "music_state", 0, 500)
    plan["actions"].append(deepcopy(row["action"]))
    plan["beats"][0]["action_ids"].append("music")
    plan["coverage"][0]["action_ids"].append("music")
    asset = deepcopy(plan["assets"][0])
    asset.update(asset_id="audio", kind="audio", managed_ref="atme://projects/1/assets/audio",
                 checksum_sha256="a" * 64, duration_ms=1200)
    plan["assets"].append(asset)
    timeline["actions"].append(row)
    timeline["actions"].sort(key=lambda item: item["start_ms"])
    timeline["coverage"] = deepcopy(plan["coverage"])
    timeline["resolved_assets"].append(score([row])["resolved_assets"][0])
    return plan, timeline


def test_exact_authored_inventory_and_asset_authority():
    import json
    from dataclasses import asdict
    plan, timeline = authored_documents()
    before = deepcopy((plan, timeline))
    ledger = derive_sound_ledger(timeline, plan)
    event, = ledger.events
    assert (event.source_instruction_id, event.board_id, event.coverage_id, event.gain_db) == (
        "instruction-1", "board-main", "coverage-1", 0)
    assert json.loads(event.resolved_trigger_json) == {
        "source": {"kind": "absolute", "at_ms": 0}, "alignment_anchor_ms": 0,
        "matched_text": None, "matched_occurrence": None, "resolved_at_ms": 0,
        "confidence": 1.0, "exact": True}
    assert json.loads(event.authority_json) == {key: timeline[key] for key in (
        "timeline_id", "project_id", "project_revision", "plan_id", "plan_revision", "plan_sha256",
        "layout_id", "layout_revision", "layout_sha256", "cleaned_timeline_revision",
        "cleaned_timeline_fingerprint", "compilation_fingerprint")}
    assert json.dumps(asdict(ledger), sort_keys=True) == json.dumps(asdict(derive_sound_ledger(timeline, plan)), sort_keys=True)
    assert (plan, timeline) == before
    for field, value in (("revision", 2), ("duration_ms", 1199), ("managed_ref", "atme://projects/2/assets/audio")):
        wrong = deepcopy(plan)
        wrong["assets"][-1][field] = value
        with pytest.raises(ValueError, match="pins differ"):
            derive_sound_ledger(timeline, wrong)
    wrong = deepcopy(timeline)
    wrong["actions"] = [row for row in wrong["actions"] if row["action"]["action_id"] != "music"]
    wrong["coverage"][0]["action_ids"].remove("music")
    with pytest.raises(ValueError, match="inventory"):
        derive_sound_ledger(wrong, plan)


@pytest.mark.parametrize("easing,at,amplitude", [
    ("linear", 50, 0.5), ("ease_in", 50, 0.25), ("ease_out", 50, 0.75),
    ("ease_in_out", 25, 0.15625), ("step", 50, 0.0), ("step", 100, 1.0),
])
def test_authored_existing_easing_curves(easing, at, amplitude):
    row = sound("cue", "sound_cue", 0, 500, fade=100)
    row["action"]["sound_policy"]["fade_in"]["easing"] = easing
    assert derive_sound_ledger(score([row])).sample(at)[0].amplitude == amplitude


def test_separate_effect_buses_overlap_and_adjacent_silence_restores_exactly():
    rows = [sound("first", "sound_cue", 0, 500, bus="first"),
        sound("second", "sound_cue", 0, 500, bus="second"),
        sound("mute1", "purposeful_silence", 0, 250, bus="first"),
        sound("mute2", "purposeful_silence", 250, 400, bus="first")]
    for row in rows[2:]:
        row["action"]["sound_policy"]["bus_role"] = "effect"
    ledger = derive_sound_ledger(score(rows))
    assert [row.action_id for row in ledger.sample(250)] == ["first", "second", "mute2"]
    assert [row.amplitude for row in ledger.sample(250)] == [0, 1, 0]
    assert [row.amplitude for row in ledger.sample(400)] == [1, 1]
    assert ledger.sample(500) == ()


def test_return_prefix_uses_complete_sound_continuity_without_future_visual_execution():
    from atme.render.v2_state import validate_resolved_return_history
    from atme.render.v2_timeline_replay import ReplayError, _validate_operators
    from atme.store.contracts_v2 import ExecutableLayoutV2
    from test_v2_return_hierarchy import return_receipt_documents
    from v2_fixtures import digest

    layout, timeline = return_receipt_documents()
    returned = next(row for row in timeline["actions"] if row["action"]["verb"] == "return_board")
    start = returned["start_ms"]
    rows = [sound("play", "music_state", 0, start, post="playing", repeats=10),
        sound("continue", "music_state", start, start + 1000, expected="playing", offset=start, repeats=10)]
    timeline["actions"].extend(rows)
    timeline["actions"].sort(key=lambda row: row["start_ms"])
    timeline["coverage"][0]["action_ids"].extend(["play", "continue"])
    timeline["resolved_assets"].append(score([rows[0]])["resolved_assets"][0])
    parsed = ResolvedVisualTimelineV2.model_validate(timeline)
    before = deepcopy(timeline)
    validate_resolved_return_history(ExecutableLayoutV2.model_validate(layout), parsed, layout_sha256=digest(layout))
    assert timeline == before
    # A complete early score does not turn a future legacy control into execution support.
    legacy = sound("future", "purposeful_silence", start + 1500, start + 1600)
    legacy["action"].pop("sound_policy")
    timeline["actions"].append(legacy)
    timeline["coverage"][0]["action_ids"].append("future")
    mixed = ResolvedVisualTimelineV2.model_validate(timeline)
    validate_resolved_return_history(ExecutableLayoutV2.model_validate(layout), mixed, layout_sha256=digest(layout))
    with pytest.raises(ValueError, match="policy"):
        derive_sound_ledger(mixed)
    from atme.render.v2_state import UnsupportedVisualAction, evaluate_frame
    with pytest.raises(UnsupportedVisualAction, match="no frame implementation"):
        evaluate_frame(layout, timeline, 0)
    first = next(row for row in parsed.actions if row.action.action_id == "play")
    with pytest.raises(ReplayError, match="complete score"):
        _validate_operators((first,), sound_actions=())
    with pytest.raises(ReplayError, match="cursor consumer"):
        _validate_operators((first,))


@pytest.mark.parametrize("schema_name", ["visual-plan-v2", "resolved-visual-timeline-v2"])
@pytest.mark.parametrize("case,accepted", [
    ("cue", True), ("music", True), ("silence", True), ("legacy", True), ("null_legacy", True),
    ("missing_gain", False), ("missing_easing", False), ("unknown_state", False),
    ("wrong_role", False), ("cue_post", False), ("cue_repeats", False), ("silence_gain", False),
])
def test_action_bearing_schemas_match_local_policy_model(schema_name, case, accepted):
    from conftest import load_schema
    from jsonschema import Draft202012Validator

    verb = "purposeful_silence" if case in {"silence", "silence_gain"} else (
        "music_state" if case == "music" else "sound_cue")
    action = sound("sound", verb, 0, 500)["action"]
    if case in {"legacy", "null_legacy"}:
        action.pop("sound_policy")
        action.pop("gain_db")
        action.pop("easing")
        action.update(state="legacy arbitrary sound state", expected_state=None, post_state="legacy completion")
        if case == "null_legacy":
            action["sound_policy"] = None
    elif case == "missing_gain":
        action.pop("gain_db")
    elif case == "missing_easing":
        action.pop("easing")
    elif case == "unknown_state":
        action["state"] = "resume"
    elif case == "wrong_role":
        action["sound_policy"]["bus_role"] = "music"
    elif case == "cue_post":
        action["post_state"] = "playing"
    elif case == "cue_repeats":
        action["sound_policy"]["playback"]["repeat_count"] = 2
    elif case == "silence_gain":
        action["gain_db"] = 1
    schema = load_schema(schema_name)
    validator = Draft202012Validator({**schema["$defs"]["SoundAction"], "$defs": schema["$defs"]})
    assert validator.is_valid(action) is accepted
    if accepted:
        SoundAction.model_validate(action)
    else:
        with pytest.raises(ValueError):
            SoundAction.model_validate(action)
