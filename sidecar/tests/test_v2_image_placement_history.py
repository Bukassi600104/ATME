"""Placement permissions are project-write authority, not delayed paint errors."""

from copy import deepcopy
from dataclasses import replace

import pytest
from test_v2_image_placement_contract import image_documents
from test_v2_image_placement_project import stored_placement, verified_assets
from test_v2_registry_project import history
from test_v2_split_identity import sample_for_layout
from test_v2_timeline_replay import resolved
from v2_fixtures import digest

from atme.project_service import ProjectError, _resolved_compilation_fingerprint
from atme.render.v2_hierarchy import HierarchySnapshot, changed_hierarchy_objects
from atme.render.v2_hierarchy_replay import completed_hierarchy_basis
from atme.render.v2_state import evaluate_frame
from atme.render.v2_svg import compose_png_frame
from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    HierarchyBasis,
    validate_plan_layout,
)


def permission_case(plan, layout, fault, *, permitted=False):
    spec = next(obj for obj in plan["objects"] if obj.get("image_placement"))
    image = next(obj for obj in layout["objects"] if obj["object_id"] == spec["object_id"])
    grants = ["scale"] if fault == "cover" else ["scale", "crop"]
    if permitted:
        grants += ["crop"] if fault == "cover" else ["mask"] if fault == "clip" else ["rotate"]
    next(asset for asset in plan["assets"] if asset["asset_id"] == spec["asset_id"])[
        "allowed_transformations"] = grants[:]
    for obj in (spec, image):
        placement = obj["image_placement"]
        placement["allowed_transformations"] = grants[:]
        if fault == "cover":
            placement.update(crop={"x": 0, "y": 0, "width": 80, "height": 40}, fit="cover")
    if fault == "cover":
        image["geometry"]["bounds"].update(width=300, height=200)
    elif fault == "local-rotate":
        image["transform"]["rotation_degrees"] = 20
    else:
        owner = deepcopy(image)
        owner.pop("image_placement")
        owner.pop("variant", None)
        owner.update(object_id="image-permission-owner", object_type="clip" if fault == "clip" else "group",
                     asset_id=None, parent_id=None, child_ids=[image["object_id"]],
                     initial_state="visible", visible=True, z_index=10)
        owner["geometry"]["bounds"] = {"x": 0, "y": 0, "width": 720, "height": 720}
        owner["transform"].update(rotation_degrees=0 if fault == "clip" else 20,
                                  position={"x": 0, "y": 0}, origin={"x": 0, "y": 0})
        semantic = deepcopy(spec)
        semantic.pop("image_placement")
        semantic.update(object_id=owner["object_id"], object_type=owner["object_type"],
                        asset_id=None, initial_state="visible", child_ids=owner["child_ids"][:])
        plan["objects"].append(semantic)
        layout["objects"].append(owner)
        image["parent_id"] = owner["object_id"]
        for document in (plan, layout):
            document["boards"][0]["object_ids"].append(owner["object_id"])
        next(beat for beat in plan["beats"] if beat["beat_id"] == spec["beat_id"])[
            "object_ids"].append(owner["object_id"])
    layout["plan_sha256"] = digest(plan)


@pytest.mark.parametrize("fault", ["cover", "local-rotate", "ancestor-rotate", "clip"])
@pytest.mark.parametrize("permitted", [False, True])
def test_paired_layout_rejects_unpermitted_initial_placement(fault, permitted):
    plan, layout = image_documents()
    permission_case(plan, layout, fault, permitted=permitted)
    if permitted:
        validate_plan_layout(plan, layout)
    else:
        with pytest.raises(ValueError, match="image_placement"):
            validate_plan_layout(plan, layout)


