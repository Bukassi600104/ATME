"""Generate checked Paper & Ink v2 manifests and JSON Schemas from canonical contracts."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sidecar" / "src"))

from atme.render.style_contracts import AssetRegistry, PaperInkStyle

RESOURCE = ROOT / "production-assets" / "paper-ink-v2"


def sha(relative: str) -> str:
    return hashlib.sha256((RESOURCE / relative).read_bytes()).hexdigest()


def viewbox(relative: str) -> tuple[int, int, int, int]:
    text = (RESOURCE / relative).read_text(encoding="utf-8")
    match = re.search(r'viewBox="(\d+) (\d+) (\d+) (\d+)"', text)
    if not match:
        raise ValueError(f"missing integer viewBox: {relative}")
    return tuple(int(value) for value in match.groups())


def font(font_id, family, role, weight, file, license_file, source_url):
    return {"id": font_id, "family": family, "role": role, "weight": weight,
            "file": file, "sha256": sha(file), "license": "OFL-1.1",
            "license_file": license_file, "license_sha256": sha(license_file),
            "source_url": source_url}


def asset(asset_id, family, keywords):
    relative = f"assets/{asset_id}.svg"
    attachment_points = {
        "person-presenter": {"head": [0.5, 0.25], "left_hand": [0.29, 0.78], "right_hand": [0.71, 0.78]},
        "person-collaborators": {"left_person": [0.3, 0.48], "right_person": [0.7, 0.48]},
        "gesture-point": {"wrist": [0.2, 0.72], "finger_tip": [0.86, 0.47]},
        "gesture-emphasis": {"wrist": [0.47, 0.84], "palm": [0.55, 0.45]},
        "device-laptop": {"screen": [0.5, 0.41], "keyboard": [0.5, 0.84]},
        "device-phone": {"screen": [0.5, 0.48], "speaker": [0.5, 0.1]},
        "document-stack": {"title": [0.4, 0.45], "last_line": [0.4, 0.8]},
        "document-checklist": {"first_task": [0.5, 0.28], "last_task": [0.5, 0.74]},
        "network-nodes": {"hub": [0.5, 0.47], "leaf_left": [0.2, 0.24], "leaf_right": [0.8, 0.24]},
        "network-pipeline": {"input": [0.16, 0.5], "transform": [0.5, 0.5], "output": [0.84, 0.5]},
        "chart-bars": {"baseline": [0.52, 0.86], "peak": [0.78, 0.22]},
        "chart-trend": {"start": [0.17, 0.71], "end": [0.8, 0.22]},
        "frame-code": {"content": [0.5, 0.58], "toolbar": [0.5, 0.16]},
        "frame-terminal": {"prompt": [0.22, 0.5], "output": [0.45, 0.73]},
        "metaphor-lightbulb": {"idea": [0.5, 0.42], "base": [0.5, 0.82]},
        "metaphor-bridge": {"source": [0.16, 0.64], "destination": [0.84, 0.64]},
    }
    return {"id": asset_id, "family": family, "file": relative, "sha256": sha(relative),
            "view_box": viewbox(relative), "keywords": keywords,
            "anchors": {"center": [0.5, 0.5], **attachment_points[asset_id]},
            "provenance": {"origin": "ATME-original", "author": "ATME project",
                           "created_for": "ATME Paper & Ink v2",
                           "derivative_of_reference_art": False, "license": "ATME-project"}}


def main() -> None:
    google_commit = "e44c4b011a820c2cbe2fd2cfa8052037d7edb571"
    atkinson_commit = "1cb311624b2ddf88e9e37873999d165a8cd28b46"
    style_data = {
        "contract": "atme.paper-ink-style", "version": "2.0.0",
        "system_id": "atme-style-v2", "identity": "ATME Paper & Ink",
        "colors": {"paper": "#FAF8F1", "ink": "#172033", "muted": "#526071",
                   "accent": "#2457D6", "accent-soft": "#DCE6FF", "attention": "#B93838",
                   "success": "#237252", "evidence-mask": "#172033",
                   "evidence-highlight": "#F4C95D", "caption-bg": "#172033", "caption-fg": "#FFFFFF"},
        "fonts": [
            font("kalam-regular", "Kalam", "display", 400, "fonts/Kalam-Regular.ttf", "fonts/OFL-Kalam.txt",
                 f"https://raw.githubusercontent.com/google/fonts/{google_commit}/ofl/kalam/Kalam-Regular.ttf"),
            font("kalam-bold", "Kalam", "display", 700, "fonts/Kalam-Bold.ttf", "fonts/OFL-Kalam.txt",
                 f"https://raw.githubusercontent.com/google/fonts/{google_commit}/ofl/kalam/Kalam-Bold.ttf"),
            font("atkinson-regular", "Atkinson Hyperlegible", "body", 400,
                 "fonts/AtkinsonHyperlegible-Regular.otf", "fonts/OFL-Atkinson-Hyperlegible.txt",
                 f"https://raw.githubusercontent.com/googlefonts/atkinson-hyperlegible/{atkinson_commit}/fonts/otf/AtkinsonHyperlegible-Regular.otf"),
            font("atkinson-bold", "Atkinson Hyperlegible", "body", 700,
                 "fonts/AtkinsonHyperlegible-Bold.otf", "fonts/OFL-Atkinson-Hyperlegible.txt",
                 f"https://raw.githubusercontent.com/googlefonts/atkinson-hyperlegible/{atkinson_commit}/fonts/otf/AtkinsonHyperlegible-Bold.otf"),
        ],
        "typography": {
            "title": {"font_id": "kalam-bold", "size_px": 56, "line_height": 1.1, "max_characters_per_line": 28},
            "label": {"font_id": "kalam-bold", "size_px": 26, "line_height": 1.15, "max_characters_per_line": 32},
            "body": {"font_id": "atkinson-regular", "size_px": 32, "line_height": 1.35, "max_characters_per_line": 52},
            "caption": {"font_id": "atkinson-bold", "size_px": 28, "line_height": 1.25, "max_characters_per_line": 42},
        },
        "spacing_px": {"xs": 8, "sm": 16, "md": 24, "lg": 40, "xl": 64, "xxl": 96},
        "strokes": {"fine_px": 2.0, "regular_px": 4.0, "emphasis_px": 7.0,
                    "corner_radius_px": 14, "roughness_px": 1.6},
        "aspects": {
            "landscape-16:9": {"width": 1920, "height": 1080,
                "safe_area": {"top_px": 54, "right_px": 64, "bottom_px": 90, "left_px": 64},
                "columns": 12, "column_gap_px": 24,
                "density": {"max_primary_objects": 7, "max_context_objects": 12,
                            "min_object_gap_px": 24, "min_read_hold_ms": 1400}},
            "portrait-9:16": {"width": 1080, "height": 1920,
                "safe_area": {"top_px": 92, "right_px": 48, "bottom_px": 160, "left_px": 48},
                "columns": 4, "column_gap_px": 20,
                "density": {"max_primary_objects": 5, "max_context_objects": 8,
                            "min_object_gap_px": 28, "min_read_hold_ms": 1600}},
        },
        "motion": {"draw_min_ms": 250, "draw_max_ms": 850, "transition_ms": 420,
                   "emphasis_ms": 700, "reduced_motion_uses_reveal": True},
        "captions": {"max_lines": 2, "max_characters_per_line": 42, "bottom_safe_offset_px": 64,
                     "background_color_token": "caption-bg", "foreground_color_token": "caption-fg"},
        "evidence": {"mask_color_token": "evidence-mask", "mask_opacity": 0.62,
                     "highlight_color_token": "evidence-highlight", "source_label_color_token": "muted",
                     "min_read_hold_ms": 2200},
        "accessibility": {"minimum_text_contrast": 4.5, "minimum_large_text_contrast": 3.0},
    }
    assets = [
        asset("person-presenter", "people", ["speaker", "teacher", "human"]),
        asset("person-collaborators", "people", ["team", "people", "collaboration"]),
        asset("gesture-point", "gestures", ["point", "direction", "attention"]),
        asset("gesture-emphasis", "gestures", ["hand", "emphasis", "explain"]),
        asset("device-laptop", "devices", ["computer", "code", "screen"]),
        asset("device-phone", "devices", ["phone", "mobile", "success"]),
        asset("document-stack", "documents", ["documents", "pages", "record"]),
        asset("document-checklist", "documents", ["checklist", "approval", "tasks"]),
        asset("network-nodes", "networks", ["network", "nodes", "distributed"]),
        asset("network-pipeline", "networks", ["pipeline", "flow", "stages"]),
        asset("chart-bars", "charts", ["chart", "bars", "comparison"]),
        asset("chart-trend", "charts", ["chart", "trend", "growth"]),
        asset("frame-code", "technical-frames", ["code", "editor", "syntax"]),
        asset("frame-terminal", "technical-frames", ["terminal", "command", "output"]),
        asset("metaphor-lightbulb", "abstract-metaphors", ["idea", "insight", "solution"]),
        asset("metaphor-bridge", "abstract-metaphors", ["bridge", "connection", "transition"]),
    ]
    style = PaperInkStyle.model_validate(style_data)
    registry = AssetRegistry.model_validate({"contract": "atme.paper-ink-assets", "version": "2.0.0",
                                             "registry_id": "atme-assets-v2", "style_version": "2.0.0",
                                             "style_system_id": "atme-style-v2", "assets": assets})
    generated = (
        (RESOURCE / "style.json", style.model_dump(mode="json")),
        (RESOURCE / "asset-registry.json", registry.model_dump(mode="json")),
        (ROOT / "schemas" / "paper-ink-style-v2.schema.json", PaperInkStyle.model_json_schema()),
        (ROOT / "schemas" / "paper-ink-assets-v2.schema.json", AssetRegistry.model_json_schema()),
    )
    for path, content in generated:
        with path.open("w", encoding="utf-8", newline="\n") as output:
            output.write(json.dumps(content, indent=2) + "\n")


if __name__ == "__main__":
    main()
