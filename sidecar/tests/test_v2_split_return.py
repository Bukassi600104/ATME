"""Stored Split history uses the existing immutable chronology and observers."""

from copy import deepcopy
from dataclasses import replace

import pytest
from test_v2_split_families import geometry_split_family
from v2_fixtures import digest

from atme.render.v2_split_paint import verify_split_paint_inputs
from atme.render.v2_state import validate_resolved_return_history


def retained_history(kind, portrait=False):
    from test_v2_return_board import return_documents
    from test_v2_split_capture import counted_boundary
    from test_v2_split_identity import sample_for_layout
    from v2_split_fixtures import split_documents

    from atme.render.v2_hierarchy_replay import completed_hierarchy_basis
    from atme.render.v2_timeline_replay import _replay_split_chronology
    from atme.store.contracts_v2 import ExecutableLayoutV2, ResolvedVisualTimelineV2

    if kind in {"geometry", "morph", "descendants"}:
        layout, _, split, timeline = geometry_history(portrait)
        prior = ()
        if kind == "descendants":
            from test_v2_split_list_family import structured_list_split_family

            layout, _, split, timeline, *_ = structured_list_split_family(portrait, nested=True, nonidentity=True)
        elif kind == "morph":
            from test_v2_split_capture import peer_action
            from test_v2_timeline_replay import resolved

            layout, _, split, timeline, *_ = geometry_split_family(portrait, "rectangle", "reveal")
            drawing = layout.model_dump(mode="json")
            source = next(row for row in drawing["objects"] if row["object_id"] == "source")
            origin = deepcopy(source)
            origin.update(object_id="origin", object_type="ellipse")
            source.update(initial_state="hidden", visible=False)
            drawing["objects"].append(origin)
            drawing["boards"][0]["object_ids"].append("origin")
            layout = ExecutableLayoutV2.model_validate(drawing)
            prior = (resolved(peer_action("morph", from_object_id="origin", to_object_id="source",
                morph_policy={"mapping": "canonical_outline"}).action, 0, 500),)
            split = split.model_copy(update={"start_ms": 500, "end_ms": 1500})
    else:
        layout, _, _, prior, split = counted_boundary(group_after_count=True, group_first=kind == "group-count")
        _, profile_layout, clock = split_documents("SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9")
        drawing = layout.model_dump(mode="json")
        drawing.update(output_profile=profile_layout["output_profile"], canvas=profile_layout["canvas"])
        next(row for row in drawing["objects"] if row["object_id"] == "source")["geometry"]["bounds"].update(
            width=180, height=60)
        layout = ExecutableLayoutV2.model_validate(drawing)
        timeline = ResolvedVisualTimelineV2.model_validate(clock)
        split = split.model_copy(update={"end_ms": split.start_ms + 40})
    drawing, clock = layout.model_dump(mode="json"), timeline.model_dump(mode="json")
    board_id = drawing["boards"][0]["board_id"]
    drawing["boards"][0].update(persistence_policy="returnable", activation_policy="returnable",
                                expected_prior_state="system_established")
    interlude = deepcopy(drawing["boards"][0])
    interlude.update(board_id="board-interlude", object_ids=[], persistence_policy="single_beat",
                     activation_policy="once", expected_prior_state=None)
    drawing["boards"].append(interlude)
    drawing["activations"] = [
        {**drawing["activations"][0], "end_ms": 2000},
        {"activation_id": "activation-interlude", "board_id": "board-interlude", "start_ms": 2000,
         "end_ms": 3000, "reason": "Inspect another explanation"},
        {**drawing["activations"][0], "activation_id": "activation-return", "start_ms": 3000, "end_ms": 5000},
    ]
    layout = ExecutableLayoutV2.model_validate(drawing)
    clock.update(layout_sha256=digest(drawing), plan_sha256=layout.plan_sha256, duration_ms=5000,
        actions=[row.model_dump(mode="json") for row in (*prior, split)],
        initial_object_states=[{"object_id": obj.object_id, "state": obj.initial_state, "state_version": 1,
                                "visible": obj.visible} for obj in layout.objects])
    initial = sample_for_layout(layout)
    if kind in {"count-group", "group-count", "morph"}:
        from atme.render.v2_split import _observed_split_placements
        from atme.render.v2_split_identity import split_content_receipts
        from atme.store.contracts_v2 import (
            ResolvedAction,
            SplitPolicy,
            _split_expected_completion,
        )

        before = _replay_split_chronology(layout, initial, prior, 5000, {}).at(split.start_ms)
        row = split.model_dump(mode="json")
        policy = row["action"]["split_policy"]
        contents = {row.object_id: row for row in split_content_receipts(layout, before, {})}
        policy["source_basis"]["placements"] = [row.model_dump(mode="json") for row in _observed_split_placements(
            before, before.hierarchy.object_map({obj.object_id: obj for obj in layout.objects}),
            {"source", "part-1", "part-2"}, contents)]
        for mapping in policy["correspondences"]:
            mapping.update(source_content_sha256=contents["source"].content_sha256,
                result_content_sha256=contents[mapping["result_object_id"]].content_sha256)
        policy["source_basis_sha256"] = digest(policy["source_basis"])
        receipt = _split_expected_completion(SplitPolicy.model_validate(policy))
        receipt["completion_sha256"] = digest(receipt)
        row["split_completion_receipt"] = receipt
        split = ResolvedAction.model_validate(row)
        clock["actions"] = [row.model_dump(mode="json") for row in (*prior, split)]
    initial_basis = completed_hierarchy_basis(initial.hierarchy, {row.object_id: row for row in initial.objects})
    clock.update(initial_hierarchy_basis=initial_basis.model_dump(mode="json"),
                 initial_hierarchy_basis_sha256=initial_basis.checksum())
    # Author the return receipt from a completed prefix; assertions below pin retained values independently.
    prefix = _replay_split_chronology(layout, initial, (*prior, split), 5000, {})
    retained = prefix.at(2000)
    basis = completed_hierarchy_basis(retained.hierarchy, {row.object_id: row for row in retained.objects})
    _, return_clock = return_documents()
    returned = deepcopy(return_clock["actions"][2])
    returned.update(start_ms=3000, end_ms=3001)
    trigger = {"kind": "absolute", "at_ms": 3000}
    returned["resolved_trigger"].update(source=trigger, alignment_anchor_ms=3000, resolved_at_ms=3000)
    returned["action"].update(trigger=trigger, board_id=board_id, destination_board_id=board_id,
        source_board_id="board-interlude", source_activation_id="activation-interlude",
        prior_destination_activation_id=drawing["activations"][0]["activation_id"],
        expected_object_states={row.object_id: row.state for row in retained.objects},
        expected_object_state_versions=dict(retained.state_versions))
    returned["return_hierarchy_receipt"] = {"action_id": "return-1", "destination_board_id": board_id,
        "destination_activation_id": "activation-return", "hierarchy_basis": basis.model_dump(mode="json"),
        "hierarchy_basis_sha256": basis.checksum()}
    clock["actions"].append(returned)
    for row in clock["actions"]:
        row["action"].update(coverage_id=clock["coverage"][0]["coverage_id"], source_instruction_id="instruction-1",
                              fallback=deepcopy(clock["actions"][0]["action"]["fallback"]))
    clock["coverage"][0]["action_ids"] = [row["action"]["action_id"] for row in clock["actions"]]
    return layout, ResolvedVisualTimelineV2.model_validate(clock)


