"""P3-30: externally authored chart data, never inferred from registry artwork."""

import json
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256

import pytest
from conftest import load_schema
from jsonschema import Draft202012Validator
from test_v2_split_identity import sample_for_layout
from v2_fixtures import digest, executable_layout_v2, visual_plan_v2

from atme.render.v2_split_identity import split_content_receipts
from atme.store import contracts_v2 as contracts


def authored_payload(kind="bars", scale="linear"):
    return {
        "version": "1.0.0", "kind": kind, "title": "Measured output",
        "x_axis": {"label": "Stage", "unit": "", "domain": [0.0, 4.0],
                   "scale": "linear", "ticks": [{"value": 1.0, "label": "First"},
                                                 {"value": 2.0, "label": "Second"}]},
        "y_axis": {"label": "Output", "unit": "items", "domain": [0.0, 10.0],
                   "scale": scale, "ticks": [{"value": 0.0, "label": "0"},
                                              {"value": 10.0, "label": "10"}]},
        "series": [{"series_id": "observed", "label": "Observed", "color": "accent",
                    "points": [{"point_id": "first", "x": 1.0, "y": 3.0, "label": "3 items"},
                               {"point_id": "second", "x": 2.0, "y": 7.0, "label": "7 items"}]}],
        "bar": {"width": 0.5, "width_units": "x_axis", "baseline": 0.0} if kind == "bars" else None,
        "highlights": [{"series_id": "observed", "point_id": "second", "color": "attention"}],
        "construction": [{"series_id": "observed", "point_id": "first",
                          "start_fraction": 0.1, "end_fraction": 0.5},
                         {"series_id": "observed", "point_id": "second",
                          "start_fraction": 0.5, "end_fraction": 0.9}],
    }


def chart_documents(kind="bars"):
    plan = visual_plan_v2()
    raw = executable_layout_v2(plan)
    for key in ("objects", "actions", "coverage", "fallbacks"):
        plan[key] = plan[key][:2]
    plan["assets"] = []
    plan["beats"] = plan["beats"][:1]
    plan["conclusion_beat_id"] = plan["beats"][0]["beat_id"]
    plan["boards"][0]["object_ids"] = [obj["object_id"] for obj in plan["objects"]]
    plan["objects"][0].update(object_type="chart", chart_payload=authored_payload(kind))
    raw.update(objects=raw["objects"][:2], boards=deepcopy(plan["boards"]), evidence_treatments=[])
    obj = raw["objects"][0]
    obj.pop("path_data", None)
    obj.update(object_type="chart", variant=None, chart_payload=authored_payload(kind))
    obj["geometry"]["corner_radius"] = None
    obj["geometry"]["bounds"] = {"x": 80.0, "y": 160.0, "width": 480.0, "height": 340.0}
    raw["plan_sha256"] = digest(plan)
    return plan, raw


def payload_type():
    assert hasattr(contracts, "ChartPayload"), "strict authored chart payload is missing"
    return contracts.ChartPayload


@pytest.mark.parametrize("kind", ["bars", "line"])
def test_chart_preserves_authored_data_labels_units_scales_and_timing(kind):
    raw = authored_payload(kind)
    assert payload_type().model_validate(raw).model_dump(mode="json") == raw
    plan, layout = chart_documents(kind)
    contracts.validate_plan_layout(plan, layout)
    assert contracts.ExecutableLayoutV2.model_validate(layout).objects[0].chart_payload.model_dump(mode="json") == raw


@pytest.mark.parametrize("kind", ["bars", "line"])
@pytest.mark.parametrize("timing", ["overlap", "pause", "simultaneous"])
def test_construction_preserves_authored_overlap_and_pauses(kind, timing):
    raw = authored_payload(kind)
    first, second = raw["construction"]
    if timing == "overlap":
        second["start_fraction"] = 0.3
    elif timing == "pause":
        second["start_fraction"] = 0.7
    else:
        second.update(start_fraction=first["start_fraction"], end_fraction=first["end_fraction"])
    assert payload_type().model_validate(raw).model_dump(mode="json") == raw


