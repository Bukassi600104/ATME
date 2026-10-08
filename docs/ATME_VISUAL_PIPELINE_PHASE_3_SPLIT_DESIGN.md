# Phase 3 Split — dedicated authored visual operation

Date: 2026-10-08

Status: design proposal following approval of the dedicated operator approach;
written-contract review is required before the implementation plan/runtime work.
This is not delivered Split behavior or Phase 3 acceptance.

## Intent and preservation boundary

Split changes one named visible visual into an ordered set of distinct,
preauthored result visuals. It is not an editor clip cut, Group/ungroup parent
transfer, fragment generator, or internal creative/research operation. External
AI owns the visual meaning and authors every source/result, correspondence,
phase, pose and asset. ATME validates and executes that authored instruction.

Preserve the existing stack, MCP/project model, Authoritative Narrative Source,
cleaned timing authority, immutable source media/revisions, deterministic offline
rendering, v1/Caleb behavior, and the full R01–R15/Phase 4–12 scope.

## Chosen boundary and alternatives

Use one dedicated `SplitAction` in `CanonicalAction`. Its policy and receipts are
atomic from semantic plan through resolved execution and stored board return.
Existing fade/draw/write/reveal/move samplers may implement private phases, but
must not replace the canonical Split identity with unrelated public actions.
Such replacement would lose correspondence, ownership, version and return proof.

## Legacy compatibility and new-write rules

- Remove only the `split` discriminator from `GroupAction`; leave Group/ungroup
  semantics unchanged. Exactly one union member owns `verb: "split"`.
- `SplitAction` preserves the existing ActionBase fields, `target_ids` and optional
  `container_id`. It explicitly declares `hierarchy_policy: None = None`, accepts
  absent/null values and omits that field on canonical serialization, matching
  today's Group serializer. Non-null values reject. An absent/null new
  `split_policy` is also omitted on serialization.
- Bare old Group-shaped Split documents retain canonical parse/dump shape and
  hashes. They remain non-executable; new semantic writes reject a missing policy.
- A non-null Group hierarchy policy on Split still rejects. No automatic conversion
  to Group/ungroup, replacement, guessed result objects or inferred fragments.
- A policy-bearing action has exactly one `target_id`, equal to its source ID,
  no `container_id`, a required captured source pre-state, `post_state: "removed"`,
  and outer `easing: "linear"`. Named per-phase easing owns the actual animation;
  no other outer easing may be silently ignored.

## Strict policy and immutable participant binding

`SplitPolicy` contains `source_object_id`, `parent_policy`, one `source_exit` phase,
an ordered `results` inventory of 2–256 entries, its ordered `correspondences`, and
a complete `source_basis` plus its canonical SHA256. Each result entry names its object, correspondence binding,
construction phase/mode, optional movement phase and explicit destination pose.
Every ID must be nonblank, unique and already present in the authored layout.
The source cannot be a result. Source/result owned closures are pairwise disjoint:
no source inside a result, result inside the source, nested result roots, shared
owned node or duplicate expanded instance identity. All participants belong to
the same active board. Inventory order is semantic/construction order, not paint
order; paint order remains the actual authored sibling/layer order.

An explicit `parent_policy` is required: `common_parent` binds one sampled parent
for all roots; `authored_distinct_parents` binds each exact sampled parent chain,
world transform and clip/mask handoff separately. Neither option reparents an
object. A distinct-parent adapter requires its own proof before admission; it is
part of the complete required runtime matrix, not an implicit unsupported default.

`SplitBasis` records the source/result ownership closures, their actual parent
and sibling ordinal, local transform, world placement, pre-state, visibility,
reveal/opacity, state version and immutable content identity. Read dependencies
(ancestors, apertures, anchors and asset/style pins) are bound separately and
must also match the captured start. Limits follow existing hierarchy inventories:
at most 4096 distinct bound objects; no arbitrary new payload subclasses.

Three distinct immutable receipts prevent mutable pose/state from masquerading
as content identity:

- `content_sha256` hashes the family's canonical content projection: authored
  geometry/path/text/items/parts, immutable compound membership and child content
  identities, effective completed Count text/exact rational or Morph geometry,
  and pinned style/registry/asset payloads. It excludes local/world transforms,
  placement/ordinal, visibility, reveal, opacity, semantic state/version and global
  sample time. Compound membership is an ID-sorted content inventory; actual sibling
  paint order belongs to the captured basis, not this stable digest. Family-specific
  projections must be explicit and complete; unknown
  fields or payload subclasses cannot be silently dropped. Count provenance and
  immutable assets retain their separate originating receipt/revision bindings.
