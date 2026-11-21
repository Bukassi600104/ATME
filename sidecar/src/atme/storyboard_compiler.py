"""Deterministic placement and scheduling for stored semantic storyboards."""
from math import ceil

from PIL import ImageFont
from atme.project_service import ProjectError, _resolved_compilation_fingerprint, _visual_digest
from atme.render.style_bundle import load_bundle
from atme.render.v2_hierarchy import HierarchySnapshot
from atme.store.contracts_v2 import ExecutableLayoutV2, HierarchyBasis, VisualPlanV2, _evidence_treatment_for


COMPILER_VERSION = 3
OBJECTS = ("rectangle", "rounded_rectangle", "ellipse", "text", "evidence")
ACTIONS = ("draw", "write", "reveal", "enter", "exit", "highlight", "cross_out",
           "dim", "isolate", "insert_evidence", "return_board")


def capabilities():
    return {"object_types": list(OBJECTS), "actions": list(ACTIONS),
            "triggers": ["absolute", "word", "phrase", "beat_start", "prior_action"],
            "restrictions": ["plain_leaf_objects", "exact_measured_speech", "verified_project_evidence",
                             "renderer_target_and_state_rules_apply"]}


def _reject(owner, message):
    raise ProjectError("storyboard_needs_repair", message, [{"id": owner, "message": message}])


