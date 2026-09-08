from __future__ import annotations

import os

from atme import parent_watch


def test_parent_watchdog_is_disabled_without_a_valid_host(monkeypatch):
    monkeypatch.setattr(parent_watch, "_started", False)
    monkeypatch.delenv("ATME_PARENT_PID", raising=False)
    assert parent_watch.start_parent_watchdog() is False

    monkeypatch.setenv("ATME_PARENT_PID", "not-a-pid")
    assert parent_watch.start_parent_watchdog() is False

    monkeypatch.setenv("ATME_PARENT_PID", str(os.getpid()))
    assert parent_watch.start_parent_watchdog() is False


def test_parent_watchdog_starts_a_daemon_thread(monkeypatch):
    started: list[dict] = []
    monkeypatch.setattr(parent_watch, "_started", False)

    class FakeThread:
        def __init__(self, **kwargs):
            started.append(kwargs)

        def start(self):
            started[-1]["started"] = True

    monkeypatch.setenv("ATME_PARENT_PID", "424242")
    monkeypatch.setattr(parent_watch.threading, "Thread", FakeThread)

    assert parent_watch.start_parent_watchdog() is True
    assert started[0]["daemon"] is True
    assert started[0]["name"] == "atme-parent-watchdog"
    assert started[0]["started"] is True
