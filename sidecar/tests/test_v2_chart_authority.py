"""Real chart plans cannot falsely name their semantic narrative authority."""

from copy import deepcopy

import pytest
from test_v2_chart_project import stored_chart_basis
from test_v2_registry_project import history

from atme.project_service import ProjectError


@pytest.mark.parametrize("recording_only", [False, True])
@pytest.mark.parametrize("field", ["mode", "authority_id"])
def test_chart_storyboard_rejects_false_authority_with_current_timing_atomically(tmp_path, recording_only, field):
    service, project, plan, _, _ = stored_chart_basis(tmp_path, recording_only=recording_only)
    try:
        pid = project["project_id"]
        candidate = deepcopy(plan)
        candidate["project_revision"] = project["revision"]
        candidate["narrative_authority"][field] = (
            ("approved_script_plus_recording" if recording_only else "recording_only") if field == "mode"
            else "forged-authority")
        original = deepcopy(candidate)
        before = deepcopy((service.open(pid), history(service, pid), service.source_timeline.get(pid)))
        with pytest.raises(ProjectError) as failure:
            service.write(pid, "storyboard", candidate, project["revision"])
        assert failure.value.code == "stale_contract_basis"
        assert "authority" in str(failure.value).lower()
        assert candidate == original
        assert (service.open(pid), history(service, pid), service.source_timeline.get(pid)) == before
    finally:
        service.store.close()
