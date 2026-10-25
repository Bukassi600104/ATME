"""Real Split composition must consume the exact replay construction envelope."""

import importlib
import importlib.util
import json
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path

import pytest
from atme.render.v2_split import SplitPaintEnvelope
from atme.render.v2_state import (
    FrameSnapshot,
    SplitFrameSnapshot,
    _sample_validated_frame,
    camera_segments,
)
from atme.store.contracts_v2 import ResolvedVisualTimelineV2
from test_v2_split_action import replay_split
from test_v2_split_capture import geometry_boundary, hidden_result_boundary
from v2_split_fixtures import split_documents


def paint_module():
    name = "atme.render.v2_split_paint"
    assert importlib.util.find_spec(name) is not None, "Split compositor boundary is missing"
    return importlib.import_module(name)


def test_live_capture_retains_exact_owned_and_read_content_receipts():
    from atme.render.v2_split import capture_split
    from atme.render.v2_split_identity import split_content_receipts
    from test_v2_split_capture import ancestor_boundary

    layout, before, split = ancestor_boundary(aperture=True)
    capture = capture_split(split, layout, before, {})
    assert hasattr(capture, "content_receipts"), "Split live paint receipt carrier missing"
    expected = tuple(row for row in split_content_receipts(layout, before, {})
        if row.object_id in {*capture.owned_object_ids, *capture.read_dependency_ids})
    assert capture.content_receipts == expected
    assert "earlier" in {row.object_id for row in capture.content_receipts}


def coverage_boundary(*, portrait=False, gap=None, aperture=False, move_out=False):
    from atme.render.v2_split import capture_split
    from atme.store.contracts_v2 import (
        ResolvedAction,
        SplitPolicy,
        _split_expected_completion,
    )
    from test_v2_split_capture import ancestor_boundary
    from test_v2_split_identity import sample_for_layout
    from v2_fixtures import digest

    if aperture:
        layout, before, split = ancestor_boundary(aperture=True)
    elif portrait:
        layout, timeline, *_ = registry_paint_frames(portrait=True)
        before = sample_for_layout(layout)
        split = timeline.actions[0]
    else:
        layout, before, split = geometry_boundary()
    raw = split.model_dump(mode="json")
    raw["end_ms"] = raw["start_ms"] + 40
    policy = raw["action"]["split_policy"]
    if gap is not None:
        policy["source_exit"].update(start_tick=0, end_tick=5000 if gap == "point" else 4000)
        for row in policy["results"]:
            row["construction"]["phase"].update(start_tick=5000 if gap == "point" else 6000, end_tick=10000)
    if move_out:
        for row in policy["results"]:
            destination = dict(row["destination"])
            destination["position"] = {"x": 300, "y": 0}
            row.update(destination=destination, movement={"phase": {"start_tick": 6000, "end_tick": 10000,
                "easing": "linear"}, "from_transform": row["destination"], "destination": destination})
    completion = _split_expected_completion(SplitPolicy.model_validate(policy))
    completion["completion_sha256"] = digest(completion)
    raw["split_completion_receipt"] = completion
    split = ResolvedAction.model_validate(raw)
    before = replace(before, at_ms=split.start_ms)
    return layout, capture_split(split, layout, before, {})


@pytest.mark.parametrize("portrait", [False, True])
def test_continuous_native_alpha_proof_covers_both_profiles_and_exact_endpoint(portrait):
    from dataclasses import FrozenInstanceError

    module = paint_module()
    assert hasattr(module, "prove_split_coverage"), "Split continuous native alpha proof missing"
    layout, capture = coverage_boundary(portrait=portrait)
    inputs = module.verify_split_paint_inputs(layout, {})
    proof = module.prove_split_coverage(capture, layout, inputs)
    assert proof.proof_kind == "native_alpha_all_integer_ms_v1"
    policy = json.loads(capture.policy_json)
    assert proof.source_basis_sha256 == policy["source_basis_sha256"]
    from atme.render.v2_split_identity import split_policy_digest
    from atme.store.contracts_v2 import SplitPolicy
    assert proof.policy_sha256 == split_policy_digest(SplitPolicy.model_validate_json(capture.policy_json))
    assert proof.paint_inputs_sha256 == inputs.inputs_sha256
    assert proof.critical_times_ms[0] == capture.start_ms and proof.critical_times_ms[-1] == capture.end_ms
    assert all(row.painted_root_ids for row in proof.intervals)
    assert proof.intervals[0].start_ms == capture.start_ms
    assert proof.intervals[-1].end_ms == capture.end_ms
    assert all(a.end_ms == b.start_ms for a, b in zip(proof.intervals, proof.intervals[1:]))
    with pytest.raises(FrozenInstanceError):
        proof.proof_kind = "unchecked"


@pytest.mark.parametrize("gap,blank_ms", [("point", 20), ("span", 16)])
def test_continuity_rejects_exact_blank_handoff_millisecond(gap, blank_ms):
    module = paint_module()
    assert hasattr(module, "prove_split_coverage"), "Split continuous native alpha proof missing"
    layout, capture = coverage_boundary(gap=gap)
    inputs = module.verify_split_paint_inputs(layout, {})
    with pytest.raises(ValueError, match=f"Split.*zero painted coverage.*{blank_ms}"):
        module.prove_split_coverage(capture, layout, inputs)


def test_continuity_rejects_results_moving_out_of_real_ancestor_clip():
    module = paint_module()
    assert hasattr(module, "prove_split_coverage"), "Split continuous native alpha proof missing"
    layout, capture = coverage_boundary(aperture=True, move_out=True)
    inputs = module.verify_split_paint_inputs(layout, {})
    with pytest.raises(ValueError, match="Split.*zero painted coverage"):
        module.prove_split_coverage(capture, layout, inputs)


def test_coverage_rejects_changed_read_aperture_with_fresh_paint_inputs():
    module = paint_module()
    assert hasattr(module, "prove_split_coverage"), "Split continuous native alpha proof missing"
    layout, capture = coverage_boundary(aperture=True)
    next(obj for obj in layout.objects if obj.object_id == "earlier").geometry.bounds.width += 10
    inputs = module.verify_split_paint_inputs(layout, {})
    with pytest.raises(ValueError, match="Split.*captured read content"):
        module.prove_split_coverage(capture, layout, inputs)


def coverage_mask_boundary(*, move_out=False, unrelated=False):
    from copy import deepcopy
    from dataclasses import asdict

    from atme.render.v2_hierarchy import HierarchySnapshot
    from atme.render.v2_split import _observed_split_placements, capture_split
    from atme.render.v2_split_identity import split_content_receipts
    from atme.store.contracts_v2 import (
        ExecutableLayoutV2,
        ResolvedAction,
        SplitPolicy,
        _split_expected_completion,
    )
    from test_v2_split_capture import ancestor_boundary
    from test_v2_split_identity import sample_for_layout
    from v2_fixtures import digest

    layout, before, split = ancestor_boundary(aperture=True)
    raw_layout = layout.model_dump(mode="json")
    mask = next(row for row in raw_layout["objects"] if row["object_id"] == "earlier")
    mask.update(object_type="mask", mask_mode="alpha", mask_source_object_id="mask-source",
                mask_coordinate_space="parent_local", invert=False, feather_px=0, anchors=[],
                style={"stroke": None, "fill": None, "text": None, "effect": None})
    source = deepcopy(next(row for row in raw_layout["objects"] if row["object_id"] == "source"))
    source.update(object_id="mask-source", parent_id=mask["parent_id"], beat_id=mask["beat_id"],
        clip_id=None, z_index=9, anchors=[],
        style={"stroke": None, "fill": None, "text": None, "effect": None},
        transform=asdict(before.object("earlier").transform))
    raw_layout["objects"].append(source)
    raw_layout["boards"][0]["object_ids"].append("mask-source")
    if unrelated:
        extra = deepcopy(source)
        extra.update(object_id="unrelated-sibling", parent_id="earlier", z_index=9)
        raw_layout["objects"].append(extra)
        raw_layout["boards"][0]["object_ids"].append("unrelated-sibling")
        mask["child_ids"].append("unrelated-sibling")
    layout = ExecutableLayoutV2.model_validate(raw_layout)
    objects = {obj.object_id: obj for obj in layout.objects}
    new_frames = tuple(row for row in sample_for_layout(layout).objects if row.object_id not in
                       {frame.object_id for frame in before.objects})
    before = replace(before, objects=tuple(sorted((*before.objects, *new_frames), key=lambda row: row.object_id)),
        state_versions=tuple(sorted((*before.state_versions, *((row.object_id, 1) for row in new_frames)))),
        hierarchy=HierarchySnapshot.from_objects(objects))
    raw = split.model_dump(mode="json")
    raw["end_ms"] = raw["start_ms"] + 40
    policy = raw["action"]["split_policy"]
    policy["source_basis"]["read_dependencies"].append({"kind": "mask_source", "object_ids": ["mask-source"]})
    bound = {"source", "part-1", "part-2", "earlier", "mask-source"}
    receipts = {row.object_id: row for row in split_content_receipts(layout, before, {})}
    policy["source_basis"]["placements"] = [row.model_dump(mode="json") for row in
        _observed_split_placements(before, objects, bound, receipts)]
    for row in policy["correspondences"]:
        row.update(source_content_sha256=receipts["source"].content_sha256,
                   result_content_sha256=receipts[row["result_object_id"]].content_sha256)
    if move_out:
        for row in policy["results"]:
            destination = deepcopy(row["destination"])
            destination["position"] = {"x": 300, "y": 0}
            row.update(destination=destination, movement={"phase": {"start_tick": 6000, "end_tick": 10000,
                "easing": "linear"}, "from_transform": row["destination"], "destination": destination})
    policy["source_basis_sha256"] = digest(policy["source_basis"])
    completion = _split_expected_completion(SplitPolicy.model_validate(policy))
    completion["completion_sha256"] = digest(completion)
    raw["split_completion_receipt"] = completion
    return layout, capture_split(ResolvedAction.model_validate(raw), layout, before, {})