def geometry_history(portrait=False):
    layout, initial, split, timeline, *_ = geometry_split_family(portrait)
    timeline = timeline.model_copy(update={"layout_sha256": digest(layout.model_dump(mode="json")),
                                           "plan_sha256": layout.plan_sha256})
    return layout, initial, split, timeline


@pytest.mark.parametrize("portrait", [False, True])
def test_stored_split_requires_verified_inputs_and_preserves_public_gate(portrait):
    from atme.render.v2_state import UnsupportedVisualAction, evaluate_frame
    from atme.render.v2_timeline_replay import supports_operator

    layout, _, split, timeline = geometry_history(portrait)
    original = layout.model_dump(mode="json"), timeline.model_dump(mode="json")
    inputs = verify_split_paint_inputs(layout, {})
    validate_resolved_return_history(layout, timeline, layout_sha256=timeline.layout_sha256,
                                     split_inputs=inputs)
    assert original == (layout.model_dump(mode="json"), timeline.model_dump(mode="json"))
    assert not supports_operator(split.action)
    with pytest.raises(UnsupportedVisualAction, match="split"):
        evaluate_frame(*original, 20)
    with pytest.raises(ValueError, match="Split.*verified"):
        validate_resolved_return_history(layout, timeline, layout_sha256=timeline.layout_sha256)


