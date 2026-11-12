from copy import deepcopy

import pytest

from atme import project_v2_render
from atme.project_service import _visual_digest
from atme.render import v2_state, v2_svg
from test_v2_resolved_project import stored_v2_basis


def test_immutable_batch_retains_public_frame_checks_and_pixels(tmp_path, monkeypatch):
    core, project, _, layout, timeline = stored_v2_basis(tmp_path, real_evidence=True)
    try:
        record = {"document": timeline, "revision": project["revision"] + 1}
        assets = project_v2_render.verified_assets(core, core._row(project["project_id"]), record, layout)
    finally:
        core.store.close()
    layout["objects"][0]["semantic_role"] += " · résumé"
    timeline["layout_sha256"] = _visual_digest(layout)
    checks = (0, 3999, 4000, 4900, 9999)
    reference = [v2_svg.compose_png_frame(layout, timeline, at, assets).png for at in checks]
    original = v2_state._validate_pair
    validated = []

    def observe(*args, **kwargs):
        validated.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(v2_state, "_validate_pair", observe)
    sample = v2_svg.prepare_png_sequence(layout, timeline, assets)
    assert [sample(at).png for at in checks] == reference
    assert len(validated) == 1
    changed = deepcopy(layout)
    changed["objects"][0]["semantic_role"] += " replacement"
    with pytest.raises(ValueError, match="same composition"):
        v2_svg.prepare_png_sequence(changed, timeline, assets)
