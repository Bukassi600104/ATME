"""P3-28 exact authored point/edge authority inside reusable composition graphs."""

from copy import deepcopy

import pytest
from atme.project_service import _resolved_compilation_fingerprint
from atme.render.v2_composition import (
    build_composition_binding,
    materialize_composition,
)
from atme.store import contracts_v2 as contracts
from test_v2_composition_contract import composition_definition
from test_v2_composition_materializer import instance_spec, layout_for_expansion
from test_v2_pointer_contract import pointer_payload
from test_v2_pointer_project import persist_relationship
from test_v2_registry_project import history
from test_v2_resolved_project import stored_v2_basis
from v2_fixtures import digest, resolved_timeline_v2, visual_plan_v2


def composed_relationship_documents(kind="pointer"):
    definition = composition_definition()
    definition["objects"][0]["geometry"]["corner_radius"] = None
    arrow = pointer_payload()
    arrow.update(object_id="leader", board_id="template-board", beat_id="template-beat",
                 parent_id="root", destination_object_id="label", initial_state="visible", visible=True,
                 coverage_ids=["coverage-1"])
    if kind != "pointer":
        arrow.pop("source_point")
        arrow.update(object_type="network" if kind == "network" else "arrow", role="semantic_connector",
                     source_object_id="node", source_anchor_id="center")
    definition["objects"].append(arrow)
    definition["objects"][0]["child_ids"].append("leader")
    spec = instance_spec(definition)
    objects = materialize_composition(spec)
    layout = layout_for_expansion(objects)
    plan = visual_plan_v2()
    plan["assets"] = []
    for key in ("actions", "coverage", "fallbacks"):
        plan[key] = plan[key][:2]
    plan["beats"] = plan["beats"][:1]
    plan["conclusion_beat_id"] = plan["opening_beat_id"]
    fields = set(contracts.SemanticStandardObjectSpec.model_fields)
    plan["objects"] = [{key: deepcopy(value) for key, value in obj.items()
                        if key in fields and (key != "clip_id" or value is not None)}
                       for obj in layout["objects"]]
    connector = layout["objects"][-1]
    binding_fields = {"source_object_id", "source_anchor_id", "destination_object_id",
                      "destination_anchor_id", "source_point", "role", "routing", "allow_self_loop"}
    plan["objects"][-1]["connector_binding"] = {
        key: deepcopy(value) for key, value in connector.items() if key in binding_fields}
    plan["boards"] = deepcopy(layout["boards"])
    ids = {row["local_object_id"]: row["object_id"] for row in spec["object_map"]}
    beat = plan["beats"][0]
    beat["object_ids"] = [obj["object_id"] for obj in layout["objects"]]
    beat["attention"].update(primary_targets=[ids["node"]], secondary_context=[ids["label"], ids["leader"]])
    beat["camera_intent"]["target_ids"] = [ids["node"]]
    for action, key in zip(plan["actions"], ("node", "label"), strict=True):
        action.update(verb="reveal", target_ids=[ids[key]], expected_state="visible")
    binding = build_composition_binding(spec, layout)
    plan["objects"][0].update(object_type="instance", composition_binding=deepcopy(binding))
    layout["objects"][0]["composition_binding"] = deepcopy(binding)
    layout["plan_sha256"] = digest(plan)
    return plan, layout, spec


@pytest.mark.parametrize("kind", ["pointer", "network", "anchored"])
def test_composition_projection_preserves_authored_mapped_connector_authority(kind):
    plan, layout, spec = composed_relationship_documents(kind)
    before = deepcopy((plan, layout, spec))
    contracts.validate_plan_layout(plan, layout)
    ids = {row["local_object_id"]: row["object_id"] for row in spec["object_map"]}
    connector = layout["objects"][-1]
    assert connector["destination_object_id"] == ids["label"]
    if kind == "pointer":
        assert connector["source_point"] == {"x": 80.5, "y": 60.25}
        assert connector["source_object_id"] is connector["source_anchor_id"] is None
    else:
        assert connector["source_object_id"] == ids["node"]
        assert "source_point" not in connector
    assert (plan, layout, spec) == before


