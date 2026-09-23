"""Small rich fixtures shared by v2 schema, model, migration, and service tests."""

from __future__ import annotations

import hashlib
import json

SHA_A = "a" * 64
SHA_B = "b" * 64
PROFILE = {"profile_id": "LONG_FORM_16_9", "width": 1280, "height": 720, "fps": 30}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def common_action(action_id, instruction_id, board_id="board-main"):
    suffix = action_id.rsplit("-", 1)[-1]
    return {"action_id": action_id, "source_instruction_id": instruction_id,
            "board_id": board_id, "semantic_reason": "Explain the narrated concept",
            "trigger": {"kind": "phrase", "phrase": "system begins", "occurrence": 1,
                        "offset_ms": 0, "minimum_confidence": 0.75},
            "easing": "ease_out", "expected_state": "hidden", "post_state": "visible",
            "fallback": {"fallback_id": f"fallback-{suffix}", "on_failure": "block"},
            "coverage_id": f"coverage-{suffix}"}


def visual_plan_v2(project_revision=3):
    actions = [
        {**common_action("action-1", "instruction-1"), "verb": "draw",
         "target_ids": ["object-system"], "annotation": None},
        {**common_action("action-2", "instruction-2"), "verb": "write",
         "target_ids": ["object-label"], "annotation": None},
        {**common_action("action-3", "instruction-3"), "verb": "insert_evidence",
         "evidence_asset_id": "asset-evidence", "destination_board_id": "board-main",
         "destination_state": "evidence_visible"},
    ]
    fallbacks = [{"fallback_id": f"fallback-{n}", "affected_ids": [f"instruction-{n}"],
                  "reason_code": "asset_or_timing_failure", "degradation_class": "none",
                  "substitute": "No substitute; preserve meaning and block", "recoverable": True,
                  "production_blocking": True, "user_exception_required": False, "status": "unused"}
                 for n in range(1, 4)]
    coverage = [{"coverage_id": f"coverage-{n}", "instruction_id": f"instruction-{n}",
                 "status": "executed", "action_ids": [f"action-{n}"], "fallback_id": None}
                for n in range(1, 4)]
    return {
        "contract_version": "2.0.0", "plan_id": "plan-rich", "project_id": 1,
        "project_revision": project_revision,
        "narrative_authority": {"mode": "recording_only", "authority_id": "media-narration",
            "timing_media_id": "media-narration", "timing_media_sha256": SHA_A,
            "cleaned_timeline_revision": 2, "cleaned_timeline_fingerprint": SHA_B},
        "output_profile": PROFILE, "style_system_version": "atme-style-v2",
        "asset_registry_version": "atme-assets-v2", "declared_capability_version": "visual-contracts-v2",
        "assets": [{"asset_id": "asset-evidence", "revision": 1, "kind": "evidence",
            "semantic_role": "Primary-source proof", "managed_ref": "assets/evidence.png",
            "checksum_sha256": SHA_A, "width": 900, "height": 500, "duration_ms": None,
            "provenance": {"category": "external_evidence", "source_uri": "https://example.com/source",
                "checksum_sha256": SHA_A, "license_status": "licensed",
                "fabrication_prohibited": True, "originality_status": "reference_only"},
            "style_family": None, "style_version": None,
            "allowed_transformations": ["crop", "scale", "annotate", "color_treatment"],
            "fallback_id": "fallback-3"}],
        "objects": [
            {"object_id": "object-system", "object_type": "rounded_rectangle", "board_id": "board-main",
             "beat_id": "beat-001", "semantic_role": "System boundary", "description": "Main system",
             "asset_id": None, "initial_state": "hidden", "coverage_ids": ["coverage-1"]},
            {"object_id": "object-label", "object_type": "text", "board_id": "board-main",
             "beat_id": "beat-001", "semantic_role": "System label", "description": "Short label",
             "asset_id": None, "initial_state": "hidden", "coverage_ids": ["coverage-2"]},
            {"object_id": "object-evidence", "object_type": "evidence", "board_id": "board-main",
             "beat_id": "beat-002", "semantic_role": "Proof", "description": "Cropped source evidence",
             "asset_id": "asset-evidence", "initial_state": "hidden", "coverage_ids": ["coverage-3"]},
        ],
        "boards": [{"board_id": "board-main", "template": "evidence_annotation",
            "object_ids": ["object-system", "object-label", "object-evidence"],
            "persistence_policy": "returnable", "density_limit": 6,
            "creation_reason": "Establish and develop one persistent mental model",
            "departure_reason": None, "return_reason": "Return with evidence",
            "expected_prior_state": None, "activation_policy": "returnable",
            "aspect_composition": {"LONG_FORM_16_9": "left model, right evidence",
                                   "SHORT_FORM_9_16": "stack model above evidence"}}],
        "actions": actions,
        "beats": [
            {"beat_id": "beat-001", "narration_summary": "The system begins with one boundary.",
             "rhetorical_role": "hook", "visual_purpose": "containment", "board_id": "board-main",
             "object_ids": ["object-system", "object-label"], "action_ids": ["action-1", "action-2"],
             "attention": {"primary_targets": ["object-system"], "secondary_context": ["object-label"],
                           "dimmed_targets": [], "priority": "listen", "progressive_state": "system_established"},
             "continuity": {"keep": [], "change": [], "remove": [], "return_from_board_id": None,
                            "expected_state_versions": {}, "replacements": {}, "developed_return_state": None,
                            "hook_resolution_role": "opens_hook"},
             "camera_intent": {"mode": "hold", "target_ids": ["object-system"],
                               "reason": "Let the viewer construct the opening model", "framing": "wide",
                               "movement_purpose": "orient", "duration_ms": 0, "easing": "step"},
             "sound_intent": {"role": "none", "asset_id": None, "reason": "Narration carries the hook", "gain_db": 0},
             "evidence": None, "fallback_ids": ["fallback-1", "fallback-2"],
             "coverage_ids": ["coverage-1", "coverage-2"]},
            {"beat_id": "beat-002", "narration_summary": "The evidence resolves the opening claim.",
             "rhetorical_role": "conclusion", "visual_purpose": "proof", "board_id": "board-main",
             "object_ids": ["object-evidence"], "action_ids": ["action-3"],
             "attention": {"primary_targets": ["object-evidence"], "secondary_context": ["object-system"],
                           "dimmed_targets": ["object-label"], "priority": "inspect",
                           "progressive_state": "evidence_resolves_hook"},
             "continuity": {"keep": ["object-system"], "change": [], "remove": [],
                            "return_from_board_id": "board-main", "expected_state_versions": {"object-system": 1},
                            "replacements": {}, "developed_return_state": "evidence_visible",
                            "hook_resolution_role": "resolves_hook"},
             "camera_intent": {"mode": "cut", "target_ids": ["object-evidence"],
                               "reason": "Evidence requires immediate readable framing", "framing": "detail",
                               "movement_purpose": "return", "duration_ms": 0, "easing": "step"},
             "sound_intent": {"role": "purposeful_silence", "asset_id": None,
                              "reason": "Leave room to inspect evidence", "gain_db": 0},
             "evidence": {"claim_id": "claim-1", "claim": "The source confirms the mechanism",
                          "evidence_asset_id": "asset-evidence",
                          "crop": {"x": 0, "y": 0, "width": 900, "height": 500},
                          "focus_region": {"x": 100, "y": 100, "width": 500, "height": 200},
                          "mask_object_id": None, "darkening": 0.2, "source_label": "Example Source",
                          "annotation": "Key mechanism", "annotation_target_id": "object-evidence",
                          "annotation_omission_reason": None, "readable_hold_intent_ms": 2500,
                          "destination_board_id": "board-main", "destination_state": "evidence_visible",
                          "provenance_verified": True, "checksum_verified": True},
             "fallback_ids": ["fallback-3"], "coverage_ids": ["coverage-3"]},
        ],
        "fallbacks": fallbacks, "coverage": coverage,
        "opening_beat_id": "beat-001", "conclusion_beat_id": "beat-002",
    }


