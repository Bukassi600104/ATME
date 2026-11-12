"""Local Task10 receipt reconciliation; eligibility is pinned by reviewed source data."""

import ast
import json
import math
import re
from hashlib import file_digest, sha256
from pathlib import Path

INVENTORY = "split-evidence-inventory.json"
LIMITATIONS = {
    "P3-46": "P3-46 remains open and uncredited.",
    "windows-protection-skips-5": "Five historical Windows protection skips remain unproven and uncredited.",
    "private-diagnostic-contexts-64": "64 incomplete private diagnostic contexts remain uncredited.",
}
SECTIONS = ("native_cases", "measurements", "negative_and_adjacent_tests", "limitations")


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _json(raw):
    def invalid(value):
        raise ValueError(f"nonfinite JSON value: {value}")
    return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique, parse_constant=invalid)


def load_allowlist(path):
    return _json(Path(path).read_bytes())


def _cached_evidence(path, cache, parse_json):
    if path not in cache:
        if parse_json or path.suffix.lower() == ".json":
            raw = path.read_bytes()
            cache[path] = (raw, sha256(raw).hexdigest())
        else:
            with path.open("rb") as stream:
                cache[path] = (None, file_digest(stream, "sha256").hexdigest())
    raw, actual = cache[path]
    if parse_json and raw is None:
        raw = path.read_bytes()
        if sha256(raw).hexdigest() != actual:
            raise ValueError(f"evidence changed before JSON parsing: {path}")
        cache[path] = (raw, actual)
    return raw, actual


def _ids_digest(ids):
    return sha256(("\n".join(ids) + "\n").encode()).hexdigest()


def _terminal(data, required_id=None):
    if not isinstance(data, dict):
        raise TypeError("terminal must be a receipt object")
    nested = data.get("observed_terminal_tool_metadata", {})
    tool = [data[k] for k in ("tool_exit", "tool_exit_code", "terminal_tool_exit", "native_tool_and_test_exit") if k in data]
    test = [data[k] for k in ("test_exit", "test_exit_code", "pytest_exit_code", "printed_test_exit",
                             "printed_test_exit_code", "native_tool_and_test_exit") if k in data]
    tool += [nested[k] for k in ("tool_exit_code",) if k in nested]
    test += [nested[k] for k in ("printed_test_exit",) if k in nested]
    if not tool or not test or any(type(value) is not int or value != 0 for value in tool + test):
        raise ValueError("terminal requires actual tool/test exit0")
    summary = data.get("native_summary", "")
    for key in ("failed", "skipped"):
        if key in data:
            if type(data[key]) is not int or data[key] != 0:
                raise ValueError(f"terminal has {key} evidence")
        elif not re.fullmatch(r"\s*\d+ passed(?:, \d+ deselected)? in .+", summary):
            raise ValueError(f"terminal lacks explicit zero {key}")
    if "passed" in data and (type(data["passed"]) is not int or data["passed"] <= 0):
        raise ValueError("terminal contains no passed tests")
    keys = ("expected_executed_ids", "executed_ids", "selected_ids")
    ids = next((data[key] for key in keys if key in data), None)
    if ids is not None:
        if not isinstance(ids, list) or any(not isinstance(item, str) for item in ids) or len(ids) != len(set(ids)):
            raise ValueError("terminal ID inventory is not unique")
        hashes = {key: data[key] for key in ("ordered_ids_sha256", "ordered_id_sha256", "executed_order_sha256",
                                            "selected_order_sha256", "fresh_order_sha256") if key in data}
        # These are the two existing receipt formats, not interchangeable caller-selected encodings.
        expected = {key: sha256(("\n".join(ids) + ("" if key in {"executed_order_sha256", "fresh_order_sha256"} else "\n")).encode()).hexdigest()
                    for key in hashes}
        if not hashes or any(not isinstance(value, str) or value.lower() != expected[key] for key, value in hashes.items()):
            raise ValueError("terminal executed-ID order hash mismatch")
        if type(data.get("passed")) is not int or data["passed"] != len(ids):
            raise ValueError("terminal passed count differs from executed IDs")
    if required_id is not None and (ids is None or required_id not in ids):
        raise ValueError("node was not executed by this terminal")


