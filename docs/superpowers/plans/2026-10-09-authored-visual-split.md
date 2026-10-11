# Authored Visual Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute one externally authored visual Split with exact correspondence, immutable capture, continuous construction, atomic completion and retained history, without weakening the complete approved visual-family matrix.

**Architecture:** A dedicated discriminated `SplitAction` owns the entire operation. Strict contracts bind participants; an immutable chronological capture drives phase sampling and the existing compositor/observers. Primitive adapters must prove their actual content and construction support; parsing a family name never enables a fallback renderer.

**Tech Stack:** Existing Python 3.12/Pydantic v2 sidecar, frozen dataclasses, JSON Schema 2020-12, existing SVG/resvg/PNG composition, pytest, Ruff and local project storage. No new LLM, rendering platform or dependency upgrade.

**Spec:** `docs/ATME_VISUAL_PIPELINE_PHASE_3_SPLIT_DESIGN.md`, written contract approved by the human on 2026-10-09. Also retain `docs/ATME_VISUAL_PIPELINE_PHASE_3_REMAINING_MATRIX.md` and the R01–R15 rebuild/traceability documents.

## Global Constraints

- Preserve MCP/project architecture, Authoritative Narrative Source, cleaned timing authority, immutable media/revisions, deterministic/offline rendering and v1/Caleb behavior.
- One visible source; 2–256 ordered, unique, preauthored hidden result roots; pairwise-disjoint owned closures; same active board; at most 4096 distinct bound objects.
- `post_state: "removed"`, outer `easing: "linear"`; only named phase easing animates. No fragmentation, semantic interpretation, inferred destination or generated artwork.
- Integer ticks 0–10000, start < end; `start_ms + floor(duration_ms * tick / 10000)`; reject collapsed millisecond phases. Continuous easing only: linear/ease_in/ease_out/ease_in_out.
- Semantic state/version commit occurs once at outer end. Phase envelopes may paint earlier; no early semantic commit and no synthetic child version increment.
- Stable content, captured basis and final completion use separate canonical digests. Preserve Count rational/text provenance, Morph geometry, asset/style pins and legacy serialization.
- Common-parent and explicitly authored distinct-parent cases are required. No reparenting, layer-order inference, hidden gap, stale connector or evidence permission exception.
- Unsupported adapters remain named incomplete requirements, not permanent exclusions or generic-box substitutes. All R01–R15/Phase 4–12 exits remain.
- Existing execution method: main agent implements inline using executing-plans; the existing independent cross-reference auditor reviews bounded changes. Do not spawn replacement agents to bypass its usage limit.
- The Count baseline is source `fc480037`; its full main result is 1,653 passed, five symlink skips, exit 0. Original native failures remain unresolved. New work needs its own evidence.

## Review Focus

1. Previously Counted text and compound descendants: identity must retain exact effective payloads while pose/state changes affect only the basis (Task 2).
2. A harmless-looking sibling reorder or ancestor aperture edit: coherent rewritten hashes cannot authorize a capture of the wrong actual history (Task 4).
3. Schema-valid geometry with zero actual clipped paint: a result label or bounding box cannot satisfy continuity (Task 6).
4. Fractional enter endpoints and a move starting at the same millisecond: canonical quantization must avoid a one-frame jump or double writer (Task 5).
5. A duplicated project whose asset labels match but revision/checksum/authority differs: no stale source receipt or asset escape (Task 9).

## File boundaries and dependencies

Keep central typed models in `sidecar/src/atme/store/contracts_v2.py`; do not restructure unrelated contracts. Add focused renderer modules:

- `render/v2_split_clock.py`: model-independent integer phase resolution/progress.
- `render/v2_split_identity.py`: canonical family content projections and immutable content/basis/completion receipts.
- `render/v2_split.py`: captured ownership/read reservations and immutable sampled Split output.
- `render/v2_split_paint.py`: family/mode admission and compound construction/coverage proofs, using existing primitive paint rather than a second renderer.

