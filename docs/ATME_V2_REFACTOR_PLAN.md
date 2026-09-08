# ATME V2 repository audit and production refactor plan

Date: 2026-09-06
Status: Approved by the user; research-first implementation in progress. See `ATME_V2_PROGRESS.md` for verified results and remaining gates.
Scope: First implement and demonstrate the Caleb Writes Code production grammar discovered through the browser-extension research in the existing engine. Then refactor that proven engine into an externally AI-directed, editable production studio.

User correction incorporated: research-derived video behavior must be implemented before the broader architecture refactor. The phase order below supersedes the initial architecture-first draft.

## Approved decision

The user approved the research-first implementation sequence and release scope below. Work begins with Phase 0 baseline protection, then Phases 1-3 implement and demonstrate the researched video behavior. Broader refactoring cannot begin until the Phase 3 video-quality gate is accepted. This does not bypass the script, narrative, storyboard, preview, or revision approvals that the product itself will enforce.

At initial plan authoring, the deliverable was this document only: no implementation, dependency installation, application launch, render, or database migration was performed. That source-level audit was not a runtime certification or exhaustive security review. After approval, baseline verification and narrow renderer implementation began; their current results are recorded separately in `ATME_V2_PROGRESS.md`.

## Inputs and precedence

- User-supplied architecture specification: `C:/Users/USER/Desktop/ATME DOCS/ATME_Production_Architecture_Refactor_Specification_v2.md`.
- Dashboard reference: `C:/Users/USER/Desktop/ATME DOCS/ChatGPT Image Sep 6, 2026, 12_33_14 AM.png`.
- Brand reference: `C:/Users/USER/Desktop/ATME DOCS/ATME LOGO.png`.
- Three research ZIPs in `C:/Users/USER/Desktop/ATME DOCS/`: High Bandwidth Flash correction, Agent Harness full pass, and OpenAI Jalapeno full pass. Their outer checksums and 47 internal hashes were verified during the preceding review. Hash agreement establishes package integrity, not independent verification of video observations.
- Existing source, schemas, tests, ADRs, runbook, calibration log, original project plan, and local forensic skill.

The user's latest research-first sequencing takes precedence over the architecture specification's suggested phase order and conflicting choices in `PROJECT_PLAN.md`. Preserve that document as historical context; after approval, update the documentation index to designate the approved V2 plan and new ADRs as current. Do not silently rewrite the old decisions. The specification remains the destination architecture, not a prerequisite to implementing the observed video mechanics.

## A. Current architecture summary

| Responsibility | Actual implementation | Assessment |
|---|---|---|
| Desktop host | `app/src-tauri/src/main.rs`, Tauri 2, Rust | Spawns and supervises the Python sidecar; exposes connection details and bounded artifact opening. Preserve. |
| Interface | `app/index.html`, `app/src/main.ts`, `app/src/tokens.css` | Vanilla TypeScript/Vite. Compose, run, script review, voice upload, library, provider settings. No production timeline editor found. |
| Application API | `sidecar/src/atme/server/app.py` | Authenticated loopback FastAPI, job routes, review, streamed voice upload, SVG previews, events, model preparation. Mixes transport, SQL, worker scheduling, and business rules. |
| Orchestration | `sidecar/src/atme/orchestrator.py` | Fixed cognitive-to-media sequence, review pause, original-voice wait, stage checkpoints, safe checkpoint controls. Reuse scheduling/recovery concepts; replace mandatory creative stages. |
| Storage | `sidecar/src/atme/store/db.py` | SQLite jobs, stages, artifacts, events, LLM usage. Version-1 initialization and stage-attempt history; not an immutable, versioned editing project model. |
| Contracts | `schemas/`, `sidecar/src/atme/store/contracts.py` | Six JSON schemas including research and visual plans, with typed mirrors for some contracts. Useful foundation; versioning and semantic validation are incomplete across the whole project. |
| Rendering | `sidecar/src/atme/render/` | Custom seeded SVG primitives, resvg rasterization, Pillow composition, FFmpeg output. No React/Remotion runtime found. |
| Media | `sidecar/src/atme/audio/`, `pipeline.py` | Uploaded voice, local draft TTS, cleanup, edit-decision mapping, Whisper timestamps, script reconciliation, muxing. No general source-video compositor or media library found. |
| CLI | `sidecar/src/atme/cli.py` | `run` and `version`, primarily topic/fixture pipeline. Not yet a project integration surface. |
| Packaging | `app/sync-sidecar.ps1`, `sidecar/atme-sidecar.spec`, Tauri config | PyInstaller onedir and Windows NSIS packaging. macOS production packaging is not established. |

The working tree has extensive pre-existing modifications, untracked research/schema work, generated sidecar bundles, and test directories. Some old temporary directories cannot be enumerated under current permissions. Preserve all existing changes. No `AGENTS.md` was found in the searchable workspace. Generated binaries were inventoried as artifacts, not reverse engineered; private runtime settings and unrelated user media were not opened.

## B. Existing production engine

### What is implemented

