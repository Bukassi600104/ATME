"""Task8 private chronology proofs; not native/public Split admission."""

import json
from copy import deepcopy
from dataclasses import replace

import pytest
from atme.render.v2_split_paint import (
    _freeze_verified_split_asset,
    _VerifiedSplitAssetBytes,
)
from atme.render.v2_state import (
    UnsupportedVisualAction,
    V2FrameError,
    _validate_pair_static,
    evaluate_frame,
)
from atme.render.v2_timeline_replay import _replay_split_chronology
from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    ResolvedAction,
    ResolvedAsset,
    ResolvedVisualTimelineV2,
    SplitAssetPin,
)
from test_v2_evidence_compositor import evidence_documents
from test_v2_split_capture import geometry_boundary, peer_action
from test_v2_split_evidence_assets import ordinary_shared_evidence
from test_v2_split_evidence_assets import (
    shared_boundary as shared_boundary,  # noqa: PLC0414 -- fixture re-export
)
from test_v2_split_evidence_assets import (
    shared_inputs as shared_inputs,  # noqa: PLC0414 -- fixture dependency
)
from test_v2_split_evidence_capture import live_evidence_boundary
from test_v2_split_identity import sample_for_layout
from v2_fixtures import digest
from v2_split_fixtures import split_documents


def retained_handoff_documents(kind, *, fault=None, later_connection=None, connection_start=1500,
                                multi_note=False, with_leader=False, portrait=False):
    from atme.render.v2_split import _observed_split_placements
    from atme.render.v2_split_identity import split_content_receipts
    from atme.render.v2_timeline_replay import replay_chronology
    from atme.store.contracts_v2 import SplitPolicy, _split_expected_completion
    from test_v2_timeline_replay import resolved as timed

    layout, _, split = geometry_boundary()
    raw = layout.model_dump(mode="json")
    if portrait:
        _, profile_layout, _ = split_documents("SHORT_FORM_9_16")
        raw.update(output_profile=profile_layout["output_profile"], canvas=profile_layout["canvas"])
    extra = deepcopy(next(row for row in raw["objects"] if row["object_id"] == "part-1"))
    extra.update(object_id="relationship", z_index=3)
    if kind == "annotation":
        creation = timed(peer_action("annotate", target_ids=["source"], annotation_policy={
            "annotation_object_ids": ["relationship"],
            "phases": [{"object_id": "relationship", "mode": "draw", "weight": 1}],
            "readable_hold_ms": 100}).action.model_copy(update={"action_id": "create-note"}), 0, 100)
        removal = timed({**peer_action("reveal", target_ids=["relationship"]).action.model_dump(mode="json"),
            "verb": "exit", "action_id": "remove-note", "post_state": "removed"}, 250, 400)
        prior = (creation, removal)
        if multi_note:
            second = deepcopy(extra)
            second.update(object_id="second-note", z_index=4)
            raw["objects"].append(second)
            raw["boards"][0]["object_ids"].append("second-note")
            document = creation.model_dump(mode="json")
            policy = document["action"]["annotation_policy"]
            policy["annotation_object_ids"].append("second-note")
            policy["phases"].append({"object_id": "second-note", "mode": "draw", "weight": 1})
            creation = ResolvedAction.model_validate(document)
            first_exit = timed(removal.action, 250, 350)
            second_exit = timed(removal.action.model_copy(update={"action_id": "remove-second-note",
                                                                  "target_ids": ["second-note"]}), 360, 400)
            prior = (creation, first_exit, second_exit)
        if with_leader:
            from test_v2_annotation_contract import leader_documents

            extra["transform"]["position"]["x"] = 100.0
            leader = deepcopy(leader_documents()[1]["objects"][-1])
            leader.update(object_id="note-leader", source_object_id="relationship", destination_object_id="source",
                          z_index=4, board_id=extra["board_id"], beat_id=extra["beat_id"],
                          coverage_ids=deepcopy(extra["coverage_ids"]))
            leader["geometry"]["bounds"] = deepcopy(raw["canvas"])
            raw["objects"].append(leader)
            raw["boards"][0]["object_ids"].append("note-leader")
            document = creation.model_dump(mode="json")
            document["action"]["annotation_policy"]["leader_connector_id"] = "note-leader"
            document["action"]["annotation_policy"]["phases"].append(
                {"object_id": "note-leader", "mode": "draw", "weight": 1})
            leader_exit = timed(removal.action.model_copy(update={"action_id": "remove-leader",
                                                                  "target_ids": ["note-leader"]}), 360, 400)
            prior = (ResolvedAction.model_validate(document), timed(removal.action, 250, 350), leader_exit)
    else:
        extra.pop("path_data")
        extra["anchors"] = []
        extra["style"].update(fill=None, text=None)
        extra.update(object_type="arrow", source_object_id="source", source_anchor_id="center",
            destination_object_id="peer-target", destination_anchor_id="center", role="semantic_connector",
            routing="straight", allow_self_loop=False, initial_state="connected", visible=True)
        if kind == "pointer":
            extra.update(source_object_id=None, source_anchor_id=None, source_point={"x": 0.0, "y": 0.0},
                         destination_object_id="source", role="pointer")
        else:
            target = deepcopy(next(row for row in raw["objects"] if row["object_id"] == "source"))
            target.update(object_id="peer-target", z_index=3)
            target["transform"]["position"]["x"] = 100.0
            raw["objects"].append(target)
            raw["boards"][0]["object_ids"].append("peer-target")
            extra["z_index"] = 4
        params = {key: extra[key] for key in ("source_object_id", "source_anchor_id",
                                               "destination_object_id", "destination_anchor_id")}
        removal = timed(peer_action("disconnect", connector_id="relationship", **params).action.model_copy(
            update={"action_id": "remove-arrow", "expected_state": "connected", "post_state": "disconnected"}),
            250, 400)
        prior = (removal,)
        if kind == "connected":
            extra.update(initial_state="disconnected", visible=False)
            creation = timed(peer_action("connect", connector_id="relationship", **params).action.model_copy(
                update={"action_id": "connect-arrow", "expected_state": "disconnected", "post_state": "connected"}),
                0, 100)
            prior = (creation, removal)
    later = ()
    if later_connection is not None:
        pointer = deepcopy(extra)
        pointer.update(object_id="later-pointer", z_index=5, source_object_id=None, source_anchor_id=None,
            source_point={"x": 0.0, "y": 0.0}, destination_object_id="peer-target", role="pointer",
            initial_state="connected" if later_connection == "reconnect" else "disconnected",
            visible=later_connection == "reconnect")
        raw["objects"].append(pointer)
        raw["boards"][0]["object_ids"].append("later-pointer")
        params = {"connector_id": "later-pointer", "source_object_id": None, "source_anchor_id": None,
                  "destination_object_id": "peer-target", "destination_anchor_id": "center"}
        if later_connection == "reconnect":
            disconnected = timed(peer_action("disconnect", **params).action.model_copy(update={
                "action_id": "disconnect-later", "expected_state": "connected", "post_state": "disconnected"}),
                250, 400)
            prior = (*prior, disconnected)
        later = (timed(peer_action("connect", **params).action.model_copy(update={
            "action_id": "future-connect", "expected_state": "disconnected", "post_state": "connected"}),
            connection_start, connection_start + 100),)
    if fault == "active":
        if len(prior) == 1:
            later = (timed(prior[0].action, 1600, 1800),)
        prior = prior[:-1]
    elif fault in {"same_time", "in_flight"}:
        removal = prior[-1].model_dump(mode="json")
        removal["end_ms"] = 500 if fault == "same_time" else 600
        prior = (*prior[:-1], ResolvedAction.model_validate(removal))
    elif fault == "hold_overlap":
        creation = prior[0].model_dump(mode="json")
        creation["action"]["annotation_policy"]["readable_hold_ms"] = 600
        prior = (ResolvedAction.model_validate(creation), *prior[1:])
    elif fault == "writer":
        writer = timed(peer_action("fade", target_ids=["source"], opacity=0.8).action.model_copy(
            update={"action_id": "after-termination-writer"}), 410, 450)
        prior = (*prior, writer)
    elif fault == "re_add":
        re_add = timed({**peer_action("reveal", target_ids=["relationship"]).action.model_dump(mode="json"),
            "verb": "enter", "action_id": "re-add-note", "expected_state": "removed",
            "post_state": "visible"}, 410, 450)
        prior = (*prior, re_add)
    raw["objects"].append(extra)
    raw["boards"][0]["object_ids"].append("relationship")
    layout = ExecutableLayoutV2.model_validate(raw)
    initial = sample_for_layout(layout)
    objects = {row.object_id: row for row in layout.objects}
    prefix = replay_chronology(objects, initial.hierarchy, {row.object_id: row for row in initial.objects},
        dict(initial.state_versions), prior,
        tuple((row.board_id, row.start_ms, row.end_ms) for row in layout.activations), 2000)
    before = prefix.at(500)
    contents = {row.object_id: row for row in split_content_receipts(layout, before, {})}
    raw = split.model_dump(mode="json")
    raw.update(start_ms=500, end_ms=1500)
    policy = raw["action"]["split_policy"]
    basis = policy["source_basis"]
    bound = {"source", "part-1", "part-2"}
    if kind != "annotation":
        bound.add("relationship")
        if kind != "pointer":
            bound.add("peer-target")
        basis["read_dependencies"] = [{"kind": "connector_anchor", "object_ids": sorted(bound - {"part-1", "part-2"})}]
    elif with_leader:
        bound.update(["relationship", "note-leader"])
        basis["read_dependencies"] = [{"kind": "connector_anchor", "object_ids": ["note-leader", "relationship", "source"]}]
    basis["placements"] = [row.model_dump(mode="json") for row in
        _observed_split_placements(before, objects, bound, contents)]
    policy["source_basis_sha256"] = digest(basis)
    receipt = _split_expected_completion(SplitPolicy.model_validate(policy))
    receipt["completion_sha256"] = digest(receipt)
    raw["split_completion_receipt"] = receipt
    split = ResolvedAction.model_validate(raw)
    _, _, clock = split_documents()
    clock.update(layout_sha256=digest(layout.model_dump(mode="json")), output_profile=layout.output_profile.model_dump(mode="json"),
        actions=[row.model_dump(mode="json") for row in sorted((*prior, split, *later), key=lambda row: row.start_ms)],
        initial_object_states=[{"object_id": row.object_id, "state": row.state,
            "state_version": dict(initial.state_versions)[row.object_id], "visible": row.visible}
            for row in initial.objects])
    clock["coverage"][0]["action_ids"] = [row["action"]["action_id"] for row in clock["actions"]]
    return layout, initial, ResolvedVisualTimelineV2.model_validate(clock)


@pytest.mark.parametrize("kind", ["initial", "connected", "pointer", "annotation"])
@pytest.mark.parametrize("portrait", [False, True])
def test_retained_anchors_require_completed_handoff(kind, portrait):
    layout, initial, timeline = retained_handoff_documents(kind, portrait=portrait)
    original = layout.model_dump_json(), repr(initial), timeline.model_dump_json()
    with pytest.raises(ValueError, match="managed connector|retained annotation"):
        _replay_split_chronology(layout, initial, tuple(timeline.actions), timeline.duration_ms, {})
    replay = _replay_split_chronology(layout, initial, tuple(timeline.actions), timeline.duration_ms, {},
                                      timeline=timeline)
    before = replay.before_action("split-1")
    assert before.object("relationship").visible is False
    assert before.object("relationship").state == ("removed" if kind == "annotation" else "disconnected")
    assert dict(before.state_versions)["relationship"] == (3 if kind in {"annotation", "connected"} else 2)
    for at in (1499, 500, 1500, 400, 1000, 1999):
        sample = replay.at(at)
        assert sample.object("relationship") == before.object("relationship")
        assert dict(sample.state_versions)["relationship"] == dict(before.state_versions)["relationship"]
    assert replay.at(1500).object("source").state == "removed"
    assert (layout.model_dump_json(), repr(initial), timeline.model_dump_json()) == original


@pytest.mark.parametrize("later_connection", ["first", "reconnect"])
@pytest.mark.parametrize("start", [1500, 1600])
@pytest.mark.parametrize("portrait", [False, True])
def test_retained_handoff_allows_future_connections_after_split(later_connection, start, portrait):
    layout, initial, timeline = retained_handoff_documents("connected", later_connection=later_connection,
                                                          connection_start=start, portrait=portrait)
    replay = _replay_split_chronology(layout, initial, tuple(timeline.actions), timeline.duration_ms, {},
                                      timeline=timeline)
    assert replay.at(1499).object("later-pointer").state == "disconnected"
    assert replay.at(start + 100).object("later-pointer").state == "connected"
    assert replay.at(1499).object("relationship").state == "disconnected"


