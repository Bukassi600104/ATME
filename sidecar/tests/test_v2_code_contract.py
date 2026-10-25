"""Exact externally authored code: strict payloads, legacy shape and identity."""

import json
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256

import pytest
from atme.render.v2_split_identity import split_content_receipts
from atme.store import contracts_v2 as contracts
from conftest import load_schema
from jsonschema import Draft202012Validator
from test_v2_split_identity import identity_sample, sample_for_layout
from v2_fixtures import digest, executable_layout_v2, visual_plan_v2


def authored_payload(mode="plain"):
    lines = [{"line_id": "line-1", "spans": [
        {"span_id": "span-1", "role": "plain", "text": "\tx = 'Ω'  "}]},
        {"line_id": "line-2", "spans": []}]
    if mode == "tokens":
        lines[0]["spans"] = [
            {"span_id": "span-tab", "role": "plain", "text": "\t"},
            {"span_id": "span-name", "role": "identifier", "text": "x"},
            {"span_id": "span-op", "role": "operator", "text": " = "},
            {"span_id": "span-value", "role": "literal", "text": "'Ω'"},
            {"span_id": "span-space", "role": "plain", "text": "  "}]
    return {"version": "1.0.0", "font_system_id": "atme-code-font-v1", "mode": mode,
            "tab_size": 4, "lines": lines}


def code_object(mode="plain", *, payload=True):
    layout, _ = identity_sample()
    raw = layout.objects[0].model_dump(mode="json")
    raw.pop("path_data", None)
    raw.update(object_type="code", text="\tx = 'Ω'  \n", items=[])
    if payload:
        raw["code_payload"] = authored_payload(mode)
    return raw


def payload_type():
    assert hasattr(contracts, "CodePayload"), "strict authored code payload is missing"
    return contracts.CodePayload


@pytest.mark.parametrize("mode", ["plain", "tokens"])
@pytest.mark.parametrize("tab_size", [2, 4, 8])
def test_exact_authored_lines_spans_tabs_trailing_spaces_and_blank_line(mode, tab_size):
    raw = code_object(mode)
    raw["code_payload"]["tab_size"] = tab_size
    obj = contracts.TextObject.model_validate(raw)
    assert obj.model_dump(mode="json") == raw
    assert "\n".join("".join(span.text for span in line.spans)
                     for line in obj.code_payload.lines) == obj.text
    assert obj.code_payload.font_system_id == "atme-code-font-v1"
    assert obj.code_payload.lines[-1].spans == []


@pytest.mark.parametrize("mutation", [
    "version", "font", "mode", "tab_size", "missing_tab", "empty_lines", "duplicate_line",
    "duplicate_span", "blank_line_id", "blank_span_id", "unknown_role", "empty_span",
    "extra", "plain_many_spans", "plain_token_role", "plain_extra_empty_span",
])
def test_strict_code_payload_rejects_ambiguous_or_inferred_semantics(mutation):
    raw = authored_payload()
    line = raw["lines"][0]
    span = line["spans"][0]
    if mutation in {"version", "mode", "tab_size"}:
        raw[mutation] = {"version": "2.0.0", "mode": "auto", "tab_size": 3}[mutation]
    elif mutation == "font":
        raw["font_system_id"] = "atme-style-v2"
    elif mutation == "missing_tab":
        raw.pop("tab_size")
    elif mutation == "empty_lines":
        raw["lines"] = []
    elif mutation == "duplicate_line":
        raw["lines"][1]["line_id"] = line["line_id"]
    elif mutation == "duplicate_span":
        raw["lines"][1]["spans"] = [deepcopy(span)]
    elif mutation == "blank_line_id":
        line["line_id"] = " line-1 "
    elif mutation == "blank_span_id":
        span["span_id"] = " "
    elif mutation == "unknown_role":
        span["role"] = "inferred_keyword"
    elif mutation in {"empty_span", "plain_extra_empty_span"}:
        span["text"] = ""
    elif mutation == "extra":
        span["source_url"] = "https://example.com"
    elif mutation == "plain_many_spans":
        line["spans"].append({"span_id": "extra", "role": "plain", "text": "x"})
    elif mutation == "plain_token_role":
        span["role"] = "keyword"
    with pytest.raises(ValueError):
        payload_type().model_validate(raw)


@pytest.mark.parametrize("bad", ["\n", "\r", "\r\n", "\x00", "\x0f", "\x7f", "\x85",
                                  "\u2028", "\u2029", "\ud800", "\ufffe", "\uffff"])
def test_line_spans_reject_controls_other_separators_and_invalid_xml_scalars(bad):
    raw = authored_payload()
    raw["lines"][0]["spans"][0]["text"] = "x" + bad + "y"
    with pytest.raises(ValueError):
        payload_type().model_validate(raw)


