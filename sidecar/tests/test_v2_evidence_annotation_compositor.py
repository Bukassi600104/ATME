"""Real native evidence pixels plus authored, progressively constructed notes."""

import xml.etree.ElementTree as ET
from copy import deepcopy
from io import BytesIO

import pytest
from atme.render.v2_svg import compose_png_frame, compose_svg_frame
from PIL import Image
from test_v2_evidence_annotation_objects import cross_annotation_documents
from test_v2_evidence_compositor import evidence_documents
from v2_fixtures import digest


def native_cross_documents(tmp_path, *, portrait=False):
    service, real_layout, real_timeline, _ = evidence_documents(tmp_path, portrait=portrait)
    _, layout, timeline = cross_annotation_documents()
    intent = deepcopy(layout["evidence_treatments"][0]["intent"])
    layout["evidence_treatments"] = deepcopy(real_layout["evidence_treatments"])
    intent["evidence_asset_id"] = layout["evidence_treatments"][0]["intent"]["evidence_asset_id"]
    layout["evidence_treatments"][0]["intent"] = intent
    layout["objects"][2]["asset_id"] = intent["evidence_asset_id"]
    layout["project_id"] = real_layout["project_id"]
    layout["output_profile"] = deepcopy(real_layout["output_profile"])
    layout["canvas"] = deepcopy(real_layout["canvas"])
    timeline.update(project_id=real_timeline["project_id"], output_profile=deepcopy(real_timeline["output_profile"]),
                    resolved_assets=deepcopy(real_timeline["resolved_assets"]),
                    evidence_treatments=deepcopy(layout["evidence_treatments"]))
    timeline["actions"][2]["action"].update(evidence_asset_id=intent["evidence_asset_id"], easing="linear")
    if portrait:
        layout["objects"][2]["geometry"]["bounds"].update(x=110, y=540)
        layout["objects"][-2]["geometry"]["bounds"].update(x=110, y=1000, width=500)
        layout["objects"][-1]["geometry"]["bounds"] = {"x": 0, "y": 0, "width": 720, "height": 1280}
    timeline["layout_sha256"] = digest(layout)
    verified = service.render_evidence_bytes(layout["project_id"], timeline["resolved_assets"][0],
                                              layout["evidence_treatments"][0])
    return service, layout, timeline, {verified.asset_id: verified}


def object_node(root, key):
    return next(node for node in root.iter() if node.attrib.get("data-object-id") == key)


@pytest.mark.parametrize("portrait", [False, True])
def test_native_cross_annotation_uses_authored_notes_and_leader_without_inline_duplicate(tmp_path, portrait):
    service, layout, timeline, payload = native_cross_documents(tmp_path, portrait=portrait)
    try:
        partial = ET.fromstring(compose_svg_frame(layout, timeline, 4300, payload).svg)
        assert "".join(object_node(partial, "evidence-note").itertext()) == "Key me"
        leader_half = object_node(ET.fromstring(compose_svg_frame(layout, timeline, 4750, payload).svg), "evidence-leader")
        assert any("stroke-dasharray" in node.attrib for node in leader_half.iter())
        assert not any(node.tag.endswith("polygon") for node in leader_half.iter())
        svg = compose_svg_frame(layout, timeline, 4900, payload).svg
        root = ET.fromstring(svg)
        assert "".join(object_node(root, "evidence-note").itertext()) == "Key mechanism"
        assert any(node.tag.endswith("polygon") for node in object_node(root, "evidence-leader").iter())
        assert not any("data-evidence-annotation" in node.attrib for node in root.iter())
        assert any("data-evidence-crop" in node.attrib for node in root.iter())
        assert any("data-evidence-source-label" in node.attrib for node in root.iter())
    finally:
        service.store.close()


@pytest.mark.parametrize("portrait,red_pixel", [(False, (791, 265)), (True, (221, 675))])
def test_native_pixels_retain_attested_source_and_progressive_note_ink(tmp_path, portrait, red_pixel):
    service, layout, timeline, payload = native_cross_documents(tmp_path, portrait=portrait)
    try:
        frames = {at: compose_png_frame(layout, timeline, at, payload).png for at in (3999, 4300, 4900)}
        bounds = layout["objects"][-2]["geometry"]["bounds"]
        box = (bounds["x"], bounds["y"], bounds["x"] + bounds["width"], bounds["y"] + bounds["height"])
        ink = {}
        for at, png in frames.items():
            (tmp_path / f"cross-{'portrait' if portrait else 'landscape'}-{at}.png").write_bytes(png)
            with Image.open(BytesIO(png)) as image:
                region = image.convert("RGB").crop(box)
                pixels = region.load()
                ink[at] = sum(max(pixels[x, y]) < 120 for y in range(region.height) for x in range(region.width))
                if at == 4900:
                    assert image.convert("RGBA").getpixel(red_pixel) == (235, 30, 40, 255)
        assert ink[3999] == 0 < ink[4300] < ink[4900]
        for at in (9000, 0, 4750):
            compose_png_frame(layout, timeline, at, payload)
        assert compose_png_frame(layout, timeline, 4900, payload).png == frames[4900]
    finally:
        service.store.close()
