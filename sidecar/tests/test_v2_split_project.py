"""New Split writes must reject incomplete contracts without publishing revisions."""

from copy import deepcopy
from pathlib import Path

import pytest
from test_v2_media_decode import encoded_vfr
from test_v2_media_project import original_video
from test_visual_contracts_v2 import _store_v2_plan
from v2_split_fixtures import split_documents

from atme.project_service import ProjectError

__all__ = ["encoded_vfr", "original_video"]


def stored_split_basis(tmp_path, *, portrait=False, mode="script+audio", family="geometry", video=None,
                       with_index=False, with_context=False, history_kind=None):
    """Normal service inputs and writes; family fixtures supply authored paint packets."""
    from test_external_inputs import external_payload
    from test_project_runner import wav_bytes
    from test_v2_split_families import geometry_split_family
    from v2_fixtures import digest, visual_plan_v2

    from atme.project_service import ProjectService, _resolved_compilation_fingerprint
    from atme.store.db import JobStore

    profile = "SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9"
    if history_kind is not None:
        from test_v2_split_return import retained_history

        service = ProjectService(JobStore(tmp_path / "split.db"))
        project = service.create("Stored chronological Split return", profile, mode)
        typed_layout, typed_timeline = retained_history(history_kind, portrait)
        layout, timeline = typed_layout.model_dump(mode="json"), typed_timeline.model_dump(mode="json")
        for item in timeline["actions"]:
            if item["action"]["verb"] == "split":
                item["end_ms"] = item["start_ms"] + 10
    elif family == "evidence":
        from test_v2_split_evidence_family import short_evidence_family
        service, typed_layout, _, typed_timeline, *_ = short_evidence_family(tmp_path, portrait)
        project = service.open(typed_layout.project_id)
        if project["profile"] != profile:
            project = service.set_profile(project["project_id"], profile, project["revision"])
        layout, timeline = typed_layout.model_dump(mode="json"), typed_timeline.model_dump(mode="json")
    elif family == "media":
        import json

        from test_v2_media_project import owned_media
        from test_v2_split_identity import sample_for_layout
        from test_v2_split_media_family import media_family

        from atme.render.v2_split import _observed_split_placements
        from atme.render.v2_split_identity import SplitContentReceipt
        from atme.store.contracts_v2 import (
            ExecutableLayoutV2,
            SplitPolicy,
            _split_expected_completion,
        )

        service, project, _, owned_clock, *_ = owned_media(
            tmp_path, video, supporting=True, profile=profile, input_kind=mode)
        typed_layout, _, _, typed_timeline, *_ = media_family(portrait, raw=video, kind="video")
        layout, timeline = typed_layout.model_dump(mode="json"), typed_timeline.model_dump(mode="json")
        asset = deepcopy(owned_clock["resolved_assets"][0])
        timeline["resolved_assets"] = [asset]
        contents = {}
        for obj in layout["objects"]:
            obj.update(beat_id="beat-001", coverage_ids=[timeline["actions"][0]["action"]["coverage_id"]])
            obj["asset_id"] = asset["asset_id"]
            obj["media_playback"]["placement"]["source_revision"] = asset["revision"]
            payload = {key: obj[key] for key in ("object_type", "geometry", "style", "anchors", "asset_id", "variant", "media_playback")}
            payload["asset_bytes_sha256"] = asset["checksum_sha256"]
            contents[obj["object_id"]] = SplitContentReceipt(obj["object_id"],
                json.dumps(payload, sort_keys=True, separators=(",", ":")), digest(payload))
        typed_layout = ExecutableLayoutV2.model_validate(layout)
        policy = timeline["actions"][0]["action"]["split_policy"]
        basis = policy["source_basis"]
        basis["asset_pins"] = [{"asset_id": asset["asset_id"], "revision": asset["revision"],
            "resource_uri": asset["managed_ref"], "checksum_sha256": asset["checksum_sha256"]}]
        basis["placements"] = [row.model_dump(mode="json") for row in _observed_split_placements(
            sample_for_layout(typed_layout), {obj.object_id: obj for obj in typed_layout.objects}, set(contents), contents)]
        for row in policy["correspondences"]:
            row.update(source_content_sha256=contents["source"].content_sha256,
                       result_content_sha256=contents[row["result_object_id"]].content_sha256)
        policy["source_basis_sha256"] = digest(basis)
        receipt = _split_expected_completion(SplitPolicy.model_validate(policy))
        receipt["completion_sha256"] = digest(receipt)
        timeline["actions"][0]["split_completion_receipt"] = receipt
    else:
        service = ProjectService(JobStore(tmp_path / "split.db"))
        project = service.create("Stored authored Split", profile, mode)
        typed_layout, _, _, typed_timeline, *_ = geometry_split_family(portrait, "rectangle", "reveal")
        layout, timeline = typed_layout.model_dump(mode="json"), typed_timeline.model_dump(mode="json")
    if with_context:
        extra = deepcopy(next(obj for obj in layout["objects"] if obj["object_id"] == "source"))
        extra.update(object_id="parent-context", z_index=3)
        layout["objects"].append(extra)
        layout["boards"][0]["object_ids"].append(extra["object_id"])
        timeline["initial_object_states"].append({"object_id": extra["object_id"], "state": "visible",
                                                "state_version": 1, "visible": True})
    pid = project["project_id"]
    if mode.startswith("script") or family == "evidence":
        project = service.write(pid, "script", external_payload()["script"], project["revision"])
        project = service.approve_script(pid, project["artifacts"]["script"], project["revision"], True)
    elif with_index:
        project = service.write(pid, "script", external_payload()["script"], project["revision"])
    if mode.endswith("video") or mode == "video-only":
        staged = tmp_path / "narration.mp4"
        staged.write_bytes(video)
        project = service.attach_video_file(pid, staged, staged.name, project["revision"])["project"]
    else:
        project = service.attach_wav(pid, wav_bytes(), project["revision"])["project"]
    source = service.narrative_source(pid)
    placed = service.source_timeline.command(pid, "insert",
        {"media_id": source["timing_authority"]["media"]["media_id"], "at_ms": 0},
        project["revision"], service.source_timeline.get(pid)["timeline_revision"])
    project, cleaned = placed["project"], placed["timeline"]
    timeline["duration_ms"] = cleaned["document"]["duration_ms"]
    layout["activations"][-1]["end_ms"] = timeline["duration_ms"]
    plan, _, _ = split_documents(profile)
    semantic_fields = set(plan["objects"][0]) | ({"media_playback"} if family == "media" else set())
    plan.update(objects=[{key: deepcopy(obj[key]) for key in semantic_fields} for obj in layout["objects"]],
                boards=deepcopy(layout["boards"]), actions=[deepcopy(item["action"]) for item in timeline["actions"]])
    plan["beats"][0]["object_ids"] = [obj["object_id"] for obj in layout["objects"]]
    if history_kind is not None:
        for semantic, obj in zip(plan["objects"], layout["objects"], strict=True):
            for field in ("child_ids", "structured_list"):
                if obj.get(field):
                    semantic[field] = deepcopy(obj[field])
        beat = plan["beats"][0]
        beat["action_ids"] = [item["action"]["action_id"] for item in timeline["actions"]]
        returned = next(item["action"] for item in timeline["actions"] if item["action"]["verb"] == "return_board")
        beat["continuity"].update(return_from_board_id=returned["source_board_id"],
            developed_return_state=returned["destination_state"], expected_state_versions=returned["expected_object_state_versions"])
        plan["coverage"] = deepcopy(timeline["coverage"])
    if family in {"evidence", "media"}:
        declared = deepcopy(visual_plan_v2()["assets"][0])
        asset = timeline["resolved_assets"][0]
        declared.update({key: deepcopy(asset[key]) for key in (
            "asset_id", "revision", "managed_ref", "checksum_sha256", "kind", "width", "height",
            "allowed_transformations")})
        declared["fallback_id"] = plan["fallbacks"][0]["fallback_id"]
        if family == "evidence":
            declared["provenance"] = deepcopy(layout["evidence_treatments"][0]["asset_provenance"])
        else:
            declared.update(duration_ms=asset["duration_ms"], media_stream=deepcopy(asset["media_stream"]),
                provenance={"category": "user_owned", "source_uri": None,
                    "checksum_sha256": asset["checksum_sha256"], "license_status": "owned",
                    "fabrication_prohibited": False, "originality_status": "original"})
        plan["assets"] = [declared]
    media = source["timing_authority"]["media"]
    authority = plan["narrative_authority"]
    authority.update(mode="recording_only" if source["mode"] == "recording_authority" else "approved_script_plus_recording",
        authority_id=media["media_id"] if source["mode"] == "recording_authority" else
            f"script-revision-{source['semantic_structure']['revision']}",
        timing_media_id=media["media_id"], timing_media_sha256=media["sha256"],
        cleaned_timeline_revision=cleaned["timeline_revision"], cleaned_timeline_fingerprint=digest(cleaned["document"]))
    plan.update(project_id=pid, project_revision=project["revision"])
    try:
        project = service.write(pid, "storyboard", plan, project["revision"])
    except ProjectError as exc:
        raise AssertionError(exc.detail()) from exc
    layout.update(project_id=pid, project_revision=project["revision"],
                  plan_revision=project["artifacts"]["storyboard"], plan_sha256=digest(plan))
    project = service.write(pid, "layout", layout, project["revision"])
    timeline.update(project_id=pid, project_revision=project["revision"],
        plan_revision=project["artifacts"]["storyboard"], plan_sha256=digest(plan),
        layout_revision=project["artifacts"]["layout"], layout_sha256=digest(layout),
        cleaned_timeline_revision=cleaned["timeline_revision"], cleaned_timeline_fingerprint=digest(cleaned["document"]))
    timeline["compilation_fingerprint"] = _resolved_compilation_fingerprint(timeline)
    return service, project, plan, layout, timeline


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("mode", ["script+audio", "audio-only", "video-only"])
def test_normal_split_storage_and_repeated_duplicate_preserve_source(tmp_path, portrait, mode, original_video):
    from v2_fixtures import digest

    from atme.project_service import _resolved_compilation_fingerprint

    service, project, plan, layout, timeline = stored_split_basis(
        tmp_path, portrait=portrait, mode=mode, video=original_video)
    try:
        pid = project["project_id"]
        before = artifact_rows(service, pid)
        media = service.authoritative_media(pid)[0]
        project = service.write(pid, "resolved_timeline", timeline, project["revision"])
        assert service.artifact(pid, "resolved_timeline")["document"] == timeline
        original = artifact_rows(service, pid)
        assert len(original) == len(before) + 1
        prior = project
        for _ in range(2):
            copy = service.duplicate(prior["project_id"])
            copied_plan = service.artifact(copy["project_id"], "storyboard")["document"]
            copied_layout = service.artifact(copy["project_id"], "layout")["document"]
            copied_clock = service.artifact(copy["project_id"], "resolved_timeline")["document"]
            assert copied_plan["actions"] == plan["actions"]
            assert copied_layout["objects"] == layout["objects"]
            assert copied_clock["plan_sha256"] == digest(copied_plan)
            assert copied_clock["layout_sha256"] == digest(copied_layout)
            assert copied_clock["compilation_fingerprint"] == _resolved_compilation_fingerprint(copied_clock)
            assert service.authoritative_media(copy["project_id"])[0] == media
            assert artifact_rows(service, pid) == original
            prior = copy
        if mode.endswith("only"):
            assert "script" not in project["artifacts"]
            assert not service.store.conn.execute(
                "SELECT 1 FROM project_artifact_dependencies WHERE job_id=?", (pid,)).fetchall()
    finally:
        service.store.close()


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("mode", ["script+audio", "audio-only"])
@pytest.mark.parametrize("kind", ["geometry", "count-group", "group-count", "morph", "descendants"])
def test_normal_stored_split_return_history_and_duplicate_keep_exact_retained_state(tmp_path, portrait, mode, kind):
    from atme.render.v2_hierarchy import HierarchySnapshot
    from atme.render.v2_split_paint import verify_split_paint_inputs
    from atme.render.v2_state import _validate_consumer_history, _validate_pair_static
    from atme.store.contracts_v2 import ExecutableLayoutV2, ResolvedVisualTimelineV2

    service, project, _, layout, timeline = stored_split_basis(
        tmp_path, portrait=portrait, mode=mode, history_kind=kind)
    try:
        pid = project["project_id"]
        project = service.write(pid, "resolved_timeline", timeline, project["revision"])
        originals = artifact_rows(service, pid)
        media = service.authoritative_media(pid)[0]
        copy = service.duplicate(pid)
        expected = None
        for owner in (project, copy):
            drawing = service.artifact(owner["project_id"], "layout")["document"]
            clock = service.artifact(owner["project_id"], "resolved_timeline")["document"]
            assert drawing["objects"] == layout["objects"]
            assert clock["actions"] == timeline["actions"]
            typed_layout = ExecutableLayoutV2.model_validate(drawing)
            typed_clock = ResolvedVisualTimelineV2.model_validate(clock)
            paired = _validate_pair_static(typed_layout, typed_clock, clock["layout_sha256"],
                HierarchySnapshot.from_objects({obj.object_id: obj for obj in typed_layout.objects}))
            replay, _ = _validate_consumer_history(paired, split_inputs=verify_split_paint_inputs(typed_layout, {}))
            departed, returned = replay.at(1999), replay.at(3000)
            assert departed.objects == returned.objects
            assert departed.hierarchy == returned.hierarchy
            assert departed.state_versions == returned.state_versions
            assert returned.object("source").state == "removed"
            assert returned.object("part-1").state == returned.object("part-2").state == "visible"
            versions = dict(returned.state_versions)
            if kind in {"count-group", "group-count"}:
                assert returned.object("source").display_text == "10 widgets"
                assert returned.object("source").count_value == (10, 1)
                assert returned.object("source").transform.position.x == 100
                assert next(node for node in returned.hierarchy.nodes if node.object_id == "source").parent_id is None
                assert next(obj for obj in drawing["objects"] if obj["object_id"] == "source")["text"] == "0 widgets"
                assert versions == {"source": 4, "shell": 2, "part-1": 3, "part-2": 3}
            elif kind == "geometry":
                assert versions == {"source": 2, "part-1": 2, "part-2": 2}
            elif kind == "morph":
                assert versions == {"origin": 2, "source": 3, "part-1": 2, "part-2": 2}
                assert returned.object("origin").state == "removed"
                assert returned.object("source").morph_geometry is None
            else:
                for obj in typed_layout.objects:
                    key = obj.object_id
                    assert versions[key] == (2 if key in {"source", "part-1", "part-2"} else 1)
                    if key not in {"source", "part-1", "part-2"}:
                        assert returned.object(key).state == obj.initial_state
                        assert returned.object(key) == next(frame for frame in paired.frames if frame.object_id == key)
            if expected is None:
                expected = returned
            else:
                assert returned == expected
            assert service.authoritative_media(owner["project_id"])[0] == media
        assert artifact_rows(service, pid) == originals
    finally:
        service.store.close()


