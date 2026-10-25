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
PASSED frozen `cc1a6a4`: 1,281 passed, five preexisting Windows symlink skips,
1768.25 seconds, terminal exit 0. Retained log
`test-artifacts/phase-3aa-lifecycle-full-sidecar.log`, SHA256
`CBE1DAFFDC60F174D3ADB4434A5F4E9C7C221A22CD84C4E0D1BFE880F6E453F1`.
Main source/tests stayed frozen. This does not certify the later paired
Group/annotation slice. Previous receipt
full `79529` remains PASS but does not cover this migration. See the lifecycle
progress report for reproduction logs and immutable offline frame hashes.
Group+annotation/private blanket removal, connector/isolate, public/stored pixels,
compiler/installed and all remaining Phase 3/4–12 gates remain open. V1, Caleb,
semantic authority, schemas and public capabilities are unchanged.

## Paired Group/annotation integration checkpoint — 2026-10-04

Source `2c21c2c` integrates audited isolated `7b93db0` exactly: private Group/
ungroup, construction/hold/retained-pointer lifetimes and the shared sampled
SVG/PNG path have bounded independent PASS (37 cases), combined PASS (617 tests,
672.25s), scoped Ruff PASS and 40 deterministic offline paired frames. Ten prior
annotation frame/report hashes remain unchanged. Full main run `56029` completed:
1,318 passed, five existing Windows symlink skips, 1866.02s, on frozen `2c21c2c`.
The terminal log and empty source/tests/schema/bench diff were verified on resume;
the original process handle had expired, so its OS exit status was not captured.
Log SHA256: `D8C7AABA5FBC9143AA7F127700090C5FDCE36EC3B1A592266456FC9CB5BA48DC`.
The earlier 1,281-test full PASS at `cc1a6a4` is a separate source boundary.
Public Group and causal stored Group+annotation
admission remain closed; real stored/duplicate/return receipts and connector/
isolate follow-through remain required. This is private mechanical proof, not
Caleb-style creative acceptance, Phase 3 completion or an installed release.
See the paired Group/annotation progress report and its next stored-project map.

## Stored Group/annotation integration checkpoint — 2026-10-05

Source `eb811ce` integrates isolated `3f037ac` plus documentation follow-through:
real stored Group/ungroup and authored note/leader A/B/A receipts, atomic coherent
stale claims, duplicate identity/hash/authority rebinding, same-time causal order
and full no-return histories. Both independently authored profiles have stored
and duplicate private offline pixel proof. Focused61 plus four no-return cases,
the49-suite1,046-pass regression (five existing Windows symlink skips), scoped
Ruff and independent bounded implementation audit PASS. All10+40 previous
JSON/PNG hashes remain unchanged. Primary exact integration comparison is empty;
independent exact-integration audit PASS. Full main `24031` stopped during
continuation at 95% without terminal summary/exit marker; it is not acceptance.
The preserved log SHA256 is `120D1C5B3DFEEC40CFED1D716D7D8A4AD2BF65FD91AE4C27BB4578205021DDC8`.
Process absence and missing handle were verified before restart. A hidden,
continuation-safe full worker PID10628 PASSED on frozen `eb811ce`:1,346 passed,
five existing Windows symlink skips,2420.49s, explicit terminal exit0 at2026-10-05
21:15:23UTC. Log `phase-3ab-stored-pair-full-sidecar-rerun.log`, SHA256
`33F5E96C65A3FDEAF3336CE8C8F73063A0BFA1F9F812CEF555256BC0B2368884`.
Final source/tests/schema/bench freeze is empty. Previous1,318-pass full run
covers only `2c21c2c`. Connector `4a11891` has focused151 and broader1,106
PASS/five existing Windows symlink skips with explicit exit0; final independent
source/evidence acceptance PASS. Replacement/morph tracked724e7fc has60 PASS,
160.34s, explicit exit0, log SHA256
`4E9E38AEB3B8B309562071A3D52978070B264825F53DC10C36F2F2DFFD42D328`.
Both are integrated exactly as main `6c83b86ef9441603bade71ca51844254e62df996`;
independent exact-integration PASS, scoped Ruff PASS. All10public+40private
annotation JSON/PNG hashes reproduced unchanged. Hidden full main worker20316
completed at frozen6c83b86:1,466 PASS/five existing Windows symlink skips,2779.95s,
explicit exit0 at2026-10-06 11:40:14UTC. Log
`phase-3ad-group-connection-replacement-full-sidecar.log`, SHA256
`4C41F4764D812C07A2322FC3C91033234958CF575FB2245BDEF4560AACA328D4`.
Final source/tests/schema/bench freeze empty; worker absence verified. This is the
connector/replacement source boundary, not later Isolate or installed acceptance.
The blanket causal paired storage rejection is removed, not the sampled history
validators or public Group admission. Public preview/export, post-Group connector/
isolate/replace/morph, other Phase3 primitives/actions, compiler/installed and all
Phase4–12 requirements remain. No v1/Caleb, schema, database, MCP or capability
change; no creative or full Phase3 acceptance. See the stored-pair progress report.


## Hierarchy-aware Isolate integration checkpoint — 2026-10-07

Mainf97a850 integrates the exact independently accepted isolatedd152a43 result:
actual sampled focus/ancestor/aperture protection, maximal single-dim context roots,
exact transient restoration and focus-only versions, readable-hold/retained-pointer
conflicts, cross-board independence and nested-mask closure. Frozen193/1,217 proof
(five existing Windows skips in the broader run), final tracked196 PASS and an
independent7-case rerun56.44s certify the bounded source/test slices. Independent
exact-integration audit and scoped Ruff PASS;50 previous offline hashes unchanged.
Final196 log SHA2567B60B49EECC313C6727BE30E85F5F0E10CF5D6CCBD305FCFEB6CC46228762970.
Fresh hidden full worker17772 PASSED on frozenf97a850:1,520 PASS/five existing
Windows symlink skips,2866.49s, explicit exit0 at2026-10-07 23:24:43UTC. Log
phase-3ae-hierarchy-isolate-full-sidecar.log, SHA256
44C2FB1B56733096B4DF94DB7940FCE0975123CCB14224108A0B0F9FAF512CAD.
Final source/tests/schema/bench freeze empty and original worker stopped. The old
1,466-pass run covers only6c83b86; no later Count source is certified. Public Group/
validated compositor provenance, all remaining Phase3 primitives/actions and
Phase4–12 gates remain. No installed rebuild or creative-quality acceptance.
See the Isolate progress report and independently cross-referenced Count/Split map.