- `render/svg_builder.py`: seeded rough lines, rectangle/hachure drawing, arrows, labels, and text fading. The current renderable vocabulary is rectangle/text/arrow, not a complete illustration library.
- `render/animator.py`: cached layers of completed drawings, temporary stroke overlays, static-camera frame reuse, and raw RGB frames piped to FFmpeg. This is worth preserving on the target CPU/HDD.
- `render/camera.py`: aspect-fitted viewboxes and smooth interpolation toward focus cues.
- `pipeline.py`: separate polish, alignment, render, and assembly stages; 60-second render segments; final audio mux; artifact hashes.
- `audio/edl.py`: original-to-final time mapping for removed silence. This is an existing starting point for non-destructive media edits.
- `audio/align.py` and `voice_upload.py`: local speech recognition timestamps and matching to scene text. This is not proof of exact forced alignment for every word.
- `store/db.py` and `orchestrator.py`: persisted stage attempts and checkpoint recovery.

Historical calibration in `docs/CALIBRATION.md` reports about 22.5-23.6 baked frames/second for a short cached 720p renderer benchmark, and 13.3-13.7 for a different overlay-heavy pipeline fixture. These are dated measurements of different workloads, not current performance promises. New video layers and richer object state must be benchmarked.

### Gaps that materially affect the refactor

1. `visual_plan.py` produces one beat per scene, preserves all prior objects, automatically reframes after the first beat, and reduces unsupported actions to drawing. The schema accepts more actions than the implementation executes.
2. `pipeline.align_stage()` emits every element directive as `draw`; `_retime_layout()` distributes later elements fractionally through each scene and retimes cameras by scene index. Creative event intent is therefore not carried through fully.
3. `animator.py` caches completed elements indefinitely. Removal, replacement, temporary highlights, restored boards, and changing layers need explicit state evaluation and different cache keys.
4. Drawing durations are currently bounded by 250-800 ms constants; camera interpolation defaults to 600 ms. Retain these for legacy compatibility, not as measured corpus rules.
5. `render/autolayout.py` stacks boxes vertically. The preview endpoint constructs this fallback afresh rather than reading the actual planned layout. Sharing the SVG renderer does not make that preview equivalent to final production.
6. `agents/spatial.py` repairs overlaps by moving objects downward, which can push content out of frame and does not provide time-dependent, caption-aware, speaker-aware collision checking.
7. `render_stage()` accepts an existing segment over 1,000 bytes as reusable. It does not establish that the segment matches the current input version or is fully decodable.
8. `voice_upload.py` replaces previous uploaded project-source copies. V2 must retain original asset versions; new uploads cannot erase prior material needed for undo or old renders.
9. The orchestrator lays out before final voice cleanup and then retimes. V2 should allow early draft planning, but final storyboard approval must depend on the locked edited recording.
10. Project artifacts are often rewritten directly as JSON. SQLite transactions alone do not make the combined database-and-file state crash-safe.
11. Job status can be assigned as an arbitrary string. Review rejection currently cancels a job; the new workflow needs revision requests and enforceable version-specific approval states.
12. The API accepts landscape quality presets only. Aspect fitting in the renderer does not constitute a validated vertical production workflow.
13. There is no implemented timeline patch/undo system, evidence asset pipeline, talking-head track, caption export/mix pipeline, or MCP server in the inspected source.

## C. Caleb reverse-engineering system

### Existing locations

- Root DOCX documents and their `.extracted.txt` companions provide early narrative/style analysis. Preserve as historical research, not automatically verified timing or biographical evidence.
- `prompts/persona.constitution.md`, `writer_system.md`, `spatial_system.md`, `researcher_system.md`, and `verifier_system.md` encode early creative rules.
- `schemas/reference-video-analysis.schema.json`, its example, and `.codex/skills/caleb-video-forensics/` provide a research contract and validation workflow.
- `schemas/visual-plan.schema.json`, its example, `visual_plan.py`, and `test_visual_plan.py` are the current semantic bridge.
- `data/jobs/fixture1`, `topic1`, and existing job folders contain prior layouts, scripts, cues, manifests, and media artifacts. Preserve existing evidence; manifest presence alone is not a successful current regression run.
- Earlier browser-extension packets live outside the repository under `C:/Users/USER/Documents/Codex/2026-09-02/chrome-tabs-the-user-has-the/outputs/`; latest packets and the new specification live under `C:/Users/USER/Desktop/ATME DOCS/`.

### What the latest packets support

| Packet | Usable findings | Limitation |
|---|---|---|
| High Bandwidth Flash addendum | 146 observed minimum events; 13 board activations; visibility intervals; 50 connector IDs; corrected onset uncertainty | 120 onsets remain interval-censored. Dense transitions are a biased sample for general cadence. Attention arrows sometimes use the same semantic endpoint twice. |
| Agent Harness | Reported complete playback coverage; 117 minimum events; 22 boards/26 activations; optional Cursor sponsor around 4:44.3-5:56.7; return to prior timeline | One sponsored sample. Grouped objects average 4.35 over the full sampled video, including sponsor material. This is not a universal editorial density target. |
| OpenAI Jalapeno | 187 minimum events; 17 boards/28 activations; evidence excursions and returns; conceptual opening-to-ending resolution | Continuous audiovisual pass explicitly failed certification. Camera aggregate differs from primary action counts. Density is averaged per activation, unlike time-grid averages elsewhere. |

Proposed style capabilities: persistent board identity, versioned board returns, incremental object changes, temporary pointers, evidence/annotation/return cycles, purposeful cuts and camera movement, and conceptual resolution of the opening question.

