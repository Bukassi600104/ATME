"""Stored Group/connection returns and duplicates keep real cleaned authority."""

from copy import deepcopy
from functools import partial

import pytest
from test_v2_annotation_action import append_target
from test_v2_connection_geometry import grouped_connection_documents
from test_v2_group_annotation import consumer_clock, private_svg
from test_v2_group_annotation_project import stored_group_annotation_return_basis
from v2_fixtures import digest

from atme.project_service import ProjectError
from atme.render import v2_svg
from atme.render.v2_state import UnsupportedVisualAction


def stored_connection_basis(tmp_path, *, regroup, portrait=False, stale=None, mutate=None):
    return stored_group_annotation_return_basis(
        tmp_path, regroup=regroup, portrait=portrait, stale=stale, mutate=mutate,
        document_builder=partial(grouped_connection_documents, routing="curve"),
    )


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("regroup", [False, True])
def test_stored_connection_return_and_duplicate_preserve_cleaned_source_and_offline_pixels(tmp_path, regroup, portrait, monkeypatch):
    import socket

    service, project, timeline = stored_connection_basis(tmp_path, regroup=regroup, portrait=portrait)
    pid = project["project_id"]
    source = deepcopy(service.source_timeline.get(pid))
    try:
        project = service.write(pid, "resolved_timeline", timeline, project["revision"])
        originals = {kind: deepcopy(service.artifact(pid, kind)["document"])
                     for kind in ("storyboard", "layout", "resolved_timeline")}
        returned = timeline["actions"][-1]
        assert returned["action"]["expected_object_states"]["object-arrow"] == "disconnected"
        # The untouched root arrow receives only the connect/disconnect versions.
        assert returned["action"]["expected_object_state_versions"]["object-arrow"] == 3
        duplicate = service.duplicate(pid)
        copied = {kind: service.artifact(duplicate["project_id"], kind)["document"] for kind in originals}
        assert copied["resolved_timeline"]["actions"] == originals["resolved_timeline"]["actions"]
        assert copied["resolved_timeline"]["layout_sha256"] == digest(copied["layout"])
        assert copied["resolved_timeline"]["plan_sha256"] == digest(copied["storyboard"])
        assert copied["resolved_timeline"]["cleaned_timeline_fingerprint"] == digest(
            service.source_timeline.get(duplicate["project_id"])["document"])

        def no_network(*args, **kwargs):
            raise AssertionError("stored connector frames must render offline")

        monkeypatch.setattr(socket, "socket", no_network)
        monkeypatch.setattr(socket, "create_connection", no_network)
        frames = []
        for documents in (originals, copied):
            context, replay, camera = consumer_clock(documents["layout"], documents["resolved_timeline"])
            result = {}
            for at in (6250, 6500, 7250, 7999, 8500, 9000):
                svg = private_svg(context, replay, camera, at)
                result[at] = v2_svg._rasterize_svg_frame(context.layout, svg).png
            assert result[6250] != result[6500] != result[7250]
            assert result[7999] == result[9000] != result[8500]
            assert v2_svg._rasterize_svg_frame(context.layout, private_svg(context, replay, camera, 6250)).png == result[6250]
            frames.append(result)
            with pytest.raises(UnsupportedVisualAction):
                v2_svg.compose_png_frame(documents["layout"], documents["resolved_timeline"], 6250)
        assert frames[0] == frames[1]
        assert service.source_timeline.get(pid) == source
        assert {kind: service.artifact(pid, kind)["document"] for kind in originals} == originals
    finally:
        service.store.close()


@pytest.mark.parametrize("regroup", [False, True])
@pytest.mark.parametrize("field", ["states", "state_versions"])
def test_stored_false_connector_return_claim_rejects_atomically(tmp_path, regroup, field):
    service, project, timeline = stored_connection_basis(tmp_path, regroup=regroup, stale=("object-arrow", field))
    original = deepcopy(service.open(project["project_id"]))
    try:
        with pytest.raises(ProjectError):
            service.write(project["project_id"], "resolved_timeline", timeline, project["revision"])
        assert service.open(project["project_id"]) == original
        with pytest.raises(ProjectError):
            service.artifact(project["project_id"], "resolved_timeline")
    finally:
        service.store.close()


