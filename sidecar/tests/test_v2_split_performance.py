"""Task10 maximum authored inventory and process-isolated native measurements."""

import importlib.util
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest


def _density_document(executable, grouped):
    from v2_fixtures import executable_layout_v2, visual_plan_v2
    raw = executable_layout_v2() if executable else visual_plan_v2()
    template = raw["objects"][0]
    leaves = []
    for index in range(14):
        leaf = deepcopy(template)
        leaf.update(object_id=f"density-leaf-{index}", object_type="rectangle")
        if executable:
            leaf["geometry"]["corner_radius"] = None
            leaf["parent_id"] = "density-group" if grouped else None
        leaves.append(leaf)
    added = leaves
    if grouped:
        group = deepcopy(template)
        group.update(object_id="density-group", object_type="group", child_ids=[o["object_id"] for o in leaves])
        if executable:
            group.pop("path_data", None)
            group["geometry"]["corner_radius"] = None
            group["style"] = {"stroke": None, "fill": None, "text": None, "effect": None}
        added = [group, *leaves]
    raw["objects"].extend(added)
    ids = [o["object_id"] for o in added]
    raw["boards"][0]["object_ids"].extend(ids)
    raw["boards"][0]["density_limit"] = 12
    if not executable:
        raw["beats"][0]["object_ids"].extend(ids)
    return raw


@pytest.mark.parametrize("executable", [False, True])
def test_density_counts_roots_and_preserves_structural_inventory(executable):
    from atme.store.contracts_v2 import ExecutableLayoutV2, VisualPlanV2
    cls = ExecutableLayoutV2 if executable else VisualPlanV2
    parsed = cls.model_validate(_density_document(executable, True))
    assert len(parsed.objects) == 18
    assert len(parsed.boards[0].object_ids) == 18
    with pytest.raises(ValueError, match="exceeds density limit"):
        cls.model_validate(_density_document(executable, False))


@pytest.mark.parametrize("executable", [False, True])
@pytest.mark.parametrize("fault", ["cross-board", "unknown", "inventory", "duplicate"])
def test_density_descendants_preserve_board_identity_guards(executable, fault):
    from atme.store.contracts_v2 import ExecutableLayoutV2, VisualPlanV2
    raw = _density_document(executable, True)
    if fault == "cross-board":
        board = deepcopy(raw["boards"][0])
        board.update(board_id="other", object_ids=["density-leaf-0"])
        raw["boards"].append(board)
        raw["boards"][0]["object_ids"].remove("density-leaf-0")
        next(o for o in raw["objects"] if o["object_id"] == "density-leaf-0")["board_id"] = "other"
    elif fault == "unknown":
        raw["boards"][0]["object_ids"].append("unknown")
    elif fault == "inventory":
        raw["boards"][0]["object_ids"].remove("density-leaf-0")
    else:
        raw["objects"].append(deepcopy(raw["objects"][-1]))
    with pytest.raises(ValueError):
        (ExecutableLayoutV2 if executable else VisualPlanV2).model_validate(raw)


@pytest.mark.parametrize("executable", [False, True])
def test_density_legacy_flat_documents_and_field_bounds_unchanged(executable):
    from atme.store.contracts_v2 import ExecutableLayoutV2, VisualPlanV2
    from v2_fixtures import executable_layout_v2, visual_plan_v2
    cls = ExecutableLayoutV2 if executable else VisualPlanV2
    raw = executable_layout_v2() if executable else visual_plan_v2()
    assert len(cls.model_validate(raw).objects) == 3
    for count in (0, 13):
        raw["boards"][0]["density_limit"] = count
        with pytest.raises(ValueError):
            cls.model_validate(raw)