@pytest.mark.parametrize("fault", [None, "in_flight", "re_add"])
@pytest.mark.parametrize("portrait", [False, True])
def test_retained_annotation_handoff_uses_final_owned_note_removal(fault, portrait):
    if fault is not None:
        with pytest.raises(ValueError, match="Split|split|reservation|annotation|resurrect"):
            layout, initial, timeline = retained_handoff_documents("annotation", multi_note=True, fault=fault, portrait=portrait)
            _replay_split_chronology(layout, initial, tuple(timeline.actions), timeline.duration_ms, {}, timeline=timeline)
        return
    layout, initial, timeline = retained_handoff_documents("annotation", multi_note=True, portrait=portrait)
    replay = _replay_split_chronology(layout, initial, tuple(timeline.actions), timeline.duration_ms, {}, timeline=timeline)
    assert replay.at(350).object("relationship").state == "removed"
    assert replay.at(350).object("second-note").visible
    for key in ("relationship", "second-note"):
        for at in (400, 500, 1499, 1500):
            assert replay.at(at).object(key).state == "removed"
            assert replay.at(at).object(key).visible is False
            assert dict(replay.at(at).state_versions)[key] == 3


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("fault", [None, "active", "in_flight"])
def test_retained_annotation_pointer_requires_every_owned_leaf_removed(portrait, fault):
    if fault is not None:
        with pytest.raises(ValueError, match="Split|split|reservation|annotation"):
            layout, initial, timeline = retained_handoff_documents("annotation", with_leader=True,
                                                                   fault=fault, portrait=portrait)
            _replay_split_chronology(layout, initial, tuple(timeline.actions), timeline.duration_ms, {}, timeline=timeline)
        return
    layout, initial, timeline = retained_handoff_documents("annotation", with_leader=True, portrait=portrait)
    replay = _replay_split_chronology(layout, initial, tuple(timeline.actions), timeline.duration_ms, {}, timeline=timeline)
    assert replay.at(350).object("note-leader").visible
    for key in ("relationship", "note-leader"):
        assert replay.at(400).object(key).state == "removed"
        assert replay.at(1500).object(key) == replay.at(400).object(key)


@pytest.mark.parametrize("kind,fault", [
    ("initial", "active"), ("connected", "active"), ("pointer", "active"), ("annotation", "active"),
    ("connected", "same_time"), ("annotation", "same_time"),
    ("connected", "in_flight"), ("annotation", "in_flight"),
    ("connected", "writer"), ("annotation", "writer"),
    ("annotation", "hold_overlap"), ("annotation", "re_add"),
])
def test_retained_handoff_rejects_unterminated_or_changed_relationships(kind, fault):
    # Strict timeline resurrection checks may reject before replay is reached.
    with pytest.raises(ValueError, match="Split|split|reservation|hold|termination|annotation|connector|resurrect"):
        layout, initial, timeline = retained_handoff_documents(kind, fault=fault)
        _replay_split_chronology(layout, initial, tuple(timeline.actions), timeline.duration_ms, {}, timeline=timeline)


@pytest.mark.parametrize("later_connection", ["first", "reconnect"])
@pytest.mark.parametrize("start", [450, 1400, 1499])
def test_retained_handoff_rejects_connect_or_reconnect_before_split_end(later_connection, start):
    layout, initial, timeline = retained_handoff_documents("connected", later_connection=later_connection,
                                                          connection_start=start)
    with pytest.raises(ValueError, match="Split|split|reservation|connect"):
        _replay_split_chronology(layout, initial, tuple(timeline.actions), timeline.duration_ms, {}, timeline=timeline)


@pytest.mark.parametrize("fault", ["layout_hash", "initial_version"])
def test_split_lifecycle_observer_authenticates_paired_timeline_authority(fault):
    from atme.render.v2_lifecycle import validate_split_lifecycle

    layout, initial, timeline = retained_handoff_documents("connected")
    replay = _replay_split_chronology(layout, initial, tuple(timeline.actions), timeline.duration_ms, {}, timeline=timeline)
    capture = next(row.split_capture for checkpoint in replay.checkpoints for row in checkpoint.active
                   if hasattr(row, "split_capture"))
    raw = timeline.model_dump(mode="json")
    if fault == "layout_hash":
        raw["layout_sha256"] = "0" * 64
    else:
        next(row for row in raw["initial_object_states"] if row["object_id"] == "source")["state_version"] = 2
    changed = ResolvedVisualTimelineV2.model_validate(raw)
    with pytest.raises(ValueError, match="composition|initial|version|replay|timeline"):
        validate_split_lifecycle(capture, replay, layout, changed)


@pytest.mark.parametrize("fault", ["untyped", "duration", "actions", "initial_version", "unknown_payload"])
def test_retained_handoff_rejects_partial_or_changed_typed_context(fault):
    layout, initial, timeline = retained_handoff_documents("connected")
    actions, duration = tuple(timeline.actions), timeline.duration_ms
    if fault == "untyped":
        timeline = timeline.model_dump(mode="json")
    elif fault == "duration":
        duration -= 1
    elif fault == "actions":
        actions = actions[1:]
    elif fault == "initial_version":
        initial = replace(initial, state_versions=tuple((key, value + (key == "peer-target"))
                                                       for key, value in initial.state_versions))
    else:
        timeline.__dict__["untrusted_payload"] = {"ignore": "me"}
    with pytest.raises(ValueError):
        _replay_split_chronology(layout, initial, actions, duration, {}, timeline=timeline)


def test_split_lifecycle_observer_cannot_accept_a_copied_capture_or_partial_replay():
    from atme.render.v2_lifecycle import validate_split_lifecycle

    layout, initial, timeline = retained_handoff_documents("connected")
    replay = _replay_split_chronology(layout, initial, tuple(timeline.actions), timeline.duration_ms, {}, timeline=timeline)
    capture = next(row.split_capture for checkpoint in replay.checkpoints for row in checkpoint.active
                   if hasattr(row, "split_capture"))
    for candidate, history in ((replace(capture), replay), (capture, replace(replay, checkpoints=replay.checkpoints[-1:]))):
        with pytest.raises(ValueError, match="initial|version|actual replay|capture"):
            validate_split_lifecycle(candidate, history, layout, timeline)


@pytest.mark.parametrize("narrow_camera", [False, True])
def test_typed_retained_route_enforces_actual_evidence_readability(shared_boundary, narrow_camera):
    from test_v2_camera_action import append_camera

    layout, before, timeline = shared_context_documents(shared_boundary)
    if narrow_camera:
        clock = timeline.model_dump(mode="json")
        append_camera(clock, "camera-before-split", "camera_cut", 500, 600,
                      target="annotation-target", framing="detail")
        timeline = ResolvedVisualTimelineV2.model_validate(clock)

    def replay():
        return _replay_split_chronology(layout, replace(before, at_ms=0), tuple(timeline.actions),
                                        timeline.duration_ms, shared_boundary[3], timeline=timeline)

    if narrow_camera:
        with pytest.raises(ValueError, match="not fully readable"):
            replay()
    else:
        replay()


def readable_evidence_split_documents(tmp_path, portrait, *, annotated=False):
    from atme.project_assets import read_verified_split_asset_bytes
    from atme.render.v2_split import _observed_split_placements
    from atme.render.v2_split_identity import split_content_receipts
    from atme.store.contracts_v2 import SplitPolicy, _split_expected_completion

    service, original, original_clock, original_carrier = ordinary_shared_evidence(tmp_path, portrait)
    layout, _, split = geometry_boundary()
    raw = layout.model_dump(mode="json")
    raw.update(project_id=original.project_id, output_profile=original.output_profile.model_dump(mode="json"),
               canvas=original.canvas.model_dump(mode="json"))
    raw["activations"][0]["end_ms"] = 5000
    treatments = []
    for key, original_treatment in zip(("part-1", "part-2"), original.evidence_treatments, strict=True):
        index = next(index for index, row in enumerate(raw["objects"]) if row["object_id"] == key)
        old = raw["objects"][index]
        card = next(row for row in original.objects if row.object_id == original_treatment.object_id).model_dump(mode="json")
        for field in ("object_id", "board_id", "beat_id", "coverage_ids", "z_index", "initial_state", "visible",
                      "parent_id", "clip_id", "transform", "anchors"):
            card[field] = deepcopy(old[field])
        raw["objects"][index] = card
        treatment = original_treatment.model_dump(mode="json")
        treatment.update(object_id=key, action_id="split-1", beat_id=card["beat_id"])
        treatments.append(treatment)
    if annotated:
        from test_v2_evidence_annotation_contract import authored_evidence_annotation
        from test_v2_evidence_annotation_objects import cross_annotation_documents

        target = deepcopy(next(obj for obj in raw["objects"] if obj["object_id"] == "source"))
        target.update(object_id="annotation-target", z_index=3)
        target["geometry"]["bounds"] = {"x": 40, "y": 1200 if portrait else 610, "width": 200, "height": 40}
        target["anchors"] = [{"anchor_id": "center", "point": {"x": 0.5, "y": 0.5}}]
        raw["objects"].append(target)
        for index, (key, treatment) in enumerate(zip(("part-1", "part-2"), treatments, strict=True)):
            card = next(obj for obj in raw["objects"] if obj["object_id"] == key)
            card["anchors"] = deepcopy(target["anchors"])
            note, leader = deepcopy(cross_annotation_documents()[1]["objects"][-2:])
            note_id, leader_id = f"note-{key}", f"leader-{key}"
            text = "First mechanism" if index == 0 else "Second mechanism"
            for ordinal, obj in enumerate((note, leader), 4 + 2 * index):
                obj.update(board_id=card["board_id"], beat_id=card["beat_id"],
                           coverage_ids=deepcopy(card["coverage_ids"]), z_index=ordinal)
            note.update(object_id=note_id, text=text)
            note["geometry"]["bounds"] = {"x": 120 if portrait else 130 + 600 * index,
                "y": (520 + 600 * index) if portrait else 560, "width": 420, "height": 60}
            leader.update(object_id=leader_id, source_object_id=key, destination_object_id="annotation-target")
            leader["geometry"]["bounds"] = deepcopy(raw["canvas"])
            raw["objects"].extend((note, leader))
            annotation = authored_evidence_annotation()
            annotation.update(annotation_object_ids=[note_id], leader_connector_id=leader_id)
            for phase, object_id in zip(annotation["phases"], (note_id, leader_id), strict=True):
                phase["object_id"] = object_id
            treatment["intent"].update(annotation=text, annotation_omission_reason=None,
                annotation_target_id="annotation-target", annotation_policy=annotation)
        raw["boards"][0]["object_ids"] = [obj["object_id"] for obj in raw["objects"]]
    raw["evidence_treatments"] = treatments
    layout = ExecutableLayoutV2.model_validate(raw)
    pin = json.loads(original_carrier.rows[0].pin_json)
    carrier = read_verified_split_asset_bytes(service, layout, original_clock.resolved_assets, [pin])
    before = replace(sample_for_layout(layout), at_ms=1000)
    contents = {row.object_id: row for row in split_content_receipts(layout, before, carrier)}
    raw = split.model_dump(mode="json")
    raw.update(start_ms=1000, end_ms=2000)
    policy = raw["action"]["split_policy"]
    for index, result in enumerate(policy["results"]):
        result.update(post_state="evidence_visible", evidence_activation={
            "result_object_id": result["object_id"], "beat_id": treatments[index]["beat_id"],
            "causal_action_id": "split-1", "intent": deepcopy(treatments[index]["intent"]), "asset_pin": pin,
            "permission_sha256": digest(original_clock.resolved_assets[0].allowed_transformations),
            "allowed_transformations": original_clock.resolved_assets[0].allowed_transformations.copy()})
        result["construction"]["phase"]["end_tick"] = 6000 if index == 0 else 5000
        result["movement"] = {"phase": {"start_tick": 0, "end_tick": 4000 if index == 0 else 9000,
                                          "easing": "linear"},
            "from_transform": deepcopy(result["destination"]), "destination": deepcopy(result["destination"])}
        result["movement"]["destination"]["position"]["x"] = 20.0
        result["destination"]["position"]["x"] = 20.0
    basis = policy["source_basis"]
    basis.update(asset_pins=[pin], placements=[row.model_dump(mode="json") for row in
        _observed_split_placements(before, {row.object_id: row for row in layout.objects},
                                   {row.object_id for row in layout.objects}, contents)])
    if annotated:
        basis["read_dependencies"] = [
            {"kind": "connector_anchor", "object_ids": ["annotation-target", "leader-part-1", "leader-part-2",
                                                        "part-1", "part-2"]},
            {"kind": "annotation_anchor", "object_ids": ["annotation-target", "leader-part-1", "leader-part-2",
                                                         "note-part-1", "note-part-2"]}]
    for row in policy["correspondences"]:
        row.update(source_content_sha256=contents["source"].content_sha256,
                   result_content_sha256=contents[row["result_object_id"]].content_sha256)
    policy["source_basis_sha256"] = digest(basis)
    policy = SplitPolicy.model_validate(policy)
    raw["action"]["split_policy"] = policy.model_dump(mode="json")
    windows = [{"result_object_id": key, "treatment_sha256": digest(treatment.model_dump(mode="json")),
        "construction_complete_ms": construction, "movement_complete_ms": movement,
        "readable_hold_start_ms": hold, "readable_hold_end_ms": end}
        for treatment, (key, construction, movement, hold, end) in zip(layout.evidence_treatments,
            [("part-1", 1600, 1400, 1600, 4100), ("part-2", 1500, 1900, 1900, 4400)], strict=True)]
    receipt = _split_expected_completion(policy)
    receipt["evidence_windows"] = deepcopy(windows)
    receipt["completion_sha256"] = digest(receipt)
    raw.update(split_completion_receipt=receipt, split_evidence_windows=windows)
    action = ResolvedAction.model_validate(raw)
    _, _, clock = split_documents("SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9")
    clock.update(project_id=layout.project_id, plan_sha256=layout.plan_sha256,
        layout_sha256=digest(layout.model_dump(mode="json")), duration_ms=5000,
        resolved_assets=[row.model_dump(mode="json") for row in original_clock.resolved_assets],
        evidence_treatments=[row.model_dump(mode="json") for row in layout.evidence_treatments],
        actions=[action.model_dump(mode="json")])
    clock["initial_object_states"] = [{"object_id": row.object_id, "state": row.initial_state,
        "state_version": 1, "visible": row.visible} for row in layout.objects]
    return service, layout, replace(before, at_ms=0), ResolvedVisualTimelineV2.model_validate(clock), carrier


