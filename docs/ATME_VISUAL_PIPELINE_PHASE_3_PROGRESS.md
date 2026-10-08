# Phase 3 — renderer and action runtime progress

Status: Slices 3A–3U and bounded 3V/3W/3X stages independent PASS;
Slice 3Y implementation, bounded audit, and full sidecar regression PASS;
Slice 3Z bounded annotation contract/runtime audits and full regression PASS;
Phase 3 remains incomplete

Date: 2026-10-04

## Next executable action slice

Slice 3Z implements authored general visual annotation and passed
independent contract/runtime audits and full regression. Slice 3AA is now building
the shared hierarchy and explicit transition receipt; group/ungroup execution is not yet integrated. Next are
dynamic group/ungroup, authored split results, numeric count,
and the deterministic sound-event ledger. Existing bare `annotate` text is
not enough: execution needs exact preauthored annotation object IDs, target/
leader anchors, reveal ordering, readable hold, persistence, and ownership.
No renderer-generated copy or inferred geometry is permitted. Annotation of
an evidence object must retain its attested annotation permission and must
not weaken the separate source-contained EvidenceTreatment path. Group edits
need reversible ownership/world-transform mappings; split needs explicit
result-object correspondence; count needs numeric/format policies. Sound
events are Phase 3 timing/state evidence; audible mixing remains Phase 7.
None of these priorities removes the remaining primitive, performance,
preview/export parity, compiler, or installed acceptance gates.

## Delivered in Slice 3A

- `sidecar/src/atme/render/v2_state.py` reconstructs immutable object state from exact stored v2
  layout and resolved-timeline JSON at an arbitrary millisecond. It checks the canonical layout
  hash, plan/layout/profile/style/registry identity, initial state inventory, board ownership,
  non-overlapping same-object action windows, and unsupported verbs before returning a frame.
- Supported state operations are reveal, write, draw, progressive reveal, enter, permanent exit,
  move, scale, rotate, and fade. All other canonical actions fail explicitly. The semantic kernel
  contract is in `ATME_VISUAL_PIPELINE_PHASE_3_RUNTIME_SEMANTICS.md`.
- V2 contracts now reject NaN and Infinity. An exit declares `removed`; the v1-to-v2 migration
  records this canonical mapping for legacy remove actions.
- Focused tests exercise random/backward seeking, half-open boundaries, all five easing functions,
  channel-specific and chained transforms, board gaps and returns, immutable frame/caller state,
  malformed pairings, non-finite input, overlap, and unsupported actions.

## Incomplete Phase 3 gates

- Slice 3AA has an independently audited shared immutable hierarchy foundation:
  complete canonical parent/order snapshots, cycle/depth and inventory guards,
  structural version closure including shifted siblings, exact scope checks,
  and authored world-affine/bounds/corner preservation. Thirty-two focused
  tests and Ruff pass. The auditor's undeclared-parent, undeclared-transform and
  destination-only nested-root probes were reproduced as failing tests, fixed,
  and independently rechecked. The shared snapshot is now wired into static
  frame state, pair validation, every camera validation path, and SVG paint/
  connector maps. Initial explicit complete before/after receipt models and
  new-plan/layout validators are implemented with regenerated schemas and legacy
  hash-compatible omission. The combined focused run passed 193 cases; 43 state/
  legacy tests passed, and all ten retained offline annotation frame hashes
  remained unchanged. The added paint-order negative passed in the separate
  23/23 contract suite. Independent bounded re-audit passed static consumers
  and this initial receipt-contract stage (130 independently rerun consumer
  tests and clean Ruff). Standalone authored step replay and initial empty-shell
  ownership/initial resolved basis contracts now have bounded independent audits.
  Replay preserves hidden staged descendants, applies only authored root local
  transforms and shell semantic state, and accounts for every structural version.
  Ownership binds exact action/hash and per-shell earliest completion; the shared
  project/frame gate validates initial layout parent/order/transform identity.
  Group/ungroup remain non-executable in frame evaluation until chronological
  source binding, conflicts, dynamic consumers and returns are complete.
  The first updated full run failed (45 failed, 997 passed, five preexisting
  symlink skips); projection had incorrectly replaced authored layers with dense
  sibling ordinals. This is fixed with separate authored-layer preservation and
  direct SVG snapshot-order tests. The layer/replay/morph/replacement suite passed
  155 cases; adjacent consumers passed 218; current hierarchy/ownership/replay
  tests passed 119 and Ruff is clean. The finalized combined hierarchy/ownership/
  replay/morph/replacement/visual-contract run passed 275 tests in 132.32 seconds,
  with clean Ruff; all retained offline annotation pixel hashes remain identical.
  The frozen full run against source `965d27c` passed: 1,099 passed, five
  preexisting Windows symlink skips, 1241.91 seconds, exit 0
  (`test-artifacts/phase-3aa-final-full-sidecar.log`). This predates the new
  chronological replay route and does not prove that later source change.
  Actual group/ungroup playback, returns and compositor acceptance remain open.