@pytest.mark.parametrize("fault", ["dict", "stale-layout", "forged-manifest"])
def test_stored_split_rejects_noncanonical_frozen_authority(fault):
    layout, _, _, timeline = geometry_history()
    inputs = verify_split_paint_inputs(layout, {})
    if fault == "dict":
        inputs = inputs.__dict__
    elif fault == "stale-layout":
        inputs = replace(inputs, layout_sha256="0" * 64)
    else:
        inputs = replace(inputs, manifest_json="{}")
    with pytest.raises(ValueError, match="Split"):
        validate_resolved_return_history(layout, timeline, layout_sha256=timeline.layout_sha256,
                                         split_inputs=inputs)


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["geometry", "count-group", "group-count", "morph", "descendants"])
def test_split_aba_retains_count_content_pose_hierarchy_and_versions(kind, portrait):
    from atme.render.v2_hierarchy import HierarchySnapshot
    from atme.render.v2_state import _validate_consumer_history, _validate_pair_static

    layout, timeline = retained_history(kind, portrait)
    original = layout.model_dump(mode="json"), timeline.model_dump(mode="json")
    inputs = verify_split_paint_inputs(layout, {})
    validate_resolved_return_history(layout, timeline, layout_sha256=timeline.layout_sha256, split_inputs=inputs)
    context = _validate_pair_static(layout, timeline, timeline.layout_sha256,
        HierarchySnapshot.from_objects({obj.object_id: obj for obj in layout.objects}))
    replay, _ = _validate_consumer_history(context, split_inputs=inputs)
    before, returned = replay.at(1999), replay.at(3000)
    assert before.objects == returned.objects
    assert before.hierarchy == returned.hierarchy
    assert before.state_versions == returned.state_versions
    assert returned.object("source").state == "removed"
    assert returned.object("part-1").state == returned.object("part-2").state == "visible"
    assert dict(returned.state_versions)["source"] == (4 if kind in {"count-group", "group-count"}
                                                       else 3 if kind == "morph" else 2)
    if kind in {"count-group", "group-count"}:
        assert returned.object("source").display_text == "10 widgets"
        assert returned.object("source").count_value == (10, 1)
        assert returned.object("source").transform.position.x == 100
        assert next(row for row in returned.hierarchy.nodes if row.object_id == "source").parent_id is None
        assert dict(returned.state_versions) == {"source": 4, "shell": 2, "part-1": 3, "part-2": 3}
    elif kind == "morph":
        assert returned.object("origin").state == "removed"
        assert dict(returned.state_versions)["origin"] == 2
        assert returned.object("source").morph_geometry is None
    elif kind == "descendants":
        assert len(returned.objects) > 3
        for root in ("source", "part-1", "part-2"):
            for child in (row.object_id for row in returned.hierarchy.nodes
                          if root in returned.hierarchy.ancestors(row.object_id)):
                assert returned.object(child).transform == before.object(child).transform
                assert dict(returned.state_versions)[child] == 1
    assert original == (layout.model_dump(mode="json"), timeline.model_dump(mode="json"))


def test_stored_raw_layout_hash_and_canonical_inputs_are_independent():
    from atme.store.contracts_v2 import ExecutableLayoutV2

    layout, _, _, timeline = geometry_history()
    raw = layout.model_dump(mode="json")
    raw.pop("evidence_treatments")
    parsed = ExecutableLayoutV2.model_validate(raw)
    raw_hash = digest(raw)
    inputs = verify_split_paint_inputs(parsed, {})
    assert raw_hash != inputs.layout_sha256
    timeline = timeline.model_copy(update={"layout_sha256": raw_hash})
    validate_resolved_return_history(parsed, timeline, layout_sha256=raw_hash, split_inputs=inputs)
    with pytest.raises(ValueError, match="same composition"):
        validate_resolved_return_history(parsed, timeline, layout_sha256=inputs.layout_sha256, split_inputs=inputs)


@pytest.mark.parametrize("fault", ["order", "content", "state-version", "unknown-source"])
def test_coherently_rehashed_stale_basis_rejects_observed_boundary(fault):
    from atme.store.contracts_v2 import (
        ResolvedVisualTimelineV2,
        SplitPolicy,
        _split_expected_completion,
    )

    layout, _, _, timeline = geometry_history()
    inputs = verify_split_paint_inputs(layout, {})
    validate_resolved_return_history(layout, timeline, layout_sha256=timeline.layout_sha256, split_inputs=inputs)
    raw = timeline.model_dump(mode="json")
    row = raw["actions"][0]
    policy = row["action"]["split_policy"]
    if fault == "unknown-source":
        row["action"]["target_ids"] = ["unknown"]
        policy["source_object_id"] = "unknown"
        policy["source_basis"]["source_closure"] = {"root_id": "unknown", "owned_ids": ["unknown"]}
        source = next(p for p in policy["source_basis"]["placements"] if p["object_id"] == "source")
        source["object_id"] = "unknown"
        policy["source_basis"]["placements"].sort(key=lambda p: p["object_id"])
        for mapping in policy["correspondences"]:
            mapping["source_object_id"] = "unknown"
    elif fault == "order":
        policy["source_basis"]["placements"][0]["sibling_ordinal"] = 99
    elif fault == "content":
        placement = policy["source_basis"]["placements"][0]
        placement["content_sha256"] = "e" * 64
        for mapping in policy["correspondences"]:
            if mapping["result_object_id"] == placement["object_id"]:
                mapping["result_content_sha256"] = "e" * 64
    else:
        policy["source_basis"]["placements"][0]["state_version"] += 1
    policy["source_basis_sha256"] = digest(policy["source_basis"])
    completion = _split_expected_completion(SplitPolicy.model_validate(policy))
    completion["completion_sha256"] = digest(completion)
    row["split_completion_receipt"] = completion
    if fault == "unknown-source":
        with pytest.raises(ValueError, match="targets an object without initial state"):
            ResolvedVisualTimelineV2.model_validate(raw)
        return
    forged = ResolvedVisualTimelineV2.model_validate(raw)
    with pytest.raises(ValueError, match="unknown layout object" if fault == "unknown-source" else "basis differs"):
        validate_resolved_return_history(layout, forged, layout_sha256=timeline.layout_sha256, split_inputs=inputs)


