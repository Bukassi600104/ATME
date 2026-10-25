# Phase 3AA — sampled lifecycle and effective paint-order consumer migration

Date: 2026-10-04

Status: integrated bounded source implementation; corrected consumer-history/call-site
bounded independent source re-audit PASS; fresh combined regression PASS;
exact integration `cc1a6a4` from isolated `21eda61` PASS; full main session
`67141` PASS on frozen `cc1a6a4`: 1,281 passed, five preexisting Windows symlink
skips, 1768.25 seconds, terminal exit 0. The later paired Group/annotation slice
needs separate full evidence.
Independent exact-integration audit PASS. This is not complete Group+annotation,
public Group, Phase 3, installed-app or creative-quality acceptance. The earlier
receipt source `821acd3` is the baseline, not proof of the new integrated source.

## Implemented runtime wiring

- `v2_lifecycle.py` observes the same immutable chronological replay: exact
  captured pre-start, completed end, hold end minus one, and both sides of every
  intervening checkpoint. No alternate state ledger or state/version mutations.
- Group geometry closure uses member/shell/descendant changes and observed
  ancestry in both exact receipt bases, not ordinal-only version closure. Reading
  windows remain half-open. Unrelated sibling Group may preserve evidence reading.
- Runtime annotation geometry now requires the sampled hierarchy and uses its
  effective paint order, not the plan-time initial `(z_index, object_id)` tree.
  Plan-time validators and schemas remain unchanged.
- Annotation construction/hold geometry, target/parent visibility, opacity,
  completed-note state and matching camera viewports use lifecycle samples.
  Retained leader dependency chains are recomputed at later action captures;
  geometric Group edits require completed leader removal. The later integrated
  paired source `2c21c2c` proves real construction/hold/retention and removes the
  kernel blanket; causal storage/public admission remains explicitly closed.
- `v2_evidence_reading.py` checks each sample's chain, permission-bound rotation,
  actual world matrix/bounds, clip/mask apertures, opacity/reveal and camera/focus
  readability. Source attestation, source pixels and semantic authority are intact.
  Only Group is exempted from the old blanket same-board hold conflict, replaced
  by exact geometric lifetime checks; ordinary visual/camera conflicts remain.
- Replace/morph requires consecutive chronological nonterminal paint slots,
  in addition to existing sampled co-parent, authored-layer and geometry guards.
  Only removed/nonvisible leaves leave this view, never hidden, zero-opacity or
  zero-reveal leaves. Removed-but-visible leaves explicitly reject. Full immutable
  layout/state/version inventory and receipts retain every removed leaf.
- Preview and new resolved-artifact writes share replay/camera/temporal consumer
  history validation. New writes without returns use the complete history;
  receipt writes use the resolved-order prefix through the last return for both
  static and temporal execution checks. Full initial hierarchy/empty-shell
  ownership and receipt inventory still bind the complete original document.
  Later evidence treatment metadata is retained but not executed in an earlier
  receipt proof. The explicit legacy preview/read compatibility path is unchanged.

## Reproduction and verification

- The initial replacement/morph probe reproduced six missing rejects: hidden or
  zero-opacity intervening leaves and removed-but-visible leaves. Two additional
  positive cases initially used a nonexistent test accessor, corrected without
  relaxing assertions. New probes plus existing replace/morph suites: 76 PASS,
  session `69164`, 28.66 seconds.
- Sampled annotation-order probe initially failed for the missing required runtime
  hierarchy input. Observers and existing annotation suites: 96 PASS, session
  `86570`, 26.55 seconds.
- The new evidence fixture's initial-basis/duplicate-ID/coverage mistakes were
  corrected before behavioral reproduction. Restoring the exact original blanket
  hold guard then rejected the model-valid unrelated sibling Group at static
  preflight (session `7257`). The narrow geometric consumer replaces that guard.
- Fresh nine-suite combined run: 198 PASS, session `85107`, 106.25 seconds. Includes
  three new files (29 cases), legacy annotation, replace/morph, evidence and return.
- Adjacent camera/hierarchy/replay/return/project/aperture suites PASSED before
  the later caller corrections: 280 tests, session `40602`, 119.12 seconds. An earlier command named two nonexistent
  test files and collected no tests; it is not evidence of a passing run.
