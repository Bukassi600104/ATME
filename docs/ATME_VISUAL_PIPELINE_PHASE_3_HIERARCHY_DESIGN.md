# Phase 3AA — authored hierarchy transition design

Date: 2026-10-02

Status: shared immutable topology/static consumers, complete transition receipts,
standalone step replay, owned initial empty shells and initial resolved receipts
implemented with bounded independent audits. Chronological action execution,
dynamic consumers, continuity and production acceptance are not complete.
This is not a replacement for the approved rebuild or the remaining runtime
matrix. Group/ungroup remain non-executable until the whole path is verified.

## Required transition, not a semantic label

The existing `GroupAction(target_ids, container_id)` does not declare enough
information to change ownership. Add a compatibility-preserving explicit policy
for group/ungroup; retain old bare actions for reading/migration, but reject them
on new writes/execution. Split has separate authored-result semantics and is not
implemented by grouping.

The policy must declare ordered member roots, the same-board nonpainting group,
exact source/destination parent and sibling placement, authored local transforms,
the affected subtree closure, and world-transform preservation. Complete affected
parent child-order inventories must prevent duplicate, missing or colliding
sibling placements. No memberships, inverses, fragments or transform mappings
may be invented by the renderer. Source snapshots must match the completed
hierarchy, not merely the original layout. Reversal must restore exact declared
ownership/order/transforms. The initial layout stays immutable.

A group shell may start empty only when explicitly owned by an executable
transition policy; orphan empty groups and empty clips/masks reject. Grouping
is a structural step at the resolved action end, not a partial grouping wipe.
Member visual states/paint remain unchanged while group state changes between
canonical ungrouped/grouped states. Initial and resulting paint order, world
affines and all subtree corners must preserve authored appearance.

## One shared hierarchy for every consumer

`render/v2_hierarchy.py` now supplies frozen canonical nodes with exact parent,
board and sibling ordinal, bidirectional initial membership checks, complete
inventory/permutation validation, cycle/depth guards, and transient object maps
that cannot mutate stored layout. It derives initial sibling order from the same
`(z_index, object_id)` ordering as the current compositor. It compares authored
before/after world affines, bounds and individual corners, through the existing
four-decimal world/SVG math, with a pinned 1e-4 design-unit tolerance. It never
computes an inferred destination transform.

World-preservation validation necessarily calls the transition-scope validator:
member roots cannot nest in either snapshot; only those roots may change parents
or local transforms. Other siblings retain relative order, with explained dense
ordinal shifts tracked for versions. Descendant inventories remain exact in both
snapshots, and all other local transforms remain field-identical. This closes the
auditor's reproductions of undeclared reparenting/transform edits and destination-
only nested roots. The focused foundation suite has 32 cases including these
negative probes and either side of the serialized geometry tolerance. The original
audit was PARTIAL. The independent re-audit passed all 32 cases and Ruff and
manually confirmed all three original fail-open probes now reject. This PASS
is restricted to the standalone foundation, not action/compositor integration.

FrameSnapshot now owns the shared initial hierarchy. Pair validation and all
annotation/evidence camera checks receive that same snapshot; state visibility,
world bounds, camera geometry and SVG paint/connector maps project it rather than
rebuilding their own parent inventory. Synthetic non-executable projection tests
check connector ancestry and the paint tree; annotation/evidence identity tests
cover paths the first integration test missed. This is static wiring, not yet an
evaluated group/ungroup transition. World mappings that the current transform
representation cannot express must reject explicitly; do not approximate shear
or flatten descendants. Any retained representational limit must remain visible
in coverage and the runtime matrix, not be treated as completion of richer plans.

## State and conflicts

The initial contract now carries complete canonical `HierarchyBasis` before/after
placements and local transforms on `GroupAction.hierarchy_policy`, with hashes of
their normalized finite JSON, ordered member roots, derived structural-version
IDs, and explicit world preservation. A complete basis unambiguously includes all
parent child orders (including root and empty parents); there is no contradictory
compact second mapping. Old bare actions preserve their original serialized shape.
New plan/layout gates reject missing policies. Layout geometry validates exact
scope, world preservation, full structural change receipt, opaque nonpainting
shell, effective leaf paint order, and aperture/evidence ownership constraints.
The semantic-plan container check no longer mistakes a semantic declaration for
an executable ContainerObject.