@pytest.mark.parametrize("change", ["text", "missing_blank", "items", "wrong_object_type"])
def test_code_object_requires_exact_original_text_and_no_other_text_semantics(change):
    raw = code_object()
    if change == "text":
        raw["text"] = raw["text"].strip()
    elif change == "missing_blank":
        raw["code_payload"]["lines"].pop()
    elif change == "items":
        raw["items"] = ["not a code line"]
    else:
        raw["object_type"] = "text"
    with pytest.raises(ValueError):
        contracts.TextObject.model_validate(raw)


def test_legacy_text_code_and_flat_list_dumps_and_content_hashes_remain_exact():
    layout, sample = identity_sample()
    for object_type in ("text", "code", "callout", "list"):
        raw = code_object(payload=False)
        raw["object_type"] = object_type
        raw["items"] = ["One", "Two"] if object_type == "list" else []
        obj = contracts.TextObject.model_validate(raw)
        assert obj.model_dump(mode="json") == raw
        candidate = layout.model_copy(update={"objects": [
            obj if item.object_id == obj.object_id else item for item in layout.objects]})
        receipt = next(row for row in split_content_receipts(candidate, sample, {})
                       if row.object_id == obj.object_id)
        expected = {key: raw[key] for key in (
            "object_type", "geometry", "style", "anchors", "asset_id", "text", "items")}
        encoded = json.dumps(expected, sort_keys=True, separators=(",", ":"))
        assert receipt.canonical_json == encoded
        assert receipt.content_sha256 == sha256(encoded.encode()).hexdigest()


@pytest.mark.parametrize("change", ["line_id", "span_id", "role", "order", "tab_size", "text"])
def test_code_content_hash_binds_every_authored_payload_channel_not_placement(change):
    layout, _ = identity_sample()
    raw = code_object("tokens")
    obj = contracts.TextObject.model_validate(raw)
    layout = layout.model_copy(update={"objects": [
        obj if item.object_id == obj.object_id else item for item in layout.objects]})
    sample = sample_for_layout(layout)

    def receipt(candidate, frames=sample):
        return next(row for row in split_content_receipts(candidate, frames, {}) if row.object_id == obj.object_id)

    before = receipt(layout)
    expected = {key: raw[key] for key in (
        "object_type", "geometry", "style", "anchors", "asset_id", "text", "items", "code_payload")}
    assert before.content_sha256 == digest(expected)
    moved = replace(sample, state_versions=tuple((key, 7) for key, _ in sample.state_versions))
    assert receipt(layout, moved) == before
    changed = deepcopy(raw)
    line = changed["code_payload"]["lines"][0]
    if change == "line_id":
        line["line_id"] = "renamed-line"
    elif change == "span_id":
        line["spans"][0]["span_id"] = "renamed-span"
    elif change == "role":
        line["spans"][1]["role"] = "keyword"
    elif change == "order":
        changed["code_payload"]["lines"].reverse()
        changed["text"] = "\n\tx = 'Ω'  "
    elif change == "tab_size":
        changed["code_payload"]["tab_size"] = 8
    else:
        line["spans"][1]["text"] = "y"
        changed["text"] = "\ty = 'Ω'  \n"
    altered = contracts.TextObject.model_validate(changed)
    candidate = layout.model_copy(update={"objects": [
        altered if item.object_id == altered.object_id else item for item in layout.objects]})
    assert receipt(candidate).content_sha256 != before.content_sha256


def test_bypass_constructed_invalid_payload_fails_identity():
    layout, _ = identity_sample()
    raw = code_object()
    obj = contracts.TextObject.model_validate(raw)
    candidate = layout.model_copy(update={"objects": [
        obj if item.object_id == obj.object_id else item for item in layout.objects]})
    sample = sample_for_layout(candidate)
    obj.code_payload.lines[0].spans[0].__dict__["text"] = "different"
    with pytest.raises(ValueError):
        split_content_receipts(candidate, sample, {})


@pytest.mark.parametrize("level", ["payload", "line", "span"])
def test_unknown_nested_code_subclasses_fail_content_identity(level):
    layout, _ = identity_sample()
    obj = contracts.TextObject.model_validate(code_object())
    if level == "payload":
        class UnknownPayload(contracts.CodePayload):
            pass
        obj.code_payload = UnknownPayload.model_validate(obj.code_payload.model_dump(mode="json"))
    elif level == "line":
        class UnknownLine(contracts.CodeLine):
            pass
        line = obj.code_payload.lines[0]
        obj.code_payload.lines[0] = UnknownLine.model_validate(line.model_dump(mode="json"))
    else:
        class UnknownSpan(contracts.CodeSpan):
            pass
        span = obj.code_payload.lines[0].spans[0]
        obj.code_payload.lines[0].spans[0] = UnknownSpan.model_validate(span.model_dump(mode="json"))
    candidate = layout.model_copy(update={"objects": [
        obj if item.object_id == obj.object_id else item for item in layout.objects]})
    with pytest.raises(ValueError, match="unknown nested payload subclass"):
        split_content_receipts(candidate, sample_for_layout(candidate), {})


