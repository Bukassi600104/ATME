# Build the Windows x64 release payload from the checked-in dependency locks.
param([string]$Python = "3.12.10")
$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$envRoot = Join-Path $repo "sidecar-build\locked-env"
$pythonExe = Join-Path $envRoot "Scripts\python.exe"
$lock = Join-Path $repo "sidecar\tools\windows-py312.lock"

if (!(Test-Path -LiteralPath $pythonExe)) {
    & uv venv --python $Python $envRoot
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
& $pythonExe -c "import struct,sys; assert sys.version_info[:3] == (3,12,10) and struct.calcsize('P') == 8, 'Windows build requires 64-bit CPython 3.12.10'"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& uv pip sync --python $pythonExe --only-binary :all: --require-hashes $lock
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& uv pip check --python $pythonExe
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$originalPythonPath = $env:PYTHONPATH
Push-Location $repo
try {
    $env:PYTHONPATH = (Resolve-Path "sidecar\src").Path
    $encoder = & $pythonExe -c "from atme.ffmpeg import find_ffmpeg; print(find_ffmpeg() or '')"
    if ($LASTEXITCODE -ne 0 -or !$encoder -or !(Test-Path -LiteralPath $encoder -PathType Leaf)) {
        throw "Provide the standalone Windows x64 FFmpeg encoder using ATME_FFMPEG."
    }
    $digest = (Get-FileHash -LiteralPath $encoder -Algorithm SHA256).Hash
    if ($digest -ne "589E50B766D251AFDF181DD664D40BD94407E200B019989FD7468C7D118A28D0") {
        throw "The Windows release expects the verified FFmpeg 9.0.2 full-build encoder. Found SHA256 $digest."
    }
    & (Join-Path $PSScriptRoot "sync-sidecar.ps1") -Python $pythonExe
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Set-Location $PSScriptRoot
    & pnpm.cmd install --frozen-lockfile
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & pnpm.cmd exec tauri build --bundles nsis -- --locked
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    $env:PYTHONPATH = $originalPythonPath
    Pop-Location
}