The standalone chronology kernel now proves exact resolved-boundary source-basis
equality with CURRENT sampled transforms while preserving unrelated active
baselines. Private replay-aware dynamic camera/conflict handling now has bounded
PASS; public Group camera routing/production acceptance remains required, with retained
board parent/order expectations, and integrated preview/export parity. The new
schema data and pure validators do not claim those gates complete. Split remains
separate; the grouping policy rejects a split action rather than ignoring it.

Track exact hierarchy/state-version changes, including affected subtree and
sibling-order changes. Developed-board returns need an explicit complete parent/
sibling expectation in addition to semantic states/versions. A moved subtree must
not appear restored merely because its leaves still say visible.

Transitions must fit an active board and cannot overlap mutations of members,
container, subtrees or ancestors. Camera, connector construction, annotation
holds/pointer lifetimes and evidence treatment constraints must participate in
the same conflict analysis. No implicit clip/mask/evidence reparenting or source
ownership change is permitted. Preserve existing public v1 preview/export and
Caleb-derived behavior. The private stored v2 runner is the first integration
proof; public/installed routing remains a later gate.

## Current bounded verification

The combined hierarchy/receipt/annotation/evidence/camera/connector run passed
193 tests in 71.62 seconds; adding the leaf-paint-order negative produced a
separate 23/23 contract PASS. Forty-three state/legacy render tests passed in
182.29 seconds. Ruff is clean. Re-running the ten retained offline annotation
frames and contact sheet produced byte-for-byte identical hashes. The independent
auditor reran 130 consumer tests and Ruff and passed static consumer wiring and
the initial receipt stage, not dynamic group execution. The full updated 3AA
sidecar regression remains required; the earlier 980-test run proves 3Z only.

### Replay and ownership contract follow-through

The standalone `v2_hierarchy_replay.py` applies exact authored member-root local
transforms, changes only the shell's semantic state, and increments the complete
structural version closure. Its input frames, layout and receipts remain immutable.
Readiness applies to member roots and their ancestor chains, not every descendant:
hidden staged leaves preserve their state, paint and local transforms while their
structural versions advance. Invalid numeric frame paint/transform data rejects.
Translated/rotated/scaled multi-root grouping and nested-parent ungrouping have
explicit authored compensation tests. Moved connector subtrees reject already at
plan/layout validation, until inverse-parent connector semantics exist.

Layout `initial_empty_group_ownership` binds each initially empty group to its
real group action and exact source-basis hash. Empty clips/masks, orphan shells,
duplicate owners and nonpainting/visibility/state violations reject. Plan binding
and resolved per-shell earliest-completion checks reject swapped/later owners.
Resolved `initial_hierarchy_basis` and its hash preserve exact layout parents,
sibling ordinals and local transforms; both stored-project and direct frame
preflight validate them. Policy-bearing GroupActions require the receipt and
change only shell semantic state, leaving heterogeneous member states intact.
Absent additive fields are omitted, preserving pre-change model dump hashes.
A valid initial basis without a hierarchy action is allowed as explicit static
hierarchy provenance; it is still pair-validated, never ignored. An owner's later
complete source basis may differ from initial after authored prior actions;
chronological replay, not a static equality shortcut, must prove that boundary.

The first full 3AA run at `7ea4d0b` failed: 45 failed, 997 passed, five preexisting
Windows symlink skips, in 1325.44 seconds. Every failure traced to projection
overwriting shared authored `z_index` with unique sibling ordinals, breaking
replacement/morph layer identity. The fix preserves authored layers and makes
SVG use snapshot sibling ordinals directly. A reproduced layer-identity failure
and an opposed-layer/sibling SVG regression lock both meanings separately.
The layer/replay/morph/replacement run passed 155 tests; adjacent renderer
consumers passed 218. The updated hierarchy/ownership/replay set passed 119
tests and Ruff. Independent bounded audits passed the replay, layer separation,
and ownership boundary. The finalized combined hierarchy/ownership/replay/
morph/replacement/visual-contract suite passed 275 tests in 132.32 seconds, with
clean Ruff. Re-running the ten offline annotation frames and contact sheet
preserved every retained byte hash. The frozen full run against source commit
`965d27c` passed: 1,099 tests, five preexisting Windows symlink skips, 1241.91
seconds, exit 0 (`test-artifacts/phase-3aa-final-full-sidecar.log`). No standalone
step or accepted schema implies chronological frame execution, installed preview,
public export, or Phase 3 completion.

