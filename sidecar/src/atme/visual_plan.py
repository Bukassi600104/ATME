"""Deterministic semantic bridge from approved narration to renderable visual beats."""

from __future__ import annotations

import re


def _tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+(?:'[A-Za-z0-9]+)?", text)


def build_visual_plan(script: dict) -> dict:
    scenes = script["scenes"]
    used: set[str] = set()
    beats = []
    persistent: list[str] = []
    purpose_by_phase = {
        "hook": "conflict", "context": "sequence",
        "architecture": "causality", "conclusion": "emphasis",
    }
    for index, scene in enumerate(scenes, start=1):
        words = _tokens(scene["spoken_text"])
        trigger = ""
        for size in range(3, min(8, len(words)) + 1):
            candidate = " ".join(words[:size])
            if candidate.lower() not in used:
                trigger = candidate
                break
        trigger = trigger or " ".join(words[: min(8, len(words))])
        used.add(trigger.lower())
        directive = scene["visual_directive"].strip()
        action = directive.split()[0].lower() if directive else "draw"
        if action == "place":
            action = "reveal"
        if action == "label":
            action = "reveal"
        if action not in ("draw", "reveal", "connect", "highlight"):
            action = "draw"
        beat_id = "beat-%03d" % index
        beats.append({
            "beat_id": beat_id,
            "scene_id": int(scene["scene_id"]),
            "narration": scene["spoken_text"],
            "trigger_phrase": trigger,
            "purpose": purpose_by_phase.get(scene.get("phase"), "causality"),
            "assets": [directive],
            "actions": [action],
            "layout": "extend the persistent board near the preceding scene",
            "camera": {"action": "hold" if index == 1 else "reframe",
                       "subject": beat_id},
            "continuity": {"keep": list(persistent), "remove": []},
            "emphasis": trigger,
            "fallback": "draw a labeled box and connect it to the preceding idea",
        })
        persistent.append("el-scene-%d" % int(scene["scene_id"]))
    return {"contract_version": "1", "topic": script.get("topic", ""), "beats": beats}


def trigger_times(plan: dict, words: list[dict]) -> dict[int, int]:
    """Resolve each exact trigger phrase against aligned words; fall back to scene onset."""
    by_scene: dict[int, list[dict]] = {}
    for word in words:
        by_scene.setdefault(int(word.get("scene_id", 1)), []).append(word)
    resolved: dict[int, int] = {}
    for beat in plan["beats"]:
        sid = int(beat["scene_id"])
        scene_words = by_scene.get(sid, [])
        observed = [re.sub(r"[^a-z0-9']", "", w["word"].lower()) for w in scene_words]
        wanted = [w.lower() for w in _tokens(beat["trigger_phrase"])]
        at = scene_words[0]["start_ms"] if scene_words else 0
        for start in range(0, max(0, len(observed) - len(wanted) + 1)):
            if observed[start:start + len(wanted)] == wanted:
                at = scene_words[start]["start_ms"]
                break
        resolved[sid] = int(at)
    return resolved