@pytest.fixture(scope="module")
def stored_evidence_split(tmp_path_factory):
    directory = tmp_path_factory.mktemp("stored-split-evidence")
    service, project, plan, layout, timeline = stored_split_basis(directory, family="evidence")
    project = service.write(project["project_id"], "resolved_timeline", timeline, project["revision"])
    yield service, project, plan, layout, timeline
    service.store.close()


@pytest.mark.parametrize("mutation", ["basis_only", "activation_only", "source", "foreign", "other_copy", "mixed"])
def test_normal_split_evidence_requires_exact_current_owner_in_every_consumer(stored_evidence_split, mutation):
    from atme.store.contracts_v2 import _split_packet_digest

    service, source, *_ = stored_evidence_split
    copy = service.duplicate(source["project_id"])
    pid = copy["project_id"]
    plan = service.artifact(pid, "storyboard")["document"]
    policy = plan["actions"][0]["split_policy"]
    pin = policy["source_basis"]["asset_pins"][0]
    other_id = (service.duplicate(source["project_id"])["project_id"] if mutation == "other_copy" else
                999 if mutation == "foreign" else source["project_id"])
    wrong_uri = f"atme://projects/{other_id}/assets/{pin['asset_id']}"
    if mutation != "activation_only" and mutation != "mixed":
        pin["resource_uri"] = wrong_uri
    if mutation != "basis_only":
        for index, result in enumerate(policy["results"]):
            if mutation == "mixed" and index:
                continue
            result["evidence_activation"]["asset_pin"]["resource_uri"] = wrong_uri
    policy["source_basis_sha256"] = _split_packet_digest(policy["source_basis"])
    plan["project_revision"] = copy["revision"]
    before = artifact_rows(service, pid)
    with pytest.raises(ProjectError) as failure:
        service.write(pid, "storyboard", plan, copy["revision"])
    assert failure.value.code == "invalid_artifact"
    assert "split evidence" in str(failure.value.errors).lower()
    assert artifact_rows(service, pid) == before
    assert service.open(pid)["revision"] == copy["revision"]