### Slice 3AA chronological replay follow-through (2026-10-04)

`v2_timeline_replay.py` separates committed local frame state, immutable action
start baselines, sampled boundary poses, hierarchy and versions. Ordinary ends
commit first, structural ends then apply in resolved order, and starts capture
the resulting state. Group reads the complete sampled source basis but commits
only its authored root transforms, shell state and structural version closure.
Ordinal-only shifted siblings may keep unrelated motion; their captured baseline
is never overwritten by a partial Group sample. Overlapping operator write sets
reject instead of becoming last-writer behavior. Positive completed member alpha
and legacy dim/isolate revision history are preserved.

Ordinary `evaluate_frame` sampling now uses this shared clock after all existing
pair validation. Public Group remains explicitly unsupported until public Group
camera acceptance, annotation lifetime and retained-board hierarchy consumers are complete.
This removes the duplicate start-ordered sampling loop, not the v1/Caleb renderer.
No contracts, schemas, public dispatcher or installed application changed here.

The first independent oracle run found two numeric JSON-type mismatches in enter
and replacement reveal fractions; exact legacy float literals now replace those
integers. The hash-pinned pre-route `965d27c` evaluator generates retained full
snapshot goldens, with exact input documents/hashes, evidence insertion/return,
all five camera verbs, and representative SVG/PNG byte hashes. These independent
goldens are distinct from wrapper-plumbing comparisons that use the new clock
on both sides. The final independent bounded source/docs audit passed: 76 replay
tests in 33.85 seconds and clean Ruff. The finalized combined renderer run passed
274 tests in 136.45 seconds, exit 0
(`test-artifacts/phase-3aa-chronology-final-focused.log`). The oracle retains
27 operator families, 669 complete-frame hashes and 18 SVG/PNG byte-hash pairs.
The ten offline annotation frames/contact sheet again retained their original
hashes. The fresh full regression against source `37b0504` passed: 1,175 tests,
five preexisting Windows symlink skips, 1472.35 seconds, exit 0. This is distinct
from the frozen 1,099-test baseline. Dynamic Group consumers and full Phase 3
acceptance remain open.

Fresh full regression completed against frozen source commit `37b0504`:
`pytest tests --tb=short`, unified terminal session `24270`, log
`test-artifacts/phase-3aa-chronology-full-sidecar.log`. Terminal session `24270`
returned exit 0 with the result above; imported source/tests remained frozen
throughout. This result does not cover later static/temporal or camera integration
in the separate source checkout. The installed application is unchanged.

### Slice 3AA captured-start consumer integration (2026-10-04)

Source commit `58947e9` separates static pair preflight from temporal readiness.
Malformed bindings, unsupported forms and ignored fields reject before replay
construction. One immutable chronology supplies temporal state/version checks,
annotation/evidence readiness, replacement geometry and camera framing. Camera
targets use the sampled hierarchy and local transforms and preserve the preceding
viewport; this removes the old independent start-ordered camera ledger.

`before_action(action_id)` returns the exact captured precondition, not the
operator's zero-progress painted frame. This distinction preserves evidence
insertion's legacy paint without falsely treating its hidden source as revealed.
Transform channel purity is checked against that sampled start pose. A private
ungroup/regroup, collective move and later camera fixture verifies dynamic ancestry
and viewport inheritance; public Group still explicitly rejects.

The finalized combined run passed 282 tests in 107.36 seconds. All 27 retained
legacy oracle families remain included. The main checkout reran the 84 new/replay
cases (28.65 seconds); the independent auditor reran 84 (23.32 seconds), verified
production-source equivalence to the isolated checkout, and issued bounded PASS.
Ruff passes from the canonical sidecar working directory; two test import blocks
were mechanically normalized after its first independent lint check. The ten
network-denied annotation frames/contact sheet remain byte-identical.

The initial full attempt (session `34056`) hit a reproduced environment failure:
`test_generator_is_idempotent` launches the isolated checkout's
`sidecar/.venv/Scripts/python.exe`, which did not exist. The attempt was stopped,
not counted as PASS; its partial log remains retained. A local junction to the
existing main environment fixes that path without changing test assertions.
All 30 resource-bundle tests then passed in 9.34 seconds. The test import
normalization was also copied into the isolated checkout before restarting.

Finalized full session `91184` FAILED: 9 failed, 1,170 passed, 9 skipped,
1298.45 seconds, exit 1. The retained log is
`test-artifacts/phase-3aa-consumers-final-full-sidecar.log`. Frozen isolated
source `9ec3bb4` matched main `58947e9`. Six failures exposed static diagnostic
precedence regressions; three spies still assumed the old camera API/redundant
planning. Four skips were missing ignored VO fixtures in that checkout, not the
five preexisting Windows symlink skips. This is not full PASS evidence.

