"""Stored strict-valid hierarchy receipts cannot detach authored role roots."""

from copy import deepcopy
from dataclasses import replace

import pytest
from test_v2_illustration_assembly_project import stored_illustration_basis
from test_v2_registry_project import history
from test_v2_split_identity import sample_for_layout
from v2_fixtures import digest

from atme.project_service import ProjectError, _resolved_compilation_fingerprint
from atme.render.v2_hierarchy import HierarchySnapshot, changed_hierarchy_objects
from atme.render.v2_hierarchy_replay import completed_hierarchy_basis
from atme.render.v2_timeline_replay import replay_chronology
from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    GroupAction,
    HierarchyBasis,
    ResolvedVisualTimelineV2,
)


@pytest.mark.parametrize("portrait", [False, True])
def test_real_stored_ungroup_cannot_detach_bound_illustration_roles_atomically(tmp_path, portrait):
    service, project, plan, layout, timeline = stored_illustration_basis(tmp_path, portrait=portrait)
    try:
        pid = project["project_id"]
        group = next(obj for obj in layout["objects"] if obj["object_id"] == "illustration-group")
        group["initial_state"] = "grouped"
        next(obj for obj in plan["objects"] if obj["object_id"] == group["object_id"])["initial_state"] = "grouped"
        typed = ExecutableLayoutV2.model_validate(layout)
        objects = {obj.object_id: obj for obj in typed.objects}
        initial = sample_for_layout(typed)
        introductory = ResolvedVisualTimelineV2.model_validate(timeline).actions[:2]
        replay = replay_chronology(objects, initial.hierarchy, {obj.object_id: obj for obj in initial.objects},
            dict(initial.state_versions), tuple(introductory), (("board-main", 0, 8000),), 8000)
        captured = replay.at(4000)  # actual completed introduction, not fabricated initial-state receipt
        frames = {obj.object_id: obj for obj in captured.objects}
        roots = list(captured.hierarchy.children("board-main", None))
        members = list(captured.hierarchy.children("board-main", group["object_id"]))
        index = roots.index(group["object_id"]) + 1
        roots[index:index] = members
        after = HierarchySnapshot(tuple(replace(node, parent_id=None, sibling_ordinal=roots.index(node.object_id))
            if node.object_id in roots else node for node in captured.hierarchy.nodes))
        source = completed_hierarchy_basis(captured.hierarchy, frames)
        destination = source.model_dump(mode="json")
        nodes = {node.object_id: node for node in after.nodes}
        for item in destination["placements"]:
            node = nodes[item["object_id"]]
            item.update(parent_id=node.parent_id, sibling_ordinal=node.sibling_ordinal)
        destination = HierarchyBasis.model_validate(destination)
        raw = timeline["actions"][-1]["action"]
        for field in ("opacity", "destination", "target_ids"):
            raw.pop(field)
        raw.update(verb="ungroup", container_id=group["object_id"], target_ids=members, easing="step",
            expected_state="grouped", post_state="ungrouped", hierarchy_policy={
                "member_root_ids": members, "source_basis": source.model_dump(mode="json"),
                "destination_basis": destination.model_dump(mode="json"), "source_basis_sha256": source.checksum(),
                "destination_basis_sha256": destination.checksum(),
                "changed_object_ids": list(changed_hierarchy_objects(captured.hierarchy, after, objects)),
                "preserve_world_transform": True})
        GroupAction.model_validate(raw)
        plan["actions"][-1] = deepcopy(raw)
        plan["project_revision"] = project["revision"]
        project = service.write(pid, "storyboard", plan, project["revision"])
        layout.update(project_revision=project["revision"], plan_revision=project["artifacts"]["storyboard"], plan_sha256=digest(plan))
        project = service.write(pid, "layout", layout, project["revision"])
        next(row for row in timeline["initial_object_states"] if row["object_id"] == group["object_id"])["state"] = "grouped"
        initial_basis = completed_hierarchy_basis(initial.hierarchy, {obj.object_id: obj for obj in initial.objects})
        timeline.update(project_revision=project["revision"], plan_revision=project["artifacts"]["storyboard"],
            plan_sha256=digest(plan), layout_revision=project["artifacts"]["layout"], layout_sha256=digest(layout),
            initial_hierarchy_basis=initial_basis.model_dump(mode="json"), initial_hierarchy_basis_sha256=initial_basis.checksum())
        timeline["compilation_fingerprint"] = _resolved_compilation_fingerprint(timeline)
        ResolvedVisualTimelineV2.model_validate(timeline)  # real strict history reaches the production write boundary
        before = deepcopy((service.open(pid), history(service, pid), service.source_timeline.get(pid)))
        with pytest.raises(ProjectError) as failure:
            service.write(pid, "resolved_timeline", timeline, project["revision"])
        assert failure.value.code == "invalid_artifact"
        assert "illustration_assembly" in str(failure.value)
        assert (service.open(pid), history(service, pid), service.source_timeline.get(pid)) == before
    finally:
        service.store.close()
