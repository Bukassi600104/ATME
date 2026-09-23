"""Regenerate distributable JSON Schemas from the strict v2 contract models."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    MigrationReportV2,
    ResolvedVisualTimelineV2,
    VisualPlanV2,
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sidecar" / "tests"))
from v2_fixtures import (
    executable_layout_v2,
    resolved_timeline_v2,
    visual_plan_v2,
)

CONTRACTS = {
    "visual-plan-v2.schema.json": VisualPlanV2,
    "executable-layout-v2.schema.json": ExecutableLayoutV2,
    "resolved-visual-timeline-v2.schema.json": ResolvedVisualTimelineV2,
    "migration-report-v2.schema.json": MigrationReportV2,
}


def main() -> None:
    for filename, model in CONTRACTS.items():
        schema = model.model_json_schema(mode="validation")
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"https://atme.local/schemas/v2/{filename}"
        (ROOT / "schemas" / filename).write_text(
            json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    examples = {
        "visual-plan-v2.example.json": visual_plan_v2(),
        "executable-layout-v2.example.json": executable_layout_v2(),
        "resolved-visual-timeline-v2.example.json": resolved_timeline_v2(),
    }
    for filename, document in examples.items():
        (ROOT / "schemas" / "examples" / filename).write_text(
            json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
