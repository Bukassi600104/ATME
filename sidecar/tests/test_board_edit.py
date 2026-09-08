from copy import deepcopy
import json

import pytest

from atme.board_edit import apply_board_edit
from test_board_continuity import board_doc
from test_evidence_replace_route import setup_job


def assignments(doc):
    return {e["id"]: {"board_id": e["board_id"], "appear_at_ms": e["appear_at_ms"]} for e in doc["elements"]}


def test_legacy_conversion_preserves_geometry_and_source():
    doc = board_doc()
    timeline = doc.pop("board_timeline")
    mapping = assignments(doc)
    for e in doc["elements"]:
        e.pop("board_id")
    before = deepcopy(doc)
    result = apply_board_edit(doc, timeline, mapping, 6000)
    assert result["board_timeline"] == timeline
    assert result["elements"][0]["x"] == doc["elements"][0]["x"]
    assert doc == before


@pytest.mark.parametrize("problem", ["missing", "overlap", "duration", "inactive", "unknown"])
def test_invalid_edit_rejected_without_mutation(problem):
    doc = board_doc()
    before = deepcopy(doc)
    timeline = deepcopy(doc["board_timeline"])
    mapping = assignments(doc)
    if problem == "missing":
        mapping.pop("el-queue")
    elif problem == "overlap":
        timeline["activations"][1]["start_ms"] = 1000
    elif problem == "duration":
        timeline["activations"][-1]["end_ms"] = 7000
    elif problem == "inactive":
        mapping["el-evidence"]["appear_at_ms"] = 4500
    else:
        mapping["el-queue"]["board_id"] = "unknown"
    with pytest.raises(ValueError):
        apply_board_edit(doc, timeline, mapping, 6000)
    assert doc == before


def test_board_route_save_and_stale_revision(tmp_path):
    client, orch, headers, job, directory, _ = setup_job(tmp_path)
    (directory / "audio_state.json").write_text(json.dumps({"duration_ms": 6000}))
    url = f"/jobs/{job}/boards"
    assert client.get(url).status_code == 401
    data = client.get(url, headers=headers).json()
    payload = {"revision": data["revision"], "timeline": data["timeline"],
               "assignments": assignments({"elements": data["elements"]})}
    result = client.put(url, json=payload, headers=headers)
    assert result.status_code == 200, result.text
    assert list(directory.glob("layout.before-boards-*.json"))
    assert "aligned" not in orch.store.resume_point(job)[1]
    # Change the file as another editor could; an old revision must not overwrite it.
    path = directory / "layout.json"
    path.write_text(path.read_text() + "\n")
    assert client.put(url, json=payload, headers=headers).status_code == 409


def test_phrase_link_add_preserve_and_remove():
    doc = board_doc()
    mapping = assignments(doc)
    trigger = {"phrase": "the queue", "occurrence": 2, "offset_ms": -50, "min_confidence": 0.8}
    mapping["el-queue"]["narration_trigger"] = trigger
    edited = apply_board_edit(doc, doc["board_timeline"], mapping, 6000)
    assert edited["elements"][0]["narration_trigger"] == trigger
    assert "narration_trigger" not in doc["elements"][0]
    preserved = apply_board_edit(edited, edited["board_timeline"], assignments(edited), 6000)
    assert preserved == edited  # Older clients omit the field and preserve links.
    mapping["el-queue"]["narration_trigger"] = None
    removed = apply_board_edit(edited, edited["board_timeline"], mapping, 6000)
    assert "narration_trigger" not in removed["elements"][0]


@pytest.mark.parametrize("trigger", [{"phrase": "queue", "occurrence": 0},
                                     {"phrase": "queue", "min_confidence": 2},
                                     {"phrase": ""}, {"phrase": "queue", "unknown": True}])
def test_invalid_phrase_link_is_nonmutating(trigger):
    doc = board_doc()
    original = deepcopy(doc)
    mapping = assignments(doc)
    mapping["el-queue"]["narration_trigger"] = trigger
    with pytest.raises(ValueError):
        apply_board_edit(doc, doc["board_timeline"], mapping, 6000)
    assert doc == original


def test_phrase_link_route_roundtrip(tmp_path):
    client, orch, headers, job, directory, _ = setup_job(tmp_path)
    (directory / "audio_state.json").write_text(json.dumps({"duration_ms": 6000}))
    url = f"/jobs/{job}/boards"
    data = client.get(url, headers=headers).json()
    mapping = assignments({"elements": data["elements"]})
    target = data["elements"][0]["id"]
    mapping[target]["narration_trigger"] = {"phrase": "queue", "offset_ms": 0}
    response = client.put(url, headers=headers, json={"revision": data["revision"],
        "timeline": data["timeline"], "assignments": mapping})
    assert response.status_code == 200
    saved = client.get(url, headers=headers).json()
    assert saved["elements"][0]["narration_trigger"] == mapping[target]["narration_trigger"]
    assert orch.store.get_job(job)["status"] == "paused"
    assert "aligned" not in orch.store.resume_point(job)[1]
