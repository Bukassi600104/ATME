"""Deterministic placement and scheduling for stored semantic storyboards."""
import hashlib
from io import BytesIO
from math import ceil

from PIL import Image, ImageFont
from atme.project_service import ProjectError, _resolved_compilation_fingerprint, _visual_digest
from atme.render.style_bundle import load_bundle
from atme.render.v2_hierarchy import HierarchySnapshot
from atme.store.contracts_v2 import ExecutableLayoutV2, HierarchyBasis, VisualPlanV2, _evidence_treatment_for


COMPILER_VERSION = 7
OBJECTS = ("rectangle", "rounded_rectangle", "ellipse", "text", "evidence", "arrow", "network")
ACTIONS = ("draw", "write", "reveal", "enter", "exit", "highlight", "cross_out",
           "dim", "isolate", "insert_evidence", "return_board", "connect", "disconnect")


def capabilities():
    return {"object_types": list(OBJECTS), "actions": list(ACTIONS),
            "triggers": ["absolute", "word", "phrase", "beat_start", "prior_action"],
            "connector_anchors": ["left", "right", "top", "bottom", "center", "in", "out"],
            "connector_roles": ["semantic_connector"], "connector_routing": ["straight", "elbow", "curve"],
            "action_requirements": {"write": "text", "draw": "mark_or_arrow",
                "endpoint_edits": "disconnect_before_changing_a_connected_endpoint",
                "connect": "disconnected_named_relationship", "disconnect": "connected_named_relationship",
                "insert_evidence": "owned_png_with_source_and_read_hold", "return_board": "prior_visit_and_state_receipt",
                "highlight": "untouched_visible_mark_or_text", "cross_out": "untouched_visible_mark_or_text",
                "dim": "untouched_visible_context"},
            "restrictions": ["plain_leaf_objects", "exact_measured_speech", "verified_project_evidence",
                             "renderer_target_and_state_rules_apply"]}


def _reject(owner, message):
    raise ProjectError("storyboard_needs_repair", message, [{"id": owner, "message": message}])