- `source_basis_sha256` hashes the complete captured content identities plus
  source/result closure topology, parent/ordinal, local/world placement, state,
  effective visibility, reveal/opacity, versions and read-dependency inventory.
  It excludes only observation time. Matching content alone does not authorize a
  stale basis or a changed ancestor/aperture.
- `completion_sha256` hashes a canonical final receipt derived from that basis
  and the authored policy: source removed/nonpainted, all result states/final
  transforms/paint fields, exact root versions, unchanged owned descendant local
  records, hierarchy/dependency identities and stable content digests. The receipt
  is stored with resolved execution and rechecked on replay/return; author-supplied
  final hashes are assertions to validate, not an alternative execution oracle.

JSON uses sorted keys, compact separators and existing finite-number canonical
rules. Project assets retain immutable asset ID, revision, resource URI and checksum
bindings. Pose equality uses the existing canonical transform quantization before
hashing/comparison, not a new tolerance or raw binary-float equality.

`correspondences` is an ordered array with exactly one row per ordered result.
Each strict row contains unique `correspondence_id`, `source_object_id`,
`source_content_sha256`, `result_object_id`, `result_content_sha256`,
`relationship: "authored_assertion"`, and a nonblank `statement` of at most 512
characters. Its result ID/order must exactly match the results inventory; no
extra/missing rows or duplicate IDs are accepted. Result entries reference their
row's correspondence ID rather than embedding conflicting duplicate definitions.
An optional `source_region` is an explicit finite positive-area local rectangle
contained in the sampled source content bounds. It authorizes no pixel crop,
fragment generation or transformation. The statement is preserved for provenance;
ATME validates IDs, digests, order and geometry, never interprets the statement as
proof of semantic correspondence. No creative decision branches on its text.

## State, phases and clock

- Source is actually/effectively visible, fully revealed and has positive alpha
  at capture. Its local content and transform remain immutable during Split;
  source exit multiplies captured alpha to zero; semantic removal commits only
  at the outer action end. Removed content is retained, not deleted or resurrected
  by a later reveal; existing removed-object lifetime rules continue to apply.
- Each result root starts hidden with zero reveal progress, an explicitly authored
  positive local alpha and starting transform. Existing descendants may carry
  local states, but their entire owned closure is captured and reserved.
- A construction phase uses one explicit mode: `reveal`, `draw`, `write` or `enter`.
  Mode/family compatibility uses the faithful primitive implementation; unsupported
  modes reject rather than substitute another effect. Phase completion leaves
  its paint envelope fully constructed with authored alpha; the semantic state
  remains captured until the outer action commits.
- `enter` additionally declares its own construction-end transform. Other
  construction modes do not write transform channels. A movement phase following
  `enter` starts at or after that construction ends, declares a source transform
  identical after canonical quantization to the construction endpoint, and names
  a separate final destination.
  Thus two phases never interpolate the same transform channel concurrently or
  jump back to the root action's original pose. Reveal/draw/write may overlap
  movement because they own different channels. Without movement, final pose is
  the captured start for those modes or the declared `enter` endpoint.
- Movement, if present, declares `from_transform` and `destination`. For reveal/
  draw/write its origin must equal the captured local transform; for enter it must
  equal the authored construction endpoint, both after canonical quantization.
  It interpolates that origin to the destination using existing transform/easing rules.
  No destination, displacement, staggering, fragment shape or label is generated.
- Every phase declares integer `start_tick`/`end_tick` in 0–10000, start < end,
  and one continuous easing (`linear`, `ease_in`, `ease_out`, `ease_in_out`).
  Resolve a tick as `action_start_ms + floor(duration_ms * tick / 10000)`;
  tick 10000 resolves exactly to action end. Collapsed millisecond phases reject.
  All intervals are half-open. Result construction starts are nondecreasing in
  authored result order; equal starts are permitted. Movement cannot begin before
  its own construction begins. Overlap with source fade is allowed only as
  explicitly declared, preserving actual authored paint slots.
- Every phase fits the single active-board window. Completed phase output persists
  through the remainder of the root action. Before outer start, no participant
  changes. At exact start and throughout `[start_ms, end_ms)`, semantic states and
  versions remain captured; sampled visibility/reveal/opacity/transforms reflect
  paint envelopes only. At exact outer end, one atomic commit sets the source to
  removed/nonvisible with zero alpha/reveal and every result to visible, reveal 1,
  authored alpha and its final pose. Content is unchanged. Root versions
  increment once for exactly the source root and named result roots. No other
  object receives a synthetic version increment.
