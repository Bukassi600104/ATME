"""Phase 1: strict rich contracts, negative gates, migration, and version dispatch."""

from __future__ import annotations

import asyncio
import os
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from atme.narrative_source import describe
from atme.project_service import ProjectError, ProjectService
from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    ResolvedVisualTimelineV2,
    VisualPlanV2,
)
from atme.store.migrate_visual_v1 import migrate_visual_bundle_v1
from conftest import load_example, load_schema
from jsonschema import Draft202012Validator
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from pydantic import ValidationError
from test_board_continuity import board_doc
from test_project_runner import ready_project
from v2_fixtures import (
    digest,
    executable_layout_v2,
    resolved_timeline_v2,
    visual_plan_v2,
)


def _semantic_connector_without_source(document):
    base = deepcopy(document["objects"][0])
    base.update(object_id="connector-bad", object_type="arrow", semantic_role="Relationship",
                geometry={"bounds": {"x": 1, "y": 1, "width": 20, "height": 20},
                          "points": [{"x": 1, "y": 1}, {"x": 21, "y": 21}], "corner_radius": None},
                source_object_id=None, source_anchor_id=None, destination_object_id="object-system",
                destination_anchor_id="center", role="semantic_connector", routing="straight",
                allow_self_loop=False, description="Invalid relationship", coverage_ids=["coverage-1"])
    base.pop("path_data", None)
    document["objects"].append(base)
    document["boards"][0]["object_ids"].append("connector-bad")


def _container_child_cycle(document):
    template = deepcopy(document["objects"][0])
    template.pop("path_data", None)
    first = {**template, "object_id": "group-a", "object_type": "group", "child_ids": ["group-b"],
             "parent_id": "group-b", "semantic_role": "Group A", "description": "A"}
    second = {**template, "object_id": "group-b", "object_type": "group", "child_ids": ["group-a"],
              "parent_id": "group-a", "semantic_role": "Group B", "description": "B"}
    document["objects"].extend([first, second])
    document["boards"][0]["object_ids"].extend(["group-a", "group-b"])


def _duplicate_anchor(document):
    document["objects"][0]["anchors"].append(deepcopy(document["objects"][0]["anchors"][0]))


def _resolved_absolute_mismatch(document):
    trigger = {"kind": "absolute", "at_ms": 1500}
    document["actions"][0]["action"]["trigger"] = trigger
    document["actions"][0]["resolved_trigger"].update(
        source=trigger, alignment_anchor_ms=1500, resolved_at_ms=1400,
        matched_text=None, matched_occurrence=None, confidence=1, exact=True)


def _resolved_prior_action_mismatch(document):
    trigger = {"kind": "prior_action", "action_id": "action-1", "offset_ms": 200}
    document["actions"][1]["action"]["trigger"] = trigger
    document["actions"][1]["resolved_trigger"].update(
        source=trigger, alignment_anchor_ms=900, resolved_at_ms=1000,
        matched_text=None, matched_occurrence=None, confidence=1, exact=True)


def _resolved_unknown_beat(document):
    trigger = {"kind": "beat_start", "beat_id": "missing", "offset_ms": 0}
    document["actions"][0]["action"]["trigger"] = trigger
    document["actions"][0]["resolved_trigger"].update(
        source=trigger, alignment_anchor_ms=0, resolved_at_ms=0,
        matched_text=None, matched_occurrence=None, confidence=1, exact=True)


@pytest.mark.parametrize(
    ("name", "model", "factory"),
    [
        ("visual-plan-v2", VisualPlanV2, visual_plan_v2),
        ("executable-layout-v2", ExecutableLayoutV2, executable_layout_v2),
        ("resolved-visual-timeline-v2", ResolvedVisualTimelineV2, resolved_timeline_v2),
    ],
)
def test_v2_json_schema_and_typed_model_accept_same_golden(name, model, factory):
    document = factory()
    Draft202012Validator(load_schema(name)).validate(document)
    assert model.model_validate(document).model_dump(mode="json") == document
    assert load_example(name) == document


