"""Deterministic compilation of externally authored board proposals."""
from copy import deepcopy
import hashlib
import json
import re

from jsonschema import Draft202012Validator

from atme.board_edit import apply_board_edit
from atme.narration_events import phrase_matches, speech_tokens
from atme.render.camera import validate_camera_intent


SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["activations", "assignments"],
    "properties": {
        "activations": {"type": "array", "minItems": 1, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["board_id", "start_word_index", "reason"],
            "properties": {"board_id": {"type": "string", "minLength": 1},
                           "start_word_index": {"type": ["integer", "null"], "minimum": 0},
                           "reason": {"type": "string", "minLength": 1}}}},
        "assignments": {"type": "array", "minItems": 1, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["element_id", "board_id", "word_index"],
            "properties": {"element_id": {"type": "string", "minLength": 1},
                           "board_id": {"type": "string", "minLength": 1},
                           "word_index": {"type": "integer", "minimum": 0}}}},
    },
}


def _word_index(context):
    if (context.get("contract_version") != "1" or context.get("timebase") != "final_audio_ms"
            or context.get("status") != "ready" or context.get("issues")):
        raise ValueError("final-audio planning evidence needs review")
    indexed = {}
    previous_end = 0
    duration = context["duration_ms"]
    if type(duration) is not int or duration <= 0:
        raise ValueError("invalid final audio duration")
    for scene in context["scenes"]:
        if not scene["words"]:
            raise ValueError("missing scene evidence")
        for word in scene["words"]:
            index = word["word_index"]
            if (type(index) is not int or index != len(indexed)
                    or type(word["start_ms"]) is not int or type(word["end_ms"]) is not int
                    or not previous_end <= word["start_ms"] < word["end_ms"] <= duration
                    or type(word.get("confidence")) not in (int, float)
                    or not 0.65 <= word["confidence"] <= 1 or word.get("flagged")):
                raise ValueError("invalid or uncertain word evidence")
            indexed[index] = {**word, "scene_id": scene["scene_id"]}
            previous_end = word["end_ms"]
    if not indexed:
        raise ValueError("word evidence required")
    return indexed


def compile_storyboard_speech(plan, measured, timeline_duration_ms):
    """Compile speech triggers in narration order, keeping phrase boundaries within scenes."""
    from atme.store.contracts_v2 import ResolvedTrigger

    semantic = measured["semantic_structure"]
    context = semantic.get("planning_context")
    alignment = semantic.get("alignment_report", {})
    evidence_issue = None
    if not context:
        evidence_issue = "semantic_structure_required"
    elif (not alignment.get("accepted") or not alignment.get("matched_word_count")
          or alignment["matched_word_count"] != alignment["expected_word_count"]
          or alignment["matched_word_count"] != alignment["observed_word_count"]):
        # Reconciliation omits unmatched words. Counting occurrences in a shortened
        # sequence could fabricate adjacency or silently select a different occurrence.
        evidence_issue = "incomplete_word_alignment"
    else:
        try:
            _word_index(context)
        except ValueError:
            evidence_issue = "word_alignment_needs_review"

    beat_ids = {action_id: beat["beat_id"] for beat in plan["beats"] for action_id in beat["action_ids"]}
    matches_by_text = {}
    resolved, issues, non_speech = [], [], []
    for action in plan["actions"]:
        trigger = action["trigger"]
        if trigger["kind"] not in ("word", "phrase"):
            non_speech.append(action["action_id"])
            continue
        owner = {"beat_id": beat_ids[action["action_id"]], "action_id": action["action_id"],
                 "instruction_id": action["source_instruction_id"]}
        phrase = trigger[trigger["kind"]]
        occurrence = trigger.get("occurrence", 1)
        if evidence_issue:
            issues.append({**owner, "code": evidence_issue})
            continue
        # The acoustic reconciler currently indexes English words and contractions.
        if (not re.fullmatch(r"""[a-zA-Z0-9\s'’",.?!:;\-]+""", phrase)
                or not speech_tokens(phrase)
                or trigger["kind"] == "word" and len(speech_tokens(phrase)) != 1):
            issues.append({**owner, "code": "unsupported_speech_text", "requested": phrase})
            continue
        if phrase not in matches_by_text:
            matches_by_text[phrase] = [(scene["scene_id"], match) for scene in context["scenes"]
                                       for match in phrase_matches(scene["words"], phrase)]
        matches = matches_by_text[phrase]
        if occurrence > len(matches):
            issues.append({**owner, "code": "speech_occurrence_missing", "requested": phrase,
                           "occurrence": occurrence, "match_count": len(matches)})
            continue
        scene_id, match = matches[occurrence - 1]
        confidence = min(word["confidence"] for word in match)
        if confidence < trigger.get("minimum_confidence", 0.75):
            issues.append({**owner, "code": "low_confidence", "confidence": confidence})
            continue
        anchor = match[0]["start_ms"]
        at = anchor + trigger.get("offset_ms", 0)
        if not 0 <= at < min(context["duration_ms"], timeline_duration_ms):
            issues.append({**owner, "code": "speech_offset_out_of_bounds", "at_ms": at})
            continue
        result = ResolvedTrigger(source=trigger, alignment_anchor_ms=anchor, resolved_at_ms=at,
                                 matched_text=phrase, matched_occurrence=occurrence,
                                 confidence=confidence, exact=True)
        resolved.append({**owner, "scene_id": scene_id, "first_word_index": match[0]["word_index"],
                         "last_word_index": match[-1]["word_index"], "resolved_trigger": result.model_dump()})
    return {"scope": "storyboard_speech", "status": "needs_review" if issues else "ready",
            "resolved": resolved, "issues": issues, "non_speech_action_ids": non_speech}