Repair commit `365c3a0` restores history-independent readiness diagnostics while
retaining captured-start/history checks, and makes the spies assert one replay
and one camera plan. Four new model-valid negatives forbid clock construction.
The combined repair run passed 399 tests in 118.94 seconds; the independent
auditor reran 117 in 23.27 seconds, reviewed semantics and passed scoped Ruff.
Fresh full session `83170` PASSED against frozen repaired main source `365c3a0`:
1,187 passed, five preexisting Windows symlink skips, 1399.88 seconds, exit 0.
The original four VO integration fixtures ran instead of skipping. Log:
`test-artifacts/phase-3aa-consumer-repair-full-sidecar.log`. Imported source/tests
remained frozen throughout. This supersedes neither the failed evidence nor the
earlier independently frozen chronology result; it proves the repaired consumers.
Return receipt implementation subsequently merged at `821acd3`; its independent
54-case bounded audit and exact integration audit PASS. New resolved writes bind
complete retained-board hierarchy receipts to chronological state/version history;
legacy stored reads remain explicit. Combined main session `54572` PASSED:
298 tests in 363.73 seconds, exit 0. Full session `79529` PASSED frozen source
`821acd3`: 1,241 passed, five preexisting Windows symlink skips, 1504.30 seconds,
exit 0, log `test-artifacts/phase-3aa-return-receipt-full-sidecar.log`. Source/tests
remained unchanged. This proves receipt integration, not later isolated consumer
changes or public Group. Ten integrated offline annotation frames remain byte-identical.
See `ATME_VISUAL_PIPELINE_PHASE_3_RETURN_RECEIPT_PROGRESS.md`. Public Group remains closed.

Next: finalize receipt integration regressions, dynamic replacement/morph
paint-order validation, and Group-aware annotation/evidence construction, hold
and retained-pointer lifetimes. Only then can Group gates be removed and actual
stored-project SVG/PNG acceptance run in both profiles. Contracts/schemas,
v1/Caleb rendering and the installed app are unchanged in this bounded slice.
All remaining Phase 3 and R-01–R-15/Phase 4–12 gates remain required.

- Slice 3Z adds an optional explicit annotation policy to `TargetAction`, preserving
  legacy no-policy serialization. New plan writes require authored hidden text/
  mark leaves, exact action/beat coverage, construction order/weights, a target
  reference, optional named pointer anchors, and a retained reading hold. The
  resolved timeline constructs only the notes/leader; the target remains unchanged.
  The source compositor writes graphemes/draws strokes with phase-local easing,
  rather than generating copy or wiping a target rectangle. Hold, effective
  visibility/opacity, group paint order, world geometry, pinned text size, and
  pointer route/head guards fail closed. A retained pointer must be explicitly
  removed before an endpoint or its ancestor may change. Only note/leader state
  versions increment on board return. Evidence targets cannot bypass attested
  EvidenceTreatment. Forty contract and 42 runtime cases pass, including exact
  boundaries, pixels, random seeks, group geometry, camera handoff, offline both-
  profile frames, stored-project parity, and pointer lifecycle. Independent
  contract and runtime re-audits passed, including the corrected retained-pointer
  lifecycle and existing public v1 draft-preview isolation. Fourteen targeted
  legacy render/checkpoint/offline tests and Ruff passed. The fresh entire
  sidecar regression against finalized 3Z code passed: 980 passed, 5 skipped
  in 1340.67 seconds, exit code 0 (`test-artifacts/phase-3z-full-sidecar.log`).
  These are the preexisting Windows symlink skips; no annotation case skipped.
  This run predates the standalone 3AA hierarchy foundation and does not verify it.
  The earlier v2-selected run started before the final pointer correction and
  included one faulty head-bound test fixture, since fixed; it is superseded
  and not finalized regression evidence. Public preview/export and installed app remain
  unchanged. The retained contact sheet proves mechanics, not the final visual
  quality rubric or independently designed portrait storytelling.

- Slice 3Y adds deterministic authored geometry morphing, rather than crossfade:
  exact canonical box/ellipse outlines, ordered polygon/line/freehand vertices,
  and matching freehand M/L/Q/C commands. Shared style/ownership and explicit
  correspondence are mandatory. One path interpolates geometry, bounds,
  transform channels, and opacity; completion transfers persistent identity
  to the authored destination. Tests cover pixels, easing, random seeks,
  chains, return-state versions, camera handoff, transformed groups, static
  clip/mask parents, portrait output, legacy loading, and stored-project parity.
  Initial object inventory/state/visibility, beat anchors, and cleaned duration
  are now checked against the authoritative stored plan and source timeline.
  Independent bounded code audit passed after fixing generated schema inclusion
  and legacy morph loadability. Finalized v2-selected and legacy render/checkpoint/
  offline regressions passed: 524 passed, 5 skipped in 741.47 seconds. The skipped
  cases are preexisting Windows symlink-dependent tests; no new morph test skipped.
  Full sidecar regression passed: 898 passed, 5 skipped in 1770.36 seconds,
  exit code 0 (`test-artifacts/phase-3y-full-sidecar.log`). This is the finalized
  3Y baseline, not verification of the later 3Z annotation changes. Ruff,
  exact generated-schema/model parity, and staged whitespace checks passed.
  The retained offline contact sheet proves mechanics only, not the approved
  final visual-quality rubric. Public v2 preview/export, compiler integration,
  and installed-app acceptance remain incomplete.

