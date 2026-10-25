"""Private Split paint consumers; no public action or family admission here."""

import io
import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from hashlib import sha256
from itertools import pairwise
from math import ceil, isfinite

from PIL import Image

from atme.project_assets import (
    VerifiedEvidenceBytes,
    VerifiedImageBytes,
    VerifiedMediaBytes,
)
from atme.render.style_bundle import (
    EXPECTED_REGISTRY_SHA256,
    EXPECTED_STYLE_SHA256,
    load_bundle,
)
from atme.render.style_contracts import AssetRegistry, PaperInkStyle
from atme.render.v2_raster import canonical_png
from atme.render.v2_split import (
    SplitCapture,
    SplitPaintEnvelope,
    _validate_capture_inventory,
)
from atme.render.v2_split_clock import split_phase_progress
from atme.render.v2_state import FrameSnapshot, SplitFrameSnapshot
from atme.store.contracts_v2 import (
    MEDIA_OBJECT_TYPES,
    ClipContainer,
    ConnectorObject,
    EvidenceAction,
    EvidenceTreatment,
    ExecutableLayoutV2,
    GroupContainer,
    MarkObject,
    MaskContainer,
    ResolvedAsset,
    SplitAction,
    SplitAssetPin,
    SplitBasis,
    SplitPolicy,
    TextObject,
    VisualObject,
)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


@dataclass(frozen=True)
class _SplitPrimitivePaint:
    """One primitive dispatcher; temporal coverage/public admission is separate."""
    family: str
    object_class: type
    modes: frozenset[str]
    proof_kind: str
    paint_evidence: Callable | None


def _split_primitive_context(obj, layout, resources):
    from atme.render.v2_svg import _preflight_object

    style = resources[0]
    profile = "landscape-16:9" if layout.output_profile.profile_id == "LONG_FORM_16_9" else "portrait-9:16"
    design = style.aspects[profile]
    scale = layout.output_profile.width / design.width
    if abs(scale - layout.output_profile.height / design.height) > 1e-6:
        raise ValueError("Split paint requires uniform profile scale")
    _preflight_object(obj, style, None, scale, {item.object_id: item for item in layout.objects}, resources=resources)
    return style, scale


@lru_cache(maxsize=128)
def _geometry_alpha_facts(svg):
    """Immutable facts for an exact validated, self-contained geometry SVG.

    This sits below all carrier/checksum/geometry checks. It never caches
    author claims, admission, glyphs, compositor frames or coverage decisions.
    """
    import resvg_py

    with Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=svg, skip_system_fonts=True))) as image:
        alpha = image.convert("RGBA").getchannel("A")
        return alpha.getbbox(), alpha.size, sha256(alpha.tobytes()).hexdigest()


def _split_path_evidence(obj, layout, resources):

    from atme.render.v2_svg import _color, _shape

    style, scale = _split_primitive_context(obj, layout, resources)
    stroke = _color(obj.style.stroke, style.colors, default=style.colors[
        "attention" if obj.object_type == "highlight" else "accent" if obj.object_type == "underline" else "ink"])
    fill = _color(obj.style.fill, style.colors, default="none")
    weight = (style.strokes.emphasis_px if obj.object_type == "highlight" else style.strokes.regular_px) * scale
    # The native construction adapter proves positive rendered path length,
    # including rounded/curved/freehand geometry. A nonempty bounds box cannot.
    partial = _shape(obj, stroke, fill, weight, draw_fraction=.5)
    full = _shape(obj, stroke, fill, weight)
    bounds = obj.geometry.bounds
    width, height = layout.output_profile.width, layout.output_profile.height
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
           f'viewBox="{bounds.x - weight} {bounds.y - weight} '
           f'{bounds.width + 2 * weight} {bounds.height + 2 * weight}">{full}</svg>')
    painted, size, alpha_sha256 = _geometry_alpha_facts(svg)
    if painted is None:
        raise ValueError(f"Split geometry {obj.object_id} has no painted pixels")
    return {"full_svg_sha256": sha256(full.encode()).hexdigest(),
            "constructed_path_sha256": sha256(partial.encode()).hexdigest(), "stroke_width": weight,
            "alpha_bounds": painted, "alpha_size": size,
            "alpha_sha256": alpha_sha256}


def _split_glyph_evidence(obj, layout, resources):
    if type(obj) is TextObject and obj.object_type == "code":
        return _split_code_glyph_evidence(obj, layout, resources)
    if type(obj) is TextObject and obj.object_type == "callout":
        return _split_callout_glyph_evidence(obj, layout, resources)
    from atme.render.v2_svg import (
        SVGFrame,
        _color,
        _font,
        _rasterize_frozen_svg,
        _text,
        _text_role,
    )

    style, scale = _split_primitive_context(obj, layout, resources)
    role = _text_role(obj, style)
    font = next(item for item in style.fonts if item.id == role.font_id)
    payload = resources[2][font.file]
    measuring_font = _font(payload, max(1, ceil(role.size_px * scale)))
    lines = obj.text.splitlines() if obj.object_type != "list" else [obj.text, *(f"• {item}" for item in obj.items)]
    masks = [measuring_font.getmask(line) for line in lines]
    bounds = obj.geometry.bounds
    inner = _text(obj, _color(obj.style.text, style.colors, default=style.colors["ink"]),
                  font.family, font.weight, role.size_px * scale, role.line_height,
                  role.max_characters_per_line, payload)
    width, height = layout.output_profile.width, layout.output_profile.height
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
           f'viewBox="{bounds.x} {bounds.y} {bounds.width} {bounds.height}">{inner}</svg>')
    raster = _rasterize_frozen_svg(SVGFrame(0, width, height, svg), style, resources[2])
    with Image.open(io.BytesIO(raster.png)) as image:
        alpha = image.convert("RGBA").getchannel("A")
        painted = alpha.getbbox()
    # Pillow metrics alone are insufficient: its missing-glyph box can be
    # nonempty when the actual SVG shaper paints nothing (e.g. U+200B).
    if painted is None:
        raise ValueError(f"Split text {obj.object_id} has no painted glyphs")
    return {"font_sha256": sha256(payload).hexdigest(), "font_size": role.size_px * scale,
            "line_height": role.line_height, "lines": lines,
            "svg_sha256": sha256(inner.encode()).hexdigest(), "alpha_bounds": painted,
            "alpha_size": alpha.size, "alpha_sha256": sha256(alpha.tobytes()).hexdigest(),
            "glyph_alpha": [{"bounds": mask.getbbox(), "size": mask.size,
                              "sha256": sha256(bytes(mask)).hexdigest()} for mask in masks]}


def _split_callout_glyph_evidence(obj, layout, resources):
    """Body-only native facts, not admission of a bound pointer relationship.

    This reuses the owning box/inset/text primitive. The leader is never part
    of this paint. Registry admission still needs its captured lifecycle proof.
    """
    from atme.render.v2_callout import callout_body_svg
    from atme.render.v2_svg import SVGFrame, _rasterize_frozen_svg, _text_role

    style, scale = _split_primitive_context(obj, layout, resources)
    role = _text_role(obj, style)
    font = next(item for item in style.fonts if item.id == role.font_id)
    payload = resources[2][font.file]
    inner = callout_body_svg(obj, style, scale, payload)
    glyph = inner
    if obj.style.stroke is not None or obj.style.fill is not None:
        # Strip only the owning primitive's first explicit box, retaining its
        # exact derived glyph placement. Box alpha cannot attest an empty label.
        box, separator, glyph = inner.partition("/>")
        if not box.startswith("<rect ") or not separator:
            raise ValueError("Split Callout native body has an unexpected box structure")
    bounds = obj.geometry.bounds
    width, height = layout.output_profile.width, layout.output_profile.height
    evidence = {"callout_binding": obj.callout_binding.model_dump(mode="json"),
        "font_sha256": sha256(payload).hexdigest(), "font_size": role.size_px * scale,
        "line_height": role.line_height, "lines": obj.text.splitlines(),
        "svg_sha256": sha256(inner.encode()).hexdigest()}
    for prefix, markup in (("body", inner), ("glyph", glyph)):
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="{bounds.x} {bounds.y} {bounds.width} {bounds.height}">{markup}</svg>')
        raster = _rasterize_frozen_svg(SVGFrame(0, width, height, svg), style, resources[2])
        with Image.open(io.BytesIO(raster.png)) as image:
            alpha = image.convert("RGBA").getchannel("A")
            painted = alpha.getbbox()
        if painted is None:
            raise ValueError(f"Split Callout {obj.object_id} has no painted glyphs")
        evidence.update({f"{prefix}_alpha_bounds": painted, f"{prefix}_alpha_size": alpha.size,
                         f"{prefix}_alpha_sha256": sha256(alpha.tobytes()).hexdigest()})
    return evidence


def _split_code_glyph_evidence(obj, layout, resources):
    """Use the owning code primitive and freshly verified frozen mono bytes."""
    from atme.render.code_font_bundle import CodeFontManifest, verify_code_font_bundle
    from atme.render.v2_code import code_svg
    from atme.render.v2_svg import SVGFrame, _rasterize_frozen_svg

    style, scale = _split_primitive_context(obj, layout, resources)
    bundle = verify_code_font_bundle(resources[2].__getitem__)
    manifest = CodeFontManifest.model_validate_json(bundle.manifest_json)
    inner = code_svg(obj, style, scale, bundle)
    bounds = obj.geometry.bounds
    width, height = layout.output_profile.width, layout.output_profile.height
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
           f'viewBox="{bounds.x} {bounds.y} {bounds.width} {bounds.height}">{inner}</svg>')
    raster = _rasterize_frozen_svg(SVGFrame(0, width, height, svg), style, resources[2])
    with Image.open(io.BytesIO(raster.png)) as image:
        alpha = image.convert("RGBA").getchannel("A")
        painted = alpha.getbbox()
    if painted is None:
        raise ValueError(f"Split code {obj.object_id} has no painted glyphs")
    return {"font_sha256": manifest.font.sha256, "font_size": manifest.typography.size_px * scale,
            "line_height": manifest.typography.line_height,
            "code_payload": obj.code_payload.model_dump(mode="json"),
            "svg_sha256": sha256(inner.encode()).hexdigest(), "alpha_bounds": painted,
            "alpha_size": alpha.size, "alpha_sha256": sha256(alpha.tobytes()).hexdigest()}


def _split_registry_evidence(obj, layout, resources):
    import resvg_py

    from atme.render.v2_svg import _registry_visual

    _split_primitive_context(obj, layout, resources)
    asset = next(item for item in resources[1].assets if item.id == obj.variant)
    bounds = obj.geometry.bounds
    inner = _registry_visual(obj, resources)
    # Native pinned registry resolution; transparent backing, no system fonts,
    # and the same contain placement as actual composition. No source-file read.
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{asset.view_box[2]}" '
           f'height="{asset.view_box[3]}" viewBox="{bounds.x} {bounds.y} {bounds.width} {bounds.height}">'
           f'{inner}</svg>')
    png = resvg_py.svg_to_bytes(svg_string=svg, skip_system_fonts=True)
    with Image.open(io.BytesIO(png)) as image:
        alpha = image.convert("RGBA").getchannel("A")
        painted = alpha.getbbox()
        if painted is None:
            raise ValueError(f"Split registry {obj.object_id} has no painted pixels")
        return {"asset_sha256": asset.sha256, "svg_sha256": sha256(inner.encode()).hexdigest(),
                "alpha_bounds": painted, "alpha_size": alpha.size,
                "alpha_sha256": sha256(alpha.tobytes()).hexdigest()}