def source_evidence_handoff_documents(tmp_path, portrait, split_start, *, distinct_source=False,
                                      pointer_removal_end=None):
    from atme.project_assets import read_verified_split_asset_bytes
    from atme.render.v2_split import _observed_split_placements
    from atme.render.v2_split_identity import split_content_receipts
    from atme.store.contracts_v2 import SplitPolicy, _split_expected_completion
    from v2_fixtures import resolved_timeline_v2

    service, layout, _, timeline, carrier = readable_evidence_split_documents(tmp_path, portrait)
    raw = layout.model_dump(mode="json")
    old_source = next(obj for obj in raw["objects"] if obj["object_id"] == "source")
    source = deepcopy(next(obj for obj in raw["objects"] if obj["object_id"] == "part-1"))
    for key in ("object_id", "board_id", "beat_id", "coverage_ids", "z_index", "parent_id", "clip_id", "transform"):
        source[key] = deepcopy(old_source[key])
    source.update(initial_state="hidden", visible=False)
    raw["objects"][raw["objects"].index(old_source)] = source
    prior_treatment = deepcopy(raw["evidence_treatments"][0])
    prior_treatment.update(object_id="source", action_id="source-insert", beat_id=source["beat_id"])
    prior_treatment["intent"].update(claim_id="prior-source-claim", source_label="Original source")
    if pointer_removal_end is not None:
        from test_v2_evidence_annotation_contract import authored_evidence_annotation
        from test_v2_evidence_annotation_objects import cross_annotation_documents

        target = deepcopy(old_source)
        target.update(object_id="source-pointer-target", z_index=3)
        target["geometry"]["bounds"] = {"x": 40, "y": 1200 if portrait else 610, "width": 200, "height": 40}
        source["anchors"] = target["anchors"] = [{"anchor_id": "center", "point": {"x": 0.5, "y": 0.5}}]
        note, leader = deepcopy(cross_annotation_documents()[1]["objects"][-2:])
        for ordinal, obj in enumerate((note, leader), 4):
            obj.update(board_id=source["board_id"], beat_id=source["beat_id"],
                       coverage_ids=deepcopy(source["coverage_ids"]), z_index=ordinal)
        note.update(object_id="source-note", text="Original mechanism")
        note["geometry"]["bounds"] = {"x": 120, "y": 520 if portrait else 560, "width": 420, "height": 60}
        leader.update(object_id="source-leader", source_object_id="source",
                      destination_object_id="source-pointer-target")
        leader["geometry"]["bounds"] = deepcopy(raw["canvas"])
        raw["objects"].extend((target, note, leader))
        raw["boards"][0]["object_ids"] = [obj["object_id"] for obj in raw["objects"]]
        annotation = authored_evidence_annotation()
        annotation.update(annotation_object_ids=["source-note"], leader_connector_id="source-leader")
        for phase, key in zip(annotation["phases"], ("source-note", "source-leader"), strict=True):
            phase["object_id"] = key
        prior_treatment["intent"].update(annotation="Original mechanism", annotation_omission_reason=None,
            annotation_target_id="source-pointer-target", annotation_policy=annotation)
    assets = list(timeline.resolved_assets)
    pins = [json.loads(row.pin_json) for row in carrier.rows]
    if distinct_source:
        import hashlib

        from PIL import Image

        external = tmp_path / "external-distinct-source.png"
        Image.new("RGBA", (900, 500), (40, 170, 210, 255)).save(external)
        provenance = deepcopy(prior_treatment["asset_provenance"])
        provenance.update(source_uri="https://example.com/distinct-original",
                          checksum_sha256=hashlib.sha256(external.read_bytes()).hexdigest())
        asset = service.attach_evidence_file(layout.project_id, external, external.name,
            service._row(layout.project_id)["revision"], provenance,
            prior_treatment["allowed_transformations"])["asset"]
        source["asset_id"] = asset["asset_id"]
        prior_treatment["intent"]["evidence_asset_id"] = asset["asset_id"]
        prior_treatment.update(asset_revision=asset["revision"], asset_checksum_sha256=asset["sha256"],
            asset_managed_ref=asset["resource_uri"], asset_provenance=asset["provenance"])
        resolved = assets[0].model_dump(mode="json")
        resolved.update(asset_id=asset["asset_id"], revision=asset["revision"], managed_ref=asset["resource_uri"],
                        checksum_sha256=asset["sha256"], byte_length=asset["bytes"])
        assets.append(ResolvedAsset.model_validate(resolved))
        pins.append({"asset_id": asset["asset_id"], "revision": asset["revision"],
                     "resource_uri": asset["resource_uri"], "checksum_sha256": asset["sha256"]})
    raw["evidence_treatments"].insert(0, prior_treatment)
    raw["activations"][0]["end_ms"] = split_start + 5000
    layout = ExecutableLayoutV2.model_validate(raw)
    carrier = read_verified_split_asset_bytes(service, layout, assets, pins)
    prior = deepcopy(resolved_timeline_v2()["actions"][2])
    action = prior["action"]
    trigger = {"kind": "absolute", "at_ms": 0}
    action.update(action_id="source-insert", source_instruction_id="instruction-1", coverage_id="coverage-1",
                  target_object_id="source", evidence_asset_id=source["asset_id"], trigger=trigger,
                  fallback={"fallback_id": "fallback-1", "on_failure": "block"})
    prior.update(start_ms=0, end_ms=100, resolved_trigger={"source": trigger, "alignment_anchor_ms": 0,
        "resolved_at_ms": 0, "matched_text": None, "matched_occurrence": None, "confidence": 1, "exact": True})
    prior = ResolvedAction.model_validate(prior)
    prior_actions = [prior]
    if pointer_removal_end:
        from test_v2_timeline_replay import resolved as timed

        exit_action = peer_action("reveal", target_ids=["source-leader"]).action.model_dump(mode="json")
        exit_action.update(action_id="remove-source-pointer", verb="exit", expected_state="visible", post_state="removed")
        prior_actions.append(timed(exit_action, pointer_removal_end - 100, pointer_removal_end))
    initial = sample_for_layout(layout)
    # This is the actual ordinary scheduler prefix, not a fabricated source state.
    prefix = _replay_split_chronology(layout, initial, tuple(prior_actions), split_start + 5000, carrier)
    before = prefix.at(split_start)
    assert before.object("source").state == "evidence_visible"
    raw_action = timeline.actions[0].model_dump(mode="json")
    trigger = {"kind": "absolute", "at_ms": split_start}
    raw_action["action"].update(expected_state="evidence_visible", trigger=trigger)
    raw_action.update(start_ms=split_start, end_ms=split_start + 1000,
        resolved_trigger={"source": trigger, "alignment_anchor_ms": split_start, "resolved_at_ms": split_start,
            "matched_text": None, "matched_occurrence": None, "confidence": 1, "exact": True})
    policy = raw_action["action"]["split_policy"]
    policy["source_basis"]["asset_pins"] = sorted(pins, key=lambda row: row["asset_id"])
    bound = {"source", "part-1", "part-2"}
    if pointer_removal_end is not None:
        dependencies = ["source", "source-leader", "source-pointer-target"]
        policy["source_basis"]["read_dependencies"] = [{"kind": "connector_anchor", "object_ids": dependencies}]
        bound.update(dependencies)
    contents = {row.object_id: row for row in split_content_receipts(layout, before, carrier)}
    policy["source_basis"]["placements"] = [row.model_dump(mode="json") for row in _observed_split_placements(
        before, {obj.object_id: obj for obj in layout.objects}, bound, contents)]
    for row in policy["correspondences"]:
        row.update(source_content_sha256=contents["source"].content_sha256,
                   result_content_sha256=contents[row["result_object_id"]].content_sha256)
    policy["source_basis_sha256"] = digest(policy["source_basis"])
    policy = SplitPolicy.model_validate(policy)
    raw_action["action"]["split_policy"] = policy.model_dump(mode="json")
    windows = deepcopy(raw_action["split_evidence_windows"])
    for row in windows:
        for key in ("construction_complete_ms", "movement_complete_ms", "readable_hold_start_ms", "readable_hold_end_ms"):
            row[key] += split_start - 1000
    receipt = _split_expected_completion(policy)
    receipt["evidence_windows"] = windows
    receipt["completion_sha256"] = digest(receipt)
    raw_action.update(split_completion_receipt=receipt, split_evidence_windows=windows)
    clock = timeline.model_dump(mode="json")
    clock.update(layout_sha256=digest(layout.model_dump(mode="json")), duration_ms=split_start + 5000,
        actions=[*[row.model_dump(mode="json") for row in prior_actions], raw_action],
        resolved_assets=[row.model_dump(mode="json") for row in assets],
        evidence_treatments=[row.model_dump(mode="json") for row in layout.evidence_treatments],
        initial_object_states=[{"object_id": obj.object_id, "state": obj.initial_state,
            "state_version": 1, "visible": obj.visible} for obj in layout.objects])
    clock["coverage"][0]["action_ids"] = [*[row.action.action_id for row in prior_actions], "split-1"]
    return service, layout, initial, ResolvedVisualTimelineV2.model_validate(clock), carrier


@pytest.mark.parametrize("portrait", [False, True])
def test_completed_source_evidence_hold_hands_off_through_actual_typed_replay(tmp_path, portrait):
    service, layout, initial, timeline, carrier = source_evidence_handoff_documents(tmp_path, portrait, 4000)
    original = (tmp_path / "external-original.png").read_bytes(), dict(service._row(layout.project_id))
    replay = _replay_split_chronology(layout, initial, tuple(timeline.actions), timeline.duration_ms, carrier,
                                      timeline=timeline)
    assert replay.at(3999).object("source").state == "evidence_visible"
    assert replay.at(5000).object("source").state == "removed"
    assert replay.at(4600).object("part-1").reveal_fraction == 1
    assert original == ((tmp_path / "external-original.png").read_bytes(), dict(service._row(layout.project_id)))


@pytest.mark.parametrize("portrait", [False, True])
def test_active_source_evidence_hold_cannot_be_shortened_by_split(tmp_path, portrait):
    _, layout, initial, timeline, carrier = source_evidence_handoff_documents(tmp_path, portrait, 2000)
    # Actual ordinary source completes at100 and must remain readable until2600.
    with pytest.raises(ValueError, match="[Ss]ource.*hold|evidence.*hold"):
        _replay_split_chronology(layout, initial, tuple(timeline.actions), timeline.duration_ms, carrier,
                                  timeline=timeline)


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("distinct_source", [False, True])
def test_actual_source_evidence_uses_its_ordinary_native_treatment_and_frozen_seek(
        tmp_path, monkeypatch, portrait, distinct_source):
    import io
    import socket
    from pathlib import Path

    from atme.render.v2_camera import camera_segments
    from atme.render.v2_split_paint import verify_split_paint_inputs
    from atme.render.v2_state import _sample_validated_frame
    from atme.render.v2_svg import _compose_validated_svg_frame, _rasterize_svg_frame
    from PIL import Image

    service, layout, initial, timeline, carrier = source_evidence_handoff_documents(
        tmp_path, portrait, 4000, distinct_source=distinct_source)
    originals = {path: path.read_bytes() for path in tmp_path.glob("external-*.png")}
    project = dict(service._row(layout.project_id))
    replay = _replay_split_chronology(layout, initial, tuple(timeline.actions), timeline.duration_ms, carrier,
                                      timeline=timeline)
    inputs = verify_split_paint_inputs(layout, carrier)
    cameras = camera_segments(layout, timeline, replay, split_inputs=inputs)

    def render(at):
        frame = _sample_validated_frame(layout, timeline, replay, cameras, at)
        svg = _compose_validated_svg_frame(layout, timeline, frame, {}, None, split_inputs=inputs)
        return svg.svg, _rasterize_svg_frame(layout, svg, split_inputs=inputs).png

    expected = {at: render(at) for at in (3999, 4300, 5000)}
    assert "Original source" in expected[3999][0] and "First view" not in expected[3999][0]
    assert all(text in expected[4300][0] for text in ("Original source", "First view", "Second view"))
    assert "Original source" not in expected[5000][0]
    assert all(text in expected[5000][0] for text in ("First view", "Second view"))
    assert len({png for _, png in expected.values()}) == 3
    with Image.open(io.BytesIO(expected[3999][1])) as source, Image.open(io.BytesIO(expected[5000][1])) as result:
        assert source.convert("RGB").getpixel((350, 240) if portrait else (930, 300)) == (
            (40, 170, 210) if distinct_source else (235, 30, 40))
        assert result.convert("RGB").getpixel((370, 240) if portrait else (950, 300)) == (235, 30, 40)
        assert result.convert("RGB").getpixel((370, 840) if portrait else (370, 300)) == (25, 185, 50)
    def denied(*_args, **_kwargs):
        pytest.fail("frozen source handoff reopened source resources or used the network")
    original_open = Path.open
    def only_temporary_fonts(path, *args, **kwargs):
        assert any(part.startswith("atme-split-fonts-") for part in path.parts), "reopened source resource"
        return original_open(path, *args, **kwargs)
    with monkeypatch.context() as sealed:
        sealed.setattr(Path, "read_bytes", denied)
        sealed.setattr(Path, "read_text", denied)
        sealed.setattr(Path, "open", only_temporary_fonts)
        sealed.setattr(socket, "create_connection", denied)
        sealed.setattr(socket.socket, "connect", denied)
        for at in (5000, 3999, 4300, 5000):
            assert render(at) == expected[at]
    assert originals == {path: path.read_bytes() for path in originals}
    assert project == dict(service._row(layout.project_id))
    (tmp_path / f"source-evidence-native-{portrait}.png").write_bytes(expected[4300][1])


