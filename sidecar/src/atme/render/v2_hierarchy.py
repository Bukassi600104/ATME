"""Immutable parent/order snapshots for authored v2 hierarchy transitions.

This foundation does not enable group/ungroup actions. A future explicit policy
must supply the whole transition, state/version accounting and conflict guards.
All consumers must use the same evaluated snapshot, rather than infer membership.
"""

from __future__ import annotations

from dataclasses import dataclass

from atme.render.v2_world import world_bounds, world_matrix
from atme.store.contracts_v2 import (
    ConnectorObject,
    ContainerObject,
    GroupAction,
    MaskContainer,
    _require_hierarchy_contract,
)


class UnsupportedHierarchy(ValueError):
    """A hierarchy would change authored meaning or has no complete mapping."""


@dataclass(frozen=True)
class HierarchyNode:
    object_id: str
    board_id: str
    parent_id: str | None
    sibling_ordinal: int

    def __post_init__(self):
        if (type(self.object_id) is not str or not self.object_id
                or type(self.board_id) is not str or not self.board_id
                or self.parent_id is not None and (type(self.parent_id) is not str or not self.parent_id)
                or type(self.sibling_ordinal) is not int or self.sibling_ordinal < 0):
            raise UnsupportedHierarchy("hierarchy nodes require exact IDs and nonnegative integer ordinals")


@dataclass(frozen=True)
class HierarchySnapshot:
    nodes: tuple[HierarchyNode, ...]

    def __post_init__(self):
        if type(self.nodes) is not tuple or not self.nodes or any(type(node) is not HierarchyNode for node in self.nodes):
            raise UnsupportedHierarchy("hierarchy must be a nonempty immutable tuple of nodes")
        if len({node.object_id for node in self.nodes}) != len(self.nodes):
            raise UnsupportedHierarchy("hierarchy repeats an object")
        if self.nodes != tuple(sorted(self.nodes, key=lambda node: node.object_id)):
            raise UnsupportedHierarchy("hierarchy nodes must use canonical object-ID order")

    @classmethod
    def from_objects(cls, objects: dict):
        """Initial order exactly matches the existing compositor's sibling sort."""
        siblings = {}
        for obj in sorted(objects.values(), key=lambda obj: (obj.z_index, obj.object_id)):
            siblings.setdefault((obj.board_id, obj.parent_id), []).append(obj.object_id)
        ordinals = {object_id: ordinal for ids in siblings.values() for ordinal, object_id in enumerate(ids)}
        result = cls(tuple(HierarchyNode(obj.object_id, obj.board_id, obj.parent_id, ordinals[obj.object_id])
                           for obj in sorted(objects.values(), key=lambda obj: obj.object_id)))
        result.validate(objects)
        for obj in objects.values():
            if isinstance(obj, ContainerObject) and set(obj.child_ids) != set(result.children(obj.board_id, obj.object_id)):
                raise UnsupportedHierarchy(f"initial container {obj.object_id} disagrees with its parent inventory")
        return result

    def children(self, board_id: str, parent_id: str | None) -> tuple[str, ...]:
        return tuple(node.object_id for node in sorted(self.nodes, key=lambda node: node.sibling_ordinal)
                     if node.board_id == board_id and node.parent_id == parent_id)

    def ancestors(self, object_id: str) -> tuple[str, ...]:
        nodes = {node.object_id: node for node in self.nodes}
        if object_id not in nodes:
            raise UnsupportedHierarchy("hierarchy ancestry references an unknown object")
        result = []
        parent_id = nodes[object_id].parent_id
        while parent_id is not None:
            if parent_id not in nodes or parent_id in result or parent_id == object_id:
                raise UnsupportedHierarchy("hierarchy parentage is unknown or cyclic")
            result.append(parent_id)
            if len(result) > 8:
                raise UnsupportedHierarchy("hierarchy exceeds eight ancestor levels")
            parent_id = nodes[parent_id].parent_id
        return tuple(result)

    def validate(self, objects: dict) -> None:
        nodes = {node.object_id: node for node in self.nodes}
        if nodes.keys() != objects.keys():
            raise UnsupportedHierarchy("hierarchy must cover the exact layout inventory")
        siblings = {}
        for node in self.nodes:
            if node.board_id != objects[node.object_id].board_id:
                raise UnsupportedHierarchy("hierarchy cannot change board ownership")
            if node.parent_id is not None:
                parent = objects.get(node.parent_id)
                if not isinstance(parent, ContainerObject) or parent.board_id != node.board_id:
                    raise UnsupportedHierarchy("hierarchy needs a same-board container parent")
            self.ancestors(node.object_id)
            siblings.setdefault((node.board_id, node.parent_id), []).append(node.sibling_ordinal)
        if any(sorted(ordinals) != list(range(len(ordinals))) for ordinals in siblings.values()):
            raise UnsupportedHierarchy("hierarchy sibling ordinals must be a complete unique permutation")

    def object_map(self, objects: dict) -> dict:
        """Project ownership without changing authored layers or stored layout.

        A sibling ordinal is unique paint order, not an authored layer: two
        replacement/morph objects may intentionally share their z_index.
        Paint consumers must read snapshot order instead of changing that layer.
        """
        self.validate(objects)
        result = {}
        for node in self.nodes:
            obj = objects[node.object_id]
            updates = {"parent_id": node.parent_id}
            if isinstance(obj, ContainerObject):
                updates["child_ids"] = list(self.children(node.board_id, node.object_id))
            result[node.object_id] = obj.model_copy(update=updates, deep=True)
        return result

    def paint_order(self, objects: dict, board_id: str) -> tuple[str, ...]:
        self.validate(objects)
        mask_sources = {obj.mask_source_object_id for obj in objects.values() if isinstance(obj, MaskContainer)}
        result = []

        def walk(parent_id):
            for object_id in self.children(board_id, parent_id):
                if isinstance(objects[object_id], ContainerObject):
                    walk(object_id)
                elif object_id not in mask_sources:
                    result.append(object_id)

        walk(None)
        return tuple(result)


