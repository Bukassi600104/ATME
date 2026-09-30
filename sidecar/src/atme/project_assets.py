"""Immutable project assets; supporting images and evidence have separate trust paths."""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from atme.project_service import ProjectError
from atme.render.v2_raster import MAX_SOURCE_BYTES, UnsupportedProjectPNG, canonical_png
from atme.store.contracts_v2 import EvidenceTreatment, Provenance, ResolvedAsset

MAX_ASSET_BYTES = 256 * 1024 * 1024
EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".pdf", ".md", ".txt", ".json",
    ".wav", ".mp3", ".m4a", ".aac", ".flac", ".mp4", ".mov", ".mkv", ".webm",
})


@dataclass(frozen=True)
class VerifiedImageBytes:
    asset_id: str
    revision: int
    payload: bytes
    sha256: str
    width: int
    height: int


@dataclass(frozen=True)
class VerifiedEvidenceBytes:
    asset_id: str
    revision: int
    payload: bytes
    sha256: str
    width: int
    height: int
    treatment: EvidenceTreatment


EVIDENCE_TRANSFORMATIONS = frozenset({
    "crop", "scale", "rotate", "mask", "annotate", "color_treatment",
})


def _is_redirect(path):
    return path.is_symlink() or path.is_junction()


def _evidence_provenance(document, source_sha256):
    try:
        provenance = Provenance.model_validate(document)
    except ValueError as exc:
        raise ProjectError("invalid_evidence", "Evidence provenance is incomplete") from exc
    if (provenance.category != "external_evidence"
            or not provenance.source_uri or not provenance.source_uri.strip()
            or provenance.checksum_sha256 != source_sha256
            or provenance.license_status == "unresolved"
            or not provenance.fabrication_prohibited
            or provenance.originality_status != "reference_only"):
        raise ProjectError("invalid_evidence", "Evidence needs a matching source declaration and resolved usage rights")
    return provenance


def attach_evidence_file(service, project_id, staged_file, filename, expected_revision,
                         provenance_document, allowed_transformations):
    """Ingest a declared external source as evidence, never as a supporting image.

    Provenance is a supplied attestation, not an ATME internet/research finding.
    The staged upload is copied into project ownership; callers retain originals.
    """
    staged = Path(staged_file)
    safe_name = Path(filename or "evidence.png").name
    if staged.suffix.lower() != ".part" and staged.suffix.lower() != ".png":
        raise ProjectError("invalid_evidence", "Evidence upload must be PNG")
    if Path(safe_name).suffix.lower() != ".png":
        raise ProjectError("invalid_evidence", "Evidence filename must end in .png")
    if _is_redirect(staged) or not staged.is_file():
        raise ProjectError("invalid_evidence", "Evidence PNG must be nonempty and at most 8 MiB")
    with staged.open("rb") as source:
        raw = source.read(MAX_SOURCE_BYTES + 1)
    if not 0 < len(raw) <= MAX_SOURCE_BYTES:
        raise ProjectError("invalid_evidence", "Evidence PNG must be nonempty and at most 8 MiB")
    try:
        raster = canonical_png(raw)
    except UnsupportedProjectPNG as exc:
        raise ProjectError("invalid_evidence", str(exc)) from exc
    provenance = _evidence_provenance(provenance_document, raster.source_sha256)
    if (not isinstance(allowed_transformations, list)
            or any(not isinstance(value, str) for value in allowed_transformations)
            or len(allowed_transformations) != len(set(allowed_transformations))
            or not {"crop", "scale"}.issubset(allowed_transformations)
            or not set(allowed_transformations).issubset(EVIDENCE_TRANSFORMATIONS)):
        raise ProjectError("invalid_evidence", "Evidence treatment permissions are invalid")
    asset_id = uuid4().hex
    metadata = {
        "asset_id": asset_id, "name": safe_name, "format": "png",
        "media_type": "image/png", "bytes": len(raw), "sha256": raster.source_sha256,
        "width": raster.width, "height": raster.height, "orientation": "upright",
        "role": "evidence_asset", "provenance": provenance.model_dump(mode="json"),
        "origin_project_id": project_id,
        "allowed_transformations": allowed_transformations,
    }
    parent = service.store.db_path.resolve().parent
    asset_root = parent / "project-assets"
    directory = asset_root / str(project_id)
    target = directory / (asset_id + ".png")
    created = False
    with service.store._lock:
        conn = service.store.conn
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = service._row(project_id)
            service._expected(row, expected_revision)
            if conn.execute("SELECT COUNT(*) FROM project_assets WHERE job_id=?", (project_id,)).fetchone()[0] >= 500:
                raise ProjectError("too_large", "This project already contains 500 assets")
            if (_is_redirect(asset_root) or _is_redirect(directory)
                    or (asset_root.exists() and asset_root.resolve() != asset_root)
                    or (directory.exists() and directory.resolve() != directory)):
                raise ProjectError("invalid_evidence", "Evidence storage redirects outside this project")
            directory.mkdir(parents=True, exist_ok=True)
            if directory.resolve() != directory:
                raise ProjectError("invalid_evidence", "Evidence storage redirects outside this project")
            # Write only the bytes validated above; never re-read an untrusted
            # staged path between checksum verification and immutable storage.
            with target.open("xb") as output:
                created = True
                output.write(raw)
            revision = row["revision"] + 1
            conn.execute("INSERT INTO project_assets VALUES(?,?,?,?,?)",
                         (project_id, asset_id, revision, str(target.relative_to(parent)),
                          json.dumps(metadata, sort_keys=True)))
            conn.execute("UPDATE project_state SET revision=? WHERE job_id=?", (revision, project_id))
            conn.commit()
        except Exception:
            conn.rollback()
            if (created and not _is_redirect(asset_root) and not _is_redirect(directory)
                    and asset_root.resolve() == asset_root
                    and directory.resolve() == directory
                    and not _is_redirect(target)):
                target.unlink(missing_ok=True)
            raise
    return {"project": service.open(project_id), "asset": {**metadata, "revision": revision,
            "resource_uri": f"atme://projects/{project_id}/assets/{asset_id}"}}


