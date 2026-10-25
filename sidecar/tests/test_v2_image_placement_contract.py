"""P3-35: exact externally authored placement of immutable supporting pixels."""

from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from test_v2_project_image import _documents, _png
from test_v2_split_identity import sample_for_layout
from v2_fixtures import digest, executable_layout_v2, visual_plan_v2

from atme.render.v2_split_identity import split_content_receipts
from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    ImagePlacement,
    SemanticStandardObjectSpec,
    VisualObject,
    validate_plan_layout,
)


def image_placement(*, fit="contain", focal=(0.5, 0.5)):
    _layout, timeline = _documents("a" * 32, _png(), 1, 1)
    asset = timeline["resolved_assets"][0]
    return {
        "version": "1.0.0", "source_revision": asset["revision"],
        "source_sha256": asset["checksum_sha256"],
        "source_width": 80, "source_height": 40,
        "crop": {"x": 10, "y": 5, "width": 60, "height": 30},
        "fit": fit, "focal_point": {"x": focal[0], "y": focal[1]},
        "allowed_transformations": ["scale", "crop"],
    }


def placed_image(*, fit="contain", focal=(0.5, 0.5)):
    layout, _ = _documents("a" * 32, _png(), 1, 1)
    obj = deepcopy(layout["objects"][2])
    obj["image_placement"] = image_placement(fit=fit, focal=focal)
    return obj


@pytest.mark.parametrize("fit", ["contain", "cover"])
@pytest.mark.parametrize("focal", [(0.0, 0.0), (0.5, 0.5), (1.0, 1.0)])
def test_authored_source_pixel_crop_and_full_focal_domain_round_trip(fit, focal):
    raw = placed_image(fit=fit, focal=focal)
    parsed = VisualObject.model_validate(raw)
    assert parsed.model_dump(mode="json")["image_placement"] == raw["image_placement"]


def test_semantic_image_carries_the_same_exact_placement_intent():
    raw = placed_image(fit="cover", focal=(0.0, 1.0))
    semantic = {key: raw[key] for key in (
        "object_id", "object_type", "board_id", "beat_id", "semantic_role",
        "description", "asset_id", "initial_state", "coverage_ids", "image_placement",
    )}
    assert SemanticStandardObjectSpec.model_validate(semantic).model_dump(
        mode="json")["image_placement"] == raw["image_placement"]


def test_absent_placement_preserves_the_legacy_image_document():
    layout, _ = _documents("a" * 32, _png(), 1, 1)
    raw = layout["objects"][2]
    before = VisualObject.model_validate(raw).model_dump(mode="json")
    assert "image_placement" not in before
    assert VisualObject.model_validate(before).model_dump(mode="json") == before


@pytest.mark.parametrize("path,value", [
    (("source_revision",), True), (("source_revision",), 0),
    (("source_width",), 80.0), (("source_height",), False),
    (("source_sha256",), "x" * 64), (("version",), "2.0.0"),
    (("crop", "x"), -1), (("crop", "y"), True),
    (("crop", "width"), 60.5), (("crop", "height"), 0),
    (("crop", "x"), 21), (("crop", "y"), 11),
    (("focal_point", "x"), -0.01), (("focal_point", "y"), 1.01),
    (("focal_point", "x"), float("nan")), (("focal_point", "y"), float("inf")),
    (("fit",), "stretch"), (("allowed_transformations",), ["crop"]),
    (("allowed_transformations",), ["scale", "scale", "crop"]),
    (("allowed_transformations",), ["crop", "scale"]),
    (("allowed_transformations",), ["scale", "color_treatment"]),
    (("allowed_transformations",), ["scale"]),
])
def test_invalid_or_unpermitted_authored_placement_fails_before_render(path, value):
    payload = image_placement()
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValidationError):
        ImagePlacement.model_validate(payload)


def test_full_source_contain_and_focal_padding_need_no_crop_permission():
    payload = image_placement(focal=(0.0, 1.0))
    payload["crop"] = {"x": 0, "y": 0, "width": 80, "height": 40}
    payload["allowed_transformations"] = ["scale"]
    assert ImagePlacement.model_validate(payload).model_dump(mode="json") == payload


@pytest.mark.parametrize("owner", ["evidence", "icon", "chart"])
def test_placement_cannot_launder_another_owner_as_supporting_pixels(owner):
    obj = placed_image()
    obj["object_type"] = owner
    with pytest.raises(ValidationError, match="image_placement belongs only"):
        VisualObject.model_validate(obj)
    assert list(Draft202012Validator(VisualObject.model_json_schema()).iter_errors(obj))


