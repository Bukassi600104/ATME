"""The default watchdog must not replace an explicit pytest diagnostic timer."""

from types import SimpleNamespace

import conftest
import pytest


@pytest.mark.parametrize("fails", [False, True])
def test_default_tripwire_arms_and_always_cancels(monkeypatch, fails):
    calls = []
    monkeypatch.setattr(conftest.faulthandler, "dump_traceback_later",
                        lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(conftest.faulthandler, "cancel_dump_traceback_later",
                        lambda: calls.append("cancel"))
    request = SimpleNamespace(config=SimpleNamespace(getini=lambda name: 0.0))
    tripwire = conftest._per_test_hang_tripwire.__wrapped__(request)
    next(tripwire)
    assert calls == [((600,), {"exit": True})]
    if fails:
        with pytest.raises(ValueError, match="test failure"):
            tripwire.throw(ValueError("test failure"))
    else:
        with pytest.raises(StopIteration):
            next(tripwire)
    assert calls == [((600,), {"exit": True}), "cancel"]


@pytest.mark.parametrize("fails", [False, True])
def test_explicit_pytest_timer_is_not_armed_or_cancelled(monkeypatch, fails):
    calls = []
    monkeypatch.setattr(conftest.faulthandler, "dump_traceback_later",
                        lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(conftest.faulthandler, "cancel_dump_traceback_later",
                        lambda: calls.append("cancel"))
    request = SimpleNamespace(config=SimpleNamespace(getini=lambda name: "120"))
    tripwire = conftest._per_test_hang_tripwire.__wrapped__(request)
    next(tripwire)
    if fails:
        with pytest.raises(ValueError, match="test failure"):
            tripwire.throw(ValueError("test failure"))
    else:
        with pytest.raises(StopIteration):
            next(tripwire)
    assert calls == []