def read_verified_evidence_bytes(service, project_id, resolved_asset, treatment_document):
    """Bind an evidence treatment to one owned immutable PNG and return bytes only."""
    try:
        asset = ResolvedAsset.model_validate(resolved_asset)
        treatment = EvidenceTreatment.model_validate(treatment_document)
    except ValueError as exc:
        raise ProjectError("invalid_evidence", "Evidence render metadata is invalid") from exc
    asset_id = asset.asset_id
    expected_uri = f"atme://projects/{project_id}/assets/{asset_id}"
    origin_uri = treatment.asset_managed_ref
    if (not isinstance(project_id, int) or project_id < 1
            or len(asset_id) != 32 or any(char not in "0123456789abcdef" for char in asset_id)
            or treatment.intent.evidence_asset_id != asset_id
            or not origin_uri.startswith("atme://projects/")
            or asset.managed_ref != origin_uri
            or asset.kind != "evidence" or asset.media_type != "image/png"
            or asset.byte_length is None or asset.byte_length > MAX_SOURCE_BYTES
            or asset.width != treatment.asset_width or asset.height != treatment.asset_height
            or asset.orientation != "upright" or not asset.provenance_verified
            or asset.allowed_transformations != treatment.allowed_transformations
            or asset.revision != treatment.asset_revision
            or asset.checksum_sha256 != treatment.asset_checksum_sha256):
        raise ProjectError("invalid_evidence", "Evidence treatment and resolved asset disagree")
    with service.store._lock:
        service._row(project_id)
        row = service.store.conn.execute(
            "SELECT relative_path,metadata,revision FROM project_assets "
            "WHERE job_id=? AND asset_id=?", (project_id, asset_id),
        ).fetchone()
        if row is None:
            raise ProjectError("not_found", "Evidence asset does not belong to this project")
        metadata = json.loads(row["metadata"])
        parent = service.store.db_path.resolve().parent
        relative = Path(row["relative_path"])
        asset_root = parent / "project-assets"
        valid_shape = (len(relative.parts) == 3
                       and relative.parts[0] == "project-assets"
                       and relative.parts[1].isdigit()
                       and int(relative.parts[1]) > 0
                       and relative.parts[2] == asset_id + ".png")
        origin_id = int(relative.parts[1]) if valid_shape else None
        row_uri = f"atme://projects/{origin_id}/assets/{asset_id}"
        origin_directory = asset_root / str(origin_id) if origin_id is not None else asset_root
        lexical_path = parent / relative
        path = lexical_path.resolve()
        declared = treatment.asset_provenance.model_dump(mode="json")
        if (relative.is_absolute() or not valid_shape
                or _is_redirect(asset_root) or _is_redirect(origin_directory)
                or _is_redirect(lexical_path)
                or asset_root.resolve() != asset_root
                or origin_directory.resolve() != origin_directory
                or not path.is_relative_to(asset_root)
                or path.parent != asset_root / relative.parts[1]
                or not path.is_file()
                or row["revision"] != asset.revision
                or metadata.get("asset_id") != asset_id
                or metadata.get("origin_project_id") != origin_id
                or origin_uri != row_uri
                or (origin_id == project_id and origin_uri != expected_uri)
                or metadata.get("role") != "evidence_asset"
                or metadata.get("format") != "png"
                or metadata.get("media_type") != "image/png"
                or metadata.get("bytes") != asset.byte_length
                or metadata.get("sha256") != asset.checksum_sha256
                or metadata.get("width") != asset.width
                or metadata.get("height") != asset.height
                or metadata.get("orientation") != "upright"
                or metadata.get("allowed_transformations") != treatment.allowed_transformations
                or metadata.get("provenance") != declared):
            raise ProjectError("asset_changed", "Evidence failed ownership or declaration verification")
        with path.open("rb") as handle:
            raw = handle.read(MAX_SOURCE_BYTES + 1)
    if len(raw) != asset.byte_length or hashlib.sha256(raw).hexdigest() != asset.checksum_sha256:
        raise ProjectError("asset_changed", "Evidence failed immutable byte verification")
    try:
        raster = canonical_png(raw)
    except UnsupportedProjectPNG as exc:
        raise ProjectError("invalid_evidence", str(exc)) from exc
    if (raster.width, raster.height) != (asset.width, asset.height):
        raise ProjectError("asset_changed", "Evidence source dimensions changed")
    return VerifiedEvidenceBytes(asset_id, asset.revision, raw, asset.checksum_sha256,
                                 raster.width, raster.height, treatment)