### Shared clock integration stage

The ordinary source evaluator now uses `v2_timeline_replay.py` after unchanged
pair validation; Group remains explicitly rejected by that evaluator. The clock
orders ordinary completions, Group completions by resolved index, then starts.
Each active action retains a serialized immutable contract and captured start
frame tuple. Group validates the full sampled boundary basis but commits only
member-root locals, shell semantic state, hierarchy and structural versions.
Do not confuse ordinal-only version changes with geometric conflict dependencies.
Same-object owned-write overlaps reject; unrelated shifted siblings can animate
through Group without double interpolation. Shell alpha remains exactly one;
positive faded roots/ancestors are not normalized. Group must have an actual
active destination sample, not end at project/activation exhaustion.

The frozen pre-route full regression is baseline evidence only. Independent
snapshot/pixel goldens come from the exact hash-pinned old evaluator, retain the
input documents/hashes, and include evidence insertion/return and all camera
verbs. The final bounded independent source/docs audit passed 76 replay tests
and Ruff; the finalized combined renderer run passed 274 tests. The ten offline
annotation frames/contact sheet remain byte-identical. The fresh full suite for
the changed chronology route at `37b0504` passed: 1,175 tests, five preexisting
skips, exit 0 in 1472.35 seconds. Later consumer integration requires its own
verification. Private replay-aware camera source evaluation is now bounded PASS;
public Group camera execution/stored acceptance, retained-pointer lifetimes,
full board-return hierarchy receipts, stored grouping SVG/PNG proof and installed
production acceptance remain incomplete. No new schema or v1 behavior changed.

## Required acceptance

### Next resolved-return receipt implementation contract

The independent next-step assessment places the compiler receipt on
`ResolvedAction`, not `EvidenceAction`: semantic plan/layout action equality
must remain unchanged. An optional `return_hierarchy_receipt` must be omitted
when absent, preserving old 2.0.0 canonical dumps/hashes. A receipt on any other
action rejects. It binds action ID, destination board and destination activation,
one complete destination-board-only `HierarchyBasis` (parent, sibling ordinal
and local transform for every owned object), and its canonical SHA-256.

Typed/static validation must verify hash, identity, exact state/version key
inventory and complete same-board parent/order closure. Pairing binds the layout
board inventory, never the initial layout transforms: completed hierarchy edits
may legitimately change the retained board. Normal ProjectService resolved
writes require the receipt; legacy stored reads remain compatible. Group plus
return must always fail closed without it. Duplication/rebinding preserves it
byte-for-byte; it contains no project ID.

At the return's captured start, compare exact states, versions and the canonical
destination-board-only sampled hierarchy/local transforms. A return observes and
cuts to retained work; it never resets transforms, hierarchy or state. Share this
comparison between replay and frame temporal validation, not another history
ledger. After that consumer is verified, remove only the standalone Group+return
rejection, retaining Group+annotation and public Group gates.

Regenerate the resolved-timeline schema only; semantic-plan/layout schemas must
not acquire this compiler receipt. Acceptance must cover legacy omitted hashes,
normal missing-receipt write rejection, A-to-B-to-A after group and after ungroup,
boundary ordering, random seeks, duplicate preservation, and
continued public Group rejection. Negatives: missing/extra inventory, wrong
action/board/activation, parent/order/local transform/hash/state/version, stale
prior activation and off-board edits. Retained legacy return oracle and v1
behavior must remain unchanged. A source Group must finish strictly before its
activation ends; a cross-board Group-end exactly at return-start is therefore
invalid, not a positive fixture. Prove retained completed Groups and valid
ordinary-end/return-start ordering without weakening activation guards.
This contract is now implemented in source at `821acd3`, with independent bounded
receipt and integration PASS (54 focused tests). The complete board-only retained
basis is checked by the shared chronological observer; new writes reject absent
or stale receipts atomically and legacy stored preview explicitly opts into read
compatibility. Only the private Group+return rejection changed; Group+annotation
and public Group remain closed. Combined session `54572` PASSED: 298 tests,
363.73 seconds, exit 0. Full session `79529` PASSED frozen source `821acd3`:
1,241 passed, five preexisting symlink skips, 1504.30 seconds, exit 0. Log
`test-artifacts/phase-3aa-return-receipt-full-sidecar.log`; source/tests remained
unchanged. Later isolated lifecycle/paint-order changes are not covered. See the return-receipt progress report.

