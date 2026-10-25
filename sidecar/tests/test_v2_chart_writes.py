"""Normal inline chart writes require data; immutable legacy records stay exact."""

import json
from copy import deepcopy

import pytest
from test_v2_chart_contract import chart_documents

from atme.project_service import ProjectError, ProjectService
from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    VisualPlanV2,
    validate_plan_layout,
)
from atme.store.db import JobStore


@pytest.fixture
def service(tmp_path):
    core = ProjectService(JobStore(tmp_path / "chart-write.db"))
    yield core
    core.store.close()


def legacy_documents(*, explicit_null=False):
    plan, layout = chart_documents()
    for document in (plan, layout):
        chart = document["objects"][0]
        chart.pop("chart_payload")
        if explicit_null:
            chart["chart_payload"] = None
    return plan, layout


@pytest.mark.parametrize("explicit_null", [False, True])
def test_new_inline_chart_layout_without_authored_data_rejects(service, explicit_null):
    document = legacy_documents(explicit_null=explicit_null)[1]
    original = deepcopy(document)
    with pytest.raises(ProjectError) as failure:
        service._serialized_artifact("layout", document)
    assert failure.value.code == "invalid_artifact"
    assert "chart_payload" in str(failure.value.errors)
    assert document == original


@pytest.mark.parametrize("explicit_null", [False, True])
def test_semantic_chart_without_data_defers_custom_art_classification_to_layout(service, explicit_null):
    plan, _ = legacy_documents(explicit_null=explicit_null)
    original = deepcopy(plan)
    # SemanticStandardObjectSpec has no variant: a bare semantic declaration
    # must remain usable by the already-supported custom external art path.
    assert json.loads(service._serialized_artifact("storyboard", plan)) == original


@pytest.mark.parametrize("explicit_null", [False, True])
def test_pair_validation_cannot_treat_missing_inline_data_as_matching_semantics(explicit_null):
    plan, layout = legacy_documents(explicit_null=explicit_null)
    with pytest.raises(ValueError, match="chart_payload"):
        validate_plan_layout(plan, layout)


@pytest.mark.parametrize("kind,index,model", [("storyboard", 0, VisualPlanV2),
                                            ("layout", 1, ExecutableLayoutV2)])
def test_immutable_bare_chart_records_still_parse_and_serialize_without_rewrite(service, kind, index, model):
    document = legacy_documents()[index]
    original = deepcopy(document)
    assert model.model_validate(document).model_dump(mode="json") == document
    assert json.loads(service._serialized_artifact(kind, document, legacy_migration=True)) == original
    assert document == original


def test_trusted_immutable_pair_validation_retains_bare_chart_history():
    plan, layout = legacy_documents()
    original = deepcopy((plan, layout))
    validate_plan_layout(plan, layout, require_code_payloads=False)
    assert (plan, layout) == original


@pytest.mark.parametrize("chart_kind", ["bars", "line"])
def test_complete_inline_data_is_preserved_by_normal_write_and_pair_validation(service, chart_kind):
    plan, layout = chart_documents(chart_kind)
    original = deepcopy((plan, layout))
    for kind, document in (("storyboard", plan), ("layout", layout)):
        assert json.loads(service._serialized_artifact(kind, document)) == document
    validate_plan_layout(plan, layout)
    assert (plan, layout) == original


@pytest.mark.parametrize("bound", [False, True])
def test_authenticated_static_chart_art_stays_separate_from_inline_data(service, bound):
    plan, layout = legacy_documents()
    chart = layout["objects"][0]
    chart.update(variant="chart-bars", anchors=[])
    if bound:
        binding = {"version": "1.0.0", "asset_id": "chart-bars", "anchor_mappings": [
            {"placed_anchor_id": "center", "registry_anchor_name": "center"}]}
        plan["objects"][0]["registry_binding"] = deepcopy(binding)
        chart["registry_binding"] = deepcopy(binding)
        chart["anchors"] = [{"anchor_id": "center", "point": {"x": .5, "y": .5}}]
    original = deepcopy((plan, layout))
    for kind, document in (("storyboard", plan), ("layout", layout)):
        assert json.loads(service._serialized_artifact(kind, document)) == document
    validate_plan_layout(plan, layout)
    assert (plan, layout) == original


def test_custom_external_chart_variant_keeps_its_existing_nonregistry_write_path(service):
    plan, layout = legacy_documents()
    layout["objects"][0]["variant"] = "custom-external-illustration"
    original = deepcopy((plan, layout))
    for kind, document in (("storyboard", plan), ("layout", layout)):
        assert json.loads(service._serialized_artifact(kind, document)) == document
    validate_plan_layout(plan, layout)
    assert (plan, layout) == original
