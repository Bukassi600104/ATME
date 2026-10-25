"""Registry completeness must not reinterpret custom placed-anchor semantics."""

import json
from pathlib import Path

import pytest
from atme.project_service import ProjectError
from atme.render.style_bundle import load_bundle
from test_v2_registry_binding import bound_split_documents
from test_v2_registry_writes import service as registry_service

service = registry_service


@pytest.mark.parametrize("kind", ["icon", "pictogram", "character", "device", "document", "chart", "terminal"])
def test_custom_anchored_variant_is_not_implicitly_a_registry_claim(service, kind):
    _, layout, _ = bound_split_documents()
    actor = next(row for row in layout["objects"] if row["object_id"] == "source")
    actor.update(object_type=kind, variant="custom-external-illustration")
    actor.pop("registry_binding")
    assert json.loads(service._serialized_artifact("layout", layout)) == layout


def test_exact_known_registry_variant_with_placed_anchors_requires_binding(service):
    _, layout, _ = bound_split_documents()
    next(row for row in layout["objects"] if row["object_id"] == "source").pop("registry_binding")
    with pytest.raises(ProjectError) as failure:
        service._serialized_artifact("layout", layout)
    assert "registry_binding" in str(failure.value.errors)


def test_supplied_custom_binding_does_not_claim_arbitrary_external_metadata(service):
    _, layout, _ = bound_split_documents()
    actor = next(row for row in layout["objects"] if row["object_id"] == "source")
    actor["variant"] = actor["registry_binding"]["asset_id"] = "custom-external-illustration"
    with pytest.raises(ProjectError) as failure:
        service._serialized_artifact("layout", layout)
    assert "unknown Paper & Ink asset" in str(failure.value.errors)


def test_mutable_cached_registry_cannot_reclassify_a_custom_variant(service, monkeypatch):
    _, cached, _ = load_bundle()
    monkeypatch.setattr(cached.assets[0], "id", "custom-external-illustration")
    _, layout, _ = bound_split_documents()
    actor = next(row for row in layout["objects"] if row["object_id"] == "source")
    actor.update(object_type="icon", variant="custom-external-illustration")
    actor.pop("registry_binding")
    assert json.loads(service._serialized_artifact("layout", layout)) == layout


def test_metadata_only_classification_still_requires_actual_pinned_bytes(service, monkeypatch):
    _, layout, _ = bound_split_documents()
    actor = next(row for row in layout["objects"] if row["object_id"] == "source")
    actor.update(object_type="icon", variant="custom-external-illustration")
    actor.pop("registry_binding")
    read = Path.read_bytes

    def changed_registry(path):
        raw = read(path)
        return raw + b" " if path.name == "asset-registry.json" else raw

    monkeypatch.setattr(Path, "read_bytes", changed_registry)
    with pytest.raises(ProjectError) as failure:
        service._serialized_artifact("layout", layout)
    assert "checksum mismatch" in str(failure.value.errors)
