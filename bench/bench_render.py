"""Animator bake-rate benchmark (M0/M1 gate: >= 8 fps baked at 720p30).

Renders the fixture layout twice (cold, warm) and appends results to docs/CALIBRATION.md.
"""

from __future__ import annotations

import datetime as dt
import json
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOC = REPO / "docs" / "CALIBRATION.md"
LAYOUT = REPO / "schemas" / "examples" / "excalidraw-layout.example.json"


def main() -> int:
    doc = json.loads(LAYOUT.read_text(encoding="utf-8"))
    from atme.render.animator import render_video

    rows = []
    for run in ("cold", "warm"):
        t0 = time.perf_counter()
        stats = render_video(doc, Path(tempfile.mkdtemp()) / "b.mp4",
                             fps=30, width=1280, height=720, duration_ms=8000)
        stats["label"] = run
        stats["total_wall_s"] = round(time.perf_counter() - t0, 2)
        rows.append(stats)

    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    gate = min(r["bake_fps"] for r in rows)
    nl = chr(10)
    lines = [
        "", "## Run " + stamp + " (render bake rate)", "",
        "| Run | Frames | Wall s | Bake fps | Gate >= 8 fps |", "|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append("| %s | %d | %.2f | %.1f | %s |"
                     % (r["label"], r["frames"], r["wall_s"], r["bake_fps"],
                        "PASS" if r["bake_fps"] >= 8 else "**FAIL**"))
    lines.append("")
    lines.append("Verdict: **%s** (%.1f fps worst-case)" % ("PASS" if gate >= 8 else "FAIL", gate))
    with DOC.open("a", encoding="utf-8") as fh:
        fh.write(nl.join(lines) + nl)
    print(nl.join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
