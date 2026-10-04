# ATME visual-production traceability

Status: active requirements ledger

Owner: primary implementation agent

Independent verifier: `/root/independent_plan_auditor`

This ledger is the phase gate. A requirement remains incomplete until its contract, implementation, validation, automated evidence, and representative visual artifact all exist. Paths under **Current evidence** describe the Phase 0 checkout; they are not claims of completion.

| ID | Required final behavior | Current evidence and gap | Planned authoritative evidence | Phase | Status |
|---|---|---|---|---:|---|
| R-01 | Rich executable objects: freehand paths, geometry, callouts, pictograms, characters, media, lists, charts, technical frames, groups, masks, anchors, transforms, layers, and state | V2 state kernel, authored marks/text/lists/freehand, anchor-bound arrows, pinned illustration families, static groups/clips/masks, project-owned PNG supporting images, and bounded attested evidence cards now render in source-only SVG/PNG. Evidence composition includes an exact crop, focus, optional darkening, source label, and self-annotation; readable `insert_evidence` is supported. Legacy ambiguous masks, arbitrary media, non-rectangular evidence apertures, dynamic grouping, external clip references, richer objects, and installed preview/export still fail closed. | `schemas/executable-layout-v2.schema.json`; `schemas/resolved-visual-timeline-v2.schema.json`; `contracts_v2.py`; `project_assets.py`; `v2_raster.py`; `v2_state.py`; `v2_svg.py`; `v2_mask.py`; `v2_world.py`; `v2_path.py`; `test_v2_evidence_compositor.py`; prior Phase 3 compositor tests | 1–3 | Partial compositor; full object matrix pending |
| R-02 | One canonical executable action vocabulary from storyboard through export | V2 strict actions and Slice 3A state verbs exist; Slice 3D renders draw/write semantics, Slice 3G executes exact-binding connect/disconnect on supported arrows, Slice 3I reveals ordered list items, Slices 3J–3M add highlight/cross-out/dim/isolate attention actions, Slice 3N adds bounded hold/cut/pan/zoom/reframe camera mechanics, Slice 3T adds bounded authored-object crossfade replacement, and Slice 3Y adds explicit geometry morph correspondence. Annotation, dynamic group/ungroup/split, count, sound, non-list progressive reveal, and other unsupported semantics remain blocked; full action matrix and preview/export are pending | `schemas/visual-plan-v2.schema.json`; `contracts_v2.py`; `v2_state.py`; `v2_svg.py`; `v2_camera.py`; `v2_morph.py`; action tests; runtime semantics | 1, 3 | Partial kernel and compositor; full execution pending |
| R-03 | Deterministic Visual Director/Compiler converts semantic intent to executable composition without an internal LLM | `board_compiler.py` assigns existing objects/timing but does not create the requested composition; `agents/board_planner.py` is obsolete | compiler IR; coverage map; compile diagnostics; rich-storyboard golden output | 4 | Missing |
| R-04 | Fallbacks are reason-coded, visible, bounded, and cannot silently become final production | `render/autolayout.py` generates generic boxes/arrows and current validation can accept them | fallback records; degraded-preview state; user exception record; blocking validator fixture | 4, 8 | Missing |
| R-05 | Connected AI receives versioned, original research-derived directing grammar and truthful capabilities through MCP | `mcp_server.py` exposes schemas and broad instructions but not the complete visual grammar or coverage contract | MCP resources; capabilities manifest; client E2E trace; unsupported-capability rejection | 9 | Partial |
| R-06 | Production quality validates semantic coverage, density, legibility, pacing, evidence, continuity, narrative resolution, and parity | Current validation primarily checks structure, dependencies, timing, and freshness | validation codes; failing fixtures; repair locations; 16/20 human rubric record | 8 | Missing |
| R-07 | Original, provenance-aware Paper & Ink illustration and asset families | Phase 2 bundles sixteen original assets across eight families with anchors, provenance and checksums. Slice 3C renders all sixteen from verified local bytes at authored bounds, with strict family matching and sanitized SVG; per-beat director selection and project production composition remain pending | `production-assets/paper-ink-v2/asset-registry.json`; `style_bundle.py`; `v2_svg.py`; `test_v2_registry_illustrations.py`; Phase 2 report | 2–4 | Registry runtime partial; director/production integration pending |
| R-08 | Complete claim-to-evidence-to-annotated-return cycle | Slice 3V binds attested evidence to a bounded SVG/PNG crop/focus/attribution/self-annotation card and readable `insert_evidence`. Slice 3W executes a provenance-checked board return cut with retained object states. Non-rectangular evidence masks, cross-object annotation, full evidence-to-developed-abstraction golden cycle, installed preview/export, and quality acceptance remain missing. | evidence contract; evidence compositor; provenance/readability tests; golden cycle | 5 | Partial |
| R-09 | Boards and stable objects act as creative narrative memory | Slice 3A verifies board-gap state persistence; Slice 3W binds return to the immediately preceding source activation, latest prior destination activation, and full retained object-state/version snapshot. Creative board selection, developed abstraction, and final composition remain missing. | `test_v2_return_board.py`; board-reason contract; slideshow detector; full narrative fixture | 6 | Partial |
| R-10 | Object and relationship motion explains flow, copying, synchronization, grouping, replacement, failure, causality, and emphasis | Slice 3A defines deterministic move/scale/rotate state; Slice 3D renders stroke/glyph construction; Slices 3F–3G render and connect/disconnect one semantic arrow as endpoints move. Slice 3P makes root connector endpoints follow static-group transforms through a shared world resolver. Slice 3T adds authored-object crossfade replacement; Slice 3Y adds single-path geometry morphs, destination handoff, and chained/return continuity. No automatic object invention is performed. Multi-object flow, copying, synchronization, dynamic grouping, failure, causality, and broader explanatory motion remain missing | movement/state runtime; `v2_world.py`; `v2_morph.py`; connector/connection/world/replacement/morph tests; deterministic offline frame sheet; purpose field; seek parity | 3, 6 | Partial connector/replacement/morph motion; broader semantics pending |
| R-11 | Explicit attention target, secondary context, dimming, isolation, progressive disclosure, and reading/listening priority | Slice 3J adds highlight, Slice 3K cross-out, Slice 3L explicit dim, and Slice 3M transient focus isolation with board-wide context dimming; Slice 3I provides bounded list disclosure. Automatic focus/context choice, reading/listening priority, and a complete choreography validator remain missing | `v2_state.py`; `v2_svg.py`; `test_v2_highlight_action.py`; `test_v2_cross_out_action.py`; `test_v2_dim_action.py`; `test_v2_isolate_action.py`; attention schema/runtime; conflict validator; attention golden scenes | 6 | Partial; complete choreography missing |
| R-12 | Versioned Paper & Ink design tokens, packaged fonts, semantic colors, spacing, density, evidence, caption, motion, and format rules | Phase 2 provides strict versioned tokens, four pinned OFL fonts, both profile rules, contrast checks, deterministic proof rendering, and frozen packaging; legacy v1 remains unchanged and full v2 renderer token consumption remains Phase 3 | `production-assets/paper-ink-v2/style.json`; `paper-ink-style-v2.schema.json`; frozen `--verify-style-bundle`; Phase 2 report; Phase 3 renderer parity | 2–3 | Foundation complete; full v2 consumption pending |
| R-13 | Strong forensic plan/resolved timeline/shot/attention/evidence/continuity/quality contract is the live runtime contract | Phase 1 delivered live v2 schemas, typed models, explicit MCP/HTTP dispatch, immutable v1 migration, and safe renderer isolation. Slice 3R promotes bounded mask-source semantics into plan/layout validation while preserving old `2.0.0` masks as loadable, non-executable legacy data. Full forensic enforcement through composition, evidence, and production quality is still pending | `ATME_VISUAL_PIPELINE_PHASE_1_REPORT.md`; `contracts_v2.py`; both regenerated v2 plan/layout schemas; `test_v2_mask_contract.py`; Phase 3 runtime tests and production artifact still required | 1–8 | Contract foundation complete; runtime enforcement partial |
| R-14 | Deterministic SFX, music state, purposeful silence, transition punctuation, and narration priority | Existing audio path handles narration/media, not the complete editorial sound model | sound-event schema; mix fixtures; offline render; narration intelligibility checks | 7 | Missing |
| R-15 | Contract, compiler, renderer, visual, parity, offline, migration, performance, installed-app, and human acceptance tests | Existing suite has strong mechanical coverage but no complete rich-production golden corpus | golden project corpus; installed acceptance report; visual diffs; full requirement sign-off | 0–12 | Partial |

