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

Phase 3AA checkpoint (2026-10-04): shared hierarchy, standalone authored replay,
empty-shell ownership and initial resolved receipts have bounded verification.
The first full updated run exposed a repaired layer/order projection regression;
the frozen `965d27c` rerun passed (1,099 tests, five preexisting skips). Ordinary
frame sampling now uses a shared chronological replay kernel; its bounded
independent source/docs audit passed 76 tests, the combined renderer run passed
274 tests, and the offline annotation proof remained byte-identical. Its pinned
pre-route oracle and fresh full regression are separate gates; the latter passed
at `37b0504` (1,175 tests, five preexisting skips, exit 0 in 1472.35 seconds).
At `58947e9`, static/temporal validation and replay-aware camera planning have
bounded independent PASS: 282 combined tests, 84 independently rerun cases,
clean sidecar-cwd Ruff and unchanged ten-frame offline annotation proof. Private
group-camera ancestry/collective-motion verification is not public Group playback.
Full session `91184` FAILED at publication source `9ec3bb4`: 9 failed,
1,170 passed, 9 skipped, 1298.45 seconds, exit 1
(`test-artifacts/phase-3aa-consumers-final-full-sidecar.log`). Repair `365c3a0`
restores six diagnostic-precedence boundaries and updates three obsolete camera
spies: 399 combined tests, 117 independent tests and scoped Ruff pass. Four
isolated missing-VO-fixture skips are not baseline symlink skips. Fresh full
session `83170` PASSED frozen repaired main source `365c3a0`: 1,187 passed,
five preexisting symlink skips, 1399.88 seconds, exit 0, with those VO cases run.
Log `test-artifacts/phase-3aa-consumer-repair-full-sidecar.log`; imported
source/tests remained frozen. This is repaired-consumer regression acceptance,
not full Phase 3 or installed-app acceptance.
Initial attempt `34056` stopped for a reproduced missing isolated Python
environment; all 30 resource-bundle tests pass after the local environment repair.
Exact retained-board return receipts subsequently merged at `821acd3`; independent
54-case bounded receipt audit and exact integration audit PASS. New writes prove
complete hierarchy/state/version history, stored legacy reads remain explicit,
and only resolved-timeline schema changed. Ten integrated offline frames remain
unchanged. Combined main session `54572` PASSED: 298 tests, 363.73 seconds, exit 0.
Full session `79529` PASSED frozen source `821acd3`: 1,241 passed, five preexisting
symlink skips, 1504.30 seconds, exit 0, log
`test-artifacts/phase-3aa-return-receipt-full-sidecar.log`. Source/tests remained
unchanged; later isolated lifecycle/paint-order work is not covered by this result.
See the return-receipt progress report for exact scope and evidence.
Dynamic grouping annotation/evidence lifetimes,
effective paint-order guards, production playback, compiler
integration and all remaining Phase 3/4–12 requirements are still open. See the
Phase 3 hierarchy design, remaining matrix and R-01–R-15 ledger for scope.

For every phase the implementer records requirements claimed complete, modules changed, schema/migration effects, tests, generated fixtures, preview/export comparisons, and limitations. The independent auditor then inspects the actual artifacts and assigns Pass, Partial, Fail, or Regression.

- Any P0 failure stops dependent work.
- A P1 partial cannot survive final acceptance.
- P2 deferral requires explicit user approval.
- A schema without executable output is incomplete.
- A passing automated test without a representative visual artifact is not visual acceptance.
- A real installed-project path must prove the final workflow.

## Sampled lifecycle integration checkpoint — 2026-10-04

Integrated source `cc1a6a4` is exact to isolated `21eda61`: shared annotation,
evidence and nonterminal paint-slot observers now run in both frames and new
resolved writes. No-return writes prove full consumer history; return writes
use the causal resolved-order prefix while retaining complete structural and
attested metadata. The independent bounded source audit and fresh 25-suite
regression PASS (528 tests, 406.44s, session `62255`); scoped Ruff and exact
source/test integration comparison PASS. Fresh full main sidecar session `67141`
PASSED frozen `cc1a6a4`: 1,281 passed, five preexisting Windows symlink skips,
1768.25 seconds, terminal exit 0. Retained log
`test-artifacts/phase-3aa-lifecycle-full-sidecar.log`, SHA256
`CBE1DAFFDC60F174D3ADB4434A5F4E9C7C221A22CD84C4E0D1BFE880F6E453F1`.
Main source/tests stayed frozen. This does not certify the later paired
Group/annotation slice. Previous receipt
full `79529` remains PASS but does not cover this migration. See the lifecycle
progress report for reproduction logs and immutable offline frame hashes.
Group+annotation/private blanket removal, connector/isolate, public/stored pixels,
compiler/installed and all remaining Phase 3/4–12 gates remain open. V1, Caleb,
semantic authority, schemas and public capabilities are unchanged.

