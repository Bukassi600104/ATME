"""P3-40: authored source range/placement, not thumbnails or inferred timing."""

from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from test_v2_image_placement_contract import (
    image_documents,
    image_placement,
    placed_image,
)
from test_v2_project_image import _png
from test_v2_split_identity import sample_for_layout
from v2_fixtures import digest

from atme.render.v2_split_identity import split_content_receipts
from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    ResolvedAsset,
    SemanticStandardObjectSpec,
    VisualObject,
    validate_plan_layout,
)


def media_stream():
    return {
        "version": "1.0.0", "stream_index": 0, "width": 80, "height": 40,
        "time_base_numerator": 1, "time_base_denominator": 1000,
        "first_pts": -200, "end_pts": 2800, "frame_count": 3,
        "timestamps_sha256": "c" * 64,
    }


def media_playback():
    return {
        "version": "1.0.0", "placement": image_placement(),
        "source_duration_ms": 3000, "source_stream": media_stream(),
        "source_in_ms": 400, "source_out_ms": 2400, "timeline_start_ms": 100,
        "frame_selection": "last_pts_at_or_before",
    }


def media_object(kind="video"):
    raw = placed_image()
    raw.pop("image_placement")
    raw.update(object_type=kind, media_playback=media_playback())
    return raw


def media_documents(kind="video"):
    plan, layout = image_documents()
    plan["assets"][0].update(kind=kind, duration_ms=3000, media_stream=media_stream())
    for doc in (plan, layout):
        obj = doc["objects"][0]
        obj.pop("image_placement")
        obj.update(object_type=kind, media_playback=media_playback())
    layout["plan_sha256"] = digest(plan)
    return plan, layout


@pytest.mark.parametrize("kind", ["video", "presenter", "screen_recording"])
def test_authored_media_kinds_retain_exact_range_stream_and_placement(kind):
    raw = media_object(kind)
    parsed = VisualObject.model_validate(raw)
    assert parsed.model_dump(mode="json")["media_playback"] == media_playback()
    semantic = {key: raw[key] for key in (
        "object_id", "object_type", "board_id", "beat_id", "semantic_role",
        "description", "asset_id", "initial_state", "coverage_ids", "media_playback",
    )}
    assert SemanticStandardObjectSpec.model_validate(semantic).model_dump(
        mode="json")["media_playback"] == media_playback()
    validate_plan_layout(*media_documents(kind))


@pytest.mark.parametrize("path,value", [
    (("version",), "2.0.0"), (("source_duration_ms",), 0),
    (("source_duration_ms",), True), (("source_duration_ms",), 3000.0),
    (("source_stream", "stream_index"), -1), (("source_stream", "stream_index"), False),
    (("source_stream", "time_base_numerator"), 0),
    (("source_stream", "time_base_denominator"), 0),
    (("source_stream", "time_base_numerator"), 2),
    (("source_stream", "end_pts"), -200),
    (("source_stream", "frame_count"), 0),
    (("source_stream", "width"), 81),
    (("source_stream", "timestamps_sha256"), "z" * 64),
    (("source_duration_ms",), 3001),
    (("source_in_ms",), -1), (("source_in_ms",), 2400),
    (("source_in_ms",), 2401), (("source_in_ms",), 400.5),
    (("source_out_ms",), 3001), (("source_out_ms",), True),
    (("timeline_start_ms",), -1), (("timeline_start_ms",), 100.0),
    (("frame_selection",), "nearest_fps"), (("playback_rate",), 2),
    (("placement", "source_revision"), 0), (("placement", "source_width"), 0),
    (("placement", "source_sha256"), "z" * 64),
    (("placement", "crop", "x"), 21),
    (("placement", "focal_point", "y"), float("nan")),
    (("placement", "allowed_transformations"), ["scale"]),
])
def test_media_rejects_ambiguous_clock_or_invalid_source_placement(path, value):
    raw = media_object()
    owner = raw["media_playback"]
    for key in path[:-1]:
        owner = owner[key]
    owner[path[-1]] = value
    with pytest.raises(ValidationError):
        VisualObject.model_validate(raw)


@pytest.mark.parametrize("kind", ["video", "presenter", "screen_recording"])
@pytest.mark.parametrize("missing", ["asset_id", "media_playback"])
def test_media_cannot_exist_as_an_unbound_static_placeholder(kind, missing):
    raw = media_object(kind)
    raw.pop(missing)
    with pytest.raises(ValidationError):
        VisualObject.model_validate(raw)


@pytest.mark.parametrize("kind", ["image", "evidence", "icon", "chart", "instance"])
def test_playback_cannot_be_attached_to_another_visual_owner(kind):
    raw = media_object()
    raw["object_type"] = kind
    with pytest.raises(ValidationError, match="media_playback"):
        VisualObject.model_validate(raw)


def test_media_cannot_carry_a_conflicting_still_image_placement():
    raw = media_object()
    raw["image_placement"] = image_placement()
    with pytest.raises(ValidationError):
        VisualObject.model_validate(raw)


def test_media_schema_enforces_the_payload_and_owner_in_both_contracts():
    raw = media_object()
    for model in (VisualObject, SemanticStandardObjectSpec):
        document = raw if model is VisualObject else {key: value for key, value in raw.items()
                                                     if key in model.model_fields}
        validator = Draft202012Validator(model.model_json_schema())
        assert not list(validator.iter_errors(document))
        missing = deepcopy(document)
        missing.pop("media_playback")
        assert list(validator.iter_errors(missing))
        wrong_owner = deepcopy(document)
        wrong_owner["object_type"] = "image"
        assert list(validator.iter_errors(wrong_owner))