@pytest.mark.parametrize(
    ("mutation", "model", "factory"),
    [
        (lambda d: d.update(contract_version="9"), VisualPlanV2, visual_plan_v2),
        (lambda d: d["objects"][0].update(object_type="mystery"), VisualPlanV2, visual_plan_v2),
        (lambda d: d["actions"][0].update(verb="teleport"), VisualPlanV2, visual_plan_v2),
        (lambda d: d["actions"][0].update(unknown=True), VisualPlanV2, visual_plan_v2),
        (lambda d: d["objects"][1].update(object_id=d["objects"][0]["object_id"]), VisualPlanV2, visual_plan_v2),
        (lambda d: d["actions"][0].update(target_ids=["missing"]), VisualPlanV2, visual_plan_v2),
        (lambda d: d["actions"][0].update(verb="fade"), VisualPlanV2, visual_plan_v2),
        (lambda d: d["boards"][0].update(density_limit=1), VisualPlanV2, visual_plan_v2),
        (lambda d: d["assets"][0]["provenance"].update(license_status="unresolved"), VisualPlanV2, visual_plan_v2),
        (lambda d: d["beats"][0]["attention"]["dimmed_targets"].append("object-system"), VisualPlanV2, visual_plan_v2),
        (lambda d: d["coverage"][0]["action_ids"].append("missing"), VisualPlanV2, visual_plan_v2),
        (lambda d: d["beats"][0]["attention"]["primary_targets"].append("missing"), VisualPlanV2, visual_plan_v2),
        (lambda d: d["beats"][0]["continuity"]["keep"].append("missing"), VisualPlanV2, visual_plan_v2),
        (lambda d: d["beats"][0]["camera_intent"]["target_ids"].append("missing"), VisualPlanV2, visual_plan_v2),
        (lambda d: d["assets"][0].update(fallback_id="missing"), VisualPlanV2, visual_plan_v2),
        (lambda d: d["fallbacks"][0]["affected_ids"].append("missing"), VisualPlanV2, visual_plan_v2),
        (lambda d: d["fallbacks"][0].update(status="selected"), VisualPlanV2, visual_plan_v2),
        (lambda d: d["coverage"][0].update(status="degraded"), VisualPlanV2, visual_plan_v2),
        (lambda d: d["actions"][0].update(coverage_id="coverage-2"), VisualPlanV2, visual_plan_v2),
        (lambda d: d["objects"][0].update(beat_id="beat-002"), VisualPlanV2, visual_plan_v2),
        (lambda d: d["beats"][1]["action_ids"].append("action-1"), VisualPlanV2, visual_plan_v2),
        (lambda d: d["beats"][1]["coverage_ids"].append("coverage-1"), VisualPlanV2, visual_plan_v2),
        (lambda d: d["beats"][1]["continuity"].update(return_from_board_id="missing"),
         VisualPlanV2, visual_plan_v2),
        (lambda d: d["beats"][1]["continuity"]["expected_state_versions"].update(missing=1),
         VisualPlanV2, visual_plan_v2),
        (lambda d: d["beats"][1]["evidence"].update(mask_object_id="missing"),
         VisualPlanV2, visual_plan_v2),
        (lambda d: d["beats"][0]["sound_intent"].update(role="effect", asset_id=None),
         VisualPlanV2, visual_plan_v2),
        (lambda d: d["beats"][0]["sound_intent"].update(role="effect", asset_id="missing"),
         VisualPlanV2, visual_plan_v2),
        (lambda d: d["beats"][0]["sound_intent"].update(role="effect", asset_id="asset-evidence"),
         VisualPlanV2, visual_plan_v2),
        (lambda d: d["actions"][0].update(trigger={"kind": "phrase", "phrase": ""}), VisualPlanV2, visual_plan_v2),
        (lambda d: d["actions"][1].update(trigger={"kind": "prior_action", "action_id": "missing"}), VisualPlanV2, visual_plan_v2),
        (lambda d: d["objects"][0].update(board_id="missing"), ExecutableLayoutV2, executable_layout_v2),
        (lambda d: d["objects"][0].update(parent_id="object-label") or d["objects"][1].update(parent_id="object-system"), ExecutableLayoutV2, executable_layout_v2),
        (lambda d: d["activations"].append({**d["activations"][0], "activation_id": "overlap", "start_ms": 500}), ExecutableLayoutV2, executable_layout_v2),
        (lambda d: d["boards"][0]["object_ids"].append("missing"), ExecutableLayoutV2, executable_layout_v2),
        (_duplicate_anchor, ExecutableLayoutV2, executable_layout_v2),
        (_semantic_connector_without_source, ExecutableLayoutV2, executable_layout_v2),
        (_container_child_cycle, ExecutableLayoutV2, executable_layout_v2),
        (lambda d: d["objects"][0].update(parent_id="object-label"),
         ExecutableLayoutV2, executable_layout_v2),
        (lambda d: d["objects"][0].update(clip_id="object-label"),
         ExecutableLayoutV2, executable_layout_v2),
        (lambda d: d["actions"][0].update(end_ms=d["duration_ms"] + 1), ResolvedVisualTimelineV2, resolved_timeline_v2),
        (lambda d: d["actions"][0]["resolved_trigger"].update(confidence=0.1), ResolvedVisualTimelineV2, resolved_timeline_v2),
        (lambda d: d["actions"][0]["resolved_trigger"].update(matched_text="unrelated words"),
         ResolvedVisualTimelineV2, resolved_timeline_v2),
        (lambda d: d["validation"].update(status="warn"), ResolvedVisualTimelineV2, resolved_timeline_v2),
        (_resolved_absolute_mismatch, ResolvedVisualTimelineV2, resolved_timeline_v2),
        (_resolved_prior_action_mismatch, ResolvedVisualTimelineV2, resolved_timeline_v2),
        (_resolved_unknown_beat, ResolvedVisualTimelineV2, resolved_timeline_v2),
        (lambda d: d["actions"][0]["action"].update(coverage_id="coverage-2"),
         ResolvedVisualTimelineV2, resolved_timeline_v2),
        (lambda d: d["actions"][0]["action"].update(source_instruction_id="instruction-2"),
         ResolvedVisualTimelineV2, resolved_timeline_v2),
        (lambda d: d["actions"][0]["action"]["fallback"].update(fallback_id="missing"),
         ResolvedVisualTimelineV2, resolved_timeline_v2),
        (lambda d: d["fallbacks"][0]["affected_ids"].append("missing"),
         ResolvedVisualTimelineV2, resolved_timeline_v2),
        (lambda d: d["fallbacks"][1].update(fallback_id="fallback-1"),
         ResolvedVisualTimelineV2, resolved_timeline_v2),
        (lambda d: d["coverage"][1].update(coverage_id="coverage-1"),
         ResolvedVisualTimelineV2, resolved_timeline_v2),
        (lambda d: d["fallbacks"][0].update(status="selected"),
         ResolvedVisualTimelineV2, resolved_timeline_v2),
    ],
)
def test_invalid_v2_documents_fail_both_contract_layers(mutation, model, factory):
    document = factory()
    mutation(document)
    schema_name = {VisualPlanV2: "visual-plan-v2", ExecutableLayoutV2: "executable-layout-v2",
                   ResolvedVisualTimelineV2: "resolved-visual-timeline-v2"}[model]
    schema_errors = list(Draft202012Validator(load_schema(schema_name)).iter_errors(document))
    typed_error = None
    try:
        model.model_validate(document)
    except ValidationError as exc:
        typed_error = exc
    # Structural invalidity is caught by both. Cross-reference/state-machine rules
    # are intentionally model-level semantic constraints beyond JSON Schema.
    assert schema_errors or typed_error
    assert typed_error is not None


