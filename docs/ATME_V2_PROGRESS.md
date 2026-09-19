# ATME V2 implementation progress

Approved sequence: `ATME_V2_REFACTOR_PLAN.md`, research behavior before broad refactoring.

## Current approved override — 2026-09-08: no user API keys

The user explicitly moved no-key production ahead of the remaining full-video gate, regardless of prior research wording. This supersedes historical references below to live-provider evaluation as the next prerequisite or provider retirement waiting for later phases. Missing keys must never block continued production work.

Implemented in source:

- Compose imports validated external ScriptScenes and explicit-board LayoutDoc JSON, pauses for script approval, and routes to original narration upload. No internal research, verification, scriptwriting or layout generation runs for external projects. External content is not falsely marked independently researched/verified.
- Removed provider-key forms, paid topic generation and the production startup key store. Legacy credentials and history are preserved. Provider settings writes and topic generation now return actionable HTTP 410 responses; internal orchestrator provider resolution rejects paid-provider mode.
- Board planning now exports measured narration context and imports externally authored proposals. The full source-hash envelope prevents applying a proposal from an old recording/context even if the layout hash is unchanged. Existing validation, PNG comparison, explicit acceptance, backups and invalidation remain.
- Updated README/runbook and added `EXTERNAL_PRODUCTION.md`. The initial adapter requires matching structured files and currently uses 720p30 landscape; it is not full MCP integration or an autonomous no-input creative model. Script changes currently require importing a revised matching pair as a new project.

Verification: 196 regression tests passed in 269.47 seconds with zero failures/errors/skips (`data/baselines/no-key-cutover-results.xml`). This includes real-loopback HTTP tests; the three long media integration modules were excluded. Frontend typecheck/build passed. The systematic-debugging skill identified one obsolete provider-call-count assertion; the corrected standalone preview test passed.

A subsequent seven-test external-input run also passed, including the added orchestration test through polish, alignment, rendering and assembly with media doubles and fail-on-call creative agents. This proves routing/no-provider behavior, not actual full-video quality. No live API spending occurred. The isolated browser host was stopped and its tab closed after verification.

Browser verification used the existing isolated host with synthetic fixtures, not user projects: Compose missing-file validation, Settings without keys, Library navigation, saved proposal review and both production-renderer PNG previews passed; captured JavaScript error/warning logs were empty. The browser-verification guide informed these checks. JSON import/approval is covered by API tests; a full native file-picker/upload/render journey has not been claimed.

Still separate: rebuilding/installing the native app, the approved full original-narration acceptance video, and the broader studio/MCP refactor. No live-model evaluation or user API keys are required for those next steps. The installed app has not been updated by this source change.

## Baseline started 2026-09-06

- Source commit: `175f9bad605d63b7b78520afb70d5c7771b4edaa`, with substantial pre-existing tracked and untracked changes preserved.
- Source snapshot: `data/baselines/2026-09-06-research-first/source-baseline.zip`.
- Snapshot SHA-256: `7cfc11e33b1ba0c640a8319cfdee5709e82c10dec7b7caa9013cdbba6a703bc1`.
- Snapshot includes application/sidecar source, tests, schemas, research skill, prompts, docs, principal build manifests and current plan. It excludes user media, credentials, dependency installations, generated binaries and inaccessible old temporary folders; it is a source recovery snapshot, not a whole-machine backup. Existing source documents and generated builds remain in place.
- Test artifacts are isolated under the baseline folder. Local alignment uses the existing cached model with Hugging Face offline mode enabled. No live creative provider calls are part of these tests.

## Pre-change baseline results

| Check | Result |
|---|---|
| Non-integration Python suite | 55 passed; 16 integration tests deselected; 73.22 seconds |
| Existing real media pipeline | 4 passed; 152.83 seconds |
| TypeScript type check | Passed |
| Packaged sidecar smoke in fresh isolated data directory | Passed health/auth/shutdown; no orphan process |
| TypeScript production build | Passed; 37.35 seconds |
| Rust offline check | Passed; 8 minutes 18 seconds |
| Remaining integration suite | 12 passed; 277.91 seconds in the native Windows environment |

The unit run reports one upstream Starlette/httpx deprecation warning. This is not a failing check and does not justify an unrelated dependency upgrade during baseline capture.

