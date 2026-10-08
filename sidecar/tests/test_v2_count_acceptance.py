"""Count acceptance: exact glyphs, chronology, authority, boundaries and retained storage."""

import xml.etree.ElementTree as ET
from copy import deepcopy
from dataclasses import replace
from io import BytesIO
from time import perf_counter

import pytest
from conftest import load_schema
from PIL import Image, ImageChops
from pydantic import ValidationError
from test_v2_connection_actions import relationship_documents
from test_v2_count_contract import count_action, count_policy
from test_v2_count_integration import append_count, retime
from test_v2_group_annotation import consumer_clock, private_svg
from test_v2_group_annotation_project import stored_group_annotation_return_basis
from test_v2_group_count import group_count_documents
from test_v2_hierarchy_isolate import nested_isolate_documents
from v2_fixtures import digest

from atme.project_service import ProjectError, _resolved_compilation_fingerprint
from atme.render import v2_svg
from atme.render.v2_count import (
    _validate_glyph_inventory,
    count_step_text,
    count_text,
    count_value_at_ms,
)
from atme.render.v2_state import CountFrameObject, V2FrameError, evaluate_frame
from atme.render.v2_world import world_bounds
from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    HierarchyBasis,
    ResolvedVisualTimelineV2,
    TargetAction,
    VisualPlanV2,
)


def assert_visible_count_glyph(context, sample, frame, object_id, expected):
    """Same-frame no-glyph control proves pixels belong to the actual Count text."""
    tree = ET.fromstring(frame.svg)
    owner = next(
        node for node in tree.iter() if node.attrib.get("data-object-id") == object_id
    )
    texts = list(owner.iter("{http://www.w3.org/2000/svg}text"))
    assert texts and "".join(texts[0].itertext()) == expected
    for node in owner.iter():
        for child in list(node):
            if child.tag == "{http://www.w3.org/2000/svg}text":
                node.remove(child)
    # Serialize both through the same XML path, eliminating namespace/serialization differences.
    actual = replace(
        frame, svg=ET.tostring(ET.fromstring(frame.svg), encoding="unicode")
    )
    control = replace(frame, svg=ET.tostring(tree, encoding="unicode"))
    paint = Image.open(
        BytesIO(v2_svg._rasterize_svg_frame(context.layout, actual).png)
    ).convert("RGB")
    blank = Image.open(
        BytesIO(v2_svg._rasterize_svg_frame(context.layout, control).png)
    ).convert("RGB")
    changed = ImageChops.difference(paint, blank).getbbox()
    assert changed is not None, (
        "Count glyph is absent or fully clipped in this exact frame"
    )
    objects = sample.hierarchy.object_map(context.objects)
    transforms = {item.object_id: item.transform for item in sample.objects}
    target_bounds = world_bounds(objects[object_id], objects, transforms)
    camera = sample.camera if hasattr(sample, "camera") else None
    # Fixtures retain the full-canvas camera; changed glyph pixels must lie in target bounds.
    assert camera is None or (camera.x, camera.y, camera.width, camera.height) == (
        0,
        0,
        frame.width,
        frame.height,
    )
    assert changed[0] >= target_bounds[0] - 1 and changed[1] >= target_bounds[1] - 1
    assert changed[2] <= target_bounds[2] + 1 and changed[3] <= target_bounds[3] + 1
    return target_bounds, changed


@pytest.mark.parametrize("regroup", [False, True])
@pytest.mark.parametrize("portrait", [False, True])
def test_completed_count_payload_survives_later_hierarchy_step(regroup, portrait):
    layout, timeline = group_count_documents(regroup=regroup, portrait=portrait)
    count = next(
        row for row in timeline["actions"] if row["action"]["action_id"] == "replace-1"
    )
    retime(count, 3000, 4000)
    timeline["actions"].sort(key=lambda row: row["start_ms"])
    timeline["layout_sha256"] = digest(layout)
    original = deepcopy((layout, timeline))
    context, replay, camera = consumer_clock(layout, timeline)
    group = next(
        row
        for row in timeline["actions"]
        if row["action"]["verb"] in {"group", "ungroup"}
    )
    before = replay.before_action(group["action"]["action_id"])
    prior = before.object("object-system")
    complete = replay.at(5000).object("object-system")
    assert isinstance(prior, CountFrameObject) and isinstance(
        complete, CountFrameObject
    )
    assert prior.display_text == complete.display_text == "10 widgets"
    assert prior.count_value == complete.count_value == (10, 1)
    assert prior.state == complete.state == "visible"
    assert (
        dict(replay.at(5000).state_versions)["object-system"]
        == dict(before.state_versions)["object-system"] + 1
    )
    before_png = v2_svg._rasterize_svg_frame(
        context.layout, private_svg(context, replay, camera, 4000)
    ).png
    after_png = v2_svg._rasterize_svg_frame(
        context.layout, private_svg(context, replay, camera, 5000)
    ).png
    # The unrelated evidence reveal completes while the hierarchy commits.
    assert before_png != after_png
    assert_visible_count_glyph(
        context,
        replay.at(5000),
        private_svg(context, replay, camera, 5000),
        "object-system",
        "10 widgets",
    )
    assert (
        v2_svg._rasterize_svg_frame(
            context.layout, private_svg(context, replay, camera, 4000)
        ).png
        == before_png
    )
    assert replay.at(7900).object("object-system").display_text == "20 widgets"
    assert replay.at(7900).object("object-system").count_value == (20, 1)
    assert (layout, timeline) == original