@pytest.mark.parametrize("portrait", [False, True])
def test_untraced_recording_uses_actual_native_parity_and_process_memory(tmp_path, portrait, monkeypatch):
    """Bounded instrumentation check; this is not the maximum inventory proof."""
    import tracemalloc as allocation_trace

    from test_v2_split_families import geometry_split_family

    assert not allocation_trace.is_tracing()

    def native_fixture(authored_portrait):
        assert not allocation_trace.is_tracing(), "measurement enabled Python allocation tracing"
        return (*geometry_split_family(authored_portrait, "rectangle", "reveal")[:4], {})

    monkeypatch.setattr(sys.modules[__name__], "authored_performance_fixture", native_fixture)
    try:
        record = _measure(tmp_path, portrait)
    finally:
        if allocation_trace.is_tracing():
            allocation_trace.stop()
    assert record["inventory"] == {"results": 2, "bound_objects": 3, "painted_leaves": 3}
    assert record["repeated_seek_parity_verified"] is True
    assert record["seek_order_ms"] == [40, 0, 12, 39, 24, 32, 12, 0, 40]
    assert set(record["frames"]) == {"0", "12", "24", "32", "39", "40"}
    assert len(record["sample_compose_raster_ms"]) == 9
    assert record["network_forbidden"] and record["immutable_input_keys_unchanged"]
    assert "python_tracemalloc_peak_bytes" not in record["memory"]
    assert record["memory"]["process_working_set_bytes"] > 0
    assert record["memory"]["process_peak_working_set_bytes"] >= record["memory"]["process_working_set_bytes"]
    assert "not separately traced" in record["memory"]["memory_scope"]


