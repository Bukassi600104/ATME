"""Explicit board authoring; no inferred cuts or silent object reassignment."""
from copy import deepcopy

from atme.store.contracts import LayoutDoc


def apply_board_edit(doc, timeline, assignments, duration_ms):
    if not isinstance(assignments, dict) or set(assignments) != {e["id"] for e in doc["elements"]}:
        raise ValueError("assign every existing element exactly once")
    result = deepcopy(doc)
    result["board_timeline"] = timeline
    for el in result["elements"]:
        assignment = assignments[el["id"]]
        if (not isinstance(assignment, dict)
                or not {"board_id", "appear_at_ms"} <= set(assignment)
                or set(assignment) - {"board_id", "appear_at_ms", "narration_trigger"}):
            raise ValueError("each assignment needs board_id and appear_at_ms")
        el.update(deepcopy(assignment))
        if "narration_trigger" in assignment and assignment["narration_trigger"] is None:
            el.pop("narration_trigger", None)
    LayoutDoc.model_validate(result)
    activations = timeline["activations"]
    if any(a["end_ms"] > duration_ms for a in activations):
        raise ValueError("board timeline exceeds final audio duration")
    for el in result["elements"]:
        if not any(a["board_id"] == el["board_id"] and
                   a["start_ms"] <= el["appear_at_ms"] < a["end_ms"] for a in activations):
            raise ValueError(el["id"] + ": board must be active at element creation")
    return result