def future_group_history():
    from test_v2_split_identity import sample_for_layout
    from test_v2_timeline_replay import resolved

    from atme.render.v2_hierarchy_replay import completed_hierarchy_basis
    from atme.store.contracts_v2 import (
        ExecutableLayoutV2,
        HierarchyBasis,
        ResolvedVisualTimelineV2,
    )

    layout, timeline = retained_history("geometry")
    drawing, clock = layout.model_dump(mode="json"), timeline.model_dump(mode="json")
    shell = deepcopy(drawing["objects"][0])
    shell.pop("path_data", None)
    shell.update(object_id="future-shell", object_type="group", child_ids=[], initial_state="ungrouped",
                 visible=True, z_index=99, anchors=[],
                 style={"stroke": None, "fill": None, "text": None, "effect": None})
    shell["geometry"].update(points=[], corner_radius=None)
    drawing["objects"].append(shell)
    drawing["boards"][0]["object_ids"].append("future-shell")
    drawing["initial_empty_group_ownership"] = [{"shell_object_id": "future-shell",
        "owner_group_action_id": "future-group", "owner_source_basis_sha256": "0" * 64}]
    # Initial shell ownership is authored by the later Group, outside the return's causal prefix.
    provisional = ExecutableLayoutV2.model_validate(drawing)
    sample = sample_for_layout(provisional)
    initial = completed_hierarchy_basis(sample.hierarchy, {row.object_id: row for row in sample.objects})
    destination = initial.model_dump(mode="json")
    for placement in destination["placements"]:
        key = placement["object_id"]
        if key == "part-2":
            placement.update(parent_id="future-shell", sibling_ordinal=0)
        elif key == "future-shell":
            placement["sibling_ordinal"] -= 1
    destination = HierarchyBasis.model_validate(destination)
    action = {key: deepcopy(value) for key, value in clock["actions"][0]["action"].items()
              if key not in {"split_policy", "container_id", "target_ids", "verb"}}
    action.update(action_id="future-group", verb="group", easing="step", target_ids=["part-2"],
        container_id="future-shell", expected_state="ungrouped", post_state="grouped", hierarchy_policy={
            "member_root_ids": ["part-2"], "source_basis": initial.model_dump(mode="json"),
            "source_basis_sha256": initial.checksum(), "destination_basis": destination.model_dump(mode="json"),
            "destination_basis_sha256": destination.checksum(), "changed_object_ids": ["future-shell", "part-2"],
            "preserve_world_transform": True})
    clock["actions"].append(resolved(action, 3000, 3100).model_dump(mode="json"))
    drawing["initial_empty_group_ownership"] = [{"shell_object_id": "future-shell",
        "owner_group_action_id": "future-group", "owner_source_basis_sha256": initial.checksum()}]
    layout = ExecutableLayoutV2.model_validate(drawing)
    clock.update(layout_sha256=digest(drawing), initial_hierarchy_basis=initial.model_dump(mode="json"),
                 initial_hierarchy_basis_sha256=initial.checksum())
    clock["initial_object_states"].append({"object_id": "future-shell", "state": "ungrouped", "visible": True,
                                            "state_version": 1})
    returned = clock["actions"][-2]
    returned["action"]["expected_object_states"]["future-shell"] = "ungrouped"
    returned["action"]["expected_object_state_versions"]["future-shell"] = 1
    receipt = returned["return_hierarchy_receipt"]
    receipt["hierarchy_basis"]["placements"].append(next(p.model_dump(mode="json") for p in initial.placements
                                                        if p.object_id == "future-shell"))
    receipt["hierarchy_basis"]["placements"].sort(key=lambda p: p["object_id"])
    receipt["hierarchy_basis_sha256"] = digest(receipt["hierarchy_basis"])
    clock["coverage"][0]["action_ids"].append("future-group")
    return layout, ResolvedVisualTimelineV2.model_validate(clock)


def test_return_keeps_full_structural_ownership_and_executes_only_causal_prefix():
    from atme.store.contracts_v2 import ExecutableLayoutV2

    layout, timeline = future_group_history()
    inputs = verify_split_paint_inputs(layout, {})
    validate_resolved_return_history(layout, timeline, layout_sha256=timeline.layout_sha256, split_inputs=inputs)
    drawing = layout.model_dump(mode="json")
    drawing["initial_empty_group_ownership"][0]["owner_source_basis_sha256"] = "0" * 64
    forged = ExecutableLayoutV2.model_validate(drawing)
    forged_timeline = timeline.model_copy(update={"layout_sha256": digest(drawing)})
    with pytest.raises(ValueError, match="empty group owner"):
        validate_resolved_return_history(forged, forged_timeline, layout_sha256=digest(drawing),
                                         split_inputs=verify_split_paint_inputs(forged, {}))


def test_private_split_cannot_capture_with_assets_independent_of_frozen_inputs():
    from atme.render.v2_timeline_replay import _replay_split_chronology

    layout, initial, split, timeline = geometry_history()
    with pytest.raises(ValueError, match="asset carrier differs from frozen"):
        _replay_split_chronology(layout, initial, (split,), timeline.duration_ms, {}, timeline=timeline,
                                  split_inputs=verify_split_paint_inputs(layout, {}))