@pytest.mark.parametrize("axis", ["x_axis", "y_axis"])
@pytest.mark.parametrize("kind", ["bars", "line"])
def test_explicit_positive_log_domains_ticks_and_points_are_preserved(kind, axis):
    raw = authored_payload(kind)
    raw[axis].update(domain=[0.1, 100.0], scale="log",
                     ticks=[{"value": 1.0, "label": "1"}, {"value": 10.0, "label": "10"}])
    if kind == "bars" and axis == "y_axis":
        raw["bar"]["baseline"] = 1.0
    assert payload_type().model_validate(raw).model_dump(mode="json") == raw


@pytest.mark.parametrize("fault", [
    "version", "kind", "missing_series", "empty_series", "duplicate_series", "empty_points",
    "duplicate_point", "empty_id", "unknown_field", "missing_unit", "blank_unit", "empty_title",
    "reversed_domain", "equal_domain", "domain_size", "unknown_scale", "no_ticks", "duplicate_tick",
    "tick_outside", "data_outside", "log_domain", "log_tick", "log_data", "line_order", "line_single",
    "bar_missing", "line_bar", "width_zero", "width_basis", "bar_outside", "baseline_outside",
    "missing_construction", "duplicate_construction", "foreign_construction", "collapsed_phase",
    "phase_outside", "foreign_highlight", "duplicate_highlight", "label_control", "label_surrogate",
])
def test_chart_rejects_ambiguous_invented_or_out_of_domain_payload(fault):
    payload_type()
    raw = authored_payload("line" if fault in {"line_order", "line_single", "line_bar"} else "bars")
    axis, series = raw["y_axis"], raw["series"][0]
    if fault == "version":
        raw["version"] = "2.0.0"
    elif fault == "kind":
        raw["kind"] = "infer"
    elif fault == "missing_series":
        raw.pop("series")
    elif fault == "empty_series":
        raw["series"] = []
    elif fault == "duplicate_series":
        raw["series"].append(deepcopy(series))
    elif fault == "empty_points":
        series["points"] = []
    elif fault == "duplicate_point":
        series["points"][1]["point_id"] = "first"
    elif fault == "empty_id":
        series["series_id"] = " "
    elif fault == "unknown_field":
        series["smoothing"] = "automatic"
    elif fault == "missing_unit":
        axis.pop("unit")
    elif fault == "blank_unit":
        axis["unit"] = " "
    elif fault == "empty_title":
        raw["title"] = " "
    elif fault in {"reversed_domain", "equal_domain", "domain_size"}:
        axis["domain"] = {"reversed_domain": [10.0, 0.0], "equal_domain": [1.0, 1.0],
                          "domain_size": [0.0, 5.0, 10.0]}[fault]
    elif fault == "unknown_scale":
        axis["scale"] = "automatic"
    elif fault == "no_ticks":
        axis["ticks"] = []
    elif fault == "duplicate_tick":
        axis["ticks"].append(deepcopy(axis["ticks"][0]))
    elif fault == "tick_outside":
        axis["ticks"][0]["value"] = -1.0
    elif fault == "data_outside":
        series["points"][0]["y"] = 11.0
    elif fault in {"log_domain", "log_tick", "log_data"}:
        axis.update(scale="log", domain=[0.1, 100.0], ticks=[{"value": 1.0, "label": "1"}])
        raw["bar"]["baseline"] = 1.0
        if fault == "log_domain":
            axis["domain"][0] = 0.0
        elif fault == "log_tick":
            axis["ticks"][0]["value"] = 0.0
        else:
            series["points"][0]["y"] = 0.0
    elif fault == "line_order":
        series["points"].reverse()
    elif fault == "line_single":
        series["points"].pop()
        raw["construction"].pop()
        raw["highlights"] = []
    elif fault == "bar_missing":
        raw["bar"] = None
    elif fault == "line_bar":
        raw["bar"] = {"width": 0.5, "width_units": "x_axis", "baseline": 0.0}
    elif fault == "width_zero":
        raw["bar"]["width"] = 0.0
    elif fault == "width_basis":
        raw["bar"]["width_units"] = "invented_categories"
    elif fault == "bar_outside":
        raw["bar"]["width"] = 3.0
    elif fault == "baseline_outside":
        raw["bar"]["baseline"] = -1.0
    elif fault == "missing_construction":
        raw["construction"].pop()
    elif fault == "duplicate_construction":
        raw["construction"].append(deepcopy(raw["construction"][0]))
    elif fault == "foreign_construction":
        raw["construction"][0]["point_id"] = "invented"
    elif fault == "collapsed_phase":
        raw["construction"][0]["end_fraction"] = 0.1
    elif fault == "phase_outside":
        raw["construction"][0]["end_fraction"] = 1.1
    elif fault == "foreign_highlight":
        raw["highlights"][0]["series_id"] = "invented"
    elif fault == "duplicate_highlight":
        raw["highlights"].append(deepcopy(raw["highlights"][0]))
    elif fault == "label_control":
        series["points"][0]["label"] = "3\x00 items"
    elif fault == "label_surrogate":
        series["points"][0]["label"] = "\ud800"
    with pytest.raises(ValueError):
        payload_type().model_validate(raw)