@pytest.mark.parametrize("mutation", ["revision", "checksum", "missing_owner", "provenance", "permissions", "dimensions"])
def test_normal_split_evidence_authenticates_actual_destination_row_before_history(stored_evidence_split, mutation):
    import json

    from atme.project_service import _resolved_compilation_fingerprint

    service, source, *_ = stored_evidence_split
    copy = service.duplicate(source["project_id"])
    pid = copy["project_id"]
    timeline = service.artifact(pid, "resolved_timeline")["document"]
    asset_id = timeline["resolved_assets"][0]["asset_id"]
    row = service.store.conn.execute("SELECT * FROM project_assets WHERE job_id=? AND asset_id=?", (pid, asset_id)).fetchone()
    metadata = json.loads(row["metadata"])
    revision = row["revision"]
    if mutation == "missing_owner":
        service.store.conn.execute("DELETE FROM project_assets WHERE job_id=? AND asset_id=?", (pid, asset_id))
    else:
        if mutation == "revision":
            revision += 1
        elif mutation == "checksum":
            metadata["sha256"] = "0" * 64
        elif mutation == "provenance":
            metadata["provenance"]["source_uri"] = "https://example.com/forged-source"
        elif mutation == "permissions":
            metadata["allowed_transformations"].reverse()
        else:
            metadata["width"] += 1
        service.store.conn.execute("UPDATE project_assets SET revision=?,metadata=? WHERE job_id=? AND asset_id=?",
                                   (revision, json.dumps(metadata), pid, asset_id))
    service.store.conn.commit()
    timeline["project_revision"] = copy["revision"]
    timeline["compilation_fingerprint"] = _resolved_compilation_fingerprint(timeline)
    before = artifact_rows(service, pid)
    with pytest.raises(ProjectError) as failure:
        service.write(pid, "resolved_timeline", timeline, copy["revision"])
    assert failure.value.code == "invalid_artifact"
    assert any(word in str(failure.value).lower() for word in ("asset", "evidence", "string"))
    assert artifact_rows(service, pid) == before
    assert service.open(pid)["revision"] == copy["revision"]
    before_duplicate = database_rows(service)
    with pytest.raises(ProjectError):
        service.duplicate(pid)
    assert database_rows(service) == before_duplicate


