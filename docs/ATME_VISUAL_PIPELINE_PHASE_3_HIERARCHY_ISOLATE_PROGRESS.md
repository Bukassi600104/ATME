# Phase 3AE — hierarchy-aware transient focus isolation

Date: 2026-10-06

Status: isolated candidate; not integrated, published or installed. The original
Phase3/R01–R15/Phase4–12 scope and public Group gate remain unchanged. Main's
connector/replacement full regression is a separate frozen source boundary.

## Design and implementation

- `v2_isolation.isolation_context_roots` reads the captured hierarchy and frames.
  Explicit supported paint-leaf focus, its ancestors and focus-mask geometry
  chains are protected. Dedicated mask sources and empty containers are not
  secondary paint. Maximal ready nonfocus context roots are dimmed once; local
  descendant alpha is not rewritten, so nested context is not multiplied twice.
- `CapturedAction.context_root_ids` is immutable and derived at the exact start,
  after prior Group completions. The transient operator changes only those roots
  and restores their complete captured frames at completion. Existing board-wide
  write reservation and explicit-focus-only version increments are preserved.
- Temporal validation calls the same planner instead of rejecting every board
  containing a container. Supported focus types are unchanged; evidence itself,
  containers and connectors have not become public Isolate focus types.
- Independent pre-freeze review found two actual lifetime gaps. Any same-board
  Isolate now conflicts with a retained annotation pointer until completed solo
  exit, and with evidence's insert/readable-hold interval. Half-open boundaries
  allow starting exactly after completed exit or readable hold. Existing managed
  connection, annotation construction/hold and Group overlap guards remain.
- Focus mask-source readiness is checked locally as well as relying on the
  upstream dedicated-mask contract. Missing, hidden, transparent or incomplete
  focus apertures cannot silently enter the pure planner.

## Evidence and fixture corrections

1. Eight nested/static mask and post-Group cases initially failed at the actual
   hierarchy blanket (4.85s). Retained red log
   `phase-3ae-hierarchy-isolate-red.log`, SHA256
   `8D2DCCEF79C40ED39CF2CE10DC32A66B8B5DC0224BDAD098CCA4B7C27B9B0B50`.
2. First planner/capture change plus existing flat Isolate and replay tests:
   101 PASS,46.09s; log `phase-3ae-hierarchy-isolate-first.log`, SHA256
   `D8FF1538ECBAD88590FF3920F9354BCEA3A30546B516F0E6F50DB1EC6E6E3691`.
3. Expanded34 run:24 PASS/10 test-fixture failures,113.54s. Absolute repeated
   triggers incorrectly retained speech-match metadata; store cleanup/snapshot
   calls incorrectly used nonexistent `service.close/get` instead of the actual
   `service.store.close/open`. These tests were corrected; no renderer defect
   or successful full expanded run is inferred from those failures.
4. Independent lifetime review PARTIAL. Correctly bound red8 run:4 FAIL/4 PASS,
   23.29s. Two retained-pointer cases and the protected-evidence temporal case
   DID NOT RAISE; unrelated-focus evidence failed indirectly on opacity rather
   than the required explicit reservation. Log
   `phase-3ae-isolate-lifetime-red-bound.log`. Earlier canonical-state probe errors
   were fixture binding errors, not lifetime evidence.
5. Dedicated aperture helper red:3 DID NOT RAISE failures/40 deselected,3.71s;
   log `phase-3ae-isolate-aperture-red.log`.
6. Corrected candidate adds43 hierarchy cases and8 lifetime cases. They cover
   protected partial alpha, mixed subtree and multifocus behavior, repeated exact
   restoration, hidden/zero parents, actual Group and ungroup in both profiles,
   end-before-start boundaries, real WAV/cleaned-authority stored A/B/A receipts,
   duplicate rebinding, atomic stale state/version rejection, offline SVG/PNG
   parity and unchanged source documents. Evidence-focus lifetime is an internal
   temporal-only probe; a separate public negative preserves its unsupported type.
7. Scoped Ruff PASS. Combined candidate/legacy Isolate/replay/evidence/annotation
   run at01f9a2e completed:192 PASS/one assertion failure,222.41s. Log
   `phase-3ae-isolate-lifetime-hierarchy-combined.log`. All runtime assertions
   passed; the final public-negative assertion expected the unsupported focus
   diagnostic during an evidence hold, where the existing read-dependency
   diagnostic correctly has precedence. The corrected test preserves that order
   and exposes the unsupported type separately after the hold. This failed run
   is not overall acceptance; exact corrected frozen focused/broader runs remain.
   Corrected lifetime8 PASS,30.14s; scoped Ruff PASS. No runtime change was needed
   for this diagnostic-precedence assertion correction.

## Remaining acceptance

Complete the corrected combined matrix, independent frozen re-audit, full broader
isolated regression, exact main integration audit and fresh combined main suite.
Cross-board reservation independence and remaining mask/focus matrix evidence
must be checked explicitly before the bounded gate closes. Retain previous offline
frame hashes. No compositor caller-snapshot bypass, public Group admission,
compiler capability promotion, installed app or creative-style acceptance is
implied. All other remaining Phase3 actions/primitives and later phase exits remain.