def _split_technical_chrome_evidence(obj, layout, resources):
    """Prove the owning native chrome, never authenticate it as registry art."""
    import resvg_py

    from atme.render.v2_svg import _color
    from atme.render.v2_technical_frame import technical_frame_svg

    style, scale = _split_primitive_context(obj, layout, resources)
    inner = technical_frame_svg(obj,
        stroke=_color(obj.style.stroke, style.colors, default=style.colors["ink"]),
        fill=_color(obj.style.fill, style.colors, default="none"),
        stroke_width=style.strokes.regular_px * scale)
    bounds = obj.geometry.bounds
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{ceil(bounds.width)}" '
           f'height="{ceil(bounds.height)}" viewBox="{bounds.x} {bounds.y} {bounds.width} {bounds.height}">'
           f'{inner}</svg>')
    png = resvg_py.svg_to_bytes(svg_string=svg, skip_system_fonts=True)
    with Image.open(io.BytesIO(png)) as image:
        alpha = image.convert("RGBA").getchannel("A")
        painted = alpha.getbbox()
        if painted is None:
            raise ValueError(f"Split technical chrome {obj.object_id} has no painted pixels")
        return {"native_kind": obj.object_type, "display_state": obj.technical_frame.display_state,
                "svg_sha256": sha256(inner.encode()).hexdigest(), "alpha_bounds": painted,
                "alpha_size": alpha.size, "alpha_sha256": sha256(alpha.tobytes()).hexdigest()}


def _split_chart_evidence(obj, layout, resources):
    """Authenticate the owning data painter, pinned labels and authored clock.

    This is primitive evidence, not continuous handoff proof. Split coverage
    still uses the existing all-integer-ms shared compositor scan.
    """
    from atme.render.v2_chart import chart_svg
    from atme.render.v2_svg import SVGFrame, _rasterize_frozen_svg

    style, scale = _split_primitive_context(obj, layout, resources)
    full = chart_svg(obj, style, scale, resources[2])
    partial = chart_svg(obj, style, scale, resources[2], draw_fraction=.5)
    bounds = obj.geometry.bounds
    width, height = layout.output_profile.width, layout.output_profile.height
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
           f'viewBox="{bounds.x} {bounds.y} {bounds.width} {bounds.height}">{full}</svg>')
    raster = _rasterize_frozen_svg(SVGFrame(0, width, height, svg), style, resources[2])
    with Image.open(io.BytesIO(raster.png)) as image:
        alpha = image.convert("RGBA").getchannel("A")
        painted = alpha.getbbox()
    if painted is None:
        raise ValueError(f"Split chart {obj.object_id} has no painted data or labels")
    return {"payload": obj.chart_payload.model_dump(mode="json"),
        "svg_sha256": sha256(full.encode()).hexdigest(),
        "constructed_svg_sha256": sha256(partial.encode()).hexdigest(),
        "alpha_bounds": painted, "alpha_size": alpha.size,
        "alpha_sha256": sha256(alpha.tobytes()).hexdigest()}


def _split_image_evidence(obj, layout, resources):
    """Native placed original PNG alpha; temporal/world proof stays separate."""
    from dataclasses import replace

    from atme.render.v2_state import FrameObject, FramePoint, FrameTransform
    from atme.render.v2_svg import SVGFrame, _object_markup, _rasterize_frozen_svg

    style, scale = _split_primitive_context(obj, layout, resources)
    treatments = {}
    if obj.object_type == "evidence":
        matching = [row for row in layout.evidence_treatments if row.object_id == obj.object_id]
        if len(matching) != 1:
            raise ValueError("Split evidence paint needs its exact object treatment")
        treatment, = matching
        verified = _split_evidence_asset_value(resources[3], obj.asset_id, treatment.action_id, obj.object_id)
        raster = canonical_png(verified.payload)
        treatments[obj.object_id] = treatment
    else:
        raster = canonical_png(resources[3][obj.asset_id])
    transform = replace(FrameTransform.from_contract(obj.transform), position=FramePoint(0., 0.),
                        scale_x=1., scale_y=1., rotation_degrees=0.)
    state = FrameObject(object_id=obj.object_id, board_id=obj.board_id, state="visible", visible=True,
                        opacity=1., reveal_fraction=1., transform=transform)
    inner = _object_markup(obj, state, style, None, scale, None, {obj.object_id: obj},
                        {obj.object_id: state}, {obj.asset_id: raster}, treatments, resources=resources)
    bounds = obj.geometry.bounds
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{ceil(bounds.width)}" '
        f'height="{ceil(bounds.height)}" viewBox="{bounds.x} {bounds.y} {bounds.width} {bounds.height}">'
        f'{inner}</svg>')
    png = _rasterize_frozen_svg(SVGFrame(0, ceil(bounds.width), ceil(bounds.height), svg), style, resources[2]).png
    with Image.open(io.BytesIO(png)) as image:
        alpha = image.convert("RGBA").getchannel("A")
        if alpha.getbbox() is None:
            raise ValueError(f"Split image {obj.object_id} has no placed painted pixels")
        return {"asset_sha256": raster.source_sha256,
            "placement": obj.image_placement.model_dump(mode="json") if obj.image_placement else None,
            **({"treatment_sha256": sha256(_canonical(treatment.model_dump(mode="json")).encode()).hexdigest()}
               if treatments else {}),
            "svg_sha256": sha256(inner.encode()).hexdigest(), "alpha_bounds": alpha.getbbox(),
            "alpha_size": alpha.size, "alpha_sha256": sha256(alpha.tobytes()).hexdigest()}


def _split_media_evidence(obj, layout, resources):
    """Original decoded inventory, never a static frame/thumbnail coverage claim."""
    from atme.render.v2_media import inspect_media

    _split_primitive_context(obj, layout, resources)
    raw = resources[3][obj.asset_id]
    checked = inspect_media(raw, obj.media_playback.source_stream.stream_index)
    if checked.pin != obj.media_playback.source_stream:
        raise ValueError("Split media playback differs from actual decoded original inventory")
    return {"asset_sha256": sha256(raw).hexdigest(), "media_stream": checked.pin.model_dump(mode="json"),
            "playback": obj.media_playback.model_dump(mode="json")}


_SPLIT_IMAGE_PAINT = _SplitPrimitivePaint(
    "supporting image", VisualObject, frozenset({"reveal", "enter"}),
    "native_placed_image_alpha_v1", _split_image_evidence)


def _split_connector_recipe(obj, layout, resources):
    """Frozen authored inputs only; this is never positive native paint proof."""
    _split_primitive_context(obj, layout, resources)
    return {"authored_layout_sha256": sha256(_canonical(layout.model_dump(mode="json")).encode()).hexdigest(),
            "object_sha256": sha256(_canonical(obj.model_dump(mode="json")).encode()).hexdigest(),
            "style_sha256": EXPECTED_STYLE_SHA256, "registry_sha256": EXPECTED_REGISTRY_SHA256}


def _split_captured_connector_evidence(obj, capture, basis, layout, resources):
    from atme.render.style_bundle import registry_endpoint_inputs_for_objects
    from atme.render.v2_connector import validate_static_arrow
    from atme.render.v2_svg import _color, _connector_shape, _prepare_project_rasters

    authored = {row.object_id: row for row in layout.objects}
    frames = {row.object_id: row for row in capture.baseline}
    placements = {row.object_id: row for row in basis.placements}
    objects = {}
    for key in frames:
        updates = {"parent_id": placements[key].parent_id}
        if isinstance(authored[key], (GroupContainer, ClipContainer, MaskContainer)):
            updates["child_ids"] = sorted(
                (child for child in frames if placements[child].parent_id == key),
                key=lambda child: placements[child].sibling_ordinal)
        objects[key] = authored[key].model_copy(update=updates, deep=True)
    obj = objects[obj.object_id]
    style, scale = _split_primitive_context(authored[obj.object_id], layout, resources)
    validate_static_arrow(obj, objects)
    registry = registry_endpoint_inputs_for_objects(objects, frozen_files=resources[2])
    assets = {row.asset_id: ResolvedAsset.model_validate_json(row.resolved_json) for row in resources[3].rows}
    _, _, media_view = _prepare_project_rasters(layout, objects, frames, (), assets, resources[3], capture.start_ms)
    stroke = _color(obj.style.stroke, style.colors, default=style.colors["ink"])
    weight = style.strokes.regular_px * scale
    full = _connector_shape(obj, objects, frames, stroke, weight, None,
                            registry_inputs=registry, media_view=media_view)
    partial = _connector_shape(obj, objects, frames, stroke, weight, .5,
                               registry_inputs=registry, media_view=media_view)
    bounds = obj.geometry.bounds
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{layout.output_profile.width}" '
           f'height="{layout.output_profile.height}" viewBox="{bounds.x - weight} {bounds.y - weight} '
           f'{bounds.width + 2 * weight} {bounds.height + 2 * weight}">{full}</svg>')
    painted, size, alpha_sha256 = _geometry_alpha_facts(svg)
    if painted is None:
        raise ValueError(f"Split connector {obj.object_id} has no captured native pixels")
    return {"full_svg_sha256": sha256(full.encode()).hexdigest(),
            "constructed_path_sha256": sha256(partial.encode()).hexdigest(), "stroke_width": weight,
            "alpha_bounds": painted, "alpha_size": size, "alpha_sha256": alpha_sha256}


_SPLIT_CONNECTOR_PAINT = _SplitPrimitivePaint(
    "semantic connector", ConnectorObject, frozenset({"reveal", "draw"}),
    "native_connector_capture_alpha_v1", _split_connector_recipe)


_SPLIT_POINTER_PAINT = _SplitPrimitivePaint(
    "free-source pointer", ConnectorObject, frozenset({"reveal", "draw"}),
    "native_connector_capture_alpha_v1", _split_connector_recipe)


_SPLIT_EVIDENCE_PAINT = _SplitPrimitivePaint(
    "attested evidence", VisualObject, frozenset({"reveal", "enter"}),
    "native_attested_evidence_alpha_v1", _split_image_evidence)


_SPLIT_MEDIA_PAINT = _SplitPrimitivePaint(
    "moving media", VisualObject, frozenset({"reveal", "enter"}),
    "native_original_media_inventory_v1", _split_media_evidence)


_SPLIT_CHART_PAINT = _SplitPrimitivePaint(
    "data chart", VisualObject, frozenset({"draw", "reveal", "enter"}),
    "native_data_chart_alpha_v1", _split_chart_evidence)


_SPLIT_TECHNICAL_PAINT = _SplitPrimitivePaint(
    "technical chrome", VisualObject, frozenset({"reveal", "enter"}),
    "native_technical_chrome_alpha_v1", _split_technical_chrome_evidence)