def read_verified_image_bytes(service, project_id, resolved_asset):
    """Resolve one owned PNG to immutable, checksum-verified bytes for v2.

    Existing attachment/read APIs remain unchanged. The render path never
    passes a host path to the compositor or hashes a different read from the
    bytes it later uses.
    """
    asset = ResolvedAsset.model_validate(resolved_asset)
    asset_id = asset.asset_id
    expected_uri = f"atme://projects/{project_id}/assets/{asset_id}"
    if (not isinstance(project_id, int) or project_id < 1
            or len(asset_id) != 32 or any(char not in "0123456789abcdef" for char in asset_id)
            or asset.managed_ref != expected_uri
            or asset.kind not in {"image", "source_image"}
            or asset.media_type != "image/png"
            or asset.byte_length is None or asset.byte_length > MAX_SOURCE_BYTES
            or asset.width is None or asset.height is None
            or asset.orientation != "upright"
            # A supporting attachment proves ownership/integrity, not external
            # provenance or a plan-granted transformation permission.
            or asset.provenance_verified
            or asset.allowed_transformations != ["scale"]):
        raise ProjectError("invalid_asset", "Project image has incomplete verified render metadata")
    with service.store._lock:
        service._row(project_id)
        row = service.store.conn.execute(
            "SELECT relative_path,metadata,revision FROM project_assets "
            "WHERE job_id=? AND asset_id=?", (project_id, asset_id),
        ).fetchone()
        if row is None:
            raise ProjectError("not_found", "Project image does not belong to this project")
        metadata = json.loads(row["metadata"])
        parent = service.store.db_path.resolve().parent
        relative = Path(row["relative_path"])
        asset_root = (parent / "project-assets").resolve()
        # Duplicate projects share the original immutable managed file. Its
        # own DB row still binds asset ID, revision, size and checksum.
        valid_managed_shape = (len(relative.parts) == 3
                               and relative.parts[0] == "project-assets"
                               and relative.parts[1].isdigit()
                               and int(relative.parts[1]) > 0
                               and relative.parts[2] == asset_id + ".png")
        path = (parent / relative).resolve()
        if (relative.is_absolute() or not valid_managed_shape
                or not path.is_relative_to(asset_root)
                or path.parent != asset_root / relative.parts[1]
                or not path.is_file()
                or row["revision"] != asset.revision
                or metadata.get("asset_id") != asset_id
                or metadata.get("role") != "supporting_asset"
                or metadata.get("format") != "png"
                or metadata.get("media_type") != "image/png"
                or metadata.get("sha256") != asset.checksum_sha256
                or metadata.get("bytes") != asset.byte_length):
            raise ProjectError("asset_changed", "Project image failed ownership or integrity verification")
        with path.open("rb") as handle:
            raw = handle.read(MAX_SOURCE_BYTES + 1)
    if len(raw) != asset.byte_length or hashlib.sha256(raw).hexdigest() != asset.checksum_sha256:
        raise ProjectError("asset_changed", "Project image failed integrity verification")
    try:
        canonical = canonical_png(raw)
    except UnsupportedProjectPNG as exc:
        raise ProjectError("invalid_asset", str(exc)) from exc
    if (canonical.width, canonical.height) != (asset.width, asset.height):
        raise ProjectError("asset_changed", "Project image dimensions changed")
    return VerifiedImageBytes(asset_id, asset.revision, raw, asset.checksum_sha256,
                              canonical.width, canonical.height)


