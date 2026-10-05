# Phase 3AD — post-Group replacement/morph consumer proof

Date: 2026-10-05

Status: test-only candidate preparation against frozen connector source
`4a118918824649c225f9691dbc41219662fe4271`. Production source/tests remain frozen
for connector broad worker2652. The next-slice tests are deliberately outside
that acceptance inventory at `sidecar/test-artifacts/test_group_replacement_candidate.py`;
they are not integrated, published, installed or part of connector acceptance.
No new runtime/schema/compiler/public capability has been added by this draft.

## Independent design findings

- Current consumers already read `replay.before_action` and its sampled hierarchy,
  prove dynamic co-parentage and consecutive nonterminal paint slots. Authored
  semantic `z_index` is distinct from structural dense sibling order; keep both.
- A hidden destination cannot be a direct Group member. The existing Group
  commit requires every direct member root and its ancestor chain fully visible
  and revealed. Do not weaken this invariant to obtain a convenient fixture.
- The valid fixture moves one visible nested container root whose exact inventory
  includes a visible source and hidden untouched destination. Descendants retain
  local placement; the moved root changes their ancestor chain while preserving
  world placement through an explicitly authored compensating transform.
- Under their common sampled parent, Replace's exact local bounds/transform
  equality is the canonical co-location policy, not a demonstrated bug. Morph
  permits different geometry under its explicit correspondence policy. No
  speculative z-index, placement or readiness relaxation is justified.

## Current draft and evidence

- Actual Group and ungroup directions, independently placed landscape and portrait,
  a nonidentity rotated/scaled ancestor, source/destination visibility and version
  capture, before/after world bounds, start/mid/end/random seeks and private offline
  SVG/PNG composition. First8 cases PASS,15.74s.
- A→B→C replacements/morphs keep removed-hidden A in the complete hierarchy but
  skip only that terminal leaf for live adjacency. Eight chain cases PASS,8.40s.
- Hidden/live intermediate leaves reject; terminal removed-hidden intermediates
  remain legal. Descendant edits cannot overlap Group. Replace keeps exact authored
  local co-location. Twenty negative/compatibility cases PASS,5.18s. Scoped Ruff PASS.
- Real ProjectService/WAV/cleaned-source stored writes, complete A/B/A hierarchy /
  state/version returns, duplicate rebinding, unchanged authority/fingerprints and
  private offline pixel parity are included in the draft's full48-case run.
- First stored probe's pixel assertion incorrectly required two symmetric 50%
  crossfades to differ; those may legitimately match. The corrected assertion
  compares each partial frame with the completed third object. This was a test
  expectation error, not a production renderer failure.
- Full first draft worker12552 completed:48 PASS,181.06s, terminal exit0 at
  2026-10-05 20:58:10UTC. Log `phase-3ad-group-replacement-candidate.log`, SHA256
  `81C9DEEE7038BB4D31A15705291A22ABDEAE566676E271A18EFB3E7A1B008105`.
  First draft SHA256
  `2AE7FB966A1ED97786544CA4590940D5977BE6D0E5E46F0B6FDDA6BA14166AAC`
  was checked before and after that run. It does not certify later stronger tests.
- Initial independent review was PARTIAL. All substantive findings were addressed
  in strengthened candidate SHA256
  `AA16491F219E3D128830CB3C873AF3BFE0A876497F4EC7F7AE9B8B430CDFF4EF`.
  Eight strengthened SVG/geometry cases PASS16.71s; two coherent direct-hidden-root
  rejection cases PASS3.24s; scoped Ruff PASS. Bounded independent test-design
  re-audit PASS, no production defect or factual authority-binding mismatch found.
  The nonblocking hardening was added after the full run: hidden C is explicitly
  in Group's changed-ID closure and version2 before the chain, then version3 after
  replacement. Eight final chain cases PASS8.20s; scoped Ruff PASS. Final draft
  SHA256 `B2E94D73691A5A20C5748AE2C92ADD5188E44A1026B9E3649A3F264C75F44626`.
- Strengthened full60-case worker10336 completed:60 PASS,345.65s, explicit terminal
  exit0 at2026-10-05 21:08:36UTC; start/end exact draft hash verified. Log
  `phase-3ad-group-replacement-strengthened.log`, SHA256
  `5A1816605619DFB514CA3204D4150323EF80BFDB8773FE500485C854B27D2A7B`.
  That run precedes only the five final chain-assertion lines proved above; it is
  not a full tracked-suite or installed acceptance. Final independent read-only
  assertion/rejection-path follow-through is requested.
  Connector broad and main stored-pair full regressions remain separate boundaries.

## Implemented review follow-through awaiting final verification

1. Compare every returned A-board state/version and exact hierarchy inventory /
   basis/hash to the independently sampled pre-return frame. Subset checks do not
   prove complete source, hidden/removed destination, shell, root and sibling claims.
2. Assert both Group bases' complete inventories and sole visible member-root
   readiness; prove a hidden direct member rejects without relaxing that invariant.
3. Check all original/duplicate project IDs, plan/layout revisions and hashes,
   output profiles, cleaned revision/fingerprint, narrative/timing media identity
   and compilation fingerprints. Keep original source and stored documents unchanged.
4. Coherently false return parent/ordinal/transform claims and missing hidden /
   chain descendants must reject atomically, even when their own hashes are renewed.
5. Assert actual post-Group SVG crossfade opacity vs single morph geometry and
   effective nonterminal adjacency, not just repeated private raster output.

The strengthened draft was byte-frozen through its terminal result. The previous
48-case run does not certify the later stronger assertions. The final direct
hidden-C version assertion was added and proved only afterward. Do not alter production merely
to make a test pass or describe this partial review as final acceptance.

## Remaining acceptance

Resolve independent review and any remaining dynamic hierarchy cases, then move
the final tests into the tracked suite only after connector source verification
finishes. Freeze the resulting source, run focused/broader regressions, and retain
exact main integration/full regression evidence. Public Group admission, compiler,
installed renderer and creative/Caleb quality gates remain closed. This proof does
not complete hierarchy-aware isolate, remaining Phase3 primitives/actions or any
Phase4–12 requirement from the original approved rebuild plan.
