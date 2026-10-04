"""A retained receipt covers non-painted mask geometry and empty structural shells."""

from copy import deepcopy

import pytest
from test_v2_mask_contract import masked_documents
from test_v2_return_board import return_documents
from test_v2_return_hierarchy import (
    group_return_documents,
    private_clock,
    rehash_receipt,
)
from v2_fixtures import digest

from atme.render.v2_hierarchy_replay import completed_hierarchy_basis
from atme.render.v2_state import V2FrameError, evaluate_frame
from atme.store.contracts_v2 import ResolvedVisualTimelineV2


def mask_return_documents():
    _, layout, timeline = masked_documents()
    layout["boards"][0]["expected_prior_state"] = "system_established"
    layout["activations"][0]["end_ms"] = 6500
    layout["activations"].append({**layout["activations"][0], "activation_id": "activation-return",
                                  "start_ms": 7000, "end_ms": 10000, "reason": "Return to masked work"})
    timeline["layout_sha256"] = digest(layout)
    _, prefix = private_clock(layout, timeline)
    sample = prefix.at(7000)
    frames = {obj.object_id: obj for obj in sample.objects}
    basis = completed_hierarchy_basis(sample.hierarchy, frames)
    _, example = return_documents()
    returned = deepcopy(example["actions"][2])
    returned.update(start_ms=7000, end_ms=7001)
    trigger = {"kind": "absolute", "at_ms": 7000}
    returned["resolved_trigger"].update(source=trigger, alignment_anchor_ms=7000, resolved_at_ms=7000)
    returned["action"].update(trigger=trigger,
                               expected_object_states={key: obj.state for key, obj in frames.items()},
                               expected_object_state_versions=dict(sample.state_versions))
    returned["return_hierarchy_receipt"] = {
        "action_id": "return-1", "destination_board_id": "board-main",
        "destination_activation_id": "activation-return", "hierarchy_basis": basis.model_dump(mode="json"),
        "hierarchy_basis_sha256": basis.checksum(),
    }
    timeline["actions"].append(returned)
    timeline["coverage"][2]["action_ids"].append("return-1")
    return layout, timeline


def test_mask_source_and_container_survive_return_without_becoming_visible_artwork():
    layout, timeline = mask_return_documents()
    receipt = timeline["actions"][-1]["return_hierarchy_receipt"]
    assert {p["object_id"] for p in receipt["hierarchy_basis"]["placements"]} == {
        obj["object_id"] for obj in layout["objects"]}
    assert "mask-source" in timeline["actions"][-1]["action"]["expected_object_states"]
    prior, returned = evaluate_frame(layout, timeline, 6499), evaluate_frame(layout, timeline, 7000)
    assert prior.hierarchy == returned.hierarchy
    assert prior.objects == returned.objects
    from atme.render.v2_svg import compose_svg_frame

    assert 'data-object-id="mask-source"' not in compose_svg_frame(layout, timeline, 7000).svg


def test_receipt_cannot_omit_mask_source_even_if_state_and_version_maps_omit_it_too():
    layout, timeline = mask_return_documents()
    returned = timeline["actions"][-1]
    receipt = returned["return_hierarchy_receipt"]
    receipt["hierarchy_basis"]["placements"][:] = [
        p for p in receipt["hierarchy_basis"]["placements"] if p["object_id"] != "mask-source"]
    roots = sorted((p for p in receipt["hierarchy_basis"]["placements"] if p["parent_id"] is None),
                   key=lambda p: p["sibling_ordinal"])
    for ordinal, item in enumerate(roots):
        item["sibling_ordinal"] = ordinal
    for field in ("expected_object_states", "expected_object_state_versions"):
        returned["action"][field].pop("mask-source")
    rehash_receipt(receipt)
    ResolvedVisualTimelineV2.model_validate(timeline)
    with pytest.raises(V2FrameError, match="exact layout board inventory"):
        evaluate_frame(layout, timeline, 7000)


def test_empty_ungrouped_shell_is_in_retained_receipt_and_keeps_its_version():
    layout, timeline = group_return_documents()
    _, clock = private_clock(layout, timeline)
    sample = clock.before_action("return-1")
    assert sample.hierarchy.children("board-main", "object-group") == ()
    receipt = timeline["actions"][-1]["return_hierarchy_receipt"]
    assert "object-group" in {p["object_id"] for p in receipt["hierarchy_basis"]["placements"]}
    assert sample.object("object-group").state == "ungrouped"
    assert dict(sample.state_versions)["object-group"] == dict(clock.at(7001).state_versions)["object-group"]
