"""Shared checked coordinates for the existing sampled-aperture seam, not runtime admission."""
from copy import deepcopy
from dataclasses import fields
from math import cos, radians, sin

import pytest
from atme.render.v2_state import FrameTransform
from atme.render.v2_world import Affine, UnsupportedWorldGeometry, world_matrix
from atme.store import contracts_v2 as contracts
from test_v2_clip_containers import clipped_documents


@pytest.mark.parametrize("matrix,expected", [
    (Affine(), Affine()),
    (Affine(a=2., d=4., e=10., f=-20.), Affine(a=.5, d=.25, e=-5., f=5.)),
    (Affine(0., 1., -1., 0., 12., -3.), Affine(0., -1., 1., 0., 3., 12.)),
    (Affine(2., 1., 3., 2., 5., 7.), Affine(2., -1., -3., 2., 11., -9.)),
    (Affine(a=-2., d=4., e=6., f=8.), Affine(a=-.5, d=.25, e=3., f=-2.)),
])
def test_checked_inverse_matches_literal_affine_and_preserves_immutable_input(matrix, expected):
    before = deepcopy(matrix)
    actual = matrix.inverse()
    assert actual == expected
    assert matrix == before
    for product in (matrix @ actual, actual @ matrix):
        assert tuple(getattr(product, field.name) for field in fields(Affine)) == pytest.approx(
            (1., 0., 0., 1., 0., 0.), abs=1e-12)
    for point in ((0., 0.), (2., 3.), (-10., 25.)):
        assert actual.point(*matrix.point(*point)) == pytest.approx(point, abs=1e-12)


@pytest.mark.parametrize("matrix", [
    Affine(a=0., d=0.),
    Affine(1., 2., 2., 4.),
    Affine(a=float("nan")),
    Affine(f=float("inf")),
    Affine(e=1_000_001.),
    Affine(a=1e-8),
    Affine(1., 1., 1.+1e-10, 1.),
    Affine(a=.0001, e=200_000.),
])
def test_inverse_rejects_singular_or_unsupported_actual_coordinates(matrix):
    with pytest.raises(UnsupportedWorldGeometry):
        matrix.inverse()


def test_small_supported_scale_is_not_rejected_by_an_arbitrary_determinant_epsilon():
    matrix = Affine(a=.0001, d=.0001, e=100., f=-100.)
    assert matrix.inverse() == Affine(a=10_000., d=10_000., e=-1_000_000., f=1_000_000.)
    assert matrix.inverse().point(*matrix.point(12., 25.)) == pytest.approx((12., 25.), abs=1e-8)


@pytest.mark.parametrize("rotation", [17.1234, 90., 173.5])
def test_relative_projection_preserves_actual_rotated_nonuniform_ancestor_coordinates(rotation):
    raw, _clock = clipped_documents()
    layout = contracts.ExecutableLayoutV2.model_validate(raw)
    objects = {obj.object_id: obj for obj in layout.objects}
    owner = objects["object-group"]
    # A literal independent affine oracle: known zero origin/position, then
    # rotation and nonuniform scale. No AABB substitutes for the four corners.
    owner.geometry.bounds.x = 0.
    owner.geometry.bounds.y = 0.
    owner.geometry.bounds.width = 40.
    owner.geometry.bounds.height = 20.
    owner.transform.position.x = 0.
    owner.transform.position.y = 0.
    owner.transform.origin.x = 0.
    owner.transform.origin.y = 0.
    owner.transform.rotation_degrees = rotation
    owner.transform.scale_x = 1.2
    owner.transform.scale_y = .7
    owner.parent_id = None
    transforms = {key: FrameTransform.from_contract(obj.transform) for key, obj in objects.items()}
    pose = world_matrix(owner, objects, transforms)
    angle = radians(rotation)
    expected = [(1.2*x*cos(angle)-.7*y*sin(angle), 1.2*x*sin(angle)+.7*y*cos(angle))
                for x, y in ((0., 0.), (40., 0.), (40., 20.), (0., 20.))]
    actual = [pose.point(x, y) for x, y in ((0., 0.), (40., 0.), (40., 20.), (0., 20.))]
    for point, expected_point in zip(actual, expected, strict=True):
        assert point == pytest.approx(expected_point, abs=1e-11)
    # A separate consumer coordinate system: transforming the exact polygon
    # into it and back must recover each vertex, not a widened world rectangle.
    consumer = Affine(1.5, .25, -.4, .75, 20., -30.)
    relative = consumer.inverse() @ pose
    for local, world in zip(((0., 0.), (40., 0.), (40., 20.), (0., 20.)), actual, strict=True):
        assert consumer.point(*relative.point(*local)) == pytest.approx(world, abs=1e-10)


def test_inverse_consumes_the_actual_nested_world_matrix_without_requantizing_factors():
    raw, _clock = clipped_documents()
    inner = raw["objects"][3]
    inner["transform"].update(position={"x": 17.123456, "y": -3.456789}, scale_x=1.25, scale_y=.75,
                              rotation_degrees=30., origin={"x": .25, "y": .75})
    outer = deepcopy(inner)
    outer.update(object_id="outer-world-group", object_type="group", child_ids=[inner["object_id"]])
    outer["transform"].update(position={"x": 40., "y": 12.}, scale_x=.8, scale_y=1.1,
                              rotation_degrees=-20., origin={"x": .5, "y": .5})
    inner["parent_id"] = outer["object_id"]
    raw["objects"].append(outer)
    raw["boards"][0]["object_ids"].append(outer["object_id"])
    layout = contracts.ExecutableLayoutV2.model_validate(raw)
    objects = {obj.object_id: obj for obj in layout.objects}
    transforms = {key: FrameTransform.from_contract(obj.transform) for key, obj in objects.items()}
    target = objects["object-system"]
    pose = world_matrix(target, objects, transforms)
    before = deepcopy((objects, transforms))
    for point in ((100., 200.), (130., 270.), (250., 380.)):
        expected = point
        for key in (target.object_id, inner["object_id"], outer["object_id"]):
            obj, transform = objects[key], transforms[key]
            bounds = obj.geometry.bounds
            pivot = (round(bounds.x + bounds.width * transform.origin.x, 4),
                     round(bounds.y + bounds.height * transform.origin.y, 4))
            angle = radians(round(transform.rotation_degrees, 4))
            dx, dy = ((expected[0]-pivot[0])*round(transform.scale_x, 4),
                      (expected[1]-pivot[1])*round(transform.scale_y, 4))
            expected = (pivot[0]+dx*cos(angle)-dy*sin(angle)+round(transform.position.x, 4),
                        pivot[1]+dx*sin(angle)+dy*cos(angle)+round(transform.position.y, 4))
        assert pose.point(*point) == pytest.approx(expected, abs=1e-9)
        assert pose.inverse().point(*expected) == pytest.approx(point, abs=1e-9)
    assert (objects, transforms) == before
