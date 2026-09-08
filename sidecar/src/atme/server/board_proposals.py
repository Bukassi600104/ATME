"""Explicit, revision-checked generation and acceptance of board proposals."""
import hashlib
import json
import io
from typing import Literal
from uuid import uuid4

from fastapi import Depends, HTTPException, Response
from jsonschema import ValidationError

from atme.agents.board_planner import compile_proposal, propose_boards, _word_index
from atme.gateway.router import Ledger


def register_board_proposals(app, orch, store, auth, lock, running):
    generating = set()
    names = ("layout.json", "planning_context.json", "script.json", "audio_state.json")

    def snapshot(job_id):
        if orch is None:
            raise HTTPException(503, "orchestrator not wired")
        job = store.get_job(job_id)
        if not job:
            raise HTTPException(404, "no such job")
        if job_id in running or job["status"] not in ("paused", "done", "failed", "paused_review"):
            raise HTTPException(409, "stop the job before planning boards")
        if not {"laid_out", "polished"} <= set(store.resume_point(job_id)[1]):
            raise HTTPException(409, "saved layout and polished audio required")
        directory = orch._job_dir(job_id)
        try:
            raw = {name: (directory / name).read_bytes() for name in names}
            data = {name: json.loads(value) for name, value in raw.items()}
            context = data["planning_context.json"]
            script_hash = hashlib.sha256(json.dumps(data["script.json"], sort_keys=True,
                separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
            if (context["script_sha256"] != script_hash or
                    context["audio_sha256"] != data["audio_state.json"]["sha256"] or
                    context["duration_ms"] != data["audio_state.json"]["duration_ms"]):
                raise ValueError("stale context")
            _word_index(context)
        except (OSError, ValueError, KeyError, TypeError):
            raise HTTPException(409, "final-audio evidence missing, stale or uncertain; realign and review timing first")
        hashes = {name: hashlib.sha256(value).hexdigest() for name, value in raw.items()}
        return job, directory, data, raw, hashes

    def summary(record, candidate):
        return {"proposal_id": record["proposal_id"], "requires_review": True,
                "timeline": candidate["layout"]["board_timeline"],
                "reasons": [a["reason"] for a in record["proposal"]["activations"]],
                "assignments": [{k: e[k] for k in ("id", "scene_id", "board_id", "appear_at_ms")}
                                for e in candidate["layout"]["elements"]]}

    @app.post("/jobs/{job_id}/board-proposal", dependencies=[Depends(auth)])
    def generate(job_id: int, revision: str):
        with lock:
            job, directory, data, _, hashes = snapshot(job_id)
            if hashes["layout.json"] != revision:
                raise HTTPException(409, "layout changed; reload the editor")
            if job_id in generating:
                raise HTTPException(409, "a board proposal is already generating")
            generating.add(job_id)
        ledger = Ledger()
        try:
            try:
                completes = orch._completes_for(job["settings"])
                if not completes or "layouter" not in completes:
                    raise HTTPException(409, "configure a live spatial director for this project")
                candidate = propose_boards(data["layout.json"], data["planning_context.json"],
                                           completes["layouter"], ledger)
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(502, "board proposal failed validation or provider request; saved layout unchanged")
            finally:
                for entry in ledger.entries:
                    # Provider exception strings can contain request details. Persist usage,
                    # not raw provider errors, for this explicitly requested operation.
                    entry.error = "board proposal request failed" if entry.error else None
                    store.record_usage(job_id, entry)
            with lock:
                _, _, _, _, current = snapshot(job_id)
                if current != hashes:
                    raise HTTPException(409, "project changed during generation; proposal discarded")
                record = {"proposal_id": uuid4().hex, "source_hashes": hashes,
                          "proposal": candidate["proposal"]}
                pending = directory / "board_proposal.pending.json"
                pending.write_text(json.dumps(record, indent=2), encoding="utf-8")
                pending.replace(directory / "board_proposal.json")
                return summary(record, candidate)
        finally:
            with lock:
                generating.discard(job_id)

    def saved(job_id):
        _, directory, data, raw, hashes = snapshot(job_id)
        try:
            record = json.loads((directory / "board_proposal.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise HTTPException(404, "no saved board proposal")
        if record.get("source_hashes") != hashes:
            raise HTTPException(409, "proposal is stale; generate a new one")
        try:
            candidate = compile_proposal(data["layout.json"], data["planning_context.json"], record["proposal"])
        except (ValueError, KeyError, TypeError, ValidationError):
            raise HTTPException(409, "saved proposal is invalid; regenerate")
        return directory, raw, record, candidate

    @app.get("/jobs/{job_id}/board-proposal", dependencies=[Depends(auth)])
    def get_proposal(job_id: int):
        with lock:
            _, _, record, candidate = saved(job_id)
            return summary(record, candidate)

    @app.get("/jobs/{job_id}/board-proposal/preview", dependencies=[Depends(auth)])
    def preview(job_id: int, proposal_id: str, at_ms: int,
                version: Literal["current", "proposed"] = "proposed"):
        from atme.render.animator import _FrameRenderer, build_draw_windows
        from atme.render.svg_builder import element_stroke_info
        with lock:
            _, raw, record, candidate = saved(job_id)
            if record["proposal_id"] != proposal_id:
                raise HTTPException(409, "proposal changed; reload before previewing")
            context = json.loads(raw["planning_context.json"])
            if not 0 <= at_ms < context["duration_ms"]:
                raise HTTPException(400, "preview time must be within final audio")
            doc = candidate["layout"] if version == "proposed" else json.loads(raw["layout.json"])
            settings = store.get_job(job_id)["settings"]
            width, height = int(settings.get("width", 1280)), int(settings.get("height", 720))
            if min(width, height) <= 0:
                raise HTTPException(409, "invalid project output dimensions")
        # Bound the preview size, retaining the project's actual aspect ratio.
        scale = min(1, 960 / max(width, height))
        width, height = max(1, round(width * scale)), max(1, round(height * scale))
        infos = {el["id"]: element_stroke_info(el, doc["seed"]) for el in doc["elements"]}
        renderer = _FrameRenderer(doc, infos, build_draw_windows(doc["elements"]), width, height)
        buffer = io.BytesIO()
        renderer.frame(at_ms).save(buffer, format="PNG")
        return Response(buffer.getvalue(), media_type="image/png", headers={
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    @app.post("/jobs/{job_id}/board-proposal/accept", dependencies=[Depends(auth)])
    def accept(job_id: int, proposal_id: str):
        with lock:
            directory, raw, record, candidate = saved(job_id)
            if record["proposal_id"] != proposal_id:
                raise HTTPException(409, "proposal changed; reload before accepting")
            revision = uuid4().hex
            (directory / f"layout.before-proposal-{revision}.json").write_bytes(raw["layout.json"])
            pending = directory / f"layout.proposal-{revision}.pending.json"
            pending.write_text(json.dumps(candidate["layout"], indent=2), encoding="utf-8")
            store.reset_from_stage(job_id, "aligned")
            pending.replace(directory / "layout.json")
            store.set_job_status(job_id, "paused")
            return {"saved": True, "status": "paused", "requires_realign": True}
