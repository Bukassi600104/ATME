"""Owning P3-39 definition foundation, not instance/renderer admission."""
import hashlib
import io
import json
import xml.etree.ElementTree as ET
from copy import deepcopy

import pytest
from atme.store import contracts_v2 as contracts
from jsonschema import Draft202012Validator
from v2_fixtures import executable_layout_v2


def composition_definition():
    node, label = deepcopy(executable_layout_v2()["objects"][:2])
    for obj, key in ((node, "node"), (label, "label")):
        obj.update(object_id=key, parent_id="root", board_id="template-board",
                   beat_id="template-beat", visible=True, initial_state="visible")
    root = deepcopy(node)
    root.pop("path_data")
    root.update(object_id="root", parent_id=None, object_type="group", z_index=0,
                child_ids=["node", "label"], anchors=[], coverage_ids=["coverage-1", "coverage-2"],
                style={"stroke": None, "fill": None, "text": None, "effect": None})
    return {
        "version": "1.0.0", "definition_id": "system-card", "revision": 1,
        "root_local_id": "root", "template_board_id": "template-board",
        "template_beat_id": "template-beat", "template_coverage_ids": ["coverage-1", "coverage-2"],
        "objects": [root, node, label],
        "parameters": [
            {"parameter_id": "caption", "value_type": "string",
             "targets": [{"object_id": "label", "field": "text"}]},
            {"parameter_id": "color", "value_type": "string",
             "targets": [{"object_id": "node", "field": "style.fill"}]},
            {"parameter_id": "width", "value_type": "number",
             "targets": [{"object_id": "node", "field": "geometry.bounds.width"}]},
            {"parameter_id": "shown", "value_type": "boolean",
             "targets": [{"object_id": "label", "field": "visible"}]},
        ],
    }


def definition_type():
    assert hasattr(contracts, "CompositionDefinition"), "strict reusable definition contract is missing"
    return contracts.CompositionDefinition


def test_definition_preserves_real_objects_context_and_required_parameters():
    raw = composition_definition()
    model = definition_type().model_validate(raw)
    expected = deepcopy(raw)
    adapter = contracts.TypeAdapter(contracts.ExecutableObject)
    expected["objects"] = [adapter.validate_python(obj).model_dump(mode="json") for obj in raw["objects"]]
    assert model.model_dump(mode="json") == expected
    assert type(model.objects[0]) is contracts.GroupContainer
    assert type(model.objects[1]) is contracts.MarkObject
    assert type(model.objects[2]) is contracts.TextObject
    assert all("default_value" not in param for param in expected["parameters"])
    Draft202012Validator(definition_type().model_json_schema()).validate(expected)


def test_definition_digest_validates_then_hashes_canonical_content_without_reordering_arrays():
    raw = composition_definition()
    canonical = definition_type().model_validate(raw).model_dump(mode="json")
    expected = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":"),
                                        ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()
    assert contracts.composition_definition_digest(raw) == expected
    assert contracts.composition_definition_digest(dict(reversed(list(raw.items())))) == expected
    reordered = deepcopy(raw)
    reordered["objects"][1:] = reversed(reordered["objects"][1:])
    assert contracts.composition_definition_digest(reordered) != expected
    for path in ("revision", "definition_id"):
        changed = deepcopy(raw)
        changed[path] = 2 if path == "revision" else "another-card"
        assert contracts.composition_definition_digest(changed) != expected


