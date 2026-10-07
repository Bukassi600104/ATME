# Phase 3 next action map — Count and Split

Date: 2026-10-07

Status: independently cross-referenced implementation map, not delivered behavior.
The approved Phase3/R01–R15/Phase4–12 scope is unchanged. Count and Split cannot
be advertised as executable merely because their verb names parse today.

## Current verified gaps

- `count` is a `TargetAction` literal with no numeric policy, sampled text state,
  static/temporal consumer, glyph override or chronological operator. It fails
  execution rather than silently substituting static text.
- `split` is a `GroupAction` literal, but hierarchy contract validation rejects
  Split policies and chronological replay supports only actual Group/ungroup.
  An authored one-to-many visual operation is not a parent transfer.

## Count implementation sequence

1. Add an explicit strict count policy, with omitted optional serialization for
   legacy bare declarations. New writes/execution require it. Bind one supported,
   nonblank, single-line text object; preserve unit, placement/separator, grouping,
   decimal precision, named rounding, bounded step count and exact formatted
   endpoints. Use canonical finite decimal strings, never a platform locale or
   binary-float interpretation of authored numbers.
2. Choose and document one canonical state transition compatible with attention
   consumers. Persist numeric content independently of visibility/state; increment
   the target's version once on completion. Explicit later counts must bind their
   captured starting text, not assume the unchanged initial layout string.
3. Extend immutable captured frame content and deterministic eased step sampling.
   Final text persists through later actions and board returns. SVG must paint,
   escape and measure actual sampled text using the existing pinned font bundle.
4. Preflight every reachable formatted step, including a widest intermediate
   glyph case. Reject malformed or huge numeric forms, unsupported text families,
   hidden/partial/transparent ancestry, ignored formatting fields, stale starts,
   action outside activation and uncomposed overlapping writes. Preserve Group,
   pointer, connection, evidence hold and board-wide Isolate lifetime reservations.
5. Prove schema/model/new-write/legacy boundaries, positive/negative/reverse ranges,
   rounding and grouping, units/Unicode escaping, exact start/mid/end and random
   seeks, both independently composed profiles, post-Group sampled placement,
   camera observation, stored A/B/A/duplicate/atomic stale receipts, exact authority
   fingerprints and deterministic offline SVG/PNG. No semantic number is inferred.

## Split implementation sequence

1. Introduce a dedicated discriminated Split operation with explicit policy while
   retaining parse/dump compatibility for old bare Group-shaped Split declarations.
   A discriminator cannot assign the same verb to two competing union members;
   design the legacy shape adapter explicitly. Bare legacy execution stays rejected.
2. Name one visible source and an ordered unique inventory of authored hidden
   results. Bind exact geometry/content identities, one-to-many correspondence,
   each starting transform, source removal, result states and timing/phase order.
   Never compute fragments, invent replacement objects or fabricate evidence.
3. Require supported paintable families and explicit same-board parent/layer/paint
   slots. Static contract and normal-write validators close references and coverage;
   temporal validation uses actual sampled readiness, ancestry and world placement.
4. Reserve/version exactly source plus all results. Replay removes/fades the source
   and reveals/moves only named results from immutable captures. Camera observation
   uses their sampled union; relationship/annotation/evidence/Isolate/Group conflicts
   require an explicit safe handoff rather than retaining stale source anchors.
5. Prove missing/duplicate/orphan/self results, hash/correspondence mismatches,
   ownership changes, initial visibility, unsupported source/results, masked/clipped
   bounds and stale receipts reject atomically. Positive fixtures cover nested
   nonidentity ancestors, prior Group, both profiles, stored/duplicate authority,
   exact return states/versions/content and deterministic offline seeking/pixels.

## Shared integration and exit evidence

Use existing contracts/reference helpers and regenerated schemas, static/temporal
validation, chronological replay, SVG composition, lifecycle/camera consumers and
ProjectService storage/duplicate tests. Preserve v1/Caleb, MCP architecture, cleaned
timing authority, immutable media/revisions and external-AI semantic authorship.
Retain capability admission boundaries until the relevant execution is real.

Each implementation still needs red/green evidence, independent bounded review,
adjacent/broad regression, exact integration and frozen full-main verification.
Public Group/validated compositor provenance, remaining primitives/actions, the
compiler, production quality, installed app and all later phase exits remain.