def test_split_storage_uses_frozen_registry_after_current_bundle_changes(monkeypatch):
    import socket
    from pathlib import Path

    from test_v2_split_visual_family import split_timeline
    from test_v2_split_visual_family_boundaries import registry_boundary

    from atme.render import style_bundle, v2_state

    layout, initial, action, *_ = registry_boundary()
    timeline = split_timeline(layout, initial, action)
    timeline = timeline.model_copy(update={"layout_sha256": digest(layout.model_dump(mode="json")),
                                           "plan_sha256": layout.plan_sha256})
    inputs = verify_split_paint_inputs(layout, {})
    original = style_bundle.registry_endpoint_inputs_for_objects

    def frozen_registry(objects, **kwargs):
        if kwargs.get("frozen_files") is None:
            raise AssertionError("storage reopened the current registry instead of its frozen bytes")
        return original(objects, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("frozen storage attempted source IO or network")

    monkeypatch.setattr(v2_state, "registry_endpoint_inputs_for_objects", frozen_registry)
    monkeypatch.setattr(style_bundle, "registry_endpoint_inputs_for_objects", frozen_registry)
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    validate_resolved_return_history(layout, timeline, layout_sha256=timeline.layout_sha256, split_inputs=inputs)


def test_valid_return_does_not_hide_invalid_later_split_history():
    from test_v2_split_capture import peer_action
    from test_v2_timeline_replay import resolved

    from atme.store.contracts_v2 import ResolvedVisualTimelineV2

    layout, timeline = retained_history("geometry")
    inputs = verify_split_paint_inputs(layout, {})
    validate_resolved_return_history(layout, timeline, layout_sha256=timeline.layout_sha256, split_inputs=inputs)
    raw = timeline.model_dump(mode="json")
    action = peer_action("dim", target_ids=["part-1"]).action.model_dump(mode="json")
    action.update(action_id="after-return-invalid", expected_state="visible", post_state="visible",
                  coverage_id=raw["coverage"][0]["coverage_id"], source_instruction_id="instruction-1")
    raw["actions"].append(resolved(action, 3100, 3200).model_dump(mode="json"))
    raw["coverage"][0]["action_ids"].append("after-return-invalid")
    forged = ResolvedVisualTimelineV2.model_validate(raw)
    with pytest.raises(ValueError, match="visible context"):
        validate_resolved_return_history(layout, forged, layout_sha256=timeline.layout_sha256, split_inputs=inputs)


def test_coherent_phase_policy_cannot_store_a_native_blank_gap():
    from atme.store.contracts_v2 import (
        ResolvedVisualTimelineV2,
        SplitPolicy,
        _split_expected_completion,
    )

    layout, _, _, timeline = geometry_history()
    inputs = verify_split_paint_inputs(layout, {})
    validate_resolved_return_history(layout, timeline, layout_sha256=timeline.layout_sha256, split_inputs=inputs)
    raw = timeline.model_dump(mode="json")
    row = raw["actions"][0]
    policy = row["action"]["split_policy"]
    policy["source_exit"].update(start_tick=0, end_tick=1000)
    for result in policy["results"]:
        result["construction"]["phase"].update(start_tick=9000, end_tick=10000)
    receipt = _split_expected_completion(SplitPolicy.model_validate(policy))
    receipt["completion_sha256"] = digest(receipt)
    row["split_completion_receipt"] = receipt
    forged = ResolvedVisualTimelineV2.model_validate(raw)
    with pytest.raises(ValueError, match="zero painted coverage at 4 ms"):
        validate_resolved_return_history(layout, forged, layout_sha256=timeline.layout_sha256, split_inputs=inputs)


@pytest.mark.parametrize("fault", ["missing", "extra", "duplicate", "conflicting", "interval"])
def test_storage_coverage_requires_exact_live_capture_inventory(monkeypatch, fault):
    from atme.render import v2_state
    from atme.render.v2_split import CapturedSplitAction

    layout, _, _, timeline = geometry_history()
    validate = v2_state._validate_consumer_history

    def tampered(*args, **kwargs):
        replay, camera = validate(*args, **kwargs)
        checkpoints = []
        for checkpoint in replay.checkpoints:
            active = []
            for row in checkpoint.active:
                if not isinstance(row, CapturedSplitAction):
                    active.append(row)
                elif fault == "extra":
                    active.extend((row, replace(row, resolved_index=99)))
                elif fault == "conflicting":
                    active.extend((row, replace(row)))
                elif fault == "duplicate":
                    active.extend((row, row))
                elif fault == "interval":
                    active.append(replace(row, split_capture=replace(row.split_capture, end_ms=row.split_capture.end_ms + 1)))
                elif fault != "missing":
                    active.append(row)
            checkpoints.append(replace(checkpoint, active=tuple(active)))
        return replace(replay, checkpoints=tuple(checkpoints)), camera

    monkeypatch.setattr(v2_state, "_validate_consumer_history", tampered)
    with pytest.raises(ValueError, match="Split storage.*capture"):
        validate_resolved_return_history(layout, timeline, layout_sha256=timeline.layout_sha256,
                                         split_inputs=verify_split_paint_inputs(layout, {}))


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["count-group", "morph"])
def test_split_paints_actual_completed_count_glyphs_and_morph_geometry(kind, portrait):
    import io
    import xml.etree.ElementTree as ET

    from PIL import Image, ImageChops

    from atme.render.v2_hierarchy import HierarchySnapshot
    from atme.render.v2_state import (
        _sample_validated_frame,
        _validate_consumer_history,
        _validate_pair_static,
    )
    from atme.render.v2_svg import _compose_validated_svg_frame, _rasterize_svg_frame

    layout, timeline = retained_history(kind, portrait)
    inputs = verify_split_paint_inputs(layout, {})
    context = _validate_pair_static(layout, timeline, timeline.layout_sha256,
        HierarchySnapshot.from_objects({obj.object_id: obj for obj in layout.objects}))
    replay, cameras = _validate_consumer_history(context, split_inputs=inputs)
    split = next(row for row in timeline.actions if row.action.verb == "split")
    sample = _sample_validated_frame(layout, timeline, replay, cameras, split.start_ms)
    frame = _compose_validated_svg_frame(layout, timeline, sample, {}, split_inputs=inputs)
    tree = ET.fromstring(frame.svg)
    source = next(row for row in tree.iter() if row.attrib.get("data-object-id") == "source")
    if kind == "count-group":
        texts = list(source.iter("{http://www.w3.org/2000/svg}text"))
        assert len(texts) == 1 and "".join(texts[0].itertext()) == "10 widgets"
        assert sample.object("source").count_value == (10, 1)
    else:
        assert list(source.iter("{http://www.w3.org/2000/svg}rect"))
        assert not list(source.iter("{http://www.w3.org/2000/svg}ellipse"))
        assert sample.object("origin").state == "removed"
    actual = replace(frame, svg=ET.tostring(tree, encoding="unicode"))
    for child in list(source):
        source.remove(child)
    blank = replace(frame, svg=ET.tostring(tree, encoding="unicode"))
    painted = Image.open(io.BytesIO(_rasterize_svg_frame(layout, actual, split_inputs=inputs).png)).convert("RGB")
    control = Image.open(io.BytesIO(_rasterize_svg_frame(layout, blank, split_inputs=inputs).png)).convert("RGB")
    assert ImageChops.difference(painted, control).getbbox() is not None