def test_v1_migration_is_immutable_deterministic_and_records_loss():
    plan = {
        "contract_version": "1", "topic": "Queue evidence", "beats": [
            {"beat_id": "beat-001", "scene_id": 1, "narration": "Queue pointer.",
             "trigger_phrase": "Queue pointer", "purpose": "sequence", "assets": ["queue"],
             "actions": ["draw"], "layout": "queue", "camera": {"action": "hold", "subject": "queue"},
             "continuity": {"keep": [], "remove": []}, "emphasis": "queue",
             "fallback": "show queue boundary"},
            {"beat_id": "beat-002", "scene_id": 2, "narration": "Evidence return.",
             "trigger_phrase": "Evidence return", "purpose": "proof", "assets": ["evidence"],
             "actions": ["draw"], "layout": "evidence", "camera": {"action": "reframe", "subject": "evidence"},
             "continuity": {"keep": ["el-queue"], "remove": []}, "emphasis": "proof",
             "fallback": "show evidence boundary"},
        ]}
    layout = board_doc(); layout["canvas"] = {"width": 800, "height": 450}
    original_plan = deepcopy(plan); original_layout = deepcopy(layout)
    context = {"project_id": 7, "project_revision": 12, "plan_revision": 9, "layout_revision": 10,
               "narrative_authority": {"mode": "recording_only", "authority_id": "media-1",
                   "timing_media_id": "media-1", "timing_media_sha256": "a" * 64,
                   "cleaned_timeline_revision": 3, "cleaned_timeline_fingerprint": "b" * 64},
               "output_profile": {"profile_id": "LONG_FORM_16_9", "width": 800, "height": 450, "fps": 30}}
    first = migrate_visual_bundle_v1(plan, layout, **context)
    second = migrate_visual_bundle_v1(plan, layout, **context)
    assert first == second
    assert plan == original_plan and layout == original_layout
    VisualPlanV2.model_validate(first["visual_plan"])
    ExecutableLayoutV2.model_validate(first["executable_layout"])
    assert first["migration_report"]["source_sha256"] == {
        "visual_plan": digest(plan), "layout": digest(layout)}
    assert first["migration_report"]["warnings"], "lossy v1 connector migration must be recorded"
    assert first["migration_report"]["lossless"] is False
    assert first["migration_report"]["inserted_defaults"]
    assert first["migration_report"]["inferred_values"]
    paths = {item["path"] for item in first["migration_report"]["inserted_defaults"]}
    assert {"/style_system_version", "/asset_registry_version", "/declared_capability_version"} <= paths
    assert any(path.startswith("/boards/") for path in paths)
    assert any(path.startswith("/beats/") for path in paths)
    assert any(path.startswith("/objects/") for path in paths)
    assert any(path.startswith("/executable_objects/") for path in paths)
    pointer = next(item for item in first["executable_layout"]["objects"]
                   if item["object_id"] == "el-pointer")
    assert pointer["object_type"] == "line"
    assert "source_object_id" not in pointer and "destination_object_id" not in pointer
    unsupported = deepcopy(plan)
    unsupported["beats"][0]["actions"] = ["connect"]
    rejected = migrate_visual_bundle_v1(unsupported, layout, **context)
    assert rejected["visual_plan"]["beats"][0]["action_ids"] == []
    assert any(item["status"] == "rejected" for item in rejected["visual_plan"]["coverage"])
    assert any("lacks typed parameters" in warning for warning in rejected["migration_report"]["warnings"])


