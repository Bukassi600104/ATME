# ATME — Autonomous Technical Media Engine

Local-first Windows desktop application that turns a technical topic into a fully rendered,
hand-drawn-style explainer video (research -> script -> diagrams -> voiceover -> synced stroke
animation -> MP4). Cloud is used ONLY for LLM API calls during the cognitive phase; all media
work happens offline on CPU.

- Current approved sequence: [ATME V2 research-first plan](docs/ATME_V2_REFACTOR_PLAN.md)
- Verified implementation status: [V2 progress](docs/ATME_V2_PROGRESS.md)
- Historical milestone plan: PROJECT_PLAN.md (retained; V2 sequencing takes precedence)
- Architecture decisions: docs/ADR-*.md
- Measured performance envelope: docs/CALIBRATION.md (filled by bench/calibrate.py)
- Contracts: schemas/*.schema.json (versioned; consumed by agents, renderer, UI)

## Repository layout

    app/        Tauri v2 desktop shell (Rust backend + web frontend)        [M3]
    sidecar/    Python package "atme": agents, gateway, audio, render, server
    schemas/    Versioned JSON Schemas + valid examples (contract tests bind us)
    prompts/    Persona constitution + per-agent system prompts               [M2]
    bench/      Calibration harness (M0 kill-switch gate)
    tests/      Cross-cutting integration/soak fixtures                       [M1+]
    docs/       ADRs, calibration results, runbook

## Current production workflow

1. Open Settings and map researcher, verifier, writer, and spatial-director roles to LiteLLM
   model identifiers. The researcher must be a web-grounded endpoint. Keys are encrypted with
   Windows DPAPI and are never returned by the sidecar API.
2. Compose a topic, choose the target duration and quality, and keep script review enabled for
   the accuracy-first path.
3. Review the generated narration beside renderer-produced sketch previews.
4. Upload one continuous original WAV, MP3, M4A, AAC, or FLAC voiceover. ATME validates levels,
   decodes to its canonical track, aligns every spoken word, and rejects recordings that do not
   sufficiently match the approved script.
5. Rendering is checkpointed in 60-second segments. Interrupted jobs resume from persisted
   stage and segment state after restart; pause, resume, and cancel operate at safe checkpoints.
6. Open the completed MP4 from Library. The library retains duration, file size, date, status,
   and recorded provider cost.

The deterministic fake provider remains compiled solely for offline regression tests. The
desktop interface creates production LiteLLM jobs only.

## Build and verification

See [docs/RUNBOOK.md](docs/RUNBOOK.md) for development, sidecar, installer, and clean-start
verification commands. Current V2 acceptance gates are in docs/ATME_V2_REFACTOR_PLAN.md;
PROJECT_PLAN.md retains the historical milestone definitions.