def test_normal_split_evidence_rejects_rehashed_treatment_window(stored_evidence_split):
    from atme.project_service import _resolved_compilation_fingerprint
    from atme.store.contracts_v2 import _split_packet_digest

    service, source, *_ = stored_evidence_split
    copy = service.duplicate(source["project_id"])
    pid = copy["project_id"]
    timeline = service.artifact(pid, "resolved_timeline")["document"]
    item = timeline["actions"][0]
    item["split_evidence_windows"][0]["treatment_sha256"] = "0" * 64
    receipt = item["split_completion_receipt"]
    receipt["evidence_windows"] = deepcopy(item["split_evidence_windows"])
    receipt["completion_sha256"] = _split_packet_digest({key: value for key, value in receipt.items() if key != "completion_sha256"})
    timeline["project_revision"] = copy["revision"]
    timeline["compilation_fingerprint"] = _resolved_compilation_fingerprint(timeline)
    before = artifact_rows(service, pid)
    with pytest.raises(ProjectError) as failure:
        service.write(pid, "resolved_timeline", timeline, copy["revision"])
    assert "actual treatment and phase timing" in str(failure.value.errors)
    assert artifact_rows(service, pid) == before


def test_normal_split_evidence_preserves_origin_reference_after_duplicate(stored_evidence_split):
    from v2_fixtures import digest

    from atme.project_service import _resolved_compilation_fingerprint
    from atme.store.contracts_v2 import _split_packet_digest

    service, source, *_ = stored_evidence_split
    copy = service.duplicate(source["project_id"])
    pid = copy["project_id"]
    plan = service.artifact(pid, "storyboard")["document"]
    layout = service.artifact(pid, "layout")["document"]
    timeline = service.artifact(pid, "resolved_timeline")["document"]
    asset = plan["assets"][0]
    destination = f"atme://projects/{pid}/assets/{asset['asset_id']}"
    assert asset["managed_ref"] != destination
    asset["managed_ref"] = destination
    for treatment in layout["evidence_treatments"]:
        treatment["asset_managed_ref"] = destination
    plan["project_revision"] = copy["revision"]
    copy = service.write(pid, "storyboard", plan, copy["revision"])
    layout.update(project_revision=copy["revision"], plan_revision=copy["artifacts"]["storyboard"], plan_sha256=digest(plan))
    copy = service.write(pid, "layout", layout, copy["revision"])
    timeline["resolved_assets"][0]["managed_ref"] = destination
    timeline["evidence_treatments"] = deepcopy(layout["evidence_treatments"])
    item = timeline["actions"][0]
    by_id = {row["object_id"]: row for row in layout["evidence_treatments"]}
    for window in item["split_evidence_windows"]:
        window["treatment_sha256"] = _split_packet_digest(by_id[window["result_object_id"]])
    receipt = item["split_completion_receipt"]
    receipt["evidence_windows"] = deepcopy(item["split_evidence_windows"])
    receipt["completion_sha256"] = _split_packet_digest({key: value for key, value in receipt.items() if key != "completion_sha256"})
    timeline.update(project_revision=copy["revision"], plan_revision=copy["artifacts"]["storyboard"],
        plan_sha256=digest(plan), layout_revision=copy["artifacts"]["layout"], layout_sha256=digest(layout))
    timeline["compilation_fingerprint"] = _resolved_compilation_fingerprint(timeline)
    before = artifact_rows(service, pid)
    with pytest.raises(ProjectError, match="authoritative stored binding"):
        service.write(pid, "resolved_timeline", timeline, copy["revision"])
    assert artifact_rows(service, pid) == before


def test_normal_split_evidence_verifies_actual_bytes_and_never_repairs_original(stored_evidence_split):
    from atme.project_service import _resolved_compilation_fingerprint

    service, source, *_ = stored_evidence_split
    copy = service.duplicate(source["project_id"])
    pid = copy["project_id"]
    timeline = service.artifact(pid, "resolved_timeline")["document"]
    asset_id = timeline["resolved_assets"][0]["asset_id"]
    relative = service.store.conn.execute("SELECT relative_path FROM project_assets WHERE job_id=? AND asset_id=?",
                                          (pid, asset_id)).fetchone()[0]
    path = service.store.db_path.parent / relative
    original = path.read_bytes()
    corrupted = original + b"corrupted-test-original"
    before = artifact_rows(service, pid)
    try:
        path.write_bytes(corrupted)
        timeline["project_revision"] = copy["revision"]
        timeline["compilation_fingerprint"] = _resolved_compilation_fingerprint(timeline)
        with pytest.raises(ProjectError, match="immutable byte verification"):
            service.write(pid, "resolved_timeline", timeline, copy["revision"])
        assert artifact_rows(service, pid) == before
        assert path.read_bytes() == corrupted
    finally:
        path.write_bytes(original)


