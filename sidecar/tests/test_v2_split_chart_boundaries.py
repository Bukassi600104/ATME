"""Bounded native chart movement/coverage; no new container-family credit."""

import json
from hashlib import sha256

import pytest
from test_v2_split_chart_family import (
    chart_split_family,
    chart_split_frames,
    native_chart_oracle,
    pixels,
)
from test_v2_split_identity import sample_for_layout
from v2_fixtures import digest

from atme.render.v2_split import _observed_split_placements, capture_split
from atme.render.v2_split_identity import SplitContentReceipt
from atme.render.v2_split_paint import (
    prove_split_coverage,
    split_family_admission,
    verify_split_paint_inputs,
)
from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    ResolvedAction,
    SplitPolicy,
    _split_expected_completion,
)


def movement_chart(portrait=False, *, offscreen=False):
    layout, _, resolved, timeline, _ = chart_split_family(portrait)
    raw, action = layout.model_dump(mode="json"), resolved.model_dump(mode="json")
    policy = action["action"]["split_policy"]
    for row in policy["results"]:
        obj = next(obj for obj in raw["objects"] if obj["object_id"] == row["object_id"])
        if offscreen:
            obj["transform"]["position"]["x"] = 8000.
        elif row["object_id"] == "part-2":
            continue
        destination = row["destination"]
        if not offscreen:
            destination["position"]["x"] = 60.
        row["movement"] = {"phase": {"start_tick": 0 if offscreen else 6000, "end_tick": 10000,
            "easing": "linear"}, "from_transform": obj["transform"], "destination": destination}
    layout = ExecutableLayoutV2.model_validate(raw)
    before = sample_for_layout(layout)
    receipts = {}
    for obj in raw["objects"]:
        projection = {name: obj[name] for name in
            ("object_type", "geometry", "style", "anchors", "asset_id", "variant", "chart_payload")}
        canonical = json.dumps(projection, sort_keys=True, separators=(",", ":"))
        key = obj["object_id"]
        receipts[key] = SplitContentReceipt(key, canonical, sha256(canonical.encode()).hexdigest())
    policy["source_basis"]["placements"] = [row.model_dump(mode="json") for row in
        _observed_split_placements(before, {obj.object_id: obj for obj in layout.objects}, set(receipts), receipts)]
    policy["source_basis_sha256"] = digest(policy["source_basis"])
    completion = _split_expected_completion(SplitPolicy.model_validate(policy))
    completion["completion_sha256"] = digest(completion)
    action["split_completion_receipt"] = completion
    resolved = ResolvedAction.model_validate(action)
    timeline = timeline.model_copy(update={"actions": [resolved], "layout_sha256": digest(raw)})
    return layout, before, resolved, timeline


@pytest.mark.parametrize("portrait", [False, True])
def test_chart_split_movement_after_datum_draw_preserves_native_pixels(portrait):
    layout, before, resolved, timeline = movement_chart(portrait)
    capture = capture_split(resolved, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    assert split_family_admission("part-1", capture, layout, inputs).family == "data chart"
    proof = prove_split_coverage(capture, layout, inputs)
    assert 24 in proof.critical_times_ms
    outputs = chart_split_frames(layout, before, resolved, timeline, inputs, (40, 32, 40, 32))
    assert pixels(outputs[32][1]) == pixels(native_chart_oracle(layout, inputs, 32, "draw", dx=30.))
    assert pixels(outputs[40][1]) == pixels(native_chart_oracle(layout, inputs, 40, "draw", dx=60.))


@pytest.mark.parametrize("portrait", [False, True])
def test_chart_local_native_alpha_cannot_hide_an_offscreen_handoff_gap(portrait):
    layout, before, resolved, _ = movement_chart(portrait, offscreen=True)
    capture = capture_split(resolved, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    # Local full/partial native alpha and phase continuity are both real;
    # only the existing canvas-aware every-ms proof can find this absence.
    assert split_family_admission("part-1", capture, layout, inputs).family == "data chart"
    with pytest.raises(ValueError, match="Split has zero painted coverage at 32 ms"):
        prove_split_coverage(capture, layout, inputs)
