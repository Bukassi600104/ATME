# Phase 3AA — paired hierarchy and annotation consumer proof

Date: 2026-10-04

Status: integrated `2c21c2c` from audited isolated `7b93db0`; focused proof,
independent corrected-source re-audit and fresh combined regression PASS.
Exact source/tests/bench/pixels integration comparison and scoped Ruff PASS.
Independent exact-integration audit PASS; both logs and pixel hashes verified.
Full main `56029` completed:1,318 passed, five existing Windows symlink skips,
1866.02s, on frozen `2c21c2c`. Terminal log and empty source/tests/schema/bench
diff verified by the primary agent on resume; original exec handle had expired
before final status capture, so OS exit status is not claimed.
Log SHA256:`D8C7AABA5FBC9143AA7F127700090C5FDCE36EC3B1A592266456FC9CB5BA48DC`.
This is not public Group,
stored Group+annotation production, Phase 3, installed or creative acceptance.

## Scope and wiring

- The shared chronological kernel can now replay real Group/ungroup alongside
  authored annotation phases. Both consume the same immutable clock and hierarchy;
  no alternate state ledger, fabricated note or semantic authoring is introduced.
- Full consumer validation remains `_validate_consumer_history`: annotation
  target/note ancestry, effective paint order, geometry, construction/reading hold,
  retained-pointer removal, camera and evidence use the sampled hierarchy.
- `_sample_validated_frame` extracts the existing public evaluator's post-proof
  view/geometry assembly. Public `evaluate_frame` still performs `_validate_pair`
  admission first; Group remains rejected there. This is not a new public API.
- `_compose_validated_svg_frame` paints requested and construction-completion
  snapshots. Public SVG obtains both through public `evaluate_frame`. The private
  paired proof obtains both through the exact same validated replay. Held frames
  cannot be omitted or supplied at a different timestamp.
- `_rasterize_svg_frame` extracts the existing pinned-font, system-font-disabled
  offline rasterizer. It is shared by public PNG and the paired mechanical proof.
- Storage admission is explicitly preserved in `validate_resolved_return_history`:
  a Group+annotation pair **in the causal prefix through the last return**, or in
  the full no-return history, remains rejected. Later actions after that return
  retain the existing future-action receipt semantics. Kernel proof must not
  silently expand ProjectService storage support. Real stored writes, duplicate,
  receipts and preview remain required before this storage boundary changes.
- General connector inverse-parent semantics, hierarchy-aware isolate, public
  frame/ProjectRunner/MCP/compiler and installed acceptance remain separate open
  work. No schema, public capability, v1/Caleb engine or semantic authority change.

## Verification and retained pixels

- Initial paired chronology reproduction: ten FAILED, three passed, because the
  private blanket rejected otherwise valid unrelated and completed Group cases.
  The private kernel blanket is removed; storage/public admission stays explicit.
- Intermediate thirteen-case run: eleven passed; two tests incorrectly applied
  `pytest.approx` to nested tuples. Fixed per-coordinate comparisons without
  relaxing the 1e-4 world-preservation bound.
- Four real-paint cases initially failed on the absent shared private sampler.
  After extracting identical sampling/paint/raster bodies, seventeen cases PASS
  (`47159`, 14.60s).
- Auditor's first decision PARTIAL: needed post-pointer-exit pixels, explicit
  storage-boundary regression and corrected kernel/construction wording. All
  three are implemented; corrected independent re-audit PASS, including actual
  group from an owned empty shell and newly grouped target-ancestor checks.
- An intermediate expanded run had three invalid small-leaf radius fixtures and
  25 passes (`60721`, 14.18s); the authored radius is now within each leaf's bounds.
  No renderer geometry guard was weakened.
- Corrected focused proof PASS: 33 tests, 14.24s, exit 0 (`63554`), retained log
  `sidecar/test-artifacts/phase-3aa-group-annotation-focused.log` in the isolated
  worktree. Four additional actual Group cases were added before the fresh run.
