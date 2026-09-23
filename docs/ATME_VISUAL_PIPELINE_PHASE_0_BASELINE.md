# ATME visual-production rebuild — Phase 0 baseline

Date: 2026-09-20

Checkout: `master` at `0b454a34c1f7fb4258df352bc387369a21a38a10`

Baseline scope: tracked source, current installed project database, existing automated suites, deterministic render fixture, and approved research rules

## Decision

Final independent assessment: **PASS**.

The auditor confirmed the requirements ledger, research integrity, semantic-loss reproduction, build identities, package checks, project digest, research preservation, performance landmarks, and immutable rollback point. Phase 0 closed at commit `d041fed`; Phase 1 may begin.

## Worktree preservation

The checkout was already dirty before this rebuild began. Existing user/generated state is preserved.

- 33 tracked changes are confined to packaged build output, frozen sidecar output, and `packaged-exe-out.txt`.
- Numerous untracked packaged-smoke directories, test directories, logs, media fixtures, and diagnostic artifacts already exist.
- No cleanup, reset, deletion, checkout, or replacement was performed.
- Evidence added by this phase is limited to:
  - `docs/ATME_VISUAL_PIPELINE_REBUILD.md`
  - `docs/ATME_VISUAL_PIPELINE_TRACEABILITY.md`
  - `docs/ATME_VISUAL_PIPELINE_PHASE_0_BASELINE.md`
  - `docs/ATME_VISUAL_PIPELINE_PHASE_0_MANIFEST.json`
  - `docs/research/caleb_writes_code_reverse_engineering_blueprint.pdf`
- `bench/smoke_packaged.py` is a deliberate Phase 0 test correction: its obsolete internal-provider assertions were replaced with the approved zero-key/external-AI contract, provider-retirement checks, authentication check, graceful shutdown, and orphan detection.
- `.gitattributes` is Phase 0 preservation metadata; it marks PDF research evidence as binary so checkout normalization cannot corrupt it.

Generated build state must remain excluded from source-diff conclusions. Later phase reports must list source/schema/test changes separately from package regeneration.

The complete porcelain-status inventory is covered by deterministic classification rules with no unclassified entry:

| Category | Count | Classification rule |
|---|---:|---|
| Generated packaging | 33 | `sidecar-build/**`, `sidecar-dist/**`, `packaged-exe-out.txt` |
| Generated test/temporary output | 332 | `.packaged-*`, `.test-tmp-*`, `.tmp-*`, `test-artifacts/**` |
| Diagnostic logs | 11 | existing trace, verify, shutdown, and runtime `.txt`/`.log` files |
| Failure-baseline media | 1 | `ATME-What-Is-ATME-Caleb-Style.mp4` |
| Phase 0 evidence | 5 | four rebuild/baseline documents plus the archived blueprint |
| Phase 0 test correction | 1 | `bench/smoke_packaged.py` |
| Phase 0 preservation metadata | 1 | `.gitattributes` |
| Unclassified | 0 | — |

This classification does not declare generated files disposable. It records ownership so they are not accidentally included, reset, or removed.

## Automated baseline

| Check | Command | Result |
|---|---|---|
| Python suite | `sidecar/.venv/Scripts/python -m pytest -q` in `sidecar` | PASS; reached 100%; exit 0 |
| Python collection | `pytest --collect-only -q` with per-file count aggregation | 267 tests collected |
| Focused protected behavior | offline render, board continuity, evidence, MCP runtime, studio interaction | PASS; exit 0 |
| Frontend typecheck/build | `pnpm run build` in `app` | PASS; TypeScript and Vite production build |
| Rust host | `cargo check` in `app/src-tauri` | PASS; completed in 7m49s |
| Packaged sidecar startup | updated zero-key `bench/smoke_packaged.py` | PASS; health, auth, retired providers, shutdown, no orphan |
| Packaged MCP stdio | frozen sidecar against real MCP client tests | PASS; live handshake and project round trip |

The green suite proves current mechanical behavior only. It does not prove R-01–R-15 visual-production completeness. Existing tests strongly cover project state, timing, revisions, source editing, offline rendering, basic boards/evidence, MCP, and studio contracts; they do not yet constitute a rich-production golden corpus.

## Deterministic renderer performance baseline

Fixture: `schemas/examples/excalidraw-layout.example.json`

Render: 8 seconds, 1280x720, 30 fps, 240 frames

Output location: disposable OS temporary directories

| Run | Wall time | Bake rate | MP4 bytes | Legacy gate |
|---|---:|---:|---:|---|
| Cold | 10.60 s | 22.7 fps | 22,220 | PASS (>=8 fps) |
| Warm | 9.28 s | 26.0 fps | 22,220 | PASS (>=8 fps) |

