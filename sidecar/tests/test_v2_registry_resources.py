"""Registry metadata and rendered art must come from the same pinned bytes."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from atme.render.style_bundle import load_bundle, verified_asset_svg
from atme.render.v2_registry import registry_placement
from atme.render.v2_svg import _registry_visual
from atme.store.contracts_v2 import VisualObject
from test_v2_registry_binding import registry_object
from test_v2_registry_placement import placement_module


def verifier():
    module = placement_module()
    assert hasattr(module, "checked_registry_art"), "registry metadata/art byte binding is missing"
    return module.checked_registry_art


def pinned_bytes():
    style, registry, root = load_bundle()
    entry = next(row for row in registry.assets if row.id == "person-collaborators")
    return style, registry, root, (root / "asset-registry.json").read_bytes(), (root / entry.file).read_bytes()


def test_checked_registry_art_is_the_exact_original_payload_and_fresh_metadata(monkeypatch):
    _, _, _, registry_raw, art = pinned_bytes()
    check = verifier()
    monkeypatch.setattr(Path, "read_bytes", lambda *_: pytest.fail("pure registry verification attempted disk IO"))
    first, payload = check("person-collaborators", registry_raw, art)
    assert payload is art
    assert first.id == "person-collaborators"
    assert first.anchors["left_person"] == (.3, .48)
    first.anchors["left_person"] = (.5, .5)
    second, _ = check("person-collaborators", registry_raw, art)
    assert second.anchors["left_person"] == (.3, .48)


@pytest.mark.parametrize("mutation", ["registry-whitespace", "registry-anchor", "art-whitespace", "different-art"])
def test_modified_metadata_or_art_is_not_verified_even_when_it_is_valid_json_or_svg(mutation):
    _, _, root, registry_raw, art = pinned_bytes()
    if mutation == "registry-whitespace":
        registry_raw += b" "
    elif mutation == "registry-anchor":
        registry = json.loads(registry_raw)
        next(row for row in registry["assets"] if row["id"] == "person-collaborators")["anchors"]["left_person"] = [.5, .5]
        registry_raw = json.dumps(registry).encode()
    elif mutation == "art-whitespace":
        art += b" "
    else:
        art = (root / "assets/person-presenter.svg").read_bytes()
    with pytest.raises(ValueError, match="checksum"):
        verifier()("person-collaborators", registry_raw, art)


@pytest.mark.parametrize("field,value", [("registry", bytearray(b"mutable")), ("art", bytearray(b"mutable")),
    ("registry", "not-bytes"), ("art", None)])
def test_private_byte_verification_refuses_mutable_or_missing_payloads(field, value):
    _, _, _, registry_raw, art = pinned_bytes()
    if field == "registry":
        registry_raw = value
    else:
        art = value
    with pytest.raises(ValueError, match="immutable bytes"):
        verifier()("person-collaborators", registry_raw, art)


def test_unknown_registry_name_does_not_authenticate_a_different_artwork():
    _, _, _, registry_raw, art = pinned_bytes()
    with pytest.raises(ValueError, match="unknown Paper & Ink asset"):
        verifier()("not-a-pinned-asset", registry_raw, art)


def test_normal_registry_render_ignores_mutated_cached_semantic_metadata():
    _, registry, _, _, _ = pinned_bytes()
    entry = next(row for row in registry.assets if row.id == "person-collaborators")
    original = deepcopy(entry.anchors)
    try:
        entry.anchors["left_person"] = (.5, .5)
        checked, inner = verified_asset_svg(entry.id)
        assert inner
        assert checked.anchors["left_person"] == (.3, .48)
        assert checked is not entry
    finally:
        entry.anchors.clear()
        entry.anchors.update(original)


def test_frozen_registry_visual_rebinds_pinned_metadata_without_reading_files(monkeypatch):
    style, registry, _, registry_raw, art = pinned_bytes()
    obj_raw = registry_object()
    obj_raw.pop("registry_binding")  # Actual bound painting still has its separate runtime gate.
    obj = VisualObject.model_validate(obj_raw)
    expected = _registry_visual(obj)
    cached_registry = registry.model_copy(deep=True)
    entry = next(row for row in cached_registry.assets if row.id == obj.variant)
    entry.view_box = (0, 0, 999, 999)
    resources = (style, cached_registry, {"asset-registry.json": registry_raw, entry.file: art}, {})
    monkeypatch.setattr(Path, "read_bytes", lambda *_: pytest.fail("frozen art attempted disk IO"))
    assert _registry_visual(obj, resources) == expected
    checked, _ = verifier()(obj.variant, registry_raw, art)
    assert registry_placement(checked, obj.geometry.bounds).anchor_point("left_person") == pytest.approx((190., 345.6))


@pytest.mark.parametrize("mutation", ["registry", "art", "missing-registry", "missing-art"])
def test_frozen_registry_visual_refuses_corrupt_or_missing_byte_evidence(mutation):
    style, registry, _, registry_raw, art = pinned_bytes()
    obj_raw = registry_object()
    obj_raw.pop("registry_binding")
    obj = VisualObject.model_validate(obj_raw)
    files = {"asset-registry.json": registry_raw, "assets/person-collaborators.svg": art}
    key = "asset-registry.json" if "registry" in mutation else "assets/person-collaborators.svg"
    if mutation.startswith("missing"):
        files.pop(key)
    else:
        files[key] += b" "
    with pytest.raises(ValueError, match="registry|checksum"):
        _registry_visual(obj, (style, registry, files, {}))