_SPLIT_PAINT_ADAPTERS = (
    _SplitPrimitivePaint("geometry", MarkObject, frozenset({"reveal", "draw", "enter"}),
                         "native_path_alpha_v1", _split_path_evidence),
    _SplitPrimitivePaint("text", TextObject, frozenset({"reveal", "write", "enter"}),
                         "pinned_font_rendered_alpha_v1", _split_glyph_evidence),
    _SplitPrimitivePaint("registry illustration", VisualObject, frozenset({"reveal", "enter"}),
                         "pinned_registry_alpha_v1", _split_registry_evidence),
    _SplitPrimitivePaint("compound", GroupContainer, frozenset({"reveal", "draw", "write", "enter"}),
                         "captured_compound_closure_v1", None),
    _SplitPrimitivePaint("compound", ClipContainer, frozenset({"reveal", "draw", "write", "enter"}),
                         "captured_compound_closure_v1", None),
    _SplitPrimitivePaint("compound", MaskContainer, frozenset({"reveal", "draw", "write", "enter"}),
                         "captured_compound_closure_v1", None),
)


def _split_adapter(obj):
    from atme.render.v2_svg import (
        SUPPORTED_MARKS,
        SUPPORTED_REGISTRY_VISUALS,
        SUPPORTED_TEXT,
    )

    if type(obj) is VisualObject and obj.technical_frame is not None:
        return _SPLIT_TECHNICAL_PAINT
    if type(obj) is VisualObject and obj.chart_payload is not None:
        # Data charts use native per-datum construction, never registry art.
        return _SPLIT_CHART_PAINT
    if type(obj) is VisualObject and obj.object_type == "image":
        return _SPLIT_IMAGE_PAINT
    if type(obj) is VisualObject and obj.object_type == "evidence":
        return _SPLIT_EVIDENCE_PAINT
    if type(obj) is VisualObject and obj.object_type in MEDIA_OBJECT_TYPES:
        return _SPLIT_MEDIA_PAINT
    if type(obj) is ConnectorObject:
        if obj.object_type in {"arrow", "network"} and obj.role == "semantic_connector" and obj.source_point is None:
            return _SPLIT_CONNECTOR_PAINT
        if obj.object_type == "arrow" and obj.role == "pointer" and obj.source_point is not None:
            return _SPLIT_POINTER_PAINT
        return None  # Annotation/Callout-owned leaders keep their separate ownership gate.
    # Normal compositor support cannot implicitly admit a new Split adapter.
    # Bare legacy Callouts remain loadable but cannot claim native construction.
    # Bound Callout bodies also require the captured-read guard below; a local
    # descriptor is never sufficient to admit their pointer relationship.
    if type(obj) is TextObject and obj.object_type == "callout" and obj.callout_binding is None:
        return None
    supported = {MarkObject: SUPPORTED_MARKS, TextObject: SUPPORTED_TEXT & {"text", "list", "code", "callout"},
                 VisualObject: SUPPORTED_REGISTRY_VISUALS,
                 GroupContainer: {"group"}, ClipContainer: {"clip"}, MaskContainer: {"mask"}}
    adapter = next((row for row in _SPLIT_PAINT_ADAPTERS if type(obj) is row.object_class), None)
    return adapter if adapter is not None and obj.object_type in supported[adapter.object_class] else None


def _split_primitive_paint(obj, mode):
    adapter = _split_adapter(obj)
    if adapter is None:
        raise ValueError(f"Split {obj.object_type} construction adapter is not implemented")
    if mode not in adapter.modes:
        raise ValueError(f"Split {mode} is incompatible with {adapter.family} construction")
    return adapter


@dataclass(frozen=True)
class SplitFamilyAdmission:
    family: str
    mode: str
    content_sha256: str
    proof_kind: str
    paint_inputs_sha256: str


def _require_callout_captured_reads(capture, basis, layout, objects, resources):
    """Bound body paint only; no leader ownership transfer or lifecycle claim.

    Task8 retains relationship-origin, post-Split draw and stored-return gates.
    These local facts authenticate the existing separate read objects and their
    current canonical state, never replace actual chronological provenance.
    """
    from atme.render.v2_callout_pointer import validate_callout_pointer
    from atme.render.v2_split_identity import _content_receipts

    frames = {row.object_id: row for row in capture.baseline}
    placements = {row.object_id: row for row in basis.placements}
    connector_reads = {key for row in basis.read_dependencies if row.kind == "connector_anchor"
                       for key in row.object_ids}
    receipts = {row.object_id: row for row in getattr(capture, "content_receipts", ())}
    owned = set(capture.owned_object_ids)
    for key in sorted(owned):
        obj = objects[key]
        if type(obj) is not TextObject or obj.object_type != "callout":
            continue
        binding = obj.callout_binding
        if binding is None:
            raise ValueError("Split Callout body needs an exact callout_binding")
        leader_id, target_id = binding.leader_connector_id, binding.target_object_id
        if (not {leader_id, target_id}.issubset(connector_reads)
                or {leader_id, target_id}.intersection(owned)
                or not {leader_id, target_id}.issubset(frames)):
            raise ValueError("Split Callout needs separate captured connector_anchor leader/target reads")
        leader = objects[leader_id]
        validate_callout_pointer(leader, objects)
        if (leader.source_object_id != key or leader.source_anchor_id != binding.callout_anchor_id
                or leader.destination_object_id != target_id or leader.destination_anchor_id != binding.target_anchor_id):
            raise ValueError("Split Callout captured pointer differs from its exact binding")
        leader_frame = frames[leader_id]
        source_owned = key in basis.source_closure.owned_ids
        if source_owned:
            if leader_frame.state != "removed" or leader_frame.visible or leader_frame.opacity != 0:
                raise ValueError("Split Callout body requires a removed source pointer")
        elif (leader_frame.state != "hidden" or leader_frame.visible or leader_frame.reveal_fraction != 0
              or leader_frame.opacity <= 0):
            raise ValueError("Split Callout result requires an unchanged hidden pointer")
        # Compare the exact captured local payload, not a new input manifest's
        # claim about a mutable read object. Ancestor child hashes are historical
        # and intentionally not rebuilt from an incomplete bounded tree.
        read_ids = {leader_id, target_id}
        for read_id in tuple(read_ids):
            chain = {read_id}
            parent = placements[read_id].parent_id
            while parent is not None:
                if parent in chain or parent not in placements:
                    raise ValueError("Split Callout captured read ancestry is incomplete or cyclic")
                chain.add(parent)
                read_ids.add(parent)
                parent = placements[parent].parent_id
        for read_id in sorted(read_ids):
            if read_id not in receipts or read_id not in frames or read_id in owned:
                raise ValueError("Split Callout requires live authenticated read content receipts")
            frame, placement = frames[read_id], placements[read_id]
            if ((frame.state, frame.visible, frame.opacity, frame.reveal_fraction, asdict(frame.transform)) !=
                (placement.state, placement.local_visibility, placement.local_opacity, placement.reveal,
                 placement.local_transform.model_dump(mode="json"))):
                raise ValueError("Split Callout captured read state differs from its placement")
            projected = _content_receipts(layout=layout, objects={read_id: objects[read_id]},
                frames={read_id: frame}, children=lambda _key: (), asset_bytes=resources[3])[0]
            actual, expected = json.loads(projected.canonical_json), json.loads(receipts[read_id].canonical_json)
            actual.pop("children", None)
            expected.pop("children", None)
            if actual != expected:
                raise ValueError(f"Split Callout captured read content differs for {read_id}")


