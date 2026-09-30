"""Project-owned PNG rendering never resolves an arbitrary path in the compositor."""

from __future__ import annotations

import binascii
import hashlib
import io
import struct
from copy import deepcopy

import pytest
from atme.project_service import ProjectError, ProjectService
from atme.render.v2_raster import UnsupportedProjectPNG, canonical_png
from atme.render.v2_svg import (
    UnsupportedVisualObject,
    compose_png_frame,
    compose_svg_frame,
)
from atme.store.db import JobStore
from PIL import Image
from test_v2_frame_state import supported_documents
from test_v2_svg import primitive_documents
from v2_fixtures import digest


def _png(size=(80, 40), color=(30, 100, 210, 255)):
    output = io.BytesIO()
    Image.new("RGBA", size, color).save(output, format="PNG")
    return output.getvalue()


def _chunk(kind, body):
    return (struct.pack(">I", len(body)) + kind + body
            + struct.pack(">I", binascii.crc32(kind + body) & 0xFFFFFFFF))


def _documents(asset_id, raw, revision, project_id):
    layout, timeline = primitive_documents()
    layout["project_id"] = project_id
    timeline["project_id"] = project_id
    obj = layout["objects"][2]
    obj["object_type"] = "image"
    obj["asset_id"] = asset_id
    obj["style"] = {"stroke": None, "fill": None, "text": None, "effect": None}
    obj["geometry"]["corner_radius"] = None
    obj["geometry"]["bounds"] = {"x": 700, "y": 120, "width": 400, "height": 400}
    obj["variant"] = None
    obj.pop("path_data", None)
    timeline["layout_sha256"] = digest(layout)
    timeline["resolved_assets"] = [{
        "asset_id": asset_id, "revision": revision,
        "managed_ref": f"atme://projects/{project_id}/assets/{asset_id}",
        "checksum_sha256": hashlib.sha256(raw).hexdigest(),
        "provenance_verified": False, "kind": "image", "media_type": "image/png",
        "byte_length": len(raw), "width": 80, "height": 40,
        "orientation": "upright", "allowed_transformations": ["scale"],
    }]
    return layout, timeline


def test_owned_png_renders_with_contain_geometry_and_random_access(tmp_path):
    service = ProjectService(JobStore(tmp_path / "project.db"))
    pid = service.create("Image", "LONG_FORM_16_9", "idea-first")["project_id"]
    staged = tmp_path / "upload.png"
    raw = _png()
    staged.write_bytes(raw)
    asset = service.attach_asset_file(pid, staged, "upload.png", 0)["asset"]
    layout, timeline = _documents(asset["asset_id"], raw, asset["revision"], pid)
    verified = service.render_image_bytes(pid, timeline["resolved_assets"][0])
    assert verified.payload == raw
    supplied = {asset["asset_id"]: verified.payload}
    svg = compose_svg_frame(layout, timeline, 5000, supplied).svg
    assert 'preserveAspectRatio="xMidYMid meet"' in svg
    assert "data:image/png;base64," in svg
    rendered = Image.open(io.BytesIO(compose_png_frame(layout, timeline, 5000, supplied).png)).convert("RGB")
    assert rendered.getpixel((900, 320)) == (30, 100, 210)
    assert rendered.getpixel((900, 140)) != (30, 100, 210)
    assert compose_png_frame(layout, timeline, 5000, supplied).png == (
        compose_png_frame(layout, timeline, 5000, supplied).png
    )
    service.store.close()


def test_missing_or_mismatched_image_bytes_fail_closed():
    raw = _png()
    asset_id = "a" * 32
    layout, timeline = _documents(asset_id, raw, 1, 1)
    with pytest.raises(UnsupportedVisualObject, match="lacks verified"):
        compose_svg_frame(layout, timeline, 5000)
    with pytest.raises(UnsupportedVisualObject, match="failed asset integrity"):
        compose_svg_frame(layout, timeline, 5000, {asset_id: _png(color=(0, 0, 0, 255))})
    wrong = deepcopy(timeline)
    wrong["resolved_assets"][0]["managed_ref"] = "file:///outside.png"
    with pytest.raises(UnsupportedVisualObject, match="lacks verified"):
        compose_svg_frame(layout, wrong, 5000, {asset_id: raw})
    wrong = deepcopy(timeline)
    wrong["resolved_assets"][0]["allowed_transformations"] = ["scale", "crop"]
    with pytest.raises(UnsupportedVisualObject, match="lacks verified"):
        compose_svg_frame(layout, wrong, 5000, {asset_id: raw})
    wrong = deepcopy(timeline)
    wrong["resolved_assets"][0]["kind"] = "evidence"
    with pytest.raises(UnsupportedVisualObject, match="lacks verified"):
        compose_svg_frame(layout, wrong, 5000, {asset_id: raw})
    wrong = deepcopy(timeline)
    wrong["resolved_assets"][0]["allowed_transformations"] = ["scale"]
    rotated = deepcopy(layout)
    rotated["objects"][2]["transform"]["rotation_degrees"] = 20
    wrong["layout_sha256"] = digest(rotated)
    with pytest.raises(UnsupportedVisualObject, match="cannot rotate"):
        compose_svg_frame(rotated, wrong, 5000, {asset_id: raw})


