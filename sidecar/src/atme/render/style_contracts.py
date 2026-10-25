"""Strict contracts for ATME's versioned Paper & Ink production resources."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FontResource(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    family: str
    role: Literal["display", "body"]
    weight: Literal[400, 700]
    file: str = Field(pattern=r"^fonts/[A-Za-z0-9_.-]+\.(?:otf|ttf)$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    license: Literal["OFL-1.1"]
    license_file: str = Field(pattern=r"^fonts/OFL-[A-Za-z0-9_.-]+\.txt$")
    license_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_url: str = Field(pattern=r"^https://raw\.githubusercontent\.com/.+/[0-9a-f]{40}/.+$")


class TypographyRole(StrictModel):
    font_id: str
    size_px: int = Field(ge=18, le=96)
    line_height: float = Field(ge=1.0, le=1.8)
    max_characters_per_line: int = Field(ge=18, le=72)


class Typography(StrictModel):
    title: TypographyRole
    label: TypographyRole
    body: TypographyRole
    caption: TypographyRole


class StrokeTokens(StrictModel):
    fine_px: float = Field(ge=1.0, le=4.0)
    regular_px: float = Field(ge=2.0, le=8.0)
    emphasis_px: float = Field(ge=3.0, le=12.0)
    corner_radius_px: int = Field(ge=2, le=48)
    roughness_px: float = Field(ge=0.0, le=5.0)

    @model_validator(mode="after")
    def ordered_weights(self):
        if not self.fine_px <= self.regular_px <= self.emphasis_px:
            raise ValueError("stroke widths must increase from fine to emphasis")
        return self


class DensityRules(StrictModel):
    max_primary_objects: int = Field(ge=1, le=10)
    max_context_objects: int = Field(ge=1, le=20)
    min_object_gap_px: int = Field(ge=8, le=96)
    min_read_hold_ms: int = Field(ge=500, le=8000)


class SafeArea(StrictModel):
    top_px: int = Field(ge=0)
    right_px: int = Field(ge=0)
    bottom_px: int = Field(ge=0)
    left_px: int = Field(ge=0)


class AspectProfile(StrictModel):
    width: Literal[1080, 1920]
    height: Literal[1080, 1920]
    safe_area: SafeArea
    columns: Literal[4, 12]
    column_gap_px: int = Field(ge=12, le=48)
    density: DensityRules

    @model_validator(mode="after")
    def profile_shape(self):
        is_landscape = self.width > self.height
        if is_landscape != (self.columns == 12):
            raise ValueError("landscape requires 12 columns; portrait requires 4")
        return self


class MotionTokens(StrictModel):
    draw_min_ms: int = Field(ge=100, le=1000)
    draw_max_ms: int = Field(ge=300, le=2000)
    transition_ms: int = Field(ge=100, le=1500)
    emphasis_ms: int = Field(ge=200, le=2500)
    reduced_motion_uses_reveal: bool

    @model_validator(mode="after")
    def valid_draw_range(self):
        if self.draw_min_ms > self.draw_max_ms:
            raise ValueError("draw minimum cannot exceed draw maximum")
        return self


class CaptionTokens(StrictModel):
    max_lines: Literal[1, 2]
    max_characters_per_line: int = Field(ge=20, le=64)
    bottom_safe_offset_px: int = Field(ge=24, le=240)
    background_color_token: str
    foreground_color_token: str


class EvidenceTokens(StrictModel):
    mask_color_token: str
    mask_opacity: float = Field(ge=0.0, le=0.9)
    highlight_color_token: str
    source_label_color_token: str
    min_read_hold_ms: int = Field(ge=1000, le=10000)


class Accessibility(StrictModel):
    minimum_text_contrast: float = Field(ge=4.5, le=21)
    minimum_large_text_contrast: float = Field(ge=3.0, le=21)

    @model_validator(mode="after")
    def valid_thresholds(self):
        if self.minimum_large_text_contrast > self.minimum_text_contrast:
            raise ValueError("large text contrast cannot exceed body text contrast")
        return self


class PaperInkStyle(StrictModel):
    contract: Literal["atme.paper-ink-style"]
    version: Literal["2.0.0"]
    system_id: Literal["atme-style-v2"]
    identity: Literal["ATME Paper & Ink"]
    colors: dict[str, str]
    fonts: list[FontResource] = Field(min_length=4, max_length=8)
    typography: Typography
    spacing_px: dict[str, int]
    strokes: StrokeTokens
    aspects: dict[Literal["landscape-16:9", "portrait-9:16"], AspectProfile]
    motion: MotionTokens
    captions: CaptionTokens
    evidence: EvidenceTokens
    accessibility: Accessibility

    @model_validator(mode="after")
    def references_exist(self):
        font_ids = {font.id for font in self.fonts}
        if len(font_ids) != len(self.fonts):
            raise ValueError("font ids must be unique")
        for role in (self.typography.title, self.typography.label,
                     self.typography.body, self.typography.caption):
            if role.font_id not in font_ids:
                raise ValueError(f"unknown font id: {role.font_id}")
        fonts_by_id = {font.id: font for font in self.fonts}
        for role in (self.typography.title, self.typography.label):
            if fonts_by_id[role.font_id].role != "display":
                raise ValueError("title and label require a display font")
        for role in (self.typography.body, self.typography.caption):
            if fonts_by_id[role.font_id].role != "body":
                raise ValueError("body and caption require a body font")
        if fonts_by_id[self.typography.caption.font_id].weight != 700:
            raise ValueError("captions require a bold body font")
        for name, color in self.colors.items():
            if not isinstance(color, str) or len(color) != 7 or not color.startswith("#"):
                raise ValueError(f"color {name} must use #RRGGBB")
            int(color[1:], 16)
        required = {"paper", "ink", "muted", "accent", "accent-soft", "attention",
                    "success", "evidence-mask", "evidence-highlight", "caption-bg", "caption-fg"}
        if not required.issubset(self.colors):
            raise ValueError(f"missing semantic colors: {sorted(required - set(self.colors))}")
        for token in (self.captions.background_color_token, self.captions.foreground_color_token,
                      self.evidence.mask_color_token, self.evidence.highlight_color_token,
                      self.evidence.source_label_color_token):
            if token not in self.colors:
                raise ValueError(f"unknown color token: {token}")
        spacing_names = ("xs", "sm", "md", "lg", "xl", "xxl")
        if set(self.spacing_px) != set(spacing_names):
            raise ValueError("spacing scale must define xs, sm, md, lg, xl, xxl")
        spacing = [self.spacing_px[name] for name in spacing_names]
        if any(value <= 0 for value in spacing) or spacing != sorted(set(spacing)):
            raise ValueError("spacing scale must be positive and strictly ascending")
        required_profiles = {"landscape-16:9": (1920, 1080, 12), "portrait-9:16": (1080, 1920, 4)}
        if set(self.aspects) != set(required_profiles):
            raise ValueError("both landscape and portrait profiles are required")
        for name, dimensions in required_profiles.items():
            aspect = self.aspects[name]
            if (aspect.width, aspect.height, aspect.columns) != dimensions:
                raise ValueError(f"{name} has invalid dimensions or column count")
            safe = aspect.safe_area
            if safe.left_px + safe.right_px >= aspect.width or safe.top_px + safe.bottom_px >= aspect.height:
                raise ValueError(f"{name} safe area leaves no drawable content")
        if self.motion.draw_min_ms > self.motion.draw_max_ms:
            raise ValueError("draw minimum cannot exceed draw maximum")
        return self


AssetFamily = Literal[
    "people", "gestures", "devices", "documents", "networks", "charts",
    "technical-frames", "abstract-metaphors",
]


class AssetProvenance(StrictModel):
    origin: Literal["ATME-original"]
    author: Literal["ATME project"]
    created_for: Literal["ATME Paper & Ink v2"]
    derivative_of_reference_art: Literal[False]
    license: Literal["ATME-project"]


class AssetEntry(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    family: AssetFamily
    file: str = Field(pattern=r"^assets/[a-z0-9-]+\.svg$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    view_box: tuple[int, int, int, int]
    keywords: list[str] = Field(min_length=2, max_length=12)
    anchors: dict[str, tuple[float, float]]
    provenance: AssetProvenance

    @model_validator(mode="after")
    def valid_geometry(self):
        if self.view_box[0:2] != (0, 0) or self.view_box[2] <= 0 or self.view_box[3] <= 0:
            raise ValueError("asset viewBox must start at zero and have positive dimensions")
        if "center" not in self.anchors or len(self.anchors) < 2:
            raise ValueError("asset must declare center and semantic anchors")
        if self.file != f"assets/{self.id}.svg":
            raise ValueError("asset file must match asset id")
        if len({keyword.casefold() for keyword in self.keywords}) != len(self.keywords):
            raise ValueError("asset keywords must be unique")
        for name, point in self.anchors.items():
            if not name or not all(0.0 <= coordinate <= 1.0 for coordinate in point):
                raise ValueError("asset anchors must be named normalized points")
        return self


class AssetRegistry(StrictModel):
    contract: Literal["atme.paper-ink-assets"]
    version: Literal["2.0.0"]
    registry_id: Literal["atme-assets-v2"]
    style_version: Literal["2.0.0"]
    style_system_id: Literal["atme-style-v2"]
    assets: list[AssetEntry] = Field(min_length=16)

    @model_validator(mode="after")
    def complete_families(self):
        ids = {asset.id for asset in self.assets}
        if len(ids) != len(self.assets):
            raise ValueError("asset ids must be unique")
        if len({asset.file for asset in self.assets}) != len(self.assets):
            raise ValueError("asset files must be unique")
        expected = {"people", "gestures", "devices", "documents", "networks", "charts",
                    "technical-frames", "abstract-metaphors"}
        counts = {family: sum(asset.family == family for asset in self.assets) for family in expected}
        incomplete = sorted(family for family, count in counts.items() if count < 2)
        if incomplete:
            raise ValueError(f"each asset family requires at least two originals: {incomplete}")
        return self
