"""Full M1 pipeline integration test (runs the real pipeline, ~45 s on target hardware).

Skips unless the SAPI-generated fixture segments exist (bench/make_fixture_vo.ps1).
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from conftest import REPO_ROOT, load_schema

SEGMENTS = REPO_ROOT / "data" / "jobs" / "fixture1" / "segments"
SCRIPT = REPO_ROOT / "tests" / "fixtures" / "fixture-script.json"

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def manifest(tmp_path_factory):
    if not SEGMENTS.exists() or not SCRIPT.exists():
        pytest.skip("fixture VO missing - run bench/make_fixture_vo.ps1 first")
    job = tmp_path_factory.mktemp("job")
    shutil.copytree(SEGMENTS, job / "segments")

    src = REPO_ROOT / "sidecar" / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from atme.pipeline import run_pipeline

    return run_pipeline(SCRIPT, job)


def test_manifest_and_artifacts(manifest):
    assert manifest["artifacts"]["words_aligned"] >= 25
    mp4 = Path(manifest["artifacts"]["video"]["path"])
    assert mp4.exists() and mp4.stat().st_size > 100_000
    assert Path(manifest["artifacts"]["audio"]["path"]).exists()


def test_cue_timeline_validates_against_contract(manifest):
    cues = json.loads(Path(manifest["artifacts"]["cue_timeline"]["path"]).read_text(encoding="utf-8"))
    validator = Draft202012Validator(load_schema("cue-timeline"))
    errors = list(validator.iter_errors(cues))
    assert not [e.message for e in errors]


def test_layout_validates_against_contract(manifest):
    doc = json.loads(Path(manifest["artifacts"]["layout"]["path"]).read_text(encoding="utf-8"))
    validator = Draft202012Validator(load_schema("excalidraw-layout"))
    errors = list(validator.iter_errors(doc))
    assert not [e.message for e in errors]


def test_duration_consistency(manifest):
    cues = json.loads(Path(manifest["artifacts"]["cue_timeline"]["path"]).read_text(encoding="utf-8"))
    assert abs(cues["duration_ms"] - manifest["duration_ms"]) < 5
