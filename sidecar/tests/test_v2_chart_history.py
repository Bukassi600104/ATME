"""A trusted duplicate must not impose new chart data on immutable old records."""

import json
from copy import deepcopy

import pytest
from test_v2_chart_project import stored_chart_basis
from test_v2_registry_project import history
from v2_fixtures import digest


@pytest.mark.parametrize("recording_only", [False, True])
def test_real_duplicate_preserves_bare_legacy_chart_history_without_fabricated_data(tmp_path, recording_only):
    service, project, plan, layout, _ = stored_chart_basis(tmp_path, recording_only=recording_only)
    try:
        pid = project["project_id"]
        legacy_plan, legacy_layout = deepcopy(plan), deepcopy(layout)
        legacy_plan["objects"][2].pop("chart_payload")
        legacy_layout["objects"][2].pop("chart_payload")
        legacy_layout["plan_sha256"] = digest(legacy_plan)
        # Seed an exact prior-contract persisted fixture, not a public new-write
        # escape hatch. Current normal writes must reject this inline omission.
        for kind, document in (("storyboard", legacy_plan), ("layout", legacy_layout)):
            serialized = service._serialized_artifact(kind, document, legacy_migration=True)
            service.store.conn.execute(
                "UPDATE project_artifact_versions SET document=? WHERE job_id=? AND kind=? AND revision=?",
                (serialized, pid, kind, project["artifacts"][kind]))
        service.store.conn.commit()
        original_history = history(service, pid)
        duplicate = service.duplicate(pid)
        copy_id = duplicate["project_id"]
        copied = {}
        for kind, original in (("storyboard", legacy_plan), ("layout", legacy_layout)):
            assert service.artifact(pid, kind)["document"] == original
            record = service.artifact(copy_id, kind)
            copied[kind] = record["document"]
            assert "chart_payload" not in copied[kind]["objects"][2]
            assert copied[kind]["objects"] == original["objects"]
            assert record["duplicate_derivation"]["source_sha256"] == digest(original)
            assert record["duplicate_derivation"]["copied_sha256"] == digest(copied[kind])
            assert copied[kind]["project_id"] == copy_id != pid
        assert copied["layout"]["plan_sha256"] == digest(copied["storyboard"])
        assert copied["storyboard"]["narrative_authority"] == legacy_plan["narrative_authority"]
        assert json.loads(service._serialized_artifact("layout", copied["layout"], legacy_migration=True)) == copied["layout"]
        assert history(service, pid) == original_history
    finally:
        service.store.close()
