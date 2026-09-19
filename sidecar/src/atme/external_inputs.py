"""Small no-provider adapter for externally authored research-first productions."""
import json
from copy import deepcopy

from jsonschema import Draft202012Validator
from atme.resources import resource_path
from atme.store.contracts import LayoutDoc
from atme.render.camera import validate_camera_intent


def validate_external_inputs(script, layout):
    schema = json.loads(resource_path("schemas", "script-scenes.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(script)
    ids = [s["scene_id"] for s in script["scenes"]]
    if len(ids) != len(set(ids)):
        raise ValueError("script scene IDs must be unique")
    LayoutDoc.model_validate(layout)
    if not layout.get("board_timeline"):
        raise ValueError("external production needs an explicit board timeline; no generic fallback")
    validate_camera_intent(layout.get("camera_plan", []))
    if {e["scene_id"] for e in layout["elements"]} != set(ids):
        raise ValueError("layout must cover exactly the script's scenes")
    for el in layout["elements"]:
        if not any(a["board_id"] == el["board_id"] and a["start_ms"] <= el["appear_at_ms"] < a["end_ms"]
                   for a in layout["board_timeline"]["activations"]):
            raise ValueError("object creation must fall within its active board")
    return deepcopy(script), deepcopy(layout)
