"""Typed pydantic mirrors parse the same examples and enforce the dual-source rule."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from atme.store.contracts import CueTimeline, FactSheet, LayoutDoc, ScriptScenes

from conftest import load_example


def test_fact_sheet_parses_and_keeps_semantics() -> None:
    sheet = FactSheet.model_validate(load_example("fact-sheet"))
    verified_figures = [c for c in sheet.claims if c.kind == "figure" and c.status == "verified"]
    dropped = [c for c in sheet.claims if c.status == "dropped"]
    assert verified_figures, "example must include a surviving figure"
    assert all(len(c.source_ids) >= 2 for c in verified_figures), "ADR-0002 dual-source rule"
    assert dropped, "cite-or-cut example must survive parsing (dropped figures exempt from dual-source)"


def test_figure_with_single_source_rejected() -> None:
    raw = load_example("fact-sheet")
    fig = next(c for c in raw["claims"] if c["kind"] == "figure")
    bad = {**raw, "claims": [{**fig, "source_ids": fig["source_ids"][:1]}]}
    with pytest.raises(ValidationError):
        FactSheet.model_validate(bad)


@pytest.mark.parametrize(
    ("model", "example"),
    [(ScriptScenes, "script-scenes"), (LayoutDoc, "excalidraw-layout"), (CueTimeline, "cue-timeline")],
)
def test_remaining_contracts_round_trip(model: type, example: str) -> None:
    parsed = model.model_validate(load_example(example))
    again = model.model_validate(parsed.model_dump())
    assert again == parsed
