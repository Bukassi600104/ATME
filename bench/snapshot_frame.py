"""Dump single frames from a LayoutDoc as PNGs for visual QA.

    python bench/snapshot_frame.py --ms 500 3000 6000 --out data/out
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--layout", default="schemas/examples/excalidraw-layout.example.json")
    parser.add_argument("--out", default="data/out")
    parser.add_argument("--ms", type=int, nargs="+", required=True)
    args = parser.parse_args()

    doc = json.loads(Path(args.layout).read_text(encoding="utf-8"))
    from atme.render.animator import _FrameRenderer, build_draw_windows
    from atme.render.svg_builder import element_stroke_info

    windows = build_draw_windows(doc["elements"])
    infos = {el["id"]: element_stroke_info(el, doc["seed"]) for el in doc["elements"]}
    r = _FrameRenderer(doc, infos, windows, 1280, 720)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for ms in args.ms:
        img = r.frame(ms)
        p = out / ("frame_%07d.png" % ms)
        img.save(p)
        print("wrote", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