Together these runs passed all 71 baseline Python tests. The first sandboxed run of the remaining integration suite failed on Windows SAPI output initialization. A native SAPI probe succeeded, and all twelve tests passed outside the sandbox without changing application code. Keep the failed and native-run reports as environment evidence, rather than treating the failed run as a product regression.

Real pipeline fixture: 14,783 ms narrated duration; 455 silent-render frames including the existing 400 ms tail; 51 recognized words; 320,260-byte final MP4. Stage times: polish 70.47 s, align 44.08 s, render/segment assembly 34.50 s, final mux 1.99 s. The 151.06 s pipeline wall time includes cold imports on this machine and is not a new long-video performance guarantee.

Packaged sidecar reported version 0.1.0. This is an existing packaged artifact; source/build parity will need verification during release packaging. The smoke check establishes current lifecycle behavior, not that the package contains future changes.

## Research implementation preparation

`CALEB_PRODUCTION_RULES.md` maps twelve functional rules to source observations, current implementation restrictions and acceptance behavior. It also corrects evidence-cycle interpretation: returning to abstraction can use a developed new board, annotation is optional, and sponsor cycles must be excluded from editorial totals.

## First research-derived implementation slice

- Added optional versioned board timelines and object visibility intervals to the existing layout contract. Invalid references, overlapping activations, and malformed intervals are rejected.
- Implemented board activation/return and temporary marks in both raster animation and SVG previews. Returning to a board preserves its developed state without replaying its original drawing or retaining expired annotations.
- Made completed-layer caches visibility-aware and bounded for stateful layouts. Legacy layouts retain their existing rendering behavior.
- Added explicit camera hold, cut, pan, zoom, and reframe intent. Movement starts at its declared cue; cuts do not drift toward their destination beforehand. Existing implicit camera plans remain supported.
- Preserved explicitly authored final-audio timing through the pipeline, rejecting schedules that extend beyond the final narration instead of silently changing them with legacy scene-fraction retiming.
- Changed scene previews to use the saved production layout and camera when available, rather than rebuilding generic fallback boxes.
- Default standalone render duration now includes the entire board activation timeline.

Verification after this slice: **76 non-integration tests passed**, zero failures/errors, 42.36 seconds. The 16 integration tests were excluded from that particular run. Regression coverage includes deterministic arbitrary seeking, half-open visibility boundaries, absence of evidence-board ghosts, temporary annotation removal, camera timing, schema roundtrips, and saved-layout previews.

The real legacy audio-to-MP4 pipeline was then rerun against the changed source in a fresh job directory: **4 integration tests passed**, 39.05 seconds with warm local dependencies. Report: `data/baselines/2026-09-06-research-first/regression-pipeline-results.xml`. This covers actual alignment/render/mux and contract checks, but is not a rerun of the other twelve integration cases after the renderer changes.

Original ten-second renderer diagnostic: `schemas/examples/board-continuity.example.json`, generated by `bench/verify_board_continuity.py`. It uses an original queue explanation, not copied creator artwork. Verification artifacts are under `data/baselines/2026-09-06-research-first/board-verification-landscape/`: 960x540, 300 frames, 19.91 seconds render time. The clean original board and returned board have identical RGB SHA-256 hashes (`2595b6c4946e09e75c37de627ae9cc56b0a0aa4da6361c6f4292381aff15567d`). Landmark images were visually inspected. This is a silent regression artifact, not a completed production video or evidence that the entire visual grammar is implemented.

## Second slice: reveal actions and revision-safe segment reuse

Research rule R09 now has an executable `enter_action` distinction on rectangle, text and arrow layout elements: `draw` (legacy default) or `reveal`. Reveal is fully visible at `appear_at_ms`, with no stroke animation or text fade, and enters the static-layer cache immediately. SVG previews and raster frames share this behavior. Alignment output retains the action instead of coercing everything to `draw`; both cue contracts accept `reveal`. Unsupported entrance actions are rejected. This does not yet translate arbitrary multi-action prose into executable events: explicit layout actions must be supplied.

