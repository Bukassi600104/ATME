"""P3-34 semantic anchors follow the actual centered SVG viewport, not its box."""

import importlib
import importlib.util
from copy import deepcopy

import pytest
from atme.render.style_bundle import load_bundle
from atme.render.v2_world import world_anchor
from atme.store.contracts_v2 import Bounds, GroupContainer, Transform, VisualObject
from test_v2_group_hierarchy import grouped_documents
from test_v2_registry_binding import registry_object


def placement_module():
    name = "atme.render.v2_registry"
    assert importlib.util.find_spec(name), "Registry fitted-anchor projection is not implemented"
    return importlib.import_module(name)


def asset(asset_id="person-collaborators"):
    return next(row for row in load_bundle()[1].assets if row.id == asset_id)


@pytest.mark.parametrize("box,fit,left", [
    ((100., 200., 300., 300.), (100., 240., 300., 220.), (190., 345.6)),
    ((100., 200., 600., 220.), (250., 200., 300., 220.), (340., 305.6)),
    ((100., 200., 150., 300.), (100., 295., 150., 110.), (145., 347.8)),
])
def test_meet_projection_preserves_real_non_square_art_and_semantic_point(box, fit, left):
    module = placement_module()
    bounds = Bounds.model_validate(dict(zip(("x", "y", "width", "height"), box, strict=True)))
    placement = module.registry_placement(asset(), bounds)
    assert placement.viewport == box
    assert placement.fitted == fit
    assert placement.anchor_point("left_person") == pytest.approx(left, abs=1e-10)
    assert placement.view_box == (0, 0, 300, 220)


def test_placement_quantizes_serialized_bounds_before_svg_fit():
    module = placement_module()
    bounds = Bounds(x=100.00004, y=200.00004, width=300.00004, height=300.00004)
    placement = module.registry_placement(asset(), bounds)
    assert placement.viewport == (100., 200., 300., 300.)
    assert placement.fitted == (100., 240., 300., 220.)
    assert placement.anchor_point("left_person") == pytest.approx((190., 345.6), abs=1e-10)


@pytest.mark.parametrize("delta", [0., .00004])
def test_fitted_binding_accepts_equal_canonical_endpoint_not_raw_float_identity(delta):
    raw = registry_object()
    raw["anchors"][0]["point"]["y"] = (145.6 + delta) / 300
    placement = placement_module().validate_registry_binding(VisualObject.model_validate(raw), asset())
    assert placement.anchor_point("left_person") == pytest.approx((190., 345.6), abs=1e-10)


@pytest.mark.parametrize("point", [.48, 145.60006 / 300])
def test_binding_rejects_raw_box_letterbox_or_cross_quantum_endpoint(point):
    module = placement_module()
    raw = registry_object()
    raw["anchors"][0]["point"]["y"] = point
    with pytest.raises(module.UnsupportedRegistryPlacement, match="does not match fitted registry anchor"):
        module.validate_registry_binding(VisualObject.model_validate(raw), asset())


def test_unknown_semantic_name_does_not_fall_back_to_center():
    module = placement_module()
    raw = registry_object()
    raw["registry_binding"]["anchor_mappings"][0]["registry_anchor_name"] = "invented-hand"
    with pytest.raises(module.UnsupportedRegistryPlacement, match="unknown registry anchor"):
        module.validate_registry_binding(VisualObject.model_validate(raw), asset())


def test_binding_cannot_use_metadata_from_a_different_checked_asset():
    module = placement_module()
    with pytest.raises(module.UnsupportedRegistryPlacement, match="different registry asset"):
        module.validate_registry_binding(VisualObject.model_validate(registry_object()), asset("person-presenter"))


@pytest.mark.parametrize("field,value", [
    ("width", .00001), ("height", .00001), ("x", float("nan")),
    ("y", float("inf")), ("x", 1_000_001.), ("width", -1.),
])
def test_serialized_projection_rejects_collapsed_or_invalid_bounds(field, value):
    module = placement_module()
    raw = {"x": 100., "y": 200., "width": 300., "height": 300.}
    raw[field] = value
    with pytest.raises(ValueError):
        module.registry_placement(asset(), Bounds.model_construct(**raw))


def test_authenticated_local_point_uses_existing_nonidentity_world_matrix():
    raw = registry_object()
    raw["parent_id"] = "parent"
    raw["transform"] = {"position": {"x": 5., "y": 7.}, "scale_x": 1.5, "scale_y": .5,
        "rotation_degrees": 0., "origin": {"x": 0., "y": 0.}}
    obj = VisualObject.model_validate(raw)
    parent_raw = deepcopy(grouped_documents()[0]["objects"][3])
    parent_raw.update(object_id="parent", child_ids=[obj.object_id], parent_id=None,
        transform={"position": {"x": 40., "y": 30.}, "scale_x": 2., "scale_y": 1.25,
            "rotation_degrees": 0., "origin": {"x": 0., "y": 0.}})
    parent_raw["geometry"]["bounds"] = {"x": 0., "y": 0., "width": 1200., "height": 600.}
    parent = GroupContainer.model_validate(parent_raw)
    placement_module().validate_registry_binding(obj, asset())
    objects = {obj.object_id: obj, parent.object_id: parent}
    transforms = {key: Transform.model_validate(row.transform.model_dump()) for key, row in objects.items()}
    # Literal derivation: item (190,345.6) -> actor (240,279.8) -> parent (520,379.75).
    assert world_anchor(obj, "actor-left", objects, transforms) == pytest.approx((520., 379.75), abs=1e-10)
