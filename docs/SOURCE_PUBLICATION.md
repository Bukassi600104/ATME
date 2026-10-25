# Source publication and recovery

This document records the 2026-10-25 GitHub publication. Product status remains in the [Phase 3 ledger](ATME_VISUAL_PIPELINE_PHASE_3_LEDGER.md); publication does not satisfy a renderer, phase, installed-build or release gate.

## Source identity

The source snapshot comes from integration commit `4a121faa8265eb30717998da11ef1b5467cdce42`, including latest bounded accepted source `510f3be96e74b5af3a56e84d127bd4148c64a209`. The main checkout's corresponding ledger-only commit is `e24aa31d8ec0761e4cce0ccb24430272d5bf6e8b`.

Application source, tests, contracts, benchmarks and required production assets are copied from committed Git blobs. Publication adds repository documentation, contribution/reporting templates and the approved historical execution blueprint/audit documents. Those documentation changes do not alter the renderer or project architecture. Source-file identity is verified separately from publication commit identity.

Historical packaged executables, build intermediates, generated Tauri schemas, smoke logs and root-level research extraction scratch files are excluded from the browsing branch. The tracked research PDF and approved project documentation remain available. Original committed history is preserved separately rather than rewritten: it includes a 223,360,000-byte historical FFmpeg binary that cannot be pushed as a normal GitHub Git blob.

## Maintainer recovery archive

The repository's maintainer-only draft release **ATME development recovery — 2026-10-25**, tag `atme-history-backup-2026-10-25`, stores:

- `atme-history-2026-10-25.bundle`: complete history reachable from the saved local refs and worktree heads at capture, including original commit IDs and the historical binary.
- `backup-manifest.json`: captured refs, source identities and publication-file inventory.
- `restore-verification.json`: independent local restore/ref/object verification.
- `atme-task10-checkpoint-2026-10-25.zip`: 451 selected task checkpoint/evidence files, with a per-file checksum manifest.
- `SHA256SUMS.txt` and `RECOVERY.md`: archive checksums and restore instructions.

The full bundle is 254,928,697 bytes with SHA-256 `a58a9095d5c94288e3976924b57e3416ccf994371275af3d838d2121108efdd8`. A separate mirror clone passed `git fsck --full --no-reflogs`; all 16 captured Git refs matched, 772 reachable commits were present, and the original integration, ledger and worker commits and oversized blob were verified.

The execution ZIP SHA-256 is `f6f9c501256bdcef9ddeb734479eb30dbe7b366bc1370c7bb6d0512384813cf0`. Every archived file was read back and matched its recorded checksum. Private diagnostic dumps, original user media, runtime databases, credentials, dependencies and uncommitted packaging outputs are outside these archives. They require their own backup; a Git push is not a backup of all local files.

The draft is a recovery asset, not an ATME installer or production release. It is visible to repository maintainers, not ordinary public visitors. An ordinary source clone does not include the bundle's archived original ancestry.

## Restore into a new directory

Use authenticated GitHub CLI and a new empty recovery location. Download the draft's assets as the repository maintainer:

```powershell
gh release download atme-history-backup-2026-10-25 --repo Bukassi600104/ATME --dir .\atme-recovery
Get-FileHash .\atme-recovery\atme-history-2026-10-25.bundle -Algorithm SHA256
git clone --mirror .\atme-recovery\atme-history-2026-10-25.bundle .\atme-recovered.git
git -C .\atme-recovered.git fsck --full --no-reflogs
git -C .\atme-recovered.git rev-parse refs/heads/codex/backup-2026-10-25/integration
git --git-dir=.\atme-recovered.git worktree add --detach .\ATME-working 4a121faa8265eb30717998da11ef1b5467cdce42
Expand-Archive .\atme-recovery\atme-task10-checkpoint-2026-10-25.zip .\ATME-working\.superpowers\sdd\2026-10-09-authored-visual-split
```

Compare the checksums before restoring. Restore dependencies through the [developer runbook](RUNBOOK.md). Resume from the ledger and the checkpoint's current restart packet; historical pending/live entries below it are not current instructions.

## GitHub tracking

[Issue #1](https://github.com/Bukassi600104/ATME/issues/1) links the existing acceptance work. [Issue #2](https://github.com/Bukassi600104/ATME/issues/2) tracks current Split Task 10. Verified fixes #7 and #8 are closed only in their recorded bounded scope. GitHub issue counts do not replace the fixed 79-item completion calculation.