def test_generated_contract_schema_preserves_typed_crop_and_image_owner():
    obj = placed_image()
    validator = Draft202012Validator(VisualObject.model_json_schema())
    validator.validate(obj)
    obj["image_placement"]["crop"]["width"] = 60.5
    assert list(validator.iter_errors(obj))
    obj = placed_image()
    obj["asset_id"] = None
    with pytest.raises(ValidationError, match="explicit supporting asset_id"):
        VisualObject.model_validate(obj)
    assert list(validator.iter_errors(obj))


def test_crop_focal_and_permissions_are_content_not_mutable_pose():
    raw_bytes = _png()
    raw, _ = _documents("a" * 32, raw_bytes, 1, 1)
    key = raw["objects"][2]["object_id"]
    raw["objects"][2]["image_placement"] = image_placement()

    def receipt(document):
        layout = ExecutableLayoutV2.model_validate(document)
        return next(row for row in split_content_receipts(
            layout, sample_for_layout(layout), {"a" * 32: raw_bytes}) if row.object_id == key)

    baseline = receipt(raw)
    moved = deepcopy(raw)
    moved["objects"][2]["transform"]["position"]["x"] += 7
    assert receipt(moved).content_sha256 == baseline.content_sha256
    for field, value in (("crop", {"x": 0, "y": 0, "width": 60, "height": 30}),
                         ("focal_point", {"x": 0.0, "y": 1.0}),
                         ("allowed_transformations", ["scale", "crop", "rotate"])):
        changed = deepcopy(raw)
        changed["objects"][2]["image_placement"][field] = value
        assert receipt(changed).content_sha256 != baseline.content_sha256


def image_documents():
    plan = visual_plan_v2()
    raw = executable_layout_v2(plan)
    asset = deepcopy(plan["assets"][0])
    placement = image_placement()
    asset.update(asset_id="a" * 32, kind="image", revision=1, fallback_id=None,
                 managed_ref="atme://projects/1/assets/" + "a" * 32,
                 checksum_sha256=placement["source_sha256"], width=80, height=40,
                 allowed_transformations=["scale", "crop"])
    asset["provenance"].update(category="user_owned", source_uri=None,
                               checksum_sha256=placement["source_sha256"],
                               license_status="owned", originality_status="original")
    plan["assets"] = [asset]
    for key in ("objects", "actions", "coverage", "fallbacks"):
        plan[key] = plan[key][:2]
    plan["beats"] = plan["beats"][:1]
    plan["conclusion_beat_id"] = plan["beats"][0]["beat_id"]
    plan["boards"][0]["object_ids"] = [obj["object_id"] for obj in plan["objects"]]
    plan["objects"][0].update(object_type="image", asset_id="a" * 32,
                               image_placement=deepcopy(placement))
    plan["actions"][0]["verb"] = "reveal"
    raw.update(objects=raw["objects"][:2], boards=deepcopy(plan["boards"]), evidence_treatments=[])
    obj = raw["objects"][0]
    obj.pop("path_data", None)
    obj.update(object_type="image", asset_id="a" * 32, variant=None,
               image_placement=deepcopy(placement), style={"stroke": None, "fill": None,
                                                         "text": None, "effect": None})
    obj["geometry"]["corner_radius"] = None
    raw["plan_sha256"] = digest(plan)
    return plan, raw


def test_plan_layout_retain_the_same_authored_image_placement():
    plan, layout = image_documents()
    validate_plan_layout(plan, layout)
    layout["objects"][0]["image_placement"]["focal_point"]["x"] = 0.0
    with pytest.raises(ValueError, match="semantic field image_placement"):
        validate_plan_layout(plan, layout)


@pytest.mark.parametrize("field,value", [
    ("revision", 2), ("checksum_sha256", "b" * 64), ("width", 81), ("height", 41),
    ("kind", "icon"), ("allowed_transformations", ["scale", "crop", "rotate"]),
])
def test_placement_cannot_grant_itself_different_asset_pins_or_permissions(field, value):
    plan, layout = image_documents()
    plan["assets"][0][field] = value
    layout["plan_sha256"] = digest(plan)
    with pytest.raises(ValueError, match="image_placement.*asset"):
        validate_plan_layout(plan, layout)


def test_one_expanded_permission_use_cannot_authorize_a_bare_sibling():
    plan, layout = image_documents()
    for document in (plan, layout):
        previous = document["objects"][1]
        sibling = deepcopy(document["objects"][0])
        for key in ("object_id", "coverage_ids", "semantic_role", "description"):
            sibling[key] = previous[key]
        sibling["image_placement"]["focal_point"] = {"x": 0.0, "y": 1.0}
        document["objects"][1] = sibling
    plan["actions"][1]["verb"] = "reveal"
    layout["plan_sha256"] = digest(plan)
    validate_plan_layout(plan, layout)
    for document in (plan, layout):
        document["objects"][1].pop("image_placement")
    layout["plan_sha256"] = digest(plan)
    with pytest.raises(ValueError, match="bare image expanded asset permissions"):
        validate_plan_layout(plan, layout)
