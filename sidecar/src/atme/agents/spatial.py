"""Spatial/Layout agent: constrained placement + deterministic collision repair."""

from __future__ import annotations

import json
import logging

from atme.gateway.router import CompleteFn, Ledger, structured_call
from atme.resources import resource_path

log = logging.getLogger(__name__)

SCHEMAS = resource_path("schemas")
GRID = 50


def snap(v: int) -> int:
    return max(0, int(round(v / GRID)) * GRID)


def bbox(el: dict) -> tuple[int, int, int, int]:
    t = el["type"]
    if t == "rectangle":
        return el["x"], el["y"], el["x"] + el["width"], el["y"] + el["height"]
    if t == "text":
        w = max(GRID, 24 * len(str(el.get("text", ""))) // 2)
        h = 50
        return el["x"], el["y"], el["x"] + snap(w), el["y"] + h
    sx, sy = el["start"]["x"], el["start"]["y"]
    ex, ey = el["end"]["x"], el["end"]["y"]
    return min(sx, ex), min(sy, ey), max(sx, ex), max(sy, ey)


def overlaps(a: tuple, b: tuple, margin: int = 20) -> bool:
    return not (a[2] + margin <= b[0] or b[2] + margin <= a[0]
                or a[3] + margin <= b[1] or b[3] + margin <= a[1])


def repair_collisions(elements: list[dict]) -> int:
    """Push overlapping boxes/text apart within each board. Returns repair count.

    Legacy elements without board IDs share one implicit canvas. Different boards
    are never simultaneously visible and may deliberately reuse coordinates.
    """
    repairs = 0
    boxes = [e for e in elements if e["type"] in ("rectangle", "text")]
    for i in range(len(boxes)):
        moved = True
        guard = 0
        while moved and guard < 40:
            moved = False
            guard += 1
            bi = bbox(boxes[i])
            for j in range(len(boxes)):
                if i == j or boxes[i].get("board_id") != boxes[j].get("board_id"):
                    continue
                bj = bbox(boxes[j])
                if overlaps(bi, bj):
                    if "y" in boxes[i]:
                        boxes[i]["y"] = snap(boxes[i]["y"] + GRID * 2)
                    moved = True
                    repairs += 1
                    bi = bbox(boxes[i])
    return repairs


def layout(script_doc: dict, complete: CompleteFn, ledger: Ledger,
           canvas_w: int = 1920, canvas_h: int = 1080,
           visual_plan: dict | None = None) -> tuple[dict, dict]:
    """LLM places elements via constrained JSON, then deterministic repair + validation."""
    schema = json.loads((SCHEMAS / "excalidraw-layout.schema.json").read_text(encoding="utf-8"))

    scene_lines = ["scene %d [%s]: %s | directive: %s"
                   % (s["scene_id"], s["phase"], s["spoken_text"][:90], s["visual_directive"])
                   for s in script_doc["scenes"]]
    user = ("Canvas %dx%d, grid %d px. Create ONE diagram that grows across these scenes "
            "(elements accumulate). Use rectangle/text/arrow only; label everything; arrows "
            "carry meaning words." % (canvas_w, canvas_h, GRID))
    user += "\nScenes:\n" + "\n".join(scene_lines)
    if visual_plan:
        user += ("\n\nSemantic visual beats. Preserve continuity and use their actions/camera "
                 "intent while satisfying the layout schema:\n" +
                 json.dumps(visual_plan.get("beats", []), indent=1))

    doc, notes = structured_call(complete, ledger, "layouter", _system(), user, schema=schema)

    # normalize coordinates onto the grid (schema enforces too, but keep solver honest)
    for el in doc["elements"]:
        for key in ("x", "y"):
            if key in el:
                el[key] = snap(int(el[key]))
        for key in ("width", "height"):
            if key in el and isinstance(el[key], int):
                el[key] = max(GRID, snap(el[key]))
        for pt in ("start", "end"):
            if pt in el and isinstance(el[pt], dict):
                el[pt]["x"] = snap(el[pt]["x"])
                el[pt]["y"] = snap(el[pt]["y"])

    repairs = repair_collisions(doc["elements"])

    errors = [e.message for e in
              __import__("jsonschema").Draft202012Validator(schema).iter_errors(doc)]
    report = {"repair_moves": repairs, "schema_notes": notes, "residual_schema_errors": errors}
    log.info("layout: %d elements, %d repair moves", len(doc["elements"]), repairs)
    return doc, report


def _system() -> str:
    return resource_path("prompts", "spatial_system.md").read_text(encoding="utf-8")