def attach_asset_file(service, project_id, staged_file, filename, expected_revision):
    staged = Path(staged_file)
    safe_name = Path(filename or "asset").name
    extension = Path(safe_name).suffix.lower()
    if extension not in EXTENSIONS:
        raise ProjectError("invalid_asset", "Unsupported project asset format")
    if not staged.is_file() or not 0 < staged.stat().st_size <= MAX_ASSET_BYTES:
        raise ProjectError("invalid_asset", "Project asset must be nonempty and at most 256 MiB")
    asset_id = uuid4().hex
    media_type = mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
    metadata = {"asset_id": asset_id, "name": safe_name, "format": extension[1:],
                "media_type": media_type, "bytes": staged.stat().st_size,
                "sha256": _sha256(staged), "role": "supporting_asset"}
    parent = service.store.db_path.resolve().parent
    directory = (parent / "project-assets" / str(project_id)).resolve()
    if not directory.is_relative_to(parent):
        raise ProjectError("invalid_asset", "Asset storage escaped project data")
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (asset_id + extension)
    with service.store._lock:
        conn = service.store.conn
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = service._row(project_id)
            service._expected(row, expected_revision)
            if conn.execute("SELECT COUNT(*) FROM project_assets WHERE job_id=?", (project_id,)).fetchone()[0] >= 500:
                raise ProjectError("too_large", "This project already contains 500 supporting assets")
            os.replace(staged, target)
            revision = row["revision"] + 1
            conn.execute("INSERT INTO project_assets VALUES(?,?,?,?,?)",
                         (project_id, asset_id, revision, str(target.relative_to(parent)), json.dumps(metadata)))
            conn.execute("UPDATE project_state SET revision=? WHERE job_id=?", (revision, project_id))
            conn.commit()
        except Exception:
            conn.rollback()
            target.unlink(missing_ok=True)
            raise
    return {"project": service.open(project_id), "asset": {**metadata, "revision": revision}}


def list_assets(service, project_id):
    with service.store._lock:
        service._row(project_id)
        rows = service.store.conn.execute(
            "SELECT metadata,revision FROM project_assets WHERE job_id=? ORDER BY revision", (project_id,)).fetchall()
        result = []
        for row in rows:
            metadata = json.loads(row["metadata"])
            asset_id = metadata["asset_id"]
            current_uri = f"atme://projects/{project_id}/assets/{asset_id}"
            origin_id = metadata.get("origin_project_id", project_id)
            managed_ref = (f"atme://projects/{origin_id}/assets/{asset_id}"
                           if metadata.get("role") == "evidence_asset" else current_uri)
            result.append({**metadata, "revision": row["revision"],
                           "resource_uri": current_uri, "managed_ref": managed_ref})
        return result


def read_asset(service, project_id, asset_id, max_bytes=None):
    if not isinstance(asset_id, str) or len(asset_id) != 32:
        raise ProjectError("invalid_request", "Invalid asset ID")
    with service.store._lock:
        service._row(project_id)
        row = service.store.conn.execute(
            "SELECT relative_path,metadata,revision FROM project_assets WHERE job_id=? AND asset_id=?",
            (project_id, asset_id)).fetchone()
    if row is None:
        raise ProjectError("not_found", "Project asset does not exist")
    metadata = json.loads(row["metadata"])
    parent = service.store.db_path.resolve().parent
    path = (parent / row["relative_path"]).resolve()
    if not path.is_relative_to(parent) or not path.is_file() or _sha256(path) != metadata["sha256"]:
        raise ProjectError("asset_changed", "Project asset failed integrity verification")
    if max_bytes is not None and path.stat().st_size > max_bytes:
        raise ProjectError("too_large", "Asset is too large for this transfer")
    return path, {**metadata, "revision": row["revision"]}


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