@pytest.mark.parametrize("kind", ["pointer", "network", "anchored"])
@pytest.mark.parametrize("fault", ["source", "destination", "route"])
def test_composition_cannot_coherently_rehash_changed_semantic_relationship_authority(kind, fault):
    plan, layout, _ = composed_relationship_documents(kind)
    # First establish a genuinely valid binding; otherwise these negatives can
    # falsely pass because every bound pointer was already being rejected.
    contracts.validate_plan_layout(plan, layout)
    binding = plan["objects"][-1]["connector_binding"]
    if fault == "source":
        if kind == "pointer":
            binding["source_point"]["x"] += 1
        else:
            binding["source_anchor_id"] = "different"
    elif fault == "destination":
        binding["destination_anchor_id"] = "different"
    else:
        binding["routing"] = "curve"
    layout["plan_sha256"] = digest(plan)
    with pytest.raises(ValueError, match="expanded member|connector_binding"):
        contracts.validate_plan_layout(plan, layout)


@pytest.mark.parametrize("kind", ["network", "anchored"])
def test_composition_legacy_named_connector_omission_stays_loadable_without_new_write_admission(kind):
    plan, layout, _ = composed_relationship_documents(kind)
    plan["objects"][-1].pop("connector_binding")
    layout["plan_sha256"] = digest(plan)
    before = deepcopy((plan, layout))
    contracts.validate_plan_layout(plan, layout, require_code_payloads=False)
    assert (plan, layout) == before
    if kind == "network":
        with pytest.raises(ValueError, match="requires exact semantic connector_binding"):
            contracts.validate_plan_layout(plan, layout)
    else:
        contracts.validate_plan_layout(plan, layout)


@pytest.mark.parametrize("portrait", [False, True])
def test_composed_free_pointer_stored_duplicate_and_native_preview_keep_mapped_authority(tmp_path, portrait):
    from atme.render.v2_svg import compose_png_frame

    profile = "SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9"
    service, project, original, _, _ = stored_v2_basis(tmp_path, profile=profile)
    try:
        plan, layout, _ = composed_relationship_documents()
        plan.update(narrative_authority=deepcopy(original["narrative_authority"]),
                    output_profile=deepcopy(original["output_profile"]))
        layout["output_profile"] = deepcopy(plan["output_profile"])
        layout["canvas"].update(width=plan["output_profile"]["width"], height=plan["output_profile"]["height"])
        clock = resolved_timeline_v2(plan, layout)
        clock.update(output_profile=deepcopy(plan["output_profile"]), resolved_assets=[],
                     beat_anchors=clock["beat_anchors"][:1])
        clock["initial_object_states"] = [{"object_id": obj["object_id"], "state": obj["initial_state"],
            "visible": obj["visible"], "state_version": 1} for obj in layout["objects"]]
        project = persist_relationship(service, project, plan, layout, clock)
        pid = project["project_id"]
        before = deepcopy((history(service, pid), service.source_timeline.get(pid)))
        expected = {at: compose_png_frame(layout, clock, at).png for at in (0, 2450, 4900)}
        assert len(set(expected.values())) > 1
        assert service.runner.preview_v2_source(pid, project["revision"], 4900)["png"] == expected[4900]
        duplicate = service.duplicate(pid)
        copied_plan = service.artifact(duplicate["project_id"], "storyboard")["document"]
        copied_layout = service.artifact(duplicate["project_id"], "layout")["document"]
        copied_clock = service.artifact(duplicate["project_id"], "resolved_timeline")["document"]
        assert copied_plan["objects"] == plan["objects"]
        assert copied_layout["objects"] == layout["objects"]
        assert copied_clock["compilation_fingerprint"] == _resolved_compilation_fingerprint(copied_clock)
        for at in (4900, 0, 2450, 0):
            assert compose_png_frame(copied_layout, copied_clock, at).png == expected[at]
        assert (history(service, pid), service.source_timeline.get(pid)) == before
    finally:
        service.store.close()
