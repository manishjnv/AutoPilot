# Autopilot installer for Windows (PowerShell 5.1 or 7). Options: -DryRun, -SkipLogin.
# Env: AUTOPILOT_REF (git tag/branch to install), AUTOPILOT_DRY_RUN=1, AUTOPILOT_SKIP_LOGIN=1.
# Safe to run twice. N5.4: no administrator prompt on the normal path: Git installs per user, and the package comes
# from PyPI (or the release tag) with uv. The N8 rights step (the scheduled task Autopilot-Setup that installs winget
# packages later with no prompt) runs only with -Rights, which `ap install --rights` names. Edits no profile or PATH
# setting. `ap uninstall --rights` removes the task and its folder.
param([switch]$DryRun, [switch]$SkipLogin, [switch]$Rights)
$ErrorActionPreference = 'Stop'
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }

# ponytail: set this to the release tag when the first tag is made
$DefaultRef = 'v0.4.0'

if ($env:AUTOPILOT_DRY_RUN -eq '1') { $DryRun = $true }
if ($env:AUTOPILOT_SKIP_LOGIN -eq '1') { $SkipLogin = $true }
$Ref = if ($env:AUTOPILOT_REF) { $env:AUTOPILOT_REF } else { $DefaultRef }
if ($Ref -notmatch '^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}\z' -or $Ref -match '\.\.') {
    throw 'AUTOPILOT_REF must start with a letter or a digit, and may use only A-Z a-z 0-9 . _ / - (no "..", 100 characters at most).'
}

function Step($n, $name) { Write-Host "==> Step $n of 6: $name" }
function Fail($n, $cmd) { Write-Host "FAILED: step $n. Run this by hand: $cmd"; throw "Step $n failed." }
function Has($name) { [bool](Get-Command $name -ErrorAction SilentlyContinue) }
# Run a native program; its error text must not stop the script (Windows PowerShell 5.1). No named parameter:
# an argument such as -e would bind to it.
function Run {
    $ErrorActionPreference = 'Continue'
    $rest = @($args | Select-Object -Skip 1)   # an array also for one argument: a string would splat as characters
    & $args[0] @rest 2>&1
}
function Ver($name) { "$(Run $name --version | Select-Object -First 1)" }
# Show programs that an installer just added, to this script only. Built from the same parts each time: no growth.
$Path0 = $env:PATH
function Refresh {
    $parts = @($Path0 -split ';') +
        ([Environment]::GetEnvironmentVariable('Path', 'Machine') -split ';') +
        ([Environment]::GetEnvironmentVariable('Path', 'User') -split ';') + "$env:USERPROFILE\.local\bin"
    $env:PATH = ($parts | Where-Object { $_ } | Select-Object -Unique) -join ';'
}