Do not promote fixed event intervals, object limits, sponsor duration, SFX rules, or word offsets to corpus defaults. The approximately 175-185 caption-derived editorial WPM observations are guidance for drafting; the user's approved recording controls final timing. Presenter segments, diagram segments, evidence segments, and sponsor segments need separate comparisons.

Research work can continue alongside architecture implementation. Request a targeted Jalapeno continuous-viewing follow-up and metric reconciliation, not a repeat of all studies. Preserve raw ZIPs, checksum manifests, sample provenance, and limitations. Add adapters to a versioned research format rather than rewriting the original packets to fit the current smaller schema. Normalize frame precision, onset windows, settling windows, board activations, visibility intervals, and distinct connector versus attention-pointer roles. A pointer from empty canvas should support a free anchor; it should not require a fake self-loop relationship.

The forensic skill influences this plan by requiring evidence-linked production rules and at least three supporting videos before treating a pattern as a corpus default. This does not block implementing a supported capability or using a clearly labelled provisional setting. Keep ATME's own visual identity and original primitives.

## D. Existing LLM architecture

Active dependencies are `settings.py` (DPAPI role keys), `gateway/router.py` (LiteLLM transport, retry/repair, usage), `agents/`, `cognitive.py`, `_completes_for()` and creative stages in `orchestrator.py`, provider routes and job guards in `server/app.py`, provider UI in `main.ts`/`index.html`, CLI provider flags, the optional gateway dependency in `pyproject.toml`, and bundled imports/resources.

Remove these from normal production only after the external-plan path can render a real accepted project. Extract reusable validation, citation checks, lints, geometric utilities, and diagnostics first. Historical cost records can remain readable without ongoing token accounting. Do not erase encrypted credentials or historical records as a side effect of migration. The fake provider belongs in test support and must not be advertised as a working production AI.

No payment, subscription, credit, or entitlement implementation was found in the inspected application source. There is no corresponding subsystem to remove.

## E. KEEP

| Existing component | Why and boundary |
|---|---|
| Tauri host and local sidecar | Preserve the deployment and local media boundary. Retain exact-child process supervision and bounded artifact access. |
| SVG primitive generation, seeded variation, Paper & Ink output | Useful, deterministic starting vocabulary. Protect current successful renders. |
| Layer/static-frame caching and FFmpeg streaming | Preserve CPU/HDD efficiency while extending cache correctness. |
| Audio decoding, quality reporting, cleanup functions, final-audio alignment order | Reuse behind explicit media versions and cleanup decisions. |
| EDL mapping | Extend into a bidirectional kept-span/timebase model. |
| SQLite, stage attempts, event logs, artifact hashes | Evolve storage rather than replacing it with a new database. |
| Resource resolution, model caching, packaging knowledge, guardrails | Preserve operational work; make Windows assumptions explicit. |
| Existing research, schemas, fixtures, test renders and regression tests | Keep as versioned migration and regression evidence. |

## F. MODIFY

| Files/modules | Proposed modification |
|---|---|
| `store/db.py`, `store/contracts.py` | Add versioned project/artifact records, source authority, approval records, revision history, render jobs and transactional migrations. Separate project readiness from worker status. |
| `orchestrator.py`, `server/app.py` | Introduce a shared application service; make API and scheduling call it. Enforce dependency/version gates and typed commands. |
| `pipeline.py`, `visual_plan.py`, `schemas/` | Add a compiler around the existing layout/cue representations; preserve v1 through an adapter. Execute explicit actions rather than converting everything to drawing. |
| `render/animator.py`, `camera.py`, `svg_builder.py` | Add board state/lifetimes, media layers, supported actions, explicit camera intervals, fonts, asset references and cache invalidation. |
| `render/autolayout.py`, geometric utilities in `agents/spatial.py` | Keep legacy diagnostic fallback; add semantic layouts and time-dependent safe-zone checks. Final preflight blocks unresolved placeholder layouts. |
| `audio/voice_upload.py`, `audio/edl.py`, `audio/polish.py`, `audio/align.py` | Preserve source versions, preview cleanup, maintain audio/video time mapping, offer recorded narration authority, report uncertain alignments. |
| `cli.py` | Add project/capability/schema/validate/preview/render/status/patch operations using the same service as the UI. |
| `app/src/main.ts`, `index.html`, `tokens.css` | Split into focused TS modules; build the reference-inspired project workspace, real preview, inspector and bounded timeline. No framework rewrite planned. |
| `guardrails.py`, `resources.py`, Rust host, packaging scripts | Improve preflight, diagnostics, recovery and OS adapters; preserve a tested Windows release path. |
| README, runbook, ADRs, original plan references | Document actual V2 behavior, integration limits, migration/restore and measured performance. |

## G. REMOVE from the active production path

- Required provider/key setup, internal creative-agent routing, automatic provider repair loops, and current model-selection/cost UI, after the external integration is functional.
- Mandatory research/script generation for projects with an existing authoritative recording or approved script.
- Production use of the fake provider, one-beat-per-scene planning, permanent accumulation, automatic reframing, and unconditional action-to-draw conversion.
- Silent generic-box fallback acceptance and preview generation from unrelated fallback content.
- Replacement/deletion of old uploaded source versions and in-place artifact updates that bypass project versions.
- Size-only segment reuse and downstream approval remaining valid after inputs change.

Removal means staged deactivation and eventual dependency cleanup, not immediate wholesale deletion. Keep history and migration readers. Keep local draft TTS isolated as an optional legacy/testing facility; it is not required for the new original-voice workflow.

