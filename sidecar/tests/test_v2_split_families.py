"""Task7 family evidence; shared primitives own their artwork and contracts."""

import io
import json
import math
from hashlib import sha256
from itertools import pairwise

import pytest
import resvg_py
from atme.render.v2_split import capture_split
from atme.render.v2_split_paint import split_family_admission, verify_split_paint_inputs
from atme.render.v2_svg import _compose_validated_svg_frame, _rasterize_svg_frame
from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    ResolvedAction,
    ResolvedVisualTimelineV2,
    SplitPolicy,
    _split_expected_completion,
)
from PIL import Image
from test_v2_split_action import replay_split
from test_v2_split_capture import geometry_boundary
from test_v2_split_identity import sample_for_layout
from v2_fixtures import digest
from v2_split_fixtures import split_documents

GEOMETRY_KINDS = ("line", "rectangle", "rounded_rectangle", "ellipse", "polygon", "freehand_polyline",
                  "freehand_ML", "freehand_Q", "freehand_C", "underline", "highlight", "bracket")


def n(value):
    return f"{value:.4f}".rstrip("0").rstrip(".") if value else "0"


def curve_length(points):
    # Independent de Casteljau oracle at the approved 64 subdivision boundary;
    # no runtime parser, geometry builder or compositor is used here.
    samples = []
    for step in range(65):
        t = step / 64
        current = list(points)
        while len(current) > 1:
            current = [((1-t)*a[0]+t*b[0], (1-t)*a[1]+t*b[1]) for a, b in pairwise(current)]
        samples.append(current[0])
    return sum(math.dist(a, b) for a, b in pairwise(samples))


def authored_geometry(kind, box):
    x, y, w, h = box
    geometry = {"bounds": dict(zip(("x", "y", "width", "height"), box)), "points": [], "corner_radius": None}
    path = None
    if kind == "line":
        points = [(x, y), (x+w, y+h)]
        markup = f'<line x1="{n(x)}" y1="{n(y)}" x2="{n(x+w)}" y2="{n(y+h)}"'
        length = math.hypot(w, h)
    elif kind in {"rectangle", "rounded_rectangle"}:
        radius = 10. if kind == "rounded_rectangle" else 0.
        geometry["corner_radius"] = radius if radius else None
        points = []
        markup = f'<rect x="{n(x)}" y="{n(y)}" width="{n(w)}" height="{n(h)}" rx="{n(radius)}"'
        length = 2*(w+h-4*radius)+2*math.pi*radius
    elif kind == "ellipse":
        points = []
        markup = f'<ellipse cx="{n(x+w/2)}" cy="{n(y+h/2)}" rx="{n(w/2)}" ry="{n(h/2)}"'
        a, b = w/2, h/2
        length = math.pi*(3*(a+b)-math.sqrt((3*a+b)*(a+3*b)))
    elif kind == "polygon":
        points = [(x, y+h), (x+w/2, y), (x+w, y+h)]
        markup = '<polygon points="' + " ".join(f"{n(a)},{n(b)}" for a, b in points) + '"'
        length = 2*math.hypot(w/2,h)+w
    elif kind in {"bracket", "freehand_polyline"}:
        points = ([(x+w, y), (x, y), (x, y+h), (x+w, y+h)] if kind == "bracket" else
                  [(x, y), (x+w, y+h/2), (x, y+h)])
        markup = '<polyline points="' + " ".join(f"{n(a)},{n(b)}" for a, b in points) + '"'
        length = 2*w+h if kind == "bracket" else 2*math.hypot(w,h/2)
    elif kind == "freehand_ML":
        points = []
        path = f"M {n(x)} {n(y)} L {n(x+w)} {n(y+h/2)} L {n(x)} {n(y+h)}"
        markup = f'<path d="{path}"'
        length = 2*math.hypot(w,h/2)
    else:
        points = []
        def p(a, b):
            return (x+w*a, y+h*b)
        if kind in {"freehand_Q", "underline"}:
            controls = [p(0, 0), p(1, .5), p(0, 1)] if kind == "freehand_Q" else [p(.04,.35), p(.48,.82), p(.96,.42)]
            path = f'M {n(controls[0][0])} {n(controls[0][1])} Q ' + " ".join(n(value) for pair in controls[1:] for value in pair)
            length = curve_length(controls)
        else:
            curves = ([p(0,0), p(1,0), p(1,1), p(0,1)],) if kind == "freehand_C" else (
                [p(.52,.04), p(.82,.02), p(.96,.20), p(.96,.51)],
                [p(.96,.51), p(.97,.78), p(.73,.96), p(.49,.95)],
                [p(.49,.95), p(.18,.97), p(.04,.77), p(.04,.48)],
                [p(.04,.48), p(.04,.20), p(.25,.04), p(.52,.04)])
            path = f'M {n(curves[0][0][0])} {n(curves[0][0][1])} ' + " ".join(
                "C " + " ".join(n(value) for pair in controls[1:] for value in pair) for controls in curves)
            length = sum(curve_length(controls) for controls in curves)
        markup = f'<path d="{path}"'
        if kind in {"underline", "highlight"}:
            path = None
    geometry["points"] = [{"x": a, "y": b} for a, b in points]
    return ("freehand" if kind.startswith("freehand") else kind), geometry, path, markup, length