Limitation: this fixture uses the current small primitive/action vocabulary. It is a compatibility landmark, not evidence that dense v2 illustrations, masks, object motion, evidence composition, or portrait recomposition meet performance budgets. Phase 3 and Phase 11 require new dense and long-form benchmarks.

Additional compatibility landmarks:

| Fixture | Dimensions | Frames | Bake rate |
|---|---:|---:|---:|
| Stateful board/return | 600x400 | 180 | 66.3 fps |
| Embedded evidence excursion | 600x400 | 180 | 106.0 fps |
| Portrait stateful board | 720x1280 | 180 | 21.5 fps |

These are small v1 fixtures and do not replace future dense-scene and full-duration budgets.

## Build identity decision

Two baselines are deliberately separated:

- **Behavioral baseline:** the currently installed ATME desktop, SHA-256 `C0FBA75920BB1B03C49BCF5E674F2050A00319FD9624DA28756F97ADE980EEF2`.
- **Implementation baseline:** the recorded Git commit plus the explicit working-tree manifest.

The current release desktop executable has a different SHA-256 (`D35AD9FCE422FEA2333DFDB0A1C9B4FBC70B077ACDFB9238D3BDD7F2A10AE102`) and is not treated as the installed behavioral artifact. The installed and current packaged sidecars do match at SHA-256 `F9D2647ACF82F4A3B1288AAA0C7DF381C6FB2B48C245D06DF4CF3AD9CCFF368E`.

The detailed identity and authority hashes are in `ATME_VISUAL_PIPELINE_PHASE_0_MANIFEST.json`.

## Installed-state inspection

Database inspected read-only: `C:\Users\USER\AppData\Local\ATME\jobs\jobs.db`

- Database size: 262,144 bytes.
- Six project rows exist.
- Project 3, `Blockchain Technology`, is the only project with production artifacts.
- Project 3 is revision 7, profile `LONG_FORM_16_9`, legacy input kind `idea-first`, with approved script revision 2.
- Stored artifacts:
  - brief revision 1;
  - script revision 2;
  - storyboard revision 3;
  - layout revisions through 7.
- No completed render run is recorded for the project.

### Reproduced semantic-loss defect

Storyboard revision 3 contains:

- 8 beats;
- 35 requested assets;
- 27 requested visual actions;
- 8 fallback descriptions;
- requested action kinds: reveal, split, highlight, connect, move, count, group, replace, and cross-out.

Layout revision 7 contains:

- 16 executable elements total;
- 9 rectangles;
- 7 text elements;
- no arrows;
- no evidence images;
- no pictogram or illustration type;
- only draw and reveal actions.

The board timeline declares 8 boards and 8 activations. Each board activates exactly once for one sequential interval; no board returns. `camera_intent` is absent.

This proves the current failure path:

1. The external AI supplied a richer storyboard.
2. The executable contract could not represent most assets/actions.
3. The final layout reduced the plan to text and rectangles.
4. Fallback descriptions existed for every beat and were effectively allowed to define the result.
5. Structural validation did not reject the semantic loss or disposable-board slideshow behavior.

The live project database changes as MCP heartbeats arrive, so it was not copied or modified. A single SQLite read transaction produced a canonical logical digest of project-content tables, excluding MCP activity: `eafe7d81aeab683896aaeb880a3e7f359420c188be011bf9d972566eb47db1df`. The authoritative source recording hashes to `37a24c69a1b1ff6b77eb8e559927f3a4601047aa46eac6fe40b7f25335465d4f`.

At capture time all 34 MCP session rows had no end timestamp. This is recorded as a connection-lifecycle defect baseline, not accepted behavior.

## Known defective visual baseline

`ATME-What-Is-ATME-Caleb-Style.mp4` is preserved as failure evidence, not a golden target.

- SHA-256: `4706962D0714C81F405B6681DC85F5F87217DF76B0329A2DF769EDC1497CD25E`
- 720x1280, 30 fps, 21.658 seconds
- Phase 0 human-rubric score: **10/20**

The score reflects minimal causal structure, sparse boxes/text, limited semantic color, no evidence cycle, no rich illustration, no demonstrated board return, and a weak visual payoff. It is below the required 16/20 threshold.

## Current protected architecture evidence

| Invariant | Current evidence | Phase 0 conclusion |
|---|---|---|
| External AI / no active internal provider | `README.md`, `docs/EXTERNAL_PRODUCTION.md`, `sidecar/pyproject.toml`, retired provider routes/tests | Protected; legacy source remains and needs regression surveillance |
| Authoritative Narrative Source modes | `narrative_source.py`, `project_timing.py`, V4 migration/progress docs and tests | Protected |
| Cleaned timeline authority | `source_timeline.py`, `timeline_media.py`, source-timeline tests | Protected |
| Immutable/versioned project artifacts | `project_service.py`, project artifact tables, revision tests | Protected |
| Deterministic/offline render | renderer tests and `test_project_offline_render.py` | Protected mechanically; richer v2 path must retain it |
| Manual editing and bounded revisions | `source_timeline.py`, `revision_requests.py`, studio interaction tests | Protected |
| MCP project boundary | `mcp_server.py`, `mcp_runtime.py`, MCP tests | Protected mechanically; directing grammar is incomplete |
| Jev advisory only | `jev_decisions.py` and tests | Protected; verify every future call site |
| Preview/export shared semantics | current preview uses renderer components; parity coverage is incomplete for future v2 state | Partial; becomes a hard gate in Phase 3 onward |
| Independent 16:9/9:16 composition | profiles exist and both offline renders are tested | Partial; current support proves dimensions, not semantic recomposition |

