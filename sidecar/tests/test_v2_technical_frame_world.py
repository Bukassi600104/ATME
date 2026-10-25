"""Role fit uses actual sampled affine quadrilaterals, never world AABBs."""

from copy import deepcopy
from dataclasses import replace

import pytest
from test_v2_technical_frame_contract import documents, nested_documents

from atme.render import v2_technical_frame as native
from atme.render.v2_state import FramePoint, FrameTransform
from atme.render.v2_world import world_bounds
from atme.store.contracts_v2 import ExecutableLayoutV2


def sampled(*, nested=False):
    _, raw = nested_documents() if nested else documents()
    objects = {obj["object_id"]: obj for obj in raw["objects"]}
    chrome = objects["object-evidence"]
    chrome["geometry"]["bounds"] = {"x": 100., "y": 200., "width": 500., "height": 300.}
    chrome["anchors"][0]["point"] = {"x": .5, "y": 10/600}
    chrome["style"] = {"stroke": "ink", "fill": None, "text": None, "effect": None}
    boxes = {"part-title": (200., 215., 200., 20.), "part-address": (150., 265., 200., 20.),
        "part-content": (140., 330., 200., 120.), "list-group": (100., 200., 500., 300.)}
    if nested:
        boxes["content-leaf"] = (150., 340., 100., 80.)
    for key, values in boxes.items():
        objects[key]["geometry"]["bounds"] = dict(zip(("x", "y", "width", "height"), values, strict=True))
    layout = ExecutableLayoutV2.model_validate(raw)
    objects = {obj.object_id: obj for obj in layout.objects}
    transforms = {key: FrameTransform.from_contract(obj.transform) for key, obj in objects.items()}
    return objects["object-evidence"], objects, transforms


def validate(obj, objects, transforms):
    assert hasattr(native, "validate_technical_frame_world"), "actual sampled native world/role fit is missing"
    return native.validate_technical_frame_world(obj, objects, transforms)


def pose(x=0., y=0., sx=1., sy=1., angle=0., origin=(.5, .5)):
    return FrameTransform(FramePoint(x, y), sx, sy, angle, FramePoint(*origin))


def test_sampled_nonuniform_rotation_and_translation_have_literal_physical_endpoint():
    obj, objects, transforms = sampled()
    before = {key: item.model_dump(mode="json") for key, item in objects.items()}
    transforms["list-group"] = pose(10., 20., 2., 3., 90.)
    assert validate(obj, objects, transforms) == (("chrome-top", (795., 370.)),)
    assert {key: item.model_dump(mode="json") for key, item in objects.items()} == before


def test_fractional_pivot_is_not_replaced_with_default_center():
    obj, objects, transforms = sampled()
    transforms["list-group"] = pose(10., 20., 2., 3., 90., origin=(.25, .75))
    assert validate(obj, objects, transforms) == (("chrome-top", (895., 695.)),)


def test_complete_two_owned_ancestor_chain_has_literal_endpoint():
    obj, objects, transforms = sampled()
    outer = deepcopy(objects["list-group"])
    outer.object_id = "outer"
    outer.child_ids = ["list-group"]
    objects["outer"] = outer
    objects["list-group"].parent_id = "outer"
    transforms["list-group"] = pose(10., 20., 2., 3., 90.)
    transforms["outer"] = pose(-20., 10., .5, 2.)
    assert validate(obj, objects, transforms) == (("chrome-top", (552.5, 400.)),)


def test_ordinary_current_pose_not_authored_pose_controls_role_fit():
    obj, objects, transforms = sampled()
    validate(obj, objects, transforms)
    transforms["part-content"] = pose(500., 0.)
    with pytest.raises(ValueError, match="outside.*native.*region"):
        validate(obj, objects, transforms)


def test_rotated_region_rejects_content_inside_aabb_but_outside_actual_quad():
    obj, objects, transforms = sampled()
    transforms["list-group"] = pose(angle=45.)
    objects["part-content"].geometry.bounds.x = 115.
    objects["part-content"].geometry.bounds.y = 360.
    objects["part-content"].geometry.bounds.width = 10.
    objects["part-content"].geometry.bounds.height = 10.
    actual = world_bounds(objects["part-content"], objects, transforms)
    # Hand-derived native content quad has this broad AABB. The clip is outside
    # its left edge, despite every actual corner fitting the AABB.
    assert 95 < actual[0] < actual[2] < 541 and 159 < actual[1] < actual[3] < 605
    with pytest.raises(ValueError, match="outside.*native.*region"):
        validate(obj, objects, transforms)