## Paired Group/annotation integration checkpoint — 2026-10-04

Source `2c21c2c` integrates audited isolated `7b93db0` exactly: private Group/
ungroup, construction/hold/retained-pointer lifetimes and the shared sampled
SVG/PNG path have bounded independent PASS (37 cases), combined PASS (617 tests,
672.25s), scoped Ruff PASS and 40 deterministic offline paired frames. Ten prior
annotation frame/report hashes remain unchanged. Full main run `56029` completed:
1,318 passed, five existing Windows symlink skips, 1866.02s, on frozen `2c21c2c`.
The terminal log and empty source/tests/schema/bench diff were verified on resume;
the original process handle had expired, so its OS exit status was not captured.
Log SHA256: `D8C7AABA5FBC9143AA7F127700090C5FDCE36EC3B1A592266456FC9CB5BA48DC`.
The earlier 1,281-test full PASS at `cc1a6a4` is a separate source boundary.
Public Group and causal stored Group+annotation
admission remain closed; real stored/duplicate/return receipts and connector/
isolate follow-through remain required. This is private mechanical proof, not
Caleb-style creative acceptance, Phase 3 completion or an installed release.
See the paired Group/annotation progress report and its next stored-project map.

## Stored Group/annotation integration checkpoint — 2026-10-05

Source `eb811ce` integrates isolated `3f037ac` plus documentation follow-through:
real stored Group/ungroup and authored note/leader A/B/A receipts, atomic coherent
stale claims, duplicate identity/hash/authority rebinding, same-time causal order
and full no-return histories. Both independently authored profiles have stored
and duplicate private offline pixel proof. Focused61 plus four no-return cases,
the49-suite1,046-pass regression (five existing Windows symlink skips), scoped
Ruff and independent bounded implementation audit PASS. All10+40 previous
JSON/PNG hashes remain unchanged. Primary exact integration comparison is empty;
independent exact-integration audit PASS. Full main `24031` stopped during
continuation at 95% without terminal summary/exit marker; it is not acceptance.
The preserved log SHA256 is `120D1C5B3DFEEC40CFED1D716D7D8A4AD2BF65FD91AE4C27BB4578205021DDC8`.
Process absence and missing handle were verified before restart. A hidden,
continuation-safe full worker PID10628 PASSED on frozen `eb811ce`:1,346 passed,
five existing Windows symlink skips,2420.49s, explicit terminal exit0 at2026-10-05
21:15:23UTC. Log `phase-3ab-stored-pair-full-sidecar-rerun.log`, SHA256
`33F5E96C65A3FDEAF3336CE8C8F73063A0BFA1F9F812CEF555256BC0B2368884`.
Final source/tests/schema/bench freeze is empty. Previous1,318-pass full run
covers only `2c21c2c`. Connector `4a11891` has focused151 and broader1,106
PASS/five existing Windows symlink skips with explicit exit0; final independent
source/evidence acceptance PASS. Replacement/morph tracked724e7fc has60 PASS,
160.34s, explicit exit0, log SHA256
`4E9E38AEB3B8B309562071A3D52978070B264825F53DC10C36F2F2DFFD42D328`.
Both are integrated exactly as main `6c83b86ef9441603bade71ca51844254e62df996`;
independent exact-integration PASS, scoped Ruff PASS. All10public+40private
annotation JSON/PNG hashes reproduced unchanged. Hidden full main worker20316
completed at frozen6c83b86:1,466 PASS/five existing Windows symlink skips,2779.95s,
explicit exit0 at2026-10-06 11:40:14UTC. Log
`phase-3ad-group-connection-replacement-full-sidecar.log`, SHA256
`4C41F4764D812C07A2322FC3C91033234958CF575FB2245BDEF4560AACA328D4`.
Final source/tests/schema/bench freeze empty; worker absence verified. This is the
connector/replacement source boundary, not later Isolate or installed acceptance.
The blanket causal paired storage rejection is removed, not the sampled history
validators or public Group admission. Public preview/export, post-Group connector/
isolate/replace/morph, other Phase3 primitives/actions, compiler/installed and all
Phase4–12 requirements remain. No v1/Caleb, schema, database, MCP or capability
change; no creative or full Phase3 acceptance. See the stored-pair progress report.


