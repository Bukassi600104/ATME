"""Sound persistence binds declarations to owned audio bytes and measured duration."""
from copy import deepcopy
import wave

import pytest
from atme.project_service import (
    ProjectError,
    ProjectService,
    _resolved_compilation_fingerprint,
)
from atme.render.v2_sound_events import derive_sound_ledger
from atme.store.db import JobStore
from test_v2_resolved_project import stored_v2_basis
from test_v2_sound_events import no_media_execution
from v2_fixtures import common_action, digest

pytestmark = pytest.mark.usefixtures(no_media_execution.__name__)


def stored_sound(tmp_path, *, persist=True, change=None, basis=None):
    service, project, plan, layout, timeline = basis if basis is not None else stored_v2_basis(tmp_path)
    pid = project["project_id"]
    upload = tmp_path / "score.wav"
    with wave.open(str(upload), "wb") as stream:
        stream.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        stream.writeframes(b"\x00\x10" * 64000)
    attached = service.attach_asset_file(pid, upload, upload.name, project["revision"])
    project, owned = attached["project"], attached["asset"]
    asset_id = owned["asset_id"]
    owned = next(asset for asset in service.list_assets(pid) if asset["asset_id"] == asset_id)
    plan["assets"].append({
        "asset_id": asset_id, "revision": owned["revision"], "kind": "audio",
        "semantic_role": "Editorial score", "managed_ref": owned["resource_uri"],
        "checksum_sha256": owned["sha256"], "duration_ms": 4000,
        "provenance": {"category": "user_owned", "checksum_sha256": owned["sha256"],
                       "license_status": "owned", "fabrication_prohibited": False,
                       "originality_status": "original"},
        "allowed_transformations": [],
    })
    timeline["resolved_assets"].append({
        "asset_id": asset_id, "revision": owned["revision"], "kind": "audio",
        "managed_ref": owned["resource_uri"], "checksum_sha256": owned["sha256"],
        "duration_ms": 4000, "media_type": owned["media_type"],
        "byte_length": owned["bytes"], "allowed_transformations": [],
        "provenance_verified": True,
    })
    for verb, start, end, role in (("music_state", 0, 3000, "music"),
                                  ("purposeful_silence", 1000, 2000, "music"),
                                  ("sound_cue", 6000, 6900, "effect")):
        silent = verb == "purposeful_silence"
        policy = {"version": "1.0.0", "bus_id": "score" if role == "music" else "cue",
                  "bus_role": role, "narration_priority": "preserve_narration",
                  "fade_in": {"duration_ms": 0 if silent else 100, "easing": "linear"},
                  "fade_out": {"duration_ms": 0 if silent else 100, "easing": "linear"}}
        if not silent:
            policy["playback"] = {"source_in_ms": 0, "source_out_ms": 4000,
                                  "repeat_count": 1, "offset_ms": 0}
        trigger = {"kind": "absolute", "at_ms": start}
        action = {**common_action("action-1", "instruction-1"), "action_id": verb,
                  "verb": verb, "asset_id": None if silent else asset_id,
                  "trigger": trigger, "easing": "linear", "gain_db": 0 if silent else -12,
                  "state": "silent" if silent else "playing",
                  "expected_state": "clear" if silent else "stopped",
                  "post_state": "clear" if silent else "stopped", "sound_policy": policy}
        plan["actions"].append(action)
        plan["beats"][0]["action_ids"].append(action["action_id"])
        plan["coverage"][0]["action_ids"].append(action["action_id"])
        timeline["actions"].append({"action": deepcopy(action), "start_ms": start, "end_ms": end,
            "resolved_trigger": {"source": trigger, "alignment_anchor_ms": start,
                "matched_text": None, "matched_occurrence": None, "resolved_at_ms": start,
                "confidence": 1, "exact": True}})
    timeline["coverage"] = deepcopy(plan["coverage"])
    timeline["actions"].sort(key=lambda item: item["start_ms"])
    if change:
        change(plan, timeline)
    plan["project_revision"] = project["revision"]
    try:
        project = service.write(pid, "storyboard", plan, project["revision"])
    except ProjectError as exc:
        raise AssertionError(exc.detail()) from exc
    layout.update(project_revision=project["revision"], plan_revision=project["artifacts"]["storyboard"],
                  plan_sha256=digest(plan))
    project = service.write(pid, "layout", layout, project["revision"])
    timeline.update(project_revision=project["revision"], plan_revision=project["artifacts"]["storyboard"],
                    layout_revision=project["artifacts"]["layout"], plan_sha256=digest(plan),
                    layout_sha256=digest(layout))
    timeline["compilation_fingerprint"] = _resolved_compilation_fingerprint(timeline)
    if persist:
        try:
            project = service.write(pid, "resolved_timeline", timeline, project["revision"])
        except ProjectError as exc:
            raise AssertionError(exc.detail()) from exc
    return service, project, plan, layout, timeline