@pytest.mark.parametrize("fault", ["missing", "wrong-owner"])
def test_source_evidence_native_cannot_borrow_a_split_result_treatment(tmp_path, fault):
    from atme.render.v2_camera import camera_segments
    from atme.render.v2_split_paint import (
        _split_active_paint_modes,
        verify_split_paint_inputs,
    )
    from atme.render.v2_state import _sample_validated_frame
    from atme.store.contracts_v2 import EvidenceTreatment

    _, layout, initial, timeline, carrier = source_evidence_handoff_documents(tmp_path, False, 4000)
    replay = _replay_split_chronology(layout, initial, tuple(timeline.actions), timeline.duration_ms, carrier,
                                      timeline=timeline)
    inputs = verify_split_paint_inputs(layout, carrier)
    snapshot = _sample_validated_frame(layout, timeline, replay,
        camera_segments(layout, timeline, replay, split_inputs=inputs), 4300)
    treatments = list(timeline.evidence_treatments)
    if fault == "missing":
        treatments.pop(0)
    else:
        changed = treatments[0].model_dump(mode="json")
        changed["action_id"] = "split-1"
        treatments[0] = EvidenceTreatment.model_validate(changed)
    candidate = timeline.model_copy(update={"evidence_treatments": treatments})
    with pytest.raises(ValueError, match="source evidence needs its exact ordinary owner"):
        _split_active_paint_modes(snapshot, candidate, {obj.object_id: obj for obj in layout.objects})


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("removal_end", [3500, 0, 4050, 2550])
def test_real_source_evidence_pointer_handoff_requires_completed_post_hold_removal(tmp_path, portrait, removal_end):
    service, layout, initial, timeline, carrier = source_evidence_handoff_documents(
        tmp_path, portrait, 4000, pointer_removal_end=removal_end)
    original = (tmp_path / "external-original.png").read_bytes(), dict(service._row(layout.project_id))
    if removal_end == 3500:
        replay = _replay_split_chronology(layout, initial, tuple(timeline.actions), timeline.duration_ms, carrier,
                                          timeline=timeline)
        assert replay.before_action("split-1").object("source-leader").state == "removed"
        assert not replay.at(5000).object("source-leader").visible
        assert replay.at(5000).object("source").state == "removed"
    else:
        with pytest.raises(ValueError, match="pointer|hold|reservation|overlap"):
            _replay_split_chronology(layout, initial, tuple(timeline.actions), timeline.duration_ms, carrier,
                                      timeline=timeline)
    assert original == ((tmp_path / "external-original.png").read_bytes(), dict(service._row(layout.project_id)))


def test_typed_reading_cannot_succeed_without_native_construction_preflight(tmp_path):
    from atme.store.contracts_v2 import SplitPolicy, _split_expected_completion

    _, layout, initial, timeline, carrier = readable_evidence_split_documents(tmp_path, False)
    clock = timeline.model_dump(mode="json")
    item = clock["actions"][0]
    item["action"]["split_policy"]["results"][0]["construction"]["mode"] = "draw"
    receipt = _split_expected_completion(SplitPolicy.model_validate(item["action"]["split_policy"]))
    receipt["evidence_windows"] = deepcopy(item["split_evidence_windows"])
    receipt["completion_sha256"] = digest(receipt)
    item["split_completion_receipt"] = receipt
    timeline = ResolvedVisualTimelineV2.model_validate(clock)
    with pytest.raises(ValueError, match="Split native evidence|construction"):
        _replay_split_chronology(layout, initial, tuple(timeline.actions), timeline.duration_ms, carrier,
                                  timeline=timeline)


def test_unrelated_board_evidence_keeps_non_evidence_split_four_argument_lifecycle(tmp_path, monkeypatch):
    from atme.project_assets import read_verified_split_asset_bytes
    from atme.render import v2_split_paint
    from atme.render.v2_lifecycle import validate_split_lifecycle
    from atme.render.v2_split import _observed_split_placements
    from atme.render.v2_split_identity import split_content_receipts
    from atme.store.contracts_v2 import SplitPolicy, _split_expected_completion
    from test_v2_timeline_replay import resolved

    service, raw_layout, clock, _ = evidence_documents(tmp_path, annotation=None)
    geometry, _, split = geometry_boundary()
    parts = geometry.model_dump(mode="json")
    for obj in parts["objects"]:
        obj.update(board_id="geometry-board", beat_id="geometry-beat", coverage_ids=["geometry-coverage"])
    board = deepcopy(parts["boards"][0])
    board["board_id"] = "geometry-board"
    raw_layout["objects"].extend(parts["objects"])
    raw_layout["boards"].append(board)
    raw_layout["activations"][0]["end_ms"] = 8000
    raw_layout["activations"].append({"activation_id": "geometry-activation", "board_id": "geometry-board",
        "start_ms": 8000, "end_ms": 12000, "reason": "Inspect an unrelated authored geometry model"})
    layout = ExecutableLayoutV2.model_validate(raw_layout)
    asset = clock["resolved_assets"][0]
    pin = {"asset_id": asset["asset_id"], "revision": asset["revision"], "resource_uri": asset["managed_ref"],
           "checksum_sha256": asset["checksum_sha256"]}
    carrier = read_verified_split_asset_bytes(service, layout, [ResolvedAsset.model_validate(asset)], [pin])
    initial = sample_for_layout(layout)
    prefix = _replay_split_chronology(layout, initial, tuple(ResolvedAction.model_validate(row) for row in clock["actions"]),
                                      12000, carrier)
    before = prefix.at(9000)
    action = split.action.model_dump(mode="json")
    action.update(board_id="geometry-board", source_instruction_id="geometry-instruction",
        coverage_id="geometry-coverage", trigger={"kind": "absolute", "at_ms": 9000},
        fallback={"fallback_id": "geometry-fallback", "on_failure": "block"})
    policy = action["split_policy"]
    contents = {row.object_id: row for row in split_content_receipts(layout, before, carrier)}
    policy["source_basis"]["placements"] = [row.model_dump(mode="json") for row in _observed_split_placements(
        before, {obj.object_id: obj for obj in layout.objects}, {"source", "part-1", "part-2"}, contents)]
    for row in policy["correspondences"]:
        row.update(source_content_sha256=contents["source"].content_sha256,
                   result_content_sha256=contents[row["result_object_id"]].content_sha256)
    policy["source_basis_sha256"] = digest(policy["source_basis"])
    policy = SplitPolicy.model_validate(policy)
    action["split_policy"] = policy.model_dump(mode="json")
    item = resolved(action, 9000, 10000).model_dump(mode="json")
    receipt = _split_expected_completion(policy)
    receipt["completion_sha256"] = digest(receipt)
    item["split_completion_receipt"] = receipt
    clock["actions"].append(item)
    clock["coverage"].append({"coverage_id": "geometry-coverage", "instruction_id": "geometry-instruction",
                             "status": "executed", "action_ids": ["split-1"], "fallback_id": None})
    fallback = deepcopy(clock["fallbacks"][0])
    fallback.update(fallback_id="geometry-fallback", affected_ids=["geometry-instruction"])
    clock["fallbacks"].append(fallback)
    clock.update(layout_sha256=digest(layout.model_dump(mode="json")), duration_ms=12000,
        initial_object_states=[{"object_id": obj.object_id, "state": obj.initial_state,
            "state_version": 1, "visible": obj.visible} for obj in layout.objects])
    clock["beat_anchors"].append({"beat_id": "geometry-beat", "start_ms": 9000})
    timeline = ResolvedVisualTimelineV2.model_validate(clock)
    replay = _replay_split_chronology(layout, initial, tuple(timeline.actions), timeline.duration_ms, carrier)
    capture = next(row.split_capture for checkpoint in replay.checkpoints for row in checkpoint.active
                   if row.resolved.action.action_id == "split-1")
    validate_split_lifecycle(capture, replay, layout, timeline)
    def unrelated_inputs(*_args, **_kwargs):
        pytest.fail("unrelated-board evidence must not force frozen Split inputs")
    monkeypatch.setattr(v2_split_paint, "verify_split_paint_inputs", unrelated_inputs)
    typed = _replay_split_chronology(layout, initial, tuple(timeline.actions), timeline.duration_ms, carrier,
                                     timeline=timeline)
    assert typed.at(10000) == replay.at(10000)


def test_actual_typed_handoff_builds_once_and_threads_the_same_frozen_inputs(tmp_path, monkeypatch):
    from atme.render import v2_lifecycle, v2_split_paint

    _, layout, initial, timeline, carrier = source_evidence_handoff_documents(tmp_path, False, 4000)
    build, observe = v2_split_paint.verify_split_paint_inputs, v2_lifecycle.validate_split_lifecycle
    built, seen = [], []
    def freeze(*args, **kwargs):
        value = build(*args, **kwargs)
        built.append(value)
        return value
    def validate(*args, **kwargs):
        seen.append(kwargs["split_inputs"])
        return observe(*args, **kwargs)
    monkeypatch.setattr(v2_split_paint, "verify_split_paint_inputs", freeze)
    monkeypatch.setattr(v2_lifecycle, "validate_split_lifecycle", validate)
    replay = _replay_split_chronology(layout, initial, tuple(timeline.actions), timeline.duration_ms, carrier,
                                      timeline=timeline)
    assert replay.at(5000).object("source").state == "removed"
    assert len(built) == len(seen) == 1 and built[0] is seen[0]


def canonical_evidence_split_documents(tmp_path, portrait, source_handoff):
    from atme.store.contracts_v2 import (
        SemanticStandardObjectSpec,
        VisualPlanV2,
        validate_plan_layout,
        validate_resolved_structure,
    )
    from v2_fixtures import visual_plan_v2

    if source_handoff:
        service, layout, initial, timeline, carrier = source_evidence_handoff_documents(
            tmp_path, portrait, 4000, distinct_source=True, pointer_removal_end=3500)
    else:
        service, layout, initial, timeline, carrier = readable_evidence_split_documents(tmp_path, portrait, annotated=True)
    plan, _, _ = split_documents("SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9")
    clock = timeline.model_dump(mode="json")
    for item in clock["actions"]:
        trigger = {"kind": "absolute", "at_ms": item["start_ms"]}
        item["action"]["trigger"] = trigger
        item["resolved_trigger"] = {"source": trigger, "alignment_anchor_ms": item["start_ms"],
            "resolved_at_ms": item["start_ms"], "matched_text": None, "matched_occurrence": None,
            "confidence": 1, "exact": True}
    assets = []
    for row in carrier.rows:
        resolved = json.loads(row.resolved_json)
        treatment = next(value for value in layout.evidence_treatments
                         if value.intent.evidence_asset_id == row.asset_id)
        asset = deepcopy(visual_plan_v2()["assets"][0])
        asset.update({key: deepcopy(resolved[key]) for key in (
            "asset_id", "kind", "revision", "managed_ref", "checksum_sha256", "width", "height",
            "allowed_transformations")})
        asset.update(provenance=treatment.asset_provenance.model_dump(mode="json"), fallback_id="fallback-1")
        assets.append(asset)
    plan.update(project_id=layout.project_id, project_revision=layout.project_revision,
        plan_id=layout.plan_id, assets=assets, boards=[row.model_dump(mode="json") for row in layout.boards],
        objects=[{key: deepcopy(value) for key, value in obj.model_dump(mode="json").items()
                  if key in SemanticStandardObjectSpec.model_fields} for obj in layout.objects],
        actions=[deepcopy(row["action"]) for row in clock["actions"]],
        coverage=deepcopy(clock["coverage"]), fallbacks=deepcopy(clock["fallbacks"]))
    beat = plan["beats"][0]
    beat.update(object_ids=[row["object_id"] for row in plan["objects"]],
                action_ids=[row["action_id"] for row in plan["actions"]])
    if source_handoff:
        beat["evidence"] = layout.evidence_treatments[0].intent.model_dump(mode="json")
    semantic = VisualPlanV2.model_validate(plan)
    raw = layout.model_dump(mode="json")
    raw["plan_sha256"] = digest(semantic.model_dump(mode="json"))
    layout = ExecutableLayoutV2.model_validate(raw)
    clock.update(plan_sha256=raw["plan_sha256"], layout_sha256=digest(layout.model_dump(mode="json")))
    timeline = ResolvedVisualTimelineV2.model_validate(clock)
    validate_plan_layout(semantic.model_dump(mode="json"), layout.model_dump(mode="json"))
    validate_resolved_structure(semantic, layout, timeline, timeline.duration_ms)
    return service, semantic, layout, timeline, initial, carrier