@pytest.mark.parametrize("regroup", [False, True])
def test_stored_no_return_connector_rejects_unpaintable_bounds_before_revision_commit(tmp_path, regroup):
    def corrupt_geometry(layout, timeline):
        next(obj for obj in layout["objects"] if obj["object_id"] == "object-arrow")["geometry"]["bounds"] = {
            "x": 0, "y": 0, "width": 10, "height": 10}
        timeline["actions"] = [row for row in timeline["actions"] if row["action"]["verb"] != "return_board"]
        timeline["coverage"][2]["action_ids"].remove("return-1")

    service, project, timeline = stored_connection_basis(tmp_path, regroup=regroup, mutate=corrupt_geometry)
    original = deepcopy(service.open(project["project_id"]))
    try:
        with pytest.raises(ProjectError, match="exceeds authored bounds"):
            service.write(project["project_id"], "resolved_timeline", timeline, project["revision"])
        assert service.open(project["project_id"]) == original
    finally:
        service.store.close()


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("regroup", [False, True])
def test_stored_no_return_connector_proves_valid_full_history(tmp_path, regroup, portrait):
    def no_return(layout, timeline):
        timeline["actions"].pop()
        timeline["coverage"][2]["action_ids"].remove("return-1")

    service, project, timeline = stored_connection_basis(tmp_path, regroup=regroup, portrait=portrait, mutate=no_return)
    source = deepcopy(service.source_timeline.get(project["project_id"]))
    try:
        service.write(project["project_id"], "resolved_timeline", timeline, project["revision"])
        assert service.artifact(project["project_id"], "resolved_timeline")["document"] == timeline
        assert service.source_timeline.get(project["project_id"]) == source
    finally:
        service.store.close()


@pytest.mark.parametrize("before_return", [False, True])
def test_stored_connected_return_lifetime_obeys_resolved_order_not_shared_timestamp(tmp_path, before_return):
    def retained_connection(**kwargs):
        layout, timeline = grouped_connection_documents(**kwargs)
        timeline["actions"] = [row for row in timeline["actions"] if row["action"]["action_id"] != "action-4"]
        timeline["coverage"][2]["action_ids"].remove("action-4")
        return layout, timeline

    def later_endpoint_edit(layout, timeline):
        policy = next(row["action"]["hierarchy_policy"] for row in timeline["actions"]
                      if row["action"]["verb"] == "group")
        destination = deepcopy(next(row["local_transform"] for row in policy["destination_basis"]["placements"]
                                    if row["object_id"] == "object-system"))
        destination["position"]["x"] += 15
        append_target(timeline, "object-system", "move", 9000, 9200, destination=destination)
        if before_return:
            moved = timeline["actions"].pop()
            timeline["actions"].insert(-1, moved)

    service, project, timeline = stored_group_annotation_return_basis(
        tmp_path, regroup=True, document_builder=retained_connection, mutate=later_endpoint_edit)
    source = deepcopy(service.source_timeline.get(project["project_id"]))
    original = deepcopy(service.open(project["project_id"]))
    try:
        if before_return:
            with pytest.raises(ProjectError, match="connected lifetime"):
                service.write(project["project_id"], "resolved_timeline", timeline, project["revision"])
            assert service.open(project["project_id"]) == original
        else:
            service.write(project["project_id"], "resolved_timeline", timeline, project["revision"])
            assert service.artifact(project["project_id"], "resolved_timeline")["document"] == timeline
            layout = service.artifact(project["project_id"], "layout")["document"]
            with pytest.raises(ValueError, match="connected lifetime"):
                consumer_clock(layout, timeline)  # Full execution still proves the future edit.
        assert service.source_timeline.get(project["project_id"]) == source
    finally:
        service.store.close()
