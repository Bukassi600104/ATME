"""Shared readable bindings for Split's real hold boundary, not a fake insert.

These are observer/geometry fixtures, not evidence attestation or native proof.
"""

from copy import deepcopy
from dataclasses import replace

import pytest
from atme.render import v2_evidence_reading
from atme.render.v2_camera import CameraViewport
from atme.store.contracts_v2 import ExecutableLayoutV2, ResolvedAction
from test_v2_evidence_apertures import aperture_documents
from test_v2_split_identity import sample_for_layout
from v2_fixtures import executable_layout_v2, resolved_timeline_v2


def readable_binding(*, aperture=False):
    document = aperture_documents(rotation=0)[0] if aperture else executable_layout_v2()
    layout = ExecutableLayoutV2.model_validate(document)
    objects = {obj.object_id: obj for obj in layout.objects}
    before = sample_for_layout(layout)
    sample = replace(before, at_ms=1600, objects=tuple(
        replace(row, state="evidence_visible", visible=True, opacity=1.0, reveal_fraction=1.0)
        if row.object_id == "object-evidence" else row for row in before.objects))
    return layout, objects, layout.evidence_treatments[0], sample, CameraViewport(0, 0, 1280, 720)


def observe(arguments, *, target="object-evidence", readable_start=1600):
    assert hasattr(v2_evidence_reading, "validate_evidence_reading_binding"), (
        "shared reading still requires a fabricated insert action instead of an explicit bound target/clock")
    v2_evidence_reading.validate_evidence_reading_binding(target, readable_start, *arguments)


@pytest.mark.parametrize("aperture", [False, True])
def test_direct_evidence_readable_binding_uses_actual_target_and_hold_clock_without_action(aperture):
    arguments = readable_binding(aperture=aperture)
    original = deepcopy(arguments)
    observe(arguments)
    assert arguments == original


def test_ordinary_insert_wrapper_delegates_exact_objects_and_existing_completion_clock(monkeypatch):
    arguments = readable_binding()
    item = ResolvedAction.model_validate(resolved_timeline_v2()["actions"][2])
    calls = []

    def record(*values):
        calls.append(values)

    monkeypatch.setattr(v2_evidence_reading, "validate_evidence_reading_binding", record, raising=False)
    v2_evidence_reading.validate_evidence_reading(item, *arguments)
    assert calls == [(item.action.target_object_id, item.end_ms, *arguments)]
    assert all(actual is expected for actual, expected in zip(calls[0][2:], arguments, strict=True))


@pytest.mark.parametrize("fault", ["hidden", "partial", "translucent"])
@pytest.mark.parametrize("at", [1599, 1600, 1999, 2000])
def test_full_readability_begins_at_verified_phase_hold_not_outer_split_end(fault, at):
    layout, objects, treatment, sample, viewport = readable_binding()
    changes = {"hidden": {"visible": False}, "partial": {"reveal_fraction": 0.9},
               "translucent": {"opacity": 0.9}}[fault]
    sample = replace(sample, at_ms=at, objects=tuple(replace(row, **changes)
        if row.object_id == treatment.object_id else row for row in sample.objects))
    arguments = layout, objects, treatment, sample, viewport
    if at < 1600:
        observe(arguments)
    else:
        with pytest.raises(ValueError, match="fully visible and opaque"):
            observe(arguments)


@pytest.mark.parametrize("fault", ["wrong_target", "unknown_target", "bool_clock", "float_clock", "negative_clock"])
def test_direct_read_binding_rejects_wrong_target_or_nonexact_clock(fault):
    arguments = readable_binding()
    target = {"wrong_target": "object-1", "unknown_target": "missing"}.get(fault, "object-evidence")
    start = {"bool_clock": True, "float_clock": 1600.0, "negative_clock": -1}.get(fault, 1600)
    with pytest.raises(ValueError, match="binding"):
        observe(arguments, target=target, readable_start=start)


@pytest.mark.parametrize("fault", ["unreadable_camera", "undeclared_rotation", "clipped_aperture", "hidden_parent"])
def test_direct_read_binding_keeps_shared_world_camera_permission_and_aperture_checks(fault):
    layout, objects, treatment, sample, viewport = readable_binding(aperture=True)
    if fault == "unreadable_camera":
        viewport = CameraViewport(0, 0, 400, 300)
        message = "not fully readable"
    elif fault == "undeclared_rotation":
        treatment = treatment.model_copy(update={"allowed_transformations": ["crop", "scale", "mask"]})
        sample = replace(sample, objects=tuple(replace(row, transform=replace(row.transform,
            rotation_degrees=3)) if row.object_id == "object-evidence" else row for row in sample.objects))
        message = "undeclared rotation"
    elif fault == "clipped_aperture":
        source = objects["mask-source"]
        source.geometry.bounds.width = 100
        message = "clipped by.*mask"
    else:
        sample = replace(sample, objects=tuple(replace(row, visible=False)
            if row.object_id == "evidence-aperture" else row for row in sample.objects))
        message = "fully visible opaque parents"
    with pytest.raises(ValueError, match=message):
        observe((layout, objects, treatment, sample, viewport))
