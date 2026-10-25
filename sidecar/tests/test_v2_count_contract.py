"""Authored numeric policy is explicit; bare legacy Count is not invented."""

from copy import deepcopy
from decimal import getcontext

import pytest
from pydantic import ValidationError
from test_v2_isolate_action import isolate_documents
from test_v2_morph_action import semantic_plan

from atme.store.contracts_v2 import TargetAction, validate_plan_evidence_completeness


def count_policy(**updates):
    policy = {"text_object_id": "object-evidence", "start_value": "0", "end_value": "10",
              "decimal_places": 0, "rounding": "half_even", "step_count": 10,
              "grouping": "none", "unit": "widgets", "unit_placement": "after", "separator": " ",
              "start_text": "0 widgets", "end_text": "10 widgets"}
    policy.update(updates)
    return policy


def count_action(policy=None):
    action = deepcopy(isolate_documents("text")[1]["actions"][2]["action"])
    action.update(verb="count", expected_state="visible", post_state="visible",
                  count_policy=policy or count_policy())
    return action


def test_complete_count_policy_binds_one_visible_text_and_round_trips():
    raw = count_action()
    parsed = TargetAction.model_validate(raw)
    assert parsed.count_policy.text_object_id == parsed.target_ids[0]
    assert parsed.count_policy.step_count == 10
    assert TargetAction.model_validate(parsed.model_dump(mode="json")) == parsed


def test_bare_legacy_count_load_dump_shape_remains_unchanged():
    raw = count_action()
    raw.pop("count_policy")
    parsed = TargetAction.model_validate(raw)
    assert "count_policy" not in parsed.model_dump(mode="json")
    assert parsed.verb == "count"


@pytest.mark.parametrize("bare", [False, True])
def test_new_semantic_write_requires_explicit_count_and_text_family(bare):
    layout, timeline = isolate_documents()
    timeline["actions"][2]["action"] = count_action()
    if bare:
        timeline["actions"][2]["action"].pop("count_policy")
    plan = semantic_plan(layout, timeline)
    owned_ids = {obj["object_id"] for obj in layout["objects"]}
    for beat in plan["beats"]:
        beat["object_ids"] = [key for key in beat["object_ids"] if key in owned_ids]
        beat["action_ids"] = [action["action_id"] for action in plan["actions"]
                              if action["coverage_id"] in beat["coverage_ids"]]
    with pytest.raises(ValueError, match="count.*(explicit policy|text)"):
        validate_plan_evidence_completeness(plan)


@pytest.mark.parametrize("change", [
    {"start_value": "NaN"}, {"end_value": "Infinity"}, {"start_value": "1e3"},
    {"start_value": "01"}, {"start_value": "+1"}, {"start_value": "1000000000000000001"},
    {"decimal_places": -1}, {"decimal_places": 7}, {"rounding": "bankers"},
    {"step_count": 0}, {"step_count": 4097}, {"grouping": "locale"},
    {"unit_placement": "none"}, {"unit": "line\nbreak"}, {"separator": "\t"},
    {"start_text": "invented"}, {"end_text": "invented"},
])
def test_count_policy_rejects_invalid_numeric_and_ignored_display_fields(change):
    with pytest.raises(ValidationError) as rejected:
        TargetAction.model_validate(count_action(count_policy(**change)))
    assert all(error["type"] != "extra_forbidden" for error in rejected.value.errors())


@pytest.mark.parametrize("change", [
    {"target_ids": ["object-label"]}, {"target_ids": ["object-evidence", "object-label"]},
    {"expected_state": "hidden"}, {"post_state": "counted"}, {"verb": "isolate"},
    {"annotation": "Invent labels"},
    {"easing": "step"},
])
def test_count_policy_has_exact_target_verb_and_state_contract(change):
    raw = count_action()
    raw.update(change)
    with pytest.raises(ValidationError) as rejected:
        TargetAction.model_validate(raw)
    assert all(error["type"] != "extra_forbidden" for error in rejected.value.errors())


@pytest.mark.parametrize("start,end,expected", [
    ("0", "4", ("0", "1", "2", "3", "4")),
    ("4", "0", ("4", "3", "2", "1", "0")),
    ("-2", "2", ("-2", "-1", "0", "1", "2")),
    ("-4", "-8", ("-4", "-5", "-6", "-7", "-8")),
])
def test_every_declared_decimal_step_is_deterministic(start, end, expected):
    from atme.render.v2_count import count_text

    policy = TargetAction.model_validate(count_action(count_policy(
        start_value=start, end_value=end, step_count=4, unit="", unit_placement="none", separator="",
        start_text=expected[0], end_text=expected[-1]))).count_policy
    assert tuple(count_text(policy, at / 4) for at in range(5)) == expected


@pytest.mark.parametrize("rounding,expected", [
    ("half_even", "2"), ("half_up", "3"), ("half_down", "2"),
    ("floor", "2"), ("ceiling", "3"), ("truncate", "2"),
])
def test_named_rounding_is_explicit_and_ignores_global_decimal_context(rounding, expected):
    from atme.render.v2_count import count_text

    policy = TargetAction.model_validate(count_action(count_policy(
        start_value="2", end_value="3", step_count=2, rounding=rounding,
        unit="", unit_placement="none", separator="", start_text="2", end_text="3"))).count_policy
    previous = getcontext().copy()
    try:
        getcontext().prec = 2
        assert count_text(policy, .5) == expected
    finally:
        getcontext().prec = previous.prec


def test_grouping_before_unit_unicode_and_xml_are_not_locale_or_implicit_markup():
    from atme.render.v2_count import count_text
    from atme.render.v2_svg import _xml_escape

    policy = TargetAction.model_validate(count_action(count_policy(
        start_value="1000", end_value="2000", grouping="thousands", unit="€<&>", unit_placement="before",
        start_text="€<&> 1,000", end_text="€<&> 2,000"))).count_policy
    assert count_text(policy, .5) == "€<&> 1,500"
    assert _xml_escape(count_text(policy, .5)) == "€&lt;&amp;&gt; 1,500"