@pytest.mark.parametrize("mutation", ["origin", "provenance", "permissions"])
def test_split_actual_capture_and_frozen_native_inputs_reject_forged_treatment(stored_evidence_split, mutation):
    import json
    from dataclasses import replace
    from hashlib import sha256

    from test_v2_split_identity import sample_for_layout

    from atme.project_assets import read_verified_split_asset_bytes
    from atme.render.v2_split import capture_split
    from atme.render.v2_split_paint import (
        prove_split_coverage,
        verify_split_paint_inputs,
    )
    from atme.render.v2_timeline_replay import _replay_split_chronology
    from atme.store.contracts_v2 import (
        ExecutableLayoutV2,
        ResolvedAction,
        ResolvedVisualTimelineV2,
        _split_packet_digest,
    )

    service, source, *_ = stored_evidence_split
    copy = service.duplicate(source["project_id"])
    pid = copy["project_id"]
    layout = ExecutableLayoutV2.model_validate(service.artifact(pid, "layout")["document"])
    timeline = ResolvedVisualTimelineV2.model_validate(service.artifact(pid, "resolved_timeline")["document"])
    pins = timeline.actions[0].action.split_policy.source_basis.asset_pins
    carrier = read_verified_split_asset_bytes(service, layout, timeline.resolved_assets, pins)
    inputs = verify_split_paint_inputs(layout, carrier)
    initial = sample_for_layout(layout)
    replay = _replay_split_chronology(layout, initial, tuple(timeline.actions), timeline.duration_ms, carrier, timeline=timeline)
    capture = next(row.split_capture for checkpoint in replay.checkpoints for row in checkpoint.active)
    assert prove_split_coverage(capture, layout, inputs).paint_inputs_sha256 == inputs.inputs_sha256
    raw_layout = layout.model_dump(mode="json")
    changed = raw_layout["evidence_treatments"][0]
    if mutation == "origin":
        changed["asset_managed_ref"] = pins[0].resource_uri
    elif mutation == "provenance":
        changed["asset_provenance"]["source_uri"] = "https://example.com/forged-origin"
    else:
        changed["allowed_transformations"].reverse()
    raw_action = timeline.actions[0].model_dump(mode="json")
    for window in raw_action["split_evidence_windows"]:
        if window["result_object_id"] == changed["object_id"]:
            window["treatment_sha256"] = _split_packet_digest(changed)
    receipt = raw_action["split_completion_receipt"]
    receipt["evidence_windows"] = deepcopy(raw_action["split_evidence_windows"])
    receipt["completion_sha256"] = _split_packet_digest({key: value for key, value in receipt.items() if key != "completion_sha256"})
    forged_action = ResolvedAction.model_validate(raw_action)
    forged_layout = ExecutableLayoutV2.model_validate(raw_layout)
    with pytest.raises(ValueError, match="(?i)evidence|treatment"):
        capture_split(forged_action, forged_layout, replay.before_action(capture.action_id), carrier)
    canonical = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":"))
    row = inputs.project_assets[0]
    treatments = [json.loads(value) for value in row.treatments_json]
    treatments[0] = changed
    frozen_row = replace(row, treatments_json=tuple(canonical(value) for value in treatments))
    manifest = json.loads(inputs.manifest_json)
    manifest["project_assets"][0]["treatments"] = treatments
    manifest_json = canonical(manifest)
    forged_inputs = replace(inputs, project_assets=(frozen_row,), manifest_json=manifest_json,
                            inputs_sha256=sha256(manifest_json.encode()).hexdigest())
    with pytest.raises(ValueError, match="(?i)evidence|treatment"):
        prove_split_coverage(capture, layout, forged_inputs)


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("family", ["evidence", "media"])
def test_normal_asset_backed_split_duplicate_retains_bytes_after_origin_removal(
        tmp_path, portrait, family, original_video):
    from v2_fixtures import digest

    from atme.project_assets import read_verified_split_asset_bytes
    from atme.store.contracts_v2 import ExecutableLayoutV2

    service, project, plan, layout, timeline = stored_split_basis(
        tmp_path, portrait=portrait, family=family, video=original_video)
    try:
        pid = project["project_id"]
        originals = {str(path): path.read_bytes() for path in tmp_path.rglob("*")
                     if path.is_file() and path.suffix.lower() in {".png", ".mp4", ".wav"}}
        project = service.write(pid, "resolved_timeline", timeline, project["revision"])
        original_rows = artifact_rows(service, pid)
        first = service.duplicate(pid)
        media_id = service.narrative_source(pid)["timing_authority"]["media"]["media_id"]
        service.source_timeline.remove_source(pid, media_id, project["revision"], True)
        service.archive(pid, service.open(pid)["revision"], True)
        second = service.duplicate(first["project_id"])
        for copy in (first, second):
            copied_plan = service.artifact(copy["project_id"], "storyboard")["document"]
            copied_layout = service.artifact(copy["project_id"], "layout")["document"]
            copied_clock = service.artifact(copy["project_id"], "resolved_timeline")["document"]
            policy = copied_plan["actions"][0]["split_policy"]
            pins = policy["source_basis"]["asset_pins"]
            assert pins[0]["resource_uri"] == f"atme://projects/{copy['project_id']}/assets/{pins[0]['asset_id']}"
            assert policy["source_basis_sha256"] == digest(policy["source_basis"])
            receipt = copied_clock["actions"][0]["split_completion_receipt"]
            assert receipt["policy_sha256"] == digest(policy)
            assert receipt["asset_pins"] == pins
            carrier = read_verified_split_asset_bytes(service, ExecutableLayoutV2.model_validate(copied_layout),
                copied_clock["resolved_assets"], pins)
            assert carrier.rows and carrier.rows[0].payload in originals.values()
            assert copied_layout["objects"] == layout["objects"]
            assert copied_clock["actions"][0].get("split_evidence_windows") == timeline["actions"][0].get("split_evidence_windows")
            if family == "evidence":
                assert copied_plan["assets"][0]["managed_ref"] == plan["assets"][0]["managed_ref"]
                assert copied_layout["evidence_treatments"] == layout["evidence_treatments"]
        assert artifact_rows(service, pid) == original_rows
        assert {path: Path(path).read_bytes() for path in originals} == originals
    finally:
        service.store.close()