## H. ADD

Proposed locations are responsibilities, not a mandatory folder reshuffle:

- `sidecar/src/atme/project/`: project versions, dependencies, approval transitions, preferences and migration adapters.
- `sidecar/src/atme/services/`: project commands shared by desktop API, CLI and integrations.
- `sidecar/src/atme/compiler/`: normalization, validation and deterministic production IR.
- `sidecar/src/atme/integrations/`: a compact MCP adapter and client setup/capability checks.
- `sidecar/src/atme/media/`: asset registry, probe/normalize, proxies, source-video tracks and edit decisions.
- `sidecar/src/atme/style/`: versioned capabilities, semantic primitives, layout rules and research provenance.
- Revision proposals, dependency-aware patches, undo/redo and temporary previews.
- Captions (burn-in, SRT, VTT), supported music/SFX tracks, narration priority and mix controls.
- Structured validation errors and preflight reports; content-addressed caches and render manifests.
- Project portability manifest, explicit relinking and asset provenance.
- Golden production fixtures and focused regression coverage for the new behavior.

### Production contract and runtime decisions

1. Retain JSON Schema plus Python typed models. Version external contracts, project storage, IR, style profiles and renderer independently. Keep v1 readers; never silently coerce unknown versions.
2. Use modular contracts for project/brief, narrative/script, assets/media/EDL, beats/storyboard, boards/activations/objects/connectors, director/composition, animation/timeline/audio/captions, style, patch/revision and render manifest. Avoid repeating one fact as editable truth in multiple documents.
3. Evolve `LayoutDoc` plus `CueTimeline` into a normalized internal composition. Add explicit source timebase, output frame rate, stable IDs, board activations, object lifetime, layer order, action intervals, camera intervals, media references and audio decisions. Legacy adapter reproduces old layout/cue behavior.
4. Evaluate the same compiled composition for preview and export. Proxies may reduce media resolution, never alter timing, crop geometry or event semantics. Cache by input fingerprints, frame range and quality profile.
5. A project has a human production state; each render/analysis task has its own queued/running/paused/failed/completed state. Approval records point to immutable artifact versions. Editing invalidates only affected dependents and exposes stale artifacts clearly.
6. Use original-source time, edited-narrative time and output-frame time explicitly. Keep integer sample/frame indices and rational timebases where necessary; define rounding once. Prevent cumulative segment drift.
7. Recorded narration is timing authority after narrative lock. A scene-length edit either stays inside its available narration range or proposes an explicit media/timeline change. Changing spoken wording cannot silently change an existing recording; request a new take or a reviewed edit.
8. Preserve sources as immutable assets. Write derivatives under new versions. Commit state and referenced artifacts through staged writes with recovery rules; do not rely on a database transaction to atomically cover external files.
9. Patches carry base project version, explicit scope, preconditions, changed IDs, affected dependents and proposed output. Stale patches fail with a repairable conflict. Acceptance is atomic; rejection leaves the accepted project untouched.
10. Board-return dependencies are part of patch scope. An edit to a reused board may affect later activations; expose that impact rather than silently extending a selected-range edit.
11. External AI gets capability/schema discovery, project inputs, revision requests and bounded mutation operations. Start with local stdio MCP and the existing loopback service, plus CLI/import-export fallback. No general shell/filesystem tool is exposed through ATME. Establish client-owned session authentication without printing existing desktop bearer tokens or credentials.
12. Capability discovery reports actual supported primitives, versions, limits, output profiles and media interpretation facilities. It must not advertise planned features. Local clients and remote chat clients have different connectivity; verify one real local client first and document others only after testing. No cloud relay is included in this scope.
13. ATME remains the canonical asset/project store. Clients receive transcripts, metadata, approved derived previews or bounded media access as supported. Raw-media transmission requires the user's chosen workflow and an explicit destination; it is not automatic. Local transcription can remain a media utility without reinstating internal creative-agent routing.
14. Only `LONG_FORM_16_9` and `SHORT_FORM_9_16`. Default long-form 1080p production intent with lower-resolution previews; retain legacy 720p output compatibility. Vertical 1080x1920 is independently composed and validated. Final quality/performance presets are confirmed by benchmarking. 4K and automatic long-to-short extraction are deferred.
15. Freeze fonts, assets, seeds, style and runtime versions in the render manifest. Target reproducible composition and decoded visual/audio results in a pinned environment, not byte-identical encoded MP4 across different machines.
16. Build a restrained version of the supplied dark studio UI: left project navigation, preview, right inspector and separate speaker/illustration/caption/audio/SFX tracks. Keep data entry understandable, visible controls functional, keyboard operations accessible, and the output canvas identity independent of UI theme. Use the supplied logo as the brand source; derive small-size assets during implementation.
17. Release initially on Windows, with OS-dependent functions behind adapters. macOS is a separate verified distribution milestone requiring a Mac build/test environment. Do not label it supported merely because Tauri can target it.

## I. Migration risks and treatment