- The independent audit found a fail-open caller path: static ancestor/Group
  guards were relaxed before receipt storage consumed the temporal validator.
  Six new reproductions FAILED as expected in session `96874`. Sharing replay,
  camera and lifecycle validation corrected that helper gap. An intermediate
  combined run PASSED 250 tests (`44870`, 221.12 seconds), before the next fixes.
- The re-audit found that no-return production writes still bypassed the helper
  and static scans preceded causal slicing. Real no-return storage and same-time
  post-return cases reproduced three failures (`36218`, seven passes). Both
  callers are corrected, with atomic artifact/revision preservation asserted.
  A test incorrectly read an empty `ProjectError.errors` list; its assertion now
  uses the actual exception message, without relaxing the protected behavior.
- Corrected caller boundary run PASSED ten tests (`14989`, 51.21 seconds).
  A separate real future-evidence metadata/preview test PASSED (`17926`, 17.44
  seconds). Exact source integration/full proof is still required.
- Intermediate caller/project run `32393` finished with one test-accessor failure,
  80 passes, 310.44 seconds. It is not a passing combined run; corrected accessor
  behavior is covered by `14989` and the fresh combined run below.
- Independent corrected source re-audit PASS: real no-return write boundary,
  causal static/replay/camera/temporal scans, complete structural metadata,
  future attested evidence and initially empty shell with a future owner. Its
  extra missing-owner mutation rejects. Public Group remains closed. The auditor
  reran the focused cases and scoped Ruff. This is bounded source proof only.
- Scoped Ruff across all nine Python paths and diff whitespace checks PASS.
- Fresh frozen 25-suite combined regression PASS: 528 tests, 406.44 seconds,
  session `62255`, terminal exit 0. Retained log:
  `C:/Users/USER/.codex/worktrees/phase3-return-receipts/Movie engine/sidecar/test-artifacts/phase-3aa-lifecycle-combined.log`, SHA256
  `3400280A1B565349090D44D7BC421F21A8040E13366D86A13FB845A5A81F8D38`.
  This covers the corrected caller boundaries and lifecycle consumers, not the
  still-closed Group+annotation/public Group workflow or a full sidecar run.
- Ten network-denied annotation frames/contact sheet PASS, session `72677`:
  JSON `86D4E25C6C969281891862F8DE2F589B5EFC66404A7F6B7D3A4560F7127B0B70`;
  PNG `112A6C9F980F05D62F6D0FBBAF83A317F7D9F5D859122C2F7507C3A2C4EF6A4F`.
  These retained legacy pixels are not Group composition acceptance.
- Fresh post-correction offline proof PASS (`9315`): all ten frames and both
  contact-sheet/report hashes remain identical to the values above.
- Main's earlier frozen receipt full run separately PASSED: 1,241 passed, five
  preexisting Windows symlink skips, 1504.30 seconds, session `79529`, exit 0. It
  does not cover this isolated source migration.

## Still required

Real paired Group+annotation construction/hold/retention, exact pointer-exit
boundaries and both-profile private pixels are now separately integrated at
`2c21c2c` with bounded independent/combined PASS. Its full `56029` is still RUNNING;
the 1,281-test result above covers only earlier `cc1a6a4`. See the paired progress
report. Real stored Group+annotation/duplicate/return receipts, post-Group
replacement/morph/connector and hierarchy-aware isolate, stored Group SVG/PNG,
public/compiler/installed acceptance remain required.
All other Phase 3 primitives/actions and R-01–R-15/Phase 4–12 requirements remain.
No v1/Caleb behavior, semantic schema, public capability or installed-app change
is claimed. No release or production-readiness claim is made here.

Full main log: `sidecar/test-artifacts/phase-3aa-lifecycle-full-sidecar.log`,
SHA256 `CBE1DAFFDC60F174D3ADB4434A5F4E9C7C221A22CD84C4E0D1BFE880F6E453F1`.
Source/test tree remained exact to `cc1a6a4` at completion. No skips were added
by this slice and no test assertions were weakened.
