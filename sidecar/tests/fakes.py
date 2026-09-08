"""Scripted offline LLM fakes for agent tests (no network, no API spend)."""

from __future__ import annotations

import json


class ScriptedLLM:
    """Returns queued responses in order; records every (system, user) call for assertions."""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def __call__(self, system: str, user: str = "", **kwargs) -> str:  # user-first signature
        self.calls.append({"system": system, "user": user})
        if not self.responses:
            raise AssertionError("ScriptedLLM exhausted; unexpected call: %s" % user[:120])
        return self.responses.pop(0)


def j(obj) -> str:
    return json.dumps(obj)


FACT_SHEET_OK = {
    "topic": "Why inference is hard",
    "generated_at": "2026-01-01T00:00:00Z",
    "sources": [
        {"source_id": "src-a", "url": "https://a.example/x", "title": "Paper A",
         "retrieved_at": "2026-01-01T00:00:00Z", "excerpt": "measured 2.4x throughput"},
        {"source_id": "src-b", "url": "https://b.example/y", "title": "Docs B",
         "retrieved_at": "2026-01-01T00:00:00Z", "excerpt": "up to 2.4x higher throughput"},
        {"source_id": "src-c", "url": "https://c.example/z", "title": "Blog C",
         "retrieved_at": "2026-01-01T00:00:00Z", "excerpt": "memory wall dominates"},
    ],
    "claims": [
        {"claim_id": "clm-1", "text": "2.4x throughput via PagedAttention",
         "kind": "figure", "source_ids": ["src-a", "src-b"], "status": "unresolved"},
        {"claim_id": "clm-2", "text": "Memory wall dominates token latency",
         "kind": "fact", "source_ids": ["src-c"], "status": "unresolved"},
        {"claim_id": "clm-3", "text": "87% latency cut", "kind": "figure",
         "source_ids": ["src-c"], "status": "unresolved"},
    ],
}

VERIFIER_VERDICTS = {"verdicts": [
    {"claim_id": "clm-1", "status": "verified", "reason": "numerals match both sources"},
    {"claim_id": "clm-2", "status": "verified", "reason": "qualitative, source authoritative"},
    {"claim_id": "clm-3", "status": "dropped", "reason": "single weak source, numerals unverifiable"},
]}

SCENES_BAD = {
    "topic": "Why inference is hard",
    "scenes": [
        {"scene_id": 1, "phase": "hook",
         "spoken_text": "Let's dive in! Inference is a revolutionary trilemma of throughput, latency and cost.",
         "visual_directive": "Show the trilemma.", "est_seconds": 8, "claim_ids": []},
        {"scene_id": 2, "phase": "architecture",
         "spoken_text": "PagedAttention pages the KV cache like virtual memory for about 2.4x throughput.",
         "visual_directive": "Draw KV cache box with page rectangles.",
         "est_seconds": 12, "claim_ids": ["clm-1"]},
    ],
}

SCENES_GOOD = {
    "topic": "Why inference is hard",
    "scenes": [
        {"scene_id": 1, "phase": "hook",
         "spoken_text": "Serving large models is a fight on three fronts at once: throughput, latency, cost.",
         "visual_directive": "draw a triangle labeled Throughput, Latency, Cost",
         "est_seconds": 10, "claim_ids": []},
        {"scene_id": 2, "phase": "architecture",
         "spoken_text": "vLLM pages the KV cache like virtual memory and batches continuously for roughly 2.4x serving throughput.",
         "visual_directive": "draw stacked page rectangles inside a KV Cache box",
         "est_seconds": 14, "claim_ids": ["clm-1"]},
    ],
}

LAYOUT_OVERLAP = {
    "contract_version": "1", "seed": 7,
    "canvas": {"width": 1920, "height": 1080}, "grid": 50, "roughness": 1,
    "elements": [
        {"id": "el-a", "scene_id": 1, "appear_at_ms": 0, "type": "rectangle",
         "x": 300, "y": 300, "width": 500, "height": 150, "label": "A"},
        {"id": "el-b", "scene_id": 2, "appear_at_ms": 4000, "type": "rectangle",
         "x": 350, "y": 350, "width": 500, "height": 150, "label": "B"},
    ],
}