Captured-start consumer integration at `58947e9` completes the bounded source
portion of steps 1 and 2 below: static preflight, one immutable replay, temporal
readiness/state/version consumers and replay-aware camera planning. Private
ungroup/regroup plus collective motion verifies dynamic camera ancestry and
viewport inheritance; it does not enable public Group playback. The combined
282-case run passed, independent main recheck passed 84 and Ruff, and ten offline
annotation frame hashes/contact sheet are unchanged. Full session `91184`
FAILED at frozen source `9ec3bb4`: 9 failed, 1,170 passed, 9 skipped, exit 1
in 1298.45 seconds (`test-artifacts/phase-3aa-consumers-final-full-sidecar.log`).
Six diagnostic-precedence regressions and three obsolete camera spies were
repaired at `365c3a0`: 399 combined tests and 117 independent cases pass with
clean scoped Ruff. The four missing-fixture skips in the isolated checkout are
not baseline symlink skips. Fresh full session `83170` PASSED frozen repaired
main source `365c3a0`: 1,187 passed, five preexisting symlink skips, 1399.88 seconds,
exit 0. The four VO fixture cases ran. Log:
`test-artifacts/phase-3aa-consumer-repair-full-sidecar.log`. Imported source/tests
remained unchanged throughout; the earlier failed run stays failure evidence.
The initial attempt
`34056` stopped for a reproduced missing local Python environment; a local
environment junction restores all 30 resource-bundle tests. Frozen source/tests
are Git-identical to main `58947e9`. Steps 3–5, dynamic
effective paint-order checks, and all public/compiler/installed acceptance remain
open. No contracts or schemas changed in this slice.

### Next coherent integration slice: one replay, all temporal consumers

The independent read-only integration assessment identified four separate stale
history consumers: `v2_camera.camera_segments` (initial parents and start-ordered
transforms), the temporal half of `v2_state._validate_pair` (annotation/evidence/
replace/connect/attention/transform readiness), its retained-board state/version
loop, and retained annotation endpoint lifetime checks. Removing only the Group
gate would leave each of these incorrect. The accepted order remains:

1. Separate static pair preflight from temporal validation. Construct the shared
   immutable replay once after safe identity/inventory/policy preflight, then use
   it for all readiness/history checks; do not add another state ledger.
2. Supply camera planning with replay samples at each camera start, including the
   sampled hierarchy and local transforms. Preserve viewport inheritance and all
   existing framing guards; reject geometrically related overlapping Group edits,
   not unrelated ordinal-only shifted siblings.
3. Add a legacy-omitted resolved return hierarchy receipt: complete destination-
   board parent/order/local-transform inventory and canonical hash. New writes
   requiring that receipt must bind it to exact state/version history. A return
   observes the board, never resets it; semantic plan intent is not an executable
   transform receipt. Regenerate the resolved schema and test old serialization.
4. Migrate annotation construction/hold/retained leader lifetime, evidence
   readability/apertures, replace/morph co-parent geometry, connector ancestry,
   attention and transform preconditions to the same replay. Replace the current
   blanket container/isolate rejection with faithful hierarchy-aware validation
   or retain an explicit unsupported combination until it is implemented.
5. Only after those consumers pass, remove the standalone Group+annotation/return
   rejection and the evaluator Group gate. Exercise stored-project SVG/PNG frames
   in both profiles, random/backward seeks, exact end-before-start boundaries,
   group/ungroup world preservation, and offline execution. Preserve all 27 legacy
   oracle families and the v1/Caleb regression. Public production/compiler and
   installed-app acceptance remain separate gates.

Required negatives include Group during camera focus, annotation construction/
hold/retention or evidence reading; changed endpoint ancestry; stale/missing/extra
return inventory/hash/parent/order/local transform/state/version; and invalid
post-Group replacement/morph parentage. Required positives include a camera or
annotation starting at Group completion, return after completed group/ungroup,
retained leader exit before later Group, and unrelated sibling motion through the
structural boundary. This sequence does not remove any R-01–R-15 or Phase 4–12 work.