@pytest.fixture(scope="module", params=[(False, False), (True, False), (False, True), (True, True)])
def canonical_evidence_boundary(request, tmp_path_factory):
    portrait, source_handoff = request.param
    root = tmp_path_factory.mktemp(f"canonical-evidence-{portrait}-{source_handoff}")
    parts = canonical_evidence_split_documents(root, portrait, source_handoff)
    yield root, portrait, source_handoff, *parts
    parts[0].store.close()


def test_canonical_persisted_evidence_documents_reload_into_the_same_private_native_history(
        canonical_evidence_boundary, monkeypatch):
    import socket
    from pathlib import Path

    from atme.render.v2_camera import camera_segments
    from atme.render.v2_split_paint import verify_split_paint_inputs
    from atme.render.v2_state import _sample_validated_frame
    from atme.render.v2_svg import (
        _authored_annotation_bindings,
        _compose_validated_svg_frame,
        _rasterize_svg_frame,
    )

    tmp_path, portrait, source_handoff, service, semantic, layout, timeline, initial, carrier = canonical_evidence_boundary
    original = ({path: path.read_bytes() for path in tmp_path.glob("external-*.png")},
                dict(service._row(layout.project_id)), repr(carrier))
    def canonical(model):
        return json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    loaded = []
    for name, model in (("semantic", semantic), ("layout", layout), ("resolved", timeline)):
        payload = canonical(model)
        path = tmp_path / f"canonical-{name}.json"
        path.write_bytes(payload)
        restored = type(model).model_validate_json(path.read_bytes())
        assert canonical(restored) == payload
        assert digest(restored.model_dump(mode="json")) == digest(model.model_dump(mode="json"))
        loaded.append(restored)
    inputs = verify_split_paint_inputs(layout, carrier)
    def prepare(parts):
        _, drawing, clock = parts
        replay = _replay_split_chronology(drawing, initial, tuple(clock.actions), clock.duration_ms, carrier,
                                          timeline=clock)
        cameras = camera_segments(drawing, clock, replay, split_inputs=inputs)
        held = {key: _sample_validated_frame(drawing, clock, replay, cameras, end)
                for key, policy, _, end in _authored_annotation_bindings(clock)
                if policy.leader_connector_id is not None}
        return drawing, clock, replay, cameras, held
    def render(prepared):
        drawing, clock, replay, cameras, held = prepared
        end = clock.actions[-1].end_ms
        frame = _sample_validated_frame(drawing, clock, replay, cameras, end)
        svg = _compose_validated_svg_frame(drawing, clock, frame, held, None, split_inputs=inputs)
        return _rasterize_svg_frame(drawing, svg, split_inputs=inputs).png
    before = prepare((semantic, layout, timeline))
    after = prepare(loaded)
    expected = render(before)
    def denied(*_args, **_kwargs):
        pytest.fail("reloaded frozen evidence used the network or reopened a source resource")
    original_open = Path.open
    def only_temporary_fonts(path, *args, **kwargs):
        assert any(part.startswith("atme-split-fonts-") for part in path.parts), "reopened source resource"
        return original_open(path, *args, **kwargs)
    with monkeypatch.context() as sealed:
        sealed.setattr(Path, "read_bytes", denied)
        sealed.setattr(Path, "read_text", denied)
        sealed.setattr(Path, "open", only_temporary_fonts)
        sealed.setattr(socket, "create_connection", denied)
        sealed.setattr(socket.socket, "connect", denied)
        actual = render(after)
    assert after[2] == before[2] and actual == expected
    (tmp_path / f"canonical-evidence-{source_handoff}-{portrait}.png").write_bytes(actual)
    assert original == ({path: path.read_bytes() for path in original[0]},
                        dict(service._row(layout.project_id)), repr(carrier))


@pytest.mark.parametrize("fault", ["activation-missing", "activation-null", "activation-owner",
    "activation-absolute-time", "activation-permission", "duplicate-claim", "treatment-missing",
    "treatment-reordered", "treatment-crop", "windows-missing", "windows-null", "windows-reordered",
    "windows-premature", "receipt-windows-missing", "receipt-windows-null", "receipt-rehashed-false-state"])
