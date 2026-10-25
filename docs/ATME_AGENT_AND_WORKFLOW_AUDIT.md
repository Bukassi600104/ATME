# ATME agent and workflow audit

2026-10-12 (Africa/Lagos). Read-only investigation of orchestration; no agents stopped, goals resumed, settings changed or configurations removed.

## What actually drives development

`/goal` is not implemented inside ATME's media pipeline. Local Codex configuration has `features.goals = true`; the runtime exposes goal management tools; `C:/Users/USER/.codex/goals_1.sqlite` contains `thread_goals` and continuation-deferral tables. The implementation chat's persisted goal is `usage_limited`, not complete or currently running. Its objective is the owner's instruction to finish the approved plan without skipping steps. The CLI/app slash-command parser and scheduler source were not available for line-by-line inspection; the conclusion is based on installed configuration, runtime tools and persisted state, not an assumption that every Codex distribution implements `/goal` identically.

Read-only snapshot of development chat `01a04a23-7c5c-7eb0-9fc0-7d300e409bbe`:

| Item | Evidence |
|---|---|
| Goal ID | `73fe3cac-6531-420a-b0aa-39852a2b45a3` |
| Goal status | `usage_limited` |
| Recorded token usage | 24,550,411; runtime accounting, **not an invoice or proven wasted tokens** |
| Recorded time | 120,218 seconds (~33.4 hours); not calendar duration or human labor |
| Token budget | null; no per-goal token cap recorded |
| Main chat runtime status | idle; latest turn failed because of usage limit |
| Current model metadata | `gpt-6-astra`, `low` |
| Local rollout size | 1,000,792,763 bytes (~1 GB) |
| Project task truth | `docs/ATME_VISUAL_PIPELINE_PHASE_3_LEDGER.md` |
| Current execution | Separate `phase3-return-receipts/Movie engine` worktree, Split Task 2 |
| Execution scratch state | `.superpowers/sdd/2026-10-09-authored-visual-split/progress.md` and task briefs in that worktree |

`state_5.sqlite` records thread metadata, rollout paths and `thread_spawn_edges`; JSONL rollouts store messages/tool history and compaction records. These runtime databases must not be edited by project code. Product restart/resume is a separate system: SQLite artifacts/stages, content-addressed run manifests and 60-second render segments. A Codex goal does not itself prove any ATME milestone complete.

For a user-authorized later resume, the Codex client controls usage recovery/resumption; the agent then reads the ledger and exact worktree checkpoint. A currently `usage_limited` goal is not safely described as an agent-controlled `paused` goal. This audit does not call create/update goal tools on that chat or send it a message.

## Agent inventory

The persisted spawn graph contains **one named project development subagent**, not a large redundant implementation team. `agent-inventory.json` contains the exact IDs and edge. The forensic skill's `agents/openai.yaml` is skill UI metadata, not evidence of a running developer. No repository agent-role configuration was identified beyond that skill metadata. Global agent-role overrides were not present in the inspected safe config fields.

| Agent / role | Model and trigger | Dependencies / useful evidence | Assessment |
|---|---|---|---|
| Main implementation coordinator, chat title `ATME Video production Engine` | State metadata: GPT-6 Astra Low. Goal continuation/user follow-up; previously used multiple Sol/Astra settings | Reads approved plan, implements inline, runs tests, publishes ledger checkpoints | RETAIN one coordinator; route routine work to GPT-6.1 Sol Medium after owner approval. Avoid full discovery every continuation. |
| `/root/independent_plan_auditor` (Leibniz), ID `01a0c04a-8d18-7cf1-9367-cb2434d738eb` | State metadata: GPT-5.6 Sol Medium. Main sends bounded review requests; not an always-running daemon | Caught lost legacy Split reference checks, aliased fixtures, identity/local-visibility defects and source-reveal completion defect. Latest runtime snapshot: notLoaded, last review completed | RETAIN. Independent evidence has measurable value. Restrict reviews to bounded acceptance/change boundaries; do not retire merely because capacity was unavailable. Approved current plan requires this existing reviewer and forbids replacement to bypass limits. |
| Historical `codex-auto-review` records sharing project cwd | Runtime/internal model, Low; automatic review records | Not child implementation workers in the project spawn graph; exact internal trigger policy not fully inspected | Do not classify as duplicate product agents or disable a platform approval control. No retirement justified by cwd alone. |
| Legacy research/verifier behavior (`agents/research.py`, `cognitive.py`, prompts) | Provider-role calls in old cognitive path; historical model routing is user/provider configured | Original research/re-retrieval/cite-or-cut output; obsolete under V4 | RETIRE from production source only at V4 replacement-acceptance cleanup gate. Currently dormant source, not a live development subagent. |
| Legacy writer (`agents/scriptwriter.py`) | Old cognitive stage | Old script output duplicates external creative authority | Same gated retirement; preserve migration fixtures until replacement acceptance. |
| Legacy spatial/board planner (`agents/spatial.py`, `agents/board_planner.py`) | Old provider stage | Geometry/validation helpers have reusable deterministic portions; board planner explicitly obsolete | Retire model entrypoints after extracting/preserving required deterministic helpers. Do not delete `board_compiler.py`. |
| Jev decision integration | Optional external advisory request, environment key | Bounded advice only, cannot author/apply/approve | Retain optional/advisory boundary if owner still wants it. No live paid test performed. |