@pytest.mark.parametrize("start", [5000, 6500, 6900])
def test_managed_connector_count_waits_for_completed_disconnect(start):
    layout, timeline = relationship_documents()
    layout["objects"][1]["text"] = "0 widgets"
    append_count(timeline, "object-label", start, start + 500)
    timeline["layout_sha256"] = digest(layout)
    original = deepcopy((layout, timeline))
    if start < 6900:
        with pytest.raises(V2FrameError, match="completed disconnect"):
            evaluate_frame(layout, timeline, 0)
    else:
        frame = evaluate_frame(layout, timeline, 7150)
        assert frame.object("object-label").display_text == "5 widgets"
        assert not frame.object("object-arrow").visible
        complete = evaluate_frame(layout, timeline, start + 500)
        assert complete.object("object-label").display_text == "10 widgets"
        assert complete.object("object-label").count_value == (10, 1)
        assert complete.object("object-label").state == "visible"
        _, replay, _ = consumer_clock(layout, timeline)
        assert (
            dict(replay.at(start + 500).state_versions)["object-label"]
            == dict(replay.at(7150).state_versions)["object-label"] + 1
        )
    assert (layout, timeline) == original


@pytest.mark.parametrize("kind", ["clip", "mask"])
@pytest.mark.parametrize("portrait", [False, True])
def test_count_in_static_aperture_has_real_pixels_and_exact_seek(kind, portrait):
    layout, timeline = nested_isolate_documents(mask=kind == "mask")
    target = next(
        obj for obj in layout["objects"] if obj["object_id"] == "object-label"
    )
    target["text"] = "0 widgets"
    container = next(
        obj for obj in layout["objects"] if obj["object_id"] == "object-group"
    )
    if kind == "clip":
        container["object_type"] = "clip"
    if portrait:
        profile = {
            "profile_id": "SHORT_FORM_9_16",
            "width": 720,
            "height": 1280,
            "fps": 30,
        }
        layout["output_profile"] = deepcopy(profile)
        timeline["output_profile"] = deepcopy(profile)
        layout["canvas"].update(width=720, height=1280)
        # Independent authored portrait placements; never crop landscape output.
        for obj in layout["objects"]:
            if obj["object_id"] == "object-evidence":
                obj["geometry"]["bounds"] = {
                    "x": 80,
                    "y": 780,
                    "width": 540,
                    "height": 220,
                }
            elif obj["object_id"] == "object-label":
                obj["geometry"]["bounds"] = {
                    "x": 100,
                    "y": 220,
                    "width": 460,
                    "height": 120,
                }
            else:
                obj["geometry"]["bounds"] = {
                    "x": 40,
                    "y": 140,
                    "width": 580,
                    "height": 440,
                }
    row = timeline["actions"][2]
    row["action"] = count_action(count_policy(text_object_id="object-label"))
    row["action"]["target_ids"] = ["object-label"]
    timeline["layout_sha256"] = digest(layout)
    original = deepcopy((layout, timeline))
    before = v2_svg.compose_png_frame(layout, timeline, 3999).png
    middle = v2_svg.compose_png_frame(layout, timeline, 4450).png
    after = v2_svg.compose_png_frame(layout, timeline, 4900).png
    assert len({before, middle, after}) == 3
    assert evaluate_frame(layout, timeline, 4450).object(
        "object-label"
    ).count_value == (5, 1)
    svg = v2_svg.compose_svg_frame(layout, timeline, 4450).svg
    assert ('mask="url(' if kind == "mask" else 'clip-path="url(') in svg
    context, replay, _camera = consumer_clock(layout, timeline)
    sample = replay.at(4450)
    target_bounds, changed = assert_visible_count_glyph(
        context,
        sample,
        v2_svg.compose_svg_frame(layout, timeline, 4450),
        "object-label",
        "5 widgets",
    )
    objects = sample.hierarchy.object_map(context.objects)
    transforms = {item.object_id: item.transform for item in sample.objects}
    aperture_bounds = world_bounds(
        objects["mask-source" if kind == "mask" else "object-group"],
        objects,
        transforms,
    )
    assert (
        aperture_bounds[0] <= target_bounds[0] < target_bounds[2] <= aperture_bounds[2]
    )
    assert (
        aperture_bounds[1] <= target_bounds[1] < target_bounds[3] <= aperture_bounds[3]
    )
    assert aperture_bounds[0] <= changed[0] < changed[2] <= aperture_bounds[2]
    assert aperture_bounds[1] <= changed[1] < changed[3] <= aperture_bounds[3]
    assert v2_svg.compose_png_frame(layout, timeline, 4450).png == middle
    assert (layout, timeline) == original


