"""Additive code-font trust boundary; this is not code-family admission."""

import importlib
import importlib.util
import json
import os
import shutil
import subprocess
from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
from pathlib import Path

import pytest
from atme.render.style_bundle import (
    EXPECTED_REGISTRY_SHA256,
    EXPECTED_STYLE_SHA256,
    load_bundle,
)
from atme.store.contracts_v2 import ExecutableLayoutV2
from conftest import REPO_ROOT
from PIL import ImageFont
from test_v2_split_capture import geometry_boundary

PREFIX = "code-font-v1/"
RESOURCE = REPO_ROOT / "production-assets" / "paper-ink-v2"


def code_module():
    name = "atme.render.code_font_bundle"
    assert importlib.util.find_spec(name) is not None, "Pinned code-font boundary is missing"
    return importlib.import_module(name)


def code_layout(*, authored=False):
    layout, _, _ = geometry_boundary()
    raw = layout.model_dump(mode="json")
    obj = raw["objects"][0]
    obj.pop("path_data", None)
    obj.update(object_type="code", text="x = 1\nprint(x)", items=[])
    # Font-resource validation does not yet claim that this declared code object
    # has the later authored code payload or an executable primitive adapter.
    if authored:
        obj["style"] = {"stroke": None, "fill": None, "text": "text.code", "effect": None}
        obj["geometry"]["bounds"].update(width=200., height=100.)
        obj["code_payload"] = {"version": "1.0.0", "font_system_id": "atme-code-font-v1",
            "mode": "plain", "tab_size": 4, "lines": [
                {"line_id": f"line-{index}", "spans": [
                    {"span_id": f"span-{index}", "role": "plain", "text": text}]}
                for index, text in enumerate(obj["text"].split("\n"))]}
    return ExecutableLayoutV2.model_validate(raw)


def test_manifest_pins_actual_mono_bytes_license_and_metrics():
    module = code_module()
    bundle = module.load_code_font_bundle()
    manifest = module.CodeFontManifest.model_validate_json(bundle.manifest_json)
    files = {name: (pin, payload) for name, pin, payload in bundle.files}
    assert len(files) == 3
    assert files[module.CODE_FONT_MANIFEST][0] == module.EXPECTED_CODE_FONT_SHA256
    assert manifest.font.role == "code"
    assert manifest.typography.font_id == manifest.font.id
    assert manifest.typography.metrics_charset == "ascii-printable-v1"
    assert manifest.font.family == "JetBrains Mono"
    assert manifest.font.sha256 == "e6fd0d7e91550b3ed2b735d4312474362c4716edc4fc0577a0f61ed782d5aed1"
    assert manifest.font.license_sha256 == "a76abf002c49097d146e86740a3105a5d00450b1592e820a1109a8c5680cd697"
    for pin, payload in files.values():
        assert sha256(payload).hexdigest() == pin
    font = ImageFont.truetype(str(RESOURCE / manifest.font.file), 1000)
    assert font.getname() == ("JetBrains Mono", "Regular")
    assert {font.getlength(chr(i)) for i in range(32, 127)} == {600.0}
    license_text = files[manifest.font.license_file][1].decode("utf-8")
    assert "Copyright 2020 The JetBrains Mono Project Authors" in license_text
    assert "SIL OPEN FONT LICENSE Version 1.1" in license_text
    assert "19371302b95d218af43299bce79ddbddd0bc364d" in manifest.font.source_url
    assert bundle == module.load_code_font_bundle()
    with pytest.raises(FrozenInstanceError):
        bundle.inputs_sha256 = "0" * 64