def _split_admission_context(capture, layout, inputs):
    from atme.render.v2_split_identity import _content_receipts
    from atme.store.contracts_v2 import (
        _validate_technical_frames,
        validate_character_assembly_map,
        validate_illustration_assembly_map,
    )

    _validate_capture_inventory(capture)
    resources = _checked_split_resources(layout, inputs)
    basis = SplitBasis.model_validate_json(capture.basis_json)
    policy = SplitPolicy.model_validate_json(capture.policy_json)
    referenced = {obj.asset_id for obj in layout.objects
                  if obj.object_id in (*capture.owned_object_ids, *capture.read_dependency_ids)
                  and obj.asset_id is not None}
    if basis.asset_pins != _verified_split_asset_pins(layout, resources[3], referenced):
        raise ValueError("Split captured asset pins differ from current verified carrier")
    if (basis.style_sha256 != EXPECTED_STYLE_SHA256 or basis.registry_sha256 != EXPECTED_REGISTRY_SHA256):
        raise ValueError("Split captured paint bundle differs from verified inputs")
    objects = {obj.object_id: obj for obj in layout.objects}
    placements = {row.object_id: row for row in basis.placements}
    owned = set(capture.owned_object_ids)
    if not owned.issubset(objects):
        raise ValueError("Split owned closure is missing layout content")
    frames = {frame.object_id: frame for frame in capture.baseline if frame.object_id in owned}
    for key, frame in frames.items():
        placement = placements[key]
        if ((frame.state, frame.visible, frame.opacity, frame.reveal_fraction, asdict(frame.transform)) !=
                (placement.state, placement.local_visibility, placement.local_opacity, placement.reveal,
                 placement.local_transform.model_dump(mode="json"))):
            raise ValueError(f"Split captured state differs from its placement for {key}")
    closures = (basis.source_closure, *basis.result_closures)
    by_parent = {}
    for key in owned:
        row = placements[key]
        by_parent.setdefault(row.parent_id, []).append(key)
    for keys in by_parent.values():
        if len({placements[key].sibling_ordinal for key in keys}) != len(keys):
            raise ValueError("Split captured closure repeats a paint ordinal")
        keys.sort(key=lambda key: placements[key].sibling_ordinal)
    # Walk only the captured owned trees. Unrelated siblings/read ancestors
    # are not fabricated to satisfy a full-layout replay inventory.
    owners = {}
    def visit(key, reached):
        if key in reached:
            raise ValueError("Split captured owned closure is cyclic")
        reached.add(key)
        for child in by_parent.get(key, ()):
            visit(child, reached)

    for closure in closures:
        reached = set()
        visit(closure.root_id, reached)
        if reached != set(closure.owned_ids):
            raise ValueError("Split captured owned closure differs from parent membership")
        for key in reached:
            owners[key] = closure.root_id
    contents = _content_receipts(layout, {key: objects[key] for key in owned}, frames,
                                  lambda key: by_parent.get(key, ()), resources[3])
    receipts = {row.object_id: row for row in contents}
    for key, receipt in receipts.items():
        if receipt.content_sha256 != placements[key].content_sha256:
            raise ValueError(f"Split captured content differs for {key}")
    # Bind assembly roles to the captured current tree, not just the original
    # layout or a convenient descendant's local primitive proof. The complete
    # owned closures are already authenticated above; unrelated read ancestors
    # are deliberately not manufactured into this bounded object map.
    current = {}
    for key in owned:
        obj = objects[key]
        updates = {"parent_id": placements[key].parent_id}
        if isinstance(obj, (GroupContainer, ClipContainer, MaskContainer)):
            updates["child_ids"] = list(by_parent.get(key, ()))
        current[key] = obj.model_copy(update=updates, deep=True)
    validate_character_assembly_map(current)
    validate_illustration_assembly_map(current)
    _validate_technical_frames(current, semantic=False)
    chromes = [obj for obj in current.values()
               if type(obj) is VisualObject and obj.technical_frame is not None]
    if chromes:
        from atme.render.v2_technical_frame import validate_technical_frame_world

        # Physical role fit must use the real captured ancestor chain and poses.
        # Include only those bound read ancestors; unrelated siblings are not
        # invented to turn a local alpha proof into a sampled-world attestation.
        selected = set(owned)
        for key in owned:
            chain = {key}
            parent = placements[key].parent_id
            while parent is not None:
                if parent in chain or parent not in placements or parent not in objects:
                    raise ValueError("Split technical illustration needs complete captured ancestry")
                chain.add(parent)
                selected.add(parent)
                parent = placements[parent].parent_id
        captured_frames = {row.object_id: row for row in capture.baseline}
        captured_receipts = {row.object_id: row for row in getattr(capture, "content_receipts", ())}
        for key in selected - owned:
            obj, frame, placement = objects[key], captured_frames[key], placements[key]
            if ((frame.state, frame.visible, frame.opacity, frame.reveal_fraction, asdict(frame.transform)) !=
                    (placement.state, placement.local_visibility, placement.local_opacity, placement.reveal,
                     placement.local_transform.model_dump(mode="json"))):
                raise ValueError(f"Split captured state differs from its placement for {key}")
            if key not in captured_receipts:
                raise ValueError("Split technical illustration needs authenticated ancestor content")
            projected = _content_receipts(layout, {key: obj}, {key: frame}, lambda _key: (), resources[3])[0]
            actual, expected = json.loads(projected.canonical_json), json.loads(captured_receipts[key].canonical_json)
            actual.pop("children", None)
            expected.pop("children", None)
            if actual != expected:
                raise ValueError(f"Split captured ancestor content differs for {key}")
            updates = {"parent_id": placement.parent_id}
            if hasattr(obj, "child_ids"):
                updates["child_ids"] = sorted(
                    (child for child in selected if placements[child].parent_id == key),
                    key=lambda child: placements[child].sibling_ordinal)
            current[key] = obj.model_copy(update=updates, deep=True)
        transforms = {key: captured_frames[key].transform for key in selected}
        for chrome in chromes:
            validate_technical_frame_world(chrome, current, transforms)
    from atme.render.v2_media_view import require_media_window
    from atme.render.v2_split_clock import resolve_split_phase

    for closure in closures:
        media_ids = [key for key in closure.owned_ids if getattr(objects[key], "media_playback", None) is not None]
        if not media_ids:
            continue
        if closure.root_id == policy.source_object_id:
            start, end = capture.start_ms, resolve_split_phase(capture.start_ms, capture.end_ms, policy.source_exit)[1]
        else:
            result = next(row for row in policy.results if row.object_id == closure.root_id)
            start = resolve_split_phase(capture.start_ms, capture.end_ms, result.construction.phase)[0] + 1
            end = capture.end_ms + 1  # visible post-state includes the atomic endpoint
        require_media_window(objects, media_ids, start, end)
    _require_callout_captured_reads(capture, basis, layout, objects, resources)
    # Keep the established specialized diagnostics above, then authenticate
    # every remaining read kind at admission, not only at coverage validation.
    # Fresh resources cannot replace a historical aperture; use captured live
    # state, never layout's initial pose. Uncaptured siblings are not invented.
    captured_frames = {row.object_id: row for row in capture.baseline}
    captured_receipts = {row.object_id: row for row in getattr(capture, "content_receipts", ())}
    for key in capture.read_dependency_ids:
        if any(key not in rows for rows in (objects, captured_frames, placements, captured_receipts)):
            raise ValueError("Split read admission requires live authenticated content receipts")
        frame, placement = captured_frames[key], placements[key]
        if ((frame.state, frame.visible, frame.opacity, frame.reveal_fraction, asdict(frame.transform)) !=
                (placement.state, placement.local_visibility, placement.local_opacity, placement.reveal,
                 placement.local_transform.model_dump(mode="json"))):
            raise ValueError(f"Split captured read state differs for {key}")
        projected = _content_receipts(layout, {key: objects[key]}, {key: frame}, lambda _key: (), resources[3])[0]
        actual = json.loads(projected.canonical_json)
        expected = json.loads(captured_receipts[key].canonical_json)
        actual.pop("children", None)
        expected.pop("children", None)
        if actual != expected:
            raise ValueError(f"Split captured read content differs for {key}")
    evidence = {row["object_id"]: row for encoded in inputs.paint_evidence
                if "object_id" in (row := json.loads(encoded))}
    from atme.render.v2_state import CountFrameObject

    for key in sorted(owned):
        obj = objects[key]
        if type(frames[key]) is CountFrameObject:
            if type(obj) is not TextObject or obj.object_type != "text" or obj.items:
                raise ValueError("Split captured Count needs its exact single-line text primitive")
            # Content/origin was authenticated above; measure the same captured text the native painter draws.
            counted = obj.model_copy(update={"text": frames[key].display_text}, deep=True)
            adapter = _split_adapter(counted)
            evidence[key] = {"object_id": key, "family": adapter.family, "proof_kind": adapter.proof_kind,
                             "paint": _split_glyph_evidence(counted, layout, resources)}
        if type(obj) is not ConnectorObject or (adapter := _split_adapter(obj)) is None:
            continue
        recipe = evidence.get(key)
        if (recipe is None or recipe.get("proof_kind") != "connector_authored_recipe_v1"
                or recipe.get("family") != adapter.family or "recipe" not in recipe):
            raise ValueError("Split connector requires its frozen authored recipe before captured native proof")
        evidence[key] = {"object_id": key, "family": adapter.family, "proof_kind": adapter.proof_kind,
                         "paint": _split_captured_connector_evidence(obj, capture, basis, layout, resources)}
    return policy, objects, frames, by_parent, owners, receipts, evidence


def _split_admit_object(object_id, context, inputs):
    policy, objects, frames, children, owners, receipts, evidence = context
    if object_id not in owners:
        raise ValueError(f"Split {object_id} does not belong to an owned closure")
    root = owners[object_id]
    mode = ("source_fade" if root == policy.source_object_id else
            next(row.construction.mode for row in policy.results if row.object_id == root))

    def admit(key):
        obj, frame = objects[key], frames[key]
        adapter = _split_primitive_paint(obj, "reveal" if mode == "source_fade" else mode)
        if frame.morph_geometry is not None:
            raise ValueError(f"Split {key} captured runtime paint adapter is not implemented")
        descendants = children.get(key, ())
        if adapter.family == "compound":
            if not descendants:
                raise ValueError(f"Split {key} compound has no painted closure")
            for child in descendants:
                admit(child)
        else:
            if descendants:
                raise ValueError("Split primitive cannot own a compound closure")
            row = evidence.get(key)
            if (adapter.paint_evidence is None or row is None
                    or row["family"] != adapter.family or row["proof_kind"] != adapter.proof_kind):
                raise ValueError(f"Split {key} has no faithful primitive paint evidence")
        return adapter

    adapter = admit(object_id)
    # Family credit belongs only to a complete captured owning root. Recursive
    # leaf admission still proves every actual part with the same mode/painter;
    # a role Group or a native chrome leaf is not an assembly admission.
    if object_id == root and type(objects[root]) is GroupContainer:
        obj = objects[root]
        family = proof = None
        if obj.character_assembly is not None:
            family, proof = "authored character", "authored_character_closure_v1"
        elif obj.illustration_assembly is not None:
            family, proof = "authored illustration", "authored_illustration_closure_v1"
        elif any(type(objects[key]) is VisualObject
                 and objects[key].technical_frame is not None
                 and objects[key].technical_frame.container_group_id == root
                 for key in children.get(root, ())):
            family, proof = "technical illustration", "native_technical_closure_v1"
        if family is not None:
            return SplitFamilyAdmission(family, mode, receipts[root].content_sha256,
                                        proof, inputs.inputs_sha256)
    return SplitFamilyAdmission(adapter.family, mode, receipts[object_id].content_sha256,
                                adapter.proof_kind, inputs.inputs_sha256)


def split_family_admission(object_id: str, capture: SplitCapture, layout: ExecutableLayoutV2,
                           inputs: "VerifiedSplitPaintInputs") -> SplitFamilyAdmission:
    """Bind the single primitive dispatcher to real captured content and mode.

    This descriptor is not a continuous-coverage or public-admission receipt.
    """
    return _split_admit_object(object_id, _split_admission_context(capture, layout, inputs), inputs)


def validate_split_paint(capture: SplitCapture, layout: ExecutableLayoutV2,
                         inputs: "VerifiedSplitPaintInputs") -> None:
    context = _split_admission_context(capture, layout, inputs)
    for root in capture.owned_root_ids:
        _split_admit_object(root, context, inputs)


@dataclass(frozen=True)
class SplitCoverageInterval:
    start_ms: int
    end_ms: int
    painted_root_ids: tuple[str, ...]

    def __post_init__(self):
        ids = self.painted_root_ids
        if (type(self.start_ms) is not int or type(self.end_ms) is not int
                or not 0 <= self.start_ms < self.end_ms or type(ids) is not tuple or not ids
                or any(type(key) is not str or not key.strip() for key in ids)
                or ids != tuple(sorted(set(ids)))):
            raise ValueError("Split coverage interval requires positive time and canonical painted roots")


@dataclass(frozen=True)
class SplitCoverageProof:
    proof_kind: str
    source_basis_sha256: str
    policy_sha256: str
    paint_inputs_sha256: str
    critical_times_ms: tuple[int, ...]
    intervals: tuple[SplitCoverageInterval, ...]

    def __post_init__(self):
        times, spans = self.critical_times_ms, self.intervals
        digests = (self.source_basis_sha256, self.policy_sha256, self.paint_inputs_sha256)
        if (self.proof_kind != "native_alpha_all_integer_ms_v1"
                or any(type(value) is not str or len(value) != 64
                       or any(char not in "0123456789abcdef" for char in value) for value in digests)
                or type(times) is not tuple or len(times) < 2
                or any(type(at) is not int or at < 0 for at in times)
                or times != tuple(sorted(set(times)))
                or type(spans) is not tuple or not spans
                or any(type(row) is not SplitCoverageInterval for row in spans)):
            raise ValueError("Split coverage proof requires exact digests, critical times and intervals")
        if (spans[0].start_ms != times[0] or spans[-1].end_ms != times[-1]
                or any(a.end_ms != b.start_ms for a, b in pairwise(spans))
                or any(row.start_ms not in times or row.end_ms not in times for row in spans)):
            raise ValueError("Split coverage proof intervals must cover the complete critical-time range")


