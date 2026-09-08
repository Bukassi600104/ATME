from copy import deepcopy
import json

import pytest

from atme.agents.board_planner import compile_proposal, propose_boards
from atme.gateway.router import Ledger
from atme.planning_context import build_planning_context
from test_board_continuity import board_doc, renderer


def inputs():
    script = {"scenes": [{"scene_id": 1, "spoken_text": "Queue pointer"},
                          {"scene_id": 2, "spoken_text": "Evidence return"}]}
    words = [dict(word=word, scene_id=sid, start_ms=at, end_ms=at + 100, confidence=0.9)
             for word, sid, at in [("Queue", 1, 100), ("pointer", 1, 500),
                                  ("Evidence", 2, 2100), ("return", 2, 3500)]]
    context = build_planning_context(script, words, 6000, "a" * 64)
    proposal = {"activations": [
        {"board_id": "queue", "start_word_index": None, "reason": "Explain the queue"},
        {"board_id": "evidence", "start_word_index": 2, "reason": "Show evidence"},
        {"board_id": "queue", "start_word_index": 3, "reason": "Return to explanation"}],
        "assignments": [{"element_id": target, "board_id": board, "word_index": word}
                        for target, board, word in [("el-queue", "queue", 0),
                            ("el-pointer", "queue", 1), ("el-evidence", "evidence", 2)]]}
    return board_doc(), context, proposal


def test_word_anchored_proposal_compiles_and_returns_without_mutating_source():
    doc, context, proposal = inputs()
    original = deepcopy((doc, context, proposal))
    result = compile_proposal(doc, context, proposal)
    assert result["requires_review"] is True
    assert result["status"] == "proposed"
    candidate = result["layout"]
    assert [a["start_ms"] for a in candidate["board_timeline"]["activations"]] == [0, 2100, 3500]
    assert candidate["board_timeline"]["activations"][-1]["end_ms"] == 6000
    assert candidate["elements"][0]["x"] == doc["elements"][0]["x"]
    r = renderer(candidate)
    assert r.frame(1900).tobytes() == r.frame(4500).tobytes()
    assert (doc, context, proposal) == original


@pytest.mark.parametrize("problem", ["unknown_word", "cross_scene", "missing_object",
    "duplicate_object", "inactive_board", "reverse_cuts", "first_anchor", "uncertain"])
def test_invalid_proposals_fail_without_mutation(problem):
    doc, context, proposal = inputs()
    if problem == "unknown_word":
        proposal["assignments"][0]["word_index"] = 99
    elif problem == "cross_scene":
        proposal["assignments"][0]["word_index"] = 2
    elif problem == "missing_object":
        proposal["assignments"].pop()
    elif problem == "duplicate_object":
        proposal["assignments"].append(deepcopy(proposal["assignments"][0]))
    elif problem == "inactive_board":
        proposal["assignments"][0]["board_id"] = "evidence"
    elif problem == "reverse_cuts":
        proposal["activations"][2]["start_word_index"] = 1
    elif problem == "first_anchor":
        proposal["activations"][0]["start_word_index"] = 0
    else:
        context["scenes"][0]["words"][0]["confidence"] = 0.1
    before = deepcopy(doc)
    with pytest.raises(ValueError):
        compile_proposal(doc, context, proposal)
    assert doc == before


def test_provider_uses_existing_role_and_records_usage_without_applying():
    doc, context, proposal = inputs()
    ledger = Ledger()
    def complete(system, user):
        payload = json.loads(user)
        assert payload["context"]["timebase"] == "final_audio_ms"
        assert "never invent timestamps" in system
        return json.dumps(proposal)
    result = propose_boards(doc, context, complete, ledger)
    assert result["status"] == "proposed"
    assert ledger.entries[0].role == "layouter"
    assert len(ledger.entries) == 1


def test_unready_context_does_not_call_provider():
    doc, context, _ = inputs()
    context["status"] = "needs_review"
    def complete(*args):
        pytest.fail("must not spend on unready context")
    with pytest.raises(ValueError):
        propose_boards(doc, context, complete, Ledger())


def test_preserved_camera_cannot_exceed_recording():
    doc, context, proposal = inputs()
    doc["camera_plan"] = [{"cue_ms": 7000, "focus": {"x": 0, "y": 0, "w": 600, "h": 400}}]
    with pytest.raises(ValueError, match="camera"):
        compile_proposal(doc, context, proposal)