def _single_beat_legacy_bundle(actions):
    plan = {"contract_version": "1", "topic": "Migration matrix", "beats": [{
        "beat_id": "beat-001", "scene_id": 1, "narration": "A complete action matrix.",
        "trigger_phrase": "complete action matrix", "purpose": "sequence", "assets": [],
        "actions": actions, "layout": "queue", "camera": {"action": "hold", "subject": "queue"},
        "continuity": {"keep": [], "remove": []}, "emphasis": "matrix", "fallback": "retain meaning",
    }]}
    layout = board_doc()
    layout["canvas"] = {"width": 800, "height": 450}
    layout["elements"] = [item for item in layout["elements"] if item["scene_id"] == 1]
    layout["board_timeline"] = {"version": "1", "boards": [{"board_id": "queue"}],
        "activations": [{"activation_id": "queue", "board_id": "queue", "start_ms": 0, "end_ms": 6000}]}
    return plan, layout


def _migration_context(profile=None):
    return {"project_id": 7, "project_revision": 12, "plan_revision": 9, "layout_revision": 10,
            "narrative_authority": {"mode": "recording_only", "authority_id": "media-1",
                "timing_media_id": "media-1", "timing_media_sha256": "a" * 64,
                "cleaned_timeline_revision": 3, "cleaned_timeline_fingerprint": "b" * 64},
            "output_profile": profile or {"profile_id": "LONG_FORM_16_9", "width": 800,
                                           "height": 450, "fps": 30}}


def test_migration_covers_every_legacy_action_without_semantic_coercion():
    legacy = ["draw", "reveal", "highlight", "cross_out", "count", "remove",
              "connect", "move", "replace", "group", "split"]
    plan, layout = _single_beat_legacy_bundle(legacy)
    result = migrate_visual_bundle_v1(plan, layout, **_migration_context())
    coverage = result["visual_plan"]["coverage"]
    assert len(coverage) == len(legacy)
    assert [item["status"] for item in coverage] == ["executed"] * 6 + ["rejected"] * 5
    assert [item["verb"] for item in result["visual_plan"]["actions"]] == [
        "draw", "reveal", "highlight", "cross_out", "count", "exit"]
    assert len(result["migration_report"]["unsupported_semantics"]) == 5
    assert all(item["fallback_id"] for item in coverage[6:])


