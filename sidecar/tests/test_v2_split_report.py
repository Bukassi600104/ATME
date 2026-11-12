"""Synthetic metadata checks the reconciler; it grants no actual native credit."""

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
from test_v2_split_acceptance import split_benchmark


def test_complete_report_reconciler_exists():
    assert callable(getattr(split_benchmark(), "reconcile_report", None)), "Missing complete evidence reconciler"


def test_canonical_native_slots_keep_existing_matrix_and_sections_disjoint():
    from test_v2_split_project_flows import PROJECT_FLOW_CASE_IDS

    required = split_benchmark().required_native_cases()
    assert len(required) == 634
    assert {key for key, proof in required.items() if proof == "project"} == set(PROJECT_FLOW_CASE_IDS)
    assert not any(key.startswith(("cold-count", "retained-50", "performance-maximum-", "tests/")) for key in required)
    assert sum(proof == "visual-state" for proof in required.values()) == 302
    assert sum(proof == "history" for proof in required.values()) == 36


@pytest.fixture
def synthetic_inventory(tmp_path, monkeypatch):
    """Entirely synthetic metadata; no renderer or real acceptance is exercised."""
    benchmark = split_benchmark()
    module = benchmark._evidence_module()
    monkeypatch.setattr(benchmark, "_evidence_module", lambda: module)
    monkeypatch.setattr(benchmark, "required_native_cases", lambda: {"synthetic-native": "synthetic"})

    def write(name, value):
        path = tmp_path / name
        raw = value if isinstance(value, bytes) else (json.dumps(value, sort_keys=True) + "\n").encode()
        path.write_bytes(raw)
        return {"path": str(path), "sha256": sha256(raw).hexdigest()}

    node = "tests/synthetic_metadata_only.py::test_control"
    log = write("terminal.log", b"SYNTHETIC METADATA ONLY: 1 passed")
    terminal_data = {"tool_exit_code": 0, "pytest_exit_code": 0, "failed": 0, "skipped": 0, "passed": 1,
                     "executed_ids": [node], "ordered_ids_sha256": module._ids_digest([node])}
    terminal = write("terminal.json", terminal_data)
    reach = write("reach.json", {"scope": "SYNTHETIC METADATA ONLY"})
    image = write("artifact.png", b"SYNTHETIC METADATA ONLY; not rendered pixels")
    svg = write("artifact.svg", b"<svg>SYNTHETIC METADATA ONLY</svg>")
    manifest = write("manifest.json", {"items": [image, svg]})
    source_name = "sidecar/tests/v2_split_fixtures.py"
    source_hash = sha256((benchmark.ROOT / source_name).read_bytes()).hexdigest()
    proof = {"terminal_sha256": terminal["sha256"], "log_sha256": log["sha256"],
             "manifest_sha256": manifest["sha256"], "reach_sha256": reach["sha256"],
             "current_source_pins": {source_name: source_hash}, "accepted_source_commit": "synthetic-metadata-only",
             "test_ids": [node], "case_records": {}}
    allowlist = {"scope": "SYNTHETIC METADATA ONLY; reconciler behavior, no native acceptance",
                 "proofs": {key: deepcopy(proof) for key in ("synthetic", "maximum", "cold-count", "retained50")},
                 "extra_test_ids": [], "schema_test_ids": [], "contract_test_ids": []}
    monkeypatch.setattr(module, "load_allowlist", lambda path: allowlist)
    sections = {key: [] for key in module.SECTIONS}
    slots = [("native_cases", "synthetic-native", "synthetic"),
             ("measurements", "performance-maximum-reveal-landscape", "maximum"),
             ("measurements", "performance-maximum-reveal-portrait", "maximum"),
             ("measurements", "cold-count-landscape", "cold-count"), ("measurements", "cold-count-portrait", "cold-count"),
             ("measurements", "retained-50-annotation-group", "retained50")]
    for section, slot, group in slots:
        record = {"case_id": slot, "final_acceptance": False, "network_forbidden": True,
                  "immutable_input_keys_unchanged": True, "frames": {"0": {"png_path": image["path"], "png_sha256": image["sha256"]}}}
        if slot.startswith("performance-maximum-"):
            record.update(profile="SHORT_FORM_9_16" if slot.endswith("portrait") else "LONG_FORM_16_9",
                          family="performance", kind="maximum", mode="reveal",
                          inventory={"results":256, "bound_objects":4096, "painted_leaves":3838},
                          seek_order_ms=[40, 0, 12, 39, 24, 32, 12, 0, 40], chronology_construction_ms=1.0,
                          sample_compose_raster_ms=[1.0]*9, cold_first_seek_ms=1.0, warm_seek_ms=[1.0]*8,
                          memory={"process_working_set_bytes":100, "process_peak_working_set_bytes":100,
                                  "process_memory_api":"Windows GetProcessMemoryInfo; whole process, includes native allocations"},
                          frozen_input_keys={"ownership":{"owned_objects":4095,"read_objects":1,"read_only_objects":1,"owned_roots":257}},
                          cold_scope="synthetic fresh process metadata only", timing_scope="synthetic wall milliseconds; untraced metadata only",
                          repeated_seek_parity_verified=True,
                          frames={at:{"png_path":image["path"],"png_sha256":image["sha256"],"svg_path":svg["path"],
                                      "svg_sha256":svg["sha256"],"state_keys_sha256":sha256(at.encode()).hexdigest()}
                                  for at in ("40","0","12","39","24","32")})
        elif slot.startswith("cold-count-"):
            record.update(original_bundle_and_paths_forbidden=True, caches_cleared_before_validation=True)
        elif slot.startswith("retained-"):
            record.update(frame_count=50, original_baselines_unchanged=True)
        ref = write(slot + ".json", record)
        allowlist["proofs"][group]["case_records"][slot] = sha256(json.dumps(record, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        sections[section].append({"id": slot, "proof": group, "terminal": terminal, "log": log,
                                  "reach": reach, "manifest": manifest, "record": ref})
    sections["negative_and_adjacent_tests"] = [{"id": node, "proof": "synthetic", "terminal": terminal, "log": log, "reach": reach}]
    sections["limitations"] = [{"id": key, "uncredited": True, "waived": False} for key in module.LIMITATIONS]
    inventory = {"version": 1, **sections}

    def run():
        write(module.INVENTORY, inventory)
        code = benchmark.main(["--output-dir", str(tmp_path)])
        return code, json.loads((tmp_path / "split-acceptance.json").read_text())

    return benchmark, module, inventory, allowlist, run, write, terminal_data


def test_complete_synthetic_report_is_ready_only_for_independent_review(synthetic_inventory):
    _, _, _, _, run, _, _ = synthetic_inventory
    code, report = run()
    assert code == 0 and report["status"] == "READY FOR INDEPENDENT REVIEW"
    assert report["final_acceptance"] is False and report["missing_required_proofs"] == []
    assert report["evidence_scope"].startswith("SYNTHETIC METADATA ONLY")
    assert len(report["native_cases"]) == 1 and len(report["measurements"]) == 5
    assert len(report["negative_and_adjacent_tests"]) == 1 and len(report["limitations"]) == 3


@pytest.mark.parametrize("change", ["missing", "failed", "skipped", "tampered", "stale", "duplicate", "extra",
                                  "aggregate", "unallowlisted", "caller_acceptance", "missing_reach", "missing_record_pin",
                                  "order_hash", "wrong_node", "waived", "unknown_section", "malformed_ref",
                                  "measurement", "different_seeks", "traced_maximum", "leaves", "ownership", "read_only",
                                  "frame_keys", "missing_svg", "missing_png", "repeat_parity", "state_key"])
def test_reconciler_fails_closed_for_unproved_metadata(synthetic_inventory, change):
    _, module, inventory, allowlist, run, write, terminal_data = synthetic_inventory
    row = inventory["native_cases"][0]
    if change == "missing":
        inventory["native_cases"].clear()
    elif change in {"failed", "skipped", "order_hash", "wrong_node"}:
        if change in {"failed", "skipped"}: terminal_data[change] = 1
        elif change == "order_hash": terminal_data["ordered_ids_sha256"] = "0"*64
        else:
            terminal_data["executed_ids"] = ["tests/other.py::test_other"]
            terminal_data["ordered_ids_sha256"] = module._ids_digest(terminal_data["executed_ids"])
        ref = write("terminal.json", terminal_data)
        for proof in allowlist["proofs"].values(): proof["terminal_sha256"] = ref["sha256"]
        for section in ("native_cases", "measurements", "negative_and_adjacent_tests"):
            for item in inventory[section]: item["terminal"] = ref
    elif change == "tampered":
        write("artifact.png", b"changed")
    elif change == "stale":
        allowlist["proofs"]["synthetic"]["current_source_pins"] = {"sidecar/tests/v2_split_fixtures.py": "0"*64}
    elif change in {"duplicate", "extra"}:
        other = deepcopy(row)
        if change == "extra": other["id"] = "unapproved-case"
        inventory["native_cases"].append(other)
    elif change == "aggregate":
        row["record"] = write("aggregate.json", {"status": "DIAGNOSTIC ONLY", "cases": [], "final_acceptance": False})
    elif change == "unallowlisted":
        row["terminal"] = write("unaccepted.json", terminal_data | {"accepted": True})
    elif change == "caller_acceptance":
        row["accepted"] = True
    elif change == "missing_reach":
        allowlist["proofs"]["synthetic"]["reach_sha256"] = None
    elif change == "missing_record_pin":
        allowlist["proofs"]["synthetic"]["case_records"].clear()
    elif change == "waived":
        inventory["limitations"][0]["waived"] = True
    elif change == "unknown_section":
        inventory["accepted"] = True
    elif change == "malformed_ref":
        row["terminal"] = None
    else:
        maximum = inventory["measurements"][1]
        record = json.loads(Path(maximum["record"]["path"]).read_text())
        if change == "measurement": record["memory"]["process_memory_api"] = "tracemalloc only"
        elif change == "traced_maximum": record["memory"]["python_tracemalloc_peak_bytes"] = 100
        elif change == "leaves": record["inventory"]["painted_leaves"] = 3837
        elif change == "ownership": record["frozen_input_keys"]["ownership"].pop("owned_objects")
        elif change == "read_only": record["frozen_input_keys"]["ownership"]["read_only_objects"] = 0
        elif change == "frame_keys": record["frames"].pop("12")
        elif change == "missing_svg": record["frames"]["12"].pop("svg_sha256")
        elif change == "missing_png": record["frames"]["12"].pop("png_path")
        elif change == "repeat_parity": record.pop("repeated_seek_parity_verified")
        elif change == "state_key": record["frames"]["12"].pop("state_keys_sha256")
        else: record["seek_order_ms"][0] += 1
        maximum["record"] = write("changed-maximum.json", record)
        allowlist["proofs"]["maximum"]["case_records"][maximum["id"]] = sha256(json.dumps(record, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    code, report = run()
    assert code != 0 and report["status"] == "INCOMPLETE" and report["final_acceptance"] is False
    assert report["missing_required_proofs"]


def test_report_never_overwrites_prior_output(synthetic_inventory):
    benchmark, _, _, _, run, _, _ = synthetic_inventory
    assert run()[0] == 0
    directory = Path(synthetic_inventory[2]["native_cases"][0]["record"]["path"]).parent
    original = (directory / "split-acceptance.json").read_bytes()
    with pytest.raises(FileExistsError):
        benchmark.main(["--output-dir", str(directory)])
    assert (directory / "split-acceptance.json").read_bytes() == original


def test_individual_diagnostic_record_can_fill_its_pinned_slot(synthetic_inventory):
    _, _, inventory, _, run, write, _ = synthetic_inventory
    row = inventory["native_cases"][0]
    record = json.loads(Path(row["record"]["path"]).read_text())
    row["record"] = write("truthful-partial.json", {"status": "DIAGNOSTIC ONLY", "final_acceptance": False, "cases": [record]})
    row["record"]["pointer"] = "/cases/0"
    assert run()[0] == 0


@pytest.mark.parametrize("field,final_newline", [("ordered_ids_sha256", True), ("selected_order_sha256", True),
                                               ("executed_order_sha256", False), ("fresh_order_sha256", False)])
def test_actual_receipt_order_formats_are_normalized(field, final_newline):
    module = split_benchmark()._evidence_module()
    ids = ["tests/example.py::test_first", "tests/example.py::test_second"]
    text = "\n".join(ids) + ("\n" if final_newline else "")
    terminal = {"tool_exit": 0, "test_exit": 0, "failed": 0, "skipped": 0, "passed": 2,
                "executed_ids": ids, field: sha256(text.encode()).hexdigest()}
    module._terminal(terminal, ids[1])


def test_chart_combined_native_terminal_uses_its_actual_summary_format():
    module = split_benchmark()._evidence_module()
    module._terminal({"native_tool_and_test_exit": 0, "native_summary": "14 passed, 136 deselected in 349.68s (0:05:49)"})


def test_nested_manifest_artifacts_are_rehashed(synthetic_inventory):
    _, _, inventory, allowlist, run, write, _ = synthetic_inventory
    row = inventory["native_cases"][0]
    old_manifest = row["manifest"]
    nested = write("outer-manifest.json", {"manifests": [old_manifest]})
    row["manifest"] = nested
    allowlist["proofs"]["synthetic"]["manifest_sha256"] = nested["sha256"]
    write("artifact.png", b"nested artifact changed")
    assert run()[0] != 0


def test_shared_nested_manifest_retains_its_verified_artifact_closure(synthetic_inventory):
    _, _, inventory, allowlist, run, write, _ = synthetic_inventory
    nested = write("shared-outer.json", {"manifests": [inventory["native_cases"][0]["manifest"]]})
    for section in ("native_cases", "measurements"):
        for row in inventory[section]: row["manifest"] = nested
    for proof in allowlist["proofs"].values(): proof["manifest_sha256"] = nested["sha256"]
    assert run()[0] == 0


def test_stale_callable_reach_is_not_a_current_source_binding(synthetic_inventory):
    _, _, _, allowlist, run, _, _ = synthetic_inventory
    allowlist["proofs"]["synthetic"]["current_function_pins"] = {"bench/verify_v2_split.py": {"geometry_case": "0"*64}}
    assert run()[0] != 0


def test_duplicate_inventory_json_keys_fail_closed(synthetic_inventory):
    benchmark, module, inventory, _, _, _, _ = synthetic_inventory
    directory = Path(inventory["native_cases"][0]["record"]["path"]).parent
    (directory / module.INVENTORY).write_text('{"version":1,"version":1}')
    assert benchmark.main(["--output-dir", str(directory)]) != 0
    report = json.loads((directory / "split-acceptance.json").read_text())
    assert any("duplicate JSON key" in gap for gap in report["missing_required_proofs"])


def test_local_references_resolve_from_the_explicit_inventory_directory(synthetic_inventory):
    _, _, inventory, _, run, _, _ = synthetic_inventory
    for section in ("native_cases", "measurements", "negative_and_adjacent_tests"):
        for row in inventory[section]:
            for key in ("record", "manifest", "terminal", "reach", "log"):
                if key in row: row[key]["path"] = Path(row[key]["path"]).name
    assert run()[0] == 0


def test_binary_artifacts_are_stream_hashed_without_retaining_contents(tmp_path, monkeypatch):
    module = split_benchmark()._evidence_module()
    path = tmp_path / "opaque.png"
    contents = b"synthetic opaque artifact" * 10000
    path.write_bytes(contents)
    original = Path.read_bytes

    def forbid_whole_binary_read(candidate):
        if candidate == path:
            pytest.fail("Binary artifact was read wholesale for retention")
        return original(candidate)

    monkeypatch.setattr(Path, "read_bytes", forbid_whole_binary_read)
    cache = {}
    raw, digest = module._cached_evidence(path, cache, False)
    assert raw is None and cache[path] == (None, sha256(contents).hexdigest())
    assert digest == sha256(contents).hexdigest()


def _historical_envelope(synthetic_inventory, fault=None):
    _, _, inventory, allowlist, _, write, terminal = synthetic_inventory
    row = inventory["native_cases"][0]
    record = json.loads(Path(row["record"]["path"]).read_text())
    record.pop("final_acceptance")
    envelope = {"status": "DIAGNOSTIC ONLY", "final_acceptance": False, "cases": [record]}
    pointer = "/cases/0"
    if fault == "bare":
        envelope, pointer = record, ""
    elif fault == "case_true": record["final_acceptance"] = True
    elif fault == "envelope_true": envelope["final_acceptance"] = True
    elif fault == "missing_status": envelope.pop("status")
    elif fault == "wrong_status": envelope["status"] = "READY FOR INDEPENDENT REVIEW"
    elif fault == "wrong_pointer":
        envelope["other"] = [record]
        pointer = "/other/0"
    row["record"] = write("historical-envelope.json", envelope) | {"pointer": pointer}
    proof = allowlist["proofs"]["synthetic"]
    proof["case_records"][row["id"]] = sha256(json.dumps(record, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    proof["case_nodes"] = {row["id"]: terminal["executed_ids"][0]}
    if fault == "unbound_node": proof["case_nodes"].clear()
    elif fault == "wrong_node": proof["case_nodes"][row["id"]] = "tests/not-executed.py::test_other"
    elif fault == "tampered": Path(row["record"]["path"]).write_text("{}")


def test_missing_case_acceptance_is_bound_to_original_diagnostic_envelope_and_node(synthetic_inventory):
    _historical_envelope(synthetic_inventory)
    assert synthetic_inventory[4]()[0] == 0


@pytest.mark.parametrize("fault", ["bare", "case_true", "envelope_true", "missing_status", "wrong_status",
                                  "wrong_pointer", "tampered", "unbound_node", "wrong_node"])
def test_unbound_or_non_diagnostic_missing_case_flag_is_not_admitted(synthetic_inventory, fault):
    _historical_envelope(synthetic_inventory, fault)
    assert synthetic_inventory[4]()[0] != 0


def test_authenticated_retained_copy_survives_ephemeral_source_removal(synthetic_inventory):
    _, _, inventory, allowlist, run, write, _ = synthetic_inventory
    row = inventory["native_cases"][0]
    record = json.loads(Path(row["record"]["path"]).read_text())
    frame = record["frames"]["0"]
    durable = frame["png_path"]
    frame["png_path"] = "ephemeral-source-is-gone.png"
    row["record"] = write("retained-case.json", record)
    row["manifest"] = write("durable-manifest.json", {"pairs":[{"source":frame["png_path"],"retained":durable,"sha256":frame["png_sha256"]}]})
    proof = allowlist["proofs"]["synthetic"]
    proof["manifest_sha256"] = row["manifest"]["sha256"]
    proof["case_records"][row["id"]] = sha256(json.dumps(record, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert run()[0] == 0


def test_required_schema_nodes_are_finite_and_remain_pending_without_current_evidence(synthetic_inventory):
    benchmark, _, _, allowlist, run, _, _ = synthetic_inventory
    data = json.loads((benchmark.ROOT / "bench/split_evidence_allowlist.json").read_text())
    ids = data["schema_test_ids"]
    assert len(ids) == len(set(ids)) == 14
    assert sum(node.startswith("tests/test_v2_return_schema.py::") for node in ids) == 2
    assert sum(node.startswith("tests/test_v2_split_evidence_windows.py::test_published_schema_carries_actual_split_evidence_authority_and_windows[")
               for node in ids) == 12
    allowlist["schema_test_ids"] = ids
    code, report = run()
    assert code != 0
    assert all(any(node in gap for gap in report["missing_required_proofs"]) for node in ids)


@pytest.fixture
def mixed_native_proofs(synthetic_inventory, monkeypatch):
    """Two real canonical IDs; all evidence bytes remain synthetic metadata only."""
    benchmark, module, inventory, allowlist, run, write, terminal = synthetic_inventory
    canonical = split_benchmark().required_native_cases()
    fresh, retained = sorted(key for key, family in canonical.items() if family == "geometry")[:2]
    monkeypatch.setattr(benchmark, "required_native_cases", lambda: {fresh: "geometry", retained: "geometry"})
    default = allowlist["proofs"].pop("synthetic")
    allowlist["proofs"]["geometry"] = default
    inventory["negative_and_adjacent_tests"][0]["proof"] = "geometry"
    fresh_row = inventory["native_cases"][0]
    record = json.loads(Path(fresh_row["record"]["path"]).read_text())
    record["case_id"] = fresh
    fresh_row.update(id=fresh, proof="geometry", record=write("fresh-case.json", record))
    default["case_records"] = {fresh: sha256(json.dumps(record, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}

    record = deepcopy(record)
    record["case_id"] = retained
    record.pop("final_acceptance")
    image = write("retained.png", b"SYNTHETIC RETAINED METADATA ONLY")
    record["frames"]["0"].update(png_path=image["path"], png_sha256=image["sha256"])
    owner = "tests/synthetic_metadata_only.py::test_retained_owner"
    retained_terminal = write("retained-terminal.json", terminal | {"executed_ids": [owner],
                                                                 "ordered_ids_sha256": module._ids_digest([owner])})
    row = {"id": retained, "proof": "geometry", "terminal": retained_terminal,
           "log": write("retained.log", b"SYNTHETIC RETAINED METADATA ONLY: 1 passed"),
           "reach": write("retained-reach.json", {"scope": "SYNTHETIC RETAINED METADATA ONLY"}),
           "manifest": write("retained-manifest.json", {"items": [image]}),
           "record": write("retained-envelope.json", {"status": "DIAGNOSTIC ONLY", "final_acceptance": False,
                                                      "cases": [record]}) | {"pointer": "/cases/0"}}
    variant = deepcopy(default)
    variant.update({key + "_sha256": row[key]["sha256"] for key in ("terminal", "log", "reach", "manifest")})
    variant.update(accepted_source_commit="synthetic-retained-metadata-only",
                   test_ids=[owner], case_nodes={retained: owner},
                   case_records={retained: sha256(json.dumps(record, sort_keys=True, separators=(",", ":")).encode()).hexdigest()})
    default["case_proofs"] = {retained: variant}
    inventory["native_cases"].append(row)
    return inventory, allowlist, run, row, variant, write


def test_mixed_native_terminals_use_exact_case_proof_and_keep_negative_default(mixed_native_proofs):
    inventory, allowlist, run, row, _, _ = mixed_native_proofs
    code, report = run()
    assert code == 0 and report["final_acceptance"] is False
    native = {item["id"]: item for item in report["native_cases"]}
    assert len(native) == 2 and {item["proof"] for item in native.values()} == {"geometry"}
    assert native[row["id"]]["terminal_sha256"] == row["terminal"]["sha256"]
    fresh = inventory["native_cases"][0]
    default_sha = allowlist["proofs"]["geometry"]["terminal_sha256"]
    assert native[fresh["id"]]["terminal_sha256"] == default_sha
    assert report["negative_and_adjacent_tests"][0]["terminal_sha256"] == default_sha


@pytest.mark.parametrize("field", ["terminal_sha256", "log_sha256", "reach_sha256", "manifest_sha256",
                                   "current_source_pins", "accepted_source_commit", "case_records", "case_nodes"])
def test_native_case_proof_never_inherits_missing_default_fields(mixed_native_proofs, field):
    _, _, run, _, variant, _ = mixed_native_proofs
    variant.pop(field)
    code, report = run()
    assert code != 0 and any("never inherited" in gap for gap in report["missing_required_proofs"])


@pytest.mark.parametrize("fault", ["unknown", "wrong_family", "not_mapping", "nested", "maximum", "cold-count",
                                  "retained50", "negative-only", "schema-only", "limitations"])
def test_case_proofs_are_confined_to_exact_native_family_slots(mixed_native_proofs, synthetic_inventory, monkeypatch, fault):
    _, allowlist, run, row, variant, _ = mixed_native_proofs
    default = allowlist["proofs"]["geometry"]
    if fault in {"unknown", "wrong_family"}:
        key = "unknown-native"
        if fault == "wrong_family":
            key = next(key for key, group in split_benchmark().required_native_cases().items() if group == "text")
            benchmark = synthetic_inventory[0]
            required = benchmark.required_native_cases() | {key: "text"}
            monkeypatch.setattr(benchmark, "required_native_cases", lambda: required)
        default["case_proofs"][key] = deepcopy(variant)
    elif fault == "not_mapping": default["case_proofs"] = []
    elif fault == "nested": variant["case_proofs"] = {}
    else:
        other = deepcopy(variant)
        other["case_proofs"] = {row["id"]: deepcopy(variant)}
        allowlist["proofs"][fault] = other
    code, report = run()
    assert code != 0 and any("proofs/" in gap for gap in report["missing_required_proofs"])


@pytest.mark.parametrize("fault", ["terminal", "log", "reach", "manifest", "source", "function_reach",
                                  "missing_node", "unexecuted_node", "wrong_node", "missing_digest", "wrong_digest",
                                  "artifact", "row_selector", "row_variants", "row_acceptance", "row_final_acceptance",
                                  "envelope_bare", "envelope_true", "envelope_status", "envelope_pointer"])
def test_selected_native_case_proof_reuses_all_existing_authentication_checks(mixed_native_proofs, fault):
    _, allowlist, run, row, variant, write = mixed_native_proofs
    default = allowlist["proofs"]["geometry"]
    if fault in {"terminal", "log", "reach", "manifest"}:
        variant[fault + "_sha256"] = default[fault + "_sha256"]
    elif fault == "source": variant["current_source_pins"] = {"sidecar/tests/v2_split_fixtures.py": "0"*64}
    elif fault == "function_reach": variant["current_function_pins"] = {"bench/verify_v2_split.py": {"geometry_case": "0"*64}}
    elif fault == "missing_node": variant["case_nodes"] = {"another-case": "tests/other.py::test_other"}
    elif fault == "unexecuted_node": variant["case_nodes"][row["id"]] = "tests/other.py::test_other"
    elif fault == "wrong_node": variant["case_nodes"][row["id"]] = default["test_ids"][0]
    elif fault == "missing_digest": variant["case_records"] = {"another-case": "0"*64}
    elif fault == "wrong_digest": variant["case_records"][row["id"]] = "0"*64
    elif fault == "artifact": write("retained.png", b"tampered retained metadata")
    elif fault.startswith("row_"):
        key = {"row_selector": "case_proof", "row_variants": "case_proofs", "row_acceptance": "accepted",
               "row_final_acceptance": "final_acceptance"}[fault]
        row[key] = True
    else:
        envelope = json.loads(Path(row["record"]["path"]).read_text())
        record = envelope["cases"][0]
        pointer = "/cases/0"
        if fault == "envelope_bare": envelope, pointer = record, ""
        elif fault == "envelope_true": record["final_acceptance"] = True
        elif fault == "envelope_status": envelope.pop("status")
        else:
            envelope["other"] = [record]
            pointer = "/other/0"
        row["record"] = write("changed-retained-envelope.json", envelope) | {"pointer": pointer}
        variant["case_records"][row["id"]] = sha256(json.dumps(record, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    code, report = run()
    assert code != 0 and report["final_acceptance"] is False
    assert any(row["id"] in gap for gap in report["missing_required_proofs"])
    assert report["negative_and_adjacent_tests"][0]["terminal_sha256"] == default["terminal_sha256"]


def test_duplicate_case_proof_json_keys_are_rejected_by_existing_decoder(synthetic_inventory):
    _, module, _, _, _, _, _ = synthetic_inventory
    with pytest.raises(ValueError, match="duplicate JSON key"):
        module._json(b'{"proofs":{"geometry":{"case_proofs":{"same":{},"same":{}}}}}')