@pytest.mark.parametrize(
    "rounding,expected",
    [
        ("half_even", "-2"),
        ("half_up", "-3"),
        ("half_down", "-2"),
        ("floor", "-3"),
        ("ceiling", "-2"),
        ("truncate", "-2"),
    ],
)
def test_negative_halfway_rounding_is_named_and_exact(rounding, expected):
    policy = count_policy(
        start_value="-3",
        end_value="-2",
        rounding=rounding,
        step_count=2,
        unit="",
        unit_placement="none",
        separator="",
        start_text="-3",
        end_text="-2",
    )
    parsed = TargetAction.model_validate(count_action(policy)).count_policy
    assert count_text(parsed, 0.5) == expected


@pytest.mark.parametrize(
    "placement,unit,separator,start,end,middle",
    [
        ("none", "", "", "1,000.25", "2,000.25", "1,500.25"),
        ("before", "€", " ", "€ 1,000.25", "€ 2,000.25", "€ 1,500.25"),
        ("after", "kg", "", "1,000.25kg", "2,000.25kg", "1,500.25kg"),
    ],
)
def test_precision_grouping_unit_and_separator_have_no_locale_defaults(
    placement, unit, separator, start, end, middle
):
    policy = count_policy(
        start_value="1000.25",
        end_value="2000.25",
        decimal_places=2,
        grouping="thousands",
        unit=unit,
        unit_placement=placement,
        separator=separator,
        start_text=start,
        end_text=end,
    )
    parsed = TargetAction.model_validate(count_action(policy)).count_policy
    assert count_text(parsed, 0.5) == middle


def test_negative_zero_and_fractional_contract_boundaries_are_explicit():
    policy = count_policy(
        start_value="-0.1",
        end_value="0.1",
        unit="",
        unit_placement="none",
        separator="",
        start_text="0",
        end_text="0",
    )
    parsed = TargetAction.model_validate(count_action(policy)).count_policy
    assert {
        count_step_text(parsed, index) for index in range(parsed.step_count + 1)
    } == {"0"}
    assert count_value_at_ms(parsed, 0, 1000, 0, "linear") == (-1, 10)
    assert count_value_at_ms(parsed, 0, 1000, 500, "linear") == (0, 1)
    assert count_value_at_ms(parsed, 0, 1000, 1000, "linear") == (1, 10)
    longest = "0." + "1" * 62
    assert len(longest) == 64
    policy.update(
        start_value=longest,
        end_value=longest,
        decimal_places=6,
        start_text="0.111111",
        end_text="0.111111",
    )
    parsed = TargetAction.model_validate(count_action(policy)).count_policy
    assert count_text(parsed, 0) == count_text(parsed, 1) == "0.111111"


def test_max_level_preflight_is_bounded_and_immutable_key_cache_is_effective(
    monkeypatch,
):
    from test_v2_count_action import count_documents

    layout, timeline = count_documents(count_policy(step_count=4096))
    _validate_glyph_inventory.cache_clear()
    calls = []
    original = v2_svg._text

    def observe(obj, *args, **kwargs):
        calls.append(obj.text)
        return original(obj, *args, **kwargs)

    monkeypatch.setattr(v2_svg, "_text", observe)
    started = perf_counter()
    evaluate_frame(layout, timeline, 4000)
    duration = perf_counter() - started
    assert len(calls) == 4097
    print(
        f"MAX_LEVEL_PREFLIGHT_SECONDS={duration:.6f}"
    )  # observational host benchmark, not semantic gate
    evaluate_frame(layout, timeline, 4450)
    assert len(calls) == 4097


