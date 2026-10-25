"""Real native evidence inside permitted rotated apertures, in both profiles."""

from copy import deepcopy
from hashlib import sha256
from io import BytesIO

import pytest
from atme.render.v2_svg import compose_png_frame
from PIL import Image, ImageChops
from test_v2_evidence_apertures import aperture_documents
from test_v2_evidence_compositor import evidence_documents
from test_v2_mask_contract import MASK_FIELDS
from v2_fixtures import digest


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("shape", ["rectangle", "rounded_rectangle", "ellipse", "polygon", "clip"])
def test_native_aperture_preserves_original_source_pixels_and_unclipped_card(tmp_path, shape, portrait):
    permissions = ["crop", "scale", "annotate", "color_treatment", "mask", "rotate"]
    service, layout, timeline, _ = evidence_documents(tmp_path, portrait=portrait, permissions=permissions)
    try:
        layout, timeline = aperture_documents(shape, clip=shape == "clip", documents=(layout, timeline))
        if shape == "clip":
            # Keep the border stroke inside the authored Clip, not on its edge.
            bounds = layout["objects"][3]["geometry"]["bounds"]
            bounds.update(x=bounds["x"] - 20, y=bounds["y"] - 20,
                          width=bounds["width"] + 40, height=bounds["height"] + 40)
            timeline["layout_sha256"] = digest(layout)
        verified = service.render_evidence_bytes(layout["project_id"], timeline["resolved_assets"][0],
                                                  layout["evidence_treatments"][0])
        payload = {verified.asset_id: verified}
        actual = compose_png_frame(layout, timeline, 4900, payload).png
        output = tmp_path / f"evidence-{shape}-{'portrait' if portrait else 'landscape'}-4900.png"
        output.write_bytes(actual)
        image = Image.open(BytesIO(actual)).convert("RGBA")
        assert image.size == ((720, 1280) if portrait else (1280, 720))
        pixels = image.load()
        red = sum(pixels[x, y] == (235, 30, 40, 255) for y in range(image.height) for x in range(image.width))
        assert red > 5000  # Literal original attested quadrant, not a source-derived expected PNG.
        control, clock = deepcopy(layout), deepcopy(timeline)
        control["objects"][3]["object_type"] = "group"
        if shape != "clip":
            mask_source_id = control["objects"][3]["mask_source_object_id"]
            for key in MASK_FIELDS:
                control["objects"][3].pop(key)
            # A mask's source is a nonpainting shape, not ordinary artwork.
            # Removing the aperture must not expose that shape as a new ink mark.
            control["objects"] = [obj for obj in control["objects"] if obj["object_id"] != mask_source_id]
            for board in control["boards"]:
                board["object_ids"] = [key for key in board["object_ids"] if key != mask_source_id]
            clock["initial_object_states"] = [row for row in clock["initial_object_states"]
                                               if row["object_id"] != mask_source_id]
            control["evidence_treatments"][0]["intent"]["mask_object_id"] = None
        clock["evidence_treatments"] = deepcopy(control["evidence_treatments"])
        clock["layout_sha256"] = digest(control)
        checked_control = service.render_evidence_bytes(layout["project_id"], clock["resolved_assets"][0],
                                                         control["evidence_treatments"][0])
        expected = compose_png_frame(control, clock, 4900, {checked_control.asset_id: checked_control}).png
        output.with_name("control.png").write_bytes(expected)
        control_image = Image.open(BytesIO(expected)).convert("RGBA")
        difference = ImageChops.difference(image, control_image)
        assert difference.getchannel("A").getbbox() is None
        assert all(high <= 2 for low, high in difference.convert("RGB").getextrema())
        control_pixels = control_image.load()
        assert red == sum(control_pixels[x, y] == (235, 30, 40, 255)
                          for y in range(image.height) for x in range(image.width))
        for at in (9000, 0, 4750):
            compose_png_frame(layout, timeline, at, payload)
        assert sha256(compose_png_frame(layout, timeline, 4900, payload).png).hexdigest() == sha256(actual).hexdigest()
    finally:
        service.store.close()
