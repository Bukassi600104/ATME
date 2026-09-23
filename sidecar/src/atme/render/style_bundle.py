"""Load, validate, and render the pinned ATME Paper & Ink v2 resource bundle."""

from __future__ import annotations

import base64
import hashlib
import re
import sys
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path

from atme.render.style_contracts import AssetRegistry, PaperInkStyle


class StyleBundleError(ValueError):
    pass


# These hashes are the immutable meaning of the 2.0.0 bundle. Any intentional
# resource or token change requires a new contract version and new pins.
EXPECTED_STYLE_SHA256 = "47189551d03658bae88efcc33b7c60c3776a6faa190f8dc693ad6b8354ea8ca1"
EXPECTED_REGISTRY_SHA256 = "1bd82badacb571438d9fe4c858f7d17209be0877153a1f05d2fb224666891985"


def resource_root() -> Path:
    candidates = []
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        candidates.extend((base / "production-assets" / "paper-ink-v2",
                           Path(sys.executable).parent / "_internal" / "production-assets" / "paper-ink-v2"))
    candidates.append(Path(__file__).resolve().parents[4] / "production-assets" / "paper-ink-v2")
    for candidate in candidates:
        if (candidate / "style.json").is_file() and (candidate / "asset-registry.json").is_file():
            return candidate
    raise StyleBundleError("ATME Paper & Ink v2 resources are missing")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _verified_file(root: Path, relative: str, expected: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise StyleBundleError(f"resource escaped or is missing: {relative}")
    actual = _sha256(path)
    if actual != expected:
        raise StyleBundleError(f"resource checksum mismatch: {relative}")
    return path


def _channel(value: int) -> float:
    component = value / 255
    return component / 12.92 if component <= 0.04045 else ((component + 0.055) / 1.055) ** 2.4


def contrast_ratio(a: str, b: str) -> float:
    def luminance(color: str) -> float:
        values = [int(color[index:index + 2], 16) for index in (1, 3, 5)]
        red, green, blue = (_channel(value) for value in values)
        return 0.2126 * red + 0.7152 * green + 0.0722 * blue
    left, right = luminance(a), luminance(b)
    return (max(left, right) + 0.05) / (min(left, right) + 0.05)


def _validate_svg(path: Path, expected_view_box: tuple[int, int, int, int]) -> None:
    text = path.read_text(encoding="utf-8")
    lowered = text.lower()
    if any(token in lowered for token in ("<script", "<image", "<foreignobject", "javascript:")):
        raise StyleBundleError(f"unsafe SVG content: {path.name}")
    if re.search(r"(?:href|src)\s*=\s*['\"](?:https?:|//)", lowered):
        raise StyleBundleError(f"external SVG reference: {path.name}")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise StyleBundleError(f"invalid SVG: {path.name}") from exc
    if root.tag != "{http://www.w3.org/2000/svg}svg":
        raise StyleBundleError(f"resource is not SVG: {path.name}")
    actual_view_box = root.attrib.get("viewBox")
    if actual_view_box != " ".join(str(value) for value in expected_view_box):
        raise StyleBundleError(f"asset viewBox does not match registry: {path.name}")
    allowed_vars = {"var(--paper)", "var(--ink)", "var(--muted)", "var(--accent)", "var(--accent-soft)"}
    found = set(re.findall(r"var\(--[a-z-]+\)", text))
    if not found.issubset(allowed_vars):
        raise StyleBundleError(f"unknown SVG style token in {path.name}: {sorted(found - allowed_vars)}")


@lru_cache(maxsize=1)
def load_bundle() -> tuple[PaperInkStyle, AssetRegistry, Path]:
    root = resource_root().resolve()
    _verified_file(root, "style.json", EXPECTED_STYLE_SHA256)
    _verified_file(root, "asset-registry.json", EXPECTED_REGISTRY_SHA256)
    style = PaperInkStyle.model_validate_json((root / "style.json").read_text(encoding="utf-8"))
    registry = AssetRegistry.model_validate_json((root / "asset-registry.json").read_text(encoding="utf-8"))
    if registry.style_version != style.version or registry.style_system_id != style.system_id:
        raise StyleBundleError("asset registry is not compatible with the Paper & Ink style")
    for font in style.fonts:
        _verified_file(root, font.file, font.sha256)
        license_path = (root / font.license_file).resolve()
        if not license_path.is_relative_to(root) or not license_path.is_file():
            raise StyleBundleError(f"font license is missing: {font.license_file}")
        if _sha256(license_path) != font.license_sha256:
            raise StyleBundleError(f"font license checksum mismatch: {font.license_file}")
    for asset in registry.assets:
        path = _verified_file(root, asset.file, asset.sha256)
        _validate_svg(path, asset.view_box)
    threshold = style.accessibility.minimum_text_contrast
    paper = style.colors["paper"]
    for role in ("ink", "muted", "accent", "attention", "success"):
        if contrast_ratio(style.colors[role], paper) < threshold:
            raise StyleBundleError(f"{role} fails minimum text contrast")
    if contrast_ratio(style.colors[style.captions.foreground_color_token],
                      style.colors[style.captions.background_color_token]) < threshold:
        raise StyleBundleError("caption colors fail minimum text contrast")
    return style, registry, root


def resolve_contract_bundle(style_system_version: str, asset_registry_version: str):
    """Resolve the exact identifiers advertised by visual-production v2 contracts."""
    style, registry, root = load_bundle()
    if style_system_version != style.system_id or asset_registry_version != registry.registry_id:
        raise StyleBundleError("unsupported style or asset registry version")
    return style, registry, root


def _font_css(style: PaperInkStyle, root: Path) -> str:
    rules = []
    for font in style.fonts:
        path = _verified_file(root, font.file, font.sha256)
        mime = "font/ttf" if path.suffix == ".ttf" else "font/otf"
        payload = base64.b64encode(path.read_bytes()).decode("ascii")
        rules.append(
            f"@font-face{{font-family:'{font.family}';font-style:normal;"
            f"font-weight:{font.weight};src:url(data:{mime};base64,{payload})}}"
        )
    return "".join(rules)


def _asset_inner(path: Path, colors: dict[str, str]) -> str:
    text = path.read_text(encoding="utf-8")
    inner = re.sub(r"^\s*<svg[^>]*>", "", text, count=1)
    inner = re.sub(r"</svg>\s*$", "", inner, count=1)
    for token in ("paper", "ink", "muted", "accent", "accent-soft"):
        inner = inner.replace(f"var(--{token})", colors[token])
    return inner


def asset_matrix_svg(profile: str = "landscape-16:9") -> str:
    style, registry, root = load_bundle()
    if profile not in style.aspects:
        raise StyleBundleError(f"unknown aspect profile: {profile}")
    aspect = style.aspects[profile]
    width, height = aspect.width, aspect.height
    columns = 4 if width > height else 2
    rows = (len(registry.assets) + columns - 1) // columns
    margin_x, margin_y = aspect.safe_area.left_px, aspect.safe_area.top_px
    cell_w = (width - margin_x - aspect.safe_area.right_px) / columns
    cell_h = (height - margin_y - aspect.safe_area.bottom_px) / rows
    display_family = next(font.family for font in style.fonts if font.id == style.typography.label.font_id)
    body = [f'<rect width="{width}" height="{height}" fill="{style.colors["paper"]}"/>']
    for index, asset in enumerate(registry.assets):
        column, row = index % columns, index // columns
        x, y = margin_x + column * cell_w, margin_y + row * cell_h
        available_h = cell_h - 34
        scale = min((cell_w - 28) / asset.view_box[2], (available_h - 12) / asset.view_box[3])
        tx = x + (cell_w - asset.view_box[2] * scale) / 2
        ty = y + 4
        path = _verified_file(root, asset.file, asset.sha256)
        body.append(f'<g transform="translate({tx:.2f} {ty:.2f}) scale({scale:.5f})">'
                    f'{_asset_inner(path, style.colors)}</g>')
        body.append(f'<text x="{x + cell_w / 2:.2f}" y="{y + cell_h - 6:.2f}" '
                    f'text-anchor="middle" font-family="{display_family}" font-weight="700" '
                    f'font-size="{style.typography.label.size_px}" fill="{style.colors["ink"]}">{asset.id}</text>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}"><style>{_font_css(style, root)}</style>{"".join(body)}</svg>')


def typography_proof_svg(profile: str = "landscape-16:9") -> str:
    """Static visual proof of the same typography, contrast, and safe-area rules used by v2."""
    style, _, root = load_bundle()
    if profile not in style.aspects:
        raise StyleBundleError(f"unknown aspect profile: {profile}")
    aspect = style.aspects[profile]
    width, height = aspect.width, aspect.height
    safe = aspect.safe_area
    left, right = safe.left_px, width - safe.right_px
    top, bottom = safe.top_px, height - safe.bottom_px
    landscape = width > height
    display = next(font.family for font in style.fonts if font.id == style.typography.title.font_id)
    body = next(font.family for font in style.fonts if font.id == style.typography.body.font_id)
    caption = next(font.family for font in style.fonts if font.id == style.typography.caption.font_id)
    title_y = top + (100 if landscape else 130)
    body_y = title_y + (92 if landscape else 115)
    body_lines = (["A shared model lets each step build on the last."] if landscape else
                  ["A shared model lets each step", "build on the last."])
    body_elements = "".join(
        f'<text x="{left + 32}" y="{body_y + index * 50}" font-family="{body}" '
        f'font-size="{style.typography.body.size_px}" fill="{style.colors["ink"]}">{line}</text>'
        for index, line in enumerate(body_lines)
    )
    evidence_top = body_y + (110 if landscape else 180)
    evidence_height = min(270 if landscape else 380, bottom - evidence_top - 145)
    evidence_width = min(780 if landscape else right - left - 64, right - left - 64)
    evidence_x = left + 32
    caption_y = bottom - (85 if landscape else 110)
    markup = (
        f'<rect width="{width}" height="{height}" fill="{style.colors["paper"]}"/>'
        f'<rect x="{left}" y="{top}" width="{right-left}" height="{bottom-top}" '
        f'rx="{style.strokes.corner_radius_px}" fill="none" stroke="{style.colors["muted"]}" '
        'stroke-dasharray="10 10" opacity="0.65"/>'
        f'<text x="{left+32}" y="{top+42}" font-family="{body}" font-size="22" '
        f'fill="{style.colors["muted"]}">ATME PAPER &amp; INK / {profile.upper()}</text>'
        f'<text x="{left+32}" y="{title_y}" font-family="{display}" font-weight="700" '
        f'font-size="{style.typography.title.size_px}" fill="{style.colors["ink"]}">Ideas become clear.</text>'
        f'{body_elements}'
        f'<rect x="{evidence_x}" y="{evidence_top}" width="{evidence_width}" '
        f'height="{evidence_height}" rx="14" fill="{style.colors["accent-soft"]}" '
        f'stroke="{style.colors["ink"]}" stroke-width="{style.strokes.regular_px}"/>'
        f'<text x="{evidence_x+26}" y="{evidence_top+50}" font-family="{body}" '
        f'font-size="{style.typography.body.size_px}" fill="{style.colors["ink"]}">SOURCE NOTE</text>'
        f'<rect x="{evidence_x+26}" y="{evidence_top+83}" width="{evidence_width-52}" '
        f'height="20" fill="{style.colors["evidence-highlight"]}"/>'
        f'<text x="{evidence_x+26}" y="{evidence_top+146}" font-family="{body}" '
        f'font-size="{style.typography.body.size_px}" fill="{style.colors["ink"]}">One claim, one visible proof.</text>'
        f'<text x="{evidence_x+26}" y="{evidence_top+190}" font-family="{body}" '
        f'font-size="{style.typography.caption.size_px}" fill="{style.colors["muted"]}">Source: original ATME specimen</text>'
        f'<rect x="{left+32}" y="{caption_y-45}" width="{right-left-64}" height="75" '
        f'rx="12" fill="{style.colors["caption-bg"]}"/>'
        f'<text x="{width/2}" y="{caption_y+4}" text-anchor="middle" font-family="{caption}" '
        f'font-weight="700" font-size="{style.typography.caption.size_px}" '
        f'fill="{style.colors["caption-fg"]}">Show the connection, then let it settle.</text>'
    )
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}"><style>{_font_css(style, root)}</style>{markup}</svg>')


def _render_png(svg: str, profile: str) -> bytes:
    import resvg_py

    style, _, _ = load_bundle()
    root = resource_root().resolve()
    aspect = style.aspects[profile]
    font_files = [str(_verified_file(root, font.file, font.sha256)) for font in style.fonts]
    return bytes(resvg_py.svg_to_bytes(
        svg_string=svg, width=aspect.width, height=aspect.height,
        background=style.colors["paper"], font_files=font_files, skip_system_fonts=True,
    ))


def preview_asset_matrix(profile: str = "landscape-16:9") -> bytes:
    return _render_png(asset_matrix_svg(profile), profile)


def export_asset_matrix(profile: str = "landscape-16:9") -> bytes:
    return _render_png(asset_matrix_svg(profile), profile)


def preview_typography_proof(profile: str = "landscape-16:9") -> bytes:
    return _render_png(typography_proof_svg(profile), profile)


def export_typography_proof(profile: str = "landscape-16:9") -> bytes:
    return _render_png(typography_proof_svg(profile), profile)