| Risk | Treatment |
|---|---|
| Dirty tree or untracked work lost | Capture a reviewable baseline including tracked and untracked source changes before refactor. No reset, bulk cleanup or automatic commit of unrelated/generated files. |
| Existing projects become unreadable | Versioned copy-on-migration and legacy readers; verify old exports and source hashes before switching project authority. |
| Current source replacement loses history | Implement immutable asset versions before new editing/import workflows. Do not retrospectively promise recovery of already replaced uploads. |
| Old segments reused after an edit or crash | Fingerprints plus decode/frame/duration checks and atomic completion manifests; changed dependencies invalidate segments. |
| Renderer performance degrades with richer layers | Keep static caches and bounded worker scheduling; benchmark mixed-media fixtures and establish a bounded memory cache. |
| Live preview differs from export | Shared compiled composition and landmark/frame parity tests, including transitions and audio cuts. |
| Narrative cleanup desynchronizes video | Apply one EDL to both audio and source video; validate mapped cuts, crossfades and captions. |
| New editor overwrites an AI/manual change | Optimistic version checks, transactional patches and undo history. |
| External client cannot access local media/service | Honest capability handshake; local CLI/structured file transfer fallback; no hidden provider calls. |
| Old style rules masquerade as research | Preserve provenance and uncertainty; partition source formats and sponsor segments; reconcile conflicting counts. |
| Legacy UI rules conflict with mockup | New dark studio direction takes precedence; preserve output style independently. Do not treat mockup text as capability evidence. |
| Windows-only helpers break macOS | Isolate Explorer, DPAPI, memory probing, SAPI, binary discovery, fonts and installer paths before claiming portability. |
| Credentials leak through migration/reporting | Do not read or copy plaintext keys into plans, diagnostics or project packages; retain protected legacy settings until deliberately retired. |

## J. Tests required before invasive refactoring

Phase 0 runs the existing relevant suite in an isolated test data directory with no live provider calls. Record pass/fail/skip counts and dependency/fixture limitations. A skipped integration test is not acceptance evidence. Do not launch tests against the user's installed project database.

Existing regression starting points:

- `test_contracts.py`, `test_contracts_models.py`: schema examples, typed contracts and reference rules.
- `test_render_smoke.py`: frame dimensions, Paper & Ink, draw progression and seeded pixel determinism.
- `test_polish.py`, `test_voice_upload.py`: pause retention, EDL mapping, decoding and narration comparison.
- `test_pipeline_e2e.py`, `test_topic_e2e.py`, `test_orchestrator.py`: artifacts, duration, review gates, failures and resume. Keep fake-provider use explicitly test-only.
- `test_jobstore.py`, `test_server.py`, `test_server_controls.py`: stage attempts, API authentication, original-voice upload and review behavior.
- `test_settings.py`, `test_gateway_repair.py`, `test_agents_m2.py`: protect historical/migration behavior while extracting reusable utilities; retire active-provider expectations only after replacement tests exist.
- `test_parent_watch.py`, `test_guardrails.py`, `bench/smoke_packaged.py`: lifecycle and operational starting points. Packaged smoke runs must use disposable project data.
- `app` TypeScript check/build and `app/src-tauri` Rust check. Builds validate source, not visual usability.

Before each affected subsystem is refactored, establish these behavior tests:

1. Legacy project conversion leaves original inputs untouched and reproduces selected frames, duration and audio landmarks.
2. Replacing a source creates a new asset version; undo restores the old reference; failed import preserves the accepted source.
3. Script/narrative changes invalidate dependent approvals; stale patches and invalid project transitions are rejected.
4. Board disappears for an evidence excursion and returns with the correct version; transient marks vanish; connectors follow their valid endpoints.
5. Draw/reveal/highlight/replace/remove/move/group/split/count/cross-out each change the intended state; unsupported actions fail explicitly.
6. Cached segment with wrong input hash, truncation or incorrect duration is rebuilt; valid unaffected segments are reused.
7. Random timeline seeking gives the same composition as sequential rendering, including a return to an earlier board.
8. One EDL preserves audio/video sync and captions through multiple cuts; source-to-output time mapping handles boundaries consistently.
9. Local revision affects only its approved dependency scope; accept/reject/undo/redo survive restart.
10. Speaker, captions and diagram labels obey safe zones in landscape and portrait; text measurements use packaged fonts.
11. Capability discovery agrees with actual compiler/renderer support; no-key approved-plan production works through a real external client and through CLI.
12. A crash between file staging and database commit recovers to a valid accepted version; diagnostics omit private media and secrets.

New tests are added immediately before their related implementation, rather than creating a speculative suite for every future feature at once.

## Phased implementation plan

Each phase has a demonstrable exit gate. A failing gate is repaired before dependent work continues. The first priority after baseline protection is the researched video behavior. New project services, broad storage migrations, MCP, provider retirement, dashboard redesign and the general timeline editor wait until Phase 3 passes.

Only narrowly necessary supporting changes are allowed during the research implementation: extend existing layout/cue fields, preserve isolated test inputs, make state-aware caches correct, and ensure the preview reflects the actual rendering. These serve the researched output directly; they are not permission to bring forward the wider architecture refactor.

### Phase 0 — Baseline and regression protection

- Objective: establish what works on the present checkout and protect user work.
- Affected: existing tests, `tests/fixtures/`, `bench/`, baseline documentation; application source changes only if a separately recorded baseline defect must be repaired.
- Migration: record dirty-tree inventory, establish a recoverable source baseline without omitting untracked work, and copy selected legacy fixtures into isolated test storage.
- Tests: existing contract/render/audio/store/API checks; TypeScript and Rust checks; one real legacy media pipeline and disposable packaged lifecycle test when dependencies allow.
- Rollback: no project migration; retain original data and baseline artifacts.
- Complete when: current pass/fail/skip report, representative frame/audio landmarks, and startup/open/preview/render/memory benchmark results are recorded. Historical timings are clearly distinguished.

