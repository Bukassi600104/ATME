# V4 implementation status

Authority: ATME_V4_MIGRATION.md and the user's four approved corrections.

## First project-service slice

Implemented:

- A deterministic ProjectService sharing the existing job database, rather than a second project store.
- Authenticated bounded HTTP ingress for create/open/list/schema, external brief/script writes,
  artifact reads and explicit revision-bound script approval. Scripts need no visual layout to be stored/reviewed.
- Immutable artifact versions, durable approval events, approval invalidation after brief/script
  changes, finite JSON/size/schema checks and structured correction errors.
- Database write transactions protect revision checks across separate service connections.
- Only the two approved output-profile identifiers are accepted. This is metadata validation,
  not proof of portrait rendering or completion of all six media workflows.
- Board proposal schema, measured-word validation and deterministic compilation extracted to
  board_compiler.py. Production proposal HTTP routes and the browser harness no longer import
  the obsolete board agent/gateway for compilation.
- Explicit capabilities report MCP and project-service rendering unavailable in this slice.
  Draft project-service jobs cannot fall back into legacy orchestration.

Initial verification: 25 project-service/external-input/proposal-route tests passed, zero
failures/errors/skips; report data/baselines/v4-project-service.xml. This initial result
predates the final approval-history/concurrency checks and compiler-extraction regression run.

Final slice verification:

- 59 project/board/compiler/camera/narration/proposal regression tests passed, zero failures,
  errors or skips (146.847 seconds; data/baselines/v4-project-regression.xml).
- All eight final project-core tests passed (24.926 seconds; data/baselines/v4-core-final.xml),
  including two separate database connections racing the same revision and an isolated
  interpreter check that the project core/compiler import no agents, gateway, cognitive,
  settings or LiteLLM modules.
- Tracked-file diff whitespace checks passed. No dependency installation, live-model request,
  production-project mutation, UI/native rebuild or new full-video acceptance render occurred.

## MCP, plan ingress and local PCM media slice

Implemented after the first service foundation:

- Official MCP Python SDK 2.2.0 installed in the project environment and pinned in
  pyproject.toml; pip check passes. The stdio adapter in atme.mcp_server exposes nine
  typed project/schema/artifact/approval/media-metadata tools over the same service and
  user-selected database. It exposes no shell, arbitrary-path, model, sampling or render tool.
- A real MCP client subprocess initialized, discovered tools, created a project, received
  structured schema errors, corrected the script, approved its exact revision, stored a
  layout, rejected stale writes and reopened persisted state. This is protocol verification,
  not the final external-AI-driven video acceptance.
- Storyboard ingress uses the existing VisualPlan contract; layout ingress validates
  LayoutDoc and scene/board relationships. Plans record their script revision and report
  staleness after later script/media changes. Plan writes preserve unchanged script approval.
- Authenticated direct PCM WAV upload retains original bytes with a hash and technical
  frame/rate/channel/duration metadata. It performs no semantic transcription. This slice
  is limited to 64 MiB per WAV and 100 recordings per project; no arbitrary source paths
  are accepted. MCP sees metadata, not local paths or a copy of the recording.
- Local HTTP upload was observed from the separate MCP process against the same database.
  Connection configuration and current limitations are documented in MCP_CONNECTION.md.
  Capability reporting distinguishes an available stdio adapter from unobserved connection
  status; it does not invent a connected-client count.

Verification so far: the initial 10-test MCP/core run passed; the corrected seven-test
media/MCP run passed. The systematic-debugging guide identified a pytest binary-parameter
name exceeding Windows' environment-variable limit; explicit short IDs fixed setup/teardown.
No production media code change was needed for that test harness failure.

Earlier regression result: **212 tests passed**, zero failures/errors/skips, 329.599 seconds;
report data/baselines/v4-mcp-full.xml. The three long media integration modules
(test_pipeline_e2e, test_orchestrator, test_topic_e2e) were explicitly excluded. The run
includes the real stdio MCP client test and local HTTP-to-MCP shared-media check. Dependency
consistency and tracked-file whitespace checks passed. No model-provider credentials or
live creative calls were used. Native packaging, full-video quality and network-isolated
render acceptance were not performed in this slice.

## Deterministic project compile, preview and render slice

Implemented:

- Validation now requires the exact current approved script, current externally authored
  VisualPlan and LayoutDoc, original PCM narration, matching profile aspect ratio and authored
  timings within the narration. Project state reports actual readiness.
- A fingerprinted private runtime snapshot separates immutable script, storyboard, layout
  and hash-verified narration inputs from resumable derived work/output. Repeated compilation
  reuses only that exact snapshot; tool-supplied filesystem paths remain impossible.
- MCP and authenticated HTTP expose validation and same-renderer PNG preview. Manual render
  confirmation queues the existing polish, technical-alignment, Caleb-derived rendering and
  MP4 assembly path without blocking the MCP call. Status and authenticated integrity-checked
  MP4 retrieval are durable by run ID.
