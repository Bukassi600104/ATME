"""Persist original native owning-test results; default CLI only plans collection."""

import argparse
import ast
import importlib.util
import inspect
import json
import os
import re
import subprocess
import sys
from functools import wraps
from hashlib import file_digest, sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASE_FUNCTIONS = ("geometry_case", "text_case", "code_case", "callout_case", "chart_case", "media_case",
                  "visual_case", "visual_state_case", "aperture_case", "registry_case", "container_case",
                  "evidence_case", "connector_case", "history_case")


def benchmark():
    spec = importlib.util.spec_from_file_location("split_record_benchmark", ROOT / "bench/verify_v2_split.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(path):
    with Path(path).open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def _json_bytes(value):
    return (json.dumps(value, indent=2, allow_nan=False) + "\n").encode()


def _write(path, value):
    raw = _json_bytes(value)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {"path": str(path.resolve()), "sha256": sha256(raw).hexdigest()}


def _unique_ids(ids, required, label):
    if not isinstance(ids, list) or any(not isinstance(key, str) for key in ids):
        raise ValueError(f"{label}: expected explicit case IDs")
    if len(ids) != len(set(ids)) or set(ids) - set(required):
        raise ValueError(f"{label}: duplicate/unknown case IDs")
    return set(ids)


def select_cases(required, preserved, eligible, requested=None):
    preserved = _unique_ids(preserved, required, "preserved")
    eligible = _unique_ids(eligible, required, "eligible")
    if not eligible <= preserved:
        raise ValueError("eligible case lacks a preserved record")
    missing = set(required) - eligible
    if requested is not None and _unique_ids(requested, required, "requested") != missing:
        raise ValueError("requested cases omit/add canonical missing slots")
    return {"required_ids": sorted(required), "preserved_ids": sorted(preserved),
            "eligible_ids": sorted(eligible), "selected_ids": sorted(missing)}


def reviewed_selection(path, expected, required):
    path = Path(path)
    if _sha(path) != expected.lower():
        raise ValueError("reviewed eligibility receipt hash mismatch")
    review = json.loads(path.read_text(encoding="utf-8-sig"))
    closure_ref = review["recovered_closure"]
    closure_path = path.parent / closure_ref["path"]
    if _sha(closure_path) != closure_ref["sha256"].lower():
        raise ValueError("recovered record manifest hash mismatch")
    closure = json.loads(closure_path.read_text(encoding="utf-8-sig"))
    recovered = [row["case_id"] for row in closure["records"]]
    disposition = review["conditional_disposition"]
    eligible = disposition.get("eligible_case_ids")
    if eligible is None:
        if disposition["eligible_slots"] != len(recovered):
            raise ValueError("review must name the exact eligible subset")
        eligible = recovered
    project = [key for key, group in required.items() if group == "project"]
    plan = select_cases(required, recovered + project, eligible + project)
    plan["eligibility"] = {"path": str(path.resolve()), "sha256": expected.lower(),
                           "reviewed_head": review["reviewed_head"], "conditions": disposition["conditions"]}
    return plan


def case_id_for_item(item):
    name, p = item.originalname, getattr(getattr(item, "callspec", None), "params", {})
    if "portrait" not in p:
        return None
    profile = "portrait" if p["portrait"] else "landscape"
    names = {
        "test_split_geometry_offline_pixels_and_shuffled_seek": "geometry",
        "test_split_text_list_offline_literal_pixels_and_seek": "text-list",
        "test_split_chart_offline_authored_primitive_pixels_and_seek": "chart",
        "test_split_media_offline_verified_assets_literal_vfr_pixels_and_seek": "media",
        "test_split_visual_offline_real_owner_pixels_and_seek": "visual",
        "test_split_container_offline_literal_pixels_closures_and_seek": "container",
        "test_split_evidence_offline_attested_pixels_history_and_seek": "evidence",
    }
    if name in names:
        return f"{names[name]}-{p['kind']}-{p['mode']}-{profile}"
    if name == "test_split_code_offline_literal_glyph_pixels_and_seek":
        return f"code-{'tokens' if p['tokens'] else 'plain'}-{p['mode']}-{profile}"
    if name == "test_split_callout_offline_prefix_clock_pixels_and_readonly_leaders":
        return f"callout-{'boxed' if p['boxed'] else 'unboxed'}-{p['mode']}-{profile}"
    if name == "test_split_visual_state_offline_native_roles_pixels_and_seek":
        return f"visual-state-{p['family']}-{str(p['state']).lower()}-{p['owner']}-{p['kind']}-{p['mode']}-{profile}"
    if name == "test_split_aperture_offline_native_pixels_and_read_ancestry":
        return f"aperture-{p['family']}-{p['kind']}-reveal-{profile}"
    if name == "test_split_registry_offline_authenticated_native_roles_and_seek":
        return f"registry-{p['owner']}-{p['mode']}-{profile}"
    if name == "test_split_connector_offline_literal_routes_heads_pixels_and_seek":
        return f"connector-{p['routing']}-{p['kind']}-{p['mode']}-{profile}"
    if name == "test_split_history_offline_native_parents_prior_actions_and_return":
        return f"history-{'reversed' if p['reverse_objects'] else 'authored'}-{p['kind']}-authored-{profile}"
    if name == "test_video_only_stored_history_native_duplicate":
        return f"project-flow-{p['kind']}-video-only-{profile}"
    return None


def artifact_references(record):
    frames = record.get("frames")
    if not isinstance(frames, dict) or not frames:
        raise ValueError("native record has no frame closure")
    refs = []
    for frame in frames.values():
        for kind in ("png", "svg"):
            refs.append((frame.get(kind + "_path"), frame.get(kind + "_sha256")))
    refs.append((record.get("contact_sheet_path"), record.get("contact_sheet_sha256")))
    if any(not isinstance(path, str) or not isinstance(pin, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", pin)
           for path, pin in refs):
        raise ValueError("incomplete native PNG/SVG/contact artifact references")
    return list(dict.fromkeys(refs))


def _copy_artifact(source, destination, expected):
    digest = sha256()
    with Path(source).open("rb") as incoming, destination.open("xb") as outgoing:
        for block in iter(lambda: incoming.read(1024 * 1024), b""):
            digest.update(block)
            outgoing.write(block)
        outgoing.flush()
        os.fsync(outgoing.fileno())
    if digest.hexdigest() != expected.lower():
        raise ValueError(f"native artifact hash mismatch: {source}")
    return {"source": str(Path(source).resolve()), "copy": str(destination.resolve()), "sha256": expected.lower()}


class Collector:
    def __init__(self, output_dir, plan):
        self.output = Path(output_dir)
        self.output.mkdir(parents=True, exist_ok=False)
        self.plan, self.nodes, self.pending, self.records, self.outcomes = plan, {}, {}, {}, {}

    def bind(self, bindings):
        if set(bindings) != set(self.plan["selected_ids"]) or len(set(bindings.values())) != len(bindings):
            raise ValueError("owner node bindings omit/duplicate/add selected slots")
        self.nodes = {node: case for case, node in bindings.items()}
        _write(self.output / "plan.json", self.plan | {"node_bindings": bindings, "final_acceptance": False})

    def returned(self, nodeid, record):
        case = self.nodes.get(nodeid)
        if case is None or record.get("case_id") != case or nodeid in self.pending or case in self.records:
            raise ValueError("duplicate/unknown/wrong native record")
        self.pending[nodeid] = (record, _json_bytes(record))

    def owner_finished(self, nodeid, outcome, provenance):
        if nodeid not in self.nodes or nodeid in self.outcomes:
            raise ValueError("duplicate/unknown owning test outcome")
        self.outcomes[nodeid] = outcome
        if outcome != "passed":
            self.pending.pop(nodeid, None)
            return
        record, snapshot = self.pending.pop(nodeid)
        if _json_bytes(record) != snapshot:
            raise ValueError("owning test changed the returned native record")
        case = self.nodes[nodeid]
        directory = self.output / case
        directory.mkdir(exist_ok=False)
        pairs = [_copy_artifact(path, directory / f"{index:04d}{Path(path).suffix}", pin)
                 for index, (path, pin) in enumerate(artifact_references(record))]
        envelope = _write(directory / "record.json", {"status": "DIAGNOSTIC ONLY", "final_acceptance": False,
                                                     "cases": [json.loads(snapshot)]})
        manifest = _write(directory / "manifest.json", {"case_id": case, "artifacts": pairs,
                                                         "record": envelope, "final_acceptance": False})
        receipt = _write(directory / "receipt.json", {"case_id": case, "nodeid": nodeid, "owner_outcome": outcome,
            "source_provenance": provenance, "record": envelope | {"pointer": "/cases/0"}, "manifest": manifest,
            "status": "DIAGNOSTIC ONLY", "final_acceptance": False})
        self.records[case] = receipt

    def finish(self, exit_code, *, planning=False):
        missing = sorted(set(self.plan["selected_ids"]) - set(self.records))
        complete = not planning and exit_code == 0 and not missing
        result = {"status": "COLLECTED FOR INDEPENDENT REVIEW" if complete else "INCOMPLETE", "final_acceptance": False,
                  "planning_only": planning, "pytest_exit_code": int(exit_code), "records": self.records,
                  "missing_case_ids": missing, "owning_outcomes": self.outcomes,
                  "eligibility": self.plan.get("eligibility"), "scope": "native owning-test collection, not Task10 acceptance"}
        _write(self.output / "native-records-run.json", result)
        return 0 if complete or planning and exit_code == 0 else 1


def source_provenance(item):
    paths = {Path(__file__).resolve(), ROOT / "bench/verify_v2_split.py", Path(item.path).resolve()}
    for name, module in tuple(sys.modules.items()):
        origin = getattr(module, "__file__", None)
        if origin is None:
            continue
        path = Path(origin).resolve()
        if (name == "atme" or name.startswith(("atme.", "test_v2_")) or name in {"v2_fixtures", "v2_split_fixtures"}) and not path.is_relative_to(ROOT):
            raise ValueError(f"foreign native source origin: {name}")
        if path.is_relative_to(ROOT) and path.is_file():
            paths.add(path)
    return {"git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "owner_function": item.originalname,
            "owner_function_ast_sha256": sha256(ast.dump(ast.parse(inspect.getsource(item.obj)), include_attributes=False).encode()).hexdigest(),
            "source_pins": {str(path.relative_to(ROOT)): _sha(path) for path in sorted(paths)}}


class OwningTests:
    def __init__(self, collector, required):
        self.collector, self.required, self.current = collector, required, None

    def pytest_configure(self, config):
        import test_v2_split_acceptance as owners
        self.owners, self.original = owners, owners.split_benchmark

        def factory():
            module = self.original()
            for name in CASE_FUNCTIONS:
                actual = getattr(module, name)

                @wraps(actual)
                def capture(*args, _actual=actual, **kwargs):
                    record = _actual(*args, **kwargs)
                    self.collector.returned(self.current.nodeid, record)
                    return record

                setattr(module, name, capture)
            return module

        owners.split_benchmark = factory

    def pytest_unconfigure(self, config):
        self.owners.split_benchmark = self.original

    def pytest_collection_modifyitems(self, session, config, items):
        mapped = {}
        for item in items:
            case = case_id_for_item(item)
            if case is not None:
                if case not in self.required or case in mapped:
                    raise ValueError("owning collection has duplicate/unknown native case")
                mapped[case] = item
        if set(mapped) != set(self.required):
            raise ValueError("owning collection omits canonical native cases")
        selected = [mapped[key] for key in self.collector.plan["selected_ids"]]
        config.hook.pytest_deselected(items=[item for item in items if item not in selected])
        items[:] = selected
        self.collector.bind({case: mapped[case].nodeid for case in self.collector.plan["selected_ids"]})

    def pytest_runtest_setup(self, item):
        self.current = item
        self.before = source_provenance(item)

    def pytest_runtest_logreport(self, report):
        if report.when != "call":
            return
        after = source_provenance(self.current)
        if any(after["source_pins"].get(path) != pin for path, pin in self.before["source_pins"].items()):
            raise ValueError("native source changed during owning assertions")
        self.collector.owner_finished(report.nodeid, report.outcome, after)


def main(argv=None):
    import pytest

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--eligibility", type=Path, required=True)
    parser.add_argument("--eligibility-sha256", required=True)
    parser.add_argument("--execute", action="store_true", help="Run original owning tests; omit for metadata planning only")
    args = parser.parse_args(argv)
    required = benchmark().required_native_cases()
    plan = reviewed_selection(args.eligibility, args.eligibility_sha256, required)
    collector = Collector(args.output_dir, plan)
    command = [str(ROOT / "sidecar/tests/test_v2_split_acceptance.py"),
               str(ROOT / "sidecar/tests/test_v2_split_project_flows.py"), "--rootdir", str(ROOT / "sidecar"),
               "--basetemp", str(args.output_dir / "owners"), "-o", "addopts=", "-o", "faulthandler_timeout=900", "-q", "-x"]
    if not args.execute:
        command.append("--collect-only")
    code = pytest.main(command, plugins=[OwningTests(collector, required)])
    return collector.finish(code, planning=not args.execute)


if __name__ == "__main__":
    raise SystemExit(main())