### Phase 1 — Translate the forensic evidence into executable production rules

- Objective: convert the browser-extension findings into a concrete implementation contract for the current engine.
- Affected: research adapters, `schemas/reference-video-analysis.schema.json`, `schemas/visual-plan.schema.json`, existing examples, `visual_plan.py`, research-linked test specifications and style data.
- Migration: retain every original packet and its limitations. Map each adopted behavior to video/board/event evidence, the current code restriction, the required output behavior and its acceptance test. Extend the current representations only as needed; do not introduce the full new project architecture yet.
- Required rules: multiple visual events per narrative beat; board identity and activation; incremental objects; temporary attention marks; evidence reveal/hold/annotation/return; deliberate cuts and camera actions; conceptual opening-to-ending resolution; optional sponsor interruption with a preserved editorial board. Keep semantic connectors distinct from free-anchored pointers.
- Research closure: reconcile camera counts and density definitions; seek the missing Jalapeno continuous-viewing evidence. Do not let unavailable micro-timing turn into invented exact values. Label provisional rules and keep those configurable.
- Tests: evidence references resolve; observation timing uncertainty survives normalization; every adopted rule has an original render case and an observable pass criterion. No one-second/two-second sampling cadence becomes a fixed creative rule.
- Rollback: new normalized research/version files are additive; old inputs and schemas remain available through their versioned readers.
- Complete when: the evidence-to-rule-to-code-to-test matrix is finished and the first original reference-driven sequence is fully specified. A generic style prompt is not sufficient.

### Phase 2 — Implement the researched behavior in the existing engine

- Objective: make ATME visibly execute the learned production grammar before architectural restructuring.
- Affected: `visual_plan.py`, `pipeline.py`, `render/animator.py`, `render/camera.py`, `render/svg_builder.py`, `render/autolayout.py`, necessary existing layout/cue schemas and preview route; renderer regression tests.
- Migration: retain the current renderer and legacy fixtures. Add explicit board activations, object visibility and action intervals to its input path. Replace the current one-beat/one-scene, forever-visible, automatic-reframe and all-draw shortcuts. Do not rewrite unrelated services or move creative control to MCP in this phase.
- Implementation order: board activation/return and lifetimes; multiple timed actions; temporary annotations and semantic connectors; evidence asset display and annotation; explicit cut/hold/pan/reframe/zoom semantics; relevant diagram primitives and composition checks; actual-plan preview parity. Derive supported movement from frame evaluation so random seeking is correct.
- Audio rule: bind actions to the approved original recording using measured word/clause timestamps and disclosed uncertainty. Preserve natural pauses. Fixed narration pacing targets do not override the recording.
- Supporting correctness: invalidate cached layers/segments when their relevant input state changes and use isolated versioned fixture media. These narrowly scoped changes are prerequisites for truthful visual verification, not the broad cache/storage redesign.
- Tests: board excursion/return, reveal progression, temporary mark removal, replacement without ghost objects, connector attachment, evidence reading hold, intentional cut versus movement, action-trigger bounds, arbitrary seek parity and preview/export parity.
- Rollback: keep the old input adapter and baseline frames; revert the new input version without modifying original source recordings or accepted projects.
- Complete when: the original reference-driven sequence demonstrates the researched behaviors through ATME's actual render path, with traceable evidence and no hidden generic-box substitution. The current provider path remains untouched unless a small input adapter is required; no paid calls are needed merely to test deterministic rendering.

### Phase 3 — Full-video fidelity and usability gate

- Objective: prove the reverse-engineering implementation produces a coherent complete explainer before refactoring it.
- Affected: original production fixtures, research-comparison report, renderer/pipeline fixes found by inspection and accepted regression landmarks.
- Migration: start with short diagnostic sequences to isolate errors, then render a complete original 5-10-minute landscape explainer with an approved continuous voiceover. A user's supplied recording is preferred; an existing authorized full-length recording may be used if available. A short or synthetic-voice fixture alone cannot satisfy final acceptance.
- Evaluation: review the complete output for narrative progression, object readability, board memory, evidence cycles, attention marks, camera purpose, timing against narration, source audio clarity and opening-to-ending resolution. Compare function and supported measurements with the inspected reference segments; do not claim access to Caleb's source project or exact authoring software settings.
- Tests: full-duration audio/video consistency, no missing frames/assets, correct board returns, no collisions at visual landmarks, stable output on repeat render, pause/restart behavior and real resource measurements. Sponsor support gets a separate original optional insert test; it is not imposed on the editorial video.
- Rollback: retain last accepted renderer/input versions and repair failures in Phase 2. Do not use later architecture work as a substitute for fixing visible production shortcomings.
- Complete when: the complete render and evidence-linked comparison have been reviewed and the user accepts the video behavior as the baseline to preserve. If the required original recording is unavailable, prepare all independent work and identify that specific missing acceptance input.
- Gate: only after this acceptance may Phase 4 begin. Freeze accepted visual/audio landmarks and production inputs as golden regression cases so the refactor must preserve the demonstrated result.

### Phase 4 — Application boundary and project versions

