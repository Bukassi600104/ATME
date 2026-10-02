# Phase 3AA — authored hierarchy transition design

Date: 2026-10-02

Status: shared immutable topology foundation audited; static consumer integration
and initial complete receipt contract implemented and bounded re-audit PASS. Transition
action execution, empty-shell ownership, continuity and acceptance are not complete.
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

Still required before execution: resolved-boundary source-basis equality with
CURRENT completed transforms, unique ownership receipts for initial empty shells,
chronological transition replay, action-aware camera/conflict handling, retained
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

## Required acceptance

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