@pytest.mark.parametrize("portrait", [False, True])
def test_recording_only_split_keeps_optional_index_non_authoritative(tmp_path, portrait):
    service, project, plan, _, timeline = stored_split_basis(
        tmp_path, portrait=portrait, mode="audio-only", with_index=True)
    try:
        pid = project["project_id"]
        project = service.write(pid, "resolved_timeline", timeline, project["revision"])
        assert plan["narrative_authority"]["mode"] == "recording_only"
        assert project["approved_script_revision"] is None
        assert not service.store.conn.execute(
            "SELECT 1 FROM project_artifact_dependencies WHERE job_id=?", (pid,)).fetchall()
    finally:
        service.store.close()


@pytest.mark.parametrize("mode", ["script+audio", "audio-only"])
@pytest.mark.parametrize("mutation", ["mode", "authority_id", "timing_media_sha256",
                                      "cleaned_timeline_revision", "cleaned_timeline_fingerprint", "project_revision"])
def test_normal_split_rejects_stale_narrative_authority_without_publication(tmp_path, mode, mutation):
    service, project, plan, _, timeline = stored_split_basis(tmp_path, mode=mode)
    try:
        pid = project["project_id"]
        project = service.write(pid, "resolved_timeline", timeline, project["revision"])
        invalid = deepcopy(plan)
        invalid["project_revision"] = project["revision"]
        authority = invalid["narrative_authority"]
        if mutation == "mode":
            authority["mode"] = "recording_only" if mode.startswith("script") else "approved_script_plus_recording"
        elif mutation == "authority_id":
            authority[mutation] = "unowned-authority"
        elif mutation == "project_revision":
            invalid[mutation] -= 1
        elif mutation == "cleaned_timeline_revision":
            authority[mutation] += 1
        else:
            authority[mutation] = "0" * 64
        before = artifact_rows(service, pid)
        with pytest.raises(ProjectError) as failure:
            service.write(pid, "storyboard", invalid, project["revision"])
        assert failure.value.code == "stale_contract_basis"
        assert artifact_rows(service, pid) == before
        assert service.open(pid)["revision"] == project["revision"]
    finally:
        service.store.close()


def test_normal_split_rejects_unapproved_script_even_with_current_authority_id(tmp_path):
    from test_external_inputs import external_payload

    service, project, plan, _, timeline = stored_split_basis(tmp_path)
    try:
        pid = project["project_id"]
        project = service.write(pid, "resolved_timeline", timeline, project["revision"])
        project = service.write(pid, "script", external_payload()["script"], project["revision"])
        plan["project_revision"] = project["revision"]
        plan["narrative_authority"]["authority_id"] = f"script-revision-{project['artifacts']['script']}"
        before = artifact_rows(service, pid)
        with pytest.raises(ProjectError, match="current approved script"):
            service.write(pid, "storyboard", plan, project["revision"])
        assert artifact_rows(service, pid) == before
    finally:
        service.store.close()


@pytest.mark.parametrize("mutation", ["revision", "checksum", "authority"])
def test_coherently_rehashed_media_authority_rejects_owned_row_mismatch(tmp_path, original_video, mutation):
    from v2_fixtures import digest

    from atme.project_service import _resolved_compilation_fingerprint
    from atme.store.contracts_v2 import SplitPolicy, _split_expected_completion

    service, project, plan, layout, timeline = stored_split_basis(tmp_path, family="media", video=original_video)
    try:
        pid = project["project_id"]
        project = service.write(pid, "resolved_timeline", timeline, project["revision"])
        asset = plan["assets"][0]
        if mutation == "revision":
            asset["revision"] += 1
        elif mutation == "checksum":
            asset["checksum_sha256"] = "0" * 64
            asset["provenance"]["checksum_sha256"] = asset["checksum_sha256"]
        else:
            asset["managed_ref"] = f"atme://projects/999/assets/{asset['asset_id']}"
        for obj in (*plan["objects"], *layout["objects"]):
            placement = obj["media_playback"]["placement"]
            placement.update(source_sha256=asset["checksum_sha256"], source_revision=asset["revision"])
        policy = plan["actions"][0]["split_policy"]
        pin = policy["source_basis"]["asset_pins"][0]
        pin.update(revision=asset["revision"], checksum_sha256=asset["checksum_sha256"], resource_uri=asset["managed_ref"])
        policy["source_basis_sha256"] = digest(policy["source_basis"])
        plan["project_revision"] = project["revision"]
        project = service.write(pid, "storyboard", plan, project["revision"])
        layout.update(project_revision=project["revision"], plan_revision=project["artifacts"]["storyboard"], plan_sha256=digest(plan))
        project = service.write(pid, "layout", layout, project["revision"])
        timeline["actions"][0]["action"] = deepcopy(plan["actions"][0])
        receipt = _split_expected_completion(SplitPolicy.model_validate(policy))
        receipt["completion_sha256"] = digest(receipt)
        timeline["actions"][0]["split_completion_receipt"] = receipt
        timeline["resolved_assets"][0].update({key: asset[key] for key in ("revision", "managed_ref", "checksum_sha256")})
        timeline.update(project_revision=project["revision"], plan_revision=project["artifacts"]["storyboard"],
            plan_sha256=digest(plan), layout_revision=project["artifacts"]["layout"], layout_sha256=digest(layout))
        timeline["compilation_fingerprint"] = _resolved_compilation_fingerprint(timeline)
        before = artifact_rows(service, pid)
        originals = {path: path.read_bytes() for path in tmp_path.rglob("*.mp4")}
        with pytest.raises(ProjectError, match="[Mm]edia|original") as failure:
            service.write(pid, "resolved_timeline", timeline, project["revision"])
        assert failure.value.code == ("invalid_asset" if mutation == "authority" else "asset_changed")
        assert artifact_rows(service, pid) == before
        assert service.open(pid)["revision"] == project["revision"]
        assert {path: path.read_bytes() for path in originals} == originals
    finally:
        service.store.close()


