# Build the sidecar with PyInstaller and place artifacts where Tauri expects them.
$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Split-Path $PSScriptRoot -Parent)).Path
Set-Location $RepoRoot

& ".\sidecar\.venv\Scripts\python.exe" -m PyInstaller --noconfirm --distpath sidecar-dist --workpath sidecar-build ".\sidecar\atme-sidecar.spec"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

New-Item -ItemType Directory -Force -Path "app\src-tauri\binaries" | Out-Null
Copy-Item "sidecar-dist\atme-sidecar\atme-sidecar.exe" "app\src-tauri\binaries\atme-sidecar-x86_64-pc-windows-msvc.exe" -Force
$InternalTarget = [IO.Path]::GetFullPath((Join-Path $RepoRoot "app\src-tauri\binaries\_internal"))
if (-not $InternalTarget.StartsWith($RepoRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to replace a sidecar runtime outside the repository"
}
if (Test-Path -LiteralPath $InternalTarget) {
    Remove-Item -LiteralPath $InternalTarget -Recurse -Force
}
Copy-Item "sidecar-dist\atme-sidecar\_internal" $InternalTarget -Recurse -Force
Write-Output "synced sidecar -> app/src-tauri/binaries"