- Objective: separate UI/API commands from storage/render internals and add safe project authority.
- Affected: `server/app.py`, `orchestrator.py`, `store/db.py`, `store/contracts.py`; new project/service modules.
- Migration: wrap existing functionality first; add transactional project/version/approval records and copy-on-migration adapters. Separate render-task state from production state.
- Tests: old job visibility, migration interruption/retry, version integrity, invalid transitions, stale approval, worker serialization, authenticated commands.
- Rollback: legacy data remains readable; switch back to preserved baseline using the original database copy. Do not downgrade a migrated database in place.
- Complete when: a legacy project can be opened as a versioned project, reviewed, reopened and restored without changing its source files or losing its export.

### Phase 5 — Production contracts, validation and compiler

- Objective: make externally supplied production data executable without internal creative calls.
- Affected: `schemas/`, `store/contracts.py`, `visual_plan.py`, `pipeline.py`; compiler/validator modules.
- Migration: formalize the board/action behavior proven in Phases 1-3 into modular contracts and a shared compiled representation. Retain v1 layout/cues and the accepted research-first input versions through adapters. The compiler must preserve their output rather than replace the production grammar.
- Tests: version rejection, cross-reference failures, malformed intervals, unsupported actions, duplicate IDs, deterministic normalization, legacy frame parity.
- Rollback: new contracts are opt-in project versions; legacy route remains available during migration.
- Complete when: a supplied original script, recording and valid basic production plan compile, validate and render through the existing engine without an LLM call. Errors have stable codes and precise repair locations.

### Phase 6 — External AI integration and provider-path retirement

- Objective: make one real compatible external client operate ATME through controlled project commands.
- Affected: `cli.py`, service/API modules, new MCP adapter, provider UI/routes, `cognitive.py`, `agents/`, `gateway/`, settings/dependency/packaging configuration.
- Migration: expose capabilities, schemas, project inputs, approvals, proposals, validation, preview, render/status and revision retrieval. Provide structured export/import fallback. Extract lints/geometry/validation before disabling old creative orchestration.
- Tests: actual client connection and no-key production path; CLI/service parity; unsupported capability rejection; project scope/path containment; denied stale mutation; no accidental paid provider call.
- Rollback: retain isolated legacy code and encrypted settings for historical compatibility until cutover evidence is complete. Restore service/UI switch if the replacement fails acceptance.
- Complete when: the user can ask a connected AI to prepare a project, review the result in ATME and render it without provider-key setup. Normal UI no longer depends on internal LLM routing. Document exactly which clients were tested.

### Phase 7 — Immutable media, cleanup and narrative authority

- Objective: support approved script, script+audio/video, and recording-first entry paths on real media.
- Affected: `audio/voice_upload.py`, `audio/align.py`, `audio/edl.py`, `audio/polish.py`, pipeline, project service and media modules; Sources UI.
- Migration: asset versions and hashes first; probe media, normalize derivatives and create proxies. Add timestamped transcript import/local utility support. Preview cleanup decisions, accept narrative source and lock final edited timing before final storyboard approval.
- Tests: invalid/replaced uploads, VFR/portrait phone video, rotation/HDR normalization policy, sample rates, original retention, short-pause preservation, EDL audio/video sync and restart recovery.
- Rollback: point the project back to prior media/EDL versions; never overwrite originals.
- Complete when: original audio and talking-head source files can each become authoritative, cleanup is reversible, a timing map is inspectable, and downstream data becomes stale correctly after edits.

### Phase 8 — Harden the proven grammar and extend media composition

- Objective: preserve the already demonstrated visual grammar while extending it to the specification's broader talking-head and media workflows.
- Affected: `render/`, compiler, style/asset contracts and registry, pipeline, schemas and fixtures.
- Migration: carry forward the evidence assets, board states, camera behavior and actions implemented before refactoring. Integrate them with project versions, media assets, pinned fonts and the compiler. Add source-video composition and supported speaker layouts without weakening the accepted explanation grammar. Generalize caching around the proven state model.
- Tests: evidence excursion and restored board, object lifetimes, attention pointers, action semantics, arbitrary seek parity, speaker crop/show/hide, protected labels, bounded memory and segment fingerprints.
- Rollback: retain legacy renderer adapter and version-pinned old output path; disable unvalidated primitives via capabilities.
- Complete when: an original explanatory sequence contains incremental diagrams, temporary attention marks, an evidence insertion, a correct board return and optional speaker placement. No unresolved generic fallback is accepted for final output.

### Phase 9 — Studio interface, timeline and reversible revisions

- Objective: deliver the functional editing workflow shown by the supplied dashboard direction.
- Affected: `app/index.html`, `app/src/main.ts`, `tokens.css`; new focused UI modules; project/revision services, preview endpoints and patch contracts.
- Migration: build project navigation and actual compiled preview first; then Sources/Script/Storyboard views, inspector and frame-based timeline. Manual changes use the same bounded command/patch semantics as AI changes. Revision requests persist even if the AI client disconnects.
- Tests: selected-range context, stale patches, dependency impact on board returns, edit/accept/reject/undo/redo after restart, narration-locked duration edits, preview/export parity, keyboard navigation and responsive layout.
- Rollback: preserve accepted project versions and read-only legacy library access; experimental editor views cannot rewrite accepted media without a committed revision.
- Complete when: the user can move supported blocks, edit text/layout, swap assets, place/crop the speaker, change supported actions and SFX timing, and ask AI to revise a selection without regenerating unrelated content.