@pytest.mark.parametrize("move_out", [False, True])
def test_coverage_uses_real_alpha_mask_with_unrelated_uncaptured_sibling(move_out):
    module = paint_module()
    layout, capture = coverage_mask_boundary(move_out=move_out, unrelated=True)
    assert "unrelated-sibling" not in {row.object_id for row in capture.baseline}
    ancestor = next(row for row in capture.content_receipts if row.object_id == "earlier")
    assert "unrelated-sibling" in ancestor.canonical_json
    inputs = module.verify_split_paint_inputs(layout, {})
    if move_out:
        with pytest.raises(ValueError, match="Split.*zero painted coverage"):
            module.prove_split_coverage(capture, layout, inputs)
    else:
        proof = module.prove_split_coverage(capture, layout, inputs)
        assert all(row.painted_root_ids for row in proof.intervals)


def test_coverage_uses_frozen_fonts_and_registry_without_reopening_original_bundle(monkeypatch):
    from atme.render.style_bundle import load_bundle

    module = paint_module()
    layout, capture = coverage_boundary(portrait=True)
    inputs = module.verify_split_paint_inputs(layout, {})
    _, _, bundle_root = load_bundle()
    original_open = Path.open
    def checked_open(path, *args, **kwargs):
        assert not path.resolve().is_relative_to(bundle_root.resolve()), "coverage reopened source bundle"
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", checked_open)
    assert module.prove_split_coverage(capture, layout, inputs).paint_inputs_sha256 == inputs.inputs_sha256


def test_coverage_rejects_mutated_live_receipt_without_accepting_its_label():
    module = paint_module()
    layout, capture = coverage_boundary(aperture=True)
    inputs = module.verify_split_paint_inputs(layout, {})
    changed = replace(capture.content_receipts[0], canonical_json="{}")
    forged = replace(capture, content_receipts=(changed, *capture.content_receipts[1:]))
    with pytest.raises(ValueError, match="Split.*paint receipt"):
        module.prove_split_coverage(forged, layout, inputs)


def test_coverage_intervals_record_actual_root_changes_and_authored_phase_boundaries():
    module = paint_module()
    layout, capture = coverage_boundary()
    inputs = module.verify_split_paint_inputs(layout, {})
    proof = module.prove_split_coverage(capture, layout, inputs)
    assert [(row.start_ms, row.end_ms, row.painted_root_ids) for row in proof.intervals] == [
        (0, 1, ("source",)), (1, 32, ("part-1", "part-2", "source")),
        (32, 40, ("part-1", "part-2"))]
    assert proof.critical_times_ms == (0, 1, 8, 24, 32, 40)


def endpoint_coverage_boundary(*, results_outside=False):
    from atme.render.v2_split import capture_split
    from atme.store.contracts_v2 import SplitPolicy, _split_expected_completion
    from test_v2_split_identity import sample_for_layout
    from v2_fixtures import digest

    layout, timeline, _ = geometry_paint_frames()
    resolved = timeline.actions[0]
    policy = resolved.action.split_policy.model_dump(mode="json")
    policy["source_exit"].update(start_tick=0, end_tick=10000)
    if results_outside:
        for row in policy["results"]:
            destination = dict(row["destination"])
            destination["position"] = {"x": 2000, "y": 0}
            row.update(destination=destination, movement={"phase": {"start_tick": 6000, "end_tick": 10000,
                "easing": "linear"}, "from_transform": row["destination"], "destination": destination})
    policy = SplitPolicy.model_validate(policy)
    completion = _split_expected_completion(policy)
    completion["completion_sha256"] = digest(completion)
    from atme.store.contracts_v2 import ResolvedAction
    raw = resolved.model_dump(mode="json")
    raw["end_ms"] = 40
    raw["action"]["split_policy"] = policy.model_dump(mode="json")
    raw["split_completion_receipt"] = completion
    return layout, capture_split(ResolvedAction.model_validate(raw), layout, sample_for_layout(layout), {})


def test_endpoint_root_change_does_not_create_zero_length_coverage_interval():
    module = paint_module()
    layout, capture = endpoint_coverage_boundary()
    proof = module.prove_split_coverage(capture, layout, module.verify_split_paint_inputs(layout, {}))
    assert all(row.start_ms < row.end_ms for row in proof.intervals)
    assert proof.intervals[-1].end_ms == 40
    assert "source" in proof.intervals[-1].painted_root_ids  # valid until the exact endpoint
    assert proof.critical_times_ms[-1] == 40


def test_completed_result_paint_is_checked_at_exact_endpoint_after_source_exit():
    module = paint_module()
    layout, capture = endpoint_coverage_boundary(results_outside=True)
    with pytest.raises(ValueError, match="Split.*zero painted coverage at 40 ms"):
        module.prove_split_coverage(capture, layout, module.verify_split_paint_inputs(layout, {}))


@pytest.mark.parametrize("start,end,roots", [(0, 0, ("source",)), (2, 1, ("source",)),
    (-1, 2, ("source",)), (False, 2, ("source",)), (0, 2, ()), (0, 2, ("source", "source")),
    (0, 2, ("source", "part-1"))])
def test_coverage_interval_rejects_invalid_intrinsic_shape(start, end, roots):
    with pytest.raises(ValueError, match="Split coverage interval"):
        paint_module().SplitCoverageInterval(start, end, roots)


@pytest.mark.parametrize("fault", ["duplicate_times", "gap", "empty", "wrong_bounds", "bad_digest"])
def test_coverage_proof_rejects_invalid_intrinsic_shape(fault):
    module = paint_module()
    intervals = (module.SplitCoverageInterval(0, 40, ("source",)),)
    times = (0, 40)
    if fault == "duplicate_times":
        times = (0, 20, 20, 40)
    elif fault == "gap":
        intervals = (module.SplitCoverageInterval(0, 10, ("source",)), module.SplitCoverageInterval(20, 40, ("source",)))
    elif fault == "empty":
        intervals = ()
    elif fault == "wrong_bounds":
        times = (0, 41)
    with pytest.raises(ValueError, match="Split coverage proof"):
        module.SplitCoverageProof("native_alpha_all_integer_ms_v1", "invalid" if fault == "bad_digest" else "a"*64,
            "b"*64, "c"*64, times, intervals)


@pytest.mark.parametrize("compound", [False, True])
@pytest.mark.parametrize("portrait", [False, True])
def test_coverage_uses_real_written_graphemes_and_compound_local_children(compound, portrait):
    from atme.render.v2_split import capture_split
    from test_v2_split_identity import sample_for_layout

    module = paint_module()
    layout, timeline, _ = text_paint_frames(compound=compound, portrait=portrait)
    resolved = timeline.actions[0].model_copy(update={"end_ms": 40})
    capture = capture_split(resolved, layout, sample_for_layout(layout), {})
    initial = repr(capture.baseline)
    proof = module.prove_split_coverage(capture, layout, module.verify_split_paint_inputs(layout, {}))
    assert all(row.painted_root_ids for row in proof.intervals)
    assert proof.intervals[-1].painted_root_ids == ("part-1", "part-2")
    assert repr(capture.baseline) == initial


