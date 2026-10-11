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

Next: finish the added canonical-boundary checks and independent bounded review; commit Task 1 only after its reviewed gate. Then continue Task 2 identities without redesigning Split. No new scope or denominator change.
