"""Real shared preview/frozen paint for authored external aperture reads."""
import io
import xml.etree.ElementTree as ET
from copy import deepcopy
from dataclasses import replace

import pytest
from PIL import Image
from test_v2_external_aperture_contract import external_aperture_documents
from v2_fixtures import digest

from atme.render.v2_state import evaluate_frame
from atme.render.v2_svg import (
    _rasterize_svg_frame,
    _shape,
    compose_png_frame,
    compose_svg_frame,
)
from atme.render.v2_world import transform_svg
from atme.store import contracts_v2 as contracts

SVG = "http://www.w3.org/2000/svg"


def runtime_documents(kind, *, portrait=False, group=False):
    plan, layout, clock, ids = external_aperture_documents(kind, portrait=portrait, group=group)
    art, aperture = layout["objects"][1:3]
    art.pop("registry_binding")
    art.pop("variant")
    art.update(object_type="rectangle", style={"stroke": None, "fill": "ink", "text": None, "effect": None})
    art["geometry"]["bounds"] = {"x": 10., "y": 10., "width": 25., "height": 25.}
    plan["objects"][1].pop("registry_binding")
    plan["objects"][1]["object_type"] = "rectangle"
    aperture["geometry"]["bounds"] = {"x": 0., "y": 0., "width": 100., "height": 100.}
    leaf = next(obj for obj in layout["objects"] if obj["object_id"] == "external-receiver")
    leaf["geometry"]["bounds"] = {"x": 0., "y": 0., "width": 160., "height": 160.}
    leaf["transform"].update(position={"x": 40., "y": 0.}, scale_x=1., scale_y=1.,
                              rotation_degrees=0., origin={"x": 0., "y": 0.})
    leaf["style"] = {"stroke": None, "fill": "attention", "text": None, "effect": None}
    if group:
        subtree = next(obj for obj in layout["objects"] if obj["object_id"] == ids["receiver"])
        subtree["transform"].update(position={"x": 0., "y": 0.}, scale_x=1., scale_y=1.,
                                     rotation_degrees=0., origin={"x": 0., "y": 0.})
    if kind == "mask":
        layout["objects"][3]["geometry"]["bounds"] = deepcopy(aperture["geometry"]["bounds"])
    layout["plan_sha256"] = digest(plan)
    clock.update(plan_sha256=digest(plan), layout_sha256=digest(layout))
    contracts.validate_plan_layout(plan, layout)
    return plan, layout, clock, ids


def unclipped_documents(layout, clock):
    plain, timing = deepcopy(layout), deepcopy(clock)
    for obj in plain["objects"]:
        obj["clip_id"] = None
    timing["layout_sha256"] = digest(plain)
    return plain, timing


def native_oracle(layout, clock, ids, kind, at_ms, *, wrap_id=None, asset_bytes=None):
    """Independent nesting oracle, not an inverse-matrix/AABB implementation.

    At the authored common root, native SVG transform factors describe the
    named aperture. The normal consumer branch is wrapped there. This yields
    the same pixels as a consumer-parent-relative projection without invoking
    the new external runtime or its matrix construction.
    """
    plain, timing = unclipped_documents(layout, clock)
    frame = compose_svg_frame(plain, timing, at_ms, asset_bytes)
    tree = ET.fromstring(frame.svg)
    objects = {obj.object_id: obj for obj in contracts.ExecutableLayoutV2.model_validate(plain).objects}
    states = {state.object_id: state for state in evaluate_frame(plain, timing, at_ms).objects}
    owner = objects[ids["aperture"]]
    source = objects[owner.mask_source_object_id] if kind == "mask" else owner
    chain = [source.object_id]
    parent = source.parent_id
    while parent != ids["root"]:
        assert parent is not None
        chain.append(parent)
        parent = objects[parent].parent_id
    defs = ET.SubElement(tree, f"{{{SVG}}}defs")
    name = "independent-native-aperture"
    tag = "mask" if kind == "mask" else "clipPath"
    attrs = ({"maskUnits": "userSpaceOnUse", "maskContentUnits": "userSpaceOnUse",
              "x": "-2048", "y": "-2048", "width": "4096", "height": "4096", "style": "mask-type:alpha"}
             if kind == "mask" else {"clipPathUnits": "userSpaceOnUse"})
    definition = ET.SubElement(defs, f"{{{SVG}}}{tag}", {"id": name, **attrs})
    if kind == "mask":
        cursor = definition
        for key in reversed(chain):
            cursor = ET.SubElement(cursor, f"{{{SVG}}}g", {"transform": transform_svg(objects[key], states[key].transform)})
        cursor.append(ET.fromstring(_shape(source, "none", "#ffffff", 0)))
    else:
        bounds = source.geometry.bounds
        # SVG clipPath accepts a shape, not a group. Keep the independent native
        # factor chain on that rect rather than using an invalid nested <g>.
        ET.SubElement(definition, f"{{{SVG}}}rect", {
            **{key: str(getattr(bounds, key)) for key in ("x", "y", "width", "height")},
            "transform": " ".join(transform_svg(objects[key], states[key].transform) for key in reversed(chain))})
    selected = wrap_id or ids["receiver"]
    parent_element = next(node for node in tree.iter() if any(child.attrib.get("data-object-id") == selected for child in node))
    index, child = next((i, child) for i, child in enumerate(parent_element) if child.attrib.get("data-object-id") == selected)
    parent_element.remove(child)
    wrapper = ET.Element(f"{{{SVG}}}g", {"mask" if kind == "mask" else "clip-path": f"url(#{name})"})
    wrapper.append(child)
    parent_element.insert(index, wrapper)
    expected = replace(frame, svg=ET.tostring(tree, encoding="unicode"))
    return _rasterize_svg_frame(contracts.ExecutableLayoutV2.model_validate(plain), expected).png


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["clip", "mask"])
@pytest.mark.parametrize("group", [False, True])
def test_external_aperture_paints_the_whole_consumer_once_without_reparenting_or_owner_repaint(tmp_path, kind, portrait, group):
    _plan, layout, clock, ids = runtime_documents(kind, portrait=portrait, group=group)
    original = deepcopy((layout, clock))
    plain, timing = unclipped_documents(layout, clock)
    unrestricted = compose_png_frame(plain, timing, 1000).png  # Establish a genuinely playable fixture first.
    actual = compose_png_frame(layout, clock, 1000).png
    expected = native_oracle(layout, clock, ids, kind, 1000)
    (tmp_path / "external-aperture.png").write_bytes(actual)
    (tmp_path / "native-oracle.png").write_bytes(expected)
    assert actual == expected
    assert actual != unrestricted
    image = Image.open(io.BytesIO(actual)).convert("RGB")
    assert len(set(image.get_flattened_data())) > 2
    root = ET.fromstring(compose_svg_frame(layout, clock, 1000).svg)
    for key in (ids["art"], ids["receiver"], "external-receiver"):
        assert sum(node.attrib.get("data-object-id") == key for node in root.iter()) == 1
    if kind == "mask":
        assert all(node.attrib.get("data-object-id") != ids["source"] for node in root.iter())
    assert (layout, clock) == original