Systematic debugging reproduced a pre-existing segment-reuse defect in six failing regression cases: the old size-only check reused changed layouts/output options and unverified video files, and dropped resumed frame counts. Segment checkpoints now record a canonical layout/output fingerprint, renderer revision, start/duration, completed-video SHA-256, and original statistics. Only matching, intact checkpoints are reused. New output is written to a pending MP4 and promoted after successful rendering; checkpoint JSON is also promoted atomically. An interrupted revision preserves the previous completed segment. Old checkpoints without metadata are rerendered. Future renderer/encoding changes must bump `RENDER_CHECKPOINT_VERSION`.

Added six reveal tests and eight checkpoint tests, covering exact onset, all three element kinds, board return, reverse seek, legacy defaults, validation, cue preservation, input changes, corruption, malformed metadata and interruption. Tests of checkpoint decisions use a stub encoder; the separate real pipeline regression exercises actual FFmpeg output. These changes are source-only, not an installed release.

Verification: **90 non-integration tests passed**, 16 deselected, 48.90 seconds; **4 real pipeline integration tests passed**, 92.85 seconds. Reports: `reveal-unit-results.xml` and `reveal-pipeline-results.xml` under the baseline directory. A second render-stage call against the actual generated video successfully reused its verified segment and retained all 455 frames. The other twelve native integration cases were not rerun in this slice. The existing upstream Starlette/httpx warning remains.

## Third slice: self-contained evidence images

Added `evidence_image` elements for R04/R05. PNG content is embedded in the layout with a SHA-256 digest and explicit provenance (`original_illustration` or `external_evidence`). External evidence requires a source URL, recorded as metadata only; the renderer does not fetch it or certify its claims. Evidence images reveal instantly, retain their aspect ratio without cropping, obey board visibility/return, and use the same image markup in SVG previews and raster rendering. Existing annotations can appear over an evidence board; annotations are not mandatory.

Inputs are limited to static PNGs, 8 MiB compressed and 16 million pixels each. Strict base64, signature, checksum and Pillow verification reject malformed or substituted assets. No arbitrary local file paths, external SVG references, or remote image requests are introduced. Renderer checkpoint version was bumped so previously rendered segments cannot conceal this change.

This is renderer/contract support, not a finished evidence-media import interface or automatic evidence selection. Authored layouts must supply the image and provenance. Captions/source labels still need separate text elements. It does not establish readability of arbitrary uploaded material or complete the full-video quality gate.

Real FFmpeg verification produced a six-second, 180-frame original test-pixel sequence (`evidence-render.mp4` under the baseline directory), exercising image insertion and board return. This is a silent engineering artifact, not a production explainer.

Verification: 98 non-integration tests passed (36.89 seconds; 16 integration cases deselected). Two additional aspect-ratio/pixel-limit tests were then added and all ten evidence tests passed (1.34 seconds). Full-suite report: `evidence-all-results.xml`. No narrated integration rerun or packaged-app rebuild was performed in this slice; the real render check above covers the new image encoder path.

## Fourth slice: per-element narration triggers

Authored layouts can now attach `narration_trigger` to each element: a phrase, optional one-based occurrence, signed offset, and minimum confidence (default 0.65). The pipeline resolves these against words from the final polished recording, restricted to the element's scene. Multiple visual actions in one scene can therefore follow separate phrases. Punctuation/case and curly apostrophes are normalized. Timing comes from alignment, not research-video caption estimates.

Missing or ambiguous phrases, unavailable/low confidence, flagged words, out-of-recording offsets, inactive boards and visibility conflicts block resolution instead of guessing. An audit report is saved as `narration_events.json` on resolution success or a trigger-resolution failure, with per-target match counts/status and available confidence. The original layout is not partially mutated on failure. Existing layouts without triggers retain their previous timing behavior; a layout with explicit triggers preserves untriggered elements' authored final-audio times rather than applying scene-fraction spacing.

This implements timing for existing entrance actions, not a complete multi-action planner or camera-trigger editor. The UI does not yet author these fields or present the audit report. Board activations and visibility intervals are not automatically shifted to accommodate a trigger; conflicts require revision. There is no new API spend in these tests.

Verification: **109 non-integration tests passed**, 16 integration tests deselected, 36.71 seconds (`narration-all-results.xml` in the baseline directory). After refining visibility-conflict reporting, the 15 focused narration/reveal tests passed again. The alignment-stage test verifies the saved report and retained reveal cue using controlled word alignment. No live transcription, full narrated render, or packaged-app rebuild was performed in this slice.