def executable_layout_v2(plan=None):
    plan = plan or visual_plan_v2()
    common = {"board_id": "board-main", "z_index": 1,
              "transform": {"position": {"x": 0, "y": 0}, "scale_x": 1, "scale_y": 1,
                            "rotation_degrees": 0, "origin": {"x": 0.5, "y": 0.5}},
              "opacity": 1, "visible": False, "style": {"stroke": "ink.primary", "fill": "surface.raised",
              "text": None, "effect": None}, "anchors": [{"anchor_id": "center", "point": {"x": 0.5, "y": 0.5}}],
              "parent_id": None, "clip_id": None, "initial_state": "hidden", "asset_id": None}
    objects = [
        {**common, "object_id": "object-system", "beat_id": "beat-001", "semantic_role": "System boundary",
         "object_type": "rounded_rectangle", "geometry": {"bounds": {"x": 80, "y": 160, "width": 480, "height": 340},
         "points": [], "corner_radius": 24}, "description": "Main system", "coverage_ids": ["coverage-1"], "path_data": None},
        {**common, "object_id": "object-label", "beat_id": "beat-001", "semantic_role": "System label", "z_index": 2,
         "object_type": "text", "geometry": {"bounds": {"x": 140, "y": 210, "width": 320, "height": 80},
         "points": [], "corner_radius": None}, "style": {"stroke": None, "fill": None, "text": "text.heading", "effect": None},
         "description": "Short label", "coverage_ids": ["coverage-2"], "text": "THE SYSTEM", "items": []},
        {**common, "object_id": "object-evidence", "beat_id": "beat-002", "semantic_role": "Proof", "z_index": 3,
         "object_type": "evidence", "geometry": {"bounds": {"x": 680, "y": 130, "width": 500, "height": 420},
         "points": [], "corner_radius": 12}, "asset_id": "asset-evidence", "description": "Cropped source evidence",
         "coverage_ids": ["coverage-3"], "variant": "annotated_crop"},
    ]
    return {"contract_version": "2.0.0", "layout_id": "layout-rich", "project_id": 1,
            "project_revision": plan["project_revision"] + 1, "plan_id": plan["plan_id"], "plan_revision": 4,
            "plan_sha256": digest(plan), "output_profile": PROFILE,
            "style_system_version": "atme-style-v2", "asset_registry_version": "atme-assets-v2",
            "canvas": {"x": 0, "y": 0, "width": 1280, "height": 720}, "boards": plan["boards"],
            "objects": objects, "activations": [{"activation_id": "activation-1", "board_id": "board-main",
            "start_ms": 0, "end_ms": 10000, "reason": "Persistent board for the full explanation"}]}


