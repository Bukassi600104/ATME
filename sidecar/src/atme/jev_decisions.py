"""Optional TypeSafe Jev advisory decisions for the external-AI MCP workflow."""
from __future__ import annotations

import os

from atme.project_service import ProjectError


DECISIONS = {
    "visual_treatment": {
        "instructions": "Which approved ATME treatment best explains this narration beat while preserving compact Caleb-derived composition?",
        "criteria": {
            "talking_head": "Presenter remains dominant; few or no explanatory marks are needed.",
            "compact_illustration": "A small hand-drawn illustration adds clarity without covering the frame.",
            "diagram": "Relationships, flow, sequence, or causality need a structured diagram.",
            "evidence": "The explanation depends on source media, an interface, or other project evidence.",
            "hybrid": "Presenter and one compact explanatory visual should coexist.",
        },
    },
    "revision_route": {
        "instructions": "Which ATME subsystem should handle this bounded revision request?",
        "criteria": {
            "timeline": "Timing, split, trim, placement, silence, or clip order.",
            "captions": "Caption text, segmentation, or caption timing.",
            "storyboard": "Narrative beat, visual choice, or scene sequence.",
            "layout": "Size, position, framing, density, camera, or composition.",
            "asset": "Replace or select project media or illustration assets.",
            "manual_review": "Ambiguous, unsafe, or outside the bounded ATME workflow.",
        },
    },
    "scene_density": {
        "instructions": "How visually dense should this ATME scene be for clarity and Caleb-derived pacing?",
        "criteria": {
            "minimal": "One focal idea with generous negative space.",
            "balanced": "Presenter or main diagram plus a small number of supporting elements.",
            "dense": "Several simultaneous relationships are essential to the explanation.",
        },
    },
}


def evaluate(service, project_id: int, decision_kind: str, context: str) -> dict:
    if decision_kind not in DECISIONS:
        raise ProjectError("invalid_decision", "Unsupported Jev decision kind")
    if not isinstance(context, str) or not context.strip() or len(context) > 20_000:
        raise ProjectError("invalid_decision", "Decision context must contain 1 to 20,000 characters")
    if not os.environ.get("TYPESAFE_API_KEY"):
        raise ProjectError(
            "jev_not_configured",
            "Jev is optional. Add TYPESAFE_API_KEY to the ATME MCP server environment in your AI client.",
        )
    project = service.open(project_id)
    spec = DECISIONS[decision_kind]
    try:
        from typesafe_sdk import Choice, TypeSafeClient
        with TypeSafeClient() as client:
            response = client.system_one(
                state={
                    "project": {"id": project_id, "profile": project["profile"],
                                "input_kind": project["input_kind"], "revision": project["revision"]},
                    "context": context,
                },
                questions={
                    "decision": Choice(instructions=spec["instructions"], criteria=spec["criteria"]),
                },
            )
        answer = response.choices["decision"]
        return {"provider": "typesafe", "model": response.model, "decision_kind": decision_kind,
                "advisory_only": True, "project_revision": project["revision"],
                "answer": answer.model_dump(mode="json"),
                "usage": response.usage.model_dump(mode="json")}
    except ProjectError:
        raise
    except Exception as exc:
        raise ProjectError("jev_unavailable", f"Jev decision failed: {str(exc)[:240]}") from exc