def _split_coverage_context(capture, layout, inputs):
    from atme.render.v2_split import _AttributedSplitCapture, _PaintBoundSplitCapture
    from atme.render.v2_split_identity import _content_receipts

    validate_split_paint(capture, layout, inputs)
    if type(capture) not in (_PaintBoundSplitCapture, _AttributedSplitCapture):
        raise ValueError("Split coverage requires live captured paint receipts")
    resources = _checked_split_resources(layout, inputs)
    basis = SplitBasis.model_validate_json(capture.basis_json)
    placements = {row.object_id: row for row in basis.placements}
    receipts = {row.object_id: row for row in capture.content_receipts}
    authored = {obj.object_id: obj for obj in layout.objects}
    frames = {row.object_id: row for row in capture.baseline}
    objects = {}
    for key, placement in placements.items():
        obj, frame = authored[key], frames[key]
        # Compare local payload through the same identity projector. An ancestor
        # receipt retains its historical children hashes, even when those
        # unrelated children are intentionally absent from the bounded capture.
        projected = _content_receipts(layout, {key: obj}, {key: frame}, lambda _key: (), resources[3])[0]
        actual = json.loads(projected.canonical_json)
        expected = json.loads(receipts[key].canonical_json)
        actual.pop("children", None)
        expected.pop("children", None)
        if actual != expected:
            raise ValueError(f"Split captured read content differs for {key}")
        if ((frame.state, frame.visible, frame.opacity, frame.reveal_fraction,
                asdict(frame.transform)) != (placement.state, placement.local_visibility,
                placement.local_opacity, placement.reveal, placement.local_transform.model_dump(mode="json"))):
            raise ValueError(f"Split captured paint state differs for {key}")
        if placement.parent_id is not None and placement.parent_id not in placements:
            raise ValueError("Split coverage is missing a captured ancestor")
        objects[key] = obj.model_copy(update={"parent_id": placement.parent_id}, deep=True)
    closures = (basis.source_closure, *basis.result_closures)
    included = {}
    for closure in closures:
        selected = set(closure.owned_ids)
        parent = placements[closure.root_id].parent_id
        while parent is not None:
            if parent in selected:
                raise ValueError("Split coverage captured ancestor cycle")
            selected.add(parent)
            parent = placements[parent].parent_id
        included[closure.root_id] = frozenset(selected)
    from atme.render.v2_external_aperture import _map_signature

    captured_objects_sha256 = _map_signature(objects)
    captured_frames = tuple(frames.items())
    read_ids = frozenset(key for row in basis.read_dependencies for key in row.object_ids)
    boards = {obj.board_id for obj in objects.values()}

    def aperture_context(at_ms, states):
        # Only this post-authentication closure can issue a selected context.
        # Reuse the real captured phase sampler, not a parallel timeline or an
        # arbitrary caller-supplied owned frame map.
        from atme.render.v2_external_aperture import (
            _captured_subset_after_authentication,
        )
        from atme.render.v2_split import _sample_split_paint

        if (_map_signature(objects) != captured_objects_sha256 or type(at_ms) is not int
                or not capture.start_ms <= at_ms <= capture.end_ms):
            raise ValueError("Split selected aperture differs from authenticated captured map/time")
        expected = {**dict(captured_frames), **{row.object_id: row for row in _sample_split_paint(capture, at_ms).objects}}
        if expected != states:
            raise ValueError("Split selected aperture states differ from authenticated captured sample")
        if len(boards) != 1:
            raise ValueError("Split selected aperture requires one authenticated captured board")
        return _captured_subset_after_authentication(objects, states, capture.owned_object_ids,
            read_ids, next(iter(boards)))

    return resources, objects, frames, placements, closures, included, aperture_context


def prove_split_coverage(capture: SplitCapture, layout: ExecutableLayoutV2,
                         inputs: "VerifiedSplitPaintInputs") -> SplitCoverageProof:
    """Exact native-alpha proof over every observable integer millisecond.

    The scan streams states and keeps only one last raster result per root.
    There is no sparse frame assumption, source-file read, or duration cap.
    """
    from atme.render.v2_split import _sample_split_paint
    from atme.render.v2_split_clock import resolve_split_phase
    from atme.render.v2_split_identity import split_policy_digest
    from atme.render.v2_svg import (
        SVGFrame,
        _compose_object_tree,
        _frozen_svg_rasterizer,
        _n,
        _prepare_evidence_rasters,
        _prepare_project_rasters,
    )

    resources, objects, baseline, placements, closures, included, aperture_context = _split_coverage_context(capture, layout, inputs)
    policy = SplitPolicy.model_validate_json(capture.policy_json)
    phases = [policy.source_exit, *(row.construction.phase for row in policy.results),
              *(row.movement.phase for row in policy.results if row.movement is not None)]
    critical = {capture.start_ms, capture.end_ms}
    for phase in phases:
        critical.update(resolve_split_phase(capture.start_ms, capture.end_ms, phase))
    style = resources[0]
    profile = "landscape-16:9" if layout.output_profile.profile_id == "LONG_FORM_16_9" else "portrait-9:16"
    scale = layout.output_profile.width / style.aspects[profile].width
    ordinals = {key: row.sibling_ordinal for key, row in placements.items()}
    cache = {}
    intervals = []
    previous = None
    interval_start = capture.start_ms
    width, height = layout.output_profile.width, layout.output_profile.height
    canvas = layout.canvas
    assets = {row.asset_id: ResolvedAsset.model_validate_json(row.resolved_json) for row in resources[3].rows}
    treatments = {row.object_id: row for row in layout.evidence_treatments}
    evidence_rasters = _prepare_evidence_rasters(objects, assets, resources[3], treatments)
    with _frozen_svg_rasterizer(style, resources[2]) as rasterize:
        for at_ms in range(capture.start_ms, capture.end_ms + 1):
            paint = _sample_split_paint(capture, at_ms)
            states = {**baseline, **{row.object_id: row for row in paint.objects}}
            raster_images, media_rasters, media_view = _prepare_project_rasters(
                layout, objects, states, (), assets, resources[3], at_ms)
            raster_images.update(evidence_rasters)
            aperture_subset = (aperture_context(at_ms, states)
                if any(obj.clip_id is not None for obj in objects.values()) else None)
            constructions = {}
            for row in paint.constructions:
                closure = next(item for item in closures if item.root_id == row.root_id)
                constructions.update({key: row for key in closure.owned_ids})
            modes = {key: row.mode for key, row in constructions.items()}
            painted = []
            for root in capture.owned_root_ids:
                definitions, body = _compose_object_tree(objects, states, ordinals, style, None, scale,
                    modes, raster_images, treatments, constructions, resources, included_ids=included[root],
                    active_board_id=objects[root].board_id, captured_aperture_subset=aperture_subset,
                    media_rasters=media_rasters, media_view=media_view)
                svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
                    f'viewBox="{_n(canvas.x)} {_n(canvas.y)} {_n(canvas.width)} {_n(canvas.height)}">'
                    f'<defs>{definitions}</defs>{body}</svg>')
                last = cache.get(root)
                if last is not None and last[0] == svg:
                    positive = last[1]
                elif not body:
                    positive = False
                else:
                    with Image.open(io.BytesIO(rasterize(SVGFrame(at_ms, width, height, svg)).png)) as image:
                        positive = image.convert("RGBA").getchannel("A").getbbox() is not None
                cache[root] = (svg, positive)
                if positive:
                    painted.append(root)
            current = tuple(sorted(painted))
            if not current:
                raise ValueError(f"Split has zero painted coverage at {at_ms} ms")
            # Completion is raster-verified above, but the endpoint is not a
            # positive-duration half-open interval. Its time remains explicit.
            if at_ms == capture.end_ms:
                if not {row.root_id for row in closures[1:]}.issubset(current):
                    raise ValueError("Split completion has an unpainted visible result root")
                continue
            if previous is not None and current != previous:
                critical.add(at_ms)
                intervals.append(SplitCoverageInterval(interval_start, at_ms, previous))
                interval_start = at_ms
            previous = current
        intervals.append(SplitCoverageInterval(interval_start, capture.end_ms, previous))
    proof = SplitCoverageProof("native_alpha_all_integer_ms_v1", policy.source_basis_sha256,
        split_policy_digest(policy), inputs.inputs_sha256, tuple(sorted(critical)), tuple(intervals))
    if (proof.intervals[0].start_ms, proof.intervals[-1].end_ms) != (capture.start_ms, capture.end_ms):
        raise ValueError("Split coverage proof differs from the captured action interval")
    return proof