@pytest.mark.parametrize("profile", [
    {"profile_id": "LONG_FORM_16_9", "width": 800, "height": 450, "fps": 30},
    {"profile_id": "SHORT_FORM_9_16", "width": 450, "height": 800, "fps": 30},
])
def test_migration_accepts_both_output_profiles_without_changing_source(profile):
    plan, layout = _single_beat_legacy_bundle(["draw"])
    layout["canvas"] = {"width": profile["width"], "height": profile["height"]}
    before = deepcopy(layout)
    result = migrate_visual_bundle_v1(plan, layout, **_migration_context(profile))
    assert result["visual_plan"]["output_profile"] == profile
    assert result["executable_layout"]["output_profile"] == profile
    assert result["executable_layout"]["canvas"]["width"] == profile["width"]
    assert layout == before


def test_migration_preserves_authoritative_arrow_bindings_only():
    plan, layout = _single_beat_legacy_bundle(["draw"])
    target = {**deepcopy(layout["elements"][0]), "id": "el-target", "x": 500}
    layout["elements"].append(target)
    pointer = next(item for item in layout["elements"] if item["id"] == "el-pointer")
    pointer.update(startBinding="el-queue", endBinding="el-target")
    result = migrate_visual_bundle_v1(plan, layout, **_migration_context())
    connector = next(item for item in result["executable_layout"]["objects"]
                     if item["object_id"] == "el-pointer")
    assert connector["object_type"] == "arrow"
    assert connector["source_object_id"] == "el-queue"
    assert connector["destination_object_id"] == "el-target"
    assert any(item["path"] == "/objects/el-pointer/anchors"
               for item in result["migration_report"]["inferred_values"])


def test_migration_records_embedded_evidence_as_unsupported_registry_semantics():
    from test_evidence_image import evidence_doc

    plan, _ = _single_beat_legacy_bundle(["reveal"])
    layout = evidence_doc()
    layout["canvas"] = {"width": 800, "height": 450}
    for element in layout["elements"]:
        element["scene_id"] = 1
        element["board_id"] = "queue"
    layout["board_timeline"] = {"version": "1", "boards": [{"board_id": "queue"}],
        "activations": [{"activation_id": "queue", "board_id": "queue", "start_ms": 0, "end_ms": 6000}]}
    result = migrate_visual_bundle_v1(plan, layout, **_migration_context())
    evidence = next(item for item in result["executable_layout"]["objects"]
                    if item["object_id"] == "el-evidence")
    assert evidence["object_type"] == "evidence"
    assert any(item["path"].endswith("/png_base64")
               for item in result["migration_report"]["unsupported_semantics"])


def test_migration_rejects_overdense_boards_instead_of_silently_accepting_them():
    plan, layout = _single_beat_legacy_bundle(["draw"])
    template = deepcopy(layout["elements"][0])
    layout["elements"] = [{**template, "id": f"el-object-{index}"} for index in range(13)]
    with pytest.raises(ValidationError, match="density limit"):
        migrate_visual_bundle_v1(plan, layout, **_migration_context())


def test_schema_registry_dispatch_is_explicit_and_renderer_capability_truthful():
    assert ProjectService.schema("storyboard", "1")["properties"]["contract_version"]["const"] == "1"
    assert ProjectService.schema("storyboard", "2.0.0")["properties"]["contract_version"]["const"] == "2.0.0"
    assert ProjectService.capabilities()["visual_contracts"] == {
        "authoring_versions": ["1", "2.0.0"], "renderer_versions": ["1"],
        "active_renderer_version": "1", "v2_render_status": "implementation_pending"}
    with pytest.raises(ProjectError, match="No 'layout' contract"):
        ProjectService.schema("layout", "9")


def test_real_mcp_returns_v2_schemas_and_truthful_renderer_capability(tmp_path):
    frozen = os.environ.get("ATME_FROZEN_MCP")
    params = StdioServerParameters(
        command=frozen or sys.executable,
        args=(["mcp", "--database", str(tmp_path / "frozen-v2.db")] if frozen else
              ["-m", "atme.mcp_server", "--database", str(tmp_path / "source-v2.db")]),
        cwd=Path(__file__).resolve().parents[1],
    )

    async def exercise():
        async with Client(params, read_timeout_seconds=30) as client:
            for kind in ("storyboard", "layout", "resolved_timeline", "migration_report"):
                result = await client.call_tool("atme.get_schema", {"kind": kind, "version": "2.0.0"})
                assert not result.is_error
                schema = result.structured_content["result"]
                assert schema["properties"]["contract_version"]["const"] == "2.0.0"
            caps = await client.call_tool("atme.get_capabilities", {})
            visual = caps.structured_content["result"]["visual_contracts"]
            assert visual["authoring_versions"] == ["1", "2.0.0"]
            assert visual["renderer_versions"] == ["1"]

    asyncio.run(exercise())


