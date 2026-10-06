"""Plan transient context roots from the exact captured hierarchy, never flat IDs."""

from atme.render.v2_hierarchy import HierarchySnapshot
from atme.store.contracts_v2 import ContainerObject, MaskContainer, TargetAction


class UnsupportedIsolation(ValueError):
    """The authored focus has no visible ancestry or secondary paint context."""


def isolation_context_roots(objects: dict, hierarchy: HierarchySnapshot,
                            frames: dict, action: TargetAction) -> tuple[str, ...]:
    """Protect focus/ancestors/apertures and dim maximal visible context once.

    Context roots are captured before the operator starts. Descendant alpha is
    not rewritten; empty containers and dedicated mask sources are not paint.
    Existing static action validation owns focus types, board and time contracts.
    """
    focus = set(action.target_ids)
    protected = {key for target in focus for key in (target, *hierarchy.ancestors(target))}
    mask_sources = {obj.mask_source_object_id for obj in objects.values() if isinstance(obj, MaskContainer)}

    def ready(key):
        return all(frames[item].visible and frames[item].opacity > 0
                   and frames[item].reveal_fraction == 1
                   for item in (key, *hierarchy.ancestors(key)))

    if not all(ready(key) for key in focus):
        raise UnsupportedIsolation(f"isolate {action.action_id} needs visible focus content and parents")
    # A static mask's dedicated geometry is not a visible secondary object.
    # Protect its full chain when it provides a focus aperture.
    for key in tuple(protected):
        obj = objects[key]
        if isinstance(obj, MaskContainer):
            source = obj.mask_source_object_id
            if source is None or source not in frames or not ready(source):
                raise UnsupportedIsolation(f"isolate {action.action_id} needs a visible focus aperture")
            protected.update((source, *hierarchy.ancestors(source)))
    paint = {key for key in hierarchy.paint_order(objects, action.board_id)
             if key not in mask_sources and ready(key)}
    context_paint = paint - focus
    if not context_paint:
        raise UnsupportedIsolation(f"isolate {action.action_id} needs visible secondary context")
    roots = []

    def walk(parent):
        for key in hierarchy.children(action.board_id, parent):
            obj = objects[key]
            if key in mask_sources:
                continue
            if key not in protected and ready(key) and any(
                leaf == key or key in hierarchy.ancestors(leaf) for leaf in context_paint
            ):
                roots.append(key)
            elif isinstance(obj, ContainerObject):
                walk(key)

    walk(None)
    return tuple(roots)