def verify_compilation(plan, layout, clock, assets):
    """Record a decoded picture and measured execution facts for each saved beat."""
    from atme.render.v2_svg import prepare_png_sequence

    actions = {e["action"]["action_id"]: e for e in clock["actions"]}
    coverage = {entry["coverage_id"]: entry for entry in clock["coverage"]}
    holds = {item["action_id"]: item["intent"]["readable_hold_intent_ms"] for item in clock["evidence_treatments"]}
    duration = clock["duration_ms"]
    fps = clock["output_profile"]["fps"]
    checks = []
    samples = {0, *(min(e["end_ms"], duration - 1) for e in actions.values())}
    encoded_checks = {}
    beats = clock["beat_anchors"]
    for index, beat in enumerate(plan["beats"]):
        start = beats[index]["start_ms"]
        stop = beats[index + 1]["start_ms"] if index + 1 < len(beats) else duration
        events = [actions[key] for key in beat["action_ids"]]
        settled = max((e["end_ms"] for e in events), default=start)
        frame_number = min((stop * fps + 999) // 1000 - 1, (settled * fps + 999) // 1000)
        at = frame_number * 1000 // fps
        if at < start:
            _reject(beat["beat_id"], "This beat has no encoded picture before the next beat")
        instructions = []
        for key in beat["coverage_ids"]:
            entry = coverage[key]
            if entry["status"] != "executed" or not entry["action_ids"] or any(k not in actions for k in entry["action_ids"]):
                _reject(entry["instruction_id"], "This instruction needs an executable action before export")
            instructions.append(entry["instruction_id"])
        check = {"beat_id": beat["beat_id"], "board_id": beat["board_id"], "start_ms": start,
                 "end_ms": stop, "sample_ms": at, "frame_number": frame_number,
                 "preview_at_ms": (frame_number * 1000 + fps - 1) // fps, "action_ids": beat["action_ids"],
                 "covered_instructions": instructions}
        # Include action transitions so a primary can legitimately exit before the settled frame.
        encoded = {at, ((start * fps + 999) // 1000) * 1000 // fps}
        for event in events:
            for boundary in (event["start_ms"], event["end_ms"]):
                first = (boundary * fps + 999) // 1000
                for number in (first - 1, first, first + 1):
                    moment = number * 1000 // fps
                    if start <= moment < stop:
                        encoded.add(moment)
            key = event["action"]["action_id"]
            if key in holds:
                visit = next(v for v in layout["activations"] if v["start_ms"] <= event["start_ms"] < v["end_ms"])
                available = visit["end_ms"] - event["end_ms"]
                if available < holds[key]:
                    _reject(key, "Evidence leaves its board before the requested reading hold finishes")
                check["evidence_hold_ms"] = holds[key]
                check["available_board_hold_ms"] = available
        for moment in encoded:
            encoded_checks[moment] = check
        samples.add(at)
        checks.append(check)
    attention = {beat["beat_id"]: beat for beat in plan["beats"]}
    sampled_beats = {}
    for check in checks:
        sampled_beats.setdefault(check["sample_ms"], []).append(check)

    def inspect(frame):
        owner = encoded_checks.get(frame.at_ms)
        if owner:
            primary = attention[owner["beat_id"]]["attention"]["primary_targets"]
            visible = []
            for key in primary:
                obj = frame.object(key)
                if (obj.board_id == frame.active_board_id and obj.visible and
                        obj.opacity > 0 and obj.reveal_fraction > 0):
                    visible.append(key)
            owner.setdefault("primary_targets_seen", set()).update(visible)
            if frame.at_ms == owner["sample_ms"]:
                owner["visible_primary_targets"] = visible
        for check in sampled_beats.get(frame.at_ms, []):
            beat = attention[check["beat_id"]]
            if frame.active_board_id != beat["board_id"]:
                _reject(beat["beat_id"], "The requested board is absent at the sampled beat")
            for key in beat["attention"]["dimmed_targets"]:
                obj = frame.object(key)
                if not obj.visible or not 0 < obj.opacity < 1:
                    _reject(beat["beat_id"], f"Add a supported dim action for the requested context {key}")
            for key in beat["continuity"]["remove"]:
                if frame.object(key).visible:
                    _reject(beat["beat_id"], f"Object {key} remains visible after its requested removal")

    frames = {}
    compose = prepare_png_sequence(layout, clock, assets, on_sample=inspect,
                                   state_samples=sorted(encoded_checks.keys() - samples))
    for at in sorted(samples):
        png = compose(at).png
        with Image.open(BytesIO(png)) as image:
            extrema = image.convert("RGB").getextrema()
        frames[at] = (hashlib.sha256(png).hexdigest(), any(lo != hi for lo, hi in extrema))
    for check in checks:
        wanted = attention[check["beat_id"]]["attention"]["primary_targets"]
        seen = check["primary_targets_seen"]
        for key in wanted:
            if key not in seen:
                _reject(check["beat_id"], f"Requested primary target {key} has no visible frame on this board during its beat")
        check["primary_targets_seen"] = [key for key in wanted if key in seen]
        checksum, visible_ink = frames[check["sample_ms"]]
        check.update(frame_sha256=checksum, visible_picture_detail=visible_ink)
        if not visible_ink and check.get("evidence_hold_ms"):
            _reject(check["beat_id"], "The sampled evidence frame has no visible picture detail")
    return {"status": "verified", "compiler_version": COMPILER_VERSION, "plan_revision": clock["plan_revision"],
            "layout_revision": clock["layout_revision"], "profile": clock["output_profile"]["profile_id"],
            "sampled_frames": len(frames), "picture_source": "compiled_artwork_on_paper",
            "beats": checks, "editorial_review": "unrated"}


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
    from atme.render.v2_svg import evidence_footer_height

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
    evidence = {}
    actions = {action.action_id: action for action in plan.actions}
    for beat in plan.beats:
        if beat.evidence:
            for key in beat.action_ids:
                if actions[key].verb == "insert_evidence":
                    evidence.setdefault(actions[key].target_object_id, []).append(beat.evidence)
    placed = []
    for board in plan.boards:
        if not board.object_ids:
            continue
        if len(board.object_ids) > min(board.density_limit, aspect.density.max_context_objects):
            _reject(board.board_id, "Reduce visible objects or split this board into two visits")
        connectors = [key for key in board.object_ids if objects[key].object_type in {"arrow", "network"}]
        nodes = [key for key in board.object_ids if key not in connectors]
        count = len(nodes)
        if not count:
            _reject(board.board_id, "A relationship board requires placed endpoints")
        anchor_points = {"left": (0, .5), "right": (1, .5), "top": (.5, 0), "bottom": (.5, 1),
                         "center": (.5, .5), "in": (0, .5) if landscape else (.5, 0),
                         "out": (1, .5) if landscape else (.5, 1)}
        anchors = {key: {} for key in nodes}
        for edge in connectors:
            binding = objects[edge].connector_binding
            if not binding or binding.role != "semantic_connector":
                _reject(edge, "Supply a semantic connector with two named endpoints")
            for node, name in [(binding.source_object_id, binding.source_anchor_id),
                               (binding.destination_object_id, binding.destination_anchor_id)]:
                if node not in anchors or name not in anchor_points:
                    _reject(edge, f"Unsupported connector endpoint {node} at anchor {name}")
                ax, ay = anchor_points[name]
                anchors[node][name] = {"anchor_id": name, "point": {"x": ax, "y": ay}}
        columns = min(count, 2) if landscape else 1
        rows = ceil(count / columns)
        w, h = (usable_w - gap * (columns - 1)) // columns, (usable_h - gap * (rows - 1)) // rows
        for index, key in enumerate([*nodes, *connectors]):
            obj = objects[key]
            states = {"hidden", "visible", "connected", "disconnected"} if key in connectors else {"hidden", "visible"}
            if obj.object_type not in OBJECTS or obj.initial_state not in states:
                _reject(key, f"Automatic placement does not support {obj.object_type} in state {obj.initial_state}")
            if obj.object_type != "evidence" and obj.asset_id:
                _reject(key, "This asset needs a supported asset placement")
            cell = ({"x": x, "y": y, "width": usable_w, "height": usable_h} if key in connectors else
                    {"x": x + index % columns * (w + gap), "y": y + index // columns * (h + gap),
                     "width": w, "height": h})
            item = obj.model_dump(mode="json", exclude_none=True)
            item.update(z_index=index, visible=obj.initial_state in {"visible", "connected"}, opacity=1,
                        transform={"position": {"x": 0, "y": 0}}, anchors=list(anchors.get(key, {}).values()),
                        geometry={"bounds": cell, "points": [], "corner_radius":
                                  round(style.strokes.corner_radius_px * scale) if obj.object_type in
                                  {"rounded_rectangle", "evidence"} else None},
                        style={"stroke": "ink.primary", "fill": "surface.raised"})
            if key in connectors:
                item.update(item.pop("connector_binding"))
                item["style"] = {"stroke": "ink.accent"}
            elif obj.object_type == "text":
                text, inset, bounds = _fit_heading(obj, cell, font, role, scale)
                item["geometry"]["bounds"] = bounds
                item.update(text=text, text_inset_px=inset, items=[], style={"text": "text.heading"})
            elif obj.object_type == "evidence" and key in evidence:
                heights = [w * intent.crop.height / intent.crop.width + evidence_footer_height(
                    scale, intent.annotation is not None and intent.annotation_target_id == key) for intent in evidence[key]]
                fitted = min(h, ceil(max(heights)))
                item["geometry"]["bounds"] = {**cell, "height": fitted, "y": cell["y"] + (h - fitted) // 2}
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
            elif trigger.kind == "beat_start" and trigger.beat_id in starts:
                candidates.append(starts[trigger.beat_id] + trigger.offset_ms)
        if not candidates and beats:
            _reject(beat.beat_id, "Give this beat a measured, absolute, earlier beat or previous-action start")
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
    for beat, next_beat in zip(plan.beats, beats[1:]):
        for key in beat.action_ids:
            if ends[key] > next_beat["start_ms"]:
                _reject(key, f"Action extends beyond its owning beat {beat.beat_id}")
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
        if beat.continuity.replacements:
            _reject(beat.beat_id, "The requested replacements need explicit executable object transitions")
        board = next(board for board in plan.boards if board.board_id == beat.board_id)
        if (beat.camera_intent.framing in {"close", "detail", "medium"}
                and set(board.object_ids) != set(beat.camera_intent.target_ids)):
            _reject(beat.beat_id, "Use a dedicated board for this camera framing or supply an executable camera move")
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
    scheduled = {event["action"]["action_id"] for event in events}
    for entry in plan.coverage:
        if entry.status != "executed" or not set(entry.action_ids).issubset(scheduled):
            _reject(entry.instruction_id, "The declared instruction has incomplete scheduled coverage")
    for fallback in plan.fallbacks:
        if fallback.production_blocking and fallback.status in {"selected", "rejected"}:
            _reject(fallback.fallback_id, "Resolve the selected production-blocking fallback before compilation")
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