@pytest.mark.parametrize("field,value", [("visible", False), ("opacity", 0)])
def test_static_mask_contract_rejects_unready_count_aperture_source(field, value):
    layout, timeline = nested_isolate_documents(mask=True)
    target = next(
        obj for obj in layout["objects"] if obj["object_id"] == "object-label"
    )
    target["text"] = "0 widgets"
    source = next(obj for obj in layout["objects"] if obj["object_id"] == "mask-source")
    source[field] = value
    if field == "visible":
        next(
            item
            for item in timeline["initial_object_states"]
            if item["object_id"] == "mask-source"
        )["visible"] = value
    row = timeline["actions"][2]
    row["action"] = count_action(count_policy(text_object_id="object-label"))
    row["action"]["target_ids"] = ["object-label"]
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(ValueError, match="mask"):
        evaluate_frame(layout, timeline, 0)


def test_plan_count_array_order_does_not_override_resolved_numeric_history(tmp_path):
    service, project, timeline = stored_group_annotation_return_basis(
        tmp_path, regroup=True, document_builder=group_count_documents
    )
    pid = project["project_id"]
    try:
        plan = deepcopy(service.artifact(pid, "storyboard")["document"])
        layout = deepcopy(service.artifact(pid, "layout")["document"])
        indices = [
            index
            for index, action in enumerate(plan["actions"])
            if action["verb"] == "count"
        ]
        assert len(indices) == 2
        plan["actions"][indices[0]], plan["actions"][indices[1]] = (
            plan["actions"][indices[1]],
            plan["actions"][indices[0]],
        )
        plan["project_revision"] = project["revision"]
        project = service.write(pid, "storyboard", plan, project["revision"])
        layout.update(
            project_revision=project["revision"],
            plan_revision=project["artifacts"]["storyboard"],
            plan_sha256=digest(plan),
        )
        project = service.write(pid, "layout", layout, project["revision"])
        timeline.update(
            project_revision=project["revision"],
            plan_revision=project["artifacts"]["storyboard"],
            plan_sha256=digest(plan),
            layout_revision=project["artifacts"]["layout"],
            layout_sha256=digest(layout),
        )
        timeline["compilation_fingerprint"] = _resolved_compilation_fingerprint(
            timeline
        )
        updated = service.write(pid, "resolved_timeline", timeline, project["revision"])
        assert updated["revision"] == project["revision"] + 1
        _, replay, _ = consumer_clock(layout, timeline)
        assert replay.at(6000).object("object-system").display_text == "0 widgets"
        assert replay.at(7000).object("object-system").count_value == (10, 1)
        assert replay.at(7900).object("object-system").count_value == (20, 1)
    finally:
        service.store.close()


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("later-initial-text", "stale captured starting text"),
        ("resolved-policy", "changes authored actions"),
        ("retained-transform", "hierarchy"),
        ("retained-ordinal", "hierarchy"),
    ],
)
def test_coherently_bound_count_storage_disagreement_rejects_atomically(
    tmp_path, mutation, reason
):
    service, project, timeline = stored_group_annotation_return_basis(
        tmp_path, regroup=True, document_builder=group_count_documents
    )
    pid = project["project_id"]
    try:
        if mutation == "later-initial-text":
            layout = deepcopy(service.artifact(pid, "layout")["document"])
            next(
                obj for obj in layout["objects"] if obj["object_id"] == "object-system"
            )["text"] = "10 widgets"
            layout["project_revision"] = project["revision"]
            # Later Count's authored start passes plan/layout's declared-start set.
            project = service.write(pid, "layout", layout, project["revision"])
            timeline.update(
                project_revision=project["revision"],
                layout_revision=project["artifacts"]["layout"],
                layout_sha256=digest(layout),
            )
        elif mutation == "resolved-policy":
            policy = next(
                row
                for row in timeline["actions"]
                if row["action"]["action_id"] == "count-2"
            )["action"]["count_policy"]
            policy.update(end_value="30", end_text="30 widgets")
        else:
            receipt = timeline["actions"][-1]["return_hierarchy_receipt"]
            rows = receipt["hierarchy_basis"]["placements"]
            target = next(row for row in rows if row["object_id"] == "object-system")
            if mutation == "retained-transform":
                target["local_transform"]["position"]["x"] += 5
            else:
                sibling = next(
                    row
                    for row in rows
                    if row["object_id"] != target["object_id"]
                    and row["parent_id"] == target["parent_id"]
                )
                assert sibling["parent_id"] == target["parent_id"]
                target["sibling_ordinal"], sibling["sibling_ordinal"] = (
                    sibling["sibling_ordinal"],
                    target["sibling_ordinal"],
                )
            receipt["hierarchy_basis_sha256"] = HierarchyBasis.model_validate(
                receipt["hierarchy_basis"]
            ).checksum()
        timeline["compilation_fingerprint"] = _resolved_compilation_fingerprint(
            timeline
        )
        before = deepcopy(service.open(pid))
        source = deepcopy(service.source_timeline.get(pid))
        artifacts = {
            kind: deepcopy(service.artifact(pid, kind))
            for kind in ("storyboard", "layout")
        }
        assert timeline["layout_sha256"] == digest(artifacts["layout"]["document"])
        assert timeline["plan_sha256"] == digest(artifacts["storyboard"]["document"])
        with pytest.raises(ProjectError) as failure:
            service.write(pid, "resolved_timeline", timeline, project["revision"])
        assert failure.value.code == "invalid_artifact"
        assert reason in failure.value.detail()["message"]
        assert service.open(pid) == before
        assert service.source_timeline.get(pid) == source
        assert {kind: service.artifact(pid, kind) for kind in artifacts} == artifacts
        with pytest.raises(ProjectError):
            service.artifact(pid, "resolved_timeline")
    finally:
        service.store.close()


