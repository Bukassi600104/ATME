# Phase 1 — runtime contract v2 report

Status: complete; independent audit PASS

Date: 2026-09-21

## Outcome

Phase 1 establishes an additive, versioned visual-production contract family without changing
legacy v1 rendering behavior. The live runtime now distinguishes semantic intent, executable
layout, and resolved timing instead of reducing all three to boxes and generic draw commands.

The v2 renderer is intentionally not claimed in this phase. MCP, HTTP, project storage, validation,
preview/export readiness, and migration all dispatch on explicit versions. V2 artifacts are accepted
and retained, but the current renderer reports `renderer_contract_unsupported` until Phase 3.

## Contract set

1. `visual-plan-v2.schema.json`
   - narrative authority and cleaned-timeline dependency;
   - independent output profile;
   - style/asset registry versions;
   - stable assets, objects, boards, beats, actions, attention, continuity, evidence, camera, sound,
     fallbacks, and instruction coverage.
2. `executable-layout-v2.schema.json`
   - typed scene graph with geometry, transforms, style references, anchors, parent/group/clip links,
     connectors, deterministic z-order, and half-open board activations.
3. `resolved-visual-timeline-v2.schema.json`
   - immutable plan/layout/timing fingerprints;
   - resolved assets and initial states;
   - canonical actions with word/phrase timing evidence, confidence, and half-open intervals;
   - coverage, fallback, and structured validation state.
4. `migration-report-v2.schema.json`
   - source/output hashes and revisions;
   - inserted, inferred, unsupported, and degraded fields;
   - warnings and lossless/lossy status.

## Canonical action vocabulary

The strict union covers reveal, write, draw, enter, exit, move, scale, rotate, fade, highlight,
dim, isolate, connect, disconnect, replace, morph, cross-out, annotate, group, ungroup, split,
count, progressive reveal, evidence insertion, board return, camera hold/cut/pan/zoom/reframe,
sound cues, music state, and purposeful silence. Unknown verbs and verb/payload mismatches fail.

No Phase 1 code maps an unknown v2 action to `draw`. The existing v1 builder remains isolated for
legacy compatibility and is scheduled for replacement by the Phase 4 Visual Director/Compiler.

## Object vocabulary

The typed contract covers freehand marks, lines, arrows, rectangles, rounded rectangles, ellipses,
polygons, brackets, underlines, highlights, callouts, text, lists, icons, pictograms, characters,
images, evidence, charts, comparisons, browser/application/terminal/code/document frames, devices,
servers, databases, folders, networks, groups, masks, clips, compositions, and instances.

## Migration and persistence

- V1 schemas and models are unchanged and remain renderable.
- Migration accepts only explicit v1 plan/layout documents.
- It creates new immutable v2 storyboard and layout revisions in one transaction.
- Original v1 revisions remain addressable and unchanged.
- Both v2 revisions store the same migration report.
- Migration IDs and output are deterministic for the same inputs and context.
- Unsupported v1 semantics are rejected or recorded as degradation; none are invented.
- Project duplication copies contract metadata and migration evidence additively.

## Runtime dispatch

- `atme.get_schema` accepts an explicit version.
- Capabilities separately report authoring versions `[1, 2.0.0]` and renderer versions `[1]`.
- Project writes select schemas from the document's explicit `contract_version`.
- V2 plan/layout writes verify project revision, plan revision, and plan hash.
- Revision proposals use the submitted document's declared version.
- Preview/export validation blocks v2 until the v2 renderer exists.
- New schemas are automatically bundled because the frozen sidecar packages the complete schema tree.

## Validation implemented

