"""Retain real paired hierarchy/annotation pixels without public Group admission.

This is mechanical private-consumer evidence, not Caleb-style creative acceptance.
Run with the existing sidecar Python environment. No network or source mutations.
"""

from __future__ import annotations

import json
import socket
import sys
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "sidecar/src"), str(ROOT / "sidecar/tests")]

from test_v2_annotation_action import append_target
from test_v2_group_annotation import (
    annotation_group_documents,
    consumer_clock,
    private_svg,
    regroup_first_documents,
)
from v2_fixtures import digest

from atme.render.v2_state import UnsupportedVisualAction, evaluate_frame
from atme.render.v2_svg import _rasterize_svg_frame


def no_network(*args, **kwargs):
    raise AssertionError("Group/annotation proof attempted network access")


def main():
    sheet = Image.new("RGB", (2000, 2880), "#101722")
    labels = ImageDraw.Draw(sheet)
    evidence = {"scope": "private paired consumers; public Group closed; not creative or installed acceptance",
                "frames": []}
    with patch.object(socket, "socket", no_network), patch.object(socket, "create_connection", no_network):
        for row, (mode, portrait) in enumerate((mode, portrait)
                for mode in ("ungroup", "group", "note-after-exit", "target-after-exit") for portrait in (False, True)):
            if mode in {"group", "ungroup"}:
                builder = regroup_first_documents if mode == "group" else annotation_group_documents
                layout, timeline = builder(nested=True, portrait=portrait)
                moments = (5999, 6000, 6500, 6750, 7999)
            else:
                shell = "annotation-group" if mode == "note-after-exit" else "target-group"
                layout, timeline = annotation_group_documents(shell, 8250, 8700, portrait=portrait)
                append_target(timeline, "annotation-leader", "exit", 8000, 8250)
                moments = (7999, 8125, 8250, 8699, 8700)
            timeline["layout_sha256"] = digest(layout)
            original = deepcopy((layout, timeline))
            context, replay, camera = consumer_clock(layout, timeline)
            profile = layout["output_profile"]["profile_id"]
            labels.text((10, row * 360 + 4), f"{mode} / {profile}", fill="white")
            for column, moment in enumerate(moments):
                svg = private_svg(context, replay, camera, moment)
                raw = _rasterize_svg_frame(context.layout, svg).png
                private_svg(context, replay, camera, 9000)
                assert _rasterize_svg_frame(context.layout, private_svg(context, replay, camera, moment)).png == raw
                evidence["frames"].append({"mode": mode, "profile": profile, "at_ms": moment,
                    "layout_sha256": digest(layout), "timeline_sha256": digest(timeline),
                    "svg_sha256": sha256(svg.svg.encode("utf-8")).hexdigest(), "png_sha256": sha256(raw).hexdigest()})
                image = Image.open(BytesIO(raw)).convert("RGB")
                image.thumbnail((384, 320), Image.Resampling.LANCZOS)
                sheet.paste(image, (column * 400, row * 360 + 35))
                labels.text((column * 400 + 10, row * 360 + 20), f"{moment} ms", fill="white")
            assert (layout, timeline) == original
            try:
                evaluate_frame(layout, timeline, moments[0])
            except UnsupportedVisualAction:
                pass
            else:
                raise AssertionError("Private proof unexpectedly opened public Group admission")
    destination = ROOT / "docs/visual-acceptance"
    destination.mkdir(parents=True, exist_ok=True)
    image_path = destination / "phase-3aa-group-annotation.png"
    sheet.save(image_path)
    evidence["contact_sheet_sha256"] = sha256(image_path.read_bytes()).hexdigest()
    report_path = destination / "phase-3aa-group-annotation.json"
    report_path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(f"PASS: {len(evidence['frames'])} immutable offline paired frames; {image_path}")
    print(f"Report SHA256: {sha256(report_path.read_bytes()).hexdigest()}")
    print(f"Contact sheet SHA256: {evidence['contact_sheet_sha256']}")


if __name__ == "__main__":
    main()