### Independent next-consumer assessment after receipt integration

The independent read-only assessment confirms SVG already projects sampled
hierarchy and sibling ordinals. Do not replace its compositor or remove gates to
hide stale validators. The remaining source defects are:

- Annotation temporal checks reuse the captured-start projected objects and
  transforms at construction end and hold end. Retained pointer dependency chains
  are frozen at that same start. Runtime geometry calls the plan-time annotation
  layout helper, which rebuilds initial `(z_index, object_id)` order instead of
  accepting sampled hierarchy order.
- Evidence temporal checks freeze ancestry, opacity, world geometry and aperture
  at insert start, while camera sampling advances. Group conflict checks only
  cover the action interval, not its extended readable hold.
- Replacement/morph validates sampled parentage but still equates authored layer
  identity with effective stacking position. Hierarchy-aware isolate is separately
  unsupported: dimming every non-focus object also dims the focus's ancestors.

Implementation order remains one shared replay, no extra history ledger:

1. Add read-only lifecycle sampling at captured pre-start, construction end,
   hold end minus one, and relevant Group start/completion boundaries. Preserve
   half-open rules: Group completion at consumer start and Group start at hold
   end are allowed; related overlap within construction/hold rejects. Geometric
   dependencies are not the ordinal-only structural version closure.
2. Add sampled paint-order proofs without overwriting authored layers. Annotation
   target precedes every note/leader. Replacement alternatives share sampled
   parent, authored layer and consecutive nonterminal paint slots.
3. Migrate annotation geometry/readiness and completed notes throughout hold.
   Recompute retained leader/endpoint chains through later hierarchy boundaries;
   related changes require a fully completed solo leader exit. Unrelated Group
   remains valid when relative paint order and geometry remain unchanged.
4. Migrate evidence chain, rotation permission, apertures, geometry, opacity and
   camera readability at every lifecycle sample. Preserve all attestation rules.
5. Apply replacement/morph sampled slots, then connector ancestry and separately
   hierarchy-aware isolate. Only remove the private Group+annotation blanket
   after complete consumer proofs; public Group still needs stored SVG/PNG,
   both profiles, seek/offline and full acceptance.

The compatibility-safe replacement slot view removes only canonical terminal
leaves (`state == "removed"` and `visible is False`), never hidden, zero-opacity,
zero-reveal or inactive authored leaves. Always retain the current source and
destination. Either adjacent orientation remains valid. This preserves the
existing chain whose removed first source lies between later alternatives, while
rejecting an intervening future leaf. Keep every leaf in receipts and state/
version inventory; this view is not source deletion. Explicitly reject a sampled
removed-but-visible leaf before filtering: current models do not universally
enforce that invariant. Add a model-valid negative instead of relying on another
guard. Only temporal validation
can apply this rule, not plan/static checks that lack chronological state.

Required positives: post-Group annotation/evidence at exact completion; unrelated
Group during hold and pointer retention; completed leader exit before endpoint
edits; post-Group adjacent replacement/morph; valid removed-source chains; random
and backward seeks; both-profile SVG/PNG. Required negatives: related Group in
construction/hold/retention, stale endpoint ancestry or annotation paint order,
changed evidence aperture, intervening nonterminal replacement leaf, and Group
starting one millisecond before hold end. Existing stale receipt negatives remain.
This is an audited implementation map, not delivered consumer functionality.
Receipt integration full session `79529` subsequently PASSED frozen source
`821acd3` (1,241 passed, five preexisting symlink skips, 1504.30 seconds, exit 0).
It does not certify the consumer work described here.

Prove real grouping and later collective transforms, exact ungroup roundtrips,
nested/nonidentity parent geometry, overlapping-leaf paint order, camera and
connector handoff, annotation lifecycle conflicts, retained-board hierarchy and
versions, stored-project parity, immutable random seeking, both profiles, actual
SVG/PNG pixels, offline frames and v1 regressions. Negative cases must cover stale
source ownership/order/transforms, incomplete destination inventory, nested or
duplicate members, cycles/depth, cross-board transitions, invalid shells, non-step
events, unrepresentable/world-changing transforms, forbidden aperture/evidence
ownership and conflicts. All other Phase 3 primitives/actions and later phases
remain required.

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
