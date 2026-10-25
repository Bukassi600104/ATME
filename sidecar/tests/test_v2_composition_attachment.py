"""A bound semantic root may lower only to its exact same-ID ordinary Group."""
from copy import deepcopy

import pytest
from atme.store import contracts_v2 as contracts
from jsonschema import Draft202012Validator
from test_v2_composition_binding import rehash_binding
from test_v2_composition_contract import composition_definition
from test_v2_composition_materializer import (
    instance_spec,
    layout_for_expansion,
    materializer,
)
from v2_fixtures import digest, visual_plan_v2


def composition_project_documents(kind="instance", *, attach=True, definition=None):
    definition = deepcopy(definition) if definition is not None else composition_definition()
    for obj in definition["objects"][1:]:
        obj.update(visible=False, initial_state="hidden")
    spec = instance_spec(definition)
    spec["kind"] = kind
    if spec["parameter_values"]:
        spec["parameter_values"][-1]["value"]["value"] = False
    objects = materializer().materialize_composition(spec)
    layout = layout_for_expansion(objects)
    plan = visual_plan_v2()
    plan["assets"] = []
    for field in ("actions", "fallbacks", "coverage"):
        plan[field] = plan[field][:2]
    plan["beats"] = plan["beats"][:1]
    plan["conclusion_beat_id"] = plan["opening_beat_id"]
    fields = set(contracts.SemanticStandardObjectSpec.model_fields)
    plan["objects"] = [{key: deepcopy(value) for key, value in obj.items()
                        if key in fields and (key != "clip_id" or value is not None)}
                       for obj in layout["objects"]]
    plan["boards"] = deepcopy(layout["boards"])
    ids = [obj["object_id"] for obj in layout["objects"]]
    plan["beats"][0]["object_ids"] = ids
    plan["beats"][0]["attention"].update(primary_targets=[ids[1]], secondary_context=[ids[2]])
    plan["beats"][0]["camera_intent"]["target_ids"] = [ids[1]]
    plan["actions"][0]["target_ids"] = [ids[1]]
    plan["actions"][1]["target_ids"] = [ids[2]]
    layout["plan_sha256"] = digest(plan)
    # Prove the fixture's ordinary pre-binding graph is valid before asking a
    # missing alias/binding contract to accept the new shape.
    contracts.validate_plan_layout(plan, layout)
    if attach:
        binding = materializer().build_composition_binding(spec, layout)
        plan["objects"][0].update(object_type=kind, composition_binding=deepcopy(binding))
        for field in ("character_assembly", "illustration_assembly"):
            plan["objects"][0].pop(field, None)  # Authenticated native root metadata stays in the binding.
        layout["objects"][0]["composition_binding"] = deepcopy(binding)
        layout["plan_sha256"] = digest(plan)
    return plan, layout


def test_unbound_ordinary_group_fixture_preserves_the_existing_contract():
    plan, layout = composition_project_documents(attach=False)
    contracts.validate_plan_layout(plan, layout)


@pytest.mark.parametrize("kind", ["composition", "instance"])
def test_exact_bound_semantic_root_lowers_to_the_same_real_group(kind):
    plan, layout = composition_project_documents(kind)
    contracts.validate_plan_layout(plan, layout)
    parsed = contracts.ExecutableLayoutV2.model_validate(layout)
    assert type(parsed.objects[0]) is contracts.GroupContainer
    assert parsed.objects[0].object_id == plan["objects"][0]["object_id"]
    assert parsed.objects[0].composition_binding.model_dump(mode="json") == plan["objects"][0]["composition_binding"]
    Draft202012Validator(contracts.VisualPlanV2.model_json_schema()).validate(plan)
    Draft202012Validator(contracts.ExecutableLayoutV2.model_json_schema()).validate(layout)


@pytest.mark.parametrize("defect", ["other_type", "kind", "root_id", "missing_plan_binding", "missing_layout_binding",
    "direct_children", "missing_member", "extra_member", "binding_difference", "false_root_order"])
def test_alias_never_waives_binding_identity_direct_members_or_actual_graph(defect):
    plan, layout = composition_project_documents()
    root = plan["objects"][0]
    if defect == "other_type":
        root["object_type"] = "comparison"
    elif defect == "kind":
        root["object_type"] = "composition"
    elif defect == "root_id":
        root["object_id"] = "different-root"
    elif defect == "missing_plan_binding":
        root.pop("composition_binding")
    elif defect == "missing_layout_binding":
        layout["objects"][0].pop("composition_binding")
    elif defect == "direct_children":
        root["child_ids"].pop()
    elif defect == "missing_member":
        plan["objects"].pop()
        plan["boards"][0]["object_ids"].pop()
        plan["beats"][0]["object_ids"].pop()
    elif defect == "extra_member":
        extra = deepcopy(layout["objects"][1])
        extra.update(object_id="unmapped", parent_id=root["object_id"])
        layout["objects"].append(extra)
        layout["objects"][0]["child_ids"].append("unmapped")
        layout["boards"][0]["object_ids"].append("unmapped")
    else:
        binding = root["composition_binding"]
        next(row for row in binding["members"] if row["object_id"] == root["object_id"])["sibling_ordinal"] = 1
        rehash_binding(binding)
        if defect == "false_root_order":
            layout["objects"][0]["composition_binding"] = deepcopy(binding)
    layout["plan_sha256"] = digest(plan)
    with pytest.raises(ValueError):
        contracts.validate_plan_layout(plan, layout)


@pytest.mark.parametrize("family", ["character", "illustration"])
@pytest.mark.parametrize("native_root", [False, True])
def test_bound_root_preserves_native_assembly_ownership_without_semantic_alias_shortcuts(family, native_root):
    from test_v2_composition_contract import bound_native_definition

    definition = bound_native_definition(family)
    for obj in definition["objects"]:
        obj["coverage_ids"] = sorted({"coverage-1" if key == "coverage-3" else key for key in obj["coverage_ids"]})
    definition["template_coverage_ids"] = sorted({key for obj in definition["objects"] for key in obj["coverage_ids"]})
    field = f"{family}_assembly"
    if native_root:
        root = next(obj for obj in definition["objects"] if field in obj)
        definition["objects"] = [root, *(obj for obj in definition["objects"]
            if obj["object_id"] in root["child_ids"])]
        root["parent_id"] = None
        definition["root_local_id"] = root["object_id"]
    plan, layout = composition_project_documents(definition=definition)
    contracts.validate_plan_layout(plan, layout)
    assert plan["objects"][0]["object_type"] == "instance"
    assert "composition_binding" in plan["objects"][0]
    assert field not in plan["objects"][0] or not native_root
    native = next(obj for obj in layout["objects"] if field in obj)
    assert native[field]["roles"]
