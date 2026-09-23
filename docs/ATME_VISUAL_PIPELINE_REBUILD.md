# ATME visual-production rebuild

Status: approved and active

Started: 2026-09-20

Current phase: Phase 3 — Renderer and action runtime (Phase 2 gate passed)

## Goal

Rebuild ATME's missing visual-production pipeline so that a connected external AI can create original, research-informed Paper & Ink explainer videos with rich illustration, executable motion, evidence handling, continuity, attention choreography, sound, and production-quality validation. Preserve the existing MCP boundary, project architecture, authoritative-narrative rules, non-destructive editing, immutable revisions, and deterministic offline renderer.

## Protected invariants

These are non-regression requirements in every phase:

1. External AI is the semantic and creative authority through MCP. ATME does not add an internal LLM or user API-key workflow.
2. Both Authoritative Narrative Source modes remain supported: approved external script plus recording, and recording-only authority.
3. The accepted cleaned source timeline is downstream timing authority.
4. Source media remains immutable; edits are stored as versioned decisions.
5. Project artifacts and approvals remain revisioned and conflict-checked.
6. Preview and final export use the same composition semantics.
7. Rendering remains deterministic and works without network access after required local dependencies and media are present.
8. Manual editing, manual rendering, and bounded selected-range AI revision requests remain available.
9. MCP client identity is displayed only when the client supplies it.
10. Jev is advisory and cannot author, apply, or approve production artifacts.
11. The connected AI receives project authority through MCP only; it is not granted authority to edit ATME application source code.
12. ATME uses an original Paper & Ink identity. Research is converted into transferable functional rules, not copied artwork, wording, handwriting, branding, or creator identity.
13. Long-form 16:9 and short-form 9:16 share narrative and timing authority but are independently composed.
14. Legacy projects are migrated through versioned adapters and rollback paths, never destructive replacement.
15. Cache invalidation follows artifact dependencies and revisions.

## Locked requirements

The authoritative requirement definitions and evidence mapping live in `ATME_VISUAL_PIPELINE_TRACEABILITY.md`.

- R-01: executable visual language
- R-02: storyboard action parity
- R-03: deterministic Visual Director/Compiler
- R-04: fallback containment
- R-05: versioned research grammar exposed through MCP
- R-06: production-quality validation
- R-07: original illustration and asset system
- R-08: complete evidence pipeline
- R-09: creative continuity and board memory
- R-10: explanatory object and relationship motion
- R-11: attention choreography
- R-12: complete Paper & Ink style system
- R-13: forensic contract promoted into runtime
- R-14: sound and editorial punctuation
- R-15: production acceptance and visual tests

## Execution order

### Phase 0 — Baseline and architectural freeze

Inventory the checkout, installed state, contracts, renderer, MCP, project data, tests, and generated outputs. Reproduce the semantic-loss failure. Record protected golden behavior and performance evidence without changing production behavior.

Exit: a current baseline report, complete traceability matrix, dirty-tree inventory, test results, representative installed-project evidence, and an independent audit decision.

### Phase 1 — Runtime contract v2

Promote the stronger forensic plan, resolved timeline, shot/beat, attention, evidence, continuity, sound, fallback, coverage, and quality records into versioned live schemas. Define one canonical object and action vocabulary and a non-destructive v1 migration.

Exit: positive and negative contract fixtures, migration round trips, one contract version consumed by MCP/compiler/validator/preview/renderer, and explicit rejection of unknown actions.

### Phase 2 — Paper & Ink style and asset foundation

Create versioned design tokens, bundled render-safe fonts, semantic colors, density/spacing rules, aspect-ratio rules, and an original provenance-aware asset registry for people, gestures, devices, documents, networks, charts, technical frames, and abstract metaphors.

Exit: consistent preview/export rendering, provenance and checksum coverage, accessible typography/contrast, and no dependency on unpinned system handwriting fonts.

### Phase 3 — Renderer and action runtime

Implement all v2 primitives, groups, layers, clips, masks, anchors, transforms, opacity, object state, entry/exit, movement, relationship animation, progressive disclosure, attention states, and purposeful camera behavior on the deterministic render path.

