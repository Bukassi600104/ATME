param([Parameter(Mandatory)][string]$InstallDir)
$ErrorActionPreference = 'Stop'
if (-not [IO.Path]::IsPathRooted($InstallDir)) { throw 'An absolute ATME installation path is required.' }
$directory = [IO.Path]::GetFullPath($InstallDir)
$expected = @((Join-Path $directory 'atme-app.exe'), (Join-Path $directory 'atme-sidecar.exe'))
foreach ($instance in @(Get-Process -Name 'atme-app','atme-sidecar' -ErrorAction SilentlyContinue)) {
    if ($expected -notcontains $instance.Path -or $instance.HasExited) { continue }
    # Retain the process handle so its PID cannot be reused during tree termination.
    $null = $instance.Handle
    & "$env:SystemRoot\System32\taskkill.exe" /PID $instance.Id /T /F | Out-Null
    if (-not $instance.WaitForExit(5000)) { throw "Could not close $($instance.Path)." }
}
