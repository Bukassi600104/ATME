"""Board-scoped visibility for research rules R01-R03.

All intervals are half-open on the final narration timeline. Creation/drawing
time is independent of visibility: restoring a board must not redraw its objects.
Legacy layouts without visibility metadata keep their existing behavior.
"""
from __future__ import annotations

import json
from functools import lru_cache

from jsonschema import Draft202012Validator

from atme.resources import resource_path


@lru_cache(maxsize=1)
def _validator():
    schema = json.loads(resource_path("schemas", "excalidraw-layout.schema.json")
                        .read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def validate_visibility(doc: dict) -> None:
    timeline = doc.get("board_timeline")
    has_metadata = "board_timeline" in doc or any(
        "board_id" in e or "visibility_intervals" in e or "enter_action" in e
        or e.get("type") == "evidence_image"
        or "narration_trigger" in e
        for e in doc["elements"])
    if not has_metadata:
        return
    errors = list(_validator().iter_errors(doc))
    if errors:
        error = errors[0]
        path = "/".join(str(p) for p in error.absolute_path)
        raise ValueError(f"invalid visibility layout at {path}: {error.message}")
    element_ids = [e["id"] for e in doc["elements"]]
    if len(element_ids) != len(set(element_ids)):
        raise ValueError("duplicate element ID in visibility layout")
    board_ids: set[str] = set()
    if timeline is not None:
        ids = [b["board_id"] for b in timeline["boards"]]
        board_ids = set(ids)
        if len(ids) != len(board_ids):
            raise ValueError("duplicate board ID")
        activation_ids: set[str] = set()
        previous_end = 0
        for activation in timeline["activations"]:
            if activation["activation_id"] in activation_ids:
                raise ValueError("duplicate board activation ID")
            activation_ids.add(activation["activation_id"])
            if activation["board_id"] not in board_ids:
                raise ValueError("board activation references an unknown board")
            start, end = activation["start_ms"], activation["end_ms"]
            if start >= end or start < previous_end:
                raise ValueError("board activations must be ordered, non-empty and non-overlapping")
            previous_end = end
    for element in doc["elements"]:
        if element["type"] == "evidence_image":
            from atme.render.evidence import validate_png
            validate_png(element["png_base64"], element["sha256"])
        if timeline is not None and element.get("board_id") not in board_ids:
            raise ValueError(f"{element['id']}: missing or unknown board reference")
        if timeline is None and "board_id" in element:
            raise ValueError(f"{element['id']}: board reference requires board_timeline")
        previous_end = element["appear_at_ms"]
        for interval in element.get("visibility_intervals", []):
            start, end = interval["start_ms"], interval["end_ms"]
            if start >= end or start < previous_end:
                raise ValueError(f"{element['id']}: visibility must be ordered, non-empty, "
                                 "non-overlapping and not precede creation")
            previous_end = end


def visible_elements(doc: dict, t_ms: int) -> list[dict]:
    """Evaluate visibility from time alone; no playback history is consulted."""
    timeline = doc.get("board_timeline")
    active_board = None
    if timeline is not None:
        active_board = next((a["board_id"] for a in timeline["activations"]
                             if a["start_ms"] <= t_ms < a["end_ms"]), None)
    visible = []
    for element in doc["elements"]:
        if t_ms < element["appear_at_ms"]:
            continue
        if timeline is not None and element.get("board_id") != active_board:
            continue
        intervals = element.get("visibility_intervals")
        if intervals is not None and not any(
                span["start_ms"] <= t_ms < span["end_ms"] for span in intervals):
            continue
        visible.append(element)
    return visible
