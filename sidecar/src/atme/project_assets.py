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
class VerifiedMediaBytes:
    asset_id: str
    revision: int
    payload: bytes
    sha256: str
    width: int
    height: int
    stream_json: str


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


def read_verified_image_bytes(service, project_id, resolved_asset, *, layout=None):
    """Resolve one owned PNG to immutable, checksum-verified bytes for v2.

    Existing attachment/read APIs remain unchanged. The render path never
    passes a host path to the compositor or hashes a different read from the
    bytes it later uses.
    """
    asset = ResolvedAsset.model_validate(resolved_asset)
    if layout is not None:
        from atme.store.contracts_v2 import (
            ExecutableLayoutV2,
            validate_image_asset_binding,
        )

        try:
            layout = ExecutableLayoutV2.model_validate(
                layout.model_dump(mode="json") if isinstance(layout, ExecutableLayoutV2) else layout)
            owners = [obj for obj in layout.objects if obj.object_type == "image" and obj.asset_id == asset.asset_id]
            if layout.project_id != project_id or not owners:
                raise ValueError("image_placement requires the matching project and image owner")
            for obj in owners:
                validate_image_asset_binding(obj, asset)
        except ValueError as exc:
            raise ProjectError("invalid_asset", str(exc)) from exc
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
            or layout is None and asset.allowed_transformations != ["scale"]):
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


