"""Job Orchestrator (M3): drives one job through checkpointed stages via JobStore.

Stage map to plan S2 state machine:
  created -> researched -> verified -> scripted -> [reviewed: auto-skip until Review UI]
  -> laid_out -> voiced -> polished+aligned+rendered+assembled (media block)

Honest interim limitation: the media block executes as ONE run_pipeline call; a crash inside it
re-runs the whole media block on resume. Segment-level render checkpoints arrive with renderer
segmentation (M4). Cognitive and voice stages are individually resumable NOW.

Every stage writes artifacts through the store; llm usage rows land per gateway entry.
"""

from __future__ import annotations

import json
import hashlib
import logging
import sys
import time
from pathlib import Path
from typing import Any

from atme.store.db import JobStore

log = logging.getLogger(__name__)


class JobPaused(RuntimeError):
    pass


class JobCanceled(RuntimeError):
    pass


class Orchestrator:
    def __init__(self, db_path: str | Path, data_root: str | Path | None = None,
                 settings_store=None):
        db_path = Path(db_path)
        self.store = JobStore(db_path)
        self.data_root = Path(data_root) if data_root is not None else db_path.parent
        self.settings_store = settings_store

    # ------------------------------------------------------------------ submit
    def submit_topic(self, topic: str, provider: str = "fake",
                     providers_json: str | None = None,
                     width: int = 1280, height: int = 720, fps: int = 30,
                     voice: str = "sapi",
                     review_gate: bool = True) -> int:
        job_id = self.store.create_job(topic=topic,
                                       settings={"provider": provider, "width": width,
                                                 "height": height, "fps": fps,
                                                 "voice": voice,
                                                 "review_gate": review_gate,
                                                 **({"providers_json": providers_json}
                                                    if providers_json else {})})
        for name in ("created", "researched", "verified", "scripted", "reviewed",
                     "laid_out", "voiced", "polished", "aligned", "rendered", "assembled"):
            self.store.ensure_stage(job_id, name)
        return job_id

    # ------------------------------------------------------------------ helpers
    def _completes_for(self, settings: dict):
        provider = settings.get("provider", "fake")
        if provider == "litellm":
            pj = settings.get("providers_json")
            if not pj and self.settings_store is not None:
                cfg = self.settings_store.runtime_roles()
            elif pj:
                cfg = json.loads(pj) if isinstance(pj, str) else pj
            else:
                raise ValueError("AI providers are not configured")
            from atme.gateway.router import RoleConfig, make_litellm_complete

            return {role: make_litellm_complete(role, RoleConfig(**cfg[role]))
                    for role in ("reasoner", "researcher", "writer", "layouter")}
        return None  # fake

    def _stage(self, job_id: int, name: str, fn, attempt: int = 1,
               artifact_fn=None) -> Any:
        first, done = self.store.resume_point(job_id)
        if name in done:
            log.info("resume: %s already done, skipping", name)
            return None
        with self.store._lock:
            latest = self.store.conn.execute(
                "SELECT attempt,status FROM stages WHERE job_id=? AND name=? "
                "ORDER BY attempt DESC LIMIT 1", (job_id, name)).fetchone()
        stage_attempt = int(latest["attempt"]) if latest else max(1, attempt)
        if latest and latest["status"] in ("failed", "running"):
            stage_attempt += 1
        self._check_control(job_id)
        self.store.start_stage(job_id, name, attempt=stage_attempt)
        try:
            result = fn()
            if artifact_fn:
                for kind, path in artifact_fn(result):
                    self._attach_file(job_id, name, kind, Path(path))
            self._check_control(job_id)
        except (JobPaused, JobCanceled):
            with self.store._tx() as conn:
                conn.execute(
                    "UPDATE stages SET status='pending',error=NULL,ended_at=? "
                    "WHERE job_id=? AND name=? AND attempt=?",
                    (time.time(), job_id, name, stage_attempt))
            raise
        except Exception as exc:  # noqa: BLE001
            self.store.finish_stage(job_id, name, ok=False, error=str(exc)[:300],
                                    attempt=stage_attempt)
            raise
        self.store.finish_stage(job_id, name, ok=True,
                                attempt=stage_attempt)
        return result

    def _attach_file(self, job_id: int, stage: str, kind: str, path: Path) -> None:
        if not path.exists() or not path.is_file():
            raise RuntimeError("stage %s did not produce %s" % (stage, path))
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
        sha = digest.hexdigest()
        with self.store._lock:
            exists = self.store.conn.execute(
                "SELECT 1 FROM artifacts WHERE job_id=? AND stage=? AND kind=? "
                "AND path=? AND sha256=?", (job_id, stage, kind, str(path), sha)).fetchone()
        if not exists:
            self.store.attach_artifact(job_id, stage, kind, str(path), sha, path.stat().st_size)

    def _repair_missing_checkpoints(self, job_id: int, job_dir: Path) -> None:
        expected = [
            ("researched", [job_dir / "fact_sheet.json"]),
            ("scripted", [job_dir / "script.json"]),
            ("laid_out", [job_dir / "layout.json"]),
            ("polished", [job_dir / "audio_state.json", job_dir / "audio" / "final.wav"]),
            ("aligned", [job_dir / "align_state.json", job_dir / "cue_timeline.json"]),
            ("rendered", [job_dir / "render_state.json", job_dir / "out" / "video.mp4"]),
            ("assembled", [job_dir / "manifest.json", job_dir / "out" / "final.mp4"]),
        ]
        _first, done = self.store.resume_point(job_id)
        for stage, paths in expected:
            if stage in done and not all(path.exists() and path.stat().st_size > 0 for path in paths):
                self.store.log(job_id, "checkpoint %s was incomplete; rebuilding downstream" % stage,
                               level="warning")
                self.store.reset_from_stage(job_id, stage)
                break

    def _check_control(self, job_id: int) -> None:
        job = self.store.get_job(job_id)
        status = job and job.get("status")
        if status == "pause_requested":
            self.store.set_job_status(job_id, "paused")
            self.store.log(job_id, "job paused at a safe checkpoint")
            raise JobPaused("job paused")
        if status in ("cancel_requested", "canceled"):
            self.store.set_job_status(job_id, "canceled")
            self.store.log(job_id, "job canceled")
            raise JobCanceled("job canceled")

    # ------------------------------------------------------------------ run
    def run_job(self, job_id: int, progress_cb=None) -> dict:
        job = self.store.get_job(job_id)
        if not job:
            raise KeyError("job %s not found" % job_id)
        settings = job["settings"]
        topic = job["topic"]
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        self._repair_missing_checkpoints(job_id, job_dir)

        from atme import warmup

        warmup.warm_heavy_imports()

        from atme.guardrails import GuardrailError, preflight

        try:
            _stats = preflight(job_dir)
            self.store.log(job_id, "preflight ok: %s" % json.dumps(_stats))
        except GuardrailError as exc:
            self.store.log(job_id, str(exc), level="error")
            self.store.set_job_status(job_id, "failed")
            raise
        self.store.set_job_status(job_id, "running")

        # ---- cognitive: checkpoint research, verification, script, review, layout ----
        from atme import cognitive

        completes_cache: list[Any] = [None]

        def get_completes():
            if completes_cache[0] is None:
                completes_cache[0] = self._completes_for(settings)
            return completes_cache[0]

        self._stage(job_id, "created", lambda: True)

        def do_research():
            out = cognitive.research_stage(
                topic, job_dir, completes=get_completes(),
                max_research_rounds=1 if settings.get("provider") == "fake" else None)
            for entry in out["ledger_entries"]:
                self.store.record_usage(job_id, entry)
            return out

        research_out = self._stage(
            job_id, "researched", do_research,
            artifact_fn=lambda _out: [("fact_sheet", job_dir / "fact_sheet.json")])
        if research_out is None:
            fact_sheet = _load_json(job_dir / "fact_sheet.json")
        else:
            fact_sheet = research_out["fact_sheet"]
        # The research agent includes adversarial verification and cite-or-cut. Keeping a
        # distinct checkpoint makes the audit state explicit without repeating provider calls.
        self._stage(job_id, "verified", lambda: True)

        def do_script():
            out = cognitive.script_stage(
                fact_sheet, int(settings.get("target_seconds", 45)), job_dir,
                completes=get_completes())
            for entry in out["ledger_entries"]:
                self.store.record_usage(job_id, entry)
            self.store.set_job_title(
                job_id, out["script_doc"].get("title") or topic)
            return out

        script_out = self._stage(
            job_id, "scripted", do_script,
            artifact_fn=lambda _out: [("script", job_dir / "script.json"),
                                      ("review_flags", job_dir / "review_flags.json")])
        script_doc = (script_out or {}).get("script_doc")
        if script_doc is None:
            script_doc = _load_json(job_dir / "script.json")

        # Review gate (plan S2): ON by default. Pause here; POST /jobs/{id}/review
        # marks 'reviewed' done and restarts the run.
        _fp2, dn2 = self.store.resume_point(job_id)
        if "reviewed" in dn2:
            pass  # approved earlier
        elif settings.get("review_gate", True):
            self.store.set_job_status(job_id, "paused")
            if progress_cb:
                progress_cb("paused_review", job_id)
            return {"job_id": job_id, "paused": True, "script": script_doc}
        else:
            self._stage(
                job_id, "reviewed", lambda: True,
                artifact_fn=lambda _out: [("approved_script", job_dir / "script.json")])
        if progress_cb:
            progress_cb("cognitive", job_id)

        def do_layout():
            out = cognitive.layout_stage(script_doc, job_dir, completes=get_completes())
            for entry in out["ledger_entries"]:
                self.store.record_usage(job_id, entry)
            return out

        self._stage(
            job_id, "laid_out", do_layout,
            artifact_fn=lambda _out: [("layout", job_dir / "layout.json"),
                                      ("layout_report", job_dir / "layout_report.json"),
                                      ("visual_plan", job_dir / "visual_plan.json")])

        # ---- voiced: draft TTS or an uploaded original recording
        seg_dir = job_dir / "segments"
        have_segments = any(seg_dir.glob("scene*.wav"))
        voice_mode = settings.get("voice", "sapi")

        if voice_mode == "upload" and not (job_dir / "audio" / "upload.wav").exists():
            self.store.set_job_status(job_id, "waiting_voice")
            if progress_cb:
                progress_cb("waiting_voice", job_id)
            return {"job_id": job_id, "paused": True, "waiting_voice": True}

        def voiced():
            if have_segments:
                return None
            from atme.audio.tts_sapi import synthesize_scenes

            return synthesize_scenes(script_doc["scenes"], seg_dir)

        if voice_mode == "upload":
            _fp_voice, done_voice = self.store.resume_point(job_id)
            if "voiced" not in done_voice:
                self.store.start_stage(job_id, "voiced")
                self.store.finish_stage(job_id, "voiced", ok=True)
        elif not have_segments:
            self._stage(job_id, "voiced", voiced)
        else:
            self.store.start_stage(job_id, "voiced")
            self.store.finish_stage(job_id, "voiced", ok=True)
        if progress_cb:
            progress_cb("voice", job_id)

        # ---- independently checkpointed media stages ----
        from atme.pipeline import (align_stage, assemble_stage, polish_stage,
                                   render_stage)

        mode = "upload" if voice_mode == "upload" else "segments"
        audio_state = self._stage(
            job_id, "polished", lambda: polish_stage(job_dir, voice_mode=mode),
            artifact_fn=lambda out: [("audio", out["final_wav"]),
                                     ("audio_state", job_dir / "audio_state.json")])
        if audio_state is None:
            audio_state = _load_json(job_dir / "audio_state.json")
        if progress_cb:
            progress_cb("polished", job_id)

        align_state = self._stage(
            job_id, "aligned", lambda: align_stage(
                job_dir, script_doc, audio_state, voice_mode=mode,
                layout_dict=_load_layout(job_dir)),
            artifact_fn=lambda out: [("cue_timeline", out["cues_file"]),
                                     ("planning_context", out["planning_context_file"]),
                                     ("layout", out["layout_file"]),
                                     ("visual_plan", out["visual_plan_file"]),
                                     ("align_state", job_dir / "align_state.json")])
        if align_state is None:
            align_state = _load_json(job_dir / "align_state.json")
        if progress_cb:
            progress_cb("aligned", job_id)

        render_state = self._stage(
            job_id, "rendered", lambda: render_stage(
                job_dir, align_state, width=settings.get("width", 1280),
                height=settings.get("height", 720), fps=settings.get("fps", 30),
                control_cb=lambda: self._check_control(job_id)),
            artifact_fn=lambda out: [("silent_video", out["silent_video"]),
                                     ("render_state", job_dir / "render_state.json")])
        if render_state is None:
            render_state = _load_json(job_dir / "render_state.json")
        if progress_cb:
            progress_cb("rendered", job_id)

        manifest = self._stage(
            job_id, "assembled", lambda: assemble_stage(
                job_dir, script_doc, audio_state, align_state, render_state),
            artifact_fn=lambda out: [("video", out["artifacts"]["video"]["path"]),
                                     ("manifest", job_dir / "manifest.json")])
        if manifest is None:
            manifest = _load_json(job_dir / "manifest.json")
        if progress_cb:
            progress_cb("done", job_id)

        self.store.set_job_status(job_id, "done")
        return {"job_id": job_id, "manifest": manifest}

    def _job_dir(self, job_id: int) -> Path:
        return self.data_root / "jobs" / ("job-%04d" % job_id)


def ledger_entries(ledger_summary: dict | None):
    """Convert gateway ledger summary rows into store-compatible pseudo-entries."""
    if not ledger_summary:
        return []
    from atme.gateway.router import LedgerEntry

    out = []
    for role, slot in ledger_summary.get("roles", {}).items():
        out.append(LedgerEntry(role=role, model="aggregated",
                               prompt_tokens=slot.get("prompt_tokens", 0),
                               completion_tokens=slot.get("completion_tokens", 0),
                               cost_usd=slot.get("cost_usd") or None))
    return out


def _load_layout(job_dir: Path) -> dict | None:
    p = job_dir / "layout.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def _load_json(path: Path) -> dict:
    if not path.exists():
        raise RuntimeError("resume requires persisted %s" % path)
    return json.loads(path.read_text(encoding="utf-8"))
