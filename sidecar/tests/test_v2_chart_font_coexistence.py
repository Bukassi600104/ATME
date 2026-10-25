"""Chart-triggered checked-font rasterization retains the existing mono path."""

import socket
from copy import deepcopy
from pathlib import Path

import pytest
from test_v2_chart_compositor import runtime_documents
from test_v2_code_compositor import code_documents
from v2_fixtures import digest

from atme.render import v2_state
from atme.render.style_bundle import registry_endpoint_inputs_for_objects
from atme.render.v2_split_paint import verify_split_paint_inputs
from atme.render.v2_svg import (
    _compose_validated_svg_frame,
    _rasterize_svg_frame,
    compose_png_frame,
    compose_svg_frame,
)
from atme.store.contracts_v2 import ExecutableLayoutV2, ResolvedVisualTimelineV2


@pytest.mark.parametrize("portrait", [False, True])
def test_chart_and_code_union_checked_fonts_and_match_frozen_offline(portrait, monkeypatch):
    layout, timeline = runtime_documents(portrait=portrait)
    code_layout, code_timeline = code_documents(portrait)
    code = deepcopy(code_layout["objects"][0])
    code["geometry"]["bounds"]["y"] = 540
    layout["objects"][1] = code
    timeline["actions"] += code_timeline["actions"]
    timeline["coverage"] += code_timeline["coverage"]
    timeline["fallbacks"] += code_timeline["fallbacks"]
    timeline["layout_sha256"] = digest(layout)
    before = deepcopy((layout, timeline))
    times = (700, 2000, 2450, 2900)
    expected = {at: compose_png_frame(layout, timeline, at).png for at in times}
    assert len(set(expected.values())) == len(times)
    complete = compose_svg_frame(layout, timeline, 2900).svg
    assert "Measured output" in complete and "e\u0301x" in complete
    assert "Kalam" in complete and "JetBrains Mono" in complete
    typed = ExecutableLayoutV2.model_validate(layout)
    resolved = ResolvedVisualTimelineV2.model_validate(timeline)
    inputs = verify_split_paint_inputs(typed, {})
    assert any("code-font-v1/" in name for name, _, _ in inputs.bundle_bytes)
    registry = registry_endpoint_inputs_for_objects({obj.object_id: obj for obj in typed.objects},
        frozen_files={name: raw for name, _, raw in inputs.bundle_bytes})

    def forbidden(*args, **kwargs):
        raise AssertionError("mixed chart/code reopened a source or attempted network access")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    for at in (2900, 700, 2450, 2000, 2900):
        sample = v2_state._evaluate_frame_with_registry_inputs(layout, timeline, at, registry)
        svg = _compose_validated_svg_frame(typed, resolved, sample, {}, split_inputs=inputs)
        assert _rasterize_svg_frame(typed, svg, split_inputs=inputs).png == expected[at]
    assert (layout, timeline) == before
