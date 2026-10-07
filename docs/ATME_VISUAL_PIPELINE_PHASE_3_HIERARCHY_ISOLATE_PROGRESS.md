# Phase 3AE — hierarchy-aware transient focus isolation

Date: 2026-10-06

Status: integrated source f97a850 after exact independent integration PASS;
fresh full-main regression is running, not installed acceptance. The original
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
   Correctly bound red log SHA256
   `35DE55FBAA276ADB3A9075583834C38422D67815CDE92D0E2C22327F737CDF3A`.
5. Dedicated aperture helper red:3 DID NOT RAISE failures/40 deselected,3.71s;
   log `phase-3ae-isolate-aperture-red.log`.
   SHA256 `B9D57155F7B64F38ECDF476BD2AA50C1C987FAF7CE262BEDFF4C11FEEEEB26DE`.
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
   The failed193-run log SHA256 is
   `B2E2C00DF21CC28828BBD0BD01C16E53EE2D9B0C97AF2F668D40889875E3C781`.
8. Final corrected source783290536fb655ffa901aeaed8149b87ed9893d8 is frozen.
   Hidden focused worker7388 started2026-10-06 11:19:33UTC, log
   `phase-3ae-isolate-focused-frozen.log`; broader worker21112 started11:19:38UTC,
   log `phase-3ae-isolate-v2-frozen.log`. Both live command lines and source/tests/
   schema/bench freeze were verified. Both completed with explicit exit0: focused
   193 PASS,291.72s,2026-10-06 11:24:27UTC; broader1,217 PASS/five existing Windows
   symlink skips,1732.55s,11:48:33UTC. End source/tests/schema/bench freeze and
   worker absence were verified before adding the later test-only proof.
   Focused log SHA256
   `FFE8DAC2B7CFA836540E74ABE9F72628C730FD7205918E0145C8C6B1C9F07E83`;
   broader log SHA256
   `6BADA5F795EFF31E1570A9041F8B2A068D077E2E05D6AD9E7D7FD61E2031A601`.
   Independent frozen implementation re-audit PASS; no runtime defect remains.
   Final evidence acceptance requested three additional cross-board/nested-mask
   cases. No implementation change was requested by this follow-through.
   Ten public and40 private offline annotation frames reproduced; all retained
   JSON/PNG hashes remain byte-identical, with no bench or v1 source change.
9. Additional proof was authored outside the frozen test inventory in
   `test-artifacts/test_isolate_acceptance_candidate.py`. One nested-mask case
   passed initially; two B-board cases initially omitted the Isolate action's
   B board ID and were correctly rejected for crossing ownership. Correcting
   only that fixture field gives3 PASS,25.90s, draft SHA256
   `E100B82A849F6B1CC6BAA881DFC73D9E8F2470E349AB3B63CCF12C8D980C7997`.
   Promoted to `tests/test_v2_isolate_acceptance.py` with docstring/import-format
   changes only. It proves retained A pointer frames/versions stay exact during
   an actual later B activation, and two nested focus masks preserve both sources
   and ancestor chains with SVG/PNG restoration and random seek parity.
10. Stored original/duplicate tests now explicitly assert output profiles,
    narrative/timing media IDs/hashes/revisions, plan/layout revisions and IDs,
    cleaned authority revisions/fingerprints and compilation fingerprints.
    The added3 plus hardened stored4 tests PASS:7 PASS/39 deselected,60.52s.
    Scoped Ruff PASS. Production source/schema/bench remain identical to783.
    These additions were not present in the older193/1,217 collection. Final
    tracked focused verification and independent added-proof acceptance remain.
11. Final tracked focused worker18172 completed on exacta74526f:196 PASS,
    223.27s, explicit exit0 at2026-10-07 08:29:06UTC. Log
    `phase-3ae-isolate-focused-final.log`, SHA256
    `7B60B49EECC313C6727BE30E85F5F0E10CF5D6CCBD305FCFEB6CC46228762970`.
    Source/tests/schema/bench freeze remained empty afterward. PID18172 was later
    reused by an unrelated command; its new creation time/command line is not the
    original regression worker and was left untouched.
    Independent bounded implementation/evidence acceptance PASS, including an
    independent7-case rerun56.44s of the promoted proof and hardened stored tests.
    Corrected extra3 log SHA256
    `228C145E47B32ACDA6D7563AF779CE838746021D3B51AA72724D11BC8733510D`;
    tracked extra7 log SHA256
    `3326ACB7C0B01585C0169D7A185DDD3FAAC6B640B25FA572B9EAA80A5D4D0B6A`.
    Auditor accepts existing1,217 broad proof plus final tracked196 and exact
    integration/fresh main full suite; production unchanged after783 means no
    repeated unchanged-production isolated broad run is needed.

## Remaining acceptance

Frozen193/1,217 matrices and independent implementation re-audit are complete.
Final tracked focused proof and independent evidence acceptance are complete.
Exact main integration audit PASS atf97a850f13777aa9c18fa78033f8301103bf6523,
byte-identical to isolatedd152a43 across audited source/tests/schema/bench/report.
Scoped Ruff PASS. Hidden full-main worker17772 started2026-10-07 22:36:29UTC,
frozenf97a850; log `phase-3ae-hierarchy-isolate-full-sidecar.log`. Verified live
worker creation time/command line and source freeze; terminal result pending.
Old1,466 PASS covers only6c83b86. Finish the fresh combined main suite.
Evidence-hold cross-board overlap is impossible under the existing single-active
board contract: its hold must fit A's activation and activations cannot overlap.
Do not invent an invalid concurrent-board fixture to claim that acceptance.
Retain previous offline
frame hashes. No compositor caller-snapshot bypass, public Group admission,
compiler capability promotion, installed app or creative-style acceptance is
implied. All other remaining Phase3 actions/primitives and later phase exits remain.
