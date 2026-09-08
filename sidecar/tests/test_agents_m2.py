"""Research/verifier cite-or-cut, scriptwriter lint+revision, spatial collision repair."""

from __future__ import annotations

import json

from jsonschema import Draft202012Validator

from conftest import load_schema
from fakes import (FACT_SHEET_OK, LAYOUT_OVERLAP, SCENES_BAD, SCENES_GOOD, ScriptedLLM,
                   VERIFIER_VERDICTS, j)

from atme.agents.research import research, verify
from atme.agents.scriptwriter import compose, numeric_claims_guard, style_lint
from atme.agents.spatial import layout as spatial_layout
from atme.gateway.router import Ledger


def _research_llms():
    # researcher: expansion -> retrieval ; reasoner: verdict batch(es)
    researcher = ScriptedLLM([
        j({"queries": ["paged attention numbers", "memory wall analysis", "kv cache criticism"]}),
        j(FACT_SHEET_OK),
    ])
    reasoner = ScriptedLLM([j(VERIFIER_VERDICTS)])
    return researcher, reasoner


def test_cite_or_cut_end_to_end():
    researcher, reasoner = _research_llms()
    sheet = research("Why inference is hard", researcher, reasoner, max_rounds=2)
    by_id = {c["claim_id"]: c for c in sheet["claims"]}
    assert by_id["clm-1"]["status"] == "verified"          # dual-sourced figure survives
    assert by_id["clm-3"]["status"] == "dropped"           # single-source figure cut structurally
    assert sheet["_ledger"]["total_calls"] >= 3            # expansion+retrieval+verify ledgered
    # dedupe: second-round expansion would have repeated queries -> only one retrieval call made
    retrieval_calls = [c for c in researcher.calls if "Search angles" in c["user"]]
    assert len(retrieval_calls) == 1


def test_scriptwriter_lints_then_accepts_revision():
    writer = ScriptedLLM([j(SCENES_BAD), j(SCENES_GOOD)])
    problems_first = style_lint(SCENES_BAD)
    assert any("banned phrase" in p for p in problems_first)
    assert any("exclamation" in p for p in problems_first)

    # compose() consumes POST-verification sheets; simulate verify() output here
    fact_sheet = {**FACT_SHEET_OK,
                  "claims": [{**c, "status": "verified"}
                             for c in FACT_SHEET_OK["claims"] if c["claim_id"] == "clm-1"]}
    doc, flags = compose(fact_sheet, target_seconds=24, complete=writer, ledger=Ledger())
    assert doc["scenes"][0]["spoken_text"].startswith("Serving large models")
    assert not style_lint(doc), "revised draft must pass the linter"
    assert not numeric_claims_guard(doc, fact_sheet)


def test_numeric_guard_flags_untraceable_numbers():
    verified_sheet = {**FACT_SHEET_OK,
                      "claims": [{**c, "status": "verified"}
                                 for c in FACT_SHEET_OK["claims"] if c["claim_id"] == "clm-1"]}
    # "87" exists ONLY inside a dropped claim -> must be flagged as untraceable
    bad = {**SCENES_GOOD,
           "scenes": [{**SCENES_GOOD["scenes"][1],
                       "spoken_text": "It cuts latency by 87 percent instantly."}]}
    flags = numeric_claims_guard(bad, verified_sheet)
    assert any("87" in f for f in flags), flags

    # the surviving dual-sourced 2.4x figure traces fine and stays unflagged
    clean = numeric_claims_guard(SCENES_GOOD, verified_sheet)
    assert not clean, clean


def test_spatial_repairs_overlaps_and_validates():
    layouter = ScriptedLLM([j(LAYOUT_OVERLAP)])
    doc, report = spatial_layout({"scenes": SCENES_GOOD["scenes"][:2]},
                                 layouter, Ledger())
    schema = load_schema("excalidraw-layout")
    errors = list(Draft202012Validator(schema).iter_errors(doc))
    assert not errors
    boxes = [e for e in doc["elements"] if e["type"] == "rectangle"]
    assert report["repair_moves"] > 0
    ys = sorted(b["y"] for b in boxes)
    assert ys[1] >= ys[0] + 250, "overlapping boxes must be pushed apart"


def test_spatial_deterministic_same_seed():
    outs = []
    for _ in range(2):
        llm = ScriptedLLM([j(LAYOUT_OVERLAP)])
        doc, _rep = spatial_layout({"scenes": SCENES_GOOD["scenes"][:2]}, llm, Ledger())
        outs.append(json.dumps(doc, sort_keys=True))
    assert outs[0] == outs[1]