"""Guardrail preflight tests (no downloads)."""

from __future__ import annotations

import pytest

from atme.guardrails import GuardrailError, disk_free_gb, mem_status, preflight


def test_preflight_passes_on_normal_machine(tmp_path, monkeypatch):
    monkeypatch.setenv("ATME_MIN_FREE_GB", "0.001")
    stats = preflight(tmp_path)
    assert stats["free_gb"] > 0


def test_disk_guardrail_raises_when_floor_high(tmp_path, monkeypatch):
    monkeypatch.setenv("ATME_MIN_FREE_GB", "999999")
    with pytest.raises(GuardrailError, match="disk preflight failed"):
        preflight(tmp_path)


def test_memory_guardrail_raises_when_ceiling_low(tmp_path, monkeypatch):
    monkeypatch.setenv("ATME_MAX_MEM_LOAD", "1")   # any real machine exceeds 1%
    with pytest.raises(GuardrailError, match="memory preflight failed"):
        preflight(tmp_path)


def test_helpers_return_sane_values(tmp_path):
    assert disk_free_gb(tmp_path) > 0
    load, total = mem_status()
    assert total >= 15 or total == -1
    assert load <= 100