- Slice 3X adds an immutable stored `resolved_timeline` artifact with exact
  plan/layout revision and hash, cleaned source-timeline, profile, style,
  registry, authored-action, coverage, fallback, asset, and compilation-
  fingerprint binding. Duplicates rebind ordinary project-asset references to
  the copied project while retaining evidence-origin references. A private
  source-only runner method composes stored-project frames from verified
  project-owned image/evidence bytes using the same v2 compositor tested by
  direct frame evaluation. It is a parity and integrity harness, not the
  public project preview: MCP/HTTP project preview and export continue to
  reject v2, renderer capabilities remain v1-only, and no installed desktop
  rebuild is claimed. The resolved timeline is not yet exposed as a writable
  MCP artifact; the Phase 4 deterministic compiler and full Phase 3 runtime
  gate must precede production routing.
  The independent source-only re-audit passed after rejecting raster objects
  without a nonblank asset ID and requiring every referenced image/evidence
  asset in the resolved inventory. Fifteen direct stored-project tests passed.
- Slice 3W adds an explicit source/prior/destination activation lineage and
  complete retained object-state/version snapshot for `return_board`. New plan
  writes and plan/layout pairing require this declaration; older incomplete
  `2.0.0` documents still parse but cannot execute. The pure frame runtime
  validates the snapshot and cuts to the reactivated board without recreating
  objects; A→B→A and same-board activation-gap returns are covered. This is
  bounded continuity mechanics, not the full evidence-to-developed-abstraction
  golden cycle, installed preview/export, or final Phase 3 acceptance. Its
  bounded independent re-audit, the v2 suite, and full sidecar regression passed.
- Slice 3V now preserves evidence-treatment intent in the v2 contract and has
  source-only evidence PNG ingestion and a separate immutable-byte resolver.
  The latter accepts only project-owned evidence assets with declared external
  provenance, matching checksum and revision, resolved usage rights, and
  explicit permitted transformations; supporting images cannot substitute.
  Uploaded originals are not deleted. Duplicating a project preserves evidence
  origin references and records separate artifact-derivation hashes without
  rewriting inherited migration receipts. The independent bounded re-audit
  passed for the ingestion stage; Windows redirect tests skipped only when
  this host denied symlink creation. The subsequent source-only compositor
  stage now draws attested exact-pixel crops with bounded focus, optional
  outside-focus darkening, source label, self-anchored annotation, and a
  rounded card in SVG/PNG. `insert_evidence` fades this immutable evidence
  object in; its authored hold requires board activation, visible/opaque
  ancestors, sufficient on-screen size and focus, camera containment, and
  a non-clipping rectangular mask/clip if declared. Undeclared rotation is
  rejected across the full timeline. Other mask shapes and annotation targets
  remain fail-closed for evidence. Slice 3V did not execute `return_board`;
  Slice 3W now requires explicit source/prior/destination activation lineage,
  returnability policy, and a complete retained-state/version snapshot.
  Old incomplete 2.0.0 evidence remains loadable but non-executable. This
  compositor stage passed `pytest -q sidecar/tests -k v2 -x`, the full
  `pytest -q sidecar/tests -x` regression, and Ruff on changed Python files.
  Its bounded independent re-audit has since passed. This slice has not been packaged into the installed sidecar, exposed via MCP,
  or connected to desktop preview/export. Do not route 3U supporting images
  through the evidence trust path.
- Slice 3U adds a bounded project-owned PNG render path. The project service
  verifies ownership, revision, managed path, metadata, checksum, and decoded
  dimensions before supplying immutable bytes to the v2 compositor. That
  compositor embeds only a validated/canonicalized RGB/RGBA PNG at authored
  bounds with contain scaling. Missing or inconsistent bytes fail closed,
  including for hidden objects. This is a standalone v2 frame path, not the
  desktop preview/export or evidence compositor. This source-only slice is
  not shipped in the currently built sidecar/Tauri binaries. Their embedded
  v2 schemas are older than the regenerated source schema; packaging and
  source/frozen schema parity remain an explicit later gate before any v2
  installed-app capability is advertised.
- Slice 3T adds deterministic `replace` crossfades for two co-located,
  same-parent, same-board authored paintable leaves. The plan and resolved
  timeline enforce distinct participants, source precondition, hidden
  destination, and visible destination post-state. Frame state removes the
  source and reveals the destination through a half-open eased opacity
  transition. Ancestor visibility, action overlaps, board activation, camera
  liveness, connector endpoints, mask-only sources, and future malformed
  actions fail closed. No morph or geometry interpolation is implied. The
  bounded slice passed independent audit and full sidecar regression;
  preview/export and full
  Phase 3 remain incomplete.

