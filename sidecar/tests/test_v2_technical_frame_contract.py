"""P3-29 content binds real authored parts, not synthetic window inventories."""

import json
from copy import deepcopy
from hashlib import sha256

import pytest
from conftest import load_schema
from jsonschema import Draft202012Validator
from test_v2_progressive_list import list_documents as flat_list_documents
from test_v2_split_identity import sample_for_layout
from test_v2_structured_list_contract import documents as list_documents
from v2_fixtures import digest

from atme.render.v2_split_identity import split_content_receipts
from atme.render.v2_svg import UnsupportedVisualObject, compose_svg_frame
from atme.store import contracts_v2 as contracts

# Literal independent expectations: changing an admitted kind's state/role
# interpretation must invalidate the wrong contract, never alias its content.
CASES = [
    ("browser", ["ready", "loading", "error"], ["title", "address", "content"]),
    ("application", ["ready", "busy", "error"], ["title", "navigation", "content"]),
    ("server", ["idle", "active", "offline"], ["title", "content"]),
    ("database", ["idle", "active", "offline"], ["title", "content"]),
    ("folder", ["closed", "open"], ["title", "content"]),
    ("comparison", ["balanced", "contrast"], ["left_title", "left_content", "right_title", "right_content"]),
]


def documents(kind="browser", state="ready", roles=None):
    roles = roles or ["title", "address", "content"]
    plan, layout = list_documents()
    objects = {obj["object_id"]: obj for obj in layout["objects"]}
    chrome = objects["object-evidence"]
    template = deepcopy(objects["list-item-a"])
    chrome.pop("text")
    chrome.pop("items")
    chrome.pop("structured_list")
    chrome.update(object_type=kind, variant=state, asset_id=None,
        style={"stroke": "ink-primary", "fill": None, "text": None, "effect": None},
        anchors=[{"anchor_id": "chrome-top", "point": {"x": .5, "y": 0.0}}],
        technical_frame={"version": "1.0.0", "container_group_id": "list-group",
            "display_state": state,
            "roles": [{"role": role, "object_id": "part-" + role} for role in roles],
            "anchor_mappings": [{"placed_anchor_id": "chrome-top", "native_anchor_name": "top"}]})
    chrome["geometry"]["bounds"] = {"x": 680.0, "y": 130.0, "width": 500.0, "height": 420.0}
    parts = []
    for index, role in enumerate(roles):
        part = deepcopy(template)
        part.update(object_id="part-" + role, text="Authored " + role, z_index=index + 1,
            board_id=chrome["board_id"], beat_id=chrome["beat_id"], coverage_ids=deepcopy(chrome["coverage_ids"]))
        parts.append(part)
    group = objects["list-group"]
    group["child_ids"] = [chrome["object_id"], *[part["object_id"] for part in parts]]
    layout["objects"] = [obj for obj in layout["objects"] if not obj["object_id"].startswith("list-item-")] + parts
    layout["boards"][0].update(object_ids=[obj["object_id"] for obj in layout["objects"]], density_limit=9)
    fields = ("object_id", "object_type", "board_id", "beat_id", "semantic_role", "description",
        "asset_id", "initial_state", "coverage_ids", "technical_frame", "child_ids")
    plan["objects"] = [{key: deepcopy(obj[key]) for key in fields if key in obj} for obj in layout["objects"]]
    plan["boards"] = deepcopy(layout["boards"])
    for beat in plan["beats"]:
        beat["object_ids"] = [obj["object_id"] for obj in plan["objects"] if obj["beat_id"] == beat["beat_id"]]
    layout["plan_sha256"] = digest(plan)
    return plan, layout


def binding_model():
    assert hasattr(contracts, "TechnicalFrameBinding"), "strict real-part technical binding is missing"
    return contracts.TechnicalFrameBinding