## Fifth slice: timing-report review surface

Run and Script Review now include a collapsible narration timing report with an explicit load/refresh button. The panel shows scene, target, phrase, status, resolved time, match count and available confidence. It distinguishes no report, no authored triggers, resolved triggers and review-required results. It labels the data as the last saved alignment report; it does not imply that later script/voice edits have already been revalidated. Report text is inserted with `textContent`, not executable HTML.

Added authenticated `GET /jobs/{job_id}/narration-events`: checks job existence, returns explicit empty/unavailable states, and responds with 409 for incomplete report JSON. The UI handles request failures and re-enables refresh after an error. This is read-only review, not trigger editing or approval. Evidence import remains pending safe stage invalidation; no import control was added in this slice.

TypeScript checking and the Vite production build passed. The two new route tests passed, covering authentication, missing jobs, unavailable reports, empty reports, successful resolution, review-required results and malformed JSON. No interactive browser/desktop visual verification or packaged-app rebuild was performed.

Full non-integration regression run: **111 passed**, 16 integration cases deselected, 43.23 seconds; report `timing-ui-all-results.xml` under the baseline directory. Existing Starlette/httpx deprecation warning remains.

## Sixth slice: replacing images in existing evidence slots

Script Review now displays PNG replacement controls for evidence slots already present in the saved layout. Users choose a PNG, supply original/external provenance and description/source URL, and receive explicit save/error feedback. A successful save refreshes the rendered scene preview. The inventory endpoint returns only slot metadata, not embedded image payloads.

The authenticated replacement endpoint bounds the request, accepts only PNG/checksum/provenance fields, validates the complete resulting layout, and refuses running jobs or unfinished layout stages. It shares the worker-start lock, preserves the previous layout in a uniquely named backup, writes the replacement via a pending file, invalidates alignment/render/assembly while preserving polished audio, and leaves the job paused. Invalidation occurs before file promotion so interruption cannot mark new pixels as already rendered. Existing content-addressed segment checks handle the changed layout on rerender. Reports and rendered files from the prior attempt may remain on disk as historical output, but the downstream stages are no longer marked complete.

This replaces existing slots only; creating new evidence boards/slots and selecting their placement remain pending. Current automatic layout generation does not yet create evidence slots. Controls therefore appear only on layouts already authored with them. No live browser/desktop interaction or packaged release verification is claimed.

TypeScript checking and the frontend production build passed. Route tests cover replacement/backup/invalidation, authentication, active jobs, invalid checksums, wrong target types, inventory payload omission and unfinished layout rejection.

Full non-integration regression: **114 passed**, 16 integration cases deselected, 69.51 seconds (`evidence-import-results.xml` in the baseline directory). Existing Starlette/httpx warning remains. No narrated integration rerun was performed in this slice.

## Seventh slice: new evidence slots on authored boards

Script Review now offers an additional evidence-image form per scene when the layout has an authored board timeline. The user selects a board activation and enters canvas x/y/width/height on the existing 50-pixel grid plus a final-audio reveal time. New images are overlays; the control explicitly says it does not create a board or rearrange other objects. Successful creation refreshes the preview, preserves the previous layout and invalidates alignment/rendering through the same guarded save path as replacement. The add button is disabled after success to prevent accidental duplicate submission; reopening review exposes the new slot's replacement control and another add form without discarding edits during save.

Added authenticated POST to the evidence-slot resource and board/canvas metadata to its inventory. Creation rejects duplicate IDs, unknown scenes/boards, off-grid or off-canvas placement, and reveal times when the selected board is inactive. Layouts without a board timeline are explicitly unsupported for new-slot creation rather than silently assigned a board. This does not yet make the automatic legacy layout generator produce research-style board timelines.

Frontend type checking and production build passed. Automated coverage exercises successful creation/inventory/invalidation and non-mutating rejection of invalid placement. Interactive UI and packaged-app verification remain pending.

All ten focused evidence-creation/replacement tests passed (108.44 seconds on this run). No live provider calls were needed.