- Slice 3S executes the bounded explicit static-alpha mask contract in v2 frame
  state and SVG/PNG. Four static filled aperture geometries (rectangle, rounded
  rectangle, ellipse, polygon) compose with source transform, a stationary
  parent-local aperture, transformed masked content, opacity/visibility, and
  nested groups/clips/masks. The aperture source never paints independently.
  Invalid geometry, source actions, legacy ambiguous masks, masked camera and
  connector endpoints, dynamic/inverted/feathered/media masks, and external
  `clip_id` fail closed. Independent audit and the full sidecar regression
  passed. Desktop preview/export,
  the broader object/action matrix, and full Phase 3 remain incomplete.

- Slice 3R defined an explicit static alpha-mask source contract before 3S
  enabled bounded mask rendering. A fully specified mask declares its unique same-parent geometry
  source, parent-local coordinate space, no inversion, and no feather. The source
  is excluded from visible attention, camera, continuity, annotation, action, and
  connector roles. Plan/layout mask semantics must match. Existing `2.0.0` masks
  that omit all policy fields remain schema- and model-loadable for immutable
  revision compatibility, including parse/dump/reparse when those fields become
  `null`; they are legacy ambiguous masks and stay non-executable. Mixed or
  partial policies fail validation. External `clip_id` remains
  fail-closed: 3Q containment covers current clipping needs, while reference
  ownership/coordinate semantics remain unspecified. Preview/export integration
  and full Phase 3 acceptance remain incomplete.

- Slice 3Q adds hard-edge rectangular static clip containers. A clip is a
  non-painting local stacking context whose authored bounds crop its child
  subtree, including nested groups and clips. Local transforms, opacity,
  visibility, deterministic ordering, and animated transforms are preserved.
  Masks, external `clip_id` references, dynamic membership, connector children,
  clipped connector endpoints, and clipped camera focus still fail closed.
  This does not complete Phase 3 or enable desktop preview/export.

- Slice 3P introduces one deterministic affine resolver for the compositor's
  nested SVG transforms, camera focus bounds, and root-level connector endpoints.
  Grouped visual leaves can now be framed, and root connectors can bind to grouped
  endpoint anchors. Ancestor visibility/opacity and camera-window conflicts are
  checked. Connector objects inside groups, masks/clips, dynamic membership,
  preview/export, and full Phase 3 acceptance remain unsupported.

- Slice 3O adds authored static groups as nested, non-painting stacking contexts. Root and
  child layers sort locally; nested transforms, ancestor visibility and multiplicative
  opacity reach SVG/PNG without changing v1. Group membership is contract-checked for
  same-board ownership, bidirectional references, cycles, duplicate children, and depth.
  Dynamic group/ungroup/split actions, masks, clips, clip references, and grouped
  camera/connector geometry were explicitly unsupported at that historical
  checkpoint. Later hierarchy/mask/camera slices supersede those static limitations;
  `58947e9` adds private replay-aware group-camera consumption, not public
  Group playback. This is not final hierarchy,
  preview/export, or full Phase 3 acceptance.

- Slice 3N adds bounded purposeful-camera mechanics for all five canonical camera verbs.
  Target geometry and completed transforms define a canvas-bounded, aspect-preserving viewport;
  cut/hold are immediate, while pan/zoom/reframe use deterministic eased interpolation.
  Camera actions do not mutate target semantic state, and SVG/PNG use the same viewport.
  Invalid target visibility, incompatible geometry, overlapping camera windows or focus edits,
  and impossible framing fail closed. This is not an automatic director or a production
  preview/export integration.

- Slice 3B now emits SVG and a tested resvg PNG frame for five geometric mark types and
  text/list objects. It measures text against the pinned font, scales style tokens to the
  authored 16:9 or 9:16 output size, keeps the authored canvas origin, and rejects unsupported
  objects, ignored fields, and unsupported semantics. The PNG API
  loads verified packaged font files and disables system-font fallback. This is a
  limited compositor path, not the project's preview/export implementation.
- Slice 3C adds pinned original-registry artwork for explicitly selected icon, pictogram,
  character, device, document, chart, and terminal illustrations. All sixteen bundled assets
  are independently composited and raster-tested inside authored bounds. The bundle checksum
  is rechecked at composition; invalid family/type selection and overridden illustration
  styling fail. Arbitrary project images, video, evidence, and data-driven charts remain
  unsupported.
- Slice 3D implements `draw` as progressive SVG path stroke for the five supported mark types,
  and `write` as whole-grapheme text/list progression using the authored font and line breaks.
  The mark's fill appears at action completion. These two verbs no longer use a generic
  rectangular reveal. Ordered list disclosure is added in the later bounded Slice 3I.
  This is a limited frame-compositor capability, not desktop preview/export wiring.
- Slice 3E adds bounded `freehand` point-polylines and authored absolute M/L/Q/C path strokes.
  Its parser accepts data-only coordinates, emits sanitized path geometry, checks control points
  against authored bounds, and rejects unsupported SVG commands and invalid/degenerate paths.
  Existing `draw` progression now applies to these strokes. This does not add arbitrary SVG,
  external artwork, or full-object compositor coverage.