### Phase 10 — Landscape/vertical profiles, captions and final audio

- Objective: finish both production profiles with readable layout and intelligible audio.
- Affected: composition/style schemas, compiler, renderer/media/audio modules, timeline inspector and export UI.
- Migration: landscape and vertical share core data/services, with distinct approved layouts and safe zones. Add caption tracks and SRT/VTT/burn-in, music ducking, SFX limits and final loudness checks. Preserve a no-music/no-SFX preference.
- Tests: landscape and 1080x1920 outputs, portrait phone source, crop anchors, long labels, caption collisions, subtitle time mapping, audible narration priority and mix export.
- Rollback: restore prior profile/layout/mix version. Reject unsupported profile changes rather than silently crop an existing render.
- Complete when: one project in each profile renders with approved framing and audio; vertical is independently composed. Square output is absent. No automatic speech acceleration to satisfy a target WPM.

### Phase 11 — Preflight, recovery, diagnostics and performance

- Objective: make failures early, understandable and recoverable under real project load.
- Affected: validators, `guardrails.py`, render cache/manifests, store/service transaction recovery, lifecycle modules, diagnostics and benchmarks.
- Migration: content/version keyed caches, atomic segment completion, decode validation, stale-artifact invalidation and bounded caches. Preflight assets/fonts/codecs/versions/output permission/disk/resources/pending approvals. Expose approved fallbacks explicitly.
- Tests: corrupted segment, changed asset with same filename, missing font/media, disk exhaustion, failure during commit, interrupted render/resume/cancel, application close, diagnostic redaction and proxy eviction.
- Rollback: caches are disposable; accepted source/project versions survive. Rebuild invalid derivatives rather than reuse uncertain files.
- Complete when: an interrupted real render resumes safely, a local edit rebuilds affected output, missing prerequisites have actionable messages, and measured performance is published for the target machine without invented promises.

### Phase 12 — Full production acceptance

- Objective: verify complete workflows and visual quality rather than only module tests.
- Affected: golden projects, regression harness, release reports and any fixes revealed by acceptance.
- Migration: exercise legacy and V2 projects side by side; all fixture assets original, user-provided or appropriately licensed.
- Tests/projects: basic explainer, technical diagram, evidence-and-board-return explainer, talking-head explainer, audio-only narration, video-only narration, portrait input, a 10-13-minute landscape project, a vertical short, heavy text, many diagrams, and an SFX/mix stress case. Also test optional sponsorship and disabled captions/music.
- Rollback: fixes return to their owning phase; preserve last accepted project/render manifest.
- Complete when: required workflows pass with duration/frame/audio/visual-landmark checks, real UI review, reopen/reproduce, local revision and recovery. The long video must be a complete production render; a short sample alone cannot satisfy this gate.

### Phase 13 — Packaging and integration polish

- Objective: make the validated Windows product usable after installation and explain setup accurately.
- Affected: Tauri/PyInstaller config, runtime resources/fonts/icons, installer, CLI/MCP setup, documentation and diagnostics.
- Migration: package matching source/runtime versions, retain project upgrade backups and stable data locations, include a portable-project manifest and controlled asset relinking.
- Tests: clean Windows install/start/close, app upgrade with existing projects, required media dependencies, initial alignment model setup, disconnected-client recovery, project package reopen and no orphan sidecar processes.
- Rollback: previous installer plus pre-migration project backup; no destructive automatic down-migration.
- Complete when: installed application completes the approved production workflow on this machine and has clear recovery/integration instructions. A macOS release requires its own later build and acceptance evidence.

## Decisions and limits for approval

- Implement the researched Caleb Writes Code production behavior first (Phases 1-2), then accept a complete original video (Phase 3). Broader refactoring starts in Phase 4 and must preserve that accepted baseline.
- Keep the current Python SVG/FFmpeg renderer and Tauri/vanilla-TS stack. No Remotion migration or general editor framework replacement is proposed.
- Adopt external creative AI, local project authority, immutable sources, reversible edits and enforced approvals.
- Use the supplied dark studio reference and logo direction; preserve original Paper & Ink production assets and research mechanics independently.
- Windows is the first verified release; platform adapters support later macOS work, but no untested macOS support claim.
- Support 16:9 and 9:16 through the same engine. Defer 1:1, 4K performance promises, automatic long-to-short extraction, arbitrary keyframe graphs, advanced grading/masking, multicam, cloud relay and payments.
- External client compatibility and charges remain properties of the selected client/services. Removing ATME provider keys does not promise free creative services or universal client/media access.
- No research measurement becomes an exact runtime default merely because it was printed in a report. Vertical, SFX and exact word synchronization remain separate calibration work.
- The audit is sufficient to propose this sequence; it does not establish current tests pass. Phase 0 provides that evidence before invasive changes.

## Final release acceptance

The release is accepted only when a real user can create/open a project, select landscape or vertical, provide an idea/script/recording, use a tested external AI connection, approve the appropriate narrative version, upload and preserve original media, accept reversible cleanup, approve the storyboard/director plan, preview the actual composition, make bounded manual/AI revisions, pass preflight, render a complete video, and reopen/reproduce it.

There must be no required internal creative-provider keys, no silent loss of working legacy render behavior, no pretend capability controls, and no success claim based solely on fake-provider or short demo output. Keep the user's project/source history and the research corpus throughout the migration.