def _source(root, proof):
    pins = proof.get("current_source_pins")
    if not pins:
        raise ValueError("missing eligible current-source/E8 reach binding")
    for name, expected in pins.items():
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            raise ValueError(f"current-source path unavailable: {name}")
        if sha256(path.read_bytes()).hexdigest() != expected.lower():
            raise ValueError(f"stale current-source pin: {name}")
    for name, functions in proof.get("current_function_pins", {}).items():
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("current-source function escaped root")
        actual = {node.name: sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()
                  for node in ast.parse(path.read_text(encoding="utf-8-sig")).body
                  if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        if any(actual.get(key) != value for key, value in functions.items()):
            raise ValueError(f"stale current-source function reach: {name}")


def _measurement(record, slot):
    if slot.startswith("performance-maximum-"):
        expected_profile = "SHORT_FORM_9_16" if slot.endswith("portrait") else "LONG_FORM_16_9"
        inventory = record.get("inventory", {})
        if not isinstance(inventory, dict):
            raise TypeError("maximum inventory must be an object")
        if (record.get("profile") != expected_profile
                or any(type(inventory.get(key)) is not int or inventory[key] != value
                       for key, value in (("results", 256), ("bound_objects", 4096), ("painted_leaves", 3838)))
                or record.get("family") != "performance"
                or record.get("kind") != "maximum" or record.get("mode") != "reveal"):
            raise ValueError("maximum requires actual256-result/4096-bound profile")
        order = record.get("seek_order_ms")
        if order != [40, 0, 12, 39, 24, 32, 12, 0, 40] or any(type(value) is not int for value in order):
            raise ValueError("maximum requires the same nine integer seeks")
        frozen = record.get("frozen_input_keys", {})
        ownership = frozen.get("ownership", {}) if isinstance(frozen, dict) else {}
        if not isinstance(ownership, dict) or any(type(ownership.get(key)) is not int or ownership[key] != value
                for key, value in (("owned_objects", 4095), ("read_objects", 1), ("read_only_objects", 1), ("owned_roots", 257))):
            raise ValueError("maximum lacks the existing4095-owned/one-read-only ownership proof")
        frames = record.get("frames")
        if not isinstance(frames, dict) or set(frames) != {"40", "0", "12", "39", "24", "32"}:
            raise ValueError("maximum requires the exact six unique clock frames")
        for frame in frames.values():
            if not isinstance(frame, dict) or any(not isinstance(frame.get(key), str) or not re.fullmatch(r"[0-9a-fA-F]{64}", frame[key])
                    for key in ("png_sha256", "svg_sha256", "state_keys_sha256")) or any(not isinstance(frame.get(key), str)
                    for key in ("png_path", "svg_path")):
                raise ValueError("maximum frame lacks authenticated PNG/SVG/state hashes")
        if record.get("repeated_seek_parity_verified") is not True:
            raise ValueError("maximum repeated-seek equality assertion is not proven")
        for key, count in (("sample_compose_raster_ms", 9), ("warm_seek_ms", 8),
                           ("chronology_construction_ms", None), ("cold_first_seek_ms", None)):
            value = record.get(key)
            values = value if count else [value]
            if (not isinstance(values, list) or (count and len(values) != count) or any(type(value) not in (int, float)
                    or not math.isfinite(value) or value < 0 for value in values)):
                raise ValueError(f"missing actual measurement: {key}")
        samples = record["sample_compose_raster_ms"]
        if record["cold_first_seek_ms"] != samples[0] or record["warm_seek_ms"] != samples[1:]:
            raise ValueError("cold/warm measurements differ from the actual nine seeks")
        memory = record.get("memory", {})
        if not isinstance(memory, dict):
            raise TypeError("maximum memory must be an object")
        if (memory.get("process_memory_api") != "Windows GetProcessMemoryInfo; whole process, includes native allocations"
                or any(type(memory.get(key)) is not int or memory[key] <= 0
                       for key in ("process_working_set_bytes", "process_peak_working_set_bytes"))
                or memory["process_peak_working_set_bytes"] < memory["process_working_set_bytes"]
                or record.get("immutable_input_keys_unchanged") is not True or record.get("network_forbidden") is not True
                or not isinstance(record.get("frozen_input_keys"), dict) or not record["frozen_input_keys"]
                or not isinstance(record.get("cold_scope"), str) or not record["cold_scope"]
                or not isinstance(record.get("timing_scope"), str) or not record["timing_scope"]):
            raise ValueError("maximum lacks native-inclusive memory/immutable-key proof")
        if any(key.startswith("python_tracemalloc") for key in memory) or "tracemalloc enabled" in record["timing_scope"]:
            raise ValueError("old traced maximum is supporting only; current untraced proof required")
    elif slot.startswith("cold-count-"):
        for key in ("network_forbidden", "original_bundle_and_paths_forbidden", "caches_cleared_before_validation",
                    "immutable_input_keys_unchanged"):
            if record.get(key) is not True:
                raise ValueError(f"cold Count lacks {key}")
    elif slot == "retained-50-annotation-group":
        if record.get("frame_count") != 50 or record.get("original_baselines_unchanged") is not True:
            raise ValueError("retained50 evidence is incomplete")


def _native_case_proofs(proofs, native_requirements):
    variants, errors = {}, {}
    families = set(native_requirements.values())
    for group, default in proofs.items():
        if "case_proofs" not in default:
            continue
        try:
            cases = default["case_proofs"]
            if group not in families or not isinstance(cases, dict):
                raise ValueError("case_proofs requires a canonical native family")
            for slot, proof in cases.items():
                if native_requirements.get(slot) != group:
                    raise ValueError("unknown/extra/wrong-family case_proofs key")
                required = ("terminal_sha256", "log_sha256", "reach_sha256", "manifest_sha256",
                            "current_source_pins", "accepted_source_commit", "case_records", "case_nodes")
                if (not isinstance(proof, dict) or "case_proofs" in proof
                        or any(not proof.get(key) for key in required)):
                    raise ValueError("case proof must be complete; defaults are never inherited")
            variants[group] = cases
        except (ValueError, TypeError) as exc:
            errors[group] = str(exc)
    return variants, errors


def reconcile(output_dir, root, native_requirements, allowlist_path):
    """No rendering, test execution, accepted-flag inference or source rewriting."""
    output_dir, root = Path(output_dir), Path(root)
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / "split-acceptance.json"
    if destination.exists():
        raise FileExistsError(destination)
    allowlist = load_allowlist(allowlist_path)
    proofs = allowlist["proofs"]
    tests = {}
    for group, proof in proofs.items():
        for node in proof.get("test_ids", []):
            tests.setdefault(node, []).append(group)
    for node in allowlist["extra_test_ids"] + allowlist["schema_test_ids"] + allowlist["contract_test_ids"]:
        tests.setdefault(node, [])
    requirements = {"native_cases": native_requirements, "measurements": {
        "performance-maximum-reveal-landscape": "maximum", "performance-maximum-reveal-portrait": "maximum",
        "cold-count-landscape": "cold-count", "cold-count-portrait": "cold-count",
        "retained-50-annotation-group": "retained50"},
        "negative_and_adjacent_tests": tests, "limitations": LIMITATIONS}
    report = {"scope": "machine evidence reconciliation; independent review/public/installed/creative acceptance outstanding",
              "evidence_scope": allowlist["scope"], "status": "INCOMPLETE", "final_acceptance": False,
              **{key: [] for key in SECTIONS}, "missing_required_proofs": []}
    gaps = report["missing_required_proofs"]
    case_proofs, invalid_case_proofs = _native_case_proofs(proofs, native_requirements)
    gaps.extend(f"proofs/{group}: {error}" for group, error in invalid_case_proofs.items())
    reads = {}

    def read(ref, base, *, decode=True):
        if not isinstance(ref, dict) or set(ref) - {"path", "sha256", "pointer", "artifact_root"}:
            raise ValueError("invalid local evidence reference")
        name, expected = ref.get("path"), ref.get("sha256")
        if not isinstance(name, str) or "://" in name or not isinstance(expected, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
            raise ValueError("evidence requires a local path and SHA256")
        path = (base / name).resolve()
        raw, actual = _cached_evidence(path, reads, decode)
        if actual != expected.lower():
            raise ValueError(f"hash mismatch: {path}")
        data = _json(raw) if decode else raw
        pointer = ref.get("pointer", "")
        if not isinstance(pointer, str) or (pointer and not pointer.startswith("/")) or re.search(r"~(?![01])", pointer):
            raise ValueError("invalid evidence JSON pointer")
        for component in pointer.split("/")[1:]:
            component = component.replace("~1", "/").replace("~0", "~")
            if isinstance(data, list) and (not component.isdecimal() or str(int(component)) != component):
                raise ValueError("invalid evidence array pointer")
            data = data[int(component)] if isinstance(data, list) else data[component]
        return data, path

    artifact_json_pins = {}

    def artifacts(data, base, authenticated=None):
        pins = set()
        if isinstance(data, list):
            for child in data:
                pins |= artifacts(child, base, authenticated)
        elif isinstance(data, dict):
            pairs = []
            if "sha256" in data:
                durable = [key for key in ("copy", "retained", "path", "file") if key in data]
                pairs.extend((data[key], data["sha256"]) for key in (durable or ["source"]) if key in data)
            for key, value in data.items():
                if key.endswith("_path") and key[:-5] + "_sha256" in data:
                    pairs.append((value, data[key[:-5] + "_sha256"]))
            for name, pin in pairs:
                if authenticated is not None:
                    candidates = [path for path, expected in authenticated if expected == pin.lower()]
                    if not candidates:
                        raise ValueError("case artifact is absent from the authenticated durable manifest")
                    name = str(min(candidates))
                raw, path = read({"path": name, "sha256": pin}, base, decode=False)
                pins.add((path, pin.lower()))
                if path.suffix.lower() == ".json":
                    child = _json(raw)
                    is_record = isinstance(child, dict) and ("case_id" in child or "status" in child and "cases" in child)
                    if authenticated is not None or not is_record:
                        key = path, authenticated is not None
                        if key not in artifact_json_pins:
                            artifact_json_pins[key] = set()
                            artifact_json_pins[key] = artifacts(child, path.parent, authenticated)
                        pins |= artifact_json_pins[key]
            for child in data.values():
                if isinstance(child, (dict, list)):
                    pins |= artifacts(child, base, authenticated)
        return pins

    try:
        inventory = _json((output_dir / INVENTORY).read_bytes())
        if set(inventory) != {"version", *SECTIONS} or inventory["version"] != 1 or type(inventory["version"]) is not int:
            raise ValueError("inventory requires version1 and exactly four proof sections")
    except (OSError, ValueError, TypeError) as exc:
        inventory = {key: [] for key in SECTIONS}
        gaps.append(f"inventory: {exc}")

    for section, required in requirements.items():
        rows = inventory.get(section)
        if not isinstance(rows, list):
            gaps.append(f"{section}: expected a list")
            rows = []
        ids = [row.get("id") if isinstance(row, dict) else None for row in rows]
        for slot in sorted(set(required) - {key for key in ids if isinstance(key, str)}):
            gaps.append(f"{section}/{slot}: missing")
        seen = set()
        for row, slot in zip(rows, ids, strict=True):
            label = f"{section}/{slot}"
            if not isinstance(slot, str) or slot not in required or slot in seen:
                gaps.append(label + ": unknown/duplicate/extra ID")
                continue
            seen.add(slot)
            try:
                if section == "limitations":
                    if row != {"id": slot, "uncredited": True, "waived": False}:
                        raise ValueError("limitation must remain explicit, uncredited and unwaived")
                    report[section].append({**row, "description": LIMITATIONS[slot]})
                    continue
                allowed = required[slot] if section == "negative_and_adjacent_tests" else [required[slot]]
                if set(row) - {"id", "proof", "terminal", "log", "reach", "record", "manifest"}:
                    raise ValueError("unknown proof fields; caller acceptance flags are not evidence")
                for key in ("terminal", "reach") + (() if section == "negative_and_adjacent_tests" else ("record", "manifest")):
                    if not isinstance(row.get(key), dict):
                        raise TypeError(f"missing local reference: {key}")
                    if key != "record" and row[key].get("pointer"):
                        raise ValueError("receipt and manifest references must bind the complete pinned document")
                group = row.get("proof")
                if group not in allowed or group not in proofs:
                    raise ValueError("missing eligible slot-to-terminal binding")
                if section == "native_cases" and group in invalid_case_proofs:
                    raise ValueError("invalid native case_proofs contract")
                proof = proofs[group]
                if section == "native_cases":
                    proof = case_proofs.get(group, {}).get(slot, proof)
                if not proof.get("terminal_sha256") or row.get("terminal", {}).get("sha256", "").lower() != proof["terminal_sha256"]:
                    raise ValueError("terminal is not allowlisted for this slot")
                terminal, _ = read(row["terminal"], output_dir)
                _terminal(terminal, slot if section == "negative_and_adjacent_tests" else None)
                if proof.get("log_sha256"):
                    if row.get("log", {}).get("sha256", "").lower() != proof["log_sha256"]:
                        raise ValueError("missing pinned terminal log")
                    read(row["log"], output_dir, decode=False)
                if not proof.get("reach_sha256") or row.get("reach", {}).get("sha256", "").lower() != proof["reach_sha256"]:
                    raise ValueError("missing eligible current-source/E8 reach receipt")
                read(row["reach"], output_dir)
                _source(root, proof)
                result = {"id": slot, "proof": group, "terminal_sha256": proof["terminal_sha256"],
                          "accepted_source_commit": proof["accepted_source_commit"]}
                if section != "negative_and_adjacent_tests":
                    if not proof.get("manifest_sha256") or row.get("manifest", {}).get("sha256", "").lower() != proof["manifest_sha256"]:
                        raise ValueError("missing allowlisted native artifact manifest")
                    manifest, manifest_path = read(row["manifest"], output_dir)
                    artifact_root = (manifest_path.parent / row["manifest"].get("artifact_root", "")).resolve()
                    manifest_pins = artifacts(manifest, artifact_root)
                    record, record_path = read(row["record"], output_dir)
                    if not isinstance(record, dict) or record.get("case_id") != slot or "cases" in record:
                        raise ValueError("individual diagnostic case required; partial aggregate cannot substitute")
                    if record.get("final_acceptance") is not False:
                        if "final_acceptance" in record:
                            raise ValueError("case acceptance must not be true/null/noncanonical")
                        pointer = row["record"].get("pointer", "")
                        envelope, _ = read({key: value for key, value in row["record"].items() if key != "pointer"}, output_dir)
                        if (not re.fullmatch(r"/cases/(0|[1-9][0-9]*)", pointer) or not isinstance(envelope, dict)
                                or envelope.get("status") != "DIAGNOSTIC ONLY" or envelope.get("final_acceptance") is not False
                                or not isinstance(envelope.get("cases"), list)):
                            raise ValueError("missing case flag requires the complete pinned diagnostic envelope")
                        case_ids = [item.get("case_id") if isinstance(item, dict) else None for item in envelope["cases"]]
                        if (any(not isinstance(key, str) for key in case_ids) or len(case_ids) != len(set(case_ids))
                                or envelope["cases"][int(pointer.rsplit("/", 1)[1])] != record):
                            raise ValueError("diagnostic envelope pointer is not an exact unique case")
                        node = proof.get("case_nodes", {}).get(slot)
                        if not isinstance(node, str):
                            raise ValueError("missing accepted case-to-executed-node binding")
                        _terminal(terminal, node)
                    record_digest = sha256(json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
                    if proof.get("case_records", {}).get(slot) != record_digest:
                        raise ValueError("missing allowlisted individual case-record binding")
                    record_pins = artifacts(record, record_path.parent, manifest_pins)
                    if not record_pins or not record_pins <= manifest_pins:
                        raise ValueError("case artifacts are absent from authenticated manifest")
                    if section == "measurements":
                        _measurement(record, slot)
                    elif any(record.get(key) is not True for key in ("network_forbidden", "immutable_input_keys_unchanged")):
                        raise ValueError("native case lacks offline/immutable-key proof")
                    result.update(record=record, manifest_sha256=proof["manifest_sha256"],
                                  record_sha256=row["record"]["sha256"], artifact_count=len(record_pins))
                report[section].append(result)
            except (OSError, ValueError, KeyError, TypeError, IndexError, SyntaxError) as exc:
                gaps.append(label + ": " + str(exc))
    maximum = [row["record"] for row in report["measurements"] if row["id"].startswith("performance-maximum-")]
    if len(maximum) == 2 and maximum[0]["seek_order_ms"] != maximum[1]["seek_order_ms"]:
        gaps.append("measurements/maximum: profiles do not use the same nine seeks")
    if not gaps:
        report["status"] = "READY FOR INDEPENDENT REVIEW"
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(f"{report['status']}: {len(gaps)} missing proofs; {destination}")
    return 1 if gaps else 0