@pytest.mark.parametrize("partial", [False, True])
def test_shared_object_tree_has_real_transparent_root_paint_without_other_roots(partial):
    import io

    import resvg_py
    from atme.render import v2_svg
    from PIL import Image

    assert hasattr(v2_svg, "_compose_object_tree"), "Split shared transparent tree renderer missing"
    layout, timeline, frames = geometry_paint_frames()
    inputs = paint_module().verify_split_paint_inputs(layout, {})
    resources = paint_module()._checked_split_resources(layout, inputs)
    for index, selected, should_paint in ((0, "part-1", False), (1, "part-1", True), (2, "source", False)):
        snapshot = frames[index]
        objects = snapshot.hierarchy.object_map({obj.object_id: obj for obj in layout.objects})
        states = {row.object_id: row for row in snapshot.objects}
        ordinals = {row.object_id: row.sibling_ordinal for row in snapshot.hierarchy.nodes}
        envelopes = paint_module()._split_active_paint_modes(snapshot, timeline, objects)
        if partial:
            # Captured coverage has no states/ordinals for unrelated siblings.
            states = {selected: states[selected]}
            ordinals = {selected: ordinals[selected]}
        definitions, body = v2_svg._compose_object_tree(objects, states, ordinals, resources[0], None,
            1280 / resources[0].aspects["landscape-16:9"].width,
            {key: value.mode for key, value in envelopes.items()}, {}, {}, envelopes,
            resources, included_ids=frozenset({selected}))
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720"><defs>{definitions}</defs>{body}</svg>'
        with Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=svg, skip_system_fonts=True))) as image:
            rgba = image.convert("RGBA")
        assert (rgba.getchannel("A").getbbox() is not None) is should_paint
        assert rgba.getpixel((500, 500))[3] == 0
        if should_paint:
            assert rgba.getpixel((20, 10)) == (23, 32, 51, 255)
            assert rgba.getpixel((10, 25))[3] == 0  # no fully drawn source underneath


@pytest.mark.parametrize("aperture", [False, True])
def test_shared_object_tree_keeps_actual_transformed_ancestor_clip(aperture):
    import io

    import resvg_py
    from atme.render import v2_svg
    from PIL import Image
    from test_v2_split_capture import ancestor_boundary

    assert hasattr(v2_svg, "_compose_object_tree"), "Split shared transparent tree renderer missing"
    layout, before, _ = ancestor_boundary(aperture=aperture)
    inputs = paint_module().verify_split_paint_inputs(layout, {})
    resources = paint_module()._checked_split_resources(layout, inputs)
    objects = before.hierarchy.object_map({obj.object_id: obj for obj in layout.objects})
    definitions, body = v2_svg._compose_object_tree(objects,
        {row.object_id: row for row in before.objects},
        {row.object_id: row.sibling_ordinal for row in before.hierarchy.nodes},
        resources[0], None, 1280 / resources[0].aspects["landscape-16:9"].width,
        {}, {}, {}, {}, resources, included_ids=frozenset({"source", "earlier"}))
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720"><defs>{definitions}</defs>{body}</svg>'
    with Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=svg, skip_system_fonts=True))) as image:
        alpha = image.convert("RGBA").getchannel("A")
    assert alpha.getpixel((110, 70)) > 0
    assert (alpha.getpixel((109, 70)) == 0) is aperture
    assert alpha.getpixel((500, 500)) == 0


@pytest.mark.parametrize("at_ms", [0, 180, 270, 540, 720, 900, 1000])
def test_coverage_sampler_reuses_exact_replay_without_fabricated_action_identity(at_ms):
    from atme.render import v2_split
    from atme.render.v2_timeline_replay import _capture_split_from_history

    assert hasattr(v2_split, "_sample_split_paint"), "Split shared coverage sampler missing"
    layout, before, split = geometry_boundary()
    base = v2_split.capture_split(split, layout, before, {})
    attributed = _capture_split_from_history(layout, before, (split,), 0, 2000, {}).split_capture
    original = repr(base)
    actual = v2_split._sample_split_paint(base, at_ms)
    replay = v2_split.sample_split(attributed, at_ms)
    assert actual.objects == replay.objects
    assert [(row.root_id, row.mode, row.construction_fraction) for row in actual.constructions] == [
        (row.root_id, row.mode, row.construction_fraction) for row in replay.envelopes]
    assert all(not hasattr(row, "action_id") for row in actual.constructions)
    assert repr(base) == original
    # The shared internal math must not weaken public/history attribution.
    with pytest.raises(ValueError, match="attributed history"):
        v2_split.sample_split(base, at_ms)


@pytest.mark.parametrize("family", ["geometry", "text", "registry illustration", "compound"])
def test_family_admission_binds_captured_content_and_authored_mode(family):
    from dataclasses import FrozenInstanceError

    from atme.render.v2_split import capture_split
    from test_v2_split_identity import sample_for_layout

    module = paint_module()
    assert hasattr(module, "split_family_admission"), "Split capture-bound family admission missing"
    if family == "registry illustration":
        layout, timeline, *_ = registry_paint_frames(portrait=True)
    elif family == "text":
        layout, timeline, _ = text_paint_frames(compound=False, portrait=False)
    else:
        layout, timeline, _ = geometry_paint_frames(compound=family == "compound")
    capture = capture_split(timeline.actions[0], layout, sample_for_layout(layout), {})
    before = repr(capture)
    inputs = module.verify_split_paint_inputs(layout, {})
    receipt = module.split_family_admission("part-1", capture, layout, inputs)
    placement = next(row for row in json.loads(capture.basis_json)["placements"] if row["object_id"] == "part-1")
    result = next(row for row in json.loads(capture.policy_json)["results"] if row["object_id"] == "part-1")
    assert receipt.family == family
    assert receipt.mode == result["construction"]["mode"]
    assert receipt.content_sha256 == placement["content_sha256"]
    assert receipt.paint_inputs_sha256 == inputs.inputs_sha256
    assert receipt.proof_kind == {"geometry": "native_path_alpha_v1", "text": "pinned_font_rendered_alpha_v1",
        "registry illustration": "pinned_registry_alpha_v1", "compound": "captured_compound_closure_v1"}[family]
    source = module.split_family_admission("source", capture, layout, inputs)
    assert source.mode == "source_fade"
    module.validate_split_paint(capture, layout, inputs)
    assert repr(capture) == before
    with pytest.raises(FrozenInstanceError):
        receipt.mode = "enter"


@pytest.mark.parametrize("compound", [False, True])
def test_family_admission_rejects_changed_captured_payload_even_with_fresh_inputs(compound):
    from atme.render.v2_split import capture_split

    module = paint_module()
    assert hasattr(module, "split_family_admission"), "Split capture-bound family admission missing"
    layout, before, split = hidden_result_boundary() if compound else geometry_boundary()
    capture = capture_split(split, layout, before, {})
    key = "child" if compound else "part-1"
    next(obj for obj in layout.objects if obj.object_id == key).geometry.bounds.width += 10
    inputs = module.verify_split_paint_inputs(layout, {})
    with pytest.raises(ValueError, match="Split.*captured content"):
        module.split_family_admission("part-1", capture, layout, inputs)


def test_family_admission_rejects_read_dependency_as_owned_paint():
    from atme.render.v2_split import capture_split
    from test_v2_split_capture import ancestor_boundary

    module = paint_module()
    assert hasattr(module, "split_family_admission"), "Split capture-bound family admission missing"
    layout, before, split = ancestor_boundary()
    capture = capture_split(split, layout, before, {})
    inputs = module.verify_split_paint_inputs(layout, {})
    with pytest.raises(ValueError, match="Split.*owned closure"):
        module.split_family_admission("earlier", capture, layout, inputs)
    # The same read ancestor must not force fabricated full-layout state.
    module.validate_split_paint(capture, layout, inputs)


def test_family_admission_checks_every_compound_leaf_mode():
    from atme.render.v2_split import capture_split
    from atme.store.contracts_v2 import (
        ResolvedAction,
        SplitPolicy,
        _split_expected_completion,
    )
    from test_v2_split_identity import sample_for_layout
    from v2_fixtures import digest

    module = paint_module()
    assert hasattr(module, "split_family_admission"), "Split capture-bound family admission missing"
    layout, timeline, _ = text_paint_frames(compound=True, portrait=False)
    raw = timeline.actions[0].model_dump(mode="json")
    next(row for row in raw["action"]["split_policy"]["results"] if row["object_id"] == "part-1")["construction"]["mode"] = "draw"
    completion = _split_expected_completion(SplitPolicy.model_validate(raw["action"]["split_policy"]))
    completion["completion_sha256"] = digest(completion)
    raw["split_completion_receipt"] = completion
    capture = capture_split(ResolvedAction.model_validate(raw), layout, sample_for_layout(layout), {})
    inputs = module.verify_split_paint_inputs(layout, {})
    with pytest.raises(ValueError, match="Split.*draw.*text"):
        module.split_family_admission("part-1", capture, layout, inputs)