The contract/model layer rejects unknown versions/types/actions, extra properties, duplicate IDs,
missing references, wrong action payloads, cyclic parents, invalid connectors/anchors/self-loops,
unknown boards/assets, overlapping activations, profile/canvas mismatch, low-confidence exact timing,
out-of-duration/non-monotonic actions, deleted-object resurrection, state precondition failures,
camera intent without purpose, attention conflicts, density violations, unverifiable evidence,
unknown style/asset versions, unexplained evidence annotation omission, incomplete coverage,
coverage/fallback state disagreement, plan-to-layout semantic drift, unresolved production-blocking
fallbacks, and v1/v2 cross-routing. Word, phrase, absolute, beat-start, and prior-action triggers are
discriminated contracts; resolved timing must preserve the authored trigger and its ordering evidence.
Objects, actions, and coverage records are each owned by exactly one beat; continuity, evidence masks,
and sound assets are closed references. Parent links resolve only to containers, clip links resolve only
to masks/clips, and executable layouts must preserve every semantic object and board directing field.
Resolved timelines carry explicit beat and alignment anchors so trigger offsets can be verified rather
than inferred from an untrusted timestamp.

## Automated evidence

- Golden JSON Schema and typed-model agreement for all three v2 contracts.
- Rich plan fixture with evidence, attention, continuity, sound intent, fallback and coverage.
- Rich executable-layout fixture.
- Resolved timeline fixture with alignment confidence and production-ready state.
- Negative contract matrix in `sidecar/tests/test_visual_contracts_v2.py`.
- Deterministic immutable migration proof covering every legacy action, both output profiles,
  bound/unbound arrows, evidence, dense-board rejection, and complete default/inference reporting.
- Project-service storage, plan/layout semantic-preservation, and all-entry renderer-isolation proof.
- Service migration history preservation proof.
- Existing v1 contract, MCP, project, preview, renderer, and source-authority regression coverage.
- Phase 1 contract/MCP suite: 87 passed against source and 87 passed against the rebuilt frozen sidecar.
- Full sidecar test suite: 357 collected and passed on 2026-09-21.
- Production desktop TypeScript/Vite build: passed on 2026-09-21.
- Ruff on touched Python files: passed with `--no-cache`.

## Packaged-runtime evidence

- `app/sync-sidecar.ps1` rebuilt the PyInstaller onedir sidecar and synchronized the complete runtime
  into `app/src-tauri/binaries`.
- A real stdio MCP client launched `sidecar-dist/atme-sidecar/atme-sidecar.exe` and retrieved the v2
  storyboard, layout, resolved-timeline, and migration-report schemas.
- The same frozen session reported authoring versions `[1, 2.0.0]`, renderer versions `[1]`, and did
  not claim v2 rendering.
- Source, frozen-sidecar, and Tauri-bundled schema hashes match:
  - visual plan: `16AB6FC66AC8AA4AB5B33B59809A632B07404E76949D00470746E1849462323E`;
  - executable layout: `9E427C9F3C67EA3515C4FF7B8F9913140939C344B1E8A42AF4A827AC9B19ABFB`;
  - resolved visual timeline: `682AB0DCBF5FA30D6EC2B0BC5179469DC825E9E986598574D6A07B5E33937CEE`;
  - migration report: `575AA5C61B9E11C2F1921FADBDE38F1ED5A8D57E1F802E64BDBF51A422CA09EB`.

## Requirement claims

- R-01: contract-defined; runtime rendering remains Phase 3.
- R-02: contract-defined with strict canonical vocabulary; action execution remains Phase 3.
- R-13: implemented for live schemas, typed models, version dispatch, immutable migration, storage,
  truthful capabilities, and v1/v2 renderer isolation.

## Independent gate

`/root/independent_plan_auditor` returned **PASS** on 2026-09-21 after two correction cycles. Its
final probes confirmed rejection of every formerly accepted-invalid ownership, continuity, evidence,
sound, parent/clip, trigger, fallback, coverage, and plan-to-layout mutation case. It also confirmed
frozen packaging, MCP capability truthfulness, migration cross-validation, and renderer isolation.

## Known limitations carried forward

- V2 visual output is not rendered in Phase 1; this is explicitly blocked, not degraded.
- Style and asset version names are reserved but their registries and render assets arrive in Phase 2.
- The deterministic Visual Director/Compiler arrives in Phase 4.
- Cross-stage state/coverage validation will deepen as the renderer and compiler become executable.