def changed_hierarchy_objects(before: HierarchySnapshot, after: HierarchySnapshot, objects: dict) -> tuple[str, ...]:
    """Exact structural/version closure, including sibling ordinal changes."""
    before.validate(objects)
    after.validate(objects)
    old_nodes, new_nodes = ({node.object_id: node for node in snapshot.nodes} for snapshot in (before, after))
    changed = {object_id for object_id in objects if old_nodes[object_id] != new_nodes[object_id]}
    moved_roots = {object_id for object_id in objects
                   if old_nodes[object_id].parent_id != new_nodes[object_id].parent_id}
    for object_id, obj in objects.items():
        if (set(before.ancestors(object_id)).intersection(moved_roots)
                or set(after.ancestors(object_id)).intersection(moved_roots)
                or isinstance(obj, ContainerObject)
                and before.children(obj.board_id, object_id) != after.children(obj.board_id, object_id)):
            changed.add(object_id)
    return tuple(sorted(changed))


def validate_transition_scope(before: HierarchySnapshot, after: HierarchySnapshot, objects: dict,
                              before_transforms: dict, after_transforms: dict,
                              moved_roots: tuple[str, ...]) -> tuple[str, ...]:
    """Reject hidden mutations; return the exact source/destination subtree union.

    Only declared roots may reparent or receive a replacement local transform.
    Their descendants keep local placement, and other siblings keep relative
    order. Dense ordinal shifts caused by insertion/removal are permitted and
    remain observable through ``changed_hierarchy_objects`` for versioning.
    """
    if (type(moved_roots) is not tuple or not moved_roots
            or any(type(root) is not str for root in moved_roots)
            or len(set(moved_roots)) != len(moved_roots)
            or set(moved_roots) - objects.keys()):
        raise UnsupportedHierarchy("world preservation needs unique authored member roots")
    before.validate(objects)
    after.validate(objects)
    if before_transforms.keys() != objects.keys() or after_transforms.keys() != objects.keys():
        raise UnsupportedHierarchy("world preservation requires the complete local-transform inventory")
    for snapshot in (before, after):
        if any(set(snapshot.ancestors(root)).intersection(moved_roots) for root in moved_roots):
            raise UnsupportedHierarchy("a member root cannot also contain another member root")
    old_nodes, new_nodes = ({node.object_id: node for node in snapshot.nodes} for snapshot in (before, after))
    for object_id in objects.keys() - set(moved_roots):
        if old_nodes[object_id].parent_id != new_nodes[object_id].parent_id:
            raise UnsupportedHierarchy(f"undeclared parent change for {object_id}")
        if before_transforms[object_id] != after_transforms[object_id]:
            raise UnsupportedHierarchy(f"undeclared local transform change for {object_id}")
    parents = {(node.board_id, node.parent_id) for snapshot in (before, after) for node in snapshot.nodes}
    for board_id, parent_id in parents:
        old_order, new_order = (tuple(object_id for object_id in snapshot.children(board_id, parent_id)
                                     if object_id not in moved_roots) for snapshot in (before, after))
        if old_order != new_order:
            raise UnsupportedHierarchy("undeclared sibling order change outside the member roots")
    closures = [{object_id for object_id in objects if object_id in moved_roots
                 or set(snapshot.ancestors(object_id)).intersection(moved_roots)} for snapshot in (before, after)]
    if closures[0] != closures[1]:
        raise UnsupportedHierarchy("member roots cannot acquire or lose undeclared descendants")
    return tuple(sorted(closures[0] | closures[1]))