def resolved_timeline_v2(plan=None, layout=None):
    plan = plan or visual_plan_v2(); layout = layout or executable_layout_v2(plan)
    resolved = []
    for index, action in enumerate(plan["actions"]):
        start = index * 2000
        resolved.append({"action": action, "start_ms": start, "end_ms": start + 900,
                         "resolved_trigger": {"source": action["trigger"],
                         "alignment_anchor_ms": start, "matched_text": "system begins",
                         "matched_occurrence": 1, "resolved_at_ms": start,
                         "confidence": 0.98, "exact": True}})
    return {"contract_version": "2.0.0", "timeline_id": "timeline-rich", "project_id": 1,
            "project_revision": layout["project_revision"] + 1, "plan_id": plan["plan_id"], "plan_revision": 4,
            "plan_sha256": digest(plan), "layout_id": layout["layout_id"], "layout_revision": 5,
            "layout_sha256": digest(layout), "cleaned_timeline_revision": 2,
            "cleaned_timeline_fingerprint": SHA_B, "output_profile": PROFILE,
            "style_system_version": "atme-style-v2", "asset_registry_version": "atme-assets-v2",
            "duration_ms": 10000, "compilation_fingerprint": SHA_A,
            "resolved_assets": [{"asset_id": "asset-evidence", "revision": 1,
                                 "managed_ref": "assets/evidence.png", "checksum_sha256": SHA_A,
                                 "provenance_verified": True}],
            "initial_object_states": [{"object_id": obj["object_id"], "state": "hidden",
                                       "state_version": 1, "visible": False} for obj in layout["objects"]],
            "beat_anchors": [{"beat_id": "beat-001", "start_ms": 0},
                             {"beat_id": "beat-002", "start_ms": 4000}],
            "actions": resolved, "coverage": plan["coverage"],
            "fallbacks": plan["fallbacks"],
            "validation": {"status": "pass", "production_ready": True, "issues": []}}
