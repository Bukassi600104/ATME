"""Metadata-only collector checks; no native production or acceptance credit."""

import importlib.util
import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest


def collector_module():
    path = Path(__file__).resolve().parents[2] / "bench/split_native_records.py"
    spec = importlib.util.spec_from_file_location("native_record_collector", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ORIGINAL_IDS = (
    "visual-state-character-true-part-2-open_hands-draw-landscape", "aperture-illustration-clip-reveal-landscape",
    "registry-part-2-enter-landscape", "chart-bars-draw-landscape", "container-mask-result-reveal-landscape",
    "evidence-plain-reveal-landscape", "media-image-reveal-landscape", "text-list-text-write-landscape",
    "visual-illustration-reveal-landscape", "connector-curve-pointer-draw-landscape",
    "history-authored-distinct-clip-authored-landscape",
)


def test_durable_collector_interface_exists():
    path = Path(__file__).resolve().parents[2] / "bench/split_native_records.py"
    assert path.is_file(), "Missing durable native record collector"


def test_exact634_to613_uses_explicit_current_eligibility_not_record_existence():
    module = collector_module()
    required = module.benchmark().required_native_cases()
    project = [key for key, group in required.items() if group == "project"]
    preserved = list(ORIGINAL_IDS) + project
    plan = module.select_cases(required, preserved, preserved)
    assert len(required) == 634 and len(plan["eligible_ids"]) == 21 and len(plan["selected_ids"]) == 613
    conditional = module.select_cases(required, preserved, [key for key in preserved if key != "evidence-plain-reveal-landscape"])
    assert len(conditional["selected_ids"]) == 614
    assert "evidence-plain-reveal-landscape" in conditional["selected_ids"]
    assert "evidence-plain-reveal-landscape" not in plan["selected_ids"]


@pytest.mark.parametrize("fault", ["duplicate", "unknown", "omission", "extra", "not_preserved"])
def test_selection_rejects_duplicate_unknown_omitted_or_extra_slots(fault):
    module = collector_module()
    required, preserved, eligible, requested = {"a": "metadata", "b": "metadata"}, ["a"], ["a"], ["b"]
    if fault == "duplicate": requested = ["b", "b"]
    elif fault == "unknown": requested = ["unknown"]
    elif fault == "omission": requested = []
    elif fault == "extra": requested = ["a", "b"]
    else: preserved = []
    with pytest.raises(ValueError): module.select_cases(required, preserved, eligible, requested)


@pytest.fixture
def metadata_record(tmp_path):
    png, svg, contact = tmp_path / "source.png", tmp_path / "source.svg", tmp_path / "contact.png"
    for path in (png, svg, contact): path.write_bytes(b"SYNTHETIC METADATA ONLY " + path.name.encode())
    return {"case_id": "a", "frames": {"0": {"png_path": str(png), "png_sha256": sha256(png.read_bytes()).hexdigest(),
            "svg_path": str(svg), "svg_sha256": sha256(svg.read_bytes()).hexdigest(),
            "state_versions": {"source": 7}, "state_sha256": {"source": "unchanged producer value"}}},
            "contact_sheet_path": str(contact), "contact_sheet_sha256": sha256(contact.read_bytes()).hexdigest()}


def bound_collector(module, tmp_path, selected=("a",)):
    plan = module.select_cases(dict.fromkeys(selected, "metadata"), [], [])
    collector = module.Collector(tmp_path / "output", plan)
    collector.bind({key: f"tests/metadata_only.py::test_{key}" for key in selected})
    return collector


def test_owning_assertions_must_pass_before_envelope_is_persisted(tmp_path, metadata_record):
    module = collector_module()
    collector = bound_collector(module, tmp_path)
    node = "tests/metadata_only.py::test_a"
    original = deepcopy(metadata_record)
    originals = {path: Path(path).read_bytes() for path, _ in module.artifact_references(metadata_record)}
    collector.returned(node, metadata_record)
    assert not (collector.output / "a").exists()
    collector.owner_finished(node, "passed", {"metadata_only": True, "owner_function": "test_a"})
    envelope = json.loads((collector.output / "a/record.json").read_text())
    assert envelope == {"status": "DIAGNOSTIC ONLY", "final_acceptance": False, "cases": [original]}
    assert "final_acceptance" not in envelope["cases"][0]
    assert metadata_record == original
    assert all(Path(path).read_bytes() == raw for path, raw in originals.items())
    assert collector.finish(0) == 0


def test_incremental_record_survives_later_owner_assertion_failure(tmp_path, metadata_record):
    module = collector_module()
    collector = bound_collector(module, tmp_path, ("a", "b"))
    collector.returned("tests/metadata_only.py::test_a", metadata_record)
    collector.owner_finished("tests/metadata_only.py::test_a", "passed", {"metadata_only": True})
    sealed = (collector.output / "a/record.json").read_bytes()
    other = metadata_record | {"case_id": "b"}
    collector.returned("tests/metadata_only.py::test_b", other)
    collector.owner_finished("tests/metadata_only.py::test_b", "failed", {"metadata_only": True})
    assert collector.finish(1) == 1
    result = json.loads((collector.output / "native-records-run.json").read_text())
    assert result["status"] == "INCOMPLETE" and result["missing_case_ids"] == ["b"]
    assert (collector.output / "a/record.json").read_bytes() == sealed and not (collector.output / "b").exists()


@pytest.mark.parametrize("fault", ["tampered", "missing", "missing_ref", "changed_record", "duplicate", "wrong_case", "missing_return"])
def test_record_and_artifact_failures_cannot_be_sealed(tmp_path, metadata_record, fault):
    module = collector_module()
    collector = bound_collector(module, tmp_path)
    node = "tests/metadata_only.py::test_a"
    if fault == "wrong_case":
        with pytest.raises(ValueError): collector.returned(node, metadata_record | {"case_id": "unknown"})
        return
    if fault != "missing_return": collector.returned(node, metadata_record)
    if fault == "duplicate":
        with pytest.raises(ValueError): collector.returned(node, metadata_record)
        return
    if fault == "tampered": Path(metadata_record["frames"]["0"]["png_path"]).write_bytes(b"changed")
    elif fault == "missing": Path(metadata_record["frames"]["0"]["svg_path"]).unlink()
    elif fault == "missing_ref": metadata_record["frames"]["0"].pop("svg_sha256")
    elif fault == "changed_record": metadata_record["frames"]["0"]["state_versions"]["source"] = 99
    with pytest.raises((ValueError, OSError, KeyError)): collector.owner_finished(node, "passed", {"metadata_only": True})
    assert not (collector.output / "a/receipt.json").exists()
    assert collector.finish(1) == 1


def test_no_overwrite_and_partial_or_planning_results_stay_incomplete(tmp_path, metadata_record):
    module = collector_module()
    collector = bound_collector(module, tmp_path)
    collector.returned("tests/metadata_only.py::test_a", metadata_record)
    collector.owner_finished("tests/metadata_only.py::test_a", "passed", {"metadata_only": True})
    original = (collector.output / "a/record.json").read_bytes()
    with pytest.raises(FileExistsError): bound_collector(module, tmp_path)
    assert (collector.output / "a/record.json").read_bytes() == original
    other = module.Collector(tmp_path / "planned", module.select_cases({"b": "metadata"}, [], []))
    other.bind({"b": "tests/metadata_only.py::test_b"})
    assert other.finish(0, planning=True) == 0
    result = json.loads((other.output / "native-records-run.json").read_text())
    assert result["status"] == "INCOMPLETE" and result["planning_only"] and result["final_acceptance"] is False


def test_case_dispatch_uses_existing_owner_parameter_identities():
    module = collector_module()
    item = SimpleNamespace(originalname="test_split_code_offline_literal_glyph_pixels_and_seek",
                           callspec=SimpleNamespace(params={"portrait":True,"tokens":True,"mode":"write"}))
    assert module.case_id_for_item(item) == "code-tokens-write-portrait"
    item.originalname = "test_split_history_offline_native_parents_prior_actions_and_return"
    item.callspec.params = {"portrait":False,"kind":"count-group","reverse_objects":True}
    assert module.case_id_for_item(item) == "history-reversed-count-group-authored-landscape"