def geometry_split_family(portrait, kind="bracket", mode="draw"):
    from atme.render.v2_split import _observed_split_placements

    layout, _, resolved = geometry_boundary()
    raw = layout.model_dump(mode="json")
    _, _, timeline = split_documents("SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9")
    raw["output_profile"] = timeline["output_profile"]
    raw["canvas"] = {"x": 0, "y": 0, "width": 720 if portrait else 1280, "height": 1280 if portrait else 720}
    boxes = ({"source": (160., 80., 80., 120.), "part-1": (100., 400., 80., 120.), "part-2": (160., 400., 80., 120.)}
             if portrait else {"source": (80., 100., 80., 120.), "part-1": (400., 100., 80., 120.), "part-2": (460., 100., 80., 120.)})
    literal = {}
    expected_hashes = {}
    expected_payloads = {}
    for obj in raw["objects"]:
        object_type, geometry, path, markup, length = authored_geometry(kind, boxes[obj["object_id"]])
        obj.update(object_type=object_type, path_data=path, geometry=geometry)
        obj["style"]["fill"] = None
        obj["style"]["stroke"] = {"source": "ink.primary", "part-1": "ink.accent", "part-2": "attention"}[obj["object_id"]]
        if mode == "enter" and obj["object_id"] != "source":
            obj["transform"]["position"]["x"] = -80.
        # Independently authored identity projection, not a runtime receipt.
        payload = {key: obj[key] for key in ("object_type", "geometry", "style", "anchors", "asset_id", "path_data")}
        expected_payloads[obj["object_id"]] = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        expected_hashes[obj["object_id"]] = sha256(expected_payloads[obj["object_id"]].encode()).hexdigest()
        literal[obj["object_id"]] = (markup, length)
    layout = ExecutableLayoutV2.model_validate(raw)
    before = sample_for_layout(layout)
    raw_action = resolved.model_dump(mode="json")
    raw_action["end_ms"] = 40
    policy = raw_action["action"]["split_policy"]
    # Fixture placement projection reuses capture geometry only; expected
    # content digests above are wholly independent of the identity producer.
    from atme.render.v2_split_identity import SplitContentReceipt
    receipts = {key: SplitContentReceipt(key, expected_payloads[key], value) for key, value in expected_hashes.items()}
    objects = {obj.object_id: obj for obj in layout.objects}
    policy["source_basis"]["placements"] = [row.model_dump(mode="json") for row in
        _observed_split_placements(before, objects, set(objects), receipts)]
    for row in policy["correspondences"]:
        row.update(source_content_sha256=expected_hashes["source"], result_content_sha256=expected_hashes[row["result_object_id"]])
    for row in policy["results"]:
        row["construction"]["mode"] = mode
        if mode == "enter":
            row["construction"]["enter_destination"] = row["destination"]
    # Semantic enumeration is intentionally opposite to captured sibling paint
    # order. Overlapping colored strokes make an ordering error visible.
    policy["results"].reverse()
    policy["correspondences"].reverse()
    policy["source_basis"]["result_closures"].reverse()
    policy["source_basis_sha256"] = digest(policy["source_basis"])
    completion = _split_expected_completion(SplitPolicy.model_validate(policy))
    completion["completion_sha256"] = digest(completion)
    raw_action["split_completion_receipt"] = completion
    resolved = ResolvedAction.model_validate(raw_action)
    timeline["actions"] = [raw_action]
    timeline["initial_object_states"] = [{"object_id": row.object_id, "state": row.state, "state_version": 1,
                                          "visible": row.visible} for row in before.objects]
    return layout, before, resolved, ResolvedVisualTimelineV2.model_validate(timeline), expected_hashes, literal, boxes


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", GEOMETRY_KINDS)
@pytest.mark.parametrize("mode", ["draw", "reveal", "enter"])
def test_split_family_matrix_geometry_identity_real_pixels_and_shuffled_seek(portrait, kind, mode):
    import xml.etree.ElementTree as ET

    from atme.render.v2_state import _sample_validated_frame, camera_segments

    layout, before, resolved, timeline, expected_hashes, literal, boxes = geometry_split_family(portrait, kind, mode)
    capture = capture_split(resolved, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    for key in ("source", "part-1", "part-2"):
        admission = split_family_admission(key, capture, layout, inputs)
        assert admission.family == "geometry" and admission.content_sha256 == expected_hashes[key]
        assert admission.mode == ("source_fade" if key == "source" else mode)
    replay = replay_split(layout, before, (resolved,), duration=timeline.duration_ms)
    cameras = camera_segments(layout, timeline, replay)
    outputs = {}
    for at in (40, 0, 12, 40, 12, 0):
        snapshot = _sample_validated_frame(layout, timeline, replay, cameras, at)
        svg = _compose_validated_svg_frame(layout, timeline, snapshot, {}, split_inputs=inputs)
        actual_order = [node.attrib["data-object-id"] for node in ET.fromstring(svg.svg).iter()
                        if "data-object-id" in node.attrib]
        assert actual_order == ({0: ["source"], 12: ["source", "part-1", "part-2"], 40: ["part-1", "part-2"]}[at])
        png = _rasterize_svg_frame(layout, svg, split_inputs=inputs).png
        if at in outputs:
            assert (svg.svg, png) == outputs[at]
        outputs[at] = (svg.svg, png)
    width, height = layout.output_profile.width, layout.output_profile.height
    colors = json.loads(inputs.style_json)["colors"]
    for at, fraction, source_alpha in ((0, 0, 1), (12, .5, .8333), (40, 1, 0)):
        body = [f'<rect width="{width}" height="{height}" fill="#FAF8F1"/>']
        for key in ("source", "part-1", "part-2"):
            alpha = source_alpha if key == "source" else 1
            if not alpha or key != "source" and fraction == 0:
                continue
            markup, length = literal[key]
            dash = (f' stroke-dasharray="{n(length)} {n(length)}" stroke-dashoffset="{n(length/2)}"'
                    if key != "source" and fraction == .5 and mode == "draw" else "")
            weight = json.loads(inputs.style_json)["strokes"]["emphasis_px"]*2/3 if kind == "highlight" else 4*2/3
            color = colors[{"source": "ink", "part-1": "accent", "part-2": "attention"}[key]]
            inner = f'{markup} fill="none" stroke="{color}" stroke-width="{n(weight)}" stroke-linecap="round" stroke-linejoin="round"{dash}/>'
            if key != "source" and fraction == .5 and mode in {"reveal", "enter"}:
                x, y, w, h = boxes[key]
                clip_id = "oracle-" + key
                inner = (f'<defs><clipPath id="{clip_id}"><rect x="{n(x)}" y="{n(y)}" width="{n(w/2)}" height="{n(h)}"/></clipPath></defs>'
                         f'<g clip-path="url(#{clip_id})">{inner}</g>')
            transform = ' transform="translate(-40 0)"' if key != "source" and fraction == .5 and mode == "enter" else ""
            body.append(f'<g opacity="{alpha}"{transform}>{inner}</g>')
        expected_svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">{"".join(body)}</svg>'
        with (Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=expected_svg, skip_system_fonts=True))) as expected,
              Image.open(io.BytesIO(outputs[at][1])) as actual):
            assert actual.convert("RGBA").tobytes() == expected.convert("RGBA").tobytes()


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", GEOMETRY_KINDS)
@pytest.mark.parametrize("mode", ["draw", "reveal", "enter"])
def test_geometry_family_has_native_continuous_coverage(portrait, kind, mode):
    from atme.render.v2_split_paint import prove_split_coverage

    layout, before, resolved, _, expected_hashes, _, _ = geometry_split_family(portrait, kind, mode)
    capture = capture_split(resolved, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    original = repr(capture)
    proof = prove_split_coverage(capture, layout, inputs)
    assert proof.paint_inputs_sha256 == inputs.inputs_sha256
    assert proof.critical_times_ms[0] == 0 and proof.critical_times_ms[-1] == 40
    assert all(row.start_ms < row.end_ms and row.painted_root_ids for row in proof.intervals)
    assert proof.intervals[0].start_ms == 0 and proof.intervals[-1].end_ms == 40
    assert proof.intervals[-1].painted_root_ids == ("part-1", "part-2")
    assert repr(capture) == original
    assert split_family_admission("part-1", capture, layout, inputs).content_sha256 == expected_hashes["part-1"]


@pytest.mark.parametrize("kind", GEOMETRY_KINDS)
def test_geometry_family_rejects_incompatible_write_mode(kind):
    layout, before, resolved, _, _, _, _ = geometry_split_family(False, kind, "write")
    capture = capture_split(resolved, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    with pytest.raises(ValueError, match="Split write is incompatible with geometry construction"):
        split_family_admission("part-1", capture, layout, inputs)


@pytest.mark.parametrize("kind", GEOMETRY_KINDS)
def test_geometry_family_fresh_paint_inputs_cannot_replace_captured_payload(kind):
    layout, before, resolved, _, _, _, _ = geometry_split_family(False, kind)
    capture = capture_split(resolved, layout, before, {})
    next(obj for obj in layout.objects if obj.object_id == "part-1").geometry.bounds.width += 1
    inputs = verify_split_paint_inputs(layout, {})
    with pytest.raises(ValueError, match="Split captured content differs"):
        split_family_admission("part-1", capture, layout, inputs)


@pytest.mark.parametrize("mutation", ["points", "path", "style"])
def test_geometry_family_coherent_payload_mutation_is_not_new_authority(mutation):
    kind = "freehand_C" if mutation == "path" else "bracket"
    layout, before, resolved, _, _, _, _ = geometry_split_family(False, kind)
    capture = capture_split(resolved, layout, before, {})
    obj = next(row for row in layout.objects if row.object_id == "part-1")
    if mutation == "points":
        obj.geometry.points[0].x -= 1
    elif mutation == "path":
        tokens = obj.path_data.split()
        tokens[1] = str(float(tokens[1])+1)
        obj.path_data = " ".join(tokens)
    else:
        obj.style.stroke = "ink.primary"
    inputs = verify_split_paint_inputs(layout, {})
    with pytest.raises(ValueError, match="Split captured content differs"):
        split_family_admission("part-1", capture, layout, inputs)


@pytest.mark.parametrize("fault", ["missing", "forged"])
def test_geometry_family_rehashed_paint_labels_do_not_attest_primitive(fault):
    from dataclasses import replace

    layout, before, resolved, _, _, _, _ = geometry_split_family(False)
    capture = capture_split(resolved, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    rows = [json.loads(row) for row in inputs.paint_evidence]
    if fault == "missing":
        rows = [row for row in rows if row.get("object_id") != "part-1"]
    else:
        next(row for row in rows if row.get("object_id") == "part-1")["proof_kind"] = "author_claim"
    manifest = json.loads(inputs.manifest_json)
    manifest["paint_evidence"] = rows
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    forged = replace(inputs, paint_evidence=tuple(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                     for row in rows), manifest_json=encoded, inputs_sha256=sha256(encoded.encode()).hexdigest())
    with pytest.raises(ValueError, match="Split frozen paint binding differs"):
        split_family_admission("part-1", capture, layout, forged)


def test_validated_local_geometry_alpha_cache_reuses_only_exact_native_svg(monkeypatch):
    from atme.render import v2_split_paint

    assert hasattr(v2_split_paint, "_geometry_alpha_facts"), "Exact-SVG local alpha cache missing"
    v2_split_paint._geometry_alpha_facts.cache_clear()
    native = resvg_py.svg_to_bytes
    observed = []
    def counted_native(**kwargs):
        observed.append(kwargs["svg_string"])
        return native(**kwargs)
    monkeypatch.setattr(resvg_py, "svg_to_bytes", counted_native)
    layout, _, _, _, _, _, _ = geometry_split_family(False, "rectangle")
    first = verify_split_paint_inputs(layout, {})
    assert len(observed) == 3
    assert verify_split_paint_inputs(layout, {}) == first and len(observed) == 3
    obj = next(row for row in layout.objects if row.object_id == "part-1")
    obj.geometry.bounds.width += 1
    assert verify_split_paint_inputs(layout, {}).inputs_sha256 != first.inputs_sha256
    assert len(observed) == 4
    obj.geometry.bounds.width -= 1
    obj.style.stroke = "ink.primary"
    verify_split_paint_inputs(layout, {})
    assert len(observed) == 5
    # A warmed valid cache cannot hide invalid authored geometry.
    obj.geometry.corner_radius = 1
    with pytest.raises(ValueError, match="ignored corner radius"):
        verify_split_paint_inputs(layout, {})
    assert len(observed) == 5
    obj.geometry.corner_radius = None
    raw = layout.model_dump(mode="json")
    _, _, portrait = split_documents("SHORT_FORM_9_16")
    raw["output_profile"] = portrait["output_profile"]
    raw["canvas"] = {"x": 0, "y": 0, "width": 720, "height": 1280}
    changed_profile = ExecutableLayoutV2.model_validate(raw)
    verify_split_paint_inputs(changed_profile, {})
    assert len(observed) == 8  # all three complete SVG headers changed
    next(row for row in changed_profile.objects if row.object_id == "part-1").geometry.bounds.x += 1
    verify_split_paint_inputs(changed_profile, {})
    assert len(observed) == 9  # changed local geometry/viewBox cannot hit
    from dataclasses import replace

    from atme.render.v2_split_paint import _checked_split_resources
    rows = list(first.bundle_bytes)
    index = next(index for index, row in enumerate(rows) if row[0].startswith("fonts/"))
    name, _, payload = rows[index]
    corrupted = payload+b"\0"
    rows[index] = (name, sha256(corrupted).hexdigest(), corrupted)
    forged = replace(first, bundle_bytes=tuple(rows))
    with pytest.raises(ValueError, match="Split bundle checksum mismatch"):
        _checked_split_resources(geometry_split_family(False, "rectangle")[0], forged)
    assert len(observed) == 9  # warm geometry evidence does not bypass byte pins
    assert v2_split_paint._geometry_alpha_facts.cache_info().maxsize == 128
    v2_split_paint._geometry_alpha_facts.cache_clear()


@pytest.mark.parametrize("portrait", [False, True])
def test_geometry_family_authored_movement_after_construction_has_real_pixels(portrait):
    from atme.render.v2_split_paint import prove_split_coverage
    from atme.render.v2_state import _sample_validated_frame, camera_segments

    layout, before, resolved, timeline, _, literal, _ = geometry_split_family(portrait, "bracket")
    raw = resolved.model_dump(mode="json")
    policy = raw["action"]["split_policy"]
    result = next(row for row in policy["results"] if row["object_id"] == "part-1")
    original = result["destination"]
    moved = {**original, "position": {"x": 60., "y": 0.}}
    result.update(destination=moved, movement={"phase": {"start_tick": 6000, "end_tick": 10000,
        "easing": "linear"}, "from_transform": original, "destination": moved})
    completion = _split_expected_completion(SplitPolicy.model_validate(policy))
    completion["completion_sha256"] = digest(completion)
    raw["split_completion_receipt"] = completion
    resolved = ResolvedAction.model_validate(raw)
    timeline = timeline.model_copy(update={"actions": [resolved]})
    capture = capture_split(resolved, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    proof = prove_split_coverage(capture, layout, inputs)
    assert 24 in proof.critical_times_ms and 40 in proof.critical_times_ms
    replay = replay_split(layout, before, (resolved,), duration=timeline.duration_ms)
    cameras = camera_segments(layout, timeline, replay)
    width, height = layout.output_profile.width, layout.output_profile.height
    colors = json.loads(inputs.style_json)["colors"]
    for at, translation, source_alpha in ((24, 0, .3333), (32, 30, 0), (40, 60, 0)):
        snapshot = _sample_validated_frame(layout, timeline, replay, cameras, at)
        svg = _compose_validated_svg_frame(layout, timeline, snapshot, {}, split_inputs=inputs)
        actual_png = _rasterize_svg_frame(layout, svg, split_inputs=inputs).png
        body = [f'<rect width="{width}" height="{height}" fill="#FAF8F1"/>']
        for key in ("source", "part-1", "part-2"):
            if key == "source" and not source_alpha:
                continue
            color = colors[{"source": "ink", "part-1": "accent", "part-2": "attention"}[key]]
            markup, _ = literal[key]
            body.append(f'<g opacity="{source_alpha if key == "source" else 1}" transform="translate({translation if key == "part-1" else 0} 0)">'
                        f'{markup} fill="none" stroke="{color}" stroke-width="2.6667" stroke-linecap="round" stroke-linejoin="round"/></g>')
        expected_svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">{"".join(body)}</svg>'
        with (Image.open(io.BytesIO(actual_png)) as actual,
              Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=expected_svg, skip_system_fonts=True))) as expected):
            assert actual.convert("RGBA").tobytes() == expected.convert("RGBA").tobytes()
