# Build the sidecar with PyInstaller and place artifacts where Tauri expects them.
param([string]$Python = (Join-Path $PSScriptRoot '..\sidecar\.venv\Scripts\python.exe'))

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Split-Path $PSScriptRoot -Parent)).Path
Set-Location $RepoRoot

& $Python -m PyInstaller --noconfirm --distpath sidecar-dist --workpath sidecar-build ".\sidecar\atme-sidecar.spec"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

New-Item -ItemType Directory -Force -Path "app\src-tauri\binaries" | Out-Null
Copy-Item "sidecar-dist\atme-sidecar\atme-sidecar.exe" "app\src-tauri\binaries\atme-sidecar-x86_64-pc-windows-msvc.exe" -Force
# Tauri maps sidecar-dist/atme-sidecar/_internal directly into the installer.
Write-Output "synced sidecar -> app/src-tauri/binaries"