- Locally recognized token text is private matching evidence. Exposed timed word labels are
  copied from the approved external script and identify that semantic source.
- Network-trapped acceptance rendered real MP4s for LONG_FORM_16_9 at 1280×720 and
  SHORT_FORM_9_16 at 720×1280. It exercised real snapshotting, audio slicing/dynamics, frame
  rendering, FFmpeg segmentation/mux, durable state and checksums with synthetic narration
  and an installed timing-engine double. No LLM usage was recorded.

Verification: **217 tests passed**, zero failures/errors/skips in 352.455 seconds; report
`data/baselines/v4-project-render-full.xml`. Ruff checks for the changed project/render/MCP
files and tracked-file whitespace checks passed. The three older long integration modules
were explicitly excluded as in the prior V4 run. A final seven-test focused run then passed
after verifying real MCP image transport and proving that a queued render stays bound to its
immutable revision even if the project is revised while rendering.

## Authoritative narrative and pre-layout timing correction

Implemented:

- Project state now carries an explicit Authoritative Narrative Source. Script-authority
  projects require exact external-script approval; audio-only/video-only projects do not.
  Their recording remains semantic and timing authority, while a connected-AI transcript or
  scene map is stored as a non-authoritative derived index.
- MCP can describe the authority, return integrity-checked audio content, and expose the
  original audio or video recording as a binary resource for connected-AI semantic analysis.
- Non-blocking pre-layout timing works before semantic structure exists. Recording-only runs
  expose anonymous speech-unit timestamps without local recognized text. Script-authority
  runs expose approved-script labels; recording-authority runs with a derived index identify
  those labels as connected-AI-derived rather than authoritative.
- PCM WAV remains supported. MP4, MOV, MKV and WebM can now be streamed up to 1 GiB; ATME
  retains the original video as authority and extracts a private PCM timing track locally.
  Rendering consumes the canonical timing track without changing the Caleb-derived visuals.
- Stereo recordings are mixed to mono while preserving frame count/timebase. Queued timing
  remains bound to its immutable source revision if the project changes during processing.

Verification: **226 tests passed**, zero failures/errors/skips in 397.720 seconds; report
`data/baselines/v4-authority-video-full.xml`. This includes actual video generation/upload/audio
extraction, real MCP audio/resource/image transport, both authority modes, queued-revision
isolation, and real offline landscape/portrait MP4 acceptance. Ruff, dependency and tracked-file
whitespace checks passed. No provider credentials or creative LLM calls were used.

## Desktop authority intake, MCP connection and package slice

Implemented:

- Desktop project intake offers script+audio, script+video, audio-only and video-only modes.
  Only script-authority modes request and explicitly approve a script. Recording-authority
  modes proceed directly from the user recording and explain the connected-AI semantic step.
- Audio/video upload writes through the authenticated bounded project endpoints and immediately
  queues the new pre-layout technical timing operation. Partial projects remain visible if a
  local model or media check needs attention.
- Settings generates copyable stdio MCP client JSON for the exact installed sidecar and project
  database. No model-provider field or API key is present.
- The frozen sidecar now multiplexes desktop HTTP and stdio MCP modes. Production packaging
  explicitly excludes LiteLLM/provider integrations and the package metadata no longer offers
  a gateway install extra.

Verification: the production TypeScript/Vite build passed, Rust `cargo check` passed, and the
optimized Windows application plus NSIS installer built successfully at
`app/src-tauri/target/release/bundle/nsis/ATME_0.1.1_x64-setup.exe`. Archive inspection found
the MCP-capable sidecar and no LiteLLM paths. Frozen HTTP health/capabilities/shutdown passed,
and the official MCP client completed its full project correction/persistence/audio/resource/
preview round trip against the frozen executable. The final focused authority/timing/media/MCP/
offline-render run passed 20 tests after the earlier 226-test broad run.

## Remaining migration work

CLI project operations, remaining Director/Timeline schema ingress, bounded patches, full
editing, talking-head production, and a real external-AI/original-human-narration/local-model
acceptance production remain. The obsolete cognitive source modules, CLI provider branch,
settings, prompt bundle, dependency and provider-specific tests still need Phase G deletion
after replacement acceptance. Their continued source presence is migration compatibility, not
a supported alternate mode. The new installer is built; the currently installed application
has not been overwritten automatically.

## Studio workspace and bounded revision slice

Implemented:

- The primary desktop experience is now a persistent production studio: project navigation,
  renderer-backed viewer, visible Sources/Assets library, contextual inspector and multi-track
  timeline share one workspace for 16:9 and 9:16 projects. The former authority/settings wizard
  is no longer the primary entry point.
