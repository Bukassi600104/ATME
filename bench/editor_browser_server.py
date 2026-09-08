"""Isolated browser verification host. Never use as a production server.

Serves the actual built frontend/API; only Tauri sidecar discovery is simulated.
All provider/media job execution is disabled and all writes stay in a new test dir.
"""
import argparse
import json
from pathlib import Path
import sys
import secrets
import hashlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sidecar" / "src"))

from atme.orchestrator import Orchestrator
from atme.server.app import create_app
from atme.settings import SettingsStore
from atme.store.db import STAGE_ORDER
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import uvicorn


class VerificationOrchestrator(Orchestrator):
    def run_job(self, job_id, progress_cb=None):
        raise RuntimeError("Browser verification host: job execution intentionally disabled")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--port", type=int, default=5173)
    parser.add_argument("--stop", action="store_true", help="Gracefully stop this isolated verification host")
    parser.add_argument("--proposal-fixture", action="store_true", help="Seed an explicitly synthetic saved proposal; no model calls")
    args = parser.parse_args()
    if args.stop:
        import re
        from urllib.request import Request, urlopen
        url = f"http://127.0.0.1:{args.port}"
        html = urlopen(url, timeout=5).read().decode("utf-8")
        if "Disabled verification command:" not in html:
            raise RuntimeError("Refusing to stop a non-verification server")
        token = re.search(r'"token": "([A-Za-z0-9_-]+)"', html).group(1)
        response = urlopen(Request(url + "/shutdown", data=b"", method="POST",
                                   headers={"Authorization": "Bearer " + token}), timeout=5)
        print(response.read().decode("utf-8"))
        return
    directory = Path(args.data_dir).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    orch = VerificationOrchestrator(directory / "jobs.db", data_root=directory,
                                   settings_store=SettingsStore(directory / "settings.json"))
    job = orch.store.create_job("Original queue explanation — browser verification", settings={
        "provider": "fake", "voice": "upload", "review_gate": True})
    job_dir = orch._job_dir(job)
    job_dir.mkdir(parents=True, exist_ok=True)
    layout = json.loads((ROOT / "schemas/examples/board-continuity.example.json").read_text())
    (job_dir / "layout.json").write_text(json.dumps(layout), encoding="utf-8")
    (job_dir / "script.json").write_text(json.dumps({"topic": "Queues", "scenes": [
        {"scene_id": i, "phase": "architecture", "spoken_text": text,
         "visual_directive": "Explain the queue", "est_seconds": duration}
        for i, text, duration in [(1, "Arrivals exceed service capacity.", 4),
                                  (2, "This measurement is illustrative.", 3),
                                  (3, "The backlog grows by four each second.", 3)]
    ]}), encoding="utf-8")
    (job_dir / "audio_state.json").write_text(json.dumps({"duration_ms": 10000}))
    (job_dir / "narration_events.json").write_text(json.dumps([
        {"target_id": "el-test", "scene_id": 1, "phrase": "service capacity",
         "status": "ambiguous", "match_count": 2}]))
    if args.proposal_fixture:
        from atme.planning_context import build_planning_context
        from atme.agents.board_planner import compile_proposal
        script = json.loads((job_dir / "script.json").read_text(encoding="utf-8"))
        times = sorted({e["appear_at_ms"] for e in layout["elements"]} | {7000})
        words = [{"word": "synthetic", "scene_id": 1 if at < 4000 else 2 if at < 7000 else 3,
                  "start_ms": at, "end_ms": at + 50, "confidence": 0.9} for at in times]
        context = build_planning_context(script, words, 10000, "a" * 64)
        (job_dir / "planning_context.json").write_text(json.dumps(context), encoding="utf-8")
        (job_dir / "audio_state.json").write_text(json.dumps({"duration_ms": 10000, "sha256": "a" * 64}))
        proposal = {"activations": [{"board_id": a["board_id"],
                     "start_word_index": None if i == 0 else times.index(a["start_ms"]),
                     "reason": "Synthetic browser-verification fixture, not an AI result"}
                     for i, a in enumerate(layout["board_timeline"]["activations"])],
                    "assignments": [{"element_id": e["id"], "board_id": e["board_id"],
                                     "word_index": times.index(e["appear_at_ms"])} for e in layout["elements"]]}
        compile_proposal(layout, context, proposal)
        names = ("layout.json", "planning_context.json", "script.json", "audio_state.json")
        record = {"proposal_id": "browser-fixture", "proposal": proposal,
                  "source_hashes": {name: hashlib.sha256((job_dir / name).read_bytes()).hexdigest() for name in names}}
        (job_dir / "board_proposal.json").write_text(json.dumps(record), encoding="utf-8")
    for stage in STAGE_ORDER:
        orch.store.start_stage(job, stage)
        orch.store.finish_stage(job, stage, ok=True)
    orch.store.set_job_status(job, "done")
    token = secrets.token_urlsafe(24)
    app = create_app(token, orch)
    app.mount("/assets", StaticFiles(directory=ROOT / "app/dist/assets"), name="assets")
    @app.get("/", response_class=HTMLResponse)
    def index():
        html = (ROOT / "app/dist/index.html").read_text(encoding="utf-8")
        bridge = "<script>window.__consoleErrors=[];window.addEventListener('error',e=>window.__consoleErrors.push(e.message));window.addEventListener('unhandledrejection',e=>window.__consoleErrors.push(String(e.reason)));window.__TAURI_INTERNALS__={invoke:async(name)=>{if(name==='sidecar_info')return " + json.dumps({"ready": True, "port": args.port, "token": token}) + ";throw new Error('Disabled verification command: '+name)}};</script>"
        return html.replace("<head>", "<head>" + bridge)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=args.port))
    app.state.uvicorn_server = server
    print(f"Isolated verification job {job}; http://127.0.0.1:{args.port}", flush=True)
    server.run()


if __name__ == "__main__":
    main()
