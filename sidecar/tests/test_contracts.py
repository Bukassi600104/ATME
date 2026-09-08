"""Golden-file discipline: every bundled example MUST validate against its schema."""

from __future__ import annotations

import copy

import pytest
from jsonschema import Draft202012Validator

from conftest import CONTRACTS, load_example, load_schema


@pytest.mark.parametrize("name", CONTRACTS)
def test_examples_validate_against_schema(name: str) -> None:
    validator = Draft202012Validator(load_schema(name))
    errors = sorted(validator.iter_errors(load_example(name)), key=lambda e: list(e.path))
    assert not [e.message for e in errors]


def test_figure_claims_require_two_sources() -> None:
    """Semantic rule behind ADR-0002: dual-sourced figures must be enforced by the schema."""
    validator = Draft202012Validator(load_schema("fact-sheet"))
    doc = load_example("fact-sheet")

    figure = next(c for c in doc["claims"] if c["kind"] == "figure")
    weakened = copy.deepcopy(doc)
    weakened["claims"] = [
        {**figure, "claim_id": "clm-single-src", "source_ids": figure["source_ids"][:1]}
    ]
    assert any(e.message for e in validator.iter_errors(weakened)), "single-source figure should fail"


def test_grid_snapping_enforced_by_layout_schema() -> None:
    validator = Draft202012Validator(load_schema("excalidraw-layout"))
    doc = load_example("excalidraw-layout")

    offgrid = copy.deepcopy(doc)
    offgrid["elements"][0]["x"] = 313  # not a multiple of the 50px grid
    assert any(e.message for e in validator.iter_errors(offgrid)), "off-grid coordinate should fail"
