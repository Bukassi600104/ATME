"""New placed-anchor writes are strict; art-only and explicit history stay intact."""

import json
from copy import deepcopy

import pytest
from atme.project_service import ProjectError, ProjectService
from atme.render.v2_svg import compose_svg_frame
from atme.store.db import JobStore
from test_v2_registry_binding import bound_split_documents
from test_v2_registry_runtime import bound_art_documents
from v2_fixtures import digest


@pytest.fixture
def service(tmp_path):
    core = ProjectService(JobStore(tmp_path / "registry-write.db"))
    yield core
    core.store.close()


@pytest.mark.parametrize("fault", ["asset", "name", "family", "version"])
def test_new_semantic_binding_must_name_verified_registry_metadata(service, fault):
    plan, _, _ = bound_split_documents()
    actor = next(obj for obj in plan["objects"] if obj["object_id"] == "source")
    if fault == "asset":
        actor["registry_binding"]["asset_id"] = "not-in-the-registry"
    elif fault == "name":
        actor["registry_binding"]["anchor_mappings"][0]["registry_anchor_name"] = "invented-part"
    elif fault == "family":
        actor["object_type"] = "device"
    else:
        plan["asset_registry_version"] = "1.0.1"
    before = deepcopy(plan)
    with pytest.raises(ProjectError) as failure:
        service._serialized_artifact("storyboard", plan)
    assert failure.value.code == "invalid_artifact"
    assert "registry" in str(failure.value.errors)
    assert plan == before


@pytest.mark.parametrize("fault", ["unbound", "name", "fit", "family", "version"])
def test_new_layout_binding_must_cover_and_authenticate_placed_anchors(service, fault):
    _, layout, _ = bound_split_documents()
    actor = next(obj for obj in layout["objects"] if obj["object_id"] == "source")
    if fault == "unbound":
        actor.pop("registry_binding")
    elif fault == "name":
        actor["registry_binding"]["anchor_mappings"][0]["registry_anchor_name"] = "invented-part"
    elif fault == "fit":
        actor["anchors"][0]["point"]["x"] = .51
    elif fault == "family":
        actor["object_type"] = "device"
    else:
        layout["asset_registry_version"] = "1.0.1"
    before = deepcopy(layout)
    with pytest.raises(ProjectError) as failure:
        service._serialized_artifact("layout", layout)
    assert failure.value.code == "invalid_artifact"
    assert "registry" in str(failure.value.errors)
    assert layout == before


@pytest.mark.parametrize("anchorless", [False, True])
def test_valid_new_bound_or_art_only_documents_preserve_exact_json(service, anchorless):
    plan, layout, _ = bound_split_documents()
    if anchorless:
        next(obj for obj in plan["objects"] if obj["object_id"] == "source").pop("registry_binding")
        actor = next(obj for obj in layout["objects"] if obj["object_id"] == "source")
        actor.pop("registry_binding")
        actor["anchors"] = []
    before = deepcopy((plan, layout))
    for kind, document in (("storyboard", plan), ("layout", layout)):
        assert json.loads(service._serialized_artifact(kind, document)) == document
    assert (plan, layout) == before


def test_explicit_legacy_layout_can_keep_bare_anchors_without_rewriting_history(service):
    _, layout, _ = bound_split_documents()
    next(obj for obj in layout["objects"] if obj["object_id"] == "source").pop("registry_binding")
    before = deepcopy(layout)
    assert json.loads(service._serialized_artifact("layout", layout, legacy_migration=True)) == before
    with pytest.raises(ProjectError, match="Schema validation failed"):
        service._serialized_artifact("layout", layout)
    assert layout == before


def test_explicit_migration_cannot_bypass_supplied_binding_at_runtime(service):
    layout, timeline = bound_art_documents()
    layout["objects"][2]["anchors"][0]["point"]["x"] = .31
    timeline["layout_sha256"] = digest(layout)
    service._serialized_artifact("layout", layout, legacy_migration=True)
    with pytest.raises(ValueError, match="does not match fitted registry anchor"):
        compose_svg_frame(layout, timeline, 0)