def test_local_leaf_admission_does_not_admit_unsupported_sibling_or_whole_split():
    from copy import deepcopy

    from atme.render.v2_split import _observed_split_placements, capture_split
    from atme.render.v2_split_identity import split_content_receipts
    from atme.store.contracts_v2 import (
        ExecutableLayoutV2,
        ResolvedAction,
        SplitPolicy,
        _split_expected_completion,
    )
    from test_v2_split_identity import sample_for_layout
    from v2_fixtures import digest

    module = paint_module()
    layout, _, split = hidden_result_boundary()
    raw = layout.model_dump(mode="json")
    child = deepcopy(next(row for row in raw["objects"] if row["object_id"] == "child"))
    child.pop("path_data")
    child.update(object_id="text-sibling", object_type="text", text="AB", items=[], z_index=1,
                 style={"stroke": None, "fill": None, "text": "text.body", "effect": None})
    child["geometry"]["bounds"] = {"x": 100, "y": 100, "width": 320, "height": 120}
    raw["objects"].append(child)
    raw["boards"][0]["object_ids"].append("text-sibling")
    next(row for row in raw["objects"] if row["object_id"] == "part-1")["child_ids"].append("text-sibling")
    layout = ExecutableLayoutV2.model_validate(raw)
    before = sample_for_layout(layout)
    receipts = {row.object_id: row for row in split_content_receipts(layout, before, {})}
    action = split.model_dump(mode="json")
    policy = action["action"]["split_policy"]
    basis = policy["source_basis"]
    next(row for row in basis["result_closures"] if row["root_id"] == "part-1")["owned_ids"].append("text-sibling")
    objects = {obj.object_id: obj for obj in layout.objects}
    basis["placements"] = [row.model_dump(mode="json") for row in
        _observed_split_placements(before, objects, set(objects), receipts)]
    for row in policy["correspondences"]:
        row.update(source_content_sha256=receipts["source"].content_sha256,
                   result_content_sha256=receipts[row["result_object_id"]].content_sha256)
    next(row for row in policy["results"] if row["object_id"] == "part-1")["construction"]["mode"] = "draw"
    policy["source_basis_sha256"] = digest(basis)
    completion = _split_expected_completion(SplitPolicy.model_validate(policy))
    completion["completion_sha256"] = digest(completion)
    action["split_completion_receipt"] = completion
    capture = capture_split(ResolvedAction.model_validate(action), layout, before, {})
    inputs = module.verify_split_paint_inputs(layout, {})
    local = module.split_family_admission("child", capture, layout, inputs)
    assert (local.family, local.mode, local.content_sha256) == (
        "geometry", "draw", receipts["child"].content_sha256)
    with pytest.raises(ValueError, match="Split.*draw.*text"):
        module.split_family_admission("part-1", capture, layout, inputs)
    with pytest.raises(ValueError, match="Split.*draw.*text"):
        module.validate_split_paint(capture, layout, inputs)


def geometry_paint_frames(mode="draw", *, compound=False):
    from atme.store.contracts_v2 import (
        ResolvedAction,
        SplitPolicy,
        _split_expected_completion,
    )
    from v2_fixtures import digest

    layout, initial, split = hidden_result_boundary() if compound else geometry_boundary()
    raw_action = split.model_dump(mode="json")
    policy = raw_action["action"]["split_policy"]
    for result in policy["results"]:
        result["construction"]["mode"] = mode
    receipt = _split_expected_completion(SplitPolicy.model_validate(policy))
    receipt["completion_sha256"] = digest(receipt)
    raw_action["split_completion_receipt"] = receipt
    split = ResolvedAction.model_validate(raw_action)
    _, _, raw = split_documents()
    raw["actions"] = [raw_action]
    raw["initial_object_states"] = [
        {"object_id": frame.object_id, "state": frame.state,
         "state_version": dict(initial.state_versions)[frame.object_id], "visible": frame.visible}
        for frame in initial.objects
    ]
    timeline = ResolvedVisualTimelineV2.model_validate(raw)
    replay = replay_split(layout, initial, (split,), duration=timeline.duration_ms)
    camera = camera_segments(layout, timeline, replay)
    frames = tuple(_sample_validated_frame(layout, timeline, replay, camera, at) for at in (0, 270, 900))
    return layout, timeline, frames


def test_geometry_split_draw_uses_real_stroke_pixels_not_reveal_wipe():
    import io
    import xml.etree.ElementTree as ET

    from atme.render.v2_svg import _compose_validated_svg_frame, _rasterize_svg_frame
    from PIL import Image

    layout, timeline, frames = geometry_paint_frames()
    originals = tuple(repr(frame) for frame in frames)
    inputs = paint_module().verify_split_paint_inputs(layout, {})
    outputs = [_compose_validated_svg_frame(layout, timeline, frame, {}, split_inputs=inputs) for frame in frames]
    mid = ET.fromstring(outputs[1].svg)
    groups = [node for node in mid.iter() if node.attrib.get("data-object-id") in {"part-1", "part-2"}]
    assert [node.attrib["data-object-id"] for node in groups] == ["part-1", "part-2"]
    for group in groups:
        assert "clip-path" not in group.attrib
        stroke = next(iter(group))
        assert stroke.attrib["stroke-dasharray"] == "80 80"
        assert stroke.attrib["stroke-dashoffset"] == "40"
        assert stroke.attrib["fill"] == "none"
    images = [Image.open(io.BytesIO(_rasterize_svg_frame(layout, output, split_inputs=inputs).png)).convert("RGB")
              for output in outputs]
    ink = (23, 32, 51)
    # A half-drawn rectangle follows its top/right perimeter, not a left-half wipe.
    assert images[1].getpixel((20, 10)) == ink
    assert images[1].getpixel((10, 25)) != ink
    assert images[0].getpixel((10, 25)) == images[2].getpixel((10, 25)) == ink
    assert tuple(repr(frame) for frame in frames) == originals


def test_geometry_split_rejects_write_instead_of_silently_revealing():
    from atme.render.v2_svg import _compose_validated_svg_frame

    layout, timeline, frames = geometry_paint_frames("write")
    with pytest.raises(ValueError, match="Split.*write.*geometry"):
        _compose_validated_svg_frame(layout, timeline, frames[1], {},
                                     split_inputs=paint_module().verify_split_paint_inputs(layout, {}))


@pytest.mark.parametrize("mode", ["draw", "reveal"])
def test_compound_construction_preserves_child_state_and_paints_root_envelope(mode):
    import xml.etree.ElementTree as ET

    from atme.render.v2_svg import _compose_validated_svg_frame

    layout, timeline, frames = geometry_paint_frames(mode, compound=True)
    snapshot = frames[1]
    original = repr(snapshot)
    assert snapshot.object("child").reveal_fraction == 1
    frame = _compose_validated_svg_frame(layout, timeline, snapshot, {},
                                         split_inputs=paint_module().verify_split_paint_inputs(layout, {}))
    groups = {node.attrib["data-object-id"]: node for node in ET.fromstring(frame.svg).iter()
              if "data-object-id" in node.attrib}
    child_shape = next(iter(groups["child"]))
    if mode == "draw":
        assert child_shape.attrib["stroke-dashoffset"] == "40"
        assert "clip-path" not in groups["part-1"].attrib
    else:
        assert "clip-path" in next(iter(groups["part-1"])).attrib
        assert "stroke-dasharray" not in child_shape.attrib
    assert repr(snapshot) == original


def test_compositor_rejects_envelope_not_bound_to_resolved_split():
    from atme.render.v2_svg import _compose_validated_svg_frame

    layout, timeline, frames = geometry_paint_frames()
    snapshot = frames[1]
    bad = replace(snapshot, envelopes=(replace(snapshot.envelopes[0], construction_fraction=.1),
                                       *snapshot.envelopes[1:]))
    with pytest.raises(ValueError, match="Split.*resolved construction"):
        _compose_validated_svg_frame(layout, timeline, bad, {},
                                     split_inputs=paint_module().verify_split_paint_inputs(layout, {}))