- Compound construction is derived root-owned paint: child local states/content/
  poses and versions remain captured, while the root's construction envelope
  affects its painted closure. A mode requiring unmodelled child-state mutation
  rejects until faithful compound construction exists; it must not fake a draw
  by changing independent child versions or substitute a box.
- The write reservation covers source/result roots and their complete owned
  painted closures for the whole outer interval, even though only roots acquire
  semantic version increments. Read reservations explicitly enumerate parent
  chains; clip and mask objects plus mask-source closures; managed connector and
  annotation anchor/endpoint definitions; and immutable asset/style revisions.
  Reject overlapping writes to these participants or dependencies, including
  reparent/reorder, content/state/pose/opacity/reveal, aperture/anchor changes and
  conflicting evidence/Isolate holds. Read-only camera observation is allowed;
  anchor lifecycle handoffs must complete before capture, not mutate a reserved
  endpoint mid-Split. Same-time completions precede captures using existing chronology.

Paint continuity is required throughout the outer action: at least one source or
result has positive, nonempty painted coverage after ancestor opacity and clip/
mask effects. Source fade may not finish before a result begins actually painting.
Zero-width, transparent or fully clipped results do not satisfy this rule. Validate
phase boundary and critical coverage intervals with a faithful family proof; if
such proof is unavailable, reject admission rather than trust sparse samples.
Split contains no implicit intentional-blank exception. An independently authored
camera may move away, but Split cannot manufacture that camera decision or use it
to waive its own participant coverage requirement.

## Family coverage — no convenience narrowing

The contract covers the complete approved visual family matrix. Runtime admission
requires faithful primitive support and the appropriate identity/permission proof;
unsupported families remain explicit named gaps until implemented, never flattened
to generic boxes or permanently omitted from the approved end state.

| Family | Required identity and execution proof |
| --- | --- |
| Geometry/freehand/marks/brackets | Exact bounds, points/path, style and construction support; no generated fragments. |
| Text/list/code/callout | Exact authored content, item/token/anchor identity where applicable, pinned glyphs and mode-compatible construction. No semantic splitting of strings. |
| Registry artwork/characters/devices/technical illustrations | Verified registry/project asset identity, declared state/pose/parts/anchors and style pins; no inferred internal artwork. |
| Truthful data-bound charts | Exact authored series, labels, units, domains/scales, highlights and construction; no invented data, static-art substitution or inferred chart decomposition. |
| Group/clip/mask/composition/instance visuals | Complete owned painted closure and actual hierarchy/world/paint slots; no parent transfer. Empty nonpainting shells are not visual sources; mask-only aperture objects are read dependencies, not invented result artwork. |
| Supporting images/source video/presenter | Original checked asset identity, declared frame/range/crop/fit/focal/transform decisions and faithful media adapter. Static thumbnails do not prove executable video. |
| Attested evidence | Existing verified bytes, permission and full treatment/readability/hold proofs. Split does not authorize fabrication, source-pixel modification or unapproved crop; each new evidence result requires its own authored attested treatment. |
| Semantic connectors/free-source pointers | Explicit relationship/anchor/lifetime handoff, not source endpoints retained after removal. No substitution of an unmanaged arrow for an unproved managed relationship. |

A Split policy cannot bypass any current unsupported-family, evidence treatment,
asset integrity, semantic-anchor, media range or mask/clip contract. The foundation
does not claim all those adapters exist today. The full Split/runtime matrix must
eventually prove their required cases or retain the broader phase gate as open.

Evidence requires an explicit activation handoff, not only an asset checksum.
Every evidence result must bind its own existing attested treatment and semantic
beat/causal owner, permission, crop/fit/focus/allowed-transform decisions, construction
completion and uninterrupted readable hold within the board activation. Source
evidence must finish its required hold before Split capture. A result's hold begins
only after its full construction and any movement completes; the existing evidence
reading validator must prove each camera/aperture boundary through that hold.
The handoff must preserve the existing `insert_evidence` treatment/ownership proofs
without a second overlapping writer or a fabricated prior insertion for a hidden
result. Until a dedicated validated activation adapter can represent this causal
handoff in semantic, resolved and stored contracts, evidence-bearing Split results
are explicitly non-executable. Evidence activation, media decoding and reusable
instance expansion remain named required adapter gates, not omitted family enums
or permission exceptions.