@pytest.mark.parametrize("fault", ["cover", "local-rotate", "clip"])
def test_real_layout_permission_failure_is_atomic(tmp_path, fault):
    service, project, plan, layout, _clock = stored_placement(tmp_path, persist=False)
    try:
        pid = project["project_id"]
        permission_case(plan, layout, fault)
        plan["project_revision"] = project["revision"]
        project = service.write(pid, "storyboard", plan, project["revision"])
        layout.update(project_revision=project["revision"], plan_revision=project["artifacts"]["storyboard"],
                      plan_sha256=digest(plan))
        before = deepcopy((service.open(pid), history(service, pid), service.source_timeline.get(pid)))
        with pytest.raises(ProjectError) as failure:
            service.write(pid, "layout", layout, project["revision"])
        assert failure.value.code == "invalid_artifact"
        assert any("image_placement" in row["message"] for row in failure.value.errors)
        assert (service.open(pid), history(service, pid), service.source_timeline.get(pid)) == before
    finally:
        service.store.close()


def group_history(plan, layout, clock, *, permitted):
    image = next(obj for obj in layout["objects"] if obj["object_id"] == "object-image")
    image["geometry"]["bounds"] = {"x": 0, "y": 0, "width": 200, "height": 100}
    image["transform"].update(position={"x": 80, "y": 510}, origin={"x": 0, "y": 0})
    grants = ["scale", "crop", "rotate"] if permitted else ["scale", "crop"]
    spec = next(obj for obj in plan["objects"] if obj["object_id"] == image["object_id"])
    for obj in (image, spec):
        obj["image_placement"]["allowed_transformations"] = grants[:]
    for inventory in (plan["assets"], clock["resolved_assets"]):
        next(asset for asset in inventory if asset["asset_id"] == image["asset_id"])[
            "allowed_transformations"] = grants[:]
    shell = deepcopy(image)
    shell.pop("image_placement")
    shell.pop("variant", None)
    shell.update(object_id="image-history-shell", object_type="group", asset_id=None,
                 child_ids=[], initial_state="ungrouped", z_index=5, anchors=[])
    shell["geometry"]["bounds"] = {"x": 0, "y": 0, "width": 720, "height": 720}
    shell["transform"].update(position={"x": 0, "y": 0}, rotation_degrees=180,
                              origin={"x": 0, "y": 0})
    semantic = deepcopy(spec)
    semantic.pop("image_placement")
    semantic.update(object_id=shell["object_id"], object_type="group", asset_id=None, initial_state="ungrouped")
    plan["objects"].append(semantic)
    layout["objects"].append(shell)
    for document in (plan, layout):
        document["boards"][0]["object_ids"].append(shell["object_id"])
    beat = next(row for row in plan["beats"] if row["beat_id"] == spec["beat_id"])
    beat["object_ids"].append(shell["object_id"])
    clock["initial_object_states"].append({"object_id": shell["object_id"], "state": "ungrouped",
                                            "visible": True, "state_version": 1})
    layout["initial_empty_group_ownership"] = [{"shell_object_id": shell["object_id"],
        "owner_group_action_id": "group-image", "owner_source_basis_sha256": "0" * 64}]
    typed = ExecutableLayoutV2.model_validate(layout)
    objects = {obj.object_id: obj for obj in typed.objects}
    before = HierarchySnapshot.from_objects(objects)
    source = completed_hierarchy_basis(before, {row.object_id: row for row in sample_for_layout(typed).objects})
    after = HierarchySnapshot(tuple(replace(node, parent_id=shell["object_id"], sibling_ordinal=0)
        if node.object_id == image["object_id"] else replace(node, sibling_ordinal=node.sibling_ordinal-1)
        if node.object_id == shell["object_id"] else node for node in before.nodes))
    destination = deepcopy(source.model_dump(mode="json"))
    nodes = {node.object_id: node for node in after.nodes}
    for row in destination["placements"]:
        node = nodes[row["object_id"]]
        row.update(parent_id=node.parent_id, sibling_ordinal=node.sibling_ordinal)
        if row["object_id"] == image["object_id"]:
            row["local_transform"].update(position={"x": -80, "y": -510}, rotation_degrees=180)
    destination = HierarchyBasis.model_validate(destination)
    template = deepcopy(clock["actions"][0]["action"])
    template.pop("annotation", None)
    for verb, start, old, new, old_h, new_h in (
            ("group", 6000, source, destination, before, after),
            ("ungroup", 7000, destination, source, after, before)):
        action = deepcopy(template)
        action.update(action_id=verb+"-image", verb=verb, target_ids=[image["object_id"]],
            container_id=shell["object_id"], easing="step", expected_state="ungrouped" if verb == "group" else "grouped",
            post_state="grouped" if verb == "group" else "ungrouped", coverage_id="coverage-3",
            source_instruction_id=next(row["instruction_id"] for row in plan["coverage"]
                                       if row["coverage_id"] == "coverage-3"),
            fallback={"fallback_id": "fallback-3", "on_failure": "block"},
            hierarchy_policy={"member_root_ids": [image["object_id"]],
                "source_basis": old.model_dump(mode="json"), "source_basis_sha256": old.checksum(),
                "destination_basis": new.model_dump(mode="json"), "destination_basis_sha256": new.checksum(),
                "changed_object_ids": list(changed_hierarchy_objects(old_h, new_h, objects)),
                "preserve_world_transform": True})
        row = resolved(action, start, start+500).model_dump(mode="json")
        clock["actions"].append(row)
        plan["actions"].append(deepcopy(row["action"]))
        beat["action_ids"].append(action["action_id"])
        for document in (plan, clock):
            next(item for item in document["coverage"] if item["coverage_id"] == "coverage-3")[
                "action_ids"].append(action["action_id"])
    layout["initial_empty_group_ownership"][0]["owner_source_basis_sha256"] = source.checksum()
    clock.update(initial_hierarchy_basis=source.model_dump(mode="json"), initial_hierarchy_basis_sha256=source.checksum())


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("permitted", [False, True])
def test_real_group_ungroup_history_checks_current_image_permissions(tmp_path, portrait, permitted):
    service, project, plan, layout, clock = stored_placement(tmp_path, portrait, persist=False)
    try:
        pid = project["project_id"]
        group_history(plan, layout, clock, permitted=permitted)
        plan["project_revision"] = project["revision"]
        try:
            project = service.write(pid, "storyboard", plan, project["revision"])
        except ProjectError as exc:
            raise AssertionError(exc.errors) from exc
        layout.update(project_revision=project["revision"], plan_revision=project["artifacts"]["storyboard"],
                      plan_sha256=digest(plan))
        project = service.write(pid, "layout", layout, project["revision"])
        clock.update(project_revision=project["revision"], plan_revision=project["artifacts"]["storyboard"],
            plan_sha256=digest(plan), layout_revision=project["artifacts"]["layout"], layout_sha256=digest(layout))
        clock["compilation_fingerprint"] = _resolved_compilation_fingerprint(clock)
        before = deepcopy((service.open(pid), history(service, pid), service.source_timeline.get(pid)))
        if not permitted:
            with pytest.raises(ProjectError, match="rotate") as failure:
                service.write(pid, "resolved_timeline", clock, project["revision"])
            assert failure.value.code == "invalid_artifact"
            assert (service.open(pid), history(service, pid), service.source_timeline.get(pid)) == before
        else:
            service.write(pid, "resolved_timeline", clock, project["revision"])
            supplied = verified_assets(service, pid, layout, clock)
            expected = None
            for at in (7500, 6500, 5999, 6500, 7500):
                frame = evaluate_frame(layout, clock, at)
                assert frame.hierarchy.ancestors("object-image") == (("image-history-shell",) if at == 6500 else ())
                png = compose_png_frame(layout, clock, at, supplied).png
                if expected is None:
                    expected = png
                assert png == expected
    finally:
        service.store.close()