def authored_performance_fixture(portrait=False):
    """One read ancestor, 257 owned groups and3838 genuinely painted leaves."""
    from atme.render.v2_split import _observed_split_placements
    from atme.store.contracts_v2 import (
        ExecutableLayoutV2,
        ResolvedAction,
        ResolvedVisualTimelineV2,
        SplitPolicy,
        _split_expected_completion,
    )
    from test_v2_split_families import authored_geometry, geometry_split_family
    from test_v2_split_identity import sample_for_layout
    from test_v2_split_reusable_family import independent_receipts
    from v2_fixtures import digest
    from v2_split_fixtures import split_policy

    base, _, resolved, timeline, *_ = geometry_split_family(portrait, "rectangle", "reveal")
    raw = base.model_dump(mode="json")
    template = deepcopy(raw["objects"][0])
    raw["objects"] = []
    closures = {}
    roots = ["source"] + [f"part-{i}" for i in range(1, 257)]
    for ordinal, key in enumerate(roots):
        # All authored tiles and every leaf are on canvas in both profiles.
        x = 20. + (ordinal % 17) * (40. if portrait else 72.)
        y = 20. + (ordinal // 17) * (76. if portrait else 42.)
        leaves = [f"{key}-ink-{i:02d}" for i in range(15 if 1 <= ordinal <= 240 else 14)]
        root = deepcopy(template)
        root.update(object_id=key, object_type="group", parent_id="performance-stage", child_ids=leaves,
                    z_index=ordinal, visible=key == "source", initial_state="visible" if key == "source" else "hidden",
                    anchors=[], style={"stroke": None, "fill": None, "text": None, "effect": None})
        root["geometry"]["bounds"].update(x=0., y=0., width=30., height=30.)
        root.pop("path_data", None)
        root["transform"].update(position={"x": x, "y": y}, origin={"x": 0., "y": 0.}, scale_x=1., scale_y=1., rotation_degrees=0.)
        raw["objects"].append(root)
        closures[key] = sorted([key, *leaves])
        for index, leaf_id in enumerate(leaves):
            leaf = deepcopy(template)
            _, geometry, path, _, _ = authored_geometry("rectangle", ((index % 3)*10., (index // 3)*6., 7., 3.))
            leaf.update(object_id=leaf_id, parent_id=key, z_index=index,
                        visible=True, initial_state="visible", geometry=geometry, path_data=path)
            leaf["transform"].update(position={"x": 0., "y": 0.}, origin={"x": 0., "y": 0.}, scale_x=1., scale_y=1., rotation_degrees=0.)
            raw["objects"].append(leaf)
    stage = deepcopy(raw["objects"][0])
    stage.update(object_id="performance-stage", parent_id=None, child_ids=roots, z_index=0,
                 visible=True, initial_state="visible")
    stage["transform"]["position"] = {"x": 0., "y": 0.}
    stage["geometry"]["bounds"].update(width=raw["canvas"]["width"], height=raw["canvas"]["height"])
    raw["objects"].append(stage)
    assert len(raw["objects"]) == len({o["object_id"] for o in raw["objects"]}) == 4096
    raw["boards"][0].update(object_ids=[o["object_id"] for o in raw["objects"]])
    layout = ExecutableLayoutV2.model_validate(raw)
    raw = layout.model_dump(mode="json")
    before = sample_for_layout(layout)
    receipts = independent_receipts(raw)
    action = resolved.model_dump(mode="json")
    policy = split_policy(256)
    basis = policy["source_basis"]
    basis.update(source_closure={"root_id": "source", "owned_ids": closures["source"]},
                 result_closures=[{"root_id": key, "owned_ids": closures[key]} for key in roots[1:]],
                 read_dependencies=[{"kind": "ancestor", "object_ids": sorted(["performance-stage", *roots])}],
                 style_sha256=resolved.action.split_policy.source_basis.style_sha256,
                 registry_sha256=resolved.action.split_policy.source_basis.registry_sha256)
    objects = {o.object_id: o for o in layout.objects}
    basis["placements"] = [row.model_dump(mode="json") for row in _observed_split_placements(before, objects, set(objects), receipts)]
    for result, correspondence in zip(policy["results"], policy["correspondences"]):
        key = result["object_id"]
        result["destination"] = objects[key].transform.model_dump(mode="json")
        correspondence.update(source_content_sha256=receipts["source"].content_sha256,
                              result_content_sha256=receipts[key].content_sha256)
    policy["source_basis_sha256"] = digest(basis)
    action["action"]["split_policy"] = policy
    completion = _split_expected_completion(SplitPolicy.model_validate(policy))
    completion["completion_sha256"] = digest(completion)
    action["split_completion_receipt"] = completion
    clock = timeline.model_dump(mode="json")
    clock.update(actions=[action], layout_sha256=digest(raw), initial_object_states=[
        {"object_id": row.object_id, "state": row.state, "visible": row.visible, "state_version": 1} for row in before.objects])
    return layout, before, ResolvedAction.model_validate(action), ResolvedVisualTimelineV2.model_validate(clock), {}


def _working_set():
    """Native-inclusive process residency; distinct from Python traced allocations."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [(name, ctypes.c_size_t) for name in
                ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return {"process_working_set_bytes": counters.WorkingSetSize,
                "process_peak_working_set_bytes": counters.PeakWorkingSetSize,
                "process_memory_api": "Windows GetProcessMemoryInfo; whole process, includes native allocations"}
    raise RuntimeError("Task10 working-set measurement is authored for the Windows proof host")


def _measure(output_dir, portrait):
    path = Path(__file__).resolve().parents[2] / "bench/verify_v2_split.py"
    spec = importlib.util.spec_from_file_location("split_performance_benchmark", path)
    benchmark = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(benchmark)
    from hashlib import sha256

    from v2_fixtures import digest
    inventory, frozen = {}, {}
    original_replay = benchmark._replay_split_chronology
    original_inputs = benchmark.verify_split_paint_inputs

    def observed_inputs(layout, assets):
        inputs = original_inputs(layout, assets)
        frozen.update(layout_sha256=sha256(layout.model_dump_json().encode()).hexdigest(),
                      manifest_sha256=sha256(inputs.manifest_json.encode()).hexdigest(),
                      asset_pins_sha256=sha256(inputs.asset_pins_json.encode()).hexdigest(),
                      paint_inputs_sha256=inputs.inputs_sha256,
                      bundle_resources=[{"key": key, "sha256": pin, "actual_bytes_sha256": sha256(data).hexdigest()}
                                        for key, pin, data in inputs.bundle_bytes])
        return inputs

    def observed_replay(layout, before, actions, duration_ms, assets, **kwargs):
        replay = original_replay(layout, before, actions, duration_ms, assets, **kwargs)
        captures = {row.resolved_index: row.split_capture for checkpoint in replay.checkpoints
                    for row in checkpoint.active if hasattr(row, "split_capture")}
        assert len(captures) == 1
        capture = next(iter(captures.values()))
        owned, reads = set(capture.owned_object_ids), set(capture.read_dependency_ids)
        inventory.update(results=len(json.loads(capture.policy_json)["results"]), bound_objects=len(owned | reads),
                         painted_leaves=sum(obj.object_type == "rectangle" for obj in layout.objects))
        frozen.update(captured_policy_sha256=sha256(capture.policy_json.encode()).hexdigest(),
                      captured_owned_ids_sha256=digest(sorted(owned)), captured_read_ids_sha256=digest(sorted(reads)),
                      baseline_state_sha256=sha256(repr(before).encode()).hexdigest())
        frozen["ownership"] = {"owned_objects": len(owned), "read_objects": len(reads),
                               "read_only_objects": len(reads - owned), "owned_roots": len(capture.owned_root_ids)}
        return replay

    benchmark.verify_split_paint_inputs = observed_inputs
    benchmark._replay_split_chronology = observed_replay

    def fixture(p, _kind, _mode):
        values = authored_performance_fixture(p)
        frozen["timeline_sha256"] = sha256(values[3].model_dump_json().encode()).hexdigest()
        return values

    record = benchmark._native_case(Path(output_dir), portrait, "maximum", "reveal", "performance",
                                   fixture)
    # _native_case returns only after repeated SVG/PNG/state equality checks.
    record["repeated_seek_parity_verified"] = True
    record["memory"] = {"memory_scope": "Windows whole-process resident working-set includes Python/native allocations and mapped pages; Python allocations are not separately traced",
                        **_working_set()}
    for frame in record["frames"].values():
        frame["state_keys_sha256"] = digest({"versions": frame.pop("state_versions"), "states": frame.pop("state_sha256")})
    record.update(inventory=inventory, frozen_input_keys=frozen,
                  cold_scope="first native seek in a fresh Python process; OS filesystem caches are not flushed",
                  timing_scope="perf_counter wall milliseconds; Python allocation tracing disabled; capture precedes first seek",
                  cold_first_seek_ms=record["sample_compose_raster_ms"][0],
                  warm_seek_ms=record["sample_compose_raster_ms"][1:])
    return record


def performance_case(output_dir: Path, portrait: bool) -> dict:
    """Run one profile serially in a fresh process, preserving native artifacts."""
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    result = output_dir / ("performance-portrait.json" if portrait else "performance-landscape.json")
    if result.exists():
        raise FileExistsError(result)
    root = Path(__file__).resolve().parents[2]
    env = dict(os.environ, PYTHONPATH=os.pathsep.join((str(root / "sidecar/src"), str(root / "sidecar/tests"))))
    command = [sys.executable, str(Path(__file__).resolve()), "--measure", str(output_dir), str(int(portrait)), str(result)]
    with result.with_suffix(".log").open("x", encoding="utf-8") as log:
        subprocess.run(command, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    return json.loads(result.read_text(encoding="utf-8"))


@pytest.mark.parametrize("portrait", [False, True])
def test_maximum_fixture_is_a_real_closed_authored_inventory(portrait):
    assert "authored_performance_fixture" in globals(), "maximum authored performance fixture missing"
    layout, before, action, timeline, assets = authored_performance_fixture(portrait)
    from atme.render.v2_split import capture_split
    capture = capture_split(action, layout, before, assets)
    assert len(action.action.split_policy.results) == 256
    assert len(layout.objects) == 4096
    assert set(capture.owned_object_ids) | set(capture.read_dependency_ids) == {o.object_id for o in layout.objects}
    assert len(capture.owned_object_ids) == 4095
    assert set(capture.read_dependency_ids) - set(capture.owned_object_ids) == {"performance-stage"}
    assert sum(o.object_type == "rectangle" for o in layout.objects) == 3838
    assert len(timeline.initial_object_states) == 4096


@pytest.mark.parametrize("portrait", [False, True])
def test_maximum_native_process_cold_and_warm_seek_proof(tmp_path, portrait):
    assert "performance_case" in globals(), "maximum native measurement interface missing"
    record = performance_case(tmp_path, portrait)
    assert record["inventory"] == {"results": 256, "bound_objects": 4096, "painted_leaves": 3838}
    assert record["frozen_input_keys"]["ownership"]["owned_objects"] == 4095
    assert record["frozen_input_keys"]["ownership"]["read_only_objects"] == 1
    assert record["network_forbidden"] and record["immutable_input_keys_unchanged"]
    assert record["cold_scope"] == "first native seek in a fresh Python process; OS filesystem caches are not flushed"
    assert record["seek_order_ms"] == [40, 0, 12, 39, 24, 32, 12, 0, 40]
    assert set(record["frames"]) == {"0", "12", "24", "32", "39", "40"}
    assert record["repeated_seek_parity_verified"] is True
    assert len(record["sample_compose_raster_ms"]) == 9
    assert all(t >= 0 for t in record["sample_compose_raster_ms"])
    assert "python_tracemalloc_peak_bytes" not in record["memory"]
    assert record["memory"]["process_peak_working_set_bytes"] > 0
    assert record["frames"]["0"]["png_sha256"] != record["frames"]["40"]["png_sha256"]
    for frame in record["frames"].values():
        assert Path(frame["svg_path"]).read_text(encoding="utf-8").startswith("<svg")
        assert Path(frame["png_path"]).read_bytes().startswith(b"\x89PNG")
    import xml.etree.ElementTree as ET

    from PIL import Image
    midpoint = ET.parse(record["frames"]["12"]["svg_path"])
    painted_ids = {node.attrib["data-object-id"] for node in midpoint.iter() if "data-object-id" in node.attrib}
    assert len(painted_ids) == 4096
    assert {"performance-stage", "source", *[f"part-{i}" for i in range(1, 257)]} <= painted_ids
    for at, ordinals in ((0, (0,)), (40, range(1, 257))):
        with Image.open(record["frames"][str(at)]["png_path"]) as png:
            assert png.size == ((720, 1280) if portrait else (1280, 720))
            pixels = png.convert("RGB")
            background = pixels.getpixel((0, 0))
            for ordinal in ordinals:
                x = 20 + (ordinal % 17) * (40 if portrait else 72)
                y = 20 + (ordinal // 17) * (76 if portrait else 42)
                for leaf in range(15 if 1 <= ordinal <= 240 else 14):
                    assert pixels.getpixel((x + (leaf % 3)*10 + 3, y + (leaf // 3)*6)) != background
    assert Path(record["contact_sheet_path"]).is_file()


if __name__ == "__main__":
    import faulthandler
    faulthandler.dump_traceback_later(900)
    if len(sys.argv) != 5 or sys.argv[1] != "--measure":
        raise SystemExit("usage: test_v2_split_performance.py --measure OUTPUT PORTRAIT RESULT")
    measured = _measure(Path(sys.argv[2]), bool(int(sys.argv[3])))
    with Path(sys.argv[4]).open("x", encoding="utf-8") as output:
        json.dump(measured, output, indent=2)