- Slice 3F adds bounded semantic arrows between named anchors on two same-board objects. Straight,
  elbow, and quadratic-curve routes follow endpoint movement, scale, and rotation in random-access
  frames; authored `draw` progresses the shaft and places the arrowhead only at completion.
  Free-source pointers, network objects, independent connector transforms, hidden endpoints,
  cross-board bindings, and out-of-bounds routes remain rejected. This does not implement the
  full network-layout engine.
- Slice 3G adds canonical `connect`/`disconnect` actions for that arrow subset. The resolved
  timeline now treats source/destination as checked references, not objects mutated by a
  connection. Exact static binding and canonical disconnected→connected→disconnected state
  transitions are required; connect draws the shaft/arrowhead and disconnect retracts it.
  Managed connector initial visibility must match its relationship state, and unrelated
  target/transform actions cannot move or redraw it independently. Neither verb broadens
  support to free-source pointers or general networks. State evaluation and SVG composition
  share one static arrow support gate, so unsupported self-loops, connector endpoints, and
  ignored connector styling cannot pass state evaluation but fail at rendering.
- Slice 3H adds bounded authored `underline` and `highlight` mark objects. The former is one
  curved accent stroke; the latter is a slightly asymmetric attention-color emphasis ring.
  Both use exact authored bounds, pinned style tokens, and stroke-progressive `draw` timing,
  with fill, injected path data, ignored points, and unknown color tokens rejected. These are
  explicit visual objects, not by themselves execution of a `highlight` action or an
  automatic attention director. A bounded target action follows in Slice 3J.
- Slice 3I implements `progressive_reveal` only for an authored, initially hidden `list`
  text object with stored ordered items. The heading appears after progression begins; complete
  items arrive at eased equal fractions of the action window, without cropped glyphs or a
  generic reveal rectangle. The full list is measured against the pinned font and authored
  bounds before the compositor returns a frame. State and SVG share one nonblank/single-line item gate,
  including Unicode line separators. Reusing a previously touched list or targeting a
  non-list object fails closed. The action requires canonical hidden→visible states. General
  ordered-child/group reveal is still unavailable.
- Slice 3J implements a bounded `highlight` target action on an already-visible, untouched
  supported mark or text object. It draws a deterministic attention ring over the target during
  the action and leaves the underlying content visible and unchanged. The target must be on the
  active board and declare the canonical visible→highlighted state transition. The completed
  ring follows the target's existing transform and persists. Connectors, illustrations, hidden
  or previously acted-on targets, and subsequent actions on that target fail closed. This is
  one explicit attention cue, not dimming, isolation, or an automatic attention director.
- Slice 3K implements `cross_out` as two sequential hand-drawn attention strokes over a
  visible, untouched supported mark or text object. The original content remains intact, while
  the strokes persist and follow the target's existing transform. Exact visible→crossed_out
  states, an active board window, and terminal target ownership are required. This is a
  correction cue, not automatic semantic revision or removal.
- Slice 3L implements `dim` as a temporary, deterministic attention cue for visible supported
  marks/text. It lowers opacity to 35% of the authored value, holds, then restores the exact
  value at the action end. It does not leave a dimmed state behind. Multiple unique targets
  and repeated non-overlapping dim windows are supported; hidden targets, prior edits, step
  easing, and board-crossing windows fail closed. Slice 3L alone does not implement isolation
  or an automatic attention director; explicit isolation follows in Slice 3M.
- Slice 3M implements an explicit `isolate` focus action on supported marks, text, and pinned
  registry illustrations. It temporarily dims all other visible objects on that board and
  restores their pre-action opacity exactly. It can focus a previously revealed object; same-
  board visual actions cannot overlap the isolation window, because they would conflict with
  context ownership. A fully revealed focus and at least one visible non-focus context object
  are required, so no-op isolation fails closed. This does not choose focus automatically or
  implement full choreography.
- No audio events are produced by the kernel. The full 35-type primitive/container
  compositor, asset/media resolution, remaining canonical action verbs, camera/board composition,
  and real project preview/export dispatcher are still required.
- The current application continues to report renderer v1 and rejects v2 layouts for public
  project preview/export. The Slice 3X source-only method does not alter this gate.
- Real-project preview/export parity, frozen/offline execution, and representative production
  acceptance remain outstanding; proof-render parity from Phase 2 is not a substitute.

## Verification

- Slice 3A focused tests: 30 passed.
- Combined v2 contract/frame-state tests: pass.
- Ruff on touched Python: pass.
- Full sidecar regression: passed after Slice 3B (2026-09-23).
- Slice 3B focused SVG/raster tests: 21 passed; 51 combined frame-state/compositor tests passed.
- Independent Slice 3B decision: PASS for the declared primitive subset; not full Phase 3.
- Slice 3C focused illustration tests: 38 passed; 119 combined Phase 2/3 renderer tests passed.
- Independent Slice 3C decision: PASS for verified bundled illustrations and the strict SVG subset;
  not full Phase 3. The auditor separately rechecked the nested-viewport hardening. The full
  sidecar regression passed against the finalized Slice 3C files (2026-09-23).
