from __future__ import annotations

import faulthandler

import json
import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _per_test_hang_tripwire():
    """Fail one genuinely stuck test without timing out a healthy full suite."""
    faulthandler.dump_traceback_later(600, exit=True)
    try:
        yield
    finally:
        faulthandler.cancel_dump_traceback_later()

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = REPO_ROOT / "schemas"
SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

CONTRACTS = [
    "fact-sheet",
    "script-scenes",
    "excalidraw-layout",
    "cue-timeline",
    "reference-video-analysis",
    "visual-plan",
]


def load_schema(name: str) -> dict:
    return json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))


def load_example(name: str) -> dict:
    return json.loads((SCHEMAS / "examples" / f"{name}.example.json").read_text(encoding="utf-8"))