@pytest.mark.parametrize("defect", [
    "duplicate_id", "unknown_root", "leaf_root", "second_root", "foreign_parent", "missing_child",
    "duplicate_child", "nonreciprocal", "cycle", "empty_container", "foreign_board", "foreign_beat",
    "foreign_coverage", "duplicate_coverage", "unused_coverage", "external_clip", "nested_composition",
    "nested_instance", "unknown_anchor", "foreign_connector", "duplicate_anchor", "unresolved_mask",
])
def test_definition_rejects_open_or_inconsistent_template_namespace(defect):
    raw = composition_definition()
    root, node, label = raw["objects"]
    if defect == "duplicate_id":
        label["object_id"] = "node"
    elif defect == "unknown_root":
        raw["root_local_id"] = "elsewhere"
    elif defect == "leaf_root":
        raw["root_local_id"] = "node"
    elif defect == "second_root":
        label["parent_id"] = None
    elif defect == "foreign_parent":
        label["parent_id"] = "outer-project-object"
    elif defect == "missing_child":
        root["child_ids"].append("outer-project-object")
    elif defect == "duplicate_child":
        root["child_ids"].append("node")
    elif defect == "nonreciprocal":
        root["child_ids"].remove("label")
    elif defect == "cycle":
        root["parent_id"] = "root"
        root["child_ids"].append("root")
    elif defect == "empty_container":
        root["child_ids"] = []
    elif defect == "foreign_board":
        label["board_id"] = "outer-board"
    elif defect == "foreign_beat":
        label["beat_id"] = "outer-beat"
    elif defect == "foreign_coverage":
        label["coverage_ids"] = ["outer-coverage"]
    elif defect == "duplicate_coverage":
        raw["template_coverage_ids"].append("coverage-1")
    elif defect == "unused_coverage":
        raw["template_coverage_ids"].append("unused")
    elif defect == "external_clip":
        node["clip_id"] = "outer-clip"
    elif defect in {"nested_composition", "nested_instance"}:
        node.pop("path_data")
        node.update(object_type=defect.removeprefix("nested_"), variant=None)
    elif defect == "duplicate_anchor":
        node["anchors"].append(deepcopy(node["anchors"][0]))
    elif defect == "unresolved_mask":
        node.pop("path_data")
        node.update(object_type="mask", child_ids=["label"])
        label["parent_id"] = "node"
        root["child_ids"].remove("label")
    else:
        arrow = deepcopy(node)
        arrow.pop("path_data")
        arrow.update(object_id="leader", object_type="arrow", source_object_id=None,
                     source_anchor_id=None, destination_object_id="label", destination_anchor_id="center",
                     role="pointer", routing="straight", allow_self_loop=False)
        if defect == "unknown_anchor":
            arrow["destination_anchor_id"] = "outer-anchor"
        else:
            arrow["destination_object_id"] = "outer-object"
        raw["objects"].append(arrow)
        root["child_ids"].append("leader")
    with pytest.raises(ValueError):
        definition_type().model_validate(raw)


@pytest.mark.parametrize("defect", [
    "unknown_parameter_field", "unknown_target", "wrong_type", "duplicate_parameter", "duplicate_target",
    "overlapping_target", "empty_targets", "code_text", "list_text", "default", "numeric_bool",
    "nonfinite", "unknown_nested_field", "unknown_parameter_payload", "model_object", "model_target",
])
def test_definition_rejects_ambiguous_parameters_and_non_wire_payloads(defect):
    raw = composition_definition()
    params = raw["parameters"]
    label = raw["objects"][2]
    if defect == "unknown_parameter_field":
        params[0]["targets"][0]["field"] = "__dict__.text"
    elif defect == "unknown_target":
        params[0]["targets"][0]["object_id"] = "outer-object"
    elif defect == "wrong_type":
        params[0]["value_type"] = "number"
    elif defect == "duplicate_parameter":
        params[1]["parameter_id"] = "caption"
    elif defect == "duplicate_target":
        params[0]["targets"].append(deepcopy(params[0]["targets"][0]))
    elif defect == "overlapping_target":
        params[1]["targets"] = deepcopy(params[0]["targets"])
    elif defect == "empty_targets":
        params[0]["targets"] = []
    elif defect in {"code_text", "list_text"}:
        label["object_type"] = defect.removesuffix("_text")
    elif defect == "default":
        params[0]["default_value"] = "implicit"
    elif defect == "numeric_bool":
        label["geometry"]["bounds"]["width"] = True
    elif defect == "nonfinite":
        label["opacity"] = float("nan")
    elif defect == "unknown_nested_field":
        label["geometry"]["computed"] = 42
    elif defect == "unknown_parameter_payload":
        params[0]["targets"][0]["expression"] = "evaluate()"
    elif defect == "model_object":
        raw["objects"][2] = contracts.TextObject.model_validate(label)
    else:
        class ForeignTarget:
            object_id = "label"
            field = "text"
        params[0]["targets"][0] = ForeignTarget()
    with pytest.raises(ValueError):
        definition_type().model_validate(raw)


@pytest.mark.parametrize("kind", ["composition", "instance"])
def test_legacy_bare_visual_shapes_remain_exact_and_have_no_binding(kind):
    obj = deepcopy(executable_layout_v2()["objects"][0])
    obj.pop("path_data")
    obj.update(object_type=kind, variant=None)
    assert contracts.VisualObject.model_validate(obj).model_dump(mode="json") == obj


