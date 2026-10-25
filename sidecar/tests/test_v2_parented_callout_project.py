"""Normal immutable project writes, not a private-only parented leader demo."""
from copy import deepcopy

import pytest
from atme.project_service import ProjectError, _visual_digest
from atme.store import contracts_v2 as contracts
from test_v2_callout_contract import callout_documents
from test_v2_group_hierarchy import grouped_documents
from test_v2_split_project import artifact_rows
from test_visual_contracts_v2 import _store_v2_plan


def authored_parented_documents(portrait):
    plan, layout, _clock = callout_documents()
    shell = deepcopy(grouped_documents()[0]["objects"][3])
    shell.update(object_id="authored-callout-group", child_ids=[obj["object_id"] for obj in layout["objects"]])
    shell["transform"].update(position={"x": 30., "y": 20.}, scale_x=1.1, scale_y=.9,
                              rotation_degrees=7., origin={"x": 0., "y": 0.})
    for obj in layout["objects"]:
        obj["parent_id"] = shell["object_id"]
    layout["objects"].append(shell)
    plan["objects"].append({key: deepcopy(value) for key, value in shell.items()
                            if key in contracts.SemanticStandardObjectSpec.model_fields and (key != "clip_id" or value is not None)})
    for inventory in (layout["boards"][0]["object_ids"], plan["boards"][0]["object_ids"], plan["beats"][0]["object_ids"]):
        inventory.append(shell["object_id"])
    for document in (plan, layout):
        document["boards"][0]["density_limit"] = len(document["boards"][0]["object_ids"])
    if portrait:
        profile = {"profile_id": "SHORT_FORM_9_16", "width": 720, "height": 1280, "fps": 30}
        plan["output_profile"] = deepcopy(profile)
        layout["output_profile"] = deepcopy(profile)
        layout["canvas"].update(width=720, height=1280)
    layout["plan_sha256"] = _visual_digest(plan)
    contracts.validate_plan_layout(plan, layout)
    return plan, layout, shell["object_id"]


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("fault", [None, "binding", "membership"])
def test_real_parented_callout_writes_duplicate_or_reject_atomically(tmp_path, portrait, fault):
    service, project, existing = _store_v2_plan(tmp_path, profile="SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9")
    try:
        plan, layout, group_id = authored_parented_documents(portrait)
        pid = project["project_id"]
        plan.update(project_id=pid, project_revision=project["revision"],
                    narrative_authority=deepcopy(existing["narrative_authority"]))
        project = service.write(pid, "storyboard", plan, project["revision"])
        layout.update(project_id=pid, project_revision=project["revision"],
                      plan_revision=project["artifacts"]["storyboard"], plan_sha256=_visual_digest(plan))
        pointer = next(obj for obj in layout["objects"] if obj["object_id"] == "annotation-leader")
        if fault is not None:
            if fault == "binding":
                pointer["source_object_id"] = "object-label"
            else:
                pointer["parent_id"] = None
                next(obj for obj in layout["objects"] if obj["object_id"] == group_id)["child_ids"].remove(pointer["object_id"])
            before = artifact_rows(service, pid)
            with pytest.raises(ProjectError) as failure:
                service.write(pid, "layout", layout, project["revision"])
            assert failure.value.code == "invalid_artifact"
            assert service.open(pid)["revision"] == project["revision"]
            assert artifact_rows(service, pid) == before
            return
        service.write(pid, "layout", layout, project["revision"])
        assert service.artifact(pid, "layout")["document"] == layout
        before = artifact_rows(service, pid)
        copied = service.duplicate(pid)
        duplicate = service.artifact(copied["project_id"], "layout")["document"]
        assert next(obj for obj in duplicate["objects"] if obj["object_id"] == "annotation-leader")["parent_id"] == group_id
        assert next(obj for obj in duplicate["objects"] if obj["object_id"] == "annotation-note")["callout_binding"] == next(
            obj for obj in layout["objects"] if obj["object_id"] == "annotation-note")["callout_binding"]
        assert artifact_rows(service, pid) == before
    finally:
        service.store.close()


def test_complete_callout_definition_materializes_into_a_real_validated_destination():
    from test_v2_composition_contract import bound_native_definition
    from test_v2_composition_materializer import (
        instance_spec,
        layout_for_expansion,
        materializer,
    )

    spec = instance_spec(bound_native_definition("callout"))
    expanded = materializer().materialize_composition(spec)
    layout = layout_for_expansion(expanded)
    materializer().validate_composition_expansion(spec, layout)
    typed = contracts.ExecutableLayoutV2.model_validate(layout)
    mapped = {row["local_object_id"]: row["object_id"] for row in spec["object_map"]}
    pointer = next(obj for obj in typed.objects if obj.object_id == mapped["annotation-leader"])
    assert pointer.parent_id == spec["root_object_id"]
    binding = contracts.CompositionBinding.model_validate(materializer().build_composition_binding(spec, layout))
    assert {row.object_id for row in binding.members} == {obj.object_id for obj in typed.objects}
