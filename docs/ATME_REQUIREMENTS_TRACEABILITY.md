# ATME requirements traceability — audit snapshot

Audit date: 2026-10-12 (Africa/Lagos). Audit-only; no implementation approval implied.

Main checkout: `ce939f347eab2f210a1f132f15c578a3bcc680f7`, branch `codex/visual-pipeline-v2`. Main application/source/test/schema content has no diff from `fc480037`. Isolated Split checkout: `C:/Users/USER/.codex/worktrees/phase3-return-receipts/Movie engine`, HEAD `cb8c9739f6b633517d43815787f4e6b60bd520bd`, with unfinished Task 2 changes. Neither isolated code nor current source is evidence of installed behavior.

This report interprets existing authority; it does not replace the authoritative Phase 3 ledger or approve a new scope. Evidence identifiers refer to the register in [the blueprint](ATME_MASTER_EXECUTION_BLUEPRINT.md#evidence-register).

## Authority and discovery

| Order | Source | Authority and application |
|---|---|---|
| 1 | Owner's current audit request, attached `Pasted text.txt`; owner decisions recorded in current ledger and approved Split plan | Audit only; preserve stack, approved phase, all requirements, data and active work. Implementation requires a final owner decision. |
| 1 | `ATME_V4_MIGRATION.md`; `ATME_VISUAL_PIPELINE_REBUILD.md` protected invariants | Current architectural authority: external AI supplies semantics; MCP carries artifacts; ATME validates/stores/compiles/renders locally. Two narrative-authority modes; cleaned timeline controls downstream timing. |
| 2 | `ATME_VISUAL_PIPELINE_TRACEABILITY.md`; `ATME_VISUAL_PIPELINE_PHASE_3_REMAINING_MATRIX.md`; approved Split design/eleven-task plan | R-01–R-15 remain required. Phase 3 is active; Phase 4–12 are not silently optional. Current ledger owns status and fixed scoring. |
| 2 | `C:/Users/USER/Desktop/ATME DOCS/ATME_Production_Architecture_Refactor_Specification_v2.md`; editor research/approval plan; V2/V4 progress | Locked refactor direction and later corrections. Where earlier deferrals conflict with V4, V4 explicitly supersedes them. |
| 3 | `PROJECT_PLAN.md`, accepted ADR-0001–0004, original `Automated AI Pipeline for Technical Hand-Drawn Vid.docx` and its extracted text | Historical product/engineering specification, still applicable only where not superseded. CPU-first layered SVG/FFmpeg approach is retained. |
| 4 | Original Caleb channel analysis DOCX/extracted text; archived four-page research PDF; three forensic ZIPs in `Desktop/ATME DOCS`; `CALEB_PRODUCTION_RULES.md` | Evidence and research-derived grammar. Biography, inferred tools, sample timing, Remotion suggestions and sample sponsor structure are not independent approval to change architecture or force templates. |
| 5 | Dated progress logs, agent plans, scratch `.superpowers/sdd/.../progress.md`, historical test reports | Evidence of bounded work; cannot promote an unimplemented capability or override owner requirements. Scratch records contain stale intermediate statements. |

Inventory was created before deeper inspection: `audit-evidence/2026-10-12/inventory.json` (298 selected source/document/configuration files), plus initial hashes for 254 tracked source/test/schema/asset files. Discovery covered repository subdirectories, project `.codex`, all Git worktrees, `Desktop/ATME DOCS`, `Desktop/Atme projects`, installed ATME databases, and the separately identified Basic Knowledge folders. Inaccessible old temporary pytest directories were recorded by Git; they were not treated as missing production requirements. No claim is made to have read every line of every generated file or unrelated desktop project.

## Classification rules

VERIFIED WORKING means the **stated bounded behavior**, supported by named tests/logs/artifacts; it never means complete product acceptance. IMPLEMENTED, UNVERIFIED means code exists without sufficient applicable verification. PARTIALLY IMPLEMENTED means meaningful work remains. BROKEN requires observed failure. MISSING means no required runtime implementation was identified. BLOCKED names an access/environment/verification impediment. SUPERSEDED requires a later authority. Historical and fresh evidence are distinguished.

## Core requirements

Paths below are repository-relative. Python module names are under `sidecar/src/atme/`; tests under `sidecar/tests/`.

| ID | Requirement / authority | Implementation and evidence | Audit classification / remaining verification |
|---|---|---|---|
| A-01 | External AI semantic authority, no production internal provider; V4 | `mcp_server.py`, `project_service.py`, retired routes, `pyproject.toml`, V4 progress | PARTIALLY IMPLEMENTED: active boundary exists, but obsolete `agents/`, gateway, prompts, cognitive/pipeline entry paths and tests remain pending replacement acceptance. Do not reactivate or delete during audit. |
| A-02 | Explicit approval of exact external script; V4 | `project_service.py`, approval event/version tables, `test_project_service.py`, `test_mcp_server.py` | VERIFIED WORKING for bounded revision/approval checks in historical source suite; final production creative approval remains per project. |
| A-03 | Recording-only authority and script-plus-recording authority; V4 | `narrative_source.py`, `project_timing.py`, `test_project_timing.py` | VERIFIED WORKING at source contract level; timing tests mock acoustic recognition. Accuracy on real speech remains unverified by those tests. |
| A-04 | Immutable recording; accepted cleanup controls timing; V4/source-preparation change | `source_timeline.py`, `timeline_media.py`, version/event tables; `test_source_timeline.py` | VERIFIED WORKING for bounded revisioned edits, history and linked media behavior. Full current desktop playback is unverified. Legacy automatic silence slicing must not run on approved project cleanup. |
| A-05 | Durable revision/conflict checks and dependency invalidation; rebuild invariants | `store/db.py`, `project_service.py`, `project_runner.py`; service/runner/revision tests | VERIFIED WORKING within exercised source paths; full v2 artifact-to-export cache matrix remains incomplete. |
| A-06 | Actual MCP, truthful client identity and capability reporting; V4 | `mcp_server.py`, `mcp_runtime.py`, `mcp_activity.py`; actual stdio tests | IMPLEMENTED, UNVERIFIED for current live installed connection; historical source/frozen tests exist. Fresh audit results and limitations are in blueprint. No connector was used to modify real projects. |
| A-07 | Manual source corrections, bounded selected-range AI proposals, explicit application; editor plan | `revision_requests.py`, `source_timeline.py`, `server/board_proposals.py`, `app/src/studio.ts` | VERIFIED WORKING for tested source operations; PARTIALLY IMPLEMENTED as full v2 visual editing workflow. Static UI tests are not interactive desktop tests. |
| A-08 | Deterministic local rendering and segmented resume; ADR-0001/0004/V4 | `render/animator.py`, `pipeline.py`, runner, render checkpoint/offline tests | VERIFIED WORKING for bounded v1 fixtures and historical tests; full v2 public workflow is MISSING. Network-blocked test mocks recognition and denoise; it is not real-narration or OS-wide isolation proof. |
| A-09 | Reliable MP4 export | FFmpeg streaming/assembly, `media_delivery.py`, `project_runner.py` | VERIFIED WORKING for legacy sample codec/container and bounded historical tests. Long-form premium production and latest installed export are unverified. |
| A-10 | Both LONG_FORM_16_9 and SHORT_FORM_9_16, independently composed | profiles, v2 fixtures/style bundle, offline tests | PARTIALLY IMPLEMENTED: authored profile support exists; automatic semantic recomposition is Phase 4/11, not a resize. |
| A-11 | Resource limits, CPU/HDD suitability, no dumped frame sequence | guardrails, serial worker, streaming renderer; calibration and Phase 0 report | PARTIALLY IMPLEMENTED: small v1 benchmarks exist; dense v2/long-project budgets remain unproven. Historical hardware/timing is not a fresh benchmark. |
| A-12 | Installable desktop, no orphan processes, offline reopen/resume | Tauri Rust host, `parent_watch.py`, NSIS hooks, installer tests, V4 progress | IMPLEMENTED, UNVERIFIED against current source in installed app. Preexisting dirty binaries and different source/package histories require identity-aware release testing. |
| A-13 | Technical alignment on final audio | ADR-0003, `audio/align.py`, project timing and cleaned timeline | PARTIALLY IMPLEMENTED for production accuracy: ordering is explicit; empirical word/visual onset accuracy on complete approved narration is not established. |
| A-14 | Jev advisory only; no author/apply/approve authority | rebuild invariants; `jev_decisions.py`, dedicated tests | IMPLEMENTED, UNVERIFIED in this audit's live integration; historical tests exist. Paid/external calls deliberately not invoked. |
| A-15 | Accessibility, keyboard control, preview continuity | original plan and editor plan; TS/CSS studio and source interaction tests | PARTIALLY IMPLEMENTED: controls/styles exist; fresh keyboard, contrast, playback/navigation and installed accessibility inspection not performed. |

## Current visual requirements (all retained)

| ID | Approved requirement | Identified implementation / evidence | Audit classification and exact gap |
|---|---|---|---|
| R-01 | Rich executable objects | `contracts_v2.py`, `render/v2_*`, style/asset registry; P3-01–43 | PARTIALLY IMPLEMENTED. Basic geometry, text, freehand, illustration, masks and evidence mechanics exist. Brackets, code/callouts, richer technical visuals/charts, parts, media runtime and other finite rows remain. Schema declarations are not runtime support. |
| R-02 | Canonical actions from storyboard to export | state/replay, Count/Morph/Group/annotation implementations; Split worktree | PARTIALLY IMPLEMENTED. Group has private evidence; public admission closed. Split Task 1 bounded pass; Task 2 partial. Non-list disclosure and sound-event ledger missing. Full public action parity missing. |
| R-03 | Deterministic semantic Visual Director/Compiler | `board_compiler.py` only assigns existing elements/word anchors; runner snapshots inputs | MISSING for approved rich compiler. Existing deterministic compilation is narrower than composition synthesis and instruction coverage. |
| R-04 | Visible, bounded fallback; no fallback-only production | generic `render/autolayout.py`; Phase 0 semantic-loss reproduction | MISSING as production gate. Structural validation does not establish faithful storyboard execution. |
| R-05 | Versioned original production grammar through MCP | schemas/resources, `ProjectService.capabilities()` | PARTIALLY IMPLEMENTED. `v2_renderer_available=False` is truthful. Full directing grammar and production notifications remain Phase 9. |
| R-06 | Semantic/visual production validation | structural/revision/timing checks | MISSING as complete quality gate. Needs coverage, legibility, density, pacing, evidence, continuity, payoff and human criteria. |
| R-07 | Original provenance-aware asset families | sixteen original registry assets/eight families; Phase 2 report, registry/font tests | PARTIALLY IMPLEMENTED. Foundation has bounded verification; richer variants, semantic parts/anchors and compiler selection remain. |
| R-08 | Complete evidence-to-annotated-developed-return cycle | `project_assets.py`, evidence/mask/annotation/return runtime and stored receipts | PARTIALLY IMPLEMENTED. Full claim-to-evidence narrative cycle and public/installed rendering unproven; richer apertures/cross-object annotation remain. |
| R-09 | Narrative board memory and developed returns | hierarchy replay, return receipts, stored A/B/A proofs | PARTIALLY IMPLEMENTED. Mechanical memory exists; creative board selection and opening-to-ending resolution remain Phase 6. |
| R-10 | Explanatory object/relationship motion | transforms, connectors, replacement, geometric morph, Count, hierarchy | PARTIALLY IMPLEMENTED. Genuine mechanics exist; approved whole vocabulary and coherent full explanation not delivered. |
| R-11 | Attention choreography | highlight, cross-out, dim, isolate, flat-list disclosure | PARTIALLY IMPLEMENTED. Automatic semantic choice is external/compiled; reading/listening priorities and whole-narrative validator incomplete. |
| R-12 | Complete Paper & Ink style | pinned OFL fonts, tokens, asset registry, v2 SVG | PARTIALLY IMPLEMENTED. Foundation verified historically; all primitive/style-token consumption and installed parity remain. |
| R-13 | Forensic contracts live throughout runtime | versioned schemas, migration adapter, resolved storage/history | PARTIALLY IMPLEMENTED. Contract/storage foundations exist; compiler-to-production enforcement incomplete. |
| R-14 | SFX/music/silence/punctuation with narration priority | SoundAction vocabulary; narration polish/mux | MISSING as editorial sound runtime. Do not confuse narration audio with sound-event ledger or mixing. |
| R-15 | Full golden/visual/offline/migration/performance/installed/human acceptance | 1,653 historical passes, private pixel evidence, fresh audit subset | PARTIALLY IMPLEMENTED; native reliability BLOCKED. Passing slices do not satisfy the complete corpus or 16/20 human gate. |

## Superseded requirements and contradictions

| Earlier statement | Later authority / resolution |
|---|---|
| Topic-to-video internal research/writer/verifier/provider settings and default TTS | SUPERSEDED as production direction by V4 external-AI/original-recording authority. Legacy source still exists for migration compatibility. |
| Research plan says defer MCP/provider retirement until complete video gate | SUPERSEDED by explicit V4 migration sequence. Do not resurrect this old deferral. |
| Original proposal names Manim; archived research proposes Remotion | Accepted ADR-0001/current protected architecture retain layered SVG/FFmpeg. Research does not approve a platform replacement. |
| ADR-0003 includes automatic silence slicing | Current project source-cleanup contract controls edits; retained legacy pipeline must not recut accepted project audio. The invariant of aligning final audio remains. |
| Old traceability rows say annotation/Count unimplemented | Current finite Phase 3 ledger and later checkpoint evidence supersede dated prose within its verified scope. Public release remains unavailable. |
| Scratch Split progress says Task 1 in progress and Task 2 not started | Later terminal entries and main ledger supersede intermediate notes. Task 1 passed bounded review; Task 2 remains partial. |
| Historical 23.7% | No supporting denominator/record found in inspected project docs or a targeted search of the main rollout. Treat as owner-supplied historical reference, not validated product completion. Current reproducible Phase 3 score is 2150/7900 = 27.2%. |
| Basic Knowledge proof rounds starts nearest-frame in top-level manifest | `proof.cue_start_quantization` and r03 report explicitly supersede draft rounding with ceiling-to-frame. Do not apply the obsolete rule to r03. |
| Talking-head report says source picture is never compiled | Current runner materializes and copies source video; this old finding is not a current blanket failure. Full v2 presenter runtime is still absent (P3-40). |

No full-product weighting exists that supports a defensible overall verified percentage. Final Phase 3 accepted count is 0/79, while 25 rows have bounded regression evidence. These are different measures. Neither zero final acceptance nor 27.2% engineering credit means nothing has been built.