Full regression: **121 non-integration tests passed**, 16 integration cases deselected, 155.83 seconds (`evidence-create-results.xml`). Existing upstream Starlette/httpx warning remains.

## Eighth slice: board-timeline authoring (2026-09-07)

Script Review now has a board editor with activation rows, explicit start/end milliseconds, repeat-board returns, and per-object board/creation-time assignments. For a legacy canvas it presents an unsaved single-board proposal. Saving validates complete assignments, unique board/activation IDs, non-overlapping intervals, active-board creation times and final-audio duration. No geometry, camera cues or phrase triggers are silently rewritten. Blank timeline gaps remain intentional blank output.

The authenticated editor requires a saved layout and final polished audio. GET returns only timing/assignment metadata and a layout revision hash. PUT rejects active jobs, unfinished layout, stale revisions and oversized requests; it preserves a uniquely named layout backup and resets alignment/rendering before promoting the edited layout. The job remains paused. Reopening Script Review refreshes evidence creation controls for the newly authored boards.

This closes the manual-JSON requirement for assigning legacy elements to boards, but is not automatic narrative board planning. The editor currently uses numeric fields rather than a graphical timeline. Interactive browser/desktop verification and narrated acceptance remain outstanding. An initial patch attempt failed on a sandbox startup timeout without creating files; the subsequent patch succeeded. File access/testing used the available cmd shell after PowerShell commands stalled.

Seven focused board-edit tests passed (26.55 seconds), including immutable legacy conversion, invalid-assignment rejection, saved backups and stale-revision protection. TypeScript checking and frontend production build passed.

Broader regression: **128 tests passed**, 256.11 seconds, with the four integration modules explicitly excluded. Report: `data/baselines/2026-09-07-boards-results.xml`. Frontend production build passed again after adding visible interval-field labels. No narrated integration rerun or installed-app update was performed.

## Ninth slice: browser workflow verification and access fixes

Added `bench/editor_browser_server.py`, an explicitly isolated verification host serving the built frontend and real FastAPI routes against a new test database. Only Tauri discovery is simulated. Job/provider execution raises an explicit test-host error; no live API calls or user projects are used. Test data lives under `data/baselines/2026-09-07-browser-session`.

Browser verification reproduced a missing navigation path: completed projects had no Library action for reopening the visual editors. Added **Edit visuals** for stopped/reviewable projects. This mode makes narration read-only, uses resume instead of script approval, and offers Back to Library without canceling the job. The ordinary script-review flow remains separate.