@pytest.mark.parametrize("kind,states,roles", CASES)
def test_native_state_is_authored_content_not_operator_lifecycle(kind, states, roles):
    for state in states:
        plan, raw = documents(kind, state, roles)
        contracts.validate_plan_layout(plan, raw)
        layout = contracts.ExecutableLayoutV2.model_validate(raw)
        chrome = next(obj for obj in layout.objects if obj.object_id == "object-evidence")
        assert chrome.initial_state == "hidden"
        assert chrome.variant == state
        assert chrome.technical_frame.model_dump(mode="json") == raw["objects"][2]["technical_frame"]


@pytest.mark.parametrize("fault", ["version", "blank_group", "blank_part", "duplicate_part",
    "duplicate_role", "no_roles", "implicit_content", "blank_anchor", "unknown_anchor", "alias_anchor"])
def test_strict_binding_cannot_invent_or_ignore_content_and_anchors(fault):
    raw = documents()[1]["objects"][2]["technical_frame"]
    if fault == "version":
        raw["version"] = "2.0.0"
    elif fault == "blank_group":
        raw["container_group_id"] = " "
    elif fault == "blank_part":
        raw["roles"][0]["object_id"] = " "
    elif fault == "duplicate_part":
        raw["roles"][1]["object_id"] = raw["roles"][0]["object_id"]
    elif fault == "duplicate_role":
        raw["roles"][1]["role"] = raw["roles"][0]["role"]
    elif fault == "no_roles":
        raw["roles"] = []
    elif fault == "implicit_content":
        raw["content"] = ["Fake default label"]
    elif fault == "blank_anchor":
        raw["anchor_mappings"][0]["placed_anchor_id"] = " "
    elif fault == "unknown_anchor":
        raw["anchor_mappings"][0]["native_anchor_name"] = "center"
    else:
        raw["anchor_mappings"].append({"placed_anchor_id": "alias", "native_anchor_name": "top"})
    with pytest.raises(ValueError):
        binding_model().model_validate(raw)


@pytest.mark.parametrize("fault", ["wrong_kind", "wrong_state", "wrong_variant", "wrong_roles",
    "unmapped_anchor", "self_group", "self_part", "registry_binding"])
def test_chrome_owner_cannot_reinterpret_binding(fault):
    binding_model()
    raw = documents()[1]["objects"][2]
    if fault == "wrong_kind":
        raw["object_type"] = "device"
    elif fault == "wrong_state":
        raw["variant"] = raw["technical_frame"]["display_state"] = "busy"
    elif fault == "wrong_variant":
        raw["variant"] = "error"
    elif fault == "wrong_roles":
        raw["technical_frame"]["roles"].reverse()
    elif fault == "unmapped_anchor":
        raw["anchors"].append({"anchor_id": "extra", "point": {"x": 1, "y": .5}})
    elif fault == "self_group":
        raw["technical_frame"]["container_group_id"] = raw["object_id"]
    elif fault == "self_part":
        raw["technical_frame"]["roles"][0]["object_id"] = raw["object_id"]
    else:
        raw["registry_binding"] = {"version": "1.0.0", "asset_id": "device-laptop",
            "anchor_mappings": [{"placed_anchor_id": "chrome-top", "registry_anchor_name": "top"}]}
    with pytest.raises(ValueError, match="technical_frame|registry_binding"):
        contracts.VisualObject.model_validate(raw)


@pytest.mark.parametrize("semantic", [False, True])
@pytest.mark.parametrize("fault", ["unknown_group", "wrong_group", "missing_part", "wrong_kind",
    "wrong_order", "foreign_child", "cross_beat", "changed_coverage"])
