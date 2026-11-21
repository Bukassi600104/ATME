"""Closed captions on the project's measured final-audio clock."""
from html import escape

from atme.audio.voice_upload import _token
from atme.project_service import ProjectError


def measured_cues(measured):
    structure = measured["semantic_structure"]
    context = structure.get("planning_context", {})
    report = structure.get("alignment_report", {})
    if (context.get("status") != "ready" or not report.get("matched_word_count")
            or report["matched_word_count"] != report["expected_word_count"]
            or report["matched_word_count"] != report["observed_word_count"]):
        raise ProjectError("captions_need_review", "Review the measured recording and transcript alignment")
    cues = []
    for scene in context["scenes"]:
        words = scene["words"]
        cursor, prefix = 0, []
        current = None
        for token in scene["narration"].split():
            labels = _token(token)
            if not labels:
                if current:
                    current["text"] += " " + token
                else:
                    prefix.append(token)
                continue
            section = words[cursor:cursor + len(labels)]
            if [word["word"].lower() for word in section] != labels:
                raise ProjectError("captions_need_review", "Caption words differ from the measured transcript")
            text = " ".join([*prefix, token])
            prefix.clear()
            start, end = section[0]["start_ms"], section[-1]["end_ms"]
            if (current is None or len(current["text"]) + 1 + len(text) > 42
                    or end - current["start_ms"] > 4500 or start - current["end_ms"] >= 600
                    or current["text"].endswith((".", "?", "!"))):
                current = {"cue_id": f"cue-{section[0]['word_index']}", "text": text,
                           "start_ms": start, "end_ms": end}
                cues.append(current)
            else:
                current.update(text=current["text"] + " " + text, end_ms=end)
            cursor += len(labels)
        if cursor != len(words) or prefix:
            raise ProjectError("captions_need_review", "A transcript segment needs editorial alignment")
    return cues


def validate_edits(cues, previous, duration):
    if not isinstance(cues, list) or len(cues) != len(previous):
        raise ProjectError("invalid_captions", "Edit the cues from the current measured track")
    end = 0
    for cue, original in zip(cues, previous):
        if not isinstance(cue, dict) or set(cue) != set(original) or cue["cue_id"] != original["cue_id"]:
            raise ProjectError("invalid_captions", "Caption identifiers and order must match the measured track")
        if (type(cue["start_ms"]) is not int or type(cue["end_ms"]) is not int
                or not end <= cue["start_ms"] < cue["end_ms"] <= duration):
            raise ProjectError("invalid_captions", f"{cue['cue_id']} overlaps another caption or exceeds the recording")
        text = cue["text"]
        if (not isinstance(text, str) or len(text) > 400 or len(text.split("\n")) > 2
                or any(not line.strip() for line in text.split("\n"))
                or any(ord(c) < 32 and c != "\n" for c in text)):
            raise ProjectError("invalid_captions", f"{cue['cue_id']} needs one or two lines of readable text")
        end = cue["end_ms"]


def serialize(cues, fmt):
    if fmt not in ("vtt", "srt"):
        raise ProjectError("invalid_format", "Choose SRT or WebVTT")
    def stamp(ms):
        seconds, fraction = divmod(ms, 1000)
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        separator = "." if fmt == "vtt" else ","
        return f"{hours:02}:{minutes:02}:{seconds:02}{separator}{fraction:03}"
    rows = ["WEBVTT", ""] if fmt == "vtt" else []
    for i, cue in enumerate(cues, 1):
        rows.extend([str(i), f"{stamp(cue['start_ms'])} --> {stamp(cue['end_ms'])}", escape(cue["text"], quote=False), ""])
    return "\n".join(rows) + "\n"
