"""Explicit authored Split packets; expected values never use Split implementation."""

from copy import deepcopy

from v2_fixtures import (
    common_action,
    digest,
    executable_layout_v2,
    resolved_timeline_v2,
    visual_plan_v2,
)


def split_policy(result_count=2):
    transform = {"position": {"x": 0.0, "y": 0.0}, "scale_x": 1.0,
                 "scale_y": 1.0, "rotation_degrees": 0.0,
                 "origin": {"x": .5, "y": .5}}
    ids = ["source"] + [f"part-{i + 1}" for i in range(result_count)]
    placements = []
    for ordinal, key in enumerate(ids):
        placements.append({
            "object_id": key, "parent_id": None, "sibling_ordinal": ordinal,
            "local_content_bounds": {"x": 10.0, "y": 10.0, "width": 20.0, "height": 20.0},
            "local_transform": deepcopy(transform),
            "world_matrix": [1.0, 0.0, 0.0, 1.0, 0.0, 0.0],
            "world_corners": [{"x": 10.0, "y": 10.0}, {"x": 30.0, "y": 10.0},
                              {"x": 30.0, "y": 30.0}, {"x": 10.0, "y": 30.0}],
            "world_bounds": {"x": 10.0, "y": 10.0, "width": 20.0, "height": 20.0},
            "state": "visible" if key == "source" else "hidden",
            "local_visibility": key == "source", "effective_visibility": key == "source",
            "reveal": 1.0 if key == "source" else 0.0,
            "local_opacity": 1.0, "state_version": 1, "content_sha256": "a" * 64,
        })
    basis = {"source_closure": {"root_id": "source", "owned_ids": ["source"]},
             "result_closures": [{"root_id": key, "owned_ids": [key]} for key in ids[1:]],
             "placements": sorted(placements, key=lambda row: row["object_id"]),
             "read_dependencies": [], "asset_pins": [],
             "style_sha256": "b" * 64, "registry_sha256": "c" * 64}
    return {"source_object_id": "source", "parent_policy": "common_parent",
            "source_exit": {"start_tick": 2000, "end_tick": 8000, "easing": "linear"},
            "results": [{"object_id": key, "correspondence_id": f"map-{key}",
                         "construction": {"mode": "reveal", "phase": {
                             "start_tick": 0, "end_tick": 6000, "easing": "linear"},
                             "enter_destination": None},
                         "movement": None, "destination": deepcopy(transform), "post_state": "visible"}
                        for key in ids[1:]],
            "correspondences": [{"correspondence_id": f"map-{key}",
                                 "source_object_id": "source", "source_content_sha256": "a" * 64,
                                 "result_object_id": key, "result_content_sha256": "a" * 64,
                                 "relationship": "authored_assertion", "statement": "Authored part",
                                 "source_region": None} for key in ids[1:]],
            "source_basis": basis, "source_basis_sha256": digest(basis)}


def split_action(result_count=2, *, policy=True):
    raw = {**common_action("split-1", "instruction-1"), "verb": "split",
           "target_ids": ["source"], "container_id": None,
           "easing": "linear", "expected_state": "visible", "post_state": "removed"}
    if policy:
        raw["split_policy"] = split_policy(result_count)
    return raw


def split_documents(profile_id="LONG_FORM_16_9", family="geometry", result_count=2,
                    parent_policy="common_parent"):
    """Contract fixture only; placeholder content pins are not runtime paint proof."""
    if family != "geometry" or parent_policy != "common_parent":
        raise ValueError("Fixture adapter not authored yet; do not synthesize unsupported artwork")
    if profile_id not in {"LONG_FORM_16_9", "SHORT_FORM_9_16"}:
        raise ValueError("Unknown fixture profile")
    plan = visual_plan_v2()
    layout = executable_layout_v2()
    action = split_action(result_count)
    profile = {"profile_id": profile_id, "width": 1280 if profile_id == "LONG_FORM_16_9" else 720,
               "height": 720 if profile_id == "LONG_FORM_16_9" else 1280, "fps": 30}
    placements = action["split_policy"]["source_basis"]["placements"]
    objects = []
    for placement in placements:
        obj = deepcopy(layout["objects"][0])
        obj.update(object_id=placement["object_id"], object_type="rectangle",
                   initial_state=placement["state"], visible=placement["effective_visibility"],
                   z_index=placement["sibling_ordinal"],
                   geometry={"bounds": deepcopy(placement["local_content_bounds"]),
                             "points": [], "corner_radius": None},
                   transform=deepcopy(placement["local_transform"]))
        objects.append(obj)
    ids = [obj["object_id"] for obj in objects]
    semantic_fields = plan["objects"][0].keys()
    plan.update(objects=[{key: obj[key] for key in semantic_fields} for obj in objects],
                actions=[action], assets=[], output_profile=profile)
    plan["coverage"] = [{"coverage_id": action["coverage_id"], "instruction_id": "instruction-1",
                         "status": "executed", "action_ids": ["split-1"], "fallback_id": None}]
    plan["fallbacks"] = [plan["fallbacks"][0]]
    plan["fallbacks"][0]["fallback_id"] = action["fallback"]["fallback_id"]
    plan["boards"][0]["object_ids"] = ids
    plan["boards"][0]["density_limit"] = max(12, len(ids))
    beat = plan["beats"][0]
    beat.update(object_ids=ids, action_ids=["split-1"], evidence=None,
                fallback_ids=[action["fallback"]["fallback_id"]], coverage_ids=[action["coverage_id"]])
    beat["attention"].update(primary_targets=["source"], secondary_context=[], dimmed_targets=[])
    beat["camera_intent"]["target_ids"] = ["source"]
    plan.update(beats=[beat], opening_beat_id=beat["beat_id"], conclusion_beat_id=beat["beat_id"])
    layout.update(objects=objects, boards=deepcopy(plan["boards"]), evidence_treatments=[],
                  plan_sha256=digest(plan), output_profile=profile,
                  canvas={"x": 0, "y": 0, "width": profile["width"], "height": profile["height"]})
    timeline = deepcopy(resolved_timeline_v2(plan, layout))
    timeline.update(output_profile=profile, resolved_assets=[],
                    beat_anchors=[{"beat_id": beat["beat_id"], "start_ms": 0}])
    timeline["initial_object_states"] = [
        {"object_id": obj["object_id"], "state": obj["initial_state"],
         "state_version": 1, "visible": obj["visible"]} for obj in objects]
    return plan, layout, timeline