@pytest.mark.parametrize("field,value", [
    ("contract", "atme.paper-ink-style"), ("version", "2.0.0"),
    ("system_id", "atme-style-v2"), ("font.role", "body"),
    ("font.file", "../../font.ttf"), ("font.license_file", "C:/license.txt"),
    ("font.sha256", "0"), ("font.source_url", "https://example.com/font.ttf"),
    ("font.source_url", "https://raw.githubusercontent.com/JetBrains/JetBrainsMono/master/font.ttf"),
    ("typography.font_id", "atkinson-regular"), ("typography.size_px", 0),
    ("typography.line_height", 0.9), ("typography.max_characters_per_line", 10000),
    ("typography.metrics_charset", "all-unicode"), ("unexpected", True),
])
def test_code_manifest_rejects_wrong_identity_paths_roles_and_metrics(field, value):
    module = code_module()
    raw = json.loads(module.load_code_font_bundle().manifest_json)
    parts = field.split(".")
    target = raw[parts[0]] if len(parts) == 2 else raw
    target[parts[-1]] = value
    with pytest.raises(ValueError):
        module.CodeFontManifest.model_validate(raw)


@pytest.mark.parametrize("target", ["manifest", "font", "license"])
def test_source_loader_rechecks_tampered_or_missing_bytes_after_success(tmp_path, target):
    module = code_module()
    root = tmp_path / "resources"
    shutil.copytree(RESOURCE / "code-font-v1", root / "code-font-v1")
    bundle = module.load_code_font_bundle(root)
    manifest = module.CodeFontManifest.model_validate_json(bundle.manifest_json)
    relative = {"manifest": module.CODE_FONT_MANIFEST, "font": manifest.font.file,
                "license": manifest.font.license_file}[target]
    path = root / relative
    path.write_bytes(path.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="code.font.*checksum"):
        module.load_code_font_bundle(root)
    path.unlink()
    with pytest.raises(ValueError, match="code.font.*missing"):
        module.load_code_font_bundle(root)


def test_font_failure_never_falls_back_to_system_or_legacy_font(tmp_path):
    module = code_module()
    root = tmp_path / "resources"
    shutil.copytree(RESOURCE / "code-font-v1", root / "code-font-v1")
    manifest = module.CodeFontManifest.model_validate_json(module.load_code_font_bundle(root).manifest_json)
    (root / manifest.font.file).write_bytes(b"not a font")
    with pytest.raises(ValueError, match="code.font.*checksum"):
        module.load_code_font_bundle(root)


def test_code_free_split_does_not_load_or_pin_code_resources(monkeypatch):
    from atme.render.v2_split_paint import _verified_split_bundle

    layout, _, _ = geometry_boundary()
    original = Path.read_bytes

    def deny_code(path):
        assert "code-font-v1" not in path.parts, "code-free work loaded optional code resources"
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", deny_code)
    bundle = _verified_split_bundle(layout)
    assert not any(name.startswith(PREFIX) for name, _, _ in bundle.files)
    assert "code_font" not in json.loads(bundle.manifest_json)
    assert sha256((RESOURCE / "style.json").read_bytes()).hexdigest() == EXPECTED_STYLE_SHA256
    assert sha256((RESOURCE / "asset-registry.json").read_bytes()).hexdigest() == EXPECTED_REGISTRY_SHA256


def test_code_layout_requires_exact_conditional_split_resource_inventory():
    module = code_module()
    from atme.render.v2_split_paint import _verified_split_bundle

    plain, _, _ = geometry_boundary()
    original = _verified_split_bundle(plain)
    code = _verified_split_bundle(code_layout())
    expected = module.load_code_font_bundle()
    assert code.style_json == original.style_json
    assert code.registry_json == original.registry_json
    assert tuple(row for row in code.files if not row[0].startswith(PREFIX)) == original.files
    assert tuple(row for row in code.files if row[0].startswith(PREFIX)) == expected.files
    assert json.loads(code.manifest_json)["code_font"] == json.loads(expected.manifest_json)
    assert code.inputs_sha256 != original.inputs_sha256


