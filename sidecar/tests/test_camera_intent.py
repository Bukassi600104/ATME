"""Research R06-R07: intentional cuts and movements, not automatic reframing."""
import pytest

from atme.render.camera import validate_camera_intent, viewbox_at


def focus(x=0):
    return {"x": x, "y": 0, "width": 300, "height": 200}


def plan():
    return [
        {"cue_ms": 0, "action": "hold", "focus": focus()},
        {"cue_ms": 1000, "action": "pan", "transition_ms": 1000,
         "easing": "linear", "focus": focus(300)},
        {"cue_ms": 3000, "action": "cut", "focus": focus()},
    ]


def view(at):
    return viewbox_at(plan(), 600, 400, at, 600, 400)


def test_pan_begins_at_declared_onset_and_settles_at_end():
    assert view(900)["x"] == 0
    assert view(1000)["x"] == 0
    assert view(1500)["x"] == pytest.approx(117)
    assert view(2000)["x"] == 234
    assert view(2900)["x"] == 234


def test_cut_does_not_move_camera_before_boundary():
    assert view(2999)["x"] == 234
    assert view(3000)["x"] == 0


def test_declared_hold_does_not_anticipate_next_cue():
    cues = [{"cue_ms": 0, "action": "hold", "focus": focus()},
            {"cue_ms": 3000, "action": "cut", "focus": focus(300)}]
    assert viewbox_at(cues, 600, 400, 2900, 600, 400)["x"] == 0


def test_camera_composition_adds_breathing_room_without_exceeding_canvas():
    framed = viewbox_at([{"cue_ms": 0, "action": "hold", "focus": focus(150)}], 600, 400, 0, 600, 400)
    assert framed["w"] == pytest.approx(366)
    assert framed["h"] == pytest.approx(244)


@pytest.mark.parametrize("fault", ["overlap", "mixed", "duration", "first_move"])
def test_invalid_intent_fails_before_render(fault):
    cues = plan()
    if fault == "overlap":
        cues[2]["cue_ms"] = 1500
    elif fault == "mixed":
        del cues[2]["action"]
    elif fault == "duration":
        cues[1]["transition_ms"] = 0
    else:
        cues[0]["action"] = "pan"
        cues[0]["transition_ms"] = 500
    with pytest.raises(ValueError):
        validate_camera_intent(cues)