Slice 3X adds immutable resolved-timeline persistence and a private, verified
stored-project v2 frame-parity harness. It does not satisfy R-13's production
compiler or R-15's public preview/export and installed-app acceptance gates;
MCP timeline authoring and renderer-v2 capability remain unavailable.

Slice 3Y advances R-02/R-10 with explicit authored geometry correspondence:
canonical box/ellipse outlines, ordered polygon/line/freehand vertices, and
matching freehand path commands now execute as a single interpolated shape,
with destination identity, camera handoff, and retained board-return history.
`v2_morph.py`, `test_v2_morph_action.py`, and the retained offline frame sheet
prove this bounded source runtime. Stored initial-state and beat inventories
and cleaned duration strengthen R-13. These do not complete dynamic grouping,
annotation/count/split/sound, multi-object explanatory choreography, compiler
production routing, or R-15's installed/public-preview/export quality acceptance.

## Required golden workflows

Slice 3AA adds an audited immutable topology/world/scope foundation, shared static
frame/camera/SVG hierarchy consumers, and initial complete authored group/ungroup
receipt schemas with plan/layout checks, standalone step replay, owned initial
empty-shell and initial resolved hierarchy receipts. This advances
R-01/R-02/R-08/R-10/R-13 without claiming public transition execution: dynamic
consumer/conflict integration, retained-board hierarchy, and production
parity remain incomplete. The auditor's failed scope/consumer cases now have
regression tests. The first full updated run failed due to authored-layer/sibling
ordinal conflation; that defect is fixed with both layer-preservation and explicit
opposed-order SVG tests. The frozen `965d27c` full suite passed (1,099 tests, five
preexisting Windows symlink skips). The later shared chronology kernel advances
exact boundary source binding, active-baseline preservation and version history;
ordinary source frames use it after existing pair validation. An independent
pre-route snapshot/pixel oracle covers 27 families, 669 snapshots and 18 SVG/PNG
pairs. Its bounded independent source/docs audit passed 76 tests; the finalized
combined renderer run passed 274 tests, with unchanged offline annotation pixels.
Its fresh full regression at `37b0504` passed: 1,175 tests, five preexisting
skips, exit 0 in 1472.35 seconds. This does not prove subsequent consumer changes.
The subsequent `58947e9` slice advances R-01/R-02/R-08/R-10 with static
preflight, exact immutable captured-start temporal validation and replay-aware
camera framing. Its private group-camera fixture verifies ancestry after
ungroup/regroup and collective motion, without enabling public Group frames.
Combined tests passed 282; independent rerun passed 84 and sidecar-cwd Ruff.
Ten offline annotation frames and their contact sheet remain byte-identical.
Full session `91184` FAILED at publication source `9ec3bb4`: 9 failed,
1,170 passed, 9 skipped, exit 1 in 1298.45 seconds, retained log
`test-artifacts/phase-3aa-consumers-final-full-sidecar.log`. Six diagnostic-order
regressions and three obsolete camera spies were repaired at `365c3a0`;
399 combined tests, 117 independent cases and scoped Ruff pass. Four isolated
missing-VO-fixture skips are distinct from five baseline symlink skips. Fresh
full session `83170` PASSED frozen repaired main source `365c3a0`: 1,187 passed,
five preexisting symlink skips, 1399.88 seconds, exit 0, with those VO cases run.
Log `test-artifacts/phase-3aa-consumer-repair-full-sidecar.log`; imported
source/tests remained frozen. This proves repaired consumers, not all Phase 3.
Initial attempt `34056` stopped for a reproduced missing isolated Python
environment; its corrected resource-bundle suite passes all 30 tests. No partial
attempt is a full PASS. Exact return hierarchy receipts are now implemented at
`821acd3`, advancing R-08/R-09/R-13: complete retained board inventory, canonical
hierarchy hash and exact chronological state/version binding, atomic new-write
rejection, explicit legacy reads, duplication preservation and resolved-only schema
delivery. Independent 54-case receipt and exact integration audits PASS. Combined
main session `54572` PASSED (298 tests, 363.73 seconds, exit 0). Full session
`79529` PASSED frozen source `821acd3`: 1,241 passed, five preexisting symlink skips,
1504.30 seconds, exit 0, log `test-artifacts/phase-3aa-return-receipt-full-sidecar.log`.
Source/tests remained unchanged. This does not prove later isolated lifecycle/
paint-order changes, public Group or Phase 3 completion.
Ten integrated offline annotation frames/contact sheet remain byte-identical.
Group annotation/evidence lifetimes, effective paint order, public playback and installed acceptance remain
open; all R-01–R-15 requirements and later phases remain retained.

