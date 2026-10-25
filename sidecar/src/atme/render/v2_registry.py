"""Pure placement of caller-verified registry art and named semantic anchors.

No resource lookup lives here. Placement callers supply verified metadata;
checked_registry_art explicitly binds metadata and art to immutable bytes.
SVG fitting uses serialized viewport bounds; implicit fit math stays full
precision until an endpoint is serialized.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from atme.render.style_bundle import EXPECTED_REGISTRY_SHA256, _validate_svg
from atme.render.style_contracts import AssetEntry, AssetProvenance, AssetRegistry
from atme.render.v2_world import _q, world_anchor, world_matrix
from atme.store.contracts_v2 import (
    Bounds,
    ClipContainer,
    ContainerObject,
    GroupContainer,
    MaskContainer,
    RegistryAnchorMapping,
    RegistryBinding,
    SemanticStandardObjectSpec,
    VisualObject,
)

SUPPORTED_REGISTRY_VISUALS = {
    "icon": frozenset({"people", "gestures", "devices", "documents", "networks",
                       "charts", "technical-frames", "abstract-metaphors"}),
    "pictogram": frozenset({"people", "gestures", "devices", "documents", "networks",
                            "charts", "technical-frames", "abstract-metaphors"}),
    "character": frozenset({"people"}),
    "device": frozenset({"devices"}),
    "document": frozenset({"documents"}),
    "chart": frozenset({"charts"}),
    "terminal": frozenset({"technical-frames"}),
}


class UnsupportedRegistryPlacement(ValueError):
    """Registry metadata and authored placement cannot agree faithfully."""


@dataclass(frozen=True)
class RegistryEndpointInputs:
    """Immutable byte evidence, not cached metadata or a visibility assertion."""
    registry_payload: bytes
    artworks: tuple[tuple[str, bytes], ...]


def _registry_endpoint_assets(inputs) -> dict[str, AssetEntry]:
    if inputs is None:
        raise UnsupportedRegistryPlacement("registry endpoint requires verified inputs")
    if (type(inputs) is not RegistryEndpointInputs
            or set(inputs.__dict__) != {"registry_payload", "artworks"}
            or type(inputs.registry_payload) is not bytes or type(inputs.artworks) is not tuple):
        raise UnsupportedRegistryPlacement("requires exact immutable registry endpoint inputs")
    if sha256(inputs.registry_payload).hexdigest() != EXPECTED_REGISTRY_SHA256:
        raise UnsupportedRegistryPlacement("registry metadata checksum mismatch")
    keys = []
    result = {}
    for row in inputs.artworks:
        if (type(row) is not tuple or len(row) != 2 or type(row[0]) is not str
                or type(row[1]) is not bytes or row[0] in result):
            raise UnsupportedRegistryPlacement("requires exact immutable registry endpoint inputs")
        keys.append(row[0])
        result[row[0]], _ = checked_registry_art(row[0], inputs.registry_payload, row[1])
    if keys != sorted(keys):
        raise UnsupportedRegistryPlacement("requires exact immutable registry endpoint inputs")
    return result


def registry_endpoint_inputs(registry_payload: bytes, artworks: Mapping[str, bytes]) -> RegistryEndpointInputs:
    """Freeze caller-supplied normal/frozen bytes and prove their exact pins."""
    if not isinstance(artworks, Mapping) or any(type(key) is not str for key in artworks):
        raise UnsupportedRegistryPlacement("requires exact immutable registry endpoint inputs")
    result = RegistryEndpointInputs(registry_payload, tuple(sorted(artworks.items())))
    _registry_endpoint_assets(result)
    return result


def validate_registry_new_write_objects(objects, inputs, *, placed: bool) -> None:
    """Authenticate explicit new-write claims; anchorless baseline art needs none.

    Caller supplies authenticated bytes. Historical parse/serialization and
    runtime endpoint admission are separate and never rewritten here.
    """
    bound = [obj for obj in objects if getattr(obj, "registry_binding", None) is not None]
    candidates = [obj for obj in objects if placed and isinstance(obj, VisualObject)
        and obj.object_type in SUPPORTED_REGISTRY_VISUALS and obj.anchors and obj.variant is not None]
    if not bound and not candidates:
        return
    assets = _registry_endpoint_assets(inputs)
    if candidates:
        # The full pinned metadata, not a type label or subset artwork bank,
        # establishes whether an unbound variant actually claims registry art.
        registry = {entry.id: entry for entry in AssetRegistry.model_validate_json(inputs.registry_payload).assets}
        for obj in candidates:
            asset = registry.get(obj.variant)
            if (asset is not None and asset.family in SUPPORTED_REGISTRY_VISUALS[obj.object_type]
                    and obj.registry_binding is None):
                raise UnsupportedRegistryPlacement("placed registry anchors require an explicit all-and-only registry_binding")
    for obj in bound:
        asset = assets.get(obj.registry_binding.asset_id)
        if asset is None:
            raise UnsupportedRegistryPlacement("registry write inputs lack the exact asset")
        if placed:
            validate_registry_binding(obj, asset)
            continue
        _known(obj, SemanticStandardObjectSpec)
        _known(obj.registry_binding, RegistryBinding)
        SemanticStandardObjectSpec.model_validate(obj.model_dump(mode="json"))
        if asset.family not in SUPPORTED_REGISTRY_VISUALS.get(obj.object_type, ()):
            raise UnsupportedRegistryPlacement("binding uses an incompatible registry asset family")
        for mapping in obj.registry_binding.anchor_mappings:
            _known(mapping, RegistryAnchorMapping)
            if mapping.registry_anchor_name not in asset.anchors:
                raise UnsupportedRegistryPlacement(f"unknown registry anchor: {mapping.registry_anchor_name}")


def _checked_registry_entry(asset_id: str, registry_payload: bytes) -> AssetEntry:
    if type(registry_payload) is not bytes:
        raise UnsupportedRegistryPlacement("registry verification requires immutable bytes")
    if sha256(registry_payload).hexdigest() != EXPECTED_REGISTRY_SHA256:
        raise UnsupportedRegistryPlacement("registry metadata checksum mismatch")
    registry = AssetRegistry.model_validate_json(registry_payload)
    entry = next((row for row in registry.assets if row.id == asset_id), None)
    if entry is None:
        raise UnsupportedRegistryPlacement(f"unknown Paper & Ink asset: {asset_id}")
    return entry


def checked_registry_art(asset_id: str, registry_payload: bytes,
                         artwork_payload: bytes) -> tuple[AssetEntry, bytes]:
    """Authenticate exact pinned byte evidence, never a mutable cached model.

    The caller obtains normal files or frozen carrier bytes. The returned
    metadata is fresh and belongs to the same verified artwork payload.
    """
    if type(artwork_payload) is not bytes:
        raise UnsupportedRegistryPlacement("registry verification requires immutable bytes")
    entry = _checked_registry_entry(asset_id, registry_payload)
    if sha256(artwork_payload).hexdigest() != entry.sha256:
        raise UnsupportedRegistryPlacement("registry artwork checksum mismatch")
    _validate_svg(Path(entry.file), entry.view_box, payload=artwork_payload)
    return entry, artwork_payload


def _known(model, cls):
    if (type(model) is not cls or set(model.__dict__) != set(cls.model_fields) or model.model_extra):
        raise UnsupportedRegistryPlacement("registry placement has an unknown or missing contract payload")


@dataclass(frozen=True)
class RegistryPlacement:
    viewport: tuple[float, float, float, float]
    fitted: tuple[float, float, float, float]
    view_box: tuple[int, int, int, int]
    anchors: tuple[tuple[str, float, float], ...]

    def anchor_point(self, name: str) -> tuple[float, float]:
        for key, x, y in self.anchors:
            if key == name:
                return x, y
        raise UnsupportedRegistryPlacement(f"unknown registry anchor: {name}")


def registry_placement(asset: AssetEntry, bounds: Bounds) -> RegistryPlacement:
    """Use the exact centered meet viewport that SVG paints, including gutters."""
    _known(asset, AssetEntry)
    _known(asset.provenance, AssetProvenance)
    _known(bounds, Bounds)
    # Catch bypass-constructed/mutated metadata, without pretending it verifies
    # the file. Byte attestation is always the calling carrier's responsibility.
    AssetEntry.model_validate(asset.model_dump(mode="json"))
    Bounds.model_validate(bounds.model_dump(mode="json"))
    x, y, width, height = (_q(value) for value in (bounds.x, bounds.y, bounds.width, bounds.height))
    if width <= 0 or height <= 0:
        raise UnsupportedRegistryPlacement("serialized registry viewport collapses to zero area")
    _, _, view_width, view_height = asset.view_box
    scale = min(width / view_width, height / view_height)
    fit_width, fit_height = view_width * scale, view_height * scale
    fit_x, fit_y = x + (width - fit_width) / 2, y + (height - fit_height) / 2
    anchors = tuple((name, fit_x + fit_width * point[0], fit_y + fit_height * point[1])
        for name, point in sorted(asset.anchors.items()))
    for _, anchor_x, anchor_y in anchors:
        _q(anchor_x)
        _q(anchor_y)
    return RegistryPlacement((x, y, width, height), (fit_x, fit_y, fit_width, fit_height), asset.view_box, anchors)


def validate_registry_binding(obj: VisualObject, asset: AssetEntry) -> RegistryPlacement:
    """Check local endpoints only; sampled world/aperture proof is separate."""
    _known(obj, VisualObject)
    _known(obj.registry_binding, RegistryBinding)
    for mapping in obj.registry_binding.anchor_mappings:
        _known(mapping, RegistryAnchorMapping)
    VisualObject.model_validate(obj.model_dump(mode="json"))
    if obj.variant != asset.id or obj.registry_binding.asset_id != asset.id:
        raise UnsupportedRegistryPlacement("binding names a different registry asset from checked metadata")
    if asset.family not in SUPPORTED_REGISTRY_VISUALS.get(obj.object_type, ()):
        raise UnsupportedRegistryPlacement("binding uses an incompatible registry asset family")
    placement = registry_placement(asset, obj.geometry.bounds)
    declared = {anchor.anchor_id: anchor for anchor in obj.anchors}
    x, y, width, height = placement.viewport
    for mapping in obj.registry_binding.anchor_mappings:
        target = placement.anchor_point(mapping.registry_anchor_name)
        point = declared[mapping.placed_anchor_id].point
        actual = x + width * point.x, y + height * point.y
        if tuple(map(_q, actual)) != tuple(map(_q, target)):
            raise UnsupportedRegistryPlacement(
                f"placed anchor {mapping.placed_anchor_id} does not match fitted registry anchor")
    return placement


def validate_registry_world_binding(obj: VisualObject, asset: AssetEntry,
                                    objects: dict, transforms: dict) -> tuple:
    """Compare final q4 endpoints after the complete caller-sampled hierarchy.

    Neither locally rounded endpoints nor the original authored pose are used
    as a substitute for the sampled transform chain. Resource/aperture admission
    belongs to the caller; this pure geometry seam performs no live lookup.
    """
    placement = validate_registry_binding(obj, asset)
    if objects.get(obj.object_id) != obj:
        raise UnsupportedRegistryPlacement("registry sampled hierarchy names a different or missing object")
    claims = {}
    for owner in objects.values():
        if isinstance(owner, ContainerObject):
            for child in owner.child_ids:
                claims.setdefault(child, []).append(owner.object_id)
    visited = set()
    current = obj
    while current is not None:
        if current.object_id in visited or current.object_id not in transforms:
            raise UnsupportedRegistryPlacement("registry sampled hierarchy is cyclic or lacks a transform")
        visited.add(current.object_id)
        expected_owners = [] if current.parent_id is None else [current.parent_id]
        if claims.get(current.object_id, []) != expected_owners:
            raise UnsupportedRegistryPlacement("registry sampled hierarchy lacks unique reciprocal membership")
        if current.parent_id is None:
            break
        parent = objects.get(current.parent_id)
        if (type(parent) not in {GroupContainer, ClipContainer, MaskContainer}
                or parent.object_id != current.parent_id):
            raise UnsupportedRegistryPlacement("registry sampled hierarchy lacks an exact parent")
        current = parent
    matrix = world_matrix(obj, objects, transforms)
    endpoints = []
    for mapping in obj.registry_binding.anchor_mappings:
        expected = tuple(map(_q, matrix.point(*placement.anchor_point(mapping.registry_anchor_name))))
        actual = tuple(map(_q, world_anchor(obj, mapping.placed_anchor_id, objects, transforms)))
        if actual != expected:
            raise UnsupportedRegistryPlacement(
                f"placed anchor {mapping.placed_anchor_id} does not match fitted registry sampled world anchor")
        endpoints.append((mapping.placed_anchor_id, actual))
    return tuple(endpoints)


def registry_relationship_anchor(obj, anchor_id: str, objects: dict, transforms: dict,
                                  registry_inputs: RegistryEndpointInputs | None = None) -> tuple[float, float]:
    """Resolve one endpoint without IO or inferred aperture visibility.

    Legacy unbound geometry retains its existing route. A bound endpoint needs
    the same pinned byte inventory and the actual complete sampled hierarchy.
    Explicit aperture ancestry is unsupported, not guessed from an AABB.
    """
    if isinstance(obj, VisualObject) and obj.technical_frame is not None:
        from atme.render.v2_technical_frame import validate_technical_frame_world

        try:
            points = dict(validate_technical_frame_world(obj, objects, transforms))
        except ValueError as exc:
            raise UnsupportedRegistryPlacement(str(exc)) from exc
        current = obj
        while current is not None:
            if current.clip_id is not None or isinstance(current, (ClipContainer, MaskContainer)):
                raise UnsupportedRegistryPlacement(
                    "technical_frame relationship anchor is unavailable under sampled aperture ancestry")
            current = objects[current.parent_id] if current.parent_id is not None else None
        if anchor_id not in points:
            raise UnsupportedRegistryPlacement(f"unknown placed technical_frame anchor: {anchor_id}")
        return points[anchor_id]
    if not isinstance(obj, VisualObject) or obj.registry_binding is None:
        return world_anchor(obj, anchor_id, objects, transforms)
    asset = _registry_endpoint_assets(registry_inputs).get(obj.variant)
    if asset is None:
        raise UnsupportedRegistryPlacement("registry endpoint inputs lack the exact variant")
    points = dict(validate_registry_world_binding(obj, asset, objects, transforms))
    current = obj
    while current is not None:
        if current.clip_id is not None or isinstance(current, (ClipContainer, MaskContainer)):
            raise UnsupportedRegistryPlacement("registry relationship anchor is unavailable under sampled aperture ancestry")
        current = objects[current.parent_id] if current.parent_id is not None else None
    if anchor_id not in points:
        raise UnsupportedRegistryPlacement(f"unknown placed registry anchor: {anchor_id}")
    return points[anchor_id]