- Independent final re-audit repeated all 37 current cases: PASS, 25.25 seconds,
  explicitly isolated source on PYTHONPATH. Scoped Ruff PASS. Both artifact
  hashes and all 40 frames independently verified; contact sheet inspected.
- Fresh frozen 28-suite combined run `26030` PASS: 617 tests, 672.25 seconds,
  terminal exit 0. Retained log:
  `C:/Users/USER/.codex/worktrees/phase3-return-receipts/Movie engine/sidecar/test-artifacts/phase-3aa-group-annotation-combined.log`,
  SHA256 `F884AEDEE44C1B9330D59CDEDA09E726C5DBCEEB9340274611E20B379A1B687F`.
  No full sidecar run covers this later slice yet.
- Scoped Ruff from sidecar cwd across the three source modules, test and bench
  script PASS. Diff whitespace checks PASS. Root-cwd lint package-discovery
  warnings are not described as a pass; the actual sidecar context is authoritative.
- `bench/verify_v2_group_annotation.py` produced 40 deterministic network-denied
  frames: nested translated/rotated/nonuniform-scaled Group and ungroup in both
  independently placed profiles; solo pointer fade/removal and later related
  note/target ungroup in both profiles. Random seeks and immutable input documents
  are asserted. Public Group remains closed for each case.
- Retained report `docs/visual-acceptance/phase-3aa-group-annotation.json` SHA256:
  `7489307543D1D562A10B22EB782C79392CC0EC0144E3ABA9BC2223ADB5AED08A`.
  Contact sheet `docs/visual-acceptance/phase-3aa-group-annotation.png` SHA256:
  `4B04705E56C18687C7BB289C375C5F16E14B83C5DFA92CBA4CA00033CF43549C`.
  Visual inspection confirms stable layout at structural boundaries, readable
  authored note/pointer progression, and note/target retention after pointer
  removal. These simple geometry fixtures are software-mechanics tests, **not**
  production artwork, research-style compliance or the final visual rubric.
- Ten original public annotation frames also PASS (`29495`) after the shared
  sampler/compositor extraction, with unchanged report SHA256
  `86D4E25C6C969281891862F8DE2F589B5EFC66404A7F6B7D3A4560F7127B0B70`
  and PNG SHA256 `112A6C9F980F05D62F6D0FBBAF83A317F7D9F5D859122C2F7507C3A2C4EF6A4F`.
  The first hash command used incorrect positional PowerShell arguments; the
  corrected explicit `-LiteralPath` hash check confirms both values. The retained
  artifact diff is empty.

## Remaining acceptance

Exact integration and the fresh full frozen regression are complete for2c21c2c.
Stored Group+annotation writes, duplicate/return-receipt history and both-profile
stored/private SVG/PNG now have bounded independent implementation PASS in
source3f037ac, integrated as eb811ce, with independent exact-integration PASS.
Main24031 stopped at95% during continuation without terminal result; it is not
acceptance. Its preserved log SHA256 is120D1C5B3DFEEC40CFED1D716D7D8A4AD2BF65FD91AE4C27BB4578205021DDC8.
Verified process absence/missing handle preceded the hidden continuation-safe
rerun PID10628 (2026-10-05 20:34:55UTC), frozen eb811ce,
log phase-3ab-stored-pair-full-sidecar-rerun.log. This rerun PASSED:1,346 tests,
five existing Windows symlink skips,2420.49s, terminal exit0; source freeze empty.
Log SHA25633F5E96C65A3FDEAF3336CE8C8F73063A0BFA1F9F812CEF555256BC0B2368884.
Connector4a11891 focused151/broad1,106 PASS/five existing Windows symlink skips,
tracked replacement724e7fc60 PASS and final independent source/evidence acceptance
are integrated exactly as6c83b86. Independent integration audit and scoped Ruff PASS;
all50 retained offline frame hashes unchanged. Combined main full worker20316
PASSED on frozen6c83b86:1,466 PASS/five existing Windows symlink skips,2779.95s,
explicit exit0 at2026-10-06 11:40:14UTC. Log
phase-3ad-group-connection-replacement-full-sidecar.log, SHA256
4C41F4764D812C07A2322FC3C91033234958CF575FB2245BDEF4560AACA328D4.
Source freeze empty and worker absent. No later Isolate or installer acceptance.
Post-Group connector and isolate/replace/morph consumers remain required before
public/production admission. Trusted
private snapshots must not become a caller-supplied public validation bypass.
All remaining Phase 3 actions/primitives and approved R-01–R-15/Phase 4–12
requirements remain in the original plan. The later candidate3f037ac has
61 focused plus4 no-return cases and49-suite regression1,046 passed/five existing
Windows symlink skips; its independent implementation review resumed after a
usage-limit interruption and passed. It is integrated as eb811ce, but it is not
certified by the earlier2c21c2c full run. No installer or release was rebuilt.

