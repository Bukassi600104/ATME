"""Cognitive e2e: topic -> fake research/script/layout -> SAPI VO -> rendered MP4.

Exercises the FULL vertical slice keylessly (fake provider), ~45 s on target hardware.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from conftest import REPO_ROOT, load_schema

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    job = tmp_path_factory.mktemp("topicjob")
    src = REPO_ROOT / "sidecar" / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

    from atme import cognitive

    cog = cognitive.run_cognitive("Why inference is hard", job, completes=None)

    from atme.audio.tts_sapi import synthesize_scenes

    synthesize_scenes(cog["script_doc"]["scenes"], job / "segments")

    from atme.pipeline import run_pipeline

    manifest = run_pipeline(None, job, script_dict=cog["script_doc"],
                            layout_dict=cog["layout_doc"])
    return job, cog, manifest


def test_cognitive_artifacts_exist_and_validate(results):
    job, _cog, _m = results
    sheet = json.loads((job / "fact_sheet.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(load_schema("fact-sheet"))
    # post-verification sheet must satisfy the strict schema (dual-sourced figures etc.)
    assert not list(validator.iter_errors(sheet)), "fact sheet violates contract"
    verified = [c for c in sheet["claims"] if c["status"] == "verified"]
    assert verified, "fake research must produce at least one verified claim"
    assert all(len(set(c["source_ids"])) >= 2
               for c in verified if c["kind"] == "figure"), "dual-source rule"


def test_script_passes_linter(results):
    job, cog, _m = results
    from atme.agents.scriptwriter import style_lint

    assert not style_lint(cog["script_doc"]), cog.get("_lint_problems")


def test_media_manifest_complete(results):
    job, _cog, manifest = results
    mp4 = Path(manifest["artifacts"]["video"]["path"])
    assert mp4.exists() and mp4.stat().st_size > 100_000
    cues = json.loads(Path(manifest["artifacts"]["cue_timeline"]["path"]).read_text(encoding="utf-8"))
    assert not list(Draft202012Validator(load_schema("cue-timeline")).iter_errors(cues))
    assert cues["words"], "alignment produced zero words"
    ledger = json.loads((job / "ledger.json").read_text(encoding="utf-8"))
    assert ledger["total_calls"] >= 3, "research+verify calls must be ledgered"
