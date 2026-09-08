"""Deterministic fallback layout: script scenes + measured starts -> valid LayoutDoc.

This is the safety net that keeps rendering possible even while the Spatial Agent (M2) is
offline, and the structural seed that agent will refine. Output is grid-snapped and validated
against schemas/excalidraw-layout.schema.json by tests.
"""

from __future__ import annotations

GRID = 50


def _snap(v: int) -> int:
    return max(0, int(round(v / GRID)) * GRID)


def build_layout(scenes: list[dict], scene_starts_ms: list[int], canvas_w: int = 1920,
                 canvas_h: int = 1080, seed: int = 7,
                 title: str | None = None) -> dict:
    n = len(scenes)
    box_w, box_h = 600, 200
    top_y = 300
    v_gap = 250
    elements: list[dict] = []
    camera_plan: list[dict] = []

    if title:
        elements.append({
            "id": "el-title", "scene_id": 1, "appear_at_ms": _snap(max(0, scene_starts_ms[0])),
            "type": "text", "x": _snap(canvas_w / 2 - len(title) * 12),
            "y": 100, "text": title, "size": "l",
        })

    centers = []
    for i, scene in enumerate(scenes[:n]):
        bx = _snap((canvas_w - box_w) / 2)
        by = _snap(top_y + i * (box_h + v_gap))
        label = str(scene.get("phase", "scene")).capitalize()
        elements.append({
            "id": "el-scene-%d" % (i + 1), "scene_id": i + 1,
            "appear_at_ms": int(scene_starts_ms[i]),
            "type": "rectangle", "x": bx, "y": by,
            "width": box_w, "height": box_h,
            "label": label, "stroke": "ink", "fillStyle": "hachure",
        })
        centers.append((bx, by))
        if i > 0:
            px, py = centers[i - 1]
            sx, sy = _snap(px + box_w / 2), _snap(py + box_h)
            ex, ey = _snap(bx + box_w / 2), _snap(by)
            elements.append({
                "id": "el-arrow-%d" % (i + 1), "scene_id": i + 1,
                "appear_at_ms": int(scene_starts_ms[i] - 250) if scene_starts_ms[i] >= 250 else 0,
                "type": "arrow",
                "start": {"x": _snap(px + box_w / 2), "y": _snap(py + box_h)},
                "end": {"x": ex, "y": ey},
                "startBinding": "el-scene-%d" % i, "endBinding": "el-scene-%d" % (i + 1),
            })

    for i, start in enumerate(scene_starts_ms):
        bx, by = centers[min(i, len(centers) - 1)]
        fw, fh = 1500, 850
        fx = _snap(max(0, min(canvas_w - fw, bx + box_w / 2 - fw / 2)))
        fy = int(max(0, min(canvas_h - fh, by + box_h / 2 - fh / 2)))
        camera_plan.append({"cue_ms": int(start), "focus": {"x": fx, "y": fy,
                                                            "width": fw, "height": fh},
                            "easing": "easeInOut"})
    camera_plan.sort(key=lambda c: c["cue_ms"])

    return {
        "contract_version": "1",
        "seed": seed,
        "canvas": {"width": canvas_w, "height": canvas_h},
        "grid": GRID,
        "roughness": 1,
        "elements": elements,
        "camera_plan": camera_plan,
    }
