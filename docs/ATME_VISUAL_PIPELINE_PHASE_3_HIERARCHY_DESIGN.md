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
baselines. Still required before public Group execution: action-aware dynamic
camera/conflict handling, retained
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
verification. Dynamic camera source evaluation, retained-pointer lifetimes,
full board-return hierarchy receipts, stored grouping SVG/PNG proof and installed
production acceptance remain incomplete. No new schema or v1 behavior changed.

## Required acceptance

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
