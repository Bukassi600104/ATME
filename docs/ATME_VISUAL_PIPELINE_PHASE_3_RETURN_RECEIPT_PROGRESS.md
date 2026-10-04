# Phase 3AA — exact retained-board hierarchy receipts

Date: 2026-10-04

Status: source implementation and independent bounded receipt audit PASS.
This is not public Group, full Phase 3, installed-app or creative-quality
acceptance. The isolated source worktree is
`C:/Users/USER/.codex/worktrees/phase3-return-receipts/Movie engine`.

## Implemented boundaries

- The optional compiler receipt belongs to `ResolvedAction`, never semantic
  `EvidenceAction`. Omitted receipts preserve old normalized 2.0.0 hashes.
- Identity binds action, destination board and activation, exact board-owned
  parent/order/local-transform inventory and canonical hierarchy SHA-256. A
  receipt cannot change semantic action/state/version inventory.
- `v2_return.py` compares one captured chronological start to exact retained
  board state, versions and hierarchy. Return changes none of them. Both replay
  and frame temporal validation use that observer; no extra history ledger.
- Normal `ProjectService.write(resolved_timeline)` requires receipts and proves
  their history before committing. Stored private preview explicitly selects
  legacy-read mode. The common validator requires that mode as a keyword.
- Write-time history replay uses the stable resolved-index prefix through the
  last return. Unknown prior or same-time preceding operators fail closed;
  unrelated later or same-time following operators do not redefine that receipt.
- Shared private Group+return replay requires complete receipts. Group+annotation
  and public Group rendering remain closed. Group must finish strictly inside
  its activation; no boundary guard was relaxed.
- Only the resolved-timeline schema changed (49 added lines). Plan/layout schema
  hashes remain byte-identical to main: `5171EDB5E2380AB26BAA738D6BDCF163FB8EB3788D1DE8C07A1186F1768F9087`
  and `3E4AFF7E12F75D13856A177C6D4317AC5A654648C5603AC77D9ABAECC63F72A2`.
  Model/schema parity, deterministic regeneration, registry and real source MCP
  schema delivery are tested. Existing packaging already includes schemas.

## Verification evidence

- Integrated onto repaired main as `821acd30bca1ce7386213c7e3e56ab1a973f5afb`
  from isolated receipt commit `98db1e2`. Independent integration audit PASS:
  all 15 receipt files match exactly; repaired static readiness guards and
  shared-replay camera spies remain intact; scoped Ruff and diff checks pass.
- Fresh combined main regression PASSED: 298 tests in 363.73 seconds, session
  `54572`, exit 0, log `test-artifacts/phase-3aa-return-receipt-combined.log`.
  Fresh full main regression PASSED at frozen source `821acd3`: 1,241 passed,
  five preexisting Windows symlink skips, 1504.30 seconds, session `79529`, exit 0.
  Log `test-artifacts/phase-3aa-return-receipt-full-sidecar.log`; source/tests
  remained unchanged throughout. Later isolated lifecycle/paint-order changes
  are not covered by this full result.
  The integrated offline comparison passed ten frames, session `36329`,
  retaining both hashes recorded below. Source/tests remain frozen at `821acd3`.
- Independent final bounded audit: 54 receipt-focused tests passed in 88.57
  seconds; Ruff passed across all 13 changed/new Python files and diff whitespace
  validation passed. The auditor found no remaining blocker within this boundary.
- Broader return/chronology/stored-project/visual-contract run: 247 passed in
  377.80 seconds, terminal `79836`. This predates the final same-time index-prefix
  refinement and is not full sidecar evidence.
- Fresh six receipt suites after that refinement: 51 passed in 98.25 seconds,
  terminal `55865`; separate mask-source/empty-shell inventory suite: 3 passed
  in 1.04 seconds. Scoped Ruff and diff whitespace checks pass.
- The isolated-source network-denied annotation proof passed ten deterministic
  frames plus contact sheet, terminal `7381`. JSON hash
  `86D4E25C6C969281891862F8DE2F589B5EFC66404A7F6B7D3A4560F7127B0B70`
  and PNG hash `112A6C9F980F05D62F6D0FBBAF83A317F7D9F5D859122C2F7507C3A2C4EF6A4F`
  remain identical. This is retained legacy pixel evidence, not Group pixels.
- Tests cover grouped and ungrouped A-to-B-to-A histories; multiple returns with
  distinct receipts; forward/backward/random seeking; no return version/reset;
  exact mask-source and empty-shell inventory; malformed identity/hash/parents/
  cycles/order; coherently missing/extra layout inventory; stale state/version/
  transform/order/parent; ordinary-end/return-start ordering; strict Group-end
  activation rejection; explicit legacy preview; atomic failed writes; exact
  normal storage and duplication/fingerprint preservation; real MCP schemas.
- The earlier repaired-consumer full run at main source `365c3a0` passed 1,187
  tests with five preexisting Windows symlink skips (1399.88 seconds, terminal
  `83170`). It does not prove this new receipt source. The older `91184` failed
  run remains failure evidence.

## Still required

Dynamic
Group annotation/evidence lifetimes, effective paint order, stored Group SVG/PNG
acceptance, compiler/public/installed routing and all other approved Phase 3–12
and R-01–R-15 requirements remain open. V1/Caleb behavior and the installed app
are unchanged; no release or production-readiness claim is made here.

## Sampled lifecycle integration checkpoint — 2026-10-04

Integrated source `cc1a6a4` is exact to isolated `21eda61`: shared annotation,
evidence and nonterminal paint-slot observers now run in both frames and new
resolved writes. No-return writes prove full consumer history; return writes
use the causal resolved-order prefix while retaining complete structural and
attested metadata. The independent bounded source audit and fresh 25-suite
regression PASS (528 tests, 406.44s, session `62255`); scoped Ruff and exact
source/test integration comparison PASS. Fresh full main sidecar session `67141`
is RUNNING on frozen `cc1a6a4`; no full result is claimed yet. Previous receipt
full `79529` remains PASS but does not cover this migration. See the lifecycle
progress report for reproduction logs and immutable offline frame hashes.
Group+annotation/private blanket removal, connector/isolate, public/stored pixels,
compiler/installed and all remaining Phase 3/4–12 gates remain open. V1, Caleb,
semantic authority, schemas and public capabilities are unchanged.