def history(service, pid):
    return tuple(tuple(row) for row in service.store.conn.execute(
        "SELECT kind,revision,document FROM project_artifact_versions WHERE job_id=? ORDER BY kind,revision",
        (pid,)))


def test_owned_sound_persists_reopens_and_duplicates_with_rebound_pins(tmp_path):
    service, project, plan, layout, timeline = stored_sound(tmp_path)
    pid, db_path = project["project_id"], service.store.db_path
    original = history(service, pid)
    ledger = derive_sound_ledger(timeline, plan)
    service.store.close()
    service = ProjectService(JobStore(db_path))
    try:
        assert service.artifact(pid, "resolved_timeline")["document"] == timeline
        assert derive_sound_ledger(service.artifact(pid, "resolved_timeline")["document"], plan) == ledger
        duplicate = service.duplicate(pid)
        copy_id = duplicate["project_id"]
        copied_plan = service.artifact(copy_id, "storyboard")["document"]
        copied = service.artifact(copy_id, "resolved_timeline")["document"]
        sound = next(asset for asset in copied["resolved_assets"] if asset["kind"] == "audio")
        assert sound["managed_ref"] == f"atme://projects/{copy_id}/assets/{sound['asset_id']}"
        assert copied["initial_object_states"] == timeline["initial_object_states"]
        assert service.artifact(copy_id, "layout")["document"]["objects"] == layout["objects"]
        assert copied_plan["actions"] == plan["actions"]
        assert derive_sound_ledger(copied, copied_plan)
        assert history(service, pid) == original
    finally:
        service.store.close()


@pytest.mark.parametrize("field,value", [
    ("revision", 99), ("managed_ref", "atme://projects/999/assets/foreign"),
    ("checksum_sha256", "f" * 64), ("byte_length", 1),
    ("media_type", "audio/mpeg"), ("media_type", None), ("duration_ms", 3999),
])
def test_changed_sound_pins_reject_atomically(tmp_path, field, value):
    service, project, _, _, timeline = stored_sound(tmp_path, persist=False)
    try:
        before = history(service, project["project_id"])
        timeline["resolved_assets"][-1][field] = value
        timeline["compilation_fingerprint"] = _resolved_compilation_fingerprint(timeline)
        with pytest.raises(ProjectError):
            service.write(project["project_id"], "resolved_timeline", timeline, project["revision"])
        assert history(service, project["project_id"]) == before
        assert service.open(project["project_id"])["revision"] == project["revision"]
    finally:
        service.store.close()


def test_changed_owned_bytes_reject_write_and_duplicate_atomically(tmp_path):
    service, project, _, _, timeline = stored_sound(tmp_path)
    try:
        pid = project["project_id"]
        path, _ = service.asset(pid, timeline["resolved_assets"][-1]["asset_id"])
        path.write_bytes(b"changed after ingestion")
        before = history(service, pid)
        jobs = service.store.conn.execute("SELECT count(*) FROM jobs").fetchone()[0]
        timeline["project_revision"] = project["revision"]
        timeline["compilation_fingerprint"] = _resolved_compilation_fingerprint(timeline)
        with pytest.raises(ProjectError, match="integrity"):
            service.write(pid, "resolved_timeline", timeline, project["revision"])
        with pytest.raises(ProjectError, match="integrity"):
            service.duplicate(pid)
        assert history(service, pid) == before
        assert service.store.conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == jobs
    finally:
        service.store.close()


@pytest.mark.parametrize("field,value", [
    ("revision", 99), ("managed_ref", "atme://projects/999/assets/foreign"),
    ("checksum_sha256", "f" * 64), ("asset_id", "f" * 32), ("kind", "sound_effect"),
])
def test_matching_plan_and_resolved_cannot_forge_owned_pins(tmp_path, field, value):
    def change(plan, timeline):
        original_id = plan["assets"][-1]["asset_id"]
        plan["assets"][-1][field] = value
        timeline["resolved_assets"][-1][field] = value
        if field == "asset_id":
            for action in plan["actions"]:
                if action.get("asset_id") == original_id:
                    action["asset_id"] = value
            for item in timeline["actions"]:
                if item["action"].get("asset_id") == original_id:
                    item["action"]["asset_id"] = value
    service, project, _, _, timeline = stored_sound(tmp_path, persist=False, change=change)
    try:
        before = history(service, project["project_id"])
        with pytest.raises(ProjectError, match="[Ss]ound"):
            service.write(project["project_id"], "resolved_timeline", timeline, project["revision"])
        assert history(service, project["project_id"]) == before
    finally:
        service.store.close()
