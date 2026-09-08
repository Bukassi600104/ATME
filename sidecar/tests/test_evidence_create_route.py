import json

import pytest

from test_evidence_replace_route import setup_job


def placement():
    return {"scene_id": 2, "board_id": "evidence", "appear_at_ms": 2100,
            "x": 50, "y": 50, "width": 200, "height": 100}


def test_new_slot_is_saved_inventoried_and_invalidates_render(tmp_path):
    client, orch, headers, job, directory, payload = setup_job(tmp_path)
    payload["placement"] = placement()
    url = f"/jobs/{job}/evidence/el-new"
    result = client.post(url, json=payload, headers=headers)
    assert result.status_code == 200, result.text
    doc = json.loads((directory / "layout.json").read_text())
    assert doc["elements"][-1]["id"] == "el-new"
    assert doc["elements"][-1]["appear_at_ms"] == 2100
    assert doc["elements"][-1]["enter_action"] == "reveal"
    assert "aligned" not in orch.store.resume_point(job)[1]
    inventory = client.get(f"/jobs/{job}/evidence", headers=headers).json()
    assert len(inventory["slots"]) == 2
    assert inventory["boards"] and inventory["activations"] and inventory["canvas"]
    assert client.post(url, json=payload, headers=headers).status_code == 409


@pytest.mark.parametrize("field,value", [
    ("x", 25), ("width", 1000), ("board_id", "missing"),
    ("appear_at_ms", 4100), ("scene_id", 999), ("scene_id", []),
])
def test_invalid_placement_does_not_mutate_layout(tmp_path, field, value):
    client, orch, headers, job, directory, payload = setup_job(tmp_path)
    payload["placement"] = placement()
    payload["placement"][field] = value
    before = (directory / "layout.json").read_bytes()
    result = client.post(f"/jobs/{job}/evidence/el-new", json=payload, headers=headers)
    assert result.status_code == 400
    assert (directory / "layout.json").read_bytes() == before
    assert "assembled" in orch.store.resume_point(job)[1]
