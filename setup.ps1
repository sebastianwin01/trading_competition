# Run with: powershell -ExecutionPolicy Bypass -File .\setup.ps1
$ErrorActionPreference = 'Stop'
$setupScript = Join-Path $PSScriptRoot 'scripts/setup.py'

foreach ($candidate in @('python', 'python3', 'py')) {
    $pythonCommand = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($null -eq $pythonCommand) { continue }
    # A Windows App Execution Alias may exist without an installed Python.
    try {
        & $pythonCommand.Source -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>$null
        if ($LASTEXITCODE -ne 0) { continue }
    } catch { continue }
    & $pythonCommand.Source $setupScript @args
    exit $LASTEXITCODE
}
Write-Error 'Install Python 3.11 or newer, reopen your terminal, and rerun setup.ps1.'
exit 1