def test_contract_requires_complete_real_group_and_role_ownership(semantic, fault):
    binding_model()
    plan, layout = documents()
    document = plan if semantic else layout
    objects = {obj["object_id"]: obj for obj in document["objects"]}
    chrome = objects["object-evidence"]
    group = objects["list-group"]
    if fault == "unknown_group":
        chrome["technical_frame"]["container_group_id"] = "absent"
    elif fault == "wrong_group":
        chrome["technical_frame"]["container_group_id"] = "object-system"
    elif fault == "missing_part":
        chrome["technical_frame"]["roles"][0]["object_id"] = "absent"
    elif fault == "wrong_kind":
        objects["part-title"]["object_type"] = "rectangle"
        if not semantic:
            objects["part-title"].pop("text")
            objects["part-title"].pop("items")
            objects["part-title"]["path_data"] = None
    elif fault == "wrong_order":
        group["child_ids"].reverse()
    elif fault == "foreign_child":
        group["child_ids"].append("object-label")
        if not semantic:
            objects["object-label"]["parent_id"] = group["object_id"]
    elif fault == "cross_beat":
        objects["part-title"]["beat_id"] = "beat-001"
    else:
        objects["part-content"]["coverage_ids"] = ["coverage-1"]
    with pytest.raises(ValueError, match="technical_frame"):
        (contracts.VisualPlanV2 if semantic else contracts.ExecutableLayoutV2).model_validate(document)


@pytest.mark.parametrize("fault", ["removed", "different_valid_state"])
def test_layout_cannot_add_or_change_semantic_native_meaning(fault):
    binding_model()
    plan, layout = documents()
    chrome = next(obj for obj in plan["objects"] if obj["object_id"] == "object-evidence")
    if fault == "removed":
        chrome.pop("technical_frame")
    else:
        chrome["technical_frame"]["display_state"] = "error"
    with pytest.raises(ValueError, match="changes semantic field technical_frame"):
        contracts.validate_plan_layout(plan, layout)


def test_identity_pins_native_binding_and_preserves_bare_legacy_hash():
    binding_model()
    plan, raw = documents()
    chrome = raw["objects"][2]
    for bound in (True, False):
        if not bound:
            chrome.pop("technical_frame")
        layout = contracts.ExecutableLayoutV2.model_validate(raw)
        receipt = next(row for row in split_content_receipts(layout, sample_for_layout(layout), {})
            if row.object_id == chrome["object_id"])
        payload = {key: chrome[key] for key in ("object_type", "geometry", "style", "anchors", "asset_id", "variant")}
        if bound:
            payload["technical_frame"] = chrome["technical_frame"]
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        assert receipt.canonical_json == encoded
        assert receipt.content_sha256 == sha256(encoded.encode()).hexdigest()
        if not bound:
            assert "technical_frame" not in layout.objects[2].model_dump(mode="json")
            plan["objects"][2].pop("technical_frame")
            assert "technical_frame" not in contracts.VisualPlanV2.model_validate(plan).objects[2].model_dump(mode="json")


@pytest.mark.parametrize("name", ["visual-plan-v2", "executable-layout-v2"])
def test_json_schema_preserves_bound_contract_and_rejects_wrong_native_kind(name):
    plan, layout = documents()
    document = plan if name == "visual-plan-v2" else layout
    schema = Draft202012Validator(load_schema(name))
    schema.validate(document)
    document["objects"][2]["object_type"] = "device"
    assert list(schema.iter_errors(document))


def nested_documents():
    plan, layout = documents()
    objects = {obj["object_id"]: obj for obj in layout["objects"]}
    content = objects["part-content"]
    leaf = deepcopy(content)
    leaf.update(object_id="content-leaf", parent_id=content["object_id"], z_index=0)
    content.pop("text")
    content.pop("items")
    content.update(object_type="group", child_ids=[leaf["object_id"]],
        style={"stroke": None, "fill": None, "text": None, "effect": None})
    layout["objects"].append(leaf)
    layout["boards"][0]["object_ids"].append(leaf["object_id"])
    fields = list(plan["objects"][0])
    spec = next(obj for obj in plan["objects"] if obj["object_id"] == content["object_id"])
    spec.update(object_type="group", child_ids=[leaf["object_id"]])
    plan["objects"].append({key: deepcopy(leaf[key]) for key in fields})
    plan["boards"] = deepcopy(layout["boards"])
    for beat in plan["beats"]:
        if beat["beat_id"] == leaf["beat_id"]:
            beat["object_ids"].append(leaf["object_id"])
    layout["plan_sha256"] = digest(plan)
    return plan, layout


