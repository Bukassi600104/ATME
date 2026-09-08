"""Gateway repair ladder + ledger behavior."""

from __future__ import annotations

import pytest

from atme.gateway.router import (CompletionText, Ledger, SchemaViolation,
                                 extract_json, structured_call)
from fakes import ScriptedLLM, j

SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["name"],
    "properties": {"name": {"type": "string"}},
}


def test_extract_json_tolerates_fences():
    fence = chr(96) * 3
    text = fence + "json\n" + j({"a": 1}) + "\n" + fence
    assert extract_json(text) == {"a": 1}


def test_repair_ladder_recovers_from_bad_json():
    llm = ScriptedLLM(["not json at all", j({"name": "ok"})])
    ledger = Ledger()
    out, notes = structured_call(llm, ledger, "writer", "sys", "user", schema=SCHEMA)
    assert out == {"name": "ok"}
    assert len(notes) == 1 and len(ledger.entries) == 2
    assert ledger.summary()["total_calls"] == 2


def test_repair_ladder_exhausts_and_raises():
    llm = ScriptedLLM([j({"wrong": 1})] * 5)
    with pytest.raises(SchemaViolation):
        structured_call(llm, ledger := Ledger(), "layouter", "sys", "user", schema=SCHEMA)
    assert len(ledger.entries) == 4      # initial + 3 repairs


def test_transport_error_gets_repair_round():
    class Flaky:
        def __init__(self):
            self.n = 0
        def __call__(self, system, user="", **kw):
            self.n += 1
            if self.n == 1:
                raise TimeoutError("boom")
            return j({"name": "fine"})

    ledger = Ledger()
    out, _ = structured_call(Flaky(), ledger, "reasoner", "sys", "user", schema=SCHEMA)
    assert out == {"name": "fine"}
    assert ledger.entries[0].ok is False and "transport" in ledger.entries[0].error


def test_provider_usage_metadata_reaches_ledger():
    def measured(system, user):
        return CompletionText(j({"name": "metered"}), model="provider/actual",
                              prompt_tokens=123, completion_tokens=45, cost_usd=0.012)

    output, _ = structured_call(measured, ledger := Ledger(), "writer", "sys", "user",
                                schema=SCHEMA, model_label="configured/model")
    assert output == {"name": "metered"}
    entry = ledger.entries[0]
    assert (entry.model, entry.prompt_tokens, entry.completion_tokens, entry.cost_usd) == (
        "provider/actual", 123, 45, 0.012)