Integration files: `v2_timeline_replay.py`, `v2_state.py`, `v2_svg.py`, `v2_hierarchy_replay.py`, `v2_lifecycle.py`, `v2_return.py`, `v2_evidence_reading.py`, and existing static/normal-write validators in `contracts_v2.py`. Touch `project_service.py` only if an existing generic stored-history/duplicate binding omits the new receipt; do not redesign its API/database. Schema generation remains `sidecar/tools/generate_v2_schemas.py`.

Tests: new `v2_split_fixtures.py`, `test_v2_split_contract.py`, `test_v2_split_identity.py`, `test_v2_split_capture.py`, `test_v2_split_action.py`, `test_v2_split_compositor.py`, `test_v2_split_lifecycle.py`, `test_v2_split_families.py`, `test_v2_split_project.py`, `test_v2_split_acceptance.py`. Reuse current Count/Group/Morph/return/evidence fixtures. Helpers author explicit source/result content; they never invoke production fragment generation.

Commands below run from the execution worktree's `sidecar` directory with the approved environment, e.g. `$atmePy = 'C:/Users/USER/Desktop/Movie engine/sidecar/.venv/Scripts/python.exe'`. Resolve the actual isolated root before use; never run against a guessed checkout. Use the managed worktree tools/using-git-worktrees at execution time. The source publisher is not an execution checkout.

## Task 1: Dedicated strict operation, legacy shape and schemas

**Files:** Modify `store/contracts_v2.py`; create `render/v2_split_clock.py`; create fixtures and `tests/test_v2_split_contract.py`; regenerate the two action-bearing schemas, inspecting all generator outputs.

**Interfaces:** Define `SplitPhase(start_tick, end_tick, easing)`, `SplitConstruction(mode, phase, enter_destination)`, `SplitMovement(phase, from_transform, destination)`, `SplitCorrespondence`, `SplitResult`, `SplitBasis`, `SplitPolicy` and `SplitAction` using existing StrictModel/Bounds/Transform types. Required fields are exactly the approved spec; `enter_destination` is required only for enter and rejected for other modes. Define `resolve_split_phase(start_ms: int, end_ms: int, phase: SplitPhase) -> tuple[int, int]` and `split_phase_progress(start_ms: int, end_ms: int, at_ms: int, easing: str) -> float`. Clock helpers must not import contracts at runtime; use type-only imports.

Pin the basis packet explicitly: `SplitPlacement` contains object ID, parent ID, sibling ordinal, local Transform, six finite affine components in existing a/b/c/d/e/f order, world Bounds, semantic state, effective visibility, reveal, local opacity, state version and content SHA256. `SplitClosure` binds a root ID to ordered owned IDs. `SplitReadDependency` binds a kind (`ancestor`, `aperture`, `mask_source`, `connector_anchor`, `annotation_anchor`) to ordered object IDs. `SplitAssetPin` contains asset ID, revision, resource URI and checksum SHA256. `SplitBasis` contains source closure, ordered result closures, ID-sorted placements, ordered read dependencies, ID-sorted asset pins, style SHA256 and registry SHA256. All object lists close against the actual layout and the 4096 distinct-object limit; no arbitrary dictionary payloads. Task 2's completion packet reuses placements/pins and binds source-basis and policy SHA256, retaining the distinction between unchanged child local fields and recomputed effective visibility.

Fixture interface: `split_documents(profile_id: str = "LONG_FORM_16_9", family: str = "geometry", result_count: int = 2, parent_policy: str = "common_parent") -> tuple[dict, dict, dict]` returns independently authored plan/layout/resolved documents with source ID `source` and result IDs `part-1` onward. Author its basis/expected receipts independently of production helpers; unsupported family fixtures are not fake executable objects.

- [ ] Write `test_dedicated_split_legacy_roundtrip` covering hierarchy-policy absent/null/non-null, split-policy absent/null, unchanged old Group-shaped canonical JSON/hash, single union discriminator and legacy execution rejection. Test `SplitAction` alone plus plan/resolved schema round trips.
- [ ] Write `test_split_policy_limits_and_phase_clock`: assert result lengths 1/257 reject, 2/256 parse; bound inventories 4097 reject; unknown fields/nonfinite/bool ticks reject; `(100, 111, ticks 1000..9000)` resolves `(101, 109)` and a collapsed interval rejects. Assert non-linear outer easing rejects.

