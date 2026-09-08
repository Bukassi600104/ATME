from copy import deepcopy

import pytest

from atme.agents.spatial import repair_collisions, bbox, overlaps


def boxes():
    return [dict(id=f"el-{i}", type="rectangle", scene_id=i + 1,
                 board_id=board, appear_at_ms=i * 2000,
                 x=100, y=100, width=200, height=100)
            for i, board in enumerate(["explanation", "evidence"])]


def test_different_boards_can_reuse_the_same_canvas_position():
    elements = boxes()
    before = deepcopy(elements)
    assert repair_collisions(elements) == 0
    assert elements == before


@pytest.mark.parametrize("legacy", [False, True])
def test_same_board_still_repairs_collisions(legacy):
    elements = boxes()
    for el in elements:
        if legacy:
            el.pop("board_id")
        else:
            el["board_id"] = "explanation"
    assert repair_collisions(elements) > 0
    assert not overlaps(bbox(elements[0]), bbox(elements[1]))


def test_other_board_does_not_change_same_board_repair():
    elements = boxes()
    elements[1]["board_id"] = "explanation"
    expected = deepcopy(elements)
    repair_collisions(expected)
    extra = dict(boxes()[1], id="el-other")
    elements.insert(1, extra)
    repair_collisions(elements)
    assert [el for el in elements if el["id"] != "el-other"] == expected
    assert extra["y"] == 100
