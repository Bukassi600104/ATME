"""Retain actual source-compositor pixels, with network access forbidden.

Run: sidecar/.venv/Scripts/python.exe bench/verify_v2_morph.py
This is a bounded source acceptance proof, not the public desktop preview.
"""

from __future__ import annotations

import json
import socket
import sys
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "sidecar/src"), str(ROOT / "sidecar/tests")]

from test_v2_morph_action import morph_documents
from v2_fixtures import digest

from atme.render.v2_svg import compose_png_frame


def no_network(*args, **kwargs):
    raise AssertionError("Offline morph proof attempted network access")


def main():
    moments = (6000, 6250, 6500, 6750, 7000)
    mappings = ("canonical_outline", "ordered_vertices", "matching_path_commands")
    sheet = Image.new("RGB", (1600, 660), "#101722")
    labels = ImageDraw.Draw(sheet)
    evidence = {"scope": "source-only private compositor; network forbidden", "frames": []}
    with patch.object(socket.socket, "connect", no_network), patch.object(socket, "create_connection", no_network):
        for row, mapping in enumerate(mappings):
            layout, timeline = morph_documents(mapping)
            # Isolate the authored change in the proof; unrelated fixture objects
            # are not an illustration treatment and must not obscure its pixels.
            layout["objects"][1]["opacity"] = 0
            layout["objects"][2]["opacity"] = 0
            timeline["layout_sha256"] = digest(layout)
            labels.text((10, row * 220 + 4), mapping, fill="white")
            for column, moment in enumerate(moments):
                result = compose_png_frame(layout, timeline, moment).png
                # Seek elsewhere first; same requested time must reproduce exact bytes.
                compose_png_frame(layout, timeline, 7400)
                assert compose_png_frame(layout, timeline, moment).png == result
                evidence["frames"].append({"mapping": mapping, "at_ms": moment,
                                            "sha256": sha256(result).hexdigest()})
                frame = Image.open(BytesIO(result)).convert("RGB").resize((320, 180))
                sheet.paste(frame, (column * 320, row * 220 + 35))
                labels.text((column * 320 + 10, row * 220 + 20), f"{moment} ms", fill="white")
    destination = ROOT / "docs/visual-acceptance"
    destination.mkdir(parents=True, exist_ok=True)
    image_path = destination / "phase-3y-morph.png"
    sheet.save(image_path)
    evidence["contact_sheet_sha256"] = sha256(image_path.read_bytes()).hexdigest()
    (destination / "phase-3y-morph.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(f"PASS: {len(evidence['frames'])} deterministic offline frames; {image_path}")


if __name__ == "__main__":
    main()