```python
phase = SplitPhase(start_tick=1000, end_tick=9000, easing="linear")
assert resolve_split_phase(100, 111, phase) == (101, 109)
assert split_phase_progress(100, 200, 100, "linear") == 0
assert split_phase_progress(100, 200, 200, "linear") == 1
```
- [ ] Run `$atmePy -m pytest -o addopts= tests/test_v2_split_contract.py -q`; retain the specific expected missing-model/unsupported-contract failures, not a broken import environment.
- [ ] Implement the dedicated models; remove only Split from Group's literals. Declare `hierarchy_policy: None = None` and omitted optional policy serialization. Put source/correspondence/result order, IDs, required removed state and phase-channel validation in strict validators. Bare legacy reads stay intact; no runtime enabling.
- [ ] Run the contract tests plus `test_v2_hierarchy_contract.py`, `test_v2_count_contract.py` and `test_visual_contracts_v2.py`. Run `$atmePy tools/generate_v2_schemas.py` twice and prove byte-repeatability; reject accidental legacy/example changes.
- [ ] Commit only this task's files after bounded review.

## Task 2: Three identities, not one mutable paint hash

**Files:** Create `render/v2_split_identity.py`, `tests/test_v2_split_identity.py`; extend only Split receipt models in `store/contracts_v2.py`.

**Red/green command:** `$atmePy -m pytest -o addopts= tests/test_v2_split_identity.py -q`; red must demonstrate the named missing behavior, green must exit 0.

**Interfaces:** Define immutable `SplitContentReceipt(object_id: str, canonical_json: str, content_sha256: str)`. Provide `split_content_receipts(layout: ExecutableLayoutV2, sample: ReplaySample, asset_bytes: Mapping[str, bytes | VerifiedEvidenceBytes]) -> tuple[SplitContentReceipt, ...]`, `split_basis_digest(basis: SplitBasis) -> str`, `split_completion_digest(receipt: SplitCompletionReceipt) -> str`. Define strict `SplitCompletionReceipt` covering the spec's final root states/versions/poses, retained descendant local records, content and dependency identities. Mutable model inputs are canonicalized into immutable JSON; output order is explicit.

- [ ] Write `test_content_basis_completion_are_distinct`: assert pose/state/version/ordinal edits leave content digest unchanged but invalidate basis; content/glyph/Count rational/Morph geometry/style/asset edits invalidate content. A completion changing only a child version rejects.
- [ ] Write `test_known_payloads_and_canonical_correspondence`: assert unknown FrameObject subclass/unknown family field rejects; ID-sorted compound content is stable across sibling order while the basis changes; correspondence source/result digests and exact inventory order match; out-of-bounds source_region rejects.

Assertions after arranging original/pose-only/content-changed samples in the named identity test:
```python
assert original_content.content_sha256 == pose_only_content.content_sha256
assert original_content.content_sha256 != changed_content.content_sha256
assert split_basis_digest(original_basis) != split_basis_digest(pose_only_basis)
```
- [ ] Run identity tests red; implement explicit per-family projections, finite JSON and existing transform quantization. No `getattr`-based unknown payload acceptance or hashing the entire mutable FrameObject as content.
- [ ] Run identity/contract tests green and Count/Morph/Group receipt regressions. Keep asset pins independently verified; a caller-provided checksum is not proof.
- [ ] Commit the reviewed receipt boundary.

## Task 3: Semantic/layout/resolved reference and coverage closure

**Files:** Modify `store/contracts_v2.py`; extend `test_v2_split_contract.py`; add normal-write tests in `test_v2_split_project.py`; regenerate affected schemas.

**Red/green command:** `$atmePy -m pytest -o addopts= tests/test_v2_split_contract.py tests/test_v2_split_project.py -q`.

**Interfaces:** Add `_require_split_contract(action: SplitAction) -> None` and `_validate_split_references(action: SplitAction, objects: Mapping[str, ObjectBase], boards: Mapping[str, BoardSpec]) -> None`; integrate `_action_object_references` and existing plan/layout/resolved validators. ResolvedAction gains optional omitted `split_completion_receipt`, required by validated Split execution, never by old records.