## Lifecycle and observer responsibilities

Static and normal-write validation closes source/result/reference/coverage/beat/
board ownership, asset/style identity and authored phase/pose inventories.
Temporal validation samples the actual pre-action hierarchy, not initial layout
assumptions, including prior Group, Count, Morph, nonidentity ancestors and apertures.

Direct writes or relevant ancestor/aperture changes cannot overlap the reservation.
Managed connectors and retained annotation pointers need completed removal or an
explicit provable handoff before a referenced source disappears. Existing evidence
insertion/reading holds and board-wide Isolate reservations remain unchanged.
Replace/Morph/Group conflicts cannot silently overwrite a Split capture.

Camera consumers observe the sampled visible source/result union during construction
and the result set afterward, using actual world bounds and clip/mask visibility.
They do not frame initial coordinates or hidden outputs as if already painted.
Split does not itself invent or move the camera; authored camera actions still
need their own valid purpose, bounds and lifetime proof.

Source content (including Count provenance) is retained after removal; results are
distinct preauthored objects, not silently cloned mutable source payloads. Subsequent
actions bind each result's actual resulting state/content/pose. A/B/A board returns
must prove the exact source/result states, versions and hierarchy basis. Duplicate
projects rebind project/authority/asset/cleaned-timing identities without altering
correspondence, phases or immutable source media.

## Implementation boundary and proof gates

The first implementation slice is contract foundation: strict dedicated model,
legacy compatibility, plan/layout/resolved bindings, negative fixtures and generated
schemas. It does not add a fake runtime; Split remains explicitly rejected until
chronology, sampling, SVG/PNG, consumers and stored-history proofs exist.

Then implement immutable capture/reservations, phase/state sampling, real composition,
lifecycle/camera observers and stored/duplicate/return validation. Acceptance includes
missing/duplicate/self/orphan results; coherent stale hashes/content/geometry/poses/
parents/order/states/versions; unsupported modes/families; all phase boundaries;
arbitrary seeks; prior Group/Count/Morph; nested transforms/apertures; conflicts;
independent 16:9 and 9:16 layouts; real source SVG/PNG; stored atomic rejection;
offline operation and unchanged legacy/v1/Caleb frame hashes.

Compatibility fixtures must separately prove absent/null/non-null hierarchy policy,
absent/null policy serialization, original bare record hashes and round trips through
both generated schemas. Reference/coverage helpers must include policy result IDs,
closures and read dependencies although outer `target_ids` names only the source.
Identity fixtures distinguish stable content, mutable basis and completion receipts;
they reject coherent stale digests rather than merely malformed hash strings.
Boundary tests cover phase-complete-but-outer-active samples (no early semantic
commit), exact outer commit/version counts, enter-to-move continuity, fully clipped
paint gaps, every ownership intersection and missing evidence activation handoff.

Require red/green tests, independent bounded review, adjacent/broad regression,
exact integration and frozen full main verification. Public v2/capability, compiler,
creative-quality, native reliability, production dependency locking, frozen/installed,
full Phase 3 and later phase gates are not waived by this design or a schema pass.

## Review outcome required

The independent pre-revision review returned PARTIAL with nine blocking ambiguities.
This revision addresses their written definitions: canonical removed state; atomic
outer semantic commit; enter/move origin; three separate digest receipts; concrete
correspondence rows; disjoint ownership/read reservations; paint continuity;
evidence activation handoff; and legacy nullable hierarchy/reference coverage.
The existing exit validator, Replace replay and removed-object lifetime validator
were inspected to ground the removal decision; this is not a proposed change to
those operations. A truthful data-chart family row and explicit distinct-parent
policy also preserve the broader approved matrix.

This is a main-agent written-contract correction, not independent acceptance or
runtime proof. The auditor reached its account usage limit after providing those
findings; fresh independent review remains pending. No Split product/schema/test
code was changed. The full main Count regression ran against frozen source
`fc480037af0d4d6447559c8ab6d88cf067a39eda` and subsequently completed1,653 passed,
five skipped, exit0; see Count progress record33. This is not Split acceptance.

Review this written contract for phase/state/identity/coverage fidelity and family
scope. After approval, write the task-by-task implementation plan using the existing
inline implementation method with the independent cross-reference auditor. No
Split runtime code or main frozen-source changes are authorized by this draft alone.
