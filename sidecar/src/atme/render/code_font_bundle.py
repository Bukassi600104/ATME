"""Additive pinned code typography; the Paper & Ink 2.0.0 bundle is untouched.

Resource verification is not code-object or Split-family admission. Producers
and frozen consumers use the same current pins and bytes, without system-font
fallback, a mutable cache, or a runtime network dependency.
"""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Literal

from PIL import ImageFont
from pydantic import BaseModel, ConfigDict, Field, model_validator

from atme.render.style_bundle import resource_root

CODE_FONT_MANIFEST = "code-font-v1/code-font.json"
EXPECTED_CODE_FONT_SHA256 = "3285149d5c04493582e40f03c446d1e65e6d37170afe20a223e114e32f4bc73e"
_SOURCE = r"^https://raw\.githubusercontent\.com/.+/[0-9a-f]{40}/.+$"


class CodeFontBundleError(ValueError):
    pass


class _StrictCodeFontModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)


class CodeFontResource(_StrictCodeFontModel):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    family: str = Field(min_length=1)
    role: Literal["code"]
    weight: Literal[400]
    file: str = Field(pattern=r"^code-font-v1/fonts/[A-Za-z0-9_-]+\.ttf$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    license: Literal["OFL-1.1"]
    license_file: str = Field(pattern=r"^code-font-v1/fonts/OFL-[A-Za-z0-9_-]+\.txt$")
    license_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_url: str = Field(pattern=_SOURCE)
    license_source_url: str = Field(pattern=_SOURCE)


class CodeTypography(_StrictCodeFontModel):
    font_id: str = Field(min_length=1)
    size_px: int = Field(ge=18, le=96)
    line_height: float = Field(ge=1.0, le=1.8)
    max_characters_per_line: int = Field(ge=18, le=72)
    advance_em: float = Field(gt=0, le=2)
    metrics_charset: Literal["ascii-printable-v1"]


class CodeFontManifest(_StrictCodeFontModel):
    contract: Literal["atme.code-font-bundle"]
    version: Literal["1.0.0"]
    system_id: Literal["atme-code-font-v1"]
    font: CodeFontResource
    typography: CodeTypography

    @model_validator(mode="after")
    def exact_resource_reference(self):
        if self.typography.font_id != self.font.id:
            raise ValueError("code-font typography must reference its exact pinned resource")
        return self


@dataclass(frozen=True)
class VerifiedCodeFontBundle:
    manifest_json: str
    files: tuple[tuple[str, str, bytes], ...] = field(repr=False)
    inputs_sha256: str


def verify_code_font_bundle(read_payload: Callable[[str], bytes]) -> VerifiedCodeFontBundle:
    """Verify source or already frozen bytes against the same immutable pins."""
    checked = {}

    def read(relative, expected):
        try:
            payload = read_payload(relative)
        except (OSError, KeyError) as exc:
            raise CodeFontBundleError(f"code-font resource missing: {relative}") from exc
        if type(payload) is not bytes or sha256(payload).hexdigest() != expected:
            raise CodeFontBundleError(f"code-font resource checksum mismatch: {relative}")
        checked[relative] = (expected, payload)
        return payload

    raw = read(CODE_FONT_MANIFEST, EXPECTED_CODE_FONT_SHA256)
    manifest = CodeFontManifest.model_validate_json(raw)
    font = manifest.font
    payload = read(font.file, font.sha256)
    read(font.license_file, font.license_sha256)
    # Decode the pinned bytes using the existing measuring engine. A declaration
    # of "mono" is not proof, and font failure must not select another family.
    # This manifest promises printable-ASCII advances, not universal Unicode
    # coverage. The later code primitive must check every admitted payload glyph.
    try:
        measuring_font = ImageFont.truetype(io.BytesIO(payload), 1000)
        advances = {measuring_font.getlength(chr(code)) for code in range(32, 127)}
        if (measuring_font.getname() != (font.family, "Regular")
                or advances != {manifest.typography.advance_em * 1000}):
            raise CodeFontBundleError("code-font bytes differ from their family/mono metrics")
    except OSError as exc:
        raise CodeFontBundleError("code-font bytes cannot be decoded") from exc
    canonical = json.dumps(manifest.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    receipt = json.dumps({"manifest": json.loads(canonical),
                          "files": {name: pin for name, (pin, _) in sorted(checked.items())}},
                         sort_keys=True, separators=(",", ":"))
    return VerifiedCodeFontBundle(canonical, tuple((name, *row) for name, row in sorted(checked.items())),
                                  sha256(receipt.encode()).hexdigest())


def load_code_font_bundle(root: Path | None = None) -> VerifiedCodeFontBundle:
    """Rehash current packaged bytes on every call; no cache is an attestation."""
    root = (resource_root() if root is None else root).resolve()

    def read(relative):
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise CodeFontBundleError("code-font resource escaped its pinned root")
        return path.read_bytes()

    return verify_code_font_bundle(read)
