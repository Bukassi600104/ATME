"""Final canonical registry endpoints must survive the complete sampled chain."""

import math
from copy import deepcopy

import pytest
from atme.render.v2_state import FrameTransform
from atme.store.contracts_v2 import GroupContainer, Transform, VisualObject
from test_v2_group_hierarchy import grouped_documents
from test_v2_registry_binding import registry_object
from test_v2_registry_placement import asset, placement_module


def world_validator():
    module = placement_module()
    assert hasattr(module, "validate_registry_world_binding"), "sampled registry world authentication is missing"
    return module.validate_registry_world_binding


def authored_chain(delta=0.):
    raw = registry_object()
    raw["anchors"][0]["point"]["y"] = (145.6 + delta) / 300
    raw["parent_id"] = "parent"
    raw["transform"] = {"position": {"x": 5., "y": 7.}, "scale_x": 1.5, "scale_y": .5,
        "rotation_degrees": 0., "origin": {"x": 0., "y": 0.}}
    obj = VisualObject.model_validate(raw)
    parent_raw = deepcopy(grouped_documents()[0]["objects"][3])
    parent_raw.update(object_id="parent", child_ids=[obj.object_id], parent_id="outer",
        transform={"position": {"x": 40., "y": 30.}, "scale_x": 2., "scale_y": 1.25,
            "rotation_degrees": 0., "origin": {"x": 0., "y": 0.}})
    parent_raw["geometry"]["bounds"] = {"x": 0., "y": 0., "width": 1200., "height": 600.}
    parent = GroupContainer.model_validate(parent_raw)
    outer_raw = deepcopy(parent_raw)
    outer_raw.update(object_id="outer", child_ids=["parent"], parent_id=None,
        transform={"position": {"x": -20., "y": 10.}, "scale_x": .5, "scale_y": 2.,
            "rotation_degrees": 0., "origin": {"x": 0., "y": 0.}})
    outer = GroupContainer.model_validate(outer_raw)
    objects = {row.object_id: row for row in (obj, parent, outer)}
    transforms = {key: row.transform for key, row in objects.items()}
    return obj, objects, transforms


@pytest.mark.parametrize("sampled", [False, True])
def test_exact_named_point_matches_literal_complete_nested_world_endpoint(sampled):
    obj, objects, transforms = authored_chain()
    if sampled:
        transforms = {key: FrameTransform.from_contract(value) for key, value in transforms.items()}
    before = {key: row.model_dump(mode="json") for key, row in objects.items()}
    result = world_validator()(obj, asset(), objects, transforms)
    # Local190,345.6 -> actor240,279.8 -> parent520,379.75 -> outer240,769.5.
    assert result == (("actor-left", (240., 769.5)),)
    assert before == {key: row.model_dump(mode="json") for key, row in objects.items()}
    with pytest.raises(TypeError):
        result[0] = ("forged", (0., 0.))


@pytest.mark.parametrize("owner", ["object", "parent", "outer"])
def test_local_sub_quantum_equivalence_is_rejected_when_sampled_chain_amplifies_it(owner):
    obj, objects, transforms = authored_chain(.00004)
    placement_module().validate_registry_binding(obj, asset())  # Local q4 matches.
    key = obj.object_id if owner == "object" else owner
    transforms[key] = transforms[key].model_copy(update={"scale_y": 100.})
    with pytest.raises(placement_module().UnsupportedRegistryPlacement, match="sampled world anchor"):
        world_validator()(obj, asset(), objects, transforms)


def test_local_sub_quantum_equivalence_survives_when_final_sample_is_canonically_equal():
    obj, objects, transforms = authored_chain(.00004)
    transforms["outer"] = transforms["outer"].model_copy(update={"scale_y": .01})
    assert world_validator()(obj, asset(), objects, transforms) == (("actor-left", (240., 13.7975)),)