# The official installer runs in its own PowerShell process: its settings and its exit stay there.
function Ensure($n, $name, $exe, $url) {
    Step $n $name
    $cmd = "powershell -NoProfile -ExecutionPolicy Bypass -Command `"irm $url | iex`""
    if (Has $exe) { Write-Host "found: $(Ver $exe)"; return }
    if ($DryRun) { Write-Host "would install. Command: $cmd"; return }
    Write-Host "run: $cmd"
    Run powershell -NoProfile -ExecutionPolicy Bypass -Command "irm $url | iex" | Out-Host
    if ($LASTEXITCODE -ne 0) { Fail $n $cmd }
    Refresh
    if (-not (Has $exe)) { Fail $n $cmd }
}

Refresh
# N5.4: the normal path takes no rights. -Rights is the one consent (N8): one elevated PowerShell creates the task.
Write-Host 'Autopilot builds your software project while you are away. You write what you want in plain words and start it once. You get working software, tested, with a record of every step.'
Write-Host 'This script installs: Git (winget, per user, when missing), uv, Claude Code, Python 3.12 (when missing), Autopilot.'
if ($Rights) { Write-Host 'Rights it takes: one administrator prompt now, and the scheduled task Autopilot-Setup (highest run level) so later runs install winget packages with no prompt. Remove it later with: ap uninstall --rights' }
else { Write-Host 'Rights it takes: none. A run that needs a system tool later prints its install command; `ap install --rights` sets up the no-prompt path once.' }
$TaskName = 'Autopilot-Setup'
# The script the task runs lives under ProgramData; the elevated step writes it and lets only Administrators and
# SYSTEM change it (icacls, well-known SIDs), so a user process can queue winget ids but never change what runs.
$SetupDir = Join-Path $env:ProgramData 'Autopilot'
$SetupScript = Join-Path $SetupDir 'setup.ps1'
$SetupQueue = Join-Path $SetupDir 'setup-queue.txt'
# The task runs this script as administrator: it installs the winget ids queued by `ap` (ids only, checked by pattern).
# The queue is cleared, never deleted, so its ACL (Users may write it) stays.
$SetupBody = @'
$q = Join-Path $env:ProgramData 'Autopilot\setup-queue.txt'
if (-not (Test-Path $q)) { exit 0 }
$ids = Get-Content $q | Where-Object { $_ -match '^[A-Za-z0-9][A-Za-z0-9.+_-]{1,99}$' } | Select-Object -Unique
Clear-Content $q
foreach ($id in $ids) { winget install --id $id -e --source winget --silent --accept-package-agreements --accept-source-agreements }
'@
# The body travels inside the elevated command as base64: no user-writable draft file that could be swapped before
# the administrator step reads it.
$SetupB64 = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($SetupBody))
# The task is complete only when it runs the script under ProgramData (an older install pointed at LOCALAPPDATA).
function HasTask {
    $out = Run schtasks /Query /TN $TaskName /V /FO LIST   # Run: stderr never stops the script
    ($LASTEXITCODE -eq 0) -and ("$out" -match [regex]::Escape($SetupScript))
}

Step 1 'git'
$needGit = -not (Has git)
# N5.4: per user, no administrator prompt. A missing winget is not fatal: the PyPI package needs no git.
$gitCmd = 'winget install --id Git.Git -e --source winget --scope user --silent --accept-package-agreements --accept-source-agreements'
if (-not $needGit) { Write-Host "found: $(Ver git)" }
elseif (-not (Has winget)) { Write-Host 'git is missing and winget is absent: skipped (not needed for the package install). Get git from https://git-scm.com/download/win when a project needs it.' }
elseif ($DryRun) { Write-Host "would install (per user). Command: $gitCmd" }
else {
    Write-Host "run: $gitCmd"
    Run winget install --id Git.Git -e --source winget --scope user --silent --accept-package-agreements --accept-source-agreements | Out-Host
    Refresh
    if (-not (Has git)) { Write-Host "git did not install: $gitCmd (not needed for the package install; a project that uses git needs it)" }
}
if ($Rights) {
$taskCmd = "schtasks /Create /TN $TaskName /TR `"powershell -NoProfile -ExecutionPolicy Bypass -File $SetupScript`" /SC ONCE /ST 00:00 /RL HIGHEST /F"
# The elevated step: a folder the user may have made first is removed, then the folder, the script and the queue get
# fixed ACLs (well-known SIDs: Administrators, SYSTEM, Users): only Administrators change the folder and the script;
# Users may write the queue file only.
$aclCmd = "if (Test-Path '$SetupDir') { Remove-Item -Recurse -Force '$SetupDir' }; New-Item -ItemType Directory -Force '$SetupDir' | Out-Null; " +
    "icacls '$SetupDir' /setowner *S-1-5-32-544 | Out-Null; icacls '$SetupDir' /inheritance:r /grant:r '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-545:(OI)(CI)RX' | Out-Null; " +
    "[IO.File]::WriteAllText('$SetupScript', [Text.Encoding]::ASCII.GetString([Convert]::FromBase64String('$SetupB64'))); " +
    "New-Item -ItemType File -Force '$SetupQueue' | Out-Null; icacls '$SetupQueue' /grant '*S-1-5-32-545:M' | Out-Null"
if ($DryRun) {
    Write-Host "would write $SetupScript (Administrators only) and create the scheduled task (one administrator prompt). Command: $aclCmd; $taskCmd"
} elseif (-not (HasTask)) {
    $script = "$aclCmd; $taskCmd" + '; exit $LASTEXITCODE'
    Write-Host "run as administrator (one prompt): $script"
    $p = Start-Process powershell -Verb RunAs -Wait -PassThru -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', $script
    if ($p.ExitCode -ne 0) { Write-Host "the elevated step returned $($p.ExitCode); later runs print install commands instead" }
} else { Write-Host "found: scheduled task $TaskName" }
}

