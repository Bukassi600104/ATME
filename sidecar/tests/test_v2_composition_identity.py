"""Initial expansion identity coexists with sampled Count/Morph/hierarchy content."""
import json
from dataclasses import replace

import pytest
from atme.render.v2_split_identity import split_content_receipts
from atme.store import contracts_v2 as contracts
from test_v2_composition_attachment import composition_project_documents
from test_v2_split_identity import sample_for_layout


def bound_identity():
    _plan, document = composition_project_documents()
    layout = contracts.ExecutableLayoutV2.model_validate(document)
    sample = sample_for_layout(layout)
    return layout, sample


def test_bound_content_retains_canonical_immutable_receipt_without_nil_template_fields():
    layout, sample = bound_identity()
    root = layout.objects[0]
    rows = {row.object_id: row for row in split_content_receipts(layout, sample, {})}
    assert json.loads(rows[root.object_id].canonical_json)["composition_binding"] == root.composition_binding.model_dump(mode="json")
    assert all("composition_binding" not in obj for obj in
               json.loads(rows[root.object_id].canonical_json)["composition_binding"]["instance"]["definition"]["objects"])


@pytest.mark.parametrize("defect", ["unknown", "subclass", "null_template_binding", "false_receipt"])
def test_bypass_constructed_nested_binding_cannot_be_laundered_by_serialization(defect):
    layout, sample = bound_identity()
    root = layout.objects[0]
    binding = root.composition_binding
    if defect == "unknown":
        binding.instance.definition.objects[1].__dict__["unrecognized"] = "must reject"
    elif defect == "subclass":
        class UnknownBinding(contracts.CompositionBinding):
            pass
        root.composition_binding = UnknownBinding.model_construct(**binding.__dict__)
    elif defect == "null_template_binding":
        prototype = binding.instance.definition.objects[0]
        prototype.model_fields_set.add("composition_binding")
    else:
        binding.expansion_sha256 = "0" * 64
    with pytest.raises(ValueError):
        split_content_receipts(layout, sample, {})


def test_sampled_hierarchy_is_not_frozen_to_the_initial_expansion_receipt():
    layout, sample = bound_identity()
    root, _mark, label = layout.objects
    before = {row.object_id: row for row in split_content_receipts(layout, sample, {})}
    # Group/current hierarchy actions remain an independent mutable channel.
    changed = replace(sample, hierarchy=type(sample.hierarchy)(tuple(
        replace(node, parent_id=None, sibling_ordinal=1) if node.object_id == label.object_id else node
        for node in sample.hierarchy.nodes)))
    after = {row.object_id: row for row in split_content_receipts(layout, changed, {})}
    assert after[root.object_id] != before[root.object_id]
    assert after[label.object_id] == before[label.object_id]
    assert json.loads(after[root.object_id].canonical_json)["composition_binding"] == root.composition_binding.model_dump(mode="json")
    raw = root.model_dump(mode="json")
    raw["child_ids"] = raw["child_ids"][:1]
    contracts.GroupContainer.model_validate(raw)  # Current object, not initial Layout validation.
