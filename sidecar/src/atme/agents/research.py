"""Research agent + adversarial verifier (ADR-0002, accuracy-first).

Flow: query expansion -> multi-angle retrieval via the WEB-GROUNDED researcher role ->
candidate claim extraction -> isolated reasoner-role cross-examination per claim ->
cite-or-cut. Efficiency guards: query dedupe, per-topic cache, token ceiling.
"""

from __future__ import annotations

import json
import logging
from urllib.parse import urlparse

from atme.gateway.router import CompleteFn, Ledger, structured_call
from atme.resources import resource_path

log = logging.getLogger(__name__)

PROMPTS = resource_path("prompts")
SCHEMAS = resource_path("schemas")
MAX_ROUNDS = 5


def _sys(name: str) -> str:
    return (PROMPTS / name).read_text(encoding="utf-8")


def constitution() -> str:
    return (PROMPTS / "persona.constitution.md").read_text(encoding="utf-8")


def expand_queries(complete: CompleteFn, ledger: Ledger, topic: str, n: int = 4) -> list[str]:
    schema = {"type": "object", "additionalProperties": False,
              "required": ["queries"],
              "properties": {"queries": {"type": "array", "minItems": 1, "maxItems": n,
                                         "items": {"type": "string", "minLength": 3}}}}
    out, _ = structured_call(
        complete, ledger, "researcher",
        _sys("researcher_system.md"),
        "Topic: %s\nPropose %d distinct search angles covering mechanism, numbers, and criticism."
        % (topic, n),
        schema=schema)
    seen, queries = set(), []
    for q in out["queries"]:
        k = q.strip().lower()
        if k not in seen:
            seen.add(k)
            queries.append(q.strip())
    return queries[:n]


def retrieve(complete: CompleteFn, ledger: Ledger, topic: str, queries: list[str]) -> tuple[dict, dict]:
    """One retrieval pass. Returns (fact_sheet_dict, raw_response_meta)."""
    user = ("Topic: %s\nSearch angles (cover ALL):\n%s\n\n"
            "Retrieve sources and extract candidate claims with exact figures. "
            "Every figure needs at least two independent sources."
            % (topic, "\n".join("- " + q for q in queries)))
    schema = json.loads((SCHEMAS / "fact-sheet.schema.json").read_text(encoding="utf-8"))
    # retrieval-stage relaxations: topic gets stamped by research(); dual-source rule is
    # enforced AFTER verification (cite-or-cut), so neutralize the if/then here.
    schema["required"] = [r for r in schema.get("required", []) if r != "topic"]
    schema["$defs"]["claim"]["if"] = {"properties": {"kind": {"enum": []}}}
    schema["$defs"]["source"]["required"] = [
        r for r in schema["$defs"]["source"].get("required", []) if r != "retrieved_at"]
    sheet, meta = structured_call(complete, ledger, "researcher",
                                  _sys("researcher_system.md"), user, schema=schema)
    sheet.setdefault("topic", topic)
    return sheet, meta


def verify(complete: CompleteFn, ledger: Ledger, sheet: dict) -> dict:
    """Cross-examine every claim against its cited excerpts; cite-or-cut."""
    sources = {s["source_id"]: s for s in sheet.get("sources", [])}
    verdicts: dict[str, dict] = {}
    claims = sheet.get("claims", [])
    for i in range(0, len(claims), 5):
        batch = claims[i:i + 5]
        payload = []
        for c in batch:
            srcs = []
            for sid in c.get("source_ids", []):
                s = sources.get(sid, {})
                srcs.append({"source_id": sid, "title": s.get("title"),
                             "excerpt": (s.get("excerpt") or "")[:600]})
            payload.append({"claim_id": c["claim_id"], "text": c["text"],
                            "kind": c["kind"], "sources": srcs})
        schema = {"type": "object", "additionalProperties": False, "required": ["verdicts"],
                  "properties": {"verdicts": {"type": "array", "items": {
                      "type": "object", "additionalProperties": False,
                      "required": ["claim_id", "status"],
                      "properties": {
                          "claim_id": {"type": "string"},
                          "status": {"enum": ["verified", "dropped"]},
                          "reason": {"type": "string"}}}}}}
        out, _ = structured_call(complete, ledger, "reasoner",
                                 _sys("verifier_system.md"),
                                 json.dumps(payload, indent=1), schema=schema)
        for v in out["verdicts"]:
            verdicts[v["claim_id"]] = v

    for c in claims:
        v = verdicts.get(c["claim_id"])
        cited = [sources.get(source_id, {}) for source_id in c.get("source_ids", [])]
        domains = {urlparse(source.get("url", "")).hostname or "" for source in cited}
        domains = {domain.lower().removeprefix("www.") for domain in domains if domain}
        dual_ok = len(set(c.get("source_ids", []))) >= 2 and len(domains) >= 2
        if c["kind"] == "figure" and not dual_ok:
            c["status"] = "dropped"          # structural rule regardless of model opinion
        elif v is None:
            c["status"] = "unresolved"
        else:
            c["status"] = v["status"]
            if v.get("reason"):
                c["notes"] = (c.get("notes") or "") + " verifier: " + v["reason"]
        c["verification_rounds"] = c.get("verification_rounds", 0) + 1
    sheet["claims"] = claims
    return sheet


def research(topic: str, complete_researcher: CompleteFn, complete_reasoner: CompleteFn,
             max_rounds: int = MAX_ROUNDS, progress_cb=None,
             ledger: Ledger | None = None) -> dict:
    ledger = ledger or Ledger()
    all_sources: dict[str, dict] = {}
    claims_by_id: dict[str, dict] = {}
    used_queries: list[str] = []

    for rnd in range(1, max_rounds + 1):
        if progress_cb:
            progress_cb(rnd, max_rounds)
        queries = [q for q in expand_queries(complete_researcher, ledger, topic,
                                             n=3 if rnd > 1 else 4)
                   if q.lower() not in {u.lower() for u in used_queries}]
        if not queries:
            break
        used_queries.extend(queries)

        sheet, _meta = retrieve(complete_researcher, ledger, topic, queries)
        sheet["topic"] = topic
        for s in sheet.get("sources", []):
            all_sources.setdefault(s["source_id"], s)
        for c in sheet.get("claims", []):
            c["verification_rounds"] = rnd
            claims_by_id[c["claim_id"]] = c

        working = {"topic": topic, "generated_at": sheet.get("generated_at", ""),
                   "research_model": sheet.get("research_model"),
                   "verification_rounds_used": rnd,
                   "sources": list(all_sources.values()),
                   "claims": list(claims_by_id.values())}
        working = verify(complete_reasoner, ledger, working)

        unresolved = [c for c in working["claims"] if c["status"] == "unresolved"]
        log.info("round %d: %d claims, %d unresolved", rnd, len(working["claims"]), len(unresolved))
        if not unresolved:
            break

    final = {"topic": topic, "generated_at": working.get("generated_at", ""),
             "research_model": working.get("research_model"),
             "verification_rounds_used": min(max_rounds, rnd),
             "sources": list(all_sources.values()),
             "claims": working["claims"]}
    final["_ledger"] = ledger.summary()
    return final
