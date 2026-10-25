"""Invalid chart writes cannot alter immutable project or cleaned-source history."""

from copy import deepcopy

import pytest
from test_v2_chart_project import stored_chart_basis
from test_v2_registry_project import history

from atme.project_service import ProjectError, _resolved_compilation_fingerprint


@pytest.mark.parametrize("recording_only", [False, True])
@pytest.mark.parametrize("fault,error_code", [
    ("missing_inline_data", "invalid_artifact"),
    ("changed_semantic_data", "invalid_artifact"),
    ("stale_project_revision", "stale_contract_basis"),
    ("stale_cleaned_basis", "stale_contract_basis"),
    ("raw_media_duration", "invalid_artifact"),
])
def test_invalid_chart_project_write_is_atomic(tmp_path, recording_only, fault, error_code):
    service, project, _, layout, timeline = stored_chart_basis(tmp_path, recording_only=recording_only)
    try:
        pid = project["project_id"]
        kind = "layout" if fault in {"missing_inline_data", "changed_semantic_data"} else "resolved_timeline"
        candidate = deepcopy(layout if kind == "layout" else timeline)
        candidate["project_revision"] = project["revision"]
        if fault == "missing_inline_data":
            candidate["objects"][2].pop("chart_payload")
        elif fault == "changed_semantic_data":
            candidate["objects"][2]["chart_payload"]["series"][0]["points"][0]["y"] = 4.
        elif fault == "stale_project_revision":
            candidate["project_revision"] -= 1
        elif fault == "stale_cleaned_basis":
            candidate.update(cleaned_timeline_revision=0, cleaned_timeline_fingerprint="0"*64)
        else:
            candidate["duration_ms"] = 7000  # source was really cleaned to 6000 ms
        if kind == "resolved_timeline":
            candidate["compilation_fingerprint"] = _resolved_compilation_fingerprint(candidate)
        original = deepcopy(candidate)
        before = deepcopy((service.open(pid), history(service, pid), service.source_timeline.get(pid)))
        with pytest.raises(ProjectError) as failure:
            service.write(pid, kind, candidate, project["revision"])
        assert failure.value.code == error_code
        assert candidate == original
        assert (service.open(pid), history(service, pid), service.source_timeline.get(pid)) == before
    finally:
        service.store.close()