The packaged entry point exposes only HTTP service or MCP modes. Fresh packaged checks confirmed provider configuration writes return HTTP 410, internal topic-generation jobs return HTTP 410, no model call is made, authentication remains required, stdio MCP connects, and graceful shutdown leaves no orphan. Migration-era `cognitive.py`, `agents/`, `gateway/`, and prompts remain in source but are not reachable from the packaged desktop entry point; they remain a removal/migration concern rather than an active production dependency.

## Research preservation

- The 29-file forensic-study manifest and all recorded paths/sizes/hashes were independently verified.
- All three supplied forensic ZIPs match their supplied checksum files.
- The four-page blueprint was copied out of the temporary preview directory without modification to `docs/research/caleb_writes_code_reverse_engineering_blueprint.pdf`; both copies hash to `DD807F8C639BCD4AD88B15B4C441137E4B24B51866E93C23A21B13B1E9AAD485`.

## Authoritative source areas for the rebuild

### Contracts and research

- `schemas/visual-plan.schema.json`
- `schemas/excalidraw-layout.schema.json`
- `schemas/cue-timeline.schema.json`
- `schemas/reference-video-analysis.schema.json`
- `docs/CALEB_PRODUCTION_RULES.md`
- approved forensic packets and aggregate reports outside the repository

### Compilation, validation, and project authority

- `sidecar/src/atme/visual_plan.py`
- `sidecar/src/atme/board_compiler.py`
- `sidecar/src/atme/external_inputs.py`
- `sidecar/src/atme/store/contracts.py`
- `sidecar/src/atme/project_service.py`
- `sidecar/src/atme/project_runner.py`
- `sidecar/src/atme/project_timing.py`

### Renderer

- `sidecar/src/atme/render/animator.py`
- `sidecar/src/atme/render/svg_builder.py`
- `sidecar/src/atme/render/visibility.py`
- `sidecar/src/atme/render/camera.py`
- `sidecar/src/atme/render/evidence.py`
- `sidecar/src/atme/render/autolayout.py`

### MCP and studio

- `sidecar/src/atme/mcp_server.py`
- `sidecar/src/atme/mcp_runtime.py`
- `sidecar/src/atme/mcp_activity.py`
- `sidecar/src/atme/revision_requests.py`
- `app/src/studio.ts`
- `app/src/board-editor.ts`
- `app/src/board-proposal.ts`
- `app/src/main.ts`

## Phase 1 prerequisites and risks

1. Do not build the compiler before the canonical v2 schemas and migration policy are fixed.
2. Do not add rich renderer behavior to only preview or only export.
3. Do not reinterpret legacy artifacts in place; create versioned adapters and new revisions.
4. Do not make schema presence synonymous with support; capabilities require implementation and tests.
5. Do not expose v2 MCP guidance before the runtime can execute it.
6. Do not activate strict quality blocking until capable primitives/compiler paths exist; validation can be introduced in report-only mode first.
7. Do not benchmark v2 against the simple 22 KB legacy fixture alone.
8. Do not use installed user project data as a writable test fixture.
9. Do not allow every storyboard fallback to become a production scene.
10. Do not treat landscape-to-portrait cropping as composition.

## Phase 0 exit checklist

- [x] Approved goal and phase order recorded.
- [x] R-01–R-15 ledger recorded.
- [x] Protected invariants recorded.
- [x] Dirty-tree/generated-state inventory recorded.
- [x] Current Python, frontend, and Rust baselines executed.
- [x] Current deterministic render benchmark recorded.
- [x] Stateful-board, evidence, and portrait compatibility benchmarks recorded.
- [x] Installed project inspected read-only.
- [x] Installed project-content logical digest recorded without copying the live database.
- [x] Semantic-loss failure reproduced with counts.
- [x] Source ownership areas mapped.
- [x] Installed/current build identities separated and hashed.
- [x] Packaged zero-key startup/provider-retirement smoke passed.
- [x] Packaged MCP stdio handshake and project round trip passed.
- [x] Known defective output hashed and scored.
- [x] Temporary four-page blueprint preserved and hashed.
- [x] Independent auditor recheck received and all remaining corrections resolved.