def test_nested_real_content_subtree_uses_each_actual_local_pose():
    obj, objects, transforms = sampled(nested=True)
    transforms["part-content"] = pose(20., 10.)
    assert validate(obj, objects, transforms) == (("chrome-top", (350., 205.)),)
    transforms["content-leaf"] = pose(0., 300.)
    with pytest.raises(ValueError, match="content-leaf.*outside.*native.*region"):
        validate(obj, objects, transforms)


@pytest.mark.parametrize("fault", ["missing_pose", "cycle", "missing_parent", "second_owner", "cross_board",
    "changed_role_parent", "different_chrome", "unknown_node"])
def test_world_guard_cannot_fill_or_infer_missing_actual_hierarchy(fault):
    obj, objects, transforms = sampled()
    if fault == "missing_pose":
        transforms.pop("part-title")
    elif fault == "cycle":
        objects["list-group"].parent_id = "list-group"
    elif fault == "missing_parent":
        obj.parent_id = "absent"
    elif fault == "second_owner":
        group = deepcopy(objects["list-group"])
        group.object_id = "second-owner"
        objects[group.object_id] = group
        transforms[group.object_id] = FrameTransform.from_contract(group.transform)
    elif fault == "cross_board":
        objects["part-title"].board_id = "foreign-board"
    elif fault == "changed_role_parent":
        objects["part-title"].parent_id = None
        objects["list-group"].child_ids.remove("part-title")
    elif fault == "different_chrome":
        objects[obj.object_id] = deepcopy(obj)
        objects[obj.object_id].geometry.bounds.x += 1
    else:
        objects["list-group"].__dict__["ignored_payload"] = True
    with pytest.raises(ValueError):
        validate(obj, objects, transforms)


def test_local_q4_equivalence_does_not_authorize_amplified_world_anchor():
    obj, objects, transforms = sampled()
    obj.anchors[0].point.x += .00000001
    native.validate_technical_frame_local(obj)
    transforms["list-group"] = pose(sx=1000., sy=1000.)
    with pytest.raises(ValueError, match="sampled world anchor"):
        validate(obj, objects, transforms)


def test_shuffled_current_samples_are_pure_and_have_no_file_or_network_lookup(monkeypatch):
    from pathlib import Path
    from socket import socket

    obj, objects, transforms = sampled()
    expected = validate(obj, objects, transforms)
    def forbidden(*args, **kwargs):
        raise AssertionError("pure world fit attempted IO")
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(socket, "connect", forbidden)
    for x in (30., -20., 10., 30.):
        transforms["list-group"] = pose(x)
        assert validate(obj, objects, transforms) == (("chrome-top", (350. + x, 205.)),)
    transforms["list-group"] = FrameTransform.from_contract(objects["list-group"].transform)
    assert validate(obj, objects, transforms) == expected


@pytest.mark.parametrize("field", ["position_x", "position_y", "origin_x", "origin_y",
    "rotation_degrees", "scale_x", "scale_y"])
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, "1", None])
def test_runtime_sample_rejects_invalid_numbers_before_any_geometry(field, bad):
    obj, objects, transforms = sampled()
    # Include a real unrelated node: full supplied sample authentication must
    # not depend on which matrix happens to be visited later.
    source = transforms["object-label"]
    if field.startswith(("position_", "origin_")):
        name, axis = field.split("_")
        invalid = replace(source, **{name: replace(getattr(source, name), **{axis: bad})})
    else:
        invalid = replace(source, **{field: bad})
    transforms["object-label"] = invalid
    original_objects = {key: item.model_dump(mode="json") for key, item in objects.items()}
    with pytest.raises(ValueError, match="technical_frame current transform"):
        validate(obj, objects, transforms)
    assert transforms["object-label"] is invalid
    assert transforms[obj.object_id] == FrameTransform.from_contract(obj.transform)
    assert {key: item.model_dump(mode="json") for key, item in objects.items()} == original_objects


@pytest.mark.parametrize("field", ["scale_x", "scale_y"])
@pytest.mark.parametrize("bad", [0., -1.])
def test_runtime_sample_rejects_nonpositive_scales_without_mutation(field, bad):
    obj, objects, transforms = sampled()
    invalid = replace(transforms["object-label"], **{field: bad})
    transforms["object-label"] = invalid
    with pytest.raises(ValueError, match="technical_frame current transform"):
        validate(obj, objects, transforms)
    assert transforms["object-label"] is invalid