## Next isolated hierarchy consumer — 2026-10-06

Hierarchy-aware Isolate candidatea74526f remains isolated, not integrated or
installed. It captures maximal context roots from actual hierarchy, preserves
focus/ancestor/mask alpha and exact restoration, and closes independently found
retained-pointer/evidence-hold lifetime conflicts. Frozen7832905 focused193 and
broader1,217 PASS/five existing Windows symlink skips, explicit exit0; freeze/log
hashes and worker absence verified. Added cross-board/two-mask3 cases and hardened
stored4 cases PASS; independent bounded implementation/evidence audit PASS,
including its independent7-case rerun56.44s. Production unchanged after783; final
tracked focused worker18172 is running on exacta74526f.50 old offline hashes stay
identical. Main's connector/replacement full1,466 PASS covers only6c83b86. Exact
Isolate integration/full regression remain; no public/installed/creative/Phase3/
Phase4–12 gate is waived.


## Hierarchy-aware Isolate integration checkpoint — 2026-10-07

Mainf97a850 integrates the exact independently accepted isolatedd152a43 result:
actual sampled focus/ancestor/aperture protection, maximal single-dim context roots,
exact transient restoration and focus-only versions, readable-hold/retained-pointer
conflicts, cross-board independence and nested-mask closure. Frozen193/1,217 proof
(five existing Windows skips in the broader run), final tracked196 PASS and an
independent7-case rerun56.44s certify the bounded source/test slices. Independent
exact-integration audit and scoped Ruff PASS;50 previous offline hashes unchanged.
Final196 log SHA2567B60B49EECC313C6727BE30E85F5F0E10CF5D6CCBD305FCFEB6CC46228762970.
Fresh hidden full worker17772 PASSED on frozenf97a850:1,520 PASS/five existing
Windows symlink skips,2866.49s, explicit exit0 at2026-10-07 23:24:43UTC. Log
phase-3ae-hierarchy-isolate-full-sidecar.log, SHA256
44C2FB1B56733096B4DF94DB7940FCE0975123CCB14224108A0B0F9FAF512CAD.
Final source/tests/schema/bench freeze empty and original worker stopped. The old
1,466-pass run covers only6c83b86; no later Count source is certified. Public Group/
validated compositor provenance, all remaining Phase3 primitives/actions and
Phase4–12 gates remain. No installed rebuild or creative-quality acceptance.
See the Isolate progress report and independently cross-referenced Count/Split map.


## Next isolated Count consumer — 2026-10-08

Isolated9914a8c implements explicit decimal policy, exact integer-clock steps,
Count-only immutable text/rational provenance and canonical visible→visible state.
Independent pre-freeze FAIL exposed rounded numeric-chain discontinuity, ignored
step easing and non-Count frame serialization drift; all are reproduced and
corrected, not hidden by new goldens. Corrected Count/replay124 PASS includes all
27 untouched legacy frame/SVG/PNG families; migration/read/new-write4 PASS and
scoped Ruff PASS. Two schemas are extended without rewriting legacy examples.
Initial isolated9914 focused255 passed,233.14s, explicit exit0. Expandedaa352
adds Group/subtype/glyph/storage proof; broader1,312 passed/five existing Windows
symlink skips,2117.64s, explicit exit0. However focused297 had296 passed/one native
morph rasterizer failure, and its exact repeat crashed with a WER-confirmed
Windows execute access violation. The native root cause remains unconfirmed.
Dump-enabled replay-only20, same-process raster-prefix/replay142 and unchanged
legacy27 golden-family arms passed; these bounded negative reproductions do not
clear the failures. The further41 candidate acceptance tests passed106.34s,
including actual Count glyph pixels, hierarchy/mask/connector and coherent stored
chronology/policy/return atomics, exact schemas and numeric boundaries. They are
now promoted as isolatedb7d9bbf: tracked41 passed53.78s and independent exact
promotion/functional audits PASS. Instrumented297 also passed347.00s with106
valid raster inputs, still negative reproduction evidence only. Count remains
isolated from main and cannot be packaged based
on a later green retry alone. Native diagnostic/final integration gates remain.
No Count integration, advertisement, installation or full-Phase3 claim. The approved
R01–R15/Phase4–12 scope is unchanged.