Ensure 2 'uv' 'uv' 'https://astral.sh/uv/install.ps1'
Ensure 3 'Claude Code' 'claude' 'https://claude.ai/install.ps1'

Step 4 'Autopilot'
# N5: Autopilot cannot run without Python 3.10 or newer. This is the one system install; uv installs it for this user.
function PyOk {
    foreach ($p in 'python3', 'python', 'py') {
        if (Has $p) { $null = Run $p -c 'import sys; sys.exit(sys.version_info < (3, 10))'; if ($LASTEXITCODE -eq 0) { return $true } }
    }
    $false
}
$pycmd = 'uv python install 3.12'
if (PyOk) { Write-Host 'found: Python 3.10 or newer' }
elseif ($DryRun) { Write-Host "would run (no Python 3.10 or newer found). Command: $pycmd" }
else {
    Write-Host "run: $pycmd"
    Run uv python install 3.12 | Out-Host
    if ($LASTEXITCODE -ne 0) { Fail 4 $pycmd }
}
# N5.3: the package from PyPI first (no git needed); the release tag on GitHub when PyPI has no release yet.
$addr = "git+https://github.com/manishjnv/AutoPilot@$Ref"
if ((Has autopilot) -or ((Has uv) -and ("$(Run uv tool list)" -match 'dev-autopilot'))) {
    $v = if (Has autopilot) { Ver autopilot } else { 'dev-autopilot' }
    Write-Host "found: $v"
    Write-Host "To update, run: ap upgrade"
} elseif ($DryRun) {
    Write-Host "would install. Command: uv tool install dev-autopilot (or uv tool install `"$addr`")"
} else {
    Write-Host "run: uv tool install dev-autopilot"
    Run uv tool install dev-autopilot | Out-Host
    if ($LASTEXITCODE -ne 0) {
        Write-Host "run: uv tool install `"$addr`""
        Run uv tool install $addr | Out-Host
        if ($LASTEXITCODE -ne 0) { Fail 4 "uv tool install `"$addr`"" }
    }
    Refresh
    if (-not (Has autopilot)) { Fail 4 "uv tool install `"$addr`"" }
}
if ($DryRun) { Write-Host 'would check: ap is on PATH' }
elseif (Has ap) { Write-Host 'found: ap' }
else { Fail 4 "uv tool install --reinstall `"$addr`" (then make sure $env:USERPROFILE\.localin is on PATH)" }

Step 5 'login check'
if ($SkipLogin) { Write-Host 'skipped (-SkipLogin)' }
elseif ($DryRun) { Write-Host 'would run: claude auth status' }
else {
    $null = Run claude auth status
    if ($LASTEXITCODE -eq 0) { Write-Host 'Claude Code is logged in.' }
    else {
        Write-Host 'Claude Code is not logged in. Run: claude auth login'
        Write-Host 'You need a paid Claude plan or an API key. This script does not log in for you.'
    }
}

Step 6 'rights for later installs'
if ($DryRun) { Write-Host "would check: scheduled task $TaskName" }
elseif (HasTask) { Write-Host "found: scheduled task $TaskName (undo: ap uninstall --rights)" }
else { Write-Host "none taken (N5.4). Later runs print the install command of a missing system tool; `ap install --rights` sets up the no-prompt path once." }

if (-not $DryRun) { Write-Host "Installed: $(Ver autopilot)" }
Write-Host 'To uninstall, run: uv tool uninstall dev-autopilot (and ap uninstall --rights)'
$global:LASTEXITCODE = 0   # keep a native exit code from an earlier step out of the CI result
Write-Host 'Done. Open a NEW terminal if `ap` is not found.'
Write-Host 'Open a project folder and type `ap`.'