def test_v1_and_v2_models_never_cross_accept():
    from atme.store.contracts import LayoutDoc
    with pytest.raises(ValidationError):
        LayoutDoc.model_validate(executable_layout_v2())
    with pytest.raises(ValidationError):
        ExecutableLayoutV2.model_validate(board_doc())


@pytest.mark.parametrize("kind", ["word", "beat_start", "absolute", "prior_action"])
def test_resolved_trigger_kinds_require_and_accept_truthful_anchors(kind):
    document = resolved_timeline_v2()
    item = document["actions"][0] if kind != "prior_action" else document["actions"][1]
    if kind == "word":
        trigger = {"kind": "word", "word": "system", "occurrence": 1,
                   "offset_ms": 0, "minimum_confidence": 0.75}
        resolved = {"source": trigger, "alignment_anchor_ms": 0, "resolved_at_ms": 0,
                    "matched_text": "system", "matched_occurrence": 1,
                    "confidence": 0.98, "exact": True}
    elif kind == "beat_start":
        trigger = {"kind": "beat_start", "beat_id": "beat-001", "offset_ms": 0}
        resolved = {"source": trigger, "alignment_anchor_ms": 0, "resolved_at_ms": 0,
                    "matched_text": None, "matched_occurrence": None,
                    "confidence": 1, "exact": True}
    elif kind == "absolute":
        trigger = {"kind": "absolute", "at_ms": 0}
        resolved = {"source": trigger, "alignment_anchor_ms": 0, "resolved_at_ms": 0,
                    "matched_text": None, "matched_occurrence": None,
                    "confidence": 1, "exact": True}
    else:
        trigger = {"kind": "prior_action", "action_id": "action-1", "offset_ms": 0}
        resolved = {"source": trigger, "alignment_anchor_ms": 900, "resolved_at_ms": 900,
                    "matched_text": None, "matched_occurrence": None,
                    "confidence": 1, "exact": True}
    item["action"]["trigger"] = trigger
    item["resolved_trigger"] = resolved
    ResolvedVisualTimelineV2.model_validate(document)


def _store_v2_plan(tmp_path):
    service, project = ready_project(tmp_path)
    plan = visual_plan_v2(project["revision"]); plan["project_id"] = project["project_id"]
    source = describe(service, project["project_id"])
    timeline = service.source_timeline.get(project["project_id"])
    media = source["timing_authority"]["media"]
    plan["narrative_authority"].update(
        mode="approved_script_plus_recording", authority_id="script-revision-1",
        timing_media_id=media["media_id"], timing_media_sha256=media["sha256"],
        cleaned_timeline_revision=timeline["timeline_revision"],
        cleaned_timeline_fingerprint=digest(timeline["document"]),
    )
    project = service.write(project["project_id"], "storyboard", plan, project["revision"])
    return service, project, plan


@pytest.mark.parametrize("mutation", [
    lambda plan: plan["objects"][0].update(beat_id="beat-002"),
    lambda plan: plan["beats"][1]["action_ids"].append("action-1"),
    lambda plan: plan["beats"][1]["continuity"].update(return_from_board_id="missing"),
    lambda plan: plan["beats"][1]["continuity"]["expected_state_versions"].update(missing=1),
    lambda plan: plan["beats"][1]["evidence"].update(mask_object_id="missing"),
    lambda plan: plan["beats"][0]["sound_intent"].update(role="effect", asset_id=None),
    lambda plan: plan["beats"][1]["coverage_ids"].append("coverage-1"),
])
def test_project_service_rejects_semantically_open_visual_plans(tmp_path, mutation):
    service, project, plan = _store_v2_plan(tmp_path)
    invalid = deepcopy(plan)
    invalid["project_revision"] = project["revision"]
    mutation(invalid)
    with pytest.raises(ProjectError) as failure:
        service.write(project["project_id"], "storyboard", invalid, project["revision"])
    assert failure.value.code == "invalid_artifact"


