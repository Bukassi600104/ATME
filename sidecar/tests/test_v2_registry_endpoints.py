"""Bound relationship endpoints consume pinned bytes and the requested hierarchy."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from atme.render.style_bundle import load_bundle
from atme.render.v2_connector import connector_route
from atme.render.v2_state import FrameObject, FrameTransform
from atme.store.contracts_v2 import (
    ClipContainer,
    ConnectorObject,
    MaskContainer,
    TextObject,
)
from test_v2_connector_svg import connector_documents
from test_v2_mask_contract import MASK_FIELDS
from test_v2_registry_placement import placement_module
from test_v2_registry_world import authored_chain


def endpoint_module():
    module = placement_module()
    assert hasattr(module, "registry_endpoint_inputs"), "verified registry endpoint inputs are missing"
    assert hasattr(module, "registry_relationship_anchor"), "sampled registry relationship authentication is missing"
    return module


def inputs(asset_id="person-collaborators"):
    _, registry, root = load_bundle()
    entry = next(row for row in registry.assets if row.id == asset_id)
    return endpoint_module().registry_endpoint_inputs((root / "asset-registry.json").read_bytes(),
        {asset_id: (root / entry.file).read_bytes()})


def route_scene(delta=0.):
    actor, objects, transforms = authored_chain(delta)
    source = connector_documents()[0]
    label = TextObject.model_validate(source["objects"][1])
    objects[label.object_id] = label
    transforms[label.object_id] = label.transform
    arrow_raw = deepcopy(source["objects"][3])
    arrow_raw.update(source_object_id=actor.object_id, source_anchor_id="actor-left",
        destination_object_id=label.object_id, destination_anchor_id="center")
    arrow_raw["geometry"]["bounds"] = {"x": 0., "y": 0., "width": 1200., "height": 1000.}
    arrow = ConnectorObject.model_validate(arrow_raw)
    objects[arrow.object_id] = arrow
    transforms[arrow.object_id] = arrow.transform
    frames = {key: FrameObject(key, row.board_id, "visible", True, 1., 1.,
        FrameTransform.from_contract(transforms[key])) for key, row in objects.items()}
    return actor, arrow, objects, transforms, frames


def test_relationship_endpoint_is_literal_nested_world_position_without_file_io(monkeypatch):
    actor, _, objects, transforms, _ = route_scene()
    module, frozen = endpoint_module(), inputs()
    before = {key: row.model_dump(mode="json") for key, row in objects.items()}
    monkeypatch.setattr(Path, "read_bytes", lambda *_: pytest.fail("endpoint math attempted resource IO"))
    assert module.registry_relationship_anchor(actor, "actor-left", objects, transforms, frozen) == (240., 769.5)
    assert before == {key: row.model_dump(mode="json") for key, row in objects.items()}


@pytest.mark.parametrize("routing,want", [
    ("straight", ((240., 769.5), (300., 250.))),
    ("elbow", ((240., 769.5), (300., 769.5), (300., 250.))),
    ("curve", ((240., 769.5), (270., 769.5), (300., 250.))),
])
def test_shared_connector_routes_use_verified_registry_endpoint(routing, want):
    _, arrow, objects, _, frames = route_scene()
    arrow = arrow.model_copy(update={"routing": routing})
    route = connector_route(arrow, objects, frames, 2.6667, registry_inputs=inputs())
    assert route.points == want
    assert route.length > 0


def test_bound_connector_never_falls_back_to_arbitrary_normalized_anchor_without_inputs():
    _, arrow, objects, _, frames = route_scene()
    with pytest.raises(ValueError, match="registry endpoint requires verified inputs"):
        connector_route(arrow, objects, frames, 2.6667)


def test_endpoint_inputs_require_the_exact_variant_not_another_valid_asset():
    actor, _, objects, transforms, _ = route_scene()
    with pytest.raises(ValueError, match="registry endpoint inputs lack the exact variant"):
        endpoint_module().registry_relationship_anchor(actor, "actor-left", objects, transforms, inputs("person-presenter"))


@pytest.mark.parametrize("mutation", ["art", "registry", "duplicate", "mutable", "extra"])
def test_forged_frozen_endpoint_inputs_are_rechecked_at_consumption(mutation):
    actor, _, objects, transforms, _ = route_scene()
    module, frozen = endpoint_module(), inputs()
    if mutation == "registry":
        frozen = replace(frozen, registry_payload=frozen.registry_payload + b" ")
    elif mutation == "art":
        key, raw = frozen.artworks[0]
        frozen = replace(frozen, artworks=((key, raw + b" "),))
    elif mutation == "duplicate":
        frozen = replace(frozen, artworks=(*frozen.artworks, frozen.artworks[0]))
    elif mutation == "mutable":
        frozen = replace(frozen, artworks=list(frozen.artworks))
    else:
        object.__setattr__(frozen, "unproved", True)
    with pytest.raises(ValueError, match="checksum|immutable registry endpoint inputs"):
        module.registry_relationship_anchor(actor, "actor-left", objects, transforms, frozen)


@pytest.mark.parametrize("owner,kind", [("parent", "clip"), ("outer", "mask"),
    ("actor", "clip_id"), ("outer", "clip_id")])
def test_bound_anchor_refuses_actual_sampled_aperture_chain(owner, kind):
    actor, arrow, objects, _, frames = route_scene()
    key = actor.object_id if owner == "actor" else owner
    raw = objects[key].model_dump(mode="json")
    if kind == "clip_id":
        objects[key] = objects[key].model_copy(update={"clip_id": "explicit-aperture"})
    elif kind == "clip":
        raw["object_type"] = "clip"
        objects[key] = ClipContainer.model_validate(raw)
    else:
        raw.update(object_type="mask", **MASK_FIELDS)
        objects[key] = MaskContainer.model_validate(raw)
    with pytest.raises(ValueError, match="registry relationship anchor is unavailable under sampled aperture"):
        connector_route(arrow, objects, frames, 2.6667, registry_inputs=inputs())


def test_unrelated_clipped_art_does_not_block_unclipped_registry_relationship():
    _, arrow, objects, _, frames = route_scene()
    unrelated = objects["parent"].model_copy(update={"object_id": "unrelated-clip", "parent_id": None,
        "child_ids": [], "clip_id": "unrelated-aperture"})
    objects[unrelated.object_id] = unrelated
    frames[unrelated.object_id] = replace(frames["parent"], object_id=unrelated.object_id)
    assert connector_route(arrow, objects, frames, 2.6667, registry_inputs=inputs()).points == ((240., 769.5), (300., 250.))


def test_local_sub_quantum_match_cannot_feed_a_different_sampled_world_route():
    _, arrow, objects, transforms, frames = route_scene(.00004)
    transformed = transforms["outer"].model_copy(update={"scale_y": 100.})
    frames["outer"] = replace(frames["outer"], transform=FrameTransform.from_contract(transformed))
    with pytest.raises(ValueError, match="sampled world anchor"):
        connector_route(arrow, objects, frames, 2.6667, registry_inputs=inputs())


def test_unknown_placed_anchor_is_not_inferred_from_registry_center():
    actor, _, objects, transforms, _ = route_scene()
    with pytest.raises(ValueError, match="unknown placed registry anchor"):
        endpoint_module().registry_relationship_anchor(actor, "not-authored", objects, transforms, inputs())