- [ ] Write `test_split_references_include_results_and_dependencies`: assert source-only outer targets still require all results, owned closures, read dependencies, board and beat/coverage ownership; orphan/uncovered/foreign-board results reject.
- [ ] Write `test_normal_write_rejects_incomplete_split_atomically`: compare revision/artifact rows before and after missing policy, extra correspondence, false content digest, non-null container/hierarchy and missing completion receipt. No partial writes.

```python
assert {"source", "part-1", "part-2"} <= _action_object_references(action)
assert after_project["revision"] == before_project["revision"]
assert after_artifact_rows == before_artifact_rows
```
- [ ] Run these tests red; implement reference completeness without treating every referenced dependency as a state mutation. Source ends removed; result roots end visible; read-only dependencies keep state/version.
- [ ] Run focused contracts/project tests green and schema equivalence/repeatability. Existing project entrypoints/API shape and legacy hashes must remain unchanged.
- [ ] Commit the reviewed static boundary; runtime still rejects until Tasks 4–6.

## Task 4: Immutable capture, disjoint ownership and full reservations

**Files:** Create `render/v2_split.py`, `tests/test_v2_split_capture.py`; modify replay capture hooks and state validation.

**Red/green command:** `$atmePy -m pytest -o addopts= tests/test_v2_split_capture.py -q`.

**Interfaces:** Define frozen `SplitCapture(start_ms: int, end_ms: int, policy_json: str, basis_json: str, completion_json: str, owned_root_ids: tuple[str, ...], owned_object_ids: tuple[str, ...], read_dependency_ids: tuple[str, ...], baseline: tuple[FrameObject, ...])` and `capture_split(resolved: ResolvedAction, layout: ExecutableLayoutV2, before: ReplaySample, asset_bytes: Mapping[str, bytes | VerifiedEvidenceBytes]) -> SplitCapture`. Add a known frozen `CapturedSplitAction(CapturedAction)` carrying that capture; legacy CapturedAction/FrameObject shapes stay unchanged. Define `validate_split_reservations(capture: SplitCapture, actions: tuple[ResolvedAction, ...]) -> None`.

- [ ] Write `test_actual_capture_after_group_count_morph`: assert actual parent/ordinal/world/local/state/version/content basis after prior actions, both parent policies and nonidentity ancestors. Reordered authored arrays cannot override resolved chronology.
- [ ] Write `test_disjoint_closures_and_read_write_conflicts`: parameterize source-inside-result, result-inside-source, nested/shared result nodes and shared expanded instance; direct/root/descendant/ancestor/aperture/anchor writers all reject. Read-only camera observation passes.
- [ ] Write `test_coherent_stale_basis_cannot_replace_actual_history`: recompute a submitted hash after changing a sibling ordinal or aperture and assert rejection against the real sampled start.

```python
assert capture.owned_root_ids == ("source", "part-1", "part-2")
assert set(capture.owned_object_ids).isdisjoint(capture.read_dependency_ids)
assert capture.baseline == independently_expected_captured_frames
```
The disjoint read/write assertion applies to normalized reservation sets: dependencies already owned are removed from read-only IDs but remain bound in the basis.
- [ ] Run capture tests red; capture immutable known payloads, expand actual closures/read dependencies, require visible fully revealed source and hidden zero-reveal positive-alpha results. Compare all submitted receipts to actual history before any mutation.
- [ ] Run capture tests green and Group ownership/Count acceptance tests. Same-time prior completions must precede captures.
- [ ] Commit after independent bounded review; do not claim missing adapter families pass.

## Task 5: Phase sampling and one atomic outer completion

**Files:** Modify `v2_split.py`, `v2_timeline_replay.py`, `v2_state.py`; create `tests/test_v2_split_action.py`.

**Red/green command:** `$atmePy -m pytest -o addopts= tests/test_v2_split_action.py -q`.

