"""Render a LayoutDoc to MP4 from the command line.

    python -m atme.render.demo --layout schemas/examples/excalidraw-layout.example.json ^
        --out data/out/demo.mp4 --duration-ms 12000
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--layout", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--duration-ms", type=int, default=None)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    args = parser.parse_args()

    doc = json.loads(Path(args.layout).read_text(encoding="utf-8"))
    from atme.render.animator import render_video

    def cb(done: int, total: int) -> None:
        sys.stderr.write("frame %d/%d\r" % (done, total))
        sys.stderr.flush()

    stats = render_video(doc, args.out, fps=args.fps, width=args.width, height=args.height,
                         duration_ms=args.duration_ms, progress_cb=cb)
    print("")
    print("stats:", json.dumps(stats))
    print("wrote:", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