@pytest.mark.parametrize("during_hold", [False, True])
def test_count_preserves_existing_evidence_hold_guard_and_exact_completed_boundary(
    tmp_path, during_hold
):
    from test_v2_evidence_compositor import evidence_documents

    service, layout, timeline, verified = evidence_documents(tmp_path)
    try:
        target = next(
            obj for obj in layout["objects"] if obj["object_id"] == "object-label"
        )
        target["text"] = "0 widgets"
        treatment = layout["evidence_treatments"][0]
        insert = next(
            row
            for row in timeline["actions"]
            if row["action"]["action_id"] == treatment["action_id"]
        )
        hold_end = insert["end_ms"] + treatment["intent"]["readable_hold_intent_ms"]
        start = hold_end - 500 if during_hold else hold_end
        append_count(timeline, "object-label", start, start + 1000)
        timeline["layout_sha256"] = digest(layout)
        original = deepcopy((layout, timeline))
        payload = {verified.asset_id: verified}
        if during_hold:
            with pytest.raises(
                V2FrameError, match="uninterrupted readable insert and hold"
            ):
                evaluate_frame(layout, timeline, 0)
            assert (layout, timeline) == original
            return
        before = evaluate_frame(layout, timeline, start - 1).object("object-evidence")
        middle = evaluate_frame(layout, timeline, start + 500)
        assert middle.object("object-evidence") == before
        assert middle.object("object-label").count_value == (5, 1)
        svg = v2_svg.compose_svg_frame(layout, timeline, start + 500, payload).svg
        assert 'data-evidence-source-label="claim-1"' in svg
        assert "5 widgets" in svg
        assert v2_svg.compose_png_frame(
            layout, timeline, start + 500, payload
        ).png.startswith(b"\x89PNG")
        assert (layout, timeline) == original
    finally:
        service.store.close()


@pytest.mark.parametrize(
    "name,model",
    [
        ("visual-plan-v2", VisualPlanV2),
        ("resolved-visual-timeline-v2", ResolvedVisualTimelineV2),
        ("executable-layout-v2", ExecutableLayoutV2),
    ],
)
def test_distributed_schemas_exactly_match_repeatable_model_generation(name, model):
    stored = deepcopy(load_schema(name))
    assert stored.pop("$schema") == "https://json-schema.org/draft/2020-12/schema"
    assert stored.pop("$id") == f"https://atme.local/schemas/v2/{name}.schema.json"
    first = model.model_json_schema()
    assert first == stored
    assert model.model_json_schema() == first


@pytest.mark.parametrize("value", ["1000000000000000000", "-1000000000000000000"])
def test_count_formatter_admits_exact_signed_magnitude_and_max_precision(value):
    expected = value + ".000000"
    parsed = TargetAction.model_validate(
        count_action(
            count_policy(
                start_value=value,
                end_value=value,
                decimal_places=6,
                unit="",
                unit_placement="none",
                separator="",
                start_text=expected,
                end_text=expected,
            )
        )
    ).count_policy
    assert count_text(parsed, 0.5) == expected
    assert count_value_at_ms(parsed, 0, 1000, 500, "linear") == (int(value), 1)


@pytest.mark.parametrize(
    "change",
    [
        {"decimal_places": True},
        {"step_count": True},
        {"start_value": "-0"},
        {"start_value": "-0.0"},
        {"start_value": "-1000000000000000001"},
    ],
)
def test_count_policy_rejects_boolean_integer_fields_and_noncanonical_boundary_values(
    change,
):
    with pytest.raises(ValidationError):
        TargetAction.model_validate(count_action(count_policy(**change)))