**Interfaces:** Define frozen `SplitPaintEnvelope(root_id: str, action_id: str, mode: str, construction_fraction: float)` and `SplitSample(objects: tuple[FrameObject, ...], envelopes: tuple[SplitPaintEnvelope, ...])`; `sample_split(capture: SplitCapture, at_ms: int) -> SplitSample`. Define known frozen `SplitReplaySample(ReplaySample)` and `SplitFrameSnapshot(FrameSnapshot)` carrying envelopes only when present; legacy samples retain their existing classes/serialization. `version_targets(SplitAction)` returns source then ordered result roots, never read/child IDs.

- [ ] Write `test_phase_end_is_not_semantic_commit`: for source/result phases ending before outer end, assert painted completion persists but captured states/versions remain until exact outer end; assert removed source, fully visible results and exactly +1 root versions then.
- [ ] Write `test_enter_move_endpoint_and_seek_parity`: assert canonical fractional endpoint equality, source origin for reveal/draw/write, enter endpoint origin for later move, no concurrent transform writes; compare shuffled seeks to chronological samples at every phase boundary ±1ms.
- [ ] Write `test_split_does_not_resurrect_removed_source_or_mutate_children`: retained source Count payload/provenance remains exact; later source reveal rejects; descendant local payload/pose/state/version records remain captured while effective paint visibility may change.

```python
assert before_outer_end.object("source").state == "visible"
assert at_outer_end.object("source").state == "removed"
assert at_outer_end.object("part-1").state == "visible"
assert dict(at_outer_end.state_versions)["part-1"] == captured_versions["part-1"] + 1
```
- [ ] Run action tests red; reuse shared continuous easing and transform interpolation, add actual Split chronological support, completion receipt comparison and root-only commit. Do not lower into unrelated public actions.
- [ ] Run green with timeline replay, hierarchy, Count and return tests. Exact outer action end must be inside a sampleable board/timeline window, not an out-of-range test shortcut.
- [ ] Commit the reviewed replay boundary.

## Task 6: Real composition, compound envelopes and continuity

**Files:** Create `render/v2_split_paint.py`, `tests/test_v2_split_compositor.py`; modify `v2_svg.py` and verified snapshot consumers.

**Red/green command:** `$atmePy -m pytest -o addopts= tests/test_v2_split_compositor.py -q`.

**Interfaces:** Provide `validate_split_paint(capture: SplitCapture, layout: ExecutableLayoutV2, asset_bytes: Mapping[str, bytes | VerifiedEvidenceBytes]) -> None` and `split_construction_for(snapshot: FrameSnapshot, object_id: str) -> SplitPaintEnvelope | None`. Define frozen `SplitCoverageInterval(start_ms: int, end_ms: int, painted_root_ids: tuple[str, ...])` and `SplitCoverageProof(intervals: tuple[SplitCoverageInterval, ...])`; `prove_split_coverage(capture: SplitCapture, layout: ExecutableLayoutV2) -> SplitCoverageProof`. Compound paint uses the root envelope over the captured painted closure; it does not synthesize child actions/versions.

- [ ] Write `test_source_fade_and_authored_results_have_real_pixels`: independently assert start/mid/end SVG structure and PNG pixels for explicit marks, text and verified illustration results. No solid rectangle stand-in; actual sibling order survives opposing semantic order.
- [ ] Write `test_compound_draw_write_preserve_local_children`: root envelopes construct the proper eligible paths/glyphs in captured paint order; incompatible mixed closures reject until their faithful adapter is implemented.
- [ ] Write `test_zero_clipped_paint_does_not_satisfy_continuity`: source-ending-before-results, transparent/zero-reveal/clipped results and a movement through a closing aperture reject; an overlap with positively painted coverage passes. Bounds alone are insufficient.

```python
assert start_svg_sha256 != midpoint_svg_sha256 != completed_svg_sha256
assert actual_midpoint_pixels == independently_expected_midpoint_pixels
assert all(interval.painted_root_ids for interval in proof.intervals)
```
Include the exact zero-paint millisecond when source exit ends at result construction start, not only a positive-length blank gap. PNG oracles inspect authored glyph/path/asset pixels, not merely different hashes.
- [ ] Run compositor tests red; connect the envelopes to existing primitive construction, root opacity/clip/mask wrappers and asset preflight. Coverage proof must include phase/geometry critical intervals, not sparse frame sampling; unavailable proofs reject admission.
- [ ] Run green, both independent 16:9/9:16 compositions and adjacent SVG/PNG goldens. Preserve the base snapshot path and old frame hashes; public Group/provenance/capability admission is a separate existing gate.
- [ ] Commit the reviewed compositor boundary.

