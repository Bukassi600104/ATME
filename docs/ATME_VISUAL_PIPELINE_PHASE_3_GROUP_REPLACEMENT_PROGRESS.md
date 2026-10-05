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
- Full draft worker12552 started2026-10-05 20:55:04UTC, log
  `phase-3ad-group-replacement-candidate.log`, RUNNING. Draft SHA256
  `2AE7FB966A1ED97786544CA4590940D5977BE6D0E5E46F0B6FDDA6BA14166AAC`
  is checked before and after that run. No terminal result is claimed yet.
- Independent test-design review is requested and pending. Connector broad and
  main stored-pair full regressions remain separate acceptance boundaries.

## Remaining acceptance

Resolve independent review and any remaining dynamic hierarchy cases, then move
the final tests into the tracked suite only after connector source verification
finishes. Freeze the resulting source, run focused/broader regressions, and retain
exact main integration/full regression evidence. Public Group admission, compiler,
installed renderer and creative/Caleb quality gates remain closed. This proof does
not complete hierarchy-aware isolate, remaining Phase3 primitives/actions or any
Phase4–12 requirement from the original approved rebuild plan.
