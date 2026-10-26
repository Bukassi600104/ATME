# Source publication and recovery

This document records the original 2026-10-25 publication and the accepted-source checkpoint of 2026-10-26. Product status remains in the [Phase 3 ledger](ATME_VISUAL_PIPELINE_PHASE_3_LEDGER.md); publication does not satisfy a renderer, phase, installed-build or release gate.

## Source identity

The current source snapshot comes from integration commit `d6fdfea5667446695717eea8fb5d0f91ce050ccb`, including latest bounded accepted product source `94281c334ce050ad38f390cf1b1c460e82c4a75d`. The corresponding main ledger-only commit is `68d6caff57fe721f85575ddad25cfaa909fbc3ff`. All 525 published source blobs match the committed integration snapshot; the professional repository README and contribution/reporting documents are preserved separately.

This checkpoint includes reviewed parent/history and retained-frame work, the authenticated cold Count/frozen-capture repair (422 passing named checks), and original v1/Caleb adjacency (57 passing checks with independent native inspection). The prior 421-pass/one-failure compatibility run remains recorded with no aggregate green credit. Earlier large retained inventories are historical rather than blanket-current regression claims after runtime changes. Phase 3 remains 79 items / 4,925 of 7,900 points = 62.3%. Uncommitted project-flow and maximum-measurement work is excluded from this source publication.

Application source, tests, contracts, benchmarks and required production assets are copied from committed Git blobs. Publication adds repository documentation, contribution/reporting templates and the approved historical execution blueprint/audit documents. Those documentation changes do not alter the renderer or project architecture. Source-file identity is verified separately from publication commit identity.

Historical packaged executables, build intermediates, generated Tauri schemas, smoke logs and root-level research extraction scratch files are excluded from the browsing branch. The tracked research PDF and approved project documentation remain available. Original committed history is preserved separately rather than rewritten: it includes a 223,360,000-byte historical FFmpeg binary that cannot be pushed as a normal GitHub Git blob.

## Maintainer recovery archive

The repository's maintainer-only draft release **ATME development recovery — 2026-10-25**, tag `atme-history-backup-2026-10-25`, stores:

- `atme-history-2026-10-25.bundle.part01` through `.part11` and `bundle-parts.json`: ordered binary parts reconstructing the complete history reachable from saved refs and worktree heads, including original commit IDs and the historical binary. The unchanged bundle was split after full-file uploads failed with DNS and HTTP 408 errors.
- `backup-manifest.json`: captured refs, source identities and publication-file inventory.
- `restore-verification.json`: independent local restore/ref/object verification.
- `github-readback-verification.json`: authenticated download, reconstruction and Git verification of the stored parts.
- `atme-task10-checkpoint-2026-10-25.zip`: 451 selected task checkpoint/evidence files, with a per-file checksum manifest.
- `SHA256SUMS.txt` and `RECOVERY.md`: archive checksums and restore instructions.

The full bundle is 254,928,697 bytes with SHA-256 `a58a9095d5c94288e3976924b57e3416ccf994371275af3d838d2121108efdd8`. A separate mirror clone passed `git fsck --full --no-reflogs`; all 16 captured Git refs matched, 772 reachable commits were present, and the original integration, ledger and worker commits and oversized blob were verified.

The execution ZIP SHA-256 is `f6f9c501256bdcef9ddeb734479eb30dbe7b366bc1370c7bb6d0512384813cf0`. Every archived file was read back and matched its recorded checksum. Private diagnostic dumps, original user media, runtime databases, credentials, dependencies and uncommitted packaging outputs are outside these archives. They require their own backup; a Git push is not a backup of all local files.

The draft is a recovery asset, not an ATME installer or production release. It is visible to repository maintainers, not ordinary public visitors. An ordinary source clone does not include the bundle's archived original ancestry.

## 2026-10-26 recovery supplement

The same maintainer-only draft also stores `atme-history-supplement-2026-10-26.bundle`, `atme-task10-supplement-2026-10-26.zip`, dated checkpoint/snapshot/checksum files and `SUPPLEMENT_2026-10-26.md`. The 44,154-byte incremental bundle preserves newer committed history without duplicating or rewriting the original large object. Its SHA-256 is `f6afdabe277e8e14d7341b8c1a27138626179a7b1320d8161452e07a2e3357da`.

All seven new data/manifest assets were authenticated-downloaded and matched byte-for-byte, including every entry in the 220-entry ZIP. A fresh two-stage restore using the previously authenticated original archive and downloaded supplement passed bundle verification and fsck, recovered all 22 captured refs and 787 commits, and preserved the original FFmpeg blob and accepted integration/main heads. The original 18 asset names, IDs and sizes stayed unchanged. `github-supplement-readback-2026-10-26.json` records this proof; a pending-readback field in the captured checkpoint is historical rather than the final verification state.

The ZIP includes five explicitly unfinished source-file snapshots for disaster recovery, separate from accepted source publication. They do not close project-flow, performance, Task 10, phase or release gates. Original user media, runtime databases, credentials, private diagnostic dumps, dependencies and unrelated packaging outputs remain excluded. For the newer checkpoint, restore the original archive first, then follow `SUPPLEMENT_2026-10-26.md`; extract unfinished snapshots separately and reconcile them before use.

## Restore into a new directory

Use authenticated GitHub CLI and a new empty recovery location. Download the draft's assets as the repository maintainer:

```powershell
gh release download atme-history-backup-2026-10-25 --repo Bukassi600104/ATME --dir .\atme-recovery
@'
from pathlib import Path
import hashlib, json
p = Path("atme-recovery")
m = json.loads((p / "bundle-parts.json").read_text())
out = p / m["bundle_name"]
with out.open("xb") as f:
    for part in m["ordered_parts"]:
        data = (p / part["name"]).read_bytes()
        assert len(data) == part["bytes"]
        assert hashlib.sha256(data).hexdigest() == part["sha256"]
        f.write(data)
assert out.stat().st_size == m["bundle_bytes"]
with out.open("rb") as f:
    assert hashlib.file_digest(f, "sha256").hexdigest() == m["bundle_sha256"]
'@ | py -3.12 -
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