@pytest.mark.parametrize("gap_ms", [1, 20, 39])
def test_storage_rejects_single_blank_millisecond_near_start_middle_and_end(gap_ms):
    from atme.store.contracts_v2 import (
        ResolvedVisualTimelineV2,
        SplitPolicy,
        _split_expected_completion,
    )

    layout, _, _, timeline = geometry_history()
    raw = timeline.model_dump(mode="json")
    row = raw["actions"][0]
    policy = row["action"]["split_policy"]
    policy["source_exit"].update(start_tick=0, end_tick=gap_ms * 250)
    for result in policy["results"]:
        result["construction"]["phase"].update(start_tick=gap_ms * 250, end_tick=10000)
    receipt = _split_expected_completion(SplitPolicy.model_validate(policy))
    receipt["completion_sha256"] = digest(receipt)
    row["split_completion_receipt"] = receipt
    with pytest.raises(ValueError, match=f"zero painted coverage at {gap_ms} ms"):
        validate_resolved_return_history(layout, ResolvedVisualTimelineV2.model_validate(raw),
            layout_sha256=timeline.layout_sha256, split_inputs=verify_split_paint_inputs(layout, {}))


def test_storage_checks_each_completed_result_even_when_another_root_still_paints():
    from atme.store.contracts_v2 import (
        ResolvedVisualTimelineV2,
        SplitPolicy,
        _split_expected_completion,
    )

    layout, _, _, timeline = geometry_history()
    raw = timeline.model_dump(mode="json")
    row = raw["actions"][0]
    policy = row["action"]["split_policy"]
    result = policy["results"][0]
    start = deepcopy(result["destination"])
    destination = deepcopy(start)
    destination["position"]["x"] = 2000
    result.update(destination=destination, movement={
        "phase": {"start_tick": 6000, "end_tick": 10000, "easing": "linear"},
        "from_transform": start, "destination": destination})
    receipt = _split_expected_completion(SplitPolicy.model_validate(policy))
    receipt["completion_sha256"] = digest(receipt)
    row["split_completion_receipt"] = receipt
    with pytest.raises(ValueError, match="unpainted visible result root"):
        validate_resolved_return_history(layout, ResolvedVisualTimelineV2.model_validate(raw),
            layout_sha256=timeline.layout_sha256, split_inputs=verify_split_paint_inputs(layout, {}))