def bound_native_definition(family):
    if family == "character":
        from test_v2_character_assembly_contract import documents
        objects = documents()[1]["objects"][-5:]
    elif family == "illustration":
        from test_v2_illustration_assembly_contract import documents
        objects = documents()[1]["objects"][-3:]
    elif family == "technical":
        from test_v2_technical_frame_contract import documents
        objects = documents()[1]["objects"]
    elif family == "list":
        from test_v2_structured_list_contract import documents
        objects = documents()[1]["objects"]
    else:
        from test_v2_callout_contract import callout_documents
        objects = callout_documents()[1]["objects"]
    raw = composition_definition()
    root = raw["objects"][0]
    raw["parameters"] = []
    raw["template_coverage_ids"] = sorted({key for obj in objects for key in obj["coverage_ids"]})
    root["coverage_ids"] = deepcopy(raw["template_coverage_ids"])
    root["child_ids"] = []
    for obj in objects:
        obj.update(board_id=raw["template_board_id"], beat_id=raw["template_beat_id"])
        if obj["parent_id"] is None:
            obj["parent_id"] = "root"
            root["child_ids"].append(obj["object_id"])
    raw["objects"] = [root, *objects]
    return raw


@pytest.mark.parametrize("family", ["character", "illustration", "technical", "list", "callout"])
@pytest.mark.parametrize("foreign", [False, True])
def test_native_payload_references_are_closed_not_resolved_against_outer_project(family, foreign):
    raw = bound_native_definition(family)
    if foreign:
        owner_field = {"character": "character_assembly", "illustration": "illustration_assembly",
                       "technical": "technical_frame", "list": "structured_list", "callout": "callout_binding"}[family]
        binding = next(obj[owner_field] for obj in raw["objects"] if owner_field in obj)
        if family in {"character", "illustration", "technical"}:
            binding["roles"][0]["object_id"] = "outer-object"
        elif family == "list":
            binding["item_object_ids"][0] = "outer-object"
        else:
            binding["target_object_id"] = "outer-object"
        with pytest.raises(ValueError):
            definition_type().model_validate(raw)
    else:
        model = definition_type().model_validate(raw)
        assert len(model.objects) == len(raw["objects"])
        assert contracts.composition_definition_digest(raw)


@pytest.mark.parametrize("kind", ["clip", "mask"])
def test_internal_clip_mask_ownership_is_real_and_keeps_external_references_closed(kind):
    raw = composition_definition()
    root, _node, label = raw["objects"]
    raw["parameters"] = []
    container = deepcopy(root)
    container.update(object_id="aperture", object_type=kind, parent_id="root", child_ids=["label"])
    label["parent_id"] = "aperture"
    root["child_ids"] = ["node", "aperture"]
    if kind == "mask":
        container.update(mask_mode="alpha", mask_source_object_id="node", mask_coordinate_space="parent_local",
                         invert=False, feather_px=0)
        container["geometry"]["corner_radius"] = None
    raw["objects"].append(container)
    model = definition_type().model_validate(raw)
    assert model.objects[-1].child_ids == ["label"]
    if kind == "mask":
        container["mask_source_object_id"] = "outer-source"
    else:
        label["clip_id"] = "aperture"
    with pytest.raises(ValueError):
        definition_type().model_validate(raw)


@pytest.mark.parametrize("field,value_type", [
    ("text", "string"), ("style.stroke", "string"), ("style.fill", "string"), ("style.text", "string"),
    ("geometry.bounds.x", "number"), ("geometry.bounds.y", "number"),
    ("geometry.bounds.width", "number"), ("geometry.bounds.height", "number"),
    ("transform.position.x", "number"), ("transform.position.y", "number"),
    ("transform.scale_x", "number"), ("transform.scale_y", "number"),
    ("transform.rotation_degrees", "number"), ("opacity", "number"), ("visible", "boolean"),
])
def test_finite_target_inventory_has_exact_scalar_types(field, value_type):
    raw = composition_definition()
    raw["parameters"] = [{"parameter_id": "explicit", "value_type": value_type,
                          "targets": [{"object_id": "node" if field in {"style.stroke", "style.fill"}
                                       else "label", "field": field}]}]
    assert definition_type().model_validate(raw).parameters[0].value_type == value_type
    raw["parameters"][0]["value_type"] = "string" if value_type != "string" else "number"
    with pytest.raises(ValueError):
        definition_type().model_validate(raw)


