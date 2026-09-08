# ATME — Autonomous Technical Media Engine: End-to-End Build Plan

A production Windows desktop application that turns a topic into a fully rendered, hand-drawn-style technical explainer video (research → script → diagrams → voiceover → synced stroke animation → MP4), modeled on the "Caleb Writes Code" format defined in the two workspace documents. Not a demo: resumable, provider-agnostic, installable, and sized honestly for THIS machine.

---

## 1. Measured Machine Envelope (ground truth for every decision)

| Component | Measured | Consequence |
|---|---|---|
| CPU | Intel Core i3-7100U, 2 cores / 4 threads, 2.4 GHz (Kaby Lake, 15 W) | Bottom-tier for ML inference. All local model work must use int8-quantized, CPU-first models. Expect slower-than-real-time TTS; renders take 30–120 min per video. One media worker at a time, ever. |
| RAM | 16 GB total (~4 GB free under normal load) | Enough if models stay small and load once. Add a commit-charge guardrail that pauses jobs before OOM. |
| GPU | Intel HD 620 (no CUDA / no usable compute) | Confirms the documents' CPU-only mandate; ignore GPU acceleration entirely. |
| Disk | 1 TB HGST 5400 RPM HDD, 523 GB free | **Never write frame sequences to disk.** Stream frames to FFmpeg over stdio. Keep models resident in a long-lived process (loading from HDD each run would waste minutes). |
| OS / thermals | Windows 11 Pro (21H2) | Sustained AVX load on a 15 W chip throttles → checkpoint renders in segments so any interruption costs ≤ 1 segment. |
| Toolchain | Python 3.12.10, Node 24, pnpm 11.7, Rust 1.96 + cargo, Git, FFmpeg 8.1 full — ALL PRESENT | No prerequisite installs needed beyond project deps. |

## 2. Goal & Success Criteria (definition of done)

**Goal:** Type a technical topic in the app GUI → walk away → receive a polished H.264 MP4 with word-synced whiteboard animation, entirely automated; cloud used *only* for LLM API calls during the cognitive phase.

Done means all of:
1. **End-to-end autonomy:** topic → 5–10 min video; the script-review human gate ships ON by default (accuracy-first) and can be switched off for fully unattended runs.
2. **Resumability:** kill the app or lose power mid-pipeline; relaunch resumes from last checkpoint (per-stage AND mid-render segments).
3. **Provider freedom:** switch LLM providers (DeepSeek / Gemini / Groq / OpenAI-compatible local vLLM) from Settings without code changes (LiteLLM routing).
4. **Two voice paths:** bundled local TTS **and** uploaded human voiceover (MP3/WAV), both flowing through the same polish → align → render chain.
5. **Clean lifecycle:** closing the app leaves no orphan Python processes; uninstall/reinstall works.
6. **Verified quality gates:** adversarial fact verification with dual-sourced quantitative claims (≥2 independent citations each), JSON-schema validation on every agent output, collision-free layouts, loudness-normalized audio (-16 LUFS ±1).
7. **Runs acceptably on this PC:** published performance budgets met (§6).
8. **Authored interface:** the UI conforms to the §S1 design language (anti-pattern ban list enforced), fully keyboard-operable, AA contrast.

## 3. Architecture Overview (per Document #1, refined for this hardware)

+--------------------------------------------------------------------------+
|                          Tauri v2 Desktop App                            |
|  WebView2 GUI (HTML/JS): New Job - Pipeline Monitor - Script Review -    |
|  Artifact Library - Provider & Key Settings - Audio Upload               |
|  Rust backend: job orchestration state machine - SQLite - event bus -    |
|  key vault (DPAPI) - sidecar lifecycle supervisor                        |
+---------------------+---------------------------------------^------------+
                      | loopback HTTP + SSE          |
                      | (ephemeral port, token)      |