@pytest.mark.parametrize("field,value", [
    ("revision", 2), ("checksum_sha256", "b" * 64), ("width", 81), ("height", 41),
    ("duration_ms", 3001), ("duration_ms", None), ("kind", "presenter"),
    ("allowed_transformations", ["scale", "crop", "rotate"]),
])
def test_semantic_media_inventory_cannot_change_source_pins_or_grants(field, value):
    plan, layout = media_documents()
    plan["assets"][0][field] = value
    layout["plan_sha256"] = digest(plan)
    with pytest.raises(ValueError, match="media_(playback|stream).*asset"):
        validate_plan_layout(plan, layout)


def test_executable_media_cannot_retime_the_externally_authored_source_range():
    plan, layout = media_documents()
    layout["objects"][0]["media_playback"]["source_in_ms"] = 401
    with pytest.raises(ValueError, match="semantic field media_playback"):
        validate_plan_layout(plan, layout)


def test_media_range_and_stream_affect_content_identity_but_pose_does_not():
    _plan, layout = media_documents()
    target = layout["objects"][0]["object_id"]

    def receipt(document):
        parsed = ExecutableLayoutV2.model_validate(document)
        # This tests content projection/byte binding only, not media decoding or
        # Split admission. Native moving-video proof is a separate owning gate.
        return next(row for row in split_content_receipts(
            parsed, sample_for_layout(parsed), {"a" * 32: _png()}) if row.object_id == target)

    before = receipt(layout)
    moved = deepcopy(layout)
    moved["objects"][0]["transform"]["position"]["x"] += 7
    assert receipt(moved).content_sha256 == before.content_sha256
    for field, value in (("source_in_ms", 401), ("timeline_start_ms", 101)):
        changed = deepcopy(layout)
        changed["objects"][0]["media_playback"][field] = value
        assert receipt(changed).content_sha256 != before.content_sha256
    changed = deepcopy(layout)
    changed["objects"][0]["media_playback"]["source_stream"]["stream_index"] = 1
    assert receipt(changed).content_sha256 != before.content_sha256


def test_resolved_media_can_pin_duration_without_changing_legacy_asset_serialization():
    old = {
        "asset_id": "a" * 32, "revision": 1, "managed_ref": "atme://projects/1/media/" + "a" * 32,
        "checksum_sha256": "a" * 64, "provenance_verified": False,
    }
    assert "duration_ms" not in ResolvedAsset.model_validate(old).model_dump(mode="json")
    assert "media_stream" not in ResolvedAsset.model_validate(old).model_dump(mode="json")
    pinned = {**old, "kind": "video", "duration_ms": 3000, "width": 80, "height": 40,
              "media_stream": media_stream()}
    assert ResolvedAsset.model_validate(pinned).model_dump(mode="json")["duration_ms"] == 3000
    for invalid in (0, True, 3000.5):
        with pytest.raises(ValidationError):
            ResolvedAsset.model_validate({**pinned, "duration_ms": invalid})


@pytest.mark.parametrize("field,value", [("duration_ms", 2999), ("width", 81),
                                       ("kind", "image"), ("height", None)])
def test_resolved_media_rejects_mismatched_selected_stream_pins(field, value):
    raw = {
        "asset_id": "a" * 32, "revision": 1, "managed_ref": "atme://projects/1/media/" + "a" * 32,
        "checksum_sha256": "a" * 64, "provenance_verified": False, "kind": "video",
        "width": 80, "height": 40, "duration_ms": 3000, "media_stream": media_stream(),
    }
    raw[field] = value
    with pytest.raises(ValidationError, match="media_stream"):
        ResolvedAsset.model_validate(raw)


def test_duration_uses_exact_rational_floor_not_container_or_float_rounding():
    raw = media_object()
    playback = raw["media_playback"]
    playback["source_stream"].update(time_base_numerator=1, time_base_denominator=30000,
                                     first_pts=9001, end_pts=99120, frame_count=90)
    playback["source_duration_ms"] = 3003
    assert VisualObject.model_validate(raw).media_playback.source_duration_ms == 3003
    playback["source_duration_ms"] = 3000
    with pytest.raises(ValidationError, match="media_playback"):
        VisualObject.model_validate(raw)
    playback["source_duration_ms"] = 3004
    with pytest.raises(ValidationError, match="media_playback"):
        VisualObject.model_validate(raw)


def test_legacy_still_objects_do_not_acquire_media_fields():
    raw = placed_image()
    parsed = VisualObject.model_validate(raw).model_dump(mode="json")
    assert "media_playback" not in parsed


@pytest.mark.parametrize("kind,path", [
    ("video", ("media_playback",)),
    ("video", ("media_playback", "source_stream")),
    ("video", ("media_playback", "placement")),
    ("video", ("media_playback", "placement", "crop")),
    ("video", ("media_playback", "placement", "focal_point")),
    ("image", ("image_placement",)),
    ("image", ("image_placement", "crop")),
    ("image", ("image_placement", "focal_point")),
])
def test_identity_rejects_unknown_nested_payload_subclass_even_without_extra_fields(kind, path):
    _plan, raw = media_documents() if kind == "video" else image_documents()
    layout = ExecutableLayoutV2.model_validate(raw)
    supplied = {"a" * 32: _png()}
    baseline = split_content_receipts(layout, sample_for_layout(layout), supplied)
    assert baseline
    parent = layout.objects[0]
    for name in path[:-1]:
        parent = getattr(parent, name)
    value = getattr(parent, path[-1])
    unknown_type = type("UnknownPayload", (type(value),), {})
    object.__setattr__(parent, path[-1], unknown_type.model_construct(**value.__dict__))
    with pytest.raises(ValueError, match="unknown nested payload subclass"):
        split_content_receipts(layout, sample_for_layout(layout), supplied)
