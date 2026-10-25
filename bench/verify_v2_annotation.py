"""Retain annotation phase pixels and offline/random-seek proof.

Run: sidecar/.venv/Scripts/python.exe bench/verify_v2_annotation.py
This is mechanical source-compositor proof, not final creative acceptance.
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

from test_v2_annotation_contract import leader_documents
from v2_fixtures import digest

from atme.render.v2_svg import compose_png_frame


def no_network(*args, **kwargs):
    raise AssertionError("Offline annotation proof attempted network access")


def main():
    moments = (6000, 6250, 6500, 6750, 7000)
    sheet = Image.new("RGB", (1920, 720), "#101722")
    labels = ImageDraw.Draw(sheet)
    evidence = {"scope": "source-only compositor mechanics; network forbidden; not creative acceptance",
                "frames": []}
    with patch.object(socket.socket, "connect", no_network), patch.object(socket, "create_connection", no_network):
        for row, profile in enumerate(("LONG_FORM_16_9", "SHORT_FORM_9_16")):
            _, layout, timeline = leader_documents()
            if row:
                for doc in (layout, timeline):
                    doc["output_profile"] = {"profile_id": profile, "width": 720, "height": 1280, "fps": 30}
                layout["canvas"].update(width=720, height=1280)
                layout["objects"][-1]["geometry"]["bounds"]["width"] = 600
                timeline["layout_sha256"] = digest(layout)
            origin_y = 0 if not row else 280
            labels.text((10, origin_y + 4), profile + " / authored note then pointer", fill="white")
            for column, moment in enumerate(moments):
                result = compose_png_frame(layout, timeline, moment).png
                compose_png_frame(layout, timeline, 7999)
                assert compose_png_frame(layout, timeline, moment).png == result
                evidence["frames"].append({"profile": profile, "at_ms": moment,
                                            "sha256": sha256(result).hexdigest()})
                size = (384, 216) if not row else (224, 398)
                frame = Image.open(BytesIO(result)).convert("RGB").resize(size)
                sheet.paste(frame, (column * 384, origin_y + 35))
                labels.text((column * 384 + 10, origin_y + 20), f"{moment} ms", fill="white")
    destination = ROOT / "docs/visual-acceptance"
    destination.mkdir(parents=True, exist_ok=True)
    image_path = destination / "phase-3z-annotation.png"
    sheet.save(image_path)
    evidence["contact_sheet_sha256"] = sha256(image_path.read_bytes()).hexdigest()
    (destination / "phase-3z-annotation.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(f"PASS: {len(evidence['frames'])} deterministic offline frames; {image_path}")


if __name__ == "__main__":
    main()
