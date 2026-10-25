"""Bindings survive real immutable writes/duplicates; bare history stays legacy."""
import json
from copy import deepcopy

import pytest
from atme.project_service import ProjectError
from atme.store import contracts_v2 as contracts
from jsonschema import Draft202012Validator, ValidationError
from test_v2_composition_attachment import composition_project_documents
from test_v2_registry_project import history
from test_v2_resolved_project import stored_v2_basis
from v2_fixtures import digest


def stored_composition_basis(tmp_path, *, portrait=False):
    profile = "SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9"
    service, project, original_plan, _, _ = stored_v2_basis(tmp_path, profile=profile)
    plan, layout = composition_project_documents()
    plan.update(project_id=project["project_id"], project_revision=project["revision"],
                output_profile=deepcopy(original_plan["output_profile"]),
                narrative_authority=deepcopy(original_plan["narrative_authority"]))
    project = service.write(project["project_id"], "storyboard", plan, project["revision"])
    layout.update(project_id=project["project_id"], project_revision=project["revision"],
                  output_profile=deepcopy(plan["output_profile"]),
                  plan_revision=project["artifacts"]["storyboard"], plan_sha256=digest(plan))
    layout["canvas"].update(width=plan["output_profile"]["width"], height=plan["output_profile"]["height"])
    project = service.write(project["project_id"], "layout", layout, project["revision"])
    return service, project, plan, layout


@pytest.mark.parametrize("portrait", [False, True])
def test_bound_project_duplicate_preserves_every_member_receipt_authority_and_history(tmp_path, portrait):
    service, project, plan, layout = stored_composition_basis(tmp_path, portrait=portrait)
    try:
        pid = project["project_id"]
        before = history(service, pid)
        duplicate = service.duplicate(pid)
        copied = {}
        for kind, authored in (("storyboard", plan), ("layout", layout)):
            assert service.artifact(pid, kind)["document"] == authored
            row = service.artifact(duplicate["project_id"], kind)
            copied[kind] = row["document"]
            assert copied[kind]["objects"] == authored["objects"]
            assert row["duplicate_derivation"]["source_sha256"] == digest(authored)
            assert row["duplicate_derivation"]["copied_sha256"] == digest(copied[kind])
        assert copied["layout"]["plan_sha256"] == digest(copied["storyboard"])
        assert copied["storyboard"]["narrative_authority"] == plan["narrative_authority"]
        contracts.validate_plan_layout(copied["storyboard"], copied["layout"])
        assert history(service, pid) == before
    finally:
        service.store.close()


@pytest.mark.parametrize("fault", ["missing_binding", "changed_member", "false_root_order"])
def test_invalid_bound_layout_write_preserves_project_and_source_history(tmp_path, fault):
    service, project, _plan, layout = stored_composition_basis(tmp_path)
    try:
        from test_v2_composition_binding import rehash_binding

        pid = project["project_id"]
        candidate = deepcopy(layout)
        candidate["project_revision"] = project["revision"]
        if fault == "missing_binding":
            candidate["objects"][0].pop("composition_binding")
        elif fault == "changed_member":
            candidate["objects"][1]["geometry"]["bounds"]["width"] += 1
        else:
            binding = candidate["objects"][0]["composition_binding"]
            next(row for row in binding["members"] if row["object_id"] == candidate["objects"][0]["object_id"])["sibling_ordinal"] = 1
            rehash_binding(binding)
        before = deepcopy((service.open(pid), history(service, pid), service.source_timeline.get(pid)))
        original = deepcopy(candidate)
        with pytest.raises(ProjectError) as failure:
            service.write(pid, "layout", candidate, project["revision"])
        assert failure.value.code == "invalid_artifact"
        assert candidate == original
        assert (service.open(pid), history(service, pid), service.source_timeline.get(pid)) == before
    finally:
        service.store.close()


def bare_legacy_documents():
    plan, layout = composition_project_documents(attach=False)
    plan["objects"][0].update(object_type="instance")
    plan["objects"][0].pop("child_ids")
    layout["objects"][0].update(object_type="instance", variant=None)
    layout["objects"][0].pop("child_ids")
    for obj in layout["objects"][1:]:
        obj["parent_id"] = None
    layout["plan_sha256"] = digest(plan)
    return plan, layout


def test_bare_legacy_wire_is_loadable_but_never_a_new_composition_write(tmp_path):
    plan, layout = bare_legacy_documents()
    contracts.validate_plan_layout(plan, layout, require_code_payloads=False)
    assert contracts.VisualPlanV2.model_validate(plan).model_dump(mode="json")["objects"] == plan["objects"]
    assert contracts.ExecutableLayoutV2.model_validate(layout).model_dump(mode="json")["objects"] == layout["objects"]
    service, _project, _old_plan, _old_layout = stored_composition_basis(tmp_path)
    try:
        for kind, document in (("storyboard", plan), ("layout", layout)):
            assert json.loads(service._serialized_artifact(kind, document, legacy_migration=True)) == document
            with pytest.raises(ProjectError, match="Schema validation"):
                service._serialized_artifact(kind, document)
    finally:
        service.store.close()


def test_actual_legacy_duplicate_preserves_bare_records_without_invented_bindings(tmp_path):
    service, project, plan, layout = stored_composition_basis(tmp_path)
    try:
        pid = project["project_id"]
        legacy_plan, legacy_layout = bare_legacy_documents()
        for field in ("project_id", "project_revision", "narrative_authority", "output_profile"):
            legacy_plan[field] = deepcopy(plan[field])
        for field in ("project_id", "project_revision", "output_profile", "canvas", "plan_revision"):
            legacy_layout[field] = deepcopy(layout[field])
        legacy_layout["plan_sha256"] = digest(legacy_plan)
        for kind, document in (("storyboard", legacy_plan), ("layout", legacy_layout)):
            serialized = service._serialized_artifact(kind, document, legacy_migration=True)
            service.store.conn.execute("UPDATE project_artifact_versions SET document=? WHERE job_id=? AND kind=? AND revision=?",
                (serialized, pid, kind, project["artifacts"][kind]))
        service.store.conn.commit()
        before = history(service, pid)
        copied = service.duplicate(pid)
        for kind, original in (("storyboard", legacy_plan), ("layout", legacy_layout)):
            assert service.artifact(pid, kind)["document"] == original
            row = service.artifact(copied["project_id"], kind)
            assert row["document"]["objects"] == original["objects"]
            assert all("composition_binding" not in obj for obj in row["document"]["objects"])
            assert row["duplicate_derivation"]["source_sha256"] == digest(original)
        assert history(service, pid) == before
    finally:
        service.store.close()


@pytest.mark.parametrize("kind,model", [("storyboard", contracts.VisualPlanV2), ("layout", contracts.ExecutableLayoutV2)])
@pytest.mark.parametrize("nested", [None, {}])
def test_distributable_recursive_schema_rejects_even_null_binding_inside_definition(kind, model, nested):
    plan, layout = composition_project_documents()
    document = plan if kind == "storyboard" else layout
    schema = model.model_json_schema()
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(document)
    template = document["objects"][0]["composition_binding"]["instance"]["definition"]
    template["objects"][0]["composition_binding"] = nested
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(document)
    with pytest.raises(ValueError):
        model.model_validate(document)