+---------------------v-------------------------------+--------------------+
|        Python Sidecar (PyInstaller onedir, long-lived)                   |
|  Cognitive (online): litellm router -> Research Agent -> Verifier ->     |
|                      Scriptwriter Agent -> Spatial/Layout Agent          |
|  Media (offline):    Kokoro-82M TTS / VO ingest -> noisereduce ->        |
|                      VAD silence-slice -> pedalboard -> faster-whisper   |
|                      align -> Layered SVG Animator -> FFmpeg (stdio)     |
+--------------------------------------------------------------------------+

**Deliberate refinements vs. the document (rationale recorded so they aren't relitigated later):**
- **LiteLLM as an SDK inside the sidecar**, not a separate proxy server process — saves a process and ~200 MB RAM on a 16 GB machine; identical multi-provider routing.
- **Custom "Layered SVG Animator" replaces full Manim** as the render engine. It implements exactly the technique the spec names (Excalidraw JSON → SVG paths → stroke-dasharray/dashoffset draw-on keyed to word timestamps → camera pans), but composites in layers: static elements are cached rasters; only the currently-drawing stroke re-rasterizes each frame. Full Manim re-rasterizes scenes and is too slow/opaque for a 2-core CPU; the renderer interface stays pluggable so Manim can be swapped in later if ever needed.
- **Alignment order fixed:** silence-slicing shifts timestamps, so faster-whisper alignment runs on the FINAL polished audio track (the doc's described order would desync).
- **Defaults tuned down:** 1280×720 @ 30 fps default output ("Final 1080p" as an explicit overnight option), 24 fps alternative.

## 4. Repository Layout & Tech Stack

Movie engine/
├─ app/            Tauri v2 (Rust src-tauri/, web frontend)
├─ sidecar/        Python package "atme" (uv-managed, py3.12, ruff+mypy)
│   ├─ gateway/    litellm router, model roles, schema-constrained completion
│   ├─ agents/     research, verifier, scriptwriter, spatial
│   ├─ audio/      tts_kokoro, ingest_vo, polish, align
│   ├─ render/     excalidraw parser, svg builder, layered animator, camera
│   ├─ assemble/   ffmpeg muxer
│   ├─ server/     loopback FastAPI app + SSE progress + shutdown hooks
│   └─ store/      pydantic contracts, SQLite access
├─ schemas/        Versioned JSON Schemas: fact-sheet, script-scenes, excalidraw-layout, cue-timeline
├─ prompts/        Versioned persona constitution + per-agent system prompts (from Document #2 analysis)
├─ tests/          unit + golden-file + offline-fixture integration + soak
└─ docs/           ADRs, performance-calibration results, runbook

Stack: **Tauri v2 + Rust** (shell/orchestration), **vanilla TS frontend** (keep bundle light), **Python sidecar** (all media/ML), **SQLite** (job state), **FFmpeg 8.1** bundled, models fetched on first run with SHA-256 verification.

## 5. Subsystem Implementation Plan

### S1 — App Shell & UI/UX (Tauri v2)

**Design intent — "The Drafting Table": an instrument, not a website.** The product's entire output is hand-inked whiteboard explanation, so the interface borrows the drafting metaphor restrained to structure and motion — never cartoonish. One idea carries everything: precision-tool credibility, the same trait the target channel projects. Hairline construction rules instead of card shadows, progress rendered literally as ink strokes being drawn, monospace telemetry, warm-paper light theme and graphite dark theme. Simple to look at, advanced underneath.

**Design language (implemented as CSS custom-property tokens in one tokens.css):**
- Type: **IBM Plex Sans** (UI) + **IBM Plex Mono** (every datum: timings, logs, hashes, sizes, percentages) — bundled locally, zero runtime font fetches. Sentence-case microcopy written the way a senior engineer writes: "Rendering segment 14/22 — 61%", never "Magic happening…".
- Palette "Paper & Ink" (default light): warm paper #FAF9F5, ink #191917, hairline #E6E3DB; "Graphite" dark theme: #15171B ground. Exactly ONE accent — marker orange #E8590C — used strictly semantically (active stage, primary action). State colors only beyond it: done green #2F9E44, attention amber, failure signal red. No other hues anywhere.
- Surfaces: flat, separated by 1px hairlines and whitespace. **Zero gradients, zero glassmorphism, zero drop-shadow cards, max 4px radius.** Depth comes from alignment and rhythm, not effects.
- Icons: one curated 1.5px-stroke geometric set (~24 glyphs). **No emoji anywhere in the product.**
- Motion: purposeful and rare — 120–220 ms ease-out; honors Windows reduced-motion. Signature motion is the **stroke-draw**: the wordmark and stage progress ink themselves on.
- Signature element — **the Run Line**: the pipeline renders as one continuous horizontal stroke across the top of the Run view. Completed stages are solid ink; the active stage animates as a self-drawing stroke with mono percentage; a failure appears as a red double-underline at the break with a Resume affordance; after a crash, unfinished segments show as faint pencil guides — "resumable here" communicated at a glance.

**Five destinations, nothing more:**
1. **Compose** (new job): one focused surface — oversized topic prompt ("What are we explaining?"), an inline chip row (voice: Kokoro voices / uploaded VO, quality preset, provider profile), one primary button Start run. Advanced knobs (duration target, silence thresholds, model-role overrides) collapse under "Fine-tuning" — progressive disclosure, no multi-step wizard.
2. **Run** (monitor): Run Line on top; split below — left: current stage detail (artifact sizes, verifier round count, claims accepted/dropped); right: quiet monospace event log with autoscroll. Footer: elapsed, ETA interpolated from the M0 calibration curves, live token/cost meter. Pause/Cancel as quiet text buttons.
3. **Review** (script gate): manuscript-style two-pane — editable narration left; right column previews each scene as its ACTUAL static SVG sketch, produced by reusing the sidecar's Excalidraw-to-SVG builder over loopback (no duplicate renderer — the UI shows precisely what will be drawn). Clicking a sketch highlights its spoken span; flagged low-confidence words and cite-or-cut drops surface as margin notes. Actions: Approve & continue / Edit & approve.
4. **Library**: editorial rows (16:9 thumbnail, title, duration · date · size · cost), hover-revealed actions (open, reveal folder, delete, export run report). No uniform card grid.
5. **Settings**: dense, honest forms. Providers & Keys styled like a validated config file (status dot + last-checked per key); Model Roles as a 4-row matrix (reasoner / researcher / writer / layouter → endpoint) that warns when researcher lacks web grounding; quality/audio threshold controls captioned with their calibrated time cost on THIS machine ("1080p ≈ overnight").

Chrome & interaction: slim custom title strip (app mark + current-job status pill; native Windows window controls kept). Command palette (Ctrl+K) for power actions; keyboard map: Ctrl+N compose, Space pause/resume, F copy artifact path. Visible focus rings, WCAG-AA contrast, font scaling respected.

**Explicit anti-"AI-generated" ban list, enforced at design review:** no purple/blue gradients, no glass blur, no emoji icons, no Inter-by-default look, no tiled stat-card dashboards, no rounded-everything, no sparkle metaphors, no marketing copy inside the product. Character comes from typography, the Run Line, genuine telemetry density, and dry precise copy — the devtools lineage (Linear / VS Code), not the SaaS-admin template.

**Frontend implementation (deliberately small):** vanilla TS modules + tokens.css; the only bespoke components are the Run Line (SVG), the log console, and the sketch preview pane — everything else is typographic layout. No UI framework, no CSS framework: fewer dependencies, instant cold start on HDD, easier to keep coherent.

Rust responsibilities (unchanged): spawn/supervise sidecar (health checks, restart w/ backoff, graceful shutdown then PID-targeted kill on window close — the documented zombie-process fix); SQLite job store; event fan-out to webview; DPAPI-backed key storage (keyring crate); Tauri capabilities allowlisting ONLY the exact sidecar binary (shell:allow-spawn).

### S2 — Orchestration Harness (the heart)
Stage state machine per job: created → researched → verified → scripted → reviewed(human gate, ON by default; disable for unattended runs) → laid_out → voiced → polished → aligned → rendered(segmented) → assembled → done, plus failed(stage, reason) and paused.
- SQLite tables: jobs, stages(status, attempt, started, ended), artifacts(path, sha256, bytes), events(log), llm_usage(tokens, cost).
- Every stage: idempotent, takes versioned inputs from prior artifacts, writes its artifact + hash before marking done → crash-safe resume.
- Render stage subdivides into N segments (60 s of timeline each) with per-segment checkpoint files on the HDD (cheap: one small file each, no frame dumps).
- Watchdogs: orphan-PID sweep at app start; disk-space preflight (>10 GB free required); commit-charge guardrail (pause >85% RAM).

### S3 — Sidecar Contract
Loopback-only HTTP (127.0.0.1, ephemeral port, bearer token passed via env by Rust): POST /jobs/stage, GET /progress (SSE), GET /healthz, POST /shutdown. All payloads are the versioned pydantic/JSON-Schema contracts in schemas/. Media stages execute strictly serially through one worker queue (this CPU cannot parallelize them productively).

### S4 — LLM Gateway (LiteLLM SDK)
Model **roles**, not hardcoded models — user maps roles to any provider in Settings: reasoner (verification/layout arbitration), researcher (query expansion/extraction; MUST map to a web-grounded model — Settings validates and warns otherwise), writer (script), layouter (tool-calling for geometry). Every call: JSON-schema-constrained output, temperature caps per role, retry ladder (validate → repair-prompt retry ×3 → escalate role to stronger model → fail stage cleanly), full token/cost ledger per job.

### S5 — Research Agent (+ adversarial Verifier) — ACCURACY-FIRST
Retrieval is performed by **web-grounded LLM endpoints routed through LiteLLM** (e.g., Perplexity Sonar models, Gemini with Google Search grounding, or any OpenAI-compatible endpoint exposing web search) — **no separate search-provider API key is ever required**; the user's existing LLM keys cover it. Pipeline: query expansion → multi-angle retrieval passes → source-aware extraction, supplemented by free keyless direct fetches (arXiv API, official docs URLs cited by the grounded model) so every citation resolves to full text stored raw (text + URL + date) in the job store. Output: **claim-level fact sheet in which every quantitative claim carries at least two independent citations.**
Verifier hardening (accuracy over speed): an isolated reasoner-role instance cross-examines every claim against its retrieved sources; numerals must match sources exactly; any detected contradiction forces re-retrieval of that claim; the verification loop is capped at 5 rounds; anything still unresolved is DROPPED (cite-or-cut) and listed in the job report so nothing unsourced ever reaches narration.
Efficiency guards (efficiency ≠ speed-cutting: eliminate wasted work, spend what accuracy needs): query deduplication across passes, a per-topic research cache reused across jobs, batched extraction calls, and a hard token-budget ceiling per stage so verification loops cannot run away. Internet is required only in this phase.

### S6 — Scriptwriter Agent
Persona "constitution" distilled from Document #2 codified in prompts/: information-density targets, banned hype vocabulary, systems-engineering framing (trilemmas, bottlenecks, trade-offs), Hook → Context → Architecture → Conclusion structure, spoken-text pacing ~150 wpm. Output: scenes[] JSON — spoken_text, visual_directive written in a constrained directive grammar (box/text/arrow/label/highlight/camera verbs only — this grammar is what makes Phase II reliable). A deterministic style-lint pass (word counts per beat, jargon density, directive grammar conformance) precedes LLM self-review.

### S7 — Spatial/Layout Agent
Tool-schema-constrained calls emitting element placements; all coordinates snapped to the 50 px grid; deterministic seeded generation (same input → same diagram). Local geometric post-pass: bounding-box overlap detection with automatic repair (nudge/resize within grid) and bounded LLM repair round if unsolvable. Also emits the **camera plan** (focus boxes per beat → pan/zoom easing curve) and the per-scene cue timeline skeleton.

### S8 — Audio Engine
Path A — local TTS: **Kokoro-82M ONNX int8**, model kept warm in the sidecar, strict request queue, SHA-256 phrase cache across jobs (huge win: repeated phrases skip synthesis entirely on this CPU).
Path B — human VO upload (MP3/WAV), waveform-validated.
Shared polish chain: noisereduce (spectral gating) → Silero-VAD silence slicing (configurable: e.g. cuts >100 ms below −30 dBFS) → pedalboard (compressor → noise gate → limiter) → loudness normalize −16 LUFS. Output: final WAV + the edit-decision list mapping original↔final timeline (feeds §S9 and subtitles).

### S9 — Alignment Engine
faster-whisper base.en int8 (tiny.en fallback if calibration says so) with vad_filter=True, word-level timestamps computed on the FINAL audio; confidence gate flags low-confidence words for optional manual correction in Script Review; output cue_timeline.json: word → ms range → owning scene → visual directive trigger points.

### S10 — Layered SVG Animator (render engine)
Parse Excalidraw JSON → SVG paths with roughness perturbation (seeded RNG). Frame loop: composite = cached static-layer bitmap + active-stroke overlay rasterized via dashoffset interpolation at the timestamp dictated by cue_timeline; camera transform applied at composite time. Frames piped PNG → FFmpeg stdin (image2pipe) — zero temp image files on the HDD. Segment renderer emits seg_XX.mp4 checkpoint files.

### S11 — Assembly
Concat segments → mux polished audio → H.264 (**CRF 21, preset superfast** — measured on this CPU: 66.4 fps @720p30 vs 23.2 fps at 'fast', so encoding is never the bottleneck; docs/CALIBRATION.md), AAC 160k, +faststart; thumbnail from a chosen beat; chapters from scenes; final artifact hash + size logged; Library entry created.

### S12 — Packaging & Installer
PyInstaller **onedir** sidecar (faster cold start than one-file on HDD, avoids bootloader/child double-extract); Tauri NSIS installer bundling FFmpeg binary + sidecar; models (Kokoro int8 ~90 MB, whisper base.en int8 ~80 MB, Silero ~2 MB) downloaded on first run with checksum verification; unsigned-binary SmartScreen note documented for v1.

### S13 — Skills/Plugins (post-core)
Manifest-defined Python skills (scrapers, arXiv fetchers, codebase parsers) installed at runtime, registered as tools mapped through the LiteLLM router; sandboxed to a plugin directory; capability-gated. Built only after M4 ships.

## 6. Performance Engineering for THIS Machine

**M0 Calibration Harness (built first, runs on your PC, numbers recorded in docs/)** measures real rates: Kokoro int8 words/sec, whisper base/tiny alignment RTF, polish-chain minutes per minute-of-audio, animator frames/sec at 720p and 1080p, end-to-end wall clock for a fixed 3-min fixture. **All defaults below are provisional until M0 confirms or tightens them.**

| Stage (8-min video) | Budget on i3-7100U | Mitigation if exceeded |
|---|---|---|
| Research + script (online) | 8–20 min — accuracy mode: multi-pass retrieval + up-to-5-round verification | n/a |
| TTS (Kokoro int8) | 10–25 min | phrase cache; Piper fallback engine; recommend VO upload |
| Polish + align | 5–12 min | tiny.en model |
| Render 720p30 | 45–90 min segmented | layer-cache hit-rate tuning; 24 fps mode |
| Render 1080p30 | 2–4 h — "overnight" preset only | documented, opt-in |
| RAM ceiling | sidecar ≤ 3.5 GB steady-state | guardrail pause; smaller whisper model |

Standing rules: one media job at a time; serial stage execution; models never reloaded mid-job; caches for TTS phrases and rendered static layers; everything checkpointed against power loss/throttling.

## 7. Milestones (risk-first; each exits with something runnable)

- **M0 — Scaffold + Calibration (first!)**: repo layout, contracts/schemas v1, test runner, calibration harness producing the real numbers table. Exit: measured budgets replace estimates; renderer/TTS approach confirmed feasible. Kill-switch checkpoint: if Kokoro RTF > 3× real-time or render < 4 fps at 720p, pivot defaults to VO-upload-first + 720p24 before building more.
- **M1 — Offline media spine**: fixture script JSON → TTS/upload → polish → align → render → MP4 via sidecar CLI. Exit: 3-min fixture video, word-synced drawing, plays correctly, timings logged.
- **M2 — Cognitive phase**: LiteLLM gateway, research+verifier, scriptwriter+linter, spatial agent+collision repair. Exit: topic → validated script + collision-free layout JSON on 3 test topics across 2 different providers; verification audit shows ≥90% of quantitative claims dual-sourced and ZERO uncited numeric claims reaching scripts.
- **M3 — Orchestrator + App shell**: Tauri GUI wired to full state machine, SQLite persistence, SSE monitor, script-review gate, settings/key vault, resume-from-every-stage incl. mid-render kill test. Exit: unattended topic→MP4 through the GUI; crash-resume demonstrated at 3 random points; UI passes the §S1 design review (tokens, Run Line behavior, anti-pattern ban list, keyboard map).
- **M4 — Productionization**: PyInstaller onedir + NSIS installer, first-run model fetcher, zombie-watchdog, disk/RAM guardrails, logging/cost reports. Exit: clean install under a fresh Windows user profile, full video produced, zero orphan processes.
- **M5 — Hardening + skills**: soak tests (3 consecutive full videos), failure-mode suite (bad API key, internet drop at each online stage, corrupted upload, disk-full simulation), plugin manifest + 2 sample skills, docs/runbook. Exit: acceptance checklist §2 fully green.

## 8. Testing & QA Strategy
Unit tests per module (geometry snapping, EDL math, dashoffset timing, LUFS normalization); golden-file schema tests for every agent contract; **offline integration fixtures** (recorded LLM responses) so the whole pipeline is regression-testable without internet/API spend; fault-injection harness (kill sidecar at random offsets ×50); visual QA checklist (grid alignment, no overlaps, sync tolerance ±40 ms verified programmatically against cue timeline); performance regression gate comparing against M0 baselines.

## 9. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| TTS too slow on 2 cores | M0 kill-switch; Piper fallback; VO-upload-first UX; aggressive phrase cache |
| Render throughput too low | Layer-cached compositor; 720p default; 24 fps mode; segment resume |
| LLM outputs violate schemas | Schema-constrained calls + repair ladder + deterministic linters; stages fail loudly, never silently |
| Hallucinated facts | Adversarial verifier, cite-or-cut, source ledger retained with job |
| Whisper hallucination/desync | VAD pre-filter, align on FINAL audio, confidence gating + manual correction |
| Throttle/power-loss mid-render | 60 s segment checkpoints; resume semantics tested in fault suite |
| Memory pressure (16 GB, heavy baseline) | Warm-but-small models, ≤3.5 GB sidecar budget, commit-charge guardrail |
| HDD latency | Stdio frame streaming (no temp frames), onedir packaging, minimal small writes |

## 10. Assumptions
English-language content; you hold at least one LLM API key (any provider); single concurrent media job is acceptable on this hardware; v1 ships unsigned (SmartScreen "More info → Run anyway"). No separate search-provider key is required at any point — research relies solely on web-grounded LLM endpoints reachable through the user's normal LiteLLM provider keys.