@pytest.mark.parametrize("bad", [True, "3", float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("field", ["point", "domain", "tick", "width", "baseline", "fraction"])
def test_numeric_fields_do_not_coerce_or_accept_nonfinite_values(field, bad):
    payload_type()
    raw = authored_payload()
    if field == "point":
        raw["series"][0]["points"][0]["y"] = bad
    elif field == "domain":
        raw["y_axis"]["domain"][1] = bad
    elif field == "tick":
        raw["y_axis"]["ticks"][0]["value"] = bad
    elif field == "fraction":
        raw["construction"][0]["start_fraction"] = bad
    else:
        raw["bar"][field] = bad
    with pytest.raises(ValueError) as error:
        payload_type().model_validate(raw)
    if isinstance(bad, (bool, str)):
        assert any(row["type"] == "float_type" for row in error.value.errors())


@pytest.mark.parametrize("semantic", [False, True])
@pytest.mark.parametrize("fault", ["wrong_owner", "registry_binding", "technical_binding", "asset"])
def test_data_bound_chart_cannot_impersonate_another_owner_or_registry_art(semantic, fault):
    payload_type()
    plan, raw = chart_documents()
    obj = (plan if semantic else raw)["objects"][0]
    if fault == "wrong_owner":
        obj["object_type"] = "device"
    elif fault == "registry_binding":
        obj["registry_binding"] = {"version": "1.0.0", "asset_id": "chart-bars", "anchor_mappings": [
            {"placed_anchor_id": "center", "registry_anchor_name": "top"}]}
    elif fault == "technical_binding":
        from test_v2_technical_frame_contract import documents

        obj["technical_frame"] = documents()[1]["objects"][2]["technical_frame"]
    else:
        obj["asset_id"] = "asset-evidence"
    model = contracts.VisualPlanV2 if semantic else contracts.ExecutableLayoutV2
    with pytest.raises(ValueError, match="chart_payload|technical_frame"):
        model.model_validate(plan if semantic else raw)


@pytest.mark.parametrize("field", ["title", "data", "unit", "domain", "scale", "tick", "highlight", "timing"])
def test_authored_chart_content_is_preserved_by_layout_and_independent_identity(field):
    payload_type()
    plan, raw = chart_documents()
    layout = contracts.ExecutableLayoutV2.model_validate(raw)
    sample = sample_for_layout(layout)
    before = {row.object_id: row for row in split_content_receipts(layout, sample, {})}["object-system"]
    document = json.loads(before.canonical_json)
    authored = raw["objects"][0]
    expected = {key: deepcopy(authored[key]) for key in (
        "object_type", "geometry", "style", "anchors", "asset_id", "variant", "chart_payload")}
    encoded = json.dumps(expected, sort_keys=True, separators=(",", ":"))
    assert document == expected
    assert before.canonical_json == encoded
    assert before.content_sha256 == sha256(encoded.encode()).hexdigest()
    changed = deepcopy(raw)
    payload = changed["objects"][0]["chart_payload"]
    if field == "title":
        payload["title"] = "Authored new title"
    elif field == "data":
        payload["series"][0]["points"][0]["y"] = 4.0
    elif field == "unit":
        payload["y_axis"]["unit"] = "requests"
    elif field == "domain":
        payload["y_axis"]["domain"][1] = 12.0
    elif field == "scale":
        payload["x_axis"].update(scale="log", domain=[0.1, 4.0])
    elif field == "tick":
        payload["x_axis"]["ticks"][0]["label"] = "Step A"
    elif field == "highlight":
        payload["highlights"] = []
    else:
        payload["construction"][0]["end_fraction"] = 0.4
    with pytest.raises(ValueError, match="chart_payload"):
        contracts.validate_plan_layout(plan, changed)
    current = contracts.ExecutableLayoutV2.model_validate(changed)
    after = {row.object_id: row for row in split_content_receipts(current, sample_for_layout(current), {})}["object-system"]
    assert after.content_sha256 != before.content_sha256
    moved = replace(sample, objects=tuple(replace(row, transform=replace(row.transform,
                    position=replace(row.transform.position, x=row.transform.position.x + 7)))
                    if row.object_id == "object-system" else row
                    for row in sample.objects))
    assert split_content_receipts(layout, moved, {}) == split_content_receipts(layout, sample, {})


@pytest.mark.parametrize("name,model,document", [
    ("visual-plan-v2", contracts.VisualPlanV2, "plan"),
    ("executable-layout-v2", contracts.ExecutableLayoutV2, "layout"),
])
def test_chart_schema_and_model_agree_on_payload_presence_and_owner(name, model, document):
    payload_type()
    plan, raw = chart_documents()
    candidate = plan if document == "plan" else raw
    schema = load_schema(name)
    assert "ChartPayload" in schema["$defs"]
    Draft202012Validator(schema).validate(candidate)
    assert model.model_validate(candidate)
    candidate["objects"][0]["object_type"] = "device"
    assert list(Draft202012Validator(schema).iter_errors(candidate))
    with pytest.raises(ValueError):
        model.model_validate(candidate)


def test_bare_legacy_registry_chart_shape_and_identity_remain_unchanged():
    plan, raw = chart_documents()
    plan["objects"][0].pop("chart_payload")
    obj = raw["objects"][0]
    obj.pop("chart_payload")
    obj["variant"] = "chart-bars"
    layout = contracts.ExecutableLayoutV2.model_validate(raw)
    original = layout.objects[0].model_dump(mode="json")
    assert "chart_payload" not in original
    assert original == obj
    before = next(row for row in split_content_receipts(layout, sample_for_layout(layout), {})
                  if row.object_id == "object-system")
    assert "chart_payload" not in json.loads(before.canonical_json)
    expected = {key: deepcopy(obj[key]) for key in (
        "object_type", "geometry", "style", "anchors", "asset_id", "variant")}
    encoded = json.dumps(expected, sort_keys=True, separators=(",", ":"))
    assert before.canonical_json == encoded
    assert before.content_sha256 == sha256(encoded.encode()).hexdigest()


@pytest.mark.parametrize("kind", ["bars", "line"])
def test_series_scoped_point_ids_exact_text_and_authored_paint_order_are_not_inferred(kind):
    raw = authored_payload(kind)
    raw["title"] = '  Measured Ω <output> "exact"  '
    second = deepcopy(raw["series"][0])
    second.update(series_id="control", label="Control", color="muted")
    raw["series"].append(second)
    raw["construction"] += [{**deepcopy(row), "series_id": "control"}
                            for row in raw["construction"]]
    raw["x_axis"]["ticks"].reverse()
    if kind == "bars":
        raw["series"][0]["points"].reverse()
    assert payload_type().model_validate(raw).model_dump(mode="json") == raw


@pytest.mark.parametrize("fault", ["extra_payload", "extra_nested", "missing_nested", "subclass",
                                  "boolean_data", "invented_highlight"])
def test_content_identity_rejects_bypassed_or_unknown_chart_model_payloads(fault):
    payload_type()
    raw = chart_documents()[1]
    layout = contracts.ExecutableLayoutV2.model_validate(raw)
    payload = layout.objects[0].chart_payload
    point = payload.series[0].points[0]
    if fault == "extra_payload":
        payload.__dict__["invented_data"] = True
    elif fault == "extra_nested":
        point.__dict__["smoothing"] = "invented"
    elif fault == "missing_nested":
        point.__dict__.pop("label")
    elif fault == "subclass":
        class UnknownChartPoint(contracts.ChartPoint):
            pass

        payload.series[0].points[0] = UnknownChartPoint.model_validate(point.model_dump(mode="json"))
    elif fault == "boolean_data":
        point.y = True
    else:
        payload.highlights[0].point_id = "invented"
    with pytest.raises(ValueError):
        split_content_receipts(layout, sample_for_layout(layout), {})