def multiple_split_history():
    from test_v2_split_identity import sample_for_layout

    from atme.render.v2_hierarchy_replay import completed_hierarchy_basis
    from atme.render.v2_split import _observed_split_placements
    from atme.render.v2_split_identity import split_content_receipts
    from atme.render.v2_timeline_replay import _replay_split_chronology
    from atme.store.contracts_v2 import (
        ExecutableLayoutV2,
        ResolvedAction,
        ResolvedVisualTimelineV2,
        SplitPolicy,
        _split_expected_completion,
    )

    layout, timeline = retained_history("geometry")
    drawing, clock = layout.model_dump(mode="json"), timeline.model_dump(mode="json")
    template = next(row for row in drawing["objects"] if row["object_id"] == "part-2")
    for ordinal in (3, 4):
        obj = deepcopy(template)
        obj.update(object_id=f"part-{ordinal}", z_index=ordinal)
        drawing["objects"].append(obj)
        drawing["boards"][0]["object_ids"].append(obj["object_id"])
        clock["initial_object_states"].append({"object_id": obj["object_id"], "state": "hidden", "visible": False,
                                                "state_version": 1})
        clock["actions"][-1]["action"]["expected_object_states"][obj["object_id"]] = "hidden"
        clock["actions"][-1]["action"]["expected_object_state_versions"][obj["object_id"]] = 1
    layout = ExecutableLayoutV2.model_validate(drawing)
    initial = sample_for_layout(layout)
    basis = completed_hierarchy_basis(initial.hierarchy, {row.object_id: row for row in initial.objects})
    clock.update(layout_sha256=digest(drawing), initial_hierarchy_basis=basis.model_dump(mode="json"),
                 initial_hierarchy_basis_sha256=basis.checksum())
    receipt = clock["actions"][-1]["return_hierarchy_receipt"]
    receipt["hierarchy_basis"]["placements"].extend(row.model_dump(mode="json") for row in basis.placements
                                                  if row.object_id in {"part-3", "part-4"})
    receipt["hierarchy_basis"]["placements"].sort(key=lambda row: row["object_id"])
    receipt["hierarchy_basis_sha256"] = digest(receipt["hierarchy_basis"])
    before = _replay_split_chronology(layout, initial, tuple(ResolvedAction.model_validate(row) for row in clock["actions"]),
                                      5000, {}).at(3500)
    row = deepcopy(clock["actions"][0])
    trigger = {"kind": "absolute", "at_ms": 3500}
    row.update(start_ms=3500, end_ms=3540)
    row["resolved_trigger"].update(source=trigger, alignment_anchor_ms=3500, resolved_at_ms=3500,
                                   matched_text=None, matched_occurrence=None, confidence=1, exact=True)
    row["action"].update(action_id="split-2", trigger=trigger, target_ids=["part-1"])
    policy = row["action"]["split_policy"]
    policy["source_object_id"] = "part-1"
    policy["source_basis"]["source_closure"] = {"root_id": "part-1", "owned_ids": ["part-1"]}
    policy["source_basis"]["result_closures"] = [{"root_id": key, "owned_ids": [key]} for key in ("part-3", "part-4")]
    contents = {row.object_id: row for row in split_content_receipts(layout, before, {})}
    policy["source_basis"]["placements"] = [row.model_dump(mode="json") for row in _observed_split_placements(
        before, before.hierarchy.object_map({obj.object_id: obj for obj in layout.objects}),
        {"part-1", "part-3", "part-4"}, contents)]
    for result, mapping, key in zip(policy["results"], policy["correspondences"], ("part-3", "part-4"), strict=True):
        result.update(object_id=key, correspondence_id=f"map-{key}")
        mapping.update(source_object_id="part-1", result_object_id=key, correspondence_id=f"map-{key}",
                       source_content_sha256=contents["part-1"].content_sha256,
                       result_content_sha256=contents[key].content_sha256)
    policy["source_basis_sha256"] = digest(policy["source_basis"])
    receipt = _split_expected_completion(SplitPolicy.model_validate(policy))
    receipt["completion_sha256"] = digest(receipt)
    row["split_completion_receipt"] = receipt
    clock["actions"].append(row)
    clock["coverage"][0]["action_ids"].append("split-2")
    return layout, ResolvedVisualTimelineV2.model_validate(clock)


def test_storage_proves_each_actual_split_once_including_after_the_last_return(monkeypatch):
    from atme.render import v2_split_paint
    from atme.store.contracts_v2 import (
        ResolvedVisualTimelineV2,
        SplitPolicy,
        _split_expected_completion,
    )

    layout, timeline = multiple_split_history()
    original = layout.model_dump(mode="json"), timeline.model_dump(mode="json")
    seen = []
    prove = v2_split_paint.prove_split_coverage
    inputs = verify_split_paint_inputs(layout, {})

    def observed(capture, drawing, frozen):
        result = prove(capture, drawing, frozen)
        assert frozen is inputs
        seen.append((capture.action_id, capture.start_ms, capture.end_ms))
        return result

    monkeypatch.setattr(v2_split_paint, "prove_split_coverage", observed)
    validate_resolved_return_history(layout, timeline, layout_sha256=timeline.layout_sha256, split_inputs=inputs)
    assert seen == [("split-1", 0, 40), ("split-2", 3500, 3540)]
    assert original == (layout.model_dump(mode="json"), timeline.model_dump(mode="json"))
    raw = timeline.model_dump(mode="json")
    row = raw["actions"][-1]
    policy = row["action"]["split_policy"]
    policy["source_basis"]["placements"][0]["state_version"] += 1
    policy["source_basis_sha256"] = digest(policy["source_basis"])
    receipt = _split_expected_completion(SplitPolicy.model_validate(policy))
    receipt["completion_sha256"] = digest(receipt)
    row["split_completion_receipt"] = receipt
    forged = ResolvedVisualTimelineV2.model_validate(raw)
    with pytest.raises(ValueError, match="basis differs"):
        validate_resolved_return_history(layout, forged, layout_sha256=timeline.layout_sha256, split_inputs=inputs)


