import sys
from types import SimpleNamespace

import pytest

from atme.jev_decisions import evaluate
from atme.project_service import ProjectError, ProjectService
from atme.store.db import JobStore


class Dumpable(SimpleNamespace):
    def model_dump(self, mode="json"):
        return dict(self.__dict__)


def test_jev_is_optional_and_never_required_for_project_work(monkeypatch, tmp_path):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    store = JobStore(tmp_path / "project.db")
    service = ProjectService(store)
    project_id = service.create("Optional Jev", "LONG_FORM_16_9", "video-only")["project_id"]
    with pytest.raises(ProjectError) as raised:
        evaluate(service, project_id, "visual_treatment", "Explain tokenization")
    assert raised.value.code == "jev_not_configured"
    assert service.open(project_id)["revision"] == 0
    store.close()


def test_jev_returns_typed_advice_without_mutating_project(monkeypatch, tmp_path):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    captured = {}

    class Choice:
        def __init__(self, **kwargs): self.kwargs = kwargs

    class Client:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def system_one(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                model="jev-test",
                choices={"decision": Dumpable(choice="diagram", confidence=0.94,
                                                probabilities={"diagram": 0.94})},
                usage=Dumpable(input_tokens=40, output_tokens=0),
            )

    monkeypatch.setitem(sys.modules, "typesafe_sdk",
                        SimpleNamespace(Choice=Choice, TypeSafeClient=Client))
    store = JobStore(tmp_path / "project.db")
    service = ProjectService(store)
    project_id = service.create("Jev advice", "LONG_FORM_16_9", "video-only")["project_id"]
    result = evaluate(service, project_id, "visual_treatment", "Show how tokens relate")
    assert result["answer"]["choice"] == "diagram"
    assert result["advisory_only"] is True
    assert captured["state"]["project"]["revision"] == 0
    assert service.open(project_id)["revision"] == 0
    store.close()