Exit: every supported primitive/action works in preview and export, identical inputs produce identical output, random seeking matches sequential evaluation, and unsupported actions fail.

### Phase 4 — Visual Director/Compiler

Build the deterministic bridge from the external AI's semantic storyboard to executable composition. Compile narrative purpose, assets, relationships, attention, continuity, evidence, timing, style, and aspect ratio into objects and actions. Emit a coverage map for every storyboard instruction.

Exit: every instruction is executed, explicitly degraded, or rejected; no semantic field silently disappears; fallback-only scenes cannot be production-ready.

### Phase 5 — Evidence pipeline

Implement claim linking, crop/focus regions, masking, darkening, highlights, callouts, annotation targets, source labels, reading holds, provenance, and developed abstraction return.

Exit: evidence is readable, sourced, correctly targeted, never fabricated, and returns to the declared board/state.

### Phase 6 — Continuity, attention, and narrative choreography

Use boards and stable objects as narrative memory. Add declared board reasons, object-state evolution, developed returns, opening-to-conclusion resolution, attention priority, dimming, isolation, listening/reading states, progressive disclosure, density rules, and semantic pacing.

Exit: no inappropriate scene-per-board slideshow, no resurrected objects, one clear visual purpose per beat, and an observable opening-to-ending payoff.

### Phase 7 — Sound and editorial punctuation

Add deterministic SFX cues, music state, purposeful silence, transition punctuation, fades, gain, and narration-priority rules on the canonical timeline. Sponsor segments remain optional.

Exit: sound is synchronized, restrained, offline-renderable, subordinate to narration, and never based on an undeclared local semantic decision.

### Phase 8 — Production-quality gate

Validate intent coverage, fallback state, density, legibility, safe areas, off-canvas content, evidence, pacing, action execution, continuity, camera purpose, narrative resolution, audio, aspect ratio, and preview/export parity. Separate hard failures, warnings, and human-review criteria.

Exit: hard failures block production, warnings identify repair locations, no fallback-only production is approved, and human review reaches at least 16/20 with no hard failure.

### Phase 9 — MCP production grammar

Expose actual schema/capability versions, directing rules, examples, evidence/continuity/attention/fallback rules, validation, revision, preview, and render operations. Add real-time artifact notifications. Advertise only implemented capabilities.

Exit: a supported external client completes the workflow without filesystem/source-code access or API-key setup; installed ATME reflects live connection and artifact activity.

### Phase 10 — Studio integration

Wire the production pipeline into the studio: live artifact updates, renderer-backed preview, contextual inspector, validation, bounded annotations, revision review, manual edits, manual render, and AI-requested render. Keep the user workflow simpler than a general-purpose NLE.

Exit: production remains visible and playable throughout; manual and AI workflows coexist; navigation and menus do not block playback.

### Phase 11 — Format adaptation, cache correctness, and performance

Implement semantic 16:9/9:16 recomposition, revision-aware cache invalidation, and recorded performance budgets for long projects, dense scenes, live preview, and rendering.

Exit: portrait is recomposed rather than cropped; cache invalidation is correct; performance budgets pass without changing meaning or timing authority.

### Phase 12 — Migration, acceptance, packaging, and release

Run the complete golden corpus: script-plus-recording, recording-only, talking head, abstraction-only, evidence-led, optional sponsor, no sponsor, manual-plus-AI revisions, both profiles, migrated v1, and network-isolated render. Test the packaged application, not just development services.

Exit: every R-01–R-15 item passes; no unresolved P0/P1 item remains; preview/export parity, migration, determinism, offline operation, installed-app behavior, and human visual review all pass.

## Phase gate protocol

For every phase the implementer records requirements claimed complete, modules changed, schema/migration effects, tests, generated fixtures, preview/export comparisons, and limitations. The independent auditor then inspects the actual artifacts and assigns Pass, Partial, Fail, or Regression.

- Any P0 failure stops dependent work.
- A P1 partial cannot survive final acceptance.
- P2 deferral requires explicit user approval.
- A schema without executable output is incomplete.
- A passing automated test without a representative visual artifact is not visual acceptance.
- A real installed-project path must prove the final workflow.