def test_duplicate_rejects_rehashed_receipt_without_publishing_any_destination_rows(tmp_path):
    import json

    from v2_fixtures import digest

    from atme.project_service import _resolved_compilation_fingerprint

    service, project, _, _, timeline = stored_split_basis(tmp_path)
    try:
        pid = project["project_id"]
        project = service.write(pid, "resolved_timeline", timeline, project["revision"])
        receipt = timeline["actions"][0]["split_completion_receipt"]
        receipt["placements"][0]["state_version"] += 1
        receipt["completion_sha256"] = digest({key: value for key, value in receipt.items() if key != "completion_sha256"})
        timeline["compilation_fingerprint"] = _resolved_compilation_fingerprint(timeline)
        # Corrupt a previously valid immutable row only to exercise duplicate's read boundary.
        service.store.conn.execute("UPDATE project_artifact_versions SET document=? WHERE job_id=? AND kind='resolved_timeline'",
                                   (json.dumps(timeline), pid))
        service.store.conn.commit()
        tables = ("jobs", "project_state", "project_artifact_versions", "project_duplicate_derivations", "project_assets")
        before = {table: tuple(tuple(row) for row in service.store.conn.execute(f"SELECT * FROM {table}")) for table in tables}
        with pytest.raises(ProjectError, match="Split|split"):
            service.duplicate(pid)
        after = {table: tuple(tuple(row) for row in service.store.conn.execute(f"SELECT * FROM {table}")) for table in tables}
        assert after == before
    finally:
        service.store.close()


@pytest.mark.parametrize("kind", ["storyboard", "layout", "resolved_timeline", "cleaned_timeline"])
def test_duplicate_rejects_coherent_stale_immutable_project_revision(tmp_path, kind):
    import json

    from v2_fixtures import digest

    from atme.project_service import _resolved_compilation_fingerprint

    service, project, plan, layout, timeline = stored_split_basis(tmp_path)
    try:
        pid = project["project_id"]
        project = service.write(pid, "resolved_timeline", timeline, project["revision"])
        documents = {"storyboard": plan, "layout": layout, "resolved_timeline": timeline}
        if kind == "cleaned_timeline":
            cleaned = service.source_timeline.get(pid)
            moved = service.source_timeline.command(pid, "move",
                {"clip_id": cleaned["document"]["clips"][0]["clip_id"], "to_index": 0},
                project["revision"], cleaned["timeline_revision"])
            assert moved["timeline"]["document"] == cleaned["document"]
            revision = moved["timeline"]["timeline_revision"]
            plan["narrative_authority"]["cleaned_timeline_revision"] = revision
            timeline["cleaned_timeline_revision"] = revision
        else:
            documents[kind]["project_revision"] += 1
        layout["plan_sha256"] = digest(plan)
        timeline.update(plan_sha256=digest(plan), layout_sha256=digest(layout))
        timeline["compilation_fingerprint"] = _resolved_compilation_fingerprint(timeline)
        for artifact_kind, document in documents.items():
            service.store.conn.execute(
                "UPDATE project_artifact_versions SET document=? WHERE job_id=? AND kind=? AND revision=?",
                (json.dumps(document), pid, artifact_kind, project["artifacts"][artifact_kind]))
        service.store.conn.commit()
        before = database_rows(service)
        with pytest.raises(ProjectError, match="immutable.*(?:revision|timing)") as failure:
            service.duplicate(pid)
        assert failure.value.code == "stale_contract_basis"
        assert database_rows(service) == before
    finally:
        service.store.close()


@pytest.mark.parametrize("mutation", ["parent", "order", "content", "pose", "state", "version", "phase", "receipt"])
def test_coherently_rehashed_stale_split_rejects_at_normal_atomic_boundary(tmp_path, mutation):
    from v2_fixtures import digest

    from atme.project_service import _resolved_compilation_fingerprint
    from atme.store.contracts_v2 import SplitPolicy, _split_expected_completion

    service, project, plan, layout, timeline = stored_split_basis(tmp_path, with_context=mutation == "parent")
    try:
        pid = project["project_id"]
        project = service.write(pid, "resolved_timeline", timeline, project["revision"])
        original = deepcopy(timeline)
        policy = plan["actions"][0]["split_policy"]
        placements = policy["source_basis"]["placements"]
        row = placements[0]
        if mutation == "parent":
            context = deepcopy(next(item for item in placements if item["object_id"] == "source"))
            context.update(object_id="parent-context", sibling_ordinal=3)
            for item in placements:
                item["parent_id"] = context["object_id"]
            placements.append(context)
            placements.sort(key=lambda item: item["object_id"])
            policy["source_basis"]["read_dependencies"] = [{"kind": "ancestor", "object_ids": [context["object_id"]]}]
        elif mutation == "order":
            placements[0]["sibling_ordinal"], placements[1]["sibling_ordinal"] = (
                placements[1]["sibling_ordinal"], placements[0]["sibling_ordinal"])
        elif mutation == "content":
            row["content_sha256"] = "0" * 64
            for correspondence in policy["correspondences"]:
                if correspondence["result_object_id"] == row["object_id"]:
                    correspondence["result_content_sha256"] = row["content_sha256"]
        elif mutation == "pose":
            row["local_transform"]["position"]["x"] += 1
            next(result for result in policy["results"] if result["object_id"] == row["object_id"])["destination"] = deepcopy(row["local_transform"])
        elif mutation == "state":
            row["local_opacity"] = 0.5
        elif mutation == "version":
            row["state_version"] += 1
        elif mutation == "phase":
            policy["source_exit"].update(start_tick=0, end_tick=1000)
            for result in policy["results"]:
                result["construction"]["phase"].update(start_tick=9000, end_tick=10000)
        if mutation != "receipt":
            policy["source_basis_sha256"] = digest(policy["source_basis"])
            plan["project_revision"] = project["revision"]
            project = service.write(pid, "storyboard", plan, project["revision"])
            layout.update(project_revision=project["revision"], plan_revision=project["artifacts"]["storyboard"],
                          plan_sha256=digest(plan))
            project = service.write(pid, "layout", layout, project["revision"])
            timeline["actions"][0]["action"] = deepcopy(plan["actions"][0])
            receipt = _split_expected_completion(SplitPolicy.model_validate(policy))
            receipt["completion_sha256"] = digest(receipt)
            timeline["actions"][0]["split_completion_receipt"] = receipt
        else:
            receipt = timeline["actions"][0]["split_completion_receipt"]
            receipt["placements"][0]["state_version"] += 1
            receipt["completion_sha256"] = digest({key: value for key, value in receipt.items() if key != "completion_sha256"})
        timeline.update(project_revision=project["revision"], plan_revision=project["artifacts"]["storyboard"],
            plan_sha256=digest(plan), layout_revision=project["artifacts"]["layout"], layout_sha256=digest(layout))
        timeline["compilation_fingerprint"] = _resolved_compilation_fingerprint(timeline)
        before = artifact_rows(service, pid)
        media = service.authoritative_media(pid)[0]
        with pytest.raises(ProjectError) as failure:
            service.write(pid, "resolved_timeline", timeline, project["revision"])
        assert failure.value.code == "invalid_artifact"
        assert "split" in (str(failure.value) + str(failure.value.errors)).lower()
        assert artifact_rows(service, pid) == before
        assert service.open(pid)["revision"] == project["revision"]
        assert service.authoritative_media(pid)[0] == media
        assert service.artifact(pid, "resolved_timeline")["document"] == original
    finally:
        service.store.close()