def compile_proposal(doc, context, proposal):
    """Compile referenced words into exact intervals; reject, never clamp or guess."""
    words = _word_index(context)
    Draft202012Validator(SCHEMA).validate(proposal)
    rows = proposal["activations"]
    starts = []
    for index, row in enumerate(rows):
        anchor = row["start_word_index"]
        if index == 0:
            if anchor is not None:
                raise ValueError("first board must begin at audio zero with null anchor")
            starts.append(0)
        else:
            if anchor not in words or anchor is None:
                raise ValueError("unknown board word anchor")
            starts.append(words[anchor]["start_ms"])
            if starts[-1] <= starts[-2]:
                raise ValueError("board anchors must increase strictly")
    timeline = {"version": "1", "boards": [{"board_id": b} for b in
                dict.fromkeys(r["board_id"] for r in rows)],
                "activations": [{"activation_id": f"planned-{i + 1}",
                    "board_id": row["board_id"], "start_ms": starts[i],
                    "end_ms": starts[i + 1] if i + 1 < len(starts) else context["duration_ms"]}
                    for i, row in enumerate(rows)]}
    elements = {e["id"]: e for e in doc["elements"]}
    assignments = {}
    for row in proposal["assignments"]:
        target, anchor = row["element_id"], row["word_index"]
        if target not in elements or target in assignments or anchor not in words:
            raise ValueError("unknown or duplicate element/word assignment")
        if elements[target]["scene_id"] != words[anchor]["scene_id"]:
            raise ValueError("object word anchor must belong to its narration scene")
        assignments[target] = {"board_id": row["board_id"],
                               "appear_at_ms": words[anchor]["start_ms"],
                               "narration_trigger": None}
    candidate = apply_board_edit(doc, timeline, assignments, context["duration_ms"])
    camera = candidate.get("camera_plan", [])
    validate_camera_intent(camera)
    if any(c["cue_ms"] + c.get("transition_ms", 0) > context["duration_ms"] for c in camera):
        raise ValueError("preserved camera schedule exceeds final audio; revise camera first")
    return {"status": "proposed", "requires_review": True,
            "source_layout_sha256": hashlib.sha256(json.dumps(doc, sort_keys=True,
                separators=(",", ":")).encode()).hexdigest(),
            "audio_sha256": context["audio_sha256"], "script_sha256": context["script_sha256"],
            "context_sha256": hashlib.sha256(json.dumps(context, sort_keys=True,
                separators=(",", ":"), allow_nan=False).encode()).hexdigest(),
            "proposal": deepcopy(proposal), "layout": candidate}