def test_content_group_is_real_explicit_tree_not_virtual_chrome_parts():
    plan, layout = nested_documents()
    contracts.validate_plan_layout(plan, layout)
    parsed = contracts.ExecutableLayoutV2.model_validate(layout)
    receipts = {row.object_id: row for row in split_content_receipts(parsed, sample_for_layout(parsed), {})}
    content = json.loads(receipts["part-content"].canonical_json)
    assert content["children"][0]["object_id"] == "content-leaf"
    assert "content-leaf" in receipts


@pytest.mark.parametrize("semantic", [False, True])
def test_title_cannot_bind_a_group_even_if_it_contains_text(semantic):
    plan, layout = nested_documents()
    document = plan if semantic else layout
    objects = {obj["object_id"]: obj for obj in document["objects"]}
    objects["object-evidence"]["technical_frame"]["roles"][0]["object_id"] = "part-content"
    objects["object-evidence"]["technical_frame"]["roles"][2]["object_id"] = "part-title"
    objects["list-group"]["child_ids"] = ["object-evidence", "part-content", "part-address", "part-title"]
    if not semantic:
        objects["part-content"]["z_index"], objects["part-title"]["z_index"] = 1, 3
    with pytest.raises(ValueError, match="technical_frame role requires real plain Text"):
        (contracts.VisualPlanV2 if semantic else contracts.ExecutableLayoutV2).model_validate(document)


@pytest.mark.parametrize("field", ["version", "container_group_id", "display_state", "roles", "anchor_mappings"])
def test_binding_has_no_generated_defaults(field):
    raw = documents()[1]["objects"][2]["technical_frame"]
    raw.pop(field)
    with pytest.raises(ValueError):
        binding_model().model_validate(raw)


@pytest.mark.parametrize("nested", ["binding", "role", "mapping"])
def test_identity_refuses_bypassed_unknown_native_payload_subclasses(nested):
    _, raw = documents()
    layout = contracts.ExecutableLayoutV2.model_validate(raw)
    obj = layout.objects[2]
    if nested == "binding":
        class UnknownBinding(contracts.TechnicalFrameBinding):
            invented: str = "virtual"
        obj.technical_frame = UnknownBinding.model_validate(obj.technical_frame.model_dump())
    elif nested == "role":
        class UnknownRole(contracts.TechnicalRoleBinding):
            invented: str = "virtual"
        obj.technical_frame.roles[0] = UnknownRole.model_validate(obj.technical_frame.roles[0].model_dump())
    else:
        class UnknownMapping(contracts.TechnicalAnchorMapping):
            invented: str = "virtual"
        obj.technical_frame.anchor_mappings[0] = UnknownMapping.model_validate(obj.technical_frame.anchor_mappings[0].model_dump())
    with pytest.raises(ValueError, match="unknown nested payload subclass"):
        split_content_receipts(layout, sample_for_layout(layout), {})


@pytest.mark.parametrize("bound", [False, True])
def test_contract_identity_does_not_admit_unproven_native_or_fallback_paint(bound):
    plan, layout = documents()
    if not bound:
        layout["objects"][2].pop("technical_frame")
    _, timeline = flat_list_documents()
    for item, action in zip(timeline["actions"], plan["actions"], strict=True):
        item["action"] = action
    timeline["initial_object_states"] = [{"object_id": obj["object_id"], "state": obj["initial_state"],
        "state_version": 1, "visible": obj["visible"]} for obj in layout["objects"]]
    timeline["layout_sha256"] = digest(layout)
    timeline["plan_sha256"] = layout["plan_sha256"]
    if bound:
        # This contract-only fixture deliberately places top at viewport y=0,
        # not the actual physical native y=10. It must never gain fallback paint.
        with pytest.raises(ValueError, match="physical native anchor"):
            compose_svg_frame(layout, timeline, 1000)
    else:
        with pytest.raises(UnsupportedVisualObject, match="browser, which has no SVG implementation"):
            compose_svg_frame(layout, timeline, 1000)
