# Requires the repository .venv and a Visual Studio developer PowerShell.
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepositoryRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$Python = Join-Path $RepositoryRoot ".venv\Scripts\python.exe"
$Preparer = Join-Path $RepositoryRoot "prepare_sdlc_team.py"

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Missing repository interpreter: $Python. Create .venv and install requirements.txt using your configured package registry."
}

$env:PYTHONUTF8 = "1"
$env:PATH = "$(Split-Path $Python -Parent);$env:PATH"

# Preparation never starts Copilot or sends prompts: the SDK later uses this
# editable checkout so tester commands exercise the files its agents modify.
Write-Host "[setup] Preparing Beancount demo-base-1048 (9747213802acb733ce53acc6e963f5961f47d6cd) from the local bundle."
& $Python $Preparer
if ($LASTEXITCODE -ne 0) {
    throw "Beancount preparation failed (exit $LASTEXITCODE). Preserve existing workspace edits; verify requirements.txt and the C compiler in Developer PowerShell. No reset was performed."
}
Write-Host "[setup] Ready. Run: & `"$Python`" `"$(Join-Path $PSScriptRoot 'main.py')`""
Write-Host "[setup] The demo reuses Copilot CLI login, never commits or pushes, and rolls back its edits after stopping the runtime."
