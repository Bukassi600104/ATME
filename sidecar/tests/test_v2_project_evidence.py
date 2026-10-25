"""Evidence PNG attestation is independent of ordinary supporting images."""

from __future__ import annotations

import hashlib
import io
import json
import os
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from test_project_runner import ready_project
from v2_fixtures import digest, executable_layout_v2, visual_plan_v2

from atme.narrative_source import describe
from atme.project_service import ProjectError, ProjectService
from atme.server.app import create_app
from atme.store.db import JobStore


def _png(size=(900, 500), color=(40, 90, 180, 255)):
    output = io.BytesIO()
    Image.new("RGBA", size, color).save(output, format="PNG")
    return output.getvalue()


def _provenance(raw):
    return {
        "category": "external_evidence", "source_uri": "https://example.com/source",
        "checksum_sha256": hashlib.sha256(raw).hexdigest(),
        "license_status": "licensed", "fabrication_prohibited": True,
        "originality_status": "reference_only",
    }


def _owned_evidence(tmp_path):
    service = ProjectService(JobStore(tmp_path / "evidence.db"))
    pid = service.create("Evidence", "LONG_FORM_16_9", "idea-first")["project_id"]
    raw = _png()
    staged = tmp_path / "original.png"
    staged.write_bytes(raw)
    permissions = ["crop", "scale", "annotate", "color_treatment"]
    asset = service.attach_evidence_file(pid, staged, "original.png", 0,
                                         _provenance(raw), permissions)["asset"]
    assert staged.read_bytes() == raw  # an external original is not moved/deleted
    treatment = executable_layout_v2(visual_plan_v2())["evidence_treatments"][0]
    treatment["intent"]["evidence_asset_id"] = asset["asset_id"]
    treatment.update(asset_revision=asset["revision"],
                     asset_checksum_sha256=asset["sha256"],
                     asset_managed_ref=asset["resource_uri"],
                     asset_provenance=asset["provenance"])
    resolved = {
        "asset_id": asset["asset_id"], "revision": asset["revision"],
        "managed_ref": asset["resource_uri"], "checksum_sha256": asset["sha256"],
        "provenance_verified": True, "kind": "evidence", "media_type": "image/png",
        "byte_length": asset["bytes"], "width": asset["width"], "height": asset["height"],
        "orientation": "upright", "allowed_transformations": permissions,
    }
    return service, pid, raw, resolved, treatment


def test_project_owned_evidence_resolves_only_with_matching_treatment(tmp_path):
    service, pid, raw, resolved, treatment = _owned_evidence(tmp_path)
    verified = service.render_evidence_bytes(pid, resolved, treatment)
    assert verified.payload == raw
    assert verified.treatment.intent.source_label == treatment["intent"]["source_label"]
    assert service.render_evidence_bytes(pid, resolved, treatment).payload == raw
    service.store.close()


@pytest.mark.parametrize("field,value", [
    ("kind", "image"), ("provenance_verified", False), ("media_type", "image/jpeg"),
    ("orientation", None), ("width", 899), ("height", 499),
    ("byte_length", 1), ("revision", 99),
    ("allowed_transformations", ["scale"]),
])
def test_resolver_rejects_mutated_resolved_metadata(tmp_path, field, value):
    service, pid, _, resolved, treatment = _owned_evidence(tmp_path)
    resolved[field] = value
    with pytest.raises(ProjectError, match="disagree|declaration"):
        service.render_evidence_bytes(pid, resolved, treatment)
    service.store.close()


def test_resolver_rejects_cross_project_and_supporting_substitution(tmp_path):
    service, pid, raw, resolved, treatment = _owned_evidence(tmp_path)
    other = service.create("Other", "LONG_FORM_16_9", "idea-first")["project_id"]
    with pytest.raises(ProjectError):
        service.render_evidence_bytes(other, resolved, treatment)
    staged = tmp_path / "support.png"
    staged.write_bytes(raw)
    supporting = service.attach_asset_file(pid, staged, "support.png", 1)["asset"]
    substitute = deepcopy(resolved)
    substitute.update(asset_id=supporting["asset_id"], revision=supporting["revision"],
                      managed_ref=f"atme://projects/{pid}/assets/{supporting['asset_id']}")
    substituted_treatment = deepcopy(treatment)
    substituted_treatment["intent"]["evidence_asset_id"] = supporting["asset_id"]
    substituted_treatment.update(asset_revision=supporting["revision"],
                                 asset_managed_ref=substitute["managed_ref"])
    with pytest.raises(ProjectError, match="declaration"):
        service.render_evidence_bytes(pid, substitute, substituted_treatment)
    service.store.close()


