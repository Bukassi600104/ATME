# Split implementation evidence

This is supporting evidence, not a second completion ledger. Status and scoring remain in [the authoritative Phase 3 ledger](ATME_VISUAL_PIPELINE_PHASE_3_LEDGER.md). The approved specification and eleven-task plan are unchanged.

## 2026-10-11 — Task 1, implemented / under verification

- Baseline documentation committed independently: `080ed4d`; implementation-start tracking: `85cad10`.
- Execution checkout: `C:/Users/USER/.codex/worktrees/phase3-return-receipts/Movie engine`, based on `080ed4d`; product changes remain uncommitted pending bounded review. Main product source is still `fc480037`.
- Delivered locally: strict dedicated `SplitAction`, ordered authored policy/basis/correspondence models, legacy shape preservation, phase-local integer clock, explicit contract fixtures, and two regenerated action-bearing schemas. No renderer, MCP, project API, public admission, family adapter or Caleb behavior is enabled/changed in this slice.
- Initial RED: 34 expected missing-model failures. GREEN: first 34 tests; extended contract/schema round trips and positive state-version constraint then passed. An accidental test-code placement and a fixture using invalid version 0 were corrected, not hidden by weakened production validation.
- Adjacent contract regression: 198 passed in 118.93 seconds, exit 0. Later public rejection and historical hash checks: 202 passed in 116.21 seconds, exit 0. Four files: `test_v2_split_contract.py`, `test_v2_hierarchy_contract.py`, `test_v2_count_contract.py`, `test_visual_contracts_v2.py`.
- Final 202-test run checked all loaded `atme.*` origins before collection (5 modules) and after collection (41 modules); all were inside the isolated source root. The main virtual environment supplied dependencies only.
- Legacy bare Split SHA256 independently measured using the frozen `fc480037` GroupAction implementation: `0641f8ebbc70734af19f0d353fef461690c46eb29a6c8e7d16213702ce225bf1`. Absent/null optional fields preserve that exact hash. Non-null hierarchy policy rejects; both bare and authored-policy Split remain rejected by public `evaluate_frame`.
- Schema generator run twice: all 9 inspected schema/example hashes repeat identically. Only `visual-plan-v2.schema.json` and `resolved-visual-timeline-v2.schema.json` changed. Ruff and whitespace checks passed at this checkpoint.
- Reviewer raised raw transform equality, then withdrew that objection after reconciling approved specification lines 107–108 and 141–149: pose equality is explicitly canonical-quantized, not raw binary-float equality. Four-decimal boundary tests were added. World range/collapsed-scale execution validation belongs to actual capture, not a claim of schema-level renderer admission.
- The reviewer hit its usage limit before delivering a completed bounded audit. No bounded-review PASS, Task 1 completion, source commit, whole-Split acceptance or full-source regression is claimed. Do not spawn a replacement to bypass this limit.
- Private retained evidence: `.superpowers/sdd/2026-10-09-authored-visual-split/task-1-red.log`, `task-1-focused.log`, `task-1-final.log`, and the loaded-module origin guard in the same execution workspace.

This historical checkpoint is superseded by the terminal evidence below, not rewritten as a pass.

## 2026-10-11 — Task 1 bounded completion, Task 2 started

- Isolated product commit: `5183cb6f1f836beeb1129d63d95b859a1fce1118`, six explicitly staged files only. Main product source and installed application remain unchanged.
- Independent reviewer resumed after the usage reset and found a genuine legacy compatibility defect: dedicated Split had lost the old Group target/container reference checks. Six tests first failed with `DID NOT RAISE`; the existing simple target/container and same-board group checks were restored for Split. Full policy result/read-dependency closure remains Task 3, not silently implemented or claimed here.
- Reviewer also identified shared plan/resolved fixture dictionaries. Resolved fixtures now deep-copy their inputs; a mutation-independence test proves plan edits do not alter the resolved test document.
- Independent bounded source review: **PASS**; reviewer independently ran **76 Split tests**, Ruff and whitespace checks. No further Task 1 production defect found. This is not whole-Split or Phase 3 acceptance.
- Fresh post-fix task-completion command: the four approved contract files, loaded-origin guard enabled, **226 passed in 163.96 seconds, exit 0**. All loaded ATME module origins verified before and after collection. Retained `task-1-tests.log` SHA256: `AD775BAB4F3124FD0C6ED77D3DDE388A3FE684F788216F2173E70E311F6E317F`.
- Final generator repeat: **9 schema/example hashes identical**; only the two action-bearing schemas changed. `visual-plan-v2.schema.json` SHA256: `16B803064876CA3CC8BF7733392FE6E3141AD457E9D6A960BBEA08D8F7A0257E`; `resolved-visual-timeline-v2.schema.json`: `766825BE82CD33B6DD637F94D1BFBED9A2667C2E5F41BA88B93EE67DB54BD8F1`.
- Phase-clock import probe confirmed no runtime import of `contracts_v2`. Public bare/policy Split execution still rejects. No rendered family, pixel proof, full-source regression, installer or public feature admission is claimed.
- Task 2 began at `5183cb6`: initial nine tests fail for the specifically missing identity module/completion receipt, with isolated module origins verified. They cover initial geometry pose/content distinction, immutable receipts, unknown payload rejection, exact Count text/rational payloads, Morph content and resolved-only completion placement. They do **not yet cover every Task 2 obligation**: compound order, styles/assets, complete receipt binding and child-version rejection remain to be added before task completion.
- Current reviewer is cross-checking Task 2 obligations without changing scope. No new ledger item, family, action or acceptance gate was introduced.

Next: finish Task 2's approved tests and identity implementation, then run its named Count/Morph/Group regressions and bounded review. The complete eleven-task Split plan remains binding.