- Project creation asks only for a title, output profile and optional first recording. Narrative
  authority, timing internals, database location and raw MCP configuration are inferred or kept
  behind Advanced connection details.
- Script viewing presents the externally authored artifact first. Local JSON editing is a collapsed,
  explicitly labelled manual override for targeted corrections, not a parallel authoring flow.
- AI Connection never fabricates a connected-client identity. Until a client actually reports one,
  the studio says that no identity has been reported and exposes only the local launch configuration
  under Advanced.
- Sources accept authoritative WAV/video uploads and Assets accept immutable supporting images,
  documents, audio and video without changing narrative authority. Timeline clips and arbitrary
  ranges can be selected for a bounded revision request.
- The connected AI can list pending requests and submit one schema-validated script, storyboard or
  layout proposal. The studio previews proposed layouts through the existing Caleb-derived renderer;
  no project artifact changes until the local user explicitly applies the proposal.
- Output-profile changes, deterministic validation, render history, exact-revision render confirmation
  and completed MP4 playback are available from the studio without adding model-provider settings.

Verification: production TypeScript/Vite build and Ruff checks passed. The focused revision/asset/
project/runner/MCP suite passed 25 tests, followed by **230 passing broad regression tests** with the
three established long legacy integration modules excluded. The refreshed frozen MCP executable passed
its full project/media/resource/preview round trip and frozen HTTP health/capability/shutdown acceptance.
The Windows release executable and NSIS installer were rebuilt successfully at
`app/src-tauri/target/release/bundle/nsis/ATME_0.1.1_x64-setup.exe` (SHA-256
`33E45E307A88759D8CA69B4D2C73B4C156622A912BB29E3C6C6FA39C8F662861`). Archive inspection found the
sidecar and no LiteLLM path. The installed application was not overwritten automatically.

## Source preparation and production timeline slice

Implemented:

- Imported recordings enter an immutable source-timeline contract. Split, trim, bounded delete,
  ripple delete, sequence moves and bounded edge crossfades create new timeline revisions;
  original source bytes are never rewritten.
- Video is available in the central viewer before script, storyboard or layout artifacts exist.
  Loopback playback uses short-lived unguessable tickets and HTTP byte ranges. Viewer playback,
  scrubbing and playhead share one timebase; renderer frames use the same viewer as an overlay.
- Video clips display cached time-quantized JPEG thumbnails. Audio and linked video audio display
  cached min/max/RMS waveform peaks at 10, 40, 160 and 640 ms. Optional deterministic likely-
  silence markers are evidence only and never trigger deletion.
- The timeline supports horizontal scrolling, an adaptive time ruler, playhead-centered zoom,
  Ctrl-wheel/pinch zoom, Shift-wheel horizontal scrolling, plus/minus and Fit Timeline.
- Source removal requires an impact preview and explicit confirmation. It removes the source from
  active project state, closes its sequence positions and makes dependent plans stale while
  retaining immutable artifacts, render history, the external file and ATME's managed source copy.
- Technical timing and rendering materialize the cleaned timeline. The project path disables the
  legacy automatic silence slicer, so downstream timing cannot silently diverge from the user's
  cleanup. Video is one logical linked A/V clip, so timing edits preserve picture/audio sync.

MCP exposes the cleaned timeline read-only to the connected AI. Cleanup edits and source removal
remain deliberate local-user operations.

Release verification: the focused source-timeline/media suite passed all 5 tests. The production
regression selection contains 239 tests and passed in full, with the three established retired legacy
integration modules excluded. Ruff and the production TypeScript/Vite build passed. The final frozen
sidecar passed its 2-test full stdio MCP round trip and its HTTP startup, health, authenticated
capability and graceful-shutdown acceptance. Tauri produced the Windows executable and NSIS installer
at `app/src-tauri/target/release/bundle/nsis/ATME_0.1.1_x64-setup.exe` (136,524,027 bytes; SHA-256
`A7BAB32F2009E59A817EC9D817646F69539B9FC59A59019FE5791780402D8B20`).

## Installer process-lock correction

The failed reinstall was traced to two orphaned `atme-sidecar.exe` processes running from the
installed ATME directory and holding packaged Python modules open. The NSIS bundle now runs scoped
pre-install and pre-uninstall hooks that terminate the exact `atme-app.exe` and `atme-sidecar.exe`
process trees before copying or removing application files. It does not delete project data or user
source media. A regression test verifies that both lifecycle hooks remain configured.

The corrected installer built successfully at
`app/src-tauri/target/release/bundle/nsis/ATME_0.1.1_x64-setup.exe` (136,526,466 bytes; SHA-256
`059A7639C684645F92D9CA11A2A58688B0B29B9A00198D3DE84D7069F3C95B61`). The lifecycle test and Ruff
check passed, and no installed ATME desktop or sidecar process remained after clearing the reproduced
lock condition.