def test_code_payload_is_preserved_from_semantic_plan_and_schema_without_invention():
    plan = visual_plan_v2()
    layout = executable_layout_v2()
    payload = authored_payload("tokens")
    next(obj for obj in plan["objects"] if obj["object_id"] == "object-label").update(
        object_type="code", code_payload=payload)
    target = next(obj for obj in layout["objects"] if obj["object_id"] == "object-label")
    target.update(object_type="code", text="\tx = 'Ω'  \n", items=[], code_payload=deepcopy(payload))
    layout["plan_sha256"] = digest(plan)
    contracts.validate_plan_layout(plan, layout)
    for document, schema in ((plan, "visual-plan-v2"), (layout, "executable-layout-v2")):
        Draft202012Validator(load_schema(schema)).validate(document)
    target["code_payload"]["lines"][0]["spans"][1]["role"] = "keyword"
    with pytest.raises(ValueError, match="code_payload"):
        contracts.validate_plan_layout(plan, layout)
    plan["objects"] = [{key: value for key, value in obj.items() if key != "code_payload"}
                       for obj in plan["objects"]]
    with pytest.raises(ValueError, match="code_payload"):
        contracts.validate_plan_layout(plan, layout)


def code_plan_layout():
    plan = visual_plan_v2()
    target = next(obj for obj in plan["objects"] if obj["object_id"] == "object-label")
    target.update(object_type="code", code_payload=authored_payload())
    layout = executable_layout_v2(plan)
    target = next(obj for obj in layout["objects"] if obj["object_id"] == "object-label")
    target.update(object_type="code", text="\tx = 'Ω'  \n", items=[], code_payload=authored_payload())
    return plan, layout


@pytest.mark.parametrize("missing", ["plan", "layout", "both"])
def test_new_code_contracts_reject_missing_payload_without_inferred_legacy_status(missing):
    plan, layout = code_plan_layout()
    if missing in {"plan", "both"}:
        next(obj for obj in plan["objects"] if obj["object_type"] == "code").pop("code_payload")
    if missing in {"layout", "both"}:
        next(obj for obj in layout["objects"] if obj["object_type"] == "code").pop("code_payload")
    with pytest.raises(ValueError, match="code_payload"):
        contracts.validate_plan_layout(plan, layout)
    if missing in {"plan", "both"}:
        with pytest.raises(ValueError, match="code_payload"):
            contracts.validate_plan_evidence_completeness(plan)
    # Only explicit legacy compatibility validation may admit the bare pair.
    if missing == "both":
        contracts.validate_plan_layout(plan, layout, require_code_payloads=False)


@pytest.mark.parametrize("missing", ["plan", "layout", "both", "none"])
def test_real_project_code_writes_are_exact_or_atomically_rejected(tmp_path, missing):
    from atme.project_service import ProjectError, _visual_digest
    from test_v2_split_project import artifact_rows
    from test_visual_contracts_v2 import _store_v2_plan

    service, project, existing = _store_v2_plan(tmp_path)
    try:
        plan, layout = code_plan_layout()
        pid = project["project_id"]
        plan.update(project_id=pid, project_revision=project["revision"],
                    narrative_authority=deepcopy(existing["narrative_authority"]))
        if missing in {"plan", "both"}:
            next(obj for obj in plan["objects"] if obj["object_type"] == "code").pop("code_payload")
            before = artifact_rows(service, pid)
            with pytest.raises(ProjectError) as failure:
                service.write(pid, "storyboard", plan, project["revision"])
            assert failure.value.code == "invalid_artifact"
            assert any("code_payload" in error["message"] for error in failure.value.errors)
            assert service.open(pid)["revision"] == project["revision"]
            assert artifact_rows(service, pid) == before
            return
        project = service.write(pid, "storyboard", plan, project["revision"])
        layout.update(project_id=pid, project_revision=project["revision"],
                      plan_revision=project["artifacts"]["storyboard"], plan_sha256=_visual_digest(plan))
        if missing == "layout":
            next(obj for obj in layout["objects"] if obj["object_type"] == "code").pop("code_payload")
            before = artifact_rows(service, pid)
            with pytest.raises(ProjectError) as failure:
                service.write(pid, "layout", layout, project["revision"])
            assert failure.value.code == "invalid_artifact"
            assert any("code_payload" in error["message"] for error in failure.value.errors)
            assert service.open(pid)["revision"] == project["revision"]
            assert artifact_rows(service, pid) == before
        else:
            project = service.write(pid, "layout", layout, project["revision"])
            stored = service.artifact(pid, "layout")["document"]
            assert stored == layout
            assert service.artifact(pid, "storyboard")["document"] == plan
            original_rows = artifact_rows(service, pid)
            copied = service.duplicate(pid)
            copied_layout = service.artifact(copied["project_id"], "layout")["document"]
            assert next(obj for obj in copied_layout["objects"] if obj["object_type"] == "code")[
                "code_payload"] == authored_payload()
            assert artifact_rows(service, pid) == original_rows
    finally:
        service.store.close()