def artifact_rows(service, project_id):
    with service.store._lock:
        return tuple(tuple(row) for row in service.store.conn.execute(
            "SELECT kind,revision,document FROM project_artifact_versions WHERE job_id=? "
            "ORDER BY kind,revision", (project_id,)))


def database_rows(service):
    tables = ("jobs", "project_state", "project_artifact_versions", "project_duplicate_derivations", "project_assets")
    return {table: tuple(tuple(row) for row in service.store.conn.execute(f"SELECT * FROM {table}")) for table in tables}


@pytest.mark.parametrize("mutation", ["missing_policy", "extra_correspondence", "false_content_digest",
                                      "container", "hierarchy"])
def test_normal_write_rejects_incomplete_split_atomically(tmp_path, mutation):
    service, project, existing = _store_v2_plan(tmp_path)
    try:
        plan, _layout, _timeline = split_documents()
        plan.update(project_id=project["project_id"], project_revision=project["revision"],
                    narrative_authority=deepcopy(existing["narrative_authority"]))
        # A valid normal write establishes that negatives reach the Split boundary.
        project = service.write(project["project_id"], "storyboard", plan, project["revision"])
        invalid = deepcopy(plan)
        invalid["project_revision"] = project["revision"]
        action = invalid["actions"][0]
        if mutation == "missing_policy":
            action.pop("split_policy")
        elif mutation == "extra_correspondence":
            action["split_policy"]["correspondences"].append(
                deepcopy(action["split_policy"]["correspondences"][0]))
        elif mutation == "false_content_digest":
            action["split_policy"]["correspondences"][0]["source_content_sha256"] = "0" * 64
        elif mutation == "container":
            action["container_id"] = "source"
        else:
            action["hierarchy_policy"] = {}
        before = artifact_rows(service, project["project_id"])
        with pytest.raises(ProjectError) as failure:
            service.write(project["project_id"], "storyboard", invalid, project["revision"])
        assert failure.value.code == "invalid_artifact"
        assert service.open(project["project_id"])["revision"] == project["revision"]
        assert artifact_rows(service, project["project_id"]) == before
    finally:
        service.store.close()


@pytest.mark.parametrize("mutation", ["missing_completion", "false_rehashed_completion", "changed_authored_policy"])
def test_normal_resolved_split_write_rejects_receipt_atomically(tmp_path, mutation):
    from v2_fixtures import digest

    from atme.project_service import _resolved_compilation_fingerprint

    service, project, _plan, _layout, timeline = stored_split_basis(tmp_path)
    try:
        project = service.write(project["project_id"], "resolved_timeline", timeline, project["revision"])
        timeline["project_revision"] = project["revision"]
        if mutation == "missing_completion":
            timeline["actions"][0].pop("split_completion_receipt")
        elif mutation == "changed_authored_policy":
            policy = timeline["actions"][0]["action"]["split_policy"]
            policy["correspondences"][0]["statement"] = "Resolved-only assertion"
            receipt = timeline["actions"][0]["split_completion_receipt"]
            receipt["policy_sha256"] = digest(policy)
            receipt["completion_sha256"] = digest({key: value for key, value in receipt.items() if key != "completion_sha256"})
        else:
            receipt = timeline["actions"][0]["split_completion_receipt"]
            receipt["placements"][0]["state_version"] += 1
            receipt["completion_sha256"] = digest({key: value for key, value in receipt.items() if key != "completion_sha256"})
        timeline["compilation_fingerprint"] = _resolved_compilation_fingerprint(timeline)
        before = artifact_rows(service, project["project_id"])
        with pytest.raises(ProjectError) as failure:
            service.write(project["project_id"], "resolved_timeline", timeline, project["revision"])
        assert failure.value.code == "invalid_artifact"
        if mutation == "missing_completion":
            assert "completion receipt" in str(failure.value)
        elif mutation == "changed_authored_policy":
            assert "authoritative plan" in str(failure.value)
        assert service.open(project["project_id"])["revision"] == project["revision"]
        assert artifact_rows(service, project["project_id"]) == before
    finally:
        service.store.close()