## Task 7: Complete family adapter matrix, not convenience narrowing

**Files:** Extend `v2_split_identity.py`, `v2_split_paint.py`, `v2_split_fixtures.py`; create `tests/test_v2_split_families.py`. Primitive implementation remains in the owning remaining-matrix work (paths/text/list/registry/container/media/evidence/chart/connector modules), not duplicate Split-only artwork.

**Red/green command:** `$atmePy -m pytest -o addopts= tests/test_v2_split_families.py -q`; each independently reviewed row has its own positive/negative parameter cases.

**Interfaces:** Define frozen `SplitFamilyAdmission(family: str, mode: str, content_sha256: str, proof_kind: str)` in `v2_split_paint.py`; `split_family_admission(object_id: str, capture: SplitCapture, layout: ExecutableLayoutV2) -> SplitFamilyAdmission` returns that known descriptor or raises a named unsupported-adapter error. Each adapter pins its proof_kind to its implemented analytic/primitive proof, not an unchecked author string. Every positive adapter feeds Tasks 2/4/6, not a parallel sampling pipeline.

- [ ] Add parameterized `test_split_family_matrix` with each row below. Assert independently authored source/result payloads, supported construction, pinned identity, real SVG/PNG and repeated seek parity; explicit unsupported cases assert their exact adapter gap, not a generic fallback.

```python
assert admission.family == expected_family
assert admission.content_sha256 == independently_authored_content_sha256
assert shuffled_seek_frames == ordered_seek_frames
assert rendered_payload_pixels == expected_payload_pixels
```
- [ ] Run red for newly enabled adapters; finish the owning primitive work before admitting that row. For every row, retain named negative proof until its positive adapter has its own approved contract/runtime tests. This is an execution dependency, not permission to omit the row.
- [ ] Enable/test the rows separately: geometry/freehand/marks/brackets; text/list/code/callout; registry/characters/devices/technical illustrations; truthful data-bound charts; group/clip/mask/composition/instance; checked image/source-video/presenter; attested evidence; semantic connectors/free-source pointers.
- [ ] For charts require actual series/labels/units/domain/scale/highlight/construction, not static artwork. For media require real range/frame decoding and crop/fit/focal decisions, not thumbnails. For reusable instances require expanded disjoint IDs and exact parent/aperture/world proof. Richer poses/internal parts and code/callout anchors depend on their remaining-matrix primitive contracts.
- [ ] Run green per completed row plus its primitive suite. **Task 7 and full Split acceptance remain incomplete while any required row lacks positive runtime proof.** Record its owning remaining-matrix dependency and exact missing proof in the progress ledger; never label a partial internal kernel as finished production Split.
- [ ] Commit each reviewed adapter separately.

## Task 8: Camera, connector/annotation and evidence lifecycle

**Files:** Modify `v2_state.py`, `v2_lifecycle.py`, `v2_evidence_reading.py`; extend strict evidence handoff models only when implementing the evidence adapter; create `tests/test_v2_split_lifecycle.py`.

**Red/green command:** `$atmePy -m pytest -o addopts= tests/test_v2_split_lifecycle.py -q`.

**Interfaces:** `validate_split_lifecycle(capture: SplitCapture, replay: ChronologicalReplay, layout: ExecutableLayoutV2, timeline: ResolvedVisualTimelineV2) -> None`. It uses existing world bounds, lifetime and reading validators. Evidence activation needs a strict `SplitEvidenceActivation` binding result, treatment, semantic beat/causal owner, permission/transformation pins, full-construction boundary and hold end; no hidden fake insert_evidence action.

