"""Scriptwriter agent + deterministic style linter (persona constitution enforced)."""

from __future__ import annotations

import json
import logging
import re

from atme.agents.research import constitution
from atme.gateway.router import CompleteFn, Ledger, structured_call
from atme.resources import resource_path

log = logging.getLogger(__name__)

PROMPTS = resource_path("prompts")
SCHEMAS = resource_path("schemas")

BANNED_PATTERNS = [
    r"\brevolutionar\w*", r"\bgame[- ]?chang\w*", r"\bmind[- ]?blow\w*",
    r"\binsane\b", r"\bsupercharg\w*", r"\bunlock the power of\b",
    r"\b10x developer\b", r"\bin today'?s video\b", r"\bdive (deep )?in\b",
    r"\bagi is coming\b", r"\blet'?s\b",
]
DIRECTIVE_VERBS = ("draw", "place", "label", "connect", "highlight")
WORDS_PER_SECOND = 2.5   # ~150 wpm


def style_lint(scenes_doc: dict) -> list[str]:
    """Deterministic checks; returns human-readable violations."""
    problems: list[str] = []
    banned = [re.compile(p, re.IGNORECASE) for p in BANNED_PATTERNS]
    for s in scenes_doc.get("scenes", []):
        sid = s["scene_id"]
        text = s["spoken_text"]
        if "!" in text:
            problems.append("scene %d: exclamation mark" % sid)
        for pat in banned:
            m = pat.search(text)
            if m:
                problems.append("scene %d: banned phrase %r" % (sid, m.group(0)))
        words = len(text.split())
        est = s.get("est_seconds") or round(words / WORDS_PER_SECOND)
        if words < 8:
            problems.append("scene %d: too short (%d words)" % (sid, words))
        directive = s["visual_directive"].strip().lower()
        first_word = directive.split(" ")[0] if directive else ""
        if first_word not in DIRECTIVE_VERBS:
            problems.append("scene %d: directive must start with one of %s (got %r)"
                            % (sid, DIRECTIVE_VERBS, first_word))
    return problems


def numeric_claims_guard(scenes_doc: dict, fact_sheet: dict) -> list[str]:
    """Every number spoken must exist verbatim in a SURVIVING claim or its cited sources.

    Dropped claims are forbidden material - numbers appearing only there must be flagged.
    """
    surviving_ids = {c["claim_id"] for c in fact_sheet.get("claims", [])
                     if c.get("status") == "verified"}
    source_ids = {sid for c in fact_sheet.get("claims", [])
                  if c["claim_id"] in surviving_ids for sid in c.get("source_ids", [])}
    claims = [c for c in fact_sheet.get("claims", []) if c["claim_id"] in surviving_ids]
    sources = [s for s in fact_sheet.get("sources", []) if s.get("source_id") in source_ids]
    corpus = json.dumps(claims) + json.dumps(sources)
    flags: list[str] = []
    for s in scenes_doc.get("scenes", []):
        for num in re.findall(r"\d+(?:\.\d+)?%?", s["spoken_text"]):
            if num not in corpus:
                flags.append("scene %d: number %r not traceable to fact sheet"
                             % (s["scene_id"], num))
    return flags


def compose(fact_sheet: dict, target_seconds: int, complete: CompleteFn,
            ledger: Ledger) -> tuple[dict, list[str]]:
    """Write the script from a verified fact sheet; one linter-driven revision round."""
    schema = json.loads((SCHEMAS / "script-scenes.schema.json").read_text(encoding="utf-8"))
    system = _system_prompt()
    user = (
        "Fact sheet (surviving claims only - dropped ones are forbidden material):\n%s\n\n"
        "Target spoken length: ~%d seconds. Write scenes per the structure contract. "
        "Set claim_ids to the fact-sheet claims each scene relies on."
        % (json.dumps({k: v for k, v in fact_sheet.items() if k != "_ledger"}, indent=1),
           target_seconds)
    )
    doc, _notes = structured_call(complete, ledger, "writer", system, user, schema=schema)

    problems = style_lint(doc)
    if problems:
        log.info("style lint found %d issues; requesting one revision", len(problems))
        doc2, _ = structured_call(
            complete, ledger, "writer", system,
            user + "\n\nYour draft violated the constitution:\n- " + "\n- ".join(problems[:10])
            + "\nReturn ONLY corrected JSON.", schema=schema)
        remaining = style_lint(doc2)
        doc = doc2 if len(remaining) <= len(problems) else doc
        problems = remaining

    guard = numeric_claims_guard(doc, fact_sheet)
    return doc, problems + guard


def _system_prompt() -> str:
    return (
        (PROMPTS / "writer_system.md").read_text(encoding="utf-8")
        + "\n\n# Persona Constitution\n" + constitution()
    )
