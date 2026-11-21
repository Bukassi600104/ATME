import asyncio
import sys
from pathlib import Path

import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from atme import pipeline, project_timing
from atme.project_service import ProjectError, ProjectService
from atme.store.db import JobStore
from test_external_inputs import external_payload
from test_project_runner import wav_bytes
from test_project_timing import fake_polish, observed_words
from v2_fixtures import visual_plan_v2


def measured_plan(tmp_path, monkeypatch, *, extra_word=False):
    service = ProjectService(JobStore(tmp_path / "story.db"))
    pid = service.create("Revisit the queue", "LONG_FORM_16_9", "script+audio")["project_id"]
    script = external_payload()["script"]
    script["scenes"][1]["spoken_text"] = "Queue pointer."
    service.write(pid, "script", script, 0)
    service.approve_script(pid, 1, 1, True)
    upload = service.attach_wav(pid, wav_bytes(), 2)
    placed = service.edit_source_timeline(pid, "insert", {"media_id": upload["media"]["media_id"], "at_ms": 0}, 3, 0)
    rev = placed["project"]["revision"]
    words = observed_words()
    words[2]["word"], words[3]["word"] = "Queue", "pointer"
    if extra_word:
        words.insert(3, {**words[2], "word": "other", "start_ms": 1450, "end_ms": 1490})
    monkeypatch.setattr(pipeline, "polish_stage", fake_polish)
    monkeypatch.setattr(project_timing, "_acoustic_words", lambda *_: words)
    run = service.timing.prepare(pid, rev)
    context = service.visual_compilation_context(pid, rev)
    plan = visual_plan_v2(rev)
    plan.update(context["project"], narrative_authority=context["narrative_authority"])
    plan["actions"][0]["trigger"] = {"kind": "phrase", "phrase": "queue pointer", "occurrence": 2, "offset_ms": 25}
    plan["actions"][1]["trigger"] = {"kind": "word", "word": "pointer", "occurrence": 1}
    plan["actions"][2]["trigger"] = {"kind": "absolute", "at_ms": 3000}
    state = service.write(pid, "storyboard", plan, rev)
    return service, pid, state["revision"], plan, run["run_id"]


def test_mcp_compiles_second_spoken_occurrence_from_pre_storyboard_run(tmp_path, monkeypatch):
    service, pid, rev, plan, run_id = measured_plan(tmp_path, monkeypatch)
    db = service.store.db_path
    service.store.close()
    src = Path(__file__).resolve().parents[1] / "src"

    async def exercise():
        params = StdioServerParameters(command=sys.executable, args=["-m", "atme.mcp_server", "--database", str(db)],
                                      env={"PYTHONPATH": str(src)})
        async with Client(params, read_timeout_seconds=60) as client:
            args = {"project_id": pid, "expected_revision": rev, "timing_run_id": run_id}
            result = await client.call_tool("atme.compile_storyboard_speech", args)
            assert not result.is_error, result.content
            value = result.structured_content["result"]
            assert value["status"] == "ready" and not value["issues"]
            assert value["scope"] == "storyboard_speech" and value["non_speech_action_ids"] == ["action-3"]
            phrase, word = value["resolved"]
            assert (phrase["scene_id"], phrase["first_word_index"], phrase["last_word_index"]) == (2, 2, 3)
            assert phrase["instruction_id"] == plan["actions"][0]["source_instruction_id"]
            assert phrase["resolved_trigger"]["alignment_anchor_ms"] == 1100
            assert phrase["resolved_trigger"]["resolved_at_ms"] == 1125
            assert word["resolved_trigger"]["resolved_at_ms"] == 400
            again = await client.call_tool("atme.compile_storyboard_speech", args)
            assert again.structured_content["result"] == value

    asyncio.run(exercise())


@pytest.mark.parametrize(("trigger", "issue"), [
    ({"kind": "phrase", "phrase": "pointer queue"}, "speech_occurrence_missing"),
    ({"kind": "word", "word": "queue", "occurrence": 3}, "speech_occurrence_missing"),
    ({"kind": "word", "word": "que"}, "speech_occurrence_missing"),
    ({"kind": "word", "word": "queue", "minimum_confidence": 1}, "low_confidence"),
    ({"kind": "word", "word": "queue", "offset_ms": -101}, "speech_offset_out_of_bounds"),
    ({"kind": "word", "word": "C++"}, "unsupported_speech_text"),
])
def test_speech_repair_points_to_instruction(tmp_path, monkeypatch, trigger, issue):
    service, pid, rev, plan, run_id = measured_plan(tmp_path, monkeypatch)
    try:
        plan["actions"][0]["trigger"] = trigger
        plan["project_revision"] = rev
        state = service.write(pid, "storyboard", plan, rev)
        result = service.compile_storyboard_speech(pid, state["revision"], run_id)
        assert result["status"] == "needs_review"
        assert len(result["resolved"]) == len(result["issues"]) == 1
        problem = result["issues"][0]
        assert (problem["action_id"], problem["beat_id"], problem["instruction_id"], problem["code"]) == (
            "action-1", "beat-001", "instruction-1", issue)
    finally:
        service.store.close()


def test_missing_alignment_and_new_edit_cannot_supply_exact_speech(tmp_path, monkeypatch):
    service, pid, rev, plan, run_id = measured_plan(tmp_path, monkeypatch, extra_word=True)
    try:
        result = service.compile_storyboard_speech(pid, rev, run_id)
        assert not result["resolved"] and {i["code"] for i in result["issues"]} == {"incomplete_word_alignment"}
        timeline = service.source_timeline.get(pid)
        args = {"clip_id": timeline["document"]["clips"][0]["clip_id"], "start_ms": 50, "end_ms": 7000}
        edit = service.edit_source_timeline(pid, "trim", args, rev, timeline["timeline_revision"])
        rev = edit["project"]["revision"]
        ctx = service.visual_compilation_context(pid, rev)
        plan.update(ctx["project"], narrative_authority=ctx["narrative_authority"])
        state = service.write(pid, "storyboard", plan, rev)
        with pytest.raises(ProjectError) as caught:
            service.compile_storyboard_speech(pid, state["revision"], run_id)
        assert caught.value.code == "stale_timing"
    finally:
        service.store.close()