def test_definition_hash_refuses_invalid_content_rather_than_laundering_it():
    raw = composition_definition()
    raw["objects"][1]["transform"]["position"]["x"] = True
    with pytest.raises(ValueError):
        contracts.composition_definition_digest(raw)
    raw = composition_definition()
    raw["definition_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        contracts.composition_definition_digest(raw)


def test_definition_rejects_depth_beyond_existing_eight_ancestor_limit():
    raw = composition_definition()
    root, _node, label = raw["objects"]
    root["child_ids"] = ["nested-1", "node"]
    for depth in range(1, 10):
        group = deepcopy(root)
        group.update(object_id=f"nested-{depth}", parent_id="root" if depth == 1 else f"nested-{depth-1}",
                     child_ids=["label"] if depth == 9 else [f"nested-{depth+1}"])
        raw["objects"].append(group)
    label["parent_id"] = "nested-9"
    with pytest.raises(ValueError, match="eight ancestor"):
        definition_type().model_validate(raw)


@pytest.mark.parametrize("field", ["style.stroke", "style.fill"])
def test_parameter_target_must_be_consumed_by_the_exact_native_object(field):
    raw = composition_definition()
    raw["parameters"] = [{"parameter_id": "bad-style", "value_type": "string",
                          "targets": [{"object_id": "label", "field": field}]}]
    with pytest.raises(ValueError, match="consumed"):
        definition_type().model_validate(raw)


def test_definition_cannot_exceed_the_existing_one_board_density_ceiling():
    raw = composition_definition()
    for index in range(10):
        part = deepcopy(raw["objects"][1])
        part["object_id"] = f"extra-{index}"
        raw["objects"].append(part)
        raw["objects"][0]["child_ids"].append(part["object_id"])
    assert len(raw["objects"]) == 13
    with pytest.raises(ValueError):
        definition_type().model_validate(raw)
    schema = definition_type().model_json_schema()
    root = schema["$defs"][schema["$ref"].split("/")[-1]] if "$ref" in schema else schema
    assert root["properties"]["objects"]["maxItems"] == 12


@pytest.mark.parametrize("subclass", [False, True])
@pytest.mark.parametrize("digest", [False, True])
def test_top_level_model_and_subclass_cannot_bypass_raw_wire_validation(subclass, digest):
    model = definition_type().model_validate(composition_definition())
    if subclass:
        class UnknownDefinition(definition_type()):
            pass
        model = UnknownDefinition.model_construct(**model.__dict__)
    with pytest.raises(ValueError):
        if digest:
            contracts.composition_definition_digest(model)
        else:
            definition_type().model_validate(model)


def parameter_owner_definition(kind):
    if kind in {"connector", "technical"}:
        raw = bound_native_definition("callout" if kind == "connector" else "technical")
        key = next(obj["object_id"] for obj in raw["objects"]
                   if obj["object_type"] == ("arrow" if kind == "connector" else "browser"))
        return raw, key
    raw = composition_definition()
    raw["parameters"] = []
    if kind == "group":
        return raw, "root"
    if kind == "text":
        return raw, "label"
    node = raw["objects"][1]
    if kind == "code":
        from test_v2_code_contract import code_object
        code = code_object()
        for field in ("object_id", "board_id", "beat_id", "parent_id", "coverage_ids"):
            code[field] = deepcopy(node[field])
        code["style"] = {"stroke": None, "fill": None, "text": "text.code", "effect": None}
        raw["objects"][1] = code
    elif kind == "freehand":
        node.update(object_type="freehand", path_data="M 80 160 L 100 190")
        node["geometry"]["corner_radius"] = None
        node["style"]["fill"] = None
    elif kind in {"image", "evidence", "registry", "chart"}:
        node.pop("path_data")
        node.update(object_type="icon" if kind == "registry" else kind, variant=None,
                    style={"stroke": None, "fill": None, "text": None, "effect": None})
        node["geometry"]["corner_radius"] = None
        if kind == "chart":
            from test_v2_chart_contract import authored_payload
            node["chart_payload"] = authored_payload()
        elif kind in {"image", "evidence"}:
            node["asset_id"] = "checked-later-at-owner-boundary"
        else:
            node["variant"] = "concept-lightbulb"
    return raw, "node"


@pytest.mark.parametrize("kind,field,consumed", [
    ("group", "style.stroke", False), ("group", "style.fill", False),
    ("group", "style.text", False), ("group", "geometry.bounds.width", False),
    ("group", "transform.scale_x", True), ("group", "opacity", True),
    ("mark", "style.text", False), ("mark", "style.fill", True),
    ("freehand", "style.fill", False), ("freehand", "geometry.bounds.x", False),
    ("freehand", "style.stroke", True), ("freehand", "transform.position.x", True),
    ("text", "style.fill", False), ("text", "style.text", True),
    ("code", "text", False), ("code", "style.text", False),
    ("code", "geometry.bounds.width", True),
    ("registry", "style.stroke", False), ("registry", "style.fill", False),
    ("registry", "style.text", False), ("registry", "geometry.bounds.width", True),
    ("image", "style.stroke", False), ("image", "style.fill", False),
    ("image", "style.text", False), ("image", "transform.rotation_degrees", False),
    ("image", "transform.position.x", True),
    ("evidence", "style.fill", True), ("evidence", "style.text", False),
    ("evidence", "style.stroke", True),
    ("chart", "text", False), ("chart", "style.stroke", True),
    ("chart", "style.fill", True), ("chart", "style.text", True),
    ("technical", "style.text", False), ("technical", "style.fill", True),
    ("connector", "style.fill", False), ("connector", "style.text", False),
    ("connector", "geometry.bounds.x", False), ("connector", "transform.position.x", False),
    ("connector", "style.stroke", True), ("connector", "visible", True),
])
def test_parameter_applicability_matches_native_owner_not_a_generic_path(kind, field, consumed):
    raw, key = parameter_owner_definition(kind)
    definition_type().model_validate(raw)
    value_type = "boolean" if field == "visible" else "string" if field == "text" or field.startswith("style.") else "number"
    raw["parameters"] = [{"parameter_id": "authored", "value_type": value_type,
                          "targets": [{"object_id": key, "field": field}]}]
    if consumed:
        assert definition_type().model_validate(raw).parameters[0].targets[0].object_id == key
    else:
        with pytest.raises(ValueError, match="consumed"):
            definition_type().model_validate(raw)


def test_definition_json_entrypoint_retains_the_same_exact_closed_contract():
    raw = composition_definition()
    model = definition_type().model_validate_json(json.dumps(raw))
    assert model.model_dump(mode="json") == definition_type().model_validate(raw).model_dump(mode="json")


@pytest.mark.parametrize("portrait", [False, True])
def test_evidence_fill_parameter_has_real_native_backing_pixels(tmp_path, portrait):
    from atme.render.style_bundle import resolve_contract_bundle
    from atme.render.v2_svg import (
        UnsupportedVisualObject,
        compose_png_frame,
        compose_svg_frame,
    )
    from PIL import Image
    from test_v2_evidence_compositor import evidence_documents
    from v2_fixtures import digest

    service, layout, timeline, verified = evidence_documents(tmp_path, portrait=portrait)
    try:
        evidence = layout["objects"][2]
        raw, key = parameter_owner_definition("evidence")
        raw["objects"][1]["asset_id"] = evidence["asset_id"]
        raw["parameters"] = [{"parameter_id": "backing", "value_type": "string",
                              "targets": [{"object_id": key, "field": "style.fill"}]}]
        definition_type().model_validate(raw)
        style, _, _ = resolve_contract_bundle(layout["style_system_version"], layout["asset_registry_version"])
        payload = {verified.asset_id: verified}
        bounds = evidence["geometry"]["bounds"]
        point = (int(bounds["x"] + 25), int(bounds["y"] + 12))
        results = []
        for token, color in (("surface.paper", style.colors["paper"]),
                             ("surface.accent", style.colors["accent-soft"])):
            evidence["style"]["fill"] = token
            timeline["layout_sha256"] = digest(layout)
            svg = ET.fromstring(compose_svg_frame(layout, timeline, 4900, payload).svg)
            owner = next(node for node in svg.iter() if node.attrib.get("data-object-id") == evidence["object_id"])
            backing = [node for node in owner.iter() if node.tag.endswith("}rect")
                       and float(node.attrib.get("width", "0")) == bounds["width"]
                       and float(node.attrib.get("height", "0")) == bounds["height"]
                       and node.attrib.get("fill") == color]
            assert len(backing) == 1
            png = compose_png_frame(layout, timeline, 4900, payload).png
            with Image.open(io.BytesIO(png)) as image:
                rgb = image.convert("RGB").getpixel(point)
            assert rgb == tuple(int(color[index:index+2], 16) for index in (1, 3, 5))
            results.append((rgb, png))
        assert results[0][0] != results[1][0] and results[0][1] != results[1][1]
        (tmp_path / "evidence-backing.png").write_bytes(results[1][1])
        evidence["style"]["text"] = "text.body"
        timeline["layout_sha256"] = digest(layout)
        with pytest.raises(UnsupportedVisualObject, match="unsupported styling"):
            compose_svg_frame(layout, timeline, 4900, payload)
    finally:
        service.store.close()