- Slice 3D focused SVG/raster tests: 29 passed, including all five supported draw paths,
  random/backward seek parity, incompatible-target rejection, zero-length path rejection,
  and combining-character text writing. The independent auditor passed the bounded gate after
  97 combined Phase 3 tests, 13 targeted v1/offline-render tests, and Ruff. The full sidecar
  regression also passed with exit code 0 against the finalized Slice 3D files (2026-09-23).
- Slice 3E focused freehand/SVG tests and Ruff passed. The independent auditor passed the
  bounded gate after rechecking coordinate overflow, serialized zero-length paths, malformed
  inputs, future/hidden path rejection, and deterministic seek/raster output; 79 focused tests
  passed in its separate run. The full sidecar regression passed against the finalized 3E files
  with exit code 0 (2026-09-23).
- Slice 3F focused connector/SVG tests and Ruff passed. The independent auditor passed the
  bounded gate after 72 connector/SVG/frame-state tests, 12 targeted v1/offline-render tests,
  and checks for effective endpoint visibility, fractional transform parity, bounds, routing,
  and deterministic seeking. The full sidecar regression passed against finalized 3F files
  with exit code 0 (2026-09-23).
- Slice 3G: 85 focused connection/connector/state/contract tests and Ruff passed. The
  independent auditor passed the bounded gate, including shared fail-closed validation,
  random-access deterministic seeking, and 13 targeted v1/offline-render regressions.
  The full sidecar regression passed with exit code 0 against finalized Slice 3G files
  (2026-09-23). No full Phase 3 or installed-app claim follows.
- Slice 3H: 89 focused emphasis/SVG/state/freehand tests and Ruff passed in the independent
  audit. The auditor also passed 13 targeted v1/offline-render regressions and found no bounded
  blocker. The full sidecar regression passed with exit code 0 against finalized Slice 3H
  files (2026-09-23); no installed-app or full Phase 3 claim follows.
- Slice 3I: the independent auditor passed the bounded gate after the blank/Unicode-line-break
  and noncanonical completed-state gaps were fixed. Its final 82-test focused state/SVG/list
  run, Ruff, and 13 targeted v1/offline-render regressions passed. The full sidecar regression
  passed with exit code 0 against the final state guard (2026-09-23). This is not a full Phase 3
  gate completion claim.
- Slice 3J: independent bounded audit PASS after 79 focused highlight/emphasis/SVG/state
  tests, Ruff, and 13 targeted v1/offline-render regressions. The full sidecar regression
  passed with exit code 0 against finalized Slice 3J files (2026-09-23). No full Phase 3 or
  installed-app claim follows.
- Slice 3K: independent bounded audit PASS after 89 focused cross-out/highlight/emphasis/SVG/state
  tests, Ruff, and 13 targeted v1/offline-render regressions. The full sidecar regression
  passed with exit code 0 against finalized Slice 3K files (2026-09-23). This is not full
  Phase 3 or installed-app acceptance.
- Slice 3L: independent bounded audit PASS after its 90-test focused state/SVG/attention run,
  Ruff, and 12 targeted v1/offline-render regressions. The main focused set passed 100 tests.
  The full sidecar regression passed with exit code 0 against finalized Slice 3L files
  (2026-09-23). This is not full Phase 3 or installed-app acceptance.
- Slice 3M: independent bounded audit PASS after the focus-readiness and real-context guards
  were added. Sixteen direct isolation tests, the broader attention/renderer-focused suite,
  Ruff, and targeted v1/offline-render regressions passed. The full sidecar regression passed
  with exit code 0 against finalized Slice 3M files (2026-09-23). This is not full Phase 3
  or installed-app acceptance.
- Slice 3N: independent bounded audit PASS after all five camera verbs, transformed and
  portrait target geometry, random seeks, SVG/PNG parity, framing mismatch, safe-area,
  overlap and invalid-target guards were verified. The auditor's focused state/compositor
  set passed 73 tests, Ruff passed, and 14 targeted v1 render/checkpoint/offline tests
  passed. This is not full Phase 3 or installed-app acceptance.
- Slice 3O: independent bounded re-audit PASS after fixing shared frame/SVG hierarchy
  rejection, `GroupAction.container_id` references, and snapshot field semantics. The
  auditor verified 41 focused group/camera/connector tests, Ruff, and direct unsupported
  hierarchy probes. The main 13-case group suite and targeted legacy render/checkpoint/
  offline regression passed. This is not full Phase 3 or installed-app acceptance.
- Slice 3P: independent bounded re-audit PASS after shared nested affine geometry,
  four-decimal SVG/world-bounds parity, and finite/bounded transform guards were
  verified. The auditor passed 68 focused world/group/camera/connector/connection
  tests and Ruff. The main v2-selected suite and 14 targeted legacy render/
  checkpoint/offline tests passed with exit code 0. This is not full Phase 3 or
  installed-app acceptance.