## Independently mapped next stored-project slice

This was the independently authored implementation map. The bounded stored
slice now satisfies its caller/receipt/profile/duplicate/atomic-history proof;
exact-integration/full-main verification is in progress. Public Group and the
other remaining hierarchy consumers are not implied. See the3AB progress report.

1. Reuse `stored_v2_basis` for real WAV/project/cleaned-authority identity and the
   existing group-return project's plan-building pattern. Use exact authored
   Group or ungroup with note/leader inventory; do not introduce a parallel store.
2. Activations A 0–8000, B 8000–9000, returned A 9000–10000. Group completes at
   6000; annotation constructs 6000–7000; reading hold ends at 8000. Author a real
   B object/action and beat/coverage/anchor. Preserve strict Group completion rules.
3. Derive board-A return hierarchy, all states and structural versions from the
   immutable prefix at 9000. Include note and leader, expected versions and the
   exact checksum; never assume fixed version numbers after structural closure.
4. Preserve semantic plan/layout/actions/coverage/continuity, empty-shell ownership
   for actual Group and complete initial hierarchy; rebind every revision/hash
   and cleaned timing fingerprint before computing compilation fingerprint last.
5. Prove real writes for Group and ungroup before changing the explicit storage
   guard. Assert exact artifacts and no source mutation. Keep public Group closed.
6. Prove stale note/leader state/version claims authored consistently into plan
   and resolved action reject atomically through actual retained-history checks;
   also one otherwise coherent stale Group source history.
7. Duplicate/rebind real projects; exact hierarchy receipts/versions and cleaned
   timing remain semantically identical. Source and duplicate private SVG/PNG
   samples must match; public ProjectRunner remains unavailable and advertises v1.
8. Test same-time invalid endpoint edits before/after last return by resolved list
   order, plus no-return full history: causal cases reject, future metadata remains
   retained without claiming future execution support. Never timestamp-slice it.
9. Only remove the causal storage guard after this vertical matrix, independent
   audit, adjacent/full regression and offline/private pixel parity pass. Public
   admission, compositor provenance, connector/isolate and all later gates remain.


## Hierarchy-aware Isolate integration checkpoint — 2026-10-07

Mainf97a850 integrates the exact independently accepted isolatedd152a43 result:
actual sampled focus/ancestor/aperture protection, maximal single-dim context roots,
exact transient restoration and focus-only versions, readable-hold/retained-pointer
conflicts, cross-board independence and nested-mask closure. Frozen193/1,217 proof
(five existing Windows skips in the broader run), final tracked196 PASS and an
independent7-case rerun56.44s certify the bounded source/test slices. Independent
exact-integration audit and scoped Ruff PASS;50 previous offline hashes unchanged.
Final196 log SHA2567B60B49EECC313C6727BE30E85F5F0E10CF5D6CCBD305FCFEB6CC46228762970.
Fresh hidden full worker17772 is running on frozenf97a850, started2026-10-07
22:36:29UTC; log phase-3ae-hierarchy-isolate-full-sidecar.log, terminal pending.
The old1,466-pass main run covers only6c83b86, not this later source. Public Group/
validated compositor provenance, all remaining Phase3 primitives/actions and
Phase4–12 gates remain. No installed rebuild or creative-quality acceptance.
See the Isolate progress report and independently cross-referenced Count/Split map.
