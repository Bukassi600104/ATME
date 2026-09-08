# ATME Runbook (developer)

## Prereqs on the dev box
Python 3.12 · Node 24 + pnpm 11 · Rust 1.96+ · FFmpeg 8.1 (winget Gyan build) — all present.

## One-time setup

    py -3.12 -m venv sidecar\.venv
    sidecar\.venv\Scripts\python -m pip install -e "./sidecar[dev,gateway,audio,align,tts,render]"

Fixture VO for tests (Windows SAPI, no downloads):

    powershell -File bench\make_fixture_vo.ps1

## Run pieces standalone

| Piece | Command |
|---|---|
| Contract+unit tests | sidecar: python -m pytest -q |
| Full e2e incl. integration | sidecar: python -m pytest -q (integration auto-skips without fixture VO) |
| Offline regression pipeline | PYTHONPATH=sidecar/src; python -m atme.cli run --topic "..." --provider fake --job-dir data/jobs/x |
| Sidecar HTTP API | python -m atme.server --port 0 --token DEV |
| UI typecheck | app: pnpm exec tsc --noEmit |
| Rust check | app/src-tauri: cargo check |
| Calibration | python bench/calibrate.py / bench/bench_ml.py / bench/bench_render.py |

## Production behavior

- Desktop jobs always use configured LiteLLM roles; the fake provider is test-only.
- The original-voice path is primary. Uploads are streamed to disk, decoded to mono 24 kHz WAV,
  quality checked, polished, transcribed, reconciled against the approved script, then used as
  the master timeline for diagrams and camera cues.
- SAPI remains a local draft-voice option. Kokoro is not presented as a production-quality
  default on this CPU.
- The alignment model can be prepared from Settings and is cached under the per-user ATME data
  directory. Starting a job also begins preparation in the background.
- Cognitive and media stages are independently checkpointed; rendered output is subdivided into
  60-second MP4 segments. Missing checkpoint files are detected and rebuilt downstream.
- Sidecar work is serialized to one worker on this machine. Sidecar health is monitored off the
  UI thread, so the window remains closable during cold start. Closing the desktop app requests a
  graceful shutdown and then terminates the exact Windows process tree; the frozen sidecar also
  watches its trusted host PID and exits independently if the desktop host disappears.

## Failure triage quickrefs
- SchemaViolation in logs -> an agent output violated its contract 4x; check prompts/ changes
  against golden fixtures first.
- ffmpeg failed 69,320... -> see stderr tail in job events; usually disk-full or codec arg drift.
- Orphan python processes after close -> should be impossible post-M4 zombie hook; if seen,
  taskkill /PID <child> and file it.

## Packaging (M4)

    powershell -File app\sync-sidecar.ps1      # PyInstaller onedir + copy into src-tauri/binaries
    cd app\src-tauri && cargo tauri build       # NSIS installer (requires WiX-free NSIS toolchain via tauri cli)

The faster-whisper alignment model is fetched on first preparation/use and cached in
`%APPDATA%\dev.atme.engine\models`. Hugging Face's content-addressed cache validates downloaded
artifacts. Provider setup and the first model preparation require internet access; media work is
offline after the model is cached.

## Environment contract between host and sidecar

| Var | Meaning |
|---|---|
| ATME_PORT | loopback port the sidecar binds |
| ATME_TOKEN | bearer token for every non-healthz route |
| ATME_FFMPEG | optional explicit ffmpeg path (else bundled/PATH) |
| ATME_DATA_DIR | per-user jobs, settings, and artifacts root (set by Tauri) |
| ATME_MODEL_DIR | faster-whisper cache root (set by Tauri) |
| ATME_MIN_FREE_GB / ATME_MAX_MEM_LOAD | guardrail thresholds |

## Interactive desktop run (M3+)

    # terminal 1 - sidecar on a fixed port for dev
    sidecar\.venv\Scripts\python -m atme.server --port 5175 --token dev-token
    # terminal 2 - UI with live reload
    cd app && pnpm exec vite dev
    # terminal 3 (optional native shell)
    cd app && pnpm exec tauri dev

## Installer build (M4)

    powershell -File app\sync-sidecar.ps1     # refresh bundled sidecar first
    cd app && pnpm exec vite build
    cd app && pnpm exec tauri build
    # artifacts: app\src-tauri\target\release\bundle\nsis\*.exe

The PyInstaller sidecar uses `onedir`; the Tauri resource map must include the complete
`sidecar-dist\atme-sidecar\_internal` directory. Bundling only `atme-sidecar.exe` creates an
installer that cannot start on a clean machine.
