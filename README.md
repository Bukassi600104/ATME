<img src="app/src-tauri/icons/icon.png" alt="ATME logo" width="80">

# ATME — Autonomous Technical Media Engine

ATME is a local-first Windows desktop studio for narration-led, hand-drawn-style explainer videos. An external AI client authors the creative material; ATME retains the original recording, manages revisions, validates production contracts, and previews and renders locally.

The original Caleb-derived **Paper & Ink** workflow remains part of the engine. The ongoing visual pipeline rebuild adds authored geometry, animation, hierarchy and editing primitives while preserving that behavior.

**Development status:** this repository publishes work in progress, not an accepted production release. Implemented primitives and bounded passing regressions do not establish end-to-end release readiness. Split Task 10 cross-matrix verification is ongoing; native reliability, public v2 admission, installed application and human acceptance gates remain open. The [Phase 3 ledger](docs/ATME_VISUAL_PIPELINE_PHASE_3_LEDGER.md) is the current completion authority. Source publication does not close those gates.

## Production workflow

1. Create a project and supply an original recording: PCM WAV audio or supported MP4, MOV, MKV or WebM video. Script-based projects also use an externally authored script.
2. Connect a trusted external AI client through local MCP to author the script or derived scene index, storyboard and layout. Script-based projects require explicit approval of the exact script revision. In recording-only projects, the recording remains both narrative and timing authority; a derived transcript never replaces it.
3. Review renderer-backed frames, sources and assets. Request a focused revision against a selected timeline range, then accept or reject the proposal locally.
4. Validate and render the saved revision from immutable inputs. Source edits retain the original media; derived caches can be rebuilt. The engine supports authored 16:9 and 9:16 profiles.

ATME requires no internal LLM or mandatory AI provider API keys. Creative authorship belongs to the connected external client, whose account or subscription is separate. Local speech processing supplies technical timing rather than semantic authorship. First timing-model preparation needs internet access; timing and deterministic rendering can operate offline after the model is cached. Optional TypeSafe Jev decisions are advisory and are not required for editing or rendering.

See [external production contracts](docs/EXTERNAL_PRODUCTION.md) and the [client-specific MCP connection guide](docs/MCP_CONNECTION.md). Local MCP requires a client with working local stdio support and the correct executable and project store. Check configuration for your actual client; ordinary ChatGPT access does not by itself establish a local ATME connection.

## Architecture

| Location | Responsibility |
|---|---|
| [app](app/) | Tauri 2 / Rust Windows host and vanilla TypeScript / Vite studio |
| [sidecar](sidecar/) | Python 3.12+, Pydantic contracts, FastAPI loopback service, MCP adapter and SQLite project storage |
| [renderer](sidecar/src/atme/render/) | Deterministic scene evaluation, SVG/resvg rasterization and FFmpeg video output |
| [schemas](schemas/) | Versioned JSON contracts and examples |
| [production-assets](production-assets/) | Paper & Ink artwork, fonts and style bundles |
| [sidecar/tests](sidecar/tests/) and [bench](bench/) | Regression coverage, native evidence and calibration tools |
| [docs](docs/) | Approved plans, acceptance requirements, evidence and operational guidance |

The desktop starts an authenticated loopback sidecar. External clients use the stdio MCP adapter; project writes are revision-bound and creative artifacts are versioned immutably. Rendering consumes the saved inputs rather than asking an internal model to invent missing creative decisions.

## Developer setup

Use Windows, Python 3.12, Node.js and pnpm, Rust with the Windows MSVC build tools, WebView2, and FFmpeg on `PATH`. The [runbook](docs/RUNBOOK.md) records the development environment and native packaging details. Source checks do not constitute installed application acceptance.

From the repository root in PowerShell:

```powershell
py -3.12 -m venv sidecar\.venv
.\sidecar\.venv\Scripts\python.exe -m pip install -e "./sidecar[dev,audio,align,tts,render]"
Set-Location app
pnpm install --frozen-lockfile
pnpm check
pnpm build
```

`pnpm dev` starts the Vite frontend on port 5173; the full studio also needs its Tauri host and sidecar. Follow the runbook for native startup and packaging, including PyInstaller and the complete bundled sidecar runtime.

For a bounded Python check, run from the repository root:

```powershell
Set-Location sidecar
.\.venv\Scripts\python.exe -m pytest tests/test_contracts.py -q
```

Select additional checks for changed behavior using [CONTRIBUTING.md](CONTRIBUTING.md). Native renderer suites can be lengthy and need their dependencies and fixtures; a partial run is not a passed acceptance gate.

## Project documentation

- [Source publication](docs/SOURCE_PUBLICATION.md): source identities and maintainer recovery backup; publication does not establish release acceptance.
- [Phase 3 ledger](docs/ATME_VISUAL_PIPELINE_PHASE_3_LEDGER.md): current status, fixed scope, outstanding blockers and evidence.
- [Visual pipeline rebuild](docs/ATME_VISUAL_PIPELINE_REBUILD.md) and [remaining matrix](docs/ATME_VISUAL_PIPELINE_PHASE_3_REMAINING_MATRIX.md): approved implementation and acceptance requirements.
- [Split progress](docs/ATME_VISUAL_PIPELINE_PHASE_3_SPLIT_PROGRESS.md): detailed checkpoint history for the active work.
- [Master execution blueprint](docs/ATME_MASTER_EXECUTION_BLUEPRINT.md): approved historical handoff and wider context; read current status in the ledger.
- [Runbook](docs/RUNBOOK.md), [MCP guide](docs/MCP_CONNECTION.md) and [production contracts](docs/EXTERNAL_PRODUCTION.md): development, client integration and project authority rules.
- [V4 migration](docs/ATME_V4_MIGRATION.md), [V4 progress](docs/ATME_V4_PROGRESS.md) and [original project plan](PROJECT_PLAN.md): historical plans and evidence, not substitutes for the current ledger.

## Contributing and licensing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before changing contracts, rendering behavior or acceptance evidence. Include reproducible steps and redacted logs when reporting a bug.

No project-wide license is currently declared. Bundled third-party notices apply to their respective assets, including the font notices under [Paper & Ink assets](production-assets/paper-ink-v2/). Publication alone does not declare a project license.