def _fit_heading(obj, cell, font, role, scale):
    lines = []
    inset = ceil(role.size_px * scale * .7)
    def fits(text):
        return len(text) <= role.max_characters_per_line and font.getlength(text) <= cell["width"] - 2 * inset
    for paragraph in obj.description.splitlines():
        line = ""
        for word in paragraph.split():
            if not fits(word):
                _reject(obj.object_id, "A label word exceeds the available width")
            joined = f"{line} {word}".strip()
            if line and not fits(joined):
                lines.append(line)
                line = word
            else:
                line = joined
        lines.append(line)
    if not any(lines):
        _reject(obj.object_id, "A visible label needs text")
    w = max(1, ceil(max(font.getlength(line) for line in lines))) + 2 * inset
    h = ceil(len(lines) * role.size_px * scale * role.line_height) + 2 * inset
    if h > cell["height"]:
        _reject(obj.object_id, "Wrapped label exceeds the safe area")
    return "\n".join(lines), inset, {"x": cell["x"] + (cell["width"] - w) // 2,
                              "y": cell["y"] + (cell["height"] - h) // 2, "width": w, "height": h}


def _placements(plan, style, root):
    width, height = plan.output_profile.width, plan.output_profile.height
    landscape = width > height
    aspect = style.aspects["landscape-16:9" if landscape else "portrait-9:16"]
    scale = width / aspect.width
    safe = aspect.safe_area
    gap = ceil(aspect.density.min_object_gap_px * scale)
    role = style.typography.title
    heading = next(font for font in style.fonts if font.id == role.font_id)
    font = ImageFont.truetype(str(root / heading.file), ceil(role.size_px * scale))
    x, y = ceil(safe.left_px * scale), ceil(safe.top_px * scale)
    usable_w = width - x - ceil(safe.right_px * scale)
    usable_h = height - y - ceil(safe.bottom_px * scale)
    objects = {obj.object_id: obj for obj in plan.objects}
    placed = []
    for board in plan.boards:
        count = len(board.object_ids)
        if not count:
            continue
        if count > min(board.density_limit, aspect.density.max_context_objects):
            _reject(board.board_id, "Reduce visible objects or split this board into two visits")
        columns = min(count, 2) if landscape else 1
        rows = ceil(count / columns)
        w, h = (usable_w - gap * (columns - 1)) // columns, (usable_h - gap * (rows - 1)) // rows
        for index, key in enumerate(board.object_ids):
            obj = objects[key]
            if obj.object_type not in OBJECTS or obj.initial_state not in {"hidden", "visible"}:
                _reject(key, f"Automatic placement does not support {obj.object_type} in state {obj.initial_state}")
            if obj.object_type != "evidence" and obj.asset_id:
                _reject(key, "This asset needs a supported asset placement")
            cell = {"x": x + index % columns * (w + gap), "y": y + index // columns * (h + gap),
                    "width": w, "height": h}
            item = obj.model_dump(mode="json", exclude_none=True)
            item.update(z_index=index, visible=obj.initial_state == "visible", opacity=1,
                        transform={"position": {"x": 0, "y": 0}}, anchors=[],
                        geometry={"bounds": cell, "points": [], "corner_radius":
                                  round(style.strokes.corner_radius_px * scale) if obj.object_type in
                                  {"rounded_rectangle", "evidence"} else None},
                        style={"stroke": "ink.primary", "fill": "surface.raised"})
            if obj.object_type == "text":
                text, inset, bounds = _fit_heading(obj, cell, font, role, scale)
                item["geometry"]["bounds"] = bounds
                item.update(text=text, text_inset_px=inset, items=[], style={"text": "text.heading"})
            placed.append(item)
    return placed


def _schedule(plan, speech, duration, motion):
    actions = {action.action_id: action for action in plan.actions}
    events, beats, visits = [], [], []
    ends, starts, seen_visits = {}, {}, {}
    for beat in plan.beats:
        speech_starts = [speech[key]["resolved_at_ms"] for key in beat.action_ids if key in speech]
        absolute = [actions[key].trigger.at_ms for key in beat.action_ids if actions[key].trigger.kind == "absolute"]
        candidates = speech_starts + absolute
        for key in beat.action_ids:
            trigger = actions[key].trigger
            if trigger.kind == "prior_action" and trigger.action_id in ends:
                candidates.append(ends[trigger.action_id] + trigger.offset_ms)
        if not candidates and beats:
            _reject(beat.beat_id, "Give this beat a measured, absolute or previous-action start")
        start = min(candidates) if beats else 0
        if not 0 <= start < duration or beats and start < beats[-1]["start_ms"]:
            _reject(beat.beat_id, "Beat starts must follow narration order and fit the recording")
        starts[beat.beat_id] = start
        beats.append({"beat_id": beat.beat_id, "start_ms": start})
        new_visit = not visits or visits[-1]["board_id"] != beat.board_id
        returns = [actions[key] for key in beat.action_ids if actions[key].verb == "return_board"]
        if returns and (len(returns) != 1 or not new_visit or beat.board_id not in seen_visits):
            _reject(beat.beat_id, "A board return must open a new visit to a previously shown board")
        if new_visit:
            if visits:
                if start <= visits[-1]["start_ms"]:
                    _reject(beat.beat_id, "Two different boards cannot begin at the same time")
                visits[-1]["end_ms"] = start
            visit = {"board_id": beat.board_id, "activation_id": None, "start_ms": start,
                     "end_ms": duration, "reason": beat.narration_summary}
            if beat.board_id in seen_visits and not returns:
                _reject(beat.beat_id, "Declare the state to preserve with a return_board instruction")
            if returns:
                action = returns[0]
                for owner, expected in ((visits[-1], action.source_activation_id),
                                        (seen_visits[beat.board_id], action.prior_destination_activation_id),
                                        (visit, action.destination_activation_id)):
                    if owner["activation_id"] not in (None, expected):
                        _reject(action.action_id, "Inconsistent board visit identity")
                    owner["activation_id"] = expected
            visits.append(visit)
            seen_visits[beat.board_id] = visit
        for key in beat.action_ids:
            action = actions[key]
            if action.verb not in ACTIONS:
                _reject(key, f"Automatic scheduling does not support {action.verb}")
            trigger = action.trigger
            if key in speech:
                resolved = speech[key]
            else:
                if trigger.kind == "absolute":
                    anchor = trigger.at_ms
                elif trigger.kind == "beat_start" and trigger.beat_id in starts:
                    anchor = starts[trigger.beat_id]
                elif trigger.kind == "prior_action" and trigger.action_id in ends:
                    anchor = ends[trigger.action_id]
                else:
                    _reject(key, "Trigger requires an available timing measurement or an earlier action")
                resolved = {"source": trigger.model_dump(), "alignment_anchor_ms": anchor,
                            "resolved_at_ms": anchor + getattr(trigger, "offset_ms", 0),
                            "exact": True, "confidence": 1}
            at = resolved["resolved_at_ms"]
            length = motion.emphasis_ms if action.verb in {"highlight", "cross_out"} else motion.transition_ms
            end = at + (1 if action.verb == "return_board" else length)
            if not start <= at < end <= duration:
                _reject(key, "Action extends outside its beat or the edited recording")
            ends[key] = end
            events.append({"action": action.model_dump(mode="json", exclude_unset=True), "start_ms": at,
                           "end_ms": end, "resolved_trigger": resolved})
    used = {v["activation_id"] for v in visits if v["activation_id"] is not None}
    for index, visit in enumerate(visits):
        if visit["activation_id"] is None:
            name = f"visit-{index + 1}"
            while name in used:
                name += "-auto"
            visit["activation_id"] = name
            used.add(name)
    return sorted(events, key=lambda event: event["start_ms"]), beats, visits


def compile_documents(plan_document, basis, source, speech, owned):
    plan = VisualPlanV2.model_validate(plan_document)
    style, _, root = load_bundle()
    duration = source["document"]["duration_ms"]
    if duration <= 0:
        _reject(plan.plan_id, "Place the authoritative recording on the edited timeline")
    events, beats, visits = _schedule(plan, speech, duration, style.motion)
    objects = _placements(plan, style, root)
    declared = {obj.object_id: obj for obj in plan.objects}
    assets = {asset.asset_id: asset for asset in plan.assets}
    actions = {action.action_id: action for action in plan.actions}
    treatments, pins = [], {}
    for beat in plan.beats:
        if beat.camera_intent.mode not in {"cut", "hold"} or beat.sound_intent.role not in {"none", "purposeful_silence"}:
            _reject(beat.beat_id, "This camera move or soundtrack requires an executable treatment")
        if beat.evidence:
            action = next(actions[key] for key in beat.action_ids if actions[key].verb == "insert_evidence")
            asset = assets[beat.evidence.evidence_asset_id]
            metadata = owned.get(asset.asset_id)
            if not metadata or metadata["sha256"] != asset.checksum_sha256 or metadata["revision"] != asset.revision:
                _reject(action.action_id, "Evidence asset differs from its saved source")
            treatment = _evidence_treatment_for(beat, asset, declared[action.target_object_id], action)
            treatments.append(treatment.model_dump(mode="json"))
            pins[asset.asset_id] = {"asset_id": asset.asset_id, "revision": asset.revision,
                                    "managed_ref": asset.managed_ref, "checksum_sha256": asset.checksum_sha256,
                                    "kind": "evidence", "provenance_verified": True, "media_type": "image/png",
                                    "byte_length": metadata["bytes"], "width": asset.width, "height": asset.height,
                                    "orientation": "upright", "allowed_transformations": asset.allowed_transformations}
    layout = {**basis, "contract_version": "2.0.0", "layout_id": f"layout-{plan.plan_id}",
              "canvas": {"x": 0, "y": 0, "width": plan.output_profile.width, "height": plan.output_profile.height},
              "boards": plan_document["boards"], "objects": objects, "activations": visits,
              "evidence_treatments": treatments}
    placed = ExecutableLayoutV2.model_validate(layout)
    hierarchy = HierarchySnapshot.from_objects({obj.object_id: obj for obj in placed.objects})
    transforms = {obj.object_id: obj.transform for obj in placed.objects}
    holds = {t["action_id"]: t["intent"]["readable_hold_intent_ms"] for t in treatments}
    for event in events:
        action = event["action"]
        key = action["action_id"]
        if not any(v["board_id"] == action["board_id"] and v["start_ms"] <= event["start_ms"]
                   and event["end_ms"] + holds.get(key, 0) <= v["end_ms"] for v in visits):
            _reject(key, "This action and its reading hold must fit in one visit to its board")
        if action["verb"] == "return_board":
            # All supported actions preserve object transforms and hierarchy.
            retained = HierarchyBasis(placements=[
                {"object_id": node.object_id, "board_id": node.board_id, "parent_id": node.parent_id,
                 "sibling_ordinal": node.sibling_ordinal, "local_transform": transforms[node.object_id]}
                for node in hierarchy.nodes if node.board_id == action["board_id"]])
            event["return_hierarchy_receipt"] = {"action_id": key, "destination_board_id": action["board_id"],
                                                  "destination_activation_id": action["destination_activation_id"],
                                                  "hierarchy_basis": retained.model_dump(mode="json"),
                                                  "hierarchy_basis_sha256": retained.checksum()}
    clock = {**basis, "project_revision": basis["project_revision"] + 1, "contract_version": "2.0.0",
             "timeline_id": f"timeline-{plan.plan_id}", "layout_id": layout["layout_id"],
             "layout_revision": basis["project_revision"] + 1, "layout_sha256": _visual_digest(layout),
             "cleaned_timeline_revision": source["timeline_revision"],
             "cleaned_timeline_fingerprint": _visual_digest(source["document"]),
             "duration_ms": duration, "resolved_assets": list(pins.values()), "evidence_treatments": treatments,
             "initial_object_states": [{"object_id": obj["object_id"], "state": obj["initial_state"],
                                        "state_version": 1, "visible": obj["visible"]} for obj in objects],
             "beat_anchors": beats, "actions": events, "coverage": plan_document["coverage"],
             "fallbacks": plan_document["fallbacks"], "validation": {"status": "pass", "production_ready": True, "issues": []}}
    clock["compilation_fingerprint"] = _resolved_compilation_fingerprint(clock)
    return layout, clock
