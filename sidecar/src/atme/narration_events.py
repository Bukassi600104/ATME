"""Resolve authored element triggers against final-audio word alignment."""
from copy import deepcopy
import re


class TriggerResolutionError(ValueError):
    def __init__(self, report):
        self.report = report
        super().__init__("visual narration triggers need review: " + ", ".join(
            r["target_id"] + " (" + r["status"] + ")" for r in report
            if r["status"] != "resolved"))


def _tokens(text):
    return re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", text.lower().replace("’", "'"))


def resolve_narration_events(doc, words, duration_ms):
    """Return a copy and audit report. Never partially mutate on failed resolution.

    Each target uses its scene's words. Repeated phrases require a one-based
    occurrence. Untriggered elements retain explicitly authored final-audio times.
    """
    from atme.render.visibility import validate_visibility
    validate_visibility(doc)
    result = deepcopy(doc)
    report = []
    for el in result["elements"]:
        trigger = el.get("narration_trigger")
        if trigger is None:
            continue
        row = {"target_id": el["id"], "scene_id": el["scene_id"],
               "phrase": trigger["phrase"], "status": "missing"}
        report.append(row)
        observed, owners = [], []
        scene_words = sorted((w for w in words if w.get("scene_id") == el["scene_id"]),
                             key=lambda w: w["start_ms"])
        for word in scene_words:
            for token in _tokens(word["word"]):
                observed.append(token)
                owners.append(word)
        wanted = _tokens(trigger["phrase"])
        matches = [i for i in range(len(observed) - len(wanted) + 1)
                   if wanted and observed[i:i + len(wanted)] == wanted]
        row["match_count"] = len(matches)
        occurrence = trigger.get("occurrence")
        if not matches or (occurrence is not None and occurrence > len(matches)):
            continue
        if occurrence is None and len(matches) != 1:
            row["status"] = "ambiguous"
            continue
        first = matches[(occurrence or 1) - 1]
        matched = owners[first:first + len(wanted)]
        scores = [w.get("confidence") for w in matched]
        confidence = min(scores) if all(isinstance(s, (int, float))
                                        and 0 <= s <= 1 for s in scores) else None
        row["confidence"] = confidence
        if confidence is None:
            row["status"] = "confidence_unavailable"
            continue
        if confidence < trigger.get("min_confidence", 0.65) or any(w.get("flagged") for w in matched):
            row["status"] = "low_confidence"
            continue
        at = int(matched[0]["start_ms"]) + trigger.get("offset_ms", 0)
        row["at_ms"] = at
        if at < 0 or at >= duration_ms:
            row["status"] = "out_of_bounds"
            continue
        timeline = result.get("board_timeline")
        if timeline and not any(a["board_id"] == el["board_id"]
                                and a["start_ms"] <= at < a["end_ms"]
                                for a in timeline["activations"]):
            row["status"] = "inactive_board"
            continue
        el["appear_at_ms"] = at
        row["status"] = "resolved"
    if any(r["status"] != "resolved" for r in report):
        raise TriggerResolutionError(report)
    try:
        validate_visibility(result)  # reject conflicts with authored visibility intervals
    except ValueError as exc:
        if not report:
            raise
        for row in report:
            row["status"] = "timing_conflict"
            row["detail"] = str(exc)
        raise TriggerResolutionError(report) from exc
    return result, report