def test_resolver_rejects_row_metadata_path_and_bytes_tampering(tmp_path):
    service, pid, raw, resolved, treatment = _owned_evidence(tmp_path)
    asset_id = resolved["asset_id"]
    with service.store._lock:
        row = service.store.conn.execute(
            "SELECT relative_path,metadata FROM project_assets WHERE job_id=? AND asset_id=?",
            (pid, asset_id),
        ).fetchone()
        metadata = json.loads(row["metadata"])
        changed = deepcopy(metadata)
        changed["provenance"]["source_uri"] = "https://example.com/other"
        service.store.conn.execute(
            "UPDATE project_assets SET metadata=? WHERE job_id=? AND asset_id=?",
            (json.dumps(changed), pid, asset_id),
        )
        service.store.conn.commit()
    with pytest.raises(ProjectError, match="declaration"):
        service.render_evidence_bytes(pid, resolved, treatment)
    with service.store._lock:
        service.store.conn.execute(
            "UPDATE project_assets SET metadata=?,relative_path=? WHERE job_id=? AND asset_id=?",
            (json.dumps(metadata), "../../outside.png", pid, asset_id),
        )
        service.store.conn.commit()
    with pytest.raises(ProjectError, match="declaration"):
        service.render_evidence_bytes(pid, resolved, treatment)
    with service.store._lock:
        service.store.conn.execute(
            "UPDATE project_assets SET relative_path=? WHERE job_id=? AND asset_id=?",
            (row["relative_path"], pid, asset_id),
        )
        service.store.conn.commit()
    path, _ = service.asset(pid, asset_id)
    path.write_bytes(_png(color=(1, 2, 3, 255)))
    with pytest.raises(ProjectError, match="byte"):
        service.render_evidence_bytes(pid, resolved, treatment)
    assert raw != path.read_bytes()
    service.store.close()


def test_evidence_declaration_and_png_are_strict(tmp_path):
    service = ProjectService(JobStore(tmp_path / "evidence.db"))
    pid = service.create("Evidence", "LONG_FORM_16_9", "idea-first")["project_id"]
    raw = _png()
    staged = tmp_path / "source.png"
    staged.write_bytes(raw)
    for change in ({"checksum_sha256": "a" * 64}, {"license_status": "unresolved"},
                   {"fabrication_prohibited": False}, {"originality_status": "unresolved"}):
        with pytest.raises(ProjectError, match="declaration"):
            service.attach_evidence_file(pid, staged, "source.png", 0,
                                         {**_provenance(raw), **change}, ["crop", "scale"])
    with pytest.raises(ProjectError, match="permissions"):
        service.attach_evidence_file(pid, staged, "source.png", 0,
                                     _provenance(raw), ["scale"])
    staged.write_bytes(b"not PNG")
    with pytest.raises(ProjectError, match="PNG"):
        service.attach_evidence_file(pid, staged, "source.png", 0,
                                     _provenance(raw), ["crop", "scale"])
    service.store.close()


def test_duplicate_project_keeps_immutable_evidence_resolution(tmp_path):
    service, pid, raw, resolved, treatment = _owned_evidence(tmp_path)
    copy_id = service.duplicate(pid)["project_id"]
    assert service.render_evidence_bytes(copy_id, resolved, treatment).payload == raw
    service.store.close()


def test_authenticated_evidence_upload_route_and_asset_listing(tmp_path):
    service = ProjectService(JobStore(tmp_path / "http.db"))
    pid = service.create("Evidence", "LONG_FORM_16_9", "idea-first")["project_id"]
    http = TestClient(create_app("local-test", type("Runtime", (), {"store": service.store})()))
    raw = _png()
    headers = {
        "Authorization": "Bearer local-test",
        "x-filename": "source.png",
        "x-evidence-provenance": json.dumps(_provenance(raw)),
        "x-evidence-transformations": json.dumps(["crop", "scale"]),
    }
    unauthenticated = http.post(f"/projects/{pid}/evidence-assets?expected_revision=0",
                                content=raw, headers={key: value for key, value in headers.items()
                                                      if key != "Authorization"})
    assert unauthenticated.status_code == 401
    uploaded = http.post(f"/projects/{pid}/evidence-assets?expected_revision=0",
                         content=raw, headers=headers)
    assert uploaded.status_code == 200, uploaded.text
    asset = uploaded.json()["asset"]
    assert asset["role"] == "evidence_asset"
    assert asset["provenance"] == _provenance(raw)
    listed = http.get(f"/projects/{pid}/assets", headers={"Authorization": "Bearer local-test"})
    assert listed.status_code == 200
    assert listed.json()["assets"][0]["asset_id"] == asset["asset_id"]
    service.store.close()


def test_evidence_size_bound_and_stale_revision_do_not_create_project_files(tmp_path):
    service = ProjectService(JobStore(tmp_path / "bounded.db"))
    pid = service.create("Evidence", "LONG_FORM_16_9", "idea-first")["project_id"]
    staged = tmp_path / "too-large.png"
    with staged.open("wb") as output:
        output.truncate(8 * 1024 * 1024 + 1)
    with pytest.raises(ProjectError, match="8 MiB"):
        service.attach_evidence_file(pid, staged, "too-large.png", 0,
                                     _provenance(b""), ["crop", "scale"])
    raw = _png()
    staged.write_bytes(raw)
    with pytest.raises(ProjectError) as failure:
        service.attach_evidence_file(pid, staged, "source.png", 99,
                                     _provenance(raw), ["crop", "scale"])
    assert failure.value.code == "revision_conflict"
    assert not (tmp_path / "project-assets" / str(pid)).exists()
    service.store.close()