def text_paint_frames(*, compound, portrait):
    from atme.render.v2_split_identity import split_content_receipts
    from atme.store.contracts_v2 import (
        ExecutableLayoutV2,
        ResolvedAction,
        SplitPolicy,
        _split_expected_completion,
    )
    from test_v2_split_identity import sample_for_layout
    from v2_fixtures import digest

    layout, _, split = hidden_result_boundary() if compound else geometry_boundary()
    raw = layout.model_dump(mode="json")
    profile = "SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9"
    _, _, timeline = split_documents(profile)
    raw["output_profile"] = timeline["output_profile"]
    raw["canvas"] = {"x": 0, "y": 0, "width": 720 if portrait else 1280,
                     "height": 1280 if portrait else 720}
    for obj in raw["objects"]:
        if obj["object_id"] == "source":
            continue
        second = obj["object_id"] == "part-2"
        obj["geometry"]["bounds"] = {"x": 100 if portrait or not second else 600,
                                       "y": 330 if portrait and second else 100,
                                       "width": 320, "height": 120}
        if obj["object_type"] == "group":
            continue
        obj.pop("path_data")
        obj.update(object_type="text", text="CD" if second else "A\u0301B", items=[],
                   style={"stroke": None, "fill": None, "text": "text.body", "effect": None})
    layout = ExecutableLayoutV2.model_validate(raw)
    initial = sample_for_layout(layout)
    raw_action = split.model_dump(mode="json")
    policy = raw_action["action"]["split_policy"]
    basis = policy["source_basis"]
    contents = {row.object_id: row.content_sha256 for row in split_content_receipts(layout, initial, {})}
    objects = {obj.object_id: obj for obj in layout.objects}
    for placement in basis["placements"]:
        bounds = objects[placement["object_id"]].geometry.bounds.model_dump(mode="json")
        x, y, w, h = (bounds[name] for name in ("x", "y", "width", "height"))
        placement.update(local_content_bounds=bounds, world_bounds=dict(bounds),
                         world_corners=[{"x": a, "y": b} for a, b in ((x, y), (x+w, y), (x+w, y+h), (x, y+h))],
                         content_sha256=contents[placement["object_id"]])
    for correspondence in policy["correspondences"]:
        correspondence.update(source_content_sha256=contents["source"],
                              result_content_sha256=contents[correspondence["result_object_id"]])
    for result in policy["results"]:
        result["construction"]["mode"] = "write"
    policy["source_basis_sha256"] = digest(basis)
    receipt = _split_expected_completion(SplitPolicy.model_validate(policy))
    receipt["completion_sha256"] = digest(receipt)
    raw_action["split_completion_receipt"] = receipt
    split = ResolvedAction.model_validate(raw_action)
    timeline["actions"] = [raw_action]
    timeline["initial_object_states"] = [
        {"object_id": frame.object_id, "state": frame.state, "state_version": 1, "visible": frame.visible}
        for frame in initial.objects]
    timeline = ResolvedVisualTimelineV2.model_validate(timeline)
    replay = replay_split(layout, initial, (split,), duration=timeline.duration_ms)
    cameras = camera_segments(layout, timeline, replay)
    return layout, timeline, tuple(_sample_validated_frame(layout, timeline, replay, cameras, at)
                                   for at in (0, 270, 900))


def registry_paint_frames(*, portrait):
    from atme.render.v2_split_identity import split_content_receipts
    from atme.store.contracts_v2 import (
        ExecutableLayoutV2,
        ResolvedAction,
        SplitPolicy,
        _split_expected_completion,
    )
    from test_v2_split_identity import sample_for_layout
    from v2_fixtures import digest

    layout, _, split = geometry_boundary()
    raw = layout.model_dump(mode="json")
    _, _, timeline = split_documents("SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9")
    raw["output_profile"] = timeline["output_profile"]
    raw["canvas"] = {"x": 0, "y": 0, "width": 720 if portrait else 1280,
                     "height": 1280 if portrait else 720}
    boxes = ({"source": (180, 100, 280, 240), "part-1": (120, 420, 300, 250),
              "part-2": (250, 510, 300, 250)} if portrait else
             {"source": (80, 120, 280, 240), "part-1": (420, 210, 300, 250),
              "part-2": (550, 300, 300, 250)})
    variants = {"source": "person-presenter", "part-1": "device-laptop", "part-2": "document-stack"}
    for obj in raw["objects"]:
        obj.pop("path_data")
        obj.update(object_type="icon", variant=variants[obj["object_id"]],
                   style={"stroke": None, "fill": None, "text": None, "effect": None})
        obj["geometry"]["bounds"] = dict(zip(("x", "y", "width", "height"), boxes[obj["object_id"]], strict=True))
    layout = ExecutableLayoutV2.model_validate(raw)
    initial = sample_for_layout(layout)
    raw_action = split.model_dump(mode="json")
    policy = raw_action["action"]["split_policy"]
    contents = {item.object_id: item.content_sha256 for item in split_content_receipts(layout, initial, {})}
    for placement in policy["source_basis"]["placements"]:
        x, y, w, h = map(float, boxes[placement["object_id"]])
        bounds = dict(zip(("x", "y", "width", "height"), (x, y, w, h), strict=True))
        placement.update(local_content_bounds=bounds, world_bounds=dict(bounds),
                         world_corners=[{"x": a, "y": b} for a, b in ((x, y), (x+w, y), (x+w, y+h), (x, y+h))],
                         content_sha256=contents[placement["object_id"]])
    for correspondence in policy["correspondences"]:
        correspondence.update(source_content_sha256=contents["source"],
                              result_content_sha256=contents[correspondence["result_object_id"]])
    # Semantic result order is intentionally the opposite of captured paint order.
    policy["results"].reverse()
    policy["correspondences"].reverse()
    policy["source_basis"]["result_closures"].reverse()
    policy["source_basis_sha256"] = digest(policy["source_basis"])
    receipt = _split_expected_completion(SplitPolicy.model_validate(policy))
    receipt["completion_sha256"] = digest(receipt)
    raw_action["split_completion_receipt"] = receipt
    timeline["actions"] = [raw_action]
    timeline["initial_object_states"] = [{"object_id": frame.object_id, "state": frame.state,
        "state_version": 1, "visible": frame.visible} for frame in initial.objects]
    timeline = ResolvedVisualTimelineV2.model_validate(timeline)
    replay = replay_split(layout, initial, (ResolvedAction.model_validate(raw_action),), duration=timeline.duration_ms)
    cameras = camera_segments(layout, timeline, replay)
    return layout, timeline, tuple(_sample_validated_frame(layout, timeline, replay, cameras, at)
                                   for at in (0, 270, 900)), boxes, variants


@pytest.mark.parametrize("portrait", [False, True])
def test_source_fade_and_authored_registry_results_have_real_pixels(portrait):
    import io
    import xml.etree.ElementTree as ET

    import resvg_py
    from atme.render.v2_svg import _compose_validated_svg_frame, _rasterize_svg_frame
    from PIL import Image

    layout, timeline, frames, boxes, variants = registry_paint_frames(portrait=portrait)
    inputs = paint_module().verify_split_paint_inputs(layout, {})
    original = repr(frames)
    outputs = [_compose_validated_svg_frame(layout, timeline, frame, {}, split_inputs=inputs) for frame in frames]
    colors = json.loads(inputs.style_json)["colors"]
    assets = {item["id"]: item for item in json.loads(inputs.registry_json)["assets"]}
    payloads = {name: payload for name, _, payload in inputs.bundle_bytes}
    width, height = layout.output_profile.width, layout.output_profile.height
    # Independent SVG oracle: literal pinned originals and authored placement,
    # no compositor, Split sampler, registry sanitizer, or interpolation helper.
    for index, (fraction, source_alpha) in enumerate(((0, 1), (.5, .8333), (1, 0))):
        body = [f'<rect width="{width}" height="{height}" fill="#FAF8F1"/>']
        for key in ("source", "part-1", "part-2"):
            reveal, alpha = (1, source_alpha) if key == "source" else (fraction, 1)
            if not reveal or not alpha:
                continue
            asset = assets[variants[key]]
            x, y, w, h = boxes[key]
            original_svg = ET.fromstring(payloads[asset["file"]])
            inner = "".join(ET.tostring(child, encoding="unicode") for child in original_svg)
            for token, value in colors.items():
                inner = inner.replace(f"var(--{token})", value)
            view = " ".join(str(n) for n in asset["view_box"])
            body.append(f'<defs><clipPath id="oracle-{key}"><rect x="{x}" y="{y}" '
                        f'width="{w * reveal}" height="{h}"/></clipPath></defs>'
                        f'<g opacity="{alpha}" clip-path="url(#oracle-{key})">'
                        f'<svg x="{x}" y="{y}" width="{w}" height="{h}" viewBox="{view}" '
                        f'preserveAspectRatio="xMidYMid meet">{inner}</svg></g>')
        expected_svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">' + "".join(body) + '</svg>'
        expected = Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=expected_svg, skip_system_fonts=True))).convert("RGBA")
        actual = Image.open(io.BytesIO(_rasterize_svg_frame(layout, outputs[index], split_inputs=inputs).png)).convert("RGBA")
        assert actual.tobytes() == expected.tobytes()
        assert any(pixel[:3] != (250, 248, 241) for pixel in actual.get_flattened_data())
    midpoint_order = [node.attrib["data-object-id"] for node in ET.fromstring(outputs[1].svg).iter()
                      if "data-object-id" in node.attrib]
    assert midpoint_order == ["source", "part-1", "part-2"]
    assert [row.object_id for row in timeline.actions[0].action.split_policy.results] == ["part-2", "part-1"]
    assert len({output.svg for output in outputs}) == 3
    assert repr(frames) == original


