# ATME — Autonomous Technical Media Engine

Local-first Windows desktop application for hand-drawn-style explainer production.
The approved no-key workflow imports externally authored scripts and production layouts,
then handles review, original voiceover, alignment, animation and MP4 rendering locally.
The desktop and connected AI share a revisioned local project database. Use the
production audit and live-test plan to see which workflows have been verified in a Windows build.

- [Production audit, open work and live-test plan](docs/PRODUCTION_READINESS.md)
- [Project-service architecture](docs/ATME_V4_MIGRATION.md)
- [Project-service implementation history](docs/ATME_V4_PROGRESS.md)
- Development MCP connection: [local setup and supported tools](docs/MCP_CONNECTION.md)
- Renderer verification evidence: [research progress](docs/ATME_V2_PROGRESS.md)
- Architecture decisions: docs/ADR-*.md
- Measured performance envelope: docs/CALIBRATION.md (filled by bench/calibrate.py)
- Contracts: schemas/*.schema.json (versioned; consumed by agents, renderer, UI)

## Repository layout

    app/        Tauri v2 desktop shell (Rust backend + web frontend)        [M3]
    sidecar/    Python package "atme": projects, MCP, audio timing, render, server
    schemas/    Versioned JSON Schemas + valid examples (contract tests bind us)
    prompts/    Persona constitution + per-agent system prompts               [M2]
    bench/      Calibration harness (M0 kill-switch gate)
    tests/      Cross-cutting integration/soak fixtures                       [M1+]
    docs/       ADRs, calibration results, runbook

## Current production workflow

1. Open or create a project in the desktop studio and add an original PCM WAV narration or
   MP4/MOV/MKV/WebM source video. Follow [external production contracts](docs/EXTERNAL_PRODUCTION.md).
2. Let a trusted connected AI author the script/derived scene index, storyboard and layout through
   local MCP. Script-based projects require explicit approval of the external script; recording-only
   projects do not, because the recording remains both narrative and timing authority.
3. Review renderer-backed frames in the central viewer, inspect sources and assets, and select clips
   or an exact timeline range. Focused revisions can be requested from the connected AI and remain
   proposals until the user accepts them.
4. Use local editing only for targeted timing or script corrections. It is a secondary override,
   not a second creative-authoring workflow.
5. Resolve deterministic validation issues and render the exact saved revision locally. Both 16:9
   long-form and 9:16 short-form use the same studio workspace and Caleb-derived renderer.

Legacy credentials/history are retained, but the interface neither requests keys nor
creates paid-provider jobs. The fake provider remains an offline test fixture only.
External AI subscriptions are separate. AI Connection supports ChatGPT Desktop, Codex and Claude
Desktop and exposes verified local MCP configuration. Optional TypeSafe Jev decisions use a key
passed by the AI client's MCP environment and are never required for editing or rendering. The connection
indicator reflects a live authenticated desktop bridge, not shared-database activity. Advanced configuration
does not invent a client identity or connection count when the client has not reported one.

## Build and verification

See [docs/RUNBOOK.md](docs/RUNBOOK.md) for development, sidecar, installer, and clean-start
verification commands. Set `ATME_DATA_DIR` to an absolute directory to run the desktop with a
separate project store for testing. The installed desktop otherwise uses its configured data
directory. The renderer research and original milestone documents retain their historical results.