No separate current testing agent was identified. Tests run as Python/native subprocesses launched by the main agent or auditor. Read-only process inventory also found an `atme-sidecar.exe`; an application sidecar is not a development agent. Process presence alone does not prove an active render, stalled worker or orphan. This audit left it untouched.

To stop future work safely, the owner should pause/interupt the exact implementation chat through the client, allow a bounded test to finish or record its incomplete result, checkpoint the worktree and test PID/creation identity, and then address any child worker by verified ownership. Never blanket-kill all Python/FFmpeg/ATME processes. At this snapshot there is no active named development-agent turn requiring termination.

## Evidence of avoidable cost

| Finding | Observed evidence | Consequence / recommendation |
|---|---|---|
| Oversized reconstruction context | ~1 GB main rollout; repeated full plan/progress reads visible in recent turns | Read ledger header/current task brief first; retrieve exact modules/tests only. Preserve accepted decisions instead of rediscovering them. |
| Repeated review coordination | One-pass main-history count found 199 `followup_task`, 93 `wait_agent`, 71 `send_message`, 50 `list_agents`, 365 `wait` calls, but only one `spawn_agent` in that counted record type | Counts demonstrate orchestration load, not 199 unnecessary reviews. Use one request per immutable task boundary; wait on results instead of repeatedly asking status. Counts exclude other tool encodings, so are not a total system census. |
| Redundant narrative checkpoints | Same integration story repeated in rebuild, traceability, runtime semantics, remaining matrix and multiple progress reports | Keep detailed evidence once; link from the authoritative ledger. Do not rewrite old historical evidence or create a second progress score. |
| Stale intermediate status | Scratch progress says Task 1 in progress/Task 2 not started before later terminal entries; old traceability row says Count/annotation absent | Explicit latest-checkpoint pointer prevents obsolete directions winning retrieval. Changes to tracking need only record new evidence. |
| Long full regressions | Frozen main run took 4,279.28 s (~71 minutes); many previous full integrations | Target tests per changed dependency; run broad/full regression at integration or shared-kernel changes, not every documentation adjustment. Never waive named approved acceptance suites. |
| Reviewer capacity stalls | Recorded usage/model-capacity interruptions; original audit resumed and found genuine bugs | Continue independent already-approved test/implementation work only where allowed. Queue review; do not invent PASS or spawn a substitute to bypass a limit. |
| Native retries without cause closure | Later green Count runs did not resolve U+000F/native AV | One reproducible diagnostic plan, exact failure inputs/binary hashes, bounded attempts; retain unresolved status when cause is unknown. |
| Import/environment ambiguity | Split plan requires origin guard because main editable install can shadow isolated source | Preserve guard. “Tests pass” against the wrong worktree is invalid evidence. |
| Test-output path fragility | Fresh audit initially failed at 260–261-character pending paths | Use a short disposable test root for verification; track the actual product limitation separately, not as ten unrelated defects. |

There is no evidence that mass agent retirement would be the principal saving. The most defensible savings are smaller reads, fewer duplicate status reports, scoped test selection, and routine work on the cheaper supported role.

## Minimal compatible operating structure

1. One primary implementer/coordinator owns code, tests and the existing ledger.
2. The existing independent reviewer handles approved task gates and critical interfaces. No new persistent testing or documentation agent.
3. Deterministic test subprocesses produce durable command/exit/source evidence; they are not LLM delegates.

Preferred routing is supported by the current local model cache and tool runtime: `gpt-6.1-sol` supports `low`/`medium`, and `gpt-6-astra` supports `low`/`medium`. This establishes available configuration choices, not future capacity or permission to change the current reviewer:

| Work | Proposed model / effort | Escalation |
|---|---|---|
| Routine bounded implementation and coordination | GPT-6.1 Sol Medium | After two distinct failed repair hypotheses, write a precise blocker packet |
| Deterministic result triage / simple verification | GPT-6.1 Sol Low, normally in the same chat | Use actual test evidence; avoid an LLM just to read an exit code |
| Critical bounded independent review | GPT-6 Astra Low | Current reviewer substitution/settings change needs owner approval and must respect no-bypass rule |
| Native renderer, identity, synchronization or architecture issue | GPT-6 Astra Medium | Time-box investigation; no wholesale rewrite without a separately approved decision |

No routing change was applied. The current audit itself does not certify model throughput/cost superiority.

## Restart and retry protocol

Use the **existing Phase 3 ledger** as completion authority and the **existing task progress/brief** as execution detail. Add a compact latest checkpoint there after implementation approval: active task/row, worktree+HEAD+dirty paths, exact last verified tests and source identity, blocker, pending approval/reviewer, next command. Do not add an independent competing task database or a new goal per slice.

On resume: read that packet; check exact Git state and any retained worker's PID+creation identity; retrieve the matching test tail/result; continue the named next step. Only inspect wider code when a new failing dependency requires it. Re-run completed tests only for changed inputs, different source/dependencies, uncertain terminal evidence or an explicit integration gate.

Recommended bound: two distinct repair attempts on the same failure, then targeted escalation; one focused regression after a localized correction, broader regression once at the specified boundary. A repeated unchanged failure is not a new task. Approval/capacity blocks remain blocks; elapsed waiting never grants permission. These are proposed efficiency rules, not changes to the currently approved eleven-task Split plan.