@pytest.mark.parametrize("family", ["geometry", "text", "registry illustration"])
def test_verified_inputs_include_adapter_generated_primitive_paint_evidence(family):
    if family == "geometry":
        layout, _, _ = geometry_paint_frames()
    elif family == "text":
        layout, _, _ = text_paint_frames(compound=False, portrait=False)
    else:
        layout, _, _, _, _ = registry_paint_frames(portrait=False)
    inputs = paint_module().verify_split_paint_inputs(layout, {})
    rows = [json.loads(row) for row in inputs.paint_evidence]
    evidence = next((row for row in rows if row.get("object_id") == "part-1"), None)
    assert evidence is not None, "Split primitive paint evidence is missing"
    assert evidence["family"] == family
    assert evidence["proof_kind"] and evidence["paint"]
    assert inputs.inputs_sha256 == sha256(inputs.manifest_json.encode()).hexdigest()


@pytest.mark.parametrize("empty", ["glyph", "path", "rounded_to_zero"])
def test_nonempty_bounds_do_not_attest_empty_primitive_paint(empty):
    if empty == "glyph":
        layout, _, _ = text_paint_frames(compound=False, portrait=False)
        next(obj for obj in layout.objects if obj.object_id == "part-1").text = "\u200b"
    else:
        from atme.store.contracts_v2 import ExecutableLayoutV2

        layout, _, _ = geometry_paint_frames()
        raw = layout.model_dump(mode="json")
        obj = next(obj for obj in raw["objects"] if obj["object_id"] == "part-1")
        if empty == "path":
            obj["object_type"] = "line"
            obj["style"]["fill"] = None
            obj["geometry"]["points"] = [{"x": 15, "y": 15}, {"x": 15, "y": 15}]
        else:
            obj["geometry"]["bounds"].update(width=1e-7, height=1e-7)
        layout = ExecutableLayoutV2.model_validate(raw)
    with pytest.raises(ValueError, match="(Split.*paint|zero length)"):
        paint_module().verify_split_paint_inputs(layout, {})


@pytest.mark.parametrize("compound", [False, True])
@pytest.mark.parametrize("portrait", [False, True])
def test_split_write_paints_whole_authored_grapheme_pixels(compound, portrait):
    import io
    import xml.etree.ElementTree as ET

    import resvg_py
    from atme.render.style_bundle import load_bundle
    from atme.render.v2_svg import _compose_validated_svg_frame, _rasterize_svg_frame
    from PIL import Image

    layout, timeline, frames = text_paint_frames(compound=compound, portrait=portrait)
    original = repr(frames)
    inputs = paint_module().verify_split_paint_inputs(layout, {})
    outputs = [_compose_validated_svg_frame(layout, timeline, frame, {}, split_inputs=inputs) for frame in frames]
    key = "child" if compound else "part-1"
    groups = {node.attrib["data-object-id"]: node for node in ET.fromstring(outputs[1].svg).iter()
              if "data-object-id" in node.attrib}
    assert "".join(groups[key].itertext()) == "A\u0301"
    assert "clip-path" not in groups[key].attrib
    style, _, root = load_bundle()
    font = next(item for item in style.fonts if item.id == style.typography.body.font_id)
    # Independent literal whole-glyph oracle, without the Split or text-construction helpers.
    design = style.aspects["portrait-9:16" if portrait else "landscape-16:9"]
    size = style.typography.body.size_px * layout.output_profile.width / design.width
    expected_svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{layout.output_profile.width}" '
                    f'height="{layout.output_profile.height}"><rect width="100%" height="100%" fill="#FAF8F1"/>'
                    f'<text x="100" y="{100+size}" fill="#172033" font-family="{font.family}" '
                    f'font-weight="{font.weight}" font-size="{size}">A\u0301</text></svg>')
    expected = Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=expected_svg,
                         font_files=[str(root / font.file)], skip_system_fonts=True))).convert("RGB")
    actual = Image.open(io.BytesIO(_rasterize_svg_frame(layout, outputs[1], split_inputs=inputs).png)).convert("RGB")
    region = (98, 98, 422, 222)
    assert actual.crop(region).tobytes() == expected.crop(region).tobytes()
    assert any(pixel != (250, 248, 241) for pixel in actual.crop(region).get_flattened_data())
    assert "A\u0301B" in outputs[2].svg
    assert repr(frames) == original


def test_split_compositor_consumes_frozen_fonts_without_reopening_bundle(monkeypatch):
    import inspect

    import resvg_py
    from atme.render.style_bundle import load_bundle
    from atme.render.v2_svg import _compose_validated_svg_frame, _rasterize_svg_frame

    assert "split_inputs" in inspect.signature(_compose_validated_svg_frame).parameters, "Split frozen input consumer missing"
    assert "split_inputs" in inspect.signature(_rasterize_svg_frame).parameters, "Split frozen raster input missing"
    layout, timeline, frames = text_paint_frames(compound=True, portrait=True)
    inputs = paint_module().verify_split_paint_inputs(layout, {})
    reference_svg = _compose_validated_svg_frame(layout, timeline, frames[1], {}, split_inputs=inputs)
    reference_png = _rasterize_svg_frame(layout, reference_svg, split_inputs=inputs)
    _, _, root = load_bundle()
    original_open = Path.open

    def no_bundle_read(path, *args, **kwargs):
        assert not path.resolve().is_relative_to(root.resolve()), "renderer reopened mutable bundle files"
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", no_bundle_read)
    rasterize = resvg_py.svg_to_bytes
    observed_paths = []
    payloads = {name: payload for name, _, payload in inputs.bundle_bytes}

    def checked_rasterize(**kwargs):
        assert kwargs["skip_system_fonts"] is True
        # Primitive path/registry alpha checks need no fonts. Actual glyph
        # checks and final composition must still use the frozen font files.
        if "<text" in kwargs["svg_string"]:
            assert kwargs.get("font_files")
        for name in kwargs.get("font_files", ()):
            path = Path(name)
            assert not path.resolve().is_relative_to(root.resolve())
            assert path.read_bytes() == payloads["fonts/" + path.name]
            observed_paths.append(path)
        return rasterize(**kwargs)

    monkeypatch.setattr(resvg_py, "svg_to_bytes", checked_rasterize)
    actual_svg = _compose_validated_svg_frame(layout, timeline, frames[1], {}, split_inputs=inputs)
    actual_png = _rasterize_svg_frame(layout, actual_svg, split_inputs=inputs)
    assert actual_svg == reference_svg and actual_png == reference_png
    assert observed_paths and all(not path.exists() for path in observed_paths)


@pytest.mark.parametrize("frame_index", [0, 1, 2])
def test_split_compositor_requires_frozen_inputs_before_during_and_after(frame_index):
    from atme.render.v2_svg import _compose_validated_svg_frame

    layout, timeline, frames = geometry_paint_frames()
    with pytest.raises(ValueError, match="Split.*frozen paint inputs"):
        _compose_validated_svg_frame(layout, timeline, frames[frame_index], {})


