"""Return compiler data is distributable without changing semantic authoring schemas."""

import json
import os
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

from conftest import load_schema

from atme.project_service import ProjectService
from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    MigrationReportV2,
    ResolvedVisualTimelineV2,
    VisualPlanV2,
)

ROOT = Path(__file__).resolve().parents[2]


def test_all_generated_schemas_match_models_and_regeneration_is_deterministic():
    models = {"visual-plan-v2": VisualPlanV2, "executable-layout-v2": ExecutableLayoutV2,
              "resolved-visual-timeline-v2": ResolvedVisualTimelineV2, "migration-report-v2": MigrationReportV2}
    paths = list((ROOT / "schemas").glob("*v2.schema.json")) + list((ROOT / "schemas/examples").glob("*v2.example.json"))
    before = {path: sha256(path.read_bytes()).hexdigest() for path in paths}
    for name, model in models.items():
        expected = model.model_json_schema(mode="validation")
        expected.update({"$schema": "https://json-schema.org/draft/2020-12/schema",
                         "$id": f"https://atme.local/schemas/v2/{name}.schema.json"})
        assert load_schema(name) == expected
    env = {**os.environ, "PYTHONPATH": str(ROOT / "sidecar/src")}
    subprocess.run([sys.executable, str(ROOT / "sidecar/tools/generate_v2_schemas.py")],
                   cwd=ROOT, env=env, check=True, capture_output=True)
    assert before == {path: sha256(path.read_bytes()).hexdigest() for path in paths}


def test_schema_registry_and_packaging_expose_compiler_receipt_not_plan_intent():
    schema = ProjectService.schema("resolved_timeline", "2.0.0")
    assert "return_hierarchy_receipt" in schema["$defs"]["ResolvedAction"]["properties"]
    assert "ReturnHierarchyReceipt" in schema["$defs"]
    for kind in ("storyboard", "layout"):
        assert "ReturnHierarchyReceipt" not in ProjectService.schema(kind, "2.0.0")["$defs"]
    assert '(str(ROOT / "schemas"), "schemas")' in (ROOT / "sidecar/atme-sidecar.spec").read_text(encoding="utf-8")
    assert json.loads((ROOT / "schemas/resolved-visual-timeline-v2.schema.json").read_text()) == schema
