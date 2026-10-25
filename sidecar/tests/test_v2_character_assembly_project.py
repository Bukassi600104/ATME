"""Real immutable projects bind authored character content to current authority."""

from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from socket import socket

import pytest
from test_v2_character_assembly_compositor import original_pose_documents
from test_v2_registry_project import history
from test_v2_resolved_project import stored_v2_basis
from test_v2_split_identity import sample_for_layout
from v2_fixtures import digest

from atme.project_service import ProjectError, _resolved_compilation_fingerprint
from atme.render import v2_state
from atme.render.style_bundle import registry_endpoint_inputs_for_objects
from atme.render.v2_hierarchy import HierarchySnapshot, changed_hierarchy_objects
from atme.render.v2_hierarchy_replay import completed_hierarchy_basis
from atme.render.v2_split_paint import verify_split_paint_inputs
from atme.render.v2_svg import (
    _compose_validated_svg_frame,
    _rasterize_svg_frame,
    compose_png_frame,
)
from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    HierarchyBasis,
    ResolvedVisualTimelineV2,
)


def stored_character_basis(tmp_path, pose="neutral", *, portrait=False, invalid_role_history=False):
    profile = "SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9"
    service, project, plan, old_layout, old_timeline = stored_v2_basis(tmp_path, profile=profile)
    pid = project["project_id"]
    layout, timeline = original_pose_documents(pose, portrait=portrait)
    # Retain the fixture's real introductory instructions and semantic speech
    # coverage, then place the character action in its actual conclusion beat.
    objects = {obj["object_id"]: obj for obj in layout["objects"]}
    for old in old_layout["objects"][:2]:
        objects[old["object_id"]].update(initial_state=old["initial_state"], visible=old["visible"])
    objects["object-group"].update(initial_state="visible", visible=True)
    row = timeline["actions"][0]
    row.update(start_ms=4000, end_ms=5000)
    row["action"]["trigger"] = {"kind": "absolute", "at_ms": 4000}
    row["resolved_trigger"].update(source=row["action"]["trigger"], alignment_anchor_ms=4000, resolved_at_ms=4000)
    if invalid_role_history:
        objects["actor-group"]["initial_state"] = "grouped"
        initial = sample_for_layout(ExecutableLayoutV2.model_validate(layout))
        current = {obj.object_id: obj for obj in ExecutableLayoutV2.model_validate(layout).objects}
        before = initial.hierarchy
        frames = {obj.object_id: obj for obj in initial.objects}
        roots = list(before.children("board-main", None))
        members = list(before.children("board-main", "actor-group"))
        index = roots.index("actor-group") + 1
        roots[index:index] = members
        after = HierarchySnapshot(tuple(replace(node, parent_id=None, sibling_ordinal=roots.index(node.object_id))
            if node.object_id in roots else node for node in before.nodes))
        source = completed_hierarchy_basis(before, frames)
        timeline.update(initial_hierarchy_basis=source.model_dump(mode="json"),
                        initial_hierarchy_basis_sha256=source.checksum())
        destination = source.model_dump(mode="json")
        nodes = {node.object_id: node for node in after.nodes}
        for item in destination["placements"]:
            node = nodes[item["object_id"]]
            item.update(parent_id=node.parent_id, sibling_ordinal=node.sibling_ordinal)
        destination = HierarchyBasis.model_validate(destination)
        action = row["action"]
        for field in ("opacity", "destination"):
            action.pop(field)
        action.update(verb="ungroup", target_ids=members, container_id="actor-group", easing="step",
            expected_state="grouped", post_state="ungrouped", hierarchy_policy={
                "member_root_ids": members, "source_basis": source.model_dump(mode="json"),
                "destination_basis": destination.model_dump(mode="json"), "source_basis_sha256": source.checksum(),
                "destination_basis_sha256": destination.checksum(),
                "changed_object_ids": list(changed_hierarchy_objects(before, after, current)),
                "preserve_world_transform": True})
    timeline["actions"] = [*deepcopy(old_timeline["actions"][:2]), row]
    timeline["coverage"] = deepcopy(old_timeline["coverage"])
    timeline["fallbacks"] = deepcopy(old_timeline["fallbacks"])
    timeline["initial_object_states"] = [{"object_id": obj["object_id"], "state": obj["initial_state"],
        "state_version": 1, "visible": obj["visible"]} for obj in layout["objects"]]
    fields = set(plan["objects"][0]) | {"child_ids", "character_assembly"}
    plan["objects"] = [{key: deepcopy(value) for key, value in obj.items() if key in fields} for obj in layout["objects"]]
    plan["assets"] = []
    plan["boards"] = deepcopy(layout["boards"])
    plan["actions"] = [deepcopy(row["action"]) for row in timeline["actions"]]
    plan["coverage"] = deepcopy(timeline["coverage"])
    plan["fallbacks"] = deepcopy(timeline["fallbacks"])
    for beat in plan["beats"]:
        beat["object_ids"] = [obj["object_id"] for obj in plan["objects"] if obj["beat_id"] == beat["beat_id"]]
        beat["action_ids"] = [row["action_id"] for row in plan["actions"] if row["coverage_id"] in beat["coverage_ids"]]
        beat["evidence"] = None
    plan["project_revision"] = project["revision"]
    project = service.write(pid, "storyboard", plan, project["revision"])
    layout.update(project_id=pid, project_revision=project["revision"],
        plan_revision=project["artifacts"]["storyboard"], plan_sha256=digest(plan))
    project = service.write(pid, "layout", layout, project["revision"])
    source = service.source_timeline.get(pid)
    timeline.update(project_id=pid, project_revision=project["revision"],
        plan_revision=project["artifacts"]["storyboard"], plan_sha256=digest(plan),
        layout_revision=project["artifacts"]["layout"], layout_sha256=digest(layout),
        cleaned_timeline_revision=source["timeline_revision"], cleaned_timeline_fingerprint=digest(source["document"]))
    timeline["compilation_fingerprint"] = _resolved_compilation_fingerprint(timeline)
    return service, project, plan, layout, timeline


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("pose", ["neutral", "point_right", "open_hands"])
def test_real_stored_and_duplicate_character_preserve_content_authority_and_offline_pixels(tmp_path, portrait, pose, monkeypatch):
    service, project, plan, layout, timeline = stored_character_basis(tmp_path, pose, portrait=portrait)
    try:
        pid = project["project_id"]
        project = service.write(pid, "resolved_timeline", timeline, project["revision"])
        original = deepcopy((history(service, pid), service.source_timeline.get(pid)))
        media = {str(path): sha256(path.read_bytes()).hexdigest() for path in tmp_path.rglob("*.wav")}
        duplicate = service.duplicate(pid)
        copy_id = duplicate["project_id"]
        docs = {}
        for kind, authored in (("storyboard", plan), ("layout", layout), ("resolved_timeline", timeline)):
            assert service.artifact(pid, kind)["document"] == authored
            record = service.artifact(copy_id, kind)
            docs[kind] = record["document"]
            assert record["duplicate_derivation"]["source_sha256"] == digest(authored)
            assert record["duplicate_derivation"]["copied_sha256"] == digest(docs[kind])
            assert docs[kind]["project_id"] == copy_id != pid
            assert docs[kind]["project_revision"] == authored["project_revision"]
        assert docs["storyboard"]["objects"] == plan["objects"]
        assert docs["layout"]["objects"] == layout["objects"]
        assert docs["storyboard"]["narrative_authority"] == plan["narrative_authority"]
        assert docs["layout"]["plan_sha256"] == docs["resolved_timeline"]["plan_sha256"] == digest(docs["storyboard"])
        assert docs["resolved_timeline"]["layout_sha256"] == digest(docs["layout"])
        assert docs["resolved_timeline"]["compilation_fingerprint"] == _resolved_compilation_fingerprint(docs["resolved_timeline"])
        assert service.source_timeline.get(copy_id)["document"] == original[1]["document"]
        expected = {at: compose_png_frame(layout, timeline, at).png for at in (4000, 4500, 5000)}
        typed = ExecutableLayoutV2.model_validate(docs["layout"])
        resolved = ResolvedVisualTimelineV2.model_validate(docs["resolved_timeline"])
        inputs = verify_split_paint_inputs(typed, {})
        registry = registry_endpoint_inputs_for_objects({obj.object_id: obj for obj in typed.objects},
            frozen_files={name: raw for name, _, raw in inputs.bundle_bytes})
        def forbidden(*args, **kwargs):
            raise AssertionError("stored character frozen preview attempted live IO")
        with monkeypatch.context() as offline:
            offline.setattr(Path, "read_bytes", forbidden)
            offline.setattr(socket, "connect", forbidden)
            for at in (5000, 4000, 4500, 5000, 4500):
                frame = v2_state._evaluate_frame_with_registry_inputs(docs["layout"], docs["resolved_timeline"], at, registry)
                svg = _compose_validated_svg_frame(typed, resolved, frame, {}, split_inputs=inputs)
                assert _rasterize_svg_frame(typed, svg, split_inputs=inputs).png == expected[at]
        assert (history(service, pid), service.source_timeline.get(pid)) == original
        assert media == {str(path): sha256(path.read_bytes()).hexdigest() for path in tmp_path.rglob("*.wav")}
    finally:
        service.store.close()


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("fault", ["semantic_role", "missing_anchor", "plan_binding", "role_order"])
def test_character_graph_or_semantic_write_failure_is_atomic(tmp_path, portrait, fault):
    service, project, plan, layout, _ = stored_character_basis(tmp_path, portrait=portrait)
    try:
        pid = project["project_id"]
        before = deepcopy((service.open(pid), history(service, pid), service.source_timeline.get(pid)))
        kind = "storyboard" if fault == "semantic_role" else "layout"
        candidate = deepcopy(plan if kind == "storyboard" else layout)
        candidate["project_revision"] = project["revision"]
        objects = {obj["object_id"]: obj for obj in candidate["objects"]}
        actor = objects["actor-group"]
        if fault == "semantic_role":
            actor["character_assembly"]["semantic_anchors"][1]["object_id"] = "actor-torso"
        elif fault == "missing_anchor":
            objects["actor-head"]["anchors"] = []
        elif fault == "plan_binding":
            actor["character_assembly"]["pose_id"] = "open_hands"
            ExecutableLayoutV2.model_validate(candidate)  # valid alone, false semantic pairing
        else:
            actor["child_ids"].reverse()
        with pytest.raises(ProjectError) as failure:
            service.write(pid, kind, candidate, project["revision"])
        assert failure.value.code == "invalid_artifact"
        assert "character_assembly" in str(failure.value.errors)
        assert (service.open(pid), history(service, pid), service.source_timeline.get(pid)) == before
    finally:
        service.store.close()


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("fault", ["plan_hash", "layout_hash", "cleaned_hash", "cleaned_revision", "timing_changed", "script_changed"])
def test_rehashed_character_timeline_cannot_claim_stale_authority(tmp_path, portrait, fault):
    service, project, _, _, timeline = stored_character_basis(tmp_path, portrait=portrait)
    try:
        pid = project["project_id"]
        media = {str(path): sha256(path.read_bytes()).hexdigest() for path in tmp_path.rglob("*.wav")}
        if fault == "timing_changed":
            source = service.source_timeline.get(pid)
            edited = service.source_timeline.command(pid, "split",
                {"clip_id": source["document"]["clips"][0]["clip_id"], "at_ms": 5000},
                project["revision"], source["timeline_revision"])
            project = edited["project"]
        elif fault == "script_changed":
            script = service.artifact(pid, "script")["document"]
            project = service.write(pid, "script", script, project["revision"])
        candidate = deepcopy(timeline)
        candidate["project_revision"] = project["revision"]
        if fault in {"plan_hash", "layout_hash", "cleaned_hash"}:
            field = {"plan_hash": "plan_sha256", "layout_hash": "layout_sha256",
                "cleaned_hash": "cleaned_timeline_fingerprint"}[fault]
            candidate[field] = "0" * 64
        elif fault == "cleaned_revision":
            candidate["cleaned_timeline_revision"] += 1
        candidate["compilation_fingerprint"] = _resolved_compilation_fingerprint(candidate)
        ResolvedVisualTimelineV2.model_validate(candidate)
        before = deepcopy((service.open(pid), history(service, pid), service.source_timeline.get(pid)))
        with pytest.raises(ProjectError) as failure:
            service.write(pid, "resolved_timeline", candidate, project["revision"])
        assert failure.value.code == "stale_contract_basis"
        assert (service.open(pid), history(service, pid), service.source_timeline.get(pid)) == before
        assert media == {str(path): sha256(path.read_bytes()).hexdigest() for path in tmp_path.rglob("*.wav")}
    finally:
        service.store.close()


@pytest.mark.parametrize("portrait", [False, True])
def test_stored_real_structural_history_cannot_detach_bound_roles_atomically(tmp_path, portrait):
    service, project, _, _, timeline = stored_character_basis(tmp_path, portrait=portrait, invalid_role_history=True)
    try:
        pid = project["project_id"]
        ResolvedVisualTimelineV2.model_validate(timeline)  # reaches the real history gate
        before = deepcopy((service.open(pid), history(service, pid), service.source_timeline.get(pid)))
        with pytest.raises(ProjectError) as failure:
            service.write(pid, "resolved_timeline", timeline, project["revision"])
        assert failure.value.code == "invalid_artifact"
        assert "character_assembly" in str(failure.value)
        assert (service.open(pid), history(service, pid), service.source_timeline.get(pid)) == before
    finally:
        service.store.close()