@pytest.mark.parametrize("kind", ["registry", "image", "evidence"])
def test_frozen_resource_consumers_match_existing_pixels_without_source_reads(tmp_path, monkeypatch, kind):
    """Resource parity only: this does not admit these families to Split."""
    from atme import project_assets
    from atme.render.v2_state import evaluate_frame
    from atme.render.v2_svg import _compose_validated_svg_frame, _rasterize_svg_frame
    from atme.store.contracts_v2 import ExecutableLayoutV2
    from test_v2_evidence_compositor import evidence_documents
    from test_v2_project_image import _documents
    from test_v2_registry_illustrations import illustration_documents

    service = None
    if kind == "registry":
        raw_layout, raw_timeline = illustration_documents()
        # The shared legacy fixture retains an unused project asset. Frozen
        # inputs intentionally require the exact inventory actually consumed.
        raw_timeline["resolved_assets"] = []
        layout = ExecutableLayoutV2.model_validate(raw_layout)
        carrier = {}
    elif kind == "image":
        service, layout, resolved, pins, payload = owned_image_inputs(tmp_path)
        raw_layout, raw_timeline = _documents(pins[0]["asset_id"], payload, pins[0]["revision"], layout.project_id)
        carrier = project_assets.read_verified_split_asset_bytes(service, layout, resolved, pins)
    else:
        service, raw_layout, raw_timeline, _ = evidence_documents(tmp_path)
        layout = ExecutableLayoutV2.model_validate(raw_layout)
        owned = service.list_assets(layout.project_id)[0]
        pins = [{"asset_id": owned["asset_id"], "revision": owned["revision"],
                 "resource_uri": owned["resource_uri"], "checksum_sha256": owned["sha256"]}]
        carrier = project_assets.read_verified_split_asset_bytes(service, layout, raw_timeline["resolved_assets"], pins)
    try:
        timeline = ResolvedVisualTimelineV2.model_validate(raw_timeline)
        snapshot = evaluate_frame(raw_layout, raw_timeline, 5000)
        expected_svg = _compose_validated_svg_frame(layout, timeline, snapshot, {}, carrier)
        expected_png = _rasterize_svg_frame(layout, expected_svg)
        inputs = paint_module().verify_split_paint_inputs(layout, carrier)
        original_open = Path.open

        def only_frozen_fonts(path, *args, **kwargs):
            assert any(part.startswith("atme-split-fonts-") for part in path.parts), "reopened source resource"
            return original_open(path, *args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(Path, "open", only_frozen_fonts)
            actual_svg = _compose_validated_svg_frame(layout, timeline, snapshot, {}, split_inputs=inputs)
            actual_png = _rasterize_svg_frame(layout, actual_svg, split_inputs=inputs)
        assert actual_svg == expected_svg
        assert actual_png == expected_png
        if kind != "registry":
            with pytest.raises(ValueError, match="Split asset bytes differ"):
                _compose_validated_svg_frame(layout, timeline, snapshot, {}, {}, split_inputs=inputs)
            changed = timeline.model_copy(deep=True)
            changed.resolved_assets[0].revision += 1
            with pytest.raises(ValueError, match="Split resolved assets differ"):
                _compose_validated_svg_frame(layout, changed, snapshot, {}, split_inputs=inputs)
            duplicate = timeline.model_copy(deep=True)
            duplicate.resolved_assets.append(duplicate.resolved_assets[0])
            with pytest.raises(ValueError, match="Split resolved assets differ"):
                _compose_validated_svg_frame(layout, duplicate, snapshot, {}, split_inputs=inputs)
    finally:
        if service is not None:
            service.store.close()


@pytest.mark.parametrize("fault", ["layout", "payload", "style", "manifest", "mutable"])
def test_frozen_paint_consumer_rejects_changed_binding(fault):
    import inspect

    from atme.render.v2_svg import _compose_validated_svg_frame

    assert "split_inputs" in inspect.signature(_compose_validated_svg_frame).parameters, "Split frozen input consumer missing"
    layout, timeline, frames = geometry_paint_frames()
    inputs = paint_module().verify_split_paint_inputs(layout, {})
    if fault == "layout":
        layout = layout.model_copy(deep=True)
        layout.objects[0].description += " changed"
    elif fault == "payload":
        row = inputs.bundle_bytes[0]
        inputs = replace(inputs, bundle_bytes=((row[0], row[1], row[2] + b"changed"), *inputs.bundle_bytes[1:]))
    elif fault == "style":
        inputs = replace(inputs, style_json="{}")
    elif fault == "manifest":
        inputs = replace(inputs, manifest_json="{}")
    else:
        inputs = replace(inputs, bundle_bytes=list(inputs.bundle_bytes))
    with pytest.raises(ValueError, match="Split"):
        _compose_validated_svg_frame(layout, timeline, frames[1], {}, split_inputs=inputs)


def paint_snapshot(*, compound=False, at_ms=450):
    layout, initial, split = hidden_result_boundary() if compound else geometry_boundary()
    _, _, raw = split_documents()
    raw["actions"] = [split.model_dump(mode="json")]
    raw["initial_object_states"] = [
        {"object_id": frame.object_id, "state": frame.state,
         "state_version": dict(initial.state_versions)[frame.object_id], "visible": frame.visible}
        for frame in initial.objects
    ]
    timeline = ResolvedVisualTimelineV2.model_validate(raw)
    replay = replay_split(layout, initial, (split,), duration=timeline.duration_ms)
    snapshot = _sample_validated_frame(layout, timeline, replay,
                                       camera_segments(layout, timeline, replay), at_ms)
    return snapshot


def test_construction_lookup_uses_exact_root_and_retains_legacy_snapshot():
    module = paint_module()
    snapshot = paint_snapshot()
    assert module.split_construction_for(snapshot, "part-1") is snapshot.envelopes[0]
    assert module.split_construction_for(snapshot, "source") is None
    final = paint_snapshot(at_ms=900)
    assert type(final) is FrameSnapshot
    assert module.split_construction_for(final, "part-1") is None


def test_compound_envelope_lookup_preserves_child_local_records():
    module = paint_module()
    snapshot = paint_snapshot(compound=True)
    before = repr(snapshot)
    root = snapshot.envelopes[0].root_id
    children = snapshot.hierarchy.children(snapshot.object(root).board_id, root)
    assert children, "fixture must exercise a real compound result"
    for child in children:
        assert module.split_construction_for(snapshot, child) is snapshot.envelopes[0]
    assert repr(snapshot) == before


@pytest.mark.parametrize("fault", ["duplicate", "missing_root", "nan", "outside", "mode", "mutable"])
def test_construction_lookup_rejects_malformed_envelopes(fault):
    module = paint_module()
    snapshot = paint_snapshot()
    envelope = snapshot.envelopes[0]
    faults = {
        "duplicate": snapshot.envelopes + (envelope,),
        "missing_root": (replace(envelope, root_id="unknown"),),
        "nan": (replace(envelope, construction_fraction=float("nan")),),
        "outside": (replace(envelope, construction_fraction=1.01),),
        "mode": (replace(envelope, mode="invented"),),
        "mutable": list(snapshot.envelopes),
    }
    with pytest.raises(ValueError, match="Split.*envelope"):
        module.split_construction_for(replace(snapshot, envelopes=faults[fault]), "source")


def test_construction_lookup_rejects_unknown_carrier_and_overlapping_roots():
    module = paint_module()
    snapshot = paint_snapshot(compound=True)

    @dataclass(frozen=True)
    class Unknown(SplitFrameSnapshot):
        pass

    with pytest.raises(ValueError, match="Split.*snapshot"):
        module.split_construction_for(Unknown(**snapshot.__dict__), "source")
    root = snapshot.envelopes[0].root_id
    child = snapshot.hierarchy.children(snapshot.object(root).board_id, root)[0]
    overlap = SplitPaintEnvelope(child, "second", "reveal", .5)
    with pytest.raises(ValueError, match="Split.*overlap"):
        module.split_construction_for(replace(snapshot, envelopes=snapshot.envelopes + (overlap,)), child)


def test_verified_bundle_freezes_real_pinned_bytes_without_serializing_payloads():
    module = paint_module()
    layout, _, _ = geometry_boundary()
    frozen = module._verified_split_bundle(layout)
    assert frozen == module._verified_split_bundle(layout)
    manifest = json.loads(frozen.manifest_json)
    assert frozen.inputs_sha256 == sha256(frozen.manifest_json.encode()).hexdigest()
    assert {row[0] for row in frozen.files} >= {"style.json", "asset-registry.json"}
    for name, checksum, payload in frozen.files:
        assert type(payload) is bytes
        assert sha256(payload).hexdigest() == checksum
        assert manifest["files"][name] == checksum
    assert "payload" not in frozen.manifest_json


@pytest.mark.parametrize("target", ["style", "registry", "font", "license", "illustration"])
def test_verified_bundle_rechecks_bytes_even_after_cached_bundle_load(monkeypatch, target):
    from atme.render.style_bundle import load_bundle

    module = paint_module()
    layout, _, _ = geometry_boundary()
    style, registry, root = load_bundle()
    module._verified_split_bundle(layout)
    relative = {"style": "style.json", "registry": "asset-registry.json",
                "font": style.fonts[0].file, "license": style.fonts[0].license_file,
                "illustration": registry.assets[0].file}[target]
    original = Path.read_bytes

    def changed(path):
        payload = original(path)
        return payload + b"tampered" if path.resolve() == (root / relative).resolve() else payload

    monkeypatch.setattr(Path, "read_bytes", changed)
    with pytest.raises(ValueError, match="Split.*checksum"):
        module._verified_split_bundle(layout)


def owned_image_inputs(tmp_path, *, transparent=False):
    from atme.project_service import ProjectService
    from atme.store.contracts_v2 import ExecutableLayoutV2
    from atme.store.db import JobStore
    from test_v2_project_image import _documents, _png

    service = ProjectService(JobStore(tmp_path / "split-paint.db"))
    pid = service.create("Split paint", "LONG_FORM_16_9", "idea-first")["project_id"]
    raw = _png(color=(30, 100, 210, 0 if transparent else 255))
    staged = tmp_path / "original.png"
    staged.write_bytes(raw)
    asset = service.attach_asset_file(pid, staged, "original.png", 0)["asset"]
    asset = next(row for row in service.list_assets(pid) if row["asset_id"] == asset["asset_id"])
    layout, timeline = _documents(asset["asset_id"], raw, asset["revision"], pid)
    pin = {"asset_id": asset["asset_id"], "revision": asset["revision"],
           "resource_uri": asset["resource_uri"], "checksum_sha256": asset["sha256"]}
    return service, ExecutableLayoutV2.model_validate(layout), timeline["resolved_assets"], [pin], raw


def test_paint_inputs_require_trusted_asset_origin_not_raw_bytes(tmp_path):
    module = paint_module()
    service, layout, _resolved, pins, raw = owned_image_inputs(tmp_path)
    try:
        with pytest.raises(ValueError, match="trusted.*asset"):
            module.verify_split_paint_inputs(layout, {pins[0]["asset_id"]: raw})
    finally:
        service.store.close()


def test_paint_inputs_freeze_verified_project_bytes_and_exact_pins(tmp_path):
    from atme import project_assets

    module = paint_module()
    service, layout, resolved, pins, raw = owned_image_inputs(tmp_path)
    try:
        carrier = project_assets.read_verified_split_asset_bytes(service, layout, resolved, pins)
        inputs = module.verify_split_paint_inputs(layout, carrier)
        assert carrier[pins[0]["asset_id"]] == raw
        assert json.loads(inputs.asset_pins_json) == pins
        assert inputs.project_assets[0].payload == raw
        assert inputs.inputs_sha256 == sha256(inputs.manifest_json.encode()).hexdigest()
        pins[0]["resource_uri"] = "altered"
        resolved[0]["revision"] += 1
        assert json.loads(inputs.asset_pins_json)[0]["resource_uri"] != "altered"
        assert module.verify_split_paint_inputs(layout, carrier) == inputs
    finally:
        service.store.close()


@pytest.mark.parametrize("field,value", [("revision", 999), ("resource_uri", "atme://wrong"),
                                         ("checksum_sha256", "0" * 64)])
def test_project_resolver_rejects_forged_split_pin(tmp_path, field, value):
    from atme import project_assets

    service, layout, resolved, pins, _ = owned_image_inputs(tmp_path)
    try:
        pins[0][field] = value
        with pytest.raises(ValueError, match="Split.*pin"):
            project_assets.read_verified_split_asset_bytes(service, layout, resolved, pins)
    finally:
        service.store.close()


def test_transparent_project_pixels_do_not_become_positive_paint_evidence(tmp_path):
    from atme import project_assets

    module = paint_module()
    service, layout, resolved, pins, _ = owned_image_inputs(tmp_path, transparent=True)
    try:
        carrier = project_assets.read_verified_split_asset_bytes(service, layout, resolved, pins)
        with pytest.raises(ValueError, match="Split.*transparent"):
            module.verify_split_paint_inputs(layout, carrier)
    finally:
        service.store.close()


@pytest.mark.parametrize("fault", ["payload", "dimensions", "revision", "duplicate", "subclass"])
def test_paint_inputs_reject_corrupted_private_carrier(tmp_path, fault):
    from atme import project_assets

    module = paint_module()
    service, layout, resolved, pins, _ = owned_image_inputs(tmp_path)
    try:
        carrier = project_assets.read_verified_split_asset_bytes(service, layout, resolved, pins)
        row = carrier.rows[0]
        if fault == "payload":
            carrier = replace(carrier, rows=(replace(row, payload=row.payload + b"changed"),))
        elif fault in {"dimensions", "revision"}:
            metadata = json.loads(row.resolved_json)
            metadata["width" if fault == "dimensions" else "revision"] += 1
            carrier = replace(carrier, rows=(replace(row, resolved_json=json.dumps(metadata)),))
        elif fault == "duplicate":
            with pytest.raises(ValueError, match="Split.*unique"):
                replace(carrier, rows=carrier.rows + carrier.rows)
            return
        else:
            @dataclass(frozen=True)
            class Unknown(type(carrier)):
                pass
            carrier = Unknown(carrier.rows)
        with pytest.raises(ValueError, match="Split"):
            module.verify_split_paint_inputs(layout, carrier)
    finally:
        service.store.close()


def test_duplicate_evidence_keeps_origin_separate_from_current_split_pin(tmp_path):
    from atme import project_assets
    from atme.store.contracts_v2 import ExecutableLayoutV2
    from test_v2_evidence_compositor import evidence_documents

    module = paint_module()
    service, raw_layout, timeline, verified = evidence_documents(tmp_path)
    try:
        source_id = raw_layout["project_id"]
        copy_id = service.duplicate(source_id)["project_id"]
        raw_layout["project_id"] = copy_id
        layout = ExecutableLayoutV2.model_validate(raw_layout)
        owned = next(row for row in service.list_assets(copy_id) if row["asset_id"] == verified.asset_id)
        assert owned["managed_ref"] != owned["resource_uri"]
        pin = {"asset_id": verified.asset_id, "revision": owned["revision"],
               "resource_uri": owned["resource_uri"], "checksum_sha256": owned["sha256"]}
        carrier = project_assets.read_verified_split_asset_bytes(service, layout, timeline["resolved_assets"], [pin])
        inputs = module.verify_split_paint_inputs(layout, carrier)
        assert json.loads(inputs.asset_pins_json) == [pin]
        assert json.loads(inputs.project_assets[0].resolved_json)["managed_ref"] == owned["managed_ref"]
        exposed = carrier[verified.asset_id]
        exposed.treatment.intent.source_label = "changed outside carrier"
        assert module.verify_split_paint_inputs(layout, carrier) == inputs
        with pytest.raises(ValueError, match="Split.*pin"):
            project_assets.read_verified_split_asset_bytes(service, layout, timeline["resolved_assets"],
                                                           [{**pin, "resource_uri": owned["managed_ref"]}])
    finally:
        service.store.close()


@pytest.mark.parametrize("entry", ["resolver", "producer"])
@pytest.mark.parametrize("fault", ["mixed_evidence", "unsupported_consumer"])
def test_project_paint_inputs_bind_each_consumer_role(tmp_path, entry, fault):
    from copy import deepcopy

    from atme import project_assets
    from atme.store.contracts_v2 import ExecutableLayoutV2
    from test_v2_evidence_compositor import evidence_documents

    module = paint_module()
    if fault == "mixed_evidence":
        service, raw, timeline, _ = evidence_documents(tmp_path)
        layout = ExecutableLayoutV2.model_validate(raw)
        resolved = timeline["resolved_assets"]
        owned = service.list_assets(layout.project_id)[0]
        pins = [{"asset_id": owned["asset_id"], "revision": owned["revision"],
                 "resource_uri": owned["resource_uri"], "checksum_sha256": owned["sha256"]}]
    else:
        service, layout, resolved, pins, _ = owned_image_inputs(tmp_path)
    try:
        carrier = project_assets.read_verified_split_asset_bytes(service, layout, resolved, pins)
        raw = layout.model_dump(mode="json")
        consumer = next(obj for obj in raw["objects"] if obj["asset_id"] is not None)
        if fault == "mixed_evidence":
            extra = deepcopy(consumer)
            extra.update(object_id="ordinary-copy", object_type="image", variant=None)
            raw["objects"].append(extra)
            next(board for board in raw["boards"] if board["board_id"] == extra["board_id"])["object_ids"].append(extra["object_id"])
        else:
            consumer.update(object_type="icon", variant=None)
        bad = ExecutableLayoutV2.model_validate(raw)
        with pytest.raises(ValueError, match="Split.*consumer"):
            if entry == "resolver":
                project_assets.read_verified_split_asset_bytes(service, bad, resolved, pins)
            else:
                module.verify_split_paint_inputs(bad, carrier)
    finally:
        service.store.close()
