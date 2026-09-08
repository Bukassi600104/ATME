"""JobStore: stage transitions, artifact binding, resume-point semantics, usage ledger."""

from __future__ import annotations

from atme.store.db import JobStore


def test_stage_progression_and_resume(tmp_path):
    store = JobStore(tmp_path / "jobs.db")
    job = store.create_job(topic="t", title="T")

    # fresh job: resume at created
    assert store.resume_point(job) == ("created", [])

    for stage in ("created", "researched", "verified"):
        store.start_stage(job, stage)
        store.finish_stage(job, stage, ok=True)
    first, done = store.resume_point(job)
    assert first == "scripted" and done == ["created", "researched", "verified"]

    # failure at scripted -> resume retries exactly there
    store.start_stage(job, "scripted")
    store.finish_stage(job, "scripted", ok=False, error="llm timeout")
    assert store.get_job(job)["status"] == "failed"
    assert store.resume_point(job) == ("scripted", ["created", "researched", "verified"])

    # retry succeeds
    store.start_stage(job, "scripted", attempt=2)
    store.finish_stage(job, "scripted", ok=True, attempt=2)
    assert store.resume_point(job)[0] == "reviewed"


def test_artifacts_bound_to_stages(tmp_path):
    store = JobStore(tmp_path / "jobs.db")
    job = store.create_job()
    store.attach_artifact(job, "aligned", "cue_timeline", "x.json", "abc123", 10)
    store.attach_artifact(job, "rendered", "video", "y.mp4", "def456", 999)
    only = store.artifacts_for(job, "aligned")
    assert len(only) == 1 and only[0]["kind"] == "cue_timeline"
    assert len(store.artifacts_for(job)) == 2


def test_usage_and_events(tmp_path):
    from atme.gateway.router import LedgerEntry

    store = JobStore(tmp_path / "jobs.db")
    job = store.create_job()
    store.record_usage(job, LedgerEntry(role="writer", model="fake/1",
                                        prompt_tokens=100, completion_tokens=50,
                                        cost_usd=0.01, wall_ms=800))
    row = store.conn.execute("SELECT * FROM llm_usage WHERE job_id=?", (job,)).fetchone()
    assert row["role"] == "writer" and row["cost_usd"] == 0.01
    store.log(job, "hello")
    ev = store.conn.execute("SELECT message FROM events WHERE job_id=?", (job,)).fetchall()
    assert any("hello" in e["message"] for e in ev)


def test_reset_preserves_attempt_history_and_uses_latest_status(tmp_path):
    store = JobStore(tmp_path / "jobs.db")
    job = store.create_job("attempt history")
    for stage in ("created", "researched", "verified", "scripted", "reviewed",
                  "laid_out", "voiced", "polished", "aligned", "rendered", "assembled"):
        store.ensure_stage(job, stage)
        store.start_stage(job, stage)
        store.finish_stage(job, stage)
    store.reset_from_stage(job, "rendered")
    assert store.resume_point(job)[0] == "rendered"
    rows = store.conn.execute(
        "SELECT attempt,status FROM stages WHERE job_id=? AND name='rendered' ORDER BY attempt",
        (job,)).fetchall()
    assert [(row["attempt"], row["status"]) for row in rows] == [
        (1, "done"), (2, "pending")]