def _split_focus_bounds(capture, layout, timeline, replay, inputs, camera_action_id, *,
                         layout_sha256=None, structural_timeline=None):
    """Observe actual transparent Split paint without invoking camera framing."""
    from atme.render.style_bundle import registry_endpoint_inputs_for_objects
    from atme.render.v2_camera import CameraViewport
    from atme.render.v2_split import (
        CapturedSplitAction,
        _AttributedSplitCapture,
        _json,
        sample_split,
    )
    from atme.render.v2_split_identity import _stored_value
    from atme.render.v2_state import _validate_pair_static
    from atme.render.v2_svg import (
        SVGFrame,
        _annotation_paint_modes,
        _authored_annotation_bindings,
        _compose_object_tree,
        _preflight_annotation_pointers,
        _preflight_object,
        _prepare_evidence_rasters,
        _prepare_project_rasters,
        _rasterize_frozen_svg,
    )
    from atme.render.v2_timeline_replay import (
        ChronologicalReplay,
        _split_causal_timeline,
    )
    from atme.store.contracts_v2 import (
        CameraAction,
        ContainerObject,
        ResolvedVisualTimelineV2,
        _split_logical_write_owners,
    )

    if (type(capture) is not _AttributedSplitCapture or type(replay) is not ChronologicalReplay
            or type(layout) is not ExecutableLayoutV2 or type(timeline) is not ResolvedVisualTimelineV2):
        raise ValueError("Split focus requires exact attributed capture and paired replay contracts")
    _validate_capture_inventory(capture)
    layout = ExecutableLayoutV2.model_validate(_stored_value(layout))
    timeline = _split_causal_timeline(timeline, tuple(timeline.actions), structural_timeline)
    resources = _checked_split_resources(layout, inputs)
    authored = {obj.object_id: obj for obj in layout.objects}
    registry = registry_endpoint_inputs_for_objects(authored, frozen_files=resources[2])
    paired = _validate_pair_static(layout, timeline,
        layout_sha256 if layout_sha256 is not None else sha256(_json(layout.model_dump(mode="json")).encode()).hexdigest(),
        replay.checkpoints[0].hierarchy, registry_inputs=registry, structural_timeline=structural_timeline)
    recorded = {row.resolved_index: row for checkpoint in replay.checkpoints for row in checkpoint.active}
    if (replay.duration_ms != timeline.duration_ms
            or tuple(recorded[key].resolved for key in sorted(recorded)) != tuple(timeline.actions)
            or {key: json.loads(value) for key, value in replay.authored_objects_json}
                != {key: obj.model_dump(mode="json") for key, obj in authored.items()}
            or {key: row.state_version for key, row in paired.initial.items()}
                != dict(replay.checkpoints[0].state_versions)):
        raise ValueError("Split focus differs from the complete actual replay and initial authority")
    camera = next((row for row in timeline.actions if row.action.action_id == camera_action_id), None)
    if camera is None or not isinstance(camera.action, CameraAction):
        raise ValueError("Split focus requires an actual authored camera boundary")
    candidates = [row for row in recorded.values() if isinstance(row, CapturedSplitAction)
                  and row.resolved.start_ms <= camera.start_ms
                  and set(camera.action.target_ids).intersection(row.split_capture.owned_object_ids)]
    if len(candidates) != 1 or candidates[0].split_capture is not capture:
        raise ValueError("Split focus needs one unambiguous actual capture")
    treatments = {(row.action_id, row.object_id): row for row in timeline.evidence_treatments}
    if any(treatments.get((capture.action_id, key)) != EvidenceTreatment.model_validate_json(encoded)
           for key, encoded in capture.evidence_treatments_json):
        raise ValueError("Split focus treatment inventory differs from its actual capture")
    sample = replay.before_action(camera_action_id)
    objects = sample.hierarchy.object_map(authored)
    states = {row.object_id: row for row in sample.objects}
    policy = SplitPolicy.model_validate_json(capture.policy_json)
    logical = _split_logical_write_owners(policy)
    annotations = _authored_annotation_bindings(timeline)
    annotation_leaders = {policy.leader_connector_id for _, policy, _, _ in annotations}
    activation = next((row for row in layout.activations if row.board_id == camera.action.board_id
                       and row.start_ms <= camera.start_ms and camera.end_ms <= row.end_ms), None)
    if activation is None:
        raise ValueError("Split focus requires one actual active-board camera window")
    envelopes = tuple(envelope for index in sorted(recorded)
                      if isinstance(recorded[index], CapturedSplitAction)
                      and recorded[index].resolved.start_ms <= sample.at_ms < recorded[index].resolved.end_ms
                      for envelope in sample_split(recorded[index].split_capture, sample.at_ms).envelopes)
    values = {"at_ms": sample.at_ms, "active_board_id": activation.board_id, "objects": sample.objects,
              "hierarchy": sample.hierarchy,
              "camera": CameraViewport(layout.canvas.x, layout.canvas.y, layout.canvas.width, layout.canvas.height)}
    snapshot = SplitFrameSnapshot(**values, envelopes=envelopes) if envelopes else FrameSnapshot(**values)
    modes = _split_active_paint_modes(snapshot, timeline, objects)
    selected = set(capture.owned_object_ids) | logical.keys()
    selected.update(parent for key in tuple(selected) for parent in sample.hierarchy.ancestors(key))
    style = resources[0]
    profile = "landscape-16:9" if layout.output_profile.profile_id == "LONG_FORM_16_9" else "portrait-9:16"
    scale = layout.output_profile.width / style.aspects[profile].width
    for key in selected:
        if not isinstance(objects[key], ContainerObject):
            _preflight_object(objects[key], style, None, scale, objects,
                              annotation_pointer=key in annotation_leaders, resources=resources)
    held_frames = {}
    for key, annotation, _, end in annotations:
        if annotation.leader_connector_id is not None:
            held = replay.at(end)
            board = next((row.board_id for row in layout.activations if row.start_ms <= end < row.end_ms), None)
            held_frames[key] = FrameSnapshot(at_ms=end, active_board_id=board, objects=held.objects,
                hierarchy=held.hierarchy, camera=snapshot.camera)
    _preflight_annotation_pointers(annotations, held_frames, layout, style, scale, registry)
    assets = {row.asset_id: row for row in timeline.resolved_assets}
    rasters, media, media_view = _prepare_project_rasters(layout, objects, states, timeline.actions,
        assets, resources[3], sample.at_ms, duration_ms=timeline.duration_ms)
    evidence = {row.object_id: row for row in timeline.evidence_treatments}
    rasters.update(_prepare_evidence_rasters(objects, assets, resources[3], evidence))
    active_modes = _annotation_paint_modes(annotations, sample.at_ms)
    active_modes.update({key: row.mode for key, row in modes.items()})
    definitions, body = _compose_object_tree(objects, states,
        {row.object_id: row.sibling_ordinal for row in sample.hierarchy.nodes}, style, None, scale,
        active_modes, rasters, evidence, modes, resources,
        included_ids=frozenset(selected), registry_inputs=registry, active_board_id=activation.board_id,
        media_rasters=media, media_view=media_view)
    width, height, canvas = layout.output_profile.width, layout.output_profile.height, layout.canvas
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
           f'viewBox="{canvas.x} {canvas.y} {canvas.width} {canvas.height}">'
           f'<defs>{definitions}</defs>{body}</svg>')
    with Image.open(io.BytesIO(_rasterize_frozen_svg(SVGFrame(sample.at_ms, width, height, svg),
                                                   style, resources[2]).png)) as image:
        painted = image.convert("RGBA").getchannel("A").getbbox()
    if painted is None:
        raise ValueError("Split camera has no visible painted union")
    return (canvas.x + painted[0] * canvas.width / width, canvas.y + painted[1] * canvas.height / height,
            canvas.x + painted[2] * canvas.width / width, canvas.y + painted[3] * canvas.height / height)


def _split_active_paint_modes(snapshot, timeline, objects):
    """Bind renderer modes to the exact replay envelope, never infer draw/write.

    This private primitive consumer is not a family/continuous-coverage proof.
    Compound modes bind every leaf; incompatible closures remain fail-closed.
    """
    expected = []
    by_object = {}
    for resolved in timeline.actions:
        action = resolved.action
        if not isinstance(action, SplitAction):
            continue
        if action.split_policy is None:
            raise ValueError("Split paint requires an authored policy")
        policy = action.split_policy
        for key in policy.source_basis.source_closure.owned_ids:
            obj = objects[key]
            if isinstance(obj, VisualObject) and obj.object_type == "evidence":
                owners = [item for item in timeline.actions if isinstance(item.action, EvidenceAction)
                          and item.action.verb == "insert_evidence" and item.action.target_object_id == key
                          and item.end_ms <= resolved.start_ms]
                treatments = [row for row in timeline.evidence_treatments if len(owners) == 1
                              and (row.action_id, row.object_id) == (owners[0].action.action_id, key)]
                baseline = next(row for row in policy.source_basis.placements if row.object_id == key)
                if (len(treatments) != 1 or treatments[0].intent.evidence_asset_id != obj.asset_id
                        or not baseline.effective_visibility or baseline.reveal != 1 or baseline.local_opacity <= 0):
                    raise ValueError("Split native source evidence needs its exact ordinary owner and visible baseline")
            else:
                _split_primitive_paint(obj, "reveal")
        for result, closure in zip(policy.results, policy.source_basis.result_closures, strict=True):
            for key in closure.owned_ids:
                obj = objects[key]
                if type(obj) is VisualObject and obj.object_type == "evidence":
                    # Family admission cannot replace exact causal activation checks.
                    activation = result.evidence_activation
                    treatments = [row for row in timeline.evidence_treatments
                                  if (row.action_id, row.object_id) == (action.action_id, key)]
                    if (key != result.object_id or activation is None or len(treatments) != 1
                            or result.construction.mode not in {"reveal", "enter"}
                            or activation.result_object_id != key
                            or activation.causal_action_id != action.action_id
                            or activation.beat_id != obj.beat_id
                            or treatments[0].intent != activation.intent
                            or treatments[0].intent.evidence_asset_id != obj.asset_id
                            or treatments[0].allowed_transformations != activation.allowed_transformations):
                        raise ValueError("Split native evidence needs its exact result, treatment and construction")
                else:
                    _split_primitive_paint(obj, result.construction.mode)
            if resolved.start_ms <= snapshot.at_ms < resolved.end_ms:
                envelope = SplitPaintEnvelope(result.object_id, action.action_id,
                    result.construction.mode, split_phase_progress(resolved.start_ms, resolved.end_ms,
                        snapshot.at_ms, result.construction.phase))
                expected.append(envelope)
                for key in closure.owned_ids:
                    if key in by_object:
                        raise ValueError("Split paint envelopes overlap owned closures")
                    by_object[key] = envelope
    actual = snapshot.envelopes if type(snapshot) is SplitFrameSnapshot else ()
    if tuple(expected) != actual:
        raise ValueError("Split paint envelope differs from the resolved construction")
    for key, envelope in by_object.items():
        if split_construction_for(snapshot, key) != envelope:
            raise ValueError("Split paint envelope differs from its root")
    return by_object


@dataclass(frozen=True)
class _SplitAssetBytes:
    asset_id: str
    resolved_json: str
    pin_json: str
    payload: bytes = field(repr=False)
    treatment_json: str | None
    treatments_json: tuple[str, ...] = field(default=(), kw_only=True)


def _row_evidence_treatments(row):
    """One exclusive canonical representation; never a selected fallback."""
    if type(row.treatments_json) is not tuple:
        raise ValueError("Split evidence treatments require an immutable tuple")
    if row.treatments_json:
        if row.treatment_json is not None or len(row.treatments_json) < 2:
            raise ValueError("Split multi-consumer evidence requires only its complete treatment tuple")
        encoded = row.treatments_json
    else:
        encoded = () if row.treatment_json is None else (row.treatment_json,)
    if any(type(value) is not str for value in encoded):
        raise ValueError("Split evidence treatment rows require canonical JSON")
    treatments = tuple(EvidenceTreatment.model_validate_json(value) for value in encoded)
    keys = tuple((value.action_id, value.object_id) for value in treatments)
    if (keys != tuple(sorted(set(keys))) or any(_canonical(value.model_dump(mode="json")) != raw
            for value, raw in zip(treatments, encoded, strict=True))):
        raise ValueError("Split evidence treatments require unique canonical ordered pairs")
    return treatments


@dataclass(frozen=True)
class _VerifiedSplitAssetBytes(Mapping):
    """Private project-resolver carrier; no authorable transport format."""
    rows: tuple[_SplitAssetBytes, ...]

    def __post_init__(self):
        if (type(self.rows) is not tuple or any(type(row) is not _SplitAssetBytes for row in self.rows)
                or tuple(row.asset_id for row in self.rows) != tuple(sorted({row.asset_id for row in self.rows}))):
            raise ValueError("Split asset carrier requires canonical unique immutable rows")
        for row in self.rows:
            _row_evidence_treatments(row)

    def __iter__(self):
        return iter(row.asset_id for row in self.rows)

    def __len__(self):
        return len(self.rows)

    def __contains__(self, key):
        return any(row.asset_id == key for row in self.rows)

    def __getitem__(self, key):
        row = next((row for row in self.rows if row.asset_id == key), None)
        if row is None:
            raise KeyError(key)
        if row.treatments_json:
            _row_evidence_treatments(row)
            raise ValueError("Split evidence asset-only lookup is ambiguous; bind action and object")
        if row.treatment_json is None:
            return row.payload
        asset = ResolvedAsset.model_validate_json(row.resolved_json)
        return VerifiedEvidenceBytes(key, asset.revision, row.payload, asset.checksum_sha256,
                                     asset.width, asset.height,
                                     EvidenceTreatment.model_validate_json(row.treatment_json))

    def evidence_for(self, asset_id, action_id, object_id):
        if any(type(key) is not str or not key.strip() for key in (asset_id, action_id, object_id)):
            raise ValueError("Split evidence lookup requires exact asset, action and object IDs")
        row = next((row for row in self.rows if row.asset_id == asset_id), None)
        if row is None:
            raise ValueError("Split evidence lookup references an absent asset")
        matches = [value for value in _row_evidence_treatments(row)
                   if (value.action_id, value.object_id) == (action_id, object_id)]
        if len(matches) != 1:
            raise ValueError("Split evidence lookup requires its exact object treatment")
        asset = ResolvedAsset.model_validate_json(row.resolved_json)
        return VerifiedEvidenceBytes(asset_id, asset.revision, row.payload, asset.checksum_sha256,
                                     asset.width, asset.height, matches[0])