def literal_transform(point, row, transform):
    q = lambda value: float(f"{value:.4f}")
    bounds = row.geometry.bounds
    ox, oy = q(bounds.x + bounds.width * transform.origin.x), q(bounds.y + bounds.height * transform.origin.y)
    theta = math.radians(q(transform.rotation_degrees))
    dx, dy = (point[0] - ox) * q(transform.scale_x), (point[1] - oy) * q(transform.scale_y)
    return (ox + dx * math.cos(theta) - dy * math.sin(theta) + q(transform.position.x),
            oy + dx * math.sin(theta) + dy * math.cos(theta) + q(transform.position.y))


@pytest.mark.parametrize("order", [(0, 1, 2, 3), (3, 1, 0, 2)])
def test_projection_uses_requested_fractional_rotation_pivots_not_authored_pose_or_previous_seek(order):
    obj, objects, transforms = authored_chain()
    baseline = deepcopy(transforms)
    results = {}
    for step in order:
        sampled = dict(transforms)
        sampled[obj.object_id] = Transform(position={"x": 5.123456 + step, "y": -7.654321},
            scale_x=.812345, scale_y=1.234567, rotation_degrees=11.234567 + step,
            origin={"x": .234567, "y": .765432})
        sampled["parent"] = Transform(position={"x": -2.123456, "y": 30.654321},
            scale_x=1.111111, scale_y=.876543, rotation_degrees=-23.456789,
            origin={"x": .3, "y": .6})
        expected = (190., 345.6)
        for key in (obj.object_id, "parent", "outer"):
            expected = literal_transform(expected, objects[key], sampled[key])
        expected = tuple(float(f"{value:.4f}") for value in expected)
        result = world_validator()(obj, asset(), objects,
            {key: FrameTransform.from_contract(value) for key, value in sampled.items()})
        assert result == (("actor-left", expected),)
        results[step] = result
    assert len(set(results.values())) == 4
    assert transforms == baseline


@pytest.mark.parametrize("mutation", ["missing-object", "different-object", "missing-parent", "missing-transform", "cycle"])
def test_incomplete_or_different_sample_chain_has_no_pose_fallback(mutation):
    obj, objects, transforms = authored_chain()
    if mutation == "missing-object":
        objects.pop(obj.object_id)
    elif mutation == "different-object":
        objects[obj.object_id] = obj.model_copy(update={"parent_id": None})
    elif mutation == "missing-parent":
        objects.pop("parent")
    elif mutation == "missing-transform":
        transforms.pop("outer")
    else:
        objects["outer"] = objects["outer"].model_copy(update={"parent_id": "parent"})
    with pytest.raises(placement_module().UnsupportedRegistryPlacement, match="sampled hierarchy"):
        world_validator()(obj, asset(), objects, transforms)


@pytest.mark.parametrize("field,value", [("scale_y", .00001), ("scale_y", float("nan")),
    ("rotation_degrees", float("inf")), ("scale_x", 1_000_001.)])
def test_sampled_invalid_world_components_fail_closed(field, value):
    obj, objects, transforms = authored_chain()
    transforms["parent"] = transforms["parent"].model_copy(update={field: value})
    with pytest.raises(ValueError):
        world_validator()(obj, asset(), objects, transforms)


@pytest.mark.parametrize("mutation", ["missing-child", "duplicate-child", "non-container", "second-owner", "root-claimed"])
def test_sampled_parent_claim_requires_unique_reciprocal_container_membership(mutation):
    obj, objects, transforms = authored_chain()
    if mutation == "missing-child":
        objects["parent"] = objects["parent"].model_copy(update={"child_ids": ["unrelated"]})
    elif mutation == "duplicate-child":
        objects["parent"] = objects["parent"].model_copy(update={"child_ids": [obj.object_id, obj.object_id]})
    elif mutation == "non-container":
        objects["parent"] = obj.model_copy(update={"object_id": "parent", "parent_id": "outer"})
    else:
        child = "outer" if mutation == "root-claimed" else obj.object_id
        objects["second-owner"] = objects["outer"].model_copy(update={"object_id": "second-owner", "child_ids": [child]})
    with pytest.raises(placement_module().UnsupportedRegistryPlacement, match="sampled hierarchy"):
        world_validator()(obj, asset(), objects, transforms)