def test_canonical_persisted_evidence_corruption_cannot_acquire_authority(canonical_evidence_boundary, tmp_path, fault):
    from atme.render.v2_split_paint import verify_split_paint_inputs
    from atme.store.contracts_v2 import (
        VisualPlanV2,
        validate_plan_layout,
        validate_resolved_structure,
    )

    root, _, _, service, semantic, layout, timeline, initial, carrier = canonical_evidence_boundary
    models = (semantic, layout, timeline)
    originals = tuple(model.model_dump(mode="json") for model in models)
    documents = deepcopy(originals)
    plan, drawing, clock = documents
    semantic_split = next(row for row in plan["actions"] if row["verb"] == "split")
    item = next(row for row in clock["actions"] if row["action"]["verb"] == "split")
    result = semantic_split["split_policy"]["results"][0]
    if fault == "activation-missing":
        result.pop("evidence_activation")
    elif fault == "activation-null":
        result["evidence_activation"] = None
    elif fault == "activation-owner":
        result["evidence_activation"]["causal_action_id"] = "not-the-owning-split"
    elif fault == "activation-absolute-time":
        result["evidence_activation"]["readable_hold_start_ms"] = 1600
    elif fault == "activation-permission":
        result["evidence_activation"]["permission_sha256"] = "0" * 64
    elif fault == "duplicate-claim":
        semantic_split["split_policy"]["results"][1]["evidence_activation"]["intent"]["claim_id"] = (
            result["evidence_activation"]["intent"]["claim_id"])
    elif fault == "treatment-missing":
        drawing["evidence_treatments"].pop()
    elif fault == "treatment-reordered":
        drawing["evidence_treatments"].reverse()
    elif fault == "treatment-crop":
        treatment = next(row for row in drawing["evidence_treatments"] if row["action_id"] == "split-1")
        treatment["intent"]["crop"]["x"] += 1
        treatment["intent"]["focus_region"]["x"] += 1
    elif fault == "windows-missing":
        item.pop("split_evidence_windows")
    elif fault == "windows-null":
        item["split_evidence_windows"] = None
    elif fault == "windows-reordered":
        item["split_evidence_windows"].reverse()
        item["split_completion_receipt"]["evidence_windows"] = deepcopy(item["split_evidence_windows"])
    elif fault == "windows-premature":
        window = item["split_evidence_windows"][0]
        window["readable_hold_start_ms"] -= 1
        window["readable_hold_end_ms"] -= 1
        item["split_completion_receipt"]["evidence_windows"] = deepcopy(item["split_evidence_windows"])
    elif fault == "receipt-windows-missing":
        item["split_completion_receipt"].pop("evidence_windows")
    elif fault == "receipt-windows-null":
        item["split_completion_receipt"]["evidence_windows"] = None
    else:
        item["split_completion_receipt"]["placements"][0]["state_version"] += 1
    if fault.startswith("receipt-") or fault in {"windows-reordered", "windows-premature"}:
        receipt = item["split_completion_receipt"]
        receipt["completion_sha256"] = digest({key: value for key, value in receipt.items()
                                                if key != "completion_sha256"})
    drawing["plan_sha256"] = clock["plan_sha256"] = digest(plan)
    clock["layout_sha256"] = digest(drawing)
    snapshots = {path: path.read_bytes() for path in root.glob("external-*.png")}, dict(service._row(layout.project_id))
    paths = []
    for index, document in enumerate(documents):
        path = tmp_path / f"corrupted-contract-{index}.json"
        path.write_bytes(json.dumps(document, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode("utf-8"))
        paths.append(path)
    with pytest.raises(ValueError):
        restored_plan = VisualPlanV2.model_validate_json(paths[0].read_bytes())
        restored_layout = ExecutableLayoutV2.model_validate_json(paths[1].read_bytes())
        restored_clock = ResolvedVisualTimelineV2.model_validate_json(paths[2].read_bytes())
        validate_plan_layout(restored_plan.model_dump(mode="json"), restored_layout.model_dump(mode="json"))
        validate_resolved_structure(restored_plan, restored_layout, restored_clock, restored_clock.duration_ms)
        verify_split_paint_inputs(restored_layout, carrier)
        _replay_split_chronology(restored_layout, initial, tuple(restored_clock.actions),
                                restored_clock.duration_ms, carrier, timeline=restored_clock)
    assert originals == tuple(model.model_dump(mode="json") for model in models)
    assert snapshots == ({path: path.read_bytes() for path in snapshots[0]}, dict(service._row(layout.project_id)))


def test_canonical_evidence_family_proof_does_not_admit_public_or_storage_execution(canonical_evidence_boundary):
    from atme.render.v2_split_paint import (
        _split_adapter,
        split_family_admission,
        verify_split_paint_inputs,
    )
    from atme.render.v2_state import validate_resolved_return_history
    from atme.render.v2_timeline_replay import supports_operator

    _, _, _, _, _, layout, timeline, initial, carrier = canonical_evidence_boundary
    split = next(row for row in timeline.actions if row.action.verb == "split")
    assert not supports_operator(split.action)
    with pytest.raises(UnsupportedVisualAction, match="split"):
        evaluate_frame(layout.model_dump(mode="json"), timeline.model_dump(mode="json"), split.start_ms)
    with pytest.raises(ValueError, match="[Ss]plit|split"):
        validate_resolved_return_history(layout, timeline, layout_sha256=digest(layout.model_dump(mode="json")))
    replay = _replay_split_chronology(layout, initial, tuple(timeline.actions), timeline.duration_ms, carrier,
                                      timeline=timeline)
    capture = next(row.split_capture for checkpoint in replay.checkpoints for row in checkpoint.active
                   if row.resolved.action.action_id == split.action.action_id)
    inputs = verify_split_paint_inputs(layout, carrier)
    objects = {obj.object_id: obj for obj in layout.objects}
    for result in split.action.split_policy.results:
        assert _split_adapter(objects[result.object_id]).family == "attested evidence"
        admission = split_family_admission(result.object_id, capture, layout, inputs)
        assert admission.family == "attested evidence"
        assert admission.proof_kind == "native_attested_evidence_alpha_v1"


@pytest.mark.parametrize("portrait", [False, True])
def test_split_native_annotation_binds_each_result_clock_and_real_pointer(tmp_path, monkeypatch, portrait):
    import io
    import re
    import socket
    from pathlib import Path

    from atme.render.v2_camera import camera_segments
    from atme.render.v2_split_paint import verify_split_paint_inputs
    from atme.render.v2_state import _sample_validated_frame
    from atme.render.v2_svg import (
        UnsupportedVisualObject,
        _authored_annotation_bindings,
        _compose_validated_svg_frame,
        _rasterize_svg_frame,
    )
    from PIL import Image

    service, layout, initial, timeline, carrier = readable_evidence_split_documents(tmp_path, portrait, annotated=True)
    original = (tmp_path / "external-original.png").read_bytes(), dict(service._row(layout.project_id))
    replay = _replay_split_chronology(layout, initial, tuple(timeline.actions), timeline.duration_ms, carrier)
    cameras = camera_segments(layout, timeline, replay)
    inputs = verify_split_paint_inputs(layout, carrier)
    held = {("split-1", "part-1"): _sample_validated_frame(layout, timeline, replay, cameras, 1600),
            ("split-1", "part-2"): _sample_validated_frame(layout, timeline, replay, cameras, 1500)}
    assert [(key, start, end) for key, _, start, end in _authored_annotation_bindings(timeline)] == [
        (("split-1", "part-1"), 1000, 1600), (("split-1", "part-2"), 1000, 1500)]

    def render(at):
        sample = _sample_validated_frame(layout, timeline, replay, cameras, at)
        svg = _compose_validated_svg_frame(layout, timeline, sample, held, None, split_inputs=inputs)
        return svg.svg, _rasterize_svg_frame(layout, svg, split_inputs=inputs).png

    partial_svg, partial_png = render(1200)
    full_svg, full_png = render(2000)
    assert "First mechanism" not in partial_svg and "Second mechanism" not in partial_svg
    assert "First mechanism" in full_svg and "Second mechanism" in full_svg
    assert not re.search(r'clip-path="url\(#reveal-note-part-', partial_svg)
    assert 'data-object-id="leader-part-1"' in full_svg and 'data-object-id="leader-part-2"' in full_svg
    with Image.open(io.BytesIO(partial_png)) as partial, Image.open(io.BytesIO(full_png)) as full:
        box = (120, 520, 540, 580) if portrait else (130, 560, 550, 620)
        assert partial.crop(box).tobytes() != full.crop(box).tobytes()
    assert replay.at(1500).object("leader-part-2").reveal_fraction == 1
    assert 0 < replay.at(1500).object("leader-part-1").reveal_fraction < 1
    for invalid in ({"split-1": held[("split-1", "part-1")]},
                    {("split-1", "part-1"): held[("split-1", "part-1")]},
                    {("split-1", "part-1"): held[("split-1", "part-2")],
                     ("split-1", "part-2"): held[("split-1", "part-1")]}):
        with pytest.raises(UnsupportedVisualObject, match="exact completed construction frame"):
            _compose_validated_svg_frame(layout, timeline,
                _sample_validated_frame(layout, timeline, replay, cameras, 999), invalid, None, split_inputs=inputs)
    (tmp_path / f"split-native-annotations-{portrait}.png").write_bytes(full_png)

    def denied(*_args, **_kwargs):
        pytest.fail("frozen authored annotation reopened source files or used the network")

    original_open = Path.open

    def only_temporary_fonts(path, *args, **kwargs):
        assert any(part.startswith("atme-split-fonts-") for part in path.parts), "reopened source resource"
        return original_open(path, *args, **kwargs)

    with monkeypatch.context() as sealed:
        sealed.setattr(Path, "read_bytes", denied)
        sealed.setattr(Path, "read_text", denied)
        sealed.setattr(Path, "open", only_temporary_fonts)
        sealed.setattr(socket, "create_connection", denied)
        sealed.setattr(socket.socket, "connect", denied)
        assert render(2000) == (full_svg, full_png)
        assert render(1200) == (partial_svg, partial_png)
        assert render(2000) == (full_svg, full_png)
    assert original == ((tmp_path / "external-original.png").read_bytes(), dict(service._row(layout.project_id)))


def test_native_annotation_binding_keeps_legacy_bare_split_cleanly_closed():
    from atme.render.v2_svg import _authored_annotation_bindings, compose_svg_frame

    _, layout, timeline = split_documents()
    timeline["actions"][0]["action"].pop("split_policy")
    timeline["actions"][0].pop("split_completion_receipt", None)
    typed = ResolvedVisualTimelineV2.model_validate(timeline)
    with pytest.raises(ValueError, match="Split|split"):
        _authored_annotation_bindings(typed)
    with pytest.raises(ValueError, match="Split|split"):
        compose_svg_frame(layout, timeline, 0)


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("at_ms", [1200, 2500])
def test_split_camera_includes_native_owned_notes_and_pointer_not_readonly_target(tmp_path, portrait, at_ms):
    from atme.render.v2_camera import camera_segments
    from atme.render.v2_split_paint import (
        _split_focus_bounds,
        verify_split_paint_inputs,
    )
    from test_v2_camera_action import append_camera

    _, layout, initial, timeline, carrier = readable_evidence_split_documents(tmp_path, portrait, annotated=True)
    clock = timeline.model_dump(mode="json")
    append_camera(clock, "camera-after-notes", "camera_cut", at_ms, at_ms + 100, target="part-1", framing="wide")
    timeline = ResolvedVisualTimelineV2.model_validate(clock)
    replay = _replay_split_chronology(layout, initial, tuple(timeline.actions), timeline.duration_ms, carrier)
    capture = next(row.split_capture for checkpoint in replay.checkpoints for row in checkpoint.active
                   if row.resolved.action.action_id == "split-1")
    inputs = verify_split_paint_inputs(layout, carrier)
    observed = _split_focus_bounds(capture, layout, timeline, replay, inputs, "camera-after-notes")
    if at_ms == 1200:
        assert observed[:2] == (8, 8)
        assert (1101 if portrait else 551) < observed[3] < (1200 if portrait else 610)
        with pytest.raises(ValueError, match="focus-object edit"):
            camera_segments(layout, timeline, replay, split_inputs=inputs)
    else:
        assert observed[:3] == ((119, 79, 621) if portrait else (119, 129, 1201))
        # The pinned 4px stroke at 2/3 scale extends two alpha pixels past the
        # leader endpoint. The read-only target's bottom edge is not painted.
        assert observed[3] == (1222 if portrait else 632)
        assert observed[3] < (1240 if portrait else 650)
        assert camera_segments(layout, timeline, replay, split_inputs=inputs)


@pytest.mark.parametrize("portrait", [False, True])
def test_real_readable_evidence_fixture_uses_original_bytes_and_actual_result_clocks(tmp_path, portrait):
    from atme.render.v2_camera import CameraViewport
    from atme.render.v2_evidence_reading import validate_evidence_reading_binding

    service, layout, initial, timeline, carrier = readable_evidence_split_documents(tmp_path, portrait)
    original = (tmp_path / "external-original.png").read_bytes(), dict(service._row(layout.project_id))
    replay = _replay_split_chronology(layout, initial, tuple(timeline.actions), timeline.duration_ms, carrier)
    assert replay.evidence_treatments_json == ()
    viewport = CameraViewport(0, 0, layout.canvas.width, layout.canvas.height)
    for treatment, start, end in zip(layout.evidence_treatments, (1600, 1900), (4100, 4400), strict=True):
        for at in (start, end - 1, 2000):
            validate_evidence_reading_binding(treatment.object_id, start, layout,
                {row.object_id: row for row in layout.objects}, treatment, replay.at(at), viewport)
    assert replay.at(1599).object("part-1").reveal_fraction < 1
    assert 0 < replay.at(1899).object("part-2").transform.position.x < 20
    assert original == ((tmp_path / "external-original.png").read_bytes(), dict(service._row(layout.project_id)))


@pytest.mark.parametrize("portrait", [False, True])
def test_real_readable_evidence_split_runs_bound_reading_on_typed_replay(tmp_path, portrait):
    _, layout, initial, timeline, carrier = readable_evidence_split_documents(tmp_path, portrait)
    replay = _replay_split_chronology(layout, initial, tuple(timeline.actions), timeline.duration_ms, carrier,
                                      timeline=timeline)
    assert replay.at(1600).object("part-1").reveal_fraction == 1
    assert replay.at(1900).object("part-2").transform.position.x == 20


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("annotated", [False, True])
def test_split_evidence_lifecycle_reads_each_actual_result_hold_with_frozen_inputs(tmp_path, monkeypatch,
                                                                                portrait, annotated):
    from atme.render import v2_evidence_reading
    from atme.render.v2_lifecycle import validate_split_lifecycle
    from atme.render.v2_split_paint import verify_split_paint_inputs

    service, layout, initial, timeline, carrier = readable_evidence_split_documents(
        tmp_path, portrait, annotated=annotated)
    replay = _replay_split_chronology(layout, initial, tuple(timeline.actions), timeline.duration_ms, carrier)
    capture = next(row.split_capture for checkpoint in replay.checkpoints for row in checkpoint.active
                   if row.resolved.action.action_id == "split-1")
    inputs = verify_split_paint_inputs(layout, carrier)
    original = (repr(replay), repr(capture), layout.model_dump(mode="json"), timeline.model_dump(mode="json"),
                (tmp_path / "external-original.png").read_bytes(), dict(service._row(layout.project_id)))
    actual_reader = v2_evidence_reading.validate_evidence_reading_binding
    readings = []

    def observe(target, start, layout, objects, treatment, sample, viewport):
        actual_reader(target, start, layout, objects, treatment, sample, viewport)
        readings.append((target, start, sample.at_ms))

    monkeypatch.setattr(v2_evidence_reading, "validate_evidence_reading_binding", observe)
    validate_split_lifecycle(capture, replay, layout, timeline, split_inputs=inputs)
    # Frozen authority is value-bound; an equal immutable reconstruction is valid.
    validate_split_lifecycle(capture, replay, layout, timeline, split_inputs=replace(inputs))
    for target, start, end in (("part-1", 1600, 4100), ("part-2", 1900, 4400)):
        observed = {at for key, clock, at in readings if key == target and clock == start}
        assert {start, 1999, 2000, end - 1}.issubset(observed)
        assert min(observed) == start and max(observed) == end - 1
    assert original == (repr(replay), repr(capture), layout.model_dump(mode="json"), timeline.model_dump(mode="json"),
                        (tmp_path / "external-original.png").read_bytes(), dict(service._row(layout.project_id)))


@pytest.mark.parametrize("portrait", [False, True])
def test_split_evidence_lifecycle_observes_retained_camera_before_its_readable_holds(tmp_path, portrait):
    from atme.render.v2_lifecycle import validate_split_lifecycle
    from atme.render.v2_split_paint import verify_split_paint_inputs
    from test_v2_camera_action import append_camera

    _, layout, initial, timeline, carrier = readable_evidence_split_documents(tmp_path, portrait, annotated=True)
    clock = timeline.model_dump(mode="json")
    append_camera(clock, "camera-before-split", "camera_cut", 500, 600, target="annotation-target", framing="detail")
    timeline = ResolvedVisualTimelineV2.model_validate(clock)
    replay = _replay_split_chronology(layout, initial, tuple(timeline.actions), timeline.duration_ms, carrier)
    capture = next(row.split_capture for checkpoint in replay.checkpoints for row in checkpoint.active
                   if row.resolved.action.action_id == "split-1")
    with pytest.raises(ValueError, match="not fully readable"):
        validate_split_lifecycle(capture, replay, layout, timeline, split_inputs=verify_split_paint_inputs(layout, carrier))


@pytest.fixture(scope="module")
def split_reading_boundary(tmp_path_factory):
    from atme.render.v2_split_paint import verify_split_paint_inputs

    service, layout, initial, timeline, carrier = readable_evidence_split_documents(
        tmp_path_factory.mktemp("reading-authority"), False, annotated=True)
    replay = _replay_split_chronology(layout, initial, tuple(timeline.actions), timeline.duration_ms, carrier)
    capture = next(row.split_capture for checkpoint in replay.checkpoints for row in checkpoint.active
                   if row.resolved.action.action_id == "split-1")
    yield capture, replay, layout, timeline, verify_split_paint_inputs(layout, carrier), initial, carrier
    service.store.close()


@pytest.mark.parametrize("fault", ["missing", "wrong_type", "layout_pin", "payload", "missing_asset",
                                  "extra_asset", "treatment", "capture_copy", "replay_duration"])
def test_split_reading_rejects_substituted_frozen_or_replay_authority(split_reading_boundary, fault):
    from atme.render.v2_lifecycle import validate_split_lifecycle

    capture, replay, layout, timeline, inputs, _, _ = split_reading_boundary
    if fault == "missing":
        inputs = None
    elif fault == "wrong_type":
        inputs = {"inputs_sha256": inputs.inputs_sha256}
    elif fault == "layout_pin":
        inputs = replace(inputs, layout_sha256="0" * 64)
    elif fault == "payload":
        inputs = replace(inputs, project_assets=(replace(inputs.project_assets[0], payload=b"corrupt"),))
    elif fault == "missing_asset":
        inputs = replace(inputs, project_assets=())
    elif fault == "extra_asset":
        inputs = replace(inputs, project_assets=inputs.project_assets + inputs.project_assets)
    elif fault == "treatment":
        inputs = replace(inputs, project_assets=(replace(inputs.project_assets[0],
            treatments_json=inputs.project_assets[0].treatments_json[::-1]),))
    elif fault == "capture_copy":
        capture = replace(capture)
    else:
        replay = replace(replay, duration_ms=replay.duration_ms + 1)
    with pytest.raises(ValueError):
        validate_split_lifecycle(capture, replay, layout, timeline, split_inputs=inputs)


def test_split_reading_samples_actual_half_open_camera_and_replay_boundaries(split_reading_boundary):
    from atme.render.v2_camera import camera_segments
    from atme.render.v2_lifecycle import _evidence_window_samples
    from test_v2_camera_action import append_camera

    _, _, layout, timeline, inputs, initial, carrier = split_reading_boundary
    clock = timeline.model_dump(mode="json")
    append_camera(clock, "camera-before-split", "camera_cut", 500, 600, target="annotation-target", framing="detail")
    append_camera(clock, "camera-after-split", "camera_reframe", 2500, 2600,
                  target="part-1", framing="wide", easing="ease_in_out")
    timeline = ResolvedVisualTimelineV2.model_validate(clock)
    replay = _replay_split_chronology(layout, initial, tuple(timeline.actions), timeline.duration_ms, carrier)
    plan = camera_segments(layout, timeline, replay, split_inputs=inputs)
    samples = _evidence_window_samples(replay, 1600, 4100, plan)
    assert tuple(row.at_ms for row in samples) == (1600, 1999, 2000, 2499, 2500, 2599, 2600, 4099)
    assert all(row == replay.at(row.at_ms) for row in samples)


@pytest.mark.parametrize("start,end", [(True, 4100), (1600.0, 4100), (-1, 4100), (1600, 1600),
                                      (1600, 1500), (1600, 5001), (1600, True)])
def test_split_reading_sampler_rejects_nonexact_or_unbounded_windows(split_reading_boundary, start, end):
    from atme.render.v2_lifecycle import _evidence_window_samples

    _, replay, _, _, _, _, _ = split_reading_boundary
    with pytest.raises(ValueError, match="half-open window"):
        _evidence_window_samples(replay, start, end, ())


@pytest.mark.parametrize("portrait", [False, True])
def test_private_split_evidence_native_uses_each_original_crop_and_actual_clock(tmp_path, monkeypatch, portrait):
    import io
    import socket
    from pathlib import Path

    from atme.render.v2_camera import camera_segments
    from atme.render.v2_split_paint import _split_adapter, verify_split_paint_inputs
    from atme.render.v2_state import _sample_validated_frame
    from atme.render.v2_svg import _compose_validated_svg_frame, _rasterize_svg_frame
    from PIL import Image

    service, layout, initial, timeline, carrier = readable_evidence_split_documents(tmp_path, portrait)
    original = (tmp_path / "external-original.png").read_bytes(), dict(service._row(layout.project_id))
    replay = _replay_split_chronology(layout, initial, tuple(timeline.actions), timeline.duration_ms, carrier)
    camera = camera_segments(layout, timeline, replay)
    inputs = verify_split_paint_inputs(layout, carrier)
    assert all(_split_adapter(obj).family == "attested evidence"
               for obj in layout.objects if obj.object_type == "evidence")

    def render(at, supplied):
        snapshot = _sample_validated_frame(layout, timeline, replay, camera, at)
        svg = _compose_validated_svg_frame(layout, timeline, snapshot, {}, supplied, split_inputs=inputs)
        return _rasterize_svg_frame(layout, svg, split_inputs=inputs).png

    sequential = {at: render(at, carrier) for at in (1200, 1600, 1900, 4399)}
    colors = ((235, 30, 40), (25, 185, 50))
    with Image.open(io.BytesIO(sequential[1900])) as image:
        rgb = image.convert("RGB")
        assert rgb.getpixel((370, 240) if portrait else (950, 300)) == colors[0]
        assert rgb.getpixel((370, 840) if portrait else (370, 300)) == colors[1]
    with Image.open(io.BytesIO(sequential[1200])) as partial, Image.open(io.BytesIO(sequential[1900])) as full:
        partial_counts = tuple(partial.convert("RGB").get_flattened_data())
        full_counts = tuple(full.convert("RGB").get_flattened_data())
        for color in colors:
            assert 0 < sum(pixel == color for pixel in partial_counts) < sum(pixel == color for pixel in full_counts)
        assert min(i % partial.width for i, pixel in enumerate(partial_counts) if pixel == colors[1]) == 105
        # The two-pixel focus stroke covers the first column at x=120.
        assert min(i % full.width for i, pixel in enumerate(full_counts) if pixel == colors[1]) == 121
    assert replay.at(1200).object("part-2").transform.position.x < 20
    (tmp_path / f"split-evidence-native-{portrait}.png").write_bytes(sequential[1900])

    def denied(*_args, **_kwargs):
        pytest.fail("frozen Split evidence reopened source files or used the network")

    original_open = Path.open

    def only_temporary_fonts(path, *args, **kwargs):
        assert any(part.startswith("atme-split-fonts-") for part in path.parts), "reopened source resource"
        return original_open(path, *args, **kwargs)

    with monkeypatch.context() as sealed:
        sealed.setattr(Path, "read_bytes", denied)
        sealed.setattr(Path, "read_text", denied)
        sealed.setattr(Path, "open", only_temporary_fonts)
        sealed.setattr(socket, "create_connection", denied)
        sealed.setattr(socket.socket, "connect", denied)
        for at in (4399, 1200, 1900, 1600, 1200):
            assert render(at, None) == sequential[at]
    assert original == ((tmp_path / "external-original.png").read_bytes(), dict(service._row(layout.project_id)))
    with pytest.raises((UnsupportedVisualAction, V2FrameError), match="split|Split"):
        evaluate_frame(layout.model_dump(mode="json"), timeline.model_dump(mode="json"), 1900)


@pytest.mark.parametrize("fault", ["missing_activation", "wrong_owner", "wrong_pair", "draw", "unpaired_treatment"])
def test_private_split_evidence_native_rejects_unbound_result_construction(tmp_path, fault):
    from atme.render.v2_camera import camera_segments
    from atme.render.v2_split_paint import verify_split_paint_inputs
    from atme.render.v2_state import _sample_validated_frame
    from atme.render.v2_svg import _compose_validated_svg_frame

    _, layout, initial, timeline, carrier = readable_evidence_split_documents(tmp_path, False)
    replay = _replay_split_chronology(layout, initial, tuple(timeline.actions), timeline.duration_ms, carrier)
    snapshot = _sample_validated_frame(layout, timeline, replay, camera_segments(layout, timeline, replay), 1600)
    inputs = verify_split_paint_inputs(layout, carrier)
    changed = timeline.model_copy(deep=True)
    result = changed.actions[0].action.split_policy.results[0]
    if fault == "missing_activation":
        result.evidence_activation = None
    elif fault == "wrong_owner":
        result.evidence_activation.causal_action_id = "other-owner"
    elif fault == "wrong_pair":
        result.evidence_activation.result_object_id = "part-2"
    elif fault == "draw":
        result.construction.mode = "draw"
    else:
        changed.evidence_treatments[0].intent.crop.x = 5
    with pytest.raises(ValueError, match="exact result|exact paired"):
        _compose_validated_svg_frame(layout, changed, snapshot, {}, split_inputs=inputs)


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("at,landscape,vertical", [
    (1000, (8, 8, 32, 32), (8, 8, 32, 32)),
    (1200, (8, 8, 857, 550), (8, 8, 305, 1100)),
    (2500, (119, 129, 1201, 551), (119, 79, 621, 1101)),
])
def test_camera_observes_actual_split_union(tmp_path, portrait, at, landscape, vertical):
    from atme.render import v2_split_paint
    from atme.render.v2_camera import UnsupportedCamera, camera_segments
    from atme.render.v2_split import CapturedSplitAction
    from test_v2_camera_action import append_camera

    _, layout, initial, timeline, carrier = readable_evidence_split_documents(tmp_path, portrait)
    raw = timeline.model_dump(mode="json")
    append_camera(raw, "observe-split", "camera_cut", at, at + 100, target="part-1")
    timeline = ResolvedVisualTimelineV2.model_validate(raw)
    replay = _replay_split_chronology(layout, initial, tuple(timeline.actions), timeline.duration_ms, carrier)
    captures = {id(row.split_capture): row.split_capture for checkpoint in replay.checkpoints
                for row in checkpoint.active if isinstance(row, CapturedSplitAction)}
    assert len(captures) == 1
    capture = next(iter(captures.values()))
    inputs = v2_split_paint.verify_split_paint_inputs(layout, carrier)
    before = repr(replay), layout.model_dump_json(), timeline.model_dump_json(), capture
    assert hasattr(v2_split_paint, "_split_focus_bounds"), "actual clipped Split camera observation is missing"
    bounds = v2_split_paint._split_focus_bounds(capture, layout, timeline, replay, inputs, "observe-split")
    assert bounds == (vertical if portrait else landscape)
    if at < 2000:
        with pytest.raises(UnsupportedCamera, match="focus-object edit"):
            camera_segments(layout, timeline, replay, split_inputs=inputs)
    else:
        segments = camera_segments(layout, timeline, replay, split_inputs=inputs)
        assert len(segments) == 1
        assert segments[0][0].action.action_id == "observe-split"
    assert before == (repr(replay), layout.model_dump_json(), timeline.model_dump_json(), capture)


def test_split_camera_cannot_freeze_focus_before_a_later_overlapping_writer():
    from atme.render.v2_camera import UnsupportedCamera, camera_segments
    from atme.render.v2_split_paint import verify_split_paint_inputs
    from test_v2_camera_action import append_camera
    from test_v2_timeline_replay import resolved as timed

    layout, _, split = geometry_boundary()
    _, _, raw = split_documents()
    raw.update(layout_sha256=digest(layout.model_dump(mode="json")), actions=[split.model_dump(mode="json")])
    append_camera(raw, "observe-split", "camera_cut", 1500, 2000, target="part-1")
    destination = next(row for row in layout.objects if row.object_id == "part-1").transform.model_dump(mode="json")
    destination["position"]["x"] = 100
    writer = timed(peer_action("move", target_ids=["part-1"], destination=destination).action, 1600, 1900)
    raw["actions"].append(writer.model_dump(mode="json"))
    raw["coverage"][0]["action_ids"].append(writer.action.action_id)
    raw["actions"].sort(key=lambda row: row["start_ms"])
    timeline = ResolvedVisualTimelineV2.model_validate(raw)
    replay = _replay_split_chronology(layout, sample_for_layout(layout), tuple(timeline.actions), timeline.duration_ms, {})
    with pytest.raises(UnsupportedCamera, match="focus-object edit"):
        camera_segments(layout, timeline, replay, split_inputs=verify_split_paint_inputs(layout, {}))


@pytest.mark.parametrize("aperture", [False, True])
def test_split_camera_preserves_ancestor_and_aperture_focus_lifetime(aperture):
    from atme.render.v2_camera import UnsupportedCamera, camera_segments
    from atme.render.v2_split import _observed_split_placements
    from atme.render.v2_split_identity import split_content_receipts
    from atme.render.v2_split_paint import verify_split_paint_inputs
    from atme.store.contracts_v2 import (
        SplitPolicy,
        StyleRefs,
        _split_expected_completion,
    )
    from test_v2_camera_action import append_camera
    from test_v2_split_capture import ancestor_boundary
    from test_v2_split_contract import split_with_earlier_ancestor
    from test_v2_timeline_replay import resolved as timed

    layout, _, split = ancestor_boundary(aperture=aperture)
    _, _, raw = split_with_earlier_ancestor()
    layout = ExecutableLayoutV2.model_validate(layout.model_copy(update={"objects": [
        obj.model_copy(update={"style": StyleRefs(), "anchors": [], "initial_state": "visible", "visible": True})
        if obj.object_id == "earlier" else obj
        for obj in layout.objects]}).model_dump(mode="json"))
    initial = sample_for_layout(layout)
    before = _replay_split_chronology(layout, initial, (), raw["duration_ms"], {}).at(split.start_ms)
    objects = {row.object_id: row for row in layout.objects}
    contents = {row.object_id: row for row in split_content_receipts(layout, before, {})}
    packet = split.model_dump(mode="json")
    policy = packet["action"]["split_policy"]
    policy["source_basis"]["placements"] = [row.model_dump(mode="json") for row in
        _observed_split_placements(before, objects, set(objects), contents)]
    for row in policy["correspondences"]:
        row.update(source_content_sha256=contents["source"].content_sha256,
                   result_content_sha256=contents[row["result_object_id"]].content_sha256)
    policy["source_basis_sha256"] = digest(policy["source_basis"])
    receipt = _split_expected_completion(SplitPolicy.model_validate(policy))
    receipt["completion_sha256"] = digest(receipt)
    packet["split_completion_receipt"] = receipt
    split = ResolvedAction.model_validate(packet)
    raw.update(layout_sha256=digest(layout.model_dump(mode="json")), actions=[split.model_dump(mode="json")])
    raw["coverage"] = [row for row in raw["coverage"] if row["coverage_id"] != "coverage-earlier"]
    for fallback in raw["fallbacks"]:
        fallback["affected_ids"] = [key for key in fallback["affected_ids"] if key != "instruction-earlier"]
    next(row for row in raw["initial_object_states"] if row["object_id"] == "earlier").update(state="visible", visible=True)
    start = split.end_ms + 100
    append_camera(raw, "observe-split", "camera_cut", start, start + 500, target="part-1")
    timeline = ResolvedVisualTimelineV2.model_validate(raw)
    inputs = verify_split_paint_inputs(layout, {})
    replay = _replay_split_chronology(layout, initial, tuple(timeline.actions), timeline.duration_ms, {})
    assert len(camera_segments(layout, timeline, replay, split_inputs=inputs)) == 1
    writer = timed(peer_action("fade", target_ids=["earlier"], opacity=.5).action, start + 100, start + 300)
    raw["actions"].append(writer.model_dump(mode="json"))
    raw["coverage"][0]["action_ids"].append(writer.action.action_id)
    raw["actions"].sort(key=lambda row: row["start_ms"])
    timeline = ResolvedVisualTimelineV2.model_validate(raw)
    replay = _replay_split_chronology(layout, initial, tuple(timeline.actions), timeline.duration_ms, {})
    with pytest.raises(UnsupportedCamera, match="focus-object edit"):
        camera_segments(layout, timeline, replay, split_inputs=inputs)


@pytest.mark.parametrize("portrait", [False, True])
def test_split_evidence_hold_does_not_admit_an_unrelated_focus_camera(tmp_path, portrait):
    from test_v2_camera_action import append_camera

    _, layout, _, timeline, _ = readable_evidence_split_documents(tmp_path, portrait)
    document = layout.model_dump(mode="json")
    extra = deepcopy(next(row for row in document["objects"] if row["object_id"] == "source"))
    extra.update(object_id="unrelated-focus", z_index=3)
    document["objects"].append(extra)
    document["boards"][0]["object_ids"].append(extra["object_id"])
    layout = ExecutableLayoutV2.model_validate(document)
    raw = timeline.model_dump(mode="json")
    raw["layout_sha256"] = digest(layout.model_dump(mode="json"))
    raw["initial_object_states"].append({"object_id": extra["object_id"], "state": extra["initial_state"],
                                        "state_version": 1, "visible": True})
    append_camera(raw, "unrelated-camera", "camera_cut", 2500, 2600, target=extra["object_id"])
    timeline = ResolvedVisualTimelineV2.model_validate(raw)
    with pytest.raises(V2FrameError, match="uninterrupted readable"):
        _validate_pair_static(layout, timeline, raw["layout_sha256"], sample_for_layout(layout).hierarchy)


@pytest.fixture(scope="module")
def split_camera_boundary(tmp_path_factory):
    from atme.render.v2_split import CapturedSplitAction
    from atme.render.v2_split_paint import verify_split_paint_inputs
    from test_v2_camera_action import append_camera

    _, layout, initial, timeline, carrier = readable_evidence_split_documents(
        tmp_path_factory.mktemp("split-camera-boundary"), False)
    raw = timeline.model_dump(mode="json")
    append_camera(raw, "observe-split", "camera_cut", 2500, 2600, target="part-1")
    timeline = ResolvedVisualTimelineV2.model_validate(raw)
    replay = _replay_split_chronology(layout, initial, tuple(timeline.actions), timeline.duration_ms, carrier)
    capture = next(row.split_capture for checkpoint in replay.checkpoints
                   for row in checkpoint.active if isinstance(row, CapturedSplitAction))
    return capture, layout, timeline, replay, verify_split_paint_inputs(layout, carrier)


@pytest.mark.parametrize("fault", ["copied_capture", "missing_inputs", "partial_replay", "changed_layout",
                                  "changed_timeline", "false_initial_version", "unknown_camera"])
def test_split_camera_cannot_substitute_capture_replay_or_frozen_authority(split_camera_boundary, fault):
    from atme.render.v2_split_paint import _split_focus_bounds

    capture, layout, timeline, replay, inputs = split_camera_boundary
    camera = "observe-split"
    if fault == "copied_capture":
        capture = replace(capture)
    elif fault == "missing_inputs":
        inputs = None
    elif fault == "partial_replay":
        replay = replace(replay, duration_ms=replay.duration_ms + 1)
    elif fault == "changed_layout":
        layout = layout.model_copy(deep=True)
        layout.objects[0].geometry.bounds.x += 1
    elif fault == "changed_timeline":
        timeline = timeline.model_copy(deep=True)
        timeline.layout_sha256 = "a" * 64
    elif fault == "false_initial_version":
        first = replay.checkpoints[0]
        replay = replace(replay, checkpoints=(replace(first, state_versions=tuple(
            (key, version + 1) for key, version in first.state_versions)), *replay.checkpoints[1:]))
    else:
        camera = "not-an-authored-camera"
    with pytest.raises(ValueError):
        _split_focus_bounds(capture, layout, timeline, replay, inputs, camera)


def test_split_camera_repeats_the_actual_frozen_observation_without_source_or_network_reads(
        split_camera_boundary, monkeypatch):
    import socket
    from pathlib import Path

    from atme.render.v2_camera import camera_segments
    from atme.render.v2_split_paint import _split_focus_bounds

    capture, layout, timeline, replay, inputs = split_camera_boundary
    before = repr(replay), capture
    original_open = Path.open

    def denied(*_args, **_kwargs):
        pytest.fail("Split camera reopened source files or used the network")

    def only_temporary_fonts(path, *args, **kwargs):
        assert any(part.startswith("atme-split-fonts-") for part in path.parts), "reopened source resource"
        return original_open(path, *args, **kwargs)

    with monkeypatch.context() as sealed:
        sealed.setattr(Path, "read_bytes", denied)
        sealed.setattr(Path, "read_text", denied)
        sealed.setattr(Path, "open", only_temporary_fonts)
        sealed.setattr(socket, "create_connection", denied)
        sealed.setattr(socket.socket, "connect", denied)
        for _ in range(2):
            assert _split_focus_bounds(capture, layout, timeline, replay, inputs, "observe-split") == (119, 129, 1201, 551)
            assert len(camera_segments(layout, timeline, replay, split_inputs=inputs)) == 1
    assert before == (repr(replay), capture)


def shared_context_documents(shared_boundary):
    layout, before, action, carrier = shared_boundary
    _, _, raw = split_documents()
    raw.update(project_id=layout.project_id, plan_id=layout.plan_id, plan_revision=layout.plan_revision,
        plan_sha256=layout.plan_sha256, layout_id=layout.layout_id,
        layout_sha256=digest(layout.model_dump(mode="json")),
        resolved_assets=[json.loads(row.resolved_json) for row in carrier.rows],
        evidence_treatments=[row.model_dump(mode="json") for row in layout.evidence_treatments],
        actions=[action.model_dump(mode="json")], initial_object_states=[{
            "object_id": row.object_id, "state": row.state, "state_version": dict(before.state_versions)[row.object_id],
            "visible": row.visible} for row in before.objects])
    return layout, before, ResolvedVisualTimelineV2.model_validate(raw)


def test_pair_context_keeps_every_split_pair_out_of_the_ordinary_action_map(shared_boundary):
    layout, before, timeline = shared_context_documents(shared_boundary)
    context = _validate_pair_static(layout, timeline, digest(layout.model_dump(mode="json")), before.hierarchy)
    assert context.treatments_by_action == {}
    assert context.treatments_by_pair == {("split-1", key): treatment
        for key, treatment in zip(("part-1", "part-2"), layout.evidence_treatments, strict=True)}
    # Static storage inventory is not public renderer admission.
    with pytest.raises(UnsupportedVisualAction, match="split"):
        evaluate_frame(layout.model_dump(mode="json"), timeline.model_dump(mode="json"), 1500)


def test_pair_context_cannot_skip_nonlast_split_result_positive_alpha_guard(shared_boundary):
    layout, before, timeline = shared_context_documents(shared_boundary)
    raw = layout.model_dump(mode="json")
    next(row for row in raw["objects"] if row["object_id"] == "part-1")["opacity"] = 0.0
    changed = ExecutableLayoutV2.model_validate(raw)
    clock = timeline.model_dump(mode="json")
    clock["layout_sha256"] = digest(changed.model_dump(mode="json"))
    timeline = ResolvedVisualTimelineV2.model_validate(clock)
    with pytest.raises(V2FrameError, match="evidence|opacity|hidden"):
        _validate_pair_static(changed, timeline, clock["layout_sha256"], before.hierarchy)


@pytest.mark.parametrize("fault", ["missing_treatment", "missing_window", "false_window_hash",
                                  "reordered_windows", "duplicate_window", "wrong_result", "false_hold_end"])
def test_pair_context_requires_complete_selected_split_window_authority(shared_boundary, fault):
    layout, before, timeline = shared_context_documents(shared_boundary)
    # Causal storage history copies typed documents; coherent copies cannot
    # replace the selected Split's complete result/window authority.
    if fault == "missing_treatment":
        layout = layout.model_copy(update={"evidence_treatments": layout.evidence_treatments[1:]})
        timeline = timeline.model_copy(update={"evidence_treatments": layout.evidence_treatments,
            "layout_sha256": digest(layout.model_dump(mode="json"))})
    else:
        item = timeline.actions[0]
        windows = list(item.split_evidence_windows)
        if fault == "missing_window":
            windows = windows[1:]
        elif fault == "reordered_windows":
            windows.reverse()
        elif fault == "duplicate_window":
            windows[1] = windows[0]
        else:
            field, value = (("treatment_sha256", "0" * 64) if fault == "false_window_hash" else
                            ("result_object_id", "unrelated-result") if fault == "wrong_result" else
                            ("readable_hold_end_ms", 4101))
            windows[0] = windows[0].model_copy(update={field: value})
        timeline = timeline.model_copy(update={"actions": [item.model_copy(update={"split_evidence_windows": windows})]})
    with pytest.raises(V2FrameError, match="Split|split|evidence|window|treatment"):
        _validate_pair_static(layout, timeline, digest(layout.model_dump(mode="json")), before.hierarchy)


@pytest.mark.parametrize("board_end", [4400, 4399])
def test_pair_context_uses_result_window_not_outer_split_end_for_board_hold(shared_boundary, board_end):
    layout, before, timeline = shared_context_documents(shared_boundary)
    raw = layout.model_dump(mode="json")
    raw["activations"][0]["end_ms"] = board_end
    layout = ExecutableLayoutV2.model_validate(raw)
    clock = timeline.model_dump(mode="json")
    clock["layout_sha256"] = digest(layout.model_dump(mode="json"))
    timeline = ResolvedVisualTimelineV2.model_validate(clock)
    if board_end == 4400:
        context = _validate_pair_static(layout, timeline, clock["layout_sha256"], before.hierarchy)
        assert set(context.treatments_by_pair) == {("split-1", "part-1"), ("split-1", "part-2")}
    else:
        with pytest.raises(V2FrameError, match="outlasts"):
            _validate_pair_static(layout, timeline, clock["layout_sha256"], before.hierarchy)


def test_pair_context_excludes_future_split_pairs_from_the_selected_prefix(shared_boundary):
    layout, before, timeline = shared_context_documents(shared_boundary)
    prefix = timeline.model_copy(update={"actions": []})
    context = _validate_pair_static(layout, prefix, digest(layout.model_dump(mode="json")), before.hierarchy,
                                    structural_timeline=timeline)
    assert context.treatments_by_action == context.treatments_by_pair == {}
    assert set(context.objects) == {row.object_id for row in layout.objects}


def test_pair_context_preserves_ordinary_insert_map_and_all_selected_pairs(tmp_path):
    from atme.render.v2_hierarchy import HierarchySnapshot

    _, layout, timeline, _ = ordinary_shared_evidence(tmp_path, False)
    hierarchy = HierarchySnapshot.from_objects({row.object_id: row for row in layout.objects})
    context = _validate_pair_static(layout, timeline, digest(layout.model_dump(mode="json")), hierarchy)
    assert context.treatments_by_action == {row.action_id: row for row in layout.evidence_treatments}
    assert context.treatments_by_pair == {(row.action_id, row.object_id): row for row in layout.evidence_treatments}


def test_split_evidence_replays_on_actual_scheduler_with_one_atomic_commit(tmp_path):
    layout, before, action, carrier, _ = live_evidence_boundary(tmp_path)
    initial = replace(before, at_ms=0)
    replay = _replay_split_chronology(layout, initial, (action,), 5000, carrier)
    assert replay.evidence_treatments_json == ()
    captures = [capture.split_capture for checkpoint in replay.checkpoints for capture in checkpoint.active]
    assert captures
    assert all([key for key, _ in capture.evidence_treatments_json] == ["part-1"] for capture in captures)
    assert all(json.loads(capture.evidence_treatments_json[0][1]) ==
               layout.evidence_treatments[0].model_dump(mode="json") for capture in captures)
    expected = {}
    for at, note, leader, committed in [
        (999, 0.0, 0.0, False), (1000, 0.0, 0.0, False),
        (1200, 0.5, 0.0, False), (1500, 1.0, 0.5, False),
        (1600, 1.0, 1.0, False), (1999, 1.0, 1.0, False),
        (2000, 1.0, 1.0, True), (4100, 1.0, 1.0, True),
    ]:
        sample = replay.at(at)
        expected[at] = sample
        assert sample.object("evidence-note").reveal_fraction == note
        assert sample.object("evidence-leader").reveal_fraction == leader
        assert sample.object("evidence-note").state == ("visible" if committed else "hidden")
        assert sample.object("part-1").state == ("evidence_visible" if committed else "hidden")
        assert sample.object("source").state == ("removed" if committed else "visible")
        versions = dict(sample.state_versions)
        assert [versions[key] for key in ("source", "part-1", "part-2", "evidence-note", "evidence-leader")] == (
            [2] * 5 if committed else [1] * 5)
        assert versions["annotation-target"] == 1
        assert sample.object("annotation-target") == initial.object("annotation-target")
    for at in (4100, 1200, 2000, 1000, 1600, 999, 1999, 1500):
        assert replay.at(at) == expected[at]


@pytest.mark.parametrize("selected", [False, True])
def test_legacy_treatments_require_actual_ordinary_insert_in_selected_prefix(tmp_path, selected):
    service, raw_layout, timeline, verified = evidence_documents(tmp_path)
    layout = ExecutableLayoutV2.model_validate(raw_layout)
    asset = ResolvedAsset.model_validate(timeline["resolved_assets"][0])
    pin = SplitAssetPin(asset_id=asset.asset_id, revision=asset.revision, resource_uri=asset.managed_ref,
                        checksum_sha256=asset.checksum_sha256)
    carrier = _VerifiedSplitAssetBytes((_freeze_verified_split_asset(asset, pin, verified, layout=layout),))
    insertion = next(ResolvedAction.model_validate(row) for row in timeline["actions"]
                     if row["action"]["verb"] == "insert_evidence")
    initial = sample_for_layout(layout)
    original_project = dict(service._row(layout.project_id))
    replay = _replay_split_chronology(layout, initial, (insertion,) if selected else (),
                                      timeline["duration_ms"], carrier)
    assert [key for key, _ in replay.evidence_treatments_json] == ([insertion.action.action_id] if selected else [])
    if selected:
        assert json.loads(replay.evidence_treatments_json[0][1]) == layout.evidence_treatments[0].model_dump(mode="json")
        assert replay.at(insertion.end_ms).object(insertion.action.target_object_id).state == "evidence_visible"
    else:
        assert replay.at(insertion.end_ms).objects == initial.objects
    assert dict(service._row(layout.project_id)) == original_project


@pytest.mark.parametrize("fault", ["missing_treatment", "changed_treatment"])
def test_chronology_cannot_avoid_actual_split_treatment_context_validation(tmp_path, fault):
    layout, before, action, carrier, _ = live_evidence_boundary(tmp_path)
    raw = layout.model_dump(mode="json")
    if fault == "missing_treatment":
        raw["evidence_treatments"] = []
    else:
        raw["evidence_treatments"] = deepcopy(raw["evidence_treatments"])
        raw["evidence_treatments"][0]["intent"]["claim"] = "Substituted narrative claim"
    altered = ExecutableLayoutV2.model_validate(raw)
    with pytest.raises(ValueError, match="evidence|treatment"):
        _replay_split_chronology(altered, replace(before, at_ms=0), (action,), 5000, carrier)