def test_project_directory_redirect_is_rejected(tmp_path):
    service = ProjectService(JobStore(tmp_path / "redirect.db"))
    pid = service.create("Evidence", "LONG_FORM_16_9", "idea-first")["project_id"]
    root = tmp_path / "project-assets"
    root.mkdir()
    other = root / "999"
    other.mkdir()
    redirected = root / str(pid)
    try:
        os.symlink(other, redirected, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks are unavailable on this host")
    raw = _png()
    staged = tmp_path / "source.png"
    staged.write_bytes(raw)
    with pytest.raises(ProjectError, match="redirects"):
        service.attach_evidence_file(pid, staged, "source.png", 0,
                                     _provenance(raw), ["crop", "scale"])
    assert list(other.iterdir()) == []
    service.store.close()


@pytest.mark.parametrize("level", ["root", "origin"])
@pytest.mark.parametrize("duplicate", [False, True])
def test_resolver_rejects_redirected_ancestor_after_ingest(tmp_path, level, duplicate):
    service, pid, _, resolved, treatment = _owned_evidence(tmp_path)
    target_id = service.duplicate(pid)["project_id"] if duplicate else pid
    root = tmp_path / "project-assets"
    original = root if level == "root" else root / str(pid)
    moved = tmp_path / ("relocated-root" if level == "root" else "relocated-origin")
    original.rename(moved)
    try:
        os.symlink(moved, original, target_is_directory=True)
    except (OSError, NotImplementedError):
        moved.rename(original)
        service.store.close()
        pytest.skip("directory symlinks are unavailable on this host")
    with pytest.raises(ProjectError, match="ownership|declaration"):
        service.render_evidence_bytes(target_id, resolved, treatment)
    service.store.close()


def test_duplicate_rebinds_stored_v2_plan_layout_and_keeps_evidence_origin(tmp_path):
    service, project = ready_project(tmp_path)
    pid = project["project_id"]
    raw = _png()
    staged = tmp_path / "source.png"
    staged.write_bytes(raw)
    asset = service.attach_evidence_file(
        pid, staged, "source.png", project["revision"], _provenance(raw),
        ["crop", "scale", "annotate", "color_treatment"],
    )["asset"]
    project = service.open(pid)
    plan = visual_plan_v2(project["revision"])
    plan["project_id"] = pid
    media = describe(service, pid)["timing_authority"]["media"]
    cleaned = service.source_timeline.get(pid)
    plan["narrative_authority"].update(
        mode="approved_script_plus_recording", authority_id="script-revision-1",
        timing_media_id=media["media_id"], timing_media_sha256=media["sha256"],
        cleaned_timeline_revision=cleaned["timeline_revision"],
        cleaned_timeline_fingerprint=digest(cleaned["document"]),
    )
    plan["assets"][0].update(
        asset_id=asset["asset_id"], revision=asset["revision"],
        managed_ref=asset["resource_uri"], checksum_sha256=asset["sha256"],
        width=asset["width"], height=asset["height"], provenance=asset["provenance"],
    )
    plan["objects"][2]["asset_id"] = asset["asset_id"]
    plan["actions"][2]["evidence_asset_id"] = asset["asset_id"]
    plan["beats"][1]["evidence"]["evidence_asset_id"] = asset["asset_id"]
    project = service.write(pid, "storyboard", plan, project["revision"])
    layout = executable_layout_v2(plan)
    next(obj for obj in layout["objects"] if obj["object_type"] == "evidence")["asset_id"] = asset["asset_id"]
    layout.update(project_id=pid, project_revision=project["revision"],
                  plan_revision=project["revision"], plan_sha256=digest(plan))
    project = service.write(pid, "layout", layout, project["revision"])
    copy_id = service.duplicate(pid)["project_id"]
    cloned_plan = service.artifact(copy_id, "storyboard")["document"]
    cloned_layout = service.artifact(copy_id, "layout")["document"]
    assert cloned_plan["project_id"] == cloned_layout["project_id"] == copy_id
    assert cloned_layout["plan_sha256"] == digest(cloned_plan)
    treatment = cloned_layout["evidence_treatments"][0]
    assert treatment["asset_managed_ref"] == asset["resource_uri"]
    copied_asset = service.list_assets(copy_id)[0]
    assert copied_asset["resource_uri"] == f"atme://projects/{copy_id}/assets/{asset['asset_id']}"
    assert copied_asset["managed_ref"] == asset["resource_uri"]
    resolved = {
        "asset_id": asset["asset_id"], "revision": asset["revision"],
        "managed_ref": copied_asset["managed_ref"], "checksum_sha256": asset["sha256"],
        "provenance_verified": True, "kind": "evidence", "media_type": "image/png",
        "byte_length": asset["bytes"], "width": asset["width"], "height": asset["height"],
        "orientation": "upright", "allowed_transformations": asset["allowed_transformations"],
    }
    assert service.render_evidence_bytes(copy_id, resolved, treatment).payload == raw
    service.store.close()
