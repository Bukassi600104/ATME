"""The external-read membership allowance cannot borrow an owned assembly."""
from copy import deepcopy

import pytest
from atme.render.v2_composition import (
    build_composition_binding,
    materialize_composition,
)
from atme.store import contracts_v2 as contracts
from test_v2_composition_materializer import instance_spec
from test_v2_external_aperture_membership import membership_documents


@pytest.mark.parametrize("kind", ["clip", "mask"])
def test_existing_composition_gate_blocks_a_bound_closure_below_an_external_consumer(kind):
    layout, _clock, ids, _reference = membership_documents(kind)
    spec = instance_spec(root="owned-assembly")
    spec["root_parent_id"] = ids["receiver"]
    additions = [obj.model_dump(mode="json") for obj in materialize_composition(spec)]
    member = next(obj for obj in layout["objects"] if obj["object_id"] == ids["receiver"])
    member["child_ids"].append(spec["root_object_id"])
    layout["objects"].extend(additions)
    layout["boards"][0]["object_ids"].extend(obj["object_id"] for obj in additions)
    layout["boards"][0]["density_limit"] = len(layout["boards"][0]["object_ids"])
    contracts.ExecutableLayoutV2.model_validate(layout)
    original = deepcopy(layout)
    # The actual accepted expansion gate rejects before a binding can exist.
    # Do not fabricate one just to cover a later defense-in-depth predicate.
    with pytest.raises(ValueError, match="composition external parent.*clipping remains closed"):
        build_composition_binding(spec, layout)
    assert layout == original


@pytest.mark.parametrize("field", ["clip_id", "child_ids", "mask_source_object_id"])
def test_destination_receipt_cannot_smuggle_read_or_reciprocal_identity_fields(field):
    _layout, clock, ids, _reference = membership_documents("mask")
    policy = next(row["action"]["hierarchy_policy"] for row in clock["actions"]
                  if row["action"]["action_id"] == "external-membership")
    destination = deepcopy(policy["destination_basis"])
    row = next(row for row in destination["placements"] if row["object_id"] == ids["receiver"])
    row[field] = [] if field == "child_ids" else ids["source"]
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        contracts.HierarchyBasis.model_validate(destination)
