"""Immutable supporting project assets; never treated as narrative authority."""
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
from atme.store.contracts_v2 import ResolvedAsset

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
        return [{**json.loads(row["metadata"]), "revision": row["revision"],
                 "resource_uri": f"atme://projects/{project_id}/assets/{json.loads(row['metadata'])['asset_id']}"}
                for row in rows]


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
