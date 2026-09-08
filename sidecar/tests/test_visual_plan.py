from __future__ import annotations

from atme.visual_plan import build_visual_plan, trigger_times


SCRIPT = {
    "topic": "Inference",
    "scenes": [
        {"scene_id": 1, "phase": "hook",
         "spoken_text": "Serving models creates a three way conflict for operators.",
         "visual_directive": "draw a triangle labeled throughput latency cost"},
        {"scene_id": 2, "phase": "architecture",
         "spoken_text": "Memory movement becomes the bottleneck during decoding.",
         "visual_directive": "connect memory to the accelerator"},
    ],
}


def test_plan_has_exact_narration_and_unique_triggers():
    plan = build_visual_plan(SCRIPT)
    assert len(plan["beats"]) == 2
    assert plan["beats"][0]["narration"] == SCRIPT["scenes"][0]["spoken_text"]
    assert len({beat["trigger_phrase"].lower() for beat in plan["beats"]}) == 2
    assert plan["beats"][1]["continuity"]["keep"] == ["el-scene-1"]


def test_trigger_times_resolve_against_aligned_words():
    plan = build_visual_plan(SCRIPT)
    words = []
    cursor = 0
    for scene in SCRIPT["scenes"]:
        for word in scene["spoken_text"].split():
            words.append({"word": word, "start_ms": cursor, "end_ms": cursor + 200,
                          "scene_id": scene["scene_id"]})
            cursor += 250
    times = trigger_times(plan, words)
    assert times[1] == 0
    assert times[2] > times[1]