def test_hidden_image_still_requires_verified_bytes():
    raw = _png()
    asset_id = "b" * 32
    layout, timeline = _documents(asset_id, raw, 1, 1)
    with pytest.raises(UnsupportedVisualObject, match="lacks verified"):
        compose_svg_frame(layout, timeline, 0)
    wrong = deepcopy(timeline)
    wrong["resolved_assets"][0]["provenance_verified"] = True
    with pytest.raises(UnsupportedVisualObject, match="lacks verified"):
        compose_svg_frame(layout, wrong, 5000, {asset_id: raw})


def test_project_resolver_rejects_stale_tampered_and_other_project(tmp_path):
    service = ProjectService(JobStore(tmp_path / "project.db"))
    pid = service.create("Image", "LONG_FORM_16_9", "idea-first")["project_id"]
    other = service.create("Other", "LONG_FORM_16_9", "idea-first")["project_id"]
    raw = _png()
    staged = tmp_path / "upload.png"
    staged.write_bytes(raw)
    asset = service.attach_asset_file(pid, staged, "upload.png", 0)["asset"]
    _, timeline = _documents(asset["asset_id"], raw, asset["revision"], pid)
    resolved = timeline["resolved_assets"][0]
    with pytest.raises(ProjectError):
        service.render_image_bytes(other, resolved)
    with pytest.raises(ProjectError):
        service.render_image_bytes(pid, {**resolved, "revision": resolved["revision"] + 1})
    with pytest.raises(ProjectError, match="metadata"):
        service.render_image_bytes(pid, {**resolved, "provenance_verified": True})
    with pytest.raises(ProjectError, match="metadata"):
        service.render_image_bytes(pid, {**resolved, "allowed_transformations": ["scale", "rotate"]})
    with service.store._lock:
        service.store.conn.execute(
            "UPDATE project_assets SET relative_path=? WHERE job_id=? AND asset_id=?",
            ("../../outside.png", pid, asset["asset_id"]),
        )
        service.store.conn.commit()
    with pytest.raises(ProjectError, match="ownership"):
        service.render_image_bytes(pid, resolved)
    with service.store._lock:
        service.store.conn.execute(
            "UPDATE project_assets SET relative_path=? WHERE job_id=? AND asset_id=?",
            (f"project-assets/{pid}/{asset['asset_id']}.png", pid, asset["asset_id"]),
        )
        service.store.conn.commit()
    owned_path, _ = service.asset(pid, asset["asset_id"])
    owned_path.write_bytes(_png(color=(0, 0, 0, 255)))
    with pytest.raises(ProjectError, match="integrity"):
        service.render_image_bytes(pid, resolved)
    service.store.close()


def test_duplicate_project_can_resolve_its_shared_immutable_asset(tmp_path):
    service = ProjectService(JobStore(tmp_path / "project.db"))
    pid = service.create("Original", "LONG_FORM_16_9", "idea-first")["project_id"]
    raw = _png()
    staged = tmp_path / "upload.png"
    staged.write_bytes(raw)
    asset = service.attach_asset_file(pid, staged, "upload.png", 0)["asset"]
    copy_id = service.duplicate(pid)["project_id"]
    _, timeline = _documents(asset["asset_id"], raw, asset["revision"], copy_id)
    assert service.render_image_bytes(copy_id, timeline["resolved_assets"][0]).payload == raw
    service.store.close()


@pytest.mark.parametrize("raw", [
    b"not a png", _png() + b"trailing", _png()[:25],
    _png(size=(100, 100)) + b"junk",
])
def test_png_decoder_rejects_bad_source_bytes(raw):
    with pytest.raises(UnsupportedProjectPNG):
        canonical_png(raw)


def test_png_decoder_rejects_ancillary_metadata_and_bad_crc():
    raw = _png()
    before_idat = 8 + 25
    with pytest.raises(UnsupportedProjectPNG, match="metadata"):
        canonical_png(raw[:before_idat] + _chunk(b"tEXt", b"Comment\x00unsafe")
                      + raw[before_idat:])
    corrupted = bytearray(raw)
    corrupted[29] ^= 1
    with pytest.raises(UnsupportedProjectPNG, match="checksum"):
        canonical_png(bytes(corrupted))


def test_image_does_not_weaken_evidence_boundary():
    layout, timeline = supported_documents()
    with pytest.raises(UnsupportedVisualObject, match="verified project evidence"):
        compose_svg_frame(layout, timeline, 5000, {"asset-evidence": _png()})