Pin `SplitEvidenceActivation` fields: result_object_id, treatment_id, treatment_sha256, beat_id, causal_action_id (this Split's action ID), asset_pin (`SplitAssetPin`), permission_sha256, allowed_transformations, construction_complete_ms and readable_hold_end_ms. Add optional omitted `evidence_activation` to `SplitResult` only with this adapter; non-evidence results reject it. Re-derive all digests/times from the existing treatment/permission and actual phase windows, never trust caller assertions. Regenerate both action-bearing schemas. Ordinary evidence insertion and source-pixel/ownership rules remain unchanged.

- [ ] Write `test_camera_observes_actual_split_union`: changing visible source/result paint and masks affect camera targets; hidden outputs and initial coordinates do not. Independently authored camera retains its purpose/window rules.
- [ ] Write `test_retained_anchors_require_completed_handoff`: source-linked arrows/pointers, in-flight disconnect/reparent, Replace/Morph/Group overlap and board-wide Isolate/evidence holds reject; completed pre-capture removal or proved endpoint handoff passes.
- [ ] Write `test_evidence_activation_cannot_bypass_attestation`: absent activation, wrong causal owner, source hold still active, premature result hold, undeclared crop/rotation, bad bytes/permission and unreadable camera/aperture reject. Once the evidence adapter exists, positive holds begin only after full construction/movement and stay readable at all required boundaries.

```python
assert observed_world_bounds == independently_expected_visible_union
assert result_hold_start_ms >= max(construction_end_ms, movement_end_ms)
assert after_source_bytes == before_source_bytes
```
- [ ] Run red; implement actual sampled lifecycle dependencies, then evidence activation as part of the existing treatment/permission model. Keep evidence execution rejected until the entire handoff is representable and proven in semantic/resolved/stored contracts.
- [ ] Run green with connection/annotation/Isolate/evidence lifetime suites, both profiles and board returns. Never waive evidence to finish a smaller Split case.
- [ ] Commit separately reviewed observer and evidence boundaries.

## Task 9: Stored completion, A/B/A returns and duplicate authority

**Files:** Modify `v2_return.py`, known subtype handling in `v2_hierarchy_replay.py`, strict resolved receipt validators and only necessary generic ProjectService storage/duplicate hooks; extend `tests/test_v2_split_project.py`.

**Red/green command:** `$atmePy -m pytest -o addopts= tests/test_v2_split_project.py -q`.

**Interfaces:** Existing `validate_resolved_return_history` and `validate_return_sample` consume exact Split-derived states/content/versions/hierarchy; existing ProjectService write/duplicate signatures remain unchanged. Completion receipt is re-derived, not trusted because its hash is coherent.

- [ ] Write `test_stored_split_return_duplicate_exact_state`: real stored project in each narrative-authority mode, independently authored profiles, prior Group/Count/Morph, A/B/A, stable source payload and resulting root/descendant versions; duplicate rebinds project/authority/asset/cleaned-timing identities only.
- [ ] Write `test_stored_coherent_stale_split_rejects_atomically`: alter/re-hash policy, parent/order, phase, content, final pose/state/version, asset checksum/revision or authority; assert no revision/artifact committed and no media modified.

```python
assert returned_source.count_value == original_source.count_value
assert returned_source.display_text == original_source.display_text
assert after_failed_write_revision == before_failed_write_revision
assert duplicated_asset_pins == expected_rebound_asset_pins
```
- [ ] Run red; integrate known immutable payload/envelope/receipt handling with exact stored replay. Do not close caller-owned databases opportunistically or alter the unrelated constructor exception-safety debt.
- [ ] Run green with Group/Count/replacement/return/project evidence and schema tests.
- [ ] Commit the reviewed stored-history boundary.

## Task 10: Cross-matrix acceptance and performance/offline proof

**Files:** Create `tests/test_v2_split_acceptance.py`, `bench/verify_v2_split.py`, `docs/ATME_VISUAL_PIPELINE_PHASE_3_SPLIT_PROGRESS.md`; update authoritative phase matrix/traceability after actual evidence exists.

**Red/green command:** `$atmePy -m pytest -o addopts= tests/test_v2_split_acceptance.py -q`.

**Interfaces:** `bench/verify_v2_split.py` consumes fixed local authored fixtures/assets and emits deterministic frame hashes/contact sheets using the same validated history; no reference-video asset copying, online fetch or synthetic performance result.

Benchmark CLI: `$atmePy ../bench/verify_v2_split.py --output-dir test-artifacts/phase-3-split-offline`. Its `main()` requires the explicit output directory, emits a report with all named required cases/hashes/measurements, and exits nonzero on any missing or failed required case. A private partial-family diagnostic is a separately labelled report, never a successful final acceptance report.

- [ ] Add `test_split_acceptance_matrix`: both profiles, all completed family/mode combinations, source/result roles, common/distinct parents, nested apertures, prior actions, changed authored array order, same-time completions, malformed bounds/ticks/IDs, all reservations, arbitrary seeks and real stored/duplicate/return flows. Reference each of the nine original review findings to its test.

```python
assert proved_profiles == {"LONG_FORM_16_9", "SHORT_FORM_9_16"}
assert required_family_cases - positive_runtime_cases == set()
assert regenerated_old_frame_hashes == accepted_old_frame_hashes
```
The empty missing-case assertion is a final acceptance condition, not permission to delete unavailable cases from required_family_cases.
- [ ] Run negative additions red before changing their owner. Run acceptance/adjacent suites green with explicit exit codes; inspect expected pixels rather than only parseability or contact-sheet labels.
- [ ] Run offline preview/PNG proof and warmed/cold random seeks on the approved bounded 256-result/4096-object inventories; record measured latency/memory and retained immutable keys. Do not add an invented performance threshold or claim long-project UI performance from this kernel benchmark.
- [ ] Compare all50 old offline frame/report hashes unchanged and inspect v1/Caleb regressions. Keep unsupported family rows, native faults, production dependency locking and installed/creative gates explicit.
- [ ] Commit reviewed evidence; no final Split claim until Tasks 7–9 are fully proven.

## Task 11: Exact integration, full regression and publication

**Files:** Only the reviewed task files, generated schemas and authoritative progress ledgers; preserve unrelated dirty packaging/binaries/builds.

- [ ] Obtain bounded independent reviews per completed task and a final spec/matrix re-audit from the existing auditor. Queue requests while its account limit is active; no self-review is labelled independent PASS and no replacement agent bypasses the limit.
- [ ] Compare the execution worktree against the exact accepted main base and reviewed source boundaries; integrate without silent conflict resolutions. Run scoped Ruff and schema repeatability, then regenerate old offline proofs.
- [ ] Freeze the integrated source/tests/schemas/bench and run `$atmePy -m pytest -o addopts= -vv` with the retained diagnostic/crash-capture profile. Match process creation time/command, not PID alone: Windows may reuse a PID after exit. Retain actual terminal totals, exit code, skips, log hashes and any dumps; never restart merely because observation expired.
- [ ] Audit the full contract requirement-by-requirement. A green suite is not evidence for absent adapter cases, original native fixes or installed/creative acceptance. If a required case is missing, continue its owning task; do not shrink success.
- [ ] Publish only exact reviewed source/doc changes through the existing curated source branch with clean status, source comparisons and remote fast-forward guards. Installer/public capability/compiler/studio production activation remain their existing later approved gates, not incidental changes in this task.

## Self-review and handoff

The approved spec maps as follows: legacy/strict vocabulary → Task 1; identity and correspondence → Tasks 2–3; closure/parent/read reservations → Task 4; state/phase/clock/version rules → Tasks 1/5; compound construction/paint continuity → Task 6; complete family obligations → Task 7; camera/attention/anchor/evidence lifecycle → Task 8; immutable stored/duplicate/return behavior → Task 9; pixel/offline/negative/full regression → Tasks 10–11. Each Review Focus case has an owning named test. All new interfaces and immutable carrier types above have an owning task; family implementation dependencies do not become parse-only completion claims.

This is an implementation plan, not delivered behavior. Preserve the already selected inline implementation method. Human plan review precedes product-code work; independent review remains required and is currently unavailable at the auditor's account limit. The original full 12-phase/R01–R15 goal is unchanged.

Self-review completed on2026-10-11: explicit basis/receipt/carrier interfaces, independent assertion oracles, zero-paint boundary, separate commit steps, all eight family dependencies and process-identity verification are retained. Assertions above are test-design examples, not executed tests or product changes.
