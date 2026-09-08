"""Orchestrator: full job through JobStore + resume-skip behavior (fake provider, SAPI)."""

from __future__ import annotations

import sys

import pytest

from conftest import REPO_ROOT

pytestmark = pytest.mark.integration


@pytest.fixture()
def orch(tmp_path):
    src = REPO_ROOT / "sidecar" / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from atme.orchestrator import Orchestrator

    return Orchestrator(tmp_path / "jobs.db"), tmp_path


def test_full_job_reaches_done_with_store_checkpoints(orch):
    o, _tmp = orch
    store = o.store
    job = o.submit_topic("Why inference is hard", provider="fake", review_gate=False)
    result = o.run_job(job)
    assert result["manifest"]["artifacts"]["video"]["bytes"] > 100_000
    first, done = store.resume_point(job)
    assert first == "assembled" and len(done) >= 10
    assert store.get_job(job)["status"] == "done"
    usage = store.conn.execute(
        "SELECT COUNT(*) c FROM llm_usage WHERE job_id=?", (job,)).fetchone()
    assert usage["c"] >= 1


def test_resume_skips_completed_stages(orch, monkeypatch):
    o, _tmp = orch
    store = o.store
    job = o.submit_topic("Resume probe", provider="fake", review_gate=False)
    o.run_job(job)

    # simulate re-run after "crash": media stages back to pending, cognitive stays done
    for st in ("polished", "aligned", "rendered", "assembled"):
        store.conn.execute("UPDATE stages SET status='pending' WHERE job_id=? AND name=?",
                           (job, st))
        store.conn.execute("UPDATE stages SET started_at=NULL, ended_at=NULL "
                           "WHERE job_id=? AND name=?", (job, st))
    store.set_job_status(job, "running")
    store.conn.commit()

    from atme import cognitive as cog_mod

    calls = {"n": 0}
    real_run = cog_mod.run_cognitive

    def counting(*a, **k):
        calls["n"] += 1
        return real_run(*a, **k)

    monkeypatch.setattr(cog_mod, "run_cognitive", counting)

    # also prove voiced is skipped when segments exist
    sapi_calls = {"n": 0}

    from atme.audio import tts_sapi as sapi_mod

    real_sapi = sapi_mod.synthesize_scenes

    def counting_sapi(*a, **k):
        sapi_calls["n"] += 1
        return real_sapi(*a, **k)

    monkeypatch.setattr(sapi_mod, "synthesize_scenes", counting_sapi)

    result2 = o.run_job(job)
    assert result2["manifest"]["duration_ms"] > 0
    assert calls["n"] == 0, "resume must NOT rerun cognitive when its stages are done"
    assert sapi_calls["n"] == 0, "resume must NOT resynthesize voice when segments exist"


def test_failed_stage_marks_job_failed(orch):
    o, _tmp = orch
    store = o.store
    job = o.submit_topic("boom", provider="fake", review_gate=False)

    def bad_completes(settings):
        raise RuntimeError("provider exploded")

    o._completes_for = bad_completes  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        o.run_job(job)
    assert store.get_job(job)["status"] == "failed"
    assert store.resume_point(job)[0] in ("created", "researched")

def test_review_gate_pauses_then_approves_to_done(orch):
    o, _tmp = orch
    store = o.store
    job = o.submit_topic("Gate check", provider="fake", review_gate=True)
    result = o.run_job(job)
    assert result.get("paused") is True
    assert store.get_job(job)["status"] == "paused"
    _fp, done = store.resume_point(job)
    assert "scripted" in done and "reviewed" not in done

    # human approves via the API-equivalent path: mark reviewed, set running, re-enter
    store.start_stage(job, "reviewed")
    store.finish_stage(job, "reviewed", ok=True)
    store.set_job_status(job, "running")
    result2 = o.run_job(job)
    assert result2["manifest"]["artifacts"]["video"]["bytes"] > 100_000
    assert store.get_job(job)["status"] == "done"
