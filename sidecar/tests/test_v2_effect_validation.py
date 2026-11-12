"""Non-null effects reject at runtime without tightening legacy reads or rasterizing."""

from types import SimpleNamespace

import pytest
import resvg_py
from atme.render import v2_code, v2_svg
from atme.render.code_font_bundle import CODE_FONT_MANIFEST, CodeFontManifest
from atme.render.style_bundle import load_bundle
from atme.render.v2_callout import callout_body_svg
from atme.render.v2_chart import chart_svg
from atme.render.v2_connector import UnsupportedConnector, validate_static_arrow
from atme.render.v2_hierarchy import UnsupportedHierarchy, validate_authored_hierarchy
from atme.render.v2_mask import UnsupportedMask, mask_source_region
from atme.render.v2_state import V2FrameError, validate_static_hierarchy
from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    GroupAction,
    TextObject,
    VisualObject,
)
from PIL import ImageFont
from test_v2_callout_contract import callout_documents
from test_v2_chart_contract import chart_documents
from test_v2_code_glyphs import authored_code
from test_v2_connector_svg import connector_documents
from test_v2_group_hierarchy import grouped_documents
from test_v2_hierarchy_contract import receipt_documents
from test_v2_mask_contract import masked_documents
from test_v2_svg import primitive_documents
from v2_fixtures import digest


@pytest.fixture(autouse=True)
def forbid_native_render(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("effect validation must precede native rendering/font measurement")

    monkeypatch.setattr(resvg_py, "svg_to_bytes", forbidden)
    monkeypatch.setattr(ImageFont, "truetype", forbidden)
    monkeypatch.setattr(v2_svg, "_font", forbidden)


@pytest.mark.parametrize("effect", [None, "", "shadow"])
def test_mark_preflight_preserves_null_and_legacy_effect_roundtrip(effect):
    layout, _ = primitive_documents()
    layout["objects"][0]["style"]["effect"] = effect
    parsed = ExecutableLayoutV2.model_validate(layout)
    assert ExecutableLayoutV2.model_validate(parsed.model_dump(mode="json")) == parsed
    obj = parsed.objects[0]
    style, _, root = load_bundle()
    if effect is None:
        assert v2_svg._preflight_object(obj, style, root, 1., {}) is None
    else:
        with pytest.raises(v2_svg.UnsupportedVisualObject, match="effect"):
            v2_svg._preflight_object(obj, style, root, 1., {})


@pytest.mark.parametrize("effect", ["", "shadow"])
@pytest.mark.parametrize("at_ms", [0, 1000])
def test_public_png_entry_rejects_effect_even_when_hidden_before_native_render(effect, at_ms):
    layout, timeline = primitive_documents()
    layout["objects"][0]["style"]["effect"] = effect
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(v2_svg.UnsupportedVisualObject, match="effect"):
        v2_svg.compose_png_frame(layout, timeline, at_ms)


@pytest.mark.parametrize("effect", [None, "", "shadow"])
@pytest.mark.parametrize("owner", ["container", "mask", "connector", "hierarchy"])
def test_geometry_owners_reject_non_null_effect(effect, owner):
    if owner == "container":
        layout, _ = grouped_documents()
        parsed = ExecutableLayoutV2.model_validate(layout)
        obj = next(obj for obj in parsed.objects if obj.object_type == "group")
        def invoke():
            return validate_static_hierarchy(parsed)
        error, message = V2FrameError, "non-painting stacking context"
    elif owner == "mask":
        _, layout, _ = masked_documents()
        parsed = ExecutableLayoutV2.model_validate(layout)
        obj = next(obj for obj in parsed.objects if obj.object_id == "mask-source")
        def invoke():
            return mask_source_region(obj, obj.transform)
        error, message = UnsupportedMask, "painted style"
    elif owner == "connector":
        layout, _ = connector_documents()
        parsed = ExecutableLayoutV2.model_validate(layout)
        objects = {obj.object_id: obj for obj in parsed.objects}
        obj = objects["object-arrow"]
        def invoke():
            return validate_static_arrow(obj, objects)
        error, message = UnsupportedConnector, "ignored geometry or styling"
    else:
        plan, _, objects = receipt_documents()
        action = GroupAction.model_validate(plan["actions"][-1])
        obj = objects["object-group"]
        def invoke():
            return validate_authored_hierarchy(action, objects)
        error, message = UnsupportedHierarchy, "nonpainting group"
    obj.style.effect = effect
    if effect is None:
        invoke()
    else:
        with pytest.raises(error, match=message):
            invoke()


@pytest.mark.parametrize("effect", [None, "", "shadow"])
@pytest.mark.parametrize("owner", ["callout", "chart", "code"])
def test_text_owners_reject_effect_before_font_measurement(monkeypatch, effect, owner):
    class FontBoundaryReached(Exception):
        pass

    def stop_before_font(*args, **kwargs):
        raise FontBoundaryReached

    style, _, root = load_bundle()
    if owner == "callout":
        _, layout, _ = callout_documents()
        obj = TextObject.model_validate(next(obj for obj in layout["objects"]
                                            if obj["object_id"] == "annotation-note"))
        obj.style.stroke = obj.style.fill = None
        obj.geometry.corner_radius = None
        monkeypatch.setattr(v2_svg, "_text", stop_before_font)
        def invoke():
            return callout_body_svg(obj, style, 1., b"")
        error, message = v2_svg.UnsupportedVisualObject, "effect"
    elif owner == "chart":
        obj = VisualObject.model_validate(chart_documents()[1]["objects"][0])
        fonts = {font.file: (root / font.file).read_bytes() for font in style.fonts}
        monkeypatch.setattr(v2_svg, "_font", stop_before_font)
        def invoke():
            return chart_svg(obj, style, 1., fonts)
        error, message = ValueError, "effect"
    else:
        obj = authored_code("x=1")
        obj.style.stroke = obj.style.fill = None
        obj.style.text = "text.code"
        # Resource/glyph proof is a separate gate; isolate the subsequent style owner.
        monkeypatch.setattr(v2_code, "code_glyph_metrics", lambda *args: None)
        manifest_json = (root / CODE_FONT_MANIFEST).read_text(encoding="utf-8")
        manifest = CodeFontManifest.model_validate_json(manifest_json)
        bundle = SimpleNamespace(manifest_json=manifest_json,
                                 files=((manifest.font.file, manifest.font.sha256,
                                         (root / manifest.font.file).read_bytes()),))
        monkeypatch.setattr(ImageFont, "truetype", stop_before_font)
        def invoke():
            return v2_code.code_svg(obj, style, 1., bundle)
        error, message = v2_code.UnsupportedCode, "unstyled authored bounds"
    obj.style.effect = effect
    with pytest.raises(FontBoundaryReached if effect is None else error,
                       match=None if effect is None else message):
        invoke()
