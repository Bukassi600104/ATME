"""Render the original R01-R03 diagnostic and capture inspectable landmarks.

This is a short silent renderer verification, not the full-video acceptance gate.
Usage: python bench/verify_board_continuity.py --output-dir <new directory>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sidecar" / "src"))


def main():
    from atme.render.animator import _FrameRenderer, build_draw_windows, render_video
    from atme.render.svg_builder import element_stroke_info
    from atme.store.contracts import LayoutDoc

    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    source = ROOT / "schemas" / "examples" / "board-continuity.example.json"
    doc = LayoutDoc.model_validate(json.loads(source.read_text(encoding="utf-8"))).model_dump()
    windows = build_draw_windows(doc["elements"])
    infos = {e["id"]: element_stroke_info(e, doc["seed"]) for e in doc["elements"]}
    renderer = _FrameRenderer(doc, infos, windows, 960, 540)
    landmarks = []
    for at, name in [(3300, "attention"), (3900, "clean-board"),
                     (6500, "measurement"), (7200, "board-return"), (9500, "resolution")]:
        frame = renderer.frame(at)
        frame.save(out / f"{name}.png")
        landmarks.append({"time_ms": at, "name": name,
                          "rgb_sha256": hashlib.sha256(frame.tobytes()).hexdigest()})
    clean = next(item for item in landmarks if item["name"] == "clean-board")
    returned = next(item for item in landmarks if item["name"] == "board-return")
    assert clean["rgb_sha256"] == returned["rgb_sha256"], "Board return changed its retained state"
    stats = render_video(doc, out / "board-continuity.mp4", width=960, height=540, fps=30)
    assert stats["duration_ms"] == 10000 and stats["frames"] == 300
    report = {"purpose": "Original silent diagnostic, not full production acceptance",
              "source": str(source), "landmarks": landmarks,
              "clean_board_equals_return": True, "render": stats}
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
