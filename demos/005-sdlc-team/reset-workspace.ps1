$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Workspace = Join-Path $PSScriptRoot "workspace"
$ExpectedCommit = "9747213802acb733ce53acc6e963f5961f47d6cd"

function Invoke-WorkspaceGit {
    param([string[]] $GitArguments)
    $Output = & git -C $Workspace @GitArguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Workspace Git command failed (exit $LASTEXITCODE): $Output"
    }
    return $Output
}

foreach ($Path in @($Workspace, (Join-Path $Workspace ".git"))) {
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "Missing standalone workspace checkout: $Path. Run prepare-beancount.ps1 first. No reset was performed."
    }
    if ((Get-Item -LiteralPath $Path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "Refusing a linked workspace or Git directory: $Path. No reset was performed."
    }
}

$TopLevel = [IO.Path]::GetFullPath([string](Invoke-WorkspaceGit @("rev-parse", "--show-toplevel")))
$GitDirectory = [IO.Path]::GetFullPath([string](Invoke-WorkspaceGit @("rev-parse", "--absolute-git-dir")))
if ($TopLevel -ne [IO.Path]::GetFullPath($Workspace) -or
    $GitDirectory -ne [IO.Path]::GetFullPath((Join-Path $Workspace ".git"))) {
    throw "Refusing to reset a repository outside the demo workspace. No reset was performed."
}
$HeadCommit = [string](Invoke-WorkspaceGit @("rev-parse", "HEAD"))
if ($HeadCommit -ne $ExpectedCommit) {
    throw "Demo 005 requires HEAD $ExpectedCommit; found $HeadCommit. Preserve your commits and prepare the correct checkout. No reset was performed."
}

# Stop the demo's Copilot runtime before resetting: agent editors must not
# race with cleanup. This script never starts the CLI or sends SDK prompts.
Write-Host "[reset] Stop Demo 005 and its Copilot runtime before continuing."
Write-Host "[reset] Workspace: $Workspace"
$Status = @(Invoke-WorkspaceGit @("status", "--porcelain", "--untracked-files=all"))
if ($Status.Count -eq 0) {
    Write-Host "[reset] Workspace already clean. No files changed."
    exit 0
}
Write-Host "[reset] Tracked edits and non-ignored untracked files will be permanently discarded:"
$Status | ForEach-Object { Write-Host $_ }
Invoke-WorkspaceGit @("clean", "-nd", "--", ".") | ForEach-Object { Write-Host $_ }
Write-Host "[reset] Ignored build artifacts, the parent repository, and demo logs are preserved."

Invoke-WorkspaceGit @("clean", "-fd", "--", ".") | ForEach-Object { Write-Host $_ }
Invoke-WorkspaceGit @("restore", "--source", $ExpectedCommit, "--staged", "--worktree", "--", ".")
$Remaining = @(Invoke-WorkspaceGit @("status", "--porcelain", "--untracked-files=all"))
if ($Remaining.Count -ne 0) {
    $Remaining | ForEach-Object { Write-Host $_ }
    throw "Workspace is not clean after reset. Inspect remaining paths (nested repositories and files exposed by restored ignore rules are preserved). Do not start the demo yet."
}
Write-Host "[reset] Base restored; workspace clean. No commit or push."
Write-Host "[reset] Ready to run main.py; the SDK will reuse your Copilot CLI login."