Slice 3Z advances R-02/R-08/R-10/R-11 with authored general annotation:
exact action/beat-owned hidden leaves, ordered weighted construction, bound
pointer anchors, immutable target state/version, readable hold and retained
pointer lifecycle. Direct SVG/PNG and stored-project tests prove source runtime
mechanics; independent contract/runtime audits and full regression passed
(980 passed, 5 preexisting Windows symlink skips, exit code 0).
Cross-object evidence treatment, final creative/readability quality, compiler
production routing, and R-15 public/installed acceptance remain open.

1. Approved script plus recording.
2. Recording-only narrative and timing authority.
3. Talking-head source video with linked audio.
4. Abstraction-only technical explanation.
5. Evidence-led technical explanation.
6. Optional sponsor insertion and a coherent sponsor-free variant.
7. 16:9 landscape composition.
8. 9:16 independently recomposed composition.
9. Manual edit followed by bounded AI revision.
10. Legacy v1 project migration and rollback.
11. Reopen, preview, revise, and render while network-isolated.

## Universal exit evidence

Every requirement needs all applicable evidence:

- **Contract:** positive and negative fixtures.
- **Traceability:** storyboard instruction to compiled object/action to preview event to rendered result.
- **Coverage:** executed, explicitly degraded, or rejected—never silently discarded.
- **Determinism:** identical inputs produce identical normalized artifacts and frames.
- **Timing:** cleaned timeline remains authoritative.
- **Continuity:** random seeking and board returns reproduce the correct state.
- **Evidence:** readable, sourced, correctly targeted, and never fabricated.
- **Parity:** preview and export agree on object state, timing, framing, audio, and captions.
- **Migration:** legacy projects remain readable and immutable history survives.
- **Offline:** saved productions preview and export without network access.
- **Performance:** long and dense fixtures meet recorded budgets.
- **Visual review:** no hard failure and at least 16/20 on the approved rubric.

## Sampled lifecycle integration checkpoint — 2026-10-04

Integrated source `cc1a6a4` is exact to isolated `21eda61`: shared annotation,
evidence and nonterminal paint-slot observers now run in both frames and new
resolved writes. No-return writes prove full consumer history; return writes
use the causal resolved-order prefix while retaining complete structural and
attested metadata. The independent bounded source audit and fresh 25-suite
regression PASS (528 tests, 406.44s, session `62255`); scoped Ruff and exact
source/test integration comparison PASS. Fresh full main sidecar session `67141`
is RUNNING on frozen `cc1a6a4`; no full result is claimed yet. Previous receipt
full `79529` remains PASS but does not cover this migration. See the lifecycle
progress report for reproduction logs and immutable offline frame hashes.
Group+annotation/private blanket removal, connector/isolate, public/stored pixels,
compiler/installed and all remaining Phase 3/4–12 gates remain open. V1, Caleb,
semantic authority, schemas and public capabilities are unchanged.
