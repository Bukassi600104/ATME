"""Final-recording evidence for a subsequent visual-planning pass.

This is timing evidence, not an inferred storyboard or an assertion of alignment
quality. Missing/uncertain scenes must be reviewed before automatic planning.
"""
import hashlib
import json
import math
from copy import deepcopy


def build_planning_context(script, words, duration_ms, audio_sha256,
                           semantic_authority="approved_external_script"):
    if type(duration_ms) is not int or duration_ms <= 0:
        raise ValueError("final audio duration must be a positive integer")
    if (not isinstance(audio_sha256, str) or len(audio_sha256) != 64
            or any(c not in "0123456789abcdef" for c in audio_sha256)):
        raise ValueError("final audio checksum required")
    scenes = script["scenes"]
    ids = [s["scene_id"] for s in scenes]
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("unique script scene IDs required")
    grouped = {sid: [] for sid in ids}
    issues = []
    previous_end = 0
    previous_scene = -1
    for index, word in enumerate(words):
        sid = word.get("scene_id")
        start, end = word.get("start_ms"), word.get("end_ms")
        if (sid not in grouped or type(start) is not int or type(end) is not int
                or not 0 <= start < end <= duration_ms
                or not isinstance(word.get("word"), str) or not word["word"].strip()):
            issues.append({"code": "invalid_word", "word_index": index})
            continue
        scene_index = ids.index(sid)
        if start < previous_end or scene_index < previous_scene:
            issues.append({"code": "nonmonotonic_alignment", "word_index": index})
        previous_end = max(previous_end, end)
        previous_scene = max(previous_scene, scene_index)
        confidence = word.get("confidence")
        valid_score = (type(confidence) in (int, float) and math.isfinite(confidence)
                       and 0 <= confidence <= 1)
        if not valid_score or confidence < 0.65 or word.get("flagged"):
            issues.append({"code": "uncertain_word", "word_index": index, "scene_id": sid})
        grouped[sid].append({"word_index": index, "word": word["word"],
                             "start_ms": start, "end_ms": end,
                             "confidence": confidence if valid_score else None,
                             "flagged": bool(word.get("flagged", False))})
    result = []
    for scene in scenes:
        observed = grouped[scene["scene_id"]]
        if not observed:
            issues.append({"code": "missing_scene_alignment", "scene_id": scene["scene_id"]})
        result.append({"scene_id": scene["scene_id"],
                       "narration": scene["spoken_text"],
                       "visual_directive": scene.get("visual_directive", ""),
                       "start_ms": min((w["start_ms"] for w in observed), default=None),
                       "end_ms": max((w["end_ms"] for w in observed), default=None),
                       "words": observed})
    return {"contract_version": "1", "timebase": "final_audio_ms",
            "semantic_authority": semantic_authority,
            "status": "needs_review" if issues else "ready",
            "audio_sha256": audio_sha256, "duration_ms": duration_ms,
            "script_sha256": hashlib.sha256(json.dumps(script, sort_keys=True,
                separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest(),
            "scenes": deepcopy(result), "issues": issues}