def _split_evidence_asset_value(asset_bytes, asset_id, action_id, object_id):
    if type(asset_bytes) is _VerifiedSplitAssetBytes:
        return asset_bytes.evidence_for(asset_id, action_id, object_id)
    # Preserve the ordinary caller's exact legacy attestation; its consumer
    # performs the existing strict byte/treatment checks, never normalization.
    return asset_bytes.get(asset_id) if asset_bytes is not None else None


def _split_asset_treatment(layout, asset):
    """Legacy single-consumer caller; cannot collapse a multi-object asset."""
    treatments = _split_asset_treatments(layout, asset)
    if len(treatments) > 1:
        raise ValueError("Split evidence consumer requires its exact object treatment")
    return treatments[0] if treatments else None


def _split_asset_treatments(layout, asset):
    """Every layout consumer of one original, in canonical pair order."""
    consumers = [obj for obj in layout.objects if obj.asset_id == asset.asset_id]
    consumer_ids = {obj.object_id for obj in consumers}
    treatments = [item for item in layout.evidence_treatments
                  if item.intent.evidence_asset_id == asset.asset_id or item.object_id in consumer_ids]
    if asset.kind == "evidence":
        if (not consumers or any(type(obj) is not VisualObject or obj.object_type != "evidence" for obj in consumers)
                or len(treatments) != len(consumers) or {row.object_id for row in treatments} != consumer_ids
                or any(type(row) is not EvidenceTreatment or row.intent.evidence_asset_id != asset.asset_id
                       for row in treatments)):
            raise ValueError("Split evidence consumer requires its exact object treatment")
        return tuple(sorted(treatments, key=lambda row: (row.action_id, row.object_id)))
    if asset.kind in MEDIA_OBJECT_TYPES:
        if not consumers or treatments or any(obj.object_type != asset.kind for obj in consumers):
            raise ValueError("Frozen media consumer role differs from its exact asset kind")
        return ()
    if (asset.kind not in {"image", "source_image"} or not consumers or treatments
            or any(obj.object_type != "image" for obj in consumers)):
        raise ValueError("Split image consumer role differs from its asset kind")
    return ()


def _freeze_verified_split_evidence_asset(asset, pin, verified, layout):
    """One physical identity, independently attested complete consumer pairs."""
    from dataclasses import fields

    from atme.render.v2_split_identity import _stored_value

    if type(layout) is not ExecutableLayoutV2 or len(verified) < 2:
        raise ValueError("Split multi-consumer evidence requires its complete layout treatment tuple")
    layout = ExecutableLayoutV2.model_validate(_stored_value(layout))
    expected = _split_asset_treatments(layout, asset)
    if len(expected) < 2 or len(verified) != len(expected):
        raise ValueError("Split evidence treatment tuple differs from complete consumer inventory")
    if (asset.kind != "evidence" or not asset.provenance_verified or asset.media_type != "image/png"
            or asset.orientation != "upright" or pin.asset_id != asset.asset_id
            or pin.revision != asset.revision or pin.checksum_sha256 != asset.checksum_sha256
            or pin.resource_uri != f"atme://projects/{layout.project_id}/assets/{asset.asset_id}"):
        raise ValueError("Split evidence physical identity differs from its project pin")
    encoded = []
    payloads = set()
    for value, treatment in zip(verified, expected, strict=True):
        if (type(value) is not VerifiedEvidenceBytes
                or set(value.__dict__) != {field.name for field in fields(VerifiedEvidenceBytes)}
                or type(value.treatment) is not EvidenceTreatment or type(value.payload) is not bytes
                or type(value.asset_id) is not str or type(value.sha256) is not str
                or any(type(number) is not int for number in (value.revision, value.width, value.height))
                or (value.asset_id, value.revision, value.sha256, value.width, value.height)
                != (asset.asset_id, asset.revision, asset.checksum_sha256, asset.width, asset.height)):
            raise ValueError("Split evidence tuple contains an inexact or mixed physical snapshot")
        actual = _stored_value(value.treatment)
        if (actual != _stored_value(treatment)
                or (treatment.asset_revision, treatment.asset_checksum_sha256, treatment.asset_managed_ref,
                    treatment.asset_width, treatment.asset_height, treatment.allowed_transformations)
                != (asset.revision, asset.checksum_sha256, asset.managed_ref,
                    asset.width, asset.height, asset.allowed_transformations)):
            raise ValueError("Split evidence treatment differs from its exact consumer and source")
        encoded.append(_canonical(actual))
        payloads.add(value.payload)
    if len(payloads) != 1:
        raise ValueError("Split evidence consumers must share one exact original payload")
    payload, = payloads
    if len(payload) != asset.byte_length or sha256(payload).hexdigest() != asset.checksum_sha256:
        raise ValueError("Split evidence original bytes differ from verified metadata")
    raster = canonical_png(payload)
    if (raster.width, raster.height) != (asset.width, asset.height):
        raise ValueError("Split evidence original decoded dimensions differ")
    return _SplitAssetBytes(asset.asset_id, _canonical(asset.model_dump(mode="json")),
        _canonical(pin.model_dump(mode="json")), payload, None, treatments_json=tuple(encoded))


def _freeze_verified_split_asset(asset, pin, verified, *, layout=None):
    """Called only after the project resolver has checked ownership and URI."""
    asset = ResolvedAsset.model_validate(asset)
    pin = SplitAssetPin.model_validate(pin)
    if type(verified) is tuple:
        return _freeze_verified_split_evidence_asset(asset, pin, verified, layout)
    if (type(verified) not in (VerifiedImageBytes, VerifiedEvidenceBytes, VerifiedMediaBytes)
            or verified.asset_id != asset.asset_id or pin.asset_id != asset.asset_id
            or verified.revision != asset.revision or pin.revision != asset.revision
            or pin.resource_uri != (asset.managed_ref if layout is None
                                   else f"atme://projects/{layout.project_id}/assets/{asset.asset_id}")
            or verified.sha256 != asset.checksum_sha256 or pin.checksum_sha256 != asset.checksum_sha256
            or (verified.width, verified.height) != (asset.width, asset.height)
            or type(verified.payload) is not bytes or len(verified.payload) != asset.byte_length
            or sha256(verified.payload).hexdigest() != asset.checksum_sha256):
        raise ValueError("Split asset bytes differ from verified metadata or pin")
    if type(verified) is VerifiedMediaBytes:
        from atme.render.v2_media import inspect_media
        from atme.store.contracts_v2 import validate_media_asset_binding

        if (asset.kind not in MEDIA_OBJECT_TYPES or asset.media_stream is None or layout is None
                or type(verified.asset_id) is not str or type(verified.revision) is not int
                or type(verified.sha256) is not str or type(verified.width) is not int
                or type(verified.height) is not int or type(verified.stream_json) is not str
                or asset.media_type is None or not asset.media_type.startswith("video/")
                or asset.orientation != "upright" or asset.provenance_verified):
            raise ValueError("Frozen media requires its exact private original metadata")
        layout = ExecutableLayoutV2.model_validate(layout)
        expected_uri = f"atme://projects/{layout.project_id}/assets/{asset.asset_id}"
        owners = [obj for obj in layout.objects if obj.asset_id == asset.asset_id]
        if (not owners or asset.managed_ref != expected_uri or pin.resource_uri != expected_uri
                or any(obj.object_type != asset.kind for obj in owners)):
            raise ValueError("Frozen media requires its exact project, pin and owners")
        for obj in owners:
            validate_media_asset_binding(obj, asset)
        checked = inspect_media(verified.payload, asset.media_stream.stream_index)
        if (checked.pin != asset.media_stream or checked.pin.duration_ms != asset.duration_ms
                or checked.stream_document != verified.stream_json
                or (checked.pin.width, checked.pin.height) != (verified.width, verified.height)):
            raise ValueError("Frozen media stream differs from its recomputed original inventory")
        return _SplitAssetBytes(asset.asset_id, _canonical(asset.model_dump(mode="json")),
                               _canonical(pin.model_dump(mode="json")), verified.payload, None)
    evidence = type(verified) is VerifiedEvidenceBytes
    if not evidence and layout is not None:
        from atme.store.contracts_v2 import validate_image_asset_binding

        owners = [obj for obj in layout.objects if obj.object_type == "image" and obj.asset_id == asset.asset_id]
        if not owners or asset.managed_ref != f"atme://projects/{layout.project_id}/assets/{asset.asset_id}":
            raise ValueError("image_placement frozen asset requires the exact project and owners")
        for obj in owners:
            validate_image_asset_binding(obj, asset)
    if (asset.media_type != "image/png" or asset.orientation != "upright"
            or (evidence and (asset.kind != "evidence" or not asset.provenance_verified))
            or (not evidence and (asset.kind not in {"image", "source_image"}
                                    or asset.provenance_verified
                                    or layout is None and asset.allowed_transformations != ["scale"]))):
        raise ValueError("Split asset kind or transformation authority differs")
    treatment = EvidenceTreatment.model_validate(verified.treatment) if evidence else None
    if treatment is not None and (
            treatment.intent.evidence_asset_id != asset.asset_id
            or treatment.asset_revision != asset.revision
            or treatment.asset_checksum_sha256 != asset.checksum_sha256
            or treatment.asset_managed_ref != asset.managed_ref
            or (treatment.asset_width, treatment.asset_height) != (asset.width, asset.height)
            or treatment.allowed_transformations != asset.allowed_transformations):
        raise ValueError("Split evidence treatment differs from verified asset")
    raster = canonical_png(verified.payload)
    if (raster.width, raster.height) != (asset.width, asset.height):
        raise ValueError("Split asset decoded dimensions differ")
    return _SplitAssetBytes(asset.asset_id, _canonical(asset.model_dump(mode="json")),
                           _canonical(pin.model_dump(mode="json")), verified.payload,
                           _canonical(treatment.model_dump(mode="json")) if treatment else None)


def _revalidate_split_asset_row(layout, row):
    """Rebind every treatment and the one immutable physical snapshot."""
    asset = ResolvedAsset.model_validate_json(row.resolved_json)
    pin = SplitAssetPin.model_validate_json(row.pin_json)
    expected = _split_asset_treatments(layout, asset)
    actual = _row_evidence_treatments(row)
    if (tuple(_canonical(value.model_dump(mode="json")) for value in actual)
            != tuple(_canonical(value.model_dump(mode="json")) for value in expected)):
        raise ValueError("Split evidence consumer treatment inventory differs from layout")
    carrier = _VerifiedSplitAssetBytes((row,))
    if len(actual) > 1:
        verified = tuple(carrier.evidence_for(row.asset_id, value.action_id, value.object_id) for value in actual)
    else:
        value = carrier[row.asset_id]
        if asset.kind in MEDIA_OBJECT_TYPES:
            verified = VerifiedMediaBytes(row.asset_id, asset.revision, value, asset.checksum_sha256,
                asset.width, asset.height, asset.media_stream.model_dump_json() if asset.media_stream else "")
        else:
            verified = (value if type(value) is VerifiedEvidenceBytes else VerifiedImageBytes(
                row.asset_id, asset.revision, value, asset.checksum_sha256, asset.width, asset.height))
    if _freeze_verified_split_asset(asset, pin, verified, layout=layout) != row:
        raise ValueError("Split asset capture carrier changed after resolution")
    return asset, verified


