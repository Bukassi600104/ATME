"""Camera plan execution: eased viewBox interpolation between focus cues."""

from __future__ import annotations


def ease_in_out(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3.0 - 2.0 * t)  # smoothstep


def validate_camera_intent(plan: list[dict]) -> None:
    """Explicit intent cannot be mixed with legacy arrival-time camera cues."""
    if not any("action" in cue for cue in plan):
        return
    previous_end = -1
    for index, cue in enumerate(plan):
        action = cue.get("action")
        if action not in ("hold", "cut", "pan", "zoom", "reframe"):
            raise ValueError("explicit camera cues require a supported action on every cue")
        at = cue.get("cue_ms")
        duration = cue.get("transition_ms", 0)
        if type(at) is not int or at < 0 or type(duration) is not int or duration < 0:
            raise ValueError("camera timing must use non-negative integer milliseconds")
        if index == 0 and (at != 0 or action not in ("hold", "cut")):
            raise ValueError("explicit camera plan must establish a hold or cut at zero")
        if at < previous_end or (index and at <= plan[index - 1]["cue_ms"]):
            raise ValueError("camera cues must be ordered and movements cannot overlap")
        if action in ("hold", "cut") and duration:
            raise ValueError("hold and cut cues cannot have a movement duration")
        if action in ("pan", "zoom", "reframe") and not duration:
            raise ValueError("camera movement requires a positive transition_ms")
        if cue.get("easing", "easeInOut") not in ("linear", "easeInOut"):
            raise ValueError("unsupported camera easing")
        focus = cue.get("focus", {})
        if (any(type(focus.get(k)) is not int for k in ("x", "y", "width", "height"))
                or focus["width"] <= 0 or focus["height"] <= 0):
            raise ValueError("camera focus must have integer coordinates and positive dimensions")
        previous_end = at + duration


def _intent_focus(plan: list[dict], t_ms: int) -> dict:
    validate_camera_intent(plan)
    previous = plan[0]["focus"]
    for cue in plan:
        if t_ms < cue["cue_ms"]:
            break
        target = cue["focus"]
        duration = cue.get("transition_ms", 0)
        if duration and t_ms < cue["cue_ms"] + duration:
            p = max(0.0, (t_ms - cue["cue_ms"]) / duration)
            if cue.get("easing", "easeInOut") == "easeInOut":
                p = ease_in_out(p)
            return {k: previous[k] + (target[k] - previous[k]) * p for k in target}
        previous = target
    return previous


def viewbox_at(camera_plan: list[dict], canvas_w: float, canvas_h: float,
               t_ms: int, out_w: int, out_h: int, transition_ms: int = 600) -> dict:
    """Return the viewBox rect for time t_ms, aspect-fitted to the output frame."""
    if any("action" in cue for cue in camera_plan):
        focus = _intent_focus(camera_plan, t_ms)
        focus = _composition_padding(focus, canvas_w, canvas_h)
        return _fit_viewbox(focus["x"], focus["y"], focus["width"], focus["height"],
                            out_w, out_h)
    if not camera_plan:
        plan = [{"cue_ms": 0, "focus": {"x": 0, "y": 0, "width": canvas_w, "height": canvas_h}}]
    else:
        plan = sorted(camera_plan, key=lambda c: c["cue_ms"])

    current = plan[0]
    nxt = None
    for cue in plan:
        if cue["cue_ms"] <= t_ms:
            current = cue
        elif nxt is None:
            nxt = cue
            break

    fx, fy, fw, fh = (current["focus"]["x"], current["focus"]["y"],
                      current["focus"]["width"], current["focus"]["height"])
    if nxt is not None and transition_ms > 0:
        span_start = max(current["cue_ms"], nxt["cue_ms"] - transition_ms)
        if t_ms >= span_start:
            p = ease_in_out((t_ms - span_start) / max(1, nxt["cue_ms"] - span_start))
            f2 = nxt["focus"]
            fx += (f2["x"] - fx) * p
            fy += (f2["y"] - fy) * p
            fw += (f2["width"] - fw) * p
            fh += (f2["height"] - fh) * p

    if camera_plan:
        padded = _composition_padding({"x": fx, "y": fy, "width": fw, "height": fh}, canvas_w, canvas_h)
        fx, fy, fw, fh = padded["x"], padded["y"], padded["width"], padded["height"]
    return _fit_viewbox(fx, fy, fw, fh, out_w, out_h)


def _composition_padding(focus: dict, canvas_w: float, canvas_h: float) -> dict:
    """Add restrained board context without changing authored cue timing or target."""
    width = min(canvas_w, focus["width"] * 1.22)
    height = min(canvas_h, focus["height"] * 1.22)
    center_x = focus["x"] + focus["width"] / 2
    center_y = focus["y"] + focus["height"] / 2
    return {"x": max(0, min(canvas_w - width, center_x - width / 2)),
            "y": max(0, min(canvas_h - height, center_y - height / 2)),
            "width": width, "height": height}


def _fit_viewbox(fx, fy, fw, fh, out_w, out_h) -> dict:
    # aspect-fit fw/fh into out_w/out_h (expand the smaller dimension)
    target_ar = out_w / out_h
    ar = fw / fh if fh else target_ar
    if ar < target_ar:  # too tall -> widen
        new_w = fh * target_ar
        fx -= (new_w - fw) / 2
        fw = new_w
    elif ar > target_ar:  # too wide -> heighten
        new_h = fw / target_ar
        fy -= (new_h - fh) / 2
        fh = new_h
    return {"x": fx, "y": fy, "w": fw, "h": fh, "out_w": out_w, "out_h": out_h}