def read_verified_media_bytes(service, project_id, resolved_asset, *, layout=None):
    """Read an owned original video once; never substitute its timing WAV.

    Duplicates share the root immutable file and retain independent active
    ownership. The origin row need not remain active in the original project.
    Authored stream pins are verified, not generated or repaired by this read.
    """
    from atme.project_media import MAX_VIDEO_BYTES
    from atme.render.v2_media import inspect_media
    from atme.store.contracts_v2 import (
        MEDIA_OBJECT_TYPES,
        ExecutableLayoutV2,
        validate_media_asset_binding,
    )

    try:
        asset = ResolvedAsset.model_validate(resolved_asset)
        layout = ExecutableLayoutV2.model_validate(
            layout.model_dump(mode="json") if isinstance(layout, ExecutableLayoutV2) else layout)
        owners = [obj for obj in layout.objects if obj.asset_id == asset.asset_id]
        if (type(project_id) is not int or project_id < 1 or layout.project_id != project_id
                or not owners or any(obj.object_type not in MEDIA_OBJECT_TYPES for obj in owners)):
            raise ValueError("Media requires its matching project and exact owners")
        for obj in owners:
            validate_media_asset_binding(obj, asset)
    except ValueError as exc:
        raise ProjectError("invalid_asset", str(exc)) from exc
    asset_id = asset.asset_id
    if (len(asset_id) != 32 or any(char not in "0123456789abcdef" for char in asset_id)
            or asset.managed_ref != f"atme://projects/{project_id}/assets/{asset_id}"
            or asset.kind not in MEDIA_OBJECT_TYPES or asset.media_stream is None
            or asset.byte_length is None or asset.byte_length < 1
            or asset.orientation != "upright" or asset.provenance_verified):
        raise ProjectError("invalid_asset", "Media has incomplete verified original metadata")
    content_types = {"mp4": "video/mp4", "mov": "video/quicktime",
                     "mkv": "video/x-matroska", "webm": "video/webm"}
    with service.store._lock:
        service._row(project_id)
        source = service.store.conn.execute(
            "SELECT m.*,r.media_id AS removed FROM project_source_media m "
            "LEFT JOIN project_media_removals r ON r.job_id=m.job_id AND r.media_id=m.media_id "
            "WHERE m.job_id=? AND m.media_id=?", (project_id, asset_id),
        ).fetchone()
        attachment = service.store.conn.execute(
            "SELECT * FROM project_assets WHERE job_id=? AND asset_id=?", (project_id, asset_id),
        ).fetchone()
        if (source is not None and attachment is not None
                or source is not None and source["removed"] is not None):
            raise ProjectError("asset_changed", "Media ownership is ambiguous or the source was removed")
        row = source if source is not None else attachment
        if row is None:
            raise ProjectError("not_found", "Original media does not belong to this project")
        try:
            metadata = json.loads(row["metadata"])
            metadata_json = json.dumps(metadata, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except ValueError as exc:
            raise ProjectError("asset_changed", "Original media metadata is invalid") from exc
        if not isinstance(metadata, dict):
            raise ProjectError("asset_changed", "Original media metadata is invalid")
        is_source = source is not None
        limit = MAX_VIDEO_BYTES if is_source else MAX_ASSET_BYTES
        namespace = "project-media" if is_source else "project-assets"
        relative = Path(row["relative_path"])
        extension = metadata.get("format")
        valid_shape = (len(relative.parts) == 3 and relative.parts[0] == namespace
                       and relative.parts[1].isdigit() and int(relative.parts[1]) > 0
                       and relative.parts[1] == str(int(relative.parts[1]))
                       and type(extension) is str and extension in content_types
                       and relative.parts[2] == asset_id + "." + extension)
        if relative.is_absolute() or not valid_shape:
            raise ProjectError("asset_changed", "Original media has an invalid managed path")
        origin_id = int(relative.parts[1])
        table, identity = (("project_source_media", "media_id") if is_source else ("project_assets", "asset_id"))
        origin = service.store.conn.execute(
            f"SELECT revision,relative_path,metadata FROM {table} WHERE job_id=? AND {identity}=?",
            (origin_id, asset_id),
        ).fetchone()
        try:
            origin_metadata = json.loads(origin["metadata"]) if origin is not None else None
            origin_json = json.dumps(origin_metadata, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except ValueError as exc:
            raise ProjectError("asset_changed", "Original media lineage metadata is invalid") from exc
        parent = service.store.db_path.resolve().parent
        root = parent / namespace
        directory = root / str(origin_id)
        lexical = parent / relative
        try:
            path = lexical.resolve()
            path_valid = (not _is_redirect(root) and not _is_redirect(directory) and not _is_redirect(lexical)
                          and root.resolve() == root and directory.resolve() == directory
                          and path.parent == directory and path.is_file())
        except OSError as exc:
            raise ProjectError("asset_changed", "Original media is unavailable") from exc
        if (origin is None or origin["revision"] != row["revision"]
                or origin["relative_path"] != row["relative_path"] or origin_json != metadata_json
                or row["revision"] != asset.revision or metadata.get(identity) != asset_id
                or type(metadata.get("bytes")) is not int or metadata["bytes"] != asset.byte_length
                or asset.byte_length > limit or metadata.get("sha256") != asset.checksum_sha256
                or asset.media_type != content_types[extension]
                or is_source and metadata.get("kind") != "video"
                or not is_source and (metadata.get("role") != "supporting_asset"
                                      or metadata.get("media_type") != asset.media_type)
                or not path_valid):
            raise ProjectError("asset_changed", "Original media failed ownership or lineage verification")
        try:
            with path.open("rb") as handle:
                raw = handle.read(limit + 1)
        except OSError as exc:
            raise ProjectError("asset_changed", "Original media is unavailable") from exc
    if len(raw) != asset.byte_length or hashlib.sha256(raw).hexdigest() != asset.checksum_sha256:
        raise ProjectError("asset_changed", "Original media failed immutable byte verification")
    try:
        checked = inspect_media(raw, asset.media_stream.stream_index)
        if checked.pin != asset.media_stream or checked.pin.duration_ms != asset.duration_ms:
            raise ValueError("Original media stream inventory differs from its authored pins")
    except ValueError as exc:
        raise ProjectError("invalid_asset", str(exc)) from exc
    return VerifiedMediaBytes(asset_id, asset.revision, raw, asset.checksum_sha256,
                              checked.pin.width, checked.pin.height, checked.stream_document)


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


def read_verified_split_asset_bytes(service, layout, resolved_assets, pins):
    """Private Split paint boundary: bind pins to stored ownership before reads.

    Existing public image/evidence APIs stay unchanged. No pin URI is inferred
    from a payload or from the evidence origin; the stored listing owns it.
    """
    from atme.render.v2_split_paint import (
        _freeze_verified_split_asset,
        _split_asset_treatments,
        _VerifiedSplitAssetBytes,
    )
    from atme.store.contracts_v2 import (
        MEDIA_OBJECT_TYPES,
        ExecutableLayoutV2,
        SplitAssetPin,
    )

    layout = ExecutableLayoutV2.model_validate(layout.model_dump(mode="json"))
    assets = [ResolvedAsset.model_validate(row) for row in resolved_assets]
    pins = [SplitAssetPin.model_validate(row) for row in pins]
    required = {obj.asset_id for obj in layout.objects if obj.asset_id is not None}
    by_id = {row.asset_id: row for row in assets}
    pin_by_id = {row.asset_id: row for row in pins}
    if (len(by_id) != len(assets) or len(pin_by_id) != len(pins)
            or set(by_id) != required or set(pin_by_id) != required):
        raise ValueError("Split asset pin inventory differs from layout")
    rows = []
    with service.store._lock:
        stored = {row["asset_id"]: row for row in list_assets(service, layout.project_id)}
        for key in sorted(required):
            asset, pin = by_id[key], pin_by_id[key]
            if asset.kind in MEDIA_OBJECT_TYPES:
                if (pin.resource_uri != asset.managed_ref or pin.revision != asset.revision
                        or pin.checksum_sha256 != asset.checksum_sha256):
                    raise ValueError("Media pin differs from its exact original binding")
                verified = read_verified_media_bytes(service, layout.project_id, asset, layout=layout)
                rows.append(_freeze_verified_split_asset(asset, pin, verified, layout=layout))
                continue
            owned = stored.get(key)
            if (owned is None or pin.resource_uri != owned["resource_uri"]
                    or pin.revision != owned["revision"] or pin.checksum_sha256 != owned["sha256"]
                    or asset.managed_ref != owned["managed_ref"]):
                raise ValueError("Split asset pin differs from the authoritative stored binding")
            treatments = _split_asset_treatments(layout, asset)
            if treatments:
                values = tuple(read_verified_evidence_bytes(service, layout.project_id, asset,
                    treatment.model_dump(mode="json")) for treatment in treatments)
                verified = values[0] if len(values) == 1 else values
            else:
                verified = read_verified_image_bytes(service, layout.project_id, asset, layout=layout)
            rows.append(_freeze_verified_split_asset(asset, pin, verified, layout=layout))
    return _VerifiedSplitAssetBytes(tuple(rows))


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
