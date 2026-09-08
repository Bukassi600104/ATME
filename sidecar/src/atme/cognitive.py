"""Cognitive stage: topic -> fact sheet -> script -> layout, with pluggable LLM backend.

Providers:
  - "fake": deterministic scripted responses (offline tests / demo mode). Produces a small but
    CONTRACT-VALID fact sheet and scenes so the entire downstream pipeline runs without keys.
  - "litellm": real web-grounded research etc.; requires provider config JSON
    ({"researcher": {"model": "..."}, ...}) - wired in M3 Settings.

Everything lands as job artifacts: fact_sheet.json, script.json, layout.json (+ ledger summary).
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from atme.agents.research import research
from atme.agents.scriptwriter import compose as write_script
from atme.gateway.router import CompleteFn, Ledger

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- fake provider
class FakeCognitiveProvider:
    """Deterministic offline provider satisfying all four roles."""

    def __init__(self):
        self._expand = json.dumps({"queries": [
            "paged attention throughput numbers",
            "kv cache memory wall analysis",
            "vllm criticism and limits"]})
        self._retrieve = {
            "generated_at": "2026-01-01T00:00:00Z",
            "research_model": "fake/grounded",
            "sources": [
                {"source_id": "src-fake-a", "url": "https://example.org/paper",
                 "title": "PagedAttention paper", "publisher": "Example UC",
                 "retrieved_at": "2026-01-01T00:00:00Z",
                 "excerpt": "measured 2.4x throughput versus naive KV cache management"},
                {"source_id": "src-fake-b", "url": "https://example.net/docs",
                 "title": "vLLM design docs", "publisher": "vLLM project",
                 "retrieved_at": "2026-01-01T00:00:00Z",
                 "excerpt": "continuous batching yields up to 2.4x higher serving throughput"},
                {"source_id": "src-fake-c", "url": "https://example.org/wall",
                 "title": "The memory wall", "publisher": "Example blog",
                 "retrieved_at": "2026-01-01T00:00:00Z",
                 "excerpt": "data movement between HBM and compute dominates token latency"},
            ],
            "claims": [
                {"claim_id": "clm-paged", "text": "PagedAttention delivers about 2.4x serving throughput",
                 "kind": "figure", "source_ids": ["src-fake-a", "src-fake-b"], "status": "unresolved"},
                {"claim_id": "clm-wall", "text": "Data movement, not FLOPs, dominates token latency at batch",
                 "kind": "fact", "source_ids": ["src-fake-c"], "status": "unresolved"},
            ],
        }
        self._verdicts = {"verdicts": [
            {"claim_id": "clm-paged", "status": "verified", "reason": "numerals match"},
            {"claim_id": "clm-wall", "status": "verified", "reason": "authoritative qualitative"}]}

    def researcher(self, system: str, user: str) -> str:
        if "propose" in user.lower():
            return self._expand
        if "search angles" in user.lower():
            import json as _j
            return _j.dumps(self._retrieve)
        raise AssertionError("unexpected researcher prompt: %s" % user[:120])

    def reasoner(self, system: str, user: str) -> str:
        import json as _j
        return _j.dumps(self._verdicts)

    def writer(self, system: str, user: str) -> str:
        import json as _j
        topic = "Why inference is hard"
        return _j.dumps({
            "topic": topic, "title": "Why Inference Is Hard", "target_seconds": 30,
            "scenes": [
                {"scene_id": 1, "phase": "hook",
                 "spoken_text": "Serving large models is a fight on three fronts: throughput, latency, cost.",
                 "visual_directive": "draw a triangle labeled Throughput, Latency, Cost",
                 "est_seconds": 9, "claim_ids": []},
                {"scene_id": 2, "phase": "architecture",
                 "spoken_text": "vLLM pages the KV cache like virtual memory and batches continuously for roughly 2.4x serving throughput.",
                 "visual_directive": "draw stacked page rectangles inside a box labeled KV Cache and connect it to an arrow labeled continuous batching",
                 "est_seconds": 13, "claim_ids": ["clm-paged"]}],
        })

    def layouter(self, system: str, user: str) -> str:
        raise AssertionError("spatial agent uses its own fake in tests; autolayout covers CLI")


def _completes(completes: dict[str, CompleteFn] | None) -> dict[str, CompleteFn]:
    if completes is not None:
        return completes
    fake = FakeCognitiveProvider()
    log.info("cognitive: using FAKE provider (tests only)")
    return {"researcher": fake.researcher, "reasoner": fake.reasoner,
            "writer": fake.writer}


def research_stage(topic: str, job_dir: Path,
                   completes: dict[str, CompleteFn] | None = None,
                   max_research_rounds: int | None = None) -> dict:
    """Research and adversarially verify claims, then persist the fact sheet."""
    job_dir = Path(job_dir)
    job_dir.mkdir(parents=True, exist_ok=True)
    resolved = _completes(completes)
    ledger = Ledger()
    rounds = max_research_rounds or (1 if resolved.get("_offline") else 5)
    fact_sheet = research(topic, resolved["researcher"], resolved["reasoner"],
                          max_rounds=max(1, rounds), ledger=ledger)
    fact_sheet["claims"] = [
        claim for claim in fact_sheet["claims"]
        if claim["status"] == "verified" or claim["kind"] != "figure"]
    public_sheet = {key: value for key, value in fact_sheet.items() if key != "_ledger"}
    (job_dir / "fact_sheet.json").write_text(
        json.dumps(public_sheet, indent=2, default=str), encoding="utf-8")
    return {"fact_sheet": public_sheet, "ledger_entries": list(ledger.entries)}


def script_stage(fact_sheet: dict, target_seconds: int, job_dir: Path,
                 completes: dict[str, CompleteFn] | None = None) -> dict:
    """Write and lint narration strictly from verified research."""
    job_dir = Path(job_dir)
    resolved = _completes(completes)
    ledger = Ledger()
    surviving = [claim for claim in fact_sheet["claims"]
                 if claim["status"] == "verified"]
    script_doc, review_flags = write_script(
        {**fact_sheet, "claims": surviving}, target_seconds, resolved["writer"], ledger)
    (job_dir / "script.json").write_text(
        json.dumps(script_doc, indent=2, default=str), encoding="utf-8")
    (job_dir / "review_flags.json").write_text(
        json.dumps({"flags": review_flags}, indent=2), encoding="utf-8")
    return {"script_doc": script_doc, "review_flags": review_flags,
            "ledger_entries": list(ledger.entries)}


def layout_stage(script_doc: dict, job_dir: Path,
                 completes: dict[str, CompleteFn] | None = None) -> dict:
    """Generate a collision-repaired diagram and camera plan for the approved script."""
    from atme.agents.spatial import layout as spatial_layout
    from atme.render.autolayout import build_layout
    from atme.visual_plan import build_visual_plan

    job_dir = Path(job_dir)
    resolved = _completes(completes)
    ledger = Ledger()
    visual_plan = build_visual_plan(script_doc)
    (job_dir / "visual_plan.json").write_text(
        json.dumps(visual_plan, indent=2), encoding="utf-8")
    layout_doc = None
    report = {"fallback": False}
    if resolved.get("layouter") is not None:
        try:
            layout_doc, report = spatial_layout(
                script_doc, resolved["layouter"], ledger, visual_plan=visual_plan)
            if report.get("residual_schema_errors"):
                layout_doc = None
        except Exception as exc:  # noqa: BLE001 - deterministic fallback is production-safe
            report = {"fallback": True, "reason": str(exc)[:300]}
            log.warning("spatial agent failed (%s); using deterministic autolayout", exc)
    if layout_doc is None:
        starts = []
        cursor = 0
        for scene in script_doc["scenes"]:
            starts.append(cursor)
            cursor += int((scene.get("est_seconds") or
                           len(scene["spoken_text"]) / 2.5) * 1000)
        layout_doc = build_layout(script_doc["scenes"], starts,
                                  title=script_doc.get("title"))
        report = {**report, "fallback": True}
    (job_dir / "layout.json").write_text(
        json.dumps(layout_doc, indent=2, default=str), encoding="utf-8")
    (job_dir / "layout_report.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8")
    return {"layout_doc": layout_doc, "layout_report": report,
            "visual_plan": visual_plan,
            "ledger_entries": list(ledger.entries)}


def run_cognitive(topic: str, job_dir: Path,
                  completes: dict[str, CompleteFn] | None = None,
                  target_seconds: int = 45,
                  max_research_rounds: int | None = None) -> dict:
    """Run research->script->layout; write artifacts; return {script_doc, layout_doc, ledger}."""
    job_dir = Path(job_dir)
    job_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    resolved = _completes(completes)
    research_out = research_stage(topic, job_dir, resolved, max_research_rounds)
    script_out = script_stage(research_out["fact_sheet"], target_seconds, job_dir, resolved)
    layout_out = layout_stage(script_out["script_doc"], job_dir, resolved)
    ledger = Ledger(research_out["ledger_entries"] + script_out["ledger_entries"] +
                    layout_out["ledger_entries"])
    (job_dir / "ledger.json").write_text(
        json.dumps(ledger.summary(), indent=2), encoding="utf-8")
    timings = {"cognitive_s": round(time.perf_counter() - t0, 2)}
    log.info("cognitive done: %s", timings)
    return {"script_doc": script_out["script_doc"],
            "layout_doc": layout_out["layout_doc"],
            "ledger": ledger.summary(), "ledger_entries": list(ledger.entries),
            "timings": timings}