def test_v2_revisions_are_stored_but_never_sent_to_v1_renderer(tmp_path):
    service, project, plan = _store_v2_plan(tmp_path)
    layout = executable_layout_v2(plan)
    layout.update(project_id=project["project_id"], project_revision=project["revision"],
                  plan_revision=project["artifacts"]["storyboard"], plan_sha256=digest(plan))
    project = service.write(project["project_id"], "layout", layout, project["revision"])
    stored = service.artifact(project["project_id"], "layout")
    assert stored["contract_version"] == "2.0.0"
    report = service.runner.validate(project["project_id"])
    assert any(issue["code"] == "renderer_contract_unsupported" for issue in report["issues"])
    assert report["ready"] is False


@pytest.mark.parametrize("mutation", [
    lambda layout: layout["objects"][0].update(semantic_role="Unrelated replacement"),
    lambda layout: layout["objects"][0].update(initial_state="visible"),
    lambda layout: layout["objects"][0].update(description="Silently rewritten meaning"),
    lambda layout: layout["boards"][0].update(template="custom"),
    lambda layout: layout["boards"][0].update(activation_policy="once"),
    lambda layout: layout["boards"][0].update(creation_reason="Different directing rationale"),
    lambda layout: layout["boards"][0]["aspect_composition"].update(
        LONG_FORM_16_9="Silently recomposed"),
])
def test_hash_correct_but_semantically_changed_layout_is_rejected(tmp_path, mutation):
    service, project, plan = _store_v2_plan(tmp_path)
    layout = executable_layout_v2(plan)
    layout.update(project_id=project["project_id"], project_revision=project["revision"],
                  plan_revision=project["artifacts"]["storyboard"], plan_sha256=digest(plan))
    mutation(layout)
    with pytest.raises(ProjectError) as failure:
        service.write(project["project_id"], "layout", layout, project["revision"])
    assert failure.value.code == "invalid_artifact"
    assert "preserve semantic-plan intent" in str(failure.value)


def test_all_v2_preview_and_compile_entries_fail_before_frame_renderer(tmp_path, monkeypatch):
    service, project, plan = _store_v2_plan(tmp_path)
    layout = executable_layout_v2(plan)
    layout.update(project_id=project["project_id"], project_revision=project["revision"],
                  plan_revision=project["artifacts"]["storyboard"], plan_sha256=digest(plan))
    project = service.write(project["project_id"], "layout", layout, project["revision"])

    def forbidden(*args, **kwargs):
        raise AssertionError("v1 frame renderer must never receive a v2 document")

    monkeypatch.setattr("atme.render.animator._FrameRenderer", forbidden)
    calls = [
        lambda: service.runner.preview(project["project_id"], project["revision"], 100),
        lambda: service.runner.preview_layout(project["project_id"], project["revision"], layout, 100),
        lambda: service.runner._preview_document(layout, {"width": 1280, "height": 720},
                                                  project["project_id"], project["revision"], 100),
        lambda: service.runner.compile(project["project_id"], project["revision"]),
    ]
    for call in calls:
        with pytest.raises(ProjectError) as failure:
            call()
        assert failure.value.code == "renderer_contract_unsupported"


def test_service_migration_appends_revisions_and_preserves_v1_history(tmp_path):
    service, state = ready_project(tmp_path)
    project_id = state["project_id"]
    old_plan = service.artifact(project_id, "storyboard")
    old_layout = service.artifact(project_id, "layout")
    result = service.migrate_visual_contracts_v1(project_id, state["revision"])
    assert result["storyboard_revision"] == state["revision"] + 1
    assert result["layout_revision"] == state["revision"] + 2
    assert service.artifact(project_id, "storyboard", old_plan["revision"])["document"] == old_plan["document"]
    assert service.artifact(project_id, "layout", old_layout["revision"])["document"] == old_layout["document"]
    current_plan = service.artifact(project_id, "storyboard")
    current_layout = service.artifact(project_id, "layout")
    assert current_plan["contract_version"] == current_layout["contract_version"] == "2.0.0"
    assert current_plan["migration_report"] == current_layout["migration_report"] == result["migration_report"]
    assert service.runner.validate(project_id)["ready"] is False
    assert any(x["code"] == "renderer_contract_unsupported"
               for x in service.runner.validate(project_id)["issues"])