- Slice 3Q: independent bounded audit PASS for static hard-edge clip containers,
  local-coordinate raster crop, nested intersection, group/clip nesting,
  transformed and animated clips, opacity/visibility, deterministic seeking,
  and fail-closed mask/external-clip/camera/connector boundaries. The auditor's
  focused set passed 63 tests and Ruff. The main v2-selected suite, nine direct
  clip tests, Ruff, and 14 targeted legacy render/checkpoint/offline tests
  passed. This is not full Phase 3 or installed-app acceptance.
- Slice 3S: independent bounded audit PASS; no state, SVG/PNG,
  nesting, deterministic-seek, or v1-isolation defect. The auditor's focused
  mask contract/compositor set passed 58 tests and Ruff; 14 targeted legacy
  renderer/offline tests passed. The main v2-selected suite, 25 direct
  compositor cases, 12 render smoke/checkpoint cases, and two offline render
  cases passed. The full sidecar regression passed with exit code 0 against
  finalized Slice 3S files, and the final documentation re-audit passed.
  This is not full Phase 3 or installed-app acceptance.
- Slice 3T: independent bounded audit PASS. Twenty-eight direct
  authored-replacement tests passed, including PNG/SVG,
  random seek, exact boundaries and easing, chain and board return, camera,
  plan-level rejection, ancestor visibility/overlap, later destination edits,
  portrait output, and connector-endpoint rejection. The v2-selected suite,
  14 targeted legacy/offline tests, Ruff, and the full sidecar regression
  passed with exit code 0 against finalized Slice 3T files. Schemas remain
  equivalent to the checked-in generated JSON; this is not full Phase 3 or
  installed-app acceptance.
- Slice 3U: independent bounded source-only audit PASS after correcting
  unproven provenance/rotation claims and duplicate-project shared-asset
  resolution. Eleven direct PNG/project-asset tests, a targeted legacy
  supporting-asset/narrative-authority test, and Ruff passed in the independent
  run. The finalized v2-selected suite, targeted legacy render/checkpoint/
  offline tests, and full sidecar regression also passed with exit code 0.
  Source/frozen schema parity and desktop v2 preview/export are later
  gates; this is not full Phase 3 or installed-app acceptance.
- Slice 3V (contract stage): independent behavioral re-audit found no remaining
  evidence-contract gap after normal storyboard writes began requiring exact
  EvidenceIntent/object/insert-action inventory, immutable source snapshot,
  verified provenance/checksum, reference-only nonfabrication, permitted
  crop/annotation/color treatment, bounded source geometry, and a post-insert
  readable hold within the destination board activation. Older 2.0.0 plans
  with incomplete evidence snapshots remain loadable, but cannot pass new
  writes or become executable; the v1 migration path has an explicit legacy
  compatibility exception and remains recorded unsupported. Thirty-two
  direct evidence tests, the visual-contract suite, the v2-selected suite,
  and Ruff passed. This stage preserves and validates forensic intent only:
  evidence-specific asset attestation, action execution, raster/SVG pixels,
  desktop integration, and full production acceptance remain open.
- Slice 3V (ingestion/lineage stage): independent bounded re-audit PASS for
  declared evidence-only PNG ingestion, immutable byte resolution, project
  containment and duplicate-project evidence origin, plus separately recorded
  derivation hashes that preserve inherited migration receipts. Focused tests
  and sidecar Ruff passed. Redirect tests skip where Windows denies symlink
  creation; a stronger hostile same-user filesystem model would require
  handle-based final-path verification. Evidence placement and pixels, MCP
  upload, installed desktop integration, and full Phase 3 acceptance remain
  open. Full sidecar regression is not yet confirmed for this slice.
- Slice 3R: independent bounded audit PASS for explicit static-alpha mask
  contracts, unique non-painted geometry ownership, schema/model parity,
  preserved old `2.0.0` mask loading and parse/dump/reparse, mixed-policy
  rejection, and fail-closed mask rendering. Thirty-three direct contract
  cases and Ruff passed. Mask composition was added in Slice 3S;
  this is not full Phase 3 or installed-app acceptance.
- Slice 3X: independent bounded source-only audit PASS after exact resolved-
  timeline persistence, verified project raster composition, duplicate-project
  asset rebinding, and nonblank raster-asset enforcement. Fifteen direct
  stored-project tests, the finalized v2-selected suite, Ruff, and the full
  sidecar regression against finalized Slice 3X files passed with exit code 0.
  Public preview/export and installed-app acceptance remain closed.
- Independent Slice 3A decision: PASS. The auditor repeated the focused and v2-contract tests,
  Ruff, non-finite rejection, exact-boundary and chained-state checks, and confirmed that no v2
  production capability is falsely advertised.

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
Frozen initial focused worker38448 is running; correction re-audit and the full
Count matrix/Group/attention/glyph/store/return/duplicate/offline proofs remain.
No Count integration, advertisement, installation or full-Phase3 claim. The approved
R01–R15/Phase4–12 scope is unchanged.
