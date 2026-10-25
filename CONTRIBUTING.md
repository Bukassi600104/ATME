# Contributing to ATME

ATME is an in-progress Windows Tauri 2 application with a vanilla TypeScript/Vite frontend and a Python 3.12+ sidecar. Start with the [README setup](README.md#developer-setup) and [runbook](docs/RUNBOOK.md). The [Phase 3 ledger](docs/ATME_VISUAL_PIPELINE_PHASE_3_LEDGER.md) defines current status; the [approved rebuild](docs/ATME_VISUAL_PIPELINE_REBUILD.md) and [remaining matrix](docs/ATME_VISUAL_PIPELINE_PHASE_3_REMAINING_MATRIX.md) define active scope.

## Keep changes bounded

- Describe the failing behavior or approved requirement and the smallest change that addresses it. Discuss scope expansion before implementation.
- Read affected callers, contracts and tests. Keep the current stack and preserve the Caleb-derived Paper & Ink behavior.
- Preserve original recordings, immutable artifact versions, revision checks, script approval and recording authority. Use disposable project stores and copied media for tests.
- Never commit credentials, client configuration containing secrets, private recordings, project databases, local logs or generated runtime/build bundles. Redact tokens, personal paths and project content from reports.
- Do not weaken an assertion, change a fixture or waive a gate merely to obtain a passing result. Explain a justified oracle correction separately from a product fix.

## Verify affected behavior

Use the environment created by the README. Run commands from the indicated directory:

| Change | Check |
|---|---|
| Python contracts or behavior, from `sidecar` | `.\.venv\Scripts\python.exe -m pytest tests/<affected_test>.py -q` |
| Changed Python files, from `sidecar` | `.\.venv\Scripts\python.exe -m ruff check <changed_paths>` |
| Frontend, from `app` | `pnpm check` and `pnpm build` |
| Rust host, from `app/src-tauri` | `cargo check` with required sidecar build inputs prepared per runbook |
| Every change, from repository root | `git diff --check` |

Replace angle-bracket placeholders with actual affected paths. Add a small meaningful regression check for new non-trivial logic. Broaden verification when shared behavior changes; avoid repeated long native suites without a specific reason. Renderer changes need the applicable exact-revision, both-profile, native/pixel and retained-regression evidence required by the approved plan.

Record the source revision, exact command, terminal exit and pass/fail/skip counts. For native or long-running gates retain the named evidence and hashes required by that gate. An interrupted or partial run is incomplete evidence. Report missing dependencies, skips and checks you did not run. Unit checks do not close public admission, native reliability, installed application or human review gates, or authorize changing the ledger's fixed scope or scores.

## Reports and pull requests

For bugs, provide the exact source revision or application version, Windows environment, minimal reproduction, expected and actual behavior, and relevant redacted source/log evidence. Identify the profile and authority mode when relevant. Keep private media out of public issues; prefer a synthetic reproduction.

For pull requests, explain the problem, resulting behavior, affected contracts or callers, and validation with remaining limitations. Link the issue or approved requirement. Persistent data changes need an explicit preservation and compatibility explanation.

## License status

No project-wide license is currently declared. Bundled third-party notices apply to their respective assets and dependencies. Do not assume that public source availability grants a project-wide license or add a license declaration without the owner's decision.