def validate_world_preservation(before: HierarchySnapshot, after: HierarchySnapshot, objects: dict,
                                before_transforms: dict, after_transforms: dict, moved_roots: tuple[str, ...]) -> None:
    """Check authored mappings against emitted four-decimal affine geometry.

    No inverse, decomposition or destination transform is inferred. The pinned
    maximum discrepancy is 1e-4 design units, including projected corners.
    """
    affected = validate_transition_scope(before, after, objects, before_transforms, after_transforms, moved_roots)
    old_objects, new_objects = before.object_map(objects), after.object_map(objects)
    for object_id in affected:
        old = world_matrix(old_objects[object_id], old_objects, before_transforms)
        new = world_matrix(new_objects[object_id], new_objects, after_transforms)
        if any(abs(getattr(old, field) - getattr(new, field)) > 1e-4 for field in ("a", "b", "c", "d", "e", "f")):
            raise UnsupportedHierarchy(f"hierarchy mapping changes world affine for {object_id}")
        old_rect = world_bounds(old_objects[object_id], old_objects, before_transforms)
        new_rect = world_bounds(new_objects[object_id], new_objects, after_transforms)
        if any(abs(old_value - new_value) > 1e-4 for old_value, new_value in zip(old_rect, new_rect, strict=True)):
            raise UnsupportedHierarchy(f"hierarchy mapping changes world bounds for {object_id}")
        bounds = objects[object_id].geometry.bounds
        for x in (bounds.x, bounds.x + bounds.width):
            for y in (bounds.y, bounds.y + bounds.height):
                if any(abs(a-b) > 1e-4 for a, b in zip(old.point(x, y), new.point(x, y), strict=True)):
                    raise UnsupportedHierarchy(f"hierarchy mapping changes world corners for {object_id}")


def validate_authored_hierarchy(action: GroupAction, objects: dict) -> tuple[HierarchySnapshot, HierarchySnapshot]:
    """Validate the complete authored receipt against actual layout geometry.

    This does not execute a transition or bind its source to a resolved action
    boundary. Those chronological state/conflict checks remain runtime gates.
    """
    _require_hierarchy_contract(action)
    policy = action.hierarchy_policy
    before, after = (HierarchySnapshot(tuple(HierarchyNode(item.object_id, item.board_id, item.parent_id,
                                                          item.sibling_ordinal) for item in basis.placements))
                     for basis in (policy.source_basis, policy.destination_basis))
    transforms = [{item.object_id: item.local_transform for item in basis.placements}
                  for basis in (policy.source_basis, policy.destination_basis)]
    moved_roots = tuple(action.target_ids)
    validate_world_preservation(before, after, objects, *transforms, moved_roots)
    if changed_hierarchy_objects(before, after, objects) != tuple(policy.changed_object_ids):
        raise UnsupportedHierarchy("hierarchy receipt omits or invents structural version changes")
    shell = objects[action.container_id]
    if (shell.object_type != "group" or not shell.visible or shell.opacity != 1
            or shell.asset_id is not None or shell.anchors or shell.geometry.points
            or shell.geometry.corner_radius is not None or shell.clip_id is not None
            or any((shell.style.stroke, shell.style.fill, shell.style.text, shell.style.effect))):
        raise UnsupportedHierarchy("hierarchy shell must be a visible opaque nonpainting group")
    for snapshot in (before, after):
        for object_id, obj in objects.items():
            ancestors = set(snapshot.ancestors(object_id))
            if object_id in moved_roots or ancestors.intersection(moved_roots):
                if isinstance(obj, ConnectorObject):
                    raise UnsupportedHierarchy("hierarchy step cannot reparent a connector without inverse-parent semantics")
                dependencies = {object_id, *ancestors, action.container_id}
                if any(objects[key].object_type in {"clip", "mask", "evidence"}
                       or objects[key].clip_id is not None for key in dependencies):
                    raise UnsupportedHierarchy("hierarchy transition cannot cross aperture or evidence ownership")
    for board_id in {obj.board_id for obj in objects.values()}:
        if before.paint_order(objects, board_id) != after.paint_order(objects, board_id):
            raise UnsupportedHierarchy("hierarchy transition changes effective leaf paint order")
    return before, after
