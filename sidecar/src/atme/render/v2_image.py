"""Shared authored image/media placement on checked pixels and current hierarchy."""

from __future__ import annotations

import base64

from atme.render.v2_raster import cropped_png
from atme.store.contracts_v2 import (
    ClipContainer,
    MaskContainer,
    TransformAction,
    validate_image_asset_binding,
)


def validate_image_placement(obj, asset, objects, states, actions):
    """No implied grants: source pins and every actual ancestor/read are checked."""
    validate_image_asset_binding(obj, asset)
    validate_image_permissions(obj, objects, {key: state.transform for key, state in states.items()},
                               tuple(item.action for item in actions))


def validate_image_permissions(obj, objects, transforms, actions):
    """Shared initial/write-history/paint rule, independent of raster decoding."""
    placement = obj.image_placement
    validate_placement_permissions(obj, placement, objects, transforms, actions, label="image_placement")


def validate_placement_permissions(obj, placement, objects, transforms, actions, *, label):
    """One image/media rule; no owner conversion or implied permission grants."""
    if placement is None:
        return
    allowed = placement.allowed_transformations
    crop, bounds = placement.crop, obj.geometry.bounds
    if (placement.fit == "cover" and crop.width * bounds.height != crop.height * bounds.width
            and "crop" not in allowed):
        raise ValueError(f"{label} cover overflow requires crop permission")
    chain = []
    current = obj
    while current is not None:
        chain.append(current)
        current = objects[current.parent_id] if current.parent_id is not None else None
    ids = {node.object_id for node in chain}
    authored_rotate = any(isinstance(action, TransformAction) and action.verb == "rotate"
                          and ids.intersection(action.target_ids) for action in actions)
    if "rotate" not in allowed and (authored_rotate or any(
            node.transform.rotation_degrees != 0 or transforms[node.object_id].rotation_degrees != 0
            for node in chain)):
        raise ValueError(f"{label} cannot rotate without plan-bound permission")
    if "mask" not in allowed and any(
            isinstance(node, (ClipContainer, MaskContainer)) or node.clip_id is not None for node in chain):
        raise ValueError(f"{label} has no mask permission for its authored aperture")


def validate_image_placement_history(timeline, objects, replay):
    """Observe only the caller's causal replay, including current Group ancestry.

    No second clock, future-action scan or inferred ownership is introduced.
    Legacy images without placement retain their existing validation path.
    """
    ids = [key for key, obj in objects.items() if getattr(obj, "image_placement", None) is not None
           or getattr(obj, "media_playback", None) is not None]
    if not ids:
        return
    actions = tuple(row.action for row in timeline.actions)
    moments = {0, timeline.duration_ms - 1}
    for checkpoint in replay.checkpoints:
        moments.update((checkpoint.at_ms - 1, checkpoint.at_ms, checkpoint.at_ms + 1))
    for row in timeline.actions:
        moments.update(row.start_ms + int((row.end_ms - row.start_ms) * fraction)
                       for fraction in (.2, .5, .8))
    for at_ms in sorted(moment for moment in moments if 0 <= moment < timeline.duration_ms):
        sample = replay.at(at_ms)
        current = sample.hierarchy.object_map(objects)
        transforms = {frame.object_id: frame.transform for frame in sample.objects}
        for key in ids:
            obj = current[key]
            playback = getattr(obj, "media_playback", None)
            if playback is None:
                validate_image_permissions(obj, current, transforms, actions)
            else:
                validate_placement_permissions(obj, playback.placement, current, transforms, actions,
                                               label="media_playback.placement")


def image_placement_svg(obj, raster, *, placement=None):
    """Source crop first, uniform fit second; focal is crop-relative in both modes.

    A checked in-memory crop prevents outside pixels bleeding into resampling.
    The outer tree retains ownership of transforms, camera and apertures.
    """
    placement = obj.image_placement if placement is None else placement
    bounds = obj.geometry.bounds
    crop = placement.crop
    factor = (min if placement.fit == "contain" else max)(
        bounds.width / crop.width, bounds.height / crop.height)
    width, height = crop.width * factor, crop.height * factor

    def offset(viewport, extent, focal):
        return min(max(viewport / 2 - extent * focal, min(0, viewport - extent)),
                   max(0, viewport - extent))

    x = offset(bounds.width, width, placement.focal_point.x)
    y = offset(bounds.height, height, placement.focal_point.y)
    encoded = base64.b64encode(cropped_png(raster, crop.x, crop.y, crop.width, crop.height)).decode("ascii")

    def n(value):
        return f"{value:.4f}".rstrip("0").rstrip(".") if value else "0"

    return (f'<svg x="{n(bounds.x)}" y="{n(bounds.y)}" width="{n(bounds.width)}" '
            f'height="{n(bounds.height)}" viewBox="0 0 {n(bounds.width)} {n(bounds.height)}" '
            f'overflow="hidden" preserveAspectRatio="none">'
            f'<image x="{n(x)}" y="{n(y)}" width="{n(width)}" height="{n(height)}" '
            f'preserveAspectRatio="none" href="data:image/png;base64,{encoded}"/></svg>')