Using the available browser-control tool (the skill's preferred agent-browser CLI was absent), verified the actual built frontend: nonblank page, Library navigation, visual-editor access, read-only narration, loading saved board assignments, visible rejection of an overlapping interval, successful valid save with backup feedback, ambiguous timing report display, PNG upload through the browser file chooser, real API save, preview refresh and image persistence after reopening. Test image was the original queue diagnostic, not external creator artwork. No JavaScript errors/warnings were captured in the observed browser session.

Screenshot inspection exposed crowded native form controls. Added scoped review-form spacing, sizing, theme-aware colors and visible focus styles, and corrected evidence legend placement. Rebuilt and visually reinspected the controls successfully. This is a focused usability repair, not the deferred dashboard redesign. Frontend production build/type check passed after both fixes.

These checks do not cover native Tauri IPC, installed packaging, mobile layout, every failure state, or a new narrated production render. Browser saves are in isolated test data only. The previous 128-test Python result remains the latest full non-integration run; this slice's application changes are frontend-only.

## Tenth slice: preview/export stacking consistency

Regression tests reproduced two paint-order errors: completed elements were sorted by reveal time instead of document order, and animated strokes always painted over finished images. Export now preserves document order. Frames with an animated element below a completed element use full SVG rasterization; ordinary drawing and static holds retain the cached-layer path. This correctness fallback may cost more on densely interleaved animation and has not been benchmarked on a long narrated video.

Bumped the render checkpoint version so previously rendered segments cannot conceal the corrected behavior. Ten preview/export cases cover foreground/background annotation order, completed and active strokes, backward seeks and board returns. Separate alpha compositing permits a two-level antialiasing rounding tolerance; obscured strokes require exact preview pixels. A real 20-frame H.264 encode/decode test confirms strokes remain hidden behind the evidence image, allowing lossy codec rounding.

Focused renderer/checkpoint suite passed 54 tests; the evidence suite including the encoded-video test passed all 21 tests. No live providers, user media or installed binaries were changed. These are rendering diagnostics, not narrated production acceptance.

Broader regression passed all 139 tests with the four integration modules explicitly excluded (`data/baselines/paint-order-results.xml`). The existing upstream Starlette/httpx deprecation warning remains. `git diff --check` passed (line-ending warnings only).

## Eleventh slice: editable narration phrase links

The board editor now exposes each object's spoken trigger phrase, optional one-based occurrence, signed timing offset and confidence threshold. Existing links load from saved layouts; clearing the phrase explicitly removes its link and retains the authored fixed time. Older clients omitting the trigger field preserve existing links. No automatic phrase selection or unsupported source timing is inferred; this follows the forensic skill's distinction between an authored candidate and verified narration timing.

The existing revision-checked save route validates these edits, backs up the layout and invalidates alignment before leaving the job paused. On resume, the existing final-audio resolver determines actual times and blocks missing, ambiguous, low-confidence or conflicting matches. Camera/board activation timing is not phrase-linked by this slice. This closes a manual JSON requirement, not the automatic narrative-planning milestone.

All 22 focused board-edit/narration tests passed, including link add/preserve/remove, invalid input rejection without mutation, API roundtrip and stage invalidation. TypeScript checking and production frontend build passed. Existing upstream Starlette/httpx warning remains. Browser interaction, packaged-app verification and the broader regression suite were not rerun for this slice; the prior 139-test result predates these edits.

## Twelfth slice: board-scoped automatic collision repair

Inspection of the automatic layout path found that collision repair compared objects across separate boards. Two failing regression cases reproduced unwanted displacement (including an unrelated evidence-board object moving from y=100 to y=500). The repair pass now compares boxes/text only within the same board; legacy objects without board IDs continue to share one implicit canvas. This preserves deliberate coordinate reuse across board cuts and returns. Corrected the repair-count return annotation to integer.

All 41 focused spatial, board-continuity, visual-plan, board-editor and narration tests passed. The systematic-debugging skill guided reproduction before the fix. This does not add automatic multi-board generation: the current generation prompt still requests one accumulating diagram, and generation currently precedes final narration alignment. Changing that orchestration and adding final-audio-bound board planning remain outstanding. No installed binary update or narrated acceptance render was performed.

## Thirteenth slice: final-audio planning evidence (2026-09-08)

Alignment now writes `planning_context.json` before resolving visual triggers. It contains the approved scene narration/directives, observed word timestamps and confidence, measured scene bounds, final-audio duration/checksum and script checksum. Missing scenes retain null timing rather than guessed durations. Invalid, overlapping, out-of-order, flagged or uncertain word evidence produces `needs_review`. A `ready` status concerns these structural timing checks only, not narration completeness, semantic accuracy or production acceptance.

The context is referenced by alignment state, registered as a successful alignment artifact and included in new manifests. Older resumed alignment states remain compatible. On a visual-trigger failure the context remains available on disk for diagnosis, without marking alignment complete. No automatic board cuts are inferred and existing authored layouts are preserved. This is the input bridge for a subsequent post-audio planning pass, not that planner's implementation.

The forensic skill informed the explicit evidence/uncertainty boundary. All 45 focused context, narration, board-continuity and checkpoint tests passed, including the real alignment-stage code with mocked audio recognition on success and visual-trigger failure. No live provider call, native audio integration rerun, UI change or package update was performed.

## Fourteenth slice: word-anchored board proposal generator

Added `agents/board_planner.py`: a provider-neutral entry point using the existing layouter role and usage ledger. The model proposes board activations and complete object assignments using supplied word IDs, not invented milliseconds. First board begins at zero; each later cut uses an observed word start, and the last board holds through final-audio duration. Repeated board IDs represent returns. The prompt avoids mandatory scene cuts/sponsors and omits embedded image bytes from model input.

The compiler rechecks timing confidence, word order, known references, scene ownership, complete assignments, active-board creation and preserved camera duration. It compiles a separate validated layout candidate without mutating the source. Candidate metadata includes source layout, context, script and audio hashes plus `requires_review`. Its measured object times replace phrase links only in the candidate, not the saved project. Existing geometry/camera are preserved; this limits the quality of proposals based on legacy giant-canvas layouts.

All 62 focused planner/context/board/narration/editor tests passed. Offline provider fixtures exercised gateway usage recording; no live model request was made. Rendered-frame checks verify original-board return. The research skill guided continuity/evidence-return prompting and the separation of proposal from verified output.

This entry point is not yet wired into the app's generation/review workflow. Next work is revision-safe proposal persistence, visible review/acceptance and live-provider evaluation, followed by richer scene geometry and the narrated acceptance gate. No claim of automatic end-to-end planning or updated installation is made.

## Fifteenth slice: proposal generation, review and acceptance workflow

The visual board editor now offers an explicitly labeled, potentially billable AI proposal action and a separate saved-proposal review action. Review lists every board interval, rationale and object assignment; acceptance is a distinct user action. Unsaved manual editor values are not sent to generation. The UI explains that geometry/camera stay unchanged and candidate acceptance replaces phrase links with measured times for the current recording.

New authenticated routes generate with the project's configured layouter, persist a separate proposal atomically, reload it for review and accept it with a layout backup plus alignment/render invalidation. Generation never applies a layout. All four source artifacts (layout, script, audio state and planning context) are fingerprinted and rechecked after the provider call and before acceptance. Unready/stale timing evidence, changed source, wrong proposal IDs, duplicate generation and active jobs are rejected. Usage attempts are recorded even on provider failures; raw provider exception details are not returned or saved in proposal usage errors. No fake-provider fallback is offered by the production route.

Frontend type checking and production build passed. Route tests use injected offline provider responses, not live calls. Initial seven cases passed, covering roundtrip, backup, invalidation, source changes, authorization and generation races; broader regression includes additional duplicate/failure cases. Interactive browser testing and native packaging have not been performed for this slice. Textual proposal review is implemented, not a rendered candidate-preview comparison.

Broader regression completed successfully: **185 tests passed**, including all nine new route cases. Four integration modules were explicitly excluded. Report: `data/baselines/proposal-workflow-results.xml`. The existing upstream Starlette/httpx deprecation warning remains. No live API spend or installed-app update occurred.

## Sixteenth slice: rendered proposal comparison and browser verification

Proposal review now includes a timestamp field, board-boundary landmarks and an explicit Compare frames action. The authenticated preview route renders saved/proposed layouts through the production frame renderer, preserving output aspect ratio and bounding the preview's longest edge to 960 pixels. It rejects stale proposal/source identities, invalid times and unsupported versions. Responses are PNG with no-store headers. Previewing writes no layout and makes no model call; these are static comparisons, not playback or narration-sync acceptance.

All ten proposal-route tests passed, including a candidate whose changed cut produces different saved/proposed frames, output dimensions, authentication, bounds, stale identities, no mutation and no extra model usage. Frontend type checking and production build passed. The previous full 185-test result predates this slice; the full suite was not repeated without need.

Used the browser-verification skill and available browser-control fallback (preferred CLI previously unavailable). Reused the isolated test-host approach with a new `--proposal-fixture` option, explicitly synthetic timings and no live provider. In `data/baselines/proposal-preview-browser`, verified nonblank app, Library navigation, visual editor, saved-proposal loading, landmark selection at 6999 ms, both PNGs visibly rendered, and explicit acceptance confirmation with the job paused. No captured JavaScript errors/warnings; server logs show successful preview requests. The verification tab was closed and the temporary host stopped. User projects and installed binaries were untouched.

## Remaining research-first work

Continue the production rules with richer evidence assets and visual actions, and narration-bound event planning. The segment-level revision guard is implemented; whole-job stage invalidation and editable project versioning remain future work. Then produce and review a complete original explainer using the final narration. Research normalization and corpus-wide claims must continue to distinguish observed evidence from candidate rules.

Provider retirement, MCP, new project storage and dashboard redesign remain deferred. The installed/packaged application has not been rebuilt with this renderer slice; packaged smoke results above concern the pre-existing binary only.

No complete original reference-style video has been produced or accepted yet. Phase 3 remains an explicit future acceptance gate.
