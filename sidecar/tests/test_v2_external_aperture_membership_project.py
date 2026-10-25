"""Real stored dynamic aperture reads use the same public frame history."""
from copy import deepcopy

import pytest
from atme.project_service import ProjectError, _resolved_compilation_fingerprint
from atme.render import v2_svg
from atme.render.v2_state import evaluate_frame
from atme.store import contracts_v2 as contracts
from test_v2_external_aperture_membership import membership_documents
from test_v2_external_aperture_runtime import runtime_documents
from test_v2_group_annotation import consumer_clock, private_svg
from test_v2_registry_project import history
from test_v2_resolved_project import stored_v2_basis
from v2_fixtures import digest


def stored_membership(tmp_path, kind, *, portrait=False, ungroup=False, live=False):
    profile = "SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9"
    service, project, original, _old_layout, _old_clock = stored_v2_basis(tmp_path, profile=profile)
    layout, clock, ids, _reference = membership_documents(kind, portrait=portrait, ungroup=ungroup, live=live)
    plan = runtime_documents(kind, portrait=portrait, group=True)[0]
    fields = set(contracts.SemanticStandardObjectSpec.model_fields) | set(contracts.SemanticMaskObjectSpec.model_fields)
    plan.update(project_id=project["project_id"], project_revision=project["revision"],
                narrative_authority=deepcopy(original["narrative_authority"]), boards=deepcopy(layout["boards"]),
                actions=[deepcopy(row["action"]) for row in clock["actions"]], coverage=deepcopy(clock["coverage"]))
    plan["objects"] = [{key: deepcopy(value) for key, value in obj.items()
                        if key in fields and (key != "clip_id" or value is not None)} for obj in layout["objects"]]
    # Semantic child_ids is nonempty when present. The existing explicit
    # empty-shell owner receipt + complete Group policy declares this case.
    owned_empty = {row["shell_object_id"] for row in layout.get("initial_empty_group_ownership", [])}
    for obj in plan["objects"]:
        if obj["object_id"] in owned_empty and obj.get("child_ids") == []:
            obj.pop("child_ids")
    beat = plan["beats"][0]
    beat.update(object_ids=[obj["object_id"] for obj in plan["objects"]],
                action_ids=[row["action_id"] for row in plan["actions"]])
    contracts.VisualPlanV2.model_validate(plan)
    project = service.write(project["project_id"], "storyboard", plan, project["revision"])
    layout.update(project_id=project["project_id"], project_revision=project["revision"],
                  plan_revision=project["artifacts"]["storyboard"], plan_sha256=digest(plan))
    project = service.write(project["project_id"], "layout", layout, project["revision"])
    timing = service.source_timeline.get(project["project_id"])
    clock.update(project_id=project["project_id"], project_revision=project["revision"],
                 plan_revision=project["artifacts"]["storyboard"], plan_sha256=digest(plan),
                 layout_revision=project["artifacts"]["layout"], layout_sha256=digest(layout),
                 cleaned_timeline_revision=timing["timeline_revision"],
                 cleaned_timeline_fingerprint=digest(timing["document"]))
    clock["compilation_fingerprint"] = _resolved_compilation_fingerprint(clock)
    return service, project, clock, ids


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["clip", "mask"])
@pytest.mark.parametrize("ungroup", [False, True])
def test_real_membership_write_duplicate_preserves_cleaned_authority_and_public_pixels(tmp_path, kind, portrait, ungroup, monkeypatch):
    import socket

    service, project, clock, ids = stored_membership(tmp_path, kind, portrait=portrait, ungroup=ungroup)
    try:
        pid = project["project_id"]
        source = deepcopy(service.source_timeline.get(pid))
        service.write(pid, "resolved_timeline", clock, project["revision"])
        originals = {key: deepcopy(service.artifact(pid, key)["document"])
                     for key in ("storyboard", "layout", "resolved_timeline")}
        before = history(service, pid)
        duplicate = service.duplicate(pid)
        copied = {key: service.artifact(duplicate["project_id"], key)["document"] for key in originals}
        assert copied["resolved_timeline"]["actions"] == clock["actions"]
        assert copied["resolved_timeline"]["cleaned_timeline_fingerprint"] == digest(
            service.source_timeline.get(duplicate["project_id"])["document"])

        def no_network(*args, **kwargs):
            raise AssertionError("stored membership frames must remain offline")

        monkeypatch.setattr(socket, "create_connection", no_network)
        monkeypatch.setattr(socket.socket, "connect", no_network)
        frames = []
        for documents in (originals, copied):
            context, replay, camera = consumer_clock(documents["layout"], documents["resolved_timeline"])
            assert replay.at(2500).hierarchy.object_map(context.objects)[ids["receiver"]].clip_id == ids["aperture"]
            rendered = []
            for at in (4500, 1500, 2500, 4500):
                svg = private_svg(context, replay, camera, at)
                rendered.append((svg.svg, v2_svg._rasterize_svg_frame(context.layout, svg).png))
            frames.append(rendered)
            assert evaluate_frame(documents["layout"], documents["resolved_timeline"], 2500).at_ms == 2500
            assert v2_svg.compose_svg_frame(
                documents["layout"], documents["resolved_timeline"], 2500).svg == rendered[2][0]
            assert v2_svg.compose_png_frame(
                documents["layout"], documents["resolved_timeline"], 2500).png == rendered[2][1]
        assert frames[0] == frames[1]
        assert service.source_timeline.get(pid) == source
        assert history(service, pid) == before
    finally:
        service.store.close()


@pytest.mark.parametrize("kind", ["clip", "mask"])
def test_real_membership_positive_paint_conflict_rejects_atomically(tmp_path, kind):
    service, project, clock, _ids = stored_membership(tmp_path, kind, live=True)
    try:
        pid = project["project_id"]
        before = deepcopy((service.open(pid), history(service, pid), service.source_timeline.get(pid)))
        with pytest.raises(ProjectError) as failure:
            service.write(pid, "resolved_timeline", clock, project["revision"])
        assert failure.value.code == "invalid_artifact"
        assert "read lifetime conflicts" in str(failure.value)
        assert (service.open(pid), history(service, pid), service.source_timeline.get(pid)) == before
    finally:
        service.store.close()
