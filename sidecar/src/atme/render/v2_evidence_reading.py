"""Technical evidence readability at one exact immutable replay sample.

This does not research/verify claims or alter attested source pixels/permissions.
"""

from atme.render.v2_world import world_bounds, world_matrix
from atme.store.contracts_v2 import ContainerObject, MaskContainer


def validate_evidence_reading(item, layout, objects, treatment, sample, viewport):
    target = item.action.target_object_id
    objects = sample.hierarchy.object_map(objects)
    frames = {frame.object_id: frame for frame in sample.objects}
    transforms = {key: frame.transform for key, frame in frames.items()}
    obj = objects[target]
    ancestors = sample.hierarchy.ancestors(target)
    chain = (target, *ancestors)
    if any(not frames[key].visible or frames[key].reveal_fraction != 1
           or frames[key].opacity != 1 for key in ancestors):
        raise ValueError(f"evidence {target} needs fully visible opaque parents throughout its hold")
    if sample.at_ms >= item.end_ms and (
        not frames[target].visible or frames[target].reveal_fraction != 1 or frames[target].opacity != 1
    ):
        raise ValueError(f"evidence {target} must remain fully visible and opaque for its readable hold")
    if "rotate" not in treatment.allowed_transformations and any(
        transforms[key].rotation_degrees != 0 for key in chain
    ):
        raise ValueError(f"evidence {target} has an undeclared rotation")
    rect = world_bounds(obj, objects, transforms)
    matrix = world_matrix(obj, objects, transforms)
    for parent_id in ancestors:
        parent = objects[parent_id]
        if isinstance(parent, MaskContainer):
            source = objects[parent.mask_source_object_id]
            if source.object_type != "rectangle" or any(
                transforms[key].rotation_degrees != 0 for key in (*chain, source.object_id)
            ):
                raise ValueError(f"evidence {target} needs an axis-aligned rectangular mask aperture")
            aperture = world_bounds(source, objects, transforms)
            if (rect[0] < aperture[0] or rect[1] < aperture[1]
                    or rect[2] > aperture[2] or rect[3] > aperture[3]):
                raise ValueError(f"evidence {target} is clipped by its declared mask")
        elif isinstance(parent, ContainerObject) and parent.object_type == "clip":
            if any(transforms[key].rotation_degrees != 0 for key in chain):
                raise ValueError(f"evidence {target} needs an axis-aligned clip aperture")
            aperture = world_bounds(parent, objects, transforms)
            if (rect[0] < aperture[0] or rect[1] < aperture[1]
                    or rect[2] > aperture[2] or rect[3] > aperture[3]):
                raise ValueError(f"evidence {target} is clipped by its parent")
    crop, focus, bounds = treatment.intent.crop, treatment.intent.focus_region, obj.geometry.bounds
    source_scale = min(bounds.width / crop.width, bounds.height * 0.5 / crop.height)
    origin = matrix.point(0, 0)
    focus_x = matrix.point(focus.width * source_scale, 0)
    focus_y = matrix.point(0, focus.height * source_scale)
    displayed_focus_x = ((focus_x[0] - origin[0]) ** 2 + (focus_x[1] - origin[1]) ** 2) ** 0.5
    displayed_focus_y = ((focus_y[0] - origin[0]) ** 2 + (focus_y[1] - origin[1]) ** 2) ** 0.5
    if (rect[0] < viewport.x or rect[1] < viewport.y
            or rect[2] > viewport.x + viewport.width or rect[3] > viewport.y + viewport.height
            or (rect[2] - rect[0]) * layout.canvas.width / viewport.width < 180
            or (rect[3] - rect[1]) * layout.canvas.height / viewport.height < 160
            or displayed_focus_x * layout.canvas.width / viewport.width < 8
            or displayed_focus_y * layout.canvas.height / viewport.height < 8):
        raise ValueError(f"evidence {target} is not fully readable in the camera frame during its hold")
