"""Replay-aware lifecycle/paint proofs do not replace production Group gates."""

from copy import deepcopy

import pytest
from test_v2_morph_action import morph_documents
from test_v2_replace_action import documents
from v2_fixtures import digest

from atme.render.v2_state import V2FrameError, evaluate_frame


def intervening_documents(verb, state="hidden", visible=False, opacity=1):
    layout, timeline = morph_documents() if verb == "morph" else documents()
    leaf = deepcopy(layout["objects"][0])
    leaf.update(object_id="object-shared", initial_state=state, visible=visible, opacity=opacity)
    layout["objects"].append(leaf)
    layout["boards"][0]["object_ids"].append(leaf["object_id"])
    timeline["initial_object_states"].append({"object_id": leaf["object_id"], "state": state,
                                              "visible": visible, "state_version": 1})
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline


@pytest.mark.parametrize("verb", ["replace", "morph"])
@pytest.mark.parametrize("state,visible,opacity", [("hidden", False, 1), ("visible", True, 0)])
def test_nonterminal_intervening_leaf_cannot_be_ignored_as_a_paint_slot(verb, state, visible, opacity):
    layout, timeline = intervening_documents(verb, state, visible, opacity)
    with pytest.raises(V2FrameError, match="consecutive nonterminal paint slots"):
        evaluate_frame(layout, timeline, 100)


@pytest.mark.parametrize("verb", ["replace", "morph"])
def test_terminal_removed_leaf_remains_in_inventory_but_not_the_paint_slot_view(verb):
    layout, timeline = intervening_documents(verb, "removed", False)
    original = deepcopy((layout, timeline))
    for at in (6000, 6500, 7000, 5999, 6500):
        frame = evaluate_frame(layout, timeline, at)
        assert frame.object("object-shared").state == "removed"
        assert "object-shared" in {node.object_id for node in frame.hierarchy.nodes}
    assert (layout, timeline) == original


@pytest.mark.parametrize("verb", ["replace", "morph"])
def test_removed_but_visible_intervening_leaf_is_not_silently_filtered(verb):
    layout, timeline = intervening_documents(verb, "removed", True)
    with pytest.raises(V2FrameError, match="removed leaf.*visible"):
        evaluate_frame(layout, timeline, 100)
