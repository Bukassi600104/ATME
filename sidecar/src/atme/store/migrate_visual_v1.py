"""Deterministic, immutable adapter from ATME visual contracts v1 to v2.

The adapter never overwrites v1 input and never invents unsupported semantics.  A
legacy instruction that cannot be resolved truthfully is retained as rejected
coverage plus an explicit migration warning.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy

from atme.store.contracts import LayoutDoc
from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    MigrationReportV2,
    VisualPlanV2,
    validate_plan_layout,
)

ADAPTER_VERSION = "v1-to-v2.1"
SUPPORTED_TARGET_ACTIONS = {
    "draw": "draw", "reveal": "reveal", "highlight": "highlight",
    "cross_out": "cross_out", "count": "count", "remove": "exit",
}


def _digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def migrate_visual_bundle_v1(
    visual_plan: dict,
    layout: dict,
    *,
    project_id: int,
    project_revision: int,
    plan_revision: int,
    layout_revision: int,
    narrative_authority: dict,
    output_profile: dict,
    style_system_version: str = "atme-style-v2",
    asset_registry_version: str = "atme-assets-v2",
) -> dict:
    """Return new v2 documents and a complete migration report.

    Repeating the call with byte-equivalent inputs and context produces the same
    IDs, documents and report.  The supplied dictionaries are never mutated.
    """
    if visual_plan.get("contract_version") != "1" or layout.get("contract_version") != "1":
        raise ValueError("v1-to-v2 adapter only accepts explicit contract_version '1'")
    LayoutDoc.model_validate(layout)
    source_plan = deepcopy(visual_plan)
    source_layout = deepcopy(layout)
    source_hashes = {"visual_plan": _digest(source_plan), "layout": _digest(source_layout)}
    migration_seed = _digest({
        "adapter": ADAPTER_VERSION, "sources": source_hashes, "project_id": project_id,
        "project_revision": project_revision, "plan_revision": plan_revision,
        "layout_revision": layout_revision, "narrative_authority": narrative_authority,
        "output_profile": output_profile, "style": style_system_version,
        "assets": asset_registry_version,
    })
    migration_id = f"migration-{migration_seed[:20]}"
    plan_id = f"plan-{migration_seed[:20]}"
    layout_id = f"layout-{migration_seed[:20]}"
    changes = {key: [] for key in ("inserted_defaults", "inferred_values",
                                    "unsupported_semantics", "degraded_fields")}
    warnings: list[str] = []
    for path, value, reason in (
        ("/style_system_version", style_system_version, "v1 had no versioned style system"),
        ("/asset_registry_version", asset_registry_version, "v1 had no asset registry"),
        ("/declared_capability_version", "visual-contracts-v2", "v2 capability discriminator"),
    ):
        changes["inserted_defaults"].append({"path": path, "value": str(value), "reason": reason})

    beat_ids = {int(beat["scene_id"]): beat["beat_id"] for beat in source_plan["beats"]}
    board_timeline = source_layout.get("board_timeline") or {}
    board_ids = [x["board_id"] for x in board_timeline.get("boards", [])]
    if not board_ids:
        raise ValueError("v1 migration requires an explicit board timeline")
    element_board = {item["id"]: item.get("board_id", board_ids[0]) for item in source_layout["elements"]}
    objects = []
    executable_objects = []
    by_scene: dict[int, list[str]] = {}
    for element in source_layout["elements"]:
        object_id = element["id"]
        scene_id = int(element["scene_id"])
        beat_id = beat_ids.get(scene_id)
        if beat_id is None:
            raise ValueError(f"layout element {object_id} references an unknown visual-plan scene")
        coverage_id = f"coverage-{beat_id}-1"
        asset_id = None
        object_type = _migrated_object_type(element, source_layout["elements"])
        semantic_role = element.get("label") or element.get("text") or object_type
        objects.append({
            "object_id": object_id, "object_type": object_type, "board_id": element_board[object_id],
            "beat_id": beat_id, "semantic_role": semantic_role,
            "description": f"Migrated v1 {element['type']} object", "asset_id": asset_id,
            "initial_state": "hidden", "coverage_ids": [coverage_id],
        })
        changes["inferred_values"].append({"path": f"/objects/{object_id}/semantic_role",
            "value": semantic_role, "reason": "derived from the v1 label/text/type"})
        for field, value in (("initial_state", "hidden"), ("description", f"Migrated v1 {element['type']} object"),
                             ("coverage_ids", coverage_id)):
            changes["inserted_defaults"].append({"path": f"/objects/{object_id}/{field}",
                "value": str(value), "reason": "v1 did not carry this executable-state field"})
        by_scene.setdefault(scene_id, []).append(object_id)
        migrated_element = {**element, "board_id": element_board[object_id]}
        executable_objects.append(_migrate_element(migrated_element, beat_id, coverage_id, source_layout["canvas"],
                                                    source_layout["elements"], changes, warnings))

    plan_actions = []
    coverage = []
    fallbacks = []
    beats = []
    for beat_index, beat in enumerate(source_plan["beats"]):
        scene_id = int(beat["scene_id"])
        targets = by_scene.get(scene_id, [])
        if not targets:
            raise ValueError(f"v1 beat {beat['beat_id']} has no layout object to migrate")
        beat_action_ids = []
        beat_coverage_ids = []
        beat_fallback_ids = []
        for action_index, legacy_verb in enumerate(beat["actions"]):
            instruction_id = f"legacy-{beat['beat_id']}-action-{action_index + 1}"
            coverage_id = f"coverage-{beat['beat_id']}-{action_index + 1}"
            fallback_id = f"fallback-{beat['beat_id']}-{action_index + 1}"
            action_id = f"action-{beat['beat_id']}-{action_index + 1}"
            beat_coverage_ids.append(coverage_id); beat_fallback_ids.append(fallback_id)
            mapped = SUPPORTED_TARGET_ACTIONS.get(legacy_verb)
            fallbacks.append({
                "fallback_id": fallback_id, "affected_ids": [instruction_id],
                "reason_code": "legacy_v1_fallback", "degradation_class": "visual_simplification",
                "substitute": beat["fallback"], "recoverable": True, "production_blocking": False,
                "user_exception_required": False, "status": "unused" if mapped else "selected",
            })
            if mapped and targets:
                changes["inferred_values"].append({"path": f"/actions/{action_id}/target_ids",
                    "value": ",".join(targets), "reason": "selected from v1 objects owned by the same scene"})
                if mapped == "exit":
                    changes["inferred_values"].append({
                        "path": f"/actions/{action_id}/post_state", "value": "removed",
                        "reason": "v1 remove becomes canonical permanent v2 exit",
                    })
                plan_actions.append({
                    "action_id": action_id, "source_instruction_id": instruction_id,
                    "board_id": element_board[targets[0]], "semantic_reason": beat["purpose"],
                    "trigger": {"kind": "phrase", "phrase": beat["trigger_phrase"],
                                "occurrence": 1, "offset_ms": 0, "minimum_confidence": 0.75},
                    "easing": "ease_out", "expected_state": "visible" if mapped == "exit" else "hidden",
                    "post_state": "removed" if mapped == "exit" else "visible",
                    "fallback": {"fallback_id": fallback_id, "on_failure": "degrade"},
                    "coverage_id": coverage_id, "verb": mapped, "target_ids": targets,
                    "annotation": None,
                })
                beat_action_ids.append(action_id)
                coverage.append({"coverage_id": coverage_id, "instruction_id": instruction_id,
                                 "status": "executed", "action_ids": [action_id], "fallback_id": None})
            else:
                coverage.append({"coverage_id": coverage_id, "instruction_id": instruction_id,
                                 "status": "rejected", "action_ids": [], "fallback_id": fallback_id})
                message = f"{instruction_id}: v1 action {legacy_verb!r} lacks typed parameters and was not invented"
                warnings.append(message)
                changes["unsupported_semantics"].append({"path": f"/beats/{beat_index}/actions/{action_index}",
                    "value": legacy_verb, "reason": "typed v2 parameters unavailable"})
        board_id = element_board[targets[0]] if targets else board_ids[min(beat_index, len(board_ids) - 1)]
        primary = targets[:1] or [f"board:{board_id}"]
        rhetorical = _rhetorical_role(beat_index, len(source_plan["beats"]), beat["purpose"])
        changes["inferred_values"].extend([
            {"path": f"/beats/{beat['beat_id']}/rhetorical_role", "value": rhetorical,
             "reason": "inferred from beat position and v1 purpose"},
            {"path": f"/beats/{beat['beat_id']}/attention/primary_targets", "value": ",".join(primary),
             "reason": "first scene-owned object is the conservative attention target"},
            {"path": f"/beats/{beat['beat_id']}/camera_intent/mode",
             "value": _camera_mode(beat["camera"]["action"]), "reason": "mapped from v1 camera action"},
        ])
        for field, value, reason in (
            ("attention/priority", "listen", "v1 had no listening/reading priority"),
            ("attention/progressive_state", "legacy_migrated", "v1 had no progressive attention state"),
            ("camera_intent/framing", "medium", "v1 had no framing declaration"),
            ("camera_intent/movement_purpose", "emphasize", "v1 had no camera-purpose enum"),
            ("sound_intent/role", "none", "v1 had no editorial sound intent"),
            ("continuity/expected_state_versions", "{}", "v1 had no object-state versions"),
        ):
            changes["inserted_defaults"].append({"path": f"/beats/{beat['beat_id']}/{field}",
                                                 "value": str(value), "reason": reason})
        beats.append({
            "beat_id": beat["beat_id"], "narration_summary": beat["narration"],
            "rhetorical_role": rhetorical,
            "visual_purpose": beat["purpose"], "board_id": board_id, "object_ids": targets,
            "action_ids": beat_action_ids,
            "attention": {"primary_targets": primary, "secondary_context": [], "dimmed_targets": [],
                          "priority": "listen", "progressive_state": "legacy_migrated"},
            "continuity": {"keep": beat["continuity"]["keep"], "change": [],
                           "remove": beat["continuity"]["remove"], "return_from_board_id": None,
                           "expected_state_versions": {}, "replacements": {},
                           "developed_return_state": None,
                           "hook_resolution_role": "opens_hook" if beat_index == 0 else
                           "resolves_hook" if beat_index == len(source_plan["beats"]) - 1 else "none"},
            "camera_intent": {"mode": _camera_mode(beat["camera"]["action"]),
                              "target_ids": primary, "reason": f"Legacy camera subject: {beat['camera']['subject']}",
                              "framing": "medium", "movement_purpose": "emphasize",
                              "duration_ms": 0, "easing": "ease_in_out"},
            "sound_intent": {"role": "none", "asset_id": None,
                             "reason": "No v1 sound intent existed", "gain_db": 0},
            "evidence": None, "fallback_ids": beat_fallback_ids,
            "coverage_ids": list(dict.fromkeys(beat_coverage_ids)),
        })
    board_objects = {board_id: [] for board_id in board_ids}
    for obj in objects:
        board_objects[obj["board_id"]].append(obj["object_id"])
    boards = [{
        "board_id": board_id, "template": "custom", "object_ids": ids,
        "persistence_policy": "returnable", "density_limit": max(1, min(12, len(ids))),
        "creation_reason": "Migrated from explicit v1 board timeline", "departure_reason": None,
        "return_reason": None, "expected_prior_state": None, "activation_policy": "returnable",
        "aspect_composition": {"LONG_FORM_16_9": "preserve migrated coordinates",
                               "SHORT_FORM_9_16": "requires independent composition review"},
    } for board_id, ids in board_objects.items()]
    for board in boards:
        for field in ("template", "persistence_policy", "density_limit", "creation_reason",
                      "activation_policy", "aspect_composition"):
            changes["inserted_defaults"].append({"path": f"/boards/{board['board_id']}/{field}",
                "value": str(board[field]), "reason": "v1 board timeline did not declare this directing field"})
    plan_v2 = {
        "contract_version": "2.0.0", "plan_id": plan_id, "project_id": project_id,
        "project_revision": project_revision, "narrative_authority": narrative_authority,
        "output_profile": output_profile, "style_system_version": style_system_version,
        "asset_registry_version": asset_registry_version, "declared_capability_version": "visual-contracts-v2",
        "assets": [], "objects": objects, "boards": boards, "actions": plan_actions,
        "beats": beats, "fallbacks": fallbacks, "coverage": coverage,
        "opening_beat_id": beats[0]["beat_id"], "conclusion_beat_id": beats[-1]["beat_id"],
    }
    VisualPlanV2.model_validate(plan_v2)
    activations = [{**item, "reason": "Migrated v1 board activation"}
                   for item in board_timeline["activations"]]
    layout_v2 = {
        "contract_version": "2.0.0", "layout_id": layout_id, "project_id": project_id,
        "project_revision": project_revision + 1, "plan_id": plan_id,
        "plan_revision": project_revision + 1,
        "plan_sha256": _digest(plan_v2), "output_profile": output_profile,
        "style_system_version": style_system_version, "asset_registry_version": asset_registry_version,
        "canvas": {"x": 0, "y": 0, "width": source_layout["canvas"]["width"],
                   "height": source_layout["canvas"]["height"]},
        "boards": boards, "objects": executable_objects, "activations": activations,
    }
    ExecutableLayoutV2.model_validate(layout_v2)
    validate_plan_layout(plan_v2, layout_v2)
    output_hashes = {"visual_plan_v2": _digest(plan_v2), "executable_layout_v2": _digest(layout_v2)}
    report = {
        "contract_version": "2.0.0", "migration_id": migration_id, "adapter_version": ADAPTER_VERSION,
        "source_contracts": {"visual_plan": "1", "layout": "1"},
        "source_revisions": {"visual_plan": plan_revision, "layout": layout_revision},
        "source_sha256": source_hashes, "output_sha256": output_hashes,
        **changes, "warnings": warnings,
        "lossless": not warnings and not any(changes.values()),
    }
    MigrationReportV2.model_validate(report)
    return {"visual_plan": plan_v2, "executable_layout": layout_v2, "migration_report": report}


def _migrate_element(element, beat_id, coverage_id, canvas, all_elements, changes, warnings):
    migrated_type = _migrated_object_type(element, all_elements)
    common = {
        "object_id": element["id"], "board_id": element["board_id"], "beat_id": beat_id,
        "semantic_role": element.get("label") or element.get("text") or migrated_type,
        "z_index": all_elements.index(element), "transform": {"position": {"x": 0, "y": 0},
            "scale_x": 1, "scale_y": 1, "rotation_degrees": 0, "origin": {"x": 0.5, "y": 0.5}},
        "opacity": 1, "visible": False, "style": {"stroke": element.get("stroke", "ink"),
            "fill": element.get("fillStyle"), "text": element.get("size"), "effect": None},
        "anchors": [{"anchor_id": "center", "point": {"x": 0.5, "y": 0.5}}],
        "parent_id": None, "clip_id": None, "initial_state": "hidden", "asset_id": None,
        "description": f"Migrated v1 {element['type']} object", "coverage_ids": [coverage_id],
    }
    for field in ("z_index", "transform", "opacity", "visible", "style", "anchors",
                  "parent_id", "clip_id", "initial_state", "coverage_ids"):
        changes["inserted_defaults"].append({"path": f"/executable_objects/{element['id']}/{field}",
            "value": str(common[field]), "reason": "v1 layout did not carry this v2 scene-graph field"})
    if element["type"] == "arrow":
        start, end = element["start"], element["end"]
        ids = {x["id"] for x in all_elements}
        source, destination = element.get("startBinding"), element.get("endBinding")
        if source in ids and destination in ids:
            common.update({"object_type": "arrow", "geometry": {"bounds": _line_bounds(start, end),
                "points": [start, end], "corner_radius": None}, "source_object_id": source,
                "source_anchor_id": "center", "destination_object_id": destination,
                "destination_anchor_id": "center", "role": "semantic_connector", "routing": "straight",
                "allow_self_loop": False})
            changes["inferred_values"].append({"path": f"/objects/{element['id']}/anchors",
                "value": f"{source}:center->{destination}:center",
                "reason": "v1 binding IDs were authoritative but named anchors did not exist"})
        else:
            common.update({"object_type": "line", "geometry": {"bounds": _line_bounds(start, end),
                "points": [start, end], "corner_radius": None}, "path_data": None})
            warnings.append(f"{element['id']}: unbound v1 arrow retained as nonsemantic line geometry")
            changes["degraded_fields"].append({"path": f"/elements/{element['id']}/type",
                "value": "line", "reason": "v1 supplied no authoritative relationship endpoints"})
        return common
    bounds = {"x": element.get("x", 0), "y": element.get("y", 0),
              "width": element.get("width", max(50, canvas["width"] // 4)),
              "height": element.get("height", max(50, canvas["height"] // 6))}
    common["geometry"] = {"bounds": bounds, "points": [], "corner_radius": 0}
    if element["type"] == "text":
        common.update({"object_type": "text", "text": element["text"], "items": []})
    elif element["type"] == "evidence_image":
        common.update({"object_type": "evidence", "variant": "legacy_embedded_evidence"})
        warnings.append(f"{element['id']}: embedded v1 evidence requires asset-registry extraction")
        changes["unsupported_semantics"].append({"path": f"/elements/{element['id']}/png_base64",
            "value": "embedded bytes", "reason": "v2 evidence must use a verified registry asset"})
    else:
        common.update({"object_type": "rectangle", "path_data": None})
    return common


def _line_bounds(start, end):
    return {"x": min(start["x"], end["x"]), "y": min(start["y"], end["y"]),
            "width": max(1, abs(end["x"] - start["x"])),
            "height": max(1, abs(end["y"] - start["y"]))}


def _migrated_object_type(element, all_elements):
    if element["type"] == "evidence_image":
        return "evidence"
    if element["type"] != "arrow":
        return element["type"]
    ids = {item["id"] for item in all_elements}
    return ("arrow" if element.get("startBinding") in ids and element.get("endBinding") in ids
            else "line")


def _rhetorical_role(index, count, purpose):
    if index == 0:
        return "hook"
    if index == count - 1:
        return "conclusion"
    return {"comparison": "comparison", "proof": "evidence", "causality": "mechanism"}.get(purpose, "example")


def _camera_mode(action):
    return {"hold": "hold", "pan": "pan", "zoom": "zoom", "reframe": "reframe",
            "follow": "pan", "return": "cut"}.get(action, "cut")