def _verified_split_asset_pins(layout, carrier, referenced):
    """Compute a capture subset from checked original rows, never submitted pins."""
    required = {obj.asset_id for obj in layout.objects if obj.asset_id is not None}
    if not required and not carrier and not referenced:
        return []
    if type(carrier) is not _VerifiedSplitAssetBytes or set(carrier) != required or not referenced <= required:
        raise ValueError("Split asset capture requires exact trusted project asset inventory")
    pins = []
    for row in carrier.rows:
        _revalidate_split_asset_row(layout, row)
        pin = SplitAssetPin.model_validate_json(row.pin_json)
        if row.asset_id in referenced:
            pins.append(pin)
    return pins


@dataclass(frozen=True)
class VerifiedSplitPaintInputs:
    layout_sha256: str
    style_json: str
    registry_json: str
    bundle_bytes: tuple[tuple[str, str, bytes], ...] = field(repr=False)
    asset_pins_json: str
    project_assets: tuple[_SplitAssetBytes, ...] = field(repr=False)
    paint_evidence: tuple[str, ...]
    manifest_json: str
    inputs_sha256: str


def verify_split_paint_inputs(layout: ExecutableLayoutV2,
                             asset_bytes: Mapping[str, bytes | VerifiedEvidenceBytes]) -> VerifiedSplitPaintInputs:
    """Freeze actual byte evidence; this alone does not admit any Split family."""
    return _assemble_split_paint_inputs(layout, asset_bytes, _verified_split_bundle(layout))


def _assemble_split_paint_inputs(layout, asset_bytes, bundle):
    layout = ExecutableLayoutV2.model_validate(layout.model_dump(mode="json"))
    required = {obj.asset_id for obj in layout.objects if obj.asset_id is not None}
    if required and type(asset_bytes) is not _VerifiedSplitAssetBytes:
        raise ValueError("Split paint requires trusted project asset metadata")
    if not isinstance(asset_bytes, Mapping) or set(asset_bytes) != required:
        raise ValueError("Split paint requires the exact asset inventory")
    rows = asset_bytes.rows if type(asset_bytes) is _VerifiedSplitAssetBytes else ()
    evidence = []
    for row in rows:
        asset, verified = _revalidate_split_asset_row(layout, row)
        if asset.kind in MEDIA_OBJECT_TYPES:
            # Original-frame inventory evidence, not a still PNG/alpha claim or
            # a new Split participant adapter. Each sampled paint decodes its
            # own absolute clock through the owning media renderer.
            evidence.append(_canonical({"asset_id": row.asset_id, "kind": "decoded_video_inventory",
                "checksum_sha256": asset.checksum_sha256, "media_stream": json.loads(verified.stream_json)}))
            continue
        with Image.open(io.BytesIO(canonical_png(row.payload).payload)) as image:
            alpha_bounds = image.getchannel("A").getbbox()
        if alpha_bounds is None:
            raise ValueError("Split paint asset is entirely transparent")
        evidence.append(_canonical({"asset_id": row.asset_id, "kind": "decoded_png_alpha",
                                    "checksum_sha256": asset.checksum_sha256,
                                    "alpha_bounds": alpha_bounds}))
    resources = (PaperInkStyle.model_validate_json(bundle.style_json),
                 AssetRegistry.model_validate_json(bundle.registry_json),
                 {name: payload for name, _, payload in bundle.files}, asset_bytes)
    for obj in sorted(layout.objects, key=lambda item: item.object_id):
        adapter = _split_adapter(obj)
        if type(obj) is ConnectorObject and adapter is not None:
            evidence.append(_canonical({"object_id": obj.object_id, "family": adapter.family,
                "proof_kind": "connector_authored_recipe_v1", "recipe": _split_connector_recipe(obj, layout, resources)}))
            continue
        # Absence of a faithful leaf adapter is not positive evidence. Compound
        # closure/temporal admission is checked separately, never from root bounds.
        if adapter is not None and adapter.paint_evidence is not None:
            evidence.append(_canonical({"object_id": obj.object_id, "family": adapter.family,
                "proof_kind": adapter.proof_kind, "paint": adapter.paint_evidence(obj, layout, resources)}))
    pins_json = _canonical([json.loads(row.pin_json) for row in rows])
    layout_hash = sha256(_canonical(layout.model_dump(mode="json")).encode()).hexdigest()
    manifest = _canonical({"layout_sha256": layout_hash, "bundle": json.loads(bundle.manifest_json),
                           "asset_pins": json.loads(pins_json),
                           "project_assets": [{"resolved": json.loads(row.resolved_json),
                                               "treatment": json.loads(row.treatment_json)
                                               if row.treatment_json else None,
                                               **({"treatments": [json.loads(value) for value in row.treatments_json]}
                                                  if row.treatments_json else {})} for row in rows],
                           "paint_evidence": [json.loads(row) for row in evidence]})
    return VerifiedSplitPaintInputs(layout_hash, bundle.style_json, bundle.registry_json, bundle.files,
                                    pins_json, rows, tuple(evidence), manifest, sha256(manifest.encode()).hexdigest())


@dataclass(frozen=True)
class _SplitBundleInputs:
    style_json: str
    registry_json: str
    files: tuple[tuple[str, str, bytes], ...] = field(repr=False)
    manifest_json: str
    inputs_sha256: str


def _verified_split_bundle(layout: ExecutableLayoutV2) -> _SplitBundleInputs:
    """Freeze freshly checked bytes, not the mutable cached model's attestation.

    This is the bundle part of verified paint inputs, not a coverage proof.
    Only digest manifests belong in receipts; byte payloads stay in memory.
    """
    _, _, root = load_bundle()
    root = root.resolve()

    def payload(relative):
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Split bundle resource escaped its pinned root")
        return path.read_bytes()

    return _check_split_bundle(layout, payload)


def _check_split_bundle(layout, read_payload):
    layout = ExecutableLayoutV2.model_validate(layout.model_dump(mode="json"))
    checked = {}

    def read(relative, expected):
        payload = read_payload(relative)
        if sha256(payload).hexdigest() != expected:
            raise ValueError(f"Split bundle checksum mismatch: {relative}")
        if relative in checked and checked[relative] != (expected, payload):
            raise ValueError("Split bundle repeats a conflicting resource pin")
        checked[relative] = (expected, payload)
        return payload

    style = PaperInkStyle.model_validate_json(read("style.json", EXPECTED_STYLE_SHA256))
    registry = AssetRegistry.model_validate_json(read("asset-registry.json", EXPECTED_REGISTRY_SHA256))
    if (layout.style_system_version != style.system_id
            or layout.asset_registry_version != registry.registry_id
            or registry.style_version != style.version or registry.style_system_id != style.system_id):
        raise ValueError("Split paint requires the exact pinned style and registry versions")
    for font in style.fonts:
        read(font.file, font.sha256)
        read(font.license_file, font.license_sha256)
    for asset in registry.assets:
        read(asset.file, asset.sha256)
    code_font = None
    if any(isinstance(obj, TextObject) and obj.object_type == "code" for obj in layout.objects):
        from atme.render.code_font_bundle import verify_code_font_bundle

        code_font = verify_code_font_bundle(read_payload)
        for name, checksum, payload in code_font.files:
            if name in checked:
                raise ValueError("Split code-font resource conflicts with the legacy bundle")
            checked[name] = (checksum, payload)
    style_json = json.dumps(style.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    registry_json = json.dumps(registry.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    manifest_data = {"style": json.loads(style_json), "registry": json.loads(registry_json),
                     "files": {name: row[0] for name, row in sorted(checked.items())}}
    if code_font is not None:
        manifest_data["code_font"] = json.loads(code_font.manifest_json)
    manifest = json.dumps(manifest_data, sort_keys=True, separators=(",", ":"))
    return _SplitBundleInputs(style_json, registry_json,
                             tuple((name, *row) for name, row in sorted(checked.items())),
                             manifest, sha256(manifest.encode()).hexdigest())


def _checked_split_resources(layout, inputs):
    """Rebind an immutable carrier without reopening any mutable bundle file.

    This verifies canonical structure as well as digests. It is not a substitute
    for the project resolver that originally established ownership and revision.
    """
    if type(inputs) is not VerifiedSplitPaintInputs or type(inputs.bundle_bytes) is not tuple:
        raise ValueError("Split paint requires exact immutable verified inputs")
    files = {}
    for row in inputs.bundle_bytes:
        if (type(row) is not tuple or len(row) != 3 or type(row[0]) is not str
                or type(row[1]) is not str or type(row[2]) is not bytes
                or row[0] in files or sha256(row[2]).hexdigest() != row[1]):
            raise ValueError("Split frozen bundle row is invalid")
        files[row[0]] = row[2]
    try:
        bundle = _check_split_bundle(layout, files.__getitem__)
    except KeyError as exc:
        raise ValueError("Split frozen bundle resource is missing") from exc
    assets = _VerifiedSplitAssetBytes(inputs.project_assets)
    if _assemble_split_paint_inputs(layout, assets, bundle) != inputs:
        raise ValueError("Split frozen paint binding differs from its canonical inputs")
    return (PaperInkStyle.model_validate_json(bundle.style_json),
            AssetRegistry.model_validate_json(bundle.registry_json), files, assets)


def split_construction_for(snapshot: FrameSnapshot, object_id: str) -> SplitPaintEnvelope | None:
    """Return one captured root envelope without changing child-local records.

    Descendants share their root's construction envelope, not new child actions.
    The compositor still owns mode-specific path/glyph construction and clipping;
    this lookup alone is not evidence of painted coverage or family support.
    """
    if type(snapshot) is FrameSnapshot:
        return None
    if type(snapshot) is not SplitFrameSnapshot:
        raise ValueError("Split paint requires a known frame snapshot")
    envelopes = snapshot.envelopes
    ids = {frame.object_id for frame in snapshot.objects}
    if type(envelopes) is not tuple or not envelopes:
        raise ValueError("Split paint requires immutable nonempty envelopes")
    by_root = {}
    for envelope in envelopes:
        if (type(envelope) is not SplitPaintEnvelope
                or envelope.root_id not in ids or envelope.root_id in by_root
                or type(envelope.action_id) is not str or not envelope.action_id.strip()
                or envelope.mode not in {"reveal", "draw", "write", "enter"}
                or type(envelope.construction_fraction) not in (int, float)
                or not isfinite(envelope.construction_fraction)
                or not 0 <= envelope.construction_fraction <= 1):
            raise ValueError("Split paint has an invalid or duplicate construction envelope")
        by_root[envelope.root_id] = envelope
    for root in by_root:
        if any(ancestor in by_root for ancestor in snapshot.hierarchy.ancestors(root)):
            raise ValueError("Split construction envelopes overlap owned roots")
    if object_id not in ids:
        raise ValueError("Split paint references an unknown frame object")
    for candidate in (object_id, *snapshot.hierarchy.ancestors(object_id)):
        if candidate in by_root:
            return by_root[candidate]
    return None
