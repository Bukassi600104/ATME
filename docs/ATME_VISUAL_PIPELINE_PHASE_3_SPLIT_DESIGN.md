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
  `container_id`. An absent new `split_policy` is omitted on serialization.
  Legacy absent/null hierarchy policy remains omitted exactly as today.
- Bare old Group-shaped Split documents retain canonical parse/dump shape and
  hashes. They remain non-executable; new semantic writes reject a missing policy.
- A non-null Group hierarchy policy on Split still rejects. No automatic conversion
  to Group/ungroup, replacement, guessed result objects or inferred fragments.
- A policy-bearing action has exactly one `target_id`, equal to its source ID,
  no `container_id`, a required captured source pre-state, `post_state: "hidden"`,
  and outer `easing: "linear"`. Named per-phase easing owns the actual animation;
  no other outer easing may be silently ignored.

## Strict policy and immutable participant binding

`SplitPolicy` contains `source_object_id`, one `source_exit` phase, an ordered
`results` inventory of 2–256 entries, and a complete `source_basis` plus its
canonical SHA256. Each result entry names its object, correspondence binding,
construction phase/mode, optional movement phase and explicit destination pose.
Every ID must be nonblank, unique and already present in the authored layout.
The source cannot be a result; result roots cannot own or contain each other.
The source's removal cannot hide any result through ancestry.

`SplitBasis` records the source/result ownership closures, their actual parent
and sibling ordinal, local transform, world placement, pre-state, visibility,
reveal/opacity, state version and immutable paint identity. Read dependencies
(ancestors, apertures, anchors and asset/style pins) are bound separately and
must also match the captured start. Limits follow existing hierarchy inventories:
at most 4096 distinct bound objects; no arbitrary new payload subclasses.

Paint identity is the canonical JSON SHA256 of the authored VisualObject
definition, sampled FrameObject payload (including completed Count value/text or
Morph geometry when present), actual hierarchy placement, and pinned style/asset
registry identities. Project assets additionally retain their existing immutable
asset ID, revision, resource URI and checksum bindings. JSON uses sorted keys,
compact separators and rejects nonfinite numbers, as existing digest utilities do.
The recorded start excludes the global sample timestamp, so equivalent content
is not invalidated merely by observing it at another millisecond.

Each correspondence entry explicitly binds the source ID/paint identity to one
result ID/paint identity and its authored geometry/content relationship. Optional
authored source regions use the source's local coordinates and must lie within
its sampled content bounds. They authorize no crop or transformation by themselves.
This is deterministic manifest validation, not a claim that ATME independently
understands or verifies the semantic correctness of an illustration.

## State, phases and clock

- Source is actually/effectively visible, fully revealed and has positive alpha
  at capture. Its local content and transform remain immutable during Split;
  source exit multiplies captured alpha to zero, then sets it hidden.
- Each result root starts hidden with zero reveal progress, an explicitly authored
  positive local alpha and starting transform. Existing descendants may carry
  local states, but their entire owned closure is captured and reserved.
- A construction phase uses one explicit mode: `reveal`, `draw`, `write` or `enter`.
  Mode/family compatibility uses the faithful primitive implementation; unsupported
  modes reject rather than substitute another effect. Completion leaves that
  result root visible and fully constructed, retaining its authored alpha.
- Movement, if present, interpolates only the result's captured local transform
  to its explicit destination using the existing shared transform/easing rules.
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
  through the remainder of the root action. At root completion the source is
  hidden, every result is fully visible at its declared final pose, and versions
  increment once for exactly the source root and named result roots. No other
  object receives a synthetic version increment.
- Source/result descendants, ancestors and referenced dependencies are reserved
  where their changes could alter the operation, even when their own versions do
  not change. Same-time completions precede captures using existing chronology.

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
| Group/clip/mask/composition/instance visuals | Complete owned painted closure and actual hierarchy/world/paint slots; no parent transfer. Empty nonpainting shells are not visual sources; mask-only aperture objects are read dependencies, not invented result artwork. |
| Supporting images/source video/presenter | Original checked asset identity, declared frame/range/crop/fit/focal/transform decisions and faithful media adapter. Static thumbnails do not prove executable video. |
| Attested evidence | Existing verified bytes, permission and full treatment/readability/hold proofs. Split does not authorize fabrication, source-pixel modification or unapproved crop; each new evidence result requires its own authored attested treatment. |
| Semantic connectors/free-source pointers | Explicit relationship/anchor/lifetime handoff, not source endpoints retained after removal. No substitution of an unmanaged arrow for an unproved managed relationship. |

A Split policy cannot bypass any current unsupported-family, evidence treatment,
asset integrity, semantic-anchor, media range or mask/clip contract. The foundation
does not claim all those adapters exist today. The full Split/runtime matrix must
eventually prove their required cases or retain the broader phase gate as open.

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

Source content (including Count provenance) is retained while hidden; results are
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

Require red/green tests, independent bounded review, adjacent/broad regression,
exact integration and frozen full main verification. Public v2/capability, compiler,
creative-quality, native reliability, production dependency locking, frozen/installed,
full Phase 3 and later phase gates are not waived by this design or a schema pass.

## Review outcome required

Review this written contract for phase/state/identity/coverage fidelity and family
scope. After approval, write the task-by-task implementation plan using the existing
inline implementation method with the independent cross-reference auditor. No
Split runtime code or main frozen-source changes are authorized by this draft alone.