@pytest.mark.parametrize("target", ["manifest", "font", "license"])
def test_frozen_split_code_resources_reject_coherently_rehashed_tamper_and_missing(target):
    module = code_module()
    from atme.render.v2_split_paint import (
        _checked_split_resources,
        verify_split_paint_inputs,
    )

    layout = code_layout(authored=True)
    inputs = verify_split_paint_inputs(layout, {})
    manifest = module.CodeFontManifest.model_validate_json(module.load_code_font_bundle().manifest_json)
    relative = {"manifest": module.CODE_FONT_MANIFEST, "font": manifest.font.file,
                "license": manifest.font.license_file}[target]
    changed = tuple((name, sha256(payload + b"tamper").hexdigest(), payload + b"tamper")
                    if name == relative else (name, pin, payload)
                    for name, pin, payload in inputs.bundle_bytes)
    with pytest.raises(ValueError, match="code.font.*checksum"):
        _checked_split_resources(layout, replace(inputs, bundle_bytes=changed))
    missing = tuple(row for row in inputs.bundle_bytes if row[0] != relative)
    with pytest.raises(ValueError, match="code.font.*missing"):
        _checked_split_resources(layout, replace(inputs, bundle_bytes=missing))


def test_frozen_code_inputs_do_not_reopen_source_and_plain_inputs_reject_extra_code_rows(monkeypatch):
    module = code_module()
    from atme.render.v2_split_paint import (
        _checked_split_resources,
        verify_split_paint_inputs,
    )

    code = code_layout(authored=True)
    code_inputs = verify_split_paint_inputs(code, {})
    plain, _, _ = geometry_boundary()
    plain_inputs = verify_split_paint_inputs(plain, {})
    extra = module.load_code_font_bundle().files

    def no_source(path):
        raise AssertionError(f"frozen verification reopened {path}")

    monkeypatch.setattr(Path, "read_bytes", no_source)
    checked = _checked_split_resources(code, code_inputs)
    assert {name for name in checked[2] if name.startswith(PREFIX)} == {row[0] for row in extra}
    with pytest.raises(ValueError, match="canonical inputs"):
        _checked_split_resources(plain, replace(plain_inputs, bundle_bytes=plain_inputs.bundle_bytes + extra))


def test_legacy_declared_code_can_load_resources_but_cannot_claim_native_paint():
    from atme.render.v2_split_paint import (
        _verified_split_bundle,
        verify_split_paint_inputs,
    )

    layout = code_layout()
    assert any(name.startswith(PREFIX) for name, _, _ in _verified_split_bundle(layout).files)
    with pytest.raises(ValueError, match="exact code_payload"):
        verify_split_paint_inputs(layout, {})


def test_additive_assets_are_packaged_without_modifying_the_legacy_bundle():
    module = code_module()
    module.load_code_font_bundle()
    style, _, _ = load_bundle()
    assert [font.id for font in style.fonts] == [
        "kalam-regular", "kalam-bold", "atkinson-regular", "atkinson-bold"]
    assert set(style.typography.model_dump()) == {"title", "label", "body", "caption"}
    spec = (REPO_ROOT / "sidecar" / "atme-sidecar.spec").read_text(encoding="utf-8")
    assert '(str(ROOT / "production-assets"), "production-assets")' in spec


def test_advertised_resource_hashes_survive_fresh_windows_checkout(tmp_path):
    module = code_module()
    bundle = module.load_code_font_bundle()
    prefix = "production-assets/paper-ink-v2/"
    paths = [prefix + name for name, _, _ in bundle.files]
    env = {**os.environ, "GIT_INDEX_FILE": str(tmp_path / "isolated-index")}

    def git(*args):
        return subprocess.run(["git", "-c", "core.autocrlf=true", *args], cwd=REPO_ROOT,
                              env=env, check=True, capture_output=True, text=True).stdout

    # Never stage/overwrite the developer's real index. This exact alternate
    # index contains the candidate attributes and all three pinned resources.
    git("read-tree", "HEAD")
    git("add", "--", ".gitattributes", *paths)
    attributes = git("check-attr", "--cached", "text", "eol", "--", *paths)
    for path in paths:
        if path.endswith(".ttf"):
            assert f"{path}: text: unset" in attributes
        else:
            assert f"{path}: text: set" in attributes
            assert f"{path}: eol: lf" in attributes
    checkout = tmp_path / "fresh"
    git("checkout-index", "--prefix=" + checkout.as_posix() + "/", "--", *paths)
    for name, pin, original in bundle.files:
        copied = (checkout / prefix / name).read_bytes()
        assert copied == original
        assert sha256(copied).hexdigest() == pin
    assert module.load_code_font_bundle(checkout / prefix) == bundle
