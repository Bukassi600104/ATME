"""Phase 2 acceptance for the versioned Paper & Ink resource foundation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest
from atme.render.style_bundle import (
    EXPECTED_REGISTRY_SHA256,
    EXPECTED_STYLE_SHA256,
    StyleBundleError,
    asset_matrix_svg,
    contrast_ratio,
    export_asset_matrix,
    export_typography_proof,
    load_bundle,
    preview_asset_matrix,
    preview_typography_proof,
    resolve_contract_bundle,
    typography_proof_svg,
)
from atme.render.style_contracts import AssetRegistry, PaperInkStyle
from conftest import REPO_ROOT

RESOURCE = REPO_ROOT / "production-assets" / "paper-ink-v2"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_manifests_validate_against_runtime_models_and_json_schemas():
    style_data = json.loads((RESOURCE / "style.json").read_text(encoding="utf-8"))
    asset_data = json.loads((RESOURCE / "asset-registry.json").read_text(encoding="utf-8"))
    assert PaperInkStyle.model_validate(style_data).version == "2.0.0"
    assert AssetRegistry.model_validate(asset_data).version == "2.0.0"
    jsonschema.Draft202012Validator(
        json.loads((REPO_ROOT / "schemas" / "paper-ink-style-v2.schema.json").read_text())
    ).validate(style_data)
    jsonschema.Draft202012Validator(
        json.loads((REPO_ROOT / "schemas" / "paper-ink-assets-v2.schema.json").read_text())
    ).validate(asset_data)


def test_every_resource_is_local_pinned_and_checksum_verified():
    style, registry, root = load_bundle()
    assert digest(root / "style.json") == EXPECTED_STYLE_SHA256
    assert digest(root / "asset-registry.json") == EXPECTED_REGISTRY_SHA256
    for font in style.fonts:
        assert digest(root / font.file) == font.sha256
        assert digest(root / font.license_file) == font.license_sha256
        assert re.search(r"/[0-9a-f]{40}/", font.source_url)
    for asset in registry.assets:
        assert digest(root / asset.file) == asset.sha256
        assert asset.provenance.origin == "ATME-original"
        assert asset.provenance.derivative_of_reference_art is False


def test_all_eight_asset_families_have_multiple_originals():
    _, registry, _ = load_bundle()
    expected = {"people", "gestures", "devices", "documents", "networks", "charts",
                "technical-frames", "abstract-metaphors"}
    assert {asset.family for asset in registry.assets} == expected
    assert all(sum(asset.family == family for asset in registry.assets) >= 2 for family in expected)
    assert all(len(asset.anchors) >= 3 for asset in registry.assets)


def test_bundle_matches_live_v2_contract_identifiers():
    style, registry, _ = resolve_contract_bundle("atme-style-v2", "atme-assets-v2")
    assert style.system_id == "atme-style-v2"
    assert registry.registry_id == "atme-assets-v2"
    with pytest.raises(StyleBundleError, match="unsupported style"):
        resolve_contract_bundle("atme-style-v1", "atme-assets-v2")


def test_typography_is_bundled_and_svg_has_no_system_font_fallback():
    svg = asset_matrix_svg()
    assert "@font-face" in svg
    assert "data:font/ttf;base64," in svg
    assert "data:font/otf;base64," in svg
    assert "Segoe" not in svg and "Comic Sans" not in svg and "system-ui" not in svg


def test_rasterizer_receives_only_verified_bundled_fonts(monkeypatch):
    import resvg_py

    call = {}

    def capture(**kwargs):
        call.update(kwargs)
        return b"png"

    monkeypatch.setattr(resvg_py, "svg_to_bytes", capture)
    assert preview_asset_matrix() == b"png"
    assert call["skip_system_fonts"] is True
    assert len(call["font_files"]) == 4
    assert all(Path(path).is_file() for path in call["font_files"])


def test_semantic_text_colors_pass_wcag_aa_threshold():
    style, _, _ = load_bundle()
    threshold = style.accessibility.minimum_text_contrast
    for role in ("ink", "muted", "accent", "attention", "success"):
        assert contrast_ratio(style.colors[role], style.colors["paper"]) >= threshold
    assert contrast_ratio(style.colors["caption-fg"], style.colors["caption-bg"]) >= threshold


def test_landscape_and_portrait_have_independent_safe_density_rules():
    style, _, _ = load_bundle()
    landscape = style.aspects["landscape-16:9"]
    portrait = style.aspects["portrait-9:16"]
    assert (landscape.width, landscape.height, landscape.columns) == (1920, 1080, 12)
    assert (portrait.width, portrait.height, portrait.columns) == (1080, 1920, 4)
    assert landscape.safe_area != portrait.safe_area
    assert landscape.density != portrait.density
    assert 'width="1920" height="1080"' in asset_matrix_svg("landscape-16:9")
    assert 'width="1080" height="1920"' in asset_matrix_svg("portrait-9:16")


@pytest.mark.parametrize("profile", ["landscape-16:9", "portrait-9:16"])
def test_preview_export_are_byte_identical_and_deterministic(profile):
    first = preview_asset_matrix(profile)
    second = preview_asset_matrix(profile)
    exported = export_asset_matrix(profile)
    assert first == second == exported
    assert first.startswith(b"\x89PNG\r\n\x1a\n") and len(first) > 40_000
    assert preview_typography_proof(profile) == export_typography_proof(profile)
    assert "One claim, one visible proof." in typography_proof_svg(profile)


def test_contract_rejects_incomplete_family_and_unknown_fields():
    data = json.loads((RESOURCE / "asset-registry.json").read_text(encoding="utf-8"))
    data["assets"][0]["family"] = "gestures"
    with pytest.raises(ValueError, match="family requires at least two"):
        AssetRegistry.model_validate(data)
    style_data = json.loads((RESOURCE / "style.json").read_text(encoding="utf-8"))
    style_data["provider"] = "system-font"
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        PaperInkStyle.model_validate(style_data)


@pytest.mark.parametrize("mutate, message", [
    (lambda value: value["spacing_px"].pop("md"), "spacing scale must define"),
    (lambda value: value["spacing_px"].update({"md": -4}), "spacing scale must be positive"),
    (lambda value: value["accessibility"].pop("minimum_text_contrast"), "minimum_text_contrast"),
    (lambda value: value["accessibility"].update({"minimum_text_contrast": 2.0}),
     "greater than or equal to 4.5"),
    (lambda value: value["aspects"]["landscape-16:9"].update({"width": 1080, "height": 1920,
                                                                 "columns": 4}),
     "landscape-16:9 has invalid dimensions"),
    (lambda value: value["aspects"].pop("portrait-9:16"), "both landscape and portrait"),
    (lambda value: value["strokes"].update({"fine_px": 3.9, "regular_px": 3.0}),
     "stroke widths must increase"),
    (lambda value: value["motion"].update({"draw_min_ms": 900, "draw_max_ms": 300}),
     "draw minimum cannot exceed"),
    (lambda value: value["typography"]["title"].update({"font_id": "atkinson-regular"}),
     "title and label require a display font"),
])
def test_style_rejects_invalid_tokens_and_profiles(mutate, message):
    data = json.loads((RESOURCE / "style.json").read_text(encoding="utf-8"))
    mutate(data)
    with pytest.raises(ValueError, match=message):
        PaperInkStyle.model_validate(data)


@pytest.mark.parametrize("mutate, message", [
    (lambda value: value["assets"][0]["anchors"].pop("center"), "center and semantic anchors"),
    (lambda value: value["assets"][0].update({"keywords": ["person", "Person"]}),
     "asset keywords must be unique"),
    (lambda value: value["assets"][0].update({"file": "assets/person-collaborators.svg"}),
     "asset file must match asset id"),
])
def test_registry_rejects_invalid_asset_metadata(mutate, message):
    data = json.loads((RESOURCE / "asset-registry.json").read_text(encoding="utf-8"))
    mutate(data)
    with pytest.raises(ValueError, match=message):
        AssetRegistry.model_validate(data)


def test_runtime_rejects_svg_viewbox_disagreement(tmp_path, monkeypatch):
    import atme.render.style_bundle as bundle

    copied = tmp_path / "paper-ink-v2"
    shutil.copytree(RESOURCE, copied)
    registry_path = copied / "asset-registry.json"
    data = json.loads(registry_path.read_text(encoding="utf-8"))
    data["assets"][0]["view_box"] = [0, 0, 300, 300]
    registry_path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(bundle, "resource_root", lambda: copied)
    monkeypatch.setattr(bundle, "EXPECTED_REGISTRY_SHA256", digest(registry_path))
    bundle.load_bundle.cache_clear()
    try:
        with pytest.raises(StyleBundleError, match="viewBox does not match"):
            bundle.load_bundle()
    finally:
        bundle.load_bundle.cache_clear()


def test_runtime_rejects_checksum_tampering(tmp_path, monkeypatch):
    import atme.render.style_bundle as bundle

    copied = tmp_path / "paper-ink-v2"
    shutil.copytree(RESOURCE, copied)
    (copied / "assets" / "person-presenter.svg").write_text("<svg/>", encoding="utf-8")
    monkeypatch.setattr(bundle, "resource_root", lambda: copied)
    bundle.load_bundle.cache_clear()
    try:
        with pytest.raises(StyleBundleError, match="checksum mismatch"):
            bundle.load_bundle()
    finally:
        bundle.load_bundle.cache_clear()


@pytest.mark.parametrize("manifest", ["style.json", "asset-registry.json"])
def test_same_version_manifest_mutation_is_rejected(tmp_path, monkeypatch, manifest):
    import atme.render.style_bundle as bundle

    copied = tmp_path / "paper-ink-v2"
    shutil.copytree(RESOURCE, copied)
    path = copied / manifest
    data = json.loads(path.read_text(encoding="utf-8"))
    if manifest == "style.json":
        data["colors"]["accent"] = "#2357D6"
    else:
        data["assets"][0]["keywords"].append("changed")
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(bundle, "resource_root", lambda: copied)
    bundle.load_bundle.cache_clear()
    try:
        with pytest.raises(StyleBundleError, match="checksum mismatch"):
            bundle.load_bundle()
    finally:
        bundle.load_bundle.cache_clear()


def test_generator_is_idempotent():
    tracked = [RESOURCE / "style.json", RESOURCE / "asset-registry.json",
               REPO_ROOT / "schemas" / "paper-ink-style-v2.schema.json",
               REPO_ROOT / "schemas" / "paper-ink-assets-v2.schema.json"]
    before = {path: digest(path) for path in tracked}
    result = subprocess.run(
        [str(REPO_ROOT / "sidecar" / ".venv" / "Scripts" / "python.exe"),
         str(REPO_ROOT / "sidecar" / "tools" / "generate_paper_ink_v2.py")],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert before == {path: digest(path) for path in tracked}


def test_frozen_build_declares_production_resource_bundle():
    spec = (REPO_ROOT / "sidecar" / "atme-sidecar.spec").read_text(encoding="utf-8")
    assert '(str(ROOT / "production-assets"), "production-assets")' in spec


def test_resource_verification_command_runs_from_source():
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(REPO_ROOT / "sidecar" / "src")
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "sidecar" / "launcher.py"), "--verify-style-bundle"],
        cwd=REPO_ROOT, env=environment, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["style_system_id"] == "atme-style-v2"
    assert report["asset_registry_id"] == "atme-assets-v2"
    assert report["asset_count"] == 16
    assert set(report["proof_sha256"]) == {"landscape-16:9", "portrait-9:16"}