@pytest.mark.parametrize("fault", ["payload", "subclass"])
def test_count_native_admission_cannot_replace_authenticated_runtime_content(fault):
    from atme.render.v2_hierarchy import HierarchySnapshot
    from atme.render.v2_split import CapturedSplitAction
    from atme.render.v2_split_paint import prove_split_coverage
    from atme.render.v2_state import (
        CountFrameObject,
        _validate_consumer_history,
        _validate_pair_static,
    )

    layout, timeline = retained_history("count-group")
    inputs = verify_split_paint_inputs(layout, {})
    context = _validate_pair_static(layout, timeline, timeline.layout_sha256,
        HierarchySnapshot.from_objects({obj.object_id: obj for obj in layout.objects}))
    replay, _ = _validate_consumer_history(context, split_inputs=inputs)
    capture = next(row.split_capture for checkpoint in replay.checkpoints for row in checkpoint.active
                   if isinstance(row, CapturedSplitAction))
    source = next(row for row in capture.baseline if row.object_id == "source")
    if fault == "payload":
        changed = replace(source, display_text="11 widgets", count_value=(11, 1))
    else:
        class UnknownCount(CountFrameObject):
            pass

        changed = UnknownCount(**source.__dict__)
    forged = replace(capture, baseline=tuple(changed if row.object_id == "source" else row for row in capture.baseline))
    with pytest.raises(ValueError, match="content|frame|payload"):
        prove_split_coverage(forged, layout, inputs)
    assert source.display_text == "10 widgets" and source.count_value == (10, 1)


@pytest.mark.parametrize("fault", ["phase", "pose", "state", "version"])
def test_resolved_completion_is_rederived_even_when_checksum_is_coherent(fault):
    from atme.store.contracts_v2 import ResolvedVisualTimelineV2

    layout, _, _, timeline = geometry_history()
    validate_resolved_return_history(layout, timeline, layout_sha256=timeline.layout_sha256,
                                     split_inputs=verify_split_paint_inputs(layout, {}))
    raw = timeline.model_dump(mode="json")
    row = raw["actions"][0]
    receipt = row["split_completion_receipt"]
    if fault == "phase":
        row["action"]["split_policy"]["source_exit"]["start_tick"] += 1
    elif fault == "pose":
        receipt["placements"][0]["local_transform"]["position"]["x"] += 1
    elif fault == "state":
        receipt["placements"][0]["state"] = "stale-state"
    else:
        receipt["placements"][0]["state_version"] += 1
    receipt["completion_sha256"] = digest({key: value for key, value in receipt.items() if key != "completion_sha256"})
    with pytest.raises(ValueError, match="Split completion differs"):
        ResolvedVisualTimelineV2.model_validate(raw)


@pytest.mark.parametrize("fault", ["state", "version", "pose", "order"])
def test_aba_rejects_coherently_rehashed_retained_state_and_hierarchy(fault):
    from atme.store.contracts_v2 import ResolvedVisualTimelineV2

    layout, timeline = retained_history("geometry")
    inputs = verify_split_paint_inputs(layout, {})
    validate_resolved_return_history(layout, timeline, layout_sha256=timeline.layout_sha256, split_inputs=inputs)
    raw = timeline.model_dump(mode="json")
    returned = raw["actions"][-1]
    if fault == "state":
        returned["action"]["expected_object_states"]["source"] = "visible"
    elif fault == "version":
        returned["action"]["expected_object_state_versions"]["source"] = 1
    else:
        receipt = returned["return_hierarchy_receipt"]
        placements = receipt["hierarchy_basis"]["placements"]
        if fault == "pose":
            placements[0]["local_transform"]["position"]["x"] += 1
        else:
            placements[0]["sibling_ordinal"], placements[1]["sibling_ordinal"] = (
                placements[1]["sibling_ordinal"], placements[0]["sibling_ordinal"])
        receipt["hierarchy_basis_sha256"] = digest(receipt["hierarchy_basis"])
    forged = ResolvedVisualTimelineV2.model_validate(raw)
    with pytest.raises(ValueError, match="retained board state" if fault in {"state", "version"}
                       else "retained board hierarchy"):
        validate_resolved_return_history(layout, forged, layout_sha256=timeline.layout_sha256, split_inputs=inputs)
