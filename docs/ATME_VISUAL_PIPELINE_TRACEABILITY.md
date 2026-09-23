# ATME visual-production traceability

Status: active requirements ledger

Owner: primary implementation agent

Independent verifier: `/root/independent_plan_auditor`

This ledger is the phase gate. A requirement remains incomplete until its contract, implementation, validation, automated evidence, and representative visual artifact all exist. Paths under **Current evidence** describe the Phase 0 checkout; they are not claims of completion.

| ID | Required final behavior | Current evidence and gap | Planned authoritative evidence | Phase | Status |
|---|---|---|---|---:|---|
| R-01 | Rich executable objects: freehand paths, geometry, callouts, pictograms, characters, media, lists, charts, technical frames, groups, masks, anchors, transforms, layers, and state | V2 typed scene graph and fixtures now define the complete object vocabulary; v1 renderer remains isolated and v2 execution is intentionally blocked | `schemas/executable-layout-v2.schema.json`; `contracts_v2.py`; golden/negative fixtures; Phase 3 primitive renders | 1–3 | Contract-defined; implementation pending |
| R-02 | One canonical executable action vocabulary from storyboard through export | V2 strict discriminated actions now cover object, relationship, camera, attention, evidence, and sound actions; unknown/mismatched verbs fail; execution remains Phase 3 | `schemas/visual-plan-v2.schema.json`; resolved timeline schema; negative fixtures; Phase 3 per-action renders | 1, 3 | Contract-defined; implementation pending |
| R-03 | Deterministic Visual Director/Compiler converts semantic intent to executable composition without an internal LLM | `board_compiler.py` assigns existing objects/timing but does not create the requested composition; `agents/board_planner.py` is obsolete | compiler IR; coverage map; compile diagnostics; rich-storyboard golden output | 4 | Missing |
| R-04 | Fallbacks are reason-coded, visible, bounded, and cannot silently become final production | `render/autolayout.py` generates generic boxes/arrows and current validation can accept them | fallback records; degraded-preview state; user exception record; blocking validator fixture | 4, 8 | Missing |
| R-05 | Connected AI receives versioned, original research-derived directing grammar and truthful capabilities through MCP | `mcp_server.py` exposes schemas and broad instructions but not the complete visual grammar or coverage contract | MCP resources; capabilities manifest; client E2E trace; unsupported-capability rejection | 9 | Partial |
| R-06 | Production quality validates semantic coverage, density, legibility, pacing, evidence, continuity, narrative resolution, and parity | Current validation primarily checks structure, dependencies, timing, and freshness | validation codes; failing fixtures; repair locations; 16/20 human rubric record | 8 | Missing |
| R-07 | Original, provenance-aware Paper & Ink illustration and asset families | Phase 2 now bundles sixteen original assets across all eight families with semantic anchors, pinned manifests, provenance, checksums, and visual matrices; runtime selection and per-beat composition remain Phases 3–4 | `production-assets/paper-ink-v2/asset-registry.json`; `style_bundle.py`; four visual-acceptance sheets; Phase 2 report; Phase 3–4 execution proof | 2–4 | Foundation complete; production composition pending |
| R-08 | Complete claim-to-evidence-to-annotated-return cycle | Evidence PNG/provenance and board return exist, but focus, crop, mask, source label, target annotation, and quality checks are incomplete | evidence contract; evidence compositor; provenance/readability tests; golden cycle | 5 | Partial |
| R-09 | Boards and stable objects act as creative narrative memory | Board activation/return mechanics exist, but generated output can default to one disposable board per scene | board-reason contract; slideshow detector; state-return tests; full narrative fixture | 6 | Partial |
| R-10 | Object and relationship motion explains flow, copying, synchronization, grouping, replacement, failure, causality, and emphasis | Current motion is chiefly draw/reveal plus camera interpolation | movement/state runtime; purpose field; deterministic motion fixtures; seek parity | 3, 6 | Missing |
| R-11 | Explicit attention target, secondary context, dimming, isolation, progressive disclosure, and reading/listening priority | Temporary visibility is possible but no complete attention model or choreography validator exists | attention schema/runtime; conflict validator; attention golden scenes | 6 | Missing |
| R-12 | Versioned Paper & Ink design tokens, packaged fonts, semantic colors, spacing, density, evidence, caption, motion, and format rules | Phase 2 provides strict versioned tokens, four pinned OFL fonts, both profile rules, contrast checks, deterministic proof rendering, and frozen packaging; legacy v1 remains unchanged and full v2 renderer token consumption remains Phase 3 | `production-assets/paper-ink-v2/style.json`; `paper-ink-style-v2.schema.json`; frozen `--verify-style-bundle`; Phase 2 report; Phase 3 renderer parity | 2–3 | Foundation complete; full v2 consumption pending |
| R-13 | Strong forensic plan/resolved timeline/shot/attention/evidence/continuity/quality contract is the live runtime contract | Three live v2 production schemas plus a migration-report schema, typed models, explicit MCP/HTTP dispatch, additive contract metadata, deterministic immutable v1 migration, fixtures, and safe v1/v2 renderer isolation are implemented and independently audited | `ATME_VISUAL_PIPELINE_PHASE_1_REPORT.md`; schemas/models/migration; 87 dedicated tests; 357-test full regression; independent PASS | 1 | Complete |
| R-14 | Deterministic SFX, music state, purposeful silence, transition punctuation, and narration priority | Existing audio path handles narration/media, not the complete editorial sound model | sound-event schema; mix fixtures; offline render; narration intelligibility checks | 7 | Missing |
| R-15 | Contract, compiler, renderer, visual, parity, offline, migration, performance, installed-app, and human acceptance tests | Existing suite has strong mechanical coverage but no complete rich-production golden corpus | golden project corpus; installed acceptance report; visual diffs; full requirement sign-off | 0–12 | Partial |

## Required golden workflows

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